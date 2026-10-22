# Go versions, toolchains, dependencies

Load when: using a standard-library API you have not seen in this repo, using a feature newer than Go 1.21, or touching `go.mod`, `go.sum`, toolchains or dependencies.

Facts below were checked against the official release notes (go.dev/doc/go1.25, go1.26, go1.27, go.dev/doc/devel/release) on 2026-10-20. When in doubt, `go doc` on the installed toolchain wins over this file.

## 1. Version contract

- New modules targeting this skill declare `go 1.27.1`. Never lower an existing higher `go` line.
- The `go` line is a **minimum**. A `toolchain` line only suggests a toolchain for the main module.
- `go mod init` with Go 1.26+ writes the *previous* minor version by default (1.27 writes `go 1.26.0`). If the project standard is `go 1.27.1`, set it explicitly.
- Production and CI build with the latest patched release. **1.27.2 (2026-10-08) contains security fixes** to the `go` command, `crypto/tls`, `html/template`, `net/http`, `net/textproto` and `os`. Supported lines are 1.27.x and 1.26.x.
- `go test` in 1.27 runs the `stdversion` vet check by default: it flags standard-library symbols newer than the file's effective `go` version. Treat that as a hard error, not noise.
- Starting in 1.27, a `godebug` entry in `go.mod` or a `//go:debug` line that sets a **removed** setting (for example `asynctimerchan`) to its old value makes the build fail. Remove such lines; do not try to keep old behavior.
- Do not raise the `go` line in a library just to use a newer API. Raising it is an API decision for consumers; state it in the report.

## 2. API availability table (check here before writing from memory)

Use only APIs at or below the module's `go` line. Confirm uncertain ones with `go doc`.

| Since | API / feature | Notes |
| --- | --- | --- |
| 1.20 | `errors.Join`, `context.WithCancelCause`, `context.Cause` | |
| 1.21 | `slices`, `maps`, `cmp`, `min`/`max`/`clear` builtins, `sync.OnceFunc/OnceValue/OnceValues`, `context.WithoutCancel`, `context.AfterFunc`, `log/slog` | `slices.Clone`/`maps.Clone` are shallow |
| 1.22 | Per-iteration loop variables; `for range n`; `net/http.ServeMux` method and wildcard patterns | Do not add `x := x` copies |
| 1.23 | Range-over-func iterators, `iter.Seq`, `slices.Collect`, `maps.Keys` (returns an iterator) | Timer channels became unbuffered |
| 1.24 | `testing.T.Context`, `testing.B.Loop`, `os.Root` (directory-confined file access), `tool` directive in go.mod, `weak`, `runtime.AddCleanup` | `os.Root` is the right tool for path confinement |
| 1.25 | `sync.WaitGroup.Go`; `testing/synctest.Test` and `synctest.Wait` (GA); `T.Attr`, `T.Output`; `net/http.CrossOriginProtection`; `runtime/trace.FlightRecorder`; container-aware `GOMAXPROCS` on Linux; vet `waitgroup` and `hostport` analyzers | `os.Root` gained `ReadFile`, `WriteFile`, `MkdirAll`, `Rename`, `RemoveAll`, etc. |
| 1.26 | `new(expr)` (e.g. `Age: new(yearsSince(born))`); `errors.AsType[T]`; `T.ArtifactDir`; `testing/cryptotest.SetGlobalRandom`; `bytes.Buffer.Peek`; `slog.NewMultiHandler`; `os/signal.NotifyContext` cancels with a cause naming the signal; Green Tea GC default; rewritten `go fix` with modernizers | `crypto/*` ignore caller-supplied `random` readers |
| 1.27 | Generic methods (methods may declare type parameters); struct literal keys may be promoted-field selectors; `encoding/json/v2` and `encoding/json/jsontext` (GA); `testing/synctest.Sleep`; `httptest.NewTestServer` (in-memory network for synctest); `strings.CutLast`, `bytes.CutLast`; `uuid` package; `crypto/mldsa`; `url.URL.Clone`, `url.Values.Clone` (deep copies); `(*rand.Rand).N` generic method; `math/big.Int.Divide`; `net/http.Server.MaxHeaderValueCount`; `goroutineleak` profile (GA) | See §3 |

