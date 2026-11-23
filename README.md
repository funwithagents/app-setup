# module-setup

The Setup side of an app built from configurable libraries: choose a module, edit its config in a form, install the extra it needs, prepare what it needs on the machine, then start a session — without editing JSON by hand or restarting the app.

**Status:** early. The module contract is specified and its consuming side is implemented (the description parser, the conformance check); the extras, the config folder, the secrets, the session and the UI are still to come. Start at [specs/_overview.md](specs/_overview.md), then [specs/module-contract.md](specs/module-contract.md).

Developed spec-first: [AGENTS.md](AGENTS.md) is the operating manual, [specs/_index.md](specs/_index.md) lists the designs and their status, [plans/_index.md](plans/_index.md) the implementation plans.
