import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import gradio as gr
import pytest
from fakes import SpeechLib
from gradio.components import Component

from app_setup import app as app_module
from app_setup.app import App, AppModel, Section
from app_setup.extras import RequirementStatus
from app_setup.folder import ConfigFolder
from app_setup.secrets import SecretStore
from app_setup.ui import secrets_panel, setup_panel, unsaved_notice
from app_setup.ui.form import render_section, section_title
from app_setup.ui.panels import (
    DRAFT,
    LOCKED,
    UNSAVED_BOTTOM,
    UNSAVED_SESSION,
    UNSAVED_TOP,
    _Actions,
    _draw_table,
    _line,
    _shape,
)

DEFAULTS = {"speech": {"module": {"type": "local-voice"}}}


def _model(
    tmp_path: Path,
    locked: Callable[[], bool] | None = None,
    environ: dict[str, str] | None = None,
    **app: Any,
) -> AppModel:
    application = App(
        name="talk",
        host="talk-app",
        sections=app.pop("sections", (Section("speech", SpeechLib()),)),
        default_config=DEFAULTS,
        **app,
    )
    folder = ConfigFolder(tmp_path, DEFAULTS)
    store = SecretStore(folder.env_path, {} if environ is None else environ)
    return AppModel(application, folder, store, locked)


def _drawn(model: AppModel, config: dict[str, Any]) -> list[Any]:
    """The components the form draws for *config*."""
    with gr.Blocks() as page:
        draft, revision = gr.State(config), gr.State(0)
        for name in model.used(config):
            render_section(model, name, config, draft, revision)
    return [block for block in page.blocks.values() if isinstance(block, Component)]


def _labels(components: list[Any]) -> list[str]:
    return [c.label for c in components if getattr(c, "label", None)]


def test_the_form_draws_the_selected_module_s_fields(tmp_path: Path) -> None:
    model = _model(tmp_path)
    config = {
        "speech": {"module": {"type": "cloud-voice", "voice_id": "v1", "api_key": "k"}}
    }

    components = _drawn(model, config)
    labels = _labels(components)

    assert labels[:2] == ["Voice", "voice_id *"]
    assert "speed" in labels and "api_key_env" in labels and "timeout" in labels
    assert "api_key" not in labels  # a key written in the config is never drawn
    assert "Configure gate" in labels
    voice_id = next(c for c in components if c.label == "voice_id *")
    assert voice_id.value == "v1"


