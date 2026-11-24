# Implementation plans

Implementation plans for app-setup — each plan turns a settled part of a spec (see [specs/_index.md](../specs/_index.md)) into concrete, buildable steps. Plans are ordered by their date-time filename prefix (`YYYYMMDDHHmm_`).

## Plans

<!-- One row per plan, chronological by filename prefix. Keep the Status column in sync with each plan's `**Status:**` line. -->

| Plan | Description | Status |
|---|---|---|
| [202611231640_module-contract.md](202611231640_module-contract.md) | The consuming side of the module contract ([specs/module-contract.md](../specs/module-contract.md)): the `SetupContract` protocol, `parse_description` and its refusals, `check_contract` | Done |
| [202611231640_probe.md](202611231640_probe.md) | `probe`, the contract's seventh function ([specs/module-contract.md](../specs/module-contract.md)): in the `SetupContract` protocol, and its presence checked by `check_contract` | Done |
| [202611231650_extras.md](202611231650_extras.md) | Requirements against the installed environment ([specs/extras.md](../specs/extras.md)): `requirement_status`, `host_extras`, `find_installer` and `Installer` | Done |
| [202611231837_contract-names-and-check-setup.md](202611231837_contract-names-and-check-setup.md) | Explicit names for the contract's functions (`config_schema`, `required_extras`, `check_config`, `check_setup`) and `check_setup` covering extras and keys ([specs/module-contract.md](../specs/module-contract.md)) | Done |
| [202611231915_app-and-page.md](202611231915_app-and-page.md) | The app and its page ([specs/app.md](../specs/app.md), [specs/config-folder.md](../specs/config-folder.md), [specs/secrets.md](../specs/secrets.md), specs/session.md (removed since), [specs/ui.md](../specs/ui.md)): `App`/`AppModel`, the folder, the secrets, the session runner, the form, and the Setup, Secrets and Session tabs behind the `ui` extra | Done |
| [202611240014_panels.md](202611240014_panels.md) | The Setup and Secrets panels an app places in its own page ([specs/ui.md](../specs/ui.md), [specs/app.md](../specs/app.md), [specs/config-folder.md](../specs/config-folder.md)): no page, no `launch`, no session runner; the model locked by the app's session, the folder and secrets made ready when it is built | Done |
| [202611241003_section-fixes.md](202611241003_section-fixes.md) | Fixes found in the first app built on the panels ([specs/app.md](../specs/app.md), [specs/ui.md](../specs/ui.md), [specs/module-contract.md](../specs/module-contract.md)): a section with problems still reports its extras, a module switch drops the old module's fields, the checks run on each redraw, `*` explained, the Secrets panel showing a shadowed `.env` value and the `.env`'s other variables, each section with its own Check, Install, Download and Test | Done |
| [202611241155_ci.md](202611241155_ci.md) | Continuous integration ([specs/ci.md](../specs/ci.md)): lint, format and types, the fast tier on three platforms, the browser tests with a locked Playwright | Done |
| [202611241233_autostart.md](202611241233_autostart.md) | Autostart ([specs/autostart.md](../specs/autostart.md)): `App(autostart=...)`, the choice in `launch.json` apart from the config, the Setup panel's checkbox, `--start` / `--no-start`, `starts_at_launch` | Done |
| [202611241337_form-defaults.md](202611241337_form-defaults.md) | The form's one rule for defaults ([specs/ui.md](../specs/ui.md)): a field not set shows its default greyed, numbers included (drawn as text boxes); a value in white is set and saved | Done |
| [202611241406_base-dir.md](202611241406_base-dir.md) | Relative paths ([specs/module-contract.md](../specs/module-contract.md)): `check_setup`, `prepare`, `options`, `probe` take `base_dir`, app-setup passes the app's folder, `check_contract` checks it | Done |
| [202611241726_rename-app-setup.md](202611241726_rename-app-setup.md) | The rename ([specs/project.md](../specs/project.md) "Name"): `module-setup` / `module_setup` become `app-setup` / `app_setup`, the repository `funwithagents/app-setup`; no change in behaviour | Done |
| [202611241731_items-one-by-one.md](202611241731_items-one-by-one.md) | Items one by one ([specs/module-contract.md](../specs/module-contract.md), [specs/app.md](../specs/app.md), [specs/ui.md](../specs/ui.md)): `required` on every item (a missing one that is not required does not block), `prepare(config, item)` one item per call, run in parallel by app-setup, each with its own progress and outcome, a row per item in the Setup panel with **Prepare** and a progress bar, **Prepare all** | Done |
| [202611241810_draft-and-saved.md](202611241810_draft-and-saved.md) | Draft and saved ([specs/ui.md](../specs/ui.md), [specs/app.md](../specs/app.md), [specs/secrets.md](../specs/secrets.md)): the Setup panel says its actions try the form's draft and a session uses the saved config, shows unsaved changes, Save at the bottom; a section checked again when a field is finished or a key saved (`AppModel.unsaved`, `SecretStore.revision`, `unsaved_notice`) | In progress |
| _(add plans here — see [_plan-template.md](_plan-template.md))_ | | |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
