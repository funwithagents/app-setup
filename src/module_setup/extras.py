"""Requirements against the installed environment (specs/extras.md).

A contract names what a config needs in the library's own terms (``speech-lib[local-voice]``).
This module answers, from the metadata of the installed packages and without importing any of
them: is it installed, can it be on this machine, which extra of the host carries it; and it
installs a host's extras with uv.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

__all__ = [
    "Installer",
    "RequirementStatus",
    "find_installer",
    "host_extras",
    "requirement_status",
]

State = Literal["installed", "missing", "unavailable", "unknown"]


@dataclass(frozen=True)
class RequirementStatus:
    """Whether a requirement is met by the installed environment."""

    requirement: str
    state: State
    missing: tuple[str, ...] = ()
    detail: str = ""


def _requires(distribution: str) -> list[Requirement] | None:
    """The distribution's own requirements, or None when it is not installed."""
    try:
        raw = metadata.requires(distribution) or []
    except metadata.PackageNotFoundError:
        return None
    return [Requirement(text) for text in raw]


def _declared_extras(distribution: str) -> list[str]:
    """The extras the (installed) distribution declares, canonical, in declaration order."""
    declared = metadata.metadata(distribution).get_all("Provides-Extra") or []
    return [canonicalize_name(extra) for extra in declared]


_EXTRA_CLAUSE = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")


def _added_by(requirements: list[Requirement], extra: str) -> list[Requirement]:
    """The entries the extra adds: those whose marker names it. Returned whatever the
    platform; `_needed_here` tells which of them apply on this machine."""
    return [
        requirement
        for requirement in requirements
        if requirement.marker is not None
        and extra
        in {
            canonicalize_name(name)
            for name in _EXTRA_CLAUSE.findall(str(requirement.marker))
        }
    ]


def _needed_here(requirement: Requirement) -> bool:
    """Whether an entry an extra adds applies on this machine: its marker, evaluated with
    the extra it names selected (each spelling the marker uses is tried)."""
    marker = requirement.marker
    if marker is None:
        return True
    return any(
        marker.evaluate({"extra": name}) for name in _EXTRA_CLAUSE.findall(str(marker))
    )


def _plain(requirement: Requirement) -> str:
    """The requirement without its marker: `sdk[sockets]>=4`."""
    extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
    return f"{requirement.name}{extras}{requirement.specifier}"


def _missing(
    requirement: Requirement, seen: set[tuple[str, str]]
) -> tuple[list[str], bool]:
    """What *requirement* lacks in the environment, and whether an extra it names adds
    entries of which none applies on this machine."""
    name = canonicalize_name(requirement.name)
    try:
        version = metadata.version(requirement.name)
    except metadata.PackageNotFoundError:
        return [_plain(requirement)], False
    if (
        requirement.url is None
        and requirement.specifier
        and not requirement.specifier.contains(version, prereleases=True)
    ):
        return [f"{requirement.name}{requirement.specifier} (found {version})"], False

    own = _requires(requirement.name) or []
    lacking: list[str] = []
    off_platform = False
    for extra in sorted(canonicalize_name(e) for e in requirement.extras):
        if (name, extra) in seen:
            continue
        seen.add((name, extra))
        added = _added_by(own, extra)
        here = [entry for entry in added if _needed_here(entry)]
        if added and not here:
            off_platform = True
        for entry in here:
            found, _ = _missing(entry, seen)
            lacking += found
    return lacking, off_platform


