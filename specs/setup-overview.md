---
code:
  - src/app_setup/app.py
  - src/app_setup/form.py
  - src/app_setup/ui/panels.py
  - src/app_setup/ui/report.py
tests:
  - tests/test_app.py
  - tests/test_form.py
  - tests/ui/test_panels.py
  - tests/ui/test_report.py
  - tests-e2e/test_panels_in_browser.py
---

# Setup overview and optional sections

**Status:** Draft

## Purpose

An app composing several libraries has several sections, and the Setup panel drew each one in full, one under the other, across the whole width: its form, its table, its buttons. With five or six sections the panel became too long to read, the module chosen in one section was hard to compare with another's, and there was no way to leave a feature out.

This spec makes the panel read like a summary first: **one line per section**, each section **folded** until it is opened, its form and its table **side by side** once open, and **optional sections** the user adds or removes. The folds' lines say the whole config at a glance: there is no line nor any action for the whole config besides them.

## The panel, from top to bottom

```
Setup
▸ Agent — Anthropic · ✅ Ready
▸ Speech recognition — mlx-audio · 🟡 1 optional item missing
▾ Voice — Phonon (local) · ❌ 1 required item missing
    Settings                          ┌ On this machine ──────────────────────────────┐
    Module  [Phonon (local) ▾]        │ ❌ 1 required item missing                     │
    Voice   [Juniper        ▾]        │ Item          Status      Explanation   Action │
    ▸ Advanced                        │ Phonon model  ❌ Missing   …          [Prepare] │
    ✅ The config is valid.            │ [Check] [Install all] [Prepare all] [Test]    │
                                      └───────────────────────────────────────────────┘
    [Remove Voice]                                        (optional sections only)
Microphone processing — off                                                        [Add]
Hand signs — off                                                                   [Add]
                                                         Unsaved changes. [Save] [Revert] [Reset]
```

- **What stays as it is:** the launch checkbox, the "Configuration" title and its lines, the unsaved lines, Save, Revert and Reset at the bottom, the read-only panel of an app running a file ([config-file.md](config-file.md)), the items table and its actions ([ui.md](ui.md)).
- **One fold per section used** (a `gr.Accordion`), in the app's order. Its title line is the section's summary: `<title> — <modules> · <status>`.
  - `<modules>` is the title of the module selected in each module choice of the section, in the form's order, joined by ` · ` (`Phonon (local)`, `Deepgram v2 (hosted) · Silero VAD`); a section with no module choice has none (`Camera · ✅ Ready`).
  - `<status>` is the section's summary in the table's words, short: `✅ Ready`, `🟡 2 optional items missing`, `❌ 1 required item missing`, `❌ 2 problems in the config`. A section whose library does not import reads `❌ not installed`.
  - It is updated by every check of the section, and by each change of the section's structure (a module switched).
  - **Folded or open when the page loads:** each section decides alone, by its `Section(open=...)`:
    - `"needs"` (the default): open when the section needs something (a problem in the config, a required item missing), folded otherwise.
    - `"always"`: open. `"folded"`: folded.
    - There is no rule of the panel's own, a single section included: a one-section app that wants its section open declares `open="always"`.
    - Afterwards the user opens and closes them; a check never folds or opens one.
- **Inside an open fold, two titled columns** side by side, each half the width; on a narrow window they stack, settings first:
  - **Settings**, on the left: the form, then right under it the section's **config problems** ("✅ The config is valid." or the problems with their pointers): they are about what was typed.
  - **On this machine**, on the right, set apart by a light background and border (a panel): the section's status line, its **items table**, then its own **Check**, **Install all**, **Prepare all**, **Test** as small buttons on one row, then its output box. The table's **Action** title sits over the rows' buttons.
