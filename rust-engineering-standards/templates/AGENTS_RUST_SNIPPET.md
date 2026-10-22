## Rust — mandatory engineering policy

- For **every** task that writes, edits, reviews or tests Rust (`.rs`, Cargo manifests,
  build scripts, Rust FFI), activate the `rust-engineering-standards` skill first.
- Read its `SKILL.md` and the applicable sections of
  `references/RUST_ENGINEERING_STANDARD.md` before changing code. For concurrency
  always read §§6 and 8–16, 22, 29 and 39.
- Use the latest *verified published stable* Rust as the minimum for new projects;
  preserve the existing project's declared MSRV/edition unless an upgrade is
  explicitly approved.
- Never send raw pointers or lifetime-erased addresses as channel jobs.
- Never mutate a shared map/collection without a sound owner/lock/actor protocol.
  Immutable shared maps do not require gratuitous mutexes.
- Prefer owned, bounded channel messages; track tasks, failures, cancellation,
  queue capacity and graceful shutdown.
- Never substitute mocks, TODOs, skipped tests, bypassed lint checks or fabricated
  results for working code and verified behavior.
- Run the skill's appropriate checks; complete the anti-slop audit and report
  PASS/FAIL/NOT RUN for every claimed verification.
