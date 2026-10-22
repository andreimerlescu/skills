# Rust Engineering Standards — Mandatory Agent Skill

> **Scope:** ALL Rust code the agent writes, edits, reviews, tests, generates, or recommends; library, CLI, daemon, service, desktop, embedded, FFI, build-script, benchmark, test, example, migration, and automation code. Applies equally to short fixes and multi-agent projects. **Do not opt out merely because the task is small.**
>
> **Release baseline (verified 2026-10-19):** Rust **1.99.1** is the newest published stable patch release; **Rust 2024** is the latest stable edition. The baseline is a *floor*, not a permanent lock: check the official Rust releases page before each new project and set the project's MSRV to the latest currently released stable patch version unless the user explicitly requires broader compatibility. Existing projects must not have their MSRV/edition silently raised; report and negotiate version changes that would break consumers.
>
> **Normative words:** **MUST / MUST NOT** = mandatory and release-blocking unless an explicit user-approved, documented exception applies. **SHOULD** = default; departures require rationale. **MAY** = optional. **PROVE** = provide a compilation result, test, invariant, benchmark, documentation reference, or rigorous argument as appropriate. Never confuse a passing compiler with a proof of application correctness.

## 0. First instruction to the agent: quality outranks appearance

You are a senior Rust engineer. Your job is to produce **correct, safe, maintainable, testable, observable, resource-bounded, idiomatic** Rust that would withstand review in projects with engineering rigor comparable to Rust itself, Tokio, ripgrep, serde, rust-analyzer, rustls, and other mature systems projects. Docker and Terraform are useful operational-quality reference points, but **they are primarily Go codebases; do not copy Go's concurrency or API idioms mechanically into Rust.**

Code that *looks plausible* but is unimplemented, untested, subtly racy, or incorrect under shutdown/cancellation is a failure. Fix underlying design defects before beautifying surface details. Respect the repository's established conventions **unless those conventions violate safety or correctness**, in which case explain and propose the minimal sound change. Do not rewrite unrelated parts of a working codebase.

**Required execution loop for EVERY task:**

1. **Inspect:** read `AGENTS.md`, workspace manifests, crate source, test conventions, dependencies, feature flags, security and deployment requirements. Find the actual calling paths and existing tests.
2. **Classify:** decide whether code is single-owner, immutable-shared, mutable-shared, actor-driven, CPU-bound, I/O-bound, `async`, cross-thread, or FFI. Draw a state ownership diagram for changes involving concurrency.
3. **Specify:** define invariants, contract, observable behavior, failure states, timeouts, limits, cancellation and shutdown semantics. Define what would make the task *actually done*.
4. **Implement:** minimal end-to-end working change. Prefer stdlib and existing approved dependencies. No fake implementation, stub, fabricated API, or arbitrary unsafe escape hatch.
5. **Exercise:** add unit/integration/property/concurrency tests proportional to risk, including failure paths. Test observable effects rather than implementation details alone.
6. **Verify:** run required formatting, linting, build, tests, documentation, security checks, and target-specific checks available to the project. Capture exact commands and exit statuses.
7. **Critique:** try to break the change using the anti-slop checklist in §39. Independently inspect channel payload ownership, every mutable shared container, every spawned task, and every fallible operation.
8. **Report:** show files changed, behavior implemented, evidence, limitations and unrun checks. No claim of success for any check not actually executed.

**Stop conditions:** if no Rust compiler or tool is available, implement to the best of your ability but explicitly mark compile/lint/tests as **NOT RUN**, not PASS; give commands for later execution. If an unknown protocol, crate API, or external service is required, consult primary documentation or say verification is missing. Do not hallucinate API methods.

### 0.1 Hard release blockers

- `unsafe` or raw-pointer transfer used to bypass ownership rules, without reviewed documented invariants and soundness tests.
- Concurrent mutable access to `HashMap`, `BTreeMap`, `Vec`, caches, connection state, or other shared state without a valid ownership/synchronization design.
- `Arc<T>` presented as if reference counting alone made mutable `T` synchronized.
- `Rc<RefCell<T>>` shared across OS threads, an unchecked `unsafe impl Send/Sync`, or a lock guard accidentally held over `.await`.
- Unlimited spawning, infinite buffering, retry storms, or missing backpressure on a potentially unbounded workload.
- Dropped `JoinHandle`s for important work without lifecycle ownership; channel closure or task cancellation ignored.
- Critical errors swallowed with `let _ = ...`, `.ok()`, `.unwrap_or_default()`, or logging only when the caller needs to know a failure occurred.
- Application panic as routine error handling, including `.unwrap()`/`.expect()` on untrusted input or recoverable I/O.
- Tests mocked to pass without exercising the real behavior; assertions that cannot fail; placeholders disguised as implementations.
- Claiming tests pass when not run, disabling checks, or altering the tests to accept defective code.
- Secrets in source, logs, command arguments, artifacts, or error displays; unbounded parsing/allocation of untrusted input.
- Silent changes to public API, wire format, persistent format, edition, MSRV, supported targets, or dependency licensing.

## 1. Versioning, toolchains, editions, and compatibility

### 1.1 The moving latest-stable minimum

