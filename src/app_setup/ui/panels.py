"""The Setup and Secrets panels (specs/ui.md, "The panels").

Each panel is drawn where it is called, inside the app's own ``gr.Blocks`` (a tab, a column,
an accordion), and brings its own state and events: the app decides what it shows and where.
The config being edited (the draft) lives in each browser tab; the saved config and the
secrets are the ``AppModel``'s, shared by every tab. A section's actions try the draft; a
session uses the saved config: the Setup panel says so, and says when the two differ.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import gradio as gr

from app_setup.app import AppModel, SetupItem
from app_setup.ui.form import render_section, section_title
from app_setup.ui.report import (
    HEADER,
    Progress,
    config_report,
    env_file_rows,
    item_status,
    secrets_report,
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


# The table's columns: Item, Status, Explanation, Action.
_SCALES = (2, 2, 4, 2)


def _columns() -> list[gr.Column]:
    return [gr.Column(scale=scale, min_width=80) for scale in _SCALES]


# The most lines a section's table shows: its rows are drawn once, shown or hidden, so no
# listener is ever dropped while a browser may still call it. Items past it are listed
# under the table, without their actions.
_ROWS = 16


@dataclass(frozen=True)
class _Row:
    """One line of a section's table, drawn once: what it shows depends on the item at
    its place in the section's last check."""

    row: gr.Row
    title: gr.Markdown
    status: gr.Markdown
    explanation: gr.Markdown
    button: gr.Button  # Install or Prepare
    key: gr.Textbox  # a missing key's value
    save: gr.Button  # saves the key

    @property
    def texts(self) -> tuple[gr.Markdown, gr.Markdown, gr.Markdown]:
        return self.title, self.status, self.explanation


@dataclass(frozen=True)
class _Table:
    """A section's table: a header, then its rows, then what did not fit."""

    header: gr.Row
    rows: tuple[_Row, ...]
    overflow: gr.Markdown

    @property
    def components(self) -> list[Any]:
        """What `table_lines` updates, in its order."""
        out: list[Any] = [self.header]
        for row in self.rows:
            out += [row.row, *row.texts, row.button, row.key, row.save]
        return [*out, self.overflow]


def _draw_rows() -> _Table:
    """The table's components, all hidden until a check fills them."""
    with gr.Row(equal_height=True, visible=False) as header:
        for column, text in zip(_columns(), HEADER, strict=True):
            with column:
                gr.Markdown(text)
    rows = []
    for _ in range(_ROWS):
        with gr.Row(equal_height=True, visible=False) as row:
            title_col, status_col, explanation_col, action_col = _columns()
            with title_col:
                title = gr.Markdown()
            with status_col:
                status = gr.Markdown()
            with explanation_col:
                explanation = gr.Markdown()
            with action_col:
                button = gr.Button("Prepare", size="sm", visible=False)
                key = gr.Textbox(
                    type="password",
                    show_label=False,
                    interactive=True,
                    visible=False,
                )
                save = gr.Button("Save", size="sm", visible=False)
        rows.append(_Row(row, title, status, explanation, button, key, save))
    return _Table(header, tuple(rows), gr.Markdown(visible=False))


