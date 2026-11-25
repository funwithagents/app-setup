"""The Setup and Secrets panels (specs/ui.md, "The panels").

Each panel is drawn where it is called, inside the app's own ``gr.Blocks`` (a tab, a column,
an accordion), and brings its own state and events: the app decides what it shows and where.
The config being edited (the draft) lives in each browser tab; the saved config and the
secrets are the ``AppModel``'s, shared by every tab. A section's actions try the draft; a
session uses the saved config: the Setup panel says so, and says when the two differ. For an
app running a file as it is (a model not editable), the Setup panel is read-only: the form
shown, the checks and their actions kept, nothing to save.
"""

from __future__ import annotations

import copy
import html
import itertools
import re
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import gradio as gr

from app_setup.app import AppModel, Problem, SetupItem
from app_setup.folder import ConfigFolder
from app_setup.form import selected_modules
from app_setup.ui.form import render_section, section_title
from app_setup.ui.report import (
    HEADER,
    Progress,
    config_report,
    config_summary,
    env_file_rows,
    item_status,
    secrets_report,
    section_line,
    setup_summary,
)

__all__ = ["SetupPanel", "secrets_panel", "setup_panel", "unsaved_notice"]

Config = dict[str, Any]

# The panels' `gr.render`s run one at a time, all of them together (one concurrency group of
# one): gradio numbers a page's listeners from a counter that two renders running at once
# (the form and the table on page load, a Check and the timer's re-check) can read alike,
# and two runs of one render unregister each other's listeners; either way a button drawn
# then calls a function the server no longer knows.
_RENDERS: dict[str, Any] = {
    "concurrency_limit": 1,
    "concurrency_id": "app-setup-render",
}

# A fresh value for a panel's revision on each page load: its form is drawn when it changes.
_loads = itertools.count(1)

LOCKED = "🔒 A session is running: stop it to change the config."

# Which config the buttons use: the sections' try the draft, a session the saved one.
DRAFT = (
    "Check, Install, Prepare and Test try the config as it is in the form. "
    "Save it for a session to use it."
)
# The same, for a config app: Save writes the file it edits.
DRAFT_FILE = (
    "Check, Install, Prepare and Test try the config as it is in the form. "
    "Save writes it to `{path}`."
)
# An app running a file as it is: the form shown read-only.
READ_ONLY = (
    "Running `{path}` as it is. To change it, edit the file, then Stop and Start the "
    "session."
)
UNSAVED_TOP = "✏️ Unsaved changes — Save is at the bottom."
UNSAVED_BOTTOM = "✏️ Unsaved changes."
UNSAVED_SESSION = "The Setup tab has unsaved changes: Start uses the saved config."

# What a field's mark means: a field with a default shows it in its hover text instead.
REQUIRED = (
    "Fields marked * must be filled in; the others have a default or can stay empty. "
    "A value in grey is the default: not set, so the library's own applies, and not "
    "saved. Only what you set is saved."
)


def unsaved_notice(model: AppModel, draft: Config) -> str:
    """For the app's own session view, given a Setup panel's ``draft``: a line saying the
    draft has unsaved changes and Start uses the saved config, or "" (nothing to say, or
    the panel not loaded yet: its draft still empty)."""
    return UNSAVED_SESSION if draft and model.unsaved(draft) else ""


def saved_notice(model: AppModel, config: Config) -> str:
    """What Save says once the config is written: saved, or saved with problems a session
    would refuse it for. A half-finished config is still saved, so nothing is lost; the
    line says it cannot run yet. Only the config's own problems: what the machine misses
    needs the libraries' imports, and each section's table shows it."""
    problems = model.check_config(config)
    if not problems:
        return "✅ Saved."
    count = len(problems)
    noun = "problem" if count == 1 else "problems"
    return (
        f"⚠️ Saved, with {count} {noun} in the config: a session cannot start with it "
        "until they are fixed. Each section's **Check** lists them."
    )


@dataclass(frozen=True)
class SetupPanel:
    """What the app can listen to on a Setup panel."""

    # The config being edited in this browser tab: an input for the app's own events (the
    # Secrets panel's, for one).
    draft: gr.State
    # Changes each time this panel saves or resets the config: `saved.change(...)` to follow.
    saved: gr.State


@dataclass
class _Run:
    """One action on an item's line (a preparation, an install): its latest progress, then
    how it ended. An install may be shared by several lines (Install all: one uv run)."""

    started: float
    install: bool = False
    waiting: bool = False  # an install queued behind another
    fraction: float | None = None
    message: str = ""
    lines: list[str] = field(default_factory=list)  # uv's output, for Install all
    ok: bool | None = None  # None while it runs
    done: threading.Event = field(default_factory=threading.Event)

    def progress(self) -> Progress:
        return Progress(
            running=self.ok is None,
            fraction=self.fraction,
            message=self.message,
            elapsed_s=time.monotonic() - self.started,
            ok=self.ok,
            install=self.install,
            waiting=self.waiting and self.ok is None,
        )


