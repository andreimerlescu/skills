---
name: rust-engineering-standards
description: >-
  Mandatory senior-level Rust engineering standard for every Rust implementation,
  review, refactor, FFI, or Cargo task. Prevents pointer-through-channel slop,
  unsynchronized shared maps, unbounded concurrency, dropped task errors,
  fabricated passing tests, unchecked unsafe code, and incomplete implementations.
  Enforces idiomatic ownership, bounded workers, real tests, rustdoc, security,
  and independently verifiable delivery. Load for ALL Rust work.
metadata:
  target-model: 'DeepSeek v4 155GB and other coding agents'
  minimum-rust-at-publication: '1.99.1'
  edition: '2024'
  policy-date: '2026-10-19'
---

# Rust Engineering Standards — Mandatory Agent Skill

**ACTIVATE FOR EVERY RUST TASK.** This includes `.rs`, `Cargo.toml`, `build.rs`, `rust-toolchain.toml`, tests, architecture, FFI, macros, refactoring, reviews, releases and Rust-bearing deployment code. It applies equally to solo work and multi-agent projects.

**This file is the always-on contract.** The complete, detailed engineering standard, rationale, examples, checklists, and authoritative documentation are in [references/RUST_ENGINEERING_STANDARD.md](references/RUST_ENGINEERING_STANDARD.md). For actual Rust work, **read the relevant numbered sections before implementing**. For changes involving threads, tasks, channels, maps, locks or atomics, **read §§6 and 8–16, 22, 29 and 39** of the reference before editing. For any final delivery, apply **§39 anti-slop audit** and **§40 Definition of Done**.

## 1. Non-negotiable release blockers

The following patterns MUST NOT enter working production code without a specific, approved exception (and explicit proof where unsafe):

1. **Raw pointers, integer-encoded addresses, leaked references, `transmute`, or unchecked `unsafe impl Send/Sync` as channel payload or borrow-checker workaround.** Move owned messages instead.
2. **Unsynchronized concurrent mutation of `HashMap`, `BTreeMap`, `Vec`, cache, connection or other state.** Every mutable resource needs one exclusive owner, sound lock, atomic protocol, transaction or audited concurrent data structure.
3. **Claiming `Arc<T>` makes mutable `T` thread-safe.** It shares ownership; it does not synchronize the value. Immutable `Arc<HashMap<...>>` read-sharing is valid when contents are `Sync`.
4. **Unbounded tasks, OS threads, messages, allocations, retries, cache growth or connections** for workloads without proven finite limits. Bound both job count and payload size.
5. **std lock held across `.await`, or locks held through potentially blocking network/disk I/O.** Keep lock scope short and explicit; prefer actor ownership for complex mutable state.
6. **Background work silently detached, unobserved task panics, channels with forgotten sender clones, or incomplete shutdown.** Track joins, supervision, cancellation, queue closure and drain.
7. **Panics for ordinary external errors, swallowed `Result`, fake defaults on parse failure, and hidden partial writes.** Handle errors at the proper boundary.
8. **Fake tests, test-only implementations advertised as real, TODOs in active execution paths, assertions that cannot fail, disabled tests or invented test logs/results.**
9. **Unsafe Rust without a justified invariant, reviewed safety comment, correctly bounded API and tests.** Safe Rust is the default.
10. **Secrets in logs, unvalidated external input, unbounded parser allocation, auth bypass, non-idempotent replay or silent compatibility changes.**

If the language compiler rejects an idea, **redesign it**. Do not weaken ownership or thread-safety guarantees just to compile.

## 2. Version and edition requirements

**Verified on 2026-10-19:** latest released stable Rust is **1.99.1**; latest stable edition is **2024**. Official release: https://blog.rust-lang.org/2026/10/15/Rust-1.99.1/. On each new project, check https://blog.rust-lang.org/releases/ and choose the newest released **stable patch** as the minimum (`[package] rust-version`). The static 1.99.1 baseline is a **floor**, not a ceiling. Use `edition = "2024"` until an officially newer edition exists. Pin the tested compiler in `rust-toolchain.toml` if reproducibility requires it, and update deliberately. Do not silently raise the MSRV or edition of an existing project: honor its declared compatibility unless the user explicitly directs an upgrade. See reference §1, §36.

