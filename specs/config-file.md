---
code:
  - src/app_setup/config_file.py
  - src/app_setup/folder.py
  - src/app_setup/app.py
  - src/app_setup/autostart.py
  - src/app_setup/launch.py
  - src/app_setup/ui/panels.py
  - src/app_setup/ui/config_page.py
tests:
  - tests/test_config_file.py
  - tests/test_launch.py
  - tests/test_autostart.py
  - tests/ui/test_panels.py
  - tests/ui/test_config_page.py
---

# Config file

**Status:** Draft

## Purpose

An app runs from its folder ([config-folder.md](config-folder.md)): a config the Setup panel edits and saves, kept between launches. Two more uses need a single config **file** instead:

- **Running a given file as it is**: an example config kept with the code, a config prepared on another machine, an end-to-end test. Nothing is edited; the file is what runs.
- **Editing a file without running anything**: writing or fixing the config a program will be started with, with the same form, checks, installs and secrets as the Setup panel, but no session.

This spec adds the file next to the folder, as a second **source** of the config, and the three ways an app can be launched with them.

## The three launches

| Launch | The config | The Setup panel | The session |
|---|---|---|---|
| **From the folder** (`--folder DIR`, or the default folder) — today | `DIR/config.json`, edited and saved | Editable | At launch per `launch.json`, else `App.autostart` ([autostart.md](autostart.md)) |
| **From a file** (`--config FILE`) | `FILE`, as it is: never written | **Read-only** (below) | **At launch**, unless `--no-start` |
| **Editing a file** (a config app: `FILE` given) | `FILE`, edited and saved back to it | Editable | None: the page has Setup and Secrets only |

In all three, the keys come from **the `.env` next to the config** — `DIR/.env` for a folder, the `.env` in the file's directory for a file — unless **`--env PATH`** names another. The shell still wins over the file ([secrets.md](secrets.md)). One rule, the same whether an app runs from a folder or a file: the secrets sit beside the config they serve, and one `.env` serves every config of a directory (all the example configs of a project, say). A project keeping configs in its repository lists `.env` in its `.gitignore`.

## A config file

`ConfigFile(path, *, section=None, env_path=None, writable=False)`:

- **The file must exist.** Building it with a path that is not a file raises `ConfigFileError` (a `ValueError`) naming it: an app given `--config` with a missing file stops at launch with that message and serves no page. Nothing is created, and there is no default to write: the file is the user's. The same for a file that is not valid JSON or not an object.
- **`section`**: with a section name, the file **is that section's document** (a library's config, exactly what its contract describes), and the model sees it as `{section: document}`. Without one, the file holds the whole app config, one key per section, like a folder's `config.json`. So a library's own example configs, each one document of the library, run as they are, and an app composing several libraries runs a file in its own shape.
- **`writable`**: whether Save writes back to the file. False for an app running a file (`--config`); true for a config app. A file that is not writable is never written, whatever is clicked; `save` and `reset` raise `RuntimeError`.
- **Reset** has nothing to go back to (a file has no default): a config app offers **Revert** only, which reads the file again.
- **Relative paths** in the config resolve against the file's directory (`base_dir`), as the libraries' own `from_json_file` do ([module-contract.md](module-contract.md), "Relative paths").
- **No launch settings**: a file has no `launch.json`. An app running a file starts its session at launch (below); a config app has no session.

The file is read again each time the config is asked for (`saved_config()`), so an app running a file picks up a hand edit at the next Start: Stop, edit the file, Start, without relaunching.

## The source of a config

`AppModel(app, source, secrets=None, locked=None)` takes either a `ConfigFolder` or a `ConfigFile` (the parameter was `folder`; renamed, since it may be a file). Both give the model what it needs:

