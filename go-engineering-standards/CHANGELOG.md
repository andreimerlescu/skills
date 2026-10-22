# Changelog

## 2.0 — 2026-10-20

### Structure
- Split the single ~15k-word file into a short always-loaded `SKILL.md` core plus nine on-demand `references/`, selected by a routing table. Local models with modest working context now load only what a task needs.
- Added stable rule IDs (`R1`–`R7`, `C1`–`C7`, `E1`–`E4`, `A1`–`A4`, `T1`–`T4`) so plans, reviews and reports can cite rules precisely.
- Moved the "Go traps" section, which sat after the closing contract in v1, into `references/traps.md`.

### Local-model behavior (DeepSeek V4 and similar)
- §4 "Ground every API": run `go doc` before using any API not already seen in the repo; if `go doc` can't find it, it doesn't exist.
- §2.1 iteration budget: at most three fix attempts per distinct failure, then report with evidence.
- §2.2 context and tool-output discipline: re-run narrower on truncated output, never infer missing log lines, keep reasoning out of code and reports, re-read after ambiguous edits.
- Report format made stricter: `READY` requires build, vet, tests (and `-race` for concurrency) to have actually run in-session.
- Added `scripts/verify-go.sh`, `AGENTS.snippet.md`, `evals/scenarios.md`, operator `README.md`.

### Go facts (verified against go.dev release notes, 2026-10-20)
- New `references/go-versions.md` with an API-availability table for 1.20–1.27 and a list of outdated idioms.
- Added 1.27 behavior changes v1 missed: `encoding/json` now runs on the v2 engine (error text may differ); `Response.Body.Close` drains automatically; vet's new `%w`-with-pointer check; `gofmt` alignment change (format only changed files); `go fix` modernizers; `go mod tidy` require-block merging; removed GODEBUG settings now fail builds; `httptest.NewTestServer`; `url.URL.Clone`; `strings.CutLast`; `uuid`; goroutine labels in tracebacks.
- Added relevant 1.24–1.26 items: `os.Root` for path confinement, `errors.AsType`, `new(expr)`, `T.ArtifactDir`, container-aware `GOMAXPROCS`, Green Tea GC, `http.CrossOriginProtection`, vet `hostport`/`waitgroup`.
- Corrected the toolchain note: supported lines are 1.27.x and 1.26.x; 1.27.2 lists the security-fixed packages.

### Code example fixes
- Worker pool: workers now `range` over the jobs channel (simpler, still correct on cancellation); removed the redundant `task := task` copy that v1 itself called obsolete.
- `FetchJSON`: trailing-data check uses `errors.Is(err, io.EOF)`; body limit is a parameter.
- Typed-nil example replaced with one that actually demonstrates the bug (v1's "correct" version always returned nil).
- `WriteFile` adds context to close errors; new complete `WriteFileAtomic` (temp file, sync, rename, directory sync) instead of prose only.
- synctest example now drives a production `Run` method and checks both "not early" and "returns at deadline", instead of testing that a context times out.
- Table test uses sentinel errors with `errors.Is` instead of a `wantErr bool`.
- Added a complete `main`/`run` graceful-shutdown example.
- Snapshot uses `maps.Clone`.
