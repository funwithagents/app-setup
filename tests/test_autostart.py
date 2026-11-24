import argparse
from pathlib import Path
from typing import Any

import pytest
from fakes import SpeechLib

from module_setup.app import App, AppModel, Section
from module_setup.autostart import (
    add_start_arguments,
    autostart_section,
    starts_at_launch,
)
from module_setup.contract import check_contract, parse_description
from module_setup.folder import ConfigFolder
from module_setup.secrets import SecretStore

SPEECH = {"module": {"type": "local-voice"}}


def _model(
    tmp_path: Path,
    sections: tuple[Section, ...],
    saved: dict[str, Any] | None = None,
) -> AppModel:
    defaults = {"speech": SPEECH, "app": {"autostart": True}}
    app = App(name="talk", host="talk-app", sections=sections, default_config=defaults)
    folder = ConfigFolder(tmp_path, defaults)
    model = AppModel(app, folder, SecretStore(folder.env_path, {}))
    if saved is not None:
        model.save(saved)
    return model


def test_the_section_honours_the_module_contract() -> None:
    section = autostart_section()

    check_contract(
        section.contract,  # type: ignore[arg-type]
        [{"autostart": True}, {"autostart": False}, {}],
    )


@pytest.mark.parametrize("default", [True, False])
def test_the_schema_s_default_follows_the_section_s(default: bool) -> None:
    section = autostart_section(default=default)

    description = parse_description(section.contract.config_schema())  # type: ignore[union-attr]

    (field,) = description.schema.properties
    assert field.name == "autostart"
    assert field.has_default and field.default is default  # type: ignore[union-attr]


def test_the_section_refuses_anything_but_a_boolean(tmp_path: Path) -> None:
    model = _model(tmp_path, (autostart_section(),))

    problems = model.check_config({"app": {"autostart": "yes"}})

    assert [(p.path, p.message) for p in problems] == [
        ("/app/autostart", "Must be true or false.")
    ]
    assert model.blockers({"app": {"autostart": False}}) == []


def test_the_section_takes_the_name_and_title_it_is_given(tmp_path: Path) -> None:
    model = _model(tmp_path, (autostart_section(name="demo", title="Demo"),))

    problems = model.check_config({"demo": {"autostart": 1}})

    assert [p.path for p in problems] == ["/demo/autostart"]
    assert model.section("demo").title == "Demo"


@pytest.mark.parametrize("flag", [True, False])
def test_the_flag_wins_over_the_saved_config(tmp_path: Path, flag: bool) -> None:
    model = _model(
        tmp_path,
        (Section("speech", SpeechLib()), autostart_section()),
        saved={"speech": SPEECH, "app": {"autostart": not flag}},
    )

    assert starts_at_launch(model, flag) is flag


@pytest.mark.parametrize("saved", [True, False])
def test_without_a_flag_the_saved_config_decides(tmp_path: Path, saved: bool) -> None:
    model = _model(
        tmp_path,
        (Section("speech", SpeechLib()), autostart_section(default=not saved)),
        saved={"speech": SPEECH, "app": {"autostart": saved}},
    )

    assert starts_at_launch(model, None) is saved


def test_the_saved_config_is_read_at_the_section_s_own_name(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        (autostart_section(default=True, name="demo"),),
        saved={"app": {"autostart": True}, "demo": {"autostart": False}},
    )

    assert starts_at_launch(model, None) is False


@pytest.mark.parametrize("default", [True, False])
def test_a_config_without_the_section_falls_back_to_its_default(
    tmp_path: Path, default: bool
) -> None:
    sections = (Section("speech", SpeechLib()), autostart_section(default=default))

    assert (
        starts_at_launch(_model(tmp_path, sections, {"speech": SPEECH}), None)
        is default
    )
    assert (
        starts_at_launch(
            _model(tmp_path, sections, {"speech": SPEECH, "app": {}}), None
        )
        is default
    )


def test_an_app_without_the_section_does_not_start_unless_told(tmp_path: Path) -> None:
    model = _model(
        tmp_path, (Section("speech", SpeechLib()),), saved={"speech": SPEECH}
    )

    assert starts_at_launch(model, None) is False
    assert starts_at_launch(model, True) is True


@pytest.mark.parametrize(
    ("argv", "start"), [(["--start"], True), (["--no-start"], False), ([], None)]
)
def test_the_start_arguments(argv: list[str], start: bool | None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    add_start_arguments(parser)

    options = parser.parse_args([*argv, "--port", "8000"])

    assert options.start is start
    assert options.port == 8000
