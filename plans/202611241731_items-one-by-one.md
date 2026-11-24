# Items one by one: required or not, prepared one at a time, with progress

**Status:** Todo

Implements the updated [specs/module-contract.md](../specs/module-contract.md) (`check_setup`'s `required`, `prepare`'s `items` and progress), [specs/app.md](../specs/app.md) (`prepare` by item, `to_prepare`, `deferred`, the blockers) and [specs/ui.md](../specs/ui.md) (a row per item, **Prepare** / **Prepare all**, progress per row). No compatibility with the previous shape: no library implementing the contract has been merged yet.

## Scope

- `src/app_setup/contract.py` — `SetupContract.prepare(config, *, items, on_progress, base_dir)`; `check_contract` checks the keywords
- `src/app_setup/app.py` — `SetupItem.required`, the item's shape checked (`ContractError`), `prepare(config, items, on_progress)` one item at a time with `section` in each event, `to_prepare`, `deferred`, `blockers` on required items only
- `src/app_setup/ui/panels.py` — a `gr.render` per section drawing its item rows (state, detail, **Prepare**, a progress bar); **Prepare all**; the section's buttons disabled while one of its actions runs
- `src/app_setup/ui/report.py` — the row wording, the progress line
- `tests/fakes.py` — the fake library: `required`, `prepare(items=…)`, fractions reported, an item that fails
- `tests/test_contract.py`, `tests/test_app.py`, `tests/ui/test_panels.py`, `tests/ui/test_report.py`, `tests-e2e/test_panels_in_browser.py` — as listed in each spec's Testing
- `README.md` — the example and the Start sequence, if they name `prepare`

## Steps

1. Contract: the `prepare` signature in `SetupContract`; `check_contract` refuses a `prepare` without `items` or `on_progress` keywords.
2. Model: parse `required` into `SetupItem`, refusing a missing key or `required: false` with `preparable: false`; `blockers` counts missing required items; add `to_prepare` and `deferred`; `prepare` takes items, calls each section's contract with `items=[id]` in order, adds `section` to each event, raises at the first failure.
3. Fake library and model tests.
4. Report wording: *Ready*, *Missing* with what to do, *Not prepared yet* with "The first start will prepare it itself and be slower", *Unknown*; a progress line (bar, share, message; or message and elapsed time).
5. Panel: the item rows inside a per-section `gr.render` fed by a state holding the last check and each item's live progress; **Prepare** on a row streams that item's events into its row; **Prepare all** walks `to_prepare` the same way; buttons disabled while an action of the section runs; Check redraws the rows. The old **Download missing files** button and its output-box stream go.
6. Panel tests, then the browser test: one item prepared from its row, its progress seen, it turns ready, the other stays not prepared.
7. Specs back to `Implemented` (files and index), this plan `Done`.

## Verification

`uv run ruff check .`, `uv run ruff format --check src tests tests-e2e`, `uv run pyright` (with the browser group), `uv run pytest`, `uv run pytest tests-e2e -rs` with Chromium installed.
