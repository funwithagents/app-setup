"""The app's folder: its current config, its settings and its secrets (specs/config-folder.md).

An app runs from a folder, not from a config file. The folder holds ``config.json`` (the
config the Setup tab saves and a session starts from: one document per section),
``settings.json`` (the app's own settings: autostart) and ``.env`` (the secrets,
[secrets.py](secrets.py)). The app's default config is not in the folder: it is the
starting point written there on first launch, and what "Reset" goes back to.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["ConfigFolder", "FolderError", "Settings", "default_folder"]


class FolderError(ValueError):
    """A file of the folder that cannot be read; the message names it."""


@dataclass(frozen=True)
class Settings:
    """The app's own settings, kept next to its config."""

    autostart: bool = False


def default_folder(app_name: str) -> Path:
    """Where an app's folder lives unless it is given one: ``$XDG_CONFIG_HOME/<name>``, else
    ``~/.config/<name>``, on every platform."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / app_name


def _write_json(path: Path, data: Any) -> None:
    """Write *data* as indented JSON, replacing the file in one step, so a reader never sees
    half a file."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FolderError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FolderError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FolderError(f"{path} must hold a JSON object")
    return data


class ConfigFolder:
    """The files of one app's folder."""

    def __init__(self, path: Path, default_config: Mapping[str, Any]) -> None:
        self.path = Path(path)
        self._default = copy.deepcopy(dict(default_config))

    @property
    def config_path(self) -> Path:
        return self.path / "config.json"

    @property
    def settings_path(self) -> Path:
        return self.path / "settings.json"

    @property
    def env_path(self) -> Path:
        return self.path / ".env"

    @property
    def default_config(self) -> dict[str, Any]:
        return copy.deepcopy(self._default)

    def ensure(self) -> None:
        """Create the folder, and write the default config and settings that are missing."""
        self.path.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            _write_json(self.config_path, self._default)
        if not self.settings_path.exists():
            _write_json(self.settings_path, {"autostart": False})

    def read_config(self) -> dict[str, Any]:
        return _read_object(self.config_path)

    def save_config(self, config: Mapping[str, Any]) -> None:
        _write_json(self.config_path, dict(config))

    def reset_config(self) -> dict[str, Any]:
        """Write the default config back as the current one, and return it."""
        self.save_config(self._default)
        return self.default_config

    def read_settings(self) -> Settings:
        data = _read_object(self.settings_path)
        autostart = data.get("autostart", False)
        if not isinstance(autostart, bool):
            raise FolderError(
                f"{self.settings_path}: 'autostart' must be true or false"
            )
        return Settings(autostart=autostart)

    def save_settings(self, settings: Settings) -> None:
        data = _read_object(self.settings_path) if self.settings_path.exists() else {}
        data["autostart"] = settings.autostart
        _write_json(self.settings_path, data)
