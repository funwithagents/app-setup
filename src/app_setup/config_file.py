"""A single config file as the config's source (specs/config-file.md).

Next to the app's folder ([folder.py](folder.py)), a file is the other place a config can
come from: an app running a given file as it is (``--config FILE``, never written), or a
config app editing one (written back by Save). The file must exist: nothing is created, and
there is no default to go back to. Its keys come from the ``.env`` in its directory, unless
another is given; its relative paths resolve against its directory.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app_setup.folder import FolderError, read_json_object, write_json

__all__ = ["ConfigFile", "ConfigFileError"]


class ConfigFileError(ValueError):
    """A config file that is missing or cannot be read; the message names it."""


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        reason = "is not a file" if path.exists() else "does not exist"
        raise ConfigFileError(f"config file {path} {reason}")
    try:
        return read_json_object(path)
    except FolderError as exc:
        raise ConfigFileError(str(exc)) from exc


class ConfigFile:
    """One config file: read each time it is asked for, written back only when
    *writable*. *env_path* is the ``.env`` its keys come from (the one in its directory
    unless given)."""

    def __init__(
        self,
        path: Path | str,
        *,
        env_path: Path | str | None = None,
        writable: bool = False,
    ) -> None:
        self.path = Path(path)
        self._env_path = Path(env_path) if env_path is not None else None
        self._writable = writable
        _read(self.path)  # refused now, at launch, rather than at the first read

    @property
    def config_path(self) -> Path:
        return self.path

    @property
    def env_path(self) -> Path:
        return (
            self._env_path if self._env_path is not None else self.path.parent / ".env"
        )

    @property
    def base_dir(self) -> Path:
        """Where the config's relative paths resolve: the file's directory."""
        return self.path.absolute().parent

    @property
    def writable(self) -> bool:
        return self._writable

    @property
    def resettable(self) -> bool:
        """A file has no default to go back to."""
        return False

    def ensure(self) -> None:
        """Nothing to make ready: the file was checked when this was built, and a file is
        never created."""

    def read_config(self) -> dict[str, Any]:
        """The file as it is now: a hand edit is seen at the next read."""
        return _read(self.path)

    def save_config(self, config: Mapping[str, Any]) -> None:
        """Write *config* back to the file, keeping its permissions. Refused for a file
        that is not writable (an app running it as it is)."""
        if not self._writable:
            raise RuntimeError(f"{self.path} is run as it is: it is never written.")
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        write_json(self.path, dict(config))
        os.chmod(self.path, mode)

    def reset_config(self) -> dict[str, Any]:
        raise RuntimeError(f"{self.path} has no default config to reset to.")

    def read_launch(self) -> dict[str, Any]:
        """A file has no launch settings."""
        return {}

    def save_launch(self, settings: Mapping[str, Any]) -> None:
        raise RuntimeError(f"{self.path} has no launch settings.")
