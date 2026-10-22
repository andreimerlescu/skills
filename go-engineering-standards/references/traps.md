# Go correctness traps

Load when code touches slices/maps aliasing, error interfaces, readers/writers, `defer` in loops, equality, timers, generated code, or build tags. These make plausible-looking code fail in production.

## 1. Interfaces and typed nil
- An interface is nil only if its dynamic type **and** value are nil. A nil `*E` returned as `error` is non-nil. Return literal `nil` on success; declare helpers as returning `error`. (Example in errors-lifecycle.md.)
- Comparing interfaces whose dynamic types are not comparable (slices, maps, funcs) panics at run time, including as map keys.

## 2. Slices
- `s[:n]` shares the backing array. `s[:n:n]` caps capacity so `append` reallocates, but still shares existing elements.
- `append` may write into a shared backing array. Never treat it as a copy.
- A slice of pointers copied with `slices.Clone` still points to the same objects.
- Returning an internal slice lets callers bypass your lock. Return a copy.
- nil vs empty slice: same `len`, different JSON (`null` vs `[]`). Decide the wire contract.

## 3. Maps
- Writing to a nil map panics; reading and `len` are fine. Initialize under the right synchronization.
- Iteration order is random. Sort keys for deterministic output, hashes, signatures, golden files.
- `maps.Keys` (1.23+) returns an iterator, not a slice: `slices.Sorted(maps.Keys(m))`.

## 4. Loops and closures
- Go 1.22+ gives each iteration its own variable. Do not add `x := x`. (`go fix` and linters remove them.)
- A per-iteration copy is still shallow: a captured struct's slices/maps are shared.
- `&s[i]` (element identity) and `&v` from `for _, v := range s` (a copy) are different objects.
- `for range n` (1.22+) is fine when it reads better.

## 5. `defer`
- Arguments are evaluated when `defer` runs, not at return.
- Defers run LIFO at function return, not at the end of a loop iteration. Use a helper per item for files, rows, locks, `cancel()`.
- `defer` cannot make it safe to close something a goroutine still uses.
- `panic`/`recover` is not error handling.

## 6. Readers and writers
- `Read` may return `n > 0` **and** a non-nil error, including `io.EOF`. Process the `n` bytes first.
- Short reads without EOF are normal. `io.ReadFull` only for fixed-size frames.
- Writes can be partial; use `io.Copy`, `io.WriteString`, or check `n`.
- `bufio.Writer` must be `Flush`ed; check its error.
- `bufio.Scanner`: check `Err()` after the loop; set `Buffer` for long tokens; `Bytes()` is overwritten by the next `Scan`.

## 7. Equality and serialization
- Slices, maps and funcs are not comparable (except to nil). Use `slices.Equal`, `maps.Equal`, or specific logic.
- `reflect.DeepEqual` treats nil and empty slices as different and compares unexported fields; compare the projection you actually care about.
- `time.Time` with `==` compares location and monotonic reading; use `Equal` for instants.
- JSON, gob and binary encodings have different compatibility guarantees; test against stored fixture bytes.

## 8. Copy-prohibited values
- Never copy after first use: `sync.Mutex`, `RWMutex`, `WaitGroup`, `Once`, `Cond`, `Pool`, atomic types, `strings.Builder`, or structs containing them. `go vet`'s `copylocks` catches many cases.
- `bytes.Buffer` is not safe for concurrent writes; its `Bytes()` aliases internal storage.
- `http.Client` and `sql.DB` are concurrency-safe; requests, responses, `Rows`, `Tx` and buffers generally are not.

## 9. Time
- `time.Since` and `Sub` on values from `time.Now` use the monotonic clock; Unix timestamp subtraction does not.
- Never hold a lock while waiting on a timer for another goroutine to make progress.
- Timer/ticker channels are unbuffered (synchronous): since Go 1.23 for modules declaring `go 1.23`+, and unconditionally in Go 1.27, which removed the `asynctimerchan` setting. Old `Stop`/drain workarounds are unnecessary.

## 10. Generated code and build constraints
- Generated files carry the `// Code generated ... DO NOT EDIT.` header and are reproduced from pinned tools; edit the source, not the output.
- `go build` never runs `//go:generate`. Review generator commands before running them.
- `//go:build` constraints must be tested for every supported combination. Never hide a broken package behind a tag.
- `//go:embed` only deliberate assets; check binary size; never embed secrets.
- Linter suppressions are narrow, justified, reviewed. Never disable `vet` or `-race` to get green CI.

## 11. Closures and function values (Go 1.27)
- The compiler may give different closures the same code pointer. Never compare function values via `reflect.Value.Pointer` for identity, and do not assert on closure symbol names in tests.
