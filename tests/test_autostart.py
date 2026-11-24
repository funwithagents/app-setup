import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from fakes import SpeechLib

from app_setup.app import App, AppModel, Section
from app_setup.autostart import add_start_arguments, starts_at_launch
from app_setup.folder import ConfigFolder
from app_setup.secrets import SecretStore

DEFAULTS = {"speech": {"module": {"type": "local-voice"}}}


def _model(tmp_path: Path, autostart: bool | None, locked: bool = False) -> AppModel:
    app = App(
        name="talk",
        host="talk-app",
        sections=(Section("speech", SpeechLib()),),
        default_config=DEFAULTS,
        autostart=autostart,
    )
    folder = ConfigFolder(tmp_path, DEFAULTS)
    return AppModel(app, folder, SecretStore(folder.env_path, {}), lambda: locked)


def test_the_app_s_default_holds_until_the_user_chooses(tmp_path: Path) -> None:
    on = _model(tmp_path / "on", autostart=True)
    off = _model(tmp_path / "off", autostart=False)

    assert (on.autostart(), off.autostart()) == (True, False)
    assert not on.folder.launch_path.exists()  # nothing written until a choice


def test_the_choice_is_kept_in_launch_json_never_in_the_config(tmp_path: Path) -> None:
    model = _model(tmp_path, autostart=True)

    model.set_autostart(False)

    assert model.autostart() is False
    assert json.loads(model.folder.launch_path.read_text()) == {"autostart": False}
    # The config is the app's own sections only, saved or used.
    assert model.saved_config() == DEFAULTS
    assert model.used_config(model.saved_config()) == DEFAULTS
    # Reset restores the config's default, not the launch choice.
    model.reset()
    assert model.autostart() is False


def test_the_choice_can_change_while_a_session_runs(tmp_path: Path) -> None:
    model = _model(tmp_path, autostart=True, locked=True)

    model.set_autostart(False)  # not refused: it matters at the next launch

    assert model.autostart() is False
    with pytest.raises(RuntimeError, match="Stop the session"):
        model.save(DEFAULTS)


def test_an_app_without_autostart_has_no_choice_and_starts_only_on_start(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path, autostart=None)

    assert model.autostart() is None
    with pytest.raises(RuntimeError, match="has no autostart"):
        model.set_autostart(True)
    assert starts_at_launch(model, None) is False
    assert starts_at_launch(model, True) is True


@pytest.mark.parametrize(
    ("default", "saved", "flag", "starts"),
    [
        (True, None, None, True),  # the app's default
        (True, False, None, False),  # the user's saved choice
        (False, True, None, True),
        (True, True, False, False),  # --no-start wins for this launch
        (False, False, True, True),  # --start wins for this launch
    ],
)
def test_the_flag_wins_then_the_saved_choice_then_the_default(
    tmp_path: Path, default: bool, saved: bool | None, flag: bool | None, starts: bool
) -> None:
    model = _model(tmp_path, autostart=default)
    if saved is not None:
        model.set_autostart(saved)

    assert starts_at_launch(model, flag) is starts


@pytest.mark.parametrize(
    ("argv", "start"), [(["--start"], True), (["--no-start"], False), ([], None)]
)
def test_the_start_arguments(argv: list[str], start: Any) -> None:
    parser = argparse.ArgumentParser()
    add_start_arguments(parser)

    assert parser.parse_args(argv).start is start
