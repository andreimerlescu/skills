---
name: go-engineering-standards
description: >-
  Mandatory production-grade Go discipline for every task that writes, edits,
  reviews, tests, debugs, documents, benchmarks or operates Go code, go.mod,
  go.sum or Go CI. Enforces explicit ownership of shared state, race freedom,
  bounded goroutines, honest verification with real command output, and Go
  1.27.1+ compatibility. Tuned for local agents such as DeepSeek V4.
---

# Go Engineering Standards (core)

**Version** 2.0 · 2026-10-20 · **Go floor** `go 1.27.1` · **Build with** latest patched release (1.27.2 at time of writing).

This file is the always-loaded core. It is short on purpose. Detailed rules live in `references/` and are loaded **only when the routing table in §3 says so**. Rule IDs (`R1`, `C4`, `T2`, …) are stable: cite them in plans and reviews.

You are judged on **correct, verified behavior**, not on volume of code, abstraction, or green-looking output.

**Precedence:** system/developer safety rules and the user's requirements → repository `AGENTS.md` and documented project conventions → this skill → style preferences. If a local convention conflicts with a correctness or security rule here, say so and choose the safe option. This skill is a quality floor, not a license for unrelated rewrites.

---

## 1. Hard rules (STOP-SHIP)

If any of these holds, the change is **not production-ready**. Fix it, or report it as `BLOCKED / NOT PRODUCTION-READY` with the reason.

- **R1 Races.** No unsynchronized concurrent access to ordinary memory, including maps, slices, and anything reachable through pointers in channel payloads.
- **R2 Goroutines.** Every goroutine has an owner, a stop trigger (cancel / close / finish), and a join. Every blocking send, receive, lock wait or I/O call can be unblocked.
- **R3 Bounds.** No unbounded goroutines, queues, buffers, body reads, retries, caches or payload sizes on paths reachable by sustained or hostile load.
- **R4 Errors.** No ignored material errors (including `Close`, `Flush`, `Commit`, `rows.Err`). No `panic` for expected failures. No `recover` that hides defects. Libraries never call `os.Exit` or `log.Fatal`.
- **R5 Security.** No injection (SQL, shell, path), no secrets in logs, no disabled TLS verification, no trust of unvalidated input at a boundary.
- **R6 Real behavior.** No placeholder returns, no-op methods, `return nil` stubs, hard-coded success, or tests that only assert what a mock was told to return.
- **R7 Honest reporting.** Never claim a check ran or passed without its real output in this session. Never edit tests, gates, or this skill to make a failure disappear.

## 2. Operating loop (every task)

1. **Discover.** Read `go.mod` (the `go` line sets which APIs are legal), `AGENTS.md`, the code you will touch, its tests and call sites. Use `grep -n` and ranged reads; do not load whole large files.
2. **Plan.** For anything nontrivial, write 3–8 lines: acceptance criteria, which rule IDs apply, who owns mutable state, how goroutines stop, which tests will prove it.
3. **Load references** per §3. Only those that apply.
4. **Edit small.** One logical change at a time. Re-read the exact region before editing it. Never regenerate a whole file to change a few lines.
5. **Compile immediately.** After each edit batch: `gofmt -l <files you changed>` and `go build ./...`. Fix compile errors before writing more code.
6. **Verify.** From the module root run `<skill-dir>/scripts/verify-go.sh` (or the commands in §6). Concurrency changes require `-race`.
7. **Self-review** with §7, then **report** with §8.

### 2.1 Iteration budget (anti-loop)

- At most **3 fix attempts per distinct failure** (same test, same compile error, same race report). After the third, stop and report: the failure output, what you tried, your best hypothesis.
- Never "fix" a failure by weakening the assertion, adding `t.Skip`, raising a timeout to hide a hang, adding `time.Sleep`, deleting the test, or adding `//nolint`. Those are R7 violations.
- If a change grows past roughly 300 changed lines or 5 files without a passing build, stop and re-plan in smaller steps.

### 2.2 Context and tool-output discipline (local models)

