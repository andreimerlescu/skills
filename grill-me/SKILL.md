---
name: grill-me
description: Clarify vague or underspecified requests through rigorous, iterative questioning before implementation. Use when the user says "grill me", asks to eliminate ambiguity, wants a requirements interview, or a consequential project decision is unclear. Inspect existing context first; ask targeted follow-ups until scope is approved; revise the repository's AGENTS.md with user-confirmed, reusable instructions and iterate on that file until the user is satisfied. Never guess material requirements.
metadata:
  version: "1.0.0"
---

# grill-me — requirements interrogation and AGENTS.md convergence

## Mission

Turn ambiguous user intent into a precise, testable agreement **without inventing decisions**. Ask whatever is necessary, even across many conversational rounds, until the user explicitly approves the specification. Where the user intends durable working rules, **actually edit the repository's root `AGENTS.md`**, review it with the user, and continue revisions until the user explicitly accepts the result.

This is an interactive workflow, not an instruction to send one giant questionnaire or a request for the user to write the spec themselves.

## Invocation

Activate when any of the following holds:

- User explicitly says `grill me`, `interrogate the requirements`, `ask until it's clear`, `no assumptions`, or similar.
- The request is missing a consequential acceptance criterion, behavior, boundary, platform, security constraint, or deliverable that cannot be resolved from the repository or conversation.
- The user asks to create, review, improve, or correct `AGENTS.md` by interview.
- The user rejects an assumption or says earlier results missed their intention.

Do **not** grill on inconsequential formatting preferences or re-ask settled facts. User can explicitly say `skip the interview`, `use your judgment`, or `proceed with these assumptions`; respect that for noncritical questions and document assumptions. Never treat silence as agreement.

## Operating modes

1. **Task clarification:** Resolve the current task's unknowns, obtain scope approval, then implement and verify it. Capture persistent repo rules only when the user wants them to persist or when they explicitly approve the proposed rule.
2. **AGENTS.md refinement:** Interview the user about how agents should work in this repository, update `AGENTS.md` directly, display the change, get feedback, and repeat until explicit approval.
3. **Correction:** When a result is criticized, diagnose the specific mismatch, reopen only affected decisions, fix the artifact and any approved durable rules, then seek approval again.

If both modes apply, clarify the task first, then update `AGENTS.md` with durable decisions; keep progress and approvals distinct.

## Procedure — mandatory

### Phase 1: Inspect before asking

- Read the user request and prior turns. Inspect `AGENTS.md`, other applicable agent instructions, skill docs, and only relevant repo files, code, configuration, tests, or artifacts if accessible.
- Identify **confirmed facts**, **unresolved decisions**, **conflicts**, and **proposed defaults** separately. Do not silently promote a proposed default to a requirement.
- Identify what cannot be known without the user's preferences versus what can be verified from artifacts or documentation.
- If there is no writable local workspace or the user hasn't supplied `AGENTS.md`, say so and provide a proposed patch or installable package; **never claim that you edited the user's inaccessible file**.

### Phase 2: Grill the uncertainty

- Ask 1–5 high-value questions in each round, prioritized by their ability to change architecture, output, correctness, safety, interfaces, or acceptance criteria. A single critical blocker warrants a single question.
- Each question should address **one decision**; explain briefly why it matters or give concise, materially different options. Permit an open answer and `other`.
- Be direct and skeptical of vague nouns: "fast", "scalable", "simple", "production-ready", "works", "clean", "like X", "secure", and "done" require a definition when relevant.
- Probe assumptions, incompatible requirements, scope boundaries, target users, runtime/environment, error and edge cases, dependencies, constraints, and measurable verification.
- Challenge contradictions respectfully: identify the conflicting statements and ask which takes precedence.
- Never ask what the existing repo or conversation already answers. Do not invent answers or present unconfirmed guesses as facts.
- After each reply, incorporate answers into the decision ledger and ask only newly unresolved questions. Keep the interview moving instead of repeatedly summarizing everything.

### Phase 3: Agreement gate

Before substantive implementation, present a compact **Requirements Contract**:

- **Goal and deliverables** — what will be produced, including file paths when known.
- **Functional behavior and non-goals** — what must happen, and what is explicitly out of scope.
- **Constraints** — stack, compatibility, dependencies, security, performance, interfaces, and existing invariants as relevant.
- **Acceptance checks** — observable tests/examples that define success.
- **Decisions / open questions** — confirmed vs. explicitly delegated; no hidden assumptions.

