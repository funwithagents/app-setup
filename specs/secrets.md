---
code:
  - src/module_setup/secrets.py
tests:
  - tests/test_secrets.py
---

# Secrets

**Status:** Implemented

## Purpose

Libraries read their keys from the environment, through variable names their config gives (`x-secret-env` fields, [module-contract.md](module-contract.md)). A user should be able to provide those keys from the page, see where each one comes from, and never see one displayed back.

## Where a key comes from

| Source | When |
|---|---|
| `shell` | The variable was set, non-empty, in the environment the app was launched from. It always wins |
| `file` | The folder's `.env` holds it; the app put it into the process environment |
| `missing` | Neither |

`SecretStore(env_path, environ=os.environ)` records, when it is created, which variables the shell set. `load()` then copies the file's variables into the environment, except the shell's, and takes out those an earlier load put there that the file no longer holds. The app loads at launch and after each change, before any check or session, so the libraries' own `check_setup` and the Secrets tab see the same environment. A library never reads the `.env` itself.

## The `.env` file

The usual dialect: `NAME=value` lines, an optional `export`, values plain (a ` #` starts a comment), `'single'` or `"double"` quoted (`\n`, `\"`, `\\` escapes in double quotes), blank lines and `#` comments skipped, a later line winning.

Writing a variable replaces its line, or appends one, keeping every other line and comment; the value is always double-quoted and escaped, so it reads back the same. The file is made readable by its owner only (`0600`).

It is plain text. That is the first version's choice: simple, and the same file a developer already keeps. The OS keychain is an open question.

## API

```python
def parse_env(text: str) -> dict[str, str]: ...
def format_env(name: str, value: str) -> str: ...

class SecretStore:
    def load(self) -> None: ...
    def source(self, name: str) -> Literal["shell", "file", "missing"]: ...
    def variables(self, names: Iterable[str]) -> list[SecretVariable]: ...
    def set(self, name: str, value: str) -> Source: ...     # the source it now has
    def remove(self, name: str) -> Source: ...
```

`set` refuses a name that is not a variable name and an empty value (`ValueError`); setting a variable the shell already sets writes the file and returns `shell`, so the page can say the file's value is not the one in use. No method returns a value.

Which variables a config names is read from the sections' schemas (`module_setup.form.secret_variables`, used by `AppModel.secret_variables`): each `x-secret-env` field's value, or its default when absent; an object holding a key itself names none.

## Testing

`tests/test_secrets.py`: the dialect; a written value reads back the same, whatever its characters; the file feeds the environment but not over the shell; set and remove keep the other lines and the permissions; bad names and empty values are refused.

## Open questions

1. **The OS keychain** instead of a plain file.
2. **A key written in the config** (`api_key`, an `x-secret` field) is not drawn by the form and not managed here; moving it to a variable is left to the user.
