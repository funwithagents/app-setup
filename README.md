# module-setup

The Setup side of an app built from configurable libraries: choose a module, edit its config in a form, install the extra it needs, prepare what it needs on the machine, then start a session — without editing JSON by hand or restarting the app.

**Status:** early, every spec implemented: the module contract, the extras, and the page (an app's folder, secrets, sessions, and the Setup, Secrets and Session tabs, behind the `ui` extra). Start at [specs/_overview.md](specs/_overview.md), then [specs/module-contract.md](specs/module-contract.md).

## Using it in an app

```python
from module_setup.app import App, Section
from module_setup.ui import launch

import speech_lib.setup  # a library implementing the contract

launch(
    App(
        name="speech-demo",
        host="speech-lib",
        sections=(Section("speech", speech_lib.setup),),
        default_config={"speech": {"module": {"type": "local-voice"}}},
        start=start_session,      # SessionContext -> an object with stop()
        session_ui=session_tab,   # draws the Session tab's content (gradio)
    )
)
```

Install with the `ui` extra for the page; the base install (the contract, the conformance check, the extras) needs no gradio.

Developed spec-first: [AGENTS.md](AGENTS.md) is the operating manual, [specs/_index.md](specs/_index.md) lists the designs and their status, [plans/_index.md](plans/_index.md) the implementation plans.
