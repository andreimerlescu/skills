# Testing: proof of behavior

Load when writing or changing any `_test.go` file, fuzz target, benchmark, or golden file. Rules `T1`–`T4` in SKILL.md are the summary.

A passing test means something only if it can fail when the behavior breaks.

## 1. Pick the right layer

| Layer | Proves | Mechanism |
| --- | --- | --- |
| Unit | inputs, outputs, edge cases, error semantics | `testing.T`, table tests |
| Component | real code with nearby real dependencies | `httptest`, `t.TempDir()`, test DB |
| Integration | real protocol/persistence behavior | opt-in via env; visible skip if unavailable |
| Concurrency | race freedom, cancellation, close, liveness | barriers, `synctest`, `-race`, `-count` |
| Fuzz | robustness and invariants on hostile input | `FuzzXxx` + seed corpus |
| Benchmark | allocation, latency, throughput vs baseline | `b.Loop`, `-benchmem` |
| Regression | a known bug fails before the fix, passes after | smallest reproducer |

A unit test with a mock does not answer questions about protocol, persistence, cancellation, or wiring. Coverage percentage is not proof.

## 2. Baseline quality rules

- Use the standard `testing` package unless the repo already has approved helpers.
- Name the behavior: `TestStore_Get_NotFound`, `TestPool_CancelWhileBlocked`.
- Table tests when cases share setup and assertion shape; not as a ritual.
- Failure messages: function, input, **got**, then **want**: `t.Errorf("Parse(%q) = %v, want %v", in, got, want)`.
- `t.Helper()` in helpers. `t.Cleanup()` for teardown. `t.TempDir()` for files.
- `t.Context()` (1.24+) is cancelled just **before** cleanup functions run; use `t.Cleanup` to wait for workers to exit.
- `t.Setenv` and `t.Chdir` cannot be used in parallel tests or under a parallel parent.
- `t.Parallel()` only when state is truly isolated.
- Compare semantics: `errors.Is`, structured fields, `cmp`-style projections. Never compare error strings (and JSON error text changed in Go 1.27).
- Assert that unintended effects did **not** happen (no extra writes, no leaked goroutines, no partial state).
- `T.ArtifactDir` (1.26+) for test output files you want to keep with `go test -artifacts`.
- Golden files: `-update` is a manual, reviewed mode, never on in CI.
- Prefer black-box `package foo_test` for public contracts; same-package tests only for internal invariants.
- Do not export production symbols just for tests. Inject a clock, reader, transport, or small interface instead.

## 3. Table-driven example

```go
func TestNormalizeID(t *testing.T) {
	tests := []struct {
		name    string
		in      string
		want    string
		wantErr error
	}{
		{name: "trims whitespace", in: " a-1 ", want: "a-1"},
		{name: "rejects empty", in: "  ", wantErr: ErrEmptyID},
		{name: "preserves case", in: "AbC", want: "AbC"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := NormalizeID(tt.in)
			if !errors.Is(err, tt.wantErr) {
				t.Fatalf("NormalizeID(%q) error = %v, want %v", tt.in, err, tt.wantErr)
			}
			if err == nil && got != tt.want {
				t.Errorf("NormalizeID(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}
```

`NormalizeID` and `ErrEmptyID` stand for the real function under test. Never write a parallel "test version" of the function. Add cases from the actual contract (Unicode, length limits, invalid encodings).

## 4. Concurrency tests

For each concurrent feature, cover what applies:

1. Zero/one goroutine case.
2. Many readers, many writers, mixed.
3. A real overlap window forced with a start barrier, not hoped for.
4. Cancellation before start, while blocked on send/receive/I/O, and after completion.
5. Shutdown with work pending; double shutdown if documented idempotent.
6. Consumer exits early → producers unblock and are joined.
7. Ownership hand-off: a test that would detect sender mutation after send.
8. Slow consumer, full queue, error propagation.
9. No goroutine growth over repeated start/stop cycles.
10. Ordering and dedup properties the callers rely on.

```go
func TestCounter_ConcurrentIncrement(t *testing.T) {
	c := NewCounter()
	const workers, perWorker = 24, 100

	start := make(chan struct{})
	var wg sync.WaitGroup
	for range workers {
		wg.Go(func() {
			<-start
			for range perWorker {
				c.Increment("k")
			}
		})
	}
	close(start) // release all workers together
	wg.Wait()

	if got, want := c.Snapshot()["k"], uint64(workers*perWorker); got != want {
		t.Fatalf("count = %d, want %d", got, want)
	}
}
```

This checks the logical invariant; `-race` separately checks for observed races. Mutation check (T1): delete the `Lock` in `Increment` — this test should fail under `-race` and usually on the count.

## 5. `testing/synctest`

