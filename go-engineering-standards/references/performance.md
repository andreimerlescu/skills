# Performance and resource budgets

Load when the task claims or targets a performance improvement, touches `sync.Pool`, `unsafe`, `GOMAXPROCS`, GC settings, or profiling.

## 1. Measure first

1. State a measurable target (p99 latency, throughput, allocs/op, RSS).
2. Reproduce a baseline on representative data and hardware.
3. Profile: CPU, heap, block, mutex (`pprof`); scheduler behavior (`go tool trace`); rare events (`runtime/trace.FlightRecorder`, 1.25+).
4. Fix the biggest cause with the simplest correct change: algorithm, I/O, batching, caching, contention — before micro-allocations.
5. Re-check race safety, liveness, memory and error handling.
6. Compare before/after under identical conditions (`-count` ≥ 6, `benchstat` if available). Drop changes inside the noise.

Report baseline commit, toolchain, CPU/arch, `GOMAXPROCS`, workload and variance. Never present a single run as a result.

## 2. Rules

- Stream and batch large inputs; never read unbounded data into memory.
- Cap goroutines and queue depth independently of CPU count.
- `RWMutex` vs `Mutex`, lock-free vs locked: decide by benchmark under real contention. Lock-free is not a synonym for fast.
- `sync.Pool` only with measured benefit and correct ownership hand-back.
- `unsafe` only with a documented need, benchmark evidence, review, and dedicated tests.
- Escape analysis (`go build -gcflags=-m=2`) when relevant, without sacrificing readability.
- Bound outgoing concurrency and HTTP connection pools to match downstream capacity.

## 3. Runtime facts that change old advice

- **Container-aware `GOMAXPROCS` (1.25+, Linux):** the default honors cgroup CPU limits and updates when they change. Remove ad-hoc `automaxprocs`-style code unless measured otherwise. Setting `GOMAXPROCS` manually disables this behavior.
- **Green Tea GC is the default (1.26+).** Re-baseline GC-heavy benchmarks after upgrading before tuning `GOGC`/`GOMEMLIMIT`.
- **Size-specialized small allocations (1.27)** make some <80-byte allocations cheaper and add ~60 KB to binaries.
- **`goroutineleak` profile (1.27 GA)** finds goroutines blocked on unreachable primitives. It misses leaks reachable from globals or live goroutines; keep lifecycle tests.
- Profiling endpoints expose request and credential data. Keep them private.