def _row_updates(
    actions: _Actions, item: SetupItem | None, same_item: bool
) -> list[Any]:
    """One row's updates for *item* (None: the row hidden). *same_item*: the row showed
    this item already, so a key being typed on it is kept."""
    if item is None:
        return [gr.update(visible=False), *([gr.skip()] * 6)]
    status, explanation, button_state = _line(actions, item)
    action = _action(item)
    key = action == "key"
    variable = item.variable or ""
    return [
        gr.update(visible=True),
        f"**{item.title}**",
        status,
        explanation,
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
    checks: tuple[gr.Markdown, gr.Markdown, gr.State],
    reports: Callable[[Config], tuple[Any, ...]],
    timer: gr.Timer,
) -> None:
    """A section's table, wired once: filled from each check, each row's Install or
    Prepare and key field acting on the item at its place, and the rows' *timer*
    following each line's action. *checks*, filled by *reports*, are what a successful
    install or a key saved updates."""
    # The items the rows show, in this browser tab: a row keeping its item keeps a key
    # being typed on it.
    shown = gr.State(())

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
                return (gr.skip(),) * 6
            if action == "prepare":
                actions.start(config, item)
                status, explanation, state = _line(actions, item)
                return status, explanation, gr.update(**state), *((gr.skip(),) * 3)
            run = actions.install([item], item.host_extras[:1])
            if run is None:
                return (gr.skip(),) * 6
            run.done.wait()
            # Installed: the section checked again. Failed: the line keeps its error.
            return (
                *((gr.skip(),) * 3),
                *(reports(config) if run.ok else (gr.skip(),) * 3),
            )

        row.button.click(
            on_button,
            inputs=[checked, draft],
            outputs=[row.status, row.explanation, row.button, *checks],
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
                return (gr.skip(),) * 4
            try:
                model.secrets.set(item.variable, text or "")
            except ValueError as exc:
                gr.Warning(str(exc))
                return (gr.skip(),) * 4
            return "", *reports(config)

        for event in (row.save.click, row.key.submit):
            event(
                on_save_key,
                inputs=[row.key, checked, draft],
                outputs=[row.key, *checks],
                show_progress="hidden",
            )

    def on_rows_tick(items: tuple[SetupItem, ...]) -> list[Any]:
        """Every half second: each line's status, explanation and button (a preparation's
        progress, an install's latest words, how it ended)."""
        updates: list[Any] = []
        for index in range(_ROWS):
            item = item_at(items, index)
            if item is None:
                updates += [gr.skip()] * 3
                continue
            status, explanation, state = _line(actions, item)
            updates += [status, explanation, gr.update(**state)]
        return updates

    timer.tick(
        on_rows_tick,
        inputs=[checked],
        outputs=[
            component
            for row in table.rows
            for component in (row.status, row.explanation, row.button)
        ],
        show_progress="hidden",
    )


@dataclass(frozen=True)
class _Section:
    """One section's block on the panel: what the panel's own events update."""

    name: str
    block: gr.Column
    config_md: gr.Markdown
    summary_md: gr.Markdown
    # The section's items, from its last check: its table shows them (`checked.change`).
    checked: gr.State
    output: gr.Textbox
    buttons: tuple[gr.Button, ...]
    # The section's problems, its summary and its items, for a config.
    reports: Callable[[Config], tuple[Any, ...]]

    @property
    def checks(self) -> tuple[gr.Markdown, gr.Markdown, gr.State]:
        """What a check of the section updates: its problems, its summary, its table."""
        return self.config_md, self.summary_md, self.checked


def _section_block(
    model: AppModel,
    name: str,
    draft: gr.State,
    revision: gr.State,
    actions: _Actions,
    timer: gr.Timer,
) -> _Section:
    """Section *name*: its title, its form, and its own Check, Install all, Prepare all
    and Test, acting on it alone; then a table of what it needs, a line per item with its
    own action."""

    def reports(config: Config) -> tuple[Any, ...]:
        """The section's problems, its summary, and its items for the table."""
        items = model.check_setup(config, [name])
        actions.forget_finished(name)
        return (
            config_report(model.check_config(config, [name])),
            setup_summary(items),
            tuple(items),
        )

    # Bumped by each field of the section the user is done with: checked again then.
    edited = gr.State(0)

    # A panel-styled column, not a `gr.Group`: inside a group, gradio draws buttons flat.
    with gr.Column(variant="panel") as block:
        gr.Markdown(f"### {section_title(model, name)}")

        @gr.render(inputs=[draft, revision], triggers=[revision.change], **_RENDERS)
        def form(config: Config, loaded: int) -> None:
            # gradio also runs a render as the page loads, before the draft is read: a form
            # drawn then is replaced at once, and a click on it would reach listeners the
            # server has already dropped. Drawn from the loaded draft only.
            if loaded:
                render_section(model, name, config, draft, revision, edited)

        with gr.Row():
            check = gr.Button("Check", scale=0)
            install_all = gr.Button("Install all", scale=0)
            prepare_all = gr.Button("Prepare all", scale=0)
            probe = gr.Button("Test", scale=0)
        config_md = gr.Markdown()
        summary_md = gr.Markdown()
        checked = gr.State(())
        # The table: its rows drawn once, filled from each check (`checked`).
        table = _draw_rows()

        output = gr.Textbox(
            label="Output", lines=6, max_lines=20, interactive=False, visible=False
        )

    buttons = (check, install_all, prepare_all, probe)
    checks = (config_md, summary_md, checked)
    _wire_table(model, actions, table, draft, checked, checks, reports, timer)

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
        on_check, inputs=[draft], outputs=[config_md, summary_md, checked]
    ).then(on_free, outputs=list(buttons))

    def on_install_all(config: Config) -> Iterator[tuple[Any, ...]]:
        items = [i for i in model.check_setup(config, [name]) if i.installable]
        extras = list(dict.fromkeys(i.host_extras[0] for i in items))
        if not extras:
            yield shown("No missing extra the host can install."), *reports(config)
            return
        run = actions.install(items, extras)
        if run is None:
            yield (
                shown("One of these extras is being installed already."),
                *((gr.skip(),) * 3),
            )
            return
        heading = f"Installing: {', '.join(extras)}"
        while not run.done.wait(0.2):
            with actions.lock:
                text = "\n".join(
                    [
                        heading,
                        *(["Waiting for another install…"] if run.waiting else []),
                    ]
                    + run.lines
                )
            yield shown(text), gr.skip(), gr.skip(), gr.skip()
        with actions.lock:
            text = "\n".join([heading, *run.lines, "Done." if run.ok else ""]).rstrip()
        # Installed: the section checked again. Failed: the lines keep the error.
        yield shown(text), *(reports(config) if run.ok else (gr.skip(),) * 3)

    install_all.click(on_busy, outputs=list(buttons)).then(
        on_install_all,
        inputs=[draft],
        outputs=[output, config_md, summary_md, checked],
    ).then(on_free, outputs=list(buttons))

    def on_prepare_all(config: Config) -> None:
        for item in model.to_prepare(config, [name]):
            actions.start(config, item)

    prepare_all.click(on_prepare_all, inputs=[draft], show_progress="hidden")

    def on_edited(config: Config) -> tuple[Any, ...]:
        return reports(config)

    # A field finished: the section checked again, as if Check were clicked (a key's
    # variable renamed, a voice typed), without its output box (Check's own).
    edited.change(
        on_edited,
        inputs=[draft],
        outputs=[config_md, summary_md, checked],
        show_progress="hidden",
    )

    def on_probe(config: Config) -> Any:
        result = model.probe(config, name)
        mark = "✅" if result.get("ok") else "❌"
        return shown(
            f"{mark} {result.get('message', '')} ({result.get('duration_s', 0):.1f} s)"
        )

    probe.click(on_busy, outputs=list(buttons)).then(
        on_probe, inputs=[draft], outputs=[output]
    ).then(on_free, outputs=list(buttons))

    return _Section(
        name, block, config_md, summary_md, checked, output, buttons, reports
    )


