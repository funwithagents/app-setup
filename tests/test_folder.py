import json
from pathlib import Path

import pytest

from module_setup.folder import ConfigFolder, FolderError, Settings, default_folder

DEFAULTS = {"tts": {"module": {"type": "tone"}}}


def test_the_first_launch_writes_the_default_config_and_settings(
    tmp_path: Path,
) -> None:
    folder = ConfigFolder(tmp_path / "app", DEFAULTS)

    folder.ensure()

    assert folder.read_config() == DEFAULTS
    assert folder.read_settings() == Settings(autostart=False)
    assert json.loads(folder.config_path.read_text()) == DEFAULTS


def test_a_saved_config_survives_the_next_launch_and_reset_goes_back(
    tmp_path: Path,
) -> None:
    folder = ConfigFolder(tmp_path, DEFAULTS)
    folder.ensure()
    saved = {"tts": {"module": {"type": "kokoro", "voice": "af_heart"}}}

    folder.save_config(saved)
    ConfigFolder(tmp_path, DEFAULTS).ensure()

    assert folder.read_config() == saved
    assert folder.reset_config() == DEFAULTS
    assert folder.read_config() == DEFAULTS


def test_the_default_is_not_changed_by_what_is_saved_or_returned(
    tmp_path: Path,
) -> None:
    defaults = {"tts": {"module": {"type": "tone"}}}
    folder = ConfigFolder(tmp_path, defaults)
    folder.ensure()

    folder.default_config["tts"]["module"]["type"] = "changed"
    defaults["tts"]["module"]["type"] = "changed too"

    assert folder.reset_config() == {"tts": {"module": {"type": "tone"}}}


def test_settings_keep_keys_they_do_not_know(tmp_path: Path) -> None:
    folder = ConfigFolder(tmp_path, DEFAULTS)
    folder.ensure()
    folder.settings_path.write_text('{"autostart": false, "theme": "dark"}')

    folder.save_settings(Settings(autostart=True))

    assert json.loads(folder.settings_path.read_text()) == {
        "autostart": True,
        "theme": "dark",
    }
    assert folder.read_settings().autostart is True


@pytest.mark.parametrize(
    ("text", "message"),
    [("{", "not valid JSON"), ("[1]", "must hold a JSON object")],
)
def test_a_config_that_cannot_be_read_names_the_file(
    tmp_path: Path, text: str, message: str
) -> None:
    folder = ConfigFolder(tmp_path, DEFAULTS)
    folder.ensure()
    folder.config_path.write_text(text)

    with pytest.raises(FolderError, match=message) as error:
        folder.read_config()
    assert str(folder.config_path) in str(error.value)


def test_a_settings_value_of_the_wrong_type_is_refused(tmp_path: Path) -> None:
    folder = ConfigFolder(tmp_path, DEFAULTS)
    folder.ensure()
    folder.settings_path.write_text('{"autostart": "yes"}')

    with pytest.raises(FolderError, match="autostart"):
        folder.read_settings()


def test_the_default_folder_follows_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_folder("talk") == tmp_path / "talk"

    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert default_folder("talk") == Path.home() / ".config" / "talk"
