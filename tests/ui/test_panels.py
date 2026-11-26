import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gradio as gr
import pytest
from fakes import SpeechLib
from gradio.components import Component

from app_setup import app as app_module
from app_setup.app import App, AppModel, Section
from app_setup.config_file import ConfigFile
from app_setup.extras import RequirementStatus
from app_setup.folder import ConfigFolder
from app_setup.secrets import SecretStore
from app_setup.ui import secrets_panel, setup_panel, unsaved_notice
from app_setup.ui.form import render_section, section_title
from app_setup.ui.panels import (
    DRAFT,
    LOCKED,
    READ_ONLY,
    UNSAVED_BOTTOM,
    UNSAVED_SESSION,
    UNSAVED_TOP,
    _Actions,
    _draw_rows,
    _line,
    _table_lines,
    _wire_table,
)
from app_setup.ui.report import CHECKING_NOTE, INSTALLING_NOTE

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
        draft = gr.State(config)
        revision = gr.Number(0, precision=0, visible=False)
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

    first = tick(DEFAULTS, 1, 0, None)
    assert first[0] == ""
    running[0] = True
    note, save, reset = tick(DEFAULTS, 1, 0, first[-1])[:3]
    assert note == LOCKED
    assert save["interactive"] is False and reset["interactive"] is False
    # Unchanged since the last tick: nothing sent, the browser left alone.
    again = tick(DEFAULTS, 1, 0, tick(DEFAULTS, 1, 0, first[-1])[-1])
    assert again[:5] == [gr.skip()] * 5


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


def test_the_secrets_panel_follows_a_key_saved_elsewhere_without_a_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _model(tmp_path, environ=_environ(monkeypatch))
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    with gr.Blocks() as page:
        secrets_panel(model, gr.State(cloud))
    tick = _handler(page, "on_secrets_tick")

    # The page loads: its table, and the store's revision that table shows.
    shown, _, seen, _ = _handler(page, "on_load")(cloud)
    assert "❌ not set" in shown
    assert tick(seen, 1, cloud) == (gr.skip(),) * 4  # nothing new

    # A key saved on a line of the Setup panel, or in another tab: the same store. Even
    # when the timer's first tick comes after it (a tab not opened yet), it is seen.
    model.secrets.set("CLOUD_VOICE_KEY", "s3cret")
    report, revision, now, _ = tick(seen, 1, cloud)

    assert "`CLOUD_VOICE_KEY`" in report and "the folder's .env" in report
    assert "not set" not in report
    assert revision == 2 and now == model.secrets.revision  # the .env list drawn again


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
    speech_problems, _, speech_items, *_ = speech_check(config)
    # A check finding what the last one found leaves the table as it is (not redrawn).
    assert speech_check(config)[2] == speech_items
    backup_problems, *_ = backup_check(config)

    assert buttons.count("Test") == 2 and buttons.count("Prepare all") == 2
    assert "voice_id" not in speech_problems
    assert "/backup/module/voice_id" in backup_problems
    # The rows are drawn from the section's own items.
    assert [i.id for i in speech_items] == [
        "extra:speech-lib[local-voice]",
        "weights:Ada",
        "lexicon",
    ]

    # A section the config does not use is hidden, the others shown and checked.
    shown = _redraw(page, model, "backup", config)
    hidden = _redraw(page, model, "backup", {**config, "use_backup": False})
    assert shown.fold["visible"] is True and "/backup/module/voice_id" in shown.problems
    assert hidden.fold["visible"] is False
    assert (hidden.problems, hidden.items) == ("", ())


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
        # The config's Save, the last one: each row's key has its own above.
        save = [b for b in buttons if b.value == "Save"][-1]
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
    assert _handler(page, "on_tick")(cloud, 1, 0, None)[3:5] == [
        UNSAVED_TOP,
        UNSAVED_BOTTOM,
    ]


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
        draft, edited = gr.State(cloud), gr.State(0)
        revision = gr.Number(0, precision=0, visible=False)
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

    _, summary, items, *_ = on_edited(left)
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
    quiet = tick(cloud, 1, seen, None)
    assert all(
        isinstance(u, dict) and u.get("__type__") == "update" for u in quiet[5:-1]
    )

    model.secrets.set("CLOUD_VOICE_KEY", "s3cret")  # from the Secrets panel, say
    seen_now, problems, summary, items, _ = tick(cloud, 1, seen, None)[5:-2]

    assert seen_now == model.secrets.revision != seen
    assert "valid" in problems and summary == "✅ **Ready**"
    assert all(i.status == "ready" for i in items)
    # Seen: the next tick checks nothing again.
    assert tick(cloud, 1, seen_now, None)[6:-1] == quiet[6:-1]


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