## 3. Mandatory per-task workflow

1. **Inspect:** existing instructions (`AGENTS.md`), manifests, source, call sites, features, test setup and deployment contract.
2. **Specify:** acceptance criteria, invalid inputs, units, error paths, concurrency model, capacity, cancellation, shutdown, and backward compatibility.
3. **Design ownership:** for every mutable resource record its owner, readers, mutations, synchronization, lifetime and teardown. For channels specify payload ownership, capacity, sender/receiver closure and ACK semantics.
4. **Implement:** minimum real end-to-end behavior; no unrelated rewrites or new dependencies unless needed. Prefer standard library and existing approved crates.
5. **Test:** write tests that would fail without the feature, covering success, boundaries, failure, concurrent access, cancellation/shutdown and external integration as needed.
6. **Verify:** run formatting, Clippy, build, tests, documentation and necessary OS/feature/security checks; collect actual command results. Use [scripts/check-rust.sh](scripts/check-rust.sh) after reviewing project compatibility.
7. **Attack:** review for P0/P1 defects using reference §39; investigate every pointer, `unsafe`, shared map, clone, lock, spawn, channel, `unwrap`, swallowed error, and test mock.
8. **Report:** distinguish implemented from tested; list PASS/FAIL/**NOT RUN** with exact evidence and remaining risks. Never assert tool execution that did not occur.

## 4. Ownership and borrowing rules

- Prefer `&T` for read-only, `&mut T` for exclusive mutation, and `T` for transfer of ownership. Prefer `&str`, `&[T]` and `&Path` over `&String`, `&Vec<T>`, `&PathBuf` for non-owning parameters.
- Move an owned `String`, `Vec`, struct or `Box<T>` through a channel. **Moving a `Vec` does not clone its backing allocation.** `Box<T>` is owned indirection, not a raw unchecked pointer.
- Use `Arc<T>` for deliberate shared ownership, usually immutable. A cloned `Arc` shares object identity, can extend lifetimes and carries refcount cost; it is not a default solution to borrow checking.
- `'static` does not mean a value must leak forever: task capture should own its values. Use `std::thread::scope` for scoped synchronous borrows, not `Box::leak` or pointer reconstruction.
- Keep types and invariants clear: enums for states, meaningful newtypes for validated values and units, private fields for protected invariants, `Option` for absence, `Result` for failure.
- Never implement `unsafe impl Send`/`Sync` just to bypass the borrow checker. These unsafe traits require a complete soundness proof.

## 5. Concurrency decision table (CRITICAL)

| Need | First choice | Proof obligation |
|---|---|---|
| Only one mutable owner | plain value/`HashMap` | no other mutable owner exists |
| Many readers, no mutation after publication | `Arc<HashMap<K,V>>` | contents thread-safe; no mutation path |
| Multiple writers of simple shared state | `Arc<Mutex<HashMap<K,V>>>` | **all** reads/writes guarded; short critical section |
| Many readers, rare writes | `Arc<RwLock<T>>` if measured | fairness/hold-time and contention evaluated |
| Complex mutable shared coordination | actor task exclusively owns state | bounded commands, explicit replies and shutdown |
| Single independent counter | `AtomicU64`, etc. | memory ordering justified; no compound invariant |
| Blocking CPU or I/O jobs | fixed-size pool/limited `spawn_blocking` | worker and backlog limits |
| Async I/O waiting | bounded Tokio tasks and `mpsc` | admission, cancellation and join lifecycle |

**Do not add a mutex to immutable read-only maps automatically. Do not omit synchronization when maps are actually mutated concurrently.** Safe Rust prevents memory data races; it does not prevent lost updates across two locked calls, deadlocks, starving tasks or race conditions in external side effects.

### 5.1 Channel payload policy

**GOOD:** `tx.send(Command::Update { key: String, value: Vec<u8> })`—the receiver owns the payload after sending. **GOOD when explicitly justified:** `tx.send(Arc<ImmutableSnapshot>)` to share read-only large state. **BAD:** casting `&mut State` to an integer or raw pointer and sending its address; sharing an `Arc<UnsafeCell<HashMap<...>>>` across workers; sending references whose lifetime is not proved.

Use bounded channels as the default: `std::sync::mpsc::sync_channel(n)` for blocking single-consumer contexts, `tokio::sync::mpsc::channel(n)` for async contexts (Tokio capacity must be positive). Prefer an **actor owning a mutable map** over passing a mutable map pointer. Every send must handle closed/full/disconnected as appropriate; a send acknowledgment means queued, not executed or persisted. Queue count limits also need message-byte limits. Reference §§9–11 contains complete example implementations.

### 5.2 Async discipline

- `.await` is a cancellation and interleaving point. Never hold `std::sync::MutexGuard` across `.await`; release via a lexical scope before suspension.
- Tokio's `Mutex` is for async lock acquisition/justified across-await needs, often I/O resources; a std mutex is often preferred for short data-only sections even in async functions (see official Tokio docs).
- Don't block executor workers with `std::thread::sleep`, blocking receivers or synchronous network calls. Use async waits or a bounded dedicated blocking pool.
- Use a bounded semaphore **before spawning** unlimited work, and track `JoinHandle`/`JoinSet` completions. Dropping `JoinHandle` does not imply cancellation. `JoinSet` drop aborts tasks, but blocking tasks might not be abortable once running.
- On `select!`, inspect whether a losing future's drop can lose progress. Handle partial remote writes, idempotency and uncertain outcomes.
- Shutdown order: reject new work → close producers → signal cancellation/drain → await results with deadline → flush/persist → close resources. Reference §§13–16.

## 6. Coding style and idioms

- Apply `rustfmt`, Rust API Guidelines and existing repository style. Use `snake_case` functions/modules/fields, `UpperCamelCase` types/variants, `SCREAMING_SNAKE_CASE` constants and precise domain names.
- Prefer smaller cohesive functions, exhaustive `match`, early return, `?`, `entry`, borrow-friendly slices and structs over magic maps/strings and boolean flags.
- Public API is a compatibility promise. Use private fields, `pub(crate)` by default and explicit error types for libraries. Avoid overgeneric trait layers and macros for simple function logic.
- Prefer `TryFrom` for fallible conversion, checked arithmetic for external integers, explicit units and validated constructors; do not silently truncate via `as`.
- `HashMap` iteration is nondeterministic; explicitly sort/canonicalize for serialization, signatures, content hashes and deterministic tests.
- Treat `.clone()`, `Arc`, `Box`, `Cow`, custom allocators and lock-free algorithms as deliberate trade-offs, not performance incantations.
- Use only verified stable features and actual installed crate APIs; don't hallucinate compiler features, nightly-only methods or package versions.

## 7. Error handling and security

- `Result` for recoverable failure; `Option` for real absence; panic only for broken internal invariants. Avoid `.unwrap()`/`.expect()` on user inputs/I/O/channels/joins in services.
- `?` plus real contextual errors beats logging and returning success. `unwrap_or_default`, `.ok()` and `let _ =` cannot silently erase required errors. A poisoned mutex may indicate an invalid invariant; don't blindly recover.
- Library errors should be classifiable and retain source chains; application edges may use contextual aggregation. Only add crates actually declared in `Cargo.toml`.
- Validate untrusted input lengths/nesting, filenames, integer ranges, network targets, auth and resource budgets. Use parameterized SQL, no shell-concatenated untrusted input, TLS verification, and least privilege.
- Secrets never appear in logs, debug format, spans or stack traces. Understand FFI ABI, pointer ownership and allocator contracts before allowing unsafe.
- Use reviewed dependencies; check advisories, licenses, native code and features. Do not mistake Rust's memory safety for full application security.

## 8. Tests and proof requirements

- Unit tests for domain logic; integration for real filesystem/database/HTTP boundaries; contract tests for public formats; property/fuzz tests for parsers; concurrency stress and Loom for subtle shared state; Miri for suitable unsafe execution paths.
- Tests must have **meaningful assertions** and must fail for broken behavior. No mock-only success claimed as end-to-end integration.
- Concurrency tests should exercise many writers on the **same key**, producer faster than consumer, channel closure, task panic, dropped senders, cancellation, shutdown and lock contention. Prefer barriers to arbitrary sleeps.
- Test `Result::Err`, bad inputs, overflow, empty data, timeouts, limits, poison where applicable, and partial persistence.
- Never modify tests to permit an invalid implementation or mark required tests ignored. Document legitimately unavailable external services as NOT RUN.
- If changing performance, benchmark before and after under realistic data; report actual measurements rather than assumptions.

## 9. Required validation commands

**Adapt feature flags for mutually exclusive features; use CI targets appropriate to project.** From the workspace root:

```sh
cargo fmt --all -- --check
cargo check --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps --locked
cargo build --workspace --release --locked
```

When supported, add `--all-features` variants and OS/architecture matrices. Run configured `cargo audit`/`cargo deny` and integration/fuzz/soak checks when required. Do not claim optional tools were run if unavailable. Narrow any lint exceptions with explicit reasons; never globally suppress correctness warnings to make a build green.

## 10. Mandatory final audit

Before saying “done”, verify all of the following:

- [ ] Actual implementation is invoked and implements each acceptance criterion; no placeholder/fake output.
- [ ] No raw-pointer channel workaround or unjustified unsafe; state ownership and `Send`/`Sync` are sound.
- [ ] All shared mutable collections have a complete owner/lock/actor design; compound updates are atomic as required.
- [ ] Every queue, task pool, payload, retry, input parser and cache is bounded appropriately.
- [ ] Every spawned worker/task has completion/error/cancellation/shutdown handling; queues close and drain correctly.
- [ ] No lock held through `.await`/blocking I/O; no invented memory-ordering or unreviewed lock-free claims.
- [ ] Error paths propagate accurately; no panics on ordinary input, swallowed failures or unvalidated external data.
- [ ] Tests cover real behavior, negative paths, same-key concurrency and external integration as relevant.
- [ ] Rustdoc, configs, security, compatibility and deployment contract are updated where changed.
- [ ] Exact commands and PASS/FAIL/NOT RUN results reported truthfully; no fabricated proof.

**Unresolved P0/P1 defects mean the work is NOT COMPLETE.** Refer to full §§39–40 for the exhaustive checklist and severity matrix.

## 11. Loading the full reference and reporting

| Task | Required sections of `references/RUST_ENGINEERING_STANDARD.md` |
|---|---|
| Any Rust implementation/review | §§0–8, 23, 28, 31, 39–40 |
| Channels, actors, maps, threads, async | **§§6, 8–16, 22, 29–30, 39** |
| Public API, parser, serializable state | §§3–8, 17–19, 21–22 |
| Security/unsafe/FFI/crypto | §§8, 19–20, 22, 27, 35, 39 |
| Testing, CI, quality gates | §§21–24, 31–33, 38–40 |
| Service lifecycle, performance, operations | §§14–16, 24–27, 35–37 |
| Version/edition/release changes | §§1, 23–24, 36, 41–42 |

In the final delivery, give actual files changed, requirements met, owner/synchronization model when applicable, specific checks executed, tests skipped/unrun and remaining risks. An unavailable Rust toolchain means `NOT RUN`, never `PASS`.

**Authority:** [Rust releases](https://blog.rust-lang.org/releases/), [Rust Book](https://doc.rust-lang.org/book/), [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/), [Rustonomicon](https://doc.rust-lang.org/nomicon/), [Cargo](https://doc.rust-lang.org/cargo/), [Tokio](https://docs.rs/tokio/latest/tokio/), and citations in the full reference. This skill improves behavior but **does not replace compilation, CI and independent review**.
