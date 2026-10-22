# Review, gates, scoring, and multi-agent hand-off

Load for final review, CI gate design, scoring a change, or delegating Go work to another agent.

## 1. Preflight (discovery)

```bash
pwd
go version
go env GOVERSION GOTOOLCHAIN GOOS GOARCH CGO_ENABLED GOFLAGS GOPROXY
find . -name go.mod -not -path '*/vendor/*'      # monorepos: one gate per module
find . -name AGENTS.md -not -path '*/vendor/*'
sed -n '1,40p' go.mod
git status --short 2>/dev/null || echo "not a git repo: diff-based checks unavailable"
```

## 2. Required evidence by change type

| Change | Evidence required |
| --- | --- |
| Any Go source | gofmt (changed files), build, vet, relevant tests; read the actual diff |
| Concurrency | + `go test -race`, overlap and cancellation tests, concurrency review card |
| Exported API | + docs, examples, all call sites build, compatibility notes |
| Network / I/O | + bad responses, timeouts, cancellation, size limits, cleanup tests |
| Persistence | + restart, truncated/partial writes, concurrent ops, failure cleanup |
| Dependencies / toolchain | + `go mod tidy` diff, `go mod verify`, `govulncheck` (or why not) |
| Performance claim | + before/after benchmarks under identical conditions |
| Security-sensitive | + threat and secret-handling review, vulnerability scan |
| Generated code | + regenerate with pinned tools; deterministic diff |

One `go test ./...` run is not evidence for fuzzing, E2E, integration suites, migrations or stress lanes.

## 3. Diff red flags (investigate, do not ban blindly)

```text
make(map / map[..]..   concurrent writers or readers?
go func(               owner, stop trigger, join?
chan *T / chan Struct  reachable references and ownership?
sync.Map               why not map + Mutex?
atomic.*               single independent value? no mixed access?
sync.Pool              alias outlives Put?
context.Background()   genuine root?
time.Sleep(            test sync hack or unbounded retry?
select { default:      busy spin or silent drop?
_ = f()                material error dropped?
recover()              hiding defects?
log.Fatal / os.Exit    inside a library?
http.Get / DefaultClient / &http.Client{} per call   timeouts, reuse, limits?
http.ListenAndServe    timeouts and graceful shutdown?
io.ReadAll(            hard size limit?
exec.Command("sh","-c" interpolated input?
fmt.Sprintf( SQL       injection?
fmt.Sprintf("%s:%d"    use net.JoinHostPort
x := x in loops        obsolete since 1.22
TODO / FIXME / panic("TODO")   unfinished essential behavior?
return nil / return true stubs   R6
t.Skip / //nolint      silent coverage loss?
changed _test.go assertions next to failing code   R7 suspicion
godebug lines in go.mod   removed settings now break the build (1.27)
```

## 4. Scoring (0–4 per category)

Any non-N/A category below **3**, or any STOP-SHIP rule violated, blocks `READY`.

| Category | 0 | 2 | 4 |
| --- | --- | --- | --- |
| Correctness | stub / wrong | happy path works | invariants and failure paths proven |
| Concurrency | race, leak, unknown owner | partial sync | clear ownership, bounded lifecycle, adversarial tests |
| Errors | ignored | mostly surfaced | contextual, cleanup and partial semantics right |
| API / idioms | convoluted | serviceable | minimal, readable, stable |
| Tests | fake / self-confirming | unit happy path | regression, negative, integration, concurrency as needed |
| Security | obvious exposure | basic checks | bounded resources, trust boundaries, redaction, scans |
| Docs | wrong / missing | summaries | accurate contracts and operations notes |
| Performance | unsupported claims | microbenchmark only | representative before/after |
| Delivery integrity | false claims | incomplete reporting | exact evidence, honest blockers |

## 5. Independent verification

1. List the user-visible acceptance criteria.
2. Trace each from public entry point → real implementation → side effect / persisted state / returned value.
3. Confirm the tests drive that route, not a fake one.
4. Name the one-line mutation that would break the core invariant; confirm a test fails for it (actually apply it in a scratch copy when cheap, then revert).
5. Walk every error and shutdown edge, especially accepted-but-unfinished work.
6. Re-run checks; keep exact output and exit codes.
7. Security-critical or irreversible financial behavior requires human review per project governance.

## 6. Multi-agent hand-off

- Planner states acceptance criteria and ownership/resource invariants before delegating; delegated workers receive this skill's path and must return the SKILL.md §8 report.
- The implementer's own success claim is not evidence. A reviewer reads the real diff; a verifier re-runs the gate from the real repo.
- Nobody changes tests, the gate script, or this skill to reduce friction without independent review and a stated reason why the rule was wrong.
- Hand-off artifacts: skill path, changed files, reproduction steps, gate summary, open failures. Do not rely on chat memory.
- Stop cosmetic revision loops; distinguish real failures from style preferences.