- Keep the working set small: this core, the references the routing table selects, and ranged reads of the code you are changing. Load nothing "just in case".
- If a tool result is truncated, **re-run it narrower** (one package, `-run '^TestName$'`, `| tail -n 60`). Never infer or fill in the missing part of a log.
- Spend reasoning on invariants, ownership and failure paths. Do not spend it recalling whether an API exists; run `go doc` (§4).
- Reasoning text never goes into source files, comments, commit messages or reports. Comments state contracts and reasons, not your thought process.
- After any edit that a tool reports as failed or ambiguous, re-read the file region before trying again. Do not assume the edit landed.
- When a long session has drifted, re-read §1 and §2 of this file before the final report.

## 3. Reference routing table

Read the listed file **before editing** when the trigger applies. If several apply, read all of them. If none apply (a pure rename, a typo, a comment), the core is enough.

| Trigger in the task or diff | Read |
| --- | --- |
| `go`, `chan`, `select`, `sync.*`, `atomic.*`, `errgroup`, shared `map`, worker pools, caches, pointer payloads, timers, background loops | `references/concurrency.md` |
| Writing or changing any `_test.go`, fuzz targets, benchmarks, golden files | `references/testing.md` |
| Errors, `defer`/`Close`, retries, timeouts, config, graceful shutdown, `main` wiring | `references/errors-lifecycle.md` |
| HTTP clients/servers, files and paths, `database/sql`, JSON, subprocesses, auth, secrets, crypto, untrusted input | `references/boundaries-security.md` |
| New packages, exported API changes, naming, interfaces, generics, doc comments, README | `references/api-style-docs.md` |
| Any standard-library API you have not seen in this repo, any feature newer than Go 1.21, `go.mod`/toolchain/dependency changes | `references/go-versions.md` |
| Slices/maps aliasing, typed-nil errors, `io.Reader` contracts, `defer` in loops, equality, build tags | `references/traps.md` |
| Performance claims, profiling, `sync.Pool`, `unsafe`, GOMAXPROCS | `references/performance.md` |
| Final review, scoring, CI gates, multi-agent hand-off | `references/review-gates.md` |

## 4. Ground every API in the installed toolchain

Your training data may predate the Go version in this repository. **Do not write an API from memory when you are not certain it exists in the declared `go` version.** Check it locally; it costs one command:

```bash
go doc sync.WaitGroup.Go          # exists? exact signature?
go doc testing/synctest           # package docs and restrictions
go doc -ex strings.CutLast        # examples (Go 1.27+)
go doc golang.org/x/sync/errgroup.Group.SetLimit   # only if the module is in go.mod
go list -m all | grep -i <name>   # is this dependency actually required?
```

- If `go doc` cannot find a symbol, **it does not exist for you.** Do not invent it, and do not add a dependency to get it without stating why.
- APIs most often hallucinated or misdated are listed with their versions in `references/go-versions.md`.
- Never assume a CLI flag exists; check `go help <cmd>` or `go doc cmd/<tool>`.

## 5. Core engineering rules

These are the defaults. The references expand each one.

**Ownership and concurrency**
- **C1** Simple sequential code beats concurrent code. Add a goroutine only when you can answer: who starts it, what it owns, what stops it, who waits for it, what bounds it.
- **C2** Every mutable value shared across goroutines has exactly one documented policy: immutable after publication, exclusive hand-off, guarded by one mutex, owned by one actor goroutine, or copied.
- **C3** A channel copies the element value only. A struct sent by value that holds a slice, map, or pointer still shares that memory. `chan *T` is fine only with a written ownership contract.
- **C4** One mutex guards a whole invariant, including check-then-act sequences. Do not hold locks across I/O, callbacks, or channel operations.
- **C5** The sender closes a channel. With several senders, a coordinator closes after all senders are joined.
- **C6** Every blocking send and receive in code that can be cancelled sits in a `select` with `ctx.Done()`.
- **C7** `ctx context.Context` is the first parameter of cancellable work; pass it down; do not store it in structs by default; `context.Background()` only at real roots.

