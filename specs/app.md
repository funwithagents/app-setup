---
code:
  - src/module_setup/app.py
tests:
  - tests/test_app.py
  - tests/fakes.py
---

# App

**Status:** Implemented

## Purpose

An app built from configurable libraries declares what it is made of, and gets a Setup page and a Session tab for it. This spec is that declaration and the model behind the page: what an app gives, and what the page can do with it, with no UI. The form, the tabs and the launch are in [ui.md](ui.md); the folder, the secrets and the session each have their own spec.

## What an app declares

```python
@dataclass(frozen=True)
class Section:
    name: str
    contract: SetupContract | Callable[[], SetupContract]
    title: str | None = None
    when: Callable[[Mapping[str, Any]], bool] | None = None
    host_extra: str | None = None


@dataclass(frozen=True)
class App:
    name: str
    host: str
    sections: tuple[Section, ...]
    default_config: Mapping[str, Any]
    start: StartFunction
    title: str | None = None
    session_ui: Callable[[SessionRunner], None] | None = None
```

- **`name`** names the app's folder ([config-folder.md](config-folder.md)) and, unless `title` is given, its page.
- **`host`** is the distribution the environment is installed from: what [extras.md](extras.md) installs extras of.
- **A section** is one key of the app's config, whose document is owned by one library and described by its contract ([module-contract.md](module-contract.md)). A library's own demo has one section; an app composing libraries has one per library, and may write a contract for settings it owns itself.
- **`contract`** is the contract object, or a function returning it. The function is for a library the host installs only with one of its own extras: while it raises `ImportError`, the section is shown as needing **`host_extra`**, which the page can install; it is tried again after an install.
- **`when`**, given the whole config, says whether the section is used (a section for one embodiment of an app). A section not used is neither drawn, checked nor started; its document stays in the config, so switching back loses nothing.
- **`default_config`** is the first config of a new folder, and what "Reset" goes back to.
- **`start`** builds the runtime from the saved config ([session.md](session.md)).
- **`session_ui`** draws the Session tab's own content ([ui.md](ui.md)).

## The model

`AppModel(app, folder, secrets=None, runner=None)` is what the page does, shared by every browser tab. Every method takes the config being edited (the page's draft), except `start`, which uses the saved one.

| Method | What it does |
|---|---|
| `used(config)` | The sections the config uses, in declaration order |
| `saved_config()`, `save(config)`, `reset()` | Read, save, or reset to the default the config in the folder. `save` and `reset` raise `RuntimeError` while a session runs |
| `settings()`, `set_autostart(on)` | The folder's settings |
| `check_config(config)` | Every section's `check_config`, each problem as `Problem(section, path, message)`, the path a JSON Pointer into the app's config (`/speech/module/voice_id`). A used section absent from the config is a problem at `/<section>` |
| `check_setup(config)` | Every section's `check_setup`, each item as a `SetupItem`. An extra's item is told which host extras install it (`host_extras`, from [extras.md](extras.md)); an extra unavailable on this platform says so and has none. A section whose library does not import is one missing item, installable by its `host_extra` |
| `missing_extras(config)` | The host extras that install what is missing: the first carrier of each installable item |
| `install(extras, on_output)` | Installs the host's extras with its installer; `InstallError` when the app cannot install (no lock, no uv). Sections whose library did not import are retried afterwards |
| `prepare(config, on_progress)` | Each section with a preparable item missing: its contract's `prepare` |
| `probe(config, section)` | The section's `probe` |
| `options(config, section, name)` | The section's `options` |
| `secret_variables(config)` | Each environment variable the config names for a key, with its source ([secrets.md](secrets.md)) and the pointers naming it |
| `start_blockers(config)` | Why a session cannot start, in words: the config problems, then every missing item |
| `start()`, `stop()`, `autostart()` | The session ([session.md](session.md)). `start` uses the saved config and returns its blockers instead of starting; `autostart` starts only when the settings ask |

A `SetupItem` is the contract's item with its `section` and `host_extras`; `installable` is true for a missing extra some host extra carries. Start is refused while an item is `missing`; an `unknown` one does not block it.

## Testing

`tests/test_app.py`, over a fake library implementing the contract (`tests/fakes.py`), with the host's extras faked:

- problems pointed into the app's config; a missing section;
- a missing extra told its host extra; unavailable on this platform; carried by no host extra;
- files missing, prepared, then ready;
- a section the config does not use; a library that does not import, then does;
- the install delegated to the installer, and refused without one;
- the secrets named and their sources;
- a session started with the saved config of the used sections; refused while something is missing; the config locked while it runs; autostart.

## Open questions

1. **A section the user can switch off** (an optional library) is expressed today by the section's own schema (an `enabled` field) or by `when`. A generic switch is deferred.
2. **Checks cost an import.** `check_setup` imports each section's providers; the page runs it on request, on a thread. Caching results between two checks is deferred.
