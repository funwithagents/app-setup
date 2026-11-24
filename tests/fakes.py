"""A small speech library that implements the contract, for the app and page tests."""

from __future__ import annotations

import copy
import threading
from typing import Any


def schema() -> dict[str, Any]:
    return {
        "contract": 1,
        "distribution": "speech-lib",
        "title": "Speech",
        "schema": {
            "type": "object",
            "required": ["module"],
            "properties": {
                "module": {
                    "type": "object",
                    "title": "Voice",
                    "description": "The voice that speaks.",
                    "required": ["type"],
                    "properties": {
                        "timeout": {
                            "type": "number",
                            "description": "Seconds before a request gives up.",
                            "default": 10,
                            "exclusiveMinimum": 0,
                            "x-advanced": True,
                        }
                    },
                    "oneOf": [
                        {
                            "title": "Local voice",
                            "x-options": "voices",
                            "properties": {
                                "type": {"const": "local-voice"},
                                "voice": {
                                    "type": "string",
                                    "description": "The voice's name.",
                                    "default": "Ada",
                                },
                                "speed": {
                                    "type": ["number", "null"],
                                    "description": "The speaking rate.",
                                },
                            },
                        },
                        {
                            "title": "Cloud voice (hosted)",
                            "required": ["voice_id"],
                            "properties": {
                                "type": {"const": "cloud-voice"},
                                "voice_id": {
                                    "type": "string",
                                    "description": "The id of the voice.",
                                },
                                "speed": {
                                    "type": ["number", "null"],
                                    "description": "The speaking rate.",
                                },
                                "api_key_env": {
                                    "type": "string",
                                    "description": "The variable holding the key.",
                                    "default": "CLOUD_VOICE_KEY",
                                    "x-secret-env": True,
                                },
                                "api_key": {
                                    "type": "string",
                                    "description": "The key itself.",
                                    "x-secret": True,
                                },
                            },
                        },
                    ],
                },
                "gate": {
                    "type": "object",
                    "description": "Silence gate; absent means off.",
                    "properties": {
                        "level": {
                            "type": "integer",
                            "description": "How strict.",
                            "enum": [1, 2, 3],
                            "default": 2,
                        },
                        "loud": {
                            "type": "boolean",
                            "description": "Louder.",
                            "default": False,
                        },
                    },
                },
                "passthrough": {
                    "type": "object",
                    "description": "Arguments handed to the provider as they are.",
                    "additionalProperties": True,
                },
            },
        },
    }


class SpeechLib:
    """The contract, with what the machine has as plain attributes a test sets."""

    def __init__(self) -> None:
        self.installed = {"local-voice": True, "cloud-voice": True}
        # What is ready on the machine: the voices' weights and the lexicon.
        self.downloaded: set[str] = set()
        self.lexicon = False
        # Preparing: the items that fail, and a gate each preparation waits on once started
        # (None: no wait), so a test can see two preparations overlap.
        self.failing: set[str] = set()
        self.gate: threading.Event | None = None
        self.started: list[str] = []
        self.probed: list[dict[str, Any]] = []
        # The `base_dir` each machine-facing call was given, by function name.
        self.base_dirs: dict[str, str | None] = {}

    def config_schema(self) -> dict[str, Any]:
        return schema()

    def required_extras(self, config: dict[str, Any]) -> list[str]:
        module = config.get("module")
        kind = module.get("type") if isinstance(module, dict) else None
        return [f"speech-lib[{kind}]"] if kind in self.installed else []

    def check_config(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        module = config.get("module")
        if not isinstance(module, dict):
            return [{"path": "/module", "message": "module is required"}]
        if module.get("type") not in self.installed:
            return [{"path": "/module/type", "message": "unknown voice"}]
        if module.get("type") == "cloud-voice" and not module.get("voice_id"):
            return [{"path": "/module/voice_id", "message": "voice_id is required"}]
        return []

    def check_setup(
        self, config: dict[str, Any], *, base_dir: str | None = None
    ) -> list[dict[str, Any]]:
        import os

        self.base_dirs["check_setup"] = base_dir

        kind = config["module"]["type"]
        ok = self.installed[kind]
        items = [
            {
                "id": f"extra:speech-lib[{kind}]",
                "title": f"{kind} extra",
                "status": "ready" if ok else "missing",
                "detail": "Installed." if ok else f"pip install 'speech-lib[{kind}]'",
                "preparable": False,
                "required": True,
            }
        ]
        if kind == "cloud-voice":
            name = config["module"].get("api_key_env", "CLOUD_VOICE_KEY")
            items.append(
                {
                    "id": f"key:{name}",
                    "title": name,
                    "status": "ready" if os.environ.get(name) else "missing",
                    "detail": "Set." if os.environ.get(name) else f"Set {name}.",
                    "preparable": False,
                    "required": True,
                }
            )
        elif ok:
            voice = config["module"].get("voice", "Ada")
            items.append(
                {
                    "id": f"weights:{voice}",
                    "title": f"Voice {voice}",
                    "status": "ready" if voice in self.downloaded else "missing",
                    "detail": "Downloaded."
                    if voice in self.downloaded
                    else "Not downloaded yet.",
                    "preparable": True,
                    # The library downloads a voice itself when a session first speaks.
                    "required": False,
                }
            )
            items.append(
                {
                    "id": "lexicon",
                    "title": "Lexicon",
                    "status": "ready" if self.lexicon else "missing",
                    "detail": "Built." if self.lexicon else "Not built yet.",
                    "preparable": True,
                    # A session cannot start without it.
                    "required": True,
                }
            )
        return items

    def prepare(
        self,
        config: dict[str, Any],
        item: str,
        *,
        on_progress: Any = None,
        base_dir: str | None = None,
    ) -> None:
        self.base_dirs["prepare"] = base_dir
        voice = config["module"].get("voice", "Ada")
        if item not in (f"weights:{voice}", "lexicon"):
            raise ValueError(f"{item!r} is not a preparable item of this config")

        def report(fraction: float, message: str) -> None:
            if on_progress is not None:
                on_progress({"fraction": fraction, "message": message})

        self.started.append(item)
        report(0.0, "Starting")
        if self.gate is not None and not self.gate.wait(timeout=10):
            raise TimeoutError("the test never opened the gate")
        if item in self.failing:
            raise OSError(f"Could not get {item}: the server is unreachable.")
        report(0.5, "Halfway")
        if item == "lexicon":
            self.lexicon = True
        else:
            self.downloaded.add(voice)
        report(1.0, "Done")

    def options(
        self, name: str, config: dict[str, Any], *, base_dir: str | None = None
    ) -> list[dict[str, Any]]:
        self.base_dirs["options"] = base_dir
        if name != "voices":
            return []
        return [
            {"label": "Bo (en)", "fields": {"voice": "Bo"}},
            {"label": "Cy (fr)", "fields": {"voice": "Cy", "speed": 1.2}},
        ]

    def probe(
        self, config: dict[str, Any], *, base_dir: str | None = None
    ) -> dict[str, Any]:
        self.base_dirs["probe"] = base_dir
        self.probed.append(copy.deepcopy(config))
        return {"ok": True, "message": "Spoke.", "duration_s": 0.1}
