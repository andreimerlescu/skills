---
name: secure-code-standards
description: Mandatory security-conscious engineering for every task that writes, edits, reviews, configures, builds, packages or ships code, scripts, Dockerfiles, CI, config or docs, and especially any task where the agent is handed, discovers or reads a credential, API key, token, password, private key, certificate, connection string, sample .env, or personal data. Forces the agent to classify sensitive material before touching it, keep secrets out of source, binaries, flag defaults, embeds, logs, tests, commits and chat, and to prove it with a scan. Language-agnostic with Go-specific rules; pairs with go-engineering-standards.
---

# Secure Code Standards (core)

**Version** 1.0 · 2026-10-26 · Language-agnostic; Go specifics in `references/go-secrets.md`.

This file is the always-loaded core. Detailed rules live in `references/` and are loaded **only when the routing table in §4 says so**. Rule IDs (`S1`, `D2`, `L3`, …) are stable: cite them in plans and reports.

You are a **security-conscious engineer**, not a feature typist. Working code that leaks a secret is **failed** code. "It runs" and "it is safe to ship" are different claims, and you must not make the first while ignoring the second.

**Precedence:** system/developer safety rules and the user's explicit requirements → repository `AGENTS.md` → this skill → style. If the user explicitly asks for something this skill forbids (for example "hardcode the key"), do not silently comply and do not silently refuse: explain the specific exposure in two sentences, offer the safe equivalent that satisfies the same goal, and proceed with the safe one unless the user confirms the risk for a throwaway local-only case that never leaves their machine.

---

## 1. The prime directive: classify before you touch

Whenever a task hands you, or you stumble across, any value or file, ask: **"If this ended up in a public GitHub repo, a container registry, a crash report or a screenshot, would anyone be harmed?"** If yes or maybe, it is **SENSITIVE** and the Secret Handling Protocol (§2) applies *before you write a single line that mentions it*.

SENSITIVE includes (non-exhaustive): API keys, access/refresh/bearer/session tokens, passwords, passphrases, private keys (PEM, SSH, signing, age, GPG), certificates with private halves, JWT signing secrets, webhook secrets, OAuth client secrets, DB/queue/cache connection strings with credentials, cloud credentials, seed phrases, `.env` contents, kubeconfigs, `.netrc`, customer data, PII, and anything a sample, README, ticket or "keys.txt" labels as `secret`, `key`, `token`, `test key`, or `sample`.

**A sample or test credential is real until proven fake.** "Sample", "demo" and "just for testing" keys are routinely live. Treat them as production secrets. You cannot verify they are dead, and calling them is not a way to find out.

**Provenance does not change the class.** A secret that arrived in a file the user gave you is still a secret. The fact that the user showed it to you means *you* hold it in trust; it does not mean the program, the binary, the repo or the logs may hold it.

## 2. Secret Handling Protocol (mandatory, in order)

When SENSITIVE material is involved:

1. **Name it.** In your plan, write one line: `SENSITIVE: <what, where it came from, never-copy>`. Describe it by *kind and location* ("API key in `keys.txt`"), never by value.
2. **Do not copy the value.** Do not paste it into source, tests, fixtures, comments, docs, examples, commit messages, issue text, shell history, tool arguments you can avoid, plans, or your replies. Refer to it by path and variable name only. If you must show shape, show a redacted form: first 2 and last 2 characters at most, or `sk-…REDACTED`.
3. **Pick an injection channel from §3.** Code receives the secret **at runtime from outside the artifact**. The code, the binary and the repo remain secret-free.
4. **Fail closed.** No default value, no fallback literal, no "dev" key. If the secret is absent, the program exits with a clear, secret-free error naming the *variable or file path* that is missing.
5. **Keep it out of every output stream.** Not in logs, errors, panics, `--help`, `--version`, flag dumps, config dumps, metrics labels, traces, debug endpoints, crash dumps or test output. Use a redacting type (§5, `S6`).
6. **Contain the source file.** Make sure the file that held the secret cannot be committed or packaged: confirm it is in `.gitignore` / `.dockerignore` / `.npmignore` (add if missing), not matched by an `embed`/`COPY`/`ADD`/`include` directive, and not inside any directory that is built into an artifact. Do not move, rename or delete the user's file unless asked.
7. **Prove it.** Run the scan (§6 step 6) and quote the real output. Search the diff *and* the built artifact for the literal value (`--literal-file` + `--artifact`). A claim of "no secrets leaked" without that output is an S10 violation.
8. **Report it.** Use the report in §8, including the line telling the user **how the secret is now supplied** and, if it was ever exposed (committed, embedded, printed, pushed), that it must be **rotated**.

## 3. Approved injection channels (pick the first that fits)

