"""The Setup and Secrets panels (specs/ui.md, "The panels").

Each panel is drawn where it is called, inside the app's own ``gr.Blocks`` (a tab, a column,
an accordion), and brings its own state and events: the app decides what it shows and where.
The config being edited (the draft) lives in each browser tab; the saved config and the
secrets are the ``AppModel``'s, shared by every tab.
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import gradio as gr

from app_setup.app import AppModel, InstallError, SetupItem
from app_setup.ui.form import render_section, section_title
from app_setup.ui.report import (
    Progress,
    config_report,
    env_file_rows,
    item_line,
    secrets_report,
    setup_summary,
)

__all__ = ["SetupPanel", "secrets_panel", "setup_panel"]

Config = dict[str, Any]

# A fresh value for a panel's revision on each page load: its form is drawn when it changes.
_loads = itertools.count(1)

LOCKED = "🔒 A session is running: stop it to change the config."

# What a field's mark means: a field with a default shows it in its hover text instead.
REQUIRED = (
    "Fields marked * must be filled in; the others have a default or can stay empty. "
    "A value in grey is the default: not set, so the library's own applies, and not "
    "saved. Only what you set is saved."
)


@dataclass(frozen=True)
class SetupPanel:
    """What the app can listen to on a Setup panel."""

    # The config being edited in this browser tab: an input for the app's own events (the
    # Secrets panel's, for one).
    draft: gr.State
    # Changes each time this panel saves or resets the config: `saved.change(...)` to follow.
    saved: gr.State


def _streamed(work: Callable[[Callable[[str], None]], None]) -> Iterator[str]:
    """Run *work* on a thread, yielding the log so far each time it emits a line."""
    lines: queue.Queue[str | None] = queue.Queue()
    text: list[str] = []

    def run() -> None:
        try:
            work(lines.put)
        except Exception as exc:  # noqa: BLE001 - shown in the log
            lines.put(f"Failed: {exc}")
        finally:
            lines.put(None)

    threading.Thread(target=run, name="app-setup-action", daemon=True).start()
    while (line := lines.get()) is not None:
        text.append(line)
        yield "\n".join(text)
    yield "\n".join(text)


@dataclass
class _Run:
    """One item's preparation: its latest progress, then how it ended."""

    started: float
    fraction: float | None = None
    message: str = ""
    ok: bool | None = None  # None while it runs

    def progress(self) -> Progress:
        return Progress(
            running=self.ok is None,
            fraction=self.fraction,
            message=self.message,
            elapsed_s=time.monotonic() - self.started,
            ok=self.ok,
        )


@dataclass
class _Preparations:
    """The panel's preparations, shared by every browser tab (they act on the machine):
    each item's run, and the sections busy with Check, Install or Test."""

    model: AppModel
    runs: dict[tuple[str, str], _Run] = field(default_factory=dict)
    busy: set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, config: Config, item: SetupItem) -> bool:
        """Prepare *item* on its own thread; False when it is already being prepared."""
        key = (item.section, item.id)
        with self.lock:
            if key in self.runs and self.runs[key].ok is None:
                return False
            run = self.runs[key] = _Run(started=time.monotonic())

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

        threading.Thread(target=work, name=f"prepare-{item.id}", daemon=True).start()
        return True

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


def _row(preparations: _Preparations, item: SetupItem) -> tuple[str, dict[str, Any]]:
    """An item row's text and its Prepare button's state."""
    progress = preparations.progress(item)
    running = progress is not None and progress.running
    prepared = progress is not None and progress.ok is True
    wanted = item.preparable and item.status != "ready" and not prepared
    return item_line(item, progress), {
        "visible": wanted,
        "interactive": not running and item.section not in preparations.busy,
    }


@dataclass(frozen=True)
class _Section:
    """One section's block on the panel: what the panel's own events update."""

    name: str
    block: gr.Column
    config_md: gr.Markdown
    summary_md: gr.Markdown
    checked: gr.State  # (a counter, the section's items): its rows are drawn from it
    output: gr.Textbox
    buttons: tuple[gr.Button, ...]
    # The section's problems, its summary and its items for the rows, for a config.
    reports: Callable[[Config], tuple[str, str, tuple[int, list[SetupItem]]]]


