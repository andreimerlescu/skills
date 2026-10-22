## Go work — mandatory skill

For ANY task that creates, edits, reviews, tests, debugs or documents Go code, `go.mod`, `go.sum` or Go CI:

1. Read `<SKILL_DIR>/go-engineering-standards/SKILL.md` first, every time, even for small changes.
2. Load only the `references/` files its routing table (§3) selects for this task.
3. Before using any standard-library or module API you are not certain exists in this repo's `go` version, run `go doc <pkg>.<Symbol>`.
4. Verify with `bash <SKILL_DIR>/go-engineering-standards/scripts/verify-go.sh` (add `--race` for concurrency changes) and quote its `VERIFY-GO SUMMARY` block verbatim.
5. End with the GO CHANGE REPORT from SKILL.md §8. Never claim a check passed unless its output is in this session.
6. Never weaken, skip or delete tests, and never edit the gate script or the skill, to make a failure go away.

Replace `<SKILL_DIR>` with the real install path (relative to the repo if the skill is vendored).
