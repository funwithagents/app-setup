"""Helpers for the opt-in live tier.

A live test needs real credentials. Rather than fail when they're absent, a test
calls `require_env(...)` up front so it *skips* cleanly — you only exercise the
services you hold keys for, and a contributor (or CI) with none is never broken.
"""

import os
from typing import NoReturn

import pytest


def require_env(name: str) -> str:
    """Return env var `name`, or skip the calling test if it's unset/empty."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set; skipping live test")
    return value


# Set to "1" where the browser must be there (CI): a missing Playwright or Chromium then
# fails instead of skipping, so the browser tests cannot pass by not running.
REQUIRE_BROWSER = "APP_SETUP_E2E_REQUIRE_BROWSER"


def no_browser(reason: str) -> NoReturn:
    """Skip the calling test for *reason*, or fail it where the browser is required."""
    if os.environ.get(REQUIRE_BROWSER) == "1":
        pytest.fail(f"{reason} ({REQUIRE_BROWSER}=1)", pytrace=False)
    pytest.skip(reason, allow_module_level=True)
