from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fakes import SpeechLib

from module_setup import app as app_module
from module_setup.app import App, AppModel, InstallError, Problem, Section
from module_setup.extras import RequirementStatus
from module_setup.folder import ConfigFolder
from module_setup.secrets import SecretStore, SecretVariable
from module_setup.session import SessionContext, SessionState

DEFAULTS = {"speech": {"module": {"type": "local-voice"}}}


class Running:
    def __init__(self, context: SessionContext) -> None:
        self.context = context
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


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
) -> AppModel:
    app = App(
        name="talk",
        host="talk-app",
        sections=sections or (Section("speech", lib),),
        default_config=defaults,
        start=Running,
    )
    folder = ConfigFolder(tmp_path, app.default_config)
    folder.ensure()
    return AppModel(
        app,
        folder,
        SecretStore(folder.env_path, environ if environ is not None else {}),
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


def test_a_section_the_config_does_not_use_is_neither_checked_nor_started(
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
    assert model.session_config(config) == {"speech": config["speech"]}
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


def test_a_session_starts_with_the_saved_config_of_the_used_sections(
    tmp_path: Path, lib: SpeechLib
) -> None:
    lib.downloaded.add("Ada")
    model = _model(tmp_path, lib)

    assert model.start() == []
    assert model.runner.wait(5) is SessionState.RUNNING
    session = model.runner.session
    assert isinstance(session, Running)
    assert session.context.config == DEFAULTS
    assert session.context.folder == tmp_path

    model.stop()
    model.runner.wait(5)
    assert session.stopped


def test_a_session_does_not_start_while_something_is_missing(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)

    blockers = model.start()

    assert blockers == ["speech: Voice Ada — Not downloaded yet."]
    assert model.runner.state is SessionState.STOPPED


def test_the_config_cannot_change_while_a_session_runs(
    tmp_path: Path, lib: SpeechLib
) -> None:
    lib.downloaded.add("Ada")
    model = _model(tmp_path, lib)
    model.start()
    model.runner.wait(5)

    with pytest.raises(RuntimeError, match="Stop the session"):
        model.save({"speech": {"module": {"type": "cloud-voice"}}})
    with pytest.raises(RuntimeError, match="Stop the session"):
        model.reset()

    model.stop()
    model.runner.wait(5)
    model.save({"speech": {"module": {"type": "cloud-voice"}}})
    assert model.saved_config() == {"speech": {"module": {"type": "cloud-voice"}}}


def test_autostart_starts_only_when_the_settings_ask(
    tmp_path: Path, lib: SpeechLib
) -> None:
    lib.downloaded.add("Ada")
    model = _model(tmp_path, lib)

    assert model.autostart() == []
    assert model.runner.state is SessionState.STOPPED

    model.set_autostart(True)
    assert model.autostart() == []
    assert model.runner.wait(5) is SessionState.RUNNING
    model.stop()
    model.runner.wait(5)


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
