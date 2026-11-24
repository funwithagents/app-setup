---
code:
  - src/app_setup/app.py
tests:
  - tests/test_app.py
  - tests/fakes.py
---

# App

**Status:** Updated

## Purpose

An app built from configurable libraries declares what it is made of, and gets a Setup panel and a Secrets panel for it. This spec is that declaration and the model behind the panels: what an app gives, and what the panels can do with it, with no UI. The panels are in [ui.md](ui.md); the folder and the secrets each have their own spec.

Running the app with its config (a session: Start, Stop, the app's own controls) is the app's own. app-setup only needs to know when the config is in use, to refuse changing it then.

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
    autostart: bool | None = None
```

- **`name`** is the default name of the app's folder ([config-folder.md](config-folder.md)) and, unless `title` is given, its title.
- **`host`** is the distribution the environment is installed from: what [extras.md](extras.md) installs extras of.
- **A section** is one key of the app's config, whose document is owned by one library and described by its contract ([module-contract.md](module-contract.md)). A library's own demo has one section; an app composing libraries has one per library, and may write a contract for settings it owns itself.
- **`contract`** is the contract object, or a function returning it. The function is for a library the host installs only with one of its own extras: while it raises `ImportError`, the section is shown as needing **`host_extra`**, which the page can install; it is tried again after an install.
- **`when`**, given the whole config, says whether the section is used (a section for one embodiment of an app). A section not used is neither drawn nor checked, and the app does not run it; its document stays in the config, so switching back loses nothing.
- **`default_config`** is the first config of a new folder, and what "Reset" goes back to.
- **`autostart`** says the app starts its session at launch by default (`None`: it has no autostart); the user's choice is kept in the folder's `launch.json` ([autostart.md](autostart.md)). `AppModel.autostart()` and `set_autostart(on)` read and write it.

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
| `used(config, sections=None)` | The sections the config uses, in declaration order (only those of `sections`, when given) |
| `saved_config()`, `save(config)`, `reset()` | Read, save, or reset to the default the config in the folder. `save` and `reset` raise `RuntimeError` while the config is locked |
| `unsaved(draft)` | Whether a draft differs from the saved config: the whole config compared, not only the sections it uses (Save writes the whole draft, a section not used keeps its document, and `when` reads keys outside the sections) |
| `locked()` | Whether the app is using the saved config |
| `path` | The folder: where a section's relative paths resolve |
| `check_config(config, sections=None)` | Every section's `check_config`, each problem as `Problem(section, path, message)`, the path a JSON Pointer into the app's config (`/speech/module/voice_id`). A used section absent from the config is a problem at `/<section>` |
| `check_setup(config, sections=None)` | Every section's `check_setup`, each item as a `SetupItem`; a section whose document has problems is not asked, since the contract asks it only about a config `check_config` accepts: its extras come instead from its `required_extras` (which takes an incomplete config) and the installed packages' metadata, so an extra can be installed while the config is still being fixed — a field filled from a list the extra provides would otherwise never be filled. An extra's item is told which host extras install it (`host_extras`, from [extras.md](extras.md)); an extra unavailable on this platform says so and has none. A section whose library does not import is one missing item, installable by its `host_extra` |
| `missing_extras(config, sections=None)` | The host extras that install what is missing: the first carrier of each installable item |
| `install(extras, on_output)` | Installs the host's extras with its installer; `InstallError` when the app cannot install (no lock, no uv). Sections whose library did not import are retried afterwards |
| `prepare(config, items=None, on_progress=None)` | Makes the given `SetupItem`s ready, **all at the same time**, each on its own thread through its section's contract (`prepare(document, item.id, …)`); with `items=None`, every preparable item of the used sections that is not ready. `on_progress` receives each contract event with the item's `section` and `id` added. Blocks until every item is done and returns one `Prepared(item, ok, message)` per item: a failure is that item's outcome, with its message, and the others go on. Never raises for an item |
| `to_prepare(config, sections=None)` | The preparable items not ready yet: what **Prepare all** prepares |
| `deferred(config, sections=None)` | The missing items that are not required: what a session would get by itself, slower, if they are not prepared before |
| `probe(config, section)` | The section's `probe` |
| `options(config, section, name)` | The section's `options` |
| `secret_variables(config)` | Each environment variable the config names for a key, with its source ([secrets.md](secrets.md)) and the pointers naming it |
| `blockers(config, sections=None)` | Why the config cannot run on this machine yet, in words: its problems, then every missing **required** item; empty when it can. A missing item that is not required does not block (the session gets it), nor does an `unknown` one |
| `used_config(config)` | The documents of the sections the config uses: what the app runs with |

The checks take an optional `sections`: the Setup panel asks about one section at a time, so its Check, Install, Prepare and Test act on that section alone.

A `Prepared` is an item's outcome: `ok`, and the failure's message when not. A `SetupItem` is the contract's item (`required` included) with its `section` and `host_extras`; `installable` is true for a missing extra some host extra carries. `variable` names the environment variable a **key** item is about, so the Setup panel can offer a field to set it: the contract has one item per variable the config names for a key, not preparable and required, and gives it no kind ([module-contract.md](module-contract.md)), so an item that is neither an extra nor preparable is a key item when its `id` or `title` names, as a whole word, one of the variables its section's document names (`x-secret-env` fields, their defaults included); `None` for every other item. An item breaking the contract's rules (a key missing, not required and not preparable) raises `ContractError` naming the section and the item: it is the library's bug, and shows in its own tests and demo.

The app's own Start uses the model this way: read `saved_config()`, refuse with `blockers(config)` when there are any, then build its runtime from `used_config(config)`, relative paths resolved against `path`. Before building, an app may prepare what the session would otherwise get by itself — `prepare(config, deferred(config), on_progress)`, its progress shown in the app's own session view — so the first use is not the slow one; whether it does is the app's choice (app-setup does not run a session).

## Testing

`tests/test_app.py`, over a fake library implementing the contract (`tests/fakes.py`), with the host's extras faked:

- problems pointed into the app's config; a missing section;
- a missing extra told its host extra; unavailable on this platform; carried by no host extra;
- files missing, prepared, then ready; one item prepared alone, the others left missing; two items prepared at the same time (each started before the other finished); progress events carrying the section and the id; one item failing, its outcome carrying the message, the other prepared;
- a missing item that is not required listed in `deferred`, not in `blockers`; a malformed item refused;
- a section the config does not use; a library that does not import, then does;
- the install delegated to the installer, and refused without one;
- the secrets named and their sources; a key item told its variable, the other items none;
- building the model writes the default config and loads the `.env` under the shell's variables;
- the blockers of a config, then none once ready;
- the config refused while the app locks it, and never locked without a lock;
- a draft unsaved until it is saved, a change to a section not used included.

## Open questions

1. **A section the user can switch off** (an optional library) is expressed today by the section's own schema (an `enabled` field) or by `when`. A generic switch is deferred.
2. **Checks cost an import.** `check_setup` imports each section's providers; the page runs it on request, on a thread. Caching results between two checks is deferred.
