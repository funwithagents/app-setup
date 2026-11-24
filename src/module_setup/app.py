"""An app made of sections, and what its Setup and Secrets panels do (specs/app.md).

An ``App`` declares its sections (one library's contract each) and its default config.
``AppModel`` is everything the panels do, with no gradio: read and save the config, check it
section by section, tell what the machine is missing and which of the host's extras installs
it, install, prepare, probe, and say why the config cannot run yet. Running it is the app's.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from module_setup.contract import Description, SetupContract, parse_description
from module_setup.extras import find_installer, host_extras, requirement_status
from module_setup.folder import ConfigFolder
from module_setup.form import pointer, secret_variables
from module_setup.secrets import SecretStore, SecretVariable

__all__ = [
    "App",
    "AppModel",
    "InstallError",
    "Problem",
    "Section",
    "SetupItem",
]

ContractSource = SetupContract | Callable[[], SetupContract]


@dataclass(frozen=True)
class Section:
    """One section of the app's config: a key of ``config.json`` and the contract of the
    library that owns its document.

    *contract* may be a function returning it, for a library the host installs only with one
    of its own extras: the section then shows that extra (*host_extra*) as missing until the
    import succeeds. *when*, given the whole config, says whether the section is used (a
    section for one embodiment only); an unused section is neither drawn nor checked.
    """

    name: str
    contract: ContractSource
    title: str | None = None
    when: Callable[[Mapping[str, Any]], bool] | None = None
    host_extra: str | None = None


@dataclass(frozen=True)
class App:
    """What an app declares to get its Setup and Secrets panels."""

    name: str  # the folder's default name, and the app's title unless *title* is given
    host: str  # the distribution the environment is installed from
    sections: tuple[Section, ...]
    default_config: Mapping[str, Any]
    title: str | None = None


@dataclass(frozen=True)
class Problem:
    """Something wrong in the config itself, at a JSON Pointer into the app's config."""

    section: str
    path: str
    message: str


@dataclass(frozen=True)
class SetupItem:
    """One thing a section needs on this machine (an item of the contract's `check_setup`),
    with what the app can do about it."""

    section: str
    id: str
    title: str
    status: str  # "ready", "missing" or "unknown"
    detail: str
    preparable: bool
    # For an extra: the host's extras that install it ("" when none carries it).
    host_extras: tuple[str, ...] = field(default=())

    @property
    def is_extra(self) -> bool:
        return self.id.startswith("extra:")

    @property
    def installable(self) -> bool:
        return self.is_extra and self.status != "ready" and bool(self.host_extras)


class InstallError(RuntimeError):
    """The app cannot install for the user; the message says why."""


class _Loaded:
    """A section's contract, loaded once it imports."""

    def __init__(self, section: Section) -> None:
        self.section = section
        self.contract: SetupContract | None = None
        self.description: Description | None = None
        self.error: str | None = None

    def load(self) -> SetupContract | None:
        if self.contract is not None:
            return self.contract
        if self.error is not None:
            return None  # tried and failed: retried after an install
        source = self.section.contract
        try:
            # A contract object has `config_schema`; anything else callable loads one.
            contract: SetupContract = (
                source if hasattr(source, "config_schema") else source()  # type: ignore[operator]
            )
            description = parse_description(contract.config_schema())
        except ImportError as exc:
            self.error = str(exc) or type(exc).__name__
            return None
        self.contract, self.description, self.error = contract, description, None
        return self.contract


def _extra_item(requirement: str) -> dict[str, Any]:
    """A `check_setup` item for *requirement*, from the installed packages' metadata alone:
    for a section whose config the library cannot be asked about yet."""
    state = requirement_status(requirement)
    if state.state == "installed":
        return {
            "id": f"extra:{requirement}",
            "title": requirement,
            "status": "ready",
            "detail": "Installed.",
            "preparable": False,
        }
    return {
        "id": f"extra:{requirement}",
        "title": requirement,
        # "unavailable" is told apart by `_item`, which reads the same metadata.
        "status": "missing" if state.state in ("missing", "unavailable") else "unknown",
        "detail": state.detail,
        "preparable": False,
    }


