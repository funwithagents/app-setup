---
code:
  - pyproject.toml
tests:
  - tests/test_project_map.py
---

# Project

**Status:** Implemented

## Purpose

Structure and tooling for the module-setup project itself: Python version, dependency/packaging management with `uv`, repo layout conventions, and development tooling.

## Decided

- **Python version:** 3.11+ minimum: the lowest version among the libraries that run the conformance check in their tests, since each installs this package as a dev dependency.
- **Package layout:** `src/` layout — `src/module_setup/...` — not flat, to avoid accidentally importing an uninstalled package from the repo root.
- **Dependency/venv management:** `uv`. Dev tooling lives in the `dev` dependency group (`uv sync --dev`), not in runtime `dependencies`.
- **Runtime dependencies:** `packaging` only, to read requirement strings and extra names. The Gradio pieces will sit behind an extra, so that a library using the conformance check in its tests installs no UI.
- **Linting/formatting:** `ruff`.
- **Testing:** `pytest`, in two physically-separated tiers — a fast, deterministic, no-network default run (`tests/`, the only tier `testpaths` collects) and an opt-in live tier (`tests-e2e/`) that calls real external services. Full strategy is specced in [testing.md](testing.md).
- **Type checking:** `pyright` (`standard` mode), a dev dependency run via `uv run pyright`. Config lives in `[tool.pyright]` in `pyproject.toml`, targeting `src`, `tests`, and `tests-e2e`, pinned to the `.venv`.
- **Repo shape:**
  - `src/module_setup/` — the package, one module per core concept.
  - `specs/` — pre-implementation design docs, one per concept (this folder).
  - `plans/` — implementation plans turning settled specs into buildable steps.
  - `tests/` at repo root, mirroring the `src/module_setup/` module structure.
  - `tests-e2e/` at repo root, for the live tier above — not collected by the default `pytest` run.

## Open questions

None currently.
