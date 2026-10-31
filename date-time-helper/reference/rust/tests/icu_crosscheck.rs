//! `cargo test --features icu`: compares our conversions with ICU4X for every
//! day 1929..=2077, and shows how to use icu_calendar directly.
#![cfg(feature = "icu")]
use chrono::{Datelike, NaiveDate};
use datecal::calendars::*;
use icu_calendar::cal::{ChineseTraditional, Hebrew, Hijri};
use icu_calendar::{Date, Iso};

fn iso(n: i64) -> Date<Iso> {
    let d = from_rd(n);
    Date::try_new_iso(d.year(), d.month() as u8, d.day() as u8).unwrap()
}

#[test]
fn icu_usage_example() {
    // Gregorian -> Chinese
    let cny = Date::try_new_iso(2026, 2, 17).unwrap().to_calendar(ChineseTraditional::new());
    assert_eq!(cny.month().ordinal, 1);
    assert!(!cny.month().to_input().is_leap());
    assert_eq!(cny.day_of_month().0, 1);
    assert_eq!(cny.cyclic_year().related_iso, 2026);
    // Gregorian -> Hebrew. ICU month numbers count from TISHREI (1) and use a
    // leap flag for Adar I: number() = 6 is Adar (Adar II in leap years).
    let rh = Date::try_new_iso(2026, 9, 12).unwrap().to_calendar(Hebrew);
    assert_eq!((rh.year().extended_year(), rh.month().number(), rh.day_of_month().0), (5787, 1, 1));
    // Gregorian -> Hijri (Umm al-Qura)
    let r = Date::try_new_iso(2026, 2, 18).unwrap().to_calendar(Hijri::new_umm_al_qura());
    assert_eq!((r.year().extended_year(), r.month().ordinal, r.day_of_month().0), (1447, 9, 1));
}

/// R-D Hebrew month (Nisan = 1 .. Adar II = 13) -> ICU (number from Tishrei, leap flag)
fn rd_month_to_icu(y: i64, m: i64) -> (u8, bool) {
    let leap = hebrew_leap(y);
    match m {
        7..=11 => ((m - 6) as u8, false), // Tishrei..Shevat = 1..5
        12 if leap => (5, true),          // Adar I = M05L
        12 => (6, false),                 // Adar
        13 => (6, false),                 // Adar II = M06
        _ => ((m + 6) as u8, false),      // Nisan..Elul = 7..12
    }
}

#[test]
fn matches_icu_every_day() {
    let lo = rd(NaiveDate::from_ymd_opt(1929, 3, 1).unwrap());
    let hi = rd(NaiveDate::from_ymd_opt(2077, 11, 1).unwrap());
    let (ch, ua) = (ChineseTraditional::new(), Hijri::new_umm_al_qura());
    let mut uaq_diff = Vec::new();
    for n in lo..=hi {
        let i = iso(n);
        let c = chinese_from_fixed(n);
        let ic = i.to_calendar(ch);
        assert_eq!(
            (c.year, c.month, c.leap, c.day),
            (ic.cyclic_year().related_iso, ic.month().number(), ic.month().to_input().is_leap(), ic.day_of_month().0),
            "chinese {}", from_rd(n)
        );
        let (hy, hm, hd) = hebrew_from_fixed(n);
        let ih = i.to_calendar(Hebrew);
        let (num, leap) = rd_month_to_icu(hy, hm);
        assert_eq!(
            (hy as i32, num, leap, hd as u8),
            (ih.year().extended_year(), ih.month().number(), ih.month().to_input().is_leap(), ih.day_of_month().0),
            "hebrew {}", from_rd(n)
        );
        let (uy, um, ud) = umalqura_from_fixed(n).unwrap();
        let iu = i.to_calendar(ua);
        if (uy as i32, um as u8, ud as u8) != (iu.year().extended_year(), iu.month().ordinal, iu.day_of_month().0) {
            uaq_diff.push(from_rd(n));
        }
    }
    // Umm al-Qura is only "official" where Saudi Arabia published it with the
    // current rule (1420 AH = 1999 onward). ICU4X and hijridate agree on every
    // day of 1420..=1450 AH (1999-04-17 .. 2029-05-14); outside that window the
    // two projections differ by a day in some months. Treat those as estimates.
    let disagree_in_window: Vec<_> = uaq_diff
        .iter()
        .filter(|d| (1420..=1450).contains(&umalqura_from_fixed(rd(**d)).unwrap().0))
        .collect();
    eprintln!("umm al-qura: {} days differ from ICU4X overall, {} inside 1420-1450 AH", uaq_diff.len(), disagree_in_window.len());
    assert!(disagree_in_window.is_empty(), "Umm al-Qura mismatch in the consensus window: {disagree_in_window:?}");
}
