# Configuration, flags and CLIs

Load for any task that adds or changes flags, options, env parsing, config files, defaults or `--help`. Rules `S3`, `S4`, `S5`, `S7` apply.

## 1. Classify every setting

For each option you add, label it in the plan: **public** (port, log level), **sensitive** (credential, token, DSN with password, private key path contents), or **identifying** (user email, hostnames that reveal internal topology). Sensitive and identifying settings follow this whole file.

## 2. Defaults are promises

A default is code that runs for every user who sets nothing, appears in `--help`, appears in generated docs, and is compiled into the binary.

- Sensitive options have **no default**. An absent value is an error (S3, S7).
- Defaults must be safe by construction: bind `127.0.0.1` not `0.0.0.0`; TLS verification on; auth required; debug/pprof off; least-privilege file modes; smallest useful bound for sizes and timeouts.
- Never compute a default from a file in the repo that holds a secret, from `embed`, or from the developer's home directory.
- "Works out of the box" is not a reason to ship a credential. Out of the box, the program should tell the user precisely how to supply theirs.

## 3. How to accept a credential

Order of preference (see SKILL.md §3): secret-manager mount → `--thing-file PATH` → `THING_FILE` env → `THING` env → stdin (`--thing-stdin`). Reject `--thing=VALUE`.

Conventions that make this ergonomic:
- Flag and env names align: `--api-key-file` ↔ `API_KEY_FILE` ↔ `API_KEY`.
- Precedence is documented and tested: flag > `*_FILE` env > env. First present wins; do not merge.
- The error for "nothing supplied" lists the **names** of the three inputs and nothing else.
- Check file mode: refuse group/world-readable credential files on Unix; say `chmod 600 <path>`.
- Trim one trailing newline/space from file values; reject empty and obvious placeholders.
- Optionally support `-` as the path to read stdin, and read without terminal echo for interactive use (`golang.org/x/term.ReadPassword`).

## 4. Config files

- A config file may name where a secret lives (`api_key_file: /run/secrets/api_key`); it must not contain the secret. If the format could hold one, validate and reject inline secrets with a clear message.
- Never ship a config with real values. Ship `config.example.yaml` with obvious placeholders (`<set-via-API_KEY_FILE>`), and make the real file git-ignored.
- Strict parsing: reject unknown keys for security-relevant config so a typo (`api_kye_file`) cannot silently disable auth.
- Environment interpolation in config (`${API_KEY}`) is acceptable only if unset variables are an error, not an empty string.

## 5. `--help`, `--version`, dumps, completions

These print to terminals, CI logs and screenshots. They must show option names, descriptions, **empty** or non-sensitive defaults, and nothing from the environment.

- No `--dump-config` that prints raw values. If needed, print through the redacting type (SKILL.md S6) and test that sentinel values do not appear.
- `--version` prints version and commit only. No build flags, no module replace paths, no environment.
- Shell completion scripts and man pages are generated from flag definitions: they inherit any secret default. Check them.
- After any CLI change, run `-h`, `--version`, a no-args run, and a bad-args run, and read the output.

## 6. Environment variables

- Env is inherited by every child process and readable via `/proc/<pid>/environ` by the same user. Pass children an explicit, minimal environment (`cmd.Env = []string{...}`) instead of `os.Environ()` when the child does not need the secret.
- Never log `os.Environ()`. Never print the environment in error reports or crash handlers.
- Do not use env vars for long-lived production secrets where a mounted file is available.

## 7. Test the configuration surface

Minimum tests for a new credential option (names illustrative):
- supplied via file → success; via env → success; precedence honored.
- missing → typed error that is not nil, mentions input **names**, contains no value.
- empty file, whitespace-only, placeholder, oversized, directory, world-readable → each rejected.
- `fmt.Sprintf("%v %+v %#v", cfg)` and the JSON/slog output of the config contain the placeholder and not a sentinel secret.
- `-h` output does not contain the sentinel.
