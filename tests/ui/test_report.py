from module_setup.app import Problem, SetupItem
from module_setup.secrets import SecretVariable
from module_setup.ui.report import (
    config_report,
    secrets_report,
    setup_report,
)


def test_config_problems_are_listed_with_their_pointer() -> None:
    assert config_report([]) == "✅ **The config is valid.**"
    text = config_report(
        [Problem("speech", "/speech/module/voice_id", "voice_id is required")]
    )
    assert "`/speech/module/voice_id`: voice_id is required" in text


def test_the_setup_table_says_what_to_do_about_each_missing_item() -> None:
    items = [
        SetupItem(
            "speech",
            "extra:speech-lib[x]",
            "X extra",
            "missing",
            "Not installed.",
            False,
            ("speech-x",),
        ),
        SetupItem(
            "speech", "weights:Ada", "Voice Ada", "missing", "Not downloaded.", True
        ),
        SetupItem("speech", "key:K", "K", "ready", "Set.", False),
        SetupItem(
            "speech",
            "weights:Bo",
            "Voice | Bo",
            "unknown",
            "Fetched at first load.",
            True,
        ),
    ]

    text = setup_report(items)

    assert text.startswith("❌ **2 thing(s) missing on this machine.**")
    assert (
        "| speech | X extra | ❌ missing | Not installed. Install: `speech-x`. |"
        in text
    )
    assert (
        "| speech | Voice Ada | ❌ missing | Not downloaded. Prepare downloads it. |"
        in text
    )
    assert "| speech | K | ✅ ready | Set. |" in text
    assert "Voice \\| Bo" in text
    assert setup_report([]) == "✅ **This machine needs nothing more for this config.**"
    assert setup_report(items[2:3]).startswith("✅ **This machine is ready")


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
