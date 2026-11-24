import copy
from typing import Any

import pytest

from app_setup.contract import (
    ContractError,
    ContractViolation,
    FieldSpec,
    ObjectSpec,
    check_contract,
    parse_description,
)

# An illustrative speech library: a module choice nested under `module`, an optional object
# (`gate`), a free-form object, a field of several kinds, and every annotation.


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["module"],
        "properties": {
            "module": {
                "type": "object",
                "title": "Voice",
                "description": "The voice that speaks.",
                "required": ["type"],
                "properties": {
                    "timeout": {
                        "type": "number",
                        "description": "Seconds before a request gives up.",
                        "default": 10,
                        "exclusiveMinimum": 0,
                        "x-advanced": True,
                    }
                },
                "oneOf": [
                    {
                        "title": "Local voice",
                        "x-options": "voices",
                        "properties": {
                            "type": {"const": "local-voice"},
                            "voice": {
                                "type": "string",
                                "description": "The voice's name.",
                                "default": "Ada",
                            },
                        },
                    },
                    {
                        "title": "Cloud voice (hosted)",
                        "required": ["voice_id"],
                        "properties": {
                            "type": {"const": "cloud-voice"},
                            "voice_id": {
                                "type": "string",
                                "description": "The id of the voice.",
                            },
                            "api_key_env": {
                                "type": "string",
                                "description": "The variable holding the key.",
                                "x-secret-env": True,
                            },
                            "api_key": {
                                "type": "string",
                                "description": "The key itself.",
                                "x-secret": True,
                            },
                        },
                    },
                ],
            },
            "device": {
                "type": ["string", "integer", "null"],
                "description": "The output device.",
                "x-options": "output-devices",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Free labels.",
            },
            "gate": {
                "type": "object",
                "description": "Silence gate; absent means off.",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "How strict.",
                        "enum": [1, 2, 3],
                        "default": 2,
                    }
                },
            },
            "passthrough": {
                "type": "object",
                "description": "Arguments handed to the provider as they are.",
                "additionalProperties": True,
            },
        },
    }


def _description() -> dict[str, Any]:
    return {
        "contract": 1,
        "distribution": "speech-lib",
        "title": "Speech",
        "schema": _schema(),
    }


EXAMPLES: list[dict[str, Any]] = [
    {"module": {"type": "local-voice", "voice": "Bo"}, "passthrough": {"any": 1}},
    {
        "module": {"type": "cloud-voice", "voice_id": "v1", "api_key_env": "KEY"},
        "gate": {"level": 3},
    },
]

EXTRAS = {"speech-lib": {"local-voice", "cloud-voice"}}


