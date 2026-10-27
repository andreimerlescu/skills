# go-engineering-standards — operator notes

This README is for the humans who install and run the skill. The model reads `SKILL.md`; it does not need this file.

![Unique](https://counthis.app/github?repository=andreimerlescu/skills&label=Unique) ![Visitors](https://counthis.app/g/qyjy5vwjtjgbjfzy)

## Layout

```text
go-engineering-standards/
├── SKILL.md                     # always-loaded core: hard rules, loop, routing table, report format
├── references/                  # loaded on demand per the routing table
│   ├── concurrency.md
│   ├── testing.md
│   ├── errors-lifecycle.md
│   ├── boundaries-security.md
│   ├── api-style-docs.md
│   ├── go-versions.md           # verified Go 1.25–1.27 API/behavior table
│   ├── traps.md
│   ├── performance.md
│   └── review-gates.md
├── scripts/verify-go.sh         # quality gate; prints a summary block the model must quote
├── AGENTS.snippet.md            # paste into AGENTS.md so the skill is always triggered
├── evals/scenarios.md           # prompts to check that the model actually follows the skill
└── CHANGELOG.md
```

## Why it is split

v1 was one ~15k-word file. Local deployments often run with a much smaller working context than the model's maximum, and long instructions loaded up front get followed less reliably late in a session. v2 keeps the always-loaded core short and routes the model to the one or two references a task needs.

Install the whole directory, not just `SKILL.md`: the core points at `references/` and `scripts/` by relative path.

## Running with DeepSeek V4 locally

Facts from DeepSeek's release materials (April 2026): V4 ships as **V4-Pro** (1.6T total / 49B active) and **V4-Flash** (284B total / 13B active), both with a 1M-token maximum context and switchable thinking / non-thinking modes; DeepSeek recommends `temperature = 1.0`, `top_p = 1.0` for local deployment and at least 384K context for the maximum-effort reasoning mode. Check your serving stack's docs for the exact flags.

Practical settings for this skill:

- **Thinking mode on** for implementation and review turns. Non-thinking is fine for pure file navigation or running the gate.
- **Separate reasoning from content.** Enable your server's DeepSeek V4 reasoning parser (SGLang documents a `deepseek-v4` parser; other servers such as ds4 expose a `thinking` switch — check yours) so reasoning arrives as `reasoning_content` and does not leak into tool arguments or file edits.
- **Context:** budget at least 32K tokens for tool-using agent turns (tool schemas plus workspace context add up quickly); 64K–128K is comfortable for multi-file Go work with this skill. The core is roughly 3K tokens; each reference is about 0.5–4K.
- **Tool output limits:** cap command output in the harness (for example, the last 200 lines). The skill tells the model to re-run narrower instead of guessing truncated output.
- **Offline machines:** pre-populate the module cache (`go mod download`) and, if you want vulnerability scans, a local vuln DB for `govulncheck`. The gate reports these as SKIP rather than failing silently.
- **Toolchain:** install Go 1.27.2 or newer. With `GOTOOLCHAIN=local` the gate will fail loudly if the installed toolchain is older than `go.mod` requires, which is what you want.

## Enabling it

1. Copy the directory into your agent runtime's skills location (check your harness docs; there is no universal path).
2. Paste `AGENTS.snippet.md` into the highest relevant `AGENTS.md` and fix the path.
3. Run two or three prompts from `evals/scenarios.md` and read the transcripts. The skill is working when the model runs `go doc` before using new APIs, quotes the gate summary, and refuses to weaken tests.

## The gate script

```bash
bash scripts/verify-go.sh                 # from a module root; checks changed files if in git
bash scripts/verify-go.sh --race          # add the race detector
bash scripts/verify-go.sh --all --race --vuln   # whole tree, race, govulncheck
bash scripts/verify-go.sh --help
```

It runs each step, never stops early, writes full logs to a temp directory, and ends with a `VERIFY-GO SUMMARY` block. Exit code is non-zero if any step failed. Optional tools that are missing are reported as `SKIP`, never as `PASS`. The red-flag scan covers added lines in tracked files (`git diff HEAD`); brand-new untracked files are format-checked but not scanned. Works with macOS's bash 3.2.

## Keeping it current

Re-check `references/go-versions.md` after each Go release (February and August) and patch release. Authoritative sources:

- Release notes and history: https://go.dev/doc/go1.27, https://go.dev/doc/go1.26, https://go.dev/doc/go1.25, https://go.dev/doc/devel/release
- Memory model: https://go.dev/ref/mem · Spec: https://go.dev/ref/spec · Toolchains: https://go.dev/doc/toolchain · Modules: https://go.dev/ref/mod
- Code review and test comments: https://go.dev/wiki/CodeReviewComments, https://go.dev/wiki/TestComments
- Race detector: https://go.dev/doc/articles/race_detector · Diagnostics: https://go.dev/doc/diagnostics · Fuzzing: https://go.dev/doc/fuzz/
- Packages: https://pkg.go.dev/sync, https://pkg.go.dev/testing/synctest, https://pkg.go.dev/golang.org/x/sync/errgroup
- Vulnerabilities: https://go.dev/doc/security/vuln/
- Style: https://google.github.io/styleguide/go/
- DeepSeek V4 release notes: https://api-docs.deepseek.com/news/news260424

Language semantics (spec, memory model) outrank style guides; repository conventions outrank this skill's style preferences but not its correctness or security rules.
