"""An app made of sections, and what its Setup and Secrets panels do (specs/app.md).

An ``App`` declares its sections (one library's contract each) and its default config.
``AppModel`` is everything the panels do, with no gradio: read and save the config, check it
section by section, tell what the machine is missing and which of the host's extras installs
it, install, prepare, probe, and say why the config cannot run yet. Running it is the app's.
"""

from __future__ import annotations

import copy
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app_setup.contract import (
    ContractError,
    Description,
    SetupContract,
    parse_description,
)
from app_setup.extras import find_installer, host_extras, requirement_status
from app_setup.folder import ConfigFolder
from app_setup.form import pointer, secret_variables
from app_setup.secrets import SecretStore, SecretVariable

__all__ = [
    "App",
    "AppModel",
    "InstallError",
    "Prepared",
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
    # Whether the app starts its session at launch by default; None: the app has no
    # autostart. The user's choice is kept in the folder's launch.json (specs/autostart.md).
    autostart: bool | None = None


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
    # False: the library gets it itself when a session needs it (slower, but not blocking).
    required: bool
    # For an extra: the host's extras that install it ("" when none carries it).
    host_extras: tuple[str, ...] = field(default=())
    # For a key: the environment variable it is about (a field to set it on its line).
    variable: str | None = None

    @property
    def is_extra(self) -> bool:
        return self.id.startswith("extra:")

    @property
    def installable(self) -> bool:
        return self.is_extra and self.status != "ready" and bool(self.host_extras)

    @property
    def blocking(self) -> bool:
        """Missing, and a session cannot start without it."""
        return self.status == "missing" and self.required

    @property
    def deferred(self) -> bool:
        """Missing, but a session would get it itself (slower): better prepared now."""
        return self.status == "missing" and not self.required


@dataclass(frozen=True)
class Prepared:
    """The outcome of preparing one item: ready, or the failure's message."""

    item: SetupItem
    ok: bool
    message: str
    duration_s: float


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


# The keys every `check_setup` item carries (specs/module-contract.md "check_setup").
_ITEM_KEYS = ("id", "title", "status", "detail", "preparable", "required")


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
            "required": True,
        }
    return {
        "id": f"extra:{requirement}",
        "title": requirement,
        # "unavailable" is told apart by `_item`, which reads the same metadata.
        "status": "missing" if state.state in ("missing", "unavailable") else "unknown",
        "detail": state.detail,
        "preparable": False,
        "required": True,
    }


