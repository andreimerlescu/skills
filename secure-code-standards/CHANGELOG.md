# Changelog

## 1.0 — 2026-10-26

- Initial release.
- `SKILL.md` core: prime directive (classify before you touch), Secret Handling Protocol, approved/forbidden injection channels, stop-ship rules `S1`–`S10`, operating loop, anti-pattern tripwires, self-review and `SECURITY CHANGE REPORT`.
- Worked example of the founding failure: embedding a sample key file with `go:embed` and using it as a flag default, which ships the key in the binary and prints it in `-h`.
- References: secrets lifecycle, Go secrets/flags/embed/logging, config and CLI, logging and disclosure, build and supply chain, application security, tests and docs, incident response, review gates.
- `templates/go-secret/`: a tested redacting `Secret` type with `FromFile`/`FromEnv`/`Resolve` (fail-closed, permission checks, bounded read, placeholder rejection) and tests proving no `fmt`/`json`/`slog` path prints the value.
- `scripts/secret-scan.sh`: value-withholding scanner for credential formats, embed/COPY/default/argv/ldflags anti-patterns, tracked secret-named files, known-literal search in tree, git history and built artifacts.
- `AGENTS.snippet.md` and `evals/scenarios.md`.
