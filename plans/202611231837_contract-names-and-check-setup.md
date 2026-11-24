# Contract: explicit names, `check_setup` covers extras and keys

**Status:** Done

Implements the changes to `specs/module-contract.md` decided after the first library implemented it: the seven functions get names that say what they look at, and `check_setup` (was `check`) reports everything the machine is missing, extras and keys included, instead of assuming the extras are installed.

## Scope

- `specs/module-contract.md`, `specs/_overview.md`, `specs/_index.md`, `specs/extras.md` — the names, the order of use, `check_setup`'s three kinds of item
- `src/module_setup/contract.py` — `SetupContract` and `check_contract` with the new names
- `tests/test_contract.py` — the reference contract and the test names

## Steps

1. Rename: `describe` → `config_schema`, `requirements` → `required_extras`, `validate` → `check_config`, `check` → `check_setup`; `prepare`, `options`, `probe` unchanged.
2. `check_setup` works on the base install and returns extras (found by trying the imports), keys (the environment variables `x-secret-env` fields name), then files; it may read environment variables.
3. The Setup sequence in the overview follows: `check_config`, `check_setup`, the user installs and sets keys, `prepare`, `check_setup` again.

## Verification

`uv run ruff check .`, `uv run ruff format .`, `uv run pyright`, `uv run pytest` all pass (63 tests).
