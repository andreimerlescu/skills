//! Calendar conversions with no dependencies beyond chrono (for NaiveDate).
//!
//! Everything goes through a single integer day number, RD ("rata die"):
//! RD 1 = 0001-01-01 proleptic Gregorian = chrono `num_days_from_ce() == 1`.
//! Convert ANY calendar to RD, do arithmetic on RD (it is just an integer),
//! convert back. Never add days to a Hebrew/Hijri/Chinese date by hand.
//!
//! Month numbering used here (matches scripts/datecalc.py):
//! * Julian: 1..12, astronomical years (year 0 = 1 BCE).
//! * Hebrew: Nisan = 1 ... Elul = 6, Tishrei = 7 ... Adar (Adar I in leap years) = 12,
//!   Adar II = 13. The YEAR number increments on 1 Tishrei (month 7).
//!   (ICU/icu_calendar instead uses codes from Tishrei: M01 = Tishrei, M05L = Adar I,
//!   M06 = Adar / Adar II. Do not mix the two numberings.)
//! * Hijri: Muharram = 1 ... Ramadan = 9 ... Dhu al-Hijjah = 12.
//! * Chinese: year = Gregorian year in which that Chinese New Year falls,
//!   month 1..12 plus a leap flag, day 1..30. Valid 1929..=2100.

use chrono::{Datelike, NaiveDate};

pub fn rd(d: NaiveDate) -> i64 {
    i64::from(d.num_days_from_ce())
}

pub fn from_rd(n: i64) -> NaiveDate {
    NaiveDate::from_num_days_from_ce_opt(i32::try_from(n).expect("range")).expect("range")
}

fn fdiv(a: i64, b: i64) -> i64 {
    a.div_euclid(b)
}

// ---------------------------------------------------------------- Julian

const JULIAN_EPOCH: i64 = -1;

pub fn julian_leap(y: i64) -> bool {
    y.rem_euclid(4) == 0
}

pub fn fixed_from_julian(y: i64, m: i64, d: i64) -> i64 {
    let corr = if m <= 2 { 0 } else if julian_leap(y) { -1 } else { -2 };
    JULIAN_EPOCH - 1 + 365 * (y - 1) + fdiv(y - 1, 4) + fdiv(367 * m - 362, 12) + corr + d
}

pub fn julian_from_fixed(n: i64) -> (i64, i64, i64) {
    let y = fdiv(4 * (n - JULIAN_EPOCH) + 1464, 1461);
    let prior = n - fixed_from_julian(y, 1, 1);
    let corr = if n < fixed_from_julian(y, 3, 1) { 0 } else if julian_leap(y) { 1 } else { 2 };
    let m = fdiv(12 * (prior + corr) + 373, 367);
    let d = n - fixed_from_julian(y, m, 1) + 1;
    (y, m, d)
}

// ---------------------------------------------------------------- Hebrew

const HEBREW_EPOCH: i64 = -1_373_427; // RD of 1 Tishrei AM 1

pub fn hebrew_leap(y: i64) -> bool {
    (7 * y + 1).rem_euclid(19) < 7
}

pub fn hebrew_last_month(y: i64) -> i64 {
    if hebrew_leap(y) { 13 } else { 12 }
}

fn hebrew_elapsed_days(y: i64) -> i64 {
    let months = fdiv(235 * y - 234, 19);
    let parts = 12084 + 13753 * months;
    let days = 29 * months + fdiv(parts, 25920);
    if (3 * (days + 1)).rem_euclid(7) < 3 { days + 1 } else { days }
}

fn hebrew_year_length_correction(y: i64) -> i64 {
    let (ny0, ny1, ny2) = (hebrew_elapsed_days(y - 1), hebrew_elapsed_days(y), hebrew_elapsed_days(y + 1));
    if ny2 - ny1 == 356 {
        2
    } else if ny1 - ny0 == 382 {
        1
    } else {
        0
    }
}

pub fn hebrew_new_year(y: i64) -> i64 {
    HEBREW_EPOCH + hebrew_elapsed_days(y) + hebrew_year_length_correction(y)
}

pub fn hebrew_days_in_year(y: i64) -> i64 {
    hebrew_new_year(y + 1) - hebrew_new_year(y)
}

