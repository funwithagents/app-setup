"""The page of an app: Setup, Secrets and Session tabs (specs/ui.md). Needs the ``ui`` extra.

``launch(app)`` is an app's whole ``main()``: it reads ``--folder``, prepares the folder,
loads the secrets, starts a session when autostart is on, and serves the page.
``build_page(model)`` builds the page alone, for an app that serves it itself.
"""

from __future__ import annotations

from module_setup.ui.page import build_page, launch

__all__ = ["build_page", "launch"]
