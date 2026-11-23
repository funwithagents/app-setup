---
code:
  - src/module_setup/session.py
tests:
  - tests/test_session.py
---

# Session

**Status:** Implemented

## Purpose

A session is one run of an app's runtime, from Start to Stop: an engine speaking, an agent listening, a robot connected. The page stays up across sessions, so a user can stop, change the config, and start again without relaunching the app.

## What the app gives

```python
class Session(Protocol):
    def stop(self) -> None: ...

@dataclass(frozen=True)
class SessionContext:
    config: Mapping[str, Any]   # the document of each section the session uses
    folder: Path                # the app's folder, against which relative paths resolve

StartFunction = Callable[[SessionContext], Session]
```

`start` builds the runtime and returns once it runs; it raises to fail, its message shown on the page. The object it returns is the session's: the Session tab's content reaches it through the runner. `stop` releases everything the session holds. Both are synchronous and run on a thread of their own, so they may block (loading a model, connecting to a robot).

## The runner

`SessionRunner(start)` runs one session at a time:

| State | Meaning | Next |
|---|---|---|
| `stopped` | Nothing runs | `starting` on Start |
| `starting` | `start` is running | `running`, or `failed` when it raised |
| `running` | The session runs | `stopping` on Stop |
| `stopping` | `stop` is running | `stopped` |
| `failed` | The last `start` raised; `error` is its message | `starting` on Start |

- `start(context)` and `stop()` return at once (False when the state does not allow them); the work happens on a thread.
- A Stop asked while starting is done as soon as the session has started.
- A `stop` that raises still ends in `stopped`, with `error` saying so: the session is not reused.
- `session` is the running session's object, `None` otherwise; `context` the config it started with; `started_at` when it started.
- `version` changes on every transition, for a page that polls; `wait(timeout)` waits until no start or stop is in progress.
- `idle` is true when stopped or failed: the config may change and a session may start.

## The config is locked while a session runs

`AppModel.save` and `reset` refuse while the runner is not idle ([app.md](app.md)). A session starts from the **saved** config, never from the page's unsaved draft: what runs is always what is on disk. The page says so when the draft differs.

## Autostart

When the folder's settings say `autostart`, `launch` starts a session before serving the page, and opens the page on the Session tab. If the config cannot start (a problem, something missing), the page opens on the Setup tab and the reasons are logged. `--no-autostart` skips it for one launch.

## Testing

`tests/test_session.py`: start, run, stop; a second start refused; a failing start reported and retried; a failing stop still stops; a stop asked while starting; the version changing on every transition.

## Open questions

1. **Restarting on a crash** of the runtime itself (the session's own threads dying) is the app's business: the runner knows only `start` and `stop`.
2. **Several sessions at once** (two robots) are not supported: one app, one session.
