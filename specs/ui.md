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

**Status:** Implemented

## Purpose

Two panels an app draws in its own page: a **Setup** panel to edit, check and install, and a **Secrets** panel for keys. The app decides which it shows and where (a tab, a column, an accordion), and builds the rest of its page itself, its session first of all: starting, using and stopping the runtime differ from one app to the next. The panels are drawn with gradio, behind the `ui` extra; everything they decide comes from the gradio-free model ([app.md](app.md)), so a library that only needs the contract's conformance check never installs gradio.

## Using the panels

```python
import gradio as gr

from app_setup.app import AppModel
from app_setup.folder import ConfigFolder, default_folder
from app_setup.ui import secrets_panel, setup_panel, unsaved_notice

model = AppModel(APP, ConfigFolder(default_folder(APP.name), APP.default_config), locked=session.running)

with gr.Blocks() as page:
    with gr.Tab("Session"):
        notice = gr.Markdown()                # "The Setup tab has unsaved changes: …"
        ...                                   # the app's own: Start, Stop, its controls
    with gr.Tab("Setup"):
        setup = setup_panel(model)
    with gr.Tab("Secrets"):
        secrets_panel(model, setup.draft)

    setup.draft.change(lambda draft: unsaved_notice(model, draft), inputs=[setup.draft], outputs=[notice])
    setup.saved.change(lambda draft: unsaved_notice(model, draft), inputs=[setup.draft], outputs=[notice])

page.launch()
```

Each panel is a function drawing its components where it is called, inside the app's `gr.Blocks`. It brings its own state, its own events and its own page-load step (a `gr.on` with no trigger), so either can be used alone, and nothing has to be wired between them except what the app chooses.

**`unsaved_notice(model, draft) -> str`** is for the app's own session view: "The Setup tab has unsaved changes: Start uses the saved config." while the draft differs from the saved config (`AppModel.unsaved`), else "" (an empty draft, the panel not loaded yet, included). Given `setup.draft` as input, on its `change` and the panel's `saved.change`, it tells a user about to press Start that the edits they see are not what will run.