class AppModel:
    """The app's state and actions, shared by every browser tab on the page.

    Building it makes the folder ready (created, the default config written when there is
    none). Without *secrets*, it opens the folder's ``.env`` over ``os.environ`` and loads
    it, so the libraries find their keys. *locked*, the app's, says when the config is in
    use (a session running): saving and resetting are refused then.
    """

    def __init__(
        self,
        app: App,
        folder: ConfigFolder,
        secrets: SecretStore | None = None,
        locked: Callable[[], bool] | None = None,
    ) -> None:
        self.app = app
        self.folder = folder
        folder.ensure()
        if secrets is None:
            secrets = SecretStore(folder.env_path)
            secrets.load()
        self.secrets = secrets
        self._locked = locked
        self._loaded = {section.name: _Loaded(section) for section in app.sections}
        self._lock = threading.Lock()

    # --- Sections and their contracts.

    @property
    def title(self) -> str:
        return self.app.title or self.app.name

    def section(self, name: str) -> Section:
        return self._loaded[name].section

    def contract(self, name: str) -> SetupContract | None:
        """The section's contract, or None while its library is not installed."""
        return self._loaded[name].load()

    def description(self, name: str) -> Description | None:
        loaded = self._loaded[name]
        loaded.load()
        return loaded.description

    def unavailable(self, name: str) -> str | None:
        """Why the section's library cannot be imported, or None."""
        loaded = self._loaded[name]
        loaded.load()
        return loaded.error

    def used(self, config: Mapping[str, Any]) -> list[str]:
        """The sections this config uses, in declaration order."""
        return [
            section.name
            for section in self.app.sections
            if section.when is None or section.when(config)
        ]

    @property
    def path(self) -> Path:
        """The app's folder: where a section's relative paths resolve."""
        return self.folder.path

    # --- The config.

    def locked(self) -> bool:
        """Whether the app is using the saved config (a session running)."""
        return self._locked is not None and self._locked()

    def saved_config(self) -> dict[str, Any]:
        return self.folder.read_config()

    def save(self, config: Mapping[str, Any]) -> None:
        """Save *config* as the current one. Refused while the config is locked."""
        self._refuse_when_locked()
        self.folder.save_config(config)

    def reset(self) -> dict[str, Any]:
        """Save the app's default config as the current one, and return it."""
        self._refuse_when_locked()
        return self.folder.reset_config()

    def _refuse_when_locked(self) -> None:
        if self.locked():
            raise RuntimeError("Stop the session before changing its config.")

    def used_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """The documents of the sections *config* uses: what the app runs with."""
        return {name: copy.deepcopy(config.get(name)) for name in self.used(config)}

    # --- Checking.

    def check_config(self, config: Mapping[str, Any]) -> list[Problem]:
        """What is wrong in the config itself, for every section it uses."""
        found: list[Problem] = []
        for name in self.used(config):
            contract = self.contract(name)
            if contract is None:
                continue  # reported by check_setup, which can install it
            document = config.get(name)
            if not isinstance(document, Mapping):
                found.append(
                    Problem(name, pointer((name,)), f"The '{name}' section is missing.")
                )
                continue
            for problem in contract.check_config(copy.deepcopy(dict(document))):
                found.append(
                    Problem(
                        name,
                        pointer((name,)) + problem.get("path", ""),
                        problem["message"],
                    )
                )
        return found

    def check_setup(self, config: Mapping[str, Any]) -> list[SetupItem]:
        """What this machine is missing for every section the config uses: each section's
        `check_setup` items, an extra's item told which of the host's extras installs it. A
        section whose document has problems is not asked (the contract asks `check_setup`
        only about a config `check_config` accepts): its extras are read instead from its
        `required_extras`, which takes an incomplete config, and the installed packages'
        metadata, so what it needs can be installed while the config is being fixed (a
        voice list that needs the extra, for one)."""
        found: list[SetupItem] = []
        for name in self.used(config):
            section = self.section(name)
            contract = self.contract(name)
            if contract is None:
                extras = (section.host_extra,) if section.host_extra else ()
                found.append(
                    SetupItem(
                        section=name,
                        id=f"extra:{self.app.host}[{section.host_extra}]"
                        if section.host_extra
                        else f"extra:{name}",
                        title=f"{section.title or name} library",
                        status="missing",
                        detail=self.unavailable(name) or "Not installed.",
                        preparable=False,
                        host_extras=extras,
                    )
                )
                continue
            document = config.get(name)
            if not isinstance(document, Mapping):
                continue  # reported by check_config
            if contract.check_config(copy.deepcopy(dict(document))):
                for requirement in contract.required_extras(
                    copy.deepcopy(dict(document))
                ):
                    found.append(self._item(name, _extra_item(requirement)))
                continue
            for item in contract.check_setup(copy.deepcopy(dict(document))):
                found.append(self._item(name, item))
        return found

    def _item(self, section: str, item: Mapping[str, Any]) -> SetupItem:
        identifier = str(item.get("id", ""))
        detail = str(item.get("detail", ""))
        carriers: tuple[str, ...] = ()
        status = str(item.get("status", "unknown"))
        if identifier.startswith("extra:"):
            requirement = identifier[len("extra:") :]
            carriers = host_extras(requirement, host=self.app.host)
            if status != "ready":
                state = requirement_status(requirement).state
                if state == "unavailable":
                    detail = "Not available on this platform."
                    carriers = ()
                elif not carriers:
                    detail += f" No extra of {self.app.host} installs {requirement}."
        return SetupItem(
            section=section,
            id=identifier,
            title=str(item.get("title", identifier)),
            status=status,
            detail=detail,
            preparable=bool(item.get("preparable", False)),
            host_extras=carriers,
        )

    def blockers(self, config: Mapping[str, Any]) -> list[str]:
        """Why *config* cannot run on this machine yet, in words; empty when it can: its
        problems, then every missing item. An `unknown` item does not block."""
        reasons = [f"{p.path}: {p.message}" for p in self.check_config(config)]
        reasons += [
            f"{item.section}: {item.title} — {item.detail}"
            for item in self.check_setup(config)
            if item.status == "missing"
        ]
        return reasons

    # --- Acting on the machine.

    def install(
        self, extras: Iterable[str], on_output: Callable[[str], None] | None = None
    ) -> int:
        """Install the host's *extras* from its lock; uv's exit code."""
        extras = list(dict.fromkeys(extras))
        if not extras:
            return 0
        installer = find_installer(self.app.host)
        if isinstance(installer, str):
            raise InstallError(installer)
        with self._lock:
            code = installer.install(extras, on_output)
        for loaded in self._loaded.values():
            if loaded.contract is None:
                loaded.error = None  # retried at the next use
        return code

    def missing_extras(self, config: Mapping[str, Any]) -> list[str]:
        """The host extras that install what *config* is missing."""
        return list(
            dict.fromkeys(
                extra
                for item in self.check_setup(config)
                if item.installable
                for extra in item.host_extras[:1]
            )
        )

    def prepare(
        self,
        config: Mapping[str, Any],
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        sections: Sequence[str] | None = None,
    ) -> None:
        """Prepare the sections that have something preparable missing."""
        items = self.check_setup(config)
        wanted = {
            item.section for item in items if item.preparable and item.status != "ready"
        }
        for name in self.used(config):
            if name not in wanted or (sections is not None and name not in sections):
                continue
            contract = self.contract(name)
            if contract is not None:
                contract.prepare(copy.deepcopy(dict(config[name])), on_progress)

    def probe(self, config: Mapping[str, Any], name: str) -> dict[str, Any]:
        contract = self.contract(name)
        if contract is None:
            return {
                "ok": False,
                "message": self.unavailable(name) or "Not installed.",
                "duration_s": 0.0,
            }
        return contract.probe(copy.deepcopy(dict(config.get(name) or {})))

    def options(
        self, config: Mapping[str, Any], name: str, list_name: str
    ) -> list[dict[str, Any]]:
        contract = self.contract(name)
        if contract is None:
            return []
        return contract.options(list_name, copy.deepcopy(dict(config.get(name) or {})))

    # --- Secrets.

    def secret_variables(
        self, config: Mapping[str, Any]
    ) -> list[tuple[SecretVariable, list[str]]]:
        """Each environment variable the config names for a secret, its source, and the
        pointers that name it."""
        named: dict[str, list[str]] = {}
        for name in self.used(config):
            description = self.description(name)
            document = config.get(name)
            if description is None or not isinstance(document, Mapping):
                continue
            for path, variable in secret_variables(description.schema, document):
                named.setdefault(variable, []).append(pointer((name,)) + path)
        return [
            (variable, named[variable.name])
            for variable in self.secrets.variables(named)
        ]
