---
code:
  - src/module_setup/form.py
  - src/module_setup/ui/form.py
  - src/module_setup/ui/page.py
  - src/module_setup/ui/report.py
tests:
  - tests/test_form.py
  - tests/ui/test_page.py
  - tests/ui/test_report.py
---

# UI

**Status:** Implemented

## Purpose

The page every app gets: a Setup tab to edit, check and install, a Secrets tab for keys, and a Session tab to start, use and stop the runtime. It is drawn with gradio, behind the `ui` extra; everything it decides comes from the gradio-free model ([app.md](app.md)), so a library that only needs the contract's conformance check never installs gradio.

## Launching

```python
from module_setup.app import App, Section
from module_setup.ui import launch

launch(App(...))
```

`launch(app, argv=None, **launch_options)` is an app's whole `main()`. It reads `--folder`, `--host` (default `127.0.0.1`), `--port` and `--no-autostart`; prepares the folder ([config-folder.md](config-folder.md)); loads the secrets ([secrets.md](secrets.md)); autostarts ([session.md](session.md)); serves the page; and stops the session when the page stops. `build_page(model, selected="setup")` builds the page alone, for an app that serves it itself.

## The page

A title, the session's state (refreshed every second), and three tabs.

**Setup**

- **Save**, **Revert to saved**, **Reset to defaults** (save and reset are disabled while a session runs), and the autostart switch.
- **The form**: one group per section the config uses.
- **Checks**: **Check** shows the config's problems and a table of what the machine is missing; **Install missing extras** installs the host extras that carry them, streaming uv's output; **Download missing files** runs `prepare`, streaming its progress; **Test** runs one section's `probe`. All four act on the form's current values, saved or not.

**Secrets**: the variables the config names, each with its source; a name and a password field to write one to the folder's `.env`, or remove it. Values are never shown.

**Session**: **Start** and **Stop**, the state, why a start was refused, then the app's own content (`App.session_ui`), drawn once inside the tab and given the runner: its handlers reach the running session through `runner.session`.

Every browser tab has its own draft of the config; the saved config, the secrets and the session are the model's, shared by all.

## The form

`module_setup.form` turns a section's parsed schema and document into a tree of items, with no gradio:

| Item | From | Drawn as |
|---|---|---|
| `FormGroup` | An object | Its title and description, its items, the advanced ones in a folded **Advanced** block; an optional object gets a **Configure …** switch (off: the key is absent, so the library's defaults apply or the feature is off, as the object's description says), and its items only when on |
| `FormChoice` | A `oneOf` | A dropdown of the modules; the selected module's fields follow the common ones |
| `FormField` | A field | A text box, a number (whole for an integer) showing the default when the key is absent, a checkbox, a dropdown for an `enum`, JSON text for an array. A number with neither a value nor a default is a text box, since a number box cannot be empty |
| `FormRaw` | A free-form object | JSON text |

- A key written in the config itself (`x-secret`) is never drawn.
- A field's description is its help text; its default is shown, not written.
- **What an edit writes** (`coerce`): an empty widget, or a value equal to the field's default, removes the key, so the config holds only what differs from the library's own defaults. A number with no fraction is written as an integer; a field accepting several kinds takes a number when the text is one and the field accepts it. An invalid value (bad JSON, a fraction for an integer) is refused with a message, and the config is unchanged.
- **Switching module** (`select_branch`) keeps the fields common to every module and those the two modules share by name, and drops the old module's own.
- **A named list** (`x-options` on a module or a field) gets a button that loads `options` and a dropdown whose choice writes its fields.

A change of structure (a module switched, an optional object turned on or off, a choice from a list, revert, reset) draws the form again; a value edit does not, so typing never loses focus. Each section's problems are not drawn on the fields: **Check** lists them with their pointers.

## Reports

`module_setup.ui.report` writes the model's answers as Markdown: the problems with their pointers, the setup table (section, item, status, detail, and what to do: the host extra to install, or "Prepare downloads it"), the secrets table, and the session line.

## Testing

- `tests/test_form.py`: the tree for each kind of item; every coercion and every refusal; writing, creating and removing; switching module; optional objects; the variables a config names.
- `tests/ui/test_page.py`: the form drawn into a real gradio page (the selected module's fields, the hidden key, the list button, a section without its library); the page built with the app's own session content; the tab it opens on.
- `tests/ui/test_report.py`: the wording of every report.

Behaviour in a browser (events, the timer) is not covered by the fast tier.

## Open questions

1. **Problems on the fields themselves**, rather than in the Check report.
2. **Lists of objects as rows** rather than JSON text.
3. **Checking as one types**: today checks run on request, since `check_setup` imports providers.
4. **A browser test** of the page in the live tier: gradio's client cannot drive the per-browser draft, so the form's events are not tested today.
5. **The page's events are also gradio API endpoints**, saving a key included. The page listens on `127.0.0.1` by default; serving it on another address (`--host`) exposes them to that network. Hiding them, or adding authentication, is deferred.