@dataclass
class _Actions:
    """The panel's actions on the machine, shared by every browser tab: each line's
    preparation (in parallel) and install (one at a time: uv works on one environment),
    and the sections busy with Check, Install all or Test."""

    model: AppModel
    runs: dict[tuple[str, str], _Run] = field(default_factory=dict)
    busy: set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Held by the install running: the others wait their turn.
    installing: threading.Lock = field(default_factory=threading.Lock)

    def _claim(self, items: Sequence[SetupItem], run: _Run) -> bool:
        """Give *items* to *run*; False when one is already being acted on."""
        keys = [(item.section, item.id) for item in items]
        with self.lock:
            if any(k in self.runs and self.runs[k].ok is None for k in keys):
                return False
            for key in keys:
                self.runs[key] = run
        return True

    def start(self, config: Config, item: SetupItem) -> bool:
        """Prepare *item* on its own thread; False when it is already being prepared."""
        run = _Run(started=time.monotonic())
        if not self._claim([item], run):
            return False

        def progress(event: dict[str, Any]) -> None:
            fraction = event.get("fraction")
            with self.lock:
                run.fraction = (
                    float(fraction) if isinstance(fraction, int | float) else None
                )
                run.message = str(event.get("message", ""))

        def work() -> None:
            outcome = self.model.prepare_item(config, item, progress)
            with self.lock:
                run.ok, run.message = outcome.ok, outcome.message
            run.done.set()

        threading.Thread(target=work, name=f"prepare-{item.id}", daemon=True).start()
        return True

    def install(self, items: Sequence[SetupItem], extras: Sequence[str]) -> _Run | None:
        """Install the host's *extras* for *items* (one line's, or a section's Install all)
        in one uv run, on its own thread, after the install running if any; None when one
        of the items is already being acted on."""
        run = _Run(started=time.monotonic(), install=True, waiting=True)
        if not self._claim(items, run):
            return None

        def emit(line: str) -> None:
            with self.lock:
                run.lines.append(line)
                if line.strip():
                    run.message = line.strip()

        def work() -> None:
            with self.installing:
                with self.lock:
                    run.waiting, run.started = False, time.monotonic()
                try:
                    code = self.model.install(extras, emit)
                    ok, message = code == 0, f"uv exited with code {code}."
                except Exception as exc:  # noqa: BLE001 - shown on the line
                    ok, message = False, str(exc)
            with self.lock:
                run.ok = ok
                if not ok:
                    run.message = message
                    run.lines.append(message)
            run.done.set()

        threading.Thread(target=work, name="install", daemon=True).start()
        return run

    def progress(self, item: SetupItem) -> Progress | None:
        with self.lock:
            run = self.runs.get((item.section, item.id))
            return run.progress() if run is not None else None

    def any_running(self) -> bool:
        """Whether a line of any section is being acted on: the rows' timer runs then."""
        with self.lock:
            return any(run.ok is None for run in self.runs.values())

    def running(self, section: str) -> bool:
        with self.lock:
            return any(
                key[0] == section and run.ok is None for key, run in self.runs.items()
            )

    def forget_finished(self, section: str) -> None:
        """Drop the section's finished runs: a new check says where they stand."""
        with self.lock:
            for key in [k for k, r in self.runs.items() if k[0] == section]:
                if self.runs[key].ok is not None:
                    del self.runs[key]


def _action(item: SetupItem) -> str | None:
    """What an item's line offers: "install", "key", "prepare", or nothing."""
    if item.status == "ready":
        return None
    if item.installable:
        return "install"
    if item.variable is not None and item.status == "missing":
        return "key"
    if item.preparable:
        return "prepare"
    return None


def _line(actions: _Actions, item: SetupItem) -> tuple[str, str, dict[str, Any]]:
    """An item's line: its status, its explanation, and its button's state (Install or
    Prepare)."""
    progress = actions.progress(item)
    running = progress is not None and progress.running
    done = progress is not None and progress.ok is True
    status, explanation = item_status(item, progress)
    return (
        status,
        explanation,
        {
            "visible": _action(item) in ("install", "prepare") and not done,
            "interactive": not running and item.section not in actions.busy,
        },
    )


# The table's layout: the three text cells (Item, Status, Explanation) are one HTML block
# taking the row's width, the explanation the most of it; the action has a fixed width on
# the right (a button keeps its own width there, a key field takes what Save leaves). A
# gradio button stretches to its column's width, so the action column must not grow. The
# table sits in half a fold's width, beside the form: the text cells shrink and wrap
# rather than run under the action.
_ACTION_WIDTH = 200
_CELLS_STYLE = (
    "display:grid;width:100%;"
    "grid-template-columns:minmax(0,2fr) minmax(0,2fr) minmax(0,4fr);"
    "gap:10px;align-items:center;overflow-wrap:anywhere"
)

# The most lines a section's table shows: its rows are drawn once, shown or hidden, so no
# listener is ever dropped while a browser may still call it. Items past it are listed
# under the table, without their actions. Kept small, with few components per row: each
# event the page receives costs the browser a pass over every component, hidden ones
# included, and a page with a few sections of many rows could not keep up.
_ROWS = 10


def _inline(text: str) -> str:
    """*text*, Markdown with only `**bold**` and `` `code` `` (the report's wording), as
    HTML: escaped first, so a library's words never become markup."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)


def _cells(title: str, status: str, explanation: str) -> str:
    """A line's three text cells, laid out as the header's: one HTML block, so a row
    costs the page one component for its text, not three."""
    return (
        f'<div style="{_CELLS_STYLE}"><div><strong>{html.escape(title)}</strong></div>'
        f"<div>{_inline(status)}</div><div>{_inline(explanation)}</div></div>"
    )


@dataclass(frozen=True)
class _Row:
    """One line of a section's table, drawn once: what it shows depends on the item at
    its place in the section's last check."""

    row: gr.Row
    cells: gr.HTML  # the item, its status, its explanation
    button: gr.Button  # Install or Prepare
    key: gr.Textbox  # a missing key's value
    save: gr.Button  # saves the key


@dataclass(frozen=True)
class _Table:
    """A section's table: a header, then its rows, then what did not fit."""

    header: gr.Row
    rows: tuple[_Row, ...]
    overflow: gr.Markdown

    @property
    def components(self) -> list[Any]:
        """What `_table_lines` updates, in its order."""
        out: list[Any] = [self.header]
        for row in self.rows:
            out += [row.row, row.cells, row.button, row.key, row.save]
        return [*out, self.overflow]


def _draw_rows() -> _Table:
    """The table's components, all hidden until a check fills them."""
    item, status, explanation, action = (h.strip("*") for h in HEADER)
    with gr.Row(equal_height=True, visible=False) as header:
        gr.HTML(
            f'<div style="{_CELLS_STYLE}"><strong>{item}</strong>'
            f"<strong>{status}</strong><strong>{explanation}</strong></div>",
            scale=1,
            padding=False,
        )
        with gr.Column(scale=0, min_width=_ACTION_WIDTH):
            gr.Markdown(f"**{action}**")
    rows = []
    for _ in range(_ROWS):
        # The class names an item's line, apart from the rows around the table.
        with gr.Row(
            equal_height=True, visible=False, elem_classes=["app-setup-item"]
        ) as row:
            cells = gr.HTML(scale=1, padding=False)
            with (
                gr.Column(scale=0, min_width=_ACTION_WIDTH),
                gr.Row(equal_height=False),
            ):
                button = gr.Button("Prepare", size="sm", scale=0, visible=False)
                key = gr.Textbox(
                    type="password",
                    show_label=False,
                    interactive=True,
                    scale=1,
                    min_width=120,
                    visible=False,
                )
                save = gr.Button("Save", size="sm", scale=0, visible=False)
        rows.append(_Row(row, cells, button, key, save))
    return _Table(header, tuple(rows), gr.Markdown(visible=False))


