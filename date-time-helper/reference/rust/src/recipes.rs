//! Gregorian date recipes with chrono 0.4. Every function here is covered by
//! tests against golden data produced by `scripts/datecalc.py`.
//!
//! Rules of thumb:
//! * Calendar dates are `NaiveDate`. Do NOT do date math on `DateTime<Tz>`
//!   unless you really mean instants; convert to the local `NaiveDate` first.
//! * Never compute month lengths or weekdays by hand. Ask chrono.
//! * `Months::new(n)` adds EXACTLY n months (Jan + Months::new(1) = Feb).
//!   If the day does not exist in the target month it is CLAMPED to the last
//!   day (Jan 31 + 1 month = Feb 28/29).
//! * `Days::new(n)` adds n days. `Duration::days(n)` / `TimeDelta::days(n)`
//!   also works with `NaiveDate + ...`.

use chrono::{Datelike, Days, Months, NaiveDate, Weekday};

/// date + n days (n may be negative). None only on overflow.
pub fn add_days(d: NaiveDate, n: i64) -> Option<NaiveDate> {
    if n >= 0 {
        d.checked_add_days(Days::new(n as u64))
    } else {
        d.checked_sub_days(Days::new(n.unsigned_abs()))
    }
}

/// date + n calendar months, clamping the day (2026-01-31 + 1 = 2026-02-28).
/// Months::new(n) adds exactly n months: Months::new(1) is "next month".
pub fn add_months(d: NaiveDate, n: i32) -> Option<NaiveDate> {
    if n >= 0 {
        d.checked_add_months(Months::new(n as u32))
    } else {
        d.checked_sub_months(Months::new(n.unsigned_abs()))
    }
}

/// date + n years (Feb 29 + 1 year = Feb 28).
pub fn add_years(d: NaiveDate, n: i32) -> Option<NaiveDate> {
    add_months(d, n.checked_mul(12)?)
}

/// First day of the month containing `d`.
pub fn first_of_month(d: NaiveDate) -> NaiveDate {
    d.with_day(1).expect("day 1 always exists")
}

/// First day of the following month. (The answer to "what is the boundary of
/// this month" — use it as an exclusive upper bound: [first_of_month, first_of_next_month).)
pub fn first_of_next_month(d: NaiveDate) -> NaiveDate {
    first_of_month(d)
        .checked_add_months(Months::new(1))
        .expect("in range")
}

/// Last day of the month containing `d`.
pub fn last_of_month(d: NaiveDate) -> NaiveDate {
    first_of_next_month(d).pred_opt().expect("in range")
}

/// Number of days in a month.
pub fn days_in_month(year: i32, month: u32) -> u32 {
    let first = NaiveDate::from_ymd_opt(year, month, 1).expect("valid month");
    last_of_month(first).day()
}

/// nth weekday of a month. n = 1..=5 counts from the start, n = -1 is the
/// last, -2 second-to-last. None if it does not exist (e.g. 5th Monday).
pub fn nth_weekday_of_month(year: i32, month: u32, wd: Weekday, n: i32) -> Option<NaiveDate> {
    if n > 0 {
        // chrono has this built in: n is 1-based.
        NaiveDate::from_weekday_of_month_opt(year, month, wd, u8::try_from(n).ok()?)
    } else if n < 0 {
        let last = last_of_month(NaiveDate::from_ymd_opt(year, month, 1)?);
        let back = (last.weekday().num_days_from_monday() + 7 - wd.num_days_from_monday()) % 7;
        let d = last - Days::new(u64::from(back) + 7 * (n.unsigned_abs() as u64 - 1));
        (d.month() == month).then_some(d)
    } else {
        None
    }
}

/// First `wd` strictly after `d` ("next Monday" when d is today).
pub fn next_weekday(d: NaiveDate, wd: Weekday) -> NaiveDate {
    let ahead = (wd.num_days_from_monday() + 7 - d.weekday().num_days_from_monday()) % 7;
    d + Days::new(if ahead == 0 { 7 } else { ahead } as u64)
}

/// First `wd` on or after `d` (d itself if it is already that weekday).
pub fn weekday_on_or_after(d: NaiveDate, wd: Weekday) -> NaiveDate {
    let ahead = (wd.num_days_from_monday() + 7 - d.weekday().num_days_from_monday()) % 7;
    d + Days::new(ahead as u64)
}

/// Most recent `wd` strictly before `d` ("last Wednesday" when d is today).
pub fn prev_weekday(d: NaiveDate, wd: Weekday) -> NaiveDate {
    let back = (d.weekday().num_days_from_monday() + 7 - wd.num_days_from_monday()) % 7;
    d - Days::new(if back == 0 { 7 } else { back } as u64)
}

/// Monday of the ISO week containing `d`.
pub fn start_of_iso_week(d: NaiveDate) -> NaiveDate {
    d - Days::new(d.weekday().num_days_from_monday() as u64)
}

/// Signed whole days from a to b (b - a).
pub fn days_between(a: NaiveDate, b: NaiveDate) -> i64 {
    (b - a).num_days()
}

pub fn is_business_day(d: NaiveDate) -> bool {
    !matches!(d.weekday(), Weekday::Sat | Weekday::Sun)
}