def test_the_local_voice_gets_a_voice_list_and_an_enabled_gate_its_fields(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    config = {"speech": {"module": {"type": "local-voice"}, "gate": {"level": 3}}}

    components = _drawn(model, config)
    labels = _labels(components)

    assert "level" in labels and "loud" in labels
    assert any(
        isinstance(c, gr.Button) and c.value == "Choose from the voices list"
        for c in components
    )
    level = next(c for c in components if c.label == "level")
    assert level.value == "3"


def test_a_section_without_its_library_says_what_to_install(tmp_path: Path) -> None:
    def load() -> SpeechLib:
        raise ImportError("No module named 'speech_lib'")

    model = _model(
        tmp_path,
        sections=(Section("speech", load, title="Speech", host_extra="speech"),),
    )

    markdown = [c.value for c in _drawn(model, DEFAULTS) if isinstance(c, gr.Markdown)]

    assert section_title(model, "speech") == "Speech"
    assert any("the `speech` extra" in text for text in markdown)


def _handlers(page: gr.Blocks, name: str) -> list[Callable[..., Any]]:
    """Every function a panel registered under *name*, once each, in the order drawn (one
    per section for a section's own buttons)."""
    found: list[Callable[..., Any]] = []
    for f in page.fns.values():
        fn = f.fn
        if fn is not None and getattr(fn, "__name__", "") == name and fn not in found:
            found.append(fn)
    return found


def _handler(page: gr.Blocks, name: str) -> Callable[..., Any]:
    """The function a panel registered under *name* (for one event or several), to call as
    gradio would."""
    found = _handlers(page, name)
    assert len(found) == 1, found
    return found[0]


def test_the_panels_are_drawn_where_the_app_puts_them(tmp_path: Path) -> None:
    model = _model(tmp_path)

    with gr.Blocks() as page:
        with gr.Tab("Talk"):
            gr.Textbox(label="Say")
        with gr.Tab("Setup"):
            setup = setup_panel(model)
        with gr.Tab("Keys"):
            secrets_panel(model, setup.draft)

    tabs = [b.label for b in page.blocks.values() if isinstance(b, gr.Tab)]
    labels = _labels(list(page.blocks.values()))
    assert tabs == ["Talk", "Setup", "Keys"]  # the app's tabs, and only those
    assert "Say" in labels and "Variable" in labels
    assert "Section to test" not in labels  # each section has its own Test
    assert isinstance(setup.draft, gr.State) and isinstance(setup.saved, gr.State)


def test_the_setup_panel_greys_save_and_reset_while_the_app_locks_the_config(
    tmp_path: Path,
) -> None:
    running = [False]
    with gr.Blocks() as page:
        setup_panel(_model(tmp_path, locked=lambda: running[0]))
    tick = _handler(page, "on_tick")

    assert tick(DEFAULTS, 1, 0)[0] == ""
    running[0] = True
    note, save, reset = tick(DEFAULTS, 1, 0)[:3]
    assert note == LOCKED
    assert save["interactive"] is False and reset["interactive"] is False


def test_the_secrets_panel_reads_the_config_it_follows_else_the_saved_one(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}

    with gr.Blocks() as following:
        secrets_panel(model, gr.State(cloud))
    with gr.Blocks() as alone:
        secrets_panel(model)

    assert "`CLOUD_VOICE_KEY`" in _handler(following, "on_load")(cloud)[0]
    assert "names no environment variable" in _handler(alone, "on_load")()[0]
    model.save(cloud)
    assert "`CLOUD_VOICE_KEY`" in _handler(alone, "on_load")()[0]


def test_the_secrets_panel_keeps_the_env_file_s_variables_out_of_the_config_s_table(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    model.secrets.set("CLOUD_VOICE_KEY", "s3cret-one")
    model.secrets.set("OLD_KEY", "s3cret-two")
    with gr.Blocks() as page:
        secrets_panel(model, gr.State(cloud))

    text = _handler(page, "on_load")(cloud)[0]

    assert "| `CLOUD_VOICE_KEY` | ✅ the folder's .env |" in text
    assert "OLD_KEY" not in text  # listed with the .env's own variables instead
    assert "s3cret" not in text  # names only, never a value


def test_each_section_has_its_own_checks_acting_on_it_alone(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        sections=(
            Section("speech", SpeechLib(), title="Speech"),
            Section(
                "backup",
                SpeechLib(),
                title="Backup voice",
                when=lambda config: bool(config.get("use_backup")),
            ),
        ),
    )
    # The backup voice's config has a problem; the main voice's has none.
    config = {
        **DEFAULTS,
        "use_backup": True,
        "backup": {"module": {"type": "cloud-voice"}},
    }
    with gr.Blocks() as page:
        setup_panel(model)

    buttons = [b.value for b in page.blocks.values() if isinstance(b, gr.Button)]
    speech_check, backup_check = _handlers(page, "on_check")
    speech_problems, _, speech_items, _ = speech_check(config)
    # A check finding what the last one found leaves the table as it is (not redrawn).
    assert speech_check(config)[2] == speech_items
    backup_problems, _, _, _ = backup_check(config)

    assert buttons.count("Test") == 2 and buttons.count("Prepare all") == 2
    assert "voice_id" not in speech_problems
    assert "/backup/module/voice_id" in backup_problems
    # The rows are drawn from the section's own items.
    assert [i.id for i in speech_items] == [
        "extra:speech-lib[local-voice]",
        "weights:Ada",
        "lexicon",
    ]

    # A section the config does not use is hidden, the others shown and checked. Each
    # section: its block, its problems, its summary, its items, its lines, its output.
    redraw = _handler(page, "on_redraw")
    shown = redraw(config)
    hidden = redraw({**config, "use_backup": False})
    assert (shown[0]["visible"], shown[6]["visible"]) == (True, True)
    assert (hidden[0]["visible"], hidden[6]["visible"]) == (True, False)
    assert "/backup/module/voice_id" in shown[7]
    assert hidden[7] == "" and hidden[9] == ()


def test_an_app_with_autostart_gets_its_checkbox_saved_at_once(tmp_path: Path) -> None:
    model = _model(tmp_path, autostart=True)
    with gr.Blocks() as page:
        setup_panel(model)
    with gr.Blocks() as without:
        setup_panel(_model(tmp_path / "other"))

    (checkbox,) = [b for b in page.blocks.values() if isinstance(b, gr.Checkbox)]
    loaded = _handler(page, "on_launch_load")()
    note = _handler(page, "on_autostart")(False)

    assert checkbox.label == "Start the session when the app launches"
    assert loaded is True  # the app's default, until the user chooses
    assert note == "The session will not start when the app launches."
    assert model.autostart() is False
    assert not [b for b in without.blocks.values() if isinstance(b, gr.Checkbox)]

    # The launch choice comes first, then the "Configuration" title over the config.
    drawn = list(page.blocks.values())
    assert drawn.index(checkbox) < drawn.index(_markdown(drawn, "### Configuration"))


def _markdown(drawn: list[Any], text: str) -> Any:
    return next(b for b in drawn if isinstance(b, gr.Markdown) and b.value == text)


def test_the_config_is_tried_in_the_sections_and_saved_at_the_bottom(
    tmp_path: Path,
) -> None:
    for autostart in (True, None):
        with gr.Blocks() as page:
            setup_panel(
                _model(
                    tmp_path / str(autostart),
                    autostart=autostart,
                    sections=(
                        Section("speech", SpeechLib()),
                        Section("backup", SpeechLib()),
                    ),
                )
            )
        drawn = list(page.blocks.values())
        buttons = [b for b in drawn if isinstance(b, gr.Button)]
        save = next(b for b in buttons if b.value == "Save")
        tests = [drawn.index(b) for b in buttons if b.value == "Test"]

        # The title and the line saying which config the buttons try, then both
        # sections' blocks, then Save, Revert and Reset.
        title = drawn.index(_markdown(drawn, "### Configuration"))
        line = drawn.index(_markdown(drawn, DRAFT))
        assert len(tests) == 2
        assert title < line < min(tests) and max(tests) < drawn.index(save)
        revert = next(b for b in buttons if b.value == "Revert to saved")
        assert drawn.index(save) < drawn.index(revert)


def test_the_unsaved_lines_say_when_the_draft_differs_from_the_saved_config(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    with gr.Blocks() as page:
        setup_panel(model)
    on_draft, on_save = _handler(page, "on_draft"), _handler(page, "on_save")

    assert on_draft(DEFAULTS, 1) == ("", "")
    assert on_draft(cloud, 1) == (UNSAVED_TOP, UNSAVED_BOTTOM)
    assert on_draft(cloud, 0) == ("", "")  # the draft not loaded yet: nothing to say
    assert unsaved_notice(model, cloud) == UNSAVED_SESSION
    assert unsaved_notice(model, {}) == ""

    notice, _, *lines = on_save(cloud, 0, 1)

    assert notice == "✅ Saved." and lines == ["", ""]
    assert on_draft(DEFAULTS, 1) == (UNSAVED_TOP, UNSAVED_BOTTOM)
    assert unsaved_notice(model, cloud) == ""
    # A config with a problem is saved all the same, nothing lost, and Save says it
    # cannot run yet.
    no_voice = {"speech": {"module": {"type": "cloud-voice"}}}
    notice, _, *lines = on_save(no_voice, 1, 1)
    assert notice.startswith("⚠️ Saved, with 1 problem in the config")
    assert model.saved_config() == no_voice and lines == ["", ""]
    model.save(cloud)
    # Another tab saved: this tab's timer sees its draft differ now.
    model.save(DEFAULTS)
    assert _handler(page, "on_tick")(cloud, 1, 0)[3:5] == [UNSAVED_TOP, UNSAVED_BOTTOM]


def _listeners(page: gr.Blocks, component: Any) -> dict[str, Any]:
    """The function each event of *component* runs, by event name."""
    return {
        event: f
        for f in page.fns.values()
        for target, event in f.targets
        if target == component._id
    }


def _environ(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """An empty process environment, where the store puts its keys and the fake library
    reads them."""
    environ: dict[str, str] = {}
    monkeypatch.setattr(os, "environ", environ)
    return environ


def test_a_field_left_checks_its_section_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _model(tmp_path, environ=_environ(monkeypatch))
    model.secrets.set("OTHER_KEY", "s3cret")
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}

    # The form as the panel draws it, with the section's `edited` counter.
    with gr.Blocks() as form:
        draft, revision, edited = gr.State(cloud), gr.State(0), gr.State(0)
        render_section(model, "speech", cloud, draft, revision, edited)
    key_env = next(
        b for b in form.blocks.values() if getattr(b, "label", None) == "api_key_env"
    )
    listeners = _listeners(form, key_env)
    with gr.Blocks() as panel:
        setup_panel(model)
    (on_edited,) = _handlers(panel, "on_edited")

    # Each keystroke writes the value without counting an edit; leaving the field or
    # pressing Enter writes it and counts one, which checks the section again.
    typed = listeners["input"].fn("OTHER_KEY", cloud)
    left, count = listeners["blur"].fn("OTHER_KEY", cloud, 0)
    assert typed == left
    assert listeners["submit"].fn is listeners["blur"].fn
    assert count == 1 and edited in listeners["blur"].outputs

    _, summary, items, _ = on_edited(left)
    key = next(i for i in items if i.id == "key:OTHER_KEY")
    assert key.status == "ready" and summary == "✅ **Ready**"
    assert on_edited(cloud)[2][-1].status == "missing"  # CLOUD_VOICE_KEY, unset


def test_the_timer_checks_again_after_a_key_was_saved_and_only_then(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _model(tmp_path, environ=_environ(monkeypatch))
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    with gr.Blocks() as page:
        setup_panel(model)
    tick = _handler(page, "on_tick")
    seen = model.secrets.revision

    # Nothing written since the tab looked: no check, its seen revision kept.
    quiet = tick(cloud, 1, seen)
    assert all(isinstance(u, dict) and u.get("__type__") == "update" for u in quiet[5:])

    model.secrets.set("CLOUD_VOICE_KEY", "s3cret")  # from the Secrets panel, say
    seen_now, problems, summary, items, _ = tick(cloud, 1, seen)[5:]

    assert seen_now == model.secrets.revision != seen
    assert "valid" in problems and summary == "✅ **Ready**"
    assert all(i.status == "ready" for i in items)
    # Seen: the next tick checks nothing again.
    assert tick(cloud, 1, seen_now)[6:] == quiet[6:]


def test_a_field_not_set_shows_its_default_greyed_and_a_set_one_its_value(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    unset = {"speech": {"module": {"type": "local-voice"}, "gate": {}}}
    set_ = {
        "speech": {
            "module": {"type": "local-voice", "timeout": 3, "voice": "Bo"},
            "gate": {"loud": True},
        }
    }

    def drawn(config: dict[str, Any]) -> dict[str, Any]:
        return {c.label: c for c in _drawn(model, config) if getattr(c, "label", None)}

    empty, filled = drawn(unset), drawn(set_)

    # A number not set is an empty box with its default greyed, like text: never a
    # value that looks set. Its range is in its hint.
    assert isinstance(empty["timeout"], gr.Textbox)
    assert (empty["timeout"].value, empty["timeout"].placeholder) == ("", "10")
    assert (empty["voice"].value, empty["voice"].placeholder) == ("", "Ada")
    assert (filled["timeout"].value, filled["voice"].value) == ("3", "Bo")
    # A checkbox shows one state: unset, its hint says the default applies.
    assert "Not set: the default (off) applies." in empty["loud"].info
    assert "Not set" not in filled["loud"].info


def test_prepare_all_runs_the_lines_side_by_side_each_ending_on_its_own(
    tmp_path: Path,
) -> None:
    lib = SpeechLib()
    lib.gate = threading.Event()
    lib.failing = {"weights:Ada"}
    model = _model(tmp_path, sections=(Section("speech", lib),))
    actions = _Actions(model)
    weights, lexicon = model.to_prepare(DEFAULTS)

    for item in (weights, lexicon):
        assert actions.start(DEFAULTS, item)
    assert not actions.start(DEFAULTS, weights)  # never twice at once
    _wait(lambda: len(lib.started) == 2)

    # Both running at once, each line on its own progress, its Prepare disabled.
    for item in (weights, lexicon):
        status, explanation, button = _line(actions, item)
        assert status == "⏳ **Preparing… 0%**" and "Starting" in explanation
        assert button == {"visible": True, "interactive": False}
    assert actions.running("speech")

    lib.gate.set()
    _wait(lambda: not actions.running("speech"))

    failed_status, failed_why, failed_button = _line(actions, weights)
    ready_status, _, ready_button = _line(actions, lexicon)
    assert failed_status == "❌ **Failed**"
    assert failed_why.startswith("Could not get weights:Ada")
    assert failed_button == {"visible": True, "interactive": True}  # tried again
    assert ready_status == "✅ **Ready**"
    assert ready_button["visible"] is False
    assert lib.lexicon and "Ada" not in lib.downloaded


def test_a_busy_section_disables_its_lines(tmp_path: Path) -> None:
    model = _model(tmp_path)
    actions = _Actions(model)
    [_, lexicon] = model.to_prepare(DEFAULTS)

    actions.busy.add("speech")  # a Check, an Install all or a Test running

    assert _line(actions, lexicon)[2] == {"visible": True, "interactive": False}


def _wait(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


@pytest.fixture
def installer(monkeypatch: pytest.MonkeyPatch) -> "FakeInstaller":
    """The host's extras faked (`speech-local` carries the local voice's extra, which is
    missing), and an installer that records each run and waits on a gate a test opens."""
    carriers = {
        "speech-lib[local-voice]": "speech-local",
        "speech-lib[cloud-voice]": "speech-cloud",
        "speech-lib[gate]": "speech-gate",
    }
    monkeypatch.setattr(
        app_module,
        "host_extras",
        lambda requirement, *, host: (
            (carriers[requirement],) if requirement in carriers else ()
        ),
    )
    monkeypatch.setattr(
        app_module,
        "requirement_status",
        lambda requirement: RequirementStatus(requirement, "missing"),
    )
    fake = FakeInstaller()
    monkeypatch.setattr(app_module, "find_installer", lambda host: fake)
    return fake


class FakeInstaller:
    def __init__(self) -> None:
        self.runs: list[list[str]] = []
        self.gates: list[threading.Event] = []
        self.fail = False

    def install(self, extras: list[str], on_output: Any = None) -> int:
        gate = threading.Event()
        self.gates.append(gate)
        self.runs.append(list(extras))
        if on_output is not None:
            on_output(f"Resolved {len(extras)} extra(s)")
        assert gate.wait(timeout=5), "the test never opened the gate"
        return 1 if self.fail else 0


class TwoExtras(SpeechLib):
    """A library whose config needs two extras, both missing."""

    def check_setup(
        self, config: dict[str, Any], *, base_dir: str | None = None
    ) -> list[dict[str, Any]]:
        gate = {
            "id": "extra:speech-lib[gate]",
            "title": "gate extra",
            "status": "missing",
            "detail": "pip install 'speech-lib[gate]'",
            "preparable": False,
            "required": True,
        }
        return [gate, *super().check_setup(config, base_dir=base_dir)]


def _table(model: AppModel, actions: _Actions, config: dict[str, Any]) -> gr.Blocks:
    """A section's table drawn in a page, as its `gr.render` draws it, with what a
    check updates."""
    with gr.Blocks() as page:
        draft = gr.State(config)
        checks = (gr.Markdown(), gr.Markdown(), gr.State(()), gr.State(()))

        def reports(config: dict[str, Any]) -> tuple[Any, ...]:
            items = model.check_setup(config, ["speech"])
            return "", "", tuple(items), _shape(items)

        _draw_table(
            model,
            actions,
            model.check_setup(config, ["speech"]),
            draft,
            checks,
            reports,
            gr.Timer(0.5),
        )
    return page


def _cells(page: gr.Blocks) -> list[str]:
    """The table's text, cell by cell (the empty check outputs left out)."""
    return [
        b.value for b in page.blocks.values() if isinstance(b, gr.Markdown) and b.value
    ]


def test_the_table_has_a_line_per_item_with_its_action(
    tmp_path: Path, installer: FakeInstaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = SpeechLib()
    lib.installed["local-voice"] = False
    model = _model(tmp_path, sections=(Section("speech", lib),))
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    _environ(monkeypatch)

    local = _table(model, _Actions(model), DEFAULTS)
    keyed = _table(model, _Actions(model), cloud)

    cells = _cells(local)
    assert cells[:4] == ["**Item**", "**Status**", "**Explanation**", "**Action**"]
    assert cells[4:7] == [
        "**local-voice extra**",
        "❌ **Missing – required**",
        (
            "pip install 'speech-lib[local-voice]' **Install** adds it (the "
            "`speech-local` extra)."
        ),
    ]
    assert [b.value for b in local.blocks.values() if isinstance(b, gr.Button)] == [
        "Install"
    ]
    # The cloud voice's extra is there; its key is missing: a field and Save.
    assert "**CLOUD_VOICE_KEY**" in _cells(keyed)
    (field_,) = [b for b in keyed.blocks.values() if isinstance(b, gr.Textbox)]
    assert field_.type == "password" and field_.placeholder == "CLOUD_VOICE_KEY"
    assert [b.value for b in keyed.blocks.values() if isinstance(b, gr.Button)] == [
        "Save"
    ]


def test_installs_run_one_at_a_time_the_second_waiting_its_turn(
    tmp_path: Path, installer: FakeInstaller
) -> None:
    lib = TwoExtras()
    lib.installed["local-voice"] = False
    model = _model(tmp_path, sections=(Section("speech", lib),))
    actions = _Actions(model)
    gate, local = model.check_setup(DEFAULTS)[:2]

    first = actions.install([gate], ["speech-gate"])
    _wait(lambda: len(installer.runs) == 1)
    second = actions.install([local], ["speech-local"])
    assert first is not None and second is not None
    assert actions.install([local], ["speech-local"]) is None  # never twice at once

    status, explanation, _ = _line(actions, gate)
    assert status == "⏳ **Installing…**"
    assert explanation.startswith(
        "uv: Resolved 1 extra(s) ("
    )  # uv's latest line, the time
    assert _line(actions, local)[:2] == (
        "⏳ **Waiting**",
        "Waiting for another install…",
    )
    assert _line(actions, local)[2]["interactive"] is False

    installer.gates[0].set()
    _wait(lambda: len(installer.runs) == 2)  # the second starts once the first is done
    assert _line(actions, gate)[:2] == ("✅ **Ready**", "Installed.")
    assert _line(actions, local)[0] == "⏳ **Installing…**"
    installer.fail = True
    installer.gates[1].set()
    assert second.done.wait(timeout=5)

    assert installer.runs == [["speech-gate"], ["speech-local"]]
    assert _line(actions, local)[:2] == (
        "❌ **Failed**",
        "uv exited with code 1. **Install** tries again.",
    )


def test_install_all_installs_every_missing_extra_in_one_run(
    tmp_path: Path, installer: FakeInstaller
) -> None:
    lib = TwoExtras()
    lib.installed["local-voice"] = False
    model = _model(tmp_path, sections=(Section("speech", lib),))
    with gr.Blocks() as page:
        setup_panel(model)
    install_all = _handler(page, "on_install_all")(DEFAULTS)

    first = next(install_all)
    _wait(lambda: len(installer.runs) == 1)
    installer.gates[0].set()
    *_, (output, _, summary, _, _) = [first, *install_all]

    assert installer.runs == [["speech-gate", "speech-local"]]
    assert output["value"].startswith("Installing: speech-gate, speech-local")
    assert output["value"].endswith("Done.")
    assert summary.startswith("❌ **2 required items missing**")  # the fake stays so


def test_an_extra_installed_from_its_line_checks_the_section_again(
    tmp_path: Path, installer: FakeInstaller
) -> None:
    lib = SpeechLib()
    lib.installed["local-voice"] = False
    model = _model(tmp_path, sections=(Section("speech", lib),))
    actions = _Actions(model)
    page = _table(model, actions, DEFAULTS)
    (on_install,) = _handlers(page, "on_install")

    def release() -> None:
        _wait(lambda: len(installer.runs) == 1)
        lib.installed["local-voice"] = True  # what the install did
        installer.gates[0].set()

    threading.Thread(target=release).start()
    _, _, items, _ = on_install(DEFAULTS)

    assert installer.runs == [["speech-local"]]
    assert items[0].status == "ready"


def test_a_key_saved_on_its_line_reaches_the_store_and_turns_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environ = _environ(monkeypatch)
    model = _model(tmp_path, environ=environ)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    page = _table(model, _Actions(model), cloud)
    (on_save_key,) = _handlers(page, "on_save_key")
    seen = model.secrets.revision

    cleared, _, _, items, _ = on_save_key("s3cret", cloud)

    assert cleared == ""  # the value is never shown back
    assert model.secrets.file_names() == ["CLOUD_VOICE_KEY"]
    assert environ["CLOUD_VOICE_KEY"] == "s3cret"
    assert model.secrets.revision != seen  # every tab checks again
    key = next(i for i in items if i.variable == "CLOUD_VOICE_KEY")
    assert key.status == "ready"
