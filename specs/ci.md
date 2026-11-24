---
code:
  - .github/workflows/ci.yml
  - pyproject.toml
  - tests-e2e/support.py
tests:
  - tests-e2e/test_panels_in_browser.py
---

# Continuous integration

**Status:** Implemented

## Purpose

Both test tiers run on GitHub's hosted runners for every pull request and every push to `main`, so the verification gate of [AGENTS.md](../AGENTS.md) — lint, type check, tests — is a machine's verdict on each change and not only a local command. Neither tier needs a credential or the network: the fast tier by design ([testing.md](testing.md)), and the browser tests because they drive the panels against the tests' fake library. Like [testing.md](testing.md) this is a cross-cutting practice, not a runtime concept: nothing here ships in the package.

## Decided

### The jobs

| Job | Runner | What it runs |
|---|---|---|
| `check` | `ubuntu-24.04` | `ruff check .`, `ruff format --check src tests tests-e2e`, `pyright` |
| `fast-tier` | `ubuntu-24.04`, `macos-15`, `windows-2025` | `pytest` (the fast tier) |
| `browser` | `ubuntu-24.04` | `pytest tests-e2e` with Chromium: the panels in a headless browser |

None waits on another, and one platform's failure leaves the others running (`fail-fast: false`).

- **The fast tier on Linux, macOS and Windows.** The package is pure Python, but the folder (`~/.config`, `XDG_CONFIG_HOME`), the `.env` (its permissions), and the installer (finding `uv`, the host's project directory) meet each platform's paths there. A failure on one platform is a bug to fix, not a reason to drop it.
- **The browser on Linux only.** What it drives is gradio's page in Chromium, the same on every platform; the platform-specific code is the fast tier's.
- **Pinned runner images** (`ubuntu-24.04` rather than `ubuntu-latest`), so what the jobs were validated against moves only when a pin is bumped on purpose.
- **One Python, 3.11**, the floor of `requires-python`, set through `astral-sh/setup-uv`'s `python-version`. Local development runs the version `.python-version` names (3.12), so both ends are exercised.
- **On every pull request and every push to `main`**, and by hand (`workflow_dispatch`). A newer run on the same branch cancels the one in progress.

### Dependencies

- **`uv sync --locked`** in every job: the sync fails when `uv.lock` does not match `pyproject.toml`, so a dependency edit lands with its relock or not at all. The `dev` group brings the `ui` extra (gradio), so the panels are type-checked and tested.
- **The `browser` group**: Playwright, locked like everything else and not synced by default, so the dev loop does not carry it. The `check` job syncs it too, since pyright checks `tests-e2e/`, which imports it. `playwright install --with-deps chromium` downloads Chromium and the system libraries it needs on the runner.

### A browser test cannot pass by not running

Locally, the browser tests skip without Playwright or Chromium, like the rest of the opt-in tier. In CI, `APP_SETUP_E2E_REQUIRE_BROWSER=1` turns that skip into a failure (`tests-e2e/support.no_browser`), so a broken browser install shows as red, never as a green run that tested nothing.

### No secret

No job needs one: the libraries the tests drive are fakes, and nothing calls a real service. A fork's pull request runs the same jobs as a branch of the repository.

## Testing

The workflow is its own test: a pull request that breaks lint, types, a test on any platform, or the browser tests shows a red job. `tests-e2e/test_panels_in_browser.py` is what the browser job runs.

## Open questions

1. **Intel macOS, Linux arm64.** Not entries: the package has no native code and no platform branch beyond those the three entries cover. Add one if a bug ever shows there.
