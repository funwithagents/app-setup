# module-setup

module-setup is the Setup side of an app built from configurable libraries: libraries whose config document selects **modules** (interchangeable implementations of one job), each of which may need an optional dependency and things on the machine. Each library **declares**, as plain data, what its config looks like, which optional dependencies a config needs and what it needs on the machine; module-setup **acts** on those declarations — a form to edit the config, a check and a uv install for each missing extra, a store for secrets, and a Start/Stop session over the saved config — so that no app needs a hand-edited JSON file or a restart to change provider.

> **New here?** Read [_overview.md](_overview.md) first for the vocabulary (app, session, host, module, requirement, item) and how the specs below fit together.

## Specs

<!-- One row per concept spec. Keep the Status column in sync with each spec's `**Status:**` line. -->

| Spec | Description | Status |
|---|---|---|
| [project.md](project.md) | Project structure and tooling: Python version, packaging with uv, layout conventions | Implemented |
| [testing.md](testing.md) | Testing strategy: two-tier `tests/`/`tests-e2e/` split, functional-test philosophy, skip-without-credentials live tier | Implemented |
| [module-contract.md](module-contract.md) | The contract a library implements, as plain data and seven functions: `describe` (the config's JSON Schema, annotated), `requirements`, `validate`, `check`, `prepare`, `options`, `probe` (run it once, for real); what module-setup parses and the conformance check a library runs in its tests | Implemented |
| [extras.md](extras.md) | What is done with a requirement such as `speech-lib[local-voice]`: whether it is installed and available on this platform (from package metadata, nothing imported), which extra of the host carries it, and the uv install that adds extras from the host's lock without removing anything | Implemented |
| _(add concept specs here — see [_spec-template.md](_spec-template.md))_ | | |

Each spec also opens with a YAML **frontmatter** block declaring the `code:` and `tests:` files it governs — the spec → code/tests mapping the spec-drift checks use to scope what they compare. Keep it current when files move, and see [AGENTS.md](../AGENTS.md) ("Spec frontmatter") for the full convention. A spec that is not yet `Implemented` may name the files it *will* govern.

### Status legend

- **Not started** — no design decisions made yet
- **Draft** — actively being brainstormed/defined, contains open questions
- **Stable** — design settled, reviewed and validated (open questions are deferrals only), **ready to implement but not necessarily implemented yet**. This is the design-review gate, before code is written.
- **Implemented** — a **Stable** spec that a `Done` plan has built: the code now exists and matches the spec (design and code in sync)
- **Updated** — an **Implemented** spec since edited in a way that needs new code, so the code no longer matches it; a new implementation plan is needed (or in progress) to catch up. Returns to **Implemented** once that plan is `Done`.