def test_the_rows_timer_runs_only_while_a_line_is_acted_on(tmp_path: Path) -> None:
    lib = SpeechLib()
    lib.gate = threading.Event()
    model = _model(tmp_path, sections=(Section("speech", lib),))
    with gr.Blocks() as page:
        setup_panel(model)
    on_button = _handlers(page, "on_button")[0]  # one per row; the row given below
    items = tuple(model.check_setup(DEFAULTS))
    weights = next(i for i, item in enumerate(items) if item.id == "weights:Ada")

    def tick(items: Any) -> list[Any]:  # one for the whole panel
        return _rows_tick(page, DEFAULTS, items)

    # At rest: nothing sent, and the timer turns itself off.
    *rows, timer = tick(items)
    assert rows == [gr.skip()] * len(rows) and timer.active is False

    # A line's Prepare turns the timer on; each tick sends that line only.
    assert on_button(items, DEFAULTS, index=weights)[-1].active is True
    *rows, timer = tick(items)
    sent = [i for i, update in enumerate(rows) if update != gr.skip()]
    assert sent == [2 * weights, 2 * weights + 1]
    assert "⏳ <strong>Preparing" in rows[2 * weights] and timer.active is True

    # Done: the last tick shows how it ended, and turns the timer off.
    lib.gate.set()
    _wait(lambda: lib.downloaded == {"Ada"})
    _wait(lambda: tick(items)[-1].active is False)
    assert "✅ <strong>Ready</strong>" in tick(items)[2 * weights]


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


def _table(model: AppModel, actions: _Actions) -> gr.Blocks:
    """A section's table drawn and wired in a page, with what a check updates."""
    with gr.Blocks() as page:
        draft = gr.State({})
        checked = gr.State(())
        checks = (gr.Markdown(), gr.Markdown(), checked)

        def reports(config: dict[str, Any]) -> tuple[Any, ...]:
            return "", "", tuple(model.check_setup(config, ["speech"]))

        _wire_table(
            model, actions, _draw_rows(), draft, checked, checks, reports, gr.Timer(0.5)
        )
    return page


def _row(updates: list[Any], index: int) -> list[Any]:
    """Row *index*'s updates in `_table_lines`: shown, its cells (the item, its status,
    its explanation), its button, its key field, its key's Save."""
    start = 1 + 5 * index
    return updates[start : start + 5]