- `synctest.Test` (1.25+) runs a bubble with fake time; time advances only when every bubble goroutine is durably blocked. `synctest.Wait` waits for that state. `synctest.Sleep(d)` (1.27+) is `time.Sleep(d)` followed by `synctest.Wait()`.
- `httptest.NewTestServer` (1.27+) gives an in-memory network that works inside a bubble. Real sockets, disk and external processes do not obey fake time.
- Inside the bubble, do not call `t.Run`, `t.Parallel`, or `t.Deadline` on the bubble's `t`.
- Read `go doc testing/synctest` before first use in a repo.

```go
func TestWorker_StopsOnDeadline(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
		defer cancel()

		w := NewWorker()            // the real type under test
		done := make(chan error, 1)
		go func() { done <- w.Run(ctx) }()

		synctest.Sleep(4 * time.Second) // Go 1.27; on 1.25–1.26: time.Sleep + synctest.Wait
		select {
		case err := <-done:
			t.Fatalf("Run returned before its deadline: %v", err)
		default:
		}

		// Blocking here lets fake time advance to the deadline. If Run never
		// returns, synctest.Test reports a deadlock instead of hanging.
		if err := <-done; !errors.Is(err, context.DeadlineExceeded) {
			t.Fatalf("Run error = %v, want deadline exceeded", err)
		}
	})
}
```

The test drives the **production** `Run`, not a goroutine that only waits on `ctx.Done()`. A test whose body is just `<-ctx.Done()` proves the context package works, nothing else.

## 6. Test doubles vs slop (T4, R6)

- Never swap the implementation the user asked for with a mock in the code path under test.
- Never write `mock.Return("y")` then assert the result is `"y"` and call it a test.
- Integration/E2E tests do not silently stub network, DB, filesystem, crypto or synchronization.
- No no-op methods to satisfy an interface; write truthful minimal behavior and a failing test until done.
- Exercise public wiring (constructors, handlers, real storage), not only private helpers.
- Unavailable dependency → `t.Skipf("POSTGRES_URL not set: integration test skipped")`. Visible skip, never a pass.

## 7. Fuzzing

Fuzz parsers, decoders, escapers, validators, protocol state machines. Assert invariants, not only "no panic".

```go
func FuzzRoundTrip(f *testing.F) {
	for _, seed := range [][]byte{[]byte("hello"), {}, {0, 255, 1}} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, in []byte) {
		enc, err := Encode(in)
		if err != nil {
			t.Fatalf("Encode(%x): %v", in, err) // valid only if Encode accepts all inputs
		}
		dec, err := Decode(enc)
		if err != nil {
			t.Fatalf("Decode after Encode: %v", err)
		}
		if !bytes.Equal(dec, in) {
			t.Fatalf("round trip: got %x, want %x", dec, in)
		}
	})
}
```

For restricted input domains, assert the documented rejection instead of skipping. Bound sizes to avoid fuzzer-driven huge allocations. Keep crashers in `testdata/fuzz` and add a named regression test.

## 8. Benchmarks

```go
func BenchmarkLookup(b *testing.B) {
	s := buildFixture(b) // setup outside the measured loop
	b.ReportAllocs()
	for b.Loop() {
		_, _ = s.Lookup("hot-key")
	}
}
```

- `b.Loop` (1.24+) for new benchmarks; it keeps results live and (1.26+) no longer blocks inlining.
- Compare before/after with the same toolchain, hardware, `GOMAXPROCS`, flags and data. Use `-count` ≥ 6 and `benchstat` if available.
- Report what was measured. Never claim a speedup from a single run.

## 9. Infrastructure-facing tests

- HTTP: `httptest.NewServer`/`NewTLSServer` (or `NewTestServer` in synctest); assert method, headers, body limits, status handling, timeouts.
- Persistence: restart from a temp dir, truncated/corrupt records, concurrent writers, failure injection.
- Filesystem: atomic replace, permissions, symlinks, traversal (with `os.Root` where used), cleanup. An in-memory fake does not prove `fsync`/`rename` behavior.
- Network errors: refused, timeout, cancel, malformed body, truncated body, non-2xx.
- Shutdown: no writes after close, waiters exit, errors still reported.
- Flaky tests are bugs. Quarantine only with an issue, an owner and visibility. Never "fix" with a longer sleep.

## 10. Commands

```bash
go test ./...
go test -race ./...
go test -race -run 'TestCounter|TestWorker' -count=50 ./internal/...   # targeted stress
go test -shuffle=on -count=3 ./...                                     # order dependence
go test -covermode=atomic -coverprofile="$TMPDIR/cover.out" ./... && go tool cover -func="$TMPDIR/cover.out"
go test -run '^$' -bench '^BenchmarkLookup$' -benchmem -count=6 ./internal/store
go test -run '^$' -fuzz '^FuzzRoundTrip$' -fuzztime=30s ./internal/codec
```

Replace names with real ones from the repo. Do not commit coverage files. `go test ./...` does not run long fuzzing, E2E, or stress lanes; do not report those as run.
