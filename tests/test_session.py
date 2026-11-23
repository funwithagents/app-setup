import threading
from pathlib import Path

from module_setup.session import SessionContext, SessionRunner, SessionState

CONTEXT = SessionContext(config={"tts": {"module": {"type": "tone"}}}, folder=Path("."))


class Recorder:
    def __init__(self) -> None:
        self.started: list[SessionContext] = []
        self.stopped = 0
        self.release = threading.Event()
        self.release.set()
        self.fail_start: Exception | None = None
        self.fail_stop: Exception | None = None

    def start(self, context: SessionContext) -> "Recorder":
        self.release.wait(5)
        if self.fail_start is not None:
            raise self.fail_start
        self.started.append(context)
        return self

    def stop(self) -> None:
        self.stopped += 1
        if self.fail_stop is not None:
            raise self.fail_stop


def test_a_session_starts_runs_and_stops() -> None:
    recorder = Recorder()
    runner = SessionRunner(recorder.start)

    assert runner.start(CONTEXT)
    assert runner.wait(5) is SessionState.RUNNING
    assert runner.session is recorder
    assert runner.context == CONTEXT and runner.started_at is not None
    assert not runner.idle

    assert runner.stop()
    assert runner.wait(5) is SessionState.STOPPED
    assert recorder.stopped == 1
    assert runner.session is None and runner.idle and runner.error is None


def test_a_second_start_while_one_runs_is_refused() -> None:
    runner = SessionRunner(Recorder().start)
    runner.start(CONTEXT)
    runner.wait(5)

    assert not runner.start(CONTEXT)
    assert not SessionRunner(Recorder().start).stop()


def test_a_start_that_raises_is_failed_with_its_message_and_can_be_retried() -> None:
    recorder = Recorder()
    recorder.fail_start = ValueError("no voice named 'Zed'")
    runner = SessionRunner(recorder.start)

    runner.start(CONTEXT)

    assert runner.wait(5) is SessionState.FAILED
    assert runner.error == "no voice named 'Zed'"
    assert runner.idle

    recorder.fail_start = None
    assert runner.start(CONTEXT)
    assert runner.wait(5) is SessionState.RUNNING
    assert runner.error is None


def test_a_stop_that_raises_still_stops_and_says_so() -> None:
    recorder = Recorder()
    recorder.fail_stop = RuntimeError("device busy")
    runner = SessionRunner(recorder.start)
    runner.start(CONTEXT)
    runner.wait(5)

    runner.stop()

    assert runner.wait(5) is SessionState.STOPPED
    assert runner.error == "stop: device busy"


def test_a_stop_asked_while_starting_happens_once_started() -> None:
    recorder = Recorder()
    recorder.release.clear()
    runner = SessionRunner(recorder.start)
    runner.start(CONTEXT)
    assert runner.state is SessionState.STARTING

    assert runner.stop()
    recorder.release.set()

    for _ in range(3):
        if runner.wait(5) is SessionState.STOPPED:
            break
    assert runner.state is SessionState.STOPPED
    assert recorder.stopped == 1


def test_every_transition_changes_the_version() -> None:
    runner = SessionRunner(Recorder().start)
    before = runner.version

    runner.start(CONTEXT)
    runner.wait(5)
    running = runner.version
    runner.stop()
    runner.wait(5)

    assert before < running < runner.version
