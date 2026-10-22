# Rust Engineering Standards — DeepSeek v4 Agent Skill

A portable Agent Skills package for enforceable, senior-level Rust engineering.

## Contents

- **`SKILL.md`** — concise mandatory policy for every Rust task, structured for an agent's context budget.
- **`references/RUST_ENGINEERING_STANDARD.md`** — full, 43-section Rust engineering manual with rationale, source links, code examples, anti-patterns, concurrency architectures, tests, and acceptance checklists.
- **`scripts/check-rust.sh`** — baseline formatting, Clippy, build, docs, and test gate, with optional security checks.
- **`templates/AGENTS_RUST_SNIPPET.md`** — short permanent instruction to add to `AGENTS.md` without replacing existing instructions.

## OpenCode installation

For global use on macOS or Linux:

```sh
mkdir -p ~/.config/opencode/skills/rust-engineering-standards
cp -R SKILL.md references scripts templates \
  ~/.config/opencode/skills/rust-engineering-standards/
```

For per-repository use from the repository root:

```sh
mkdir -p .opencode/skills/rust-engineering-standards
cp -R SKILL.md references scripts templates \
  .opencode/skills/rust-engineering-standards/
```

Then **merge** the guidance in `templates/AGENTS_RUST_SNIPPET.md` into the project's existing `AGENTS.md`. Skills are discoverable, but agent selection is not infallible; the explicit repository rule helps ensure activation for every Rust task. Verify with OpenCode's current documentation: https://docs.opencode.ai/docs/skills/.

Equivalent compatible locations may be supported under `.agents/skills` and `.claude/skills`.

## Minimum Rust

As of October 19, 2026, Rust **1.99.1** is latest stable patch and Rust **2024** is latest edition. For each new project, check the official Rust release page for an updated stable compiler. Do not silently raise existing libraries' MSRV.

## Run the quality gate

From your Cargo workspace root:

```sh
bash /path/to/rust-engineering-standards/scripts/check-rust.sh
```

Set `RUST_ALL_FEATURES=1` only when all Cargo features can coexist. The gate requires installed `cargo`, `rustc`, Clippy and rustfmt. Missing tools or a service required by integration tests must be reported, not mocked into passing. Additional project-specific security, target, fuzz, Loom/Miri, fault-injection and integration checks may be required before release.

## Scope

Includes ownership and lifetimes, trait/enum/API design, channels and actor ownership, maps and locks, atomics, Tokio cancellation and shutdown, unsafe/FFI, security and supply chain, resource limits, tests, rustdoc, performance, deployment, multi-agent adversarial verification, and a strict Definition of Done.

The file packaging follows the Agent Skills model of concise skill instructions plus on-demand detailed references. **Written policy cannot guarantee model compliance by itself**; use actual CI checks and independent code review.
