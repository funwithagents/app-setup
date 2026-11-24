"""The secrets of an app: environment variables, from the shell or the folder's ``.env``
(specs/secrets.md).

A library reads its keys from the process environment, through the variable names its config
gives (`x-secret-env` fields). The app keeps the keys a user types in its folder's ``.env``
and loads them into the environment, so the libraries see them as they would a shell
variable. A variable already set in the shell wins over the file. A value is written, never
read back to the page: only where each variable comes from is shown.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = ["SecretStore", "SecretVariable", "format_env", "parse_env"]

Source = Literal["shell", "file", "missing"]

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        body, out, index = raw[1:-1], [], 0
        while index < len(body):
            char = body[index]
            if char == "\\" and index + 1 < len(body):
                out.append(_ESCAPES.get(body[index + 1], "\\" + body[index + 1]))
                index += 2
                continue
            out.append(char)
            index += 1
        return "".join(out)
    # Unquoted: a ` #` starts a comment.
    return re.split(r"\s+#", raw, maxsplit=1)[0]


def parse_env(text: str) -> dict[str, str]:
    """The variables of a ``.env`` text: ``NAME=value`` lines, ``export`` allowed, values
    plain, ``'single'`` or ``"double"`` quoted (with ``\\n``, ``\\"``, ``\\\\`` escapes);
    blank lines and ``#`` comments skipped. A later line wins."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if match is not None:
            found[match.group(1)] = _unquote(match.group(2))
    return found


def format_env(name: str, value: str) -> str:
    """One ``.env`` line for *name*, the value double-quoted and escaped."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'{name}="{escaped}"'


@dataclass(frozen=True)
class SecretVariable:
    """A variable the config names, and where its value comes from. *in_file* says the
    folder's ``.env`` sets it too: unused when the shell's value wins."""

    name: str
    source: Source
    in_file: bool = False

    @property
    def shadowed(self) -> bool:
        """The ``.env`` sets it, but the shell's value is the one in use."""
        return self.source == "shell" and self.in_file


class SecretStore:
    """The folder's ``.env`` and the process environment it feeds.

    The variables set (non-empty) in *environ* when the store is created are the shell's:
    the file never overrides them.
    """

    def __init__(
        self, env_path: Path, environ: MutableMapping[str, str] | None = None
    ) -> None:
        self.env_path = Path(env_path)
        self._environ: MutableMapping[str, str] = (
            os.environ if environ is None else environ
        )
        self._shell = {name for name, value in self._environ.items() if value}
        self._loaded: set[str] = set()

    def _file(self) -> dict[str, str]:
        try:
            return parse_env(self.env_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def load(self) -> None:
        """Put the file's variables into the environment (the shell's untouched), and take
        out those an earlier load put there that the file no longer has."""
        values = self._file()
        for name in self._loaded - set(values):
            self._environ.pop(name, None)
        self._loaded = set()
        for name, value in values.items():
            if name in self._shell:
                continue
            self._environ[name] = value
            self._loaded.add(name)

    def source(self, name: str) -> Source:
        if name in self._shell:
            return "shell"
        if self._file().get(name):
            return "file"
        return "missing"

    def variables(self, names: Iterable[str]) -> list[SecretVariable]:
        """Each of *names* once, in order, with its source and whether the file sets it
        too."""
        file = self._file()
        return [
            SecretVariable(name, self.source(name), in_file=bool(file.get(name)))
            for name in dict.fromkeys(names)
        ]

    def file_names(self) -> list[str]:
        """The variables the folder's ``.env`` sets, in the file's order; names only."""
        return [name for name, value in self._file().items() if value]

    def _rewrite(self, name: str, line: str | None) -> None:
        try:
            lines = self.env_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        kept: list[str] = []
        replaced = False
        for existing in lines:
            match = _LINE.match(existing)
            if (
                match is not None
                and match.group(1) == name
                and not existing.lstrip().startswith("#")
            ):
                if line is not None and not replaced:
                    kept.append(line)
                    replaced = True
                continue
            kept.append(existing)
        if line is not None and not replaced:
            kept.append(line)
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.write_text(
            "\n".join(kept) + ("\n" if kept else ""), encoding="utf-8"
        )
        self.env_path.chmod(0o600)

    def set(self, name: str, value: str) -> Source:
        """Write *name* to the file and load it; the source the variable now has (the shell's
        value still wins)."""
        if not _NAME.match(name):
            raise ValueError(f"{name!r} is not a variable name")
        if not value:
            raise ValueError("an empty value: remove the variable instead")
        self._rewrite(name, format_env(name, value))
        self.load()
        return self.source(name)

    def remove(self, name: str) -> Source:
        """Take *name* out of the file and the environment it fed."""
        self._rewrite(name, None)
        self.load()
        return self.source(name)
