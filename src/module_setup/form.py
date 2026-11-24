"""What a form shows for a config, and how an edit changes the config (specs/ui.md, "The form").

A parsed schema (``contract.ObjectSpec``) and a config document give a tree of form items:
groups (objects), choices (a module dropdown), fields and raw JSON blocks. An edit is then
applied to the document as a pure function: a coerced value written or removed, a module
switched (fields shared by name kept), an optional object switched on or off. Nothing here
imports gradio, so the rules a form follows are tested without a browser.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from module_setup.contract import Choice, FieldSpec, ObjectSpec

__all__ = [
    "ABSENT",
    "FormChoice",
    "FormField",
    "FormGroup",
    "FormRaw",
    "Path",
    "coerce",
    "get_at",
    "layout",
    "pointer",
    "secret_variables",
    "select_branch",
    "set_at",
    "toggle_group",
]

Path = tuple[str, ...]
Widget = Literal["text", "number", "integer", "checkbox", "dropdown", "json"]


class _Absent:
    """The value of a field that is not in the config: an edit that removes the key."""

    def __repr__(self) -> str:
        return "ABSENT"


ABSENT: Any = _Absent()


def pointer(path: Path) -> str:
    """The JSON Pointer of *path*: ``("module", "voice")`` → ``/module/voice``."""
    return "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in path)


@dataclass(frozen=True)
class FormField:
    """One editable value."""

    path: Path
    spec: FieldSpec
    widget: Widget
    value: Any  # ABSENT when the key is not in the config
    required: bool

    @property
    def label(self) -> str:
        return self.spec.title or self.spec.name

    @property
    def advanced(self) -> bool:
        return self.spec.advanced

    @property
    def choices(self) -> tuple[Any, ...]:
        return self.spec.enum or ()


@dataclass(frozen=True)
class FormRaw:
    """A free-form object, edited as JSON text."""

    path: Path
    label: str
    description: str | None
    value: Any  # ABSENT when the key is not in the config
    advanced: bool


@dataclass(frozen=True)
class FormChoice:
    """The module choice of an object: a dropdown of its branches."""

    path: Path  # the object carrying the choice
    choice: Choice
    selected: Any  # the discriminator's value in the config, or None
    label: str

    @property
    def options(self) -> tuple[tuple[str, Any], ...]:
        return tuple((branch.title, branch.value) for branch in self.choice.branches)

    @property
    def options_list(self) -> str | None:
        """The named list (`x-options`) of the selected branch, if it has one."""
        branch = self.choice.branch(self.selected)
        return branch.options if branch is not None else None


@dataclass(frozen=True)
class FormGroup:
    """An object of the config, with its items in order."""

    path: Path
    title: str | None
    description: str | None
    items: tuple[FormItem, ...]
    optional: bool  # an object that may be absent: drawn with a switch
    enabled: bool  # present in the config (always true when not optional)
    advanced: bool
    options_list: str | None


FormItem = FormField | FormRaw | FormChoice | FormGroup


def get_at(document: Any, path: Path) -> Any:
    """The value at *path*, or ABSENT."""
    for name in path:
        if not isinstance(document, Mapping) or name not in document:
            return ABSENT
        document = document[name]
    return document


def set_at(document: Mapping[str, Any], path: Path, value: Any) -> dict[str, Any]:
    """A copy of *document* with *value* at *path* (ABSENT removes the key). Missing parent
    objects are created."""
    result = copy.deepcopy(dict(document))
    if not path:
        raise ValueError("an empty path names the document itself")
    node = result
    for name in path[:-1]:
        child = node.get(name)
        if not isinstance(child, dict):
            child = {}
            node[name] = child
        node = child
    if value is ABSENT:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = copy.deepcopy(value)
    return result


def _widget(spec: FieldSpec) -> Widget:
    if spec.enum is not None:
        return "dropdown"
    if spec.types == ("boolean",):
        return "checkbox"
    if spec.types == ("number",):
        return "number"
    if spec.types == ("integer",):
        return "integer"
    if spec.types == ("array",):
        return "json"
    return "text"


def _property_items(
    properties: tuple[FieldSpec | ObjectSpec, ...],
    required: frozenset[str],
    node: Any,
    path: Path,
) -> Iterator[FormItem]:
    for prop in properties:
        child_path = (*path, prop.name)
        if isinstance(prop, FieldSpec):
            if prop.secret:
                continue  # a key written in the config is never drawn
            yield FormField(
                path=child_path,
                spec=prop,
                widget=_widget(prop),
                value=get_at(node, (prop.name,)),
                required=prop.name in required,
            )
        elif prop.free_form:
            yield FormRaw(
                path=child_path,
                label=prop.title or prop.name,
                description=prop.description,
                value=get_at(node, (prop.name,)),
                advanced=prop.advanced,
            )
        else:
            yield _group(
                prop, get_at(node, (prop.name,)), child_path, prop.name in required
            )


def _group(spec: ObjectSpec, node: Any, path: Path, required: bool) -> FormGroup:
    present = isinstance(node, Mapping)
    document = node if present else {}
    items: list[FormItem] = []
    required_names = set(spec.required)
    options_list = spec.options
    if spec.choice is not None:
        selected = document.get(spec.choice.discriminator)
        items.append(
            FormChoice(
                path=path,
                choice=spec.choice,
                selected=selected,
                label=spec.title or spec.name or "Module",
            )
        )
        branch = spec.choice.branch(selected)
        items += _property_items(spec.properties, spec.required, document, path)
        if branch is not None:
            required_names |= branch.required
            items += _property_items(
                branch.properties, frozenset(required_names), document, path
            )
            options_list = branch.options or options_list
    else:
        items += _property_items(spec.properties, spec.required, document, path)
    optional = bool(path) and not required
    return FormGroup(
        path=path,
        title=spec.title,
        description=spec.description,
        items=tuple(items),
        optional=optional,
        enabled=present or not optional,
        advanced=spec.advanced,
        options_list=options_list,
    )


def layout(schema: ObjectSpec, document: Any) -> FormGroup:
    """The form of *document* under *schema*: its root group."""
    return _group(schema, document, (), required=True)


def coerce(item: FormField | FormRaw, raw: Any) -> tuple[Any, str | None]:
    """The config value for what a widget holds, and an error when it holds nothing valid.

    An empty widget, or a value equal to the field's default, gives ABSENT: the form writes
    only what differs from what the library would use anyway. A number with no fraction is
    written as an integer.
    """
    if isinstance(item, FormRaw):
        return _json(raw)
    spec = item.spec
    value, error = _coerce_field(item, raw)
    if error is not None:
        return ABSENT, error
    if value is not ABSENT and spec.has_default and value == spec.default:
        return ABSENT, None
    return value, None


def _json(raw: Any) -> tuple[Any, str | None]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ABSENT, None
    if not isinstance(raw, str):
        return raw, None
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return ABSENT, f"not valid JSON: {exc.msg} (line {exc.lineno})"


def _coerce_field(field: FormField, raw: Any) -> tuple[Any, str | None]:
    spec = field.spec
    if field.widget == "checkbox":
        return bool(raw), None
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ABSENT, None
    if field.widget == "dropdown":
        return raw, None
    if field.widget == "json":
        return _json(raw)
    if field.widget in ("number", "integer"):
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            try:
                raw = float(raw)
            except (TypeError, ValueError):
                return ABSENT, f"{field.label}: not a number"
        if not math.isfinite(raw):
            return ABSENT, f"{field.label}: not a finite number"
        if float(raw).is_integer():
            return int(raw), None
        if field.widget == "integer":
            return ABSENT, f"{field.label}: not a whole number"
        return float(raw), None
    # Text, possibly for a field accepting several kinds: a whole number goes in as one when
    # the field takes integers, any number when it takes numbers.
    text = str(raw)
    stripped = text.strip()
    if "integer" in spec.types or "number" in spec.types:
        try:
            number = float(stripped)
        except ValueError:
            pass
        else:
            if math.isfinite(number):
                if number.is_integer() and "integer" in spec.types:
                    return int(number), None
                if "number" in spec.types:
                    return number, None
    if "string" not in spec.types:
        return ABSENT, f"{field.label}: not a valid value"
    return text, None


def _branch_names(choice: Choice, value: Any) -> set[str]:
    branch = choice.branch(value)
    return {prop.name for prop in branch.properties} if branch is not None else set()


def select_branch(
    document: Mapping[str, Any], path: Path, choice: Choice, value: Any
) -> dict[str, Any]:
    """*document* with the module at *path* switched to *value*: the old module's own fields
    are dropped, even those the new one has under the same name (a voice id of one provider
    means nothing to another); the fields common to every module are kept."""
    node = get_at(document, path)
    current = dict(node) if isinstance(node, Mapping) else {}
    previous = current.get(choice.discriminator)
    dropped = _branch_names(choice, previous)
    updated = {k: v for k, v in current.items() if k not in dropped}
    updated[choice.discriminator] = value
    if not path:
        return copy.deepcopy(updated)
    return set_at(document, path, updated)


def toggle_group(
    document: Mapping[str, Any], path: Path, enabled: bool
) -> dict[str, Any]:
    """*document* with the optional object at *path* switched on (an empty object, or the one
    already there) or off (removed)."""
    if not enabled:
        return set_at(document, path, ABSENT)
    current = get_at(document, path)
    return set_at(document, path, current if isinstance(current, Mapping) else {})


def secret_variables(schema: ObjectSpec, document: Any) -> list[tuple[str, str]]:
    """The environment variables *document* names for its secrets, as ``(pointer, name)``:
    each `x-secret-env` field's value, or its default when absent. An object that holds a
    key itself (an `x-secret` field with a value) names none."""
    found: list[tuple[str, str]] = []

    def walk(spec: ObjectSpec, node: Any, path: Path) -> None:
        if not isinstance(node, Mapping):
            return
        properties = list(spec.properties)
        if spec.choice is not None:
            branch = spec.choice.branch(node.get(spec.choice.discriminator))
            if branch is not None:
                properties += branch.properties
        fields = [p for p in properties if isinstance(p, FieldSpec)]
        if any(f.secret and node.get(f.name) for f in fields):
            return
        for prop in properties:
            if isinstance(prop, FieldSpec):
                if not prop.secret_env:
                    continue
                name = node.get(prop.name, prop.default if prop.has_default else None)
                if isinstance(name, str) and name:
                    found.append((pointer((*path, prop.name)), name))
            elif not prop.free_form:
                walk(prop, node.get(prop.name), (*path, prop.name))

    walk(schema, document, ())
    return found
