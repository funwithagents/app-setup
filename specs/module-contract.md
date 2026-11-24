---
code:
  - src/module_setup/contract.py
tests:
  - tests/test_contract.py
---

# Module contract

**Status:** Implemented

## Purpose

The contract is what a library implements so that an app can set it up without knowing it: which modules it offers, what each one's config looks like, which optional dependency a config needs, what it needs on the machine. It is the one interface between the libraries and module-setup, and every library builds against it, so it is specified before anything else. Vocabulary (app, session, host, library, module, section, requirement, item) is in [_overview.md](_overview.md).

Two rules shape it:

- **A library declares, it does not act.** It never installs a package and never runs uv. Only the host knows its own extras and its lock, so installing is module-setup's job ([extras.md](extras.md)).
- **Plain data, no shared types.** A library imports nothing from module-setup. What it returns is JSON-compatible: dicts, lists, strings, numbers, booleans, `None`. A library's own code can therefore implement the contract with no new dependency.

## The contract object

A contract is any object with the seven callables below. A Python module qualifies, and the convention is one module per library named `setup` (`speech_lib.setup`). module-setup types it with a `Protocol` (`SetupContract`), matched structurally.

```python
def config_schema() -> dict: ...
def required_extras(config: dict) -> list[str]: ...
def check_config(config: dict) -> list[dict]: ...
def check_setup(config: dict) -> list[dict]: ...
def prepare(
    config: dict, on_progress: Callable[[dict], None] | None = None
) -> None: ...
def options(name: str, config: dict) -> list[dict]: ...
def probe(config: dict) -> dict: ...
```

`config` is always the library's own config document — the object its loader's `from_dict` takes — never the whole file of an app that composes several libraries.

All seven are synchronous. module-setup calls the slow ones (`check_setup`, `prepare`, `options`, `probe`) off the page's thread.

What each answers, in the order an app uses them:

| Function | Answers | Same answer on every machine? |
|---|---|---|
| `config_schema` | What does the config look like? | yes |
| `required_extras` | Which extras does this config need? | yes |
| `check_config` | What is wrong in the config itself? | yes |
| `check_setup` | What is ready or missing on this machine for it to run: extras, keys, files? | no |
| `prepare` | — makes the missing files ready (downloads) | no |
| `options` | What can this field be set to (voices, devices)? | no |
| `probe` | Does it actually work? Runs it once | no |

The usual order: `check_config`, then `check_setup`; the user installs the missing extras and sets the missing keys; `prepare` downloads the files; `check_setup` again; `probe` when wanted; then the session starts. `check_setup` comes before `prepare` because it says whether there is anything to prepare, and `prepare` needs the extras installed.

What each may rely on:

| Function | The library's extras installed | Reads env vars | Network | May raise |
|---|---|---|---|---|
| `config_schema` | no | no | no | no |
| `required_extras` | no | no | no | no |
| `check_config` | no | no | no | no |
| `check_setup` | no | yes | no | no |
| `prepare` | yes | yes | yes | yes |
| `options` | yes | yes | yes | yes |
| `probe` | yes | yes | yes | no |

"No" under extras means the function must work in an environment holding the library's base install only. This is the contract's main demand on the libraries: today most module fields are validated in the module's constructor, after its provider library is imported. They have to be validated without that import.

## `config_schema`

```json
{
  "contract": 1,
  "distribution": "speech-lib",
  "title": "Text to speech",
  "schema": { "…": "the JSON Schema of the config document" }
}
```

- `contract` — the contract version the library implements, `1`. module-setup refuses a version it does not know, naming it.
- `distribution` — the library's distribution name, as in its `pyproject.toml`.
- `title` — the section's heading in the form.
- `schema` — the config document as a JSON Schema, restricted to the subset below.

`config_schema` is pure: the same value on every call, whatever is installed.

### The schema is for the form, not for validation

The schema says what to draw: the fields, their kind, their default, their allowed values, their help text. It is not the authority on whether a config is valid: `check_config` is. module-setup never validates a config against the schema, so it needs no JSON Schema validator, and a rule a schema cannot express (exactly one of `system_prompt` and `system_prompt_file`) simply lives in `validate`.

The two must still agree. The conformance check (below) verifies what can be verified: defaults and examples pass `check_config`, and the keys the schema names are keys `validate` accepts.

### The supported subset

