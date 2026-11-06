"""Owner-local reproductions for the two independently observed dependency defects.

Every dispatch/await remains on its bus's loop. The tests do not replace library
methods or mutate the bus registry/semaphore. See docs/ownership-patch.md for the
installed SDK/browser evidence; these tests prove mechanisms, not site behavior.
"""

import asyncio
import gc
import threading
import weakref
from collections.abc import Coroutine, Iterator
from typing import Any, TypeVar

import pytest

from bubus import BaseEvent, EventBus
from bubus.service import _get_global_lock, holds_global_lock

T = TypeVar('T')


class Owner:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        assert self.ready.wait(3)

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()

    def call(self, operation: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(operation, self.loop).result(3)

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(3)
        assert not self.thread.is_alive()
        assert self.loop.is_closed()


@pytest.fixture
def owners() -> Iterator[tuple[Owner, Owner]]:
    first, second = Owner(), Owner()
    try:
        yield first, second
    finally:
        first.close()
        second.close()


class Blocker(BaseEvent[None]):
    pass


class Probe(BaseEvent[None]):
    pass


class Parent(BaseEvent[None]):
    pass


class Child(BaseEvent[None]):
    pass


@pytest.mark.parametrize('trial', range(5))
def test_nested_drain_stays_on_owner_loop(owners: tuple[Owner, Owner], trial: int) -> None:
    async def create_bus(number: int) -> EventBus:
        return EventBus(name=f'Owner{trial}_{number}')

    buses = [owner.call(create_bus(number)) for number, owner in enumerate(owners)]
    # Observe iteration order to encounter B before A's own child. No registry
    # modification and no application wait on a foreign-loop event is involved.
    order = [bus for bus in EventBus.all_instances if any(bus is own for own in buses)]
    assert len(order) == 2
    b = next(number for number, bus in enumerate(buses) if bus is order[0])
    a = 1 - b
    entered, ran = threading.Event(), threading.Event()
    actual: list[tuple[asyncio.AbstractEventLoop, int]] = []

    async def install_blocker() -> asyncio.Event:
        release = asyncio.Event()

        async def block(event: Blocker) -> None:
            entered.set()
            await release.wait()

        async def probe(event: Probe) -> None:
            actual.append((asyncio.get_running_loop(), threading.get_ident()))
            ran.set()

        buses[b].on(Blocker, block)
        buses[b].on(Probe, probe)
        buses[b].dispatch(Blocker())
        return release

    release = owners[b].call(install_blocker())
    try:
        assert entered.wait(3)

        async def queue_probe() -> Probe:
            return buses[b].dispatch(Probe())

        probe = owners[b].call(queue_probe())

        async def run_parent() -> None:
            async def child(event: Child) -> None:
                assert asyncio.get_running_loop() is owners[a].loop

            async def parent(event: Parent) -> None:
                own_child = buses[a].dispatch(Child())
                await own_child
                await own_child.event_results_filtered(raise_if_any=True, raise_if_none=False)

            buses[a].on(Child, child)
            buses[a].on(Parent, parent)
            event = buses[a].dispatch(Parent())
            await event
            await event.event_results_filtered(raise_if_any=True, raise_if_none=False)

        owners[a].call(run_parent())
        owners[b].loop.call_soon_threadsafe(release.set)
        assert ran.wait(3)

        async def verify_probe() -> None:
            await probe
            await probe.event_results_filtered(raise_if_any=True, raise_if_none=False)

        owners[b].call(verify_probe())
        assert actual == [(owners[b].loop, owners[b].thread.ident)]
    finally:
        owners[b].loop.call_soon_threadsafe(release.set)
        for owner, bus in zip(owners, buses):
            owner.call(bus.stop())


def test_independent_loop_cannot_strand_lock_waiter(owners: tuple[Owner, Owner]) -> None:
    a, b = owners
    entered, waiting = threading.Event(), threading.Event()
    control: list[asyncio.Event] = []

    async def holder() -> None:
        assert not holds_global_lock.get()
        release = asyncio.Event()
        control.append(release)
        async with _get_global_lock():
            entered.set()
            await release.wait()

    async def waiter() -> None:
        assert not holds_global_lock.get()
        waiting.set()
        async with _get_global_lock():
            pass

    async def assert_queued() -> None:
        semaphore = _get_global_lock()._semaphore
        assert semaphore is not None
        assert semaphore._waiters is not None and len(semaphore._waiters) == 1
        assert not semaphore._waiters[0].done()

    first = asyncio.run_coroutine_threadsafe(holder(), a.loop)
    assert entered.wait(3)
    second = asyncio.run_coroutine_threadsafe(waiter(), a.loop)
    try:
        assert waiting.wait(3)
        a.call(assert_queued())
        b.call(waiter())
        a.loop.call_soon_threadsafe(control[0].set)
        first.result(3)
        # On 1.5.6 / PR30, B replaced the shared semaphore: A exits with depth
        # -1 and this already-queued acquire never receives its release.
        second.result(1)
    finally:
        a.loop.call_soon_threadsafe(control[0].set)
        first.cancel()
        second.cancel()


async def test_same_loop_nested_child_keeps_reentrancy() -> None:
    lock = _get_global_lock()
    assert not holds_global_lock.get()
    async with lock:

        async def child() -> None:
            assert holds_global_lock.get()
            async with _get_global_lock():
                assert _get_global_lock() is lock

        await asyncio.wait_for(asyncio.create_task(child()), 2)
    assert not holds_global_lock.get()
    assert not lock.locked()


async def contended_lock(cancel: str) -> tuple[weakref.ReferenceType[Any], weakref.ReferenceType[Any]]:
    entered, release = asyncio.Event(), asyncio.Event()
    acquired, release_waiter = asyncio.Event(), asyncio.Event()
    references: list[weakref.ReferenceType[Any]] = []
    order: list[str] = []

    async def holder() -> None:
        lock = _get_global_lock()
        references.append(weakref.ref(lock))
        async with lock:
            entered.set()
            try:
                await release.wait()
            finally:
                order.append('holder_exit')

    async def waiter() -> None:
        async with _get_global_lock():
            assert _get_global_lock() is references[0]()
            order.append('waiter_enter')
            acquired.set()
            await release_waiter.wait()

    first = asyncio.create_task(holder())
    tasks = [first]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.create_task(waiter())
        tasks.append(second)
        await asyncio.sleep(0)
        gc.collect()
        assert references[0]() is not None
        assert not acquired.is_set()
        if cancel == 'waiter':
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            assert not acquired.is_set()
            second = asyncio.create_task(waiter())
            tasks.append(second)
            await asyncio.sleep(0)
        if cancel == 'holder':
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            release.set()
            await first
        await asyncio.wait_for(acquired.wait(), 2)
        assert order == ['holder_exit', 'waiter_enter']
        gc.collect()
        assert references[0]() is not None
        release_waiter.set()
        await second
        return references[0], weakref.ref(asyncio.get_running_loop())
    finally:
        release.set()
        release_waiter.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all(task.done() for task in tasks)


@pytest.mark.parametrize('cancel', ['none', 'holder', 'waiter'])
async def test_same_loop_serialization_and_cancellation(cancel: str) -> None:
    await contended_lock(cancel)


def test_closed_contended_loop_and_lock_are_collectible() -> None:
    lock, loop = asyncio.run(contended_lock('none'))
    gc.collect()
    assert lock() is None
    assert loop() is None
