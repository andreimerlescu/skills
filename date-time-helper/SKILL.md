---
name: date-time-helper
description: Use for ANY date or time calculation or date-handling code in Rust or Go. Covers date arithmetic ("today + 90 days", "first monday of january 2026 + 3 weeks", "last wednesday + 5 days", "every 2 weeks after <date>"), day counts, business days, month/year boundaries, time zones and DST, and the Gregorian, Julian, Hebrew, Hijri and Chinese calendars. Includes a verified calculator script (scripts/datecalc.py), tested chrono and Go time recipes, and golden test data. Load it before writing or debugging date code, and whenever you are unsure what a date API does.
license: MIT
compatibility: python3 >= 3.9 for the script (stdlib only); Rust chrono 0.4; Go >= 1.21
metadata:
  version: "1.0.0"
---

# date-time-helper

## The one rule

**Do not do calendar arithmetic in your head.** Not weekdays, not month
lengths, not "how many days until", not what `Months::new(4)` does. Language
models get these wrong in ways that look right, then loop trying to fix them.
Every date answer comes from one of these:

1. `scripts/datecalc.py`: a verified calculator. Use it first.
2. A 5-line program in the project's language that prints the answer, run
   with the real toolchain.
3. A test that asserts the expected value (taken from 1 or 2) and passes.

If you have edited the same date code twice without a passing test, stop.
Run the calculator, write the test, then edit once. (If you notice you are
"stressed" or "confused", also load the `stress-management` skill.)

## Find the script

The script sits next to this file: `<this skill's directory>/scripts/datecalc.py`.
If you do not know the directory:

```bash
find ~/.config/opencode/skills ~/.claude/skills ~/.agents/skills .opencode/skills .claude/skills .agents/skills \
  -name datecalc.py -path '*date-time-helper*' 2>/dev/null | head -1
```

Below, `DC` means `python3 /path/to/datecalc.py`. First use on a new machine:
`DC selftest` must print `ALL PASSED`.

## Always pin "today"

Relative questions ("today", "next monday", "last wednesday") depend on the
date **in the user's time zone**. Get it from the system, then pass it in:

```bash
date +%F                       # e.g. 2026-10-31
DC --today 2026-10-31 --tz Europe/Bucharest "last wednesday + 5 days"
```

If the user's zone is unknown, use the machine's local date and say so.

## Asking the calculator

Write the question almost as the user said it. Quotes are optional.

| User asks | Command |
|---|---|
| the first monday of january 2026 + 3 weeks | `DC "first monday of january 2026 + 3 weeks"` |
| today + 90 days / 90 days from now / in 90 days | `DC "today + 90 days"` |
| last wednesday + 5 days | `DC "last wednesday + 5 days"` |
| every 2 weeks after Jan 5 | `DC "every 2 weeks after 2026-01-05 count 10"` |
| every month from Jan 31 until June | `DC "every month from 2026-01-31 until 2026-06-30"` |
| how many days between X and Y | `DC "days between 2026-01-01 and 2026-03-15"` |
| weeks until Christmas | `DC "weeks until 2026-12-25"` |
| 10 business days after X | `DC "2026-12-18 + 10 business days" --holidays 2026-12-25,2027-01-01` |
| first/last day of next month | `DC "first day of next month"`, `DC "last day of february 2028"` |
| last business day of the month | `DC "last business day of this month"` |
| 3rd friday after X | `DC "third friday after 2026-01-01"` |
| what weekday / ISO week is X | `DC info 2026-07-04` |
| X in Hebrew/Hijri/Chinese/Julian | `DC convert 2026-10-31` |
| when is Passover / Ramadan / Chinese New Year 2027 | `DC "passover 2027"`, `DC "ramadan 2027"`, `DC "chinese new year 2027"` |
| 1 Tishrei 5787 + 100 days | `DC "hebrew:5787-tishrei-1 + 100 days"` |
| 36 hours after 9:30am Jan 5, New York | `DC --tz America/New_York "2026-01-05T09:30 + 36 hours"` |

Run `DC examples` for the full grammar. Add `--json` for structured output.

### Reading the output

```
input   : first monday of january 2026 + 3 weeks
RESULT  : 2026-01-26 (Monday)
steps   :
  1st Monday of January 2026  -> 2026-01-05 (Monday)
  + 3 weeks                   -> 2026-01-26 (Monday)
today   : 2026-10-31 (Saturday)
note    : ...
```

* `RESULT` is the answer. Give it with the weekday.
* `steps` is your explanation. Reuse it instead of re-deriving.
* `note` lines are assumptions (what "next monday" meant, a clamped
  month-end, holiday caveats). Tell the user any note that affects the answer.