| Keyword | Use |
|---|---|
| `type` | `object`, `string`, `number`, `integer`, `boolean`, `array`. A list adds `null` for a nullable field (`["string", "null"]`) and may combine scalar types for a field accepting several kinds (`["string", "integer", "null"]`: a device named or numbered) |
| `properties`, `required` | An object's fields. A field not in `required` may be absent from the config |
| `title`, `description` | The field's label and help text. `description` is required on every field, nested objects included |
| `default` | The value the library uses when the field is absent. The form shows it and does not write it to the config unless the user changes it |
| `enum` | A fixed set of values: a dropdown |
| `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum` | Number bounds, shown and enforced by the form. On a field accepting several kinds they apply to its numeric values |
| `items` | The type of an array's elements, as a single `type`: a scalar type, or `object` for a list of objects, which the form edits as raw JSON (`check_config` checks its content) |
| `oneOf` | A choice between modules (below) |
| `additionalProperties: true` | A free-form object (keyword arguments passed through to a provider): edited as raw JSON |

Anything else in a schema is an error when module-setup parses the description, naming the keyword and its path, so that a library cannot ship a schema the form silently misrenders.

**An optional object is a switch.** An object-typed field that is not `required` (a voice-activity gate that can be left out) is drawn with an enable box: off means the key is absent from the config.

### A choice between modules

A module choice is an object schema with a `oneOf`, each branch being one module, told apart by a property that is a `const` in every branch:

```json
{
  "type": "object",
  "title": "Voice",
  "required": ["type"],
  "oneOf": [
    {
      "title": "Local voice",
      "properties": {
        "type": { "const": "local-voice" },
        "voice": {
          "type": "string",
          "description": "The voice's name.",
          "default": "Ada",
          "x-options": "voices"
        }
      }
    },
    {
      "title": "Cloud voice (hosted)",
      "required": ["voice_id"],
      "properties": {
        "type": { "const": "cloud-voice" },
        "voice_id": {
          "type": "string",
          "description": "The id of the voice to speak with.",
          "x-options": "voices"
        },
        "api_key_env": {
          "type": "string",
          "description": "The environment variable holding the provider's key.",
          "x-secret-env": true
        }
      }
    }
  ]
}
```

(An illustrative speech library, `speech-lib`, used in the examples of this spec.)

- The **discriminator** is the one property that is a `const` in every branch, with a different scalar value in each. module-setup finds it; it is not named separately, and it is declared in the branches only. Every branch has a `title`.
- The object's own `properties` hold the fields common to every branch; a branch adds its own, under names the common ones do not use. This is how WICA's flat `agent` object is described: `model`, `system_prompt_file` and the rest are common, `provider` discriminates, `base_url` and `hf_provider` sit in their provider's branch.
- The form draws a dropdown of the branch titles and, under it, the selected branch's fields. Switching branch keeps the values of the fields common to every branch and drops the old branch's own, even those the new branch has under the same name: a voice id of one provider means nothing to another.

A `oneOf` in any other shape is refused.

### Annotations

Four `x-` keywords carry what JSON Schema has no word for:

| Keyword | On | Meaning |
|---|---|---|
| `x-advanced: true` | a field | Drawn in a folded "Advanced" block. Fields without it are the ones a first-time user is expected to set or see |
| `x-secret-env: true` | a string field | The field's value is the *name* of an environment variable holding a secret (`api_key_env`). The Secrets tab lists every such variable of the current config |
| `x-secret: true` | a string field | The field holds a secret *itself* (`api_key`). The form never draws it and never shows its value; it stays reachable in the raw JSON view only |
| `x-options: "<name>"` | a field or a module branch | Its choices come from `options("<name>", config)` (below) |

A provider that reads a well-known variable when the config names none (many provider SDKs do) declares it as the `default` of its `x-secret-env` field, which is how the Secrets tab knows to look for it.

## `required_extras`

```python
required_extras(config) -> ["speech-lib[local-voice]"]
```

