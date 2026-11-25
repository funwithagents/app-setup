---
code:
  - src/app_setup/app.py
  - src/app_setup/ui/panels.py
  - src/app_setup/ui/report.py
tests:
  - tests/test_app.py
  - tests/ui/test_panels.py
  - tests/ui/test_report.py
  - tests-e2e/test_panels_in_browser.py
---

# Setup overview and optional sections

**Status:** Draft

## Purpose

An app composing several libraries has several sections, and the Setup panel drew each one in full, one under the other, across the whole width: its form, its table, its buttons. With five or six sections the panel became too long to read, the module chosen in one section was hard to compare with another's, and there was no way to leave a feature out.

This spec makes the panel read like a summary first: **one line per section**, each section **folded** until it is opened, its form and its table **side by side** once open, **actions for the whole config** next to each section's own, and **optional sections** the user adds or removes.

## The panel, from top to bottom

```
Setup                                              [Check all] [Install all] [Prepare all] [Test all]
❌ 1 section needs something: Voice.
▸ Agent — Anthropic · ✅ Ready
▸ Speech recognition — mlx-audio · 🟡 1 optional item missing
▾ Voice — Phonon (local) · ❌ 1 required item missing
    ┌ form ───────────────────────────┐ ┌ items ──────────────────────────────────────┐
    │ Module  [Phonon (local) ▾]      │ │ Item         Status        Explanation  Action │
    │ Voice   [Juniper        ▾]      │ │ Phonon model ❌ Missing     …         [Prepare] │
    │ ▸ Advanced                      │ │ [Check] [Install all] [Prepare all] [Test]   │
    └─────────────────────────────────┘ └─────────────────────────────────────────────┘
    [Remove Voice]                                        (optional sections only)
Microphone processing — off                                                        [Add]
Hand signs — off                                                                   [Add]
                                                         Unsaved changes. [Save] [Revert] [Reset]
```