def _row_updates(
    actions: _Actions, item: SetupItem | None, same_item: bool
) -> list[Any]:
    """One row's updates for *item* (None: the row hidden). *same_item*: the row showed
    this item already, so a key being typed on it is kept."""
    if item is None:
        return [gr.update(visible=False), *([gr.skip()] * 4)]
    status, explanation, button_state = _line(actions, item)
    action = _action(item)
    key = action == "key"
    variable = item.variable or ""
    return [
        gr.update(visible=True),
        _cells(item.title, status, explanation),
        gr.update(
            value="Install" if action == "install" else "Prepare", **button_state
        ),
        gr.update(
            visible=key,
            placeholder=variable,
            label=f"Value of {variable}",  # read by screen readers, not shown
            **({} if same_item else {"value": ""}),
        ),
        gr.update(visible=key),
    ]


def _table_lines(
    actions: _Actions,
    items: Sequence[SetupItem],
    before: Sequence[SetupItem] = (),
) -> list[Any]:
    """Every component of a section's table for *items*, a check's result; *before*, the
    items it showed until now (a row keeping its item keeps a key being typed)."""
    out: list[Any] = [gr.update(visible=bool(items))]
    for index in range(_ROWS):
        item = items[index] if index < len(items) else None
        same = (
            item is not None
            and index < len(before)
            and (before[index].section, before[index].id) == (item.section, item.id)
        )
        out += _row_updates(actions, item, same)
    rest = items[_ROWS:]
    listed = "\n".join(
        f"- **{item.title}** — {' '.join(item_status(item, actions.progress(item)))}"
        for item in rest
    )
    return [*out, gr.update(value=listed, visible=bool(rest))]


def _wire_table(
    model: AppModel,
    actions: _Actions,
    table: _Table,
    draft: gr.State,
    checked: gr.State,
    checks: tuple[Any, ...],
    reports: Callable[[Config], tuple[Any, ...]],
    timer: gr.Timer,
) -> None:
    """A section's table, wired once: filled from each check, each row's Install or
    Prepare and key field acting on the item at its place; an action started turns the
    rows' *timer* on (`_follow_rows`). *checks*, filled by *reports*, are what a
    successful install or a key saved updates."""
    # The items the rows show, in this browser tab: a row keeping its item keeps a key
    # being typed on it.
    shown = gr.State(())
    skipped = (gr.skip(),) * len(checks)

    def on_checked(
        items: tuple[SetupItem, ...], before: tuple[SetupItem, ...]
    ) -> list[Any]:
        return [*_table_lines(actions, items, before), items]

    checked.change(
        on_checked,
        inputs=[checked, shown],
        outputs=[*table.components, shown],
        show_progress="hidden",
    )

    def item_at(items: tuple[SetupItem, ...], index: int) -> SetupItem | None:
        return items[index] if index < len(items) else None

    for index, row in enumerate(table.rows):

        def on_button(
            items: tuple[SetupItem, ...], config: Config, index: int = index
        ) -> tuple[Any, ...]:
            item = item_at(items, index)
            action = _action(item) if item is not None else None
            if item is None or action not in ("install", "prepare"):
                return (gr.skip(),) * (3 + len(checks))
            if action == "prepare":
                actions.start(config, item)
                status, explanation, state = _line(actions, item)
                return (
                    _cells(item.title, status, explanation),
                    gr.update(**state),
                    *skipped,
                    gr.Timer(active=True),
                )
            run = actions.install([item], item.host_extras[:1])
            if run is None:
                return (gr.skip(),) * (3 + len(checks))
            run.done.wait()
            # Installed: the section checked again. Failed: the line keeps its error.
            return (
                *((gr.skip(),) * 2),
                *(reports(config) if run.ok else skipped),
                gr.skip(),
            )

        # Install waits for its run: the rows' timer is turned on by the panel's own
        # one-second tick, which sees an action running.
        row.button.click(
            on_button,
            inputs=[checked, draft],
            outputs=[row.cells, row.button, *checks, timer],
            show_progress="hidden",
        )

        def on_save_key(
            text: str,
            items: tuple[SetupItem, ...],
            config: Config,
            index: int = index,
        ) -> tuple[Any, ...]:
            item = item_at(items, index)
            if item is None or item.variable is None:
                return (gr.skip(),) * (1 + len(checks))
            try:
                model.secrets.set(item.variable, text or "")
            except ValueError as exc:
                gr.Warning(str(exc))
                return (gr.skip(),) * (1 + len(checks))
            return "", *reports(config)

        for event in (row.save.click, row.key.submit):
            event(
                on_save_key,
                inputs=[row.key, checked, draft],
                outputs=[row.key, *checks],
                show_progress="hidden",
            )


def _follow_rows(
    actions: _Actions, sections: Sequence[_Section], timer: gr.Timer
) -> None:
    """The rows' *timer*, one for the whole panel, on only while a line is being acted on:
    each tick sends the lines with an action (a preparation's progress, an install's latest
    words, how it ended) and nothing else, then turns itself off once none runs. An idle
    panel sends no event for its rows: each event costs the browser a pass over the page."""

    def on_rows_tick(*checked: tuple[SetupItem, ...]) -> list[Any]:
        updates: list[Any] = []
        for items in checked:
            for index in range(_ROWS):
                item = items[index] if index < len(items) else None
                if item is None or actions.progress(item) is None:
                    updates += [gr.skip()] * 2
                    continue
                status, explanation, state = _line(actions, item)
                updates += [_cells(item.title, status, explanation), gr.update(**state)]
        return [*updates, gr.Timer(active=actions.any_running())]

    timer.tick(
        on_rows_tick,
        inputs=[section.checked for section in sections],
        outputs=[
            *(
                component
                for section in sections
                for row in section.table.rows
                for component in (row.cells, row.button)
            ),
            timer,
        ],
        show_progress="hidden",
    )