The optional dependencies this config needs, each a requirement string naming **the library's own distribution and one of its own extras**, exactly as its `pyproject.toml` spells them — never a host's extra (an app's `speech-local-voice`), which the library cannot know. A config needing none returns `[]`. A library that embeds another's config passes that library's requirements through unchanged: a robot library `robot-lib` whose config embeds the speech one returns `["robot-lib[sim]", "speech-lib[local-voice]"]` for a simulated robot speaking with the local voice.

It is a function of the config, not an annotation on the schema, because what decides a requirement is not always a module choice: a robot library's `sim` extra can follow a plain `backend` field, and one module can pick between two extras by platform.

- **It reads only the fields that decide.** It is called on configs that are incomplete or invalid — the form asks "what would this need?" for each module of a dropdown, before the user has filled anything — so it ignores everything else and never raises. An unknown module yields `[]`; `check_config` is what reports it.
- **It says what the config needs, not whether it is installed.** Whether a requirement is installed, and whether it can be on this platform, is read from package metadata by module-setup ([extras.md](extras.md)), with no code in the library.

## `check_config`

```python
check_config(config) -> [{"path": "/module/voice_id", "message": "voice_id is required"}]
```

Every problem that makes the library refuse this config, `[]` when it accepts it.

- `path` — a JSON Pointer to the offending field inside the config document, `""` for a problem that is the document's as a whole or whose field the library cannot name.
- `message` — one sentence for the user, the same wording the loader raises.

`check_config` is the authority: **a config with no problem must be accepted by the library's loader and by the selected modules' constructors**, short of what only the machine, the provider's library or its service can tell (a missing key, an unreachable server, a missing extra, a voice name the provider does not know). Conversely it must report everything those would refuse on the config's shape alone.

It reports as many problems as it can, so the form can mark several fields at once. A library whose loader stops at the first error may return just that one at first; reporting all of them is an improvement it makes at its own pace.

## `check_setup`

```python
check_setup(config) -> [
  {
    "id": "extra:speech-lib[local-voice]",
    "title": "Local voice extra",
    "status": "ready",
    "detail": "Installed.",
    "preparable": false
  },
  {
    "id": "weights:local-voice/Ada",
    "title": "Local voice Ada",
    "status": "missing",
    "detail": "Not downloaded yet (about 300 MB).",
    "preparable": true
  }
]
```

Everything this config needs on **this machine** to run, each as an item. `[]` when it needs nothing.

- `id` — stable for a given config; `prepare` reports progress against it.
- `title` — what the item is.
- `status` — `ready`, `missing`, or `unknown` (the library cannot tell without doing the work).
- `detail` — one sentence: where it is, how big, or what the user must do.
- `preparable` — whether `prepare` can make it ready. `false` is for what only the user can fix; `detail` then says how.

The items, in this order:

1. **Extras** — one item per extra the config needs (`id` `extra:<requirement>`), never preparable. The library finds out by **trying the imports** the selected module needs, which is what will run: a missing package, a broken install, a version missing a symbol, a missing native library all show here. The detail of a missing one is the library's install hint. Installing is the host's business (module-setup's [extras.md](extras.md)), which also tells, from package metadata, whether the extra can be installed on this platform at all.
2. **Keys** — one item per environment variable the config names for a secret (an `x-secret-env` field), `ready` when it is set and non-empty, else `missing`, never preparable. A key written in the config itself needs no item. Whether the provider *accepts* the key is not checked here.
3. **Files** — model weights, voice files, a local file the config points at. Only once the extras are installed: looking them up may need the provider's library. Preparable when the library can download them; a local path the config names is `ready` or `missing` and never preparable.

It works on the base install (a missing extra is one of its answers), and on a config `check_config` accepts. It is **local and fast**: it imports, reads the environment, looks at caches, files and the path, and makes no network call. Importing a heavy provider can take a second or two; the import stays loaded in the process, which a session starting next would pay anyway.

The environment it reads is the process's: an app that keeps keys in a file loads them into the environment before calling it (module-setup's app does). Start is enabled when no item is `missing`. An `unknown` item does not block it.

## `prepare`

```python
prepare(config, on_progress=None) -> None
```

Makes every `preparable` item of this config ready: today, downloading model weights. It needs the config's extras installed. It blocks until done and raises on failure, with a message for the user.

- **Idempotent.** With everything ready it returns at once.
- **It leaves the rest alone.** Items that are not `preparable` are not its business.
- `on_progress`, when given, is called with `{"id": …, "fraction": 0.4, "message": "…"}`; `fraction` is `None` when the library cannot measure. It may be called from any thread.

## `options`

```python
options("voices", config) -> [{"label": "Ada (en)", "fields": {"voice": "Ada"}}]
```

The choices of a named list: the voices of a provider, the audio devices of the machine. `config` is the document being edited, so the answer can depend on the selected module.

- `label` — what the user reads.
- `fields` — the fields the choice sets, merged into the object that carries the `x-options` annotation. A choice often sets one field; a voice may set several at once (a voice id and its model), which is why it is not a single value.

`x-options` sits on a field, whose object then receives `fields`, or on a module branch, for a list that fills several of its fields.

It is a suggestion, not a constraint: the fields stay editable, `check_config` decides what is accepted. It is called on request (a refresh button), may use the network and a key, and may raise; the form then shows the message and leaves the fields as they are. An unknown `name` returns `[]`.

## `probe`

```python
probe(config) -> {"ok": true, "message": "Spoke a test sentence on the default device.", "duration_s": 1.4}
```

Runs the config for real, once and briefly, so that a user can find out from the Setup tab whether it works: the key is accepted, the server answers, the model loads, sound comes out. Each library decides what a meaningful run is: speak a short sentence, open the recognizer's connection, send one small request to a model, connect to the device.

- `ok` — whether the run succeeded.
- `message` — one sentence for the user: what was done, or what failed and what to do about it.
- `duration_s` — how long it took.

It **never raises**: a failure is `ok: false` with its message. It **releases what it built** before returning, so it never interferes with a session, and no session is running when it is called. It may read keys, use the network, cost a provider request and take several seconds (a local model is loaded, then released), so it runs **only on a click** and never gates Start: it is a diagnostic, not a step of the sequence.

A library with nothing worth running for a config returns `ok: true` and says so.

## Composition

A library that embeds another's config (a robot library carrying its voice's config) builds its contract from the other's: its schema places the embedded schema at that property, and its `required_extras`, `check_config`, `check_setup`, `prepare`, `options` and `probe` delegate for that part, re-rooting `path`s and keeping requirement strings as they are.