**Errors and resources**
- **E1** Return errors with context at boundaries: `fmt.Errorf("load account %q: %w", id, err)`. Match with `errors.Is`, `errors.As`, or `errors.AsType` (Go 1.26+), never by string.
- **E2** Close what you open, immediately after successful acquisition, and check close/flush/commit errors when they affect correctness.
- **E3** Log once at the operation boundary (handler, command, supervisor); lower layers return.
- **E4** Retries need idempotency, a bound, backoff with jitter, and cancellation.

**API and style**
- **A1** `gofmt` every edited file. MixedCaps. Initialisms `ID`, `URL`, `HTTP`. No `util`/`common`/`helpers` packages.
- **A2** Concrete types first. Small interfaces defined where consumed. No interface added only to enable mocking.
- **A3** Document concurrency safety, ownership of returned slices/maps, zero-value behavior, and error semantics on exported APIs. A doc comment that claims safety the code does not provide is R1.
- **A4** Do not change exported signatures, `go.mod` `go` line, or dependencies unless the task requires it; say so explicitly when you do.

**Tests**
- **T1** A test must be able to fail. For each critical path, name the one-line mutation (remove the lock, drop the error, skip the write) that the test would catch.
- **T2** No `time.Sleep` for synchronization in tests. Use channels/barriers, `testing/synctest`, or injected clocks.
- **T3** Test failure paths, cancellation and shutdown, not only the happy path.
- **T4** Mocks model contracts, including failures. Integration tests that cannot reach their dependency must `t.Skip` visibly with a reason, never pass silently.

## 6. Verification commands

Preferred: run the bundled gate and paste its summary block verbatim.

```bash
bash <skill-dir>/scripts/verify-go.sh            # from the module root
bash <skill-dir>/scripts/verify-go.sh --race     # required for concurrency changes
```

Manual equivalent, per module:

```bash
go version
gofmt -l <changed .go files>     # must print nothing
go build ./...
go vet ./...
go test ./...
go test -race ./...              # concurrency changes; report if unsupported on this platform
```

- **Go 1.27 `gofmt` changed column alignment slightly.** Running it over the whole tree can rewrite files you did not touch. Format and check **only files you changed** unless the task is a repo-wide reformat.
- `go test` already runs a vet subset (including `stdversion` in 1.27); `go vet ./...` is still a separate required step.
- Offline local setups: if module downloads fail, report it. Do not set `GOFLAGS=-mod=mod`, delete `go.sum` lines, or add `replace` directives to get a green build.

## 7. Self-review before reporting

Answer each with evidence from the diff, not from memory:

1. Does every new `go`, `chan`, `sync.*`, `atomic.*`, shared `map`, timer, `http.Client`, `io.ReadAll`, `exec.Command`, `context.Background()`, `_ =` assignment and `recover()` satisfy the relevant rule ID?
2. Trace each acceptance criterion from the public entry point to the real side effect. Does a test exercise that exact path?
3. What one-line mutation would break the main invariant? Would a test catch it?
4. What happens on cancellation, on timeout, on shutdown with work in flight, on the second `Close`?
5. Did I add anything not needed for the task (new abstraction, dependency, rename, reformat)? Remove it.

## 8. Report format (required, keep it factual)

```text
GO CHANGE REPORT
Task: <observable behavior delivered>
Files: <paths>
Go: go.mod <x.y.z> · toolchain used <go version output>
Behavior: <what the code now does; no marketing>
Ownership/concurrency: <owners, locks, channels, joins, bounds — or N/A>
Errors/cancellation/shutdown: <guarantees and limits>
Tests: <name — what it proves> (one line each)
Checks run: <exact command — PASS/FAIL/SKIP> (copied from real output)
Checks not run: <command — reason>
Risks/blockers: <remaining issues, or "none known">
Status: READY | NEEDS REVIEW | BLOCKED / NOT PRODUCTION-READY
```

`READY` requires: build, vet, tests (and `-race` when concurrency changed) actually ran and passed in this session. Anything less is `NEEDS REVIEW` or `BLOCKED`.

## 9. When blocked

Missing toolchain, network, credentials, services or hardware: implement what can be correct locally, write offline tests where meaningful, list exactly which checks could not run and how to run them, and never weaken a rule to work around the environment.

---

**Write boring, precise Go whose owners, invariants, cancellation, errors and tests are obvious. Prove it with commands you actually ran.**