| | `ConfigFolder` | `ConfigFile` |
|---|---|---|
| `base_dir` (where relative paths resolve; `AppModel.path`) | the folder | the file's directory |
| `env_path` | `DIR/.env`, or `--env` | the `.env` in the file's directory, or `--env` |
| `read_config()` | `config.json` | the file (wrapped in `{section: …}` with a section) |
| `save_config(config)` | writes `config.json` | writes the file (the section's document alone with a section); `RuntimeError` when not writable |
| `reset_config()` | writes the default back | `RuntimeError`: no default |
| `writable` | true | as given |
| `resettable` | true | false |
| `read_launch()` / `save_launch()` | `launch.json` | none: `{}`, and saving raises |

`ConfigFolder` gains `env_path=None` (the `.env` is `DIR/.env` unless given) and the `base_dir`, `writable` and `resettable` properties. `AppModel.editable` is `source.writable`; `AppModel.source` replaces `AppModel.folder`.

## The command line

`app_setup.launch` gives every app the same options and the same way to open its source:

```python
def add_config_arguments(parser: argparse.ArgumentParser, app: App) -> None: ...
    # --folder DIR (default: default_folder(app.name)) | --config FILE, one or the other; --env PATH

def open_source(options: argparse.Namespace, app: App, *, section: str | None = None) -> ConfigFolder | ConfigFile: ...
    # --config FILE: a ConfigFile, not writable, with `section`; else the ConfigFolder; --env on either.
    # Raises ConfigFileError for a missing or unreadable file.
```

`starts_at_launch(model, flag)` ([autostart.md](autostart.md)) gains one rule: **from a file, the session starts at launch** unless `--no-start` (the flag is `False`), whatever `App.autostart` says. Running a given file is asking for it to run.

An app's whole launch:

```python
parser = argparse.ArgumentParser()
add_config_arguments(parser, APP)
add_start_arguments(parser)
options = parser.parse_args()
try:
    source = open_source(options, APP, section="speech")   # a library's demo: its file is one document
except ConfigFileError as exc:
    parser.error(str(exc))
model = AppModel(APP, source, locked=session.running)
if starts_at_launch(model, options.start):
    start_session(model)
```

## The Setup panel, read-only

When the model is not editable (an app running a file), `setup_panel(model)` draws:

- a line naming the file: "Running `examples/configs/local-voice.json` as it is. To change it, edit the file, then Stop and Start the session.";
- each section's form **read-only** (every field shown, none editable, no module switch, no list button), so the values that run can be read;
- each section's checks as for a folder: **Check**, the table with its **Install**, key fields and **Prepare**, **Install all**, **Prepare all**, **Test**. None of them changes the config: they install packages, write keys to the `.env`, prepare files, so they all still work;
- no "Unsaved changes" line, no Save, Revert or Reset, no launch checkbox.

The Secrets panel is unchanged: it writes to the source's `.env`, and its title names that file.

## A config app

`config_page(model) -> gr.Blocks`: a page with two tabs, **Setup** (`setup_panel(model)`) and **Secrets** (`secrets_panel(model, setup.draft)`), and no session. The model's source is a writable `ConfigFile`: Save writes back to the file, Revert reads it again, there is no Reset.

```python
def add_config_app_arguments(parser: argparse.ArgumentParser) -> None: ...
    # FILE (positional, required), --env PATH, --host, --port

def open_config_app(options: argparse.Namespace, app: App, *, section: str | None = None) -> AppModel: ...
    # a writable ConfigFile (ConfigFileError for a missing file), its .env loaded
```

A library's config app is then a few lines in its project, naming its contract:

```python
APP = App(name="speech-lib-config", host="speech-lib",
          sections=(Section("speech", speech_lib.setup, title="Speech"),), default_config={})

parser = argparse.ArgumentParser(description="Edit a speech-lib config file.")
add_config_app_arguments(parser)
options = parser.parse_args()
try:
    model = open_config_app(options, APP, section="speech")
except ConfigFileError as exc:
    parser.error(str(exc))
config_page(model).launch(server_name=options.host, server_port=options.port)
```

It runs in the project's own environment (`uv run python -m …`), as the library's demo does: its checks, and what it installs, are those of the environment the config will run in. A config app installed elsewhere would report another environment.

An app that already has a page (and a session) may instead offer its own command for editing a file, building the same `config_page` from `open_config_app`: one program, one more command.

## Testing

- `tests/test_config_file.py`: a missing file, a directory, invalid JSON and a non-object each refused, naming the file; a section's document read as `{section: …}` and saved back alone; a whole-config file read and saved as it is; a file not writable never written (`save` and `reset` raise, the file's bytes unchanged); relative paths against the file's directory; the `.env` next to the file, or `--env`'s; a hand edit seen at the next read.
- `tests/test_launch.py`: `--folder` and `--config` exclusive; neither gives the default folder; `--env` on both; `open_source` for each; a missing file's error.
- `tests/test_autostart.py`: from a file, the session starts at launch, `--no-start` excepted, whatever `App.autostart` and whatever a `launch.json` nearby holds.
- `tests/ui/test_panels.py`: a read-only model draws the file's line, a read-only form, the table and its actions, and no Save, Revert, Reset, unsaved line or launch checkbox; a key saved from a line reaches the file's `.env`.
- `tests/ui/test_config_page.py`: the page has Setup and Secrets only; Save writes the file (a section's document alone); Revert reads it again; no Reset.
- Browser (`tests-e2e/test_panels_in_browser.py`): a config app edits a file and saves it; an app running a file shows the form read-only and installs from a line.

## Changes to the other specs, once this one is Stable

- [config-folder.md](config-folder.md): `env_path` given or `DIR/.env`; `base_dir`, `writable`, `resettable`; "An app runs from a folder" becomes "from a folder or a file".
- [app.md](app.md): `AppModel(app, source, …)`, `source`, `editable`; `reset` refused for a source without a default.
- [autostart.md](autostart.md): the file rule in `starts_at_launch`; no checkbox without launch settings.
- [secrets.md](secrets.md): the `.env` is the source's (next to the config, or `--env`).
- [ui.md](ui.md): the read-only Setup panel; `config_page`.

Each moves to **Updated** with that change, and back to **Implemented** with the plan that builds it.

## Open questions

1. **A config app creating a new file** is not offered: a missing file is an error. Starting from the app's default config (`App.default_config`), written at the first Save, could be added if writing a first file by hand proves a chore.
2. **Watching the file** while the app runs (a hand edit shown at once on the read-only panel) is deferred: the panel shows what was read at its last check, and a session reads the file at each Start.
3. **The read-only form** could be replaced by the file's JSON, folded, if drawing every field read-only proves costly in gradio.