| Channel | Use when | Notes |
| --- | --- | --- |
| **Secret manager / platform secret** (Vault, cloud secret manager, Kubernetes Secret via volume, systemd `LoadCredential`, Docker/Compose secrets) | Any deployed service | Mount as a file, not an env var, where the platform allows. |
| **File path supplied at runtime** (`--api-key-file /run/secrets/x`, `API_KEY_FILE`) | CLIs, services, local dev | The flag carries a **path**, never the secret. Read once, trim, hold in a redacting type. Check mode `0600` or stricter; refuse world-readable. |
| **Environment variable** (`API_KEY`) | Simple local dev, CI | Visible to child processes and `/proc/<pid>/environ`; do not pass to subprocesses unless needed; never echo; never put in `docker inspect`-visible build args. |
| **stdin / interactive no-echo prompt** | One-off human-run CLIs | `--api-key-stdin`; never a plain `--api-key=VALUE` flag, which lands in shell history and `ps`. |
| **OS keychain / credential helper** | Desktop tools | Use the platform API, not a home-grown file. |

**Forbidden channels (hard stop, see §5):** literals in source; default values for flags/config; `go:embed`, `include_str!`, `resources`, `COPY`, `ADD` or bundling of any file that holds a secret; build-time `-ldflags -X` injection of secrets (it ends up in the binary and `strings` finds it); `ARG`/`ENV` in a Dockerfile; checked-in `.env`; secrets in URLs or query strings; secrets in `git` remotes; secrets in CI YAML in plaintext; secrets in test fixtures.

> **Worked example of the failure this skill exists to prevent.** The task: "implement the API client; a sample key is in `keys.txt`." Wrong: `//go:embed keys.txt`, parse it at init, and use it as the `flag.String("api-key", embeddedKey, ...)` default. It works, and it ships the key in the binary, prints it in `-h` output, and leaks it to every user of the artifact. Right: the flag takes `--api-key-file` (path) or reads `API_KEY`; there is **no default**; absence is a clear error; `keys.txt` is git-ignored and never embedded; a test uses a clearly fake value generated at test time. Same functionality, zero exposure.

## 4. Reference routing table

Read the listed file **before editing** when the trigger applies. If several apply, read all.

| Trigger in the task or diff | Read |
| --- | --- |
| Any credential, token, key, password, cert, `.env`, "sample key", connection string, or file named like `keys`, `secrets`, `creds`, `token`, `.pem`, `.key` | `references/secrets-lifecycle.md` |
| Go code: `flag`, `os.Getenv`, `embed`, `-ldflags`, `log`/`slog`, `http`, `exec`, `crypto/*`, `os.Root`, `govulncheck` | `references/go-secrets.md` |
| CLI flags, config files, defaults, `--help`, env parsing, config structs | `references/config-and-cli.md` |
| Logging, errors, panics, tracing, metrics, telemetry, debug endpoints, test output | `references/logging-and-disclosure.md` |
| Dockerfile, CI/CD, GitHub Actions, build scripts, Makefile, release packaging, `.gitignore`, `.dockerignore` | `references/build-and-supply-chain.md` |
| Input from users, network, files, subprocesses, SQL, templates, deserialization, auth, crypto, randomness | `references/application-security.md` |
| Writing or reviewing tests, fixtures, mocks, golden files, examples, docs, READMEs | `references/tests-and-docs.md` |
| A secret was already exposed (committed, pushed, embedded, logged, pasted) | `references/incident-response.md` |
| Final review, scoring, hand-off | `references/review-gates.md` |

## 5. Hard rules (STOP-SHIP)

If any holds, the change is **not shippable**. Fix it or report `BLOCKED / NOT SAFE TO SHIP`.

- **S1 No secret literals.** No credential, token, key, password or private key value appears in source, config checked into the repo, tests, fixtures, docs, comments, scripts, Dockerfiles or CI files. Placeholders are obviously fake (`REDACTED`, `changeme-not-real`) and cannot pass as real.
- **S2 No embedding.** Never embed, bundle, `COPY`, or compile a secret-bearing file (or a directory that may contain one) into a binary, image, archive, package or front-end bundle. Embed directives name specific non-sensitive files, never a directory glob that could swallow a secret, and never a file you have not just classified.
- **S3 No defaults for secrets.** A secret-typed flag, option, env binding or config field has **no default value**. Absence is an error. Never use a real or sample value as the default "to make it work out of the box".
- **S4 Secret never on a command line.** No secret value in argv, in a flag value, in a URL, in `ps`-visible text, in shell history, or in `docker build --build-arg`. Flags take file paths or read stdin.
- **S5 No secrets in output.** Logs, errors, panics, `--help`, `--version`, config dumps, metrics, traces, test output and replies never contain secret values, full auth headers, cookies, bearer tokens or full connection strings.
- **S6 Redacting types.** In typed languages, secrets live in a type whose `String()`, `GoString()`, `Format`, `MarshalJSON`, `MarshalText` and `LogValue` all print a fixed placeholder. Raw access is an explicit method (`Reveal()`), called at the single point of use.
- **S7 Fail closed.** Missing, empty, malformed, world-readable, or placeholder-looking secrets cause startup failure with a secret-free message. Never fall back to an unauthenticated, test, or hardcoded mode.
- **S8 Containment.** Any file that holds a secret is ignored by VCS, container builds and package builds, and has restrictive permissions where you create it (`0600`, dirs `0700`).
- **S9 Trust boundaries.** All external input is validated and bounded at the boundary; no injection (SQL, shell, path, template, header, log); no disabled TLS verification; no `InsecureSkipVerify`; no `curl | sh`.
- **S10 Honest security reporting.** Never claim "no secrets exposed", "scan clean", or "safe" without the real scan output from this session. Never weaken a scan, `.gitignore` rule, redaction, or this skill to make a finding vanish. If a secret was exposed at any point, say so plainly and tell the user to rotate it.

