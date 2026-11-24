"""Whether an app starts its session at launch (specs/autostart.md).

An app that starts a session when it launches keeps the choice in its own config: a section
module-setup provides (``autostart_section``), holding ``{"autostart": bool}`` and drawn as a
checkbox on the Setup panel. ``--start`` / ``--no-start`` (``add_start_arguments``) override it
for one launch; ``starts_at_launch`` reads the flag, else the saved config, else the default.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from module_setup.app import AppModel, Section

__all__ = [
    "AutostartContract",
    "add_start_arguments",
    "autostart_section",
    "starts_at_launch",
]

_DEFAULT_NAME = "app"


class AutostartContract:
    """The module contract of the autostart section: one boolean, needing nothing."""

    def __init__(self, default: bool = True, title: str = "App") -> None:
        self.default = default
        self.title = title

    def config_schema(self) -> dict[str, Any]:
        return {
            "contract": 1,
            "distribution": "module-setup",
            "title": self.title,
            "schema": {
                "type": "object",
                "properties": {
                    "autostart": {
                        "type": "boolean",
                        "title": "Start at launch",
                        "description": "Start the session when the app launches.",
                        "default": self.default,
                    }
                },
            },
        }

    def required_extras(self, config: dict[str, Any]) -> list[str]:
        return []

    def check_config(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        if "autostart" in config and not isinstance(config["autostart"], bool):
            return [
                {
                    "path": "/autostart",
                    "message": "Must be true or false.",
                }
            ]
        return []

    def check_setup(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def prepare(
        self,
        config: dict[str, Any],
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        return None

    def options(self, name: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def probe(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "message": "Nothing to test.", "duration_s": 0.0}


def autostart_section(
    default: bool = True, name: str = _DEFAULT_NAME, title: str = "App"
) -> Section:
    """The section of ``config.json`` holding ``{"autostart": bool}``, *default* when absent."""
    return Section(name, AutostartContract(default, title), title=title)


def add_start_arguments(parser: argparse.ArgumentParser) -> None:
    """Add ``--start`` / ``--no-start`` to *parser*: ``options.start`` is True, False, or
    None when neither is given (the saved config decides)."""
    parser.add_argument(
        "--start",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Start the session at launch (--no-start: do not); "
        "without either, the saved config decides.",
    )


def starts_at_launch(model: AppModel, flag: bool | None) -> bool:
    """Whether the app starts its session now: *flag* when given; else the saved config's
    ``<section>.autostart``; else the section's default. The section is the one whose
    contract is the autostart contract; an app declaring none is read at ``app``, and does
    not start when that holds nothing."""
    if flag is not None:
        return flag
    name, default = _DEFAULT_NAME, False
    for section in model.app.sections:
        if isinstance(section.contract, AutostartContract):
            name, default = section.name, section.contract.default
            break
    document = model.saved_config().get(name)
    if isinstance(document, Mapping):
        value = document.get("autostart")
        if isinstance(value, bool):
            return value
    return default
