"""The app's folder: its current config and its secrets (specs/config-folder.md).

An app runs from a folder, not from a config file. The folder holds ``config.json`` (the
config the Setup panel saves and the app runs with: one document per section) and ``.env``
(the secrets, [secrets.py](secrets.py)). The app's default config is not in the folder: it
is the starting point written there the first time, and what "Reset" goes back to. An app
may keep its own files in the folder too; app-setup leaves them alone.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["ConfigFolder", "FolderError", "default_folder"]


class FolderError(ValueError):
    """A file of the folder that cannot be read; the message names it."""


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
    def env_path(self) -> Path:
        return self.path / ".env"

    @property
    def launch_path(self) -> Path:
        """The launch settings (whether the app starts its session at launch): apart from
        the config, which stays exactly what the app runs with."""
        return self.path / "launch.json"

    @property
    def default_config(self) -> dict[str, Any]:
        return copy.deepcopy(self._default)

    def ensure(self) -> None:
        """Create the folder, and write the default config when there is none."""
        self.path.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            _write_json(self.config_path, self._default)

    def read_config(self) -> dict[str, Any]:
        return _read_object(self.config_path)

    def save_config(self, config: Mapping[str, Any]) -> None:
        _write_json(self.config_path, dict(config))

    def read_launch(self) -> dict[str, Any]:
        """The launch settings; empty while none was saved."""
        if not self.launch_path.exists():
            return {}
        return _read_object(self.launch_path)

    def save_launch(self, settings: Mapping[str, Any]) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        _write_json(self.launch_path, dict(settings))

    def reset_config(self) -> dict[str, Any]:
        """Write the default config back as the current one, and return it."""
        self.save_config(self._default)
        return self.default_config
