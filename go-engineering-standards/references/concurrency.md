# Concurrency, ownership and aliasing

Load when the task or diff touches: `go`, `chan`, `select`, `sync.*`, `atomic.*`, `errgroup`, shared maps, caches, worker pools, pointer payloads, timers, or background loops. Rules `C1`–`C7` in SKILL.md are the summary; this file is the detail.

The goal is correctness under **every** interleaving, including cancellation and shutdown, not correctness in one test run.

## 1. Before adding any goroutine (C1)

Answer these in a comment or the plan. If you cannot, do not add the goroutine.

1. **Work** — what it does, and why the caller cannot do it synchronously.
2. **Start/limit** — who starts it, whether it spawns children, what caps the count.
3. **Data** — which inputs are copied, immutable, transferred, or synchronized.
4. **Stop** — what ends it on success, error, cancellation, peer shutdown, parent shutdown.
5. **Join** — who waits for it and who receives its error or panic.
6. **Blocking** — every channel op, lock wait, or I/O call that can block, and how each is unblocked.
7. **Backpressure** — what happens when producers outrun consumers; max queued memory.
8. **Ordering** — whether callers rely on FIFO, per-key order, or exactly-once effects.
9. **Test** — which test forces overlap, cancellation, and cleanup.

## 2. Ownership models (C2)

Every mutable object reachable from more than one goroutine uses exactly one:

1. **Immutable publication** — fully built, published through a synchronizing operation, never mutated again (including anything it points to).
2. **Exclusive hand-off** — one goroutine may touch it at a time; sending it transfers ownership; the sender keeps no alias it uses.
3. **Synchronized sharing** — one mutex guards every access, including compound operations and any reference returned to callers.
4. **Single-owner actor** — one goroutine owns the state; others send commands over a bounded channel and receive replies; nothing mutable escapes.
5. **Copy isolation** — the receiver gets a deep-enough copy to work independently.

Garbage collection prevents dangling pointers. It does not prevent races, lost updates, stale reads, or use-after-hand-off.

## 3. Values, pointers and channels (C3)

- A channel copies the element value. If the element is or contains a pointer, slice, map, interface holding those, or a closure, receiver and sender share memory.
- `chan T` is not automatically safer than `chan *T`. A struct with a `[]byte` field sent by value shares the backing array.
- Default to `chan T` with small, self-contained values. Use `chan *T` when there is a reason (large objects, buffer reuse) **and** write the contract next to the channel.

```go
// BAD: sender mutates after hand-off; receiver may read concurrently.
job := &Job{ID: "first"}
jobs <- job
job.ID = "changed"
```

```go
// GOOD: small value message, no shared references.
type JobMessage struct {
	ID       string
	Attempts int
}
```

```go
// Ownership contract: after a successful send, the caller must not read,
// write, reuse or recycle b until the consumer hands it back.
func handOff(ctx context.Context, out chan<- *Buffer, b *Buffer) error {
	select {
	case out <- b:
		return nil // ownership transferred
	case <-ctx.Done():
		return ctx.Err() // send did not happen; caller still owns b
	}
}
```

If both cases are ready, `select` picks either one. Decide the outcome from the return value, never from a later `ctx.Err()` check.

Review questions for every pointer-bearing payload: who allocates, who owns before and after the send, is it deeply immutable, are slices or maps aliased, who recycles it, what happens on cancel/timeout/retry, and what guarantees the consumer is done before reuse.

## 4. Copying is shallow

- `copy`, `slices.Clone`, `maps.Clone` and `append([]T(nil), s...)` copy elements only. Elements that are pointers, slices or maps still alias.
- `append` may write into the existing backing array when capacity allows. It is not a clone.
- `url.URL.Clone` and `url.Values.Clone` (Go 1.27) are deep copies; most other `Clone` helpers are shallow — check `go doc`.
- Treat `[]byte` from pools, network reads, `bufio.Scanner.Bytes`, drivers and parsers as **borrowed** until the API says you own it.

## 5. Memory model essentials

