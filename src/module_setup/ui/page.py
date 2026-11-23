"""The page and its launch (specs/ui.md, "The page").

One page per app, shared by every browser tab: the config being edited (the draft) lives in
each browser tab, the saved config, the secrets and the session live in the ``AppModel``. A
timer polls the session so every tab shows the same state.
"""

from __future__ import annotations

import argparse
import logging
import queue
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import gradio as gr

from module_setup.app import App, AppModel, InstallError
from module_setup.folder import ConfigFolder, default_folder
from module_setup.secrets import SecretStore
from module_setup.ui.form import render_sections
from module_setup.ui.report import (
    config_report,
    secrets_report,
    session_report,
    setup_report,
)

__all__ = ["build_page", "launch"]

log = logging.getLogger(__name__)

Config = dict[str, Any]


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


def build_page(model: AppModel, *, selected: str = "setup") -> gr.Blocks:
    """The page of *model*'s app, opened on the *selected* tab (``setup``, ``secrets`` or
    ``session``)."""
    app = model.app
    section_names = [section.name for section in app.sections]

    with gr.Blocks(title=model.title) as page:
        draft = gr.State({})
        revision = gr.State(0)
        gr.Markdown(f"# {model.title}")
        status = gr.Markdown()

        with gr.Tabs(selected=selected):
            # --- Setup -----------------------------------------------------------------
            with gr.Tab("Setup", id="setup"):
                with gr.Row():
                    save = gr.Button("Save", variant="primary", scale=0)
                    reload = gr.Button("Revert to saved", scale=0)
                    reset = gr.Button("Reset to defaults", scale=0)
                    autostart = gr.Checkbox(
                        label="Start a session when the app launches", scale=1
                    )
                notice = gr.Markdown()

                @gr.render(inputs=[draft], triggers=[revision.change])
                def form(config: Config) -> None:
                    render_sections(model, config, draft, revision)

                gr.Markdown("## Checks")
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
                output = gr.Textbox(
                    label="Output", lines=8, max_lines=20, interactive=False
                )

            # --- Secrets -----------------------------------------------------------------
            with gr.Tab("Secrets", id="secrets"):
                gr.Markdown(
                    "The keys the config names, and where each comes from. A value typed "
                    f"here is saved in `{model.folder.env_path}` and never shown again; a "
                    "variable set in the shell wins over the file."
                )
                secrets_md = gr.Markdown()
                refresh_secrets = gr.Button("Refresh", scale=0)
                with gr.Row():
                    variable = gr.Textbox(label="Variable", scale=1)
                    secret = gr.Textbox(label="Value", type="password", scale=2)
                with gr.Row():
                    save_secret = gr.Button("Save to the folder's .env", scale=0)
                    remove_secret = gr.Button("Remove from the .env", scale=0)
                secret_notice = gr.Markdown()

            # --- Session -----------------------------------------------------------------
            with gr.Tab("Session", id="session"):
                with gr.Row():
                    start = gr.Button("Start", variant="primary", scale=0)
                    stop = gr.Button("Stop", variant="stop", scale=0)
                session_md = gr.Markdown()
                blockers_md = gr.Markdown()
                if app.session_ui is not None:
                    app.session_ui(model.runner)

        timer = gr.Timer(1.0)

        # --- Events ---------------------------------------------------------------------

        def on_load(rev: int) -> tuple[Config, int, bool, str, str, str]:
            config = model.saved_config()
            config_text, setup_text = _reports(model, config)
            variables = secrets_report(model.secret_variables(config))
            return (
                config,
                rev + 1,
                model.settings().autostart,
                config_text,
                setup_text,
                variables,
            )

        page.load(
            on_load,
            inputs=[revision],
            outputs=[draft, revision, autostart, config_md, setup_md, secrets_md],
        )

        def on_save(config: Config) -> tuple[str, str, str]:
            try:
                model.save(config)
            except RuntimeError as exc:
                return f"⚠️ {exc}", *_reports(model, config)
            return "✅ Saved.", *_reports(model, config)

        save.click(on_save, inputs=[draft], outputs=[notice, config_md, setup_md])

        def on_reload(rev: int) -> tuple[Config, int, str]:
            return model.saved_config(), rev + 1, "Reverted to the saved config."

        reload.click(on_reload, inputs=[revision], outputs=[draft, revision, notice])

        def on_reset(config: Config, rev: int) -> tuple[Config, int, str]:
            try:
                return (
                    model.reset(),
                    rev + 1,
                    "Reset to the app's default config, and saved.",
                )
            except RuntimeError as exc:
                return config, rev, f"⚠️ {exc}"

        reset.click(
            on_reset, inputs=[draft, revision], outputs=[draft, revision, notice]
        )
        autostart.input(model.set_autostart, inputs=[autostart])

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
                    share = (
                        f" {fraction:.0%}" if isinstance(fraction, int | float) else ""
                    )
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

        def on_secrets(config: Config) -> str:
            return secrets_report(model.secret_variables(config))

        refresh_secrets.click(on_secrets, inputs=[draft], outputs=[secrets_md])

        def on_save_secret(
            config: Config, name: str, value: str
        ) -> tuple[Any, Any, Any]:
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
            return note, on_secrets(config), ""

        save_secret.click(
            on_save_secret,
            inputs=[draft, variable, secret],
            outputs=[secret_notice, secrets_md, secret],
        )

        def on_remove_secret(config: Config, name: str) -> tuple[Any, Any]:
            name = (name or "").strip()
            if not name:
                return "⚠️ Name the variable to remove.", gr.skip()
            model.secrets.remove(name)
            return f"`{name}` removed from the .env.", on_secrets(config)

        remove_secret.click(
            on_remove_secret,
            inputs=[draft, variable],
            outputs=[secret_notice, secrets_md],
        )

        def on_start(config: Config) -> str:
            unsaved = config and config != model.saved_config()
            blockers = model.start()
            text = ""
            if unsaved:
                text = "⚠️ The Setup tab has unsaved changes: the session uses the saved config.\n\n"
            if blockers:
                text += "**The session cannot start:**\n\n" + "\n".join(
                    f"- {b}" for b in blockers
                )
            return text

        start.click(on_start, inputs=[draft], outputs=[blockers_md])
        stop.click(lambda: model.stop() and None, outputs=None)

        def on_tick() -> tuple[str, str, Any, Any, Any, Any]:
            runner = model.runner
            text = session_report(runner)
            idle = runner.idle
            return (
                text,
                text,
                gr.update(interactive=idle),
                gr.update(interactive=runner.session is not None),
                gr.update(interactive=idle),
                gr.update(interactive=idle),
            )

        timer.tick(
            on_tick,
            outputs=[status, session_md, start, stop, save, reset],
            show_progress="hidden",
        )

    return page


