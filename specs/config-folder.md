---
code:
  - src/module_setup/folder.py
tests:
  - tests/test_folder.py
---

# Config folder

**Status:** Implemented

## Purpose

An app runs from a folder, not from a config file. The folder holds what the Setup panel saves and the app runs with, and its secrets, so that relaunching the app finds everything as it was left.

## The files

| File | Holds |
|---|---|
| `config.json` | The current config: one key per section, each holding that library's own document |
| `.env` | The secrets ([secrets.md](secrets.md)) |

The app may keep files of its own in the folder (its settings, such as whether to start a session at launch); module-setup never reads, writes or removes them.

The app's **default config** is not a file of the folder: it is part of the app (`App.default_config`). On first launch, `ensure()` creates the folder and writes the default as `config.json`; a config already there is left alone. Building the `AppModel` calls it ([app.md](app.md)). "Reset to defaults" writes the default back as the current config.

Files are written whole and replaced in one step (a temporary file renamed over the old one), so a crash never leaves half a file. JSON is indented, with a final newline, so the file stays readable and diffable by hand.

## Where the folder is

The app chooses it, typically from a `--folder` option of its own. `default_folder(name)` is the usual default: `$XDG_CONFIG_HOME/<name>`, or `~/.config/<name>` when the variable is unset, on every platform: one rule, no platform-specific directory to look up.

## API

```python
class ConfigFolder:
    def __init__(self, path: Path, default_config: Mapping[str, Any]) -> None: ...
    config_path: Path; env_path: Path
    default_config: dict          # a copy
    def ensure(self) -> None: ...
    def read_config(self) -> dict: ...
    def save_config(self, config: Mapping) -> None: ...
    def reset_config(self) -> dict: ...

def default_folder(app_name: str) -> Path: ...
```

A file that cannot be read, is not valid JSON, or does not hold an object raises `FolderError` (a `ValueError`) naming it.

The folder does not validate the config: an invalid config can be saved, and the Setup panel says what is wrong with it. That way a half-finished config is never lost.

## Testing

`tests/test_folder.py`: the first launch writes the default config and leaves the app's own files alone; a saved config survives a relaunch and reset goes back; the default cannot be changed through what is returned; unreadable files name themselves; `XDG_CONFIG_HOME` is followed.

## Open questions

1. **Several configs per app** (profiles) are not supported: one folder is one config. Running the app with another `--folder` is the way to keep two.
2. **Relative paths in a section** (a voice file) resolve against what each library is told: the app runs them with the folder (`AppModel.path`), and a library that takes a `base_dir` is given it there.