pub fn hebrew_month_length(y: i64, m: i64) -> i64 {
    let yl = hebrew_days_in_year(y);
    match m {
        2 | 4 | 6 | 10 | 13 => 29,
        12 if !hebrew_leap(y) => 29,
        8 if yl != 355 && yl != 385 => 29,
        9 if yl == 353 || yl == 383 => 29,
        _ => 30,
    }
}

/// Returns None for a month/day that does not exist (e.g. Adar II in a common year).
pub fn fixed_from_hebrew(y: i64, m: i64, d: i64) -> Option<i64> {
    if m < 1 || m > hebrew_last_month(y) || d < 1 || d > hebrew_month_length(y, m) {
        return None;
    }
    let mut n = hebrew_new_year(y) + d - 1;
    if m < 7 {
        for mm in 7..=hebrew_last_month(y) {
            n += hebrew_month_length(y, mm);
        }
        for mm in 1..m {
            n += hebrew_month_length(y, mm);
        }
    } else {
        for mm in 7..m {
            n += hebrew_month_length(y, mm);
        }
    }
    Some(n)
}

pub fn hebrew_from_fixed(n: i64) -> (i64, i64, i64) {
    let approx = ((n - HEBREW_EPOCH) as f64 / (35_975_351.0 / 98_496.0)).floor() as i64 + 1;
    let mut y = approx - 1;
    while hebrew_new_year(y + 1) <= n {
        y += 1;
    }
    let mut m = if n < fixed_from_hebrew(y, 1, 1).unwrap() { 7 } else { 1 };
    while n > fixed_from_hebrew(y, m, hebrew_month_length(y, m)).unwrap() {
        m += 1;
    }
    let d = n - fixed_from_hebrew(y, m, 1).unwrap() + 1;
    (y, m, d)
}

// ---------------------------------------------------------------- Hijri

const ISLAMIC_EPOCH: i64 = 227_015; // 1 Muharram 1 AH (Julian 622-07-16)

/// Arithmetic ("tabular", "civil") Islamic calendar.
pub fn fixed_from_hijri_tabular(y: i64, m: i64, d: i64) -> i64 {
    ISLAMIC_EPOCH - 1 + (y - 1) * 354 + fdiv(3 + 11 * y, 30) + 29 * (m - 1) + fdiv(m, 2) + d
}

pub fn hijri_tabular_from_fixed(n: i64) -> (i64, i64, i64) {
    let y = fdiv(30 * (n - ISLAMIC_EPOCH) + 10646, 10631);
    let prior = n - fixed_from_hijri_tabular(y, 1, 1);
    let m = fdiv(11 * prior + 330, 325);
    let d = n - fixed_from_hijri_tabular(y, m, 1) + 1;
    (y, m, d)
}

const UAQ_DATA: &str = include_str!("umalqura_month_lengths.txt");
const UAQ_FIRST_RD: i64 = 702_574; // 1924-08-01 = 1 Muharram 1343
const UAQ_FIRST_YEAR: i64 = 1343;

fn uaq_starts() -> Vec<i64> {
    let mut v = vec![UAQ_FIRST_RD];
    for line in UAQ_DATA.lines().filter(|l| !l.starts_with('#')) {
        for c in line.trim().bytes() {
            let last = *v.last().unwrap();
            v.push(last + 28 + i64::from(c - b'0'));
        }
    }
    v
}

/// Umm al-Qura (official Saudi calendar), 1343..=1500 AH. None outside the table.
pub fn fixed_from_umalqura(y: i64, m: i64, d: i64) -> Option<i64> {
    let s = uaq_starts();
    let idx = (y - UAQ_FIRST_YEAR) * 12 + (m - 1);
    if !(1..=12).contains(&m) || idx < 0 || idx as usize + 1 >= s.len() {
        return None;
    }
    let (a, b) = (s[idx as usize], s[idx as usize + 1]);
    (d >= 1 && d <= b - a).then_some(a + d - 1)
}

pub fn umalqura_from_fixed(n: i64) -> Option<(i64, i64, i64)> {
    let s = uaq_starts();
    if n < s[0] || n >= *s.last().unwrap() {
        return None;
    }
    let idx = s.partition_point(|&x| x <= n) - 1;
    Some((idx as i64 / 12 + UAQ_FIRST_YEAR, idx as i64 % 12 + 1, n - s[idx] + 1))
}

// ---------------------------------------------------------------- Chinese
// Astronomical rules (Reingold & Dershowitz) with Meeus new moons. Validated
// day-by-day against sxtwl for 1929-2100 (see testdata/chinese_month_starts.csv).

