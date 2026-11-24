---
code:
  - src/app_setup/form.py
  - src/app_setup/ui/form.py
  - src/app_setup/ui/panels.py
  - src/app_setup/ui/report.py
tests:
  - tests/test_form.py
  - tests/ui/test_panels.py
  - tests/ui/test_report.py
  - tests-e2e/test_panels_in_browser.py
---

# UI

**Status:** Updated

## Purpose

Two panels an app draws in its own page: a **Setup** panel to edit, check and install, and a **Secrets** panel for keys. The app decides which it shows and where (a tab, a column, an accordion), and builds the rest of its page itself, its session first of all: starting, using and stopping the runtime differ from one app to the next. The panels are drawn with gradio, behind the `ui` extra; everything they decide comes from the gradio-free model ([app.md](app.md)), so a library that only needs the contract's conformance check never installs gradio.

## Using the panels

```python
import gradio as gr

from app_setup.app import AppModel
from app_setup.folder import ConfigFolder, default_folder
from app_setup.ui import secrets_panel, setup_panel

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

- For an app with autostart, **first** a **"Start the session when the app launches"** checkbox, loaded from the folder's `launch.json` and saved at once, enabled while a session runs ([autostart.md](autostart.md)), then a **Configuration** title over the buttons below: the launch choice is not part of the config, and Save, Revert and Reset do not touch it.
- **Save**, **Revert to saved**, **Reset to defaults**. Save and Reset are disabled, with a line saying a session is running, while the model is locked (`AppModel.locked`, polled every second).
- A line saying that a field marked `*` must be filled in (the schema's `required`) and the others have a default or can stay empty, and that a value in grey is a default: not set, not saved.
- **One block per section**, in the app's order, shown while the config uses it (`when`): its title (the app's `Section(title=…)`, else its library's, never its key), its form, then **its own checks**, acting on that section alone: **Check** shows its problems and **one row per item** of what the machine needs for it (below); **Install missing extras** installs the host extras that carry what it misses, streaming uv's output; **Prepare all** prepares every item not ready yet, all at the same time, each in its own row; **Test** runs its `probe`. The output box appears with the first action that writes to it (Check's problems, Install, Test). All four act on the form's current values, saved or not. While Check, Install or Test runs, the section's other buttons are disabled, rows included; preparations run alongside each other (below).
- **An item's row**: its title, its state in plain words, its detail, and what can be done about it:
  - *Ready.*
  - *Missing* (required): what the user must do — the host extra **Install missing extras** adds, the key to set in **Secrets**, the file to provide — or, for a preparable one, a **Prepare** button.
  - *Not prepared yet* (not required): "The first start will prepare it itself and be slower"; a **Prepare** button.
  - *Unknown*: the detail.
  - While it is prepared: a progress bar with its share done and the library's message, which says what is happening ("Downloading 120 of 300 MB", "Building the plugin cache"), or, when the library cannot measure, the message and the time elapsed; then *Ready*, or the failure's message on that row, with **Prepare** offered again. A failed row does not stop the others: each row is its own preparation. While a row is being prepared, its own **Prepare** is disabled; the section's other rows stay available, so a second item can be started while the first runs. A section is one library's contract, so what it needs is installed, downloaded and tested with it; Save, Revert and Reset stay for the whole config, one file and one draft, since sections can depend on each other (`when`).
- The checks also run by themselves, for each section, each time the form's structure changes (the page loaded, a module switched, an optional object turned on or off, a choice from a list, revert, reset), and each section's output is cleared then: what was shown was about another config. A value typed does not run them; **Check** does.

It returns what the app can listen to:

| Field | What it is |
|---|---|
| `draft` | A `gr.State` holding the config being edited in this browser tab: an input for the app's own events |
| `saved` | A `gr.State` that changes each time the panel saves or resets the config: `setup.saved.change(...)` follows the saved config |

**`secrets_panel(model, config=None)`**, in two parts, names only, values never shown:

- **Keys the config uses**: the variables the config names, each with its source and the fields naming it; a variable the shell sets that the `.env` also sets reads "the shell (the folder's .env also sets it, unused)", with how to use the file's value. Under it, a name and a password field to save one to the folder's `.env`; saving a variable the shell sets says the shell's value is the one used.
- **In the folder's .env**: every variable the file sets, always listed, each with what uses it (the fields of the current config naming it, or none; unused when the shell sets it too) and its own **Remove** button, so a stale key is removed in one click. **Refresh** reads the file again.

Given a `gr.State` (a Setup panel's `draft`), the panel reads the variables from it and follows each change, so the key a newly chosen module needs appears at once; without one, it reads the saved config, on page load and on **Refresh**. The shell itself is not listed: it is read once, when the app starts, and holds much besides keys.

Every browser tab has its own draft of the config; the saved config and the secrets are the model's, shared by all.

## The form

`app_setup.form` turns a section's parsed schema and document into a tree of items, with no gradio:

| Item | From | Drawn as |
|---|---|---|
| `FormGroup` | An object | Its title and description, its items, the advanced ones in a folded **Advanced** block; an optional object gets a **Configure …** switch (off: the key is absent, so the library's defaults apply or the feature is off, as the object's description says), and its items only when on |
| `FormChoice` | A `oneOf` | A dropdown of the modules; the selected module's fields follow the common ones |
| `FormField` | A field | A text box for text and numbers alike (a number read back as one, whole for an integer; its range in its hint, checked by **Check**), a checkbox, a dropdown for an `enum`, JSON text for an array |
| `FormRaw` | A free-form object | JSON text |

- A key written in the config itself (`x-secret`) is never drawn.
- A field's description is its help text. **One rule for defaults:** a field not set shows its default greyed (a text box's placeholder: the box itself is empty; a dropdown's "(default: …)" entry; a checkbox, which must show a state, says "Not set: the default applies" in its hint), and a value in white is one the user set, which is saved. A number is not drawn as a number box because one cannot be empty: it would show the default as a value that looks set.
- **What an edit writes** (`coerce`): an empty widget, or a value equal to the field's default, removes the key, so the config holds only what differs from the library's own defaults. A number with no fraction is written as an integer; a field accepting several kinds takes a number when the text is one and the field accepts it. An invalid value (bad JSON, a fraction for an integer) is refused with a message, and the config is unchanged.
- **Switching module** (`select_branch`) keeps the fields common to every module and drops the old module's own, even those the new module has under the same name (a voice id of one provider means nothing to another).
- **A named list** (`x-options` on a module or a field) gets a button that loads `options` and a dropdown whose choice writes its fields.

A change of structure (a module switched, an optional object turned on or off, a choice from a list, revert, reset) draws the form again; a value edit does not, so typing never loses focus. Choosing the module already selected, or switching an object to the state it is in, draws nothing. The module dropdown listens to `select`, which fires once per choice (`input` fires twice, and each redraw replaces the fields). A text or number field writes on `input` and again on `blur`, so a value typed right after a redraw, before the field's listeners are attached, still reaches the config. Every form component is explicitly interactive: gradio does not infer it for components drawn inside `gr.render`. Each section's problems are not drawn on the fields: **Check** lists them with their pointers.

## Reports

`app_setup.ui.report` writes the model's answers as Markdown: the problems with their pointers, each item row's state, detail and what to do (the wording above), a preparation's progress line, and the secrets table. The rows themselves, with their buttons and progress, are drawn by `app_setup.ui.panels`, inside a `gr.render` per section redrawn on each Check.

## Testing

- `tests/test_form.py`: the tree for each kind of item; every coercion and every refusal; writing, creating and removing; switching module; optional objects; the variables a config names.
- `tests/ui/test_panels.py`: the form drawn into a real gradio page (the selected module's fields, the hidden key, the list button, a section without its library); both panels drawn in an app's own tabs, next to its own components; Save and Reset disabled while the app locks the config; a section's item rows, with a Prepare button on each preparable item not ready; the Secrets panel reading the config it follows, else the saved one.
- `tests/ui/test_report.py`: the wording of every report.

Behaviour in a browser is not covered by the fast tier: gradio's client cannot drive the per-browser draft. `tests-e2e/test_panels_in_browser.py` drives the panels in headless Chromium (Playwright, skipped when absent), inside an app's page where they are not the first tab: switch module, type a required field, save; switch back, pick a voice from the list, save; the saved file is checked each time. Then one item is prepared from its row, its progress shown on that row, and it turns ready while the other stays not prepared. Then the Secrets panel lists the key the unsaved draft names, and Save is disabled while the app's session runs and enabled once it stops. It found that the form's fields were not interactive, and that a value typed right after a module switch was lost.

## Open questions

1. **Problems on the fields themselves**, rather than in the Check report.
2. **Lists of objects as rows** rather than JSON text.
3. **Checking as one types**: today checks run on request, since `check_setup` imports providers.
4. **The button's verb is generic** (**Prepare**): what it does — a download, a cache built — is said by the library's progress message. A verb of the item's own is deferred until a row needs one.
5. **The panels' events are also gradio API endpoints**, saving a key included. Where the page listens is the app's choice: on another address than `127.0.0.1`, they are exposed to that network. Hiding them, or adding authentication, is deferred.
