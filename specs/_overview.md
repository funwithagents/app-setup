# Overview

What module-setup is, the words it uses, and how its specs fit together. Read this first; the normative detail is in the specs listed in [_index.md](_index.md).

## What it is

Some libraries are configured by a JSON document that selects **modules**: interchangeable implementations of one job, such as the providers of a speech synthesizer, the recognizers of a speech-to-text engine, or the backends of a robot driver. Each module may need an optional dependency (an **extra**) and things on the machine (model weights, a binary). Without help, a user finds this out by editing JSON by hand and reading error messages.

module-setup is the shared code that turns it into a page. Every app built on such libraries — a library's own demo, or an application composing several of them — gets the same two tabs:

- **Setup**: choose modules, edit their config in a form, see which extras are missing and install them, prepare what each module needs, manage secrets.
- **Session**: start the app's runtime with the saved config, use it, stop it.

## Vocabulary

| Word | Meaning |
|---|---|
| **app** | The process and its page. It stays up from launch to exit. |
| **session** | One run of the app's runtime, from Start to Stop. The config cannot change during a session; it can between two sessions, without restarting the app. |
| **host** | The project the app belongs to: the one whose `pyproject.toml` and `uv.lock` the environment is installed from: the library itself for its own demo, the application for an app composing several libraries. |
| **library** | A package that owns a config document and implements the contract. |
| **module** | One selectable implementation inside a library's config (one voice provider among several, one recognizer among several). |
| **section** | One library's config document inside the app's config file. |
| **requirement** | An optional dependency a config needs, written in the library's own terms: `speech-lib[local-voice]`. |
| **item** | One thing a config needs on the machine beyond packages: weights in a cache, a binary on the path. |

## Who does what

- **A library declares.** It implements the contract ([module-contract.md](module-contract.md)): it describes its config as a schema, says which requirements a config has, validates a config, checks its items and prepares them. It imports nothing from module-setup and returns plain data.
- **module-setup acts.** It renders the form from the schema, checks whether a requirement is installed from package metadata, maps it to the host's own extra and installs it with uv, stores secrets, keeps the config folder, and runs the Start/Stop state machine.
- **The host composes.** It lists its sections, hands each library's contract to module-setup, and supplies the function that builds a session from a config.

## The Setup sequence

For the config being edited, in this order, each step gating the next:

1. `validate` — the config's shape is right. Works with nothing installed.
2. requirements — every requirement of the config is installed; one click installs the missing ones.
3. `check` — every item is ready. Needs the requirements.
4. `prepare` — on click, the library fetches what it can.
5. Start is enabled.

Outside the sequence, `probe` runs one section for real on request (a Test button): it tells which section of an app is broken without starting the others.

## Planned specs

The contract is drafted first because every library builds against it. The others follow, in this order:

| Spec | What it will cover |
|---|---|
| config-folder | The app's folder: the default config, the current config, the settings (autostart) |
| secrets | The environment variables a config references, where each comes from (shell, the folder's `.env`), storing one |
| session | The Start/Stop state machine, the config locked during a session, autostart |
| ui | The Gradio pieces: the form rendered from a schema, the Setup, Secrets and Session tabs, the page |