def requirement_status(requirement: str) -> RequirementStatus:
    """Whether *requirement* (``speech-lib[local-voice]``) is installed here."""
    try:
        parsed = Requirement(requirement)
    except (InvalidRequirement, TypeError):
        return RequirementStatus(
            str(requirement), "unknown", detail=f"{requirement!r} is not a requirement."
        )
    if _requires(parsed.name) is None:
        return RequirementStatus(
            requirement,
            "missing",
            (parsed.name,),
            f"Missing: {parsed.name}.",
        )
    declared = _declared_extras(parsed.name)
    for extra in parsed.extras:
        if canonicalize_name(extra) not in declared:
            return RequirementStatus(
                requirement,
                "unknown",
                detail=f"{parsed.name} declares no extra {extra!r}.",
            )
    lacking, off_platform = _missing(parsed, set())
    if lacking:
        unique = tuple(dict.fromkeys(lacking))
        return RequirementStatus(
            requirement, "missing", unique, f"Missing: {', '.join(unique)}."
        )
    if off_platform:
        return RequirementStatus(
            requirement, "unavailable", detail="Not available on this platform."
        )
    return RequirementStatus(requirement, "installed", detail="Installed.")


def host_extras(requirement: str, *, host: str) -> tuple[str, ...]:
    """The extras of *host* to install so that *requirement* is met; ``()`` when the host
    declares none that carries it."""
    try:
        parsed = Requirement(requirement)
    except (InvalidRequirement, TypeError):
        return ()
    wanted = sorted(canonicalize_name(extra) for extra in parsed.extras)
    target = canonicalize_name(parsed.name)
    if target == canonicalize_name(host):
        return tuple(wanted)
    own = _requires(host)
    if own is None:
        return ()
    carriers: list[str] = []
    for extra in wanted:
        carrier = next(
            (
                canonicalize_name(spelling)
                for spelling in metadata.metadata(host).get_all("Provides-Extra") or []
                if any(
                    canonicalize_name(entry.name) == target
                    and extra in {canonicalize_name(e) for e in entry.extras}
                    for entry in _added_by(own, spelling)
                )
            ),
            None,
        )
        if carrier is None:
            return ()
        if carrier not in carriers:
            carriers.append(carrier)
    return tuple(carriers)


# --- Installing ---------------------------------------------------------------

_install_lock = threading.Lock()


def _project_dir(host: str) -> Path | None:
    """The local directory *host* was installed from, read from its install record."""
    try:
        record = metadata.distribution(host).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if not record:
        return None
    try:
        data = json.loads(record)
    except json.JSONDecodeError:
        return None
    url = data.get("url", "") if isinstance(data, dict) else ""
    parsed = urlparse(url)
    if parsed.scheme != "file" or "dir_info" not in data:
        return None
    return Path(url2pathname(unquote(parsed.path)))


@dataclass(frozen=True)
class Installer:
    """Installs extras of the host project with uv, from its lock."""

    project_dir: Path
    uv: str

    def _active(self) -> bool:
        """Whether the running interpreter is another environment than the project's."""
        return Path(sys.prefix).resolve() != (self.project_dir / ".venv").resolve()

    def command(self, extras: Sequence[str]) -> list[str]:
        command = [self.uv, "sync", "--inexact", "--frozen", "--no-default-groups"]
        if self._active():
            command.append("--active")
        for extra in extras:
            command += ["--extra", extra]
        return command

    def install(
        self,
        extras: Sequence[str],
        on_output: Callable[[str], None] | None = None,
    ) -> int:
        """Run the install, passing uv's output line by line to *on_output*; uv's exit
        code. One install at a time."""
        environment = dict(os.environ)
        if self._active():
            environment["VIRTUAL_ENV"] = sys.prefix
        with _install_lock:
            process = subprocess.Popen(
                self.command(extras),
                cwd=self.project_dir,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert process.stdout is not None
            for line in process.stdout:
                if on_output is not None:
                    on_output(line.rstrip("\n"))
            code = process.wait()
        importlib.invalidate_caches()
        return code


def find_installer(host: str) -> Installer | str:
    """The installer of *host*'s project, or the sentence saying why there is none."""
    project_dir = _project_dir(host)
    if project_dir is None:
        return (
            f"{host} is not installed from a local project directory, so there is no "
            "lock file to install from."
        )
    if not (project_dir / "uv.lock").is_file():
        return f"{project_dir} has no uv.lock to install from."
    uv = shutil.which("uv")
    if uv is None:
        return "uv is not on the PATH; install it to add extras from the app."
    return Installer(project_dir=project_dir, uv=uv)
