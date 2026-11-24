"""What the page writes about a config, as Markdown (specs/ui.md, "Reports").

Pure functions from the model's answers to text, so the wording is tested without a browser.
"""

from __future__ import annotations

from collections.abc import Sequence

from module_setup.app import Problem, SetupItem
from module_setup.secrets import SecretVariable

__all__ = [
    "config_report",
    "secrets_report",
    "setup_report",
]

_STATUS = {"ready": "✅ ready", "missing": "❌ missing", "unknown": "❔ unknown"}
_SOURCE = {
    "shell": "✅ the shell",
    "file": "✅ the folder's .env",
    "missing": "❌ not set",
}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def config_report(problems: Sequence[Problem]) -> str:
    if not problems:
        return "✅ **The config is valid.**"
    lines = ["❌ **The config has problems:**", ""]
    lines += [f"- `{p.path or '/'}`: {p.message}" for p in problems]
    return "\n".join(lines)


def setup_report(items: Sequence[SetupItem]) -> str:
    """What one section needs on this machine, item by item (the Setup panel shows it
    under that section, so the table has no section column)."""
    if not items:
        return "✅ **This machine needs nothing more for this config.**"
    missing = [item for item in items if item.status == "missing"]
    header = (
        "✅ **This machine is ready for this config.**"
        if not missing
        else f"❌ **{len(missing)} thing(s) missing on this machine.**"
    )
    lines = [header, "", "| What | Status | Detail |", "|---|---|---|"]
    for item in items:
        detail = item.detail
        if item.installable:
            detail += (
                f" **Install missing extras** installs it (`{item.host_extras[0]}`)."
            )
        elif item.preparable and item.status != "ready":
            detail += " **Download missing files** gets it."
        lines.append(
            f"| {_cell(item.title)} "
            f"| {_STATUS.get(item.status, item.status)} | {_cell(detail)} |"
        )
    return "\n".join(lines)


SHADOWED = "✅ the shell (the folder's .env also sets it, unused)"


NOT_NAMED = "— not named by the current config"


def secrets_report(
    variables: Sequence[tuple[SecretVariable, Sequence[str]]],
    others: Sequence[SecretVariable] = (),
) -> str:
    """One table: the variables the config names, each with where its value comes from
    and the fields naming it; then the other variables the folder's ``.env`` sets
    (*others*), named by no field of the current config. Names only, never a value."""
    rows = [
        (variable, ", ".join(f"`{p}`" for p in pointers))
        for variable, pointers in variables
    ]
    rows += [(variable, NOT_NAMED) for variable in others]
    if not rows:
        return (
            "The current config names no environment variable for a key, and the "
            "folder's .env sets none."
        )
    lines = ["| Variable | Value from | Named by |", "|---|---|---|"]
    for variable, named_by in rows:
        source = SHADOWED if variable.shadowed else _SOURCE[variable.source]
        lines.append(f"| `{variable.name}` | {source} | {named_by} |")
    parts = ["\n".join(lines)]
    if not variables:
        parts.insert(0, "The current config names no environment variable for a key.")
    if any(variable.shadowed for variable, _ in rows):
        parts.append(
            "A variable set in the shell the app was started from wins over the "
            ".env. To use the .env's value, unset it in your shell profile (and "
            "start the app again), or remove it from the .env."
        )
    return "\n\n".join(parts)
