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
        "| X extra | ❌ missing | Not installed. **Install missing extras** installs it "
        "(`speech-x`). |" in text
    )
    assert (
        "| Voice Ada | ❌ missing | Not downloaded. **Download missing files** gets it. |"
        in text
    )
    assert "| K | ✅ ready | Set. |" in text
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


def test_a_value_the_shell_shadows_and_the_file_s_other_variables_are_said() -> None:
    text = secrets_report(
        [(SecretVariable("A", "shell", in_file=True), ["/s/module/api_key_env"])],
        others=["OLD_KEY", "OTHER"],
    )

    assert "| `A` | ✅ the shell (the folder's .env also sets it, unused) |" in text
    assert "unset it in your shell profile" in text
    assert "**Also in the folder's .env**, not named by the current config: " in text
    assert "`OLD_KEY`, `OTHER`." in text
    # With no variable named, the file's variables are still listed.
    assert "`OLD_KEY`" in secrets_report([], others=["OLD_KEY"])