- A write in one goroutine and a read in another need a happens-before edge: channel send/receive, close observed by receive, `Unlock` → later `Lock`, `WaitGroup.Wait` after `Done`, `Once`, or atomics.
- Starting a goroutine synchronizes *into* it. Its completion does **not** synchronize back to the starter without a join.
- `time.Sleep` and scheduling never create happens-before edges.
- `go test -race` reports races only on executed paths. A clean run is evidence, not proof.

## 6. Primitive selection

| Problem | Start with | Notes |
| --- | --- | --- |
| Guard a struct or map invariant | `sync.Mutex` | Lock every access |
| Many readers, rare writes, measured contention | `sync.RWMutex` | No lock upgrade; benchmark first |
| One-time init | `sync.Once`, `sync.OnceValue(s)` | Decide whether errors are cached |
| Independent scalar flag/counter/pointer | `atomic.Bool`, `atomic.Int64`, `atomic.Pointer[T]` | Never for multi-field invariants |
| Join tasks that cannot fail or panic | `sync.WaitGroup.Go` (1.25+) | Caller must `Wait` |
| Join tasks with errors and cancellation | `errgroup.WithContext` + `SetLimit` | External module |
| Transfer work or ownership | `chan T` | Define close owner and capacity |
| Single-owner state machine | actor loop + command channel | Bounded queue, stop path |
| Specialized concurrent cache | `sync.Map` | Only for its documented workloads |
| Object reuse | `sync.Pool` | Items vanish at any GC; never a lifetime manager |
| Waiting on a predicate | `sync.Cond` (or channels) | `Wait` in a loop, under the lock |
| Cross-process coordination | DB transaction, file lock, lease with fencing | In-process locks do nothing across processes |

Never: spinlocks, `time.Sleep` as synchronization, atomic flags guarding multi-field state, mixing atomic and plain access to one variable.

## 7. Maps

- Concurrent **reads only** are safe after synchronized publication, if nothing writes. Any concurrent write (`m[k] = v`, `delete`, `clear`, `m[k]++`) with any other access is a race and may crash the process.
- Values that are pointers/slices/maps need their own protection even when the map structure is read-only.

```go
// Counter is safe for concurrent use. Construct with NewCounter.
type Counter struct {
	mu     sync.Mutex
	counts map[string]uint64 // guarded by mu
}

func NewCounter() *Counter {
	return &Counter{counts: make(map[string]uint64)}
}

func (c *Counter) Increment(key string) uint64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.counts[key]++
	return c.counts[key]
}

// Snapshot returns an independent copy the caller owns.
func (c *Counter) Snapshot() map[string]uint64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	return maps.Clone(c.counts) // values are scalars, so shallow is enough
}
```

Check-then-act must happen under one lock:

```go
// BAD: another goroutine can insert between the check and the store.
if _, ok := cache[key]; !ok {
	cache[key] = build()
}
```

For expensive builds, do not hold a global lock across I/O. Use per-key in-flight entries or `singleflight`, then re-check and publish under the lock. Decide whether failures are cached, how a single caller's cancellation affects shared work, and whether returned values must be copied.

Prefer `map` + `Mutex` over `sync.Map` unless profiling shows contention and the workload matches its documentation.

## 8. Mutex discipline (C4)

- Keep `mu` directly above the fields it guards; comment `// guarded by mu` or describe the invariant.
- Functions that require the lock already held end in `Locked` (`flushLocked`). Audit their callers.
- `defer mu.Unlock()` right after `Lock()` unless a measured hot path needs otherwise.
- No locks held during I/O, callbacks, channel sends/receives, or calls into unfamiliar code. Snapshot under the lock, act outside it.
- Document lock order when more than one lock can be held. Prefer one lock per small object.
- Never copy a used `Mutex`, `RWMutex`, `WaitGroup`, `Once`, `Cond`, atomic type, or a struct containing one. Use pointer receivers.
- `RWMutex`: readers still `RLock`. No upgrade from `RLock` to `Lock`; release, `Lock`, re-validate.