- **An optional section** (below) that the config uses has a **Remove <title>** button under its two columns. One the config does not use is a single line, `<title> — off`, with an **Add** button, in the app's order among the others.
- **A change of structure redraws its own section only.** Each section has its own revision: a module switched, an optional object turned on or off, a choice from a list, Add or Remove bump it, and only that section's form is drawn again and only that section checked. The page load, Revert and Reset change the panel's revision, which every section follows. A change may still change which *other* sections the config uses (a `when` reading the value): each section's redraw passes over the others cheaply (their `when` only), hides a fold no longer used, shows an "off" line, and bumps the revision of a section newly used, so that it alone is drawn and checked. (Six sections each checked and drawn for one Add made it take seconds.)
- **An install is never waited for by an event.** A line's **Install** and a section's **Install all** start it and return; the rows' timer follows it (the line's "Installing…" with uv's latest words, the section's output box). Once it has ended well, the timer shows it ("Installed. Checking the section again…") and, at its next tick, checks the section again: what it needs may have changed (a library now importing, its own lines appearing with their Prepare). Two ticks, because that first check imports the library just installed, which can hold the process for seconds.
- **Why an install is never waited for:** gradio wraps each event in a switch of matplotlib's backend, importing matplotlib if it can. An extra that brings matplotlib in makes the first event after it land build matplotlib's font cache in gradio's event loop (no event runs for about ten seconds: the line keeps its last words), and an event open while it lands fails on leaving, its outputs lost. No event spans an install, so none is lost: the rows' timer resumes once the font cache is built.

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
    open: Literal["needs", "always", "folded"] = "needs"  # its fold at page load

class AppModel:
    def optional_off(self, config) -> list[str]: ...    # the optional sections the config leaves out
    def add_section(self, config, name, document=None) -> dict: ...  # *document* (the one removed earlier), else the default, else {}
    def remove_section(self, config, name) -> dict: ... # the config without *name*
    def section_title(self, name) -> str: ...           # the app's title, else the library's, else the key
```

- Another value of `open` is refused (`ValueError`); so is `add_section` or `remove_section` on a section that is not optional.
- `app_setup.ui.report` gains `section_line(title, modules, items, problems, installed=True)` (a fold's title line; `installed=False`: `❌ not installed`); `app_setup.form` gains `selected_modules(schema, document)` (the module titles a fold's line shows).
- The folds and the table's lines carry a class (`app-setup-fold`, `app-setup-item`): a page, or a test, finds them.

## Staying light

The panel's cost in the browser grows with its components and its events ([ui.md](ui.md), "Reports"). The folds add a few components per section (the fold, its two columns and their titles, its hidden revision); no timer is added, and no `gr.render`: the folds, the Add lines and the Remove buttons are drawn once, shown or hidden. A fold's title line and visibility travel in the outputs of events that already run (the checks, the section's redraw). A folded fold's contents are not mounted in the browser. On the server, a change of structure costs its own section's check and form, not every section's.

## Testing

- `tests/test_app.py`: an optional section absent is not used, not checked, not in the blockers; `add_section` writes its default, `remove_section` takes it out; a removed then added section in a draft gets the removed document back (the panel's memory); `optional` with `bare` refused.
- `tests/test_form.py`: `selected_modules`, in the form's order, none for an optional object off.
- `tests/ui/test_report.py`: a fold's line for each status, with and without modules.
- `tests/ui/test_panels.py`: the folds' title lines follow a check and a module switch; a change in one section checks and redraws it alone (each form drawn on the panel's revision and its own section's only), and a section whose `when` turns true or false is shown (its own revision bumped) or hidden; an install from a line or a section's Install all returns at once, the rows' timer follows it, shows its end, then checks the section again, its new lines with it; at load, each section's `open` ("needs" the default: open when it needs something; "always"; "folded"), a single section ready folded unless it says "always", another value refused, and a later redraw moving none; the fold's two titled columns, the config problems under the form, the machine's column a panel with small buttons; an optional section off shows its Add line, Add opens its fold with the default document, Remove takes it out; no Add or Remove on a read-only panel.
- Browser: open a fold, switch its module and see its title line change; remove an optional section and add it back, its settings kept; a section's Check turns its fold's line ready, the fold left open; a single section needing something open, with Settings and On this machine; an install that lands a matplotlib (its first `get_backend` slow) followed live, then the library's new lines shown with their Prepare, no event lost.

## Changes to the other specs, once this one is Stable

- [app.md](app.md): `Section(optional, default, open)`, `used` leaving an absent optional section out, `optional_off`, `add_section`, `remove_section`; its open question 1 (a section the user can switch off) answered.
- [ui.md](ui.md): the panel's order (a fold per section with its two titled columns, the Add lines), the fold's title line, a revision per section, installs never waited for by an event; "One block per section" replaced.

Each moves to **Updated** with that change, and back to **Implemented** with the plan that builds it.

## Open questions

1. **Folds that follow the checks** (a section folding once it turns ready) were left out: a fold moving by itself under the user's pointer is worse than one more click.
2. **Two sections side by side**, rather than a section's form and table side by side, was considered: sections differ too much in length to sit in a grid.
3. **A fold's line with the key values** (the voice, the model), not only the modules' titles, waits for main fields (a spec not written yet): the line would show the main ones.