Not in the standard library (needs `go.mod` entry): `errgroup`, `singleflight`, `semaphore` (`golang.org/x/sync/...`), `govulncheck`, `staticcheck`.

## 3. Go 1.27 behavior changes that affect generated code

- **Generic methods:** interface methods still cannot declare type parameters, and a generic method never implements an interface method. Use them for type-specific helpers, not to build frameworks.
- **`encoding/json` is now backed by the v2 implementation.** Marshal/unmarshal behavior is preserved, but **error message text may differ**. Never assert on JSON error strings. `GOEXPERIMENT=nojsonv2` is a temporary opt-out; do not rely on it.
- **`encoding/json/v2` defaults are stricter:** invalid UTF-8 and duplicate object names are rejected. Migrating wire formats requires compatibility tests. Tag option `inline` was renamed `embed`; `format` and `unknown` tag options were removed before GA. Do not copy v2 examples written during the experiment.
- **HTTP/1 `Response.Body.Close` now drains unread content** up to a conservative limit to improve connection reuse. You still must `Close` every body. Manual drain loops are rarely needed now; if you keep one, bound it.
- **`go vet` printf check** now reports `fmt.Errorf("...: %w", p)` where `p` is `*E` and `E` itself implements `error`. Wrap the value, not a pointer to it, or `errors.Is`/`As` will miss it.
- **`gofmt` alignment fix:** formatting older files with 1.27 can produce small whitespace diffs. Format only files you changed.
- **`go fix` modernizers** (`atomictypes`, `embedlit`, `slicesbackward`, `unsafefuncs`, renamed `waitgroupgo`, …) can rewrite code. Run `go fix` only when the task is modernization, and review the diff.
- **`go mod tidy`** for `go 1.27` modules merges require blocks into at most two (direct, indirect). Expect `go.mod` diffs; they are fine.
- **`asynctimerchan` is removed.** Timer and ticker channels are always unbuffered.
- **Tracebacks include pprof goroutine labels.** Never put secrets or personal data in labels.
- **`go tool trace -http=:port`** now binds to localhost only.
- **Darwin requires macOS 13+.**
- `simd` / `simd/archsimd` are experimental (`GOEXPERIMENT=simd`). Do not use them in production code without an explicit request.

## 4. Outdated idioms to avoid (common in older training data)

| Avoid | Use instead |
| --- | --- |
| `ioutil.ReadAll`, `ioutil.ReadFile`, `ioutil.TempDir` | `io.ReadAll`, `os.ReadFile`, `os.MkdirTemp` / `t.TempDir()` |
| `rand.Seed(time.Now().UnixNano())` | `math/rand/v2` (auto-seeded); `crypto/rand` for secrets |
| `x := x` before closures in loops | nothing (Go 1.22+ semantics) |
| `for i := 0; i < b.N; i++` in new benchmarks | `for b.Loop()` |
| `wg.Add(1); go func(){ defer wg.Done() ... }()` | `wg.Go(func(){ ... })` when the func cannot panic |
| `sort.Slice` for simple cases | `slices.Sort`, `slices.SortFunc` |
| `interface{}` | `any` (identical; style only, do not churn existing code) |
| `go get` to install a binary | `go install pkg@version`, or the `tool` directive |
| `fmt.Sprintf("%s:%d", host, port)` for addresses | `net.JoinHostPort` |
| Hand-rolled `filepath.Clean` + prefix checks for confinement | `os.Root` / `os.OpenInRoot` |
| `errors.As(err, &target)` with a throwaway var | `errors.AsType[*MyErr](err)` when the module is ≥ 1.26 |

## 5. Modules and dependency hygiene

- Prefer the standard library. A new dependency needs a stated reason, a maintained source, a compatible license, and a pinned version.
- Add and remove with `go get` and `go mod tidy`, then review the diff. Run `go mod verify`. Never hand-delete `// indirect` lines or `go.sum` entries.
- No `replace` to local paths in anything published.
- Pin tools with the `tool` directive (Go 1.24+) or exact `@vX.Y.Z`; never `@latest` in CI.
- Use semantic import versioning (`/v2` and above).
- Keep cgo and platform code behind build tags with a matching build matrix.
- Run `govulncheck ./...` when dependencies or the toolchain change. It needs network access to the vulnerability database unless a local copy is configured; if it cannot run, say so.
