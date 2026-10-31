# The five calendars: rules, numbering, traps

Universal method: **convert to one integer day number (RD), do arithmetic on
the integer, convert back.** RD 1 = 0001-01-01 proleptic Gregorian =
Python `date.toordinal()` = chrono `num_days_from_ce()` = Go `datecal.RD(t)`.
Julian Day Number = RD + 1721425. Unix day = RD - 719163.

`scripts/datecalc.py convert <date>` shows a date in all five. For maths
across calendars use tags: `hebrew:5787-tishrei-1 + 100 days`.

## Gregorian
* Leap year: divisible by 4, except centuries, except every 400th (2000 yes, 2100 no).
* Month lengths: 31,28/29,31,30,31,30,31,31,30,31,30,31. Ask the library anyway.
* Week: ISO weeks start Monday; week 1 contains the year's first Thursday,
  so 2025-12-29 is in ISO week 2026-W01.
* Proleptic: extended backwards before 1582 (what all libraries do).

## Julian
* Leap year every 4 years, no exceptions. Currently 13 days behind Gregorian
  (2026-01-14 Gregorian = 2026-01-01 Julian); becomes 14 days on 2100-03-01 (Gregorian).
* Used by several Orthodox churches: Orthodox Christmas (Julian Dec 25) = Gregorian Jan 7.
* Orthodox Easter uses the Julian computus (`orthodox easter 2026` = 2026-04-12).

## Hebrew (arithmetic, exact)
* Lunisolar. 19-year cycle with 7 leap years (years 3, 6, 8, 11, 14, 17, 19);
  leap years add a 30-day Adar I. Year lengths: 353/354/355 or 383/384/385.
* **The year number changes on 1 Tishrei (autumn), not 1 Nisan.**
  AM year = Gregorian + 3760 (Jan-Sep) or + 3761 (Sep-Dec).
* Numbering in this skill (Reingold-Dershowitz): Nisan 1, Iyyar 2, Sivan 3,
  Tammuz 4, Av 5, Elul 6, Tishrei 7, Heshvan 8, Kislev 9, Tevet 10, Shevat 11,
  Adar 12 (Adar I in leap years), Adar II 13.
* ICU/icu_calendar numbers from Tishrei = 1 and marks Adar I as a leap month.
  Convert explicitly; never mix.
* Days begin at sunset. A holiday "on" 2026-09-12 starts the evening of 09-11.
* Heshvan and Kislev vary between 29/30 days. Do not assume month lengths.
* Holidays: Rosh Hashanah 1 Tishrei, Yom Kippur 10 Tishrei, Sukkot 15 Tishrei,
  Hanukkah 25 Kislev, Purim 14 Adar (14 Adar II in leap years),
  Passover 15 Nisan, Shavuot 6 Sivan.

## Hijri / Islamic
* Purely lunar: 12 months of 29/30 days, year about 354 days. It drifts about 11
  days earlier each Gregorian year, so an event can occur twice in one
  Gregorian year (Ramadan in 2030: Jan 5 and Dec 26).
* Months: Muharram 1, Safar 2, Rabi al-Awwal 3, Rabi al-Thani 4, Jumada al-Ula 5,
  Jumada al-Akhirah 6, Rajab 7, Shaban 8, **Ramadan 9**, Shawwal 10,
  Dhu al-Qadah 11, Dhu al-Hijjah 12.
* Three different things are all called "Hijri":
  1. **Umm al-Qura** (`hijri:`): official Saudi calendar, table-based.
     ICU4X and the KACST-derived table agree on every day of 1420-1450 AH
     (1999-2029). Outside that window, sources differ by a day in some months.
  2. **Tabular / civil** (`hijri-tabular:`): pure arithmetic (30-year cycle,
     leap years 2,5,7,10,13,16,18,21,24,26,29). Good for any year, but can be
     a day or two off Umm al-Qura.
  3. **Observational**: many countries start months on actual moon sighting.
     Nobody can compute this in advance. For religious dates, say
     "expected on X, subject to moon sighting".
* Days begin at sunset.
* Holidays: Islamic New Year 1 Muharram, Ramadan begins 1 Ramadan, Eid al-Fitr
  1 Shawwal, Eid al-Adha 10 Dhu al-Hijjah.

## Chinese (lunisolar, astronomical)
* Months start on the day (Beijing time, UTC+8) of the astronomical new moon.
  Month 11 contains the December solstice. A year has 12 or 13 months. In a
  13-month year, the first month with no "major solar term" is the leap month
  and repeats the previous month's number (2025 had leap month 6).
* Chinese New Year = month 1 day 1, between Jan 21 and Feb 20. In this skill a
  Chinese year is named by the Gregorian year in which its New Year falls
  (`chinese:2026-1-1` = 2026-02-17). Sexagenary label: stem = (Y-4) mod 10,
  branch/animal = (Y-4) mod 12 (2026 = Bing-Wu, Horse).
* Leap month syntax: `chinese:2025-L6-1`.
* **Validated range 1929-2100**: identical every day to sxtwl and ICU4X.
  Before 1929, official almanacs used older rules and differ in parts of 1906,
  1917 and 1922. You cannot compute it with fixed arithmetic; you need
  astronomy or a table. Do not invent "every 3rd year is leap" style rules.
* Holidays: New Year 1-1, Lantern 1-15, Dragon Boat 5-5, Mid-Autumn 8-15.

## Easter
* Western: Gregorian computus (`easter 2026` = 2026-04-05).
* Orthodox: Julian computus, then convert to Gregorian (2026-04-12).
* Both verified 1583-3999 against python-dateutil.

## Verification sources used for this skill
convertdate (Julian, Hebrew, tabular Islamic, every day 1700-2300), hijridate
(Umm al-Qura, every day 1924-2077), sxtwl (Chinese, every day 1900-2100),
ICU4X icu_calendar 2.4 (Chinese, Hebrew, Umm al-Qura, every day 1929-2077),
pyephem (new moons within 34 s), python-dateutil (month arithmetic, nth
weekday, Easter), numpy busday_count (business days).
