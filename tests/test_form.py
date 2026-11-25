from typing import Any

import pytest
from fakes import schema

from app_setup.contract import FieldSpec, parse_description
from app_setup.form import (
    ABSENT,
    FormChoice,
    FormField,
    FormGroup,
    FormRaw,
    coerce,
    get_at,
    layout,
    pointer,
    secret_variables,
    select_branch,
    selected_modules,
    set_at,
    toggle_group,
)

SCHEMA = parse_description(schema()).schema


def _items(group: FormGroup) -> dict[str, Any]:
    """The items of a group by their last path name (the choice under "<choice>")."""
    found: dict[str, Any] = {}
    for item in group.items:
        key = "<choice>" if isinstance(item, FormChoice) else item.path[-1]
        found[key] = item
    return found


def test_the_form_follows_the_selected_module_and_hides_a_written_key() -> None:
    root = layout(SCHEMA, {"module": {"type": "cloud-voice", "voice_id": "v1"}})
    module = _items(root)["module"]
    assert isinstance(module, FormGroup)

    items = _items(module)
    choice = items["<choice>"]
    assert isinstance(choice, FormChoice)
    assert choice.selected == "cloud-voice"
    assert choice.options == (
        ("Local voice", "local-voice"),
        ("Cloud voice (hosted)", "cloud-voice"),
    )
    assert list(items) == ["<choice>", "timeout", "voice_id", "speed", "api_key_env"]
    voice_id = items["voice_id"]
    assert isinstance(voice_id, FormField)
    assert (voice_id.value, voice_id.required, voice_id.widget) == ("v1", True, "text")
    assert items["timeout"].advanced and items["timeout"].widget == "number"
    assert items["speed"].value is ABSENT


def test_an_unselected_module_shows_the_choice_and_the_common_fields_only() -> None:
    module = _items(layout(SCHEMA, {"module": {}}))["module"]

    assert list(_items(module)) == ["<choice>", "timeout"]
    assert _items(module)["<choice>"].selected is None


def test_optional_objects_are_switches_and_free_form_objects_raw_json() -> None:
    off = _items(layout(SCHEMA, {"module": {"type": "local-voice"}}))
    on = _items(
        layout(SCHEMA, {"module": {"type": "local-voice"}, "gate": {"level": 3}})
    )

    assert off["gate"].optional and not off["gate"].enabled
    assert on["gate"].enabled
    level = _items(on["gate"])["level"]
    assert (level.widget, level.value, level.choices) == ("dropdown", 3, (1, 2, 3))
    assert _items(on["gate"])["loud"].widget == "checkbox"
    assert not on["module"].optional  # required
    assert isinstance(off["passthrough"], FormRaw)


def test_the_options_list_is_the_selected_branch_s() -> None:
    local = _items(layout(SCHEMA, {"module": {"type": "local-voice"}}))["module"]
    cloud = _items(layout(SCHEMA, {"module": {"type": "cloud-voice"}}))["module"]

    assert local.options_list == "voices"
    assert _items(local)["<choice>"].options_list == "voices"
    assert cloud.options_list is None


def _field(name: str, *types: str, **spec: Any) -> FormField:
    field_spec = FieldSpec(
        name=name, types=types, nullable=True, description="x", **spec
    )
    widgets: dict[tuple[str, ...], str] = {
        ("number",): "number",
        ("integer",): "integer",
        ("boolean",): "checkbox",
        ("array",): "json",
    }
    widget = widgets.get(types, "dropdown" if spec.get("enum") else "text")
    return FormField(
        path=(name,),
        spec=field_spec,
        widget=widget,  # pyright: ignore[reportArgumentType]
        value=ABSENT,
        required=False,
    )


COERCIONS = [
    (_field("t", "string"), "hello", "hello"),
    (_field("t", "string"), "", ABSENT),
    (_field("t", "string"), "   ", ABSENT),
    (_field("n", "number"), 2.0, 2),
    (_field("n", "number"), 2.5, 2.5),
    (_field("n", "number"), None, ABSENT),
    (_field("n", "number"), "1.5", 1.5),
    (_field("i", "integer"), 3.0, 3),
    (_field("b", "boolean"), True, True),
    (_field("b", "boolean", has_default=True, default=False), False, ABSENT),
    (_field("s", "string", has_default=True, default="Ada"), "Ada", ABSENT),
    (_field("e", "string", enum=("a", "b")), "b", "b"),
    (_field("e", "string", enum=("a", "b")), "", ABSENT),
    (_field("a", "array", items="string"), '["x", "y"]', ["x", "y"]),
    (_field("d", "string", "integer"), "3", 3),
    (_field("d", "string", "integer"), "speakers", "speakers"),
    (_field("d", "string", "integer"), "2.5", "2.5"),
]


@pytest.mark.parametrize(("field", "raw", "value"), COERCIONS)
def test_a_widget_value_becomes_the_config_value(
    field: FormField, raw: Any, value: Any
) -> None:
    assert coerce(field, raw) == (value, None)


@pytest.mark.parametrize(
    ("field", "raw", "error"),
    [
        (_field("i", "integer"), 2.5, "not a whole number"),
        (_field("n", "number"), "fast", "not a number"),
        (_field("n", "number"), float("inf"), "not a finite number"),
        (_field("a", "array", items="string"), "[1,", "not valid JSON"),
        (_field("k", "integer", "number"), "fast", "not a valid value"),
    ],
)
def test_a_widget_value_that_is_not_valid_is_an_error(
    field: FormField, raw: Any, error: str
) -> None:
    value, message = coerce(field, raw)

    assert value is ABSENT
    assert message is not None and error in message


