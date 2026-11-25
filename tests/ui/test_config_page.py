import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import gradio as gr
from fakes import SpeechLib

from app_setup.app import App, AppModel, Section
from app_setup.config_file import ConfigFile
from app_setup.secrets import SecretStore
from app_setup.ui import config_page
from app_setup.ui.panels import DRAFT_FILE

DOCUMENT = {"module": {"type": "local-voice"}}


def _page(tmp_path: Path) -> tuple[gr.Blocks, AppModel, Path]:
    path = tmp_path / "voice.json"
    path.write_text(json.dumps(DOCUMENT))
    app = App(
        name="speech-lib-config",
        host="speech-lib",
        sections=(Section("speech", SpeechLib(), title="Speech"),),
        default_config=DOCUMENT,
        bare=True,
        autostart=True,
    )
    model = AppModel(
        app, ConfigFile(path, writable=True), SecretStore(tmp_path / ".env", {})
    )
    return config_page(model), model, path


def _handlers(page: gr.Blocks, name: str) -> list[Callable[..., Any]]:
    found: list[Callable[..., Any]] = []
    for f in page.fns.values():
        fn = f.fn
        if fn is not None and getattr(fn, "__name__", "") == name and fn not in found:
            found.append(fn)
    return found


def test_the_page_has_setup_and_secrets_only(tmp_path: Path) -> None:
    page, _, path = _page(tmp_path)
    drawn = list(page.blocks.values())

    assert [b.label for b in drawn if isinstance(b, gr.Tab)] == ["Setup", "Secrets"]
    markdown = [b.value for b in drawn if isinstance(b, gr.Markdown)]
    assert any(f"Editing `{path}`" in text for text in markdown)
    assert DRAFT_FILE.format(path=path) in markdown  # Save writes the file
    # No session: no launch choice, no lock to follow.
    assert not [b for b in drawn if isinstance(b, gr.Checkbox)]


def test_save_writes_the_file_as_the_library_s_document(tmp_path: Path) -> None:
    page, model, path = _page(tmp_path)
    (on_save,) = _handlers(page, "on_save")[:1]  # the Setup panel's (the Secrets' next)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}

    notice, *_ = on_save(cloud, 0, 1)

    assert notice == "✅ Saved."
    assert json.loads(path.read_text()) == cloud["speech"]
    assert model.saved_config() == cloud


def test_revert_reads_the_file_again_and_there_is_no_reset(tmp_path: Path) -> None:
    page, _, path = _page(tmp_path)
    buttons = [b.value for b in page.blocks.values() if isinstance(b, gr.Button)]
    edited = {"module": {"type": "local-voice", "voice": "Cy"}}
    path.write_text(json.dumps(edited))  # changed by hand while the page is open

    (on_revert,) = _handlers(page, "on_revert")
    config, revision, notice, *_ = on_revert(1)

    assert config == {"speech": edited} and revision == 2
    assert notice == "Reverted to the saved config."
    assert "Revert to saved" in buttons and "Reset to defaults" not in buttons
    assert _handlers(page, "on_reset") == []