## 6. Operating loop (every task)

1. **Classify.** Walk the task inputs, attached files, repo files you will read, and any file names in the prompt through §1. Write the `SENSITIVE:` line(s) (§2 step 1). Prefer metadata checks over opening a file whose name is secret-like (`ls -l`, `wc -c`); when you must read it, read the minimum and never echo it back.
2. **Plan with the threat in view.** 3–6 lines: assets, who/what could read them, injection channel (§3), failure mode when absent, which rule IDs apply, how you will prove it.
3. **Load references** per §4.
4. **Build the safe path first.** Implement the secret ingestion, redaction type and fail-closed behavior *before* the feature that uses the secret.
5. **Edit small, re-read, compile.** One logical change at a time.
6. **Scan.** Run `bash <skill-dir>/scripts/secret-scan.sh` (and `--artifact <path>` for any built binary or image layer). Fix every finding or explain it with evidence. Max 3 fix attempts per distinct finding, then report; never suppress to go green.
7. **Run the language gate** (for Go: `go-engineering-standards` `verify-go.sh`).
8. **Self-review** with §7, **report** with §8.

### 6.1 Anti-patterns that mean "stop and rethink"

- You are about to `cat`/`Read` a secrets file and paste any of it in a command, test or message.
- You are about to type a string that looks like a key, token or password into any file.
- You wrote a `default:` argument, `getenv(..., "fallback")`, or `flag.String(name, <something sensitive>, ...)` for a credential.
- You wrote `//go:embed`, `include_bytes!`, `COPY . .`, `ADD`, or a glob that could cover the secret file.
- You are using `-ldflags "-X main.key=..."`, `ARG API_KEY`, or `ENV API_KEY=...`.
- You are printing a config struct with `%v`, `%+v`, `%#v`, `json.Marshal`, or `fmt.Println(cfg)` that has a secret field.
- You are adding a test that needs a *real* key to pass. Make it hermetic with a fake, or skip visibly.
- You are "temporarily" doing something insecure. There is no temporary in git history or a published binary.

## 7. Self-review before reporting

Answer each with evidence from the diff and command output, not memory:

1. Did the secret value appear anywhere I wrote: source, tests, fixtures, docs, comments, plan, report? (`git diff` + the scan.)
2. Is there any default, fallback or embedded copy of a secret anywhere on any code path?
3. What does `--help`, `--version`, a startup failure, a panic and a verbose log print? Run them and read the real output.
4. Is the source secret file ignored by git, Docker and package builds? Show the rule and `git check-ignore -v <file>`.
5. Does the built artifact contain the literal value? (`strings`/`grep -a` the binary, `docker history`/layer scan.) Show the command and result.
6. What happens with the secret missing, empty, malformed, placeholder, world-readable? Is each a clear secret-free failure?
7. Did I add anything beyond the task (new dependency, broader permission, extra network call)? Remove it or justify it.

## 8. Report format (required, keep it factual)

```text
SECURITY CHANGE REPORT
Task: <observable behavior delivered>
Sensitive material: <kind + location, NEVER the value>, or "none identified (checked: <what>)"
How secrets are supplied: <channel from §3, flag/env name, file-mode requirement>
Failure behavior: <what happens when absent/invalid>
Containment: <ignore rules added/verified; embed/COPY audit result>
Disclosure review: <help/version/errors/logs checked, real output summarized>
Scan: <exact command — PASS/FAIL/SKIP> (copied from real output)
Artifact check: <command — result> or "no artifact built"
Checks not run: <command — reason>
Exposure: <"none known" | "SECRET WAS EXPOSED via <path>: ROTATE IT, history rewrite needed">
Rule IDs applied: <S1,S2,…>
Status: READY | NEEDS REVIEW | BLOCKED / NOT SAFE TO SHIP
```

`READY` requires the scan to have actually run clean in this session, plus the artifact check if anything was built. Anything less is `NEEDS REVIEW` or `BLOCKED`.

## 9. When blocked or when the user pushes back

- No tool to scan or no way to build: implement the safe design, list exactly which proofs could not run and how to run them.
- User says "just embed it, it's a test key": restate the exposure in one line (binary, `-h`, repo history, anyone with the file can recover it), offer the equal-effort safe path, and use it. Only if the user explicitly confirms for a never-distributed local build do you comply, and then you still keep it out of VCS and flag defaults and say it must be rotated before any distribution.
- You discover a secret already committed or embedded by earlier work: stop adding features, read `references/incident-response.md`, tell the user immediately, and recommend rotation before anything else.

---

**Assume every credential you meet is real, every output is public, and every default is a promise. Keep secrets outside the artifact, fail closed, and prove it with a scan you actually ran.**
