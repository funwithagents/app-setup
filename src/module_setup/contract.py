"""The module contract, seen from the side that consumes it (specs/module-contract.md).

A library implements the contract with plain data and seven functions, and imports nothing from
here. This module is what reads that data: ``SetupContract`` types the seven functions,
``parse_description`` turns a ``config_schema()`` result into the frozen objects a form is drawn from
(refusing anything outside the spec), and ``check_contract`` is the conformance check a library
runs in its own tests.
"""

from __future__ import annotations

import copy
import inspect
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Protocol

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

__all__ = [
    "CONTRACT_VERSION",
    "Branch",
    "Choice",
    "ContractError",
    "ContractViolation",
    "Description",
    "FieldSpec",
    "ObjectSpec",
    "SetupContract",
    "check_contract",
    "parse_description",
]

CONTRACT_VERSION = 1

_FUNCTIONS = (
    "config_schema",
    "required_extras",
    "check_config",
    "check_setup",
    "prepare",
    "options",
    "probe",
)

_SCALARS = ("string", "number", "integer", "boolean")
_NUMERIC = ("number", "integer")
_BOUNDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
_DESCRIPTION_KEYS = frozenset({"contract", "distribution", "title", "schema"})
_FIELD_KEYS = frozenset(
    {
        "type",
        "title",
        "description",
        "default",
        "enum",
        "items",
        "x-advanced",
        "x-secret-env",
        "x-secret",
        "x-options",
        *_BOUNDS,
    }
)
_OBJECT_KEYS = frozenset(
    {
        "type",
        "title",
        "description",
        "properties",
        "required",
        "oneOf",
        "additionalProperties",
        "x-advanced",
        "x-options",
    }
)
_BRANCH_KEYS = frozenset(
    {"title", "description", "properties", "required", "x-options"}
)


class ContractError(ValueError):
    """A description outside the contract; the message names the path of the offender."""


class ContractViolation(AssertionError):
    """What ``check_contract`` raises: every way the contract object breaks the contract."""


