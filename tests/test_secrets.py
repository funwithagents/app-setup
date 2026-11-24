import stat
import sys
from pathlib import Path

import pytest

from module_setup.secrets import SecretStore, SecretVariable, format_env, parse_env


def test_a_dot_env_is_read_as_its_usual_dialect() -> None:
    lines = [
        "# a comment",
        "",
        "PLAIN=value # trailing comment",
        "export EXPORTED=yes",
        "SINGLE='a # not a comment'",
        'DOUBLE="line\\nbreak \\"quoted\\" back\\\\slash"',
        "SPACED = padded ",
        "PLAIN=later wins",
        "not a line",
    ]
    text = "\n".join(lines)

    assert parse_env(text) == {
        "PLAIN": "later wins",
        "EXPORTED": "yes",
        "SINGLE": "a # not a comment",
        "DOUBLE": 'line\nbreak "quoted" back\\slash',
        "SPACED": "padded",
    }


@pytest.mark.parametrize(
    "value", ["simple", 'with "quotes"', "back\\slash", "two\nlines", "#hash"]
)
def test_a_written_value_reads_back_the_same(value: str) -> None:
    assert parse_env(format_env("KEY", value)) == {"KEY": value}


def test_the_file_feeds_the_environment_but_never_overrides_the_shell(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('FROM_FILE="f"\nIN_SHELL="file value"\n')
    environ = {"IN_SHELL": "shell value", "EMPTY_IN_SHELL": ""}
    store = SecretStore(env_path, environ)

    store.load()

    assert environ["FROM_FILE"] == "f"
    assert environ["IN_SHELL"] == "shell value"
    assert store.variables(
        ["IN_SHELL", "FROM_FILE", "NOWHERE", "EMPTY_IN_SHELL", "FROM_FILE"]
    ) == [
        SecretVariable("IN_SHELL", "shell", in_file=True),
        SecretVariable("FROM_FILE", "file", in_file=True),
        SecretVariable("NOWHERE", "missing"),
        SecretVariable("EMPTY_IN_SHELL", "missing"),
    ]
    # The shell's value is used; the file's is there but unused.
    [in_shell, from_file] = store.variables(["IN_SHELL", "FROM_FILE"])
    assert (in_shell.shadowed, from_file.shadowed) == (True, False)
    assert store.file_names() == ["FROM_FILE", "IN_SHELL"]


def test_setting_a_variable_writes_the_file_privately_and_loads_it(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / "app" / ".env"
    environ: dict[str, str] = {}
    store = SecretStore(env_path, environ)

    assert store.set("API_KEY", "s3cret") == "file"
    assert store.set("OTHER", "x") == "file"
    assert store.set("API_KEY", "n3w") == "file"

    assert environ == {"API_KEY": "n3w", "OTHER": "x"}
    assert env_path.read_text() == 'API_KEY="n3w"\nOTHER="x"\n'
    if sys.platform != "win32":
        # Windows has no POSIX modes (chmod only sets read-only): the file is private
        # through the user profile's access rules there.
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_setting_a_shell_variable_writes_the_file_but_the_shell_still_wins(
    tmp_path: Path,
) -> None:
    environ = {"API_KEY": "from shell"}
    store = SecretStore(tmp_path / ".env", environ)

    assert store.set("API_KEY", "from file") == "shell"
    assert environ["API_KEY"] == "from shell"


def test_removing_a_variable_takes_it_out_of_the_file_and_the_environment(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# keys\nA=1\nB=2\n")
    environ: dict[str, str] = {}
    store = SecretStore(env_path, environ)
    store.load()

    assert store.remove("A") == "missing"

    assert environ == {"B": "2"}
    assert env_path.read_text() == "# keys\nB=2\n"


@pytest.mark.parametrize(
    ("name", "value"), [("1BAD", "x"), ("BAD-NAME", "x"), ("GOOD", "")]
)
def test_a_bad_name_or_an_empty_value_is_refused(
    tmp_path: Path, name: str, value: str
) -> None:
    with pytest.raises(ValueError):
        SecretStore(tmp_path / ".env", {}).set(name, value)
