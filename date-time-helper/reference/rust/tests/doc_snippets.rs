//! Compiles the inline snippets from reference/rust.md.
use chrono::{Datelike, Days, Months, NaiveDate, TimeDelta, Utc};
use datecal::recipes::*;

#[test]
fn snippets_from_rust_md() {
    let d = NaiveDate::from_ymd_opt(2026, 1, 5).unwrap();
    assert_eq!(d.checked_add_days(Days::new(90)), NaiveDate::from_ymd_opt(2026, 4, 5));
    assert_eq!(d.checked_sub_days(Days::new(5)), NaiveDate::from_ymd_opt(2025, 12, 31));
    assert_eq!(d.checked_add_months(Months::new(3)), NaiveDate::from_ymd_opt(2026, 4, 5));
    assert_eq!(d + TimeDelta::weeks(3), NaiveDate::from_ymd_opt(2026, 1, 26).unwrap());
    assert_eq!(NaiveDate::from_ymd_opt(2026, 2, 30), None);
    assert_eq!(d.iso_week().week(), 2);
    let fnm = d.with_day(1).unwrap().checked_add_months(Months::new(1)).unwrap();
    assert_eq!(fnm, NaiveDate::from_ymd_opt(2026, 2, 1).unwrap());
    assert_eq!(fnm.pred_opt().unwrap().day(), 31);
    let ms = d.and_hms_opt(0, 0, 0).unwrap().and_utc().timestamp_millis();
    assert_eq!(ms, 1_767_571_200_000);
    let _today_ny = Utc::now().with_timezone(&chrono_tz::America::New_York).date_naive();
    let v = every_n_days(d, 14, false, 3);
    assert_eq!(v[0], NaiveDate::from_ymd_opt(2026, 1, 19).unwrap());
    let (start, end) = (first_of_month(d), first_of_next_month(d));
    let in_month = |x: NaiveDate| x >= start && x < end;
    assert!(in_month(NaiveDate::from_ymd_opt(2026, 1, 31).unwrap()));
    assert!(!in_month(NaiveDate::from_ymd_opt(2026, 2, 1).unwrap()));
}
