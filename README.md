# app-setup

The Setup side of an app built from configurable libraries: choose a module, edit its config in a form, install the extra it needs, prepare what it needs on the machine, set its keys, then run it — without editing JSON by hand or restarting the app.

**Status:** early, every spec implemented: the module contract, the extras, and the panels (an app's folder or config file and its secrets, and the Setup and Secrets panels, behind the `ui` extra). Start at [specs/_overview.md](specs/_overview.md), then [specs/module-contract.md](specs/module-contract.md).

## Using it in an app

```python
import argparse

import gradio as gr

from app_setup.app import App, AppModel, Section
from app_setup.autostart import add_start_arguments, starts_at_launch
from app_setup.config_file import ConfigFileError
from app_setup.launch import add_config_arguments, open_source
from app_setup.ui import secrets_panel, setup_panel, unsaved_notice

import speech_lib.setup  # a library implementing the contract

APP = App(
    name="speech-demo",
    host="speech-lib",
    sections=(Section("speech", speech_lib.setup),),
    default_config={"speech": {"module": {"type": "local-voice"}}},
    autostart=True,  # the app starts its session at launch, unless the user says otherwise
)
parser = argparse.ArgumentParser()
add_config_arguments(parser, APP)  # --folder DIR (the default folder) | --config FILE; --env PATH
add_start_arguments(parser)  # --start / --no-start, for this launch only
options = parser.parse_args()
try:
    source = open_source(options, APP)  # a ConfigFolder, or a ConfigFile run as it is
except ConfigFileError as exc:
    parser.error(str(exc))

# The source made ready and its .env loaded; the config locked while a session runs.
model = AppModel(APP, source, locked=is_running)

with gr.Blocks() as page:
    with gr.Tab("Session"):
        unsaved = gr.Markdown()  # "The Setup tab has unsaved changes: Start uses the saved config."
        ...  # the app's own: Start (model.saved_config(), model.blockers(...)), Stop, its controls
    with gr.Tab("Setup"):
        setup = setup_panel(model)
    with gr.Tab("Secrets"):
        secrets_panel(model, setup.draft)

    # The Setup panel's buttons try the form as it is; a session runs the saved config.
    for event in (setup.draft.change, setup.saved.change):
        event(lambda draft: unsaved_notice(model, draft), inputs=[setup.draft], outputs=[unsaved])

# The flag; from a file, yes; else the folder's launch.json (a checkbox on the Setup panel),
# else App.autostart.
if starts_at_launch(model, options.start):
    start()  # the app's own Start: shows the blockers instead when the saved config has some

page.launch()
```

An app runs from its folder, edited and saved by the Setup panel, or from a config file given with `--config`, run as it is: the Setup panel is then read-only and the session starts at launch. The keys come from the `.env` next to the config, unless `--env` names another. A one-section app (a library's demo) declares `App(..., bare=True)`: its config is the library's own document, with no key around it. A **config app** edits one file with the same panels and no session: `config_page(open_config_app(options, APP))` ([specs/config-file.md](specs/config-file.md)).

An app that starts its session at launch says so (`App(autostart=True)`); the user's choice is kept in the folder's `launch.json`, apart from the config, and `--start` / `--no-start` override it for one launch ([specs/autostart.md](specs/autostart.md)).

Install with the `ui` extra for the panels; the base install (the contract, the conformance check, the extras, the model) needs no gradio.

Developed spec-first: [AGENTS.md](AGENTS.md) is the operating manual, [specs/_index.md](specs/_index.md) lists the designs and their status, [plans/_index.md](plans/_index.md) the implementation plans.
