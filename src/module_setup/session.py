"""One run of an app's runtime, from Start to Stop (specs/session.md).

The app gives a ``start`` function: from the saved config, it builds whatever its runtime is
(an engine, an agent, a robot connection) and returns an object with ``stop()``. The runner
calls it on a thread of its own, keeps the state the page shows, and makes sure a session is
stopped before another starts. The config cannot change while a session runs; it can between
two, without restarting the app.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "Session",
    "SessionContext",
    "SessionRunner",
    "SessionState",
    "StartFunction",
]

log = logging.getLogger(__name__)


class SessionState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class Session(Protocol):
    """What an app's ``start`` returns: a running runtime that can be stopped."""

    def stop(self) -> None: ...


@dataclass(frozen=True)
class SessionContext:
    """What ``start`` is given."""

    config: Mapping[str, Any]  # one document per section the session uses
    folder: Path  # the app's folder, against which relative paths resolve


StartFunction = Callable[[SessionContext], Session]


@dataclass
class _Snapshot:
    state: SessionState = SessionState.STOPPED
    error: str | None = None
    context: SessionContext | None = None
    session: Session | None = None
    started_at: float | None = None
    version: int = 0
    stop_requested: bool = field(default=False)


class SessionRunner:
    """Runs one session at a time. Thread-safe; ``start`` and ``stop`` return at once and the
    work happens on a thread. ``version`` changes on every transition, for a page that polls."""

    def __init__(self, start: StartFunction) -> None:
        self._start = start
        self._lock = threading.Condition()
        self._snapshot = _Snapshot()

    # --- What the page reads.

    @property
    def state(self) -> SessionState:
        return self._snapshot.state

    @property
    def error(self) -> str | None:
        """Why the last start failed, or the last stop raised; None otherwise."""
        return self._snapshot.error

    @property
    def session(self) -> Session | None:
        """The running session's object (None unless running): what the Session tab uses."""
        snapshot = self._snapshot
        return snapshot.session if snapshot.state is SessionState.RUNNING else None

    @property
    def context(self) -> SessionContext | None:
        """The config the current or last session was started with."""
        return self._snapshot.context

    @property
    def started_at(self) -> float | None:
        return self._snapshot.started_at

    @property
    def version(self) -> int:
        return self._snapshot.version

    @property
    def idle(self) -> bool:
        """Whether nothing runs: the config may change and a session may start."""
        return self._snapshot.state in (SessionState.STOPPED, SessionState.FAILED)

    # --- Transitions.

    def _set(self, **changes: Any) -> None:
        for name, value in changes.items():
            setattr(self._snapshot, name, value)
        self._snapshot.version += 1
        self._lock.notify_all()

    def start(self, context: SessionContext) -> bool:
        """Start a session with *context*; False when one is already starting, running or
        stopping."""
        with self._lock:
            if not self.idle:
                return False
            self._set(
                state=SessionState.STARTING,
                error=None,
                context=context,
                session=None,
                started_at=None,
                stop_requested=False,
            )
        threading.Thread(
            target=self._run_start,
            args=(context,),
            name="module-setup-start",
            daemon=True,
        ).start()
        return True

    def _run_start(self, context: SessionContext) -> None:
        try:
            session = self._start(context)
        except Exception as exc:
            log.exception("the session failed to start")
            with self._lock:
                self._set(
                    state=SessionState.FAILED, error=str(exc) or type(exc).__name__
                )
            return
        with self._lock:
            self._set(
                state=SessionState.RUNNING, session=session, started_at=time.time()
            )
            stop_now = self._snapshot.stop_requested
        if stop_now:
            self.stop()

    def stop(self) -> bool:
        """Stop the running session; False when none runs. A stop asked while the session is
        still starting happens as soon as it has started."""
        with self._lock:
            if self._snapshot.state is SessionState.STARTING:
                self._set(stop_requested=True)
                return True
            if self._snapshot.state is not SessionState.RUNNING:
                return False
            session = self._snapshot.session
            self._set(state=SessionState.STOPPING)
        threading.Thread(
            target=self._run_stop,
            args=(session,),
            name="module-setup-stop",
            daemon=True,
        ).start()
        return True

    def _run_stop(self, session: Session | None) -> None:
        error: str | None = None
        try:
            if session is not None:
                session.stop()
        except Exception as exc:
            log.exception("the session failed to stop cleanly")
            error = f"stop: {exc}" if str(exc) else f"stop: {type(exc).__name__}"
        with self._lock:
            self._set(state=SessionState.STOPPED, session=None, error=error)

    def wait(self, timeout: float | None = None) -> SessionState:
        """Wait until no start or stop is in progress; the state then."""
        busy = (SessionState.STARTING, SessionState.STOPPING)
        with self._lock:
            self._lock.wait_for(lambda: self._snapshot.state not in busy, timeout)
            return self._snapshot.state
