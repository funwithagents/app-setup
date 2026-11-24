---
code:
  - src/module_setup/autostart.py
tests:
  - tests/test_autostart.py
  - tests/ui/test_panels.py
---

# Autostart

**Status:** Implemented

## Purpose

Some apps start their session as soon as they launch (a demo that listens right away, a robot app that wakes up talking). Each such app used to decide that its own way: a hard-coded start, a flag, nothing. This spec gives them one way, so every app built on the panels behaves the same: whether the app starts at launch is a setting of its config, edited on the Setup panel like any other, and a command-line flag overrides it for one launch.

What starting means stays the app's ([app.md](app.md): running the config is the app's own). module-setup provides the setting, the flags and the decision; the app calls its own Start when the decision says so.

## The section

```python
from module_setup.autostart import autostart_section

APP = App(
    ...,
    sections=(Section("speech", speech_lib.setup, title="Speech"), autostart_section(default=True)),
    default_config={"speech": {...}, "app": {"autostart": True}},
)
```

`autostart_section(default=True, name="app", title="App") -> Section` is a section of `config.json` like a library's ([app.md](app.md)), named `name` (`app` unless the app already uses that key), holding one document:

```json
{"autostart": true}
```

Its contract (`AutostartContract`) is a real module contract ([module-contract.md](module-contract.md)), which `check_contract` accepts:

| Function | What it does |
|---|---|
| `config_schema` | `{"autostart": boolean}`, titled "Start at launch", described "Start the session when the app launches.", its default `default` |
| `check_config` | Refuses an `autostart` that is not `true` or `false`; an absent one is the default |
| `required_extras`, `check_setup`, `options` | Nothing: it needs no extra and nothing on the machine |
| `prepare` | Does nothing |
| `probe` | Ok, nothing to test |

The Setup panel draws it as any section: its own block, titled `title`, holding a checkbox. Saving it is saving the config, refused while a session runs.

The app's default config should set it, so a new folder says what the app does. Starting at launch by default is safe only when the default config needs nothing installed and no key (a fixture module); otherwise default to `false`.

## The flags

`add_start_arguments(parser)` adds `--start` / `--no-start` to the app's `argparse` parser (`BooleanOptionalAction`): `options.start` is `True`, `False`, or `None` when neither is given. A flag is for one launch: it is not saved.

## The decision

`starts_at_launch(model, flag) -> bool`:

1. the flag, when given (`--start` / `--no-start`);
2. else the saved config's `<name>.autostart`, `<name>` being the section whose contract is the autostart contract (`app` for an app declaring none);
3. else the section's default (`False` for an app declaring none).

A launch that should start but whose saved config has blockers (`model.blockers(config)`, [app.md](app.md)) is the app's to handle: its Start refuses as it would from a button, and the app shows the blockers instead of starting. The page opens either way, so the user can fix them.

```python
parser = argparse.ArgumentParser()
add_start_arguments(parser)
options = parser.parse_args()
model = AppModel(APP, ConfigFolder(options.folder, APP.default_config), locked=session.running)
if starts_at_launch(model, options.start):
    blockers = session.start(model)  # the app's own Start; shows its blockers when there are some
```

## Testing

`tests/test_autostart.py`:

- the contract passes `check_contract`; its schema's default follows `default`;
- a non-boolean refused, at a pointer into the app's config; the section's name and title as given;
- the flag wins over the saved config; without it, the saved config decides, read at the section's own name; a config without the section falls back to its default; an app without the section does not start unless told;
- `--start`, `--no-start` and neither parsed next to the app's own arguments.

`tests/ui/test_panels.py`: the section drawn as a checkbox, showing the saved value, under its title.

## Open questions

None.