# The least width of a fold's two columns (the form, the checks): narrower, they stack,
# the form first.
_COLUMN_MIN = 420

# What a section's last check says of it, for the whole config's line: its title, whether
# it needs something (a problem, a required item missing), its optional items missing. None
# for a section the config does not use.
Status = tuple[str, bool, int] | None


@dataclass(frozen=True)
class _Section:
    """One section on the panel, drawn once: its fold, and, for an optional section, the
    line offering to add it; what the panel's own events update."""

    name: str
    # The fold: its label is the section's line, it is shown while the config uses it.
    fold: gr.Accordion
    # An optional section's "<title> — off" line (with Add on an editable panel); None for
    # a section that is not optional.
    off: gr.Row | None
    config_md: gr.Markdown
    summary_md: gr.Markdown
    # The section's items, from its last check: its table shows them (`checked.change`).
    checked: gr.State
    # What its last check says, for the whole config's line (`status.change`).
    status: gr.State
    output: gr.Textbox
    buttons: tuple[gr.Button, ...]
    table: _Table
    # The section's problems, its summary, its items, its fold's line and its status, for
    # a config: in `checks`' order.
    reports: Callable[[Config], tuple[Any, ...]]

    @property
    def checks(self) -> tuple[Any, ...]:
        """What a check of the section updates: its problems, its summary, its table, its
        fold's line, its status."""
        return self.config_md, self.summary_md, self.checked, self.fold, self.status


def _section_block(
    model: AppModel,
    name: str,
    draft: gr.State,
    revision: gr.Number,
    removed: gr.State,
    actions: _Actions,
    timer: gr.Timer,
    initial: Config,
) -> _Section:
    """Section *name*, folded: its line as the fold's title; inside, its form beside its
    summary, its problems, a table of what it needs (a line per item with its own action)
    and its own Check, Install all, Prepare all and Test, acting on it alone. An optional
    section gets Remove under them, and a line of its own with Add while it is off.
    *initial* (the saved config) decides what is shown until the page load redraws."""
    section = model.section(name)
    title = section_title(model, name)
    readonly = not model.editable

    def line(
        config: Config, problems: Sequence[Problem], items: Sequence[SetupItem]
    ) -> str:
        description = model.description(name)
        document = config.get(name)
        modules = (
            selected_modules(
                description.schema, document if isinstance(document, dict) else {}
            )
            if description is not None
            else []
        )
        return section_line(
            title, modules, items, problems, installed=description is not None
        )

    def reports(config: Config) -> tuple[Any, ...]:
        """The section's problems, its summary, its items for the table, its fold's line
        and its status."""
        problems = model.check_config(config, [name])
        items = model.check_setup(config, [name])
        actions.forget_finished(name)
        needs = bool(problems) or any(item.blocking for item in items)
        status: Status = (title, needs, sum(1 for item in items if item.deferred))
        return (
            config_report(problems),
            setup_summary(items),
            tuple(items),
            gr.update(label=line(config, problems, items)),
            status,
        )

    # Bumped by each field of the section the user is done with: checked again then.
    edited = gr.State(0)

    # The class lets a page (or a test) find a section's fold.
    with gr.Accordion(
        title,
        open=False,
        visible=name in model.used(initial),
        elem_classes=["app-setup-fold"],
    ) as fold:
        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=_COLUMN_MIN):

                @gr.render(
                    inputs=[draft, revision], triggers=[revision.change], **_RENDERS
                )
                def form(config: Config, loaded: int) -> None:
                    # gradio also runs a render as the page loads, before the draft is
                    # read: a form drawn then is replaced at once, and a click on it would
                    # reach listeners the server has already dropped. Drawn from the
                    # loaded draft only.
                    if loaded:
                        render_section(
                            model,
                            name,
                            config,
                            draft,
                            revision,
                            edited,
                            readonly=readonly,
                        )

            with gr.Column(scale=1, min_width=_COLUMN_MIN):
                summary_md = gr.Markdown()
                config_md = gr.Markdown()
                checked = gr.State(())
                # The table: its rows drawn once, filled from each check (`checked`).
                table = _draw_rows()
                with gr.Row():
                    check = gr.Button("Check", scale=0)
                    install_all = gr.Button("Install all", scale=0)
                    prepare_all = gr.Button("Prepare all", scale=0)
                    probe = gr.Button("Test", scale=0)
                output = gr.Textbox(
                    label="Output",
                    lines=6,
                    max_lines=20,
                    interactive=False,
                    visible=False,
                )
        remove = (
            gr.Button(f"Remove {title}", scale=0)
            if section.optional and not readonly
            else None
        )
    status = gr.State(None)

    off = None
    add = None
    if section.optional:
        with gr.Row(
            equal_height=True, visible=name in model.optional_off(initial)
        ) as off:
            gr.Markdown(f"**{title}** — off")
            add = gr.Button("Add", scale=0) if not readonly else None

    buttons = (check, install_all, prepare_all, probe)
    checks = (config_md, summary_md, checked, fold, status)
    _wire_table(model, actions, table, draft, checked, checks, reports, timer)
    skipped = (gr.skip(),) * len(checks)

    if remove is not None and add is not None:

        def on_remove(config: Config, rev: int, kept: Config) -> tuple[Any, ...]:
            document = config.get(name)
            if isinstance(document, dict):
                kept = {**kept, name: copy.deepcopy(document)}
            return model.remove_section(config, name), rev + 1, kept

        # A draft edit, as a module switched: the panel redraws (`on_redraw`), the fold
        # hidden and the Add line shown; the document kept in this tab for Add.
        remove.click(
            on_remove,
            inputs=[draft, revision, removed],
            outputs=[draft, revision, removed],
            show_progress="hidden",
        )

        def on_add(config: Config, rev: int, kept: Config) -> tuple[Any, ...]:
            document = kept.get(name)
            rest = {key: value for key, value in kept.items() if key != name}
            return (
                model.add_section(config, name, document),
                rev + 1,
                rest,
                gr.update(open=True),
            )

        add.click(
            on_add,
            inputs=[draft, revision, removed],
            outputs=[draft, revision, removed, fold],
            show_progress="hidden",
        )

    def shown(text: str) -> Any:
        return gr.update(value=text, visible=True)

    def busy(on: bool) -> list[Any]:
        """Mark the section busy (its buttons and lines disabled) or free again."""
        if on:
            actions.busy.add(name)
        else:
            actions.busy.discard(name)
        return [gr.update(interactive=not on) for _ in buttons]

    def on_busy() -> list[Any]:
        return busy(True)

    def on_free() -> list[Any]:
        return busy(False)

    def on_check(config: Config) -> tuple[Any, ...]:
        return reports(config)

    check.click(on_busy, outputs=list(buttons)).then(
        on_check, inputs=[draft], outputs=list(checks)
    ).then(on_free, outputs=list(buttons))

    def on_install_all(config: Config) -> Iterator[tuple[Any, ...]]:
        items = [i for i in model.check_setup(config, [name]) if i.installable]
        extras = list(dict.fromkeys(i.host_extras[0] for i in items))
        if not extras:
            yield shown("No missing extra the host can install."), *reports(config)
            return
        run = actions.install(items, extras)
        if run is None:
            yield shown("One of these extras is being installed already."), *skipped
            return
        for text in _install_output(actions, run, extras):
            yield shown(text), *skipped
        # Installed: the section checked again. Failed: the lines keep the error.
        yield (
            shown(_install_text(actions, run, extras, done=True)),
            *(reports(config) if run.ok else skipped),
        )

    install_all.click(on_busy, outputs=list(buttons)).then(
        on_install_all,
        inputs=[draft],
        outputs=[output, *checks],
    ).then(on_free, outputs=list(buttons))

    def on_prepare_all(config: Config) -> Any:
        for item in model.to_prepare(config, [name]):
            actions.start(config, item)
        return gr.Timer(active=True)

    prepare_all.click(
        on_prepare_all, inputs=[draft], outputs=[timer], show_progress="hidden"
    )

    def on_edited(config: Config) -> tuple[Any, ...]:
        return reports(config)

    # A field finished: the section checked again, as if Check were clicked (a key's
    # variable renamed, a voice typed), without its output box (Check's own).
    edited.change(
        on_edited,
        inputs=[draft],
        outputs=list(checks),
        show_progress="hidden",
    )

    def on_probe(config: Config) -> Any:
        return shown(_probe_line(model, config, name))

    probe.click(on_busy, outputs=list(buttons)).then(
        on_probe, inputs=[draft], outputs=[output]
    ).then(on_free, outputs=list(buttons))

    return _Section(
        name,
        fold,
        off,
        config_md,
        summary_md,
        checked,
        status,
        output,
        buttons,
        table,
        reports,
    )


