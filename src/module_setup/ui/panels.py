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
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import gradio as gr

from module_setup.app import AppModel, InstallError
from module_setup.ui.form import render_sections
from module_setup.ui.report import config_report, secrets_report, setup_report

__all__ = ["SetupPanel", "secrets_panel", "setup_panel"]

Config = dict[str, Any]

# A fresh value for a panel's revision on each page load: its form is drawn when it changes.
_loads = itertools.count(1)

LOCKED = "🔒 A session is running: stop it to change the config."


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

    threading.Thread(target=run, name="module-setup-action", daemon=True).start()
    while (line := lines.get()) is not None:
        text.append(line)
        yield "\n".join(text)
    yield "\n".join(text)


def _reports(model: AppModel, config: Config) -> tuple[str, str]:
    return config_report(model.check_config(config)), setup_report(
        model.check_setup(config)
    )


def setup_panel(model: AppModel) -> SetupPanel:
    """Draw the Setup panel of *model*'s app here: Save, Revert and Reset, the form of every
    section the config uses, and the checks (Check, Install, Download, Test)."""
    section_names = [section.name for section in model.app.sections]
    draft = gr.State({})
    revision = gr.State(0)
    saved = gr.State(0)

    with gr.Row():
        save = gr.Button("Save", variant="primary", scale=0)
        revert = gr.Button("Revert to saved", scale=0)
        reset = gr.Button("Reset to defaults", scale=0)
    lock = gr.Markdown()
    notice = gr.Markdown()

    @gr.render(inputs=[draft], triggers=[revision.change])
    def form(config: Config) -> None:
        render_sections(model, config, draft, revision)

    gr.Markdown("### Checks")
    with gr.Row():
        check = gr.Button("Check", scale=0)
        install = gr.Button("Install missing extras", scale=0)
        prepare = gr.Button("Download missing files", scale=0)
        probe_section = gr.Dropdown(
            choices=section_names,
            value=section_names[0] if section_names else None,
            label="Section to test",
            scale=1,
        )
        probe = gr.Button("Test", scale=0)
    config_md = gr.Markdown()
    setup_md = gr.Markdown()
    output = gr.Textbox(label="Output", lines=8, max_lines=20, interactive=False)
    timer = gr.Timer(1.0)

    def on_load() -> tuple[Config, int]:
        return model.saved_config(), next(_loads)

    # No trigger and no input: on page load only.
    gr.on(None, on_load, outputs=[draft, revision])

    def on_redraw(config: Config) -> tuple[str, str, str]:
        return *_reports(model, config), ""

    # Each change of structure (the page loaded, a module switched, an optional object
    # turned on or off, a choice from a list, revert, reset) checks the new config again
    # and clears the output: what was shown was about another config.
    revision.change(
        on_redraw,
        inputs=[draft],
        outputs=[config_md, setup_md, output],
        show_progress="hidden",
    )

    def on_save(config: Config, count: int) -> tuple[Any, ...]:
        try:
            model.save(config)
        except RuntimeError as exc:
            return f"⚠️ {exc}", gr.skip(), *_reports(model, config)
        return "✅ Saved.", count + 1, *_reports(model, config)

    save.click(
        on_save,
        inputs=[draft, saved],
        outputs=[notice, saved, config_md, setup_md],
    )

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

    def on_check(config: Config) -> tuple[str, str]:
        return _reports(model, config)

    check.click(on_check, inputs=[draft], outputs=[config_md, setup_md])

    def on_install(config: Config) -> Iterator[tuple[Any, Any, Any]]:
        extras = model.missing_extras(config)
        if not extras:
            yield "No missing extra the host can install.", *_reports(model, config)
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
            yield text, gr.skip(), gr.skip()
        yield text, *_reports(model, config)

    install.click(on_install, inputs=[draft], outputs=[output, config_md, setup_md])

    def on_prepare(config: Config) -> Iterator[tuple[Any, Any, Any]]:
        def work(emit: Callable[[str], None]) -> None:
            def progress(event: dict[str, Any]) -> None:
                fraction = event.get("fraction")
                share = f" {fraction:.0%}" if isinstance(fraction, int | float) else ""
                emit(f"{event.get('id', '')}{share}: {event.get('message', '')}")

            emit("Preparing…")
            model.prepare(config, progress)
            emit("Done.")

        text = ""
        for text in _streamed(work):
            yield text, gr.skip(), gr.skip()
        yield text, *_reports(model, config)

    prepare.click(on_prepare, inputs=[draft], outputs=[output, config_md, setup_md])

    def on_probe(config: Config, name: str | None) -> str:
        if not name:
            return "Choose a section to test."
        result = model.probe(config, name)
        mark = "✅" if result.get("ok") else "❌"
        return f"{mark} {name}: {result.get('message', '')} ({result.get('duration_s', 0):.1f} s)"

    probe.click(on_probe, inputs=[draft, probe_section], outputs=[output])

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
    """Draw the Secrets panel of *model*'s app here: the variables the config names, each
    with where its value comes from, and a form to save one to the folder's ``.env``.

    *config* is the config the variables are read from: a Setup panel's ``draft`` follows
    the edits as they are made; without it, the saved config is read on each refresh.
    """
    gr.Markdown(
        "The keys the config names, and where each comes from. A value typed here is "
        f"saved in `{model.folder.env_path}` and never shown again; a variable set in the "
        "shell wins over the file."
    )
    secrets_md = gr.Markdown()
    refresh = gr.Button("Refresh", scale=0)
    with gr.Row():
        variable = gr.Textbox(label="Variable", scale=1, interactive=True)
        secret = gr.Textbox(label="Value", type="password", scale=2, interactive=True)
    with gr.Row():
        save_secret = gr.Button("Save to the folder's .env", scale=0)
        remove_secret = gr.Button("Remove from the .env", scale=0)
    secret_notice = gr.Markdown()

    inputs = [config] if config is not None else []

    def report(*values: Config) -> str:
        current = values[0] if values else model.saved_config()
        return secrets_report(model.secret_variables(current))

    # On page load, and on each change of the config it follows.
    gr.on(None, report, inputs=inputs, outputs=[secrets_md], show_progress="hidden")
    refresh.click(report, inputs=inputs, outputs=[secrets_md])

    def on_save(name: str, value: str, *values: Config) -> tuple[Any, Any, Any]:
        name = (name or "").strip()
        try:
            source = model.secrets.set(name, value or "")
        except ValueError as exc:
            return f"⚠️ {exc}", gr.skip(), value
        note = (
            f"✅ `{name}` saved. The shell's value still wins."
            if source == "shell"
            else f"✅ `{name}` saved."
        )
        return note, report(*values), ""

    save_secret.click(
        on_save,
        inputs=[variable, secret, *inputs],
        outputs=[secret_notice, secrets_md, secret],
    )

    def on_remove(name: str, *values: Config) -> tuple[Any, Any]:
        name = (name or "").strip()
        if not name:
            return "⚠️ Name the variable to remove.", gr.skip()
        model.secrets.remove(name)
        return f"`{name}` removed from the .env.", report(*values)

    remove_secret.click(
        on_remove,
        inputs=[variable, *inputs],
        outputs=[secret_notice, secrets_md],
    )