Ask for an explicit `approve`, `revise`, or `continue grilling`. If the user changes the scope, revisit only impacted clauses. **Do not treat an unapproved contract as permission for substantive implementation.** Read-only inspection, validation of existing state, and preparing a proposed diff are allowed during discovery.

### Phase 4: Edit the actual AGENTS.md

When AGENTS.md refinement is requested or durable guidance has been approved:

1. Resolve the correct repository root and read its **actual current** `AGENTS.md` immediately before editing. Respect nested AGENTS files; do not edit the wrong scope.
2. Preserve unrelated instructions, headings, precedence, and meaningful formatting. Keep a single installer-owned `grill-me` activation block, marked by `<!-- grill-me:start -->` and `<!-- grill-me:end -->`.
3. Convert approved reusable answers into concise, actionable `AGENTS.md` instructions. Prefer verifiable rules ("run `go test ./...` before handoff") over personality statements ("be careful"). Do not persist secrets, personal data, session-only constraints, speculative claims, or contradictory duplicates.
4. Place detail and examples in a referenced repo document/skill when needed; **keep the complete `AGENTS.md` strictly below 369 physical lines (maximum 368)**. Count via `splitlines()`, including headings, blank lines, and comments. Do not delete existing rules silently to make room.
5. Make an actual on-disk edit using available file tools. Check the current version, review the diff, and run the guard:

   ```bash
   python3 .agents/skills/grill-me/scripts/agents_guard.py check --root .
   git diff -- AGENTS.md
   ```

6. Present the changed sections/diff and actual new line count, plus unresolved issues. Ask: **"Is this AGENTS.md correct, or what should I change?"**
7. If corrections arrive, update the real file again, revalidate, present the diff, and repeat. **Stop the AGENTS.md review loop only on explicit satisfaction/acceptance** (e.g., "approved", "that's correct", "I'm satisfied"). Do not claim satisfaction on the user's behalf.
8. If no write access, changes need permissions, or the line budget cannot be met without removing other instructions, disclose the blocker and provide an exact patch/choice. Never claim edits or checks that weren't executed.

### Phase 5: Execute, verify, and learn

- For task execution, implement only the approved contract, test against acceptance checks, and show the evidence. Distinguish untested aspects.
- If validation fails or the user's feedback contradicts the contract, return to the smallest relevant clarification round. Correct the artifact; update reusable `AGENTS.md` rules only when approved.
- Report whether the **task** is accepted separately from whether **AGENTS.md** is accepted. A task being complete does not imply that the user is satisfied with AGENTS.md.
- When approval is withheld, do not present the work as approved; clearly state what remains open and ask the next targeted question.

## Suggested questioning lenses

Use only the lenses relevant to the task. Do not ask the whole list mechanically.

| Lens | Example of a productive question |
| --- | --- |
| Outcome | What observable behavior would make you call this successful? |
| Audience | Who uses it, and what is their critical workflow? |
| Scope | Which inputs, outputs, pages, integrations, and failure modes are included? |
| Boundaries | Which existing behaviors must remain unchanged? |
| Decisions | Which choice is yours to make versus mine to recommend? |
| Architecture | What environment, interfaces, and compatibility requirements are fixed? |
| Quality | What benchmark, test, or visual comparison constitutes acceptance? |
| Risk | What may never be stored, transmitted, deleted, or changed? |
| Delivery | Do you want a patch, complete files, commands, or a deployed result? |
| Persistence | Which answers should become permanent instructions in AGENTS.md? |

## Response styles

**Question round**

> "I found two interpretations with different consequences: A [...]; B [...]. Which do you want? Also, what should happen when [...]?"

**Ready-to-approve contract**

> "Here is the exact scope and how I will verify it. Confirm, revise, or tell me to keep grilling."

**AGENTS.md change review**

> "Updated `AGENTS.md` (N/368 lines), preserved existing instructions, and verified the guard. Here are the changes. Is this correct, or what should I adjust?"

## Non-negotiable safeguards

- User instructions and higher-priority operating rules always outrank this skill. A skill cannot override permission boundaries or force unauthorized writes.
- Requirements questions are not an excuse to stall clear, low-risk tasks. For explicit `grill-me` invocation, however, wait for the user's scope approval before substantive implementation.
- Do not confuse `AGENTS.md` auto-discovery with guaranteed skill loading in every agent product. The activation block is a repository instruction for compatible agents; the skill must also be installed and the agent must have file access.
- If the user ends the session mid-interview, preserve only user-approved durable project rules, not unresolved proposals. The next session should inspect AGENTS.md and ask for any missing context rather than pretend it was approved.
