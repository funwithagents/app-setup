"""Whether an app starts its session at launch (specs/autostart.md).

An app that starts a session when it launches says so (``App(autostart=True)``, its default).
The user's choice is kept apart from the config, in the folder's ``launch.json``: the Setup
panel draws it as a checkbox, saved at once. ``--start`` / ``--no-start``
(``add_start_arguments``) override it for one launch; ``starts_at_launch`` reads the flag, else
``launch.json``, else the app's default. The config and ``AppModel.used_config`` hold only the
app's own sections. An app running a file (``--config``) starts its session at launch unless
``--no-start``: running a given file is asking for it to run (specs/config-file.md).
"""

from __future__ import annotations

import argparse

from app_setup.app import AppModel
from app_setup.config_file import ConfigFile

__all__ = ["add_start_arguments", "starts_at_launch"]


def add_start_arguments(parser: argparse.ArgumentParser) -> None:
    """``--start`` / ``--no-start``: start the session at this launch, or not, whatever the
    saved choice; neither leaves it to the saved choice (``options.start`` is None)."""
    parser.add_argument(
        "--start",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="start the session at launch (--no-start: do not); "
        "without either, the saved choice decides",
    )


def starts_at_launch(model: AppModel, flag: bool | None) -> bool:
    """Whether the app starts its session now: *flag* when given; from a file, yes; else
    the saved choice (``launch.json``); else the app's default. An app with no autostart
    starts only on ``--start``, unless it runs a file. Whether the config can run is the
    app's to check (``model.blockers``)."""
    if flag is not None:
        return flag
    if isinstance(model.source, ConfigFile):
        return True
    return bool(model.autostart())
