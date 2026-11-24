---
code:
  - src/app_setup/extras.py
tests:
  - tests/test_extras.py
---

# Extras

**Status:** Implemented

## Purpose

A contract says what a config needs in the library's own terms: `speech-lib[local-voice]` ([module-contract.md](module-contract.md), "`required_extras`"). This spec is what app-setup does with such a requirement: tell whether it is installed, whether it can be on this machine, which extra of the **host** carries it, and install it. None of it needs code in the library: everything is read from the metadata of the installed packages.

## Is a requirement installed

```python
@dataclass(frozen=True)
class RequirementStatus:
    requirement: str  # "speech-lib[local-voice]", as given
    state: Literal["installed", "missing", "unavailable", "unknown"]
    missing: tuple[
        str, ...
    ]  # what is absent or at a wrong version: "voicert<3,>=2", "speech-lib"
    detail: str  # one sentence for the user


def requirement_status(requirement: str) -> RequirementStatus: ...
```

A requirement names a distribution and, usually, extras. It is **installed** when the distribution is, and when everything its extras add is too. What an extra adds is read from the distribution's metadata: its `Requires-Dist` entries whose marker names that extra.

For each such entry:

- an entry whose marker does not hold on this machine (another platform, another Python) is not needed here and is skipped;
- the named distribution must be installed at a version its specifier accepts (pre-releases included); an entry given by URL is checked for presence only;
- the entry's own extras are checked the same way, recursively (`sdk[websockets]` needs what `websockets` adds to `sdk`). A distribution already being checked is not entered again, so a cycle ends.

The states:

| State | When | Example detail |
|---|---|---|
| `installed` | Everything needed here is present | "Installed." |
| `missing` | The distribution, or something an extra adds, is absent or at a wrong version; `missing` lists each | "Missing: voicert<3,>=2." |
| `unavailable` | The extra adds requirements, and none of them applies on this machine | "Not available on this platform." |
| `unknown` | The requirement cannot be read, or the distribution declares no such extra | "speech-lib declares no extra 'fast'." |

`unavailable` is how a module that exists on one platform only shows up, with no declaration by the library: its extra's requirements all carry a marker that is false here. An extra that adds nothing at all is `installed`.

Nothing is imported: the check reads `importlib.metadata` only, so a heavy provider library costs nothing to look up, and a lookup right after an install sees the new packages.

## Which host extra carries it

The environment is installed from the host project (its `pyproject.toml` and lock), so only the host's own extras can be installed. A library's requirement is carried by a host extra that lists it:

```python
def host_extras(requirement: str, *, host: str) -> tuple[str, ...]: ...
```

- When the requirement's distribution **is** the host (a library running its own demo), the answer is the requirement's extras themselves: `speech-lib[local-voice]` → `("local-voice",)`.
- Otherwise it is every host extra whose own `Requires-Dist` entries name that distribution with that extra: an app declaring `speech-local-voice = ["speech-lib[local-voice]"]` answers `("speech-local-voice",)`. An extra that only reaches it by referring to other extras of the host (a bundle such as `all`) is not returned: installing a bundle to get one module is never what a user wants. Several direct carriers are returned in the host's declaration order; the first is installed.
- A requirement naming several extras needs a carrier for each; with one of them uncarried the answer is `()`.
- `()` means the host cannot install this requirement. The Setup tab then says which requirement no extra of the host carries, which is a gap in the host's `pyproject.toml`, not something a user can fix. A host keeps its extras complete with a test: every requirement its sections can return has a carrier.

No naming convention links a host extra to a library's: the link is the declaration itself.

## Installing

```python
@dataclass(frozen=True)
class Installer:
    project_dir: Path  # where the host's pyproject.toml and uv.lock are
    uv: str  # the uv executable

    def command(self, extras: Sequence[str]) -> list[str]: ...
    def install(
        self, extras: Sequence[str], on_output: Callable[[str], None] | None = None
    ) -> int: ...


def find_installer(host: str) -> Installer | str: ...
```

`find_installer` returns an `Installer`, or the sentence saying why the app cannot install for the user:

- the host is not installed from a local project directory (it was installed from an index or a URL, so there is no lock to install from);
- that directory has no `uv.lock`;
- `uv` is not on the `PATH`.

The project directory is read from the host distribution's own install record (`direct_url.json`, written for a project installed from a directory), so the app needs no setting for it.

The command is:

```
uv sync --inexact --frozen --no-default-groups --extra <a> --extra <b>
```

run in the project directory.

- **`--inexact`** adds what is missing and removes nothing, so extras installed earlier stay, and so does a developer's tooling.
- **`--frozen`** installs the versions the lock records and never rewrites the lock. An app must not edit a project's lock file; a lock that does not know an extra is an error uv reports.
- **`--no-default-groups`** leaves development groups alone: with `--inexact` an installed group stays, and one that was never installed is not pulled in.
- When the running interpreter is not the project's own `.venv`, `--active` is added and `VIRTUAL_ENV` points at the running environment, so the packages land where the app runs.

`install` runs it, passes each line of uv's output to `on_output` as it comes, and returns uv's exit code. It then invalidates the import caches, so a package installed a moment ago can be imported without restarting the app. One install runs at a time: a second call waits for the first.

A package that was already imported is not reloaded. An extra adds packages, and the lock keeps the versions of the others, so this does not arise in a normal install; an environment that had drifted from the lock is the exception, and restarting the app is then the answer.

## Testing

`tests/test_extras.py`, over small fake distributions written as `.dist-info` folders on `sys.path`, so the real metadata reader is exercised:

- `requirement_status`: installed; the distribution itself missing; one package of an extra missing; a wrong version; an entry skipped by its marker; an extra whose entries are all off this platform (`unavailable`); an extra that adds nothing; a nested extra missing something; a cycle of extras; an unknown extra; an unreadable requirement.
- `host_extras`: the host's own extra; a carrier in another host; two carriers in declaration order; a bundle not returned; a requirement with two extras, carried and half carried; no carrier.
- `find_installer`: each of the three refusals, and the project directory found from the install record.
- `Installer`: the command for one and for several extras, with and without `--active`; `install` against a stand-in executable that prints its arguments, checking the working directory, the lines passed to `on_output` and the exit code, for a success and a failure.

## Open questions

1. **Installing without uv.** An environment not managed by uv gets a sentence, not a button. A `pip install 'host[extra]'` fallback would install unpinned versions, which is why it is not offered.
2. **Removing an extra** nothing needs any more is not offered: `--inexact` only adds. A plain `uv sync` by hand resets the environment.
3. **A package that must be upgraded while imported** needs a restart of the app; detecting it and saying so is deferred.
4. **Windows** keeps loaded binaries locked, which can make an upgrade fail mid-install. Installs that only add packages are not affected.