class SpeechLib:
    """A contract object that honours the contract; tests subclass it to break one rule."""

    def config_schema(self) -> dict[str, Any]:
        return _description()

    def required_extras(self, config: dict[str, Any]) -> list[str]:
        module = config.get("module")
        kind = module.get("type") if isinstance(module, dict) else None
        if kind in ("local-voice", "cloud-voice"):
            return [f"speech-lib[{kind}]"]
        return []

    def check_config(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        module = config.get("module")
        if not isinstance(module, dict):
            return [{"path": "/module", "message": "module is required"}]
        problems = []
        if module.get("type") == "cloud-voice" and not module.get("voice_id"):
            problems.append(
                {"path": "/module/voice_id", "message": "voice_id is required"}
            )
        if "timeout" in module and not module["timeout"] > 0:
            problems.append(
                {"path": "/module/timeout", "message": "timeout must be > 0"}
            )
        if "voice" in module and not isinstance(module["voice"], str):
            problems.append(
                {"path": "/module/voice", "message": "voice must be a string"}
            )
        return problems

    def check_setup(
        self, config: dict[str, Any], *, base_dir: str | None = None
    ) -> list[dict[str, Any]]:
        return []

    def prepare(
        self,
        config: dict[str, Any],
        item: str,
        *,
        on_progress: Any = None,
        base_dir: str | None = None,
    ) -> None:
        return None

    def options(
        self, name: str, config: dict[str, Any], *, base_dir: str | None = None
    ) -> list[dict[str, Any]]:
        return []

    def probe(
        self, config: dict[str, Any], *, base_dir: str | None = None
    ) -> dict[str, Any]:
        return {"ok": True, "message": "Nothing to run.", "duration_s": 0.0}


def _extras_of(distribution: str) -> set[str] | None:
    return EXTRAS.get(distribution)


def _check(contract: Any, examples: list[dict[str, Any]] | None = None) -> None:
    check_contract(contract, examples or EXAMPLES, extras_of=_extras_of)


# --- parse_description ---------------------------------------------------------


def test_a_description_parses_into_the_objects_a_form_is_drawn_from():
    parsed = parse_description(_description())

    assert (parsed.contract, parsed.distribution, parsed.title) == (
        1,
        "speech-lib",
        "Speech",
    )
    root = parsed.schema
    assert root.required == {"module"}
    by_name = {p.name: p for p in root.properties}

    module = by_name["module"]
    assert isinstance(module, ObjectSpec)
    assert module.title == "Voice"
    timeout = module.properties[0]
    assert isinstance(timeout, FieldSpec)
    assert (timeout.default, timeout.exclusive_minimum, timeout.advanced) == (
        10,
        0,
        True,
    )

    device = by_name["device"]
    assert isinstance(device, FieldSpec)
    assert device.types == ("string", "integer") and device.nullable
    assert device.options == "output-devices"
    assert not device.has_default

    tags = by_name["tags"]
    assert isinstance(tags, FieldSpec) and tags.items == "string"

    gate = by_name["gate"]
    assert isinstance(gate, ObjectSpec) and "gate" not in root.required
    level = gate.properties[0]
    assert isinstance(level, FieldSpec) and level.enum == (1, 2, 3)

    passthrough = by_name["passthrough"]
    assert isinstance(passthrough, ObjectSpec) and passthrough.free_form


def test_a_bound_on_a_field_of_several_kinds_applies_to_its_numbers():
    data = _description()
    data["schema"]["properties"]["device"]["minimum"] = 0

    device = next(
        p for p in parse_description(data).schema.properties if p.name == "device"
    )

    assert isinstance(device, FieldSpec) and device.minimum == 0


def test_a_list_of_objects_is_a_field_edited_as_raw_json():
    data = _description()
    data["schema"]["properties"]["tags"]["items"] = {"type": "object"}

    tags = next(
        p for p in parse_description(data).schema.properties if p.name == "tags"
    )

    assert isinstance(tags, FieldSpec) and tags.items == "object"


def test_the_discriminator_is_found_and_each_branch_keeps_its_own_fields():
    module = parse_description(_description()).schema.properties[0]
    assert isinstance(module, ObjectSpec) and module.choice is not None
    choice = module.choice

    assert choice.discriminator == "type"
    assert [b.value for b in choice.branches] == ["local-voice", "cloud-voice"]
    local, cloud = choice.branches
    assert local.options == "voices"
    assert [p.name for p in local.properties] == ["voice"]
    assert cloud.required == {"voice_id"}
    secrets = {p.name: p for p in cloud.properties if isinstance(p, FieldSpec)}
    assert secrets["api_key_env"].secret_env and not secrets["api_key_env"].secret
    assert secrets["api_key"].secret
    assert choice.branch("cloud-voice") is cloud
    assert choice.branch("nope") is None


def test_a_flat_object_is_a_choice_with_its_common_fields():
    data = _description()
    data["schema"] = {
        "type": "object",
        "required": ["provider", "model"],
        "properties": {"model": {"type": "string", "description": "The model's name."}},
        "oneOf": [
            {"title": "A", "properties": {"provider": {"const": "a"}}},
            {
                "title": "B",
                "required": ["base_url"],
                "properties": {
                    "provider": {"const": "b"},
                    "base_url": {"type": "string", "description": "Where it runs."},
                },
            },
        ],
    }

    root = parse_description(data).schema

    assert root.choice is not None and root.choice.discriminator == "provider"
    assert [p.name for p in root.properties] == ["model"]
    assert root.required == {"provider", "model"}
    assert [p.name for p in root.choice.branches[1].properties] == ["base_url"]


def _broken(
    path: list[Any], value: Any = None, *, remove: bool = False
) -> dict[str, Any]:
    """The reference description with one node replaced (or removed)."""
    data = _description()
    node: Any = data
    for key in path[:-1]:
        node = node[key]
    if remove:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return data


_MODULE = ["schema", "properties", "module"]
_BRANCH0 = [*_MODULE, "oneOf", 0]

REFUSALS = [
    ("an unknown version", _broken(["contract"], 2), "/contract"),
    ("a missing distribution", _broken(["distribution"], remove=True), "/distribution"),
    ("an unknown top-level key", _broken(["extra"], 1), "/extra"),
    (
        "an unsupported keyword",
        _broken(["schema", "properties", "tags", "minItems"], 1),
        "/schema/properties/tags/minItems",
    ),
    (
        "a field without a description",
        _broken(["schema", "properties", "tags", "description"], remove=True),
        "/schema/properties/tags/description",
    ),
    (
        "an unsupported type",
        _broken(["schema", "properties", "tags", "type"], "date"),
        "/schema/properties/tags/type",
    ),
    (
        "an array of arrays",
        _broken(["schema", "properties", "tags", "items"], {"type": "array"}),
        "/schema/properties/tags/items",
    ),
    (
        "a bound on a field that takes no number",
        _broken(["schema", "properties", "tags", "minimum"], 0),
        "/schema/properties/tags/minimum",
    ),
    (
        "a secret that is not a string",
        _broken([*_MODULE, "properties", "timeout", "x-secret"], True),
        "/schema/properties/module/properties/timeout/x-secret",
    ),
    (
        "a required name that is no property",
        _broken(["schema", "required"], ["module", "ghost"]),
        "/schema/required",
    ),
    (
        "a free-form object that declares fields",
        _broken(["schema", "properties", "gate", "additionalProperties"], True),
        "/schema/properties/gate/additionalProperties",
    ),
    (
        "a oneOf whose branches share no const property",
        _broken([*_BRANCH0, "properties", "type"], remove=True),
        "/schema/properties/module/oneOf",
    ),
    (
        "two branches with the same value",
        _broken([*_BRANCH0, "properties", "type"], {"const": "cloud-voice"}),
        "/schema/properties/module/oneOf/1/properties/type",
    ),
    (
        "a branch without a title",
        _broken([*_BRANCH0, "title"], remove=True),
        "/schema/properties/module/oneOf/0/title",
    ),
    (
        "a branch field that is also a common field",
        _broken(
            [*_BRANCH0, "properties", "timeout"],
            {"type": "number", "description": "Again."},
        ),
        "/schema/properties/module/oneOf/0/properties/timeout",
    ),
    (
        "a const outside a oneOf",
        _broken(["schema", "properties", "tags"], {"const": "x"}),
        "/schema/properties/tags/const",
    ),
]


@pytest.mark.parametrize(
    ("data", "path"), [(d, p) for _, d, p in REFUSALS], ids=[n for n, _, _ in REFUSALS]
)
def test_what_is_outside_the_contract_is_refused_naming_its_path(data, path):
    with pytest.raises(ContractError) as error:
        parse_description(data)
    assert str(error.value).startswith(path + ":")


def test_parsing_does_not_keep_a_reference_to_the_library_s_default():
    data = _description()
    data["schema"]["properties"]["tags"]["default"] = ["a"]
    parsed = parse_description(data)

    data["schema"]["properties"]["tags"]["default"].append("b")

    tags = next(p for p in parsed.schema.properties if p.name == "tags")
    assert isinstance(tags, FieldSpec) and tags.default == ["a"]


# --- check_contract -------------------------------------------------------------


def test_a_contract_that_honours_every_rule_passes():
    _check(SpeechLib())


def test_an_installed_distribution_s_extras_are_read_from_its_metadata():
    class NeedsPytest(SpeechLib):
        def __init__(self, extra: str) -> None:
            self.extra = extra

        def required_extras(self, config: dict[str, Any]) -> list[str]:
            return [f"pytest[{self.extra}]"] if config else []

    check_contract(NeedsPytest("dev"), EXAMPLES)
    with pytest.raises(ContractViolation, match="declares no extra 'nope'"):
        check_contract(NeedsPytest("nope"), EXAMPLES)


def test_no_example_is_an_error_of_the_caller():
    with pytest.raises(ValueError, match="at least one example"):
        check_contract(SpeechLib(), [])


def _breach(contract: Any, examples: list[dict[str, Any]] | None = None) -> str:
    with pytest.raises(ContractViolation) as error:
        _check(contract, examples)
    return str(error.value)


def test_a_contract_object_missing_a_function_is_a_breach():
    class NoProbe:
        config_schema = SpeechLib.config_schema
        required_extras = SpeechLib.required_extras
        check_config = SpeechLib.check_config
        check_setup = SpeechLib.check_setup
        prepare = SpeechLib.prepare
        options = SpeechLib.options

    assert "lacks ['probe']" in _breach(NoProbe())


def test_a_description_outside_the_contract_is_a_breach():
    class Bad(SpeechLib):
        def config_schema(self) -> dict[str, Any]:
            return {**_description(), "contract": 9}

    assert "unknown contract version 9" in _breach(Bad())


def test_a_config_schema_that_changes_between_calls_is_a_breach():
    class Unstable(SpeechLib):
        calls = 0

        def config_schema(self) -> dict[str, Any]:
            self.calls += 1
            return {**_description(), "title": f"Speech {self.calls}"}

    assert "two different values" in _breach(Unstable())


def test_an_example_check_config_refuses_is_a_breach():
    examples = [*EXAMPLES, {"module": {"type": "cloud-voice"}}]

    assert "check_config() refuses example 2" in _breach(SpeechLib(), examples)


def test_an_example_key_the_schema_lacks_is_a_breach():
    examples = copy.deepcopy(EXAMPLES)
    examples[0]["module"]["speed"] = 2
    examples[1]["gate"]["depth"] = 1

    message = _breach(SpeechLib(), examples)

    assert "example 0 uses /module/speed" in message
    assert "example 1 uses /gate/depth" in message


def test_a_key_under_a_free_form_object_is_not_a_breach():
    examples = copy.deepcopy(EXAMPLES)
    examples[0]["passthrough"] = {"anything": {"nested": True}}

    _check(SpeechLib(), examples)


def test_a_default_check_config_refuses_is_a_breach():
    class BadDefault(SpeechLib):
        def config_schema(self) -> dict[str, Any]:
            data = _description()
            data["schema"]["properties"]["module"]["properties"]["timeout"][
                "default"
            ] = -1
            return data

    message = _breach(BadDefault())

    assert "/module = 'local-voice' with its defaults written out" in message
    assert "timeout must be > 0" in message


def test_a_module_no_example_covers_is_built_from_its_defaults():
    only_cloud = [EXAMPLES[1]]

    _check(SpeechLib(), only_cloud)

    class WrongDefault(SpeechLib):
        def config_schema(self) -> dict[str, Any]:
            data = _description()
            branch = data["schema"]["properties"]["module"]["oneOf"][0]
            branch["properties"]["voice"]["default"] = 7
            branch["properties"]["voice"]["type"] = ["string", "integer"]
            return data

    assert "voice must be a string" in _breach(WrongDefault(), only_cloud)


def test_a_module_that_cannot_be_built_without_an_example_is_a_breach():
    only_local = [EXAMPLES[0]]

    message = _breach(SpeechLib(), only_local)

    assert "no example selects /module = 'cloud-voice'" in message
    assert "['voice_id']" in message


def test_a_required_extras_that_raises_on_an_empty_config_is_a_breach():
    class Raises(SpeechLib):
        def required_extras(self, config: dict[str, Any]) -> list[str]:
            return [f"speech-lib[{config['module']['type']}]"]

    assert "required_extras() raised on {}" in _breach(Raises())


def test_a_requirement_that_is_malformed_or_names_nothing_declared_is_a_breach():
    class Wrong(SpeechLib):
        def required_extras(self, config: dict[str, Any]) -> list[str]:
            kind = (config.get("module") or {}).get("type")
            if kind == "local-voice":
                return ["speech-lib[fast voice"]
            if kind == "cloud-voice":
                return ["speech-lib[premium]", "other-lib[x]"]
            return []

    message = _breach(Wrong())

    assert "'speech-lib[fast voice' is not a requirement" in message
    assert "'speech-lib' declares no extra 'premium'" in message
    assert "'other-lib' is not installed" in message


def test_required_extras_is_probed_on_each_module_alone():
    seen: list[dict[str, Any]] = []

    class Records(SpeechLib):
        def required_extras(self, config: dict[str, Any]) -> list[str]:
            seen.append(config)
            return super().required_extras(config)

    _check(Records())

    assert {"module": {"type": "local-voice"}} in seen
    assert {"module": {"type": "cloud-voice"}} in seen
    assert {} in seen


def test_a_function_that_takes_no_base_dir_is_a_breach():
    class Deaf(SpeechLib):
        def probe(self, config: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
            return {"ok": True, "message": "", "duration_s": 0.0}

    class Open(SpeechLib):
        def probe(self, config: dict[str, Any], **_: Any) -> dict[str, Any]:  # type: ignore[override]
            return {"ok": True, "message": "", "duration_s": 0.0}

    assert "['probe'] take no `base_dir` keyword" in _breach(Deaf())
    _check(Open(), None)  # a `**kwargs` takes it


def test_a_prepare_that_takes_no_item_is_a_breach():
    class Whole(SpeechLib):
        # The shape before one item per call: the whole config prepared at once.
        def prepare(  # type: ignore[override]
            self,
            config: dict[str, Any],
            on_progress: Any = None,
            *,
            base_dir: str | None = None,
        ) -> None:
            return None

    class Positional(SpeechLib):
        def prepare(  # type: ignore[override]
            self,
            config: dict[str, Any],
            item: str,
            on_progress: Any = None,
            base_dir: str | None = None,
        ) -> None:
            return None

    assert "prepare() does not take `(config, item" in _breach(Whole())
    _check(Positional(), None)  # on_progress may also be given by name
