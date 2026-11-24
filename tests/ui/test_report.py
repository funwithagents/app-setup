from app_setup.app import Problem, SetupItem
from app_setup.secrets import SecretVariable
from app_setup.ui.report import (
    Progress,
    config_report,
    env_file_rows,
    item_line,
    secrets_report,
    setup_summary,
)


def test_config_problems_are_listed_with_their_pointer() -> None:
    assert config_report([]) == "✅ **The config is valid.**"
    text = config_report(
        [Problem("speech", "/speech/module/voice_id", "voice_id is required")]
    )
    assert "`/speech/module/voice_id`: voice_id is required" in text


EXTRA = SetupItem(
    "speech",
    "extra:speech-lib[x]",
    "X extra",
    "missing",
    "Not installed.",
    preparable=False,
    required=True,
    host_extras=("speech-x",),
)
VOICE = SetupItem(
    "speech", "weights:Ada", "Voice Ada", "missing", "Not downloaded.", True, False
)
LEXICON = SetupItem("speech", "lexicon", "Lexicon", "missing", "Not built.", True, True)
KEY = SetupItem("speech", "key:K", "K", "ready", "Set.", False, True)


def test_the_summary_tells_what_blocks_from_what_the_first_start_will_prepare() -> None:
    assert (
        setup_summary([]) == "✅ **This machine needs nothing more for this config.**"
    )
    assert setup_summary([KEY]) == "✅ **This machine is ready for this config.**"
    assert setup_summary([EXTRA, VOICE, KEY]).startswith(
        "❌ **1 thing(s) missing on this machine.** 1 thing(s) not prepared yet"
    )
    assert setup_summary([VOICE, KEY]) == (
        "✅ **This machine can run this config.** 1 thing(s) not prepared yet: the "
        "first start will prepare them itself, and be slower."
    )


def test_each_item_row_says_its_state_and_what_to_do() -> None:
    assert item_line(EXTRA) == (
        "**X extra** — ❌ Missing. Not installed. **Install missing extras** installs it "
        "(`speech-x`)."
    )
    assert (
        item_line(LEXICON)
        == "**Lexicon** — ❌ Missing. Not built. **Prepare** gets it."
    )
    assert item_line(VOICE) == (
        "**Voice Ada** — ⏳ Not prepared yet. Not downloaded. The first start will "
        "prepare it itself and be slower; **Prepare** does it now."
    )
    assert item_line(KEY) == "**K** — ✅ Ready. Set."


def test_a_row_being_prepared_shows_its_progress_then_how_it_ended() -> None:
    measured = Progress(True, 0.5, "Downloading 150 of 300 MB", 3.0)
    unmeasured = Progress(True, None, "Building the cache", 12.4)

    assert item_line(VOICE, measured) == (
        "**Voice Ada** — ⏳ `▓▓▓▓▓▓░░░░░░` 50% · Downloading 150 of 300 MB"
    )
    assert (
        item_line(VOICE, unmeasured) == "**Voice Ada** — ⏳ Building the cache (12 s)"
    )
    assert item_line(VOICE, Progress(False, 1.0, "Ready.", 9.0, ok=True)) == (
        "**Voice Ada** — ✅ Ready."
    )
    assert item_line(VOICE, Progress(False, 0.2, "Unreachable.", 2.0, ok=False)) == (
        "**Voice Ada** — ❌ Failed: Unreachable. **Prepare** tries again."
    )


def test_the_secrets_table_names_each_source() -> None:
    text = secrets_report(
        [
            (SecretVariable("A", "shell"), ["/s/module/api_key_env"]),
            (SecretVariable("B", "missing"), ["/s/x", "/t/y"]),
        ]
    )

    assert "| `A` | ✅ the shell | `/s/module/api_key_env` |" in text
    assert "| `B` | ❌ not set | `/s/x`, `/t/y` |" in text
    assert "names no environment variable" in secrets_report([])


def test_a_value_the_shell_shadows_is_said_with_how_to_use_the_file_s() -> None:
    text = secrets_report(
        [(SecretVariable("A", "shell", in_file=True), ["/s/module/api_key_env"])]
    )

    assert "| `A` | ✅ the shell (the folder's .env also sets it, unused) |" in text
    assert "unset it in your shell profile" in text
    assert "unset it" not in secrets_report([(SecretVariable("B", "file"), ["/s/x"])])


def test_each_variable_of_the_env_file_says_what_uses_it() -> None:
    rows = env_file_rows(
        [
            SecretVariable("KEY", "file", in_file=True),
            SecretVariable("OLD_KEY", "file", in_file=True),
            SecretVariable("BOTH", "shell", in_file=True),
        ],
        {"KEY": ["/s/module/api_key_env", "/t/module/api_key_env"]},
    )

    assert rows == [
        ("KEY", "used by `/s/module/api_key_env`, `/t/module/api_key_env`"),
        ("OLD_KEY", "not named by the current config"),
        (
            "BOTH",
            "not named by the current config — unused: the shell sets it too, and wins",
        ),
    ]