- **What stays as it is:** the launch checkbox, the "Configuration" title and its lines, the unsaved lines, Save, Revert and Reset at the bottom, the read-only panel of an app running a file ([config-file.md](config-file.md)), the items table and its actions ([ui.md](ui.md)).
- **The whole config's actions, on top:** **Check all**, **Install all**, **Prepare all**, **Test all**, and a summary line under them. They act on every section the config uses, as each section's own buttons act on one:
  - **Check all** checks every section again (its problems, its table, its fold's line).
  - **Install all** installs every host extra any section misses, in **one** uv run, its output in an output box under the summary.
  - **Prepare all** prepares every preparable item not ready, in every section, at the same time, each on its own line.
  - **Test all** runs each section's `probe`, one after the other, and writes one line per section in the output box: `✅ Voice: …` / `❌ Agent: …`.
  - The summary says the whole in one line, in the table's words: "✅ Ready to run", "✅ Ready to run — 2 optional items missing: the first start will get them, slower", "❌ 2 sections need something: Voice, Agent.". It follows every check, a section's own included.
- **One fold per section used** (a `gr.Accordion`), in the app's order. Its title line is the section's summary: `<title> — <modules> · <status>`.
  - `<modules>` is the title of the module selected in each module choice of the section, in the form's order, joined by ` · ` (`Phonon (local)`, `Deepgram v2 (hosted) · Silero VAD`); a section with no module choice has none (`Camera · ✅ Ready`).
  - `<status>` is the section's summary in the table's words, short: `✅ Ready`, `🟡 2 optional items missing`, `❌ 1 required item missing`, `❌ 2 problems in the config`. A section whose library does not import reads `❌ not installed`.
  - It is updated by every check of the section, and by each change of the form's structure (a module switched).
  - **Folded or open:** when the page loads, a section that needs something (a problem, a required item missing) is open, the others folded. Afterwards the user opens and closes them; a check never folds or opens one.
- **Inside an open fold, two columns** side by side, each half the width: the **form** on the left; on the right, the section's summary, its problems, its **items table** and its own **Check**, **Install all**, **Prepare all**, **Test**, then its output box. On a narrow window the columns stack, form first.
- **An optional section** (below) that the config uses has a **Remove <title>** button under its two columns. One the config does not use is a single line, `<title> — off`, with an **Add** button, in the app's order among the others.

## Optional sections

An app declares which of its sections the user may leave out:

```python
Section("asr", speech_lib.setup, title="Speech recognition", optional=True, default={...})
```

- **`optional`**: the section may be absent from the config. **Absent means off**: the section is not used (`AppModel.used` leaves it out), not checked, not counted by Start's blockers, and the app does not run it. Present (any document, `{}` included) means on.
- **`default`**: the document **Add** writes into the draft, the library's starting point (`{}` when not given). An optional section the app wants on at first launch is simply in `App.default_config`.
- **Add** writes the section's document into the draft (the one removed earlier in this browser tab, if any, else `default`) and opens its fold; **Remove** takes it out of the draft and keeps it in the tab, so adding it back before saving loses nothing. Both are draft edits: the unsaved lines show, and Save keeps them. Neither is offered on a read-only panel.
- **`when`** still says whether a section applies at all (one embodiment's section, say): a section `when` excludes is neither drawn nor offered, optional or not.
- **`optional` and `bare`**: a bare app's only section is the whole config; it cannot be optional (`ValueError`).
- **A rule across sections** (hand signs need a camera) is the app's: it checks it in its own contract's `check_config`, or its Start does. app-setup does not relate sections.

## API

```python
@dataclass(frozen=True)
class Section:
    ...
    optional: bool = False
    default: Mapping[str, Any] | None = None

class AppModel:
    def optional_off(self, config) -> list[str]: ...    # the optional sections the config leaves out
    def add_section(self, config, name) -> dict: ...    # the config with *name*'s default document
    def remove_section(self, config, name) -> dict: ... # the config without *name*
    def summary(self, config, sections=None) -> str: ...  # the whole config's line, in the table's words
```

`app_setup.ui.report` gains `section_line(title, modules, items, problems)` (a fold's title line) and the whole config's summary wording; `app_setup.form` gains `selected_modules(schema, document)` (the module titles a fold's line shows).

## Staying light

The panel's cost in the browser grows with its components and its events ([ui.md](ui.md), "Reports"). The folds add one component per section and the overview one summary line and one output box; no timer is added, and no `gr.render`: the folds, the Add lines and the Remove buttons are drawn once, shown or hidden. A fold's title line is updated with the checks that already run.

## Testing

- `tests/test_app.py`: an optional section absent is not used, not checked, not in the blockers; `add_section` writes its default, `remove_section` takes it out; a removed then added section in a draft gets the removed document back (the panel's memory); `optional` with `bare` refused; `summary` for a ready config, one with optional items missing, one with sections needing something.
- `tests/ui/test_report.py`: a fold's line for each status, with and without modules.
- `tests/ui/test_panels.py`: the overview's buttons act on every used section (Install all in one run with every section's extras, Test all one line per section); the folds' title lines follow a check and a module switch; a section needing something is open at load, a ready one folded; an optional section off shows its Add line, Add opens its fold with the default document, Remove takes it out; no Add or Remove on a read-only panel.
- Browser: open a fold, switch its module and see its title line change; remove an optional section and add it back, its settings kept; Check all turns a fold's line ready.

## Changes to the other specs, once this one is Stable

- [app.md](app.md): `Section(optional, default)`, `used` leaving an absent optional section out, `optional_off`, `add_section`, `remove_section`, `summary`; its open question 1 (a section the user can switch off) answered.
- [ui.md](ui.md): the panel's order (the overview's actions and summary, a fold per section, the two columns, the Add lines), the fold's title line; "One block per section" replaced.

Each moves to **Updated** with that change, and back to **Implemented** with the plan that builds it.

## Open questions

1. **Folds that follow the checks** (a section folding once it turns ready) were left out: a fold moving by itself under the user's pointer is worse than one more click.
2. **Two sections side by side**, rather than a section's form and table side by side, was considered: sections differ too much in length to sit in a grid.
3. **A fold's line with the key values** (the voice, the model), not only the modules' titles, waits for main fields (a spec not written yet): the line would show the main ones.