def _arguments(app: App, argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=app.title or app.name)
    parser.add_argument(
        "--folder",
        type=Path,
        default=default_folder(app.name),
        help="the app's folder: its config, settings and secrets "
        f"(default: {default_folder(app.name)})",
    )
    parser.add_argument("--host", default="127.0.0.1", help="the address to serve on")
    parser.add_argument("--port", type=int, default=None, help="the port to serve on")
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="do not start a session at launch, whatever the settings say",
    )
    return parser.parse_args(argv)


def launch(app: App, argv: Sequence[str] | None = None, **launch_options: Any) -> None:
    """Run *app*: prepare its folder, load its secrets, autostart, serve the page, and stop
    the session when the page stops. *argv* defaults to the command line."""
    options = _arguments(app, argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    folder = ConfigFolder(options.folder, app.default_config)
    folder.ensure()
    secrets = SecretStore(folder.env_path)
    secrets.load()
    model = AppModel(app, folder, secrets)
    log.info("folder: %s", folder.path)

    selected = "setup"
    if not options.no_autostart and model.settings().autostart:
        blockers = model.autostart()
        if blockers:
            log.warning("autostart did not start a session: %s", "; ".join(blockers))
        else:
            selected = "session"

    page = build_page(model, selected=selected)
    try:
        page.launch(
            server_name=options.host, server_port=options.port, **launch_options
        )
    finally:
        if model.runner.stop() or not model.runner.idle:
            model.runner.wait(timeout=30)