/// Move n business days (Mon-Fri). From a Saturday, +1 lands on Monday.
/// Add your own holiday check inside the loop if you need one.
pub fn add_business_days(mut d: NaiveDate, n: i64) -> NaiveDate {
    let step: i64 = if n >= 0 { 1 } else { -1 };
    for _ in 0..n.unsigned_abs() {
        d = add_days(d, step).expect("in range");
        while !is_business_day(d) {
            d = add_days(d, step).expect("in range");
        }
    }
    d
}

/// Business days in the half-open range [a, b). Negative if b < a.
pub fn business_days_between(a: NaiveDate, b: NaiveDate) -> i64 {
    let (lo, hi, sign) = if b >= a { (a, b, 1) } else { (b, a, -1) };
    let total = (hi - lo).num_days();
    let (weeks, rem) = (total / 7, total % 7);
    let mut count = weeks * 5;
    for i in 0..rem {
        if is_business_day(lo + Days::new((weeks * 7 + i) as u64)) {
            count += 1;
        }
    }
    sign * count
}

/// "every `step_days` days starting at `start`": occurrence k = start + k*step.
/// Use `include_start = false` for "every 2 weeks AFTER <date>".
pub fn every_n_days(start: NaiveDate, step_days: i64, include_start: bool, count: usize) -> Vec<NaiveDate> {
    let first = if include_start { 0 } else { 1 };
    (first..first + count as i64)
        .map(|k| add_days(start, k * step_days).expect("in range"))
        .collect()
}

/// "every n months from <start>": computed from the START each time
/// (start + k*n months), so a 31st start gives Jan 31, Feb 28, Mar 31, Apr 30
/// instead of drifting to the 28th forever.
pub fn every_n_months(start: NaiveDate, n: i32, include_start: bool, count: usize) -> Vec<NaiveDate> {
    let first = if include_start { 0 } else { 1 };
    (first..first + count as i32)
        .map(|k| add_months(start, k * n).expect("in range"))
        .collect()
}

/// Western Easter Sunday (anonymous Gregorian algorithm).
pub fn easter_western(y: i32) -> NaiveDate {
    let a = y % 19;
    let (b, c) = (y / 100, y % 100);
    let (d, e) = (b / 4, b % 4);
    let f = (b + 8) / 25;
    let g = (b - f + 1) / 3;
    let h = (19 * a + b - d - g + 15) % 30;
    let (i, k) = (c / 4, c % 4);
    let l = (32 + 2 * e + 2 * i - h - k) % 7;
    let m = (a + 11 * h + 22 * l) / 451;
    let month = (h + l - 7 * m + 114) / 31;
    let day = (h + l - 7 * m + 114) % 31 + 1;
    NaiveDate::from_ymd_opt(y, month as u32, day as u32).expect("valid")
}

/// Orthodox Easter (Julian computus) returned as a Gregorian date.
pub fn easter_orthodox(y: i32) -> NaiveDate {
    let (a, b, c) = (y % 4, y % 7, y % 19);
    let d = (19 * c + 15) % 30;
    let e = (2 * a + 4 * b - d + 34) % 7;
    let month = (d + e + 114) / 31;
    let day = (d + e + 114) % 31 + 1;
    let rd = crate::calendars::fixed_from_julian(y as i64, month as i64, day as i64);
    crate::calendars::from_rd(rd)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn d(s: &str) -> NaiveDate {
        NaiveDate::parse_from_str(s, "%Y-%m-%d").unwrap()
    }

    #[test]
    fn the_examples_from_the_skill() {
        // "first monday of january 2026 + 3 weeks"
        let fm = nth_weekday_of_month(2026, 1, Weekday::Mon, 1).unwrap();
        assert_eq!(fm, d("2026-01-05"));
        assert_eq!(add_days(fm, 21).unwrap(), d("2026-01-26"));
        // "today + 90 days" with today = 2026-10-31
        assert_eq!(add_days(d("2026-10-31"), 90).unwrap(), d("2027-01-29"));
        // "last wednesday + 5 days" with today = 2026-10-31 (Saturday)
        let lw = prev_weekday(d("2026-10-31"), Weekday::Wed);
        assert_eq!(lw, d("2026-10-28"));
        assert_eq!(add_days(lw, 5).unwrap(), d("2026-11-02"));
    }

    #[test]
    fn months_new_semantics() {
        // Months::new(N) adds exactly N months. This is the fact that the
        // looping agent kept second-guessing.
        let jan8 = d("2026-01-08");
        for n in 0..12u32 {
            let got = jan8.checked_add_months(Months::new(n)).unwrap();
            assert_eq!(got.month(), 1 + n);
            assert_eq!(got.day(), 8);
        }
        assert_eq!(add_months(d("2026-01-31"), 1).unwrap(), d("2026-02-28"));
        assert_eq!(add_months(d("2024-01-31"), 1).unwrap(), d("2024-02-29"));
        assert_eq!(first_of_next_month(d("2026-12-15")), d("2027-01-01"));
        assert_eq!(last_of_month(d("2028-02-10")), d("2028-02-29"));
    }

    #[test]
    fn every_month_does_not_drift() {
        let v = every_n_months(d("2026-01-31"), 1, true, 4);
        assert_eq!(v, vec![d("2026-01-31"), d("2026-02-28"), d("2026-03-31"), d("2026-04-30")]);
    }
}
