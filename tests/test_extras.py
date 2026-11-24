import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from module_setup.extras import (
    Installer,
    find_installer,
    host_extras,
    requirement_status,
)

# Fake distributions are real `.dist-info` folders on sys.path, so the checks run through
# the real metadata reader.


def _install(
    site: Path,
    name: str,
    version: str = "1.0",
    *,
    extras: tuple[str, ...] = (),
    requires: tuple[str, ...] = (),
    direct_url: dict | None = None,
) -> None:
    folder = site / f"{name.replace('-', '_')}-{version}.dist-info"
    folder.mkdir()
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    lines += [f"Provides-Extra: {extra}" for extra in extras]
    lines += [f"Requires-Dist: {requirement}" for requirement in requires]
    (folder / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if direct_url is not None:
        (folder / "direct_url.json").write_text(json.dumps(direct_url), "utf-8")


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "site"
    folder.mkdir()
    monkeypatch.syspath_prepend(str(folder))
    return folder


_OTHER_OS = "sys_platform == 'no-such-os'"


@pytest.fixture
def speech(site: Path) -> Path:
    """`speech-lib` with a local voice (two packages, one off this platform), a hosted
    one (an SDK with its own extra) and a voice that exists on another OS only."""
    _install(
        site,
        "speech-lib",
        extras=("local-voice", "cloud-voice", "other-os-voice", "plain", "loop"),
        requires=(
            "numberlib>=1",
            "voicert>=2,<3; extra == 'local-voice'",
            f"oddlib; {_OTHER_OS} and extra == 'local-voice'",
            "cloudsdk[sockets]>=4; extra == 'cloud-voice'",
            f"metalrt; {_OTHER_OS} and extra == 'other-os-voice'",
            "speech-lib[loop]; extra == 'loop'",
        ),
    )
    _install(site, "numberlib", "1.4")
    return site


def test_an_extra_whose_packages_are_all_present_is_installed(speech: Path) -> None:
    _install(speech, "voicert", "2.5")

    status = requirement_status("speech-lib[local-voice]")

    assert (status.state, status.missing) == ("installed", ())


def test_a_distribution_that_is_absent_is_what_is_missing(site: Path) -> None:
    status = requirement_status("speech-lib[local-voice]")

    assert (status.state, status.missing) == ("missing", ("speech-lib",))


def test_a_package_the_extra_adds_and_that_is_absent_is_named(speech: Path) -> None:
    status = requirement_status("speech-lib[local-voice]")

    assert status.state == "missing"
    assert status.missing == ("voicert<3,>=2",)
    assert status.detail == "Missing: voicert<3,>=2."


def test_a_package_at_a_version_the_extra_refuses_is_missing(speech: Path) -> None:
    _install(speech, "voicert", "3.1")

    status = requirement_status("speech-lib[local-voice]")

    assert status.state == "missing"
    assert status.missing == ("voicert<3,>=2 (found 3.1)",)


def test_what_an_extra_of_a_dependency_adds_is_checked_too(speech: Path) -> None:
    _install(
        speech,
        "cloudsdk",
        "4.2",
        extras=("sockets",),
        requires=("socketlib>=10; extra == 'sockets'",),
    )

    assert requirement_status("speech-lib[cloud-voice]").missing == ("socketlib>=10",)

    _install(speech, "socketlib", "12.0")

    assert requirement_status("speech-lib[cloud-voice]").state == "installed"


def test_an_extra_that_only_exists_on_another_platform_is_unavailable(
    speech: Path,
) -> None:
    status = requirement_status("speech-lib[other-os-voice]")

    assert (status.state, status.missing) == ("unavailable", ())
    assert status.detail == "Not available on this platform."


def test_an_extra_that_adds_nothing_or_refers_to_itself_is_installed(
    speech: Path,
) -> None:
    assert requirement_status("speech-lib[plain]").state == "installed"
    assert requirement_status("speech-lib[loop]").state == "installed"
    assert requirement_status("speech-lib").state == "installed"


def test_an_extra_the_distribution_does_not_declare_is_unknown(speech: Path) -> None:
    status = requirement_status("speech-lib[fast]")

    assert status.state == "unknown"
    assert status.detail == "speech-lib declares no extra 'fast'."


def test_text_that_is_not_a_requirement_is_unknown() -> None:
    assert requirement_status("speech-lib[oops").state == "unknown"


def test_several_extras_are_all_checked(speech: Path) -> None:
    _install(speech, "voicert", "2.0")

    status = requirement_status("speech-lib[local-voice,cloud-voice]")

    assert (status.state, status.missing) == ("missing", ("cloudsdk[sockets]>=4",))


# --- host_extras ----------------------------------------------------------------


@pytest.fixture
def app(speech: Path) -> Path:
    """An app that carries the speech library's voices under extras of its own."""
    _install(
        speech,
        "talk-app",
        extras=("speech", "speech-local-voice", "voices", "robot", "all"),
        requires=(
            "speech-lib; extra == 'speech'",
            "speech-lib[local-voice]; extra == 'speech-local-voice'",
            "speech-lib[local-voice,cloud-voice]; extra == 'voices'",
            "robot-lib[sim]; extra == 'robot'",
            "talk-app[speech-local-voice,robot]; extra == 'all'",
        ),
    )
    return speech


def test_a_library_running_its_own_app_installs_its_own_extra(speech: Path) -> None:
    assert host_extras("speech-lib[local-voice]", host="speech-lib") == ("local-voice",)
    assert host_extras("Speech_Lib[cloud-voice,local-voice]", host="speech-lib") == (
        "cloud-voice",
        "local-voice",
    )


def test_an_app_installs_the_first_of_its_extras_that_lists_the_requirement(
    app: Path,
) -> None:
    assert host_extras("speech-lib[local-voice]", host="talk-app") == (
        "speech-local-voice",
    )
    assert host_extras("speech-lib[cloud-voice]", host="talk-app") == ("voices",)
    assert host_extras("robot-lib[sim]", host="talk-app") == ("robot",)


def test_a_requirement_with_two_extras_needs_a_carrier_for_each(app: Path) -> None:
    assert host_extras("speech-lib[local-voice,cloud-voice]", host="talk-app") == (
        "voices",
        "speech-local-voice",
    )
    assert host_extras("speech-lib[local-voice,other-os-voice]", host="talk-app") == ()


def test_a_requirement_no_extra_of_the_host_lists_has_no_carrier(app: Path) -> None:
    assert host_extras("robot-lib[placo]", host="talk-app") == ()
    assert host_extras("speech-lib[local-voice]", host="not-installed") == ()
    assert host_extras("not a requirement[", host="talk-app") == ()


# --- find_installer and Installer -------------------------------------------------


def _fake_uv(folder: Path, exit_code: int = 0) -> Path:
    """An executable named `uv` that prints its working directory, environment and
    arguments: a script with a shebang, or on Windows (which runs no shebang) a `uv.cmd`
    running the same Python, as `shutil.which("uv")` would find a real `uv.exe`."""
    body = textwrap.dedent(
        f"""\
        import os, sys
        print("cwd=" + os.getcwd())
        print("venv=" + os.environ.get("VIRTUAL_ENV", ""))
        print("args=" + " ".join(sys.argv[1:]))
        sys.exit({exit_code})
        """
    )
    if sys.platform == "win32":
        (folder / "uv-script.py").write_text(body, encoding="utf-8")
        script = folder / "uv.cmd"
        script.write_text(
            f'@"{sys.executable}" "%~dp0uv-script.py" %*\r\n@exit /b %errorlevel%\r\n',
            encoding="utf-8",
        )
        return script
    script = folder / "uv"
    script.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _project(site: Path, tmp_path: Path, *, lock: bool = True) -> Path:
    project = tmp_path / "talk-project"
    project.mkdir()
    if lock:
        (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _install(
        site,
        "talk-app",
        direct_url={"url": project.as_uri(), "dir_info": {"editable": True}},
    )
    return project


def test_the_installer_is_found_from_the_host_s_install_record(
    site: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(site, tmp_path)
    uv = _fake_uv(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))

    installer = find_installer("talk-app")

    assert isinstance(installer, Installer)
    assert installer.project_dir == project
    # Windows paths compare without case (`which` may return `UV.CMD`).
    assert os.path.normcase(installer.uv) == os.path.normcase(str(uv))


def test_a_host_installed_from_an_index_cannot_install(site: Path) -> None:
    _install(site, "talk-app")
    _install(
        site,
        "url-app",
        direct_url={"url": "https://example.org/x.whl", "archive_info": {}},
    )

    for host in ("talk-app", "url-app", "not-installed"):
        refusal = find_installer(host)
        assert isinstance(refusal, str) and "local project directory" in refusal


def test_a_project_without_a_lock_cannot_install(site: Path, tmp_path: Path) -> None:
    project = _project(site, tmp_path, lock=False)

    assert find_installer("talk-app") == f"{project} has no uv.lock to install from."


def test_without_uv_the_app_cannot_install(
    site: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(site, tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    refusal = find_installer("talk-app")

    assert isinstance(refusal, str) and refusal.startswith("uv is not on the PATH")


def test_the_command_adds_extras_from_the_lock_and_removes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = Installer(project_dir=tmp_path, uv="uv")

    assert installer.command(["speech-local-voice", "robot"]) == [
        "uv",
        "sync",
        "--inexact",
        "--frozen",
        "--no-default-groups",
        "--active",
        "--extra",
        "speech-local-voice",
        "--extra",
        "robot",
    ]

    monkeypatch.setattr(sys, "prefix", str(tmp_path / ".venv"))

    assert "--active" not in installer.command(["robot"])


def test_install_runs_uv_in_the_project_and_reports_its_output(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    installer = Installer(project_dir=project, uv=str(_fake_uv(tmp_path)))
    lines: list[str] = []

    code = installer.install(["robot"], lines.append)

    assert code == 0
    assert lines == [
        f"cwd={project.resolve()}",
        f"venv={sys.prefix}",
        "args=sync --inexact --frozen --no-default-groups --active --extra robot",
    ]


def test_install_returns_uv_s_failure(tmp_path: Path) -> None:
    installer = Installer(project_dir=tmp_path, uv=str(_fake_uv(tmp_path, exit_code=2)))

    assert installer.install(["robot"]) == 2