def setup_panel(model: AppModel) -> SetupPanel:
    """Draw the Setup panel of *model*'s app here: for an app with autostart, its launch
    choice, saved at once; then the config: one block per section the config uses (its
    form, its own checks — Check, Install all, Prepare all, Test — trying the draft, a
    table of what it needs, a line per item with its own action), and at the bottom Save, Revert and Reset for the whole config, a line
    saying when the draft differs from the saved config at the top and next to Save."""
    draft = gr.State({})
    revision = gr.State(0)
    saved = gr.State(0)
    # The last `SecretStore.revision` this tab saw: when it changes (a key saved or
    # removed, from any tab), the sections are checked again.
    secrets_seen = gr.State(None)

    # The launch choice first, apart from the config it is not part of: Save, Revert and
    # Reset act on the config only.
    autostart = (
        gr.Checkbox(
            label="Start the session when the app launches",
            info="Saved at once, apart from the config: it takes effect at the next "
            "launch. --start / --no-start override it for one launch.",
            interactive=True,
        )
        if model.app.autostart is not None
        else None
    )
    launch_notice = gr.Markdown() if autostart is not None else None
    gr.Markdown("### Configuration")
    gr.Markdown(DRAFT)
    gr.Markdown(REQUIRED)
    unsaved_top = gr.Markdown()

    # The item rows' progress, on a timer of their own: sharing the lock line's timer
    # stopped the lock line updating in the browser.
    rows_timer = gr.Timer(0.5)
    actions = _Actions(model)
    sections = [
        _section_block(model, section.name, draft, revision, actions, rows_timer)
        for section in model.app.sections
    ]

    # The config is kept last, after the sections it is tried in.
    unsaved_bottom = gr.Markdown()
    with gr.Row():
        save = gr.Button("Save", variant="primary", scale=0)
        revert = gr.Button("Revert to saved", scale=0)
        reset = gr.Button("Reset to defaults", scale=0)
    lock = gr.Markdown()
    notice = gr.Markdown()
    timer = gr.Timer(1.0)

    def unsaved_lines(config: Config, rev: int) -> tuple[str, str]:
        """Both unsaved lines; none before the page load drew the draft."""
        if rev and model.unsaved(config):
            return UNSAVED_TOP, UNSAVED_BOTTOM
        return "", ""

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

    def on_redraw(config: Config) -> list[Any]:
        used = set(model.used(config))
        updates: list[Any] = []
        for section in sections:
            visible = section.name in used
            reports = section.reports(config) if visible else ("", "", (), ())
            updates += [
                gr.update(visible=visible),
                *reports,
                gr.update(value="", visible=False),
            ]
        return updates

    # Each change of structure (the page loaded, a module switched, an optional object
    # turned on or off, a choice from a list, revert, reset) shows the sections the config
    # uses, checks each again and clears its output: what was shown was about another
    # config.
    revision.change(
        on_redraw,
        inputs=[draft],
        outputs=[
            component
            for section in sections
            for component in (section.block, *section.checks, section.output)
        ],
        show_progress="hidden",
    )

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

    def on_tick(config: Config, rev: int, seen: int | None) -> list[Any]:
        """Every second: the lock (Save and Reset with it), the unsaved lines (another tab
        may have saved), and, when a key was saved or removed since this tab last looked,
        the checks of the sections the config uses."""
        locked = model.locked()
        updates: list[Any] = [
            LOCKED if locked else "",
            gr.update(interactive=not locked),
            gr.update(interactive=not locked),
            *unsaved_lines(config, rev),
        ]
        current = model.secrets.revision
        changed = rev and seen is not None and seen != current
        used = set(model.used(config)) if changed else set()
        updates.append(current if changed or seen is None else gr.skip())
        for section in sections:
            if section.name in used:
                updates += section.reports(config)
            else:
                updates += [gr.skip()] * len(section.checks)
        return updates

    timer.tick(
        on_tick,
        inputs=[draft, revision, secrets_seen],
        outputs=[
            lock,
            save,
            reset,
            unsaved_top,
            unsaved_bottom,
            secrets_seen,
            *(component for section in sections for component in section.checks),
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

    gr.Markdown(f"### In the folder's .env\n\n`{model.folder.env_path}`")
    # Changes each time the file may have changed: the list below is drawn again.
    env_revision = gr.State(0)
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
