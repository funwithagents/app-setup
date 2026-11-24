---
code:
  - src/app_setup/autostart.py
  - src/app_setup/app.py
  - src/app_setup/folder.py
  - src/app_setup/ui/panels.py
tests:
  - tests/test_autostart.py
  - tests/ui/test_panels.py
---

# Autostart

**Status:** Implemented

## Purpose

Some apps start their session as soon as they launch: a robot's app started at boot, a demo that used to connect before its page opened. They keep doing so, the same way in every app built on app-setup, and the user can turn it off, or force it for one launch.

## Decided

- **An app declares it:** `App(..., autostart=True)` — whether it starts its session at launch by default. `None` (the default) means the app has no autostart: no switch is drawn, and it starts only on `--start`.
- **The user's choice lives apart from the config,** in the folder's **`launch.json`** (`{"autostart": bool}`, [config-folder.md](config-folder.md)), written only once the user changes it; until then the app's default applies.
  - So `config.json`, and `AppModel.used_config`, stay exactly the app's own sections: an app building a typed config object from them has nothing to add, and no key of the app's can collide with it.
  - So the choice is not caught by the config's lock: it can change while a session runs, and takes effect at the next launch. **Reset to defaults** resets the config only.
- **The Setup panel draws it** for an app with autostart: a "Start the session when the app launches" checkbox at the top, saved at once, then a "Configuration" title over Save, Revert and Reset, so the choice does not read as part of the config those buttons act on ([ui.md](ui.md)).
- **One launch can override it:** `add_start_arguments(parser)` adds `--start` / `--no-start` (`argparse.BooleanOptionalAction`, default `None`), so an app's command line reads the same everywhere. `--start true/false` was not chosen: a flag pair is the usual style, and needs no string-to-boolean parsing.
- **`starts_at_launch(model, flag)`** decides: the flag when given; else `launch.json`; else `App.autostart`; `False` for an app without autostart. Whether the saved config can run is the app's to check: its own Start looks at `model.blockers(...)` and shows them instead of starting.

## API

```python
@dataclass(frozen=True)
class App:
    ...
    autostart: bool | None = None

class AppModel:
    def autostart(self) -> bool | None: ...         # launch.json, else App.autostart; None without autostart
    def set_autostart(self, on: bool) -> None: ...  # writes launch.json; RuntimeError for an app without autostart

def add_start_arguments(parser: argparse.ArgumentParser) -> None: ...
def starts_at_launch(model: AppModel, flag: bool | None) -> bool: ...
```

## Testing

`tests/test_autostart.py`: the app's default holds until a choice is saved, and nothing is written before; the choice goes to `launch.json`, never into the config or `used_config`, and survives Reset; it can change while the config is locked; an app without autostart has no choice and starts only on `--start`; the flag, then the saved choice, then the default; the arguments parse `--start`, `--no-start` and neither. `tests/ui/test_panels.py`: an app with autostart gets the checkbox, loaded from the saved choice and saved on change; an app without gets none.

## Open questions

1. **A first version kept the choice in the config,** as a section app-setup provided (`autostart_section`). Dropped before release: apps that build a typed object from their config would have had to accept a section they never use, and an app wanting its own `app` section could collide with it.
