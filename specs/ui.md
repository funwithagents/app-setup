---
code:
  - src/module_setup/form.py
  - src/module_setup/ui/form.py
  - src/module_setup/ui/panels.py
  - src/module_setup/ui/report.py
tests:
  - tests/test_form.py
  - tests/ui/test_panels.py
  - tests/ui/test_report.py
  - tests-e2e/test_panels_in_browser.py
---

# UI

**Status:** Implemented

## Purpose

Two panels an app draws in its own page: a **Setup** panel to edit, check and install, and a **Secrets** panel for keys. The app decides which it shows and where (a tab, a column, an accordion), and builds the rest of its page itself, its session first of all: starting, using and stopping the runtime differ from one app to the next. The panels are drawn with gradio, behind the `ui` extra; everything they decide comes from the gradio-free model ([app.md](app.md)), so a library that only needs the contract's conformance check never installs gradio.

## Using the panels

```python
import gradio as gr

from module_setup.app import AppModel
from module_setup.folder import ConfigFolder, default_folder
from module_setup.ui import secrets_panel, setup_panel

model = AppModel(APP, ConfigFolder(default_folder(APP.name), APP.default_config), locked=session.running)

with gr.Blocks() as page:
    with gr.Tab("Session"):
        ...                                   # the app's own: Start, Stop, its controls
    with gr.Tab("Setup"):
        setup = setup_panel(model)
    with gr.Tab("Secrets"):
        secrets_panel(model, setup.draft)

page.launch()
```

Each panel is a function drawing its components where it is called, inside the app's `gr.Blocks`. It brings its own state, its own events and its own page-load step (a `gr.on` with no trigger), so either can be used alone, and nothing has to be wired between them except what the app chooses.

Serving the page, the command line, when to start a session (a setting of the app's to start one at launch, for instance) and stopping it at exit are the app's.

## The panels

**`setup_panel(model) -> SetupPanel`**

- **Save**, **Revert to saved**, **Reset to defaults**. Save and Reset are disabled, with a line saying a session is running, while the model is locked (`AppModel.locked`, polled every second).
- A line saying that a field marked `*` must be filled in (the schema's `required`) and the others have a default (shown in the field's hover text) or can stay empty.
- **One block per section**, in the app's order, shown while the config uses it (`when`): its title (the app's `Section(title=…)`, else its library's, never its key), its form, then **its own checks**, acting on that section alone: **Check** shows its problems and a table of what the machine is missing for it; **Install missing extras** installs the host extras that carry what it misses, streaming uv's output; **Download missing files** runs its `prepare`, streaming its progress; **Test** runs its `probe`. The output box appears with the first action. All four act on the form's current values, saved or not. A section is one library's contract, so what it needs is installed, downloaded and tested with it; Save, Revert and Reset stay for the whole config, one file and one draft, since sections can depend on each other (`when`).
- The checks also run by themselves, for each section, each time the form's structure changes (the page loaded, a module switched, an optional object turned on or off, a choice from a list, revert, reset), and each section's output is cleared then: what was shown was about another config. A value typed does not run them; **Check** does.

It returns what the app can listen to:

| Field | What it is |
|---|---|
| `draft` | A `gr.State` holding the config being edited in this browser tab: an input for the app's own events |
| `saved` | A `gr.State` that changes each time the panel saves or resets the config: `setup.saved.change(...)` follows the saved config |

**`secrets_panel(model, config=None)`**: the variables the config names, each with its source; a name and a password field to write one to the folder's `.env`, or remove it. Values are never shown. A variable the shell sets that the `.env` also sets reads "the shell (the folder's .env also sets it, unused)", with how to use the file's value; the other variables the `.env` sets, named by no section of the current config, have their rows in the same table ("— not named by the current config"), so a stale key can be seen and removed. Saving a variable the shell sets says the shell's value is the one used. Given a `gr.State` (a Setup panel's `draft`), it reads the variables from it and follows each change, so the key a newly chosen module needs appears at once; without one, it reads the saved config, on page load and on **Refresh**.

Every browser tab has its own draft of the config; the saved config and the secrets are the model's, shared by all.

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
- **Switching module** (`select_branch`) keeps the fields common to every module and drops the old module's own, even those the new module has under the same name (a voice id of one provider means nothing to another).
- **A named list** (`x-options` on a module or a field) gets a button that loads `options` and a dropdown whose choice writes its fields.

A change of structure (a module switched, an optional object turned on or off, a choice from a list, revert, reset) draws the form again; a value edit does not, so typing never loses focus. Choosing the module already selected, or switching an object to the state it is in, draws nothing. The module dropdown listens to `select`, which fires once per choice (`input` fires twice, and each redraw replaces the fields). A text or number field writes on `input` and again on `blur`, so a value typed right after a redraw, before the field's listeners are attached, still reaches the config. Every form component is explicitly interactive: gradio does not infer it for components drawn inside `gr.render`. Each section's problems are not drawn on the fields: **Check** lists them with their pointers.

## Reports

`module_setup.ui.report` writes the model's answers as Markdown: the problems with their pointers, the setup table (section, item, status, detail, and what to do: the host extra to install, or "Prepare downloads it"), and the secrets table.

## Testing

- `tests/test_form.py`: the tree for each kind of item; every coercion and every refusal; writing, creating and removing; switching module; optional objects; the variables a config names.
- `tests/ui/test_panels.py`: the form drawn into a real gradio page (the selected module's fields, the hidden key, the list button, a section without its library); both panels drawn in an app's own tabs, next to its own components; Save and Reset disabled while the app locks the config; the Secrets panel reading the config it follows, else the saved one.
- `tests/ui/test_report.py`: the wording of every report.

Behaviour in a browser is not covered by the fast tier: gradio's client cannot drive the per-browser draft. `tests-e2e/test_panels_in_browser.py` drives the panels in headless Chromium (Playwright, skipped when absent), inside an app's page where they are not the first tab: switch module, type a required field, save; switch back, pick a voice from the list, save; the saved file is checked each time. Then the Secrets panel lists the key the unsaved draft names, and Save is disabled while the app's session runs and enabled once it stops. It found that the form's fields were not interactive, and that a value typed right after a module switch was lost.

## Open questions

1. **Problems on the fields themselves**, rather than in the Check report.
2. **Lists of objects as rows** rather than JSON text.
3. **Checking as one types**: today checks run on request, since `check_setup` imports providers.
4. **The panels' events are also gradio API endpoints**, saving a key included. Where the page listens is the app's choice: on another address than `127.0.0.1`, they are exposed to that network. Hiding them, or adding authentication, is deferred.
