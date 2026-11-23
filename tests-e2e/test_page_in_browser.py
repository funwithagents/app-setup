"""The page driven in a real (headless) browser: what gradio's client cannot reach.

Opt-in, like the whole tier, and skipped without Playwright and its browser:

    uv run --with playwright python -m playwright install chromium
    uv run --with playwright pytest tests-e2e -rs
"""

import json
import re
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fakes import SpeechLib  # pyright: ignore[reportMissingImports]

from module_setup.app import App, AppModel, Section
from module_setup.folder import ConfigFolder
from module_setup.secrets import SecretStore
from module_setup.ui import build_page

DEFAULTS = {"speech": {"module": {"type": "local-voice"}}}


class _Session:
    def stop(self) -> None:
        pass


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _textbox(page: Any, label: str) -> Any:
    """A gradio text box, by its label: its text area has no accessible name of its own,
    it sits inside a <label> holding the label and the help text."""
    # Matched on the text content, where the label runs into the help text.
    pattern = re.compile(r"^\s*" + re.escape(label) + r"(?![_a-z])")
    return page.locator("label").filter(has_text=pattern).locator("textarea")


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, ConfigFolder]]:
    app = App(
        name="browser",
        host="module-setup",
        sections=(Section("speech", SpeechLib()),),
        default_config=DEFAULTS,
        start=lambda context: _Session(),
    )
    folder = ConfigFolder(tmp_path, DEFAULTS)
    folder.ensure()
    page = build_page(AppModel(app, folder, SecretStore(folder.env_path, {})))
    port = _free_port()
    page.launch(server_name="127.0.0.1", server_port=port, prevent_thread_lock=True)
    try:
        yield f"http://127.0.0.1:{port}/", folder
    finally:
        page.close()


@pytest.fixture
def browser() -> Iterator[object]:
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - no browser downloaded: skip
            pytest.skip(f"no Chromium for Playwright: {exc}")
        yield launched
        launched.close()


def test_switching_module_typing_and_picking_from_a_list_are_saved(
    served: tuple[str, ConfigFolder], browser: object
) -> None:
    url, folder = served
    page = browser.new_page()  # type: ignore[attr-defined]
    page.goto(url)
    _textbox(page, "speed").wait_for()  # the form is drawn
    page.get_by_label("Voice", exact=True).click()
    page.get_by_role("option", name="Cloud voice (hosted)").click()

    voice_id = _textbox(page, "voice_id *")
    voice_id.wait_for()
    voice_id.fill("v-42")
    voice_id.press("Tab")
    page.get_by_role("button", name="Save", exact=True).click()
    page.get_by_text("Saved.").wait_for()

    assert json.loads(folder.config_path.read_text()) == {
        "speech": {"module": {"type": "cloud-voice", "voice_id": "v-42"}}
    }

    page.get_by_label("Voice", exact=True).click()
    page.get_by_role("option", name="Local voice").click()
    page.get_by_role("button", name="Choose from the voices list").click()
    page.get_by_label("Voices", exact=True).click()
    page.get_by_role("option", name="Cy (fr)").click()
    _textbox(page, "voice").wait_for()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_timeout(1000)

    assert json.loads(folder.config_path.read_text()) == {
        "speech": {"module": {"type": "local-voice", "voice": "Cy", "speed": 1.2}}
    }
