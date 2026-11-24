# Module contract: the consuming side

**Status:** Done

Implements `specs/module-contract.md` ("What module-setup provides"): the types a contract is read into, the parser that refuses what is outside the spec, and the conformance check libraries run in their tests. It leaves out everything that acts on a contract (the form, the extras, the install), which later specs cover.

## Scope

- `src/module_setup/contract.py` — `SetupContract`, `Description` / `ObjectSpec` / `FieldSpec` / `Choice` / `Branch`, `ContractError`, `parse_description`, `ContractViolation`, `check_contract`
- `tests/test_contract.py` — functional tests over a small hand-written contract
- `pyproject.toml` — the `packaging` runtime dependency
- `AGENTS.md`, `specs/project.md` — the project map row, the dependency note

## Steps

1. The frozen dataclasses a description parses into, and the `SetupContract` protocol.
2. `parse_description`: a strict walk of the schema subset, one keyword list per kind of node (field, object, branch), every refusal a `ContractError` starting with the offender's path. The discriminator is found as the one property that is a `const` in every branch.
3. `check_contract`: parse, stability of `describe`, examples through `validate`, unknown keys against the schema (free-form objects exempt), each module with its defaults written out, `requirements` probed on `{}`, each example and each module alone, extras checked against the distribution's metadata (`extras_of` injectable). Every breach collected, one `ContractViolation`.
4. Tests: the parsed objects for every supported keyword, one case per refusal, a passing contract and one broken contract per rule.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` all pass (39 tests).
