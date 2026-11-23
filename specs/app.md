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

An app built from configurable libraries declares what it is made of, and gets a Setup panel and a Secrets panel for it. This spec is that declaration and the model behind the panels: what an app gives, and what the panels can do with it, with no UI. The panels are in [ui.md](ui.md); the folder and the secrets each have their own spec.

Running the app with its config (a session: Start, Stop, the app's own controls) is the app's own. module-setup only needs to know when the config is in use, to refuse changing it then.

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
    title: str | None = None
```

- **`name`** is the default name of the app's folder ([config-folder.md](config-folder.md)) and, unless `title` is given, its title.
- **`host`** is the distribution the environment is installed from: what [extras.md](extras.md) installs extras of.
- **A section** is one key of the app's config, whose document is owned by one library and described by its contract ([module-contract.md](module-contract.md)). A library's own demo has one section; an app composing libraries has one per library, and may write a contract for settings it owns itself.
- **`contract`** is the contract object, or a function returning it. The function is for a library the host installs only with one of its own extras: while it raises `ImportError`, the section is shown as needing **`host_extra`**, which the page can install; it is tried again after an install.
- **`when`**, given the whole config, says whether the section is used (a section for one embodiment of an app). A section not used is neither drawn nor checked, and the app does not run it; its document stays in the config, so switching back loses nothing.
- **`default_config`** is the first config of a new folder, and what "Reset" goes back to.

## The model

`AppModel(app, folder, secrets=None, locked=None)` is what the panels do, shared by every browser tab. Most methods take the config being edited (a Setup panel's draft).

Building it makes the app ready to set up, so an app cannot forget a step or take them out of order:

1. **The folder**: `folder.ensure()`, which creates it and writes the default config when there is none ([config-folder.md](config-folder.md)).
2. **The secrets**: without `secrets`, it opens the folder's `.env` over `os.environ` and loads it, so the keys saved in an earlier run reach the libraries ([secrets.md](secrets.md)). An app passing its own store loads it itself.

`locked` is the app's: a function telling whether the saved config is in use (a session running). While it returns true, `save` and `reset` raise `RuntimeError`, and the Setup panel disables them. Without it, the config is never locked.

An app's whole setup:

```python
model = AppModel(APP, ConfigFolder(default_folder(APP.name), APP.default_config), locked=session.running)
```

| Method | What it does |
|---|---|
| `used(config)` | The sections the config uses, in declaration order |
| `saved_config()`, `save(config)`, `reset()` | Read, save, or reset to the default the config in the folder. `save` and `reset` raise `RuntimeError` while the config is locked |
| `locked()` | Whether the app is using the saved config |
| `path` | The folder: where a section's relative paths resolve |
| `check_config(config)` | Every section's `check_config`, each problem as `Problem(section, path, message)`, the path a JSON Pointer into the app's config (`/speech/module/voice_id`). A used section absent from the config is a problem at `/<section>` |
| `check_setup(config)` | Every section's `check_setup`, each item as a `SetupItem`. An extra's item is told which host extras install it (`host_extras`, from [extras.md](extras.md)); an extra unavailable on this platform says so and has none. A section whose library does not import is one missing item, installable by its `host_extra` |
| `missing_extras(config)` | The host extras that install what is missing: the first carrier of each installable item |
| `install(extras, on_output)` | Installs the host's extras with its installer; `InstallError` when the app cannot install (no lock, no uv). Sections whose library did not import are retried afterwards |
| `prepare(config, on_progress)` | Each section with a preparable item missing: its contract's `prepare` |
| `probe(config, section)` | The section's `probe` |
| `options(config, section, name)` | The section's `options` |
| `secret_variables(config)` | Each environment variable the config names for a key, with its source ([secrets.md](secrets.md)) and the pointers naming it |
| `blockers(config)` | Why the config cannot run on this machine yet, in words: its problems, then every missing item; empty when it can. An `unknown` item does not block |
| `used_config(config)` | The documents of the sections the config uses: what the app runs with |

A `SetupItem` is the contract's item with its `section` and `host_extras`; `installable` is true for a missing extra some host extra carries.

The app's own Start uses the model this way: read `saved_config()`, refuse with `blockers(config)` when there are any, then build its runtime from `used_config(config)`, relative paths resolved against `path`.

## Testing

`tests/test_app.py`, over a fake library implementing the contract (`tests/fakes.py`), with the host's extras faked:

- problems pointed into the app's config; a missing section;
- a missing extra told its host extra; unavailable on this platform; carried by no host extra;
- files missing, prepared, then ready;
- a section the config does not use; a library that does not import, then does;
- the install delegated to the installer, and refused without one;
- the secrets named and their sources;
- building the model writes the default config and loads the `.env` under the shell's variables;
- the blockers of a config, then none once ready;
- the config refused while the app locks it, and never locked without a lock.

## Open questions

1. **A section the user can switch off** (an optional library) is expressed today by the section's own schema (an `enabled` field) or by `when`. A generic switch is deferred.
2. **Checks cost an import.** `check_setup` imports each section's providers; the page runs it on request, on a thread. Caching results between two checks is deferred.