* `error:` means the date does not exist or the phrasing was not understood.
  Read the message, rephrase with ISO dates or simpler steps, and run again.
  Do not compute it by hand instead.

## Definitions (the script, the recipes and the tests all agree)

| Phrase | Meaning |
|---|---|
| `next monday` | first Monday strictly after today (today Monday gives +7) |
| `last monday` | most recent Monday strictly before today |
| `this monday` | Monday of the current ISO week (Mon-Sun), may be past |
| `monday` (bare) | today if Monday, else the next Monday |
| `X after D` / `X before D` | strictly after/before D. `on or after` includes D |
| `+ N months` | same day-of-month, clamped to month end (Jan 31 + 1 month = Feb 28) |
| `every N <unit> after D` | excludes D. `from D` includes D. Item k = D + k*N, always from D (no drift) |
| `days between A and B` | B - A. Add 1 if both ends count ("inclusive") |
| business days | Mon-Fri minus `--holidays`. Counts use the half-open range [A, B) |
| `+ N days/weeks/months` with a time | wall-clock: same local time, DST-aware |
| `+ N hours/minutes` | elapsed time: absolute, DST-aware with `--tz` |

## Writing date code

Read the language file before writing or fixing date code:

* **Rust**: `reference/rust.md`. Code: `reference/rust/src/recipes.rs` (chrono)
  and `reference/rust/src/calendars.rs`.
* **Go**: `reference/go.md`. Code: `reference/go/recipes.go` and `reference/go/calendars.go`.
* Calendar rules and numbering traps: `reference/calendars.md`.

Facts to remember (all tested):

* **chrono `Months::new(n)` adds exactly n months.** Jan + `Months::new(1)` =
  Feb. `checked_add_months` clamps the day (Jan 31 gives Feb 28/29).
* **Go `t.AddDate(0, 1, 0)` does not clamp.** Jan 31 gives Mar 3. Use the
  clamping `AddMonths` recipe if you mean "same day next month".
* First of next month: chrono `d.with_day(1)?.checked_add_months(Months::new(1))`;
  Go `time.Date(y, m+1, 1, 0, 0, 0, 0, time.UTC)`. Last day of the month: Go
  `time.Date(y, m+1, 0, ...)`; chrono first-of-next `.pred_opt()`.
* Month and year filters use **half-open ranges**: `start <= x < first_of_next`.
  Never `<= last_day 23:59:59`, and never a magic day constant like `day=8`.
* Go weekdays start at Sunday = 0. chrono gives you a choice:
  `num_days_from_monday()` or `num_days_from_sunday()`.
* Do date maths on civil dates (`NaiveDate`, or Go `time.Time` at UTC
  midnight). Use zones only to find "today" or for elapsed-time arithmetic.
* Never add days to a Hebrew/Hijri/Chinese day field. Convert to RD, add,
  convert back.

### Workflow for date code (copy this)

1. State the rule in one sentence ("on_month keeps entries with
   first_of_month(ref) <= ts < first_of_next_month(ref)").
2. Get 3-6 expected values from `DC`, including edges: the 31st, Feb 29,
   December to January, a DST day, a missing 5th weekday.
3. Write the test first with those values. Run it and watch it fail.
4. Implement with the recipe functions. Do not hand-roll month maths.
5. Run the test. If it fails twice, print intermediate values with a tiny
   probe program. Do not guess constants.

Golden data for your own tests is in `reference/testdata/`: `arithmetic.csv`
(4,400 cases), Hebrew/Hijri/Chinese month starts, and Julian/tabular-Hijri samples.

## Calendar support and limits

| Calendar | Script tag | Range | Status |
|---|---|---|---|
| Gregorian | ISO dates | years 1-9999 | exact |
| Julian | `julian:Y-M-D` | any | exact |
| Hebrew | `hebrew:5787-tishrei-1` or `hebrew:5787-7-1` (Nisan=1) | any | exact |
| Hijri, Umm al-Qura | `hijri:1447-9-1` | 1343-1500 AH | table; settled for 1420-1450 AH |
| Hijri, tabular | `hijri-tabular:1447-9-1` | any | exact arithmetic, may differ from Umm al-Qura by 1-2 days |
| Chinese | `chinese:2026-1-1`, leap `chinese:2025-L6-1` | 1900-2100 | matches sxtwl and ICU4X every day 1929-2100 |

Religious observance can differ from computed dates (Islamic moon sighting;
Hebrew and Islamic days start at sunset). Say so when it matters.

## If the script is not available

Use the language's own library in a throwaway program, print the value,
then use it. For example, `python3 -c "from datetime import date, timedelta; print(date(2026,10,31)+timedelta(days=90))"`,
or a `#[test]` / `go test` that prints. Running real code beats reasoning.