const MSM: f64 = 29.530588861;
const MTY: f64 = 365.242189;

fn approx_year(t: f64) -> f64 {
    2000.0 + (t - 730_120.5) / 365.2425
}

fn delta_t_seconds(y: f64) -> f64 {
    if (2005.0..2050.0).contains(&y) {
        let t = y - 2000.0;
        62.92 + 0.32217 * t + 0.005589 * t * t
    } else if (1986.0..2005.0).contains(&y) {
        let t = y - 2000.0;
        63.86 + 0.3345 * t - 0.060374 * t.powi(2) + 0.0017275 * t.powi(3) + 0.000651814 * t.powi(4)
            + 0.00002373599 * t.powi(5)
    } else if (1961.0..1986.0).contains(&y) {
        let t = y - 1975.0;
        45.45 + 1.067 * t - t.powi(2) / 260.0 - t.powi(3) / 718.0
    } else if (1941.0..1961.0).contains(&y) {
        let t = y - 1950.0;
        29.07 + 0.407 * t - t.powi(2) / 233.0 + t.powi(3) / 2547.0
    } else if (1920.0..1941.0).contains(&y) {
        let t = y - 1920.0;
        21.20 + 0.84493 * t - 0.076100 * t.powi(2) + 0.0020936 * t.powi(3)
    } else if (1900.0..1920.0).contains(&y) {
        let t = y - 1900.0;
        -2.79 + 1.494119 * t - 0.0598939 * t.powi(2) + 0.0061966 * t.powi(3) - 0.000197 * t.powi(4)
    } else if (2050.0..2150.0).contains(&y) {
        -20.0 + 32.0 * ((y - 1820.0) / 100.0).powi(2) - 0.5628 * (2150.0 - y)
    } else {
        let u = (y - 1820.0) / 100.0;
        -20.0 + 32.0 * u * u
    }
}

fn sind(x: f64) -> f64 {
    x.to_radians().sin()
}

/// Apparent solar longitude (degrees) at UT moment t (RD with fraction).
pub fn solar_longitude(t: f64) -> f64 {
    let tt = t + delta_t_seconds(approx_year(t)) / 86400.0;
    let c = (tt - 730_120.5) / 36525.0;
    let l0 = 280.46646 + 36000.76983 * c + 0.0003032 * c * c;
    let m = 357.52911 + 35999.05029 * c - 0.0001537 * c * c;
    let eq = (1.914602 - 0.004817 * c - 0.000014 * c * c) * sind(m)
        + (0.019993 - 0.000101 * c) * sind(2.0 * m)
        + 0.000289 * sind(3.0 * m);
    let omega = 125.04 - 1934.136 * c;
    (l0 + eq - 0.00569 - 0.00478 * sind(omega)).rem_euclid(360.0)
}

const NM_A: [(f64, f64, f64); 14] = [
    (299.77, 0.107408, -0.009173), (251.88, 0.016321, 0.0), (251.83, 26.651886, 0.0),
    (349.42, 36.412478, 0.0), (84.66, 18.206239, 0.0), (141.74, 53.303771, 0.0),
    (207.14, 2.453732, 0.0), (154.84, 7.306860, 0.0), (34.52, 27.261239, 0.0),
    (207.19, 0.121824, 0.0), (291.34, 1.844379, 0.0), (161.72, 24.198154, 0.0),
    (239.56, 25.513099, 0.0), (331.55, 3.592518, 0.0),
];
const NM_AC: [f64; 14] = [
    0.000325, 0.000165, 0.000164, 0.000126, 0.000110, 0.000062, 0.000060,
    0.000056, 0.000047, 0.000042, 0.000040, 0.000037, 0.000035, 0.000023,
];