def _named(variables: Sequence[str], *texts: str) -> str | None:
    """The first of *variables* one of *texts* names as a whole word: the variable a key
    item is about (the contract gives an item no kind)."""
    for variable in variables:
        word = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(variable)}(?![A-Za-z0-9_])")
        if any(word.search(text) for text in texts):
            return variable
    return None


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
        # One lock per item being prepared, so an item is never prepared twice at once.
        self._items_lock = threading.Lock()
        self._item_locks: dict[tuple[str, str], threading.Lock] = {}

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

    def used(
        self, config: Mapping[str, Any], sections: Iterable[str] | None = None
    ) -> list[str]:
        """The sections this config uses, in declaration order; only those of
        *sections* when given (the Setup panel acts on one section at a time)."""
        wanted = None if sections is None else set(sections)
        return [
            section.name
            for section in self.app.sections
            if (section.when is None or section.when(config))
            and (wanted is None or section.name in wanted)
        ]

    @property
    def _base_dir(self) -> str:
        """What a section's relative paths are relative to, handed to its library."""
        return str(self.folder.path)

    @property
    def path(self) -> Path:
        """The app's folder: where a section's relative paths resolve."""
        return self.folder.path

    # --- The config.

    def autostart(self) -> bool | None:
        """Whether the app starts its session at launch: the folder's ``launch.json``, else
        the app's default; None for an app with no autostart."""
        if self.app.autostart is None:
            return None
        value = self.folder.read_launch().get("autostart")
        return value if isinstance(value, bool) else self.app.autostart

    def set_autostart(self, on: bool) -> None:
        """Keep the user's choice in ``launch.json``. Not refused while the config is
        locked: it only matters at the next launch."""
        if self.app.autostart is None:
            raise RuntimeError(f"{self.title} has no autostart.")
        self.folder.save_launch({**self.folder.read_launch(), "autostart": bool(on)})

    def locked(self) -> bool:
        """Whether the app is using the saved config (a session running)."""
        return self._locked is not None and self._locked()

    def saved_config(self) -> dict[str, Any]:
        return self.folder.read_config()

    def unsaved(self, draft: Mapping[str, Any]) -> bool:
        """Whether *draft* differs from the saved config. The whole config is compared, not
        only the sections it uses: Save writes the whole draft, a section not used keeps its
        document, and a section's `when` may read keys outside the sections."""
        return dict(draft) != self.saved_config()

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

    def check_config(
        self, config: Mapping[str, Any], sections: Iterable[str] | None = None
    ) -> list[Problem]:
        """What is wrong in the config itself, for every section it uses (of
        *sections*, when given)."""
        found: list[Problem] = []
        for name in self.used(config, sections):
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

    def check_setup(
        self, config: Mapping[str, Any], sections: Iterable[str] | None = None
    ) -> list[SetupItem]:
        """What this machine is missing for every section the config uses: each section's
        `check_setup` items, an extra's item told which of the host's extras installs it. A
        section whose document has problems is not asked (the contract asks `check_setup`
        only about a config `check_config` accepts): its extras are read instead from its
        `required_extras`, which takes an incomplete config, and the installed packages'
        metadata, so what it needs can be installed while the config is being fixed (a
        voice list that needs the extra, for one). Only *sections*, when given."""
        found: list[SetupItem] = []
        for name in self.used(config, sections):
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
                        required=True,
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
                # The keys too: the variables the document names are read from the
                # schema, so a key is asked for while a field is still being filled in.
                for key in self._key_items(name, document):
                    found.append(self._item(name, key, [key["title"]]))
                continue
            description = self.description(name)
            variables = (
                [v for _, v in secret_variables(description.schema, document)]
                if description is not None
                else []
            )
            for item in contract.check_setup(
                copy.deepcopy(dict(document)), base_dir=self._base_dir
            ):
                found.append(self._item(name, item, variables))
        return found

    def _key_items(
        self, section: str, document: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """A `check_setup` item per environment variable *document* names for a key, from
        the schema and the environment alone: for a section whose config the library cannot
        be asked about yet."""
        description = self.description(section)
        if description is None:
            return []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path, variable in secret_variables(description.schema, document):
            if variable in seen:
                continue
            seen.add(variable)
            present = self.secrets.source(variable) != "missing"
            items.append(
                {
                    "id": f"key:{variable}",
                    "title": variable,
                    "status": "ready" if present else "missing",
                    "detail": "Set."
                    if present
                    else f"Set the environment variable {variable} (named by "
                    f"'{path.rsplit('/', 1)[-1]}').",
                    "preparable": False,
                    "required": True,
                }
            )
        return items

    def _item(
        self,
        section: str,
        item: Mapping[str, Any],
        variables: Sequence[str] = (),
    ) -> SetupItem:
        absent = [key for key in _ITEM_KEYS if key not in item]
        if absent:
            raise ContractError(
                f"section '{section}': check_setup item {item.get('id', item)!r} lacks {absent}"
            )
        if not item["required"] and not item["preparable"]:
            raise ContractError(
                f"section '{section}': check_setup item {item['id']!r} is neither required "
                "nor preparable: what a session gets by itself, prepare can get ahead"
            )
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
            preparable=bool(item["preparable"]),
            required=bool(item["required"]),
            host_extras=carriers,
            variable=None
            if identifier.startswith("extra:") or item["preparable"]
            else _named(variables, identifier, str(item.get("title", ""))),
        )

    def blockers(
        self, config: Mapping[str, Any], sections: Iterable[str] | None = None
    ) -> list[str]:
        """Why *config* cannot run on this machine yet, in words; empty when it can: its
        problems, then every missing required item. A missing item that is not required does
        not block (the session gets it), nor does an `unknown` one. Only *sections*, when
        given."""
        reasons = [
            f"{p.path}: {p.message}" for p in self.check_config(config, sections)
        ]
        reasons += [
            f"{item.section}: {item.title} — {item.detail}"
            for item in self.check_setup(config, sections)
            if item.blocking
        ]
        return reasons

    def to_prepare(
        self, config: Mapping[str, Any], sections: Iterable[str] | None = None
    ) -> list[SetupItem]:
        """The preparable items not ready yet: what Prepare all prepares."""
        return [
            item
            for item in self.check_setup(config, sections)
            if item.preparable and item.status != "ready"
        ]

    def deferred(
        self, config: Mapping[str, Any], sections: Iterable[str] | None = None
    ) -> list[SetupItem]:
        """The missing items that are not required: what a session would get by itself,
        slower, unless they are prepared first."""
        return [item for item in self.check_setup(config, sections) if item.deferred]

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

    def missing_extras(
        self, config: Mapping[str, Any], sections: Iterable[str] | None = None
    ) -> list[str]:
        """The host extras that install what *config* is missing (for *sections*, when
        given)."""
        return list(
            dict.fromkeys(
                extra
                for item in self.check_setup(config, sections)
                if item.installable
                for extra in item.host_extras[:1]
            )
        )

    def prepare(
        self,
        config: Mapping[str, Any],
        items: Sequence[SetupItem] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[Prepared]:
        """Make *items* ready, all at the same time, each on its own thread through its
        section's contract; every preparable item not ready yet when *items* is None.

        *on_progress* receives each contract event with the item's ``section`` and ``id``
        added, from any thread. Blocks until every item is done; one ``Prepared`` per item, in
        the order given. A failure is that item's outcome: it never stops the others, and
        nothing is raised for an item."""
        chosen = list(self.to_prepare(config) if items is None else items)
        outcomes: list[Prepared | None] = [None] * len(chosen)

        def run(index: int, item: SetupItem) -> None:
            outcomes[index] = self.prepare_item(config, item, on_progress)

        threads = [
            threading.Thread(
                target=run, args=(index, item), name=f"prepare-{item.id}", daemon=True
            )
            for index, item in enumerate(chosen)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return [outcome for outcome in outcomes if outcome is not None]

    def prepare_item(
        self,
        config: Mapping[str, Any],
        item: SetupItem,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> Prepared:
        """Make one *item* ready through its section's contract; its outcome, never raised.
        *on_progress* receives the contract's events with ``section`` and ``id`` added."""
        started = time.monotonic()

        def outcome(ok: bool, message: str) -> Prepared:
            return Prepared(item, ok, message, time.monotonic() - started)

        contract = self.contract(item.section)
        document = config.get(item.section)
        if contract is None or not isinstance(document, Mapping):
            return outcome(False, self.unavailable(item.section) or "Not installed.")

        def progress(event: dict[str, Any]) -> None:
            if on_progress is not None:
                on_progress({**event, "section": item.section, "id": item.id})

        guard = self._preparing(item)
        if not guard.acquire(blocking=False):
            return outcome(False, "Already being prepared.")
        try:
            contract.prepare(
                copy.deepcopy(dict(document)),
                item.id,
                on_progress=progress,
                base_dir=self._base_dir,
            )
        except Exception as exc:  # noqa: BLE001 - the item's outcome, shown on its row
            return outcome(False, str(exc) or type(exc).__name__)
        finally:
            guard.release()
        return outcome(True, "Ready.")

    def _preparing(self, item: SetupItem) -> threading.Lock:
        """The lock that keeps one item from being prepared twice at once."""
        with self._items_lock:
            return self._item_locks.setdefault(
                (item.section, item.id), threading.Lock()
            )

    def probe(self, config: Mapping[str, Any], name: str) -> dict[str, Any]:
        contract = self.contract(name)
        if contract is None:
            return {
                "ok": False,
                "message": self.unavailable(name) or "Not installed.",
                "duration_s": 0.0,
            }
        return contract.probe(
            copy.deepcopy(dict(config.get(name) or {})), base_dir=self._base_dir
        )

    def options(
        self, config: Mapping[str, Any], name: str, list_name: str
    ) -> list[dict[str, Any]]:
        contract = self.contract(name)
        if contract is None:
            return []
        return contract.options(
            list_name,
            copy.deepcopy(dict(config.get(name) or {})),
            base_dir=self._base_dir,
        )

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