A host does the same one level up: its app config is one section per library, and module-setup composes the sections' contracts ([config-folder.md](config-folder.md), [app.md](app.md)). A host's own sections (settings no library owns) are described by a contract the host writes itself, in the same shape.

A section whose *library* is itself optional for the host (an app that installs its speech library only with one of its own extras) cannot be asked to describe itself until it is installed. Gating a whole section on a requirement is the host's declaration, not part of this contract.

## What module-setup provides

`src/module_setup/contract.py`:

- **`SetupContract`** — the `Protocol` above.
- **`parse_description(data) -> Description`** — turns a `config_schema()` result into typed, frozen objects the form is drawn from, and raises `ContractError` (a `ValueError`) naming the path of anything outside this spec: an unknown contract version, an unsupported keyword, a `oneOf` without a discriminator, a field without a `description`.
- **`check_contract(contract, examples)`** — the conformance check a library runs in its own test suite (module-setup is a dev dependency there, never a runtime one). Given the contract and a list of example configs, it asserts:
  - the contract object has the seven callables;
  - `config_schema()` parses, and returns the same value twice;
  - every example passes `check_config`;
  - for every module of every choice, a config selecting it passes `check_config` with every default of the schema written out explicitly. It starts from the first example selecting that module; with none, from the module's required fields at their defaults, and a module with a required field that has no default must be covered by an example;
  - every key an example uses is a key the schema names (or sits under a free-form object);
  - `required_extras` returns well-formed requirement strings on every example, on `{}` and on each choice's bare module, without raising;
  - every extra a requirement names exists in that distribution's metadata.

  It runs neither `check_setup`, `prepare`, `options` nor `probe`: what they do depends on the machine, and each library tests its own.

  It raises `ContractViolation` (an `AssertionError`) listing every breach at once. Its `extras_of` argument replaces the metadata lookup, for a test that should not depend on what is installed.

## Testing

`tests/test_contract.py`, over small hand-written contracts:

- `parse_description`: a description using every supported keyword parses into the expected objects; each refusal (unknown version, unsupported keyword, malformed `oneOf`, missing `description`, an `x-` keyword on the wrong kind of field) raises `ContractError` naming the path.
- The discriminator is found for a nested module block and for a flat object with common fields.
- `check_contract` passes on a correct contract and fails, naming the cause, on each broken one: a missing function, a default `check_config` refuses, an example key the schema lacks, a requirement naming an extra that does not exist, a `requirements` that raises on `{}`.

## Open questions

1. **Platform limits are derived, not declared.** A module that exists on one platform only (a model that runs on Apple silicon only) is recognised because its extra's requirements all carry a marker that is false here. If that proves too indirect, a library could state the marker itself in `describe`.
2. **Fields that are lists of objects** are edited as raw JSON. Drawing them as rows is deferred.
3. **Async libraries.** `prepare`, `options` and `probe` are synchronous; a library whose only API is async wraps it. Revisit if that turns out awkward for a library built on asyncio.
4. **A shared field-declaration helper.** Each library writes its own way of declaring a field once so that it both validates and emits the schema. A helper shared between libraries would spare them that, at the price of a runtime dependency this contract deliberately avoids.
