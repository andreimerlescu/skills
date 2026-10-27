---
name: go-documentation-discipline
description: >-
  Mandatory Go documentation and code-comment discipline for DeepSeek V4 and
  other local coding agents. Produces useful GoDoc and IDE hovers, complete
  parameter and behavioral contracts, realistic usage examples, explanatory
  implementation comments, and verified repository-relative file:line usage
  references maintained as generated documentation.
compatibility: opencode
metadata:
  version: "1.0.0"
  scope: "all-go-projects"
  apply_when: "writing-reviewing-refactoring-debugging-or-generating-go"
  priority: "mandatory"
---

![Unique](https://counthis.app/github?repository=andreimerlescu/skills&label=Unique) ![Visitors](https://counthis.app/g/qyjy5vwjtjgbjfzy)

# Go Documentation Discipline

**Audience:** DeepSeek V4 (local coding agent), code-review subagents, and implementation agents.

**Activation:** Apply this skill **automatically to every Go task**, including
new features, bug fixes, migrations, code reviews that result in edits, tests,
generated scaffolds, and refactors. Do not wait to be asked to document code.
The project's higher-priority instructions remain authoritative; report a
conflict rather than silently discarding a requirement.

**Mission:** Make the repository explain itself to an engineer reading code in
VS Code, Zed, GoLand/JetBrains, a terminal, or rendered Go package docs. An
engineer should be able to inspect a function and learn what it promises, what
each input means, which edge cases matter, how to call it correctly, why its
non-obvious implementation decisions exist, and **where the repository uses
it**, without guessing.

**Non-negotiable:** Documentation is part of implementation, not an optional
polish step. A patch that compiles but leaves its affected documentation
missing, misleading, or stale is **not done**.

### Install in OpenCode / DeepSeek V4

Install this file as one of:

```text
<repository>/.opencode/skills/go-documentation-discipline/SKILL.md
<repository>/.agents/skills/go-documentation-discipline/SKILL.md
~/.config/opencode/skills/go-documentation-discipline/SKILL.md
```

OpenCode **discovers** skills but may load them **on demand**; merely placing a
file in a skills directory does not guarantee execution on every edit. To
make its use project-wide and consistent, also add the short mandatory
instruction from Section 14 to the root `AGENTS.md`, and point it at the
real installed location. Use the global path plus a globally applied agent
policy if this standard must govern all repositories. If an agent environment
does not support skill discovery, insert this policy into its persistent
system/project instructions instead of pretending the skill was auto-loaded.


---

## 1. Rules of operation: always / never

### ALWAYS

1. **Document every named function and method** you add or materially alter,
   exported or unexported, including constructors, handlers, worker functions,
   generic functions, lifecycle hooks, and interface methods. Preserve and
   correct existing documentation when changing behavior. For an unrelated
   edit, do not flood the patch with opportunistic documentation rewrites.
2. Begin a declaration's doc comment with its **exact Go identifier** and a
   meaningful behavioral description: `// ParseWindow ...`, `// Close ...`.
   A receiver method begins with the method's name, not a fake qualified name.
3. Document parameters and receiver constraints **by their actual names**,
   including ownership, nullability, units, boundary conditions, defaults,
   valid ranges, cancellation, concurrency requirements, and mutation, where
   relevant. Never invent a contract absent from implementation.
4. Document observable return-value semantics, error conditions and wrapping,
   state changes, resource ownership, concurrency guarantees, security
   assumptions, and meaningful performance contracts.
5. Include a **realistic use example** for each named callable. The example
   must agree with its signature, compile in its intended setting, have all
   required setup, and demonstrate correct error and lifecycle handling.
6. Include a **generated usage/reference section** adjacent to the callable's
   documentation, with verified repository-relative `path/file.go:line`
   locations for static references. Keep the section current when editing
   code, comments, imports, or formatting that may change line numbers.
7. Place **high-signal comments inside implementation bodies** where an
   engineer must understand *why*, invariants, synchronization, edge cases,
   failure handling, security checks, or surprising implementation choices.
8. Validate what you wrote with `gofmt`, `go doc`, compiler/tests, and a
   source-aware references facility before claiming completion.
9. Treat documentation and tracked usage locations as **testable repository
   artifacts**: a claim that cannot be verified must be qualified or omitted.
10. Apply the same accuracy standards in examples, test helpers, and build-
    tagged code that apply to production code.

### NEVER

- Write an uncommented new/modified named function and call the task finished.
- Write `// Foo does Foo`, `// Get gets`, `// Increment count`, `// Lock mutex`,
  narrate each line of code, or repeat an obvious type/signature in prose.
- Substitute a 100-line essay for a clear function name and well-structured
  implementation. Good comments supplement readable code, not excuse bad code.
- Use Javadoc/JSDoc/Doxygen tags (`@param`, `@return`, `/**`, `///`) as a
  substitute for idiomatic Go doc comments: GoDoc does not define their
  semantics as standard Go parameter documentation.
- Promise that GoDoc supports arbitrary Markdown, fenced code blocks, HTML,
  auto-clickable `file.go:line` paths, or special parameter hovers from headings.
- Manufacture sample inputs, errors, side effects, promises, performance
  numbers, or locations that have not been checked against the implementation.
- Treat substring search, raw `rg` matches, or a memorized list as proof of
  symbol identity or exhaustive call-site coverage.
- Claim `Used By` is complete for dynamic dispatch, reflection, external
  modules, callbacks registered at runtime, RPC routing, or other usages that
  cannot be enumerated statically.
- Leave `TODO: document later`, `example omitted`, `references pending`, or
  fictitious call sites in a completed production change.
- Sacrifice correctness or introduce behavioral changes just to make an
  example look simpler.

---

## 2. Separate the three documentation layers

Go has three distinct comment jobs. Use the right layer for each.

| Layer | Location | Purpose | Primary consumers |
| --- | --- | --- | --- |
| **API contract (GoDoc)** | Contiguous `//` immediately above a declaration, without blank line | What caller may rely on; inputs, outputs, gotchas, examples, usage locations | `go doc`, `pkg.go.dev`, `gopls` hover, GoLand Quick Documentation |
| **Implementation rationale** | Immediately inside a function near the relevant block | Why this algorithm, order, lock, invariant, retry, escape, or error path is necessary | Human/code-reviewing agent reading source |
| **Executable examples** | `ExampleXxx` functions in `_test.go` | Executable/compilable demonstration attached to the public API | `go test`, Go package documentation |

**Do not bury caller contracts only inside a function body:** `go doc` and many
IDE hovers present the preceding doc comment, not arbitrary comments inside
`{ ... }`. Conversely, implementation rationale belongs near the decision it
explains; do not expose private algorithms as part of an API contract unless
callers genuinely depend on them.

### Where documentation is mandatory

- Package overview: one canonical `// Package example ...` comment per package.
- Exported functions, methods, interfaces, types, variables, constants, and
  fields requiring semantic explanation: Go-standard doc comments.
- Unexported named funcs/methods: **same contract standard within this skill**
  (even though upstream Go conventions only require them when nontrivial).
- Receiver methods: describe receiver requirements (`nil` receiver, mutation,
  thread safety, shared state, lifecycle); include receiver in the parameter
  breakdown where it has meaningful constraints.
- Generic functions: identify type-parameter assumptions, ordering, equality,
  aliasing, and constraints not obvious from the type set.
- Tests/benchmarks: explain behavior under test and invocation with `go test`
  when direct invocation would be misleading; document mocks and fixtures.
- `main`, `init`, plugin callbacks, framework hooks, and interface-dispatched
  methods: explain **how they are invoked**, not invented direct callers.
- Closures: they have no separate named declaration suitable for standalone
  GoDoc. Prefer naming a substantial closure if callers need documentation;
  otherwise add a brief adjacent **why** comment for nontrivial closures.
- Generated `.go` files: change their **generator/template**, then regenerate;
  don't maintain hand edits likely to be overwritten.

---

## 3. Required contract for a function

Each named callable must answer the following, **in this order** where
applicable. Sections are sized to the contract, not padded to meet a word
count. A zero-argument function can say "Parameters: none" succinctly; an
internal one-liner need not invent elaborate edge cases.

### A. Name and one-sentence description — required

Write a complete sentence beginning with the exact identifier:

```go
// LoadSnapshot loads a consistent snapshot of the active configuration.
// A failed load leaves the receiver's current snapshot unchanged.
```

Say what observable result or side effect the operation has, not how its
internal implementation happens to work. State especially important guarantees
up front: atomicity, ordering, lossiness, idempotency, blocking, return value.
Avoid hyperbole such as "robust", "fast", "safe", "seamless", or "optimized"
unless followed by a verifiable, meaningful contract.

### B. Parameter breakdown — required

Use a GoDoc-compatible heading and list. Keep names synchronized with the
signature. Describe not only types, but *meaning* and *use restrictions*.

```go
// # Parameters
//
//   - ctx: Controls cancellation and deadlines for the whole operation.
//     It must be non-nil. Cancellation may occur after partial progress.
//   - input: UTF-8 content to parse; empty input returns ErrEmptyInput.
//     The function reads it but does not retain or mutate it.
//   - limit: Maximum accepted items, inclusive; values below 1 are rejected.
```

For methods, mention receiver constraints in a `Receiver` paragraph or list
entry if relevant. Don't describe the receiver as a normal argument at a call
site. For variadic parameters, define whether passing zero values is valid.
For function values/callbacks, describe when/how often they are invoked, whether
invocation is synchronous, whether they can run concurrently, and reentrancy.
For channels, specify producer/consumer role, buffer expectations if part of
contract, send/receive blocking behavior, **which side closes**, and
cancellation. For `io.Reader`/`io.Writer`, describe ownership and whether the
function closes it. For `[]T` and maps, describe aliasing, mutation, retention,
concurrent access, and nil vs empty distinctions. For `time.Duration`, specify
zero/negative behavior; for integers, units and boundaries. For `context.Context`,
state if cancellation is honored and whether partial results can be returned.

**If not applicable, don't invent warnings.** Use a concise `None` for a
parameterless function, not five vacuous bullets.

### C. Returns, errors, and other effects — required when applicable

Explain:

- Each result and any cross-result invariants (`n`, `err`; `value`, `ok`).
- Zero value on error, valid partial results, error identity via `errors.Is`
  or type via `errors.As`, wrapped vs replaced errors.
- Nil vs empty collections, EOF behavior, sentinel values, sortedness,
  stability, and whether result aliases input/receiver memory.
- Panics if intentionally part of contract; never mask unintended panics.
- Effects visible beyond the function: mutation, file writes, network calls,
  goroutines, transactions, resource release, ordering and durability.
- Concurrency contract: safe/unsafe concurrent invocation, lock ownership,
  whether calls may block, and whether work continues after return.
- Security assumptions, privacy/data sensitivity, data races, retry and
  idempotence semantics where they change correct usage.

Don't redundantly list every possible `fmt.Errorf` string as public API.
State meaningful error categories and what consumers should do about them.

### D. Example — required

Add a small, **accurate example using the real signature** under `# Example`.
Prefer code that can be copied with minimal adaptation. Do not use `...` as a
false promise of compiling code. Show an `if err != nil` path, `defer Close`,
`cancel()`, cleanup, or timeout when the call requires it. For instance:

```go
// # Example
//
//     start, err := time.Parse(time.RFC3339, "2026-10-20T09:00:00Z")
//     if err != nil {
//         return err
//     }
//     end := start.Add(30 * time.Minute)
//     window, err := NewWindow(start, end)
//     if err != nil {
//         return err
//     }
//     fmt.Println(window.Contains(start)) // true
```

This example is **inside a larger function returning `error`**; the surrounding
context must be stated (or use a self-contained `func example() error` snippet).
The agent must not silently present partial fragments as standalone programs.
For trivial, unexported functions, an example may be a concise one- or
three-line call from the package itself. For lifecycle hooks or test functions
not called directly by application code, give the **actual supported invocation**
(e.g. `go test -run '^TestFoo$' ./internal/foo`) rather than a fabricated call.

For important public APIs, **also** create/maintain executable `ExampleXxx`
functions in `_test.go`. The example in the declaration helps a hover reader;
the test example catches drift and can appear with the rendered package docs.
See Section 6 for naming and output verification.

### E. Where used — required, generated, and verified

Every named function/method ends its declaration comment with a `# Used By`
section. It lists **every statically resolved in-repository reference in the
analyzed scope**, using exact repository-relative file paths and **1-based
source line numbers**:

```go
// # Used By
//
// Generated from repository symbol references; do not edit these lines.
//
//   - cmd/server/main.go:47 (direct call)
//   - internal/api/handlers.go:113 (direct call)
//   - internal/jobs/registry.go:28 (function value)
//
// Scope: current module/workspace, including tests; build configuration:
// linux/amd64, default tags. Runtime/interface/external uses are not exhaustive.
```

**The locations above are illustrative examples only; they are NOT verified
locations in a user's repository.** The agent must regenerate them against the
actual repository before inserting real documentation.

Behavior of usage documentation:

1. Record usages of the **symbol**, not strings matching its name.
2. Prefer a typed or language-server references index; classify actual call
   expressions vs function-value references vs declarations. Exclude the
   declaration itself from `Used By`.
3. Include references in `_test.go`, other packages, and command packages when
   in scope; identify generated/vendor/dependency scope explicitly if relevant.
4. Sort by normalized repository-relative path, then ascending line number;
   deduplicate. Avoid absolute machine-specific file paths.
5. A line means the location of the **reference token/call**, not the target
   function's definition line, comment line, or enclosing function's start.
6. Keep all resolved references. If a symbol has extreme fan-out, the full
   list is still authoritative; an additional generated index may improve
   navigation but must not be used to falsely imply full inline coverage.
7. If there are zero references, say **"No statically resolvable in-repo
   references found in the stated scope"**, not "unused" or "dead code".
8. For interface methods, callbacks, plugin entrypoints, reflection, function
   values, and external consumers, explain that static results are **not a
   complete runtime call graph**. Label dynamic wiring you can actually verify.
9. If references cannot be verified, label `REFERENCE INDEX UNVERIFIED` in
   the working patch and **report this as an incomplete acceptance check**;
   never invent paths or numbers and never present the work as finished.
10. Treat each recorded line as **ephemeral generated metadata**, not stable
    hand-authored truth. Regenerate it after changing source or comments.

**Why this matters:** Editing a doc comment above a function may move the
functions and call sites below it. Accurate references often require multiple
format/re-index passes even if the logic never changed. See Section 7.

---

## 4. GoDoc syntax rules: make it render correctly

Use Go's official doc comment syntax, not arbitrary Markdown or JSDoc.

- Use `//` lines immediately adjacent to the declaration. A blank line
  between the comment and `func` breaks association.
- First sentence starts with the symbol name and uses complete English.
- Separate paragraphs with `//` blank lines.
- Headings: `// # Parameters`, `// # Returns`, `// # Errors`, `// # Example`,
  `// # Used By`. Put a blank comment line around headings.
- Lists: GoDoc supports lists. Use `//   - name: description` with
  continuation indentation appropriate for gofmt. Check rendered results.
- Code blocks: use **indented source lines**, such as `//     value, err := F(x)`;
  **do not use triple-backtick fences inside Go comments**. `gofmt` may change
  spacing to preserve the intended GoDoc structure.
- Cross-links to Go symbols may use `[SomeFunc]`, `[Type.Method]`, or a
  documented import path form when resolvable. Do not claim a string is a
  working link unless `go doc`/the selected renderer resolves it.
- For deprecations, use a standalone paragraph starting exactly with
  `Deprecated:` and document the supported replacement.
- `//go:...` compiler/tool directives are not ordinary prose; keep their
  exact required syntax. Do not invent directives for reference metadata.
- An inline `// comment` next to a statement is not an API doc comment.
- Avoid comments on the same line as a declaration where a preceding doc
  comment is expected.
- GoDoc does not specify a special `@param` annotation or per-parameter LSP
  hover protocol. Parameter explanations are useful **human-facing text**
  within the full documentation; how much is shown on hover depends on IDE
  configuration and display space.

Preferred section order (omit only truly inapplicable headings, **not** any
required information):

```text
Name and behavioral contract.

# Parameters
# Returns
# Errors
# Side Effects / Concurrency / Security (where meaningful)
# Example
# Used By (generated, last section)
```

Keep `# Used By` **last** so a references updater can safely replace just that
section without damaging the hand-authored behavioral contract. Avoid putting
hand-written explanation after the generated section.

---

## 5. Comments *inside* functions: explain what matters

Every nontrivial function should contain comments **near the decisions that
are otherwise difficult to infer**, not just one decorative comment above the
first line. Not every block needs a comment. A clear 5-line function may need
zero inline comments while still requiring its full GoDoc contract.

### Inline comments SHOULD document

- **Invariants:** what must remain true before/after a loop, when state is
  published, and why order matters.
- **Synchronization:** what a mutex protects, who owns state, which reads may
  race, why locks are released before callbacks or blocking I/O, and whether
  a channel value is an immutable snapshot or transfers ownership.
- **Cancellation/lifecycle:** why cleanup is deferred or why a goroutine must
  exit on `ctx.Done()`, how shutdown avoids leaks and double close.
- **Subtle edge cases:** Unicode boundary, overflow, clock issues,
  nil/empty distinctions, retries, partial failure, stale caches.
- **Security/trust:** why validation occurs before parsing/IO, constant-time
  comparisons where required, why sensitive data is not logged.
- **Transactions/consistency:** which step commits, how rollback works, and
  what partial failure leaves behind.
- **Performance trade-offs:** non-obvious batching, allocation behavior,
  asymptotic bounds if measurable and relevant, cache invalidation rules.
- **Protocol/format details:** external behavioral constraints, version
  compatibility, nonstandard cases and relevant authoritative spec links.
- **Surprising implementation choices:** why a seemingly simpler approach is
  wrong in this codebase; mention assumptions and the tests guarding them.

### Inline comments MUST NOT

```go
// BAD: Increment the counter.
count++

// BAD: Lock the mutex.
mu.Lock()

// BAD: Return the error.
return err
```

Prefer an explanation of the *invariant*, where one is genuinely needed:

```go
// Snapshot state while holding the read lock. The returned string is
// immutable, so callers may use it after the lock has been released.
r.mu.RLock()
value, ok := r.values[key]
r.mu.RUnlock()
```

And a synchronization explanation that guards against a future regression:

```go
// Release the lock before invoking a user callback. Callbacks may re-enter
// the registry; calling them under mu would deadlock that re-entry path.
r.mu.Unlock()
callback(change)
```

That example is **context-dependent**: do not copy its unlock/callback sequence
without proving that mutex ownership, state, and panic handling are correct.

### Concurrency-specific review prompts

When documenting concurrent code, answer before writing the comment:

1. Is a shared map/slice/pointer accessed by multiple goroutines? What
   mutex, ownership transfer, immutable snapshot, or other synchronizing rule
   prevents races? **Documentation never replaces synchronization.**
2. For a channel, who sends, who receives, who closes, and what prevents
   send-on-closed, deadlock, leaked goroutines, or starvation?
3. Is sending a pointer safe here? Does the pointed-to object get mutated
   after send or by multiple goroutines? Clarify ownership and aliasing. A
   pointer sent through a channel is **not inherently unsafe**; unsafe shared
   mutation and violated lifetimes are the issue. Likewise, sending a value
   is not automatically race-free when it contains shared references.
4. Are `ctx` cancellation, shutdown, retries, and partial results documented?
5. Does a goroutine outlive the function? Who is responsible for waiting or
   stopping it? Does cleanup happen on every error path?
6. Can concurrent callers reuse the receiver? Document yes/no and the
   conditions, not a hand-wavy "thread safe" claim.

Do not insert comments that assert a race is impossible without tracing the
actual happens-before relationships and running race-capable tests.

---

## 6. Executable examples and IDE usefulness

### A. Inline example in the doc comment

**Every named callable** has an illustrative usage example in its GoDoc (or
an honest invocation explanation for functions only invoked by a runtime).
A useful example chooses inputs that reveal the ordinary path or an important
edge case; it is not a generic `Foo(a, b)` copy of the signature. Show cleanup
and errors. Keep it short enough to remain readable in a hover popup.

### B. Executable package examples

For every new or materially changed **public API** where an example is
meaningful, add/maintain `ExampleXxx` in `_test.go`:

```go
package interval_test

import (
    "fmt"
    "time"

    "example.com/project/interval"
)

func ExampleNewWindow() {
    start := time.Date(2026, 10, 20, 9, 0, 0, 0, time.UTC)
    window, err := interval.NewWindow(start, start.Add(time.Minute))
    if err != nil {
        panic(err)
    }
    fmt.Println(window.Contains(start))
    fmt.Println(window.Contains(start.Add(time.Minute)))
    // Output:
    // true
    // false
}
```

*This example assumes a real, tested public `interval.NewWindow` contract with
`[start, end)` containment; substitute the actual module import path.*

Standard naming: `Example`, `ExampleFunc`, `ExampleType`,
`ExampleType_Method`, `ExampleFunc_suffix`. A suffix begins with a lowercase
letter. Follow the compiler's example-naming rules rather than inventing a
symbol. Examples compile as tests; those with an `// Output:` comment also
run and have output checked. Examples without it are compiled but not
executed by `go test`, so use an output check when feasible.

When examples require infrastructure or nondeterminism, demonstrate an
executable local or fake-backed path or state the prerequisite clearly; do
not include insecure hard-coded credentials, external network dependencies,
secret material, or examples that start unstoppable goroutines.

### C. Editor behavior, verified expectations

- **VS Code with the Go extension:** `gopls` delivers documentation/hover and
  code navigation through the Go language server. Hover content may depend
  on settings such as `hoverKind`.
- **Zed:** Go support uses `gopls` as its language server. GoDoc comments are
  source documentation; validate the actual Zed hover on the target setup.
- **GoLand/JetBrains:** Quick Documentation renders Go doc comments, headings,
  lists, and supported doc links. Check the actual popup, not only the source.
- **CLI and package docs:** `go doc -all ./path/to/package` and symbol lookup
  expose doc comments. Public exported APIs can appear on pkg.go.dev, subject
  to module accessibility and indexing. Local packages remain inspectable.

**Truth in tooling:** The text `cmd/server/main.go:47` is an informative
location, not a guaranteed clickable editor hyperlink. IDEs may offer
"Find References" independently; the inline list is a verified **snapshot**
for the human reader, not a replacement for live language-server navigation.

---

## 7. Call-site reference generation and freshness protocol

This is the most error-prone requirement. Treat it as a miniature source-code
indexing system, **not an LLM writing exercise**. The agent must not guess
`filename.go:45`, even if the function name seems unique.

### 7.1 Acceptable reference sources, in order

1. **Go language server (`gopls`)**: the editor's *Find References* or
   `gopls references file.go:line:column`, applied to the **declaration's
   identifier** at the current version of the source. The CLI is an
   experimental/debugging interface, so check `gopls help` for the installed
   version and do not hard-code its output format without verification.
2. **Typed AST index** built with `golang.org/x/tools/go/packages` (`NeedSyntax`,
   `NeedTypesInfo`), `go/types`, and `go/token.FileSet`. Resolve identifiers
   to `types.Object` identities and inspect `*ast.CallExpr` to distinguish
   direct calls from function-value references. Traverse the selected workspace
   and applicable build/test variants.
3. **Editor native Find Usages** with validation of symbol resolution and
   reported 1-based line numbers, if scripted indexing is unavailable.
4. **`rg -n` as a discovery aid only**, followed by AST/LSP/manual identity
   validation. A text match is not a verified reference.

Examples (run from repository root):

```sh
# A helper for manual discovery; NOT proof of symbol identity:
rg -n --glob '*.go' '\bNewWindow\b' .

# Exact declaration identifier position, determined from open source:
gopls references ./internal/interval/window.go:38:6

# File position is 1-based line:column; columns are UTF-8 byte offsets.
# Filter out the declaration and verify each reference's classification.
```

**The `38:6` position is an example, not a real project location.** The
reference command may return symbol references that do not invoke the
function. A reference to a method on an interface is not proof of which
concrete implementation runs at runtime.

### 7.2 Required updater behavior

If the repository lacks a dedicated reference updater, **implement one** as
part of adoption of this skill instead of repeatedly asking the model to
manually rewrite hundreds of locations. Recommended path:
`internal/tools/docrefs` or `cmd/docrefs`, with a documented command such as
`go run ./cmd/docrefs refresh ./...` and a non-mutating verification mode such
as `go run ./cmd/docrefs check ./...`. These paths/commands are **interface
suggestions**, not tools that this skill file alone magically installs.

An updater **MUST**:

1. Load configured Go packages with type/AST information for **all** relevant
   modules/workspaces, including tests and relevant `GOOS`, `GOARCH`, `-tags`
   variants; record scope and unsupported variants.
2. Identify declarations by symbol identity, including receiver-qualified
   method identity, not text alone. Do not conflate package-local `Close`
   functions or methods on different receiver types.
3. Collect source references with file, 1-based line, source form (direct
   call/function value/interface reference), and verified target identity.
   Where static resolution is not possible, classify uncertainty honestly.
4. Normalize locations relative to the repository root, use `/` separators,
   sort deterministically, deduplicate, and exclude generated docs themselves
   and the declaration. Do not include stale references from deleted files.
5. Replace **only** the generated last `# Used By` section; preserve the
   behavioral contract and implementation comments. Never overwrite prose
   written by the engineer to explain *why*.
6. Handle missing comments by reporting a documentation error or adding a
   compliant skeleton to be completed; never generate a confident but empty
   contract with fabricated semantics.
7. Avoid parse-invalid output. Format modified Go files with `gofmt` and
   reread/reindex actual on-disk text before collecting final positions.
8. **Converge:** update positions, format, reread, and repeat until a second
   refresh produces no changes, or fail with a diagnostic and **no success
   claim**. Added/removed comment lines shift subsequent call sites.
9. Preserve newline convention/encoding, avoid unrelated reformatting, and
   make updates deterministic, idempotent, and safe across reruns.
10. Support `check` mode for CI: produce a useful nonzero exit status and a
    diff when locations, names, example requirements, or scope metadata drift.
11. Fail closed or report partial coverage if packages do not typecheck or
    cannot be loaded; do not silently replace a nonempty reference list with
    "no references" because indexing failed.
12. Do not use external network calls to collect references. A local source
    index is the authority for in-repository locations.

### 7.3 Scope and inherent limits

Record what was scanned: e.g., `workspace modules; tests; linux/amd64;
default tags`. If a project supports platforms/tags that select different
source sets, index the supported matrix or explicitly state omitted variants.
Multiple modules in `go.work` must not be mistaken for a single `./...`
module. Consider private/vendor-generated Go only to the extent the policy
specifies. Source outside the checkout and external consumers are never fully
enumerable by a local source scan.

Special cases:

| Pattern | Indexing policy |
| --- | --- |
| Direct `pkg.Func(...)` or `receiver.Method(...)` | Record exact call line when types resolve |
| Method expression `(*T).Method` / method value `v.Method` | Record as function/method reference; do not label a direct invocation unless it is one |
| Interface method invocation `i.Method()` | Reference belongs to interface method; concrete targets are not always statically knowable |
| Function stored in map/field/variable or passed as callback | Record assignment/registration if statically resolvable; later calls may be indirect |
| Reflective lookup, dependency injection, RPC/router wiring | Describe specific verified dynamic registration where possible; no invented call edge |
| `main()`, `init()`, tests, examples | Explain runtime/test runner invocation when no direct repository caller exists |
| Generics and instantiations | Resolve generic object identity, not stringified type spelling |
| Comments, strings, or unrelated same-name methods | Never count as symbol references |
| Build tags/cgo/generated files | Include selected variants and document exclusions |

### 7.4 Exact finalization sequence

**Ordering is mandatory.** A reference list produced before the final source
edits is not final.

```text
1. Inspect implementation and existing docs; identify public and internal APIs.
2. Make functional edits and tests first.
3. Write/repair every affected function's GoDoc contract.
4. Write meaningful inside-function rationale near non-obvious decisions.
5. Add/update real usage examples and ExampleXxx tests.
6. Run gofmt on edited Go files.
7. Run compilation, unit tests, and appropriate vet/race checks.
8. Generate/refresh repository-qualified # Used By sections.
9. Run gofmt again if the generator changed Go sources.
10. Regenerate/recheck references until output is stable (no diff).
11. Run go doc on a sample of changed symbols and check IDE readability.
12. Run tests again if source or test examples changed; recheck locations.
13. Inspect git diff --check and git diff; ensure no fabricated metadata.
14. Report verification commands, scope, outcomes, and any known blind spots.
```

**Non-negotiable:** After any last-minute code/comment change, return to step
6 or 8 as appropriate. Do not report completion with known stale line numbers.

---

## 8. Reference-quality complete worked example

The following is an **illustrative, internally coherent API design**, not
source copied from the user's repository. The two `Used By` file positions
are examples; in a real repository they must be replaced with tool-verified
locations. The snippet shows contract docs, parameter descriptions, edge
cases, usage, and meaningful implementation rationale in one place.

```go
package interval

import (
    "errors"
    "time"
)

var ErrInvalidRange = errors.New("window end must be after start")

// Window represents the half-open interval [Start, End).
// Values are immutable after construction by NewWindow.
type Window struct {
    Start time.Time
    End   time.Time
}

// NewWindow validates and creates a half-open time window [start, end).
// A start exactly equal to end is invalid. Values retain their locations;
// comparisons use Go's time instant comparison semantics.
//
// # Parameters
//
//   - start: Inclusive lower bound. A zero time is allowed if it precedes end.
//   - end: Exclusive upper bound. It must represent an instant after start.
//
// # Returns
//
// The returned Window is valid only when err is nil. On an invalid range,
// the returned value is the zero Window and err matches ErrInvalidRange
// using errors.Is.
//
// # Example
//
//     start := time.Date(2026, 10, 20, 9, 0, 0, 0, time.UTC)
//     w, err := NewWindow(start, start.Add(time.Minute))
//     if err != nil {
//         return err // In a function returning error.
//     }
//     fmt.Println(w.Contains(start)) // true
//
// # Used By
//
// Generated from verified repository references; do not hand-edit.
//
//   - cmd/report/main.go:47 (direct call)
//   - internal/scheduler/scheduler.go:92 (direct call)
//
// Scope: illustrative paths only; regenerate against the actual repository.
func NewWindow(start, end time.Time) (Window, error) {
    if !start.Before(end) {
        return Window{}, ErrInvalidRange
    }
    // Preserve the caller's time values; converting to UTC here would change
    // their displayed locations without improving instant comparisons.
    return Window{Start: start, End: end}, nil
}

// Contains reports whether t falls in the half-open interval [Start, End).
// A timestamp exactly at End is outside the window.
//
// # Parameters
//
//   - t: Timestamp to compare as an instant, independent of its location.
//
// # Returns
//
// true when Start <= t < End; false at or beyond either boundary.
//
// # Example
//
//     start := time.Date(2026, 10, 20, 9, 0, 0, 0, time.UTC)
//     w, _ := NewWindow(start, start.Add(time.Minute)) // Known valid range.
//     fmt.Println(w.Contains(start.Add(time.Minute))) // false
//
// # Used By
//
// Generated from verified repository references; do not hand-edit.
//
//   - internal/scheduler/scheduler.go:104 (direct call)
//
// Scope: illustrative paths only; regenerate against the actual repository.
func (w Window) Contains(t time.Time) bool {
    return !t.Before(w.Start) && t.Before(w.End)
}
```

**Review the example critically:** the `fmt` identifier in the GoDoc snippets
is a documentation example and is not an import needed by `interval` itself.
A corresponding `ExampleNewWindow` in `_test.go` (Section 6) compiles and
checks behavior. A full executable example must not ignore errors except
where the test proves that the failure case is impossible. The `return err`
in the first snippet assumes a surrounding function that returns `error`;
for standalone examples write the function or use an executable test.

For other APIs, elevate the guarantees that matter:

- Database operation: transaction/rollback/commit semantics and retry safety.
- HTTP handler: request size, authorization, status codes, response body,
  cancellation, and whether partial writes are possible.
- File operation: path normalization, permissions, atomicity, `fsync`, Close,
  race with file replacement, and symlink behavior.
- Concurrent worker: ownership of maps and buffers, mutex/channel rules,
  shutdown/cancellation, task delivery semantics and race-free publication.
- Cryptographic function: allowed algorithms, nonce/key lifecycle, constant-
  time requirements and whether data is secret.
- Parsing function: accepted grammar, normalization, invalid byte handling,
  deterministic ordering and error offsets.

---

## 9. Small-function templates (no boilerplate theater)

Even simple named functions get an honest, useful contract. Keep each element
concise; don't fabricate complexity to hit a length target.

### Zero-argument function

```go
// Flush persists buffered records and waits for any in-progress write.
// If it returns an error, callers must not assume data reached disk.
//
// # Parameters
//
// None. Flush operates on the receiver's pending records.
//
// # Returns
//
// A non-nil error indicates that some records may remain buffered.
//
// # Example
//
//     if err := writer.Flush(); err != nil { return err }
//
// # Used By
//
// Generated references go here; replace with verified path/file.go:line data.
func (w *Writer) Flush() error { /* implementation omitted from template */ }
```

The snippet is a **template**, not a copy-paste-complete production function.
Replace placeholder body and generated section before completing a task.

### Intentionally pure private helper

A private pure helper can still be clear without pretending it has dangerous
edge cases. Document its actual behavior and give one concrete use. If the
only description possible is a repetition of the signature, consider removing
the needless wrapper instead of writing more documentation.

### Test function / runtime-called entrypoint

For `TestXxx`, use `go test -run '^TestXxx$' ./path/to/package` as the usage
example; `Used By` can identify test runner invocation rather than a fake
source call. For `main` and `init`, identify program startup as the runtime
trigger. Distinguish an explicit registration line from a later invocation.

---

## 10. Documentation correctness for changes and review

### When adding a function

- Give it a clear name/signature and a doc comment **before** declaring done.
- Identify the true contract from code and tests, not assumptions.
- Provide real inputs and example execution, including lifecycle/error paths.
- Update direct callers and the generated references of **affected callee
  functions**, not only the new function.
- Run the finalization sequence in Section 7.4.

### When modifying a function

- Compare **old and new contracts**: defaults, nil handling, mutation,
  cancellation, error category, return meaning, races, retries, or resources.
- Edit docs in the **same patch** as behavioral changes.
- Update `ExampleXxx`, ordinary tests, and any in-body comment invalidated by
  a new implementation.
- Refresh references after formatting, including unrelated call sites whose
  physical line numbers moved.

### When deleting/renaming/moving a function

- Remove obsolete docs; update cross-links and example names.
- Regenerate reference metadata for impacted symbols and callers.
- Do not leave source references to files that no longer exist.
- Check that a renamed method's receiver and interface contracts are still
  accurate. A call through an interface may not map to a single concrete
  receiver.

### When reviewing code

Inspect the code, not just comment presence. Verify each assertion by reading
implementation, tests, and real callers. A comment claiming a map is protected
by `mu` is invalid if another path accesses that map without the lock.
Run `go test -race` where relevant; a passing race run increases confidence
but is **not a proof that every possible race is absent**.

---

## 11. Verification: commands, acceptance gates, and failure behavior

Run in the right module/workspace, respecting repo-defined build flags,
environment, integration dependencies, CI workflows, and platform variants:

```sh
go version
go env GOWORK GOOS GOARCH

# Use the changed file list in normal work; inspect formatter output.
gofmt -l path/to/changed.go
gofmt -w path/to/changed.go

# Compile, tests, and static checks.
go test ./...
go vet ./...

# Optional but expected for concurrency-touching patches, on a supported host:
go test -race ./...

# See exactly what the public package documentation renders.
go doc -all ./internal/interval
go doc ./internal/interval.NewWindow

# Discover symbol references at a VERIFIED declaration identifier position:
gopls references ./internal/interval/window.go:38:6

# If you installed a repository-specific docrefs tool, use its actual commands:
# go run ./cmd/docrefs refresh ./...
# go run ./cmd/docrefs check ./...

git diff --check
git diff --stat
git diff
```

These are **representative commands**, not a claim that the user's repository
has `internal/interval` or `cmd/docrefs`. For private unexported functions,
`go doc` behavior and qualification may differ: inspect at package scope and
verify the doc association via AST/editor if necessary. For Go versions where
`gopls` CLI changes, use live editor Find References or the repository's typed
AST updater instead. Never claim a `go test -race` run succeeded if it did not
run or was skipped because the toolchain or platform did not support it.

### Required acceptance checklist (the agent MUST check every item)

- [ ] All added/changed named functions and methods have correct GoDoc comments.
- [ ] Every first sentence names the exact symbol and describes behavior.
- [ ] Each argument/receiver constraint is correct and useful; none is invented.
- [ ] Return, error, lifetime, aliasing, concurrency, side effect, and edge
      cases are covered wherever they affect correct use.
- [ ] Every named callable has a realistic example or honest runtime entrypoint.
- [ ] Important exported APIs have executable `ExampleXxx` coverage where
      applicable; examples compile and expected output is tested.
- [ ] Non-obvious implementation decisions have nearby *why* comments;
      obvious statements do not have narration.
- [ ] Each affected `# Used By` section contains verified repository-relative
      positions or an explicit, accurately scoped zero/limitation statement.
- [ ] Generated positions are accurate **after** all formatting and edits;
      two successive refresh/check passes produce no further changes.
- [ ] Comments and usage records avoid false claims about dynamic/indirect use.
- [ ] `gofmt`, relevant `go doc`, tests, vet, and race tests where appropriate
      have been run, with outcomes captured; failures not hidden.
- [ ] No placeholder explanation, fake source location, stale path, dead link,
      unclosed resource example, or unverified performance claim remains.
- [ ] The final diff does not introduce unrelated comment churn.

### Strict completion policy

**PASS:** All applicable acceptance checks were run and succeeded, and the
reference scope/limits are honestly recorded.

**INCOMPLETE:** Any function lacks docs, any required example is speculative,
any reference index is stale/unverified, or any relevant verification was not
possible. Report the exact limitation, evidence, and remediation. Do not
represent it as a completed production-quality patch.

**FAIL:** Comments contradict code, misstate a safety guarantee, assert
nonexistent references, or disguise a race/error as documented behavior.
Fix implementation as necessary, then reverify.

A succinct final report should state:

```text
Documentation: updated N function/method contracts, N executable examples.
In-body comments: explained invariants/edge cases without line-by-line narration.
References: indexed N symbols; scope: <modules/platform/tags/tests>;
            stabilized after final gofmt; unresolved dynamic edges: <details>.
Verification: gofmt PASS; go doc PASS; go test PASS; go vet PASS;
              go test -race PASS / NOT RUN (<reason>).
Limitations: <none, or exact problems and affected files>.
```

Never fill these fields with invented counts or `PASS` without tool evidence.

---

## 12. Agent self-check and anti-slop protocol

Before finalizing **each named function**, ask:

1. Can a competent engineer understand the contract from hover alone?
2. Does the first sentence tell what it does, not repeat its signature?
3. Do the parameter notes identify actual gotchas and not generic filler?
4. Do readers learn what errors, mutation, cancellation, and resources mean?
5. Is the call example compatible with this codebase and actually compilable
   in its declared setting? Have I handled errors instead of suppressing them?
6. Did I explain the non-obvious **why** inside the function rather than
   commenting every line?
7. Did I verify each `path/file.go:line` against the **final** source and
   resolve the symbol, not merely grep for a name?
8. Would I be comfortable if a coworker trusted every sentence during a
   production incident?

If any answer is no, **do the work**. Do not write a lengthy apology or
invent a rationale. Refactor code where necessary, amend docs, run checks,
and reindex references.

### Instruction for local models prone to premature completion

Treat "code works" and "documentation done" as separate gates. A passing
unit test does not satisfy the documentation gate. An IDE hover that displays
only a method signature does not satisfy the documentation gate. A list of
call-site strings copied from `rg` does not satisfy the reference gate. A
comment that describes a lock does not prove data race freedom. Do not self-
certify outcomes that require execution or source inspection.

The correct order is **implement → understand → document → demonstrate →
format → index → verify → finalize**. Repeat until stable.

---

## 13. Canonical references for future agents

These sources define or describe Go's actual behavior. Consult the installed
Go and gopls versions for changes; never substitute speculative standards.

1. **Go Doc Comments (official specification):**
   https://go.dev/doc/comment
2. **Go Code Review Comments — doc comments and named results:**
   https://go.dev/wiki/CodeReviewComments
3. **Testable Examples in Go (official Go blog):**
   https://go.dev/blog/examples
4. **go/doc/comment standard library package:**
   https://pkg.go.dev/go/doc/comment
5. **gopls command-line documentation (references; CLI is experimental):**
   https://github.com/golang/tools/blob/master/gopls/doc/command-line.md
6. **gopls language-server design and hover/references features:**
   https://github.com/golang/tools/blob/master/gopls/doc/design/design.md
7. **gopls hover settings:**
   https://github.com/golang/tools/blob/master/gopls/doc/settings.md
8. **Typed package analysis (`golang.org/x/tools/go/packages`):**
   https://pkg.go.dev/golang.org/x/tools/go/packages
9. **Zed Go support (uses gopls):**
   https://zed.dev/docs/languages/go
10. **GoLand Quick Documentation / reference information:**
    https://www.jetbrains.com/help/go/viewing-reference-information.html

---

## 14. One-paragraph directive for AGENTS.md

Paste the following into an existing `AGENTS.md` or equivalent root policy,
pointing to the real location of this skill. Keep any repository-specific
build/test commands and documentation-generator entrypoints there as well.

```markdown
### Go code documentation (mandatory)
For every Go change, apply `skills/go-documentation-discipline/SKILL.md`.
Every new/changed named function or method must have a correct GoDoc contract:
name/behavior, parameter and receiver gotchas, returns/errors/side effects,
a real usage example, and a machine-verified `# Used By` section containing
repo-relative `file.go:line` references. Write meaningful *why* comments inside
nontrivial implementations; never narrate obvious code. Refresh references
AFTER gofmt and repeat until stable. Verify go doc, tests, vet, and relevant
race checks. No fabricated locations, examples, or undocumented functions.
```

**This skill is a policy document.** It does not itself install an IDE,
connect to a repository, run `gopls`, or create the recommended `docrefs`
updater. Actual usage locations only become factual when indexed against a
specific checkout at a specific source revision and build configuration.
