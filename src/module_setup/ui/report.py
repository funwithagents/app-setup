"""What the page writes about a config, as Markdown (specs/ui.md, "Reports").

Pure functions from the model's answers to text, so the wording is tested without a browser.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from module_setup.app import Problem, SetupItem
from module_setup.secrets import SecretVariable
from module_setup.session import SessionRunner, SessionState

__all__ = [
    "config_report",
    "secrets_report",
    "session_report",
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
    if not items:
        return "✅ **This machine needs nothing more for this config.**"
    missing = [item for item in items if item.status == "missing"]
    header = (
        "✅ **This machine is ready for this config.**"
        if not missing
        else f"❌ **{len(missing)} thing(s) missing on this machine.**"
    )
    lines = [header, "", "| Section | What | Status | Detail |", "|---|---|---|---|"]
    for item in items:
        detail = item.detail
        if item.installable:
            detail += f" Install: `{', '.join(item.host_extras[:1])}`."
        elif item.preparable and item.status != "ready":
            detail += " Prepare downloads it."
        lines.append(
            f"| {_cell(item.section)} | {_cell(item.title)} "
            f"| {_STATUS.get(item.status, item.status)} | {_cell(detail)} |"
        )
    return "\n".join(lines)


def secrets_report(variables: Sequence[tuple[SecretVariable, Sequence[str]]]) -> str:
    if not variables:
        return "The current config names no environment variable for a key."
    lines = ["| Variable | Value from | Named by |", "|---|---|---|"]
    for variable, pointers in variables:
        lines.append(
            f"| `{variable.name}` | {_SOURCE[variable.source]} "
            f"| {', '.join(f'`{p}`' for p in pointers)} |"
        )
    return "\n".join(lines)


def session_report(runner: SessionRunner, now: float | None = None) -> str:
    state = runner.state
    if state is SessionState.RUNNING:
        started = runner.started_at or time.time()
        elapsed = int((now if now is not None else time.time()) - started)
        sections = ", ".join(runner.context.config) if runner.context else ""
        return f"🟢 **Running** for {elapsed} s — sections: {sections}"
    if state is SessionState.STARTING:
        return "🟡 **Starting…**"
    if state is SessionState.STOPPING:
        return "🟡 **Stopping…**"
    if state is SessionState.FAILED:
        return f"🔴 **Failed to start:** {runner.error}"
    if runner.error:
        return f"⚪ **Stopped** (the last stop reported: {runner.error})"
    return "⚪ **Stopped**"
