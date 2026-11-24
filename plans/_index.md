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
| _(add plans here — see [_plan-template.md](_plan-template.md))_ | | |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
