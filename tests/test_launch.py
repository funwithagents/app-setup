import argparse
import json
import os
from pathlib import Path

import pytest
from fakes import SpeechLib

from app_setup.app import App, Section
from app_setup.config_file import ConfigFile, ConfigFileError
from app_setup.folder import ConfigFolder
from app_setup.launch import (
    add_config_app_arguments,
    add_config_arguments,
    open_config_app,
    open_source,
)

DOCUMENT = {"module": {"type": "local-voice"}}
APP = App(
    name="talk",
    host="talk-app",
    sections=(Section("speech", SpeechLib()),),
    default_config=DOCUMENT,
    bare=True,
)


@pytest.fixture(autouse=True)
def environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """An empty process environment (the model loads the .env there), and the default
    folder under the test's own directory."""
    env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
    monkeypatch.setattr(os, "environ", env)
    return env


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    add_config_arguments(parser, APP)
    return parser.parse_args(argv)


def test_folder_and_config_are_one_or_the_other(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit):
        _parse(["--folder", "a", "--config", "b.json"])
    assert "not allowed with argument" in capsys.readouterr().err


def test_neither_gives_the_app_s_default_folder(tmp_path: Path) -> None:
    source = open_source(_parse([]), APP)

    assert isinstance(source, ConfigFolder)
    assert source.path == tmp_path / "xdg" / "talk"
    assert source.env_path == tmp_path / "xdg" / "talk" / ".env"
    assert source.default_config == DOCUMENT


def test_a_folder_given_with_its_env_elsewhere(tmp_path: Path) -> None:
    options = _parse(
        ["--folder", str(tmp_path / "f"), "--env", str(tmp_path / "k.env")]
    )
    source = open_source(options, APP)

    assert isinstance(source, ConfigFolder)
    assert source.path == tmp_path / "f" and source.writable
    assert source.env_path == tmp_path / "k.env"


def test_a_config_file_is_opened_as_it_is_with_its_env(tmp_path: Path) -> None:
    path = tmp_path / "voice.json"
    path.write_text(json.dumps(DOCUMENT))

    plain = open_source(_parse(["--config", str(path)]), APP)
    keyed = open_source(
        _parse(["--config", str(path), "--env", str(tmp_path / "k.env")]), APP
    )

    assert isinstance(plain, ConfigFile) and not plain.writable
    assert plain.env_path == tmp_path / ".env"
    assert keyed.env_path == tmp_path / "k.env"


def test_a_missing_config_file_is_an_error_naming_it(tmp_path: Path) -> None:
    missing = tmp_path / "nowhere.json"

    with pytest.raises(ConfigFileError, match="nowhere.json"):
        open_source(_parse(["--config", str(missing)]), APP)
    assert not missing.exists()


def test_a_config_app_edits_its_file(tmp_path: Path, environ: dict[str, str]) -> None:
    path = tmp_path / "voice.json"
    path.write_text(json.dumps(DOCUMENT))
    (tmp_path / ".env").write_text('CLOUD_VOICE_KEY="s3cret"\n')
    parser = argparse.ArgumentParser()
    add_config_app_arguments(parser)

    options = parser.parse_args([str(path), "--port", "7999"])
    model = open_config_app(options, APP)

    assert (options.host, options.port) == ("127.0.0.1", 7999)
    assert isinstance(model.source, ConfigFile) and model.editable
    assert environ["CLOUD_VOICE_KEY"] == "s3cret"  # its .env loaded
    model.save({"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}})
    assert json.loads(path.read_text()) == {
        "module": {"type": "cloud-voice", "voice_id": "v"}
    }

    with pytest.raises(ConfigFileError):
        open_config_app(parser.parse_args([str(tmp_path / "missing.json")]), APP)
    with pytest.raises(SystemExit):
        parser.parse_args([])  # FILE is required
