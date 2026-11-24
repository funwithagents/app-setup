"""The panels driven in a real (headless) browser: what gradio's client cannot reach.

Opt-in, like the whole tier, and skipped without Playwright and its browser
(`APP_SETUP_E2E_REQUIRE_BROWSER=1`, as CI sets it, makes that a failure):

    uv sync --group browser
    uv run playwright install chromium
    uv run pytest tests-e2e -rs
"""

import json
import re
import socket
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import gradio as gr
import pytest
from support import no_browser  # pyright: ignore[reportMissingImports]

try:
    from playwright import sync_api
except ImportError:
    no_browser("Playwright is not installed: uv sync --group browser")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fakes import SpeechLib  # pyright: ignore[reportMissingImports]

from app_setup.app import App, AppModel, Section
from app_setup.folder import ConfigFolder
from app_setup.secrets import SecretStore
from app_setup.ui import secrets_panel, setup_panel

DEFAULTS = {"speech": {"module": {"type": "local-voice"}}}


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


class Served:
    def __init__(self, url: str, folder: ConfigFolder, lib: SpeechLib) -> None:
        self.url, self.folder, self.lib = url, folder, lib
        self.running = False  # the app's session, as the lock reads it


@pytest.fixture
def served(tmp_path: Path) -> Iterator[Served]:
    """An app's own page: its tab first, then the two panels in tabs of its own."""
    lib = SpeechLib()
    app = App(
        name="browser",
        host="app-setup",
        sections=(Section("speech", lib),),
        default_config=DEFAULTS,
    )
    folder = ConfigFolder(tmp_path, DEFAULTS)
    port = _free_port()
    served = Served(f"http://127.0.0.1:{port}/", folder, lib)
    model = AppModel(
        app, folder, SecretStore(folder.env_path, {}), lambda: served.running
    )
    with gr.Blocks() as page:
        with gr.Tab("Talk"):
            gr.Markdown("The app's own session.")
        with gr.Tab("Setup"):
            setup = setup_panel(model)
        with gr.Tab("Keys"):
            secrets_panel(model, setup.draft)
    page.launch(server_name="127.0.0.1", server_port=port, prevent_thread_lock=True)
    try:
        yield served
    finally:
        page.close()


@pytest.fixture
def browser() -> Iterator[object]:
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - no browser downloaded: skip
            no_browser(f"no Chromium for Playwright: {exc}")
        yield launched
        launched.close()


def _open_setup(served: Served, browser: object) -> Any:
    page = browser.new_page()  # type: ignore[attr-defined]
    page.goto(served.url)
    page.get_by_role("tab", name="Setup").click()
    return page


def test_switching_module_typing_and_picking_from_a_list_are_saved(
    served: Served, browser: object
) -> None:
    folder = served.folder
    page = _open_setup(served, browser)
    _textbox(page, "speed").wait_for()  # the form is drawn
    page.get_by_text("Fields marked * must be filled in").wait_for()
    page.get_by_label("Voice", exact=True).click()
    page.get_by_role("option", name="Cloud voice (hosted)").click()

    voice_id = _textbox(page, "voice_id *")
    voice_id.wait_for()
    # The switch checked the new config without a click on Check.
    page.get_by_text("voice_id is required").wait_for()
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


def test_the_keys_follow_the_draft_and_save_waits_for_the_session_to_stop(
    served: Served, browser: object
) -> None:
    page = _open_setup(served, browser)
    _textbox(page, "speed").wait_for()
    page.get_by_label("Voice", exact=True).click()
    page.get_by_role("option", name="Cloud voice (hosted)").click()
    _textbox(page, "voice_id *").wait_for()

    page.get_by_role("tab", name="Keys").click()
    page.get_by_text("CLOUD_VOICE_KEY").wait_for()  # named by the unsaved draft

    served.running = True
    page.get_by_role("tab", name="Setup").click()
    save = page.get_by_role("button", name="Save", exact=True)
    page.get_by_text("A session is running").wait_for()
    assert save.is_disabled()

    served.running = False
    page.get_by_text("A session is running").wait_for(state="hidden")
    assert save.is_enabled()


def test_a_variable_of_the_env_file_is_removed_from_its_row(
    served: Served, browser: object
) -> None:
    env_path = served.folder.env_path
    env_path.write_text('OLD_KEY="x1"\nKEEP_KEY="x2"\n')
    page = _open_setup(served, browser)
    page.get_by_role("tab", name="Keys").click()
    page.get_by_text("not named by the current config").first.wait_for()

    row = page.locator(".row", has_text="OLD_KEY").last
    row.get_by_role("button", name="Remove").click()
    page.get_by_text("removed from the .env.").wait_for()

    assert env_path.read_text() == 'KEEP_KEY="x2"\n'
    page.get_by_text("KEEP_KEY").first.wait_for()
    assert page.get_by_role("button", name="Remove").count() == 1


def test_one_item_is_prepared_from_its_row_with_its_progress(
    served: Served, browser: object
) -> None:
    lib = served.lib
    lib.gate = threading.Event()  # holds the preparation once started
    page = _open_setup(served, browser)
    lexicon = page.locator(".row", has_text="Lexicon").last
    voice = page.locator(".row", has_text="Voice Ada").last
    lexicon.get_by_text("Missing").wait_for()  # the rows of the first check
    voice.get_by_text("Not prepared yet").wait_for()

    lexicon.get_by_role("button", name="Prepare").click()
    lexicon.get_by_text("Starting").wait_for()  # its progress, on its own row
    assert lexicon.get_by_role("button", name="Prepare").is_disabled()

    lib.gate.set()
    lexicon.get_by_text("Ready").wait_for()
    assert lib.lexicon and lib.started == ["lexicon"]
    voice.get_by_text("Not prepared yet").wait_for()  # the other row left as it was
    assert voice.get_by_role("button", name="Prepare").is_enabled()