def _probe_line(
    model: AppModel, config: Config, name: str, titled: bool = False
) -> str:
    """A section's Test, in one line; *titled*: its title first (Test all's lines)."""
    result = model.probe(config, name)
    mark = "✅" if result.get("ok") else "❌"
    head = f"{mark} {model.section_title(name)}:" if titled else mark
    return f"{head} {result.get('message', '')} ({result.get('duration_s', 0):.1f} s)"


def _install_text(
    actions: _Actions, run: _Run, extras: Sequence[str], done: bool
) -> str:
    """What an Install all's output box shows: the extras, uv's lines, how it ended."""
    heading = f"Installing: {', '.join(extras)}"
    with actions.lock:
        waiting = ["Waiting for another install…"] if run.waiting and not done else []
        end = ["Done." if run.ok else ""] if done else []
        return "\n".join([heading, *waiting, *run.lines, *end]).rstrip()


def _install_output(
    actions: _Actions, run: _Run, extras: Sequence[str]
) -> Iterator[str]:
    """An Install all's output box while it runs, five times a second."""
    while not run.done.wait(0.2):
        yield _install_text(actions, run, extras, done=False)


def _overview(
    model: AppModel,
    actions: _Actions,
    sections: Sequence[_Section],
    draft: gr.State,
    buttons: tuple[gr.Button, gr.Button, gr.Button, gr.Button],
    summary_md: gr.Markdown,
    output: gr.Textbox,
    timer: gr.Timer,
) -> None:
    """The whole config's actions, wired: Check all, Install all (one uv run for every
    section), Prepare all (every section's items, side by side) and Test all (one line per
    section), acting on every section the config uses as each section's own buttons act on
    one; and its summary line, following each section's status."""
    check_all, install_all, prepare_all, test_all = buttons
    checks = [component for section in sections for component in section.checks]

    def every_check(config: Config, names: Sequence[str]) -> list[Any]:
        """Each section's checks: those of *names* run, the others left as they are."""
        out: list[Any] = []
        for section in sections:
            if section.name in names:
                out += section.reports(config)
            else:
                out += [gr.skip()] * len(section.checks)
        return out

    def shown(text: str) -> Any:
        return gr.update(value=text, visible=True)

    def busy(on: bool) -> list[Any]:
        """Every section busy (its lines disabled) while a whole-config action runs, and
        the whole config's buttons with them."""
        for section in sections:
            if on:
                actions.busy.add(section.name)
            else:
                actions.busy.discard(section.name)
        return [gr.update(interactive=not on) for _ in buttons]

    def on_overview_busy() -> list[Any]:
        return busy(True)

    def on_overview_free() -> list[Any]:
        return busy(False)

    def on_overview_check(config: Config) -> list[Any]:
        return every_check(config, model.used(config))

    check_all.click(on_overview_busy, outputs=list(buttons)).then(
        on_overview_check, inputs=[draft], outputs=checks
    ).then(on_overview_free, outputs=list(buttons))

    def on_overview_install(config: Config) -> Iterator[list[Any]]:
        names = model.used(config)
        skipped = [gr.skip()] * len(checks)
        items = [i for i in model.check_setup(config, names) if i.installable]
        extras = list(dict.fromkeys(i.host_extras[0] for i in items))
        if not extras:
            yield [
                shown("No missing extra the host can install."),
                *every_check(config, names),
            ]
            return
        run = actions.install(items, extras)
        if run is None:
            yield [shown("One of these extras is being installed already."), *skipped]
            return
        for text in _install_output(actions, run, extras):
            yield [shown(text), *skipped]
        # Installed: every section checked again. Failed: the lines keep the error.
        yield [
            shown(_install_text(actions, run, extras, done=True)),
            *(every_check(config, names) if run.ok else skipped),
        ]

    install_all.click(on_overview_busy, outputs=list(buttons)).then(
        on_overview_install, inputs=[draft], outputs=[output, *checks]
    ).then(on_overview_free, outputs=list(buttons))

    def on_overview_prepare(config: Config) -> Any:
        for item in model.to_prepare(config):
            actions.start(config, item)
        return gr.Timer(active=True)

    prepare_all.click(
        on_overview_prepare, inputs=[draft], outputs=[timer], show_progress="hidden"
    )

    def on_overview_test(config: Config) -> Iterator[Any]:
        lines: list[str] = []
        for name in model.used(config):
            lines.append(_probe_line(model, config, name, titled=True))
            yield shown("\n".join(lines))
        if not lines:
            yield shown("No section to test.")

    test_all.click(on_overview_busy, outputs=list(buttons)).then(
        on_overview_test, inputs=[draft], outputs=[output]
    ).then(on_overview_free, outputs=list(buttons))

    def on_summary(*statuses: Status) -> str:
        known = [status for status in statuses if status is not None]
        if not known:
            return ""
        needing = [title for title, needs, _ in known if needs]
        return config_summary(needing, sum(deferred for _, _, deferred in known))

    # Each section's status changes only when its check finds otherwise: the line follows
    # every check, without an event of its own for a check that changes nothing.
    gr.on(
        [section.status.change for section in sections],
        on_summary,
        inputs=[section.status for section in sections],
        outputs=[summary_md],
        show_progress="hidden",
        trigger_mode="always_last",
    )


