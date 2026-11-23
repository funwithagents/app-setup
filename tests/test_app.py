import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from fakes import SpeechLib

from module_setup import app as app_module
from module_setup.app import App, AppModel, InstallError, Problem, Section
from module_setup.extras import RequirementStatus
from module_setup.folder import ConfigFolder
from module_setup.secrets import SecretStore, SecretVariable

DEFAULTS = {"speech": {"module": {"type": "local-voice"}}}


@pytest.fixture
def lib() -> SpeechLib:
    return SpeechLib()


@pytest.fixture(autouse=True)
def host(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The host's extras: which of them carries which requirement. A test edits the dict."""
    carriers = {
        "speech-lib[local-voice]": "speech-local",
        "speech-lib[cloud-voice]": "speech-cloud",
    }

    def host_extras(requirement: str, *, host: str) -> tuple[str, ...]:
        assert host == "talk-app"
        return (carriers[requirement],) if requirement in carriers else ()

    monkeypatch.setattr(app_module, "host_extras", host_extras)
    monkeypatch.setattr(
        app_module,
        "requirement_status",
        lambda requirement: RequirementStatus(requirement, "missing"),
    )
    return carriers


def _model(
    tmp_path: Path,
    lib: Any,
    *,
    sections: tuple[Section, ...] | None = None,
    environ: dict[str, str] | None = None,
    defaults: Mapping[str, Any] = DEFAULTS,
    locked: Callable[[], bool] | None = None,
) -> AppModel:
    app = App(
        name="talk",
        host="talk-app",
        sections=sections or (Section("speech", lib),),
        default_config=defaults,
    )
    folder = ConfigFolder(tmp_path, app.default_config)
    folder.ensure()
    return AppModel(
        app,
        folder,
        SecretStore(folder.env_path, environ if environ is not None else {}),
        locked,
    )


def test_problems_are_pointed_into_the_app_s_config(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)

    assert model.check_config({"speech": {"module": {"type": "cloud-voice"}}}) == [
        Problem("speech", "/speech/module/voice_id", "voice_id is required")
    ]
    assert model.check_config({}) == [
        Problem("speech", "/speech", "The 'speech' section is missing.")
    ]
    assert model.check_config(DEFAULTS) == []


def test_a_missing_extra_is_told_which_host_extra_installs_it(
    tmp_path: Path, lib: SpeechLib
) -> None:
    lib.installed["local-voice"] = False
    model = _model(tmp_path, lib)

    [item] = model.check_setup(DEFAULTS)

    assert (item.section, item.id, item.status) == (
        "speech",
        "extra:speech-lib[local-voice]",
        "missing",
    )
    assert item.host_extras == ("speech-local",)
    assert item.installable
    assert model.missing_extras(DEFAULTS) == ["speech-local"]


def test_an_extra_unavailable_on_this_platform_is_not_installable(
    tmp_path: Path, lib: SpeechLib, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib.installed["local-voice"] = False
    monkeypatch.setattr(
        app_module,
        "requirement_status",
        lambda requirement: RequirementStatus(requirement, "unavailable"),
    )
    model = _model(tmp_path, lib)

    [item] = model.check_setup(DEFAULTS)

    assert item.detail == "Not available on this platform."
    assert not item.installable
    assert model.missing_extras(DEFAULTS) == []


def test_an_extra_no_host_extra_carries_says_so(
    tmp_path: Path, lib: SpeechLib, host: dict[str, str]
) -> None:
    lib.installed["local-voice"] = False
    host.clear()
    model = _model(tmp_path, lib)

    [item] = model.check_setup(DEFAULTS)

    assert "No extra of talk-app installs speech-lib[local-voice]." in item.detail
    assert not item.installable


def test_a_section_with_problems_is_not_asked_what_the_machine_needs(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)
    unfinished = {"speech": {"module": {}}}  # the fake's check_setup would raise on it

    assert model.check_setup(unfinished) == []
    model.prepare(unfinished)
    assert model.blockers(unfinished) == [
        f"{p.path}: {p.message}" for p in model.check_config(unfinished)
    ]
    assert model.blockers(unfinished)


def test_files_are_prepared_then_ready(tmp_path: Path, lib: SpeechLib) -> None:
    model = _model(tmp_path, lib)
    progress: list[dict[str, Any]] = []

    before = [(i.id, i.status) for i in model.check_setup(DEFAULTS)]
    model.prepare(DEFAULTS, progress.append)
    after = [(i.id, i.status) for i in model.check_setup(DEFAULTS)]

    assert before == [
        ("extra:speech-lib[local-voice]", "ready"),
        ("weights:Ada", "missing"),
    ]
    assert after == [
        ("extra:speech-lib[local-voice]", "ready"),
        ("weights:Ada", "ready"),
    ]
    assert progress == [{"id": "weights:Ada", "fraction": 1.0, "message": "done"}]


def test_a_section_the_config_does_not_use_is_neither_checked_nor_run(
    tmp_path: Path, lib: SpeechLib
) -> None:
    robot = SpeechLib()
    sections = (
        Section("speech", lib),
        Section("robot", robot, when=lambda config: config.get("body") == "robot"),
    )
    config = {"speech": {"module": {"type": "local-voice"}}, "robot": {"module": {}}}
    model = _model(tmp_path, lib, sections=sections, defaults=config)

    assert model.used(config) == ["speech"]
    assert model.check_config(config) == []
    assert model.used_config(config) == {"speech": config["speech"]}
    assert model.used({**config, "body": "robot"}) == ["speech", "robot"]


def test_a_library_not_installed_is_one_missing_item_its_host_extra_installs(
    tmp_path: Path, lib: SpeechLib
) -> None:
    attempts: list[int] = []

    def load() -> SpeechLib:
        attempts.append(1)
        if len(attempts) == 1:
            raise ImportError("No module named 'speech_lib'")
        return lib

    model = _model(
        tmp_path,
        lib,
        sections=(Section("speech", load, title="Speech", host_extra="speech"),),
    )

    [item] = model.check_setup(DEFAULTS)
    assert (item.id, item.status, item.host_extras) == (
        "extra:talk-app[speech]",
        "missing",
        ("speech",),
    )
    assert item.detail == "No module named 'speech_lib'"
    assert model.check_config(DEFAULTS) == []  # nothing to check without the library
    assert model.description("speech") is None

    model._loaded["speech"].error = None  # what an install does
    model._loaded["speech"].contract = None
    assert model.description("speech") is not None
    assert model.check_setup(DEFAULTS)[0].id == "extra:speech-lib[local-voice]"


def test_installing_runs_the_host_s_installer_and_reloads_failed_sections(
    tmp_path: Path, lib: SpeechLib, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    class Installer:
        def install(self, extras: list[str], on_output: Any = None) -> int:
            calls.append(extras)
            if on_output is not None:
                on_output("installed")
            return 0

    monkeypatch.setattr(app_module, "find_installer", lambda host: Installer())
    model = _model(tmp_path, lib)
    lines: list[str] = []

    assert model.install(["speech-local", "speech-local", "robot"], lines.append) == 0
    assert model.install([]) == 0
    assert calls == [["speech-local", "robot"]]
    assert lines == ["installed"]

    monkeypatch.setattr(
        app_module, "find_installer", lambda host: "uv is not on the PATH"
    )
    with pytest.raises(InstallError, match="uv is not on the PATH"):
        model.install(["speech-local"])


def test_the_secrets_the_config_names_and_where_they_come_from(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib, environ={"CLOUD_VOICE_KEY": "from shell"})
    config = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}

    assert model.secret_variables(config) == [
        (SecretVariable("CLOUD_VOICE_KEY", "shell"), ["/speech/module/api_key_env"])
    ]
    assert model.secret_variables(DEFAULTS) == []


def test_building_the_model_makes_the_folder_ready_and_loads_its_secrets(
    tmp_path: Path, lib: SpeechLib, monkeypatch: pytest.MonkeyPatch
) -> None:
    environ = {"CLOUD_VOICE_KEY": "from shell", "HOME": "/home/me"}
    monkeypatch.setattr(os, "environ", environ)
    folder = ConfigFolder(tmp_path / "talk", DEFAULTS)
    (tmp_path / "talk").mkdir()
    folder.env_path.write_text('CLOUD_VOICE_KEY="from file"\nOTHER_KEY="secret"\n')

    model = AppModel(
        App("talk", "talk-app", (Section("speech", lib),), DEFAULTS), folder
    )

    assert json.loads(folder.config_path.read_text()) == DEFAULTS
    assert environ["OTHER_KEY"] == "secret"  # the libraries read it from there
    assert environ["CLOUD_VOICE_KEY"] == "from shell"  # the shell wins
    assert model.saved_config() == DEFAULTS


def test_blockers_say_why_the_config_cannot_run_yet(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)

    assert model.blockers(DEFAULTS) == ["speech: Voice Ada — Not downloaded yet."]
    assert model.blockers({"speech": {"module": {"type": "cloud-voice"}}})[0] == (
        "/speech/module/voice_id: voice_id is required"
    )

    lib.downloaded.add("Ada")
    assert model.blockers(DEFAULTS) == []


def test_the_config_cannot_change_while_the_app_locks_it(
    tmp_path: Path, lib: SpeechLib
) -> None:
    running = [True]
    model = _model(tmp_path, lib, locked=lambda: running[0])
    cloud = {"speech": {"module": {"type": "cloud-voice"}}}

    with pytest.raises(RuntimeError, match="Stop the session"):
        model.save(cloud)
    with pytest.raises(RuntimeError, match="Stop the session"):
        model.reset()
    assert model.saved_config() == DEFAULTS

    running[0] = False
    model.save(cloud)
    assert model.saved_config() == cloud
    assert model.reset() == DEFAULTS
    assert not _model(tmp_path, lib).locked()  # no lock given: never locked


def test_probe_and_options_reach_the_section_s_contract(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)

    assert model.probe(DEFAULTS, "speech")["ok"] is True
    assert lib.probed == [DEFAULTS["speech"]]
    assert [o["label"] for o in model.options(DEFAULTS, "speech", "voices")] == [
        "Bo (en)",
        "Cy (fr)",
    ]
