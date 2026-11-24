from app_setup.app import Problem, SetupItem
from app_setup.secrets import SecretVariable
from app_setup.ui.report import (
    Progress,
    config_report,
    env_file_rows,
    item_status,
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


def test_the_summary_says_it_in_the_table_s_words() -> None:
    assert setup_summary([]) == "✅ **Ready**"
    assert setup_summary([KEY]) == "✅ **Ready**"
    assert setup_summary([EXTRA, VOICE, KEY]) == (
        "❌ **1 required item missing** — 1 optional item missing: the first start "
        "will get them, slower"
    )
    assert setup_summary([EXTRA, LEXICON]) == "❌ **2 required items missing**"
    assert setup_summary([VOICE, VOICE, KEY]) == (
        "✅ **Ready to run** — 2 optional items missing: the first start will get "
        "them, slower"
    )


def test_each_line_says_its_status_and_why() -> None:
    missing_key = SetupItem(
        "speech", "key:K", "K", "missing", "Not set.", False, True, variable="K"
    )
    unknown = SetupItem(
        "speech", "gpu", "GPU", "unknown", "Cannot tell yet.", True, True
    )

    assert item_status(EXTRA) == (
        "❌ **Missing – required**",
        "Not installed. **Install** adds it (the `speech-x` extra).",
    )
    assert item_status(LEXICON) == (
        "❌ **Missing – required**",
        "Not built. **Prepare** gets it.",
    )
    assert item_status(missing_key) == (
        "❌ **Missing – required**",
        "Not set. Type `K` here, or in the Secrets panel.",
    )
    assert item_status(VOICE) == (
        "🟡 **Missing – optional**",
        "Not downloaded. Without it, the first start gets it itself and is slower.",
    )
    assert item_status(KEY) == ("✅ **Ready**", "Set.")
    assert item_status(unknown) == ("❔ **Can't tell**", "Cannot tell yet.")


def test_a_line_being_acted_on_shows_its_progress_then_how_it_ended() -> None:
    measured = Progress(True, 0.4, "Downloading 120 of 300 MB", 3.0)
    unmeasured = Progress(True, None, "Building the cache", 12.4)
    installing = Progress(True, None, "Downloading torch (120 MB)", 5.2, install=True)
    waiting = Progress(True, None, "", 1.0, install=True, waiting=True)

    assert item_status(VOICE, measured) == (
        "⏳ **Preparing… 40%**",
        "`▓▓▓▓▓░░░░░░░` Downloading 120 of 300 MB",
    )
    assert item_status(VOICE, unmeasured) == (
        "⏳ **Preparing…**",
        "Building the cache (12 s)",
    )
    assert item_status(EXTRA, installing) == (
        "⏳ **Installing…**",
        "Downloading torch (120 MB) (5 s)",
    )
    assert item_status(EXTRA, waiting) == (
        "⏳ **Waiting**",
        "Waiting for another install…",
    )
    assert item_status(VOICE, Progress(False, 1.0, "", 9.0, ok=True)) == (
        "✅ **Ready**",
        "Prepared.",
    )
    assert item_status(
        EXTRA, Progress(False, None, "", 9.0, ok=True, install=True)
    ) == (
        "✅ **Ready**",
        "Installed.",
    )
    assert item_status(VOICE, Progress(False, 0.2, "Unreachable.", 2.0, ok=False)) == (
        "❌ **Failed**",
        "Unreachable. **Prepare** tries again.",
    )
    failed = Progress(
        False, None, "uv exited with code 1.", 2.0, ok=False, install=True
    )
    assert item_status(EXTRA, failed) == (
        "❌ **Failed**",
        "uv exited with code 1. **Install** tries again.",
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
