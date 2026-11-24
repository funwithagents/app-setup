from collections.abc import Callable
from pathlib import Path
from typing import Any

import gradio as gr
from fakes import SpeechLib
from gradio.components import Component

from module_setup.app import App, AppModel, Section
from module_setup.folder import ConfigFolder
from module_setup.secrets import SecretStore
from module_setup.ui import secrets_panel, setup_panel
from module_setup.ui.form import render_section, section_title
from module_setup.ui.panels import LOCKED

DEFAULTS = {"speech": {"module": {"type": "local-voice"}}}


def _model(
    tmp_path: Path, locked: Callable[[], bool] | None = None, **app: Any
) -> AppModel:
    application = App(
        name="talk",
        host="talk-app",
        sections=app.pop("sections", (Section("speech", SpeechLib()),)),
        default_config=DEFAULTS,
        **app,
    )
    folder = ConfigFolder(tmp_path, DEFAULTS)
    return AppModel(application, folder, SecretStore(folder.env_path, {}), locked)


def _drawn(model: AppModel, config: dict[str, Any]) -> list[Any]:
    """The components the form draws for *config*."""
    with gr.Blocks() as page:
        draft, revision = gr.State(config), gr.State(0)
        for name in model.used(config):
            render_section(model, name, config, draft, revision)
    return [block for block in page.blocks.values() if isinstance(block, Component)]


def _labels(components: list[Any]) -> list[str]:
    return [c.label for c in components if getattr(c, "label", None)]


def test_the_form_draws_the_selected_module_s_fields(tmp_path: Path) -> None:
    model = _model(tmp_path)
    config = {
        "speech": {"module": {"type": "cloud-voice", "voice_id": "v1", "api_key": "k"}}
    }

    components = _drawn(model, config)
    labels = _labels(components)

    assert labels[:2] == ["Voice", "voice_id *"]
    assert "speed" in labels and "api_key_env" in labels and "timeout" in labels
    assert "api_key" not in labels  # a key written in the config is never drawn
    assert "Configure gate" in labels
    voice_id = next(c for c in components if c.label == "voice_id *")
    assert voice_id.value == "v1"