def _section_block(
    model: AppModel,
    name: str,
    draft: gr.State,
    revision: gr.State,
    preparations: _Preparations,
    timer: gr.Timer,
) -> _Section:
    """Section *name*: its title, its form, and its own Check, Install, Prepare all and
    Test, acting on it alone; then one row per item, each with its own Prepare."""
    checks = itertools.count(1)

    def reports(config: Config) -> tuple[str, str, tuple[int, list[SetupItem]]]:
        """The section's problems, its summary, and its items for the rows."""
        items = model.check_setup(config, [name])
        preparations.forget_finished(name)
        return (
            config_report(model.check_config(config, [name])),
            setup_summary(items),
            (next(checks), items),
        )

    # A panel-styled column, not a `gr.Group`: inside a group, gradio draws buttons flat.
    with gr.Column(variant="panel") as block:
        gr.Markdown(f"### {section_title(model, name)}")

        @gr.render(inputs=[draft], triggers=[revision.change])
        def form(config: Config) -> None:
            render_section(model, name, config, draft, revision)

        with gr.Row():
            check = gr.Button("Check", scale=0)
            install = gr.Button("Install missing extras", scale=0)
            prepare_all = gr.Button("Prepare all", scale=0)
            probe = gr.Button("Test", scale=0)
        config_md = gr.Markdown()
        summary_md = gr.Markdown()
        checked = gr.State((0, []))

        @gr.render(inputs=[checked], triggers=[checked.change])
        def rows(state: tuple[int, list[SetupItem]]) -> None:
            _, items = state
            lines: list[gr.Markdown] = []
            buttons: list[gr.Button] = []
            for item in items:
                text, button_state = _row(preparations, item)
                with gr.Row(equal_height=True):
                    line = gr.Markdown(text)
                    button = gr.Button("Prepare", size="sm", scale=0, **button_state)

                def on_prepare(
                    config: Config, item: SetupItem = item
                ) -> tuple[Any, Any]:
                    preparations.start(config, item)
                    text, button_state = _row(preparations, item)
                    return text, gr.update(**button_state)

                button.click(
                    on_prepare,
                    inputs=[draft],
                    outputs=[line, button],
                    show_progress="hidden",
                )
                lines.append(line)
                buttons.append(button)
            if not items:
                return

            def on_rows_tick(items: Sequence[SetupItem] = items) -> list[Any]:
                states = [_row(preparations, item) for item in items]
                return [text for text, _ in states] + [
                    gr.update(**button_state) for _, button_state in states
                ]

            timer.tick(on_rows_tick, outputs=[*lines, *buttons], show_progress="hidden")

        output = gr.Textbox(
            label="Output", lines=6, max_lines=20, interactive=False, visible=False
        )

    buttons = (check, install, prepare_all, probe)

    def shown(text: str) -> Any:
        return gr.update(value=text, visible=True)

    def busy(on: bool) -> list[Any]:
        """Mark the section busy (its buttons and rows disabled) or free again."""
        if on:
            preparations.busy.add(name)
        else:
            preparations.busy.discard(name)
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

    def on_install(config: Config) -> Iterator[tuple[Any, ...]]:
        extras = model.missing_extras(config, [name])
        if not extras:
            yield shown("No missing extra the host can install."), *reports(config)
            return

        def work(emit: Callable[[str], None]) -> None:
            emit(f"Installing: {', '.join(extras)}")
            try:
                code = model.install(extras, emit)
            except InstallError as exc:
                emit(str(exc))
                return
            emit("Done." if code == 0 else f"uv exited with code {code}.")

        text = ""
        for text in _streamed(work):
            yield shown(text), gr.skip(), gr.skip(), gr.skip()
        yield shown(text), *reports(config)

    install.click(on_busy, outputs=list(buttons)).then(
        on_install, inputs=[draft], outputs=[output, config_md, summary_md, checked]
    ).then(on_free, outputs=list(buttons))

    def on_prepare_all(config: Config) -> None:
        for item in model.to_prepare(config, [name]):
            preparations.start(config, item)

    prepare_all.click(on_prepare_all, inputs=[draft], show_progress="hidden")

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
    """Draw the Setup panel of *model*'s app here: Save, Revert and Reset for the whole
    config, then one block per section the config uses: its form, its own checks (Check,
    Install, Prepare all, Test) acting on it alone, and a row per item it needs, each with
    its own Prepare and progress."""
    draft = gr.State({})
    revision = gr.State(0)
    saved = gr.State(0)

    # The launch choice first, apart from the config it is not part of: Save, Revert and
    # Reset below act on the config only.
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
    if autostart is not None:
        gr.Markdown("### Configuration")
    with gr.Row():
        save = gr.Button("Save", variant="primary", scale=0)
        revert = gr.Button("Revert to saved", scale=0)
        reset = gr.Button("Reset to defaults", scale=0)
    lock = gr.Markdown()
    notice = gr.Markdown()
    gr.Markdown(REQUIRED)

    # The item rows' progress, on a timer of their own: sharing the lock line's timer
    # stopped the lock line updating in the browser.
    rows_timer = gr.Timer(0.5)
    preparations = _Preparations(model)
    sections = [
        _section_block(model, section.name, draft, revision, preparations, rows_timer)
        for section in model.app.sections
    ]
    timer = gr.Timer(1.0)

    def on_load() -> tuple[Config, int]:
        return model.saved_config(), next(_loads)

    # No trigger and no input: on page load only.
    gr.on(None, on_load, outputs=[draft, revision])

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
            reports = section.reports(config) if visible else ("", "", (0, []))
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
            for component in (
                section.block,
                section.config_md,
                section.summary_md,
                section.checked,
                section.output,
            )
        ],
        show_progress="hidden",
    )

    def on_save(config: Config, count: int) -> tuple[Any, ...]:
        try:
            model.save(config)
        except RuntimeError as exc:
            return f"⚠️ {exc}", gr.skip()
        return "✅ Saved.", count + 1

    save.click(on_save, inputs=[draft, saved], outputs=[notice, saved])

    def on_revert(rev: int) -> tuple[Config, int, str]:
        return model.saved_config(), rev + 1, "Reverted to the saved config."

    revert.click(on_revert, inputs=[revision], outputs=[draft, revision, notice])

    def on_reset(rev: int, count: int) -> tuple[Any, ...]:
        try:
            config = model.reset()
        except RuntimeError as exc:
            return gr.skip(), gr.skip(), gr.skip(), f"⚠️ {exc}"
        return (
            config,
            rev + 1,
            count + 1,
            "Reset to the app's default config, and saved.",
        )

    reset.click(
        on_reset,
        inputs=[revision, saved],
        outputs=[draft, revision, saved, notice],
    )

    def on_tick() -> tuple[str, Any, Any]:
        locked = model.locked()
        return (
            LOCKED if locked else "",
            gr.update(interactive=not locked),
            gr.update(interactive=not locked),
        )

    timer.tick(on_tick, outputs=[lock, save, reset], show_progress="hidden")

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

    def on_load(*values: Config) -> tuple[str, int]:
        return report(*values), next(_loads)

    # On page load, and on each change of the config it follows.
    gr.on(
        None,
        on_load,
        inputs=inputs,
        outputs=[secrets_md, env_revision],
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
