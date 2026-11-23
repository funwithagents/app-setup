# Implementation plans

Implementation plans for module-setup — each plan turns a settled part of a spec (see [specs/_index.md](../specs/_index.md)) into concrete, buildable steps. Plans are ordered by their date-time filename prefix (`YYYYMMDDHHmm_`).

## Plans

<!-- One row per plan, chronological by filename prefix. Keep the Status column in sync with each plan's `**Status:**` line. -->

| Plan | Description | Status |
|---|---|---|
| [202611231607_module-contract.md](202611231607_module-contract.md) | The consuming side of the module contract ([specs/module-contract.md](../specs/module-contract.md)): the `SetupContract` protocol, `parse_description` and its refusals, `check_contract` | Done |
| [202611231640_probe.md](202611231640_probe.md) | `probe`, the contract's seventh function ([specs/module-contract.md](../specs/module-contract.md)): in the `SetupContract` protocol, and its presence checked by `check_contract` | Done |
| _(add plans here — see [_plan-template.md](_plan-template.md))_ | | |

## Status legend

- **Todo** — written, not yet started
- **In progress** — actively being implemented
- **Done** — implemented, verified (lint/type-check/tests pass), and merged
