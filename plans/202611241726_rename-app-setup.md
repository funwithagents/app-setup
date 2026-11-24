# Rename to app-setup

**Status:** Done

Implements the name decided in `specs/project.md` ("Name"): the distribution `module-setup` becomes `app-setup`, the import `module_setup` becomes `app_setup`, with no change in behaviour. The plans written before the rename keep the old name: they record what was built then.

## Scope

- `src/module_setup/` → `src/app_setup/` — the package moved, its imports and messages renamed
- `pyproject.toml`, `uv.lock` — the distribution name, the self-reference of the `ui` extra
- `tests/`, `tests-e2e/` — the imports, the project-map paths, `APP_SETUP_E2E_REQUIRE_BROWSER`
- `.github/workflows/ci.yml` — the browser job's variable
- `README.md`, `AGENTS.md`, `specs/`, the plan template and index — the name and the paths

## Steps

1. Rename the GitHub repository to `funwithagents/app-setup` (the old URL redirects).
2. `git mv src/module_setup src/app_setup`; replace `module-setup`, `module_setup` and `MODULE_SETUP` everywhere but the earlier plans; relock.
3. Record the name and why in `specs/project.md`.

## Verification

`uv run ruff check .`, `uv run ruff format --check src tests tests-e2e`, `uv run pyright`, `uv run pytest`; no `module-setup` / `module_setup` left outside the earlier plans.