@dataclass(frozen=True)
class _Saving:
    """The bottom of an editable Setup panel, wired: Save, Revert, Reset (for a source
    with a default), the lock line and the unsaved lines, which the panel's tick keeps
    current."""

    model: AppModel
    lock: gr.Markdown
    save: gr.Button
    reset: gr.Button | None
    unsaved_top: gr.Markdown
    unsaved_bottom: gr.Markdown

    @property
    def components(self) -> list[Any]:
        """What the tick updates, in `updates`' order."""
        buttons = [self.save] + ([self.reset] if self.reset is not None else [])
        return [self.lock, *buttons, self.unsaved_top, self.unsaved_bottom]

    def now(self, config: Config, rev: int) -> tuple[Any, ...]:
        """What the tick would show: the lock, then the unsaved lines."""
        return (self.model.locked(), *_unsaved_lines(self.model, config, rev))

    def updates(self, now: tuple[Any, ...]) -> list[Any]:
        locked = now[0]
        buttons = 1 if self.reset is None else 2
        return [
            LOCKED if locked else "",
            *(gr.update(interactive=not locked) for _ in range(buttons)),
            *now[1:],
        ]


def _unsaved_lines(model: AppModel, config: Config, rev: int) -> tuple[str, str]:
    """Both unsaved lines; none before the page load drew the draft."""
    if rev and model.unsaved(config):
        return UNSAVED_TOP, UNSAVED_BOTTOM
    return "", ""


def _saving(
    model: AppModel,
    draft: gr.State,
    revision: gr.Number,
    saved: gr.State,
    unsaved_top: gr.Markdown,
) -> _Saving:
    """Draw the bottom of an editable Setup panel here, kept last, after the sections the
    config is tried in: the unsaved line, Save, Revert and Reset, the lock line and what
    the last button did; and wire them."""
    unsaved_bottom = gr.Markdown()
    with gr.Row():
        save = gr.Button("Save", variant="primary", scale=0)
        revert = gr.Button("Revert to saved", scale=0)
        reset = (
            gr.Button("Reset to defaults", scale=0) if model.source.resettable else None
        )
    lock = gr.Markdown()
    notice = gr.Markdown()

    def unsaved_lines(config: Config, rev: int) -> tuple[str, str]:
        return _unsaved_lines(model, config, rev)

    def on_draft(config: Config, rev: int) -> tuple[str, str]:
        return unsaved_lines(config, rev)

    # Each change of the draft, a value typed included: compared with the saved file.
    draft.change(
        on_draft,
        inputs=[draft, revision],
        outputs=[unsaved_top, unsaved_bottom],
        show_progress="hidden",
    )

    def on_save(config: Config, count: int, rev: int) -> tuple[Any, ...]:
        try:
            model.save(config)
        except RuntimeError as exc:
            return f"⚠️ {exc}", gr.skip(), *unsaved_lines(config, rev)
        return saved_notice(model, config), count + 1, *unsaved_lines(config, rev)

    save.click(
        on_save,
        inputs=[draft, saved, revision],
        outputs=[notice, saved, unsaved_top, unsaved_bottom],
    )

    def on_revert(rev: int) -> tuple[Any, ...]:
        config = model.saved_config()
        return (
            config,
            rev + 1,
            "Reverted to the saved config.",
            *unsaved_lines(config, rev + 1),
        )

    revert.click(
        on_revert,
        inputs=[revision],
        outputs=[draft, revision, notice, unsaved_top, unsaved_bottom],
    )

    if reset is not None:

        def on_reset(config: Config, rev: int, count: int) -> tuple[Any, ...]:
            try:
                config = model.reset()
            except RuntimeError as exc:
                return (
                    gr.skip(),
                    gr.skip(),
                    gr.skip(),
                    f"⚠️ {exc}",
                    *unsaved_lines(config, rev),
                )
            return (
                config,
                rev + 1,
                count + 1,
                "Reset to the app's default config, and saved.",
                *unsaved_lines(config, rev + 1),
            )

        reset.click(
            on_reset,
            inputs=[draft, revision, saved],
            outputs=[draft, revision, saved, notice, unsaved_top, unsaved_bottom],
        )

    return _Saving(model, lock, save, reset, unsaved_top, unsaved_bottom)