class SetupContract(Protocol):
    """The seven callables of a contract object. A Python module with these functions qualifies."""

    def config_schema(self) -> dict[str, Any]: ...

    def required_extras(self, config: dict[str, Any]) -> list[str]: ...

    def check_config(self, config: dict[str, Any]) -> list[dict[str, Any]]: ...

    # The four that may look at the machine take `base_dir`: the folder a relative path of
    # the config is relative to (the app's folder), None for the working directory.

    def check_setup(
        self, config: dict[str, Any], *, base_dir: str | None = None
    ) -> list[dict[str, Any]]: ...

    def prepare(
        self,
        config: dict[str, Any],
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        *,
        base_dir: str | None = None,
    ) -> None: ...

    def options(
        self, name: str, config: dict[str, Any], *, base_dir: str | None = None
    ) -> list[dict[str, Any]]: ...

    def probe(
        self, config: dict[str, Any], *, base_dir: str | None = None
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FieldSpec:
    """A scalar or array-of-scalars field of the config."""

    name: str
    types: tuple[
        str, ...
    ]  # without "null"; several for a field accepting more than one kind
    nullable: bool
    description: str
    title: str | None = None
    has_default: bool = False
    default: Any = None
    enum: tuple[Any, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    # The element type of an array: a scalar type, or "object" for a list of objects,
    # which a form edits as raw JSON.
    items: str | None = None
    advanced: bool = False
    secret_env: bool = False
    secret: bool = False
    options: str | None = None


@dataclass(frozen=True)
class Branch:
    """One module of a choice: the discriminator's value and the fields it adds."""

    value: Any
    title: str
    properties: tuple[FieldSpec | ObjectSpec, ...]
    required: frozenset[str]
    description: str | None = None
    options: str | None = None


@dataclass(frozen=True)
class Choice:
    """A choice between modules, told apart by the ``discriminator`` property."""

    discriminator: str
    branches: tuple[Branch, ...]

    def branch(self, value: Any) -> Branch | None:
        """The branch whose discriminator value is *value*, or None."""
        return next((b for b in self.branches if b.value == value), None)


@dataclass(frozen=True)
class ObjectSpec:
    """An object of the config: its own fields, and the module choice it carries, if any."""

    name: str  # "" for the document itself
    properties: tuple[FieldSpec | ObjectSpec, ...]
    required: frozenset[str]
    title: str | None = None
    description: str | None = None
    nullable: bool = False
    free_form: bool = False
    choice: Choice | None = None
    advanced: bool = False
    options: str | None = None


@dataclass(frozen=True)
class Description:
    """A parsed ``config_schema()`` result."""

    contract: int
    distribution: str
    title: str
    schema: ObjectSpec


# --- Parsing ------------------------------------------------------------------


def parse_description(data: Any) -> Description:
    """Turn a ``config_schema()`` result into typed objects, or raise ``ContractError``."""
    if not isinstance(data, Mapping):
        raise ContractError("the description must be an object")
    _only(data, _DESCRIPTION_KEYS, "")
    version = data.get("contract")
    if version != CONTRACT_VERSION or isinstance(version, bool):
        raise ContractError(
            f"/contract: unknown contract version {version!r}, "
            f"this module-setup knows {CONTRACT_VERSION}"
        )
    distribution = _text(data, "distribution", "")
    title = _text(data, "title", "")
    schema = data.get("schema")
    if not isinstance(schema, Mapping) or "object" not in _types(schema, "/schema")[0]:
        raise ContractError("/schema: the config document must be an object schema")
    return Description(
        contract=CONTRACT_VERSION,
        distribution=distribution,
        title=title,
        schema=_object("", schema, "/schema", needs_description=False),
    )


def _only(node: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    for key in node:
        if key not in allowed:
            raise ContractError(f"{path}/{key}: unsupported keyword {key!r}")


def _text(node: Mapping[str, Any], key: str, path: str) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value:
        raise ContractError(f"{path}/{key}: must be a non-empty string")
    return value


def _optional_text(node: Mapping[str, Any], key: str, path: str) -> str | None:
    return _text(node, key, path) if key in node else None


def _flag(node: Mapping[str, Any], key: str, path: str) -> bool:
    value = node.get(key, False)
    if not isinstance(value, bool):
        raise ContractError(f"{path}/{key}: must be a boolean")
    return value


def _types(node: Mapping[str, Any], path: str) -> tuple[tuple[str, ...], bool]:
    """The node's types without ``null``, and whether ``null`` was among them."""
    raw = node.get("type")
    names = [raw] if isinstance(raw, str) else raw
    if not isinstance(names, list) or not names:
        raise ContractError(f"{path}/type: must be a type name or a list of them")
    known = (*_SCALARS, "array", "object", "null")
    for name in names:
        if name not in known:
            raise ContractError(f"{path}/type: unsupported type {name!r}")
    types = tuple(name for name in names if name != "null")
    if not types:
        raise ContractError(f"{path}/type: a field cannot be null only")
    if len(types) > 1 and not all(name in _SCALARS for name in types):
        raise ContractError(
            f"{path}/type: only scalar types can be combined, got {list(types)}"
        )
    return types, "null" in names


def _node(
    name: str, node: Any, path: str, *, needs_description: bool = True
) -> FieldSpec | ObjectSpec:
    if not isinstance(node, Mapping):
        raise ContractError(f"{path}: must be an object")
    if "const" in node:
        raise ContractError(
            f"{path}/const: 'const' is only for the property that tells the branches "
            "of a oneOf apart"
        )
    types, _ = _types(node, path)
    if types == ("object",):
        return _object(name, node, path, needs_description=needs_description)
    return _field(name, node, path)


def _field(name: str, node: Mapping[str, Any], path: str) -> FieldSpec:
    _only(node, _FIELD_KEYS, path)
    types, nullable = _types(node, path)
    items: str | None = None
    if types == ("array",):
        element = node.get("items")
        if (
            not isinstance(element, Mapping)
            or set(element) != {"type"}
            or element["type"] not in (*_SCALARS, "object")
        ):
            raise ContractError(
                f"{path}/items: an array holds scalars of one type, or objects "
                "(edited as raw JSON), stated as a single 'type'"
            )
        items = element["type"]
    elif "items" in node:
        raise ContractError(f"{path}/items: only an array has items")
    numeric = any(t in _NUMERIC for t in types)
    bounds: dict[str, float | None] = {}
    for key in _BOUNDS:
        value = node.get(key)
        if value is not None and (
            not numeric
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise ContractError(
                f"{path}/{key}: a numeric bound on a field that accepts a number"
            )
        bounds[key] = value
    enum = node.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        raise ContractError(f"{path}/enum: must be a non-empty list")
    secret_env = _flag(node, "x-secret-env", path)
    secret = _flag(node, "x-secret", path)
    if (secret_env or secret) and "string" not in types:
        key = "x-secret-env" if secret_env else "x-secret"
        raise ContractError(f"{path}/{key}: only a string field holds a secret")
    return FieldSpec(
        name=name,
        types=types,
        nullable=nullable,
        description=_text(node, "description", path),
        title=_optional_text(node, "title", path),
        has_default="default" in node,
        default=copy.deepcopy(node.get("default")),
        enum=tuple(enum) if enum is not None else None,
        minimum=bounds["minimum"],
        maximum=bounds["maximum"],
        exclusive_minimum=bounds["exclusiveMinimum"],
        exclusive_maximum=bounds["exclusiveMaximum"],
        items=items,
        advanced=_flag(node, "x-advanced", path),
        secret_env=secret_env,
        secret=secret,
        options=_optional_text(node, "x-options", path),
    )


def _properties(
    node: Mapping[str, Any], path: str, *, skip: str | None = None
) -> tuple[FieldSpec | ObjectSpec, ...]:
    raw = node.get("properties", {})
    if not isinstance(raw, Mapping):
        raise ContractError(f"{path}/properties: must be an object")
    return tuple(
        _node(name, child, f"{path}/properties/{name}")
        for name, child in raw.items()
        if name != skip
    )


def _required(node: Mapping[str, Any], path: str, known: set[str]) -> frozenset[str]:
    raw = node.get("required", [])
    if not isinstance(raw, list) or not all(isinstance(n, str) for n in raw):
        raise ContractError(f"{path}/required: must be a list of property names")
    for name in raw:
        if name not in known:
            raise ContractError(
                f"{path}/required: {name!r} is not a property of this object"
            )
    return frozenset(raw)


def _object(
    name: str, node: Mapping[str, Any], path: str, *, needs_description: bool
) -> ObjectSpec:
    _only(node, _OBJECT_KEYS, path)
    _, nullable = _types(node, path)
    additional = node.get("additionalProperties", False)
    if not isinstance(additional, bool):
        raise ContractError(f"{path}/additionalProperties: must be true or false")
    properties = _properties(node, path)
    own = {p.name for p in properties}
    choice = _choice(node, path, own) if "oneOf" in node else None
    if additional and (properties or choice):
        raise ContractError(
            f"{path}/additionalProperties: a free-form object declares no field"
        )
    known = set(own)
    if choice is not None:
        known.add(choice.discriminator)
    return ObjectSpec(
        name=name,
        properties=properties,
        required=_required(node, path, known),
        title=_optional_text(node, "title", path),
        description=(
            _text(node, "description", path)
            if needs_description
            else _optional_text(node, "description", path)
        ),
        nullable=nullable,
        free_form=additional,
        choice=choice,
        advanced=_flag(node, "x-advanced", path),
        options=_optional_text(node, "x-options", path),
    )


def _choice(node: Mapping[str, Any], path: str, own: set[str]) -> Choice:
    raw = node["oneOf"]
    if not isinstance(raw, list) or not raw:
        raise ContractError(f"{path}/oneOf: must be a non-empty list of branches")
    for index, branch in enumerate(raw):
        if not isinstance(branch, Mapping):
            raise ContractError(f"{path}/oneOf/{index}: must be an object")
        _only(branch, _BRANCH_KEYS, f"{path}/oneOf/{index}")
        if not isinstance(branch.get("properties", {}), Mapping):
            raise ContractError(f"{path}/oneOf/{index}/properties: must be an object")
    candidates = [
        name
        for name, child in raw[0].get("properties", {}).items()
        if isinstance(child, Mapping) and "const" in child
    ]
    discriminators = [
        name
        for name in candidates
        if all(
            isinstance(b.get("properties", {}).get(name), Mapping)
            and "const" in b["properties"][name]
            for b in raw
        )
    ]
    if len(discriminators) != 1:
        raise ContractError(
            f"{path}/oneOf: exactly one property must be a 'const' in every branch, "
            f"found {discriminators}"
        )
    discriminator = discriminators[0]
    if discriminator in own:
        raise ContractError(
            f"{path}/oneOf: {discriminator!r} tells the branches apart and cannot also "
            "be a field of the object"
        )
    branches: list[Branch] = []
    for index, branch in enumerate(raw):
        branch_path = f"{path}/oneOf/{index}"
        const = branch["properties"][discriminator]
        if set(const) != {"const"} or not isinstance(const["const"], (str, int, bool)):
            raise ContractError(
                f"{branch_path}/properties/{discriminator}: must be a single scalar "
                "'const'"
            )
        if any(b.value == const["const"] for b in branches):
            raise ContractError(
                f"{branch_path}/properties/{discriminator}: {const['const']!r} "
                "already names another branch"
            )
        properties = _properties(branch, branch_path, skip=discriminator)
        for child in properties:
            if child.name in own:
                raise ContractError(
                    f"{branch_path}/properties/{child.name}: already a field common "
                    "to every branch"
                )
        known = own | {p.name for p in properties} | {discriminator}
        branches.append(
            Branch(
                value=const["const"],
                title=_text(branch, "title", branch_path),
                properties=properties,
                required=_required(branch, branch_path, known),
                description=_optional_text(branch, "description", branch_path),
                options=_optional_text(branch, "x-options", branch_path),
            )
        )
    return Choice(discriminator=discriminator, branches=tuple(branches))


# --- Conformance --------------------------------------------------------------


def _installed_extras(distribution: str) -> set[str] | None:
    """The extras *distribution* declares, or None when it is not installed."""
    try:
        declared = metadata.metadata(distribution).get_all("Provides-Extra") or []
    except metadata.PackageNotFoundError:
        return None
    return {canonicalize_name(extra) for extra in declared}


def _choices(
    spec: ObjectSpec, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], ObjectSpec, Choice]]:
    """Every choice of the schema, with the path of the object carrying it."""
    if spec.choice is not None:
        yield path, spec, spec.choice
    children = list(spec.properties)
    if spec.choice is not None:
        children += [p for b in spec.choice.branches for p in b.properties]
    for child in children:
        if isinstance(child, ObjectSpec):
            yield from _choices(child, (*path, child.name))


def _at(config: Any, path: tuple[str, ...]) -> Any:
    for name in path:
        if not isinstance(config, dict):
            return None
        config = config.get(name)
    return config


def _unknown_keys(spec: ObjectSpec, config: Any, path: str = "") -> list[str]:
    """Pointers to the keys of *config* the schema does not name."""
    if spec.free_form or not isinstance(config, dict):
        return []
    known: dict[str, FieldSpec | ObjectSpec | None] = {
        p.name: p for p in spec.properties
    }
    if spec.choice is not None:
        known[spec.choice.discriminator] = None
        branch = spec.choice.branch(config.get(spec.choice.discriminator))
        if branch is None:
            return [f"{path}/{spec.choice.discriminator}"]
        known.update({p.name: p for p in branch.properties})
    unknown: list[str] = []
    for key, value in config.items():
        if key not in known:
            unknown.append(f"{path}/{key}")
            continue
        child = known[key]
        if isinstance(child, ObjectSpec):
            unknown += _unknown_keys(child, value, f"{path}/{key}")
    return unknown


def _with_defaults(
    config: dict[str, Any], spec: ObjectSpec, branch: Branch
) -> dict[str, Any]:
    """*config* with every default of the object and of the branch written out."""
    filled = dict(config)
    for child in (*spec.properties, *branch.properties):
        if (
            isinstance(child, FieldSpec)
            and child.has_default
            and child.default is not None
            and child.name not in filled
        ):
            filled[child.name] = copy.deepcopy(child.default)
    return filled


# The functions that may look at the machine, so resolve a config's relative paths.
_TAKES_BASE_DIR = ("check_setup", "prepare", "options", "probe")


def _takes_base_dir(function: Callable[..., Any]) -> bool:
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return True  # no signature to read (a builtin): trust it
    return "base_dir" in parameters or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    )


def check_contract(
    contract: SetupContract,
    examples: Sequence[dict[str, Any]],
    *,
    extras_of: Callable[[str], set[str] | None] = _installed_extras,
) -> None:
    """Assert that *contract* honours the module contract over *examples*.

    Meant for a library's own test suite. Raises ``ContractViolation`` listing every breach;
    ``ValueError`` when given no example. *extras_of* returns the extras a distribution
    declares (None when it is not installed); the default reads the installed metadata.
    """
    if not examples:
        raise ValueError("check_contract needs at least one example config")
    absent = [
        name for name in _FUNCTIONS if not callable(getattr(contract, name, None))
    ]
    if absent:
        raise ContractViolation(f"the contract object lacks {absent}")
    deaf = [
        name for name in _TAKES_BASE_DIR if not _takes_base_dir(getattr(contract, name))
    ]
    if deaf:
        raise ContractViolation(
            f"{deaf} take no `base_dir` keyword: the folder a relative path of the config "
            "is relative to"
        )
    try:
        raw = contract.config_schema()
        description = parse_description(raw)
    except ContractError as exc:
        raise ContractViolation(
            f"config_schema() is outside the contract: {exc}"
        ) from exc

    breaches: list[str] = []
    if contract.config_schema() != raw:
        breaches.append("config_schema() returned two different values")

    def validated(config: dict[str, Any], what: str) -> None:
        problems = contract.check_config(copy.deepcopy(config))
        if problems:
            breaches.append(f"check_config() refuses {what}: {problems}")

    probes: list[tuple[str, dict[str, Any]]] = [("{}", {})]
    for index, example in enumerate(examples):
        validated(example, f"example {index}")
        for pointer in _unknown_keys(description.schema, example):
            breaches.append(f"example {index} uses {pointer}, which the schema lacks")
        probes.append((f"example {index}", example))

    for path, spec, choice in _choices(description.schema):
        where = "/" + "/".join(path) if path else "the document"
        for branch in choice.branches:
            bare = {choice.discriminator: branch.value}
            probe: dict[str, Any] = bare
            for name in reversed(path):
                probe = {name: probe}
            probes.append((f"{where} = {branch.value!r} alone", probe))

            selected = next(
                (
                    e
                    for e in examples
                    if isinstance(_at(e, path), dict)
                    and _at(e, path).get(choice.discriminator) == branch.value
                ),
                None,
            )
            if selected is None:
                needed = sorted(
                    (spec.required | branch.required) - {choice.discriminator}
                )
                defaults = {
                    p.name
                    for p in (*spec.properties, *branch.properties)
                    if isinstance(p, FieldSpec) and p.has_default
                }
                missing = [name for name in needed if name not in defaults]
                if missing:
                    breaches.append(
                        f"no example selects {where} = {branch.value!r}, and its "
                        f"required {missing} have no default to build one from"
                    )
                    continue
                base = copy.deepcopy(examples[0])
                block: dict[str, Any] = dict(bare)
            else:
                base = copy.deepcopy(selected)
                block = dict(_at(base, path))
            block = _with_defaults(block, spec, branch)
            if path:
                parent = base
                for name in path[:-1]:
                    parent = parent.setdefault(name, {})
                parent[path[-1]] = block
            else:
                base = block
            validated(base, f"{where} = {branch.value!r} with its defaults written out")

    for what, config in probes:
        try:
            found = contract.required_extras(copy.deepcopy(config))
        except Exception as exc:  # noqa: BLE001 - any raise is the breach
            breaches.append(f"required_extras() raised on {what}: {exc!r}")
            continue
        if not isinstance(found, list):
            breaches.append(f"required_extras() must return a list on {what}")
            continue
        for text in found:
            try:
                requirement = Requirement(text)
            except (InvalidRequirement, TypeError):
                breaches.append(
                    f"required_extras() on {what}: {text!r} is not a requirement"
                )
                continue
            declared = extras_of(requirement.name)
            if declared is None:
                breaches.append(
                    f"required_extras() on {what}: {requirement.name!r} is not installed"
                )
                continue
            for extra in requirement.extras:
                if canonicalize_name(extra) not in declared:
                    breaches.append(
                        f"required_extras() on {what}: {requirement.name!r} declares no "
                        f"extra {extra!r}"
                    )

    if breaches:
        unique = list(dict.fromkeys(breaches))
        raise ContractViolation(
            f"{len(unique)} breach(es) of the module contract:\n- "
            + "\n- ".join(unique)
        )
