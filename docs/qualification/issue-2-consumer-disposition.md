# Issue 2: scoped consumer release disposition

[Issue 2](https://github.com/baseproof/browser-use-bubus/issues/2) remains an open,
reproduced, pre-existing stale-context defect. Both stock 1.5.6 and
1.5.6+baseproof.3 permit the documented same-loop serialization bypass. The
two ownership fixes in PR1 do not introduce or resolve it.

The release decision for 1.5.6+baseproof.3 is to retain those two corrections
and track issue 2 separately. The following inspected consumer paths do not
start a new bus from inside an already-held Bubus handler. This is bounded
evidence, not a guarantee for arbitrary callers or every possible schedule.

## Traced source

The reviewed SDK revision is `390a0fc1068ee8b63439e8adf15606e439615b86`.
Installed `agent.py`, `agent_browser.py` and `agent_wait.py` matched that source.

- [`run_browser_use` constructs its session and Agent](https://github.com/baseproof/rpa-sdk/blob/390a0fc1068ee8b63439e8adf15606e439615b86/rpa_sdk/cua/agent.py#L905)
  before invoking `Agent.run` from its root run coroutine at line 990.
- [`navigate` constructs and starts its session](https://github.com/baseproof/rpa-sdk/blob/390a0fc1068ee8b63439e8adf15606e439615b86/rpa_sdk/cua/agent.py#L1184)
  from its dedicated root coroutine.
- Installed browser-use 0.13.14 `browser_use/agent/service.py:2572–2583`
  starts the Agent and BrowserSession buses from `Agent.run`. Its
  `browser/session.py:556,1738–1851` supplies the same session bus to watchdogs;
  the inspected default watchdog constructors do not create another bus.
- [`CallerCalls`](https://github.com/baseproof/rpa-sdk/blob/390a0fc1068ee8b63439e8adf15606e439615b86/rpa_sdk/cua/agent_wait.py#L112)
  queues callbacks to the existing owner thread without transferring the
  handler's context. Normal detach runs from the run coroutine; pending tasks
  drain before model resources close.
- RPA revision `ee4ed328656c6b034217513e7a3724bad9e69d49` invokes
  [`_cua_agent.run_browser_use` from its actuator](https://github.com/baseproof/rpa/blob/ee4ed328656c6b034217513e7a3724bad9e69d49/service/playbooks/actuator.py#L1046).
  Its session pool submits playbook work to the existing one-thread session
  executor (`service/playbooks/pool.py:515–525,1556–1567`).

## Bounded installed probe

A public `navigate("http://127.0.0.1:9", "about:blank", attach_seconds=0.25)`
call ran in installed Linux/amd64 image
`sha256:1c65a117297f260a4de8c5197d138789ec1071567a9efb4f23ccc590b679918a`,
with networking disabled, two CPUs, 2 GiB memory and a 25-second outer bound.
Read-only `sys.setprofile`/`threading.setprofile` observation recorded initial
`EventBus._start` calls without replacing any method or changing runtime source.

The process exited 0 after observing the expected `ConnectError`. Versions were
browser-use 0.13.14, rpa-sdk 0.33.0 and bubus 1.5.6+baseproof.3. Its only bus
startup had `holds_global_lock=false` and `inside_handler_context=false`.
This probes the failed-attachment startup path only; it is not a successful
browser run, real-model call, cloud test or complete lifecycle qualification.

## Explicit limitation

[`run_async_in_fresh_thread` copies its caller's context](https://github.com/baseproof/rpa-sdk/blob/390a0fc1068ee8b63439e8adf15606e439615b86/rpa_sdk/cua/agent.py#L1299).
An explicitly nested caller can therefore carry an already-held Bubus context
into the SDK. This wrapper does not reject or clear that context. Such arbitrary
nested use is outside the qualified consumer conclusion; issue 2 is not closed.

No additional lock change is justified by the automated review's unsupported
simultaneous-decrement explanation. Any fix for issue 2 needs its own regression,
source review and newly qualified package bytes. Final rpa-sdk wheel/image,
native-Linux lifecycle and real provider/cloud qualification remain required.
