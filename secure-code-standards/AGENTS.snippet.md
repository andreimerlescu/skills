## Security — mandatory skill

For ANY task that writes, edits, reviews, configures, builds or packages code, scripts, Dockerfiles, CI or docs — and ALWAYS when you are handed, find, or read a credential, API key, token, password, private key, certificate, connection string, `.env`, or a file with a name like `keys.txt` / `secrets.*` / `*.pem`:

1. Read `<SKILL_DIR>/secure-code-standards/SKILL.md` first, every time, even for small changes.
2. Before touching sensitive material, write one `SENSITIVE:` line in your plan (kind and location, never the value) and follow the Secret Handling Protocol (§2).
3. Secrets are supplied at runtime from outside the artifact (file path, env, stdin, secret manager). NEVER embed them (`go:embed`, `COPY`, `include_bytes!`), NEVER use them as flag/config defaults, NEVER put them on a command line, in `-ldflags`, in logs, in tests, in docs, or in your replies.
4. Missing secret = clear, secret-free error. No fallback literal.
5. Run `bash <SKILL_DIR>/secure-code-standards/scripts/secret-scan.sh` (add `--literal-file <secret file>` and `--artifact <binary|image tar>` when a secret file exists or anything was built) and quote its `SECRET-SCAN SUMMARY` block verbatim.
6. End with the SECURITY CHANGE REPORT from SKILL.md §8. If a secret was ever exposed, say so and tell the user to rotate it.
7. Never weaken the scanner, `.gitignore` rules, redaction, tests or this skill to make a finding go away.

Replace `<SKILL_DIR>` with the real install path. Pair with `go-engineering-standards` for Go work.
