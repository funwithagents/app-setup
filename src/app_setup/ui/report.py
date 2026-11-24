"""What the page writes about a config, as Markdown (specs/ui.md, "Reports").

Pure functions from the model's answers to text, so the wording is tested without a browser.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app_setup.app import Problem, SetupItem
from app_setup.secrets import SecretVariable

__all__ = [
    "Progress",
    "config_report",
    "item_line",
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


def setup_summary(items: Sequence[SetupItem]) -> str:
    """One line over a section's item rows: whether this machine can run its config."""
    if not items:
        return "✅ **This machine needs nothing more for this config.**"
    blocking = [item for item in items if item.blocking]
    deferred = [item for item in items if item.deferred]
    if blocking:
        line = f"❌ **{len(blocking)} thing(s) missing on this machine.**"
    elif deferred:
        line = "✅ **This machine can run this config.**"
    else:
        line = "✅ **This machine is ready for this config.**"
    if deferred:
        line += (
            f" {len(deferred)} thing(s) not prepared yet: the first start will prepare "
            "them itself, and be slower."
        )
    return line


@dataclass(frozen=True)
class Progress:
    """What an item's row shows of its preparation: running, or how it ended."""

    running: bool
    fraction: float | None  # the share done, None when the library cannot measure
    message: str  # the library's latest words, or the failure's message
    elapsed_s: float
    ok: bool | None = None  # None while running


_BAR = 12


def _bar(fraction: float) -> str:
    done = round(max(0.0, min(1.0, fraction)) * _BAR)
    return "▓" * done + "░" * (_BAR - done)


def item_line(item: SetupItem, progress: Progress | None = None) -> str:
    """An item's row: its title, its state in plain words, its detail and what to do;
    while it is prepared, its progress; once prepared, how it ended."""
    title = f"**{item.title}**"
    if progress is not None and progress.running:
        if progress.fraction is not None:
            return (
                f"{title} — ⏳ `{_bar(progress.fraction)}` {progress.fraction:.0%} · "
                f"{progress.message}"
            )
        doing = progress.message or "Preparing"
        return f"{title} — ⏳ {doing} ({progress.elapsed_s:.0f} s)"
    if progress is not None and progress.ok:
        return f"{title} — ✅ Ready."
    if progress is not None and progress.ok is False:
        return f"{title} — ❌ Failed: {progress.message} **Prepare** tries again."
    if item.status == "ready":
        return f"{title} — ✅ Ready. {item.detail}".rstrip()
    if item.status == "unknown":
        return f"{title} — ❔ Unknown. {item.detail}".rstrip()
    if not item.required:
        return (
            f"{title} — ⏳ Not prepared yet. {item.detail} The first start will prepare "
            "it itself and be slower; **Prepare** does it now."
        )
    todo = ""
    if item.installable:
        todo = f" **Install missing extras** installs it (`{item.host_extras[0]}`)."
    elif item.preparable:
        todo = " **Prepare** gets it."
    return f"{title} — ❌ Missing. {item.detail}{todo}"


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