/// UT moment (RD) of new moon number k (k = 0 near 2000-01-06). Meeus ch. 49.
pub fn nth_new_moon(k: i64) -> f64 {
    let kf = k as f64;
    let t = kf / 1236.85;
    let mut jde = 2451550.09766 + 29.530588861 * kf + 0.00015437 * t * t - 0.000000150 * t.powi(3)
        + 0.00000000073 * t.powi(4);
    let e = 1.0 - 0.002516 * t - 0.0000074 * t * t;
    let m = 2.5534 + 29.10535670 * kf - 0.0000014 * t * t - 0.00000011 * t.powi(3);
    let mp = 201.5643 + 385.81693528 * kf + 0.0107582 * t * t + 0.00001238 * t.powi(3)
        - 0.000000058 * t.powi(4);
    let f = 160.7108 + 390.67050284 * kf - 0.0016118 * t * t - 0.00000227 * t.powi(3)
        + 0.000000011 * t.powi(4);
    let om = 124.7746 - 1.56375588 * kf + 0.0020672 * t * t + 0.00000215 * t.powi(3);
    let corr = -0.40720 * sind(mp) + 0.17241 * e * sind(m) + 0.01608 * sind(2.0 * mp)
        + 0.01039 * sind(2.0 * f) + 0.00739 * e * sind(mp - m) - 0.00514 * e * sind(mp + m)
        + 0.00208 * e * e * sind(2.0 * m) - 0.00111 * sind(mp - 2.0 * f)
        - 0.00057 * sind(mp + 2.0 * f) + 0.00056 * e * sind(2.0 * mp + m)
        - 0.00042 * sind(3.0 * mp) + 0.00042 * e * sind(m + 2.0 * f)
        + 0.00038 * e * sind(m - 2.0 * f) - 0.00024 * e * sind(2.0 * mp - m)
        - 0.00017 * sind(om) - 0.00007 * sind(mp + 2.0 * m) + 0.00004 * sind(2.0 * mp - 2.0 * f)
        + 0.00004 * sind(3.0 * m) + 0.00003 * sind(mp + m - 2.0 * f)
        + 0.00003 * sind(2.0 * mp + 2.0 * f) - 0.00003 * sind(mp + m + 2.0 * f)
        + 0.00003 * sind(mp - m + 2.0 * f) - 0.00002 * sind(mp - m - 2.0 * f)
        - 0.00002 * sind(3.0 * mp + m) + 0.00002 * sind(4.0 * mp);
    let extra: f64 = NM_AC
        .iter()
        .zip(NM_A.iter())
        .map(|(c, (a0, a1, a2))| c * sind(a0 + a1 * kf + a2 * t * t))
        .sum();
    jde += corr + extra;
    let t_tt = jde - 1_721_424.5;
    t_tt - delta_t_seconds(approx_year(t_tt)) / 86400.0
}

const NM0: f64 = 2451550.09766 - 1_721_424.5;

fn new_moon_at_or_after(t: f64) -> f64 {
    let mut k = ((t - NM0) / MSM).floor() as i64 - 2;
    while nth_new_moon(k) < t {
        k += 1;
    }
    nth_new_moon(k)
}

fn new_moon_before(t: f64) -> f64 {
    let mut k = ((t - NM0) / MSM).floor() as i64 + 2;
    while nth_new_moon(k) >= t {
        k -= 1;
    }
    nth_new_moon(k)
}

fn china_offset(n: f64) -> f64 {
    if n >= 704_731.0 { 8.0 / 24.0 } else { (1397.0 / 180.0) / 24.0 }
}

fn midnight_in_china(n: i64) -> f64 {
    n as f64 - china_offset(n as f64)
}

fn china_date_of(t: f64) -> i64 {
    (t + china_offset(t)).floor() as i64
}

fn estimate_prior_solar_longitude(lam: f64, tau: f64) -> f64 {
    let rate = MTY / 360.0;
    let tau1 = tau - rate * (solar_longitude(tau) - lam).rem_euclid(360.0);
    let delta = (solar_longitude(tau1) - lam + 180.0).rem_euclid(360.0) - 180.0;
    tau.min(tau1 - rate * delta)
}

fn winter_solstice_on_or_before(n: i64) -> i64 {
    let approx = estimate_prior_solar_longitude(270.0, midnight_in_china(n + 1));
    let mut i = approx.floor() as i64 - 1;
    loop {
        let s = solar_longitude(midnight_in_china(i + 1));
        if s > 270.0 && s < 300.0 {
            return i;
        }
        i += 1;
    }
}

fn cn_new_moon_on_or_after(n: i64) -> i64 {
    china_date_of(new_moon_at_or_after(midnight_in_china(n)))
}

fn cn_new_moon_before(n: i64) -> i64 {
    china_date_of(new_moon_before(midnight_in_china(n)))
}

