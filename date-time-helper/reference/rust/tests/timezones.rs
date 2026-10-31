//! Calendar-day vs absolute-time arithmetic across a DST change (chrono-tz).
use chrono::{Days, NaiveDate, TimeDelta, TimeZone};
use chrono_tz::America::New_York;

#[test]
fn calendar_day_vs_24_hours_across_dst() {
    // 2026-03-08 is the US spring-forward day (02:00 -> 03:00).
    let start = New_York.with_ymd_and_hms(2026, 3, 7, 12, 0, 0).single().unwrap();

    // "+1 day" (same wall-clock time tomorrow): do it on the naive LOCAL
    // date-time, then re-attach the zone.
    let local_next = start.naive_local().checked_add_days(Days::new(1)).unwrap();
    let plus_one_day = New_York.from_local_datetime(&local_next).earliest().unwrap();
    assert_eq!(plus_one_day.to_rfc3339(), "2026-03-08T12:00:00-04:00");

    // "+24 hours" (absolute elapsed time): add a TimeDelta to the DateTime.
    let plus_24h = start.checked_add_signed(TimeDelta::hours(24)).unwrap();
    assert_eq!(plus_24h.to_rfc3339(), "2026-03-08T13:00:00-04:00");

    // A wall-clock time inside the gap does not exist: single()/earliest() say so.
    let gap = NaiveDate::from_ymd_opt(2026, 3, 8).unwrap().and_hms_opt(2, 30, 0).unwrap();
    assert!(New_York.from_local_datetime(&gap).earliest().is_none());

    // "Today" in a zone is the local date of now, not the UTC date.
    let late_utc = chrono::Utc.with_ymd_and_hms(2026, 11, 1, 2, 0, 0).unwrap();
    assert_eq!(late_utc.with_timezone(&New_York).date_naive(), NaiveDate::from_ymd_opt(2026, 10, 31).unwrap());
}
