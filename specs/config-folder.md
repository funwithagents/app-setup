---
code:
  - src/module_setup/folder.py
tests:
  - tests/test_folder.py
---

# Config folder

**Status:** Implemented

## Purpose

An app runs from a folder, not from a config file. The folder holds what the Setup tab saves and a session starts from, the app's own settings, and its secrets, so that relaunching the app finds everything as it was left.

## The files

| File | Holds |
|---|---|
| `config.json` | The current config: one key per section, each holding that library's own document |
| `settings.json` | The app's settings: `{"autostart": false}`. Keys this version does not know are kept when it writes |
| `.env` | The secrets ([secrets.md](secrets.md)) |

The app's **default config** is not a file of the folder: it is part of the app (`App.default_config`). On first launch, `ensure()` creates the folder and writes the default as `config.json`, and `{"autostart": false}` as `settings.json`; files already there are left alone. "Reset to defaults" writes the default back as the current config.

Files are written whole and replaced in one step (a temporary file renamed over the old one), so a crash never leaves half a file. JSON is indented, with a final newline, so the file stays readable and diffable by hand.

## Where the folder is

`launch` takes `--folder PATH`. Without it, the folder is `$XDG_CONFIG_HOME/<app name>`, or `~/.config/<app name>` when the variable is unset, on every platform: one rule, no platform-specific directory to look up.

## API

```python
class ConfigFolder:
    def __init__(self, path: Path, default_config: Mapping[str, Any]) -> None: ...
    config_path: Path; settings_path: Path; env_path: Path
    default_config: dict          # a copy
    def ensure(self) -> None: ...
    def read_config(self) -> dict: ...
    def save_config(self, config: Mapping) -> None: ...
    def reset_config(self) -> dict: ...
    def read_settings(self) -> Settings: ...
    def save_settings(self, settings: Settings) -> None: ...

@dataclass(frozen=True)
class Settings:
    autostart: bool = False

def default_folder(app_name: str) -> Path: ...
```

A file that cannot be read, is not valid JSON, or does not hold an object raises `FolderError` (a `ValueError`) naming it; so does a setting of the wrong type.

The folder does not validate the config: an invalid config can be saved, and the Setup tab says what is wrong with it. That way a half-finished config is never lost.

## Testing

`tests/test_folder.py`: the first launch writes the defaults; a saved config survives a relaunch and reset goes back; the default cannot be changed through what is returned; unknown settings are kept; unreadable files name themselves; `XDG_CONFIG_HOME` is followed.

## Open questions

1. **Several configs per app** (profiles) are not supported: one folder is one config. Running the app with another `--folder` is the way to keep two.
2. **Relative paths in a section** (a voice file) resolve against what each library is told: the session receives the folder (`SessionContext.folder`), and a library that takes a `base_dir` is given it there.