def test_the_local_voice_gets_a_voice_list_and_an_enabled_gate_its_fields(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    config = {"speech": {"module": {"type": "local-voice"}, "gate": {"level": 3}}}

    components = _drawn(model, config)
    labels = _labels(components)

    assert "level" in labels and "loud" in labels
    assert any(
        isinstance(c, gr.Button) and c.value == "Choose from the voices list"
        for c in components
    )
    level = next(c for c in components if c.label == "level")
    assert level.value == "3"


def test_a_section_without_its_library_says_what_to_install(tmp_path: Path) -> None:
    def load() -> SpeechLib:
        raise ImportError("No module named 'speech_lib'")

    model = _model(
        tmp_path,
        sections=(Section("speech", load, title="Speech", host_extra="speech"),),
    )

    markdown = [c.value for c in _drawn(model, DEFAULTS) if isinstance(c, gr.Markdown)]

    assert section_title(model, "speech") == "Speech"
    assert any("the `speech` extra" in text for text in markdown)


def _handlers(page: gr.Blocks, name: str) -> list[Callable[..., Any]]:
    """Every function a panel registered under *name*, once each, in the order drawn (one
    per section for a section's own buttons)."""
    found: list[Callable[..., Any]] = []
    for f in page.fns.values():
        fn = f.fn
        if fn is not None and getattr(fn, "__name__", "") == name and fn not in found:
            found.append(fn)
    return found


def _handler(page: gr.Blocks, name: str) -> Callable[..., Any]:
    """The function a panel registered under *name* (for one event or several), to call as
    gradio would."""
    found = _handlers(page, name)
    assert len(found) == 1, found
    return found[0]


def test_the_panels_are_drawn_where_the_app_puts_them(tmp_path: Path) -> None:
    model = _model(tmp_path)

    with gr.Blocks() as page:
        with gr.Tab("Talk"):
            gr.Textbox(label="Say")
        with gr.Tab("Setup"):
            setup = setup_panel(model)
        with gr.Tab("Keys"):
            secrets_panel(model, setup.draft)

    tabs = [b.label for b in page.blocks.values() if isinstance(b, gr.Tab)]
    labels = _labels(list(page.blocks.values()))
    assert tabs == ["Talk", "Setup", "Keys"]  # the app's tabs, and only those
    assert "Say" in labels and "Variable" in labels
    assert "Section to test" not in labels  # each section has its own Test
    assert isinstance(setup.draft, gr.State) and isinstance(setup.saved, gr.State)


def test_the_setup_panel_greys_save_and_reset_while_the_app_locks_the_config(
    tmp_path: Path,
) -> None:
    running = [False]
    with gr.Blocks() as page:
        setup_panel(_model(tmp_path, locked=lambda: running[0]))
    tick = _handler(page, "on_tick")

    assert tick()[0] == ""
    running[0] = True
    note, save, reset = tick()
    assert note == LOCKED
    assert save["interactive"] is False and reset["interactive"] is False


def test_the_secrets_panel_reads_the_config_it_follows_else_the_saved_one(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}

    with gr.Blocks() as following:
        secrets_panel(model, gr.State(cloud))
    with gr.Blocks() as alone:
        secrets_panel(model)

    assert "`CLOUD_VOICE_KEY`" in _handler(following, "on_load")(cloud)[0]
    assert "names no environment variable" in _handler(alone, "on_load")()[0]
    model.save(cloud)
    assert "`CLOUD_VOICE_KEY`" in _handler(alone, "on_load")()[0]


def test_the_secrets_panel_keeps_the_env_file_s_variables_out_of_the_config_s_table(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    model.secrets.set("CLOUD_VOICE_KEY", "s3cret-one")
    model.secrets.set("OLD_KEY", "s3cret-two")
    with gr.Blocks() as page:
        secrets_panel(model, gr.State(cloud))

    text = _handler(page, "on_load")(cloud)[0]

    assert "| `CLOUD_VOICE_KEY` | ✅ the folder's .env |" in text
    assert "OLD_KEY" not in text  # listed with the .env's own variables instead
    assert "s3cret" not in text  # names only, never a value


def test_each_section_has_its_own_checks_acting_on_it_alone(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        sections=(
            Section("speech", SpeechLib(), title="Speech"),
            Section(
                "backup",
                SpeechLib(),
                title="Backup voice",
                when=lambda config: bool(config.get("use_backup")),
            ),
        ),
    )
    # The backup voice's config has a problem; the main voice's has none.
    config = {
        **DEFAULTS,
        "use_backup": True,
        "backup": {"module": {"type": "cloud-voice"}},
    }
    with gr.Blocks() as page:
        setup_panel(model)

    buttons = [b.value for b in page.blocks.values() if isinstance(b, gr.Button)]
    speech_check, backup_check = _handlers(page, "on_check")
    speech_problems, _ = speech_check(config)
    backup_problems, _ = backup_check(config)

    assert buttons.count("Test") == 2 and buttons.count("Install missing extras") == 2
    assert "voice_id" not in speech_problems
    assert "/backup/module/voice_id" in backup_problems

    # A section the config does not use is hidden, the others shown and checked.
    redraw = _handler(page, "on_redraw")
    shown = redraw(config)
    hidden = redraw({**config, "use_backup": False})
    assert (shown[0]["visible"], shown[4]["visible"]) == (True, True)
    assert (hidden[0]["visible"], hidden[4]["visible"]) == (True, False)
    assert "/backup/module/voice_id" in shown[5]
    assert hidden[5] == ""


def test_an_app_with_autostart_gets_its_checkbox_saved_at_once(tmp_path: Path) -> None:
    model = _model(tmp_path, autostart=True)
    with gr.Blocks() as page:
        setup_panel(model)
    with gr.Blocks() as without:
        setup_panel(_model(tmp_path / "other"))

    (checkbox,) = [b for b in page.blocks.values() if isinstance(b, gr.Checkbox)]
    loaded = _handler(page, "on_launch_load")()
    note = _handler(page, "on_autostart")(False)

    assert checkbox.label == "Start the session when the app launches"
    assert loaded is True  # the app's default, until the user chooses
    assert note == "The session will not start when the app launches."
    assert model.autostart() is False
    assert not [b for b in without.blocks.values() if isinstance(b, gr.Checkbox)]
