"""The Setup tab's form, drawn from a section's schema (specs/ui.md, "The form").

Called inside the Setup panel's ``gr.render``: each section's ``FormGroup`` (app_setup.form)
becomes components whose events write to the page's draft config. A change of structure (a
module switched, an optional object turned on or off, a voice chosen from a list) also bumps
the page's revision, which draws the form again; a plain value edit does not, so typing never
loses focus. A field finished (a text box left or Enter pressed, a box ticked, a value chosen)
also bumps its section's ``edited`` state, which checks that section again.
"""

from __future__ import annotations

import json
from typing import Any

import gradio as gr

from app_setup.app import AppModel
from app_setup.form import (
    ABSENT,
    FormChoice,
    FormField,
    FormGroup,
    FormItem,
    FormRaw,
    Path,
    coerce,
    get_at,
    layout,
    select_branch,
    set_at,
    toggle_group,
)

__all__ = ["render_section", "section_title"]

Config = dict[str, Any]


def _default_text(field: FormField) -> str:
    if not field.spec.has_default:
        return ""
    default = field.spec.default
    return json.dumps(default) if not isinstance(default, str) else default


def _label(field: FormField) -> str:
    return field.label + (" *" if field.required else "")


def _number_info(field: FormField) -> str | None:
    """A field's description, with its range for a number (the box does not enforce it:
    Check reports a value outside it)."""
    spec = field.spec
    if field.widget not in ("number", "integer"):
        return spec.description
    low, high = spec.minimum, spec.maximum
    if low is not None and high is not None:
        bounds = f"from {low:g} to {high:g}"
    elif low is not None:
        bounds = f"at least {low:g}"
    elif high is not None:
        bounds = f"at most {high:g}"
    else:
        return spec.description
    return f"{spec.description or ''} ({bounds})".strip()


def _finished(
    component: Any,
    events: list[str],
    write: Any,
    draft: gr.State,
    edited: gr.State | None,
) -> None:
    """On each of *events* (the user done with the field), write the value and, given the
    section's *edited* state, bump it: the section is checked again."""
    if edited is None:
        for event in events:
            getattr(component, event)(write, inputs=[component, draft], outputs=[draft])
        return

    def on_field_done(raw: Any, config: Config, count: int) -> tuple[Config, int]:
        return write(raw, config), count + 1

    for event in events:
        getattr(component, event)(
            on_field_done,
            inputs=[component, draft, edited],
            outputs=[draft, edited],
        )


def _field(
    field: FormField, full: Path, draft: gr.State, edited: gr.State | None
) -> None:
    def write(raw: Any, config: Config) -> Config:
        value, error = coerce(field, raw)
        if error is not None:
            gr.Warning(error)
            return config
        return set_at(config, full, value)

    present = field.value is not ABSENT
    default = _default_text(field)
    component: Any
    if field.widget == "checkbox":
        # A checkbox shows one state: unset, the default's, said in its hint.
        value = field.value if present else bool(field.spec.default)
        unset = f" Not set: the default ({'on' if value else 'off'}) applies."
        component = gr.Checkbox(
            value=value,
            label=_label(field),
            info=(field.spec.description or "") + ("" if present else unset),
            interactive=True,
        )
    elif field.widget == "dropdown":
        values = {json.dumps(choice): choice for choice in field.choices}
        unset = f"(default: {default})" if default else "(not set)"
        component = gr.Dropdown(
            choices=[(unset, "")]
            + [(str(choice), key) for key, choice in values.items()],
            value=json.dumps(field.value) if present else "",
            label=_label(field),
            info=field.spec.description,
            interactive=True,
        )

        def write_choice(raw: Any, config: Config) -> Config:
            return write(values.get(raw, "") if raw else "", config)

        # A value chosen is a field finished.
        _finished(component, ["input"], write_choice, draft, edited)
        return
    elif field.widget == "json":
        component = gr.Code(
            value=json.dumps(field.value, indent=2) if present else "",
            language="json",
            label=_label(field) + " — " + (field.spec.description or ""),
            interactive=True,
        )
        _finished(component, ["blur"], write, draft, edited)
        return
    else:
        # Text and numbers alike: a field not set is empty, its default shown in grey (the
        # placeholder), so grey means "not set, the library decides" and a value means "set,
        # saved". A number box would always show a value. `coerce` reads the number back.
        component = gr.Textbox(
            value=str(field.value) if present and field.value is not None else "",
            label=_label(field),
            info=_number_info(field),
            placeholder=default or ("a number" if field.widget != "text" else ""),
            interactive=True,
        )
    if isinstance(component, gr.Checkbox):
        # A box ticked is a field finished.
        _finished(component, ["input"], write, draft, edited)
        return
    # Each keystroke writes the value, without checking (a check may import a provider).
    component.input(write, inputs=[component, draft], outputs=[draft])
    # Leaving the field, or Enter, writes it again and checks the section: a value typed
    # before the field's `input` listener is attached (right after a redraw) still reaches
    # the config.
    _finished(component, ["blur", "submit"], write, draft, edited)


