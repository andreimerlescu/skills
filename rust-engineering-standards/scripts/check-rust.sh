#!/usr/bin/env bash
# Rust Engineering Standards — baseline verification gate.
# See ../references/RUST_ENGINEERING_STANDARD.md §§23–24.
# Run at Cargo workspace root. Nonzero exit is a failed required gate.
set -Eeuo pipefail

if ! command -v cargo >/dev/null 2>&1; then
  echo 'ERROR: cargo not installed. All checks NOT RUN.' >&2
  exit 127
fi
if ! command -v rustc >/dev/null 2>&1; then
  echo 'ERROR: rustc not installed. All checks NOT RUN.' >&2
  exit 127
fi

printf 'rustc: '; rustc --version
printf 'cargo: '; cargo --version

cargo fmt --all -- --check
cargo check --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
RUSTDOCFLAGS='-D warnings' cargo doc --workspace --no-deps --locked
cargo build --workspace --release --locked

# Enable only if all feature combinations are compatible in this workspace.
if [[ "${RUST_ALL_FEATURES:-0}" == 1 ]]; then
  cargo check --workspace --all-targets --all-features --locked
  cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
  cargo test --workspace --all-features --locked
fi

# Missing OPTIONAL supply chain tools are reported as NOT RUN.
# If mandated by your project, provision them and remove these skips.
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

echo 'PASS: executed required Rust baseline checks' >&2