- On **2026-10-19**: published Rust stable version **1.99.1** ([announcement](https://blog.rust-lang.org/2026/10/15/Rust-1.99.1/)); current stable edition **2024** ([edition guide](https://doc.rust-lang.org/edition-guide/rust-2024/)).
- On **each new repository**: verify [official release index](https://blog.rust-lang.org/releases/) and `rustc --version`; choose the newest **stable patch** actually released at task start. Never infer a future Rust edition from compiler version, or assume stable APIs exist because they appear in `nightly` docs.
- For **existing repositories**, preserve declared `rust-version` and edition by default. Do not break downstream MSRV for unrelated changes; if the user specifically instructs "latest as minimum", plan a dedicated compatibility change and update docs, CI, and lockfile together.
- Record the exact minimum compiler in `[package] rust-version`. Unlike semver requirement strings, this is a **bare version**, e.g., `"1.99.1"`. Rust's `rust-version` is **a minimum supported compiler, not a lockfile for the compiler toolchain**.
- Pin the **tested toolchain** with `rust-toolchain.toml` (`channel = "1.99.1"` for this baseline) when reproducibility is more important than automatic updates; periodically update to newer stable through reviewed PRs. Never claim it will automatically select the newest toolchain if pinned. CI may additionally test `stable`.
- Set `edition = "2024"` in new Cargo packages until a newer edition is officially stable. Each edition is per-package, and an edition upgrade is distinct from compiler upgrade.
- Libraries: clearly declare and continually test the promised MSRV, targets, and features. Applications: prefer latest stable, but test deployment environment. Read [Cargo's Rust version policy](https://doc.rust-lang.org/cargo/reference/rust-version.html).

Recommended new-crate manifest (adapt crate type and packages to actual requirements):

```toml
[package]
name = "example-service"
version = "0.1.0"
edition = "2024"
rust-version = "1.99.1"
license = "MIT OR Apache-2.0"  # only if actually licensed this way

[dependencies]
# Declare real dependencies only, with audited versions/features.

[lints.rust]
unsafe_code = "forbid"  # default for crates requiring no unsafe implementation

[lints.clippy]
correctness = "deny"
suspicious = "deny"
```

`rust-toolchain.toml` for repeatable development:

```toml
[toolchain]
channel = "1.99.1"
profile = "minimal"
components = ["clippy", "rustfmt", "rust-src"]
```

**Notes:** The sample manifest is a *starting point*, not an instruction to misrepresent licensing, declare unused dependencies, or forbid legitimately reviewed low-level unsafe crates. Lint groups can interact with specific lints; pin and verify behavior on the selected compiler. Adding Clippy `pedantic` is a project decision: it contains judgment-oriented lints, not universal correctness laws.

### 1.2 Toolchain installation and validation

Follow [official installation instructions](https://rustup.rs/) rather than a vendor-supplied random script. On trusted developer hosts with verified network and prerequisites:

```sh
rustup update stable
rustup component add rustfmt clippy
rustc --version
cargo --version
rustup show active-toolchain
cargo metadata --locked --format-version 1 --no-deps
```

On fresh hosts, install `rustup` from the official distribution using the platform-specific instructions and verify TLS/provenance. Cross-target toolchains need `rustup target add <target>` **plus** actual target linkers/sysroots; a Rust target alone is not a complete cross-compilation environment. Use pinned toolchain names and explicit target matrices in CI. Do not require nightly for production merely to use experimental linting or benchmarks.

### 1.3 Workspace/lockfile policy

- Commit `Cargo.lock` for binaries/apps and commonly for workspaces; for libraries, comply with the repository's policy and understand that downstream consumers resolve their own dependencies.
- Keep dependency graph small, direct dependencies explicit, feature flags minimal and justified; understand semver, resolver, optional features, target-specific dependencies, and transitive native libraries.
- Prefer `cargo add` rather than inventing versions; read package release notes and Rust version support. Pin Git dependencies to reviewed revisions where possible.
- `cargo update` can upgrade transitive dependencies; run compatibility and security checks afterwards. Avoid broad lockfile churn in unrelated PRs.
- Define workspace lint rules and dependency inheritance consistently where practical. `--all-features` is only meaningful if features can coexist; if not, test supported combinations individually.

## 2. Mandatory design principles

1. **Ownership is architecture.** Decide who owns each piece of mutable state; encode in types and module boundaries. Share immutable references freely where sound; isolate mutation.
2. **Make invalid states unrepresentable.** Prefer enums, strong newtypes, builder validation, exhaustive `match`, and private fields over boolean flag combinations or magic strings.
3. **Use safe Rust by default.** Unsafe needs a separate written proof, sound abstraction, reviewers, and specific tests; compiler rejection is not permission to weaken safety.
4. **Choose the smallest mechanism.** Plain value > borrow > immutable `Arc` > actor/message passing or lock > low-level atomics > `unsafe`; select by problem constraints, not ritual.
5. **Correctness before performance; measurement before optimization.** Benchmark realistic workloads, then optimize proven bottlenecks without sacrificing invariants.
6. **No hidden work.** Every thread/task/process has an owner, concurrency limit, completion/error path, cancellation strategy, and shutdown deadline.
7. **Failures are part of API.** Propagate typed errors, annotate context, retry only retryable conditions, and expose operational symptoms.
8. **Minimal public API.** Favor small cohesive crates, private implementation details, stable explicit types, and clarity over generic cleverness.
9. **Documentation is executable contract.** Describe success, failure, units, ordering, timing, thread safety, cancellation, and examples; keep docs synchronized with behavior.
10. **A test must be capable of failing.** The test should detect the bug for which it was written; demonstrate this with fault injection or mutation where useful.

## 3. Style and naming conventions

Use `cargo fmt` (rustfmt) and the [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/) as the baseline. Manual formatting is not a substitute for rustfmt. Prefer lines, names and functions that make intent obvious. Favor readability in diff reviews.

| Element | Rust naming convention | Example / warning |
|---|---|---|
| Crates, modules, files | `snake_case` | `request_router`, `request_router.rs` |
| Functions, methods, locals, fields | `snake_case` | `load_config`, `pending_jobs` |
| Types, traits, structs, enums | `UpperCamelCase` | `WorkerPool`, `ConnectionState` |
| Enum variants | `UpperCamelCase` | `ConnectionState::ShuttingDown` |
| Const/static | `SCREAMING_SNAKE_CASE` | `MAX_PAYLOAD_BYTES` |
| Generic type parameters | short descriptive or `T`, `E`, `K`, `V` | `Reader`, `K: Eq + Hash` |
| Lifetimes | descriptive when more than one | `'input`, `'storage`; use `'_` when suitable |
| Feature flags | `kebab-case` preferred by many crates; match repo | `tls-rustls` |
| Tests | behavior + expectation | `rejects_duplicate_request_id` |
| Boolean names | positive predicate | `is_ready`, `has_capacity` |
| Units | encode in type or name | `timeout: Duration`, `bytes_sent` |

**Rules:**

- Avoid `data`, `stuff`, `util`, `manager`, `helper`, `foo`, `tmp`, `x` when they hide domain meaning. Short `i`, `idx`, `tx`, `rx` are fine in obvious short scopes.
- Prefer singular names for single values, plural for collections, `*_id` for identifiers, `*_at` for instants, `*_bytes` for byte counts. Prefer `Duration` rather than an integer with unclear units.
- Use descriptive verbs: `parse_*` for fallible parsing; `try_*` for non-blocking attempts; `get_*` for retrieval when needed (but idiomatic `len`, `is_empty`, `as_*` are preferred).
- Match standard conversion traits: `From` (infallible), `TryFrom` (fallible), `AsRef`/`Borrow` where semantically valid. Never implement `From` with panics for ordinary inputs.
- Use `#[non_exhaustive]` thoughtfully for public types that will grow; weigh downstream match ergonomics. Avoid public enums of booleans and stringly typed state.
- Do not name a private field `type_` when a better domain name exists; raw identifiers (`r#type`) can be correct for protocol-generated names.
- Avoid gratuitous comments narrating the obvious. Comment the **why**, **invariant**, **safety argument**, surprising trade-off, or external requirement.

### 3.1 Functions and modules

- Functions should have one coherent responsibility; split complex decision logic into named helpers rather than forcing huge blocks or a generic abstraction for every branch.
- Limit deep nesting with early returns, guards, `?`, and exhaustive `match`.
- Prefer a named `struct` with private fields over multiple parallel arrays, tuple indices, boolean argument soup, or mutable global state.
- `pub` is an intentional compatibility promise. Use `pub(crate)`/`pub(super)`/private by default. `pub use` should be curated at crate boundaries.
- Keep modules cohesive by domain/capability; **do not mechanically map one file per struct** or build Java-style interface layers.
- `lib.rs` exposes APIs; `main.rs` wires configuration, OS signals, resources, and process exit behavior. Domain logic should be testable without running a live server.

## 4. Ownership, borrowing, lifetimes and allocation

### 4.1 Ownership rules

- Prefer passing `&T` when reading, `&mut T` when mutating exclusively, and `T` when ownership truly transfers or a small `Copy` type is passed.
- Pass `&str` instead of `&String` when only string contents are required; `&[T]` instead of `&Vec<T>`; `&Path` instead of `&PathBuf`. Return owned values when the data must outlive inputs.
- Use `String`/`Vec` for owned variable-length buffers; use fixed arrays/slices for fixed/protocol lengths; avoid unnecessary `Box` unless indirection or trait object needed.
- Treat `.clone()` as a conscious choice; cloning `Arc` is cheap reference-count modification but may create shared lifetime/backpressure issues. Cloning a large `Vec`, `String`, or `HashMap` is an allocation/copy; review loop clones and hot paths.
- Avoid creating complex lifetimes unnecessarily. Often owning a small piece of data is simpler and safer than storing self-referential borrows.
- Avoid `Cow` unless a meaningful borrow-or-own behavior benefits callers; premature `Cow<'a, str>` everywhere is not an API improvement.
- Never return references into temporary values or use `Box::leak` to appease lifetimes. Leaking memory to satisfy `'static` is a defect absent an explicitly bounded one-time process-lifetime design.

### 4.2 `'static` is a lifetime bound, not a ban on cleanup

A value meeting `T: 'static` **contains no non-`'static` references**, but can still be dropped promptly. Spawning tasks typically requires owning their captured values because the task could outlive its caller. Solve with a moved owned value, scoped thread (for synchronous short-lived work), or `Arc` for *legitimate* shared ownership. Do not erase lifetimes with raw pointers.

### 4.3 Types that intentionally limit invalid states

```rust
use std::num::NonZeroUsize;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkerLimit(NonZeroUsize);

impl WorkerLimit {
    pub fn new(value: usize) -> Option<Self> {
        NonZeroUsize::new(value).map(Self)
    }

    pub fn get(self) -> usize {
        self.0.get()
    }
}
```

Use dedicated newtypes for validated identifiers, port/size restrictions, currencies/units, and status transitions. Never use a newtype only to create ceremony without validating an invariant or improving API clarity.

## 5. Traits, generics, enums, and dispatch

- Prefer concrete types until polymorphism is needed. Favor small behavior-driven traits, implemented near real uses, over anticipatory `RepositoryFactoryStrategyManager` stacks.
- Choose `impl Trait` for simple caller-facing generic parameters/returns, generic type parameters for related type constraints, and `dyn Trait` for runtime heterogeneity/plugin boundaries. Consider object safety and allocation.
- Use trait bounds only as strong as necessary. If the code does not need `Clone + Send + Sync + 'static`, do not add them.
- Make `Send`/`Sync` requirements explicit on services that cross thread boundaries. Do not add `unsafe impl` to force a nonconforming type to compile.
- Prefer enums and exhaustive matches for closed sets of states; trait objects for open behavior variants. Use `#[derive]` only when semantics (especially `Clone`, `Copy`, `Eq`, `Hash`, `Default`) are correct and desired.
- Avoid `Default` for security-significant configuration if a field missing would be dangerous. Prefer explicit validation.
- Do not use macros to paper over poor abstractions. Prefer typed functions; use `macro_rules!` for genuinely repetitive syntax; proc macros only when essential and maintained.

## 6. Collections and data structures

- `Vec<T>` for ordered sequences; `VecDeque<T>` for efficient two-ended queues; `HashMap<K,V>` for typical map lookup; `BTreeMap<K,V>` for ordered/range queries; `HashSet`/`BTreeSet` for membership; binary heap for priority queues; arena/slab only when proved beneficial.
- `HashMap` iteration order is not stable. Never depend on it for deterministic serialization, durable hashes, wire format, signing, snapshots, or reproducible tests. Sort explicitly or use ordered containers.
- `HashMap` randomized hashing mitigates many adversarial collision cases; if switching to a faster non-cryptographic hasher, document input trust and collision DoS implications.
- Avoid `map[key]` on fallible/untrusted keys: use `.get`, `.get_mut`, `.entry` and handle missing values. Avoid extra lookups with `entry` where insertion/update is needed.
- Use `usize` for memory indexes, checked numeric conversions at I/O/protocol boundaries, and explicit big-endian/little-endian encoding. Avoid silent truncation `as` casts between untrusted integer widths.
- Constrain untrusted collection sizes, recursion depth, string lengths, map key length, and nested payloads **before** allocation or expensive parsing.

### 6.1 The shared-map rule (CRITICAL)

**A `HashMap` does not need a mutex merely because multiple threads can see it. It needs an appropriate synchronization/ownership design if concurrent mutation is possible.** Rust's safe type system normally prevents unsynchronized concurrent mutable access; `UnsafeCell`, raw pointers, FFI, or incorrect `unsafe impl` can defeat that protection. `Arc<HashMap<K,V>>` is suitable for **immutable shared reads** when key and value types permit cross-thread sharing. A mutable shared map usually requires `Mutex`, `RwLock`, an owner task/actor with channels, sharding, or a verified concurrent-map implementation. **Choose deliberately and document why.**

| Access pattern | Preferred first design | Key caveat |
|---|---|---|
| Only one thread/task owns mutable map | plain `HashMap` | do not leak mutable references to other owners |
| Built once, then only reads | `Arc<HashMap<K,V>>` | no guard needed; values must also be safe to share |
| Shared read/write, straightforward operations | `Arc<Mutex<HashMap<K,V>>>` | short critical sections; lock contention |
| Read-heavy, measured benefit | `Arc<RwLock<HashMap<K,V>>>` | writer starvation/priority platform dependent |
| Complex invariants, I/O owner, serialized commands | dedicated actor owning `HashMap` + bounded channel | one owner; command protocol, backpressure |
| High-contention independent keys | validated sharded/concurrent map | per-entry semantics, atomic compound operations |
| Single counter/flag | appropriate atomic type | memory ordering and data-dependency proofs |

**No-go patterns:** `static mut HashMap`, `UnsafeCell<HashMap>` exposed across threads, raw pointer to a shared mutable map, `Arc<RefCell<HashMap>>` to satisfy thread safety, or unsynchronized mutations across callbacks. An `RwLock` is not automatically faster than a mutex; benchmark workload and critical sections first.

## 7. Error handling contracts

- Prefer `Result<T,E>` for recoverable failure, `Option<T>` for legitimate absence, and panics for broken internal invariants (not routine user input, network, filesystem or resource exhaustion).
- The `?` operator is idiomatic when the caller can act on or surface the error. Add precise context at system boundaries (filename, operation, request identifier) without disclosing secrets.
- Library public errors: explicit typed enums (often using `thiserror` when approved) with source chains; downstream code should classify. Application orchestration may use `anyhow::Result` when callers don't need stable discriminants.
- Never invent dependencies or import `thiserror`/`anyhow` unless added to `Cargo.toml` with approved version/features. The stdlib is enough for many small crates.
- Use `#[must_use]` where ignoring a returned status/value can cause a logical error; note `Result` is already must-use.
- No `.unwrap()`/`.expect()` on user-controlled data, I/O, task joins, mutex poisoning, runtime results, or channel sends in production paths. Limited use in tests/examples or genuinely proved local invariants can be acceptable with explanation.
- `unwrap_or_default()` can turn corruption or parse errors into a plausible empty result: do not use as generic error handling.
- Avoid converting error into a string too early. Preserve source chain and categorization; do not use `String` as an error type for a public library unless there's a carefully justified use.
- Distinguish invalid request (4xx), unavailability/retryable failure (5xx), conflict, timeout, cancellation, exhausted capacity, and integrity failure as appropriate to interface.
- Retry only idempotent/replay-safe operations or operations protected by idempotency keys; exponential backoff + jitter, bounded attempts/deadline, cancellation awareness, and observability.
- Treat poisoned locks as a signal that an invariant may be broken; do not blindly call `into_inner()` unless state validity is checked or the system's policy explicitly supports recovery.

## 8. `unsafe`, FFI, aliasing and soundness

**Default policy:** `#![forbid(unsafe_code)]` for ordinary application and business-logic crates. `unsafe` is not an optimization strategy and never the first answer to a borrow-checker error. Low-level/FFI crates may need narrow unsafe blocks with review.

Where approved unsafe code is truly necessary:

1. Define the *safe public interface* and invariants first. Explain why safe Rust/existing libraries cannot meet the requirement.
2. Confine unsafe operations to a very small, auditable module. Never scatter raw pointer dereferences into domain logic.
3. Every `unsafe {}` block gets a nearby `// SAFETY:` comment explaining **why that exact operation is sound**, including ownership, alignment, provenance, initialization, valid values, aliasing, exclusive/shared access, lifetime, synchronization, and drop policy as applicable.
4. Every `unsafe fn` exposes a `# Safety` contract to callers. In edition 2024, observe the rules for explicit unsafe operations inside `unsafe fn` and `unsafe_op_in_unsafe_fn`.
5. Any `unsafe impl Send` / `unsafe impl Sync` needs a proof of each trait's guarantees under *all* public safe methods and destruction. Escalate to an expert reviewer; a field being wrapped in `Arc` is insufficient.
6. For FFI, specify ABI, sizes/layout (`repr(C)` where required), alignment, ownership and allocator pairing, callback thread affinity, panic/unwind boundary, `CString`/`CStr` validity, lifetime of borrowed buffers, and error mapping.
7. Test failure, reentrancy, nulls, malformed inputs and cleanup; use Miri where supported, sanitizers when feasible, fuzzing, and independent review.

**Send** means safe to move ownership across threads; **Sync** means `&T` can be shared safely across threads. They are not decorations to suppress compiler errors. Raw pointers are not ordinary safe cross-thread message payloads. See [Rustonomicon: Send and Sync](https://doc.rust-lang.org/nomicon/send-and-sync.html) and [data races vs race conditions](https://doc.rust-lang.org/nomicon/races.html). **Safe Rust prevents data races; it does not automatically prevent logical races, deadlocks, starvation, lost updates across multiple steps, or incorrect shutdown protocols.**

## 9. Concurrency architecture — non-negotiable rules

Concurrency is a design decision, not a reason to spawn goroutine-like tasks indiscriminately. For every concurrent component, **name each mutable resource's sole owner or synchronization primitive**, and answer these questions:

1. What data is exchanged? Who owns it before `send`, after `send`, and on failed `send`?
2. Is data **copied, moved, borrowed for a bounded scope, or intentionally shared immutably**? Can the producer modify it after dispatch?
3. Can two tasks access the same memory at once? Is either access mutable? What proves the invariant?
4. How many jobs, queued messages, threads, tasks, open files and connections can exist at peak load? Is the bound enforced, not merely documented?
5. Can a task block while holding a lock? Can a lock be held across `.await`, disk/network I/O, callback, logging sink, or nested lock acquisition?
6. What happens when the consumer exits, channel closes, task panics, timer fires, caller cancels, or process receives SIGTERM?
7. Is ordering required (FIFO, per-key, total, eventual)? Is there an acknowledgement protocol? Is a retry safe?
8. Can operations overlap across mutable state and break a compound invariant despite individually safe accesses?
9. Which operations are **linearization points**? What consistency do readers and writers observe?
10. How is all of this **tested**, including adversarial scheduling, contention and teardown?

A concurrency design is incomplete until each has an explicit answer. **Never use a raw pointer in a channel merely to avoid copying a struct or satisfying a lifetime.** Channels already move owned values and safely carry `Send` payloads. Use `Arc<T>` where read-only shared ownership is actually required; protect interior mutations with a lock or actor protocol; use scoped borrowing only with lifetime guarantees.

### 9.1 Pick a concurrency model

| Model | Best use | Danger and required control |
|---|---|---|
| Sequential ownership | most business logic and parsing | simplest; don't parallelize without need |
| `std::thread::scope` | bounded CPU parallelism with scoped borrows | join/scoping and panic handling |
| Worker threads + bounded sync channel | blocking jobs, fixed worker pool | explicit shutdown, bounded queue |
| Tokio tasks + bounded `mpsc` | asynchronous I/O, high concurrent waits | cancellation, blocking code, task lifecycle |
| Actor (one state owner) | caches, mutable coordination, connection I/O | command protocol, serialized bottleneck |
| `Arc<Mutex<T>>` | short critical-section shared mutable state | contention, lock ordering, poison |
| `Arc<RwLock<T>>` | many reads / few writes after measurement | writer fairness, long read locks |
| Atomics | independent flags/counters or proven lock-free design | ordering, ABA, compound invariants |
| Sharding | measured contention on independent keys | cross-shard consistency and deadlocks |
| Rayon or limited CPU pool | data-parallel CPU computation | oversubscription, memory and blocking |

Do not conflate OS threads (`std::thread`) and async tasks (cooperatively scheduled futures); Tokio tasks are not a free CPU execution pool. Do not share one mutex merely because a component is conceptually shared: a dedicated owner is often clearer.

### 9.2 Rust's guarantees and limits

- `&mut T` is exclusive during its borrow; `&T` is shared but not generally mutable, except through sound interior mutability.
- A type being `Send` is necessary for cross-thread transfer; a type being `Sync` is necessary for sharing `&T` across threads. Some futures are not `Send` and can run on a `LocalSet` when architecturally appropriate.
- `Mutex<T>` combines access discipline with guard lifetime; `Arc<Mutex<T>>` adds multiple owners. Neither makes multi-step operations automatically atomic if locks are released between steps.
- Safe Rust prevents *memory data races*, but logic can still suffer check-then-act races, stale reads, deadlocks, inconsistent snapshots, lost updates, cancellation loss, starvation, or livelock.
- `Arc<T>` refcounts don't serialize operations on `T`. `Arc<HashMap<...>>` for read-only use is fine; `Arc<Mutex<HashMap<...>>>` for shared mutation is common. A concurrent map crate is not a license to ignore atomicity of sequences.

## 10. Channels and ownership (CRITICAL anti-slop section)

### 10.1 Channel payload rule

**Default: send an owned message by value.** This may be a small enum, a `String`, `Vec<u8>`, `Box<[u8]>`, `Bytes`-like immutable buffer when dependency justified, or a verified `Arc<ImmutableSnapshot>` when avoiding large copies across multiple receivers. Moving a `Vec` or `String` typically moves its small header; it does **not** clone the backing allocation. Heap allocations, refcounts, and copies must be understood before optimizing.

**Never assume** "pointers through channels are faster". Passing `*mut T`, `NonNull<T>`, opaque integer addresses, leaked references, `unsafe impl Send`, or a mutable shared object whose ownership is not enforced can introduce UAF, aliasing defects and races. A `Box<T>` crossing a channel is safe ownership transfer, **not** equivalent to an unrestricted raw pointer. `Arc<T>` is shared ownership, not a move-only message, and should be used only when shared identity is required.

| Payload | Meaning | Allowed? |
|---|---|---|
| `tx.send(Job { ... })` | owned value moved to receiver | **preferred** |
| `tx.send(Vec<u8>)` | owned header and allocation moved | **preferred for unique buffer** |
| `tx.send(Box<BigJob>)` | unique heap ownership moved | yes when indirection warranted |
| `tx.send(Arc<ImmutableConfig>)` | intentionally shared immutable snapshot | yes with documented reason |
| `tx.send(Arc<Mutex<State>>)` | multiple owners mutate protected state | permitted but scrutinize; actor may be simpler |
| `tx.send(&local)` to detached task | borrow may outlive local | typically fails; don't work around with pointer |
| `tx.send(*mut State)` + unsafe bypass | pointer with unproven lifetime/exclusivity | **prohibited by default** |
| integer-cast pointer, transmute, leaked static | evades lifetime/Send checks | **prohibited by default** |

**Channel expectations:** document FIFO/ordering scope, receiver cardinality, queue capacity, send/receive failure, whether dropping sender indicates EOF, and effect of receiver shutdown. Prefer **bounded** queues for producer/consumer systems. An unbounded channel creates an unbounded memory commitment unless the producer's total message count is *provably finite and small*.

### 10.2 GOOD: bounded `std::sync::mpsc` and owned messages

Complete minimal example (standard-library-only, one worker; processing order preserved):

```rust
use std::sync::mpsc::{self, Receiver, SyncSender};
use std::thread;

#[derive(Debug)]
enum Command {
    Store { key: String, value: Vec<u8> },
    Shutdown,
}

fn worker(rx: Receiver<Command>) -> usize {
    let mut processed = 0;
    while let Ok(message) = rx.recv() {
        match message {
            Command::Store { key, value } => {
                // This worker owns `key` and `value` now.
                println!("processing {} ({} bytes)", key, value.len());
                processed += 1;
            }
            Command::Shutdown => break,
        }
    }
    processed
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (tx, rx): (SyncSender<Command>, Receiver<Command>) =
        mpsc::sync_channel(32);
    let handle = thread::spawn(move || worker(rx));

    tx.send(Command::Store {
        key: "event-1".to_owned(),
        value: vec![1, 2, 3],
    })?;
    tx.send(Command::Shutdown)?;
    drop(tx);

    let processed = handle.join().map_err(|_| "worker panicked")?;
    assert_eq!(processed, 1);
    Ok(())
}
```

Production refinements: structured logging rather than `println!`; explicit result from work; decide whether shutdown **drains** queued messages; don't discard send failures. If another producer can enqueue after `Shutdown`, clarify or redesign the protocol. For multiple worker consumers, std's `mpsc` has a **single receiver**—do not wrap a blocking `Receiver` in a mutex and assume it creates a scalable multi-consumer pool. Use a deliberate dispatcher, multiple queues, or a vetted MPMC library with a reason.

### 10.3 BAD: raw pointer as an ersatz job payload

```rust,ignore
// FORBIDDEN DESIGN — illustrative pseudocode; do not implement.
// let addr = (&mut shared as *mut State) as usize;
// sender.send(addr)?;
// receiver reconstructs &mut State from addr and mutates it;
// producer may still mutate or drop State; aliasing/lifetime unsound.
```

A compilation obstacle is useful information. The correct fix is to move owned state, scope the threads, serialize operations through an actor, or wrap genuine shared state in a correct synchronization abstraction.

### 10.4 Bounded channel selection

- Blocking, single-consumer OS-thread context: `std::sync::mpsc::sync_channel(capacity)`; capacity **0** creates a synchronous rendezvous. `std::sync::mpsc::channel()` is unbounded and is **not** a safe default for unbounded producers.
- Tokio async context: `tokio::sync::mpsc::channel(capacity)`; capacity must be **at least 1**. `send(...).await` yields while backpressured. `try_send` needs explicit full/closed handling. Review `reserve`/permit semantics if preventing cancellation loss or wasted creation.
- One-off reply: `oneshot`; latest-value notifications: `watch`; notifications to many consumers: `broadcast` with lagged-receiver policy. These primitives are **not** interchangeable.
- Never call a blocking std receiver `.recv()` inside a Tokio worker loop; use async receiver, `spawn_blocking`, or a dedicated thread.
- Channel closure should be meaningful. Ensure all sender clones are dropped or receiver won't terminate. Handle `send` failure when consumer goes away. Do not `while let` forever waiting for a sender stored in self-referential state.
- Rate limits, bytes queued, per-tenant fairness and message-size caps matter in addition to number of slots. A channel of 100 messages could still hold 100 enormous payloads.
- When requests require completion confirmation, use command + response channel and transaction ID; `send` success means **queued**, not **processed** or **persisted**.

## 11. Shared state with `Mutex`, `RwLock`, and actor ownership

### 11.1 GOOD: `Arc<Mutex<HashMap<...>>>` with short critical sections

```rust
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::thread;

type Counts = Arc<Mutex<HashMap<String, u64>>>;

fn increment(counts: &Counts, key: &str) -> Result<(), &'static str> {
    let mut map = counts.lock().map_err(|_| "counts lock poisoned")?;
    let count = map.entry(key.to_owned()).or_insert(0);
    *count = count.checked_add(1).ok_or("counter overflow")?;
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let counts: Counts = Arc::new(Mutex::new(HashMap::new()));
    let handles: Vec<_> = (0..8)
        .map(|_| {
            let counts = Arc::clone(&counts);
            thread::spawn(move || increment(&counts, "requests"))
        })
        .collect();

    for handle in handles {
        handle.join().map_err(|_| "worker panicked")??;
    }
    let result = counts.lock().map_err(|_| "counts lock poisoned")?;
    assert_eq!(result.get("requests"), Some(&8));
    Ok(())
}
```

Guard lifetime is short and mutation of a single count is atomic with respect to other lockers. This example uses checked arithmetic rather than silently wrapping. For shared concurrent mutation, **check every access path**: a lock around only writers with unguarded readers is not a valid design. Avoid holding a lock during expensive serialization, logging to a blocking sink, network calls, callbacks, `.await`, or other resource acquisition.

### 11.2 GOOD: immutable shared map needs no mutex

```rust
use std::collections::HashMap;
use std::sync::Arc;
use std::thread;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut map = HashMap::new();
    map.insert("feature_x".to_owned(), true);
    let config = Arc::new(map); // Built once; never mutated after sharing.

    let config_for_reader = Arc::clone(&config);
    let reader = thread::spawn(move || {
        config_for_reader.get("feature_x").copied().unwrap_or(false)
    });

    let enabled = reader.join().map_err(|_| "reader panicked")?;
    assert!(enabled);
    Ok(())
}
```

The example's fallback `false` represents an intentional *default on absent optional feature*, not a suppressed error; treat mandatory configuration differently. `Arc<HashMap>` is sound here because reads alone do not mutate it and the contained types are thread-safe. If updates become necessary, select a real update protocol rather than introducing backdoor mutation.

### 11.3 Actor-owned mutable map: often best for complex state

Design an actor with **exclusive ownership** of its `HashMap`, an explicit bounded command queue, and optional per-request response (`oneshot`). The map never escapes; callers send value commands. Advantages: one place to check invariants, no lock exposed to callers, natural serialization of state transitions, easy auditing. Disadvantages: serialized bottleneck, queue latency, shutdown/drain design.

Actor command protocol should specify:

- Command variants with owned payloads and validated IDs.
- ACK of acceptance versus ACK of completed persistence; caller needs clear semantics.
- Per-command errors and reply channel failure handling.
- Capacity, maximum buffered bytes, batching strategy and rejection policy.
- Cancellation behavior if requester's reply receiver drops: do we finish, stop, or make it idempotent?
- Snapshot/read-query semantics and read-after-write guarantee.
- Drain or reject on shutdown; explicit state transition (`Running -> Draining -> Stopped`).

**Do not** send `&mut HashMap` or a raw map pointer through a channel to imitate an actor. The actor owns it outright.

### 11.4 Locks and critical sections

- Prefer `Mutex` initially; consider `RwLock` only if it addresses measured contention. `RwLock` does not guarantee fairness uniformly across platforms.
- Define a global lock order if acquiring multiple locks; avoid acquiring new locks inside a lock guard whenever possible. Beware callback/reentrant lock acquisition.
- Don't hold a lock while awaiting. In async contexts, a std `Mutex` is often appropriate for **short, non-`.await` data-only** critical sections. Use Tokio's async `Mutex` only when awaiting the acquisition / holding across a suspension point is essential and carefully justified, often for shared I/O state.
- Put lock operations in synchronous methods to force guard release before `.await`. **Explicit lexical scopes** beat relying on `drop(guard)` if an async liveness analysis or temporary lifetime creates ambiguity.
- Avoid exposing `MutexGuard` through public API. Provide narrow operations: `get_snapshot`, `insert`, `apply_transaction`.
- Never swap a mutex for `RefCell` to resolve compile errors; `RefCell` is runtime borrow checking, not cross-thread synchronization.
- Poisoning is not guaranteed by every lock library; define policy per lock type. Never assume poison is a general-purpose correctness validator.
- Avoid a `Mutex<Option<State>>` without understanding state transitions; model states with enums where clarity benefits.

### 11.5 BAD: protecting only one part of a logical transaction

```rust,ignore
// BAD logical race even when each get/set is under a lock:
// if balance() >= debit { withdraw(debit); }
// Another task can change the balance between the check and update.
```

**Fix:** hold a single guard across check-and-update; or send one atomic `Withdraw` command to the owner; or use an atomic CAS loop if state is truly a single scalar and ordering/retry is proved. Synchronization of individual operations is not sufficient for multi-operation invariants.

## 12. Atomics, memory ordering, and lock-free claims

- Atomics are for independent counters/flags or carefully proven synchronization algorithms, **not** a convenient substitute for protecting a `HashMap`/`Vec` with compound invariants.
- `Ordering::Relaxed` is appropriate for metrics independent of other data visibility. It does not establish happens-before relationships for accompanying writes.
- `Acquire`/`Release` and `AcqRel` require a clear publication/data-dependency proof; `SeqCst` is an understandable conservative default when atomics are necessary, **but cannot repair a fundamentally incorrect protocol**.
- For compare-exchange loops, handle both success and failure orderings correctly (failure ordering may not be `Release` or `AcqRel`); reason about retries, progress and ABA.
- Before lock-free code: prove linearizability, memory reclamation, pointer provenance, hazard/epoch ownership, fairness, cancellation behavior and destruction. Prefer a thoroughly reviewed existing implementation.
- Test with Loom (where integration uses Loom's instrumented primitives), Miri (when relevant), adversarial interleavings and stress; know that these tools do not exhaustively certify correctness for arbitrary programs.

GOOD for a standalone telemetry counter:

```rust
use std::sync::atomic::{AtomicU64, Ordering};

static ACCEPTED_REQUESTS: AtomicU64 = AtomicU64::new(0);

fn record_accepted_request() {
    ACCEPTED_REQUESTS.fetch_add(1, Ordering::Relaxed);
}

fn accepted_requests() -> u64 {
    ACCEPTED_REQUESTS.load(Ordering::Relaxed)
}
```

**Why it works:** a single atomic measurement has no accompanying data-publication requirement; reads can observe a momentarily stale count, and overflow policy must be considered for long-running/hostile scenarios. **Do not generalize** this to accounting/balance updates or publishing a fully initialized structure.

## 13. Scoped threads, thread pools, blocking operations

- When splitting a bounded CPU job that borrows local state, `std::thread::scope` avoids `'static` workarounds; all scoped threads finish before scope exits. For short computations consider sequential performance first.
- Prefer a bounded worker count or Rayon for CPU-parallel workloads; limit based on cores, memory, NUMA/topology where relevant, and per-request workload. A new OS thread per request is rarely acceptable.
- Keep blocking filesystem/CPU/dns/FFI operations off Tokio executor threads as appropriate; `spawn_blocking` uses blocking threads but has its own capacity/shutdown behavior, and arbitrary compute jobs still need an application-level concurrency semaphore.
- Don't assume dropping a Tokio `JoinHandle` cancels its task (it normally detaches); Tokio `JoinSet` dropping aborts tasks, but blocking operations may not be abortable once running. Await necessary cleanup explicitly.
- Every worker-pool API should define draining, cancellation, panic isolation, retry semantics, how errors return to submitters, and metrics on active/queued/dropped work.
- Beware nested parallelism: high request concurrency × per-request Rayon/Tokio workers can explode resource consumption.

GOOD bounded scoped borrowing:

```rust
use std::thread;

fn sum_halves(values: &[u64]) -> u64 {
    let midpoint = values.len() / 2;
    let (left, right) = values.split_at(midpoint);
    thread::scope(|scope| {
        let left_result = scope.spawn(|| left.iter().copied().sum::<u64>());
        let right_result = scope.spawn(|| right.iter().copied().sum::<u64>());
        left_result.join().expect("left computation panicked")
            + right_result.join().expect("right computation panicked")
    })
}
```

**Scope and caveats:** this is a small illustration of lifetime-safe borrowing, not an assertion that threading improves sums (it commonly doesn't for small inputs). This uses `expect` for internal computation thread panics, which should be converted to application error boundaries where recoverability matters. Unsigned overflow semantics must be defined for externally supplied values; `sum` and `+` are not appropriate if overflow must be rejected.

## 14. Async Rust, futures and runtime discipline

### 14.1 Async principles

- `async fn` creates a future; it does not start background work by itself. A future progresses when polled by an executor or explicitly awaited. Don't confuse concurrency with CPU parallelism.
- `.await` is a suspension point; another task may change shared state while suspended. Reconsider invariants and cancellation at every `.await`.
- `tokio::spawn` generally requires future and output `Send + 'static` on multi-threaded runtimes; do not bypass it with raw pointers or unchecked traits. For thread-local non-`Send` state, use a deliberate local executor/`LocalSet`, keeping such resources confined.
- Never call `std::thread::sleep` or blocking synchronous I/O inside an async task; use async timers or `spawn_blocking`/dedicated blocking threads.
- Avoid `block_on` nested inside a running async executor and synchronous functions that secretly spawn runtimes per request.
- `tokio::sync::Mutex` is not automatically the right choice; a normal mutex guarding brief data-only operations is often better (per Tokio docs). Never hold a std mutex guard across `.await`.
- Split sync parsing/validation from async orchestration. Make ownership of network clients, pools, listeners and shutdown tokens explicit.
- Make cancellation safe: when a future is dropped between two awaits, determine whether partial progress requires rollback, durable state, idempotent re-execution, or a completion worker.

### 14.2 GOOD: bounded Tokio message queue with owned payloads

Requires an explicit `tokio` dependency with needed `rt-multi-thread`, `macros`, and `sync` features. The example intentionally handles send/receive failure and join status:

```rust
use tokio::sync::mpsc;

#[derive(Debug)]
struct Work {
    id: u64,
    payload: Vec<u8>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let (tx, mut rx) = mpsc::channel::<Work>(64);

    let worker = tokio::spawn(async move {
        let mut completed = 0_u64;
        while let Some(work) = rx.recv().await {
            // Receiver now owns this message. No raw pointers, no shared mutability.
            println!("job={} bytes={}", work.id, work.payload.len());
            completed += 1;
        }
        completed
    });

    tx.send(Work { id: 7, payload: vec![9; 128] }).await?;
    drop(tx); // Close when last sender drops so receiver can finish.
    let count = worker.await?; // Observe task panic/failure.
    assert_eq!(count, 1);
    Ok(())
}
```

**Not yet a production service:** this example demonstrates the ownership contract, not a durable queue. A production worker needs real work processing, timeouts, idempotency, metrics, per-message error replies and graceful shutdown. The `#[tokio::main]` default runtime choice depends on enabled features.

### 14.3 Bounded concurrent tasks with a semaphore

For a stream of independently spawned tasks, do **not** build an unbounded vector of futures or spawn an unlimited task per message. Use a `Semaphore` and ensure that admission happens **before spawning** (or track pending producers), so memory remains bounded. Each task owns a permit until work is complete. Consider failure if semaphore is closed. For structured tasks, `JoinSet` collects completions and propagates join errors; do not drop it before deliberately dealing with outstanding tasks. Remember that `spawn_blocking` may not be abortable once running.

Pseudo-design (not an executable sample; must be integrated with application error policy):

```text
accept request
  -> validate payload size and authorization
  -> acquire admission permit with timeout/cancellation
  -> spawn owned task with permit moved into it
  -> collect completion or send response
  -> release permit on task completion/drop
on shutdown: stop admission, cancel/drain, await tasks, report failures
```

### 14.4 `select!` and cancellation

- A losing branch in `tokio::select!` is typically dropped; assess each future's cancellation safety rather than assuming "the operation will resume later."
- If cancellation can lose a message, partially written record, or permit, redesign using a maintained future, reserve/permit protocol, owned work supervisor, or idempotent transaction.
- Favor deadlines over unrelated sequential timeouts that can exceed the total request budget. Propagate remaining budget to downstream work.
- On drop/cancel, RAII frees in-memory resources, **not necessarily remote side effects**. A database write or network request may have succeeded while the reply was cancelled. Design for uncertainty.
- Use a `CancellationToken` (if the library exists and is approved), explicit shutdown channel, or runtime-provided signal handling. Cooperate at blocking points.
- Document whether shutdown drains work or drops it, and what caller sees for unfinished requests. Persist accepted jobs before acknowledging durable success.

### 14.5 Async network and service requirements

- Set connect, TLS handshake, request, idle/read, write, total, and shutdown time budgets as applicable. Never assume a client library provides safe defaults for all of them.
- Bound connections, request bodies, decompression size, header counts, redirects, retries, per-IP/per-tenant work, and outstanding tasks.
- Avoid sharing one serial connection under a long-held async mutex when a pool/owner task is a better match.
- For inbound HTTP: use explicit request validation, middleware ordering, context/tracing spans, structured error handling, readiness/liveness, and graceful signal handling.
- For outbound HTTP: use a reused client/pool, TLS validation, allowlisted endpoints where SSRF risk exists, normalized target handling, and backoff/circuit-breaking when required.
- Do not choose framework or runtime purely because examples are familiar; align with workspace and deployment constraints.

## 15. Correct shutdown, task ownership, and failure propagation

**Every spawned concurrent activity MUST have one of:**

- A parent that joins/awaits it (structured lifetime).
- A supervisor with explicit restart/backoff, tracking and shutdown.
- A deliberately detached daemon task **documented** as best effort with no required completion and a clear process lifecycle.

Do not silently discard join handles for important work. Distinguish process shutdown from a detached task's natural completion. For ordinary services:

1. Mark system `Draining`; stop accepting new work and stop scheduling retries.
2. Stop listeners/admission and close producers so consumers can drain.
3. Signal cancellation to optional/per-request operations and deadline-bound I/O.
4. Complete or durably hand off accepted work according to documented guarantee.
5. Await workers under a documented **overall** deadline; report partial completion.
6. Flush buffered logs, metrics, and persisted state with bounded time.
7. Close resources exactly once, expose unfinished work and return meaningful exit status.

**Panic policy:** panic is not a retry mechanism. A task panic can violate invariants and leave work missing; surface it, fail/restart the affected subsystem if safe, and do not report the task as completed. `catch_unwind` is not a sound generic way to conceal invalid state or catch every kind of termination.

## 16. Deadlocks, starvation, fairness, and progress guarantees

- Document lock acquisition order; add tests for reversed paths. Avoid holding a lock while calling outside code or awaiting.
- Choose bounded queues and fair scheduling across workloads. A system can be memory-safe and still starve tenants/tasks or stall indefinitely.
- Avoid cyclic actor RPC (`A` waits for `B` while `B` waits for `A`) and circular dependencies in completion notifications.
- Avoid single shared global state lock around network I/O, serialization, filesystem scanning, or expensive crypto.
- Beware priority inversion and long-running tasks on an async executor. Break CPU tasks into bounded chunks or use CPU pool.
- Measure lock hold time, queue wait time, worker utilization, dropped/retried messages, cancellation and shutdown latency.
- Use load/stress tests with abrupt disconnects, restarts, timeouts, reorderings and faults. A single race-free run is weak evidence.

## 17. Production-quality API design

- Prefer the [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/) over inventing project-specific customs. Inspect existing APIs for compatibility, error taxonomy and naming.
- Make constructors validate required invariants; preserve field privacy. Use builders for optional, numerous, or validated parameters, not for trivial structs.
- Function signatures should expose ownership accurately: `&str`/`&[T]`/`&Path` for read-only inputs, `&mut` for exclusive mutation, `T` for transfer, `Result` for ordinary errors.
- Use `&self`, `&mut self`, and `self` based on contract. A consuming `self` method conveys lifecycle transition; a shared `&self` method with interior mutation requires scrutiny and documentation.
- Avoid public APIs returning third-party dependency types unless committed to their compatibility; place external protocols behind narrow boundary types where useful, without gratuitous abstraction.
- Prefer structured enums over string error codes, boolean mode flags, and magic `usize` values. Distinguish optional from required fields.
- If public trait methods can fail, define errors/timeouts/cancellation. Document implementor obligations and whether trait objects must be `Send + Sync`.
- Trait implementations should obey established laws: `Eq`/`Hash` coherence, `Ord` total ordering, `Clone` semantics, `Iterator` contracts, `Display` user-facing vs `Debug` developer-facing. Do not derive `Eq` for values with unsuitable semantics.
- Use no `panic!` in public API for user errors unless a documented `*_unchecked` style contract and corresponding checked API make that appropriate.
- For public enums planned to expand, `#[non_exhaustive]` trades stronger forward-compatibility for consumer match inconvenience; use intentionally.
- Avoid breaking changes to serde names, defaults, enum tagging, generic bounds, auto traits, method receiver types or `Send` guarantees without versioning/migration plan.

### 17.1 Parsing and validation

```rust
use std::num::{NonZeroU16, ParseIntError};

#[derive(Debug)]
pub enum PortParseError {
    InvalidInteger(ParseIntError),
    ZeroNotAllowed,
}

impl std::fmt::Display for PortParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidInteger(err) => write!(f, "invalid port number: {err}"),
            Self::ZeroNotAllowed => f.write_str("port must not be zero"),
        }
    }
}

impl std::error::Error for PortParseError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::InvalidInteger(err) => Some(err),
            Self::ZeroNotAllowed => None,
        }
    }
}

pub fn parse_service_port(value: &str) -> Result<NonZeroU16, PortParseError> {
    let port: u16 = value
        .parse()
        .map_err(PortParseError::InvalidInteger)?;
    NonZeroU16::new(port).ok_or(PortParseError::ZeroNotAllowed)
}
```

The sample shows how to retain a meaningful source error without pulling in a dependency. Decide whether whitespace, leading zeros and protocol port 0 are permitted by the actual specification; the code above rejects zero and does not trim. Validation is a domain decision, not a one-size-fits-all parser.

## 18. Data modeling and state machines

Use enums instead of mutually inconsistent booleans. Model transitions explicitly and make invalid transitions return errors. Prefer typed IDs/units and domain objects to uncontrolled `serde_json::Value` throughout business logic.

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Lifecycle {
    Starting,
    Ready,
    Draining,
    Stopped,
}

impl Lifecycle {
    fn begin_drain(&mut self) -> Result<(), &'static str> {
        match *self {
            Lifecycle::Ready => { *self = Lifecycle::Draining; Ok(()) }
            Lifecycle::Draining => Ok(()), // Idempotent transition.
            Lifecycle::Starting => Err("not ready to drain"),
            Lifecycle::Stopped => Err("already stopped"),
        }
    }
}
```

- Clarify where a state machine lives: in a single owner actor, protected by a lock, or persisted by transactions. An enum does not itself provide concurrency safety.
- If an operation must atomically update several fields, keep them in one guarded aggregate or database transaction rather than independently locked pieces.
- Specify retry/duplicate message behavior for idempotent transitions; replayed commands should not double-charge, double-send or double-persist.
- For persisted state, include schema version, migration strategy, backward compatibility and recovery from partial writes.

## 19. Serialization, persistence, databases, and durability

- Define canonical field names, required/optional fields, precise timestamp format/timezone, numeric ranges, precision, byte encoding, enum representation, unknown-field policy and versioning.
- `serde` is a convenient tool when approved, not a substitute for validation. Deserialization success **does not imply semantic validity**.
- Reject oversized/nested malicious input and decompression bombs **before or during** parsing with real limits. Validate after parsing.
- Use transactions for multi-record invariants, with correct isolation and idempotency. Distinguish commit acknowledgement from queue insertion.
- For disk formats, avoid writing directly over a good file when a crash can leave corruption. Use an appropriate temp-file, flush/fsync/rename/parent-dir sync pattern for the filesystem and durability guarantee, verifying OS semantics. Atomic rename by itself does **not** always guarantee power-loss durability.
- Avoid serializing a `HashMap` and assuming stable key order; canonicalize when digesting/signing/reproducibly comparing.
- Apply migrations forward only with backups/rollback plan as appropriate. Never silently discard unknown critical data.
- Database connections belong to a pool/owner; do not hold a process-wide mutex across slow queries unless unavoidable and proved safe. Bound pool size, transaction lifetime, lock time, query budget and retry rates.
- Secrets/PII require encryption at rest and in transit as specified; logs, tracing spans and error contexts must redact data.

## 20. Security engineering checklist

Treat all external input and external dependencies as untrusted until validated. Rust prevents many memory safety problems but **not** authorization bypass, logic bugs, SSRF, resource exhaustion, SQL injection or cryptographic misuse.

### 20.1 Required input and privilege controls

- Validate lengths, types, character sets, encodings, canonicalization, allowed paths and domain rules at trust boundaries.
- Use parameterized SQL queries; never concatenate attacker input into SQL or shells. Spawn subprocesses using argument arrays and absolute/trusted executables where possible, rather than a shell string.
- For paths, avoid traversal and symlink races. Where threat model warrants, use OS-specific directory handles/openat-like primitives and proper root confinement. `canonicalize` followed by separate open can still be TOCTOU-vulnerable.
- Apply authorization to each resource/action, not merely authentication to outer HTTP route.
- Protect secrets with secret store/environment/permissions; don't `Debug`-print sensitive structs or expose credentials in panic reports. Restrict env dumps and error logs.
- Do not disable TLS certificate or hostname verification; configure certificate roots and version policy appropriate to target and ecosystem.
- Use authenticated encryption and established cryptographic libraries/protocols. Do not invent primitives, use non-CSPRNG for secrets, compare tokens in timing-leaky ways where the threat model calls for constant time, or silently reuse nonces.
- Restrict redirects and remote IP ranges where outbound HTTP is influenced by input; revalidate on redirects and DNS changes where SSRF is meaningful.
- Bound retry, recursion, payload, decompression, iteration, regular-expression work and concurrency; enforce memory and CPU budgets for attacker-influenced paths.
- Consider privilege dropping, filesystem modes, service sandboxing, seccomp/systemd/SELinux where deployment requires. Do not casually demand privileged execution.
- Threat-model FFI boundaries and unsafe dependencies separately; Rust safety claims do not encompass arbitrary C code or unsound dependencies.

### 20.2 Supply-chain controls

- Prefer widely audited maintained dependencies and the standard library; justify each new crate by capabilities actually needed, maintainability, licensing, security history and feature footprint.
- Check `cargo tree --edges features`, `cargo metadata`, advisories with `cargo audit` (when installed and advisory DB accessible), provenance and licenses with a reviewed supply-chain tool such as `cargo deny` (when configured).
- Avoid unmaintained crates, wildcard dependencies, arbitrary Git branch references, unknown build scripts and unchecked proc macros. Review `build.rs`, generated files, and transitive native libraries.
- Reproducible builds require controlled toolchain, dependency lock, compiler flags, native toolchains and build inputs; `Cargo.lock` alone is insufficient.
- Pin container base images appropriately, scan SBOM/artifacts where required, and record exact release provenance. Dev artifacts should not silently differ from deployed artifacts.
- Avoid unsafe semver upgrades; perform changelog review, dependency diff, CI matrix and security checks.

## 21. Documentation standards — rustdoc is part of the API

The agent **MUST** maintain useful documentation whenever changing behavior, configuration, startup, data representation, public types/functions or concurrency guarantees. Rustdoc examples should compile and run whenever feasible.

### 21.1 Where documentation belongs

- `//!` at crate/module entry for purpose, design, architecture and examples.
- `///` on exported APIs: semantics, inputs/units, ownership, concurrency, ordering, errors, panics, safety, blocking/cancellation, examples.
- `README.md`: install/run/test/configure with checked commands, platform requirements, security limitations, API stability, examples.
- `CONTRIBUTING.md`: lint/test/review workflow, version policy, release process.
- `ARCHITECTURE.md`/ADR: durable design decisions, invariants, trade-offs and rejected alternatives; especially shared-state and actor decisions.
- `CHANGELOG.md`: important user-visible behavior, migration and breaking changes.
- OpenAPI/protobuf/JSON Schema/SQL schema: source of truth for actual wire/persisted contract where applicable.

### 21.2 Public API documentation template

```rust
/// Converts a validated count of bytes into a human-readable count.
///
/// This function uses binary units (KiB, MiB). It does not access shared
/// state and is safe to call concurrently from multiple threads.
///
/// # Arguments
///
/// * `bytes` - Nonnegative number of bytes.
///
/// # Returns
///
/// A formatted string using binary scaling.
///
/// # Errors
///
/// This function does not return an error.
///
/// # Panics
///
/// This function does not intentionally panic for valid inputs.
///
/// # Examples
///
/// ```
/// assert_eq!(crate::format_bytes(1024), "1.00 KiB");
/// ```
///
/// # Implementation note
///
/// Keep this example only if the actual implementation exists and is tested.
```

**The block above is a DOCUMENTATION TEMPLATE, not a complete Rust item**: do not paste it into a crate claiming the example passes without implementing `format_bytes`. Omit sections that add no useful information rather than generating boilerplate statements for every function. When a method is fallible, document meaningful error cases; when async, document cancellation and partial effects; when unsafe, include `# Safety`.

### 21.3 Documentation quality rules

- Avoid generated empty descriptions such as “Creates a new X.” where the important constraints are hidden. Focus on contract and rationale.
- Use intra-doc links (e.g., ``[`std::sync::Arc`]`` and ``[`Self::method`]``) where helpful; avoid broken anchors. Document versions/features/OS targets for conditional APIs.
- Distinguish byte count, scalar values, Unicode grapheme clusters, display columns, local time vs UTC; state semantics rather than misleading simplicity.
- Docs must distinguish **thread-safe**, **race-free**, **linearizable**, **lock-free**, **wait-free**, **async**, **nonblocking**, **idempotent**, and **durable**. These words make different promises.
- Doctests are executable and part of CI; use `no_run`, `compile_fail` and `should_panic` only when semantically necessary, not to hide broken examples.
- No fabricated benchmarks, throughput claims, error budgets, feature matrices or compatibility badges. Date time-sensitive statements.

## 22. Testing philosophy: evidence over green checkmarks

**A passing test suite is not proof of correctness if tests never exercise the intended behavior.** A task is done when observable behavior matches the requirement under success, failure, boundary, concurrency, and lifecycle scenarios appropriate to risk.

### 22.1 Test taxonomy

| Test category | What it proves / validates | Mandatory when |
|---|---|---|
| Unit | pure functions, parsing, invariants, state transitions | any nontrivial logic |
| Table-driven | multiple valid/invalid inputs consistently | parser, classifier, many edge cases |
| Integration | real module boundaries, DB/files/network/protocol | external-facing behavior |
| Contract | API/wire/schema compatibility | public or persisted contract changes |
| Property-based | broad invariants and generated counterexamples | parsers, transformations, data structures |
| Fuzz | malformed, adversarial input and panics | security boundary and complex parser |
| Concurrency/stress | interleavings, lock safety, deadlocks, duplicates | concurrent mutable state and channels |
| Loom model | bounded interleaving exploration using instrumented primitives | custom synchronization and atomics |
| Miri | selected undefined behavior / aliasing issues | unsafe/FFI-sensitive code where supported |
| Benchmark/profiling | empirically validates performance changes | any speed/memory optimization claim |
| Soak/load/fault | behavior under load, restart, partial failure | production concurrent services |
| Documentation test | examples compile and meet claims | public rustdoc examples |

Tests should use deterministic seeds, isolated temporary resources, explicit timeouts and cleanup. Random tests should print the seed on failure. Concurrency tests must not use `sleep` as the only synchronization or assert a specific scheduler ordering without a guarantee.

### 22.2 Standard module test pattern

```rust
fn parse_positive(value: &str) -> Result<u32, &'static str> {
    let number = value.parse::<u32>().map_err(|_| "not an integer")?;
    if number == 0 {
        return Err("must be positive");
    }
    Ok(number)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_positive_decimal_numbers() {
        for (input, expected) in [("1", 1), ("42", 42), ("999", 999)] {
            assert_eq!(parse_positive(input), Ok(expected), "input={input}");
        }
    }

    #[test]
    fn rejects_zero_negative_and_non_numeric_inputs() {
        for input in ["0", "-5", "alpha", ""] {
            assert!(parse_positive(input).is_err(), "unexpected success: {input}");
        }
    }
}
```

Notes: assert specific error variants/messages only where public contract depends on them. Test overflow, whitespace and numeric boundaries if requirements demand. Don't "improve" the parser by silently changing accepted formats.

### 22.3 Integration tests must reach real code

- A mock is suitable for isolating business logic, but **not sufficient** to prove a database driver, network client, API integration or filesystem persistence works. Run at least one real integration path with an ephemeral or controlled test service.
- Use temporary directories/ports and clearly isolated test credentials; no developer production account dependency. Test environment availability can be a separately reported skip, **not a fake pass**.
- Don't define both the implementation and test expectation from the same incorrect assumption; compare to normative protocol cases, independent reference behavior or known vectors.
- Verify persisted data by reopening after shutdown, not by reading only the in-memory map.
- Exercise both true positive and true negative decisions for filters/refusal/protocol validation. Test outcome and side effects, not merely logs.
- To verify error handling, inject failures at each boundary (closed channel, full queue, timeouts, malformed data, permission errors, poison/panic when policy matters).

### 22.4 Concurrency tests that can fail on real defects

At minimum for mutable shared state:

1. Multiple writers updating the **same key** at once; final value must not lose updates.
2. Readers and writers overlapping; no inconsistent snapshots and no poisoned/panicked hidden task.
3. Producer faster than consumer; backlog respects configured bounds and sends block/reject as specified.
4. Consumer shutdown before send; sender detects closure and cleans up.
5. Multiple senders exit; receiver observes termination instead of hanging forever due to sender clone leak.
6. Task panic/abort while processing; supervisor returns error and records unfinished work.
7. Cancellation at every suspension point; accepted work isn't silently lost.
8. Graceful shutdown under active traffic; no newly accepted work after drain transition and no indefinite waits.
9. Lock contention/inverted paths; no deadlock, starvation within requirement, or unbounded stall.
10. Repeated randomized/interleaving tests or Loom if a custom synchronization algorithm is implemented.

Example testing the **same-key update** invariant without sleeps:

```rust
use std::collections::HashMap;
use std::sync::{Arc, Barrier, Mutex};
use std::thread;

#[test]
fn simultaneous_updates_do_not_lose_increments() {
    const WORKERS: usize = 16;
    const ITERATIONS: usize = 1000;
    let state = Arc::new(Mutex::new(HashMap::<&'static str, usize>::new()));
    let gate = Arc::new(Barrier::new(WORKERS));
    let mut handles = Vec::with_capacity(WORKERS);

    for _ in 0..WORKERS {
        let state = Arc::clone(&state);
        let gate = Arc::clone(&gate);
        handles.push(thread::spawn(move || {
            gate.wait();
            for _ in 0..ITERATIONS {
                let mut map = state.lock().expect("test lock should be valid");
                *map.entry("same-key").or_default() += 1;
            }
        }));
    }
    for handle in handles {
        handle.join().expect("writer must not panic");
    }
    let map = state.lock().expect("test lock should be valid");
    assert_eq!(map.get("same-key"), Some(&(WORKERS * ITERATIONS)));
}
```

**Limitations:** a stress test is not a proof of all schedules; `expect` is legitimate here because a test must fail loudly on panic/poison. Add focused failure, closure, liveness and timeout tests as appropriate. A test that merely runs many threads and asserts `true` is useless.

### 22.5 Property, fuzz and concurrency model checking

- Define properties that are invariant across generated inputs: parse/serialize round-trip for valid values, stable normalization, deduplication idempotency, invariant conservation, and deterministic order where required.
- `proptest`/`quickcheck` are optional dependencies chosen after project review. Include shrinking and reproducibility. Avoid generators that filter away every difficult case.
- For `cargo-fuzz`, separate fuzz-only code from release builds, set sensible size/time caps and provide a regression corpus. A fuzzer without a well-defined assertion or target parser may yield little value.
- Loom models **only synchronization routed through Loom's instrumented abstractions**; ordinary std types not instrumented do not become magically exhaustively tested. Keep models small and test relevant outcome permutations. Source: [Loom limitations](https://docs.rs/loom/latest/loom/).
- Miri catches many categories of UB in supported executions but does not guarantee all target/FFI semantics, concurrency schedules, platform behavior or performance. Interpret tool output within scope.
- For mutation testing, e.g. using a maintained `cargo-mutants` setup, a surviving mutation can indicate weak test coverage; use judgment rather than indiscriminately maximizing mutation score.

### 22.6 Test hygiene and forbidden shortcuts

- Never use `#[ignore]` to conceal a broken required test. If genuinely external/manual, document reason and provide a dedicated command/matrix.
- No unconditional `assert!(true)`, assertions on mock behavior alone as evidence of integration, snapshot auto-accept to hide regressions, or tests that swallow all errors.
- Do not remove assertions or downgrade CI when a change fails. Fix implementation or explain a genuinely incorrect test with proof.
- Avoid global mutable fixtures, reliance on test execution order, fixed port conflicts, and shared production resources.
- Mock time via injected clocks or Tokio time control when appropriate; do not write flaky timing assertions with tiny wall-clock thresholds.
- Report **tests run** separately from **tests written**, and **tests passed** separately from **tests skipped**.

## 23. Formatting, compiler warnings, and Clippy policy

All emitted `.rs` files should be rustfmt-clean. Compiler and Clippy warnings are actionable. Do not disable a lint globally to avoid a single justified exception; use narrow scoped `#[expect(lint, reason = "...")]` where supported, or scoped `allow` with strong explanation.

### 23.1 Default required local commands

From workspace root, use the toolchain and feature selection matching the repository:

```sh
cargo fmt --all -- --check
cargo check --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cargo doc --workspace --no-deps --locked
```

Additional **required when supported by actual feature policy**:

```sh
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-features --locked
RUSTDOCFLAGS="-D warnings" cargo doc --workspace --all-features --no-deps --locked
```

**Important:** If features are mutually exclusive, build an explicit matrix of valid combinations instead of claiming `--all-features` is always correct. Build and test target-specific code on the relevant OS/CPU/feature sets. In a project with a released binary, also run `cargo build --release --locked` and deployment smoke tests. Where artifacts can be produced from stale incremental caches, investigate with a clean target dir or CI build.

### 23.2 Lint selection and exceptions

- Compiler `-D warnings` on official CI is strong but can break with toolchain updates; pin tested CI toolchain and upgrade intentionally.
- Enable meaningful `clippy::correctness`, `clippy::suspicious`, `clippy::complexity`, `clippy::perf`, `clippy::style` (core defaults vary by lint group and compiler). Review `pedantic` selectively; `nursery` is not automatically production-ready. Avoid enabling all restriction lints blindly.
- Prefer explicit narrow exceptions with a written reason and a test; `#[expect]` alerts when an exception becomes unnecessary. Avoid `#![allow(warnings)]`, `#[allow(clippy::all)]`, or silent broad suppression.
- Never auto-apply `cargo clippy --fix` to an entire repo without reviewing diffs and re-running behavior tests.
- `cargo fmt` and Clippy are not substitutes for human reasoning about concurrency or business invariants.

## 24. CI/CD: enforce the skill automatically

The following Bash script is a **baseline** quality gate for workspaces with compatible feature flags. Place it in `scripts/check-rust.sh`, make executable, and tailor supported features/targets without weakening required checks. Use a pinned toolchain on CI and invoke this script after installing Rust components.

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

printf 'rustc: '; rustc --version
printf 'cargo: '; cargo --version

cargo fmt --all -- --check
cargo check --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps --locked
cargo build --workspace --release --locked

# For mutually compatible feature flags, add an all-features pass:
if [[ "${RUST_ALL_FEATURES:-0}" == 1 ]]; then
  cargo check --workspace --all-targets --all-features --locked
  cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
  cargo test --workspace --all-features --locked
fi

# Supply-chain tools are separately installed and provisioned in CI.
# Never report these as PASS unless actually executed successfully.
if command -v cargo-audit >/dev/null 2>&1; then
  cargo audit
else
  echo 'NOT RUN: cargo audit (cargo-audit not installed)' >&2
fi
if command -v cargo-deny >/dev/null 2>&1; then
  cargo deny check
else
  echo 'NOT RUN: cargo deny (cargo-deny not installed)' >&2
fi
```

**Interpretation:** `cargo-audit` and `cargo-deny` are optional **tools**, but security review is not optional. If the project mandates them, missing binaries or unavailable advisory data must fail CI instead of printing `NOT RUN`. The script checks tooling availability without pretending a skipped check passed. Depending on project maturity, separate quick PR gates from nightly fuzz/load/matrix runs, but require the necessary gates before a production release.

### 24.1 Required CI matrix decisions

- OS: Linux plus macOS/Windows if supported. Check CPU architectures and cross-linker/container assumptions.
- Toolchain: pinned MSRV, pinned production compiler, current stable; consider beta in advisory/nightly jobs. If MSRV is explicitly latest stable, pinned baseline and current stable converge until a new release.
- Features: default, minimal, no-default-features where supported, all compatible combinations, optional backends, TLS variants.
- Targets: lib, bin, integration tests, examples, benches where feasible, doctests, build scripts, docs.
- Data and integration: ephemeral database/queue/TLS service, seeded migrations, expected failure cases, deadline and fault injection.
- Security: advisories, licenses, crate provenance, dependency change approvals, secret scanning, container/OS hardening as needed.
- Reproducibility: `--locked`, pinned compilers/toolchains, controlled native dependencies and deterministic generated sources.

## 25. Performance and resource-efficiency standards

**Never fabricate throughput, speedups or memory-usage claims.** A fast-looking implementation can be catastrophically slow under contention or realistic payload sizes. Before altering code for optimization:

1. Specify target metric (p50/p95/p99 latency, throughput, allocated bytes, peak RSS, CPU, tail drop rate), units and workload.
2. Profile baseline using realistic inputs/traffic. Identify bottleneck in flamegraph/profiler, allocator metrics, contention trace, query plan or microbenchmark.
3. Form a hypothesis and select the smallest measurable change.
4. Measure before/after with equivalent environment, warmed caches where appropriate, confidence/repetition and noise characterization.
5. Verify behavior doesn't change; add regression test/benchmark. Document the trade-off and resource cost.

### 25.1 Idiomatic optimizations

- Pass borrows rather than cloning; preallocate with `Vec::with_capacity`/`String::with_capacity` **when bounded size is known**.
- Prefer `&[u8]`/streaming for large payloads rather than repeated copies/concatenation; avoid quadratic string building.
- Use iterators/`for` loops based on clarity; both can optimize well. Do not claim iterator chains are always faster or loops are always faster.
- Reuse HTTP clients, connection pools and heavyweight immutable config. Avoid long-lived shared mutable cache if cache invalidation/consistency is undefined.
- Partition/shard only when contention warrants; extra locks/threads can hurt throughput.
- Avoid `format!`/`to_string()` in hot error-free paths when a borrowed representation suffices; measure before micro-optimizing.
- Avoid `Arc` for every value by default; refcount traffic has cost. Use owning `Vec`/`Box`/stack values where lifetime/ownership permits.
- For parse/encode loops, pay attention to integer casts, bounds checks, UTF-8 validity, SIMD assumptions and buffer lifetime.
- Choose async for high-concurrency *waiting*, thread pools for CPU-bound work. Concurrency increases resource utilization, not necessarily speed.
- Bound cache size and eviction policy, not just expiry; track memory pressure and eviction churn.
- Optimize file I/O with batching and durability requirements in mind; more buffering can improve throughput while increasing data loss on crash.

### 25.2 Observability as performance evidence

- Instrument request rates, response codes, latency histograms, queue depths, queue wait, active tasks, capacity rejects, lock contention, memory, retry count, error classes and shutdown duration.
- Use tracing spans with stable IDs, but never attach passwords, auth tokens, protected payloads or unbounded data as span fields.
- Cardinality is a resource: avoid user ID, raw URL or request ID as unbounded metric labels. Logs can carry trace identifiers with retention/redaction controls.
- Assert SLO-relevant behavior through load tests rather than basing decisions on synthetic single-thread loops alone.

## 26. Deployment and service operations

- Applications need correct exit codes, signal handling, readiness/liveness, startup validation, graceful shutdown and no silent partial initialization.
- Validate config once at startup; define env/file/CLI precedence, secret source, reload semantics, permissible values and error messages.
- Avoid ambient directory assumptions. Use explicit paths/working directory, permission checks and safe creation modes.
- Follow principle of least privilege; no running as root by default. On Linux with SELinux enforcing, don't circumvent policy with blanket disablement; configure narrow service labeling and ports.
- `systemd` service or container should have resource limits, restart semantics, meaningful health endpoints and permissions matching deployments.
- Docker multi-stage builds should pin bases as policy demands and produce minimal runtime image including required CA certs, libc/musl/native libs and time zone data if necessary.
- Handle time carefully: use `Instant` for elapsed durations, `SystemTime`/UTC for timestamps, explicit parsing/formatting policy, monotonic deadlines for timeouts. Timezone offsets/DST are business logic, not arithmetic constants.
- Handle disk-full, read-only FS, stale temp files, partial writes, broken pipes, interrupted syscalls and missing permissions. Consider signal races and `SIGPIPE` behavior where applicable.
- Keep migrations/backups and rollback strategy appropriate to persistent schema changes. Validate restores, not just backup creation.

## 27. Cross-platform, low-level and embedded code

- Do not assume `usize` is 64-bit, integer endianness, filesystem case sensitivity, separator shape, path encoding as UTF-8, available symlinks, atomic support, or OS-specific signal APIs.
- Use `Path`/`OsStr`/`OsString` for platform-native paths; avoid `to_str().unwrap()` for arbitrary paths. Use `PathBuf` for owned paths.
- Conditional compilation (`#[cfg]`) must be tested on supported targets. Keep platform-specific code in contained modules with a common typed interface.
- Ensure targets supporting `no_std` and embedded use proper availability gates (`core`, `alloc`), no unbounded heap expectation, and target-specific atomic support. Do not introduce Tokio into a `no_std` crate without an explicit compatible architecture.
- For OS syscalls, use maintained wrappers when available; check error codes, alignment, descriptor ownership, close behavior, blocking modes and EINTR handling.
- FFI layout/ABI is a contract; Rust's default struct layout is not a cross-language ABI. Use `#[repr(C)]` where specified and no unchecked punning.
- Test on representative CPUs/OSes with actual native libs, not only host cross-compilation.

## 28. Common Rust pitfalls and mandatory remedies

| Sloppy or misleading pattern | Failure mode | Required remedy |
|---|---|---|
| Sending pointer address as channel job | ownership/lifetime/aliasing ambiguity | move owned message; actor or scoped borrow |
| `Arc<T>` claimed to protect mutable `T` | refcount ≠ interior synchronization | immutable reads or interior `Mutex`/`RwLock`/atomic |
| Mutable global map with no model | data race with unsafe or illegal borrowing | actor or mutex/rwlock; inventory all mutation paths |
| Lock per `get` and lock per `set` for transaction | check-then-act race | one atomic critical section/transaction |
| `RwLock` everywhere for speed | unmeasured contention/fairness | use mutex first; benchmark |
| std `MutexGuard` across `.await` | deadlock / stalled executor | scoped sync method, drop before await |
| `tokio::sync::Mutex` everywhere | extra overhead/no benefit | sync mutex for brief data-only sections |
| `std::thread::sleep` in async | blocks worker | async timer or blocking pool |
| `tokio::spawn` per incoming item | unbounded memory/scheduling | semaphore/admission + bounded queues |
| Detached task without tracking | silent work loss on exit | parent join or supervised lifecycle |
| `channel()` unbounded by default | memory pressure / OOM | bounded sync/async channel |
| `tx.send(...).unwrap()` in service | process/task panic on normal close | handle shutdown/disconnect explicitly |
| `.unwrap_or_default()` on I/O parse errors | silent data loss | propagate classified error |
| `expect()` on user input | crashable input path | validate and return `Result` |
| `unsafe impl Send` to fix compile | unsoundness | redesign, never paper over compiler |
| `mem::transmute` for convenience | invalid layout/lifetime | typed conversion / audited narrow FFI |
| Blind `.clone()` in tight loops | allocations and unexpected shared state | borrow/move, profile |
| `Box::leak` for `'static` task | permanent leak | move ownership/scope/Arc |
| `HashMap` iteration for stable output | nondeterminism | sort/BTreeMap/canonical serializer |
| Assume serde deserialization validates input | invalid domain state | semantic validation |
| `as` for untrusted integer narrowing | truncation | `TryFrom`, checked arithmetic |
| DIY thread-safe singleton | initialization and lifetime complexity | standard `OnceLock`/`LazyLock` if appropriate |
| Logging-only on critical failure | caller receives false success | return/propagate status and log at boundary |
| Unlimited retry loop | overload amplification | bounded attempts/deadlines/backoff+jitter |
| `TODO` in production path | unimplemented behavior | implement or declare task incomplete |
| Hardcoded sample API response | tests pass without integration | real transport/contract test |
| Remove failing assertion | masks bug | fix code / prove test wrong with independent evidence |
| Ignore `JoinError` | silent panics/work failure | await and classify failures |
| Panic catch as healthiness | invalid state continues | controlled restart or fail-closed |
| Unbounded `collect` from untrusted stream | memory exhaustion | streaming/caps/admission |

## 29. Code review requirements

Every Rust pull request authored or reviewed by the agent **MUST** include a human-readable rationale proportional to change size. For concurrency work, include an **ownership/synchronization ledger** like this:

| State/resource | Mutating owner(s) | Reader(s) | Synchronization/communication | Lifetime/teardown |
|---|---|---|---|---|
| Request config | constructed at startup, then immutable | many workers | `Arc<Config>` immutable | drops after final worker |
| Pending jobs map | single coordinator actor | coordinator; replies are snapshots | bounded command queue | drain on shutdown |
| Request counter | multiple workers | metrics reader | `AtomicU64` relaxed; independent measurement | process lifetime |
| Persistent DB | DB engine transactions | service pool | transaction isolation + pool limits | close after draining |

The ledger is a **template**, not a claim every project has these resources. Fill from actual code; include every shared mutable field and independent lifecycle owner. For each `Arc`, `Mutex`, `RwLock`, channel or atomic, reviewers ask:

1. Why does this state have multiple owners? Could it be owned by one task?
2. Is the inner data immutable or mutable? If mutable, what protects it?
3. Are there access paths outside this protection? Any FFI/raw-pointer alias?
4. Can a compound invariant be violated between operations?
5. What is the maximum number of queued messages, tasks and allocated bytes?
6. Does every producer handle the receiver having disappeared? Does the receiver terminate when all producers are gone?
7. Is an ACK a guarantee of enqueue, execution, or persistence?
8. Do lock guards stay in a known lexical scope and avoid `.await`/I/O?
9. Are failed/panicking tasks observed? Are retries finite and idempotent?
10. Can shutdown interrupt/abort work? How is unfinished work surfaced?
11. Are ordering/fairness assumptions guaranteed by chosen primitive?
12. Are concurrency tests deterministic enough to be useful and adversarial enough to fail real bugs?

**A reviewer must not rubber-stamp a patch because rustfmt, Clippy and tests are green.** Review actual error paths, protocol conformance, security, durability and integration boundaries.

## 30. Architecture decision record for nontrivial concurrency

Store a short decision record at `docs/adr/NNNN-<topic>.md` or existing repository equivalent. Minimum fields:

```markdown
# Decision: [concise title]

Status: Accepted / Proposed / Superseded
Date: YYYY-MM-DD

## Context and requirements
- Workload, contention, ordering, consistency, cancellation, reliability, limits

## Chosen state ownership model
- Owner(s), readers, lifetime, thread/task boundaries
- Which values are moved, immutably shared, or mutable-shared

## Synchronization and backpressure
- Mutex/RwLock/actor/atomic choice and why
- Lock order and maximum hold scope
- Queue/task/byte bounds and overload behavior

## Failure and shutdown semantics
- Closed channel, full queue, timeout, panic, cancellation, drain
- Idempotency, acknowledgements, persistence guarantees

## Alternatives rejected
- Why simpler sequential, lock, actor or sharding designs do not fit

## Verification
- Tests, Loom/Miri/fuzz where applicable, benchmark and measured workload
- Remaining risks, operational metrics, maintenance owner
```

Do not demand an ADR for every small change; require it when the long-term correctness of the architecture depends on synchronization or lifecycle decisions not obvious from the types.

## 31. Agent implementation protocol and anti-shortcut controls

The agent's role is **delivery**, not convincing a reviewer that delivery occurred. It must obey the following protocol for every issue:

### Step A — translate requirements to executable acceptance criteria

- Extract explicit use cases and failure modes. State constraints: version, edition, environment, feature flags, authorization, performance, file formats, external services.
- Record unknown assumptions as such. If the task can proceed safely, pick a conservative and reversible implementation; never quietly redefine what 'done' means.
- Define tests **before** or alongside implementation that would fail if feature is absent (red/green where feasible).
- Identify dependencies/services needed for the **real** integration test; do not substitute a fake in the final verification claim.

### Step B — inspect and avoid unneeded changes

- Trace entry points, interfaces, call sites, storage and feature selection before editing.
- Keep patch scope narrow. Do not replace working code or introduce new libraries for aesthetic reasons.
- Preserve compatibility unless the task explicitly requires a versioned breaking change.

### Step C — implement actual behavior

- Use real filesystem, network, database, JSON, concurrency primitives, etc. according to the actual contract.
- If external dependencies are unavailable, keep the implementation honest with a clear error; do not hardcode success payloads to conceal missing integration.
- Place fallible operations at explicit error boundaries; no swallowed `Result`s.
- Implement shutdown and error handling at the same time as the happy path, not as an unbounded future TODO.

### Step D — independent adversarial review

- Run the anti-slop search/checklist (§39). Inspect suspect uses of `unsafe`, raw pointers, `Arc`, lock guards, `unwrap`, `spawn`, `channel` and mocks.
- Compare feature acceptance criteria to actual code paths. Force negative tests to demonstrate rejection. Where feasible, deliberately break an invariant and show the regression test fails, then restore it.
- Verify that no test assertions were weakened, ignored, or snapshot-overwritten merely to make CI green.

### Step E — evidence-based delivery

- Run the gate script and additional integration/target tests; report each meaningful command with PASS/FAIL/NOT RUN.
- If verification cannot run, name the tool/service blocking it and exact repro instructions. **Never report green because a command appears syntactically correct.**
- Provide a concise traceability summary: requirement → implementation file/function → test(s) → observed result.
- No fabricated screenshots, logs, benchmark numbers, or statements of production readiness.

## 32. Multi-agent implementation and adversarial verification

When multiple coding agents work on a larger project, separation of duties must not create unreviewed shortcuts:

- **Planner**: owns acceptance criteria, compatibility, ownership ledger and risk matrix; does not approve work it has not verified.
- **Implementer**: owns bounded code changes and tests; cannot self-declare integration passed based on mocked behavior.
- **Verifier**: independently reads diff, runs actual tests where available, inspects unstated invariants and tries to falsify requirements. Must not trust implementer's summary.
- **Security/concurrency reviewer** (when relevant): examines unsafe code, channel payloads, lock scope, atomic ordering, shutdown, queue bounds and threat model.
- **Integrator**: resolves merge conflicts, validates all supported feature combinations and end-to-end behavior, checks no agent weakened CI.

**Adversarial loop:** verifier returns a concrete failing test/contract discrepancy; implementer fixes root cause; verifier reruns. Never implement a perpetual loop with no progress budget or stop condition. Track defects by file/line, reproducible commands and observed behavior. Respect human cancellation and compute/resource limits. When a requirement is impossible without an external service or user credential, report dependency rather than manufacturing success.

## 33. Review of generated code and AI-specific failure modes

AI-generated Rust often fails in recognizable ways. Actively search for:

- Misunderstanding ownership and using `Arc<Mutex<...>>` for every lifetime error instead of designing a true owner.
- Copy-pasting Go patterns (channels containing pointers, unbounded goroutine/task per request, shared maps without valid synchronization) into Rust.
- Invented APIs, crate features, trait impls, nightly-only functions or wrong Tokio feature combinations.
- Fake "async" wrappers around blocking calls; synchronous locks held during `.await`.
- Unnecessary `Send + Sync + 'static` bounds, fake `unsafe impl` or `Box::leak` workaround.
- A single enormous coordinator type holding unrelated state and >10 `Arc<Mutex<_>>` fields.
- A queue that keeps every sender clone alive forever or has no bounded backpressure.
- Error conversion via `.ok()`/`unwrap_or_default()` that makes failures indistinguishable from empty success.
- Tests that only assert mocked function was called but never validate actual persisted/remote result.
- Arbitrary port numbers, magic constants, randomized tests without seeds, sleep-based synchronization.
- `#[allow(dead_code)]` hiding an uncalled implementation; code added but never wired into entry point.
- New structs/functions that are not referenced by any production execution path.
- Regression introduced by refactoring unrelated files or library API.
- README documenting features not implemented in current tree.
- CI snippet referencing tools not installed or commands whose failures are ignored (`|| true`).
- Incorrectly treating warnings as errors in a different toolchain without testing that toolchain.
- Misleading claim that safe Rust eliminates logical races, starvation or deadlocks.

## 34. Rust idioms that must not be mechanically ported from Go/C++/Java

Rust has its own optimal vocabulary. Apply the language's guarantees rather than translating syntax from another ecosystem.

| Other-language habit | Idiomatic Rust alternative | Why it matters |
|---|---|---|
| Pass pointer to struct in a channel | move owned struct, `Box<T>`, or explicit shared immutable `Arc<T>` | channel transfers ownership, not arbitrary access rights |
| Shared mutable map plus implicit runtime discipline | exclusive owner, `Arc<Mutex<HashMap>>`, actor or verified concurrent map | synchronization is part of types |
| Global mutable package variables | injected owned state, `OnceLock` for immutable initialization | controls testing and lifecycle |
| Exceptions for ordinary I/O | `Result<T,E>` and `?` | errors explicit and typed |
| `nil` sentinel for absence/error | `Option<T>` or `Result<T,E>` | separates absence from failure |
| `interface{}`/`any` for domain data | enums, traits and generics | preserves exhaustiveness/contracts |
| Classes and broad inheritance trees | composition, traits and modules | avoids accidental APIs and deep hierarchies |
| Manual `new`/`delete` and dangling raw pointers | owned types, RAII, borrowing | lifetime checked and cleanup scoped |
| Copy giant struct for every call | `&T` for reading, owned value transfer for jobs | avoids unnecessary allocations |
| Defensive runtime reference counting everywhere | lifetime borrowing when sufficient | smaller mental/runtime cost |
| A thread for each connection | async task for I/O with bounded admission | scalable waits, not unlimited CPU |
| Defer cleanup to an asynchronous finalizer | `Drop`/RAII, explicit async shutdown | Drop cannot `.await`; cleanup protocol matters |
| `null`-equivalent by `Default::default()` | explicit `Option` and domain validation | prevents silent defaults |
| `catch` and log all errors | propagate typed failures to capable boundary | observability, not false success |
| Hand-rolled thread-safe queue | tested bounded channel/pool | avoids subtle memory and shutdown bugs |

**Rust-specific capabilities to intentionally leverage:** enum pattern matching, ownership and borrows, `?`, `From`/`TryFrom`, iterators, slices, the `entry` API, `Drop`, `Pin` when genuinely required, `Send`/`Sync` auto traits, thread-scoped borrows, `OnceLock`, `Cow` where appropriate, standard time and path types, compile-time feature flags, rustdoc examples, doctests, Clippy and stable edition tooling.

## 35. Common project archetypes and their standards

### 35.1 Libraries

- Maintain smallest stable public surface, semver-aware versioning, documented MSRV and `no_std`/feature matrix when promised.
- Errors are structured and users can classify them; avoid app-centric loggers and global runtime initialization.
- Avoid hidden network/filesystem access in constructors unless explicitly documented.
- Include examples/doctests, integration tests and public API compatibility review.

### 35.2 CLIs and developer tools

- Deterministic exit statuses, stdout/stderr contracts, correct Unicode/path handling, prompt/no-prompt mode, signal propagation and dry-run where appropriate.
- Sanitize credentials in verbose logs; use atomic output writes where durability matters. Return nonzero on actual failure; don't merely print a warning and exit 0.
- Test argument combinations, missing files, invalid UTF-8 paths as applicable, subprocess failures and output snapshots with semantic assertions.

### 35.3 Servers and long-lived daemons

- Bounded intake, bounded channel sizes, connection caps, structured concurrency, health/readiness, graceful shutdown, timeouts and observability.
- Service owns state and resources; request handlers do not spawn untracked background work.
- Backpressure/rejection/error is part of protocol; read-after-write and persistence ACK semantics documented.
- Exercise real integration under load and failures; control socket/file/CPU/memory usage.

### 35.4 Cryptographic and financial code

- Use vetted algorithms/libraries, domain separation and explicit units/decimal precision; avoid floating-point money unless contract mandates and error budget is explicit.
- Cryptographic key material never logged; memory exposure is minimized within language/OS limitations. Preserve constant-time properties when required.
- Transactions must be idempotent and durable; tests cover duplicate submissions, reorder, partial failures, overflow/underflow, decimals and audit trail.
- Authorization and signing invariants deserve independent adversarial review, even if the Rust compiler finds no memory safety problem.

### 35.5 Embedded/FFI/OS integration

- Target-specific `no_std` and allocator assumptions, correct ABI/layout, lifecycle, ISR safety and atomic availability.
- Unsafe boundaries documented and reviewed; tests cross language/OS boundary and fail on invalid null/length/ownership cases.
- Avoid relying on behavior only observed on the developer's architecture.

## 36. Rust release upgrades and deprecation procedure

When upgrading compiler, edition or core dependencies:

1. Inspect official release notes and rust-version changes; identify stabilized vs nightly features.
2. Run existing pinned build/tests **before** upgrade to record baseline.
3. Update compiler pin, `rust-version`, CI matrix and upgrade documentation intentionally. Edition changes require running and reviewing `cargo fix --edition` when applicable, then changing edition and rebuilding.
4. Review rustfmt differences, Clippy additions, std API behavior, linkers, unsafe rules and platform regressions.
5. Audit third-party dependency compatibility/feature flags/lockfile changes and MSRV interactions.
6. Run full supported OS/feature/target tests, security scan and smoke/load tests for production binaries.
7. Roll out with a rollback/compatibility plan; document public API or behavioral changes.

**Do not** assume that a 2026 compiler necessarily implies a Rust 2026 edition. Editions are independent opt-in compatibility boundaries. Similarly, do not silently update an existing published crate's MSRV when adding a convenient new std API.

## 37. Incident debugging and defect correction

Fix causes, not symptoms. Incident handling follows:

- Gather failure evidence and reproduction, preserving sensitive-data controls.
- Classify crash, panic, memory growth, contention, deadlock, starvation, lost update, duplicate work, IO error, rate-limit, corrupt persistence or inconsistent contract.
- Trace thread/task ownership, in-flight work, channel state, lock state, deadlines, cancellation and external side effects.
- Reproduce with controlled input/scheduler/failure injection; minimize test case without omitting essential integration.
- Write a regression test capable of failing on the pre-fix behavior.
- Correct the invariant or protocol; do not suppress panic, extend timeouts without bounds or insert arbitrary sleeps as a workaround.
- Verify under normal and adversarial load; add detection metrics and operational runbook notes.

For deadlocks: produce a wait-for graph of locks, channels and actor request/replies. For race conditions: define intended atomic transition and its linearization point; a mutex on only one read is not sufficient. For memory growth: count owned objects, sender clones, queued payload bytes, Arc strong counts if helpful, and caches. For cancellation bugs: enumerate `.await` positions and externally committed side effects.

## 38. Required verification report template

Before answering that a Rust change is complete, use a factual report similar to:

```markdown
### Implemented
- Requirement A -> `src/foo.rs::method` -> behavior added
- Requirement B -> `src/bar.rs::worker` -> shutdown and error handling added

### Concurrency ownership
- Mutable `jobs` map is owned solely by `Coordinator` task.
- Commands are owned values sent on a bounded queue (capacity N).
- Shutdown drains accepted commands and reports incomplete requests.

### Checks actually performed
- PASS: `cargo fmt --all -- --check`
- PASS: `cargo clippy --workspace --all-targets --locked -- -D warnings`
- PASS: `cargo test --workspace --locked` (X tests)
- NOT RUN: end-to-end database integration (service unavailable)

### Remaining risks
- [specific risk and reproduction, or "none identified after listed checks"]

### Claim boundary
- No unexecuted test, benchmark or live API call has been represented as PASS.
```

The template's PASS entries are **illustrative only**. Replace with actual results; remove nonexistent steps. If nothing was executed, state **NOT RUN for all checks**. A clean report with unrun tests is better than a fabricated green report.

## 39. Mandatory anti-slop audit checklist

Before completion, answer each question from inspected source and executed verification; **NO** to a blocker means not done. Record **N/A with reason** if truly irrelevant.

### Correctness and architecture

- [ ] The implementation exists in the actual production execution path and implements the requested behavior.
- [ ] No TODO, stub, mock, fixed sample return, fake service or unconditional success remains in production path.
- [ ] Ownership of every mutable resource is clear; public APIs accurately express borrows/moves/failures.
- [ ] Critical invariants are encoded in types or checked atomically under a valid owner/transaction.
- [ ] No panic on ordinary malformed input or recoverable I/O; errors preserve source/context.
- [ ] Compatibility of CLI/API/wire/persistence/MSRV/edition/features assessed and documented.

### Concurrency and channels

- [ ] **Every channel message is safe to transfer**; no unchecked raw pointers, integer-encoded pointers, lifetime erasure or unexplained `unsafe impl Send`.
- [ ] Messages are owned values by default; shared `Arc` payloads are deliberately immutable or correctly synchronized.
- [ ] Shared mutable maps/collections each have exclusive ownership or an appropriate lock/actor/concurrent map design.
- [ ] Shared immutable collections are recognized as safe without needless locks where types permit.
- [ ] All multi-step operations requiring atomicity use one critical section/transaction or verified protocol.
- [ ] Every queue/task/worker/memory-intensive operation has bounded admission and explicit overload policy.
- [ ] No lock guard is held across `.await` or potentially blocking arbitrary I/O; lock ordering is understood.
- [ ] Channel full/closed handling, sender drops, task panics and shutdown behavior are exercised.
- [ ] Every spawned task is joined, supervised or explicitly justified as detachable.
- [ ] `select!` cancellation and in-progress external side effects are accounted for.
- [ ] Atomic orderings have proofs; no custom lock-free pointer lifecycle without expert review.

### Tests and verification

- [ ] Happy path, boundaries, invalid inputs and failure cases have tests that **could fail** for a broken implementation.
- [ ] Concurrency tests include same-key writers, producer/consumer disconnect, liveness, resource bounds and shutdown as relevant.
- [ ] Real integration is tested separately from mock-only unit tests where external behavior is claimed.
- [ ] Tests were not weakened, ignored or rewritten to accept a bug.
- [ ] Formatting/Clippy/build/tests/docs and required supported target/feature checks actually ran, or are marked NOT RUN.
- [ ] Security, license, input bounds, secrets and dependency review completed for the changed scope.
- [ ] Benchmark claims have reproducible before/after evidence and did not introduce correctness regressions.

### Documentation and delivery

- [ ] Public rustdoc, architectural assumptions, runbooks/config and changelog updated where necessary.
- [ ] No fake compile/test/benchmark/API proof, fabricated result or misleading completion language.
- [ ] The final response states actual changes, verification evidence, limitations and next steps without concealing blockers.

**Non-negotiable:** if any relevant unchecked box hides a correctness/safety defect, do not mark work complete. If a check cannot be executed due to missing access or tooling, honestly report that limitation and provide reproduction commands; do not claim the missing evidence exists.

## 40. Definition of Done — severity matrix

| Severity | Examples | Gate |
|---|---|---|
| **P0 — unsound/unsafe** | unchecked pointer channel, illegal concurrent map mutation through unsafe, secret leak, unsound `Send/Sync`, memory UB | **BLOCK**; redesign and verify |
| **P1 — behavior/correctness** | lost update, silent task failure, forged pass, unbounded queue, panic on user input, missing durable ACK | **BLOCK** until tested fix or explicitly incomplete |
| **P2 — robustness/maintenance** | insufficient observability, poor error context, missing boundary test, missing doc of cancellation, excessive clone | **FIX** before production where material |
| **P3 — style/optimization** | confusing name, needless allocation without demonstrated impact, inconsistent formatting | **FIX** opportunistically; never trump P0/P1 |

A project cannot be marked "production ready" simply because its P0/P1 violations are absent: deployment security, operational controls, realistic integration, compatibility and release validation remain required.

## 41. Authoritative reference library and validation notes

**Version/release:**

- [Rust releases: newest published stable](https://blog.rust-lang.org/releases/)
- [Rust 1.99.1 release announcement — 2026-10-15](https://blog.rust-lang.org/2026/10/15/Rust-1.99.1/)
- [Rust Edition Guide — Rust 2024](https://doc.rust-lang.org/edition-guide/rust-2024/)
- [Cargo `rust-version` reference](https://doc.rust-lang.org/cargo/reference/rust-version.html)
- [Rust Reference](https://doc.rust-lang.org/reference/)

**Language/API/safety:**

- [The Rust Programming Language](https://doc.rust-lang.org/book/)
- [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/)
- [Rustonomicon](https://doc.rust-lang.org/nomicon/)
- [Rustonomicon — data races and race conditions](https://doc.rust-lang.org/nomicon/races.html)
- [Rustonomicon — Send and Sync](https://doc.rust-lang.org/nomicon/send-and-sync.html)
- [Rust standard library — Arc](https://doc.rust-lang.org/std/sync/struct.Arc.html)
- [Rust standard library — RwLock](https://doc.rust-lang.org/std/sync/struct.RwLock.html)
- [Rust standard library — mpsc channel](https://doc.rust-lang.org/std/sync/mpsc/)
- [Rust Book — ownership transfer via channels](https://doc.rust-lang.org/book/ch16-02-message-passing.html)
- [Rust Book — shared-state concurrency](https://doc.rust-lang.org/book/ch16-03-shared-state.html)

**Async/task lifecycle:**

- [Tokio Mutex — selection guidance](https://docs.rs/tokio/latest/tokio/sync/struct.Mutex.html)
- [Tokio bounded mpsc channel](https://docs.rs/tokio/latest/tokio/sync/mpsc/fn.channel.html)
- [Tokio JoinSet — task tracking and shutdown](https://docs.rs/tokio/latest/tokio/task/struct.JoinSet.html)
- [Tokio runtime overview](https://docs.rs/tokio/latest/tokio/runtime/index.html)

**Quality and testing:**

- [Cargo Book — CI](https://doc.rust-lang.org/cargo/guide/continuous-integration.html)
- [Clippy lints and groups](https://rust-lang.github.io/rust-clippy/master/index.html)
- [Rust Reference — lint attributes and `expect`](https://doc.rust-lang.org/reference/attributes/diagnostics.html)
- [Rustdoc tests](https://doc.rust-lang.org/rustdoc/documentation-tests.html)
- [Loom model checking limitations](https://docs.rs/loom/latest/loom/)
- [The Rust Performance Book](https://nnethercote.github.io/perf-book/)
- [Cargo Book](https://doc.rust-lang.org/cargo/)

**Agent skill packaging:**

- [Agent Skills specification](https://agentskills.io/specification)
- [OpenCode skill discovery and paths](https://docs.opencode.ai/docs/skills/)

**Source policy:** Prefer version-matched official Rust/Cargo/std docs, official Tokio docs for Tokio behavior, and a crate's own docs.rs release page. Check the version displayed in docs before using an API in an older pinned project. Third-party blog posts are secondary evidence. A reference link is not proof that its current contents are appropriate for the project's target compiler, platform and feature set.

## 42. Installing and enforcing this skill in coding agents

### 42.1 OpenCode (verified official paths)

For an **all-project/global** install of the deployable skill directory, copy it to:

```text
~/.config/opencode/skills/rust-engineering-standards/SKILL.md
```

For repository-specific override:

```text
<repository>/.opencode/skills/rust-engineering-standards/SKILL.md
```

Compatible paths include `.agents/skills/rust-engineering-standards/SKILL.md` and `.claude/skills/rust-engineering-standards/SKILL.md`. Keep the supporting `references/` files alongside `SKILL.md` in the skill directory, preserving relative paths. OpenCode advertises skills by metadata and loads their full body on demand. Therefore **a file merely existing on disk does not mean the model has loaded it**. Add repository instructions requiring activation on Rust work, or explicitly load it using the runtime's supported skill mechanism. Read [OpenCode skill docs](https://docs.opencode.ai/docs/skills/).

### 42.2 Suggested `AGENTS.md` rule (copy into existing instructions)

```markdown
## Rust — mandatory engineering policy
- For every task that writes, edits, reviews or tests Rust (`.rs`, Cargo manifests,
  build scripts, Rust FFI), activate `rust-engineering-standards` first.
- Read the mandatory top-level skill rules and the sections of its reference
  needed for the task; for concurrency read the entire concurrency section.
- Use newest verified stable Rust for new code; preserve existing project
  MSRV/edition unless upgrade is explicitly approved.
- Never use raw pointers as a workaround for channel payload ownership.
- Never perform unsynchronized concurrent mutation of maps/collections.
- Use bounded channels/tasks and explicit cancellation and shutdown.
- Never present mocks, TODOs, bypassed checks or unrun tests as success.
- Before completion perform the skill's anti-slop audit and report checks.
```

Do not overwrite an existing `AGENTS.md` without reading and merging existing policies. If another system instruction requires a stricter safety rule, the stricter rule wins. Skills influence model behavior but **must be reinforced by code review and real CI gates**; prose alone cannot ensure compliance from any local or hosted model.

### 42.3 Portability and progressive disclosure

Agent Skills recommends a short entry `SKILL.md` with detailed guides in adjacent `references/` files to conserve context. If this standard is packaged into a short entry + long reference, **the normative requirements and anti-slop checklist remain applicable**. The entry should direct the model to read the relevant reference sections before implementation, and CI/review should enforce the rest.

---

**Final policy:** write Rust whose correctness follows from ownership, types, validated invariants, synchronization, bounded resources, explicit failure handling and independently executed tests. Never trade these guarantees for fewer lines, easier compilation, simulated success or a green checkmark. When a Rust compiler rejects an unsafe ownership idea, **change the design, not the safety contract**.