def setup_panel(model: AppModel) -> SetupPanel:
    """Draw the Setup panel of *model*'s app here: for an app with autostart, its launch
    choice, saved at once; then the config: the whole config's Check all, Install all,
    Prepare all and Test all with its summary line; one fold per section the config uses,
    titled with its line (its modules, its status), open at page load when it needs
    something: inside, its form beside its own checks — Check, Install all, Prepare all,
    Test — trying the draft, and a table of what it needs, a line per item with its own
    action; an optional section's Remove, or its "off" line with Add; and at the bottom
    Save, Revert and Reset for the whole config (Reset only for a source with a default),
    a line saying when the draft differs from the saved config at the top and next to Save.

    For a model that is not editable (an app running a file as it is): a line naming the
    file, each section's form read-only, its checks and their actions as always, and
    nothing to save: no Save, Revert or Reset, no unsaved line, no launch choice."""
    editable = model.editable
    source = model.source
    draft = gr.State({})
    # Bumped on each change of the form's structure: the forms are drawn again then. A hidden
    # number, not a `gr.State`: in a tab other than the first, gradio fires a State's change
    # twice as the page loads (once more as the tab mounts), so the form was drawn twice
    # and a click on the first drawing reached listeners the second had dropped.
    revision = gr.Number(0, precision=0, visible=False)
    saved = gr.State(0)
    # The last `SecretStore.revision` this tab saw: when it changes (a key saved or
    # removed, from any tab), the sections are checked again.
    secrets_seen = gr.State(None)
    # Whether this tab's folds were opened or folded as the page loaded: once, then the
    # user's.
    unfolded = gr.State(False)
    # The documents of the optional sections removed in this tab: Add puts them back.
    removed = gr.State({})

    # The launch choice first, apart from the config it is not part of: Save, Revert and
    # Reset act on the config only.
    autostart = (
        gr.Checkbox(
            label="Start the session when the app launches",
            info="Saved at once, apart from the config: it takes effect at the next "
            "launch. --start / --no-start override it for one launch.",
            interactive=True,
        )
        # Only where the choice is kept: a folder's launch.json (a file has none).
        if model.app.autostart is not None and isinstance(source, ConfigFolder)
        else None
    )
    launch_notice = gr.Markdown() if autostart is not None else None
    gr.Markdown("### Configuration")
    if not editable:
        gr.Markdown(READ_ONLY.format(path=source.config_path))
    elif isinstance(source, ConfigFolder):
        gr.Markdown(DRAFT)
    else:
        gr.Markdown(DRAFT_FILE.format(path=source.config_path))
    gr.Markdown(REQUIRED)
    unsaved_top = gr.Markdown() if editable else None

    # The whole config's actions and its line, over the folds.
    with gr.Row():
        check_all = gr.Button("Check all", scale=0)
        install_everything = gr.Button("Install all", scale=0)
        prepare_everything = gr.Button("Prepare all", scale=0)
        test_all = gr.Button("Test all", scale=0)
    overview_md = gr.Markdown()
    overview_output = gr.Textbox(
        label="Output", lines=6, max_lines=20, interactive=False, visible=False
    )

    # The item rows' progress, on a timer of their own (sharing the lock line's stopped the
    # lock line updating in the browser), off until a line is acted on (`_follow_rows`).
    rows_timer = gr.Timer(0.5, active=False)
    actions = _Actions(model)
    initial = model.saved_config()
    sections = [
        _section_block(
            model,
            section.name,
            draft,
            revision,
            removed,
            actions,
            rows_timer,
            initial,
        )
        for section in model.app.sections
    ]
    _follow_rows(actions, sections, rows_timer)
    _overview(
        model,
        actions,
        sections,
        draft,
        (check_all, install_everything, prepare_everything, test_all),
        overview_md,
        overview_output,
        rows_timer,
    )

    # The config is kept last, after the sections it is tried in: Save, Revert, Reset, and
    # the lines the tick keeps current (the lock, Save and Reset with it, the unsaved
    # lines). A read-only panel has none of them.
    head = (
        _saving(model, draft, revision, saved, unsaved_top)
        if unsaved_top is not None
        else None
    )
    head_components = head.components if head is not None else []
    timer = gr.Timer(1.0)

    def on_load() -> tuple[Config, int, int]:
        return model.saved_config(), next(_loads), model.secrets.revision

    # No trigger and no input: on page load only.
    gr.on(None, on_load, outputs=[draft, revision, secrets_seen])

    if autostart is not None and launch_notice is not None:

        def on_launch_load() -> bool:
            return bool(model.autostart())

        gr.on(None, on_launch_load, outputs=[autostart], show_progress="hidden")

        def on_autostart(on: bool) -> str:
            model.set_autostart(on)
            return (
                "The session will start when the app launches."
                if on
                else "The session will not start when the app launches."
            )

        # `input`: the user's change only, not the value set on page load.
        autostart.input(on_autostart, inputs=[autostart], outputs=[launch_notice])

    def on_redraw(config: Config, opened: bool) -> list[Any]:
        used = set(model.used(config))
        off = set(model.optional_off(config))
        updates: list[Any] = []
        for section in sections:
            if section.name in used:
                *reports, fold, status = section.reports(config)
                # As the page loads, a section needing something is opened, the others
                # folded; afterwards the user opens and closes them.
                unfold = {} if opened else {"open": bool(status and status[1])}
                reports += [{**fold, "visible": True, **unfold}, status]
            else:
                reports = ["", "", (), gr.update(visible=False), None]
            updates += [*reports, gr.update(value="", visible=False)]
            if section.off is not None:
                updates.append(gr.update(visible=section.name in off))
        return [*updates, gr.update(value="", visible=False), True]

    # Each change of structure (the page loaded, a module switched, an optional object
    # turned on or off, an optional section added or removed, a choice from a list,
    # revert, reset) shows the sections the config uses (their folds' lines with them)
    # and the optional ones it leaves out, checks each again and clears its output and the
    # whole config's: what was shown was about another config.
    revision.change(
        on_redraw,
        inputs=[draft, unfolded],
        outputs=[
            *(
                component
                for section in sections
                for component in (
                    *section.checks,
                    section.output,
                    *([section.off] if section.off is not None else []),
                )
            ),
            overview_output,
            unfolded,
        ],
        show_progress="hidden",
    )

    # What the tick last showed in this browser tab (the lock, the unsaved lines): sent
    # again only when it changed, since each update costs the browser a pass over the page.
    ticked = gr.State(None)

    def on_tick(
        config: Config, rev: int, seen: int | None, last: tuple[Any, ...] | None
    ) -> list[Any]:
        """Every second: the lock (Save and Reset with it), the unsaved lines (another tab
        may have saved), each sent only when it changed; the rows' timer turned on when a
        line is being acted on (from another tab, or an install); and, when a key was saved
        or removed since this tab last looked, the checks of the sections the config
        uses."""
        now = head.now(config, rev) if head is not None else ()
        if head is None:
            updates: list[Any] = []
        elif now == last:
            updates = [gr.skip()] * len(head_components)
        else:
            updates = head.updates(now)
        current = model.secrets.revision
        changed = rev and seen is not None and seen != current
        used = set(model.used(config)) if changed else set()
        updates.append(current if changed or seen is None else gr.skip())
        for section in sections:
            if section.name in used:
                updates += section.reports(config)
            else:
                updates += [gr.skip()] * len(section.checks)
        rows = gr.Timer(active=True) if actions.any_running() else gr.skip()
        return [*updates, rows, now if now != last else gr.skip()]

    timer.tick(
        on_tick,
        inputs=[draft, revision, secrets_seen, ticked],
        outputs=[
            *head_components,
            secrets_seen,
            *(component for section in sections for component in section.checks),
            rows_timer,
            ticked,
        ],
        show_progress="hidden",
    )

    return SetupPanel(draft=draft, saved=saved)


