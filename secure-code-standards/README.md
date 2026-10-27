# secure-code-standards — operator notes

![Unique](https://counthis.app/github?repository=andreimerlescu/skills&label=Unique) ![Visitors](https://counthis.app/g/qyjy5vwjtjgbjfzy)

This README is for the humans who install and run the skill. The model reads `SKILL.md`; it does not need this file.

## What it fixes

Coding agents optimize for "it runs". Given a sample API key in a text file, an unaided agent will happily `//go:embed` the file and use the key as a flag default. It works, and it ships the key inside the binary, prints it in `-h`, and leaks it to everyone who receives the artifact. This skill gives the agent the instincts of a security-conscious engineer: classify sensitive material **before** touching it, inject it at runtime from outside the artifact, fail closed, redact by type, contain the source file, and **prove** all of that with a scan whose real output goes in the report.

## Layout

```text
secure-code-standards/
├── SKILL.md                    # always-loaded core: prime directive, protocol, channels, S1–S10, loop, report
├── references/                 # loaded on demand per the routing table
│   ├── secrets-lifecycle.md    # recognizing, reading, designing, rotating secrets
│   ├── go-secrets.md           # go:embed / flag defaults / ldflags traps, redacting Secret type, HTTP, files
│   ├── config-and-cli.md       # defaults, flags, config files, --help, env
│   ├── logging-and-disclosure.md
│   ├── build-and-supply-chain.md   # Docker, CI, ignore files, dependencies
│   ├── application-security.md # injection, SSRF, authn/z, crypto, DoS
│   ├── tests-and-docs.md       # hermetic tests, fixtures, docs, commits
│   ├── incident-response.md    # a secret has been exposed: rotate first
│   └── review-gates.md         # 13 gates + scoring
├── templates/go-secret/        # tested redacting Secret package (copy into a project)
├── scripts/secret-scan.sh      # the gate; never prints secret values
├── AGENTS.snippet.md           # paste into AGENTS.md so the skill always triggers
├── evals/scenarios.md          # prompts to verify the agent actually follows the skill
└── CHANGELOG.md
```

Install the whole directory: the core points at `references/`, `templates/` and `scripts/` by relative path.

## Enabling it

1. Copy the directory into your agent runtime's skills location.
2. Paste `AGENTS.snippet.md` into the highest relevant `AGENTS.md` and fix the path.
3. Run `evals/scenarios.md` S1, S2 and S5 and read the transcripts. It works when the agent writes a `SENSITIVE:` line, never copies the key, uses a path flag with an empty default, ignores `keys.txt`, and quotes a real `SECRET-SCAN SUMMARY`.

## The scanner

```bash
bash scripts/secret-scan.sh                                   # changed files (or whole tree if clean)
bash scripts/secret-scan.sh --all                             # everything tracked and unignored
bash scripts/secret-scan.sh --literal-file keys.txt --artifact ./app   # known secret vs tree, git history, binary
bash scripts/secret-scan.sh --artifact image.tar              # from `docker save`
```

- It reports **rule ID, file and line only**, never the matched value, so its output is safe to paste into a transcript.
- Rules: credential formats (`S1-PATTERN`), literal assignments (`S1-ASSIGN`), embeds and whole-context `COPY` (`S2-EMBED`), flag/config defaults (`S3-DEFAULT`), argv/ldflags/build-arg/query-string secrets (`S4-ARGV`), secret-named files tracked or unignored (`S8-TRACKED`), known literals in tree/history (`LITERAL`) and built artifacts (`ARTIFACT`).
- Exit codes: `0` clean, `1` findings, `2` usage, `3` nothing scanned.
- It is a heuristic gate. Clean output is not proof of absence. Run `gitleaks` or `trufflehog` as well if you have them; the summary tells you whether they are installed.
- The `--literal-file` search is the strongest check: it looks for the actual secret in source, git history, binaries and layers. Archive artifacts are searched as bytes, so compressed layers (`.tar.gz`) can hide a literal; extract or use an uncompressed `docker save` tar.
- Scanning a repository that *documents* secret handling (like this one) reports the intentional "WRONG" examples. That is the scanner working.
- Works with macOS's bash 3.2. Needs `grep`, `find`, `sort`, `git` (optional, for git-aware scope), `strings` (optional, for binaries).

## The Go template

`templates/go-secret/` is a drop-in `secret` package: a `Secret` type that prints `[REDACTED]` through `fmt` (every verb), `encoding/json`, `encoding.TextMarshaler` and `log/slog`; and `FromFile`, `FromEnv` and `Resolve` that fail closed, check permissions on the opened handle, bound the read, trim, and reject empty and placeholder values. Its tests prove the redaction and the failure modes. Run `go test ./...` inside a module after copying it.

## Keeping it current

Re-check the credential patterns in `scripts/secret-scan.sh` when providers change key formats. Re-check the Go claims against the current release notes (`embed` semantics, `os.Root`, `crypto/rand.Text`). Authoritative sources:

- Go `embed`: https://pkg.go.dev/embed · Go build info: https://pkg.go.dev/runtime/debug#ReadBuildInfo
- OWASP Cheat Sheet Series: https://cheatsheetseries.owasp.org (Secrets Management, Logging, Input Validation, SSRF, Password Storage)
- GitHub secret scanning patterns: https://docs.github.com/code-security/secret-scanning
- Docker build secrets: https://docs.docker.com/build/building/secrets/
- Go vulnerability management: https://go.dev/doc/security/vuln/

Repository conventions outrank this skill's style preferences, never its security rules.
