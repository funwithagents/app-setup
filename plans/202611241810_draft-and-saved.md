# Draft and saved: say which config each button uses, and check again after a fix

**Status:** Done

Implements the updated [specs/ui.md](../specs/ui.md) ("The panels", "Using the panels"), [specs/app.md](../specs/app.md) (`unsaved`) and [specs/secrets.md](../specs/secrets.md) (`revision`): the Setup panel says that its sections' actions try the form's draft while a session uses the saved config, shows when the two differ, puts Save at the bottom, and runs a section's checks again when a field is finished or a key is saved. It leaves the form itself (what an edit writes, when it redraws) as it is.

## Scope

- `src/app_setup/app.py` — `AppModel.unsaved(draft)`: the whole draft against `saved_config()`
- `src/app_setup/secrets.py` — `SecretStore.revision`, bumped by each `set` and `remove`
- `src/app_setup/ui/form.py` — `render_section(..., edited=None)`: a field finished (text box `blur` / `submit`, JSON box `blur`, checkbox and value dropdown `input`) writes the draft and bumps the section's `edited` state; `input` still writes on each keystroke without bumping
- `src/app_setup/ui/panels.py` — the new order (autostart, Configuration title and its line, the legend, the top unsaved line, the sections, the bottom unsaved line, Save / Revert / Reset, the lock line, the notice); a per-section `edited` state whose change runs that section's checks; the unsaved lines on `draft.change`, Save, Revert, Reset and the 1 s timer; the timer re-running the checks of the sections in use when `SecretStore.revision` changed since this tab last saw it (a per-tab `gr.State`); `unsaved_notice(model, draft)`
- `src/app_setup/ui/__init__.py` — export `unsaved_notice`
- `README.md` — the example shows `unsaved_notice` on the app's session tab
- `tests/test_app.py`, `tests/test_secrets.py`, `tests/ui/test_panels.py`, `tests-e2e/test_panels_in_browser.py` — as listed in each spec's Testing

## Steps

1. `AppModel.unsaved` and `SecretStore.revision`, with their tests.
2. The form: an `edited` state per section, bumped by the "finished" events; the `input` + `blur` guarantee kept (both write the value).
3. The panel: reorder; the unsaved lines and their updates; `edited.change` → the section's reports; the timer's secrets check; `unsaved_notice`.
4. Panel tests: the order, the unsaved lines, a field left re-checking its section, the timer re-checking after a key was saved and not otherwise.
5. Browser tests: "Unsaved changes" shown then gone after Save; a key saved in the Keys tab turning its row ready on Setup without Check; the lock line still updating.
6. Specs back to `Implemented` (files and index), this plan `Done`.

## Verification

`uv run ruff check .`, `uv run ruff format --check src tests tests-e2e`, `uv run pyright` (after `uv sync --all-groups`), `uv run pytest`, `uv run pytest tests-e2e -rs` twice with Chromium installed.
