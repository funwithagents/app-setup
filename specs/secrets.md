---
code:
  - src/app_setup/secrets.py
tests:
  - tests/test_secrets.py
---

# Secrets

**Status:** Updated

## Purpose

Libraries read their keys from the environment, through variable names their config gives (`x-secret-env` fields, [module-contract.md](module-contract.md)). A user should be able to provide those keys from the page, see where each one comes from, and never see one displayed back.

## Where a key comes from

| Source | When |
|---|---|
| `shell` | The variable was set, non-empty, in the environment the app was launched from. It always wins |
| `file` | The folder's `.env` holds it; the app put it into the process environment |
| `missing` | Neither |

`SecretStore(env_path, environ=os.environ)` records, when it is created, which variables the shell set. `load()` then copies the file's variables into the environment, except the shell's, and takes out those an earlier load put there that the file no longer holds. The `AppModel` loads it when it is built ([app.md](app.md)), and the store keeps the environment in step with each change, before any check or session, so the libraries' own `check_setup` and the Secrets panel see the same environment. A library never reads the `.env` itself.

**Why the shell wins.** It is the dotenv convention (python-dotenv's `load_dotenv` without `override`, Node's and Ruby's dotenv, Docker Compose's variable substitution): the `.env` holds the folder's defaults, the environment a process is started with is the deliberate, per-run choice, so a deployment (a service definition, a CI job, a variable on the command line) overrides the file without editing it, and a stale key in the folder never silently beats it. The cost, a key saved from the Secrets panel that is not the one used, is made visible instead: a variable the shell sets and the file also sets is reported as such (`SecretVariable.in_file`, `shadowed`), with how to use the file's value.

## The `.env` file

The usual dialect: `NAME=value` lines, an optional `export`, values plain (a ` #` starts a comment), `'single'` or `"double"` quoted (`\n`, `\"`, `\\` escapes in double quotes), blank lines and `#` comments skipped, a later line winning.

Writing a variable replaces its line, or appends one, keeping every other line and comment; the value is always double-quoted and escaped, so it reads back the same. The file is made readable by its owner only (`0600`; Windows has no such modes, and the file is private there through the user profile's access rules).

It is plain text. That is the first version's choice: simple, and the same file a developer already keeps. The OS keychain is an open question.

## API

```python
def parse_env(text: str) -> dict[str, str]: ...
def format_env(name: str, value: str) -> str: ...

class SecretStore:
    def load(self) -> None: ...
    def source(self, name: str) -> Literal["shell", "file", "missing"]: ...
    def variables(self, names: Iterable[str]) -> list[SecretVariable]: ...  # name, source, in_file
    def file_names(self) -> list[str]: ...                   # what the .env sets, names only
    def set(self, name: str, value: str) -> Source: ...     # the source it now has
    def remove(self, name: str) -> Source: ...
    revision: int                                            # bumped by each set and remove
```

`set` refuses a name that is not a variable name and an empty value (`ValueError`); setting a variable the shell already sets writes the file and returns `shell`, so the page can say the file's value is not the one in use. `SecretVariable.in_file` says the file sets a variable too; `shadowed` is that, with the shell's value in use. `file_names` lists what the `.env` sets, so the page can show the variables no config names (a stale key to remove). No method returns a value.

`revision` counts the writes: each `set` and `remove` bumps it, by any caller. A page that cannot be told of a write (the Setup panel, when a key is saved from the Secrets panel or another browser tab) compares it with the last one it saw, and checks the config again when it changed: a key just saved turns its item ready without a click on Check ([ui.md](ui.md)).

Which variables a config names is read from the sections' schemas (`app_setup.form.secret_variables`, used by `AppModel.secret_variables`): each `x-secret-env` field's value, or its default when absent; an object holding a key itself names none.

## Testing

`tests/test_secrets.py`: the dialect; a written value reads back the same, whatever its characters; the file feeds the environment but not over the shell, and a variable set in both is reported as shadowed; the file's names; set and remove keep the other lines and the permissions, and each bumps `revision`; bad names and empty values are refused.

## Open questions

1. **The OS keychain** instead of a plain file.
2. **A key written in the config** (`api_key`, an `x-secret` field) is not drawn by the form and not managed here; moving it to a variable is left to the user.