Serving the page, the command line, when to start a session (a setting of the app's to start one at launch, for instance) and stopping it at exit are the app's.

## The panels

**`setup_panel(model) -> SetupPanel`**

**Draft and saved.** The form edits a draft of the config, one per browser tab. Every action of a section — Check, Install, Install all, Prepare, Prepare all, Test, a key saved from its line — acts on the draft, saved or not; a session (the app's Start) uses the saved config only. The secrets (the Secrets panel) and the launch choice (the checkbox below) are saved at once. The panel says so, and says whenever the draft differs from the saved config, so a user never tests an edit, sees it work, and starts the old config.

From top to bottom:

- For an app with autostart, **first** a **"Start the session when the app launches"** checkbox, loaded from the folder's `launch.json` and saved at once, enabled while a session runs ([autostart.md](autostart.md)): the launch choice is not part of the config, and Save, Revert and Reset do not touch it.
- A **Configuration** title, always, with the line "Check, Install, Prepare and Test try the config as it is in the form. Save it for a session to use it.", then a line saying that a field marked `*` must be filled in (the schema's `required`) and the others have a default or can stay empty, and that a value in grey is a default: not set, not saved.
- **"Unsaved changes — Save is at the bottom."** while this tab's draft differs from the saved config (`AppModel.unsaved`), else nothing.
- **One block per section**, in the app's order, shown while the config uses it (`when`): its title (the app's `Section(title=…)`, else its library's, never its key), its form, then **its own checks**, acting on that section alone: **Check** shows its problems, a summary line and **a table of what the machine needs for it** (below); **Install all** installs every host extra that carries what it misses in **one** uv run (faster than one per extra), streaming uv's output; **Prepare all** prepares every item not ready yet, all at the same time, each on its own line; **Test** runs its `probe`. The output box appears with the first action that writes to it (Install all, Test). All four act on the form's current values, saved or not. While Check, Install all or Test runs, the section's other buttons are disabled, the table's included; preparations run alongside each other (below).
- **The table**: columns **Item | Status | Explanation | Action**, a header line, then one line per `check_setup` item (extras, keys, files alike), each a row of fixed-width columns (gradio's table component cannot hold a button per line). The status is one of three, short; the explanation carries the why:

  | Status | When | Explanation |
  |---|---|---|
  | ✅ **Ready** | `ready` | the library's detail ("Installed.", "Set.", "Downloaded.") |
  | ❌ **Missing – required** | `missing`, required | the detail, then what to do: the line's **Install** (naming the host extra), its key field, its **Prepare**; or the file to provide |
  | 🟡 **Missing – optional** | `missing`, not required | the detail, then "Without it, the first start gets it itself and is slower." |
  | ❔ **Can't tell** | `unknown` | the detail; never blocking |

  While or after a line's action, until the next check: ⏳ **Installing…** (uv's latest output line, marked `uv:` — its "Downloading numpy" or "Prepared 3 packages" would otherwise read as another action — and the time elapsed: uv gives no share done), ⏳ **Waiting** (an install queued behind another: "Waiting for another install…"), ⏳ **Preparing… 40%** (a bar and the library's message, which says what is happening: "Downloading 120 of 300 MB"; or, when the library cannot measure, ⏳ **Preparing…** with the message and the time elapsed), ✅ **Ready** once done, ❌ **Failed** with the error, the line's button offered again. The summary line over the table says it in the same words: "❌ 1 required item missing", "✅ Ready to run — 2 optional items missing: the first start will get them, slower", "✅ Ready".
- **A line's action**:
  - **An extra**, missing and carried by a host extra: **Install**, installing that host extra. Installs run **one at a time** (uv works on one environment): a line's Install starts at once when no install runs, else waits its turn; **Install all** waits in the same queue. After a successful install the sections' libraries are retried (`AppModel.install`) and the section checked again; a failed one stays on its line with its error. An extra no host extra carries, or unavailable on this platform: no button, the explanation says so.
  - **A key** (the item about a variable the config names, `SetupItem.variable`, [app.md](app.md)), missing: a password field and **Save**, writing to the folder's `.env` through the same `SecretStore` as the Secrets panel (the shell wins, as there); then the section is checked again, here and, through `SecretStore.revision`, in every tab. The value is never shown. The Secrets panel keeps the full picture: sources, the `.env`'s other variables, Remove.
  - **A preparable item** not ready: **Prepare**. Preparations run in parallel, each on its own line: a failed line does not stop the others; while a line is prepared its own **Prepare** is disabled, the other lines stay available.
  - **Ready, unknown, a local file to provide**: no button; the explanation says what to do.

  A section is one library's contract, so what it needs is installed, downloaded and tested with it; Save, Revert and Reset stay for the whole config, one file and one draft, since sections can depend on each other (`when`).
- At the bottom, for the whole config: **"Unsaved changes."** while the draft differs from the saved config, then **Save**, **Revert to saved**, **Reset to defaults**, then the line saying a session is running and the line saying what the last button did. A config with problems is saved all the same (nothing is lost), and Save says so: "⚠️ Saved, with 2 problems in the config: a session cannot start with it until they are fixed." Save and Reset are disabled, with that line, while the model is locked (`AppModel.locked`, polled every second). The config is saved last, after the sections it is tried in, so the buttons that try it come before the one that keeps it.
- **The unsaved lines** are compared again (draft against the saved file, which is cheap) on each change of the draft, value edits included (the form writes a value on `input`), after Save, Revert and Reset, and every second (another tab may have saved).
- **The checks run again by themselves** — the section's problems, its summary and its item rows, as if **Check** were clicked:
  - for each section, each time the form's structure changes (the page loaded, a module switched, an optional object turned on or off, a choice from a list, revert, reset), and each section's output is cleared then: what was shown was about another config;
  - for one section, when the user finishes editing one of its fields: a text box left (`blur`) or Enter pressed in it (`submit`), a JSON box left, a checkbox ticked, a choice made in a list of values. Not on each keystroke: a check may import a provider;
  - for every section the config uses, in every browser tab, when a key was saved or removed (`SecretStore.revision` changed, [secrets.md](secrets.md)), the Secrets panel's or any other write: the panel's one-second timer notices the change (each tab keeps the last revision it saw) and checks again then, and only then.

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
| `FormGroup` | An object | Its title and description, its items, the advanced ones in a folded **Advanced** block; an optional object gets a **Configure …** switch (off: the key is absent, so the library's defaults apply or the feature is off, as the object's description says), and its items only when on; one carrying a module choice starts, switched on, on its first module, so its dropdown and fields show one rather than nothing |
| `FormChoice` | A `oneOf` | A dropdown of the modules; the selected module's fields follow the common ones |
| `FormField` | A field | A text box for text and numbers alike (a number read back as one, whole for an integer; its range in its hint, checked by **Check**), a checkbox, a dropdown for an `enum`, JSON text for an array |
| `FormRaw` | A free-form object | JSON text |

- A key written in the config itself (`x-secret`) is never drawn.
- A field's description is its help text. **One rule for defaults:** a field not set shows its default greyed (a text box's placeholder: the box itself is empty; a dropdown's "(default: …)" entry; a checkbox, which must show a state, says "Not set: the default applies" in its hint), and a value in white is one the user set, which is saved. A number is not drawn as a number box because one cannot be empty: it would show the default as a value that looks set.
- **What an edit writes** (`coerce`): an empty widget, or a value equal to the field's default, removes the key, so the config holds only what differs from the library's own defaults. A number with no fraction is written as an integer; a field accepting several kinds takes a number when the text is one and the field accepts it. An invalid value (bad JSON, a fraction for an integer) is refused with a message, and the config is unchanged.
- **Switching module** (`select_branch`) keeps the fields common to every module and drops the old module's own, even those the new module has under the same name (a voice id of one provider means nothing to another).
- **A named list** (`x-options` on a module or a field) gets a button that loads `options` and a dropdown whose choice writes its fields.

A change of structure (a module switched, an optional object turned on or off, a choice from a list, revert, reset) draws the form again; a value edit does not, so typing never loses focus. A field finished (left, Enter, a box ticked, a value chosen) also bumps its section's `edited` state, which runs that section's checks again. Choosing the module already selected, or switching an object to the state it is in, draws nothing. The module dropdown listens to `select`, which fires once per choice (`input` fires twice, and each redraw replaces the fields). A text or number field writes on `input` and again on `blur`, so a value typed right after a redraw, before the field's listeners are attached, still reaches the config. Every form component is explicitly interactive: gradio does not infer it for components drawn inside `gr.render`. Each section's problems are not drawn on the fields: **Check** lists them with their pointers.

## Reports

`app_setup.ui.report` writes the model's answers as Markdown: the problems with their pointers, the summary line, each table line's status and explanation (the wording above, the transient states included), and the secrets table. The table itself, with its buttons, key fields and progress, is drawn by `app_setup.ui.panels`, inside a `gr.render` per section, drawn again only when a check finds other **lines** than the last one — other items, or an item offering another action — so a check finding the same lines, worded otherwise (the library's words replacing app-setup's once a section can be asked about), leaves the table, a line being clicked and a key being typed as they are; the rows' timer, every half second, then shows each line's latest status, wording and progress. The panels' `gr.render`s run one at a time, all of them together (one concurrency group, limit one): gradio numbers a page's listeners from a counter two renders running at once can read alike (the form and the table on page load), and two runs of one render unregister each other's listeners (a Check and the timer's re-check); either way a button drawn then calls a function the server no longer knows (found by the browser tests, under load).

## Testing

- `tests/test_form.py`: the tree for each kind of item; every coercion and every refusal; writing, creating and removing; switching module; optional objects; the variables a config names.
- `tests/ui/test_panels.py`: the form drawn into a real gradio page (the selected module's fields, the hidden key, the list button, a section without its library); both panels drawn in an app's own tabs, next to its own components; the panel's order (the Configuration line, the sections, then Save at the bottom); Save and Reset disabled while the app locks the config; the unsaved lines for a draft equal to the saved config and one differing, and `unsaved_notice`; a field left re-running its section's checks; the timer re-running the checks after a key was saved, and not otherwise; a section's table: its header and one line per item with the right action (Install for an installable extra, a key field and Save for a missing key, Prepare for a preparable item not ready, none otherwise); two installs queued, the second waiting then running; Install all in one run; a key saved from its line reaching the store and the line turning ready; the Secrets panel reading the config it follows, else the saved one.
- `tests/ui/test_report.py`: the wording of every report: each status and its explanation, the transient states, the summary.

Behaviour in a browser is not covered by the fast tier: gradio's client cannot drive the per-browser draft. `tests-e2e/test_panels_in_browser.py` drives the panels in headless Chromium (Playwright, skipped when absent), inside an app's page where they are not the first tab: switch module, type a required field, save; switch back, pick a voice from the list, save; the saved file is checked each time. Then one item is prepared from its row, its progress shown on that row, and it turns ready while the other stays not prepared. Then the Secrets panel lists the key the unsaved draft names, and Save is disabled while the app's session runs and enabled once it stops. A value typed shows "Unsaved changes", which Save takes away; a key saved in the Secrets panel turns its line ready on the Setup panel without a click on Check. An extra is installed from its line (the installer faked), its line showing Installing… then Ready; a key is saved from its line, which turns ready. It found that the form's fields were not interactive, and that a value typed right after a module switch was lost.

## Open questions

1. **Problems on the fields themselves**, rather than in the Check report.
2. **Lists of objects as rows** rather than JSON text.
3. **Checking as one types**: checks run when a field is finished, not on each keystroke, since `check_setup` imports providers.
4. **A jump from a key's line to the Secrets panel** (`setup_panel(model, secrets_tab=…)`) is deferred: the line's own field is enough to set a key.
5. **The button's verb is generic** (**Prepare**): what it does — a download, a cache built — is said by the library's progress message. A verb of the item's own is deferred until a row needs one.
6. **The panels' events are also gradio API endpoints**, saving a key included. Where the page listens is the app's choice: on another address than `127.0.0.1`, they are exposed to that network. Hiding them, or adding authentication, is deferred.
