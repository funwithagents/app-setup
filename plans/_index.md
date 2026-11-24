# Implementation plans

Implementation plans for module-setup — each plan turns a settled part of a spec (see [specs/_index.md](../specs/_index.md)) into concrete, buildable steps. Plans are ordered by their date-time filename prefix (`YYYYMMDDHHmm_`).

## Plans

<!-- One row per plan, chronological by filename prefix. Keep the Status column in sync with each plan's `**Status:**` line. -->

| Plan | Description | Status |
|---|---|---|
| [202611231607_module-contract.md](202611231607_module-contract.md) | The consuming side of the module contract ([specs/module-contract.md](../specs/module-contract.md)): the `SetupContract` protocol, `parse_description` and its refusals, `check_contract` | Done |
| [202611231640_probe.md](202611231640_probe.md) | `probe`, the contract's seventh function ([specs/module-contract.md](../specs/module-contract.md)): in the `SetupContract` protocol, and its presence checked by `check_contract` | Done |
| [202611231800_extras.md](202611231800_extras.md) | Requirements against the installed environment ([specs/extras.md](../specs/extras.md)): `requirement_status`, `host_extras`, `find_installer` and `Installer` | Done |
| [202611231950_contract-names-and-check-setup.md](202611231950_contract-names-and-check-setup.md) | Explicit names for the contract's functions (`config_schema`, `required_extras`, `check_config`, `check_setup`) and `check_setup` covering extras and keys ([specs/module-contract.md](../specs/module-contract.md)) | Done |
| [202611232100_app-and-page.md](202611232100_app-and-page.md) | The app and its page ([specs/app.md](../specs/app.md), [specs/config-folder.md](../specs/config-folder.md), [specs/secrets.md](../specs/secrets.md), specs/session.md (removed since), [specs/ui.md](../specs/ui.md)): `App`/`AppModel`, the folder, the secrets, the session runner, the form, and the Setup, Secrets and Session tabs behind the `ui` extra | Done |
| [202611241000_panels.md](202611241000_panels.md) | The Setup and Secrets panels an app places in its own page ([specs/ui.md](../specs/ui.md), [specs/app.md](../specs/app.md), [specs/config-folder.md](../specs/config-folder.md)): no page, no `launch`, no session runner; the model locked by the app's session, the folder and secrets made ready when it is built | Done |
| [202611241500_section-fixes.md](202611241500_section-fixes.md) | Fixes found in the first app built on the panels ([specs/app.md](../specs/app.md), [specs/ui.md](../specs/ui.md), [specs/module-contract.md](../specs/module-contract.md)): a section with problems still reports its extras, a module switch drops the old module's fields, the checks run on each redraw, `*` explained, the Secrets panel showing a shadowed `.env` value and the `.env`'s other variables, each section with its own Check, Install, Download and Test | Done |
| [202611251000_ci.md](202611251000_ci.md) | Continuous integration ([specs/ci.md](../specs/ci.md)): lint, format and types, the fast tier on three platforms, the browser tests with a locked Playwright | Done |
| [202611251100_autostart.md](202611251100_autostart.md) | Autostart ([specs/autostart.md](../specs/autostart.md)): `App(autostart=...)`, the choice in `launch.json` apart from the config, the Setup panel's checkbox, `--start` / `--no-start`, `starts_at_launch` | Done |
| _(add plans here — see [_plan-template.md](_plan-template.md))_ | | |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