def _raw(item: FormRaw, full: Path, draft: gr.State, edited: gr.State | None) -> None:
    present = item.value is not ABSENT
    component = gr.Code(
        value=json.dumps(item.value, indent=2) if present else "",
        language="json",
        label=f"{item.label} — {item.description or 'free-form JSON'}",
        interactive=True,
    )

    def write(raw: Any, config: Config) -> Config:
        value, error = coerce(item, raw)
        if error is not None:
            gr.Warning(f"{item.label}: {error}")
            return config
        return set_at(config, full, value)

    _finished(component, ["blur"], write, draft, edited)


def _options_picker(
    model: AppModel,
    section: str,
    list_name: str,
    path: Path,
    draft: gr.State,
    revision: gr.Number,
) -> None:
    """A button that loads a named list (`options`), and a dropdown whose choice merges its
    fields into the object at *path*."""
    full = (section, *path)
    with gr.Row():
        load = gr.Button(f"Choose from the {list_name} list", size="sm", scale=0)
        picker = gr.Dropdown(
            choices=[],
            label=f"{list_name.capitalize()}",
            visible=False,
            interactive=True,
        )
    loaded: dict[str, dict[str, Any]] = {}

    def fetch(config: Config) -> Any:
        try:
            choices = model.options(config, section, list_name)
        except Exception as exc:  # noqa: BLE001 - shown, the fields stay editable
            gr.Warning(f"The {list_name} list could not be loaded: {exc}")
            return gr.update(visible=False)
        loaded.clear()
        for index, choice in enumerate(choices):
            loaded[str(index)] = dict(choice.get("fields", {}))
        if not choices:
            gr.Info(f"The {list_name} list is empty.")
        return gr.update(
            choices=[(str(c.get("label", i)), str(i)) for i, c in enumerate(choices)],
            value=None,
            visible=bool(choices),
        )

    def choose(key: str | None, config: Config, rev: int) -> tuple[Config, int]:
        fields = loaded.get(key or "")
        if not fields:
            return config, rev
        for name, value in fields.items():
            config = set_at(config, (*full, name), value)
        return config, rev + 1

    load.click(fetch, inputs=[draft], outputs=[picker])
    picker.input(choose, inputs=[picker, draft, revision], outputs=[draft, revision])


def _item(
    model: AppModel,
    section: str,
    item: FormItem,
    draft: gr.State,
    revision: gr.Number,
    edited: gr.State | None,
) -> None:
    if isinstance(item, FormField):
        _field(item, (section, *item.path), draft, edited)
    elif isinstance(item, FormRaw):
        _raw(item, (section, *item.path), draft, edited)
    elif isinstance(item, FormChoice):
        _choice(model, section, item, draft, revision)
    else:
        _group(model, section, item, draft, revision, edited)


