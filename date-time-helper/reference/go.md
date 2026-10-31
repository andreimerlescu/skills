# Go date recipes (standard library `time`)

Everything here is compiled and tested in `reference/go/` (`go test ./...`,
`go test -race ./...`). Copy `recipes.go` / `calendars.go` instead of retyping.
The module declares `go 1.21` so it works on older toolchains; it only uses
`time`, `math`, `strings`, `sync` and `embed`.

## The facts that cause loops

| Question | Answer (tested) |
|---|---|
| Jan 31 `.AddDate(0, 1, 0)`? | **2026-03-03.** Go normalises Feb 31 forward; it does NOT clamp. Use `AddMonths` (clamps to Feb 28). |
| First day of next month? | `time.Date(y, m+1, 1, 0,0,0,0, time.UTC)`: month 13 normalises to January next year. |
| Last day of month m? | `time.Date(y, m+1, 0, 0,0,0,0, time.UTC)`: "day 0" = the day before the 1st. |
| Days in month? | `time.Date(y, m+1, 0, ...).Day()` |
| Weekday numbering? | `time.Sunday == 0` … `time.Saturday == 6`. Not Monday = 0. |
| Date format string? | Reference time: `"2006-01-02"`, `time.RFC3339`. `"YYYY-MM-DD"` is wrong. |
| Days between two dates? | Convert both to civil UTC dates, then `b.Sub(a).Hours() / 24`. Raw `Sub` on local times is off on DST days. |
| `AddDate(0,0,1)` vs `Add(24*time.Hour)`? | `AddDate` = same wall-clock time tomorrow. `Add(24h)` = 24 elapsed hours (13:00 after spring-forward). |
| ISO week? | `y, w := t.ISOWeek()` |
| Invalid date like Feb 30? | `time.Date` silently normalises it to Mar 2. Validate with a round trip: `t.Day() == d`. |

## Recipes (`recipes.go`)

Represent a calendar date as `time.Time` at midnight **UTC** (`datecal.Date(y, m, d)`).

```go
d := datecal.Date(2026, time.January, 5)
d.AddDate(0, 0, 90)                          // + 90 days
datecal.AddMonths(d, 1)                      // + 1 month, clamped
datecal.FirstOfNextMonth(d)                  // 2026-02-01
datecal.LastOfMonth(d)                       // 2026-01-31
datecal.NthWeekdayOfMonth(2026, time.January, time.Monday, 1) // 2026-01-05, true
datecal.NthWeekdayOfMonth(2026, time.November, time.Friday, -1) // last Friday
datecal.NextWeekday(today, time.Monday)      // strictly after
datecal.PrevWeekday(today, time.Wednesday)   // strictly before
datecal.DaysBetween(a, b)                    // b - a, DST-safe
datecal.AddBusinessDays(d, 10)
datecal.BusinessDaysBetween(a, b)            // Mon-Fri in [a, b)
datecal.EveryNDays(d, 14, false, 6)          // every 2 weeks AFTER d
datecal.EveryNMonths(d, 1, true, 12)         // monthly, no drift from the 31st
datecal.EasterWestern(2026); datecal.EasterOrthodox(2026)
```

### Worked examples

```go
// "first monday of january 2026 + 3 weeks" -> 2026-01-26
fm, _ := datecal.NthWeekdayOfMonth(2026, time.January, time.Monday, 1)
r := fm.AddDate(0, 0, 21)

// "last wednesday + 5 days", today = 2026-10-31 -> 2026-11-02
r = datecal.PrevWeekday(today, time.Wednesday).AddDate(0, 0, 5)

// "today" for a user in a zone: the date in THAT zone
loc, err := time.LoadLocation("Europe/Bucharest")
if err != nil { return err }
today := datecal.Civil(time.Now().In(loc))

// month filter: half-open range
start, end := datecal.FirstOfMonth(d), datecal.FirstOfNextMonth(d)
inMonth := !x.Before(start) && x.Before(end)
```

## Time zones

* `time.LoadLocation` needs tzdata on the machine; for static binaries add
  `import _ "time/tzdata"`. Handle the error.
* Wall-clock arithmetic: `t.AddDate` in the right `*time.Location`.
  Elapsed time: `t.Add(d)`. Compare instants with `Equal`, not `==`.

## Other calendars (`calendars.go`)

`RD(t)` / `FromRD(n)` convert to and from an integer day number (RD 1 =
0001-01-01). Then:
`JulianFromFixed`, `FixedFromJulian`, `HebrewFromFixed`, `FixedFromHebrew`
(Nisan = 1, returns ok), `HijriTabularFromFixed`, `FixedFromHijriTabular`,
`UmmAlQuraFromFixed`, `FixedFromUmmAlQura` (1343-1500 AH),
`ChineseFromFixed`, `FixedFromChinese(ChineseDate{Year, Month, Leap, Day})`
(1929-2100). All pure and safe for concurrent use.

To add N days to a Hebrew/Hijri/Chinese date: `FromRD(FixedFromX(...) + N)`,
then convert back if needed. Never add to the day field directly.

## Testing date code

* Expected values come from `scripts/datecalc.py`, not from memory.
* Table tests with edge cases: 31st + 1 month, Feb 29, Dec -> Jan, DST day,
  a 5th weekday that does not exist.
* `reference/testdata/*.csv` are golden files you can read in your own tests.