## 9. Channels (C5, C6)

- Sender closes. Receivers never close. With multiple senders, a coordinator closes after all senders join.
- Receive from a closed channel returns the zero value immediately; use `v, ok := <-ch` or `range`.
- Send on a closed channel panics. Design a single closer; do not `recover` around sends.
- A nil channel blocks forever. Use only as a deliberate `select` case disable.
- Use directional types in signatures: `chan<- T`, `<-chan T`.
- A buffer is a bounded queue, not a deadlock fix. Size it from throughput, burst and memory; never "make it bigger until tests pass".
- `select` has no priority. If work and `ctx.Done()` are both ready, either can win; re-check cancellation inside long loops if it matters.
- `select { default: }` in a loop is a busy spin. Block, or use a timer.
- Spawning a goroutine to make a send "non-blocking" just moves the leak.
- Say what a successful send means: accepted in memory, processed, or durably stored. They differ.

```go
func send(ctx context.Context, out chan<- Result, r Result) error {
	select {
	case out <- r:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
```

## 10. Goroutine lifecycle (R2)

Default shape: **start → cancel/close → join**. The starter is responsible for the stop and the join.

```go
var wg sync.WaitGroup
for _, task := range tasks {
	wg.Go(func() { // Go 1.25+. task is per-iteration; no copy needed.
		process(task) // must not panic; shared state must be synchronized
	})
}
wg.Wait()
```

Bounded, cancellable worker pool with error propagation:

```go
// ProcessAll runs process on every item with at most workers concurrent calls.
// It returns the first error; remaining work is cancelled. Items must be safe
// to copy (no unsynchronized shared references), process must honor ctx and be
// safe for concurrent calls, and the caller must not mutate items meanwhile.
func ProcessAll(ctx context.Context, items []Item, workers int,
	process func(context.Context, Item) error) error {
	if workers <= 0 {
		return errors.New("workers must be positive")
	}
	if process == nil {
		return errors.New("process must not be nil")
	}

	g, ctx := errgroup.WithContext(ctx)
	jobs := make(chan Item) // unbuffered: natural backpressure

	g.Go(func() error { // sole sender, sole closer
		defer close(jobs)
		for _, it := range items {
			select {
			case jobs <- it:
			case <-ctx.Done():
				return ctx.Err()
			}
		}
		return nil
	})

	for range workers {
		g.Go(func() error {
			for it := range jobs { // ends when the producer closes jobs
				if err := process(ctx, it); err != nil {
					return err
				}
			}
			return nil
		})
	}
	return g.Wait()
}
```

Why `range jobs` is safe here: on error the context cancels, the producer stops and closes `jobs`, and every worker drains out. Workers do not need their own `ctx.Done()` case because they never block on anything except `jobs`, which is always closed. `g.Wait` returns the first error; which error wins under simultaneous failures is not deterministic. This is a finite batch helper, **not** a durable job queue.

Rules:
- `wg.Go` requires a function that does not panic. Use `errgroup` when errors must propagate.
- `errgroup.WithContext` cancels its context on the first error **or when `Wait` returns**. Never reuse that context after `Wait`.
- Call `SetLimit` before starting tasks; never while tasks are running.
- A `WaitGroup` carries no errors. Collect them under a mutex, through a coordinated results channel, or use `errgroup`.
- Never `go func(){...}()` per request or message without a hard cap.
- Work that outlives a request uses a **service-owned** context with its own lifetime, not the request context and not a fresh `context.Background()` inside the handler.

## 11. Context (C7)

- `ctx` is the first parameter; forward it to every downstream call. Not stored in structs by default.
- Every `WithCancel`/`WithTimeout`/`WithDeadline` gets `defer cancel()` in the same scope (or a per-iteration helper inside loops).
- Context keys are unexported typed values; context carries request-scoped metadata only, never required dependencies.
- Cancellation is a request. Blocking code must participate (`select` on `Done`, deadlines on I/O).
- `context.WithoutCancel` drops cancellation and deadline on purpose. Give the detached work a new timeout and a lifecycle owner.
- Surface `ctx.Err()` or `context.Cause(ctx)`; never turn cancellation into success. Do not retry on a cancelled context.