fn major_solar_term(n: i64) -> i64 {
    let s = solar_longitude(midnight_in_china(n));
    (2 + (s / 30.0).floor() as i64 - 1).rem_euclid(12) + 1
}

fn no_major_solar_term(n: i64) -> bool {
    major_solar_term(n) == major_solar_term(cn_new_moon_on_or_after(n + 1))
}

fn prior_leap_month(m_prime: i64, mut m: i64) -> bool {
    while m >= m_prime {
        if no_major_solar_term(m) {
            return true;
        }
        m = cn_new_moon_before(m);
    }
    false
}

fn cn_new_year_in_sui(n: i64) -> i64 {
    let s1 = winter_solstice_on_or_before(n);
    let s2 = winter_solstice_on_or_before(s1 + 370);
    let m12 = cn_new_moon_on_or_after(s1 + 1);
    let m13 = cn_new_moon_on_or_after(m12 + 1);
    let next_m11 = cn_new_moon_before(s2 + 1);
    if ((next_m11 - m12) as f64 / MSM).round() as i64 == 12
        && (no_major_solar_term(m12) || no_major_solar_term(m13))
    {
        cn_new_moon_on_or_after(m13 + 1)
    } else {
        m13
    }
}

pub fn chinese_new_year_on_or_before(n: i64) -> i64 {
    let ny = cn_new_year_in_sui(n);
    if n >= ny { ny } else { cn_new_year_in_sui(n - 180) }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChineseDate {
    /// Gregorian year in which this Chinese year's New Year falls.
    pub year: i32,
    pub month: u8,
    pub leap: bool,
    pub day: u8,
}

pub fn chinese_from_fixed(n: i64) -> ChineseDate {
    let s1 = winter_solstice_on_or_before(n);
    let s2 = winter_solstice_on_or_before(s1 + 370);
    let m12 = cn_new_moon_on_or_after(s1 + 1);
    let next_m11 = cn_new_moon_before(s2 + 1);
    let m = cn_new_moon_before(n + 1);
    let leap_year = ((next_m11 - m12) as f64 / MSM).round() as i64 == 12;
    let raw = ((m - m12) as f64 / MSM).round() as i64
        - if leap_year && prior_leap_month(m12, m) { 1 } else { 0 };
    let month = (raw - 1).rem_euclid(12) + 1;
    let leap = leap_year && no_major_solar_term(m) && !prior_leap_month(m12, cn_new_moon_before(m));
    ChineseDate {
        year: from_rd(chinese_new_year_on_or_before(n)).year(),
        month: month as u8,
        leap,
        day: (n - m + 1) as u8,
    }
}

/// None if that (leap) month/day does not exist in that year.
pub fn fixed_from_chinese(c: ChineseDate) -> Option<i64> {
    let ny = chinese_new_year_on_or_before(rd(NaiveDate::from_ymd_opt(c.year, 7, 1)?));
    let p = cn_new_moon_on_or_after(ny + (i64::from(c.month) - 1) * 29);
    let d = chinese_from_fixed(p);
    let start = if d.month == c.month && d.leap == c.leap { p } else { cn_new_moon_on_or_after(p + 1) };
    let n = start + i64::from(c.day) - 1;
    (chinese_from_fixed(n) == c).then_some(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn d(s: &str) -> NaiveDate {
        NaiveDate::parse_from_str(s, "%Y-%m-%d").unwrap()
    }

    #[test]
    fn known_dates() {
        assert_eq!(julian_from_fixed(rd(d("2026-01-14"))), (2026, 1, 1));
        assert_eq!(hebrew_from_fixed(rd(d("2026-09-12"))), (5787, 7, 1)); // Rosh Hashanah
        assert_eq!(hebrew_from_fixed(rd(d("2026-04-02"))), (5786, 1, 15)); // Passover
        assert_eq!(umalqura_from_fixed(rd(d("2026-02-18"))), Some((1447, 9, 1))); // Ramadan
        assert_eq!(
            chinese_from_fixed(rd(d("2026-02-17"))),
            ChineseDate { year: 2026, month: 1, leap: false, day: 1 }
        );
        let leap6 = ChineseDate { year: 2025, month: 6, leap: true, day: 1 };
        assert_eq!(fixed_from_chinese(leap6).map(from_rd), Some(d("2025-07-25")));
        assert_eq!(fixed_from_hebrew(5786, 13, 1), None); // 5786 is not a leap year
    }
}
