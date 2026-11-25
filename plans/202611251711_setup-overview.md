# Setup overview

**Status:** In progress

Implements [specs/setup-overview.md](../specs/setup-overview.md) (still **Draft**: built to be seen and used before it is approved): the Setup panel read as a summary — the whole config's actions and line on top, one fold per section titled with its modules and status, its form and its checks side by side — and optional sections the user adds or removes. Its "Changes to the other specs" (app.md, ui.md) wait for the spec's approval; so does this plan's `Done`.

## Scope

- `src/app_setup/app.py` — `Section(optional, default)`; a bare app's section cannot be optional; `AppModel.used` leaving an absent optional section out; `optional_off`, `add_section` (with the document removed earlier, else the default), `remove_section`, `summary`, `section_title`; `summary_line`, the whole config's wording (gradio-free, so the model says it too)
- `src/app_setup/form.py` — `selected_modules(schema, document)`
- `src/app_setup/ui/report.py` — `section_line`, `section_status`, `config_summary`
- `src/app_setup/ui/form.py` — `section_title` delegating to the model
- `src/app_setup/ui/panels.py` — the overview (Check all, Install all, Prepare all, Test all, the summary line, an output box), one `gr.Accordion` per section with its form and checks in two columns, Remove and the "off" line with Add; the fold's label and the section's status in every check's outputs
- `tests/test_app.py`, `tests/test_form.py`, `tests/ui/test_report.py`, `tests/ui/test_panels.py`, `tests-e2e/test_panels_in_browser.py` — the spec's Testing section

## Steps

1. The model: `optional` and `default` on `Section`, `used` and the new methods; `summary` built from each used section's problems and blocking and deferred items.
2. The wording: `selected_modules` in the form, `section_line` in the report, the whole config's line shared by the model and the panel.
3. The panel, every component drawn once (no new timer, no new `gr.render`):
   - each section's checks (`reports`) gain two outputs: the fold (its label) and a hidden `status` state (title, needs something, optional items missing);
   - `on_redraw` (on `revision.change`, as before) shows each used section's fold, hides the others, shows an optional section's "off" line while the config leaves it out, and, the first time in a tab (an `unfolded` state), opens the folds of the sections needing something;
   - the whole config's line follows the sections' `status` states (`status.change`, fired only when a check finds something new; `always_last`);
   - Check all, Install all (one uv run), Prepare all, Test all (one line per section) act on every used section; whole-config actions mark every section busy;
   - Add and Remove edit the draft and bump the revision; the documents removed are kept in a per-tab state for Add; neither on a read-only panel.
4. The table in half a fold's width: the action column narrowed (200 px), the text cells shrinking and wrapping, a row's button at its own height.
   The folds and the item lines carry a class (`app-setup-fold`, `app-setup-item`): the fold's two-column row holds the whole table, so the browser tests' `.row` filters matched it, not one line (a flake found this way).
5. Tests, then the existing ones adapted to the checks' two new outputs.

## Verification

`uv run ruff check src tests tests-e2e`, `uv run ruff format src tests tests-e2e`, `uv run pyright`, `uv run pytest`, `uv run pytest tests-e2e -rs` (repeated). Mark this plan `Done` (here and in [_index.md](_index.md)) once the spec is approved and its changes to app.md and ui.md applied.
