"""The command line every app shares, and how it opens its config's source
(specs/config-file.md, "The command line" and "A config app").

An app runs from its folder (``--folder DIR``, by default ``default_folder(app.name)``) or from
a file run as it is (``--config FILE``); either takes its keys from the ``.env`` next to the
config, unless ``--env PATH`` names another. A config app edits one file (``FILE``) and has no
session.

```python
parser = argparse.ArgumentParser()
add_config_arguments(parser, APP)
add_start_arguments(parser)
options = parser.parse_args()
try:
    source = open_source(options, APP)
except ConfigFileError as exc:
    parser.error(str(exc))
model = AppModel(APP, source, locked=session.running)
```
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app_setup.app import App, AppModel
from app_setup.config_file import ConfigFile
from app_setup.folder import ConfigFolder, default_folder

__all__ = [
    "add_config_app_arguments",
    "add_config_arguments",
    "open_config_app",
    "open_source",
]


def _add_env_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env",
        type=Path,
        default=None,
        metavar="PATH",
        help="the .env file the keys are read from and saved to "
        "(default: the .env next to the config)",
    )


def add_config_arguments(parser: argparse.ArgumentParser, app: App) -> None:
    """``--folder DIR`` (default: ``default_folder(app.name)``) or ``--config FILE``, one
    or the other; ``--env PATH``."""
    where = parser.add_mutually_exclusive_group()
    where.add_argument(
        "--folder",
        type=Path,
        default=default_folder(app.name),
        metavar="DIR",
        help="the app's folder: its config, edited and saved, and its .env "
        "(default: %(default)s)",
    )
    where.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="FILE",
        help="run this config file as it is: it is never written, and the session "
        "starts at launch unless --no-start",
    )
    _add_env_argument(parser)


def open_source(options: argparse.Namespace, app: App) -> ConfigFolder | ConfigFile:
    """The source the options name: ``--config FILE``, a `ConfigFile` not writable; else
    the `ConfigFolder`; ``--env`` on either. Raises `ConfigFileError` for a missing or
    unreadable file."""
    if options.config is not None:
        return ConfigFile(options.config, env_path=options.env, writable=False)
    return ConfigFolder(options.folder, app.default_config, env_path=options.env)


def add_config_app_arguments(parser: argparse.ArgumentParser) -> None:
    """A config app's command line: ``FILE`` (the config to edit), ``--env PATH``,
    ``--host``, ``--port``."""
    parser.add_argument(
        "file",
        type=Path,
        metavar="FILE",
        help="the config file to edit (it must exist)",
    )
    _add_env_argument(parser)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="the address the page listens on (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="the port the page listens on (default: gradio's, the first free from 7860)",
    )


def open_config_app(options: argparse.Namespace, app: App) -> AppModel:
    """The model of a config app: the file given, writable, its ``.env`` loaded. Raises
    `ConfigFileError` for a missing or unreadable file."""
    return AppModel(app, ConfigFile(options.file, env_path=options.env, writable=True))
