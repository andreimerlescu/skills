# API design, style, and documentation

Load when creating packages, changing exported APIs, naming things, adding interfaces or generics, or writing doc comments and READMEs. Rules `A1`–`A4` in SKILL.md are the summary.

## 1. Formatting

- `gofmt` every edited file (Go 1.27 `gofmt` may re-align untouched files slightly; format only what you changed). `goimports` for imports if the repo uses it.
- Early returns; happy path unindented. Extract cohesive helpers, not one-line wrappers.
- Imports grouped: standard library, third-party, local module (follow repo tooling).
- No comment banners, no manual alignment, no line-length crusades.

## 2. Naming

| Element | Do | Avoid |
| --- | --- | --- |
| Package | short, lowercase, purpose: `cache`, `token` | `util`, `common`, `helpers`, `models`, `cacheManager` |
| Exported type | noun: `Client`, `Store`, `Result` | `IClient`, `BaseRepository`, `AbstractX` |
| Constructor | `New`, `NewClient`, `Open` | `CreateNewClientObject`; `queue.NewQueue` (stutter) |
| Method | verb or query: `Close`, `Get`, `Lookup` | `DoStuff`, `ProcessDataFunction` |
| Short-scope vars | `i`, `n`, `err`, `ctx`, `mu`, `wg`, `r`, `w` | `theContext` |
| Long-lived vars | `pendingRequests`, `retryDelay` | one letter across a long function |
| Initialisms | `HTTPClient`, `userID`, `parseURL` | `HttpClient`, `userId` |
| Booleans | `enabled`, `hasToken`, `shouldRetry` | `flag`, `status` |
| Constants | `MaxRetries`, `defaultTimeout` | `MAX_RETRIES` |
| Channels | what flows: `jobs`, `results`, `done` | `ch1` |
| Errors | `ErrNotFound`, `*ValidationError` | strings as identifiers |
| Tests | `TestParse_InvalidHeader` | `TestEverything` |

Receivers: 1–2 letters, consistent per type (`c *Client`), never `this`/`self`.

## 3. Types and variables

- `:=` for short locals; `var x T` when the zero value is meaningful or the type matters. Avoid shadowing `err`/`ctx` confusingly.
- Named results only for documentation or deferred error edits; no bare returns in long functions.
- Domain types (`type AccountID string`) where they prevent mix-ups; do not wrap every primitive.
- Make the zero value useful when natural; otherwise document that `New` is required.
- Do not pass pointers to slices, maps, funcs, interfaces, or small values without a semantic reason.
- Pointer receivers for mutable state, sync fields, or identity. A value receiver still shares a struct's slice/map contents.
- Go 1.26 `new(expr)` is fine for optional pointer fields: `Timeout: new(30 * time.Second)` — only if the module's `go` line is ≥ 1.26.
- No global mutable registries or singletons without justified lifecycle and synchronization. No broad `init()` side effects.

## 4. Packages and layout

```text
cmd/<app>/main.go    # config, wiring, lifecycle only
internal/<area>/     # application code
pkg/                 # only for intentionally public reusable code
```

- Package boundaries enforce invariants; folders are not architecture. Do not split a small feature into `domain/usecase/repository/adapter` layers without real complexity.
- No import cycles; dependencies flow toward smaller domain contracts.

## 5. Interfaces, embedding, generics (A2)

- Concrete types first. Define small interfaces **where consumed**. Reuse standard ones (`io.Reader`, `io.Writer`, `fs.FS`, `http.RoundTripper`).
- Constructors return concrete types. Providers export an interface only for genuine extension points.
- Embedding is composition: check promoted methods and JSON fields; forward explicitly when the contract must stay stable.
- Generics for repeated, type-safe algorithms/containers with proven benefit. Go 1.27 **generic methods** are allowed, but interface methods cannot have type parameters and generic methods cannot satisfy interface methods.
- Prefer generics over `any` + reflection when the type is known; `any` for real heterogeneity.

## 6. Encapsulation and compatibility (A4)

- Unexported fields until a consumer needs them.
- Document whether returned slices/maps/buffers are copies or live views; default to copies of internal state.
- Config structs for several related settings; functional options only when they clearly help and still validate.
- Before changing an exported API: find all call sites and implementations (`grep -rn`, `go build ./...`), check semver obligations, add migration notes.
- Do not leak implementation types; avoid exported constructors returning unexported types unless that is the package convention.

## 7. Doc comments (A3)

- Every exported identifier with non-obvious behavior gets a doc comment starting with its name, in full sentences. Package docs in `doc.go` for larger packages.
- Document what the signature cannot: valid inputs, zero value, errors returned, partial results, **concurrency safety**, **ownership of returned references**, nil handling, timeouts, shutdown obligations.
- Explain *why* for surprising choices and the invariant to preserve; do not narrate the code.
- `Example` functions with `// Output:` when deterministic; check rendering with `go doc` (1.27 `go doc -ex` lists examples).

```go
// Store keeps records indexed by ID.
//
// Store is safe for concurrent use. Get returns an independent copy; callers
// may modify it freely. Close rejects new writes and waits for accepted
// writes to finish; calling Close more than once returns ErrClosed.
type Store struct {
	mu      sync.Mutex
	records map[string]Record // guarded by mu
	closed  bool              // guarded by mu
}

// Get returns a copy of the record with the given id, or ErrNotFound.
// It returns ctx.Err() if ctx is done before the lookup completes.
func (s *Store) Get(ctx context.Context, id string) (Record, error)
```

A comment claiming safety the code does not provide is an R1 defect. If `Record` contains slices or maps, `Get` must deep-copy them or the comment must say otherwise.

Lock and actor comments sit next to the fields: which fields `mu` guards together, and for actors who sends, who closes, who waits, what happens on stop. Never `// goroutine for speed` without a bound and a reason.

## 8. README and design docs (non-trivial services)

Cover: what it guarantees and does not; supported Go/OS/arch; build and run commands with tool versions; configuration (precedence, units, secure defaults); API/CLI examples incl. failures; concurrency model (owners, bounds, ordering, retries); persistence and crash recovery; shutdown, health and readiness; test commands and required services; threat model for network-facing parts. Use short ADRs for irreversible decisions, including rejected alternatives.