def _choice(
    model: AppModel,
    section: str,
    item: FormChoice,
    draft: gr.State,
    revision: gr.Number,
) -> None:
    keys = {json.dumps(value): value for _, value in item.options}
    selected = json.dumps(item.selected) if item.selected is not None else None
    dropdown = gr.Dropdown(
        choices=[(title, json.dumps(value)) for title, value in item.options],
        value=selected if selected in keys else None,
        label=item.label,
        interactive=True,
    )

    def switch(key: str | None, config: Config, rev: int) -> tuple[Config, int]:
        node = get_at(config, (section, *item.path))
        current = (
            node.get(item.choice.discriminator) if isinstance(node, dict) else None
        )
        if key not in keys or keys[key] == current:
            # Nothing to switch: gradio fires `input` again for the same choice, and a
            # second redraw would replace the fields the user is already typing in.
            return config, rev
        return select_branch(
            config, (section, *item.path), item.choice, keys[key]
        ), rev + 1

    # `select` fires once per choice; `input` fires twice, and each redraw replaces the
    # fields, losing what is typed in between.
    dropdown.select(
        switch, inputs=[dropdown, draft, revision], outputs=[draft, revision]
    )
    if item.options_list:
        _options_picker(model, section, item.options_list, item.path, draft, revision)


def _group(
    model: AppModel,
    section: str,
    group: FormGroup,
    draft: gr.State,
    revision: gr.Number,
    edited: gr.State | None,
) -> None:
    full = (section, *group.path)
    if group.path:
        heading = f"**{group.title or group.path[-1]}**"
        if group.description:
            heading += f" — {group.description}"
        gr.Markdown(heading)
    if group.optional:
        # Off means the key is absent: the library's own defaults, or the feature off, as
        # the object's description says.
        switch = gr.Checkbox(
            value=group.enabled,
            label=f"Configure {group.title or group.path[-1]}",
            interactive=True,
        )

        # The object's own module choice, if it has one: switched on, it starts on a module.
        choice = next(
            (
                item.choice
                for item in group.items
                if isinstance(item, FormChoice) and item.path == group.path
            ),
            None,
        )

        def toggle(enabled: bool, config: Config, rev: int) -> tuple[Config, int]:
            if (get_at(config, full) is not ABSENT) == enabled:
                return config, rev  # already so: no redraw
            return toggle_group(config, full, enabled, choice), rev + 1

        switch.input(
            toggle, inputs=[switch, draft, revision], outputs=[draft, revision]
        )
        if not group.enabled:
            return
    main = [i for i in group.items if not _advanced(i)]
    advanced = [i for i in group.items if _advanced(i)]
    for item in main:
        _item(model, section, item, draft, revision, edited)
    if group.options_list and not any(isinstance(i, FormChoice) for i in group.items):
        _options_picker(model, section, group.options_list, group.path, draft, revision)
    if advanced:
        # A nested object names its own block, so it is not read as the next heading's.
        label = (
            f"Advanced — {group.title or group.path[-1]}" if group.path else "Advanced"
        )
        with gr.Accordion(label, open=False):
            for item in advanced:
                _item(model, section, item, draft, revision, edited)


def _advanced(item: FormItem) -> bool:
    return not isinstance(item, FormChoice) and item.advanced


def section_title(model: AppModel, name: str) -> str:
    """A section's title: the app's, else its library's, else its key."""
    section = model.section(name)
    description = model.description(name)
    return section.title or (description.title if description else name)


def render_section(
    model: AppModel,
    name: str,
    config: Config,
    draft: gr.State,
    revision: gr.Number,
    edited: gr.State | None = None,
) -> None:
    """Draw the form of section *name* of *config*: its fields, from its library's
    schema; or why it cannot be drawn yet (its library not installed). Given *edited*
    (a counter), each field finished bumps it: the panel checks the section again."""
    section = model.section(name)
    description = model.description(name)
    if description is None:
        gr.Markdown(
            "This section's library is not installed"
            + (f" (the `{section.host_extra}` extra)" if section.host_extra else "")
            + ": **Install all** below, then reload the page."
        )
        return
    document = get_at(config, (name,))
    _group(
        model,
        name,
        layout(description.schema, document if document is not ABSENT else {}),
        draft,
        revision,
        edited,
    )
