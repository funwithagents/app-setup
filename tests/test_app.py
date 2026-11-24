import json
import os
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from fakes import SpeechLib

from app_setup import app as app_module
from app_setup.app import App, AppModel, InstallError, Prepared, Problem, Section
from app_setup.contract import ContractError
from app_setup.extras import RequirementStatus
from app_setup.folder import ConfigFolder
from app_setup.secrets import SecretStore, SecretVariable

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


def test_a_section_with_problems_still_says_which_extra_to_install(
    tmp_path: Path, lib: SpeechLib, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The voice id is missing, and the voice list that would fill it needs the extra:
    # the extra must be installable before the config is right.
    lib.check_setup = None  # type: ignore[assignment] - never asked
    model = _model(tmp_path, lib)
    unfinished = {"speech": {"module": {"type": "cloud-voice"}}}

    [item] = model.check_setup(unfinished)

    assert (item.id, item.status, item.host_extras) == (
        "extra:speech-lib[cloud-voice]",
        "missing",
        ("speech-cloud",),
    )
    assert model.missing_extras(unfinished) == ["speech-cloud"]
    assert model.blockers(unfinished) == [
        "/speech/module/voice_id: voice_id is required",
        f"speech: speech-lib[cloud-voice] — {item.detail}",
    ]

    monkeypatch.setattr(
        app_module,
        "requirement_status",
        lambda requirement: RequirementStatus(requirement, "installed"),
    )
    [installed] = model.check_setup(unfinished)
    assert (installed.status, installed.installable) == ("ready", False)


def _states(model: AppModel, config: dict[str, Any]) -> list[tuple[str, str]]:
    return [(i.id, i.status) for i in model.check_setup(config)]


def test_files_are_prepared_then_ready(tmp_path: Path, lib: SpeechLib) -> None:
    model = _model(tmp_path, lib)
    progress: list[dict[str, Any]] = []

    before = _states(model, DEFAULTS)
    outcomes = model.prepare(DEFAULTS, on_progress=progress.append)

    assert before == [
        ("extra:speech-lib[local-voice]", "ready"),
        ("weights:Ada", "missing"),
        ("lexicon", "missing"),
    ]
    assert _states(model, DEFAULTS) == [
        ("extra:speech-lib[local-voice]", "ready"),
        ("weights:Ada", "ready"),
        ("lexicon", "ready"),
    ]
    assert [(o.item.id, o.ok, o.message) for o in outcomes] == [
        ("weights:Ada", True, "Ready."),
        ("lexicon", True, "Ready."),
    ]
    # Each event names its item and section; each item's own events stay in order.
    for item in ("weights:Ada", "lexicon"):
        mine = [e for e in progress if e["id"] == item]
        assert [(e["section"], e["fraction"]) for e in mine] == [
            ("speech", 0.0),
            ("speech", 0.5),
            ("speech", 1.0),
        ]
    assert model.to_prepare(DEFAULTS) == []
    assert model.prepare(DEFAULTS) == []  # nothing left to prepare


def test_one_item_is_prepared_alone(tmp_path: Path, lib: SpeechLib) -> None:
    model = _model(tmp_path, lib)
    [weights] = [i for i in model.to_prepare(DEFAULTS) if i.id == "weights:Ada"]

    [outcome] = model.prepare(DEFAULTS, [weights])

    assert outcome.ok
    assert lib.started == ["weights:Ada"]
    assert _states(model, DEFAULTS)[1:] == [
        ("weights:Ada", "ready"),
        ("lexicon", "missing"),
    ]


def test_items_are_prepared_at_the_same_time(tmp_path: Path, lib: SpeechLib) -> None:
    model = _model(tmp_path, lib)
    lib.gate = threading.Event()
    done: list[list[Prepared]] = []
    worker = threading.Thread(target=lambda: done.append(model.prepare(DEFAULTS)))
    worker.start()

    # Both have started while neither can finish: they run side by side.
    deadline = time.monotonic() + 5
    while len(lib.started) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sorted(lib.started) == ["lexicon", "weights:Ada"]
    assert not done

    lib.gate.set()
    worker.join(timeout=5)
    assert [o.ok for o in done[0]] == [True, True]


def test_a_failed_item_fails_alone(tmp_path: Path, lib: SpeechLib) -> None:
    model = _model(tmp_path, lib)
    lib.failing = {"weights:Ada"}

    outcomes = model.prepare(DEFAULTS)

    assert [(o.item.id, o.ok, o.message) for o in outcomes] == [
        ("weights:Ada", False, "Could not get weights:Ada: the server is unreachable."),
        ("lexicon", True, "Ready."),
    ]
    assert _states(model, DEFAULTS)[1:] == [
        ("weights:Ada", "missing"),
        ("lexicon", "ready"),
    ]


def test_a_missing_item_that_is_not_required_does_not_block(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)
    lib.lexicon = True

    assert [i.id for i in model.deferred(DEFAULTS)] == ["weights:Ada"]
    assert model.blockers(DEFAULTS) == []  # the session downloads the voice itself


def test_an_item_outside_the_contract_is_refused(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)
    honest = lib.check_setup

    def without_required(config: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in i.items() if k != "required"}
            for i in honest(config, **kwargs)
        ]

    def neither(config: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {**i, "required": False, "preparable": False}
            for i in honest(config, **kwargs)
        ]

    lib.check_setup = without_required  # type: ignore[method-assign]
    with pytest.raises(ContractError, match=r"lacks \['required'\]"):
        model.check_setup(DEFAULTS)
    lib.check_setup = neither  # type: ignore[method-assign]
    with pytest.raises(ContractError, match="neither required nor preparable"):
        model.check_setup(DEFAULTS)


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


