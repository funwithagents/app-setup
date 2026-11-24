# module-setup

The Setup side of an app built from configurable libraries: choose a module, edit its config in a form, install the extra it needs, prepare what it needs on the machine, set its keys, then run it — without editing JSON by hand or restarting the app.

**Status:** early, every spec implemented: the module contract, the extras, and the panels (an app's folder and secrets, and the Setup and Secrets panels, behind the `ui` extra). Start at [specs/_overview.md](specs/_overview.md), then [specs/module-contract.md](specs/module-contract.md).

## Using it in an app

```python
import gradio as gr

from module_setup.app import App, AppModel, Section
from module_setup.folder import ConfigFolder, default_folder
from module_setup.ui import secrets_panel, setup_panel

import speech_lib.setup  # a library implementing the contract

APP = App(
    name="speech-demo",
    host="speech-lib",
    sections=(Section("speech", speech_lib.setup),),
    default_config={"speech": {"module": {"type": "local-voice"}}},
)
# The folder made ready and its .env loaded; the config locked while a session runs.
model = AppModel(APP, ConfigFolder(default_folder(APP.name), APP.default_config), locked=is_running)

with gr.Blocks() as page:
    with gr.Tab("Session"):
        ...  # the app's own: Start (model.saved_config(), model.blockers(...)), Stop, its controls
    with gr.Tab("Setup"):
        setup = setup_panel(model)
    with gr.Tab("Secrets"):
        secrets_panel(model, setup.draft)

page.launch()
```

Install with the `ui` extra for the panels; the base install (the contract, the conformance check, the extras, the model) needs no gradio.

Developed spec-first: [AGENTS.md](AGENTS.md) is the operating manual, [specs/_index.md](specs/_index.md) lists the designs and their status, [plans/_index.md](plans/_index.md) the implementation plans.