def test_the_table_has_a_line_per_item_with_its_action(
    tmp_path: Path, installer: FakeInstaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    lib = SpeechLib()
    lib.installed["local-voice"] = False
    model = _model(tmp_path, sections=(Section("speech", lib),))
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    _environ(monkeypatch)
    actions = _Actions(model)

    local = _table_lines(actions, model.check_setup(DEFAULTS))
    keyed_items = model.check_setup(cloud)
    keyed = _table_lines(actions, keyed_items)

    assert local[0]["visible"] is True  # the header
    shown, cells, button, key, save = _row(local, 0)
    assert shown["visible"] and "<strong>local-voice extra</strong>" in cells
    assert "❌ <strong>Missing – required</strong>" in cells
    assert (
        "pip install &#x27;speech-lib[local-voice]&#x27; <strong>Install</strong> adds "
        "it (the <code>speech-local</code> extra)."
    ) in cells
    assert (button["value"], button["visible"]) == ("Install", True)
    assert (key["visible"], save["visible"]) == (False, False)
    assert _row(local, 1)[0]["visible"] is False  # one item: the other rows hidden
    # The cloud voice's extra is there; its key is missing: a field and Save, no button.
    index = next(i for i, item in enumerate(keyed_items) if item.variable)
    _, cells, button, key, save = _row(keyed, index)
    assert "<strong>CLOUD_VOICE_KEY</strong>" in cells
    assert key["visible"] and key["placeholder"] == "CLOUD_VOICE_KEY"
    assert key["value"] == "" and save["visible"] and not button["visible"]
    # Checked again with the same items: a key being typed on its line is kept.
    again = _row(_table_lines(actions, keyed_items, keyed_items), index)
    assert "value" not in again[3]


def test_the_rows_are_drawn_once_so_no_listener_is_ever_dropped(
    tmp_path: Path,
) -> None:
    model = _model(tmp_path)
    with gr.Blocks() as page:
        setup_panel(model)
    before = set(page.fns)

    # The table's rows and their listeners are the page's own, not a render's: a check,
    # whatever it finds, adds or removes none.
    assert _handlers(page, "on_rows_tick") and _handlers(page, "on_button")
    assert set(page.fns) == before
    for fn in page.fns.values():
        name = getattr(fn.fn, "__name__", "")
        if name in ("on_rows_tick", "on_button", "on_save_key", "on_checked"):
            assert fn.rendered_in is None


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
    assert explanation == f"uv: Resolved 1 extra(s). {INSTALLING_NOTE}"
    assert _line(actions, local)[:2] == (
        "⏳ **Waiting**",
        f"Waiting for another install… {INSTALLING_NOTE}",
    )
    assert _line(actions, local)[2]["interactive"] is False

    installer.gates[0].set()
    _wait(lambda: len(installer.runs) == 2)  # the second starts once the first is done
    assert _line(actions, gate)[:2] == ("✅ **Ready**", CHECKING_NOTE)
    assert _line(actions, local)[0] == "⏳ **Installing…**"
    installer.fail = True
    installer.gates[1].set()
    assert second.done.wait(timeout=5)

    assert installer.runs == [["speech-gate"], ["speech-local"]]
    assert _line(actions, local)[:2] == (
        "❌ **Failed**",
        "uv exited with code 1. **Install** tries again.",
    )


def _rows_tick(page: gr.Blocks, config: dict[str, Any], *checked: Any) -> list[Any]:
    """The rows' timer's tick for a one-section panel: the rows' cells and buttons, the
    section's checks (problems, summary, items, fold), its output box, then the timer."""
    return _handler(page, "on_rows_tick")(config, *checked)


def test_install_all_installs_every_missing_extra_in_one_run_never_waited_for(
    tmp_path: Path, installer: FakeInstaller
) -> None:
    lib = TwoExtras()
    lib.installed["local-voice"] = False
    model = _model(tmp_path, sections=(Section("speech", lib),))
    with gr.Blocks() as page:
        setup_panel(model)
    items = tuple(model.check_setup(DEFAULTS))

    # Started, and returned at once: no event stays open while packages land.
    output, *_, timer = _handler(page, "on_install_all")(DEFAULTS)
    assert output["value"].startswith("Installing: speech-gate, speech-local")
    assert timer.active is True
    _wait(lambda: len(installer.runs) == 1)
    # The rows' timer follows it: its lines, its output box.
    *_, box, timer = _rows_tick(page, DEFAULTS, items)
    assert box["value"].splitlines() == [
        "Installing: speech-gate, speech-local",
        "Resolved 2 extra(s)",
        INSTALLING_NOTE,
    ]
    assert timer.active is True

    lib.installed["local-voice"] = True  # what the install did
    installer.gates[0].set()
    # Ended well: first shown on its lines and in its box, the timer still on...
    shown: list[Any] = []

    def ended() -> bool:
        shown[:] = _rows_tick(page, DEFAULTS, items)
        return "Checking the section again" in shown[0]

    _wait(ended)
    *_, box, timer = shown
    assert box["value"].splitlines() == [
        "Installing: speech-gate, speech-local",
        "Resolved 2 extra(s)",
        "Done.",
        CHECKING_NOTE,
    ]
    assert timer.active is True
    # ...then, at the next tick, the section checked again.
    *_, checked, _, _, timer = _rows_tick(page, DEFAULTS, items)

    assert installer.runs == [["speech-gate", "speech-local"]]
    # Ended well: the section checked again, its new lines with it (the voice, the
    # lexicon), and the timer off.
    assert [i.id for i in checked] == [
        "extra:speech-lib[gate]",
        "extra:speech-lib[local-voice]",
        "weights:Ada",
        "lexicon",
    ]
    assert timer.active is False
    # Checked once: the next tick sends nothing.
    assert all(
        update == gr.skip() for update in _rows_tick(page, DEFAULTS, checked)[:-1]
    )


def test_an_extra_installed_from_its_line_is_followed_then_checks_the_section_again(
    tmp_path: Path, installer: FakeInstaller
) -> None:
    lib = SpeechLib()
    lib.installed["local-voice"] = False
    model = _model(tmp_path, sections=(Section("speech", lib),))
    with gr.Blocks() as page:
        setup_panel(model)
    on_button = _handlers(page, "on_button")[0]  # one per row; the row given below
    items = tuple(model.check_setup(DEFAULTS))
    assert [i.id for i in items] == [
        "extra:speech-lib[local-voice]"
    ]  # nothing else yet

    # The click returns at once, the install running: the line says so, its button
    # disabled, the rows' timer on.
    cells, button, *checks, timer = on_button(items, DEFAULTS, index=0)
    assert "⏳ <strong>" in cells and button["interactive"] is False
    assert checks == [gr.skip()] * 4 and timer.active is True
    _wait(lambda: len(installer.runs) == 1)
    tick = _rows_tick(page, DEFAULTS, items)
    assert "uv: Resolved 1 extra(s)" in tick[0]  # uv's latest words, live

    lib.installed["local-voice"] = True  # what the install did
    installer.gates[0].set()
    # Its end shown first, before the check that loads the library just installed...
    _wait(lambda: "Checking the section again" in _rows_tick(page, DEFAULTS, items)[0])
    # ...then the section checked again, at the next tick.
    *_, checked, fold, _, timer = _rows_tick(page, DEFAULTS, items)

    assert installer.runs == [["speech-local"]]
    # The section checked again: the library's own lines now, each with its action.
    assert [(i.id, i.status) for i in checked] == [
        ("extra:speech-lib[local-voice]", "ready"),
        ("weights:Ada", "missing"),
        ("lexicon", "missing"),
    ]
    assert fold["label"] == "Speech — Local voice · ❌ 1 required item missing"
    assert timer.active is False


def test_a_key_saved_on_its_line_reaches_the_store_and_turns_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environ = _environ(monkeypatch)
    model = _model(tmp_path, environ=environ)
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    page = _table(model, _Actions(model))
    on_save_key = _handlers(page, "on_save_key")[0]  # one per row; the row given below
    shown = tuple(model.check_setup(cloud))
    index = next(i for i, item in enumerate(shown) if item.variable)
    seen = model.secrets.revision

    cleared, _, _, items = on_save_key("s3cret", shown, cloud, index=index)

    assert cleared == ""  # the value is never shown back
    assert model.secrets.file_names() == ["CLOUD_VOICE_KEY"]
    assert environ["CLOUD_VOICE_KEY"] == "s3cret"
    assert model.secrets.revision != seen  # every tab checks again
    key = next(i for i in items if i.variable == "CLOUD_VOICE_KEY")
    assert key.status == "ready"


def _running_file(
    tmp_path: Path, environ: dict[str, str] | None = None, **app: Any
) -> tuple[AppModel, Path]:
    """An app running a file as it is: a bare app's file, its .env next to it."""
    path = tmp_path / "voice.json"
    path.write_text(json.dumps(DEFAULTS["speech"]))
    application = App(
        name="talk",
        host="talk-app",
        sections=(Section("speech", app.pop("lib", SpeechLib())),),
        default_config=DEFAULTS["speech"],
        bare=True,
        **app,
    )
    store = SecretStore(tmp_path / ".env", {} if environ is None else environ)
    return AppModel(application, ConfigFile(path), store), path


def test_a_file_run_as_it_is_gets_a_read_only_setup_panel(tmp_path: Path) -> None:
    model, path = _running_file(tmp_path, autostart=True)
    with gr.Blocks() as page:
        setup_panel(model)
    drawn = list(page.blocks.values())
    buttons = [b.value for b in drawn if isinstance(b, gr.Button)]
    markdown = [b.value for b in drawn if isinstance(b, gr.Markdown)]

    # The file named, and what to do to change it.
    assert READ_ONLY.format(path=path) in markdown
    assert f"Running `{path}` as it is." in READ_ONLY.format(path=path)
    # Nothing to save: no Save, Revert, Reset, unsaved line or launch checkbox.
    assert "Revert to saved" not in buttons and "Reset to defaults" not in buttons
    assert not [
        b for b in drawn if isinstance(b, gr.Button) and b.variant == "primary"
    ]  # the config's Save; each row's key keeps its own
    assert DRAFT not in markdown
    assert not [b for b in drawn if isinstance(b, gr.Checkbox)]
    for name in ("on_save", "on_revert", "on_reset", "on_draft", "on_autostart"):
        assert _handlers(page, name) == [], name
    # The checks and their actions, as for a folder.
    for name in ("Check", "Install all", "Prepare all", "Test"):
        assert name in buttons
    assert _handlers(page, "on_button") and _handlers(page, "on_save_key")
    _, summary, items, *_ = _handler(page, "on_check")(model.saved_config())
    assert summary and [i.id for i in items][:1] == ["extra:speech-lib[local-voice]"]
    # The tick has no lock nor unsaved line to keep: the secrets' revision, the checks
    # (problems, summary, items, fold), the rows' timer, what it showed.
    tick = _handler(page, "on_tick")(model.saved_config(), 1, None, None)
    assert tick[0] == model.secrets.revision and len(tick) == 1 + 4 + 2


def test_the_read_only_form_shows_every_field_and_edits_none(tmp_path: Path) -> None:
    model, _ = _running_file(tmp_path)
    config = {"speech": {"module": {"type": "local-voice", "voice": "Bo"}, "gate": {}}}

    with gr.Blocks() as form:
        draft = gr.State(config)
        revision = gr.Number(0, precision=0, visible=False)
        render_section(model, "speech", config, draft, revision, readonly=True)
    drawn = [b for b in form.blocks.values() if isinstance(b, Component)]
    fields = [c for c in drawn if getattr(c, "label", None)]
    labels = _labels(fields)

    # Every field shown, the values that run readable.
    assert {"Voice", "voice", "speed", "timeout", "Configure gate", "level"} <= set(
        labels
    )
    assert next(c for c in fields if c.label == "voice").value == "Bo"
    # None editable, no module switch, no list button, no listener at all.
    assert all(c.interactive is False for c in fields)
    assert not [b for b in drawn if isinstance(b, gr.Button)]
    assert not form.fns


def test_a_key_saved_from_a_line_reaches_the_file_s_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model, _ = _running_file(tmp_path, environ=_environ(monkeypatch))
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    with gr.Blocks() as page:
        setup_panel(model)
    shown = tuple(model.check_setup(cloud))
    index = next(i for i, item in enumerate(shown) if item.variable)

    _handlers(page, "on_save_key")[0]("s3cret", shown, cloud, index=index)

    assert (tmp_path / ".env").read_text() == 'CLOUD_VOICE_KEY="s3cret"\n'


BACKUP_DEFAULT = {"module": {"type": "local-voice", "voice": "Bo"}}


def _with_backup(tmp_path: Path, speech: SpeechLib, backup: SpeechLib) -> AppModel:
    """The speech section, and an optional backup voice the user may add."""
    return _model(
        tmp_path,
        sections=(
            Section("speech", speech),
            Section(
                "backup",
                backup,
                title="Backup voice",
                optional=True,
                default=BACKUP_DEFAULT,
            ),
        ),
    )


@dataclass
class _Redrawn:
    """What one section's redraw sends: its own checks, output, "off" line, the panel
    revision it saw and whether its fold was set; for each other section its fold, its
    "off" line and its own revision; the tab's layout."""

    problems: Any
    summary: Any
    items: Any
    fold: Any
    output: Any
    off: Any
    seen: Any
    opened: Any
    others: dict[str, tuple[Any, Any, Any]]
    layout: Any


def _redraw(
    page: gr.Blocks,
    model: AppModel,
    name: str,
    config: dict[str, Any],
    *,
    panel_wide: bool = True,
    opened: bool = False,
    shown: dict[str, tuple[bool, bool]] | None = None,
) -> _Redrawn:
    """Section *name*'s redraw, as gradio runs it: on a panel-wide change (the page loaded,
    Revert, Reset) or on a change of the section's own (a module switched, Add, Remove),
    every section's own revision at 5."""
    sections = model.app.sections
    index = [section.name for section in sections].index(name)
    fn = _handlers(page, "on_section_redraw")[index]
    rev, seen = (2, 1) if panel_wide else (2, 2)
    out = list(fn(config, rev, seen, opened, shown, *([5] * len(sections))))
    problems, summary, items, fold, output = out[:5]
    rest = out[5:]
    off = rest.pop(0) if sections[index].optional else None
    seen_now, opened_now = rest[:2]
    rest = rest[2:]
    others: dict[str, tuple[Any, Any, Any]] = {}
    for section in sections:
        if section.name == name:
            continue
        other_fold = rest.pop(0)
        other_off = rest.pop(0) if section.optional else None
        others[section.name] = (other_fold, other_off, rest.pop(0))
    (layout,) = rest
    return _Redrawn(
        problems,
        summary,
        items,
        fold,
        output,
        off,
        seen_now,
        opened_now,
        others,
        layout,
    )


def test_a_fold_s_line_follows_a_check_and_a_module_switch(tmp_path: Path) -> None:
    model = _model(tmp_path)
    with gr.Blocks() as page:
        setup_panel(model)
    cloud = {"speech": {"module": {"type": "cloud-voice"}}}

    *_, fold = _handler(page, "on_check")(DEFAULTS)
    assert fold["label"] == "Speech — Local voice · ❌ 1 required item missing"

    # The module switched: the section redraws, and its line names the new module.
    redrawn = _redraw(page, model, "speech", cloud, panel_wide=False, opened=True)
    assert redrawn.fold["label"] == (
        "Speech — Cloud voice (hosted) · ❌ 1 problem in the config"
    )
    assert redrawn.output == {"__type__": "update", "value": "", "visible": False}


def test_a_change_in_one_section_checks_and_redraws_it_alone(tmp_path: Path) -> None:
    speech, backup = SpeechLib(), SpeechLib()
    model = _with_backup(tmp_path, speech, backup)
    config = {**DEFAULTS, "backup": BACKUP_DEFAULT}
    with gr.Blocks() as page:
        setup_panel(model)
    checked: list[str] = []
    for name, lib in (("speech", speech), ("backup", backup)):
        original = lib.check_setup

        def spy(
            config: Any, *, base_dir: Any = None, name: str = name, f: Any = original
        ) -> Any:
            checked.append(name)
            return f(config, base_dir=base_dir)

        lib.check_setup = spy  # type: ignore[method-assign]
    shown = {"speech": (True, False), "backup": (True, False)}

    # The speech's module switched: the speech alone is checked; the backup, still used
    # as before, is left as it is (not checked, not shown again, its form not redrawn).
    redrawn = _redraw(page, model, "speech", config, panel_wide=False, shown=shown)
    assert checked == ["speech"]
    assert redrawn.others["backup"] == (gr.skip(), gr.skip(), gr.skip())
    assert redrawn.seen == 2 and redrawn.layout == shown
    # Each form drawn again on a panel-wide change and on its own section's only.
    renders = [f for f in page.fns.values() if f.fn and f.fn.__name__ == "apply"]
    revisions = [
        b
        for b in page.blocks.values()
        if isinstance(b, gr.Number) and b.visible is False
    ]
    panel, speech_rev, backup_rev = revisions[0], *revisions[1:3]
    triggers = [{target for target, _ in f.targets} for f in renders]
    assert triggers == [
        {panel._id, speech_rev._id},
        {panel._id, backup_rev._id},
    ]


def test_a_section_s_change_shows_or_hides_the_sections_its_when_reads(
    tmp_path: Path,
) -> None:
    # The backup is used only while the speech's voice is "Bo".
    model = _model(
        tmp_path,
        sections=(
            Section("speech", SpeechLib()),
            Section(
                "backup",
                SpeechLib(),
                title="Backup voice",
                when=lambda config: config["speech"]["module"].get("voice") == "Bo",
            ),
        ),
    )
    with gr.Blocks() as page:
        setup_panel(model)
    bo = {
        "speech": {"module": {"type": "local-voice", "voice": "Bo"}},
        "backup": BACKUP_DEFAULT,
    }
    ada = {**bo, "speech": DEFAULTS["speech"]}

    # Turned true: the backup's own revision bumped, so it alone is drawn and checked.
    on = _redraw(
        page,
        model,
        "speech",
        bo,
        panel_wide=False,
        shown={"speech": (True, False), "backup": (False, False)},
    )
    fold, _, revision = on.others["backup"]
    assert fold == gr.skip() and revision == 6
    assert on.layout["backup"] == (True, False)
    # Turned false: the backup's fold hidden, nothing checked or drawn for it.
    off = _redraw(page, model, "speech", ada, panel_wide=False, shown=on.layout)
    fold, _, revision = off.others["backup"]
    assert fold["visible"] is False and revision == gr.skip()
    # A panel-wide change: each section redraws itself, none touches the others.
    wide = _redraw(page, model, "speech", bo, shown=off.layout)
    assert wide.others["backup"] == (gr.skip(), None, gr.skip())


def test_each_section_s_open_says_how_its_fold_starts(tmp_path: Path) -> None:
    def at_load(speech_open: Any, backup_open: Any) -> tuple[Any, Any]:
        speech, backup = SpeechLib(), SpeechLib()  # the speech needs its lexicon
        backup.lexicon, backup.downloaded = True, {"Bo"}  # the backup ready
        model = _model(
            tmp_path / f"{speech_open}-{backup_open}",
            sections=(
                Section("speech", speech, open=speech_open),
                Section("backup", backup, optional=True, open=backup_open),
            ),
        )
        with gr.Blocks() as page:
            setup_panel(model)
        config = {**DEFAULTS, "backup": BACKUP_DEFAULT}
        speech_now = _redraw(page, model, "speech", config)
        backup_now = _redraw(page, model, "backup", config)
        assert speech_now.opened is True  # set once: afterwards, the user's
        # Afterwards, a redraw (a module switched, a check) moves none.
        for name in ("speech", "backup"):
            for panel_wide in (True, False):
                later = _redraw(
                    page, model, name, config, panel_wide=panel_wide, opened=True
                )
                assert "open" not in later.fold
        return speech_now.fold["open"], backup_now.fold["open"]

    # "needs", the default: open when the section needs something.
    assert Section("s", SpeechLib()).open == "needs"
    assert at_load("needs", "needs") == (True, False)
    # Each section its own: "always" open even ready, "folded" even needing something.
    assert at_load("folded", "always") == (False, True)
    assert at_load("needs", "always") == (True, True)


def test_a_lone_section_is_open_only_when_it_says_so(tmp_path: Path) -> None:
    def at_load(own: Any) -> Any:
        lib = SpeechLib()
        lib.lexicon, lib.downloaded = True, {"Ada"}  # ready
        model = _model(tmp_path / own, sections=(Section("speech", lib, open=own),))
        with gr.Blocks() as page:
            setup_panel(model)
        return _redraw(page, model, "speech", DEFAULTS).fold["open"]

    # No rule of its own for one section: ready, it is folded unless it asks.
    assert at_load("needs") is False
    assert at_load("always") is True


def test_an_optional_section_is_added_and_removed_in_the_draft(tmp_path: Path) -> None:
    model = _with_backup(tmp_path, SpeechLib(), SpeechLib())
    with gr.Blocks() as page:
        setup_panel(model)
    drawn = list(page.blocks.values())
    on_add, on_remove = _handler(page, "on_add"), _handler(page, "on_remove")

    # Off: its fold hidden, its line with Add shown.
    off = _redraw(page, model, "backup", DEFAULTS)
    assert off.fold["visible"] is False and off.off["visible"] is True
    assert _markdown(drawn, "**Backup voice** — off")

    # Add: its default in the draft, its own revision bumped (it alone redrawn), its fold
    # opened; the redraw shows it, checked, and leaves it open.
    added, rev, kept, fold = on_add(DEFAULTS, 3, {})
    assert added == {**DEFAULTS, "backup": BACKUP_DEFAULT} and rev == 4
    assert fold["open"] is True
    on = _redraw(page, model, "backup", added, panel_wide=False, opened=True)
    assert on.fold["visible"] is True and "open" not in on.fold
    assert on.off["visible"] is False
    assert on.fold["label"].startswith("Backup voice — Local voice · ")
    assert "Remove Backup voice" in [b.value for b in drawn if isinstance(b, gr.Button)]

    # Edited, removed, added back: its settings kept, in this tab.
    edited = {**added, "backup": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    removed, rev, kept = on_remove(edited, rev, kept)
    assert removed == DEFAULTS and rev == 5
    restored, rev, kept, _ = on_add(removed, rev, kept)
    assert restored == edited and kept == {}
    # Draft edits: unsaved until Save.
    assert _handler(page, "on_draft")(restored, rev) == (UNSAVED_TOP, UNSAVED_BOTTOM)


def test_a_read_only_panel_offers_neither_add_nor_remove(tmp_path: Path) -> None:
    path = tmp_path / "talk.json"
    path.write_text(json.dumps(DEFAULTS))
    application = App(
        name="talk",
        host="talk-app",
        sections=(
            Section("speech", SpeechLib()),
            Section("backup", SpeechLib(), title="Backup voice", optional=True),
        ),
        default_config=DEFAULTS,
    )
    model = AppModel(application, ConfigFile(path), SecretStore(tmp_path / ".env", {}))
    with gr.Blocks() as page:
        setup_panel(model)
    drawn = list(page.blocks.values())
    buttons = [b.value for b in drawn if isinstance(b, gr.Button)]

    assert _markdown(drawn, "**Backup voice** — off")  # said, not offered
    assert "Add" not in buttons and "Remove Backup voice" not in buttons
    assert _handlers(page, "on_add") == [] and _handlers(page, "on_remove") == []


def test_the_folds_add_lines_and_remove_buttons_are_drawn_once(tmp_path: Path) -> None:
    with gr.Blocks() as page:
        setup_panel(_with_backup(tmp_path, SpeechLib(), SpeechLib()))
    drawn = list(page.blocks.values())
    folds = [b for b in drawn if isinstance(b, gr.Accordion)]
    renders = [f for f in page.fns.values() if f.fn and f.fn.__name__ == "apply"]

    # One fold per section (each form's own Advanced folds are drawn in its render).
    assert [f.label for f in folds] == ["Speech", "Backup voice"]
    # The forms' renders only, one per section; the panel's two timers, the tick and the
    # rows'; no whole-config actions (each fold's line says it).
    assert len(renders) == 2
    assert len([b for b in drawn if isinstance(b, gr.Timer)]) == 2
    assert not [b for b in drawn if getattr(b, "value", None) == "Check all"]
    for name in ("on_add", "on_remove", "on_section_redraw"):
        for fn in [f for f in page.fns.values() if f.fn and f.fn.__name__ == name]:
            assert fn.rendered_in is None, name


def test_a_fold_has_its_settings_beside_what_the_machine_has(tmp_path: Path) -> None:
    with gr.Blocks() as page:
        setup_panel(_model(tmp_path))
    drawn = list(page.blocks.values())
    settings = drawn.index(_markdown(drawn, "#### Settings"))
    machine = _markdown(drawn, "#### On this machine")

    # The right column set apart as a panel; the section's own buttons small, on a row.
    column = next(
        b
        for b in drawn
        if isinstance(b, gr.Column) and machine._id in [c._id for c in b.children]
    )
    assert column.variant == "panel"
    own = [b for b in drawn if isinstance(b, gr.Button) and b.value == "Check"]
    assert [b.size for b in own] == ["sm"]
    # The config's problems (Check's first output) under the form, in the left column.
    (check,) = [f for f in page.fns.values() if f.fn and f.fn.__name__ == "on_check"]
    problems = drawn.index(check.outputs[0])
    assert settings < problems < drawn.index(machine)
    assert _handler(page, "on_check")(DEFAULTS)[0] == "✅ **The config is valid.**"


def test_a_section_s_open_must_be_one_of_its_values() -> None:
    with pytest.raises(ValueError, match="open is one of needs, always, folded, not"):
        Section("speech", SpeechLib(), open="sometimes")  # type: ignore[arg-type]


def test_the_env_list_is_drawn_again_only_when_its_rows_change(tmp_path: Path) -> None:
    model = _model(tmp_path)
    model.secrets.set("OLD_KEY", "s3cret")
    cloud = {"speech": {"module": {"type": "cloud-voice", "voice_id": "v"}}}
    with gr.Blocks() as page:
        draft = gr.State(DEFAULTS)
        secrets_panel(model, draft)
    on_config = _handler(page, "on_config")

    # The list's render follows its hidden number only, never the config: a State's
    # change fires twice as the page loads in a tab other than the first, and each run of
    # a render drops the listeners of the last (a row's Remove clicked in between failed).
    (render,) = [f for f in page.fns.values() if f.fn and f.fn.__name__ == "apply"]
    triggers = [
        page.blocks[target] for target, _ in render.targets if target is not None
    ]
    assert [type(block) for block in triggers] == [gr.Number]

    _, _, _, drawn = _handler(page, "on_load")(DEFAULTS)
    # The config changed, its rows not (OLD_KEY named by neither): not drawn again.
    assert on_config(3, drawn, {**DEFAULTS, "other": {}})[1:] == (gr.skip(), gr.skip())
    # A module naming a key: its rows change, drawn again once, the same number on the
    # second firing of the change.
    model.secrets.set("CLOUD_VOICE_KEY", "s3cret")
    first, second = on_config(3, drawn, cloud), on_config(3, drawn, cloud)
    assert first[1] == second[1] == 4 and first[2] != drawn
