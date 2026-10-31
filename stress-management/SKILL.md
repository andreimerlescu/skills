---
name: stress-management
description: Load when you notice yourself saying you are stressed, overwhelmed, confused, frustrated, stuck, thrashing or going in circles; when you keep writing "wait", "no -", "actually" or re-deriving the same fact; when you have edited the same code 3+ times for one problem, are trying numbers or constants at random, or have reasoned for a long time without running a tool; or when the user asks why you are stressed or stuck. Gives a short protocol for breaking the loop by handing the unknown to a tool, a test or another skill (dates and times go to date-time-helper).
license: MIT
metadata:
  version: "1.0.0"
---

# stress-management

"Stressed", "confused" and "thrashing" are not feelings to narrate or
apologize for. They are a **signal: you are trying to answer a question by
thinking, and thinking is not converging.** The fix is almost always to stop
reasoning and run something that answers the question for you.

You have tools. A shell that runs real code beats any amount of mental
simulation. Use it.

## Loop detectors

You are in a loop if **any** of these is true. Stop and run the protocol.

- You used words like *stressed, confused, frustrated, stuck, thrashing* about yourself.
- Your reasoning flips back and forth: "wait", "no -", "actually", "that's what
  keeps tripping me up", or the same fact re-derived with a different answer.
- You are trying values to see what sticks (`day=3`, then `4`, then `5`;
  `Months::new(6)`, then `8`).
- You edited the same function/file 3+ times for the same failure.
- The same test or compile error has come back after 3 fix attempts.
- You have written several paragraphs of reasoning without a tool call.
- You are predicting what an API returns instead of checking.
- Context is past ~60% and you are re-reading things you already read.

## The protocol: STOP

### S: Stop editing
Make no more changes to the code under discussion until step P. Half-made
edits made while confused are the main way loops get longer.

### T: Take stock (write it down, 5 lines max)
Make a scratch note (a file such as `tmp/notes.md`, or your memory tool if
you have one):

```
GOAL:     <one sentence: the observable behavior the user wants>
KNOWN:    <facts confirmed by running something, each with its source>
UNKNOWN:  <the ONE question blocking progress, phrased so a program can answer it>
TRIED:    <what failed, one line each, so you do not try it again>
NEXT:     <the single experiment that answers UNKNOWN>
```

If you cannot write UNKNOWN as one concrete question, that is the problem.
Split it until you can, for example "What does
`NaiveDate(2026,1,8).checked_add_months(Months::new(1))` return?"

### O: Offload the question to a tool
Pick the tool by the kind of question. Do not answer it yourself.

| UNKNOWN is about | Do this |
|---|---|
| A date, weekday, duration, month boundary, time zone, calendar | **Load `date-time-helper`** and run `datecalc.py`: `python3 <skill>/scripts/datecalc.py --today $(date +%F) "<question>"` |
| What a library function returns | Write a 5-10 line probe program or test that prints it, and run it. Rust: a `#[test]` with `dbg!()`, or `cargo run --example probe`. Go: `go run probe.go` or `go test -run TestProbe -v`. |
| Whether an API exists / its signature | Read the real docs: `go doc pkg.Symbol`, `cargo doc -p <crate>`, grep `~/.cargo/registry/src` or the vendored source. |
| Arithmetic, counting, unit conversion | `python3 -c "print(...)"` |
| A failing test | Run only that test with verbose output. Read the **first** failure fully. Print the actual vs expected values. |
| A compile error | Fix only the **first** error, then recompile. Later errors are often caused by the first. |
| How the existing code behaves | Run it, or add a temporary print/log, instead of tracing it in your head. |
| Which of several designs is right | Pick the simplest that satisfies GOAL, write the test first, and let the test decide. |
| Requirements (what the user actually wants) | Ask the user one precise question (see "Escalate"). |

Check your tool list for anything that fits better: an LSP, a docs server,
a step-by-step thinking tool, a memory store, other skills. Use them before
more free-form reasoning.

### P: Proceed with one verified step, or pause
- Put the experiment's result in KNOWN, then make **one** edit that uses it.
- Re-run the test. Green: continue. Red: back to T with the new fact.
- Write the code once, cleanly, from the verified facts. Do not keep patching
  a version written while confused.

## Budgets

- **2 hypotheses per unknown** without an experiment. The third idea must be
  a program you run.
- **3 fix attempts per distinct failure.** After the third, escalate.
- **No placeholder constants** (`day = 8 // anchor`). If a magic number
  appears in your fix, you are guessing. Replace it with a library call or a
  named, tested rule.

## Escalate honestly

If two passes through STOP have not unblocked you, tell the user briefly and
factually, without apologizing at length:

```
Status: blocked on <UNKNOWN>.
Verified so far: <KNOWN, short>.
Tried: <TRIED, short>.
I need: <a decision / a missing file / access / your intended rule>, or
I propose: <the next experiment> - shall I continue?
```

If the user asks "why are you stressed?", answer plainly: you were looping on
<UNKNOWN> by reasoning instead of testing, and here is the tool-based plan.
Then run it.

## Context hygiene

- When context is past ~60%, write the scratch note, then work only from it
  and the files you are editing. Do not reload large files "to be safe".
- If a tool's output was truncated, re-run it narrower. Never fill in the
  missing part from imagination.
- Prefer one decisive command over many speculative ones.

## Worked example (a real loop)

> "Jan + Months::new(4) = May... so Months::new(N) adds N months? No - wait...
> to add ONE month I use Months::new(8)? I keep typing wrong numbers under
> confusion because my anchor is at day=8..."

Apply STOP:

```
GOAL:    on_month filter returns entries in the same calendar month as ref.
KNOWN:   (nothing verified yet; every "fact" above came from my head)
UNKNOWN: what does checked_add_months(Months::new(1)) return for 2026-01-08 and 2026-01-31?
TRIED:   day constants 3,4,5,8; Months::new(4/6/8) guesses
NEXT:    run datecalc and a 6-line chrono test
```

```bash
python3 <date-time-helper>/scripts/datecalc.py "2026-01-08 + 1 month"   # 2026-02-08
python3 <date-time-helper>/scripts/datecalc.py "2026-01-31 + 1 month"   # 2026-02-28 (clamped)
python3 <date-time-helper>/scripts/datecalc.py "first day of next month" --today 2026-01-08  # 2026-02-01
```

KNOWN now: `Months::new(1)` adds exactly one month and clamps. The right
design needs no day constant: `start = d.with_day(1)`,
`end = start.checked_add_months(Months::new(1))`, keep `start <= x < end`.
Write the test with those values, implement once, run, done. (The recipe is
in date-time-helper's `reference/rust.md`.)