## 12. Publication, caches, atomics

- Reloadable config: build a complete new snapshot, then publish it (`atomic.Pointer[Config]` or under a lock). Never mutate the live one.
- `atomic.Pointer[T]` is safe only if everything reachable from `T` is immutable after `Store`.
- An atomic pointer to a mutable map does not make the map safe.
- `sync.Pool`: scrub sensitive data before `Put`; never keep aliases after `Put`; ensure all users are done first.
- Caches need bounded size, defined TTL/eviction, race-safe invalidation, and tests for concurrent miss/put/invalidate.

## 13. Deadlock, starvation, backpressure, ordering

- Review lock order, send/receive cycles, self-deadlock through re-entry, and callbacks into locked code.
- Pick an explicit backpressure policy: block with context, reject with a typed error, shed load, or persist. Never hide overload by spawning more goroutines.
- Budget goroutines, file descriptors, DB connections, idle HTTP connections, queue depth and memory together.
- Completion order is not input order. Reassemble by index when order matters.
- In-memory channels give at-most-once delivery at best. Exactly-once *effects* need idempotency keys and durable state.
- Serialize per key when same-key operations must not interleave logically, even if the map is locked.

## 14. Timers

- Stop timers and tickers you no longer need; never create a ticker per loop iteration.
- Tickers drop ticks when the receiver is slow. Do not count ticks as events.
- Timer and cancellation can become ready together in a `select`; define the acceptable outcome.

## 15. Decision playbooks

**Concurrent cache:** immutable-after-startup if possible → else `map` + `Mutex` with size/TTL/eviction → `RWMutex` or atomic snapshots only after measured contention → `sync.Map` only for its documented workloads → `singleflight` for expensive duplicate misses, with cancellation and value-ownership rules → test concurrent miss/put/invalidate/evict.

**Parallel API calls:** sequential if latency allows → reuse one `http.Client`, caller context, per-call and overall timeouts → cap parallelism (`SetLimit` or fixed pool) → value messages → define ordering, partial results, retries → test that one failure leaves no blocked goroutine.

**Background daemon:** owners rooted in `main` → few long-lived goroutines → actor owns maps if nothing escapes → service-owned context, bounded queues, join barrier → measurable durability → health/metrics → test crash-restart, full queues, cancel while blocked, shutdown order.

**Pointers in channels:** small self-contained value? use `chan T` → contains references? treat as shared → `chan *T` needs a written transfer/immutability/sync contract → pooled buffers need explicit return of ownership → if unsure, copy.

| Scenario | Prefer |
| --- | --- |
| Concurrent mutable counter map | `map` + `Mutex` |
| Lookup table built at startup | read-only map, safely published |
| Large immutable objects to workers | `chan *T` + immutable-publish contract |
| Reusable network buffers | `chan *Buffer` exclusive hand-off + explicit return |
| Message with `[]byte` field | deep copy, or exclusive transfer |
| Fan-out needing all results/errors | bounded `errgroup` |
| Cross-process state | DB transaction, lease + fencing |

## 16. Concurrency review card (copy into the report when relevant)

```text
[ ] Ownership of all reachable mutable data is documented (C2).
[ ] No unsynchronized read/write or write/write, including nested values (R1).
[ ] Every goroutine has an owner, stop trigger, and join (R2).
[ ] Every blocking send/receive/I/O has an exit path (C6).
[ ] Each channel has exactly one closer (C5).
[ ] Goroutines, queues, memory and retries are bounded (R3).
[ ] Cancellation propagates; behavior after cancel is defined (C7).
[ ] Multi-field invariants are guarded by one lock (C4).
[ ] Shutdown order prevents send-on-closed and use-after-pool-return.
[ ] Tests cover contention, cancellation, early exit, close (T3).
[ ] go test -race actually ran (paste result) — not treated as proof.
```
