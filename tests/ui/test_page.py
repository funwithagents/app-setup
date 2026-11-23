from pathlib import Path
from typing import Any

import gradio as gr
import pytest
from fakes import SpeechLib
from gradio.components import Component

from module_setup.app import App, AppModel, Section
from module_setup.folder import ConfigFolder
from module_setup.secrets import SecretStore
from module_setup.session import SessionRunner
from module_setup.ui import build_page
from module_setup.ui.form import render_sections

DEFAULTS = {"speech": {"module": {"type": "local-voice"}}}


class _Session:
    def stop(self) -> None:
        pass


def _model(tmp_path: Path, **app: Any) -> AppModel:
    application = App(
        name="talk",
        host="talk-app",
        sections=app.pop("sections", (Section("speech", SpeechLib()),)),
        default_config=DEFAULTS,
        start=lambda context: _Session(),
        **app,
    )
    folder = ConfigFolder(tmp_path, DEFAULTS)
    folder.ensure()
    return AppModel(application, folder, SecretStore(folder.env_path, {}))


def _drawn(model: AppModel, config: dict[str, Any]) -> list[Any]:
    """The components the form draws for *config*."""
    with gr.Blocks() as page:
        draft, revision = gr.State(config), gr.State(0)
        render_sections(model, config, draft, revision)
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

    assert "### Speech" in markdown
    assert any("the `speech` extra" in text for text in markdown)


def test_the_page_builds_with_the_app_s_session_content(tmp_path: Path) -> None:
    built: list[SessionRunner] = []

    def session_ui(runner: SessionRunner) -> None:
        built.append(runner)
        gr.Textbox(label="Say")

    model = _model(tmp_path, session_ui=session_ui)

    page = build_page(model, selected="session")

    assert built == [model.runner]
    labels = _labels(list(page.blocks.values()))
    assert "Say" in labels and "Variable" in labels and "Output" in labels


@pytest.mark.parametrize("selected", ["setup", "secrets", "session"])
def test_the_page_opens_on_any_tab(tmp_path: Path, selected: str) -> None:
    tabs = [
        b
        for b in build_page(_model(tmp_path), selected=selected).blocks.values()
        if isinstance(b, gr.Tabs)
    ]

    assert tabs[0].selected == selected
