import json
import os
import sys
from pathlib import Path

import pytest
from fakes import SpeechLib

from app_setup.app import App, AppModel, Section
from app_setup.config_file import ConfigFile, ConfigFileError
from app_setup.secrets import SecretStore

DOCUMENT = {"module": {"type": "local-voice", "voice": "Bo"}}


def _app(bare: bool) -> App:
    return App(
        name="talk",
        host="talk-app",
        sections=(Section("speech", SpeechLib()),),
        default_config=DOCUMENT if bare else {"speech": DOCUMENT},
        bare=bare,
    )


def _file(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda path: None, "does not exist"),
        (lambda path: path.mkdir(), "is not a file"),
        (lambda path: path.write_text("{"), "is not valid JSON"),
        (lambda path: path.write_text("[1, 2]"), "must hold a JSON object"),
    ],
)
def test_a_file_that_cannot_be_the_config_is_refused_naming_it(
    tmp_path: Path, make: object, message: str
) -> None:
    path = tmp_path / "voice.json"
    make(path)  # type: ignore[operator]

    with pytest.raises(ConfigFileError, match=message) as error:
        ConfigFile(path)
    assert str(path) in str(error.value)
    assert isinstance(error.value, ValueError)
    assert not (tmp_path / ".env").exists()  # nothing created


def test_a_bare_app_s_file_is_its_library_s_document(tmp_path: Path) -> None:
    path = _file(tmp_path / "voice.json", DOCUMENT)
    model = AppModel(
        _app(bare=True),
        ConfigFile(path, writable=True),
        SecretStore(tmp_path / ".env", {}),
    )

    # Read wrapped, the panels' usual shape; saved back as the document alone.
    assert model.saved_config() == {"speech": DOCUMENT}
    edited = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    model.save(edited)

    assert json.loads(path.read_text()) == edited["speech"]
    assert model.saved_config() == edited
    assert model.used_config(model.saved_config()) == edited


def test_a_keyed_app_s_file_holds_one_key_per_section(tmp_path: Path) -> None:
    keyed = {"speech": DOCUMENT}
    path = _file(tmp_path / "talk.json", keyed)
    model = AppModel(
        _app(bare=False),
        ConfigFile(path, writable=True),
        SecretStore(tmp_path / ".env", {}),
    )

    assert model.saved_config() == keyed
    model.save({"speech": {"module": {"type": "local-voice"}}})
    assert json.loads(path.read_text()) == {
        "speech": {"module": {"type": "local-voice"}}
    }


def test_a_file_run_as_it_is_is_never_written(tmp_path: Path) -> None:
    path = _file(tmp_path / "voice.json", DOCUMENT)
    before = path.read_bytes()
    source = ConfigFile(path)
    model = AppModel(_app(bare=True), source, SecretStore(tmp_path / ".env", {}))

    assert not model.editable
    with pytest.raises(RuntimeError, match="as it is"):
        model.save({"speech": {"module": {"type": "cloud-voice"}}})
    with pytest.raises(RuntimeError, match="no default"):
        model.reset()
    with pytest.raises(RuntimeError):
        source.save_config(DOCUMENT)
    with pytest.raises(RuntimeError):
        source.reset_config()

    assert path.read_bytes() == before


def test_a_config_app_offers_no_reset_and_no_launch_settings(tmp_path: Path) -> None:
    source = ConfigFile(_file(tmp_path / "voice.json", DOCUMENT), writable=True)
    model = AppModel(_app(bare=True), source, SecretStore(tmp_path / ".env", {}))

    assert model.editable and not source.resettable
    with pytest.raises(RuntimeError, match="no default"):
        model.reset()
    assert source.read_launch() == {}
    with pytest.raises(RuntimeError, match="no launch settings"):
        source.save_launch({"autostart": True})


@pytest.mark.skipif(sys.platform == "win32", reason="no POSIX permissions on Windows")
def test_saving_keeps_the_file_s_permissions(tmp_path: Path) -> None:
    path = _file(tmp_path / "voice.json", DOCUMENT)
    path.chmod(0o644)

    ConfigFile(path, writable=True).save_config({"module": {"type": "local-voice"}})

    assert path.stat().st_mode & 0o777 == 0o644


def test_relative_paths_resolve_against_the_file_s_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configs = tmp_path / "examples" / "configs"
    configs.mkdir(parents=True)
    _file(configs / "voice.json", DOCUMENT)
    monkeypatch.chdir(tmp_path)  # the file named relative to the working directory
    lib = SpeechLib()
    app = App("talk", "talk-app", (Section("speech", lib),), DOCUMENT, bare=True)
    model = AppModel(
        app,
        ConfigFile(Path("examples/configs/voice.json")),
        SecretStore(tmp_path / ".env", {}),
    )

    model.check_setup(model.saved_config())

    assert model.path == configs
    assert lib.base_dirs["check_setup"] == str(configs)


def test_the_keys_come_from_the_env_next_to_the_file_or_the_one_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environ: dict[str, str] = {}
    monkeypatch.setattr(os, "environ", environ)
    path = _file(tmp_path / "voice.json", DOCUMENT)
    (tmp_path / ".env").write_text('NEXT_KEY="next"\n')
    elsewhere = tmp_path / "secrets" / "keys.env"
    elsewhere.parent.mkdir()
    elsewhere.write_text('GIVEN_KEY="given"\n')

    assert ConfigFile(path).env_path == tmp_path / ".env"
    assert ConfigFile(path, env_path=elsewhere).env_path == elsewhere

    # Building the model loads the source's .env.
    AppModel(_app(bare=True), ConfigFile(path))
    assert environ == {"NEXT_KEY": "next"}
    AppModel(_app(bare=True), ConfigFile(path, env_path=elsewhere))
    assert environ["GIVEN_KEY"] == "given"


def test_a_hand_edit_is_seen_at_the_next_read(tmp_path: Path) -> None:
    path = _file(tmp_path / "voice.json", DOCUMENT)
    model = AppModel(
        _app(bare=True), ConfigFile(path), SecretStore(tmp_path / ".env", {})
    )
    assert model.saved_config() == {"speech": DOCUMENT}

    edited = {"module": {"type": "local-voice", "voice": "Cy"}}
    _file(path, edited)

    assert model.saved_config() == {"speech": edited}
    path.write_text("{")  # broken by hand: said at the next read, naming the file
    with pytest.raises(ConfigFileError, match="voice.json"):
        model.saved_config()
