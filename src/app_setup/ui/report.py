"""What the page writes about a config, as Markdown (specs/ui.md, "Reports").

Pure functions from the model's answers to text, so the wording is tested without a browser.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app_setup.app import Problem, SetupItem
from app_setup.secrets import SecretVariable

__all__ = [
    "HEADER",
    "Progress",
    "config_report",
    "item_status",
    "secrets_report",
    "setup_summary",
]

_SOURCE = {
    "shell": "✅ the shell",
    "file": "✅ the folder's .env",
    "missing": "❌ not set",
}


def config_report(problems: Sequence[Problem]) -> str:
    if not problems:
        return "✅ **The config is valid.**"
    lines = ["❌ **The config has problems:**", ""]
    lines += [f"- `{p.path or '/'}`: {p.message}" for p in problems]
    return "\n".join(lines)


def _count(n: int, what: str) -> str:
    return f"{n} {what}{'' if n == 1 else 's'}"


def setup_summary(items: Sequence[SetupItem]) -> str:
    """One line over a section's table, in the table's words: whether this machine can run
    its config."""
    blocking = [item for item in items if item.blocking]
    deferred = [item for item in items if item.deferred]
    optional = (
        f"{_count(len(deferred), 'optional item')} missing: the first start will get "
        "them, slower"
    )
    if blocking:
        line = f"❌ **{_count(len(blocking), 'required item')} missing**"
        return line + (f" — {optional}" if deferred else "")
    if deferred:
        return f"✅ **Ready to run** — {optional}"
    return "✅ **Ready**"


@dataclass(frozen=True)
class Progress:
    """What an item's line shows of an action on it (a preparation, an install): running,
    waiting its turn, or how it ended."""

    running: bool
    fraction: float | None  # the share done, None when it cannot be measured
    message: str  # the latest words (the library's, uv's), or the failure's message
    elapsed_s: float
    ok: bool | None = None  # None while running
    install: bool = False  # an install, not a preparation
    waiting: bool = False  # an install queued behind another


_BAR = 12


def _bar(fraction: float) -> str:
    done = round(max(0.0, min(1.0, fraction)) * _BAR)
    return "▓" * done + "░" * (_BAR - done)


HEADER = ("**Item**", "**Status**", "**Explanation**", "**Action**")
OPTIONAL = "Without it, the first start gets it itself and is slower."


def _todo(item: SetupItem) -> str:
    """What to do about a missing required item, after its detail."""
    if item.installable:
        return f"**Install** adds it (the `{item.host_extras[0]}` extra)."
    if item.variable is not None:
        return f"Type `{item.variable}` here, or in the Secrets panel."
    if item.preparable:
        return "**Prepare** gets it."
    return ""


def _join(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def item_status(item: SetupItem, progress: Progress | None = None) -> tuple[str, str]:
    """An item's line in the table: its status, short, and its explanation: the why, what
    to do, or the progress of what is being done."""
    if progress is not None:
        verb, doing = (
            ("Install", "Installing") if progress.install else ("Prepare", "Preparing")
        )
        if progress.waiting:
            return "⏳ **Waiting**", "Waiting for another install…"
        if progress.running and progress.fraction is not None:
            return (
                f"⏳ **{doing}… {progress.fraction:.0%}**",
                f"`{_bar(progress.fraction)}` {progress.message}".rstrip(),
            )
        if progress.running:
            return (
                f"⏳ **{doing}…**",
                _join(progress.message, f"({progress.elapsed_s:.0f} s)"),
            )
        if progress.ok:
            return "✅ **Ready**", "Installed." if progress.install else "Prepared."
        return "❌ **Failed**", _join(progress.message, f"**{verb}** tries again.")
    if item.status == "ready":
        return "✅ **Ready**", item.detail
    if item.status == "unknown":
        return "❔ **Can't tell**", item.detail
    if not item.required:
        return "🟡 **Missing – optional**", _join(item.detail, OPTIONAL)
    return "❌ **Missing – required**", _join(item.detail, _todo(item))


SHADOWED = "✅ the shell (the folder's .env also sets it, unused)"


def secrets_report(variables: Sequence[tuple[SecretVariable, Sequence[str]]]) -> str:
    """The variables the config names, each with where its value comes from and the
    fields naming it. Names only, never a value."""
    if not variables:
        return "The current config names no environment variable for a key."
    lines = ["| Variable | Value from | Named by |", "|---|---|---|"]
    for variable, pointers in variables:
        source = SHADOWED if variable.shadowed else _SOURCE[variable.source]
        lines.append(
            f"| `{variable.name}` | {source} "
            f"| {', '.join(f'`{p}`' for p in pointers)} |"
        )
    parts = ["\n".join(lines)]
    if any(variable.shadowed for variable, _ in variables):
        parts.append(SHADOW_NOTE)
    return "\n\n".join(parts)


SHADOW_NOTE = (
    "A variable set in the shell the app was started from wins over the .env. To use "
    "the .env's value, unset it in your shell profile (and start the app again), or "
    "remove it from the .env."
)


def env_file_rows(
    variables: Sequence[SecretVariable], named: Mapping[str, Sequence[str]]
) -> list[tuple[str, str]]:
    """One row per variable the folder's ``.env`` sets: its name, and what uses it
    (the fields of the current config naming it, or none) and whether the shell's
    value wins over it."""
    rows = []
    for variable in variables:
        pointers = named.get(variable.name)
        note = (
            "used by " + ", ".join(f"`{p}`" for p in pointers)
            if pointers
            else "not named by the current config"
        )
        if variable.shadowed:
            note += " — unused: the shell sets it too, and wins"
        rows.append((variable.name, note))
    return rows