def test_raw_json_is_parsed_and_empty_text_removes_it() -> None:
    raw = FormRaw(
        path=("p",), label="p", description=None, value=ABSENT, advanced=False
    )

    assert coerce(raw, '{"a": 1}') == ({"a": 1}, None)
    assert coerce(raw, "") == (ABSENT, None)
    assert coerce(raw, "{")[1] is not None


def test_set_at_writes_creates_and_removes_without_touching_the_original() -> None:
    original = {"tts": {"module": {"type": "x", "voice": "a"}}}

    written = set_at(original, ("tts", "module", "voice"), "b")
    created = set_at(original, ("tts", "gate", "level"), 3)
    removed = set_at(original, ("tts", "module", "voice"), ABSENT)

    assert written["tts"]["module"]["voice"] == "b"
    assert created["tts"]["gate"] == {"level": 3}
    assert "voice" not in removed["tts"]["module"]
    assert original == {"tts": {"module": {"type": "x", "voice": "a"}}}
    assert get_at(original, ("tts", "module", "voice")) == "a"
    assert get_at(original, ("tts", "nope")) is ABSENT


def test_switching_module_drops_the_old_modules_fields_and_keeps_the_common_ones() -> (
    None
):
    module_choice = _items(_items(layout(SCHEMA, {"module": {}}))["module"])["<choice>"]
    document = {
        "tts": {
            "module": {
                "type": "cloud-voice",
                "voice_id": "v1",
                "speed": 1.1,
                "api_key_env": "K",
                "timeout": 5,
                "unknown": True,
            }
        }
    }

    switched = select_branch(
        document, ("tts", "module"), module_choice.choice, "local-voice"
    )

    # `speed` is a field of both modules, yet the old module's value is not carried over.
    assert switched["tts"]["module"] == {
        "type": "local-voice",
        "timeout": 5,
        "unknown": True,
    }


def test_an_optional_object_is_switched_on_empty_and_off_removed() -> None:
    document = {"tts": {"module": {"type": "x"}}}

    on = toggle_group(document, ("tts", "gate"), True)
    kept = toggle_group({"tts": {"gate": {"level": 1}}}, ("tts", "gate"), True)
    off = toggle_group(on, ("tts", "gate"), False)

    assert on["tts"]["gate"] == {}
    assert kept["tts"]["gate"] == {"level": 1}
    assert "gate" not in off["tts"]


def test_an_optional_object_with_a_module_choice_starts_on_its_first_module() -> None:
    choice = _items(_items(layout(SCHEMA, {"module": {}}))["module"])["<choice>"].choice

    on = toggle_group({"tts": {}}, ("tts", "module"), True, choice)
    kept = toggle_group(
        {"tts": {"module": {"type": "cloud-voice"}}}, ("tts", "module"), True, choice
    )

    # Its dropdown shows a module, and that module's fields are drawn, rather than nothing.
    assert on["tts"]["module"] == {"type": "local-voice"}
    assert kept["tts"]["module"] == {"type": "cloud-voice"}


def test_the_secret_variables_are_the_named_ones_or_the_default() -> None:
    named = {"module": {"type": "cloud-voice", "api_key_env": "MY_KEY"}}
    default = {"module": {"type": "cloud-voice"}}
    written = {"module": {"type": "cloud-voice", "api_key": "secret"}}
    local = {"module": {"type": "local-voice"}}

    assert secret_variables(SCHEMA, named) == [("/module/api_key_env", "MY_KEY")]
    assert secret_variables(SCHEMA, default) == [
        ("/module/api_key_env", "CLOUD_VOICE_KEY")
    ]
    assert secret_variables(SCHEMA, written) == []
    assert secret_variables(SCHEMA, local) == []


def test_a_pointer_escapes_its_parts() -> None:
    assert pointer(("tts", "a/b", "c~d")) == "/tts/a~1b/c~0d"
    assert pointer(()) == ""


def _choice(name: str, *titles: str) -> dict[str, Any]:
    """An object choosing one of *titles*' modules, by its `type`."""
    return {
        "type": "object",
        "description": f"The {name}.",
        "required": ["type"],
        "oneOf": [
            {"title": title, "properties": {"type": {"const": title.lower()}}}
            for title in titles
        ],
    }


def test_the_selected_modules_are_listed_in_the_form_s_order() -> None:
    assert selected_modules(SCHEMA, {"module": {"type": "cloud-voice"}}) == [
        "Cloud voice (hosted)"
    ]
    assert selected_modules(SCHEMA, {}) == []  # none chosen yet

    two = parse_description(
        {
            "contract": 1,
            "distribution": "speech-lib",
            "title": "Speech",
            "schema": {
                "type": "object",
                "required": ["engine"],
                "properties": {
                    "engine": _choice("engine", "Deepgram", "Whisper"),
                    "vad": _choice("vad", "Silero", "WebRTC"),
                },
            },
        }
    ).schema
    document = {"engine": {"type": "whisper"}, "vad": {"type": "silero"}}

    assert selected_modules(two, document) == ["Whisper", "Silero"]
    # An optional object switched off chooses nothing.
    assert selected_modules(two, {"engine": {"type": "deepgram"}}) == ["Deepgram"]