def test_a_key_item_is_told_the_variable_it_is_about(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)
    cloud = {
        "speech": {"module": {"type": "cloud-voice", "voice_id": "v"}},
    }
    renamed = {
        "speech": {
            "module": {"type": "cloud-voice", "voice_id": "v", "api_key_env": "MY_KEY"}
        },
    }

    def variables(config: dict[str, Any]) -> dict[str, str | None]:
        return {item.id: item.variable for item in model.check_setup(config)}

    assert variables(cloud) == {
        "extra:speech-lib[cloud-voice]": None,
        "key:CLOUD_VOICE_KEY": "CLOUD_VOICE_KEY",
    }
    assert variables(renamed)["key:MY_KEY"] == "MY_KEY"
    # Files are not keys, nor is an extra.
    assert set(variables(DEFAULTS).values()) == {None}


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

    # The voice is not required (the session downloads it); the lexicon is.
    assert model.blockers(DEFAULTS) == ["speech: Lexicon — Not built yet."]
    assert model.blockers({"speech": {"module": {"type": "cloud-voice"}}})[0] == (
        "/speech/module/voice_id: voice_id is required"
    )

    lib.lexicon = True
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


def test_a_draft_is_unsaved_until_it_is_saved(tmp_path: Path, lib: SpeechLib) -> None:
    model = _model(tmp_path, lib)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    # A change outside the sections the config uses still has to be saved.
    unused = {**DEFAULTS, "backup": {"module": {"type": "cloud-voice"}}}

    assert not model.unsaved(DEFAULTS)
    assert model.unsaved(cloud)
    assert model.unsaved(unused)

    model.save(cloud)
    assert not model.unsaved(cloud)
    assert model.unsaved(DEFAULTS)


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


def test_the_checks_can_be_asked_about_some_sections_only(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(
        tmp_path,
        lib,
        sections=(Section("speech", lib), Section("backup", SpeechLib())),
    )
    config = {**DEFAULTS, "backup": {"module": {"type": "cloud-voice"}}}

    assert model.check_config(config, ["speech"]) == []
    assert [p.section for p in model.check_config(config, ["backup"])] == ["backup"]
    assert {i.section for i in model.check_setup(config, ["speech"])} == {"speech"}
    assert all(
        reason.startswith(("/speech", "speech:"))
        for reason in model.blockers(config, ["speech"])
    )
    assert model.blockers(config, ["backup"])[0].startswith("/backup/module/voice_id")
    assert model.check_config(config) == model.check_config(config, ["backup"])


def test_the_library_is_told_the_app_s_folder_for_relative_paths(
    tmp_path: Path, lib: SpeechLib
) -> None:
    model = _model(tmp_path, lib)

    model.check_setup(DEFAULTS)
    model.prepare(DEFAULTS)
    model.options(DEFAULTS, "speech", "voices")
    model.probe(DEFAULTS, "speech")

    assert lib.base_dirs == {
        "check_setup": str(tmp_path),
        "prepare": str(tmp_path),
        "options": str(tmp_path),
        "probe": str(tmp_path),
    }