def secrets_panel(model: AppModel, config: gr.State | None = None) -> None:
    """Draw the Secrets panel of *model*'s app here, in two parts: the keys the config
    names, each with where its value comes from, and a form to save one to the folder's
    ``.env``; then every variable that ``.env`` sets, each with what uses it and a
    Remove button. Names only, never a value.

    *config* is the config the variables are read from: a Setup panel's ``draft`` follows
    the edits as they are made; without it, the saved config is read on each refresh.
    """
    gr.Markdown("### Keys the config uses")
    gr.Markdown(
        "Where each key comes from. A value typed here is saved in the folder's .env and "
        "never shown again; a variable set in the shell wins over the file."
    )
    secrets_md = gr.Markdown()
    with gr.Row():
        variable = gr.Textbox(label="Variable", scale=1, interactive=True)
        secret = gr.Textbox(label="Value", type="password", scale=2, interactive=True)
    save_secret = gr.Button("Save to the folder's .env", scale=0)
    secret_notice = gr.Markdown()

    gr.Markdown(f"### In the folder's .env\n\n`{model.source.env_path}`")
    # Changes each time the file may have changed: the list below is drawn again.
    # A hidden number, not a `gr.State`, for the reason the Setup panel's `revision` is.
    env_revision = gr.Number(0, precision=0, visible=False)
    refresh = gr.Button("Refresh", scale=0)

    inputs = [config] if config is not None else []

    def current(values: tuple[Config, ...]) -> Config:
        return values[0] if values else model.saved_config()

    def report(*values: Config) -> str:
        return secrets_report(model.secret_variables(current(values)))

    def file_rows(values: tuple[Config, ...]) -> list[tuple[str, str]]:
        named = {
            variable.name: pointers
            for variable, pointers in model.secret_variables(current(values))
        }
        return env_file_rows(model.secrets.variables(model.secrets.file_names()), named)

    @gr.render(
        inputs=[env_revision, *inputs],
        triggers=[
            env_revision.change,
            *([config.change] if config is not None else []),
        ],
        **_RENDERS,
    )
    def env_file(revision: int, *values: Config) -> None:
        rows = file_rows(values)
        if not rows:
            gr.Markdown("The folder's .env sets no variable.")
        for name, note in rows:
            with gr.Row(equal_height=True):
                gr.Markdown(f"`{name}` — {note}")
                remove = gr.Button("Remove", size="sm", scale=0)

            def on_remove(
                rev: int, *values: Config, name: str = name
            ) -> tuple[Any, ...]:
                model.secrets.remove(name)
                return f"`{name}` removed from the .env.", report(*values), rev + 1

            remove.click(
                on_remove,
                inputs=[env_revision, *inputs],
                outputs=[secret_notice, secrets_md, env_revision],
            )

    # The `SecretStore.revision` the key table shows, in this browser tab: noted with the
    # table on page load. A key saved or removed anywhere else (on a line of the Setup
    # panel, in another tab) changes it: the timer below sees it and draws both parts
    # again, so no reload is needed. Noted here, not by the timer's first tick: a timer in
    # a tab not shown yet only starts when the tab is first opened, maybe after the save.
    seen = gr.State(None)

    def on_load(*values: Config) -> tuple[str, int, int]:
        return report(*values), next(_loads), model.secrets.revision

    # On page load.
    gr.on(
        None,
        on_load,
        inputs=inputs,
        outputs=[secrets_md, env_revision, seen],
        show_progress="hidden",
    )

    # The key table follows the config it reads: a module chosen in the Setup panel's
    # draft shows the key it needs at once.
    if config is not None:
        config.change(
            report, inputs=inputs, outputs=[secrets_md], show_progress="hidden"
        )

    timer = gr.Timer(1)

    def on_secrets_tick(last: int | None, rev: int, *values: Config) -> tuple[Any, ...]:
        current_revision = model.secrets.revision
        if last is None:
            return gr.skip(), gr.skip(), current_revision
        if last == current_revision:
            return gr.skip(), gr.skip(), gr.skip()
        return report(*values), rev + 1, current_revision

    timer.tick(
        on_secrets_tick,
        inputs=[seen, env_revision, *inputs],
        outputs=[secrets_md, env_revision, seen],
        show_progress="hidden",
    )

    def on_refresh(rev: int, *values: Config) -> tuple[str, int]:
        return report(*values), rev + 1

    refresh.click(
        on_refresh, inputs=[env_revision, *inputs], outputs=[secrets_md, env_revision]
    )

    def on_save(name: str, value: str, rev: int, *values: Config) -> tuple[Any, ...]:
        name = (name or "").strip()
        try:
            source = model.secrets.set(name, value or "")
        except ValueError as exc:
            return f"⚠️ {exc}", gr.skip(), value, gr.skip()
        note = (
            f"✅ `{name}` saved in the .env, but the shell's value is the one used: "
            "unset it in your shell profile to use this one."
            if source == "shell"
            else f"✅ `{name}` saved."
        )
        return note, report(*values), "", rev + 1

    save_secret.click(
        on_save,
        inputs=[variable, secret, env_revision, *inputs],
        outputs=[secret_notice, secrets_md, secret, env_revision],
    )
