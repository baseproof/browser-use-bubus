# Baseproof event-loop ownership patch

This repository is the authoritative source for the private downstream package
`bubus==1.5.6+baseproof.3`. It preserves the upstream package name, original MIT
license and authorship. Browser-use source is unchanged. The local version is
distinct from upstream `1.5.6` and satisfies its exact public-version requirement
under PEP 440. It must never replace upstream's published distribution.

## Two corrections

1. `BaseEvent.__await__` drains only running buses owned by its current event
   loop. `EventBus` retains that owner when starting its run loop and exposes the
   typed `is_running_on(loop)` predicate. This incorporates the runtime fix from
   [upstream PR30](https://github.com/browser-use/bubus/pull/30), head
   `40d6bbb11164cf1a7bc981ee0a19e239f0deafb1`.
2. `_get_global_lock()` returns the lock for the current running loop. A short
   thread lock protects registry lookup/creation; it does not serialize event
   execution across loops. Weak loop keys and weak lock values avoid retaining
   closed loops through contended semaphores. Active holders/waiters keep their
   lock alive. The existing `ReentrantLock` algorithm is unchanged.

These are demonstrated dependency mechanisms. Owner-local dispatch/await on the
published dependency ran another loop's handler in ten of ten observed trials.
The separate factory reproduction stranded a queued waiter on both upstream
1.5.6 and PR30: another loop replaced the shared semaphore before the original
holder released it. The controlled SDK browser workload and cleanup warnings
led to these probes. Neither the reproduction nor the correction identifies the
exact command behind a historical ID-less CDP parse-error reply.

`tests/test_loop_ownership.py` covers owner-local nested draining, independent
loop progress, same-loop reentrancy/serialization, holder/waiter cancellation,
and collection of an inactive lock and closed contended loop. It changes no
library method or registry entry. Every existing upstream-main test is retained.
Directly sharing a private lock between loops, or carrying an already-held lock
context into a different loop, is outside the qualified caller contract.

## Provenance and qualification

The fork baseline is `de1519b9f09a80546b42f56311e700896d3bb8fa` from
`browser-use/bubus`. All five runtime modules match the previously qualified
experimental candidate byte-for-byte:

| Module | SHA256 |
| --- | --- |
| `bubus/__init__.py` | `7ab9af76de51939bc4ad6bbbbd8043ae5d127053d0126769c5e4827a3fc126d8` |
| `bubus/helpers.py` | `7e1a968b750ca98edbd2036484248f7bd00f51537f1d3f711a73a5e4d52bda4d` |
| `bubus/logging.py` | `0aea028939ce47f1b0af5c0cbff5c90742cb7b5c2df06572c4ea061ee800c3a3` |
| `bubus/models.py` | `a927b461a5ce4d237324d8d84b079811023e95d4059a1f4ddc20ba788e2a1466` |
| `bubus/service.py` | `14bdef2492b7670766dee4edbfc6427e43c35eab3a749ecfd4b9c762ea5b3e7e` |

The unchanged MIT license SHA256 is
`4a7a9448a66aef9a1e41e62bfd1938287ebe460cc6abd2688d27ec77e24fd133`.
Earlier exact-image tests, real Gemini/OpenAI/Anthropic and GCS/Firestore results
are retained in [rpa-sdk PR100](https://github.com/baseproof/rpa-sdk/pull/100) and
[RPA PR219](https://github.com/baseproof/rpa/pull/219). They establish recorded
mechanisms/integrations, not production throughput or a later artifact's release
acceptance. The ten-minute controlled workload completed 100/100 executions,
with eight acknowledged and drained recording closures and no observed pending
CDP commands, loop/handler/parse errors or capture loss.

This fork intentionally updates package metadata to name the authoritative
Baseproof repository, preserve the upstream URL, and reject public PyPI uploads.
Therefore its archives have new hashes. The earlier experimental wheel SHA256
`533217b59cb8b60c60391ec35da055162e7b50c6834e6173288834f7975f5901`
and sdist SHA256
`977d212a0e7c8def7e23d05b4066d0ea1a7c5f898d12c0183c8aa92e5ecd63d5`
remain historical evidence and are not the fork's final publication artifacts.

## Private release contract

The inherited automatic/public PyPI publication path has been removed. The
manual private-publication workflow runs only from main. Preparation must
reproduce the exact archive hashes in the installed qualification and source
audit; changed package source, tests or archive bytes are rejected. Publication
consumes the retained preparation artifact without rebuilding it, including on
a failed-job retry. The test jobs explicitly select stable Python
3.14, matching the qualified consumer. The upstream `>=3.11` package floor is
unchanged; this release does not newly qualify every supported Python version.

Build the sdist once from the reviewed source, then build the wheel from that
sdist. Retain both exact archives, their hashes, source commit and installed
qualification results. Source checks use the original strict Pyright settings
and Ruff configuration; installation tests must resolve this exact local version
and preserve the expected runtime module hashes. Run the upstream test files,
the ownership regressions and the existing coverage gate against the installed
wheel, with no runtime source overlay.

Publication targets only
`https://us-python.pkg.dev/legalai-460612/baseproof-ai/`. Use the existing
`rpa-sdk-publisher` identity for upload and separate `rpa-sdk-reader` identity for
download. Verify both independently downloaded archive hashes and bytes before
announcing the release. An existing version must match; never overwrite it or
silently rebuild archives during a publication retry. No new credential lookup,
service account, secret or IAM role is introduced by this patch.

The workflow uses the existing organization `SDK_PUBLISHER_SA_KEY` and
`SDK_READER_SA_KEY`, explicitly verifies their distinct service-account identities,
checks existing registry bytes before upload, and uploads only missing qualified
archives. Publication/readback evidence is retained by run and attempt. Invoke
`publish.yml` on main after its source checks pass; failed publication is retried
using the successful preparation job's retained artifact. Do not rerun preparation
to substitute different bytes. Real provider/cloud and browser qualification of
the consuming rpa-sdk image remains a separate gate.

rpa-sdk selects the published local version and verifies its wheel hash before
normal installation and base-image construction. Its final wheel, sdist, image,
freeze and native-Linux browser gates still need their own qualification. RPA
then consumes that published SDK pair; it does not carry the patch implementation.

## Final-metadata candidate evidence

The [installed-wheel receipt](qualification/1.5.6+baseproof.3.json) records
149 passing tests across 14 files, including the unchanged 20,000-event stress
case and 11 new owner-local regressions. Coverage is 82.51% against the upstream
80% requirement. Strict Pyright reports zero errors/warnings; Ruff lint and
format checks pass. The wrong-loop regression fails stock 1.5.6 at the ownership
assertion. The waiter-progress regression times out on both stock and PR30,
while the corrected candidate passes. Those negative controls remain failures.

Archives were built once from `e0a403f05cc31c629c1b30a2a70849a430ab39fa`, sdist
then wheel, using uv 0.8.2 and Hatchling 1.33.0:

| Archive | SHA256 |
| --- | --- |
| `bubus-1.5.6+baseproof.3-py3-none-any.whl` | `9e4a5bdb3f9f0ff552c7635ab8887ffb43f51f2b1f6353eef4ed04b87445af9c` |
| `bubus-1.5.6+baseproof.3.tar.gz` | `a23009dc8182986c10e00ce6ce669d0feb1618a213bf78b09ba03337435074da` |

An [independent archive audit](qualification/source-archive-audit.json) verifies
the committed package source, all wheel RECORD entries, metadata and unchanged
MIT license. The five runtime modules match the earlier experimental wheel;
the changed metadata has its own installed qualification above. Local tests
used Linux/amd64, the exact installed wheel and no runtime source overlay.
Native-Linux CI, private publication/readback and the final rpa-sdk image are
separate gates; this receipt does not claim they have completed.
