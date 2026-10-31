# Rust date recipes (chrono 0.4)

Every snippet here is compiled and tested in `reference/rust/` (`cargo test`,
`cargo test --features icu`). Copy `src/recipes.rs` or `src/calendars.rs`
instead of retyping.

## The facts that cause loops

| Question you keep asking yourself | Answer (tested) |
|---|---|
| What does `Months::new(n)` add? | **Exactly n months.** `Months::new(1)` = next month. Jan 8 + `Months::new(4)` = May 8. There is no hidden offset. |
| Jan 31 + 1 month? | `checked_add_months` **clamps**: 2026-02-28 (2024-02-29 in a leap year). |
| Feb 29 + 1 year? | `checked_add_months(Months::new(12))` gives Feb 28. |
| First day of next month? | `d.with_day(1)?.checked_add_months(Months::new(1))?` |
| Last day of this month? | first-of-next-month `.pred_opt()?` |
| Days in a month? | last-of-month `.day()`. Never hardcode a table. |
| Which `day` can I safely use with `from_ymd_opt` in every month? | Days 1..=28. Better: build from day 1, then clamp or use the helpers. |
| Does `from_ymd_opt` panic on bad input? | No, it returns `None` (e.g. Feb 30). `from_ymd` (no `_opt`) is deprecated and panics. |
| Weekday numbering? | `wd.num_days_from_monday()` (Mon=0) or `num_days_from_sunday()` (Sun=0). Pick one and say which. |
| nth weekday of a month? | `NaiveDate::from_weekday_of_month_opt(y, m, Weekday::Mon, n)` with n = 1..=5. `None` if absent. |
| ISO week? | `d.iso_week().year()`, `.week()`. ISO year can differ from `d.year()` around New Year. |

## Recipes (`src/recipes.rs`)

```rust
use chrono::{Datelike, Days, Months, NaiveDate, Weekday};

let d = NaiveDate::from_ymd_opt(2026, 1, 5).unwrap();
d.checked_add_days(Days::new(90));            // + 90 days
d.checked_sub_days(Days::new(5));             // - 5 days
d.checked_add_months(Months::new(3));         // + 3 months (clamped)
d + chrono::TimeDelta::weeks(3);              // + 3 weeks (TimeDelta == old Duration)
(b - a).num_days();                           // signed day difference, b - a
d.weekday();                                  // Weekday::Mon
d.succ_opt(); d.pred_opt();                   // next / previous day
```

Helpers in `recipes.rs` (all golden-tested):
`add_days`, `add_months`, `add_years`, `first_of_month`, `first_of_next_month`,
`last_of_month`, `days_in_month`, `nth_weekday_of_month(y, m, wd, n)` (n = -1 is
last), `next_weekday` (strictly after), `weekday_on_or_after`, `prev_weekday`
(strictly before), `start_of_iso_week`, `days_between`, `add_business_days`,
`business_days_between` (half-open `[a, b)`), `every_n_days`, `every_n_months`
(no drift), `easter_western`, `easter_orthodox`.

### Worked examples

```rust
// "first monday of january 2026 + 3 weeks" -> 2026-01-26
let fm = nth_weekday_of_month(2026, 1, Weekday::Mon, 1).unwrap(); // 2026-01-05
let r = add_days(fm, 21).unwrap();

// "last wednesday + 5 days" (today 2026-10-31, a Saturday) -> 2026-11-02
let r = add_days(prev_weekday(today, Weekday::Wed), 5).unwrap();

// "every 2 weeks after 2026-01-05" -> 01-19, 02-02, 02-16, ...
let v = every_n_days(d, 14, /*include_start*/ false, 6);

// month/year filters: half-open ranges, never "<= last day 23:59:59"
let start = first_of_month(d);
let end = first_of_next_month(d);   // exclusive
let in_month = |x: NaiveDate| x >= start && x < end;
```

## Instants, zones, DST (`tests/timezones.rs`)

* Calendar maths happens on `NaiveDate` / `NaiveDateTime` in **local** time.
  Elapsed-time maths happens on `DateTime<Tz>` with `TimeDelta`.
* "+1 day, same wall-clock time" across DST:
  ```rust
  let local = dt.naive_local().checked_add_days(Days::new(1)).unwrap();
  let next = tz.from_local_datetime(&local).earliest();   // None inside a DST gap
  ```
* "+24 hours": `dt.checked_add_signed(TimeDelta::hours(24))`.
* "Today" for a user = `Utc::now().with_timezone(&tz).date_naive()`, not the UTC date.
* Time zones need `chrono-tz` (`chrono_tz::America::New_York`). `chrono::Local`
  is the machine's zone, which is rarely the user's.
* Unix ms for UTC midnight: `d.and_hms_opt(0,0,0)?.and_utc().timestamp_millis()`.

## Other calendars

Dependency-free (only chrono for `NaiveDate`): `src/calendars.rs`
* `rd(NaiveDate) -> i64` and `from_rd(i64)`. RD == `num_days_from_ce()`.
* `julian_from_fixed`, `fixed_from_julian`
* `hebrew_from_fixed`, `fixed_from_hebrew` (Nisan = 1 numbering, returns `Option`)
* `hijri_tabular_from_fixed`, `fixed_from_hijri_tabular`
* `umalqura_from_fixed`, `fixed_from_umalqura` (1343-1500 AH table)
* `chinese_from_fixed`, `fixed_from_chinese(ChineseDate{year, month, leap, day})` (1929-2100)

Or use ICU4X (`icu_calendar = "2"`), the Unicode reference implementation.
Verified with icu_calendar 2.4:

```rust
use icu_calendar::cal::{ChineseTraditional, Hebrew, Hijri};
use icu_calendar::Date;

let iso = Date::try_new_iso(2026, 2, 17).unwrap();
let c = iso.to_calendar(ChineseTraditional::new());
c.cyclic_year().related_iso;      // 2026
c.month().number();               // 1   (month number, leap flag separate)
c.month().to_input().is_leap();   // false
c.day_of_month().0;               // 1

let h = Date::try_new_iso(2026, 9, 12).unwrap().to_calendar(Hebrew);
h.year().extended_year();         // 5787
h.month().number();               // 1  <- ICU counts from TISHREI, not Nisan!

let u = Date::try_new_iso(2026, 2, 18).unwrap().to_calendar(Hijri::new_umm_al_qura());
(u.year().extended_year(), u.month().ordinal, u.day_of_month().0); // (1447, 9, 1)
```

ICU Hebrew months: Tishrei=1 … Shevat=5, Adar I = 5 with leap flag (M05L),
Adar / Adar II = 6, Nisan = 7 … Elul = 12. `calendars.rs` uses Nisan = 1.
`tests/icu_crosscheck.rs` has the conversion and checks both agree every day
1929-2077. icu_calendar's API changed during 2.x (deprecations in 2.1/2.2):
if a call does not compile, run `cargo doc --open -p icu_calendar` rather
than guessing.

## Testing date code

1. Get expected values from `scripts/datecalc.py` (never from your head).
2. Assert them in a `#[test]`. Include the edge cases: 31st + 1 month,
   Feb 29, December -> January, a DST day, a 5th weekday that does not exist.
3. `reference/testdata/*.csv` are golden files you can load in your own tests.
