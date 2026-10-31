#!/usr/bin/env python3
"""
datecalc.py - a verified date/time calculator for coding agents.

Pure standard library (Python 3.9+). No network, no third-party packages.

Why this exists: language models are bad at calendar arithmetic done "in the
head" (which weekday is Jan 5? how long is February? does Months::new(1) add
one month?). This tool does the arithmetic deterministically and prints the
steps, so the agent can answer, or write a test with known-good expected
values, instead of guessing.

QUICK START
    python3 datecalc.py "first monday of january 2026 + 3 weeks"
    python3 datecalc.py "today + 90 days"
    python3 datecalc.py "last wednesday + 5 days"
    python3 datecalc.py "every 2 weeks after 2026-01-05 count 6"
    python3 datecalc.py "days between 2026-01-01 and 2026-03-15"
    python3 datecalc.py "first day of next month"
    python3 datecalc.py "2026-01-31 + 1 month"          # clamps to 2026-02-28
    python3 datecalc.py "passover 2026"                 # holiday lookup
    python3 datecalc.py convert 2026-10-31              # all 5 calendars
    python3 datecalc.py convert "hebrew:5787-tishrei-1" # any calendar -> all
    python3 datecalc.py info 2026-02-17                 # weekday, ISO week, ...
    python3 datecalc.py examples                        # grammar cheat sheet
    python3 datecalc.py selftest                        # verify on this machine

GLOBAL OPTIONS (put them before or after the expression)
    --today YYYY-MM-DD    fix "today" (makes answers reproducible)
    --now ISO-DATETIME    fix "now" (e.g. 2026-10-31T09:15:00+02:00)
    --tz ZONE             IANA zone for today/now and DST-aware hour maths
    --holidays D,D,...    extra non-business days for "business days" maths
    --order mdy|dmy       how to read ambiguous slash dates like 03/04/2026
    --json                machine-readable output

Calendars: gregorian (proleptic), julian, hebrew, hijri (Umm al-Qura, the
official Saudi calendar, AH 1343-1500 = 1924-2077), hijri-tabular (arithmetic
"civil" Islamic calendar, any year), chinese (astronomical, 1900-2100).

Algorithms: Reingold & Dershowitz "Calendrical Calculations" for julian /
hebrew / tabular islamic / chinese; Meeus "Astronomical Algorithms" ch.49 for
new moons. Umm al-Qura month lengths are from the MIT-licensed `hijridate`
package (c) Mohammed Alshehri. See `selftest` for the verification set.
"""

from __future__ import annotations

import argparse
import calendar as _cal
import json
import math
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

__version__ = "1.0.0"


class CalcError(Exception):
    """A user-facing error with a helpful message."""


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday"]
WEEKDAYS = {
    "mon": 0, "monday": 0, "mondays": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "tuesdays": 1,
    "wed": 2, "weds": 2, "wednesday": 2, "wednesdays": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "thursdays": 3,
    "fri": 4, "friday": 4, "fridays": 4,
    "sat": 5, "saturday": 5, "saturdays": 5,
    "sun": 6, "sunday": 6, "sundays": 6,
}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MONTHS = {}
for _i, _n in enumerate(MONTH_NAMES, 1):
    MONTHS[_n.lower()] = _i
    MONTHS[_n.lower()[:3]] = _i
MONTHS["sept"] = 9

ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "last": -1, "penultimate": -2,
}
NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "hundred": 100,
}
UNITS = {
    "second": "seconds", "seconds": "seconds", "sec": "seconds", "secs": "seconds", "s": "seconds",
    "minute": "minutes", "minutes": "minutes", "min": "minutes", "mins": "minutes",
    "hour": "hours", "hours": "hours", "hr": "hours", "hrs": "hours", "h": "hours",
    "day": "days", "days": "days", "d": "days",
    "week": "weeks", "weeks": "weeks", "wk": "weeks", "wks": "weeks", "w": "weeks",
    "fortnight": "fortnights", "fortnights": "fortnights",
    "month": "months", "months": "months", "mo": "months", "mos": "months",
    "quarter": "quarters", "quarters": "quarters",
    "year": "years", "years": "years", "yr": "years", "yrs": "years", "y": "years",
    "decade": "decades", "decades": "decades",
    "weekday": "bdays", "weekdays": "bdays",   # "5 weekdays" == business days
}
TIME_UNITS = {"seconds", "minutes", "hours"}

HEBREW_MONTHS = {  # Reingold-Dershowitz numbering: Nisan = 1 ... Adar II = 13
    1: "Nisan", 2: "Iyyar", 3: "Sivan", 4: "Tammuz", 5: "Av", 6: "Elul",
    7: "Tishrei", 8: "Heshvan", 9: "Kislev", 10: "Tevet", 11: "Shevat",
    12: "Adar", 13: "Adar II",
}
HEBREW_MONTH_ALIASES = {
    "nisan": 1, "nissan": 1, "iyyar": 2, "iyar": 2, "sivan": 3, "tammuz": 4,
    "tamuz": 4, "av": 5, "ab": 5, "elul": 6, "tishrei": 7, "tishri": 7,
    "heshvan": 8, "cheshvan": 8, "marcheshvan": 8, "marheshvan": 8,
    "kislev": 9, "tevet": 10, "teveth": 10, "shevat": 11, "shvat": 11,
    "shebat": 11, "adar": 12, "adar1": 12, "adari": 12, "adar2": 13,
    "adarii": 13, "veadar": 13,
}
HIJRI_MONTHS = ["Muharram", "Safar", "Rabi al-Awwal", "Rabi al-Thani",
                "Jumada al-Ula", "Jumada al-Akhirah", "Rajab", "Shaban",
                "Ramadan", "Shawwal", "Dhu al-Qadah", "Dhu al-Hijjah"]
HIJRI_MONTH_ALIASES = {
    "muharram": 1, "safar": 2, "rabi1": 3, "rabiulawwal": 3, "rabialawwal": 3,
    "rabi2": 4, "rabiulakhir": 4, "rabialthani": 4, "jumada1": 5,
    "jumadaalula": 5, "jumada2": 6, "jumadaalakhirah": 6, "rajab": 7,
    "shaban": 8, "ramadan": 9, "shawwal": 10, "dhualqadah": 11,
    "dhulqadah": 11, "dhualhijjah": 12, "dhulhijjah": 12,
}
STEMS = ["Jia", "Yi", "Bing", "Ding", "Wu", "Ji", "Geng", "Xin", "Ren", "Gui"]
BRANCHES = ["Zi", "Chou", "Yin", "Mao", "Chen", "Si", "Wu", "Wei", "Shen",
            "You", "Xu", "Hai"]
ANIMALS = ["Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake", "Horse", "Goat",
           "Monkey", "Rooster", "Dog", "Pig"]


# --------------------------------------------------------------------------
# Gregorian helpers. RD ("rata die") day number == date.toordinal():
#   RD 1 = Monday, 0001-01-01 proleptic Gregorian.
# --------------------------------------------------------------------------

def rd(y: int, m: int, d: int) -> int:
    return date(y, m, d).toordinal()


def from_rd(n: int) -> date:
    if not 1 <= n <= date.max.toordinal():
        raise CalcError("date out of supported Gregorian range (years 1..9999)")
    return date.fromordinal(n)


def days_in_month(y: int, m: int) -> int:
    return _cal.monthrange(y, m)[1]


def is_leap(y: int) -> bool:
    return _cal.isleap(y)


def add_months(dt: datetime, n: int):
    """Add n calendar months; clamp the day to the target month's length.
    Returns (new_datetime, was_clamped)."""
    total = dt.year * 12 + (dt.month - 1) + n
    y, m0 = divmod(total, 12)
    m = m0 + 1
    if not 1 <= y <= 9999:
        raise CalcError("result out of supported range (years 1..9999)")
    dim = days_in_month(y, m)
    day = min(dt.day, dim)
    return dt.replace(year=y, month=m, day=day), day != dt.day


def nth_weekday_of_month(y: int, m: int, wd: int, n: int) -> date:
    dim = days_in_month(y, m)
    if n > 0:
        first = date(y, m, 1)
        day = 1 + (wd - first.weekday()) % 7 + 7 * (n - 1)
    else:
        last = date(y, m, dim)
        day = dim - (last.weekday() - wd) % 7 - 7 * (-n - 1)
    if not 1 <= day <= dim:
        raise CalcError(f"there is no {ordinal_text(n)} {WEEKDAY_NAMES[wd]} in "
                        f"{MONTH_NAMES[m-1]} {y}")
    return date(y, m, day)


def nth_weekday_of_year(y: int, wd: int, n: int) -> date:
    if n > 0:
        first = date(y, 1, 1)
        d = first + timedelta(days=(wd - first.weekday()) % 7 + 7 * (n - 1))
    else:
        last = date(y, 12, 31)
        d = last - timedelta(days=(last.weekday() - wd) % 7 + 7 * (-n - 1))
    if d.year != y:
        raise CalcError(f"there is no {ordinal_text(n)} {WEEKDAY_NAMES[wd]} in {y}")
    return d


def weekday_on_or_after(d: date, wd: int, strict: bool) -> date:
    delta = (wd - d.weekday()) % 7
    if delta == 0 and strict:
        delta = 7
    return d + timedelta(days=delta)


def weekday_on_or_before(d: date, wd: int, strict: bool) -> date:
    delta = (d.weekday() - wd) % 7
    if delta == 0 and strict:
        delta = 7
    return d - timedelta(days=delta)


def ordinal_text(n: int) -> str:
    if n == -1:
        return "last"
    if n == -2:
        return "second-to-last"
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def easter_gregorian(y: int) -> date:
    """Western Easter (anonymous Gregorian algorithm, Meeus/Jones/Butcher)."""
    a = y % 19
    b, c = divmod(y, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def easter_orthodox(y: int) -> date:
    """Orthodox Easter: Julian computus (Meeus), returned as a Gregorian date."""
    a = y % 4
    b = y % 7
    c = y % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    return from_rd(fixed_from_julian(y, month, day))


# --------------------------------------------------------------------------
# Julian calendar (astronomical year numbering: year 0 exists = 1 BCE)
# --------------------------------------------------------------------------

JULIAN_EPOCH = -1  # RD of Julian 0001-01-01 (= Gregorian 0000-12-30)


def julian_leap(y: int) -> bool:
    return y % 4 == 0


def fixed_from_julian(y: int, m: int, d: int) -> int:
    if not (1 <= m <= 12):
        raise CalcError("julian month must be 1..12")
    mlen = [31, 29 if julian_leap(y) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    if not 1 <= d <= mlen:
        raise CalcError(f"julian {y}-{m:02d} has {mlen} days")
    corr = 0 if m <= 2 else (-1 if julian_leap(y) else -2)
    return (JULIAN_EPOCH - 1 + 365 * (y - 1) + (y - 1) // 4
            + (367 * m - 362) // 12 + corr + d)


def julian_from_fixed(n: int):
    approx = (4 * (n - JULIAN_EPOCH) + 1464) // 1461
    y = approx
    prior = n - fixed_from_julian(y, 1, 1)
    corr = 0 if n < fixed_from_julian(y, 3, 1) else (1 if julian_leap(y) else 2)
    m = (12 * (prior + corr) + 373) // 367
    d = n - fixed_from_julian(y, m, 1) + 1
    return y, m, d


# --------------------------------------------------------------------------
# Hebrew calendar (arithmetic, exact). Months: Nisan=1 .. Adar=12, Adar II=13.
# The year number changes on 1 Tishrei (month 7), not on 1 Nisan.
# --------------------------------------------------------------------------

HEBREW_EPOCH = -1373427  # RD of 1 Tishrei AM 1


def hebrew_leap(y: int) -> bool:
    return (7 * y + 1) % 19 < 7


def hebrew_last_month(y: int) -> int:
    return 13 if hebrew_leap(y) else 12


@lru_cache(maxsize=4096)
def hebrew_elapsed_days(y: int) -> int:
    months = (235 * y - 234) // 19
    parts = 12084 + 13753 * months
    days = 29 * months + parts // 25920
    return days + 1 if (3 * (days + 1)) % 7 < 3 else days


def hebrew_year_length_correction(y: int) -> int:
    ny0, ny1, ny2 = hebrew_elapsed_days(y - 1), hebrew_elapsed_days(y), hebrew_elapsed_days(y + 1)
    if ny2 - ny1 == 356:
        return 2
    if ny1 - ny0 == 382:
        return 1
    return 0


@lru_cache(maxsize=4096)
def hebrew_new_year(y: int) -> int:
    return HEBREW_EPOCH + hebrew_elapsed_days(y) + hebrew_year_length_correction(y)


def hebrew_days_in_year(y: int) -> int:
    return hebrew_new_year(y + 1) - hebrew_new_year(y)


def hebrew_month_length(y: int, m: int) -> int:
    yl = hebrew_days_in_year(y)
    if m in (2, 4, 6, 10, 13):
        return 29
    if m == 12 and not hebrew_leap(y):
        return 29
    if m == 8 and yl not in (355, 385):   # Heshvan long only in "complete" years
        return 29
    if m == 9 and yl in (353, 383):       # Kislev short only in "deficient" years
        return 29
    return 30


def fixed_from_hebrew(y: int, m: int, d: int) -> int:
    if not 1 <= m <= hebrew_last_month(y):
        raise CalcError(f"hebrew year {y} has no month {m}"
                        + (" (Adar II only exists in leap years)" if m == 13 else ""))
    ml = hebrew_month_length(y, m)
    if not 1 <= d <= ml:
        raise CalcError(f"{HEBREW_MONTHS[m]} {y} has {ml} days")
    n = hebrew_new_year(y) + d - 1
    if m < 7:
        for mm in range(7, hebrew_last_month(y) + 1):
            n += hebrew_month_length(y, mm)
        for mm in range(1, m):
            n += hebrew_month_length(y, mm)
    else:
        for mm in range(7, m):
            n += hebrew_month_length(y, mm)
    return n


def hebrew_from_fixed(n: int):
    approx = math.floor((n - HEBREW_EPOCH) / (35975351 / 98496)) + 1
    y = approx - 1
    while hebrew_new_year(y + 1) <= n:
        y += 1
    start = 7 if n < fixed_from_hebrew(y, 1, 1) else 1
    m = start
    while n > fixed_from_hebrew(y, m, hebrew_month_length(y, m)):
        m += 1
    d = n - fixed_from_hebrew(y, m, 1) + 1
    return y, m, d


def hebrew_month_name(y: int, m: int) -> str:
    if m == 12 and hebrew_leap(y):
        return "Adar I"
    return HEBREW_MONTHS[m]


# --------------------------------------------------------------------------
# Islamic calendars
#   hijri-tabular: arithmetic civil calendar (epoch 16 July 622 Julian,
#                  leap years 2,5,7,10,13,16,18,21,24,26,29 of each 30)
#   hijri (Umm al-Qura): official Saudi calendar, table-driven, 1343-1500 AH
# Religious observance can still differ by a day or two by country, because
# many communities start months on actual moon sighting.
# --------------------------------------------------------------------------

ISLAMIC_EPOCH = 227015  # RD of 1 Muharram 1 AH (tabular)


def fixed_from_islamic_tabular(y: int, m: int, d: int) -> int:
    if not 1 <= m <= 12:
        raise CalcError("hijri month must be 1..12")
    ml = 30 if (m % 2 == 1 or (m == 12 and (14 + 11 * y) % 30 < 11)) else 29
    if not 1 <= d <= ml:
        raise CalcError(f"tabular hijri {y}-{m} has {ml} days")
    return (ISLAMIC_EPOCH - 1 + (y - 1) * 354 + (3 + 11 * y) // 30
            + 29 * (m - 1) + m // 2 + d)


def islamic_tabular_from_fixed(n: int):
    y = (30 * (n - ISLAMIC_EPOCH) + 10646) // 10631
    prior = n - fixed_from_islamic_tabular(y, 1, 1)
    m = (11 * prior + 330) // 325
    d = n - fixed_from_islamic_tabular(y, m, 1) + 1
    return y, m, d


# Umm al-Qura month lengths, one digit per month (length - 28), starting at
# 1 Muharram 1343 AH = reduced Julian day 23999 (1924-08-01). Source: hijridate (MIT).
_UAQ_FIRST_MJD = 23999
_UAQ_FIRST_YEAR = 1343
_UAQ_DATA = (
    "212212220222112121212121212131202212112212211221112212212211212121221130"
    "212121222032121211212212212121112212212121212121212212122112121212212121"
    "212121212212112121221121212121212122221211211221222121121121212121212122"
    "212121212121212121212121212121212122212121202221212121212122212121212121"
    "212121212121212121212122212121221221212121212121212112121222121212112122"
    "121212121212212121221122212121211221121122212121211212122122212121212121"
    "121212121212212121212121212212112121212212211212121221212121212121212121"
    "212211212221221121212122112121212122122121212121212121212122212121221211"
    "212121212122112121212122212111212122212121211221212212112121212221211212"
    "121221212121212121221212121212121221221211212122121212112121222121211212"
    "122212121121122122212112112212212121212121212212121212121212212121211212"
    "212212121121212221212112121221221211211221222121121122122122112112122212"
    "121211212212212121211212212122121211212122212121121212212212121121222212"
    "112111222212211211122212212121121212212212112121212212122121121212212212"
    "112121221221211211222122121121122122122112121212122121212112122212121211"
    "212212212121121212212211212121212212121212121212212211212112212221121121"
    "212221212112121222121211212122122121121212122121212121212122121221121212"
    "122212112112122212211211212221212121121221221212112121221221212112121221"
    "221211212121222121121212122211212121122212121212112212122121211212122212"
    "121121122122212112112212221211211221221212121122121221212121212121212212"
    "121121221221212112121222121211211222212121121212212212112121212212121212"
    "112212212211211221212221121121221221212121121221212212112121221221211212"
    "121222121121121222122112112122122211211212212212121121212212122112121212"
    "122122121121212212212112112212221211211221221221121122121222112121212122"
    "121212112122122121211212122212121121212212212112121212212122112121212212"
    "211212112212221121121212221212112121222121211212122122112121212122121212"
    "121212121221221121121222"
)
_MJD_TO_RD = 678575  # RD = reduced Julian day (JD - 2400000) + 678575


@lru_cache(maxsize=1)
def _uaq_starts():
    starts = [_UAQ_FIRST_MJD + _MJD_TO_RD]
    for ch in _UAQ_DATA:
        starts.append(starts[-1] + 28 + int(ch))
    return starts  # starts[i] = RD of first day of month index i; last = end sentinel


UAQ_CONSENSUS = (1420, 1450)
UAQ_NOTE = ("Umm al-Qura outside 1420-1450 AH (1999-2029) is a projection/historical "
            "reconstruction; published sources (e.g. ICU4X vs KACST tables) differ by a day "
            "in some months")


def fixed_from_umalqura(y: int, m: int, d: int) -> int:
    starts = _uaq_starts()
    idx = (y - _UAQ_FIRST_YEAR) * 12 + (m - 1)
    if not 1 <= m <= 12:
        raise CalcError("hijri month must be 1..12")
    if not 0 <= idx < len(starts) - 1:
        raise CalcError("Umm al-Qura data covers 1343-1500 AH (1924-2077 CE); "
                        "use hijri-tabular: for other years")
    ml = starts[idx + 1] - starts[idx]
    if not 1 <= d <= ml:
        raise CalcError(f"Umm al-Qura {HIJRI_MONTHS[m-1]} {y} has {ml} days")
    return starts[idx] + d - 1


def umalqura_from_fixed(n: int):
    starts = _uaq_starts()
    if not starts[0] <= n < starts[-1]:
        raise CalcError("outside Umm al-Qura range (1924-08-01 .. 2077-11-16)")
    lo, hi = 0, len(starts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if starts[mid] <= n:
            lo = mid
        else:
            hi = mid
    y, m0 = divmod(lo, 12)
    return y + _UAQ_FIRST_YEAR, m0 + 1, n - starts[lo] + 1


# --------------------------------------------------------------------------
# Chinese calendar (astronomical, Reingold & Dershowitz rules, Beijing time)
# Moments are RD days with fractions, in Universal Time.
# --------------------------------------------------------------------------

MEAN_SYNODIC_MONTH = 29.530588861
MEAN_TROPICAL_YEAR = 365.242189
CHINESE_RANGE = (1900, 2100)
CHINESE_PRE1929_NOTE = ("before 1929 official almanacs used older rules; this astronomical result "
                        "differs from them in parts of 1906, 1917 and 1922")


def _approx_year(t: float) -> float:
    return 2000.0 + (t - 730120.5) / 365.2425


def delta_t_seconds(year: float) -> float:
    """TT - UT (Espenak & Meeus polynomials). Only ~1 minute matters here."""
    y = year
    if 2005 <= y < 2050:
        t = y - 2000
        return 62.92 + 0.32217 * t + 0.005589 * t * t
    if 1986 <= y < 2005:
        t = y - 2000
        return (63.86 + 0.3345 * t - 0.060374 * t ** 2 + 0.0017275 * t ** 3
                + 0.000651814 * t ** 4 + 0.00002373599 * t ** 5)
    if 1961 <= y < 1986:
        t = y - 1975
        return 45.45 + 1.067 * t - t ** 2 / 260 - t ** 3 / 718
    if 1941 <= y < 1961:
        t = y - 1950
        return 29.07 + 0.407 * t - t ** 2 / 233 + t ** 3 / 2547
    if 1920 <= y < 1941:
        t = y - 1920
        return 21.20 + 0.84493 * t - 0.076100 * t ** 2 + 0.0020936 * t ** 3
    if 1900 <= y < 1920:
        t = y - 1900
        return (-2.79 + 1.494119 * t - 0.0598939 * t ** 2 + 0.0061966 * t ** 3
                - 0.000197 * t ** 4)
    if 2050 <= y < 2150:
        return -20 + 32 * ((y - 1820) / 100) ** 2 - 0.5628 * (2150 - y)
    u = (y - 1820) / 100
    return -20 + 32 * u * u


def _dyn(t: float) -> float:
    return t + delta_t_seconds(_approx_year(t)) / 86400.0


def _sin(deg: float) -> float:
    return math.sin(math.radians(deg))


def _cos(deg: float) -> float:
    return math.cos(math.radians(deg))


def solar_longitude(t: float) -> float:
    """Apparent geocentric solar longitude in degrees at UT moment t (RD).
    Meeus ch.25 (higher accuracy variant via equation of center + nutation
    + aberration); accurate to ~0.01 deg."""
    T = (_dyn(t) - 730120.5) / 36525.0
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
    M = 357.52911 + 35999.05029 * T - 0.0001537 * T * T
    C = ((1.914602 - 0.004817 * T - 0.000014 * T * T) * _sin(M)
         + (0.019993 - 0.000101 * T) * _sin(2 * M)
         + 0.000289 * _sin(3 * M))
    omega = 125.04 - 1934.136 * T
    lam = L0 + C - 0.00569 - 0.00478 * _sin(omega)
    return lam % 360.0


_NM_A = [(299.77, 0.107408, -0.009173), (251.88, 0.016321, 0), (251.83, 26.651886, 0),
         (349.42, 36.412478, 0), (84.66, 18.206239, 0), (141.74, 53.303771, 0),
         (207.14, 2.453732, 0), (154.84, 7.306860, 0), (34.52, 27.261239, 0),
         (207.19, 0.121824, 0), (291.34, 1.844379, 0), (161.72, 24.198154, 0),
         (239.56, 25.513099, 0), (331.55, 3.592518, 0)]
_NM_AC = [0.000325, 0.000165, 0.000164, 0.000126, 0.000110, 0.000062, 0.000060,
          0.000056, 0.000047, 0.000042, 0.000040, 0.000037, 0.000035, 0.000023]


@lru_cache(maxsize=8192)
def nth_new_moon(k: int) -> float:
    """UT moment (RD) of new moon number k (k=0 ~ 2000-01-06). Meeus ch.49."""
    T = k / 1236.85
    jde = (2451550.09766 + 29.530588861 * k + 0.00015437 * T ** 2
           - 0.000000150 * T ** 3 + 0.00000000073 * T ** 4)
    E = 1 - 0.002516 * T - 0.0000074 * T * T
    M = 2.5534 + 29.10535670 * k - 0.0000014 * T ** 2 - 0.00000011 * T ** 3
    Mp = (201.5643 + 385.81693528 * k + 0.0107582 * T ** 2 + 0.00001238 * T ** 3
          - 0.000000058 * T ** 4)
    F = (160.7108 + 390.67050284 * k - 0.0016118 * T ** 2 - 0.00000227 * T ** 3
         + 0.000000011 * T ** 4)
    Om = 124.7746 - 1.56375588 * k + 0.0020672 * T ** 2 + 0.00000215 * T ** 3
    corr = (-0.40720 * _sin(Mp)
            + 0.17241 * E * _sin(M)
            + 0.01608 * _sin(2 * Mp)
            + 0.01039 * _sin(2 * F)
            + 0.00739 * E * _sin(Mp - M)
            - 0.00514 * E * _sin(Mp + M)
            + 0.00208 * E * E * _sin(2 * M)
            - 0.00111 * _sin(Mp - 2 * F)
            - 0.00057 * _sin(Mp + 2 * F)
            + 0.00056 * E * _sin(2 * Mp + M)
            - 0.00042 * _sin(3 * Mp)
            + 0.00042 * E * _sin(M + 2 * F)
            + 0.00038 * E * _sin(M - 2 * F)
            - 0.00024 * E * _sin(2 * Mp - M)
            - 0.00017 * _sin(Om)
            - 0.00007 * _sin(Mp + 2 * M)
            + 0.00004 * _sin(2 * Mp - 2 * F)
            + 0.00004 * _sin(3 * M)
            + 0.00003 * _sin(Mp + M - 2 * F)
            + 0.00003 * _sin(2 * Mp + 2 * F)
            - 0.00003 * _sin(Mp + M + 2 * F)
            + 0.00003 * _sin(Mp - M + 2 * F)
            - 0.00002 * _sin(Mp - M - 2 * F)
            - 0.00002 * _sin(3 * Mp + M)
            + 0.00002 * _sin(4 * Mp))
    extra = sum(c * _sin(a0 + a1 * k + a2 * T * T) for c, (a0, a1, a2) in zip(_NM_AC, _NM_A))
    jde += corr + extra
    t_tt = jde - 1721424.5  # RD (TT)
    return t_tt - delta_t_seconds(_approx_year(t_tt)) / 86400.0


_NM0 = 2451550.09766 - 1721424.5


def new_moon_at_or_after(t: float) -> float:
    k = math.floor((t - _NM0) / MEAN_SYNODIC_MONTH) - 2
    while nth_new_moon(k) < t:
        k += 1
    return nth_new_moon(k)


def new_moon_before(t: float) -> float:
    k = math.floor((t - _NM0) / MEAN_SYNODIC_MONTH) + 2
    while nth_new_moon(k) >= t:
        k -= 1
    return nth_new_moon(k)


def _china_offset(n: float) -> float:
    # Beijing standard time (UTC+8) from 1929; before that, Beijing local mean
    # time (116 deg 25' E = 1397/180 hours).
    return 8 / 24 if n >= 704731 else (1397 / 180) / 24  # 704731 = 1929-01-01


def _midnight_in_china(n: int) -> float:
    return n - _china_offset(n)


def _china_date_of(t: float) -> int:
    return math.floor(t + _china_offset(t))


def _solar_longitude_after(lam: float, t: float) -> float:
    rate = MEAN_TROPICAL_YEAR / 360
    tau = t + rate * ((lam - solar_longitude(t)) % 360)
    a, b = max(t, tau - 5), tau + 5
    for _ in range(60):
        mid = (a + b) / 2
        if (solar_longitude(mid) - lam) % 360 < 180:
            b = mid
        else:
            a = mid
    return (a + b) / 2


def _estimate_prior_solar_longitude(lam: float, tau: float) -> float:
    rate = MEAN_TROPICAL_YEAR / 360
    tau1 = tau - rate * ((solar_longitude(tau) - lam) % 360)
    delta = (solar_longitude(tau1) - lam + 180) % 360 - 180
    return min(tau, tau1 - rate * delta)


@lru_cache(maxsize=4096)
def _winter_solstice_on_or_before(n: int) -> int:
    approx = _estimate_prior_solar_longitude(270, _midnight_in_china(n + 1))
    i = math.floor(approx) - 1
    while not (270 < solar_longitude(_midnight_in_china(i + 1)) < 300):
        i += 1
    return i


@lru_cache(maxsize=8192)
def _cn_new_moon_on_or_after(n: int) -> int:
    return _china_date_of(new_moon_at_or_after(_midnight_in_china(n)))


@lru_cache(maxsize=8192)
def _cn_new_moon_before(n: int) -> int:
    return _china_date_of(new_moon_before(_midnight_in_china(n)))


@lru_cache(maxsize=8192)
def _major_solar_term(n: int) -> int:
    s = solar_longitude(_midnight_in_china(n))
    return (2 + math.floor(s / 30) - 1) % 12 + 1


def _no_major_solar_term(n: int) -> bool:
    return _major_solar_term(n) == _major_solar_term(_cn_new_moon_on_or_after(n + 1))


def _prior_leap_month(m_prime: int, m: int) -> bool:
    while m >= m_prime:
        if _no_major_solar_term(m):
            return True
        m = _cn_new_moon_before(m)
    return False


@lru_cache(maxsize=1024)
def _cn_new_year_in_sui(n: int) -> int:
    s1 = _winter_solstice_on_or_before(n)
    s2 = _winter_solstice_on_or_before(s1 + 370)
    m12 = _cn_new_moon_on_or_after(s1 + 1)
    m13 = _cn_new_moon_on_or_after(m12 + 1)
    next_m11 = _cn_new_moon_before(s2 + 1)
    if (round((next_m11 - m12) / MEAN_SYNODIC_MONTH) == 12
            and (_no_major_solar_term(m12) or _no_major_solar_term(m13))):
        return _cn_new_moon_on_or_after(m13 + 1)
    return m13


def _check_chinese_range(n: int):
    y = from_rd(n).year
    if not CHINESE_RANGE[0] <= y <= CHINESE_RANGE[1]:
        raise CalcError(f"chinese calendar supported for {CHINESE_RANGE[0]}-"
                        f"{CHINESE_RANGE[1]} only (validated range)")


def chinese_new_year_on_or_before(n: int) -> int:
    ny = _cn_new_year_in_sui(n)
    return ny if n >= ny else _cn_new_year_in_sui(n - 180)


@lru_cache(maxsize=8192)
def chinese_from_fixed(n: int):
    """Returns (gregorian_year_of_new_year, month 1..12, is_leap_month, day)."""
    _check_chinese_range(n)
    s1 = _winter_solstice_on_or_before(n)
    s2 = _winter_solstice_on_or_before(s1 + 370)
    m12 = _cn_new_moon_on_or_after(s1 + 1)
    next_m11 = _cn_new_moon_before(s2 + 1)
    m = _cn_new_moon_before(n + 1)
    leap_year = round((next_m11 - m12) / MEAN_SYNODIC_MONTH) == 12
    month = (round((m - m12) / MEAN_SYNODIC_MONTH)
             - (1 if (leap_year and _prior_leap_month(m12, m)) else 0))
    month = (month - 1) % 12 + 1
    leap_month = (leap_year and _no_major_solar_term(m)
                  and not _prior_leap_month(m12, _cn_new_moon_before(m)))
    day = n - m + 1
    gy = from_rd(chinese_new_year_on_or_before(n)).year
    return gy, month, leap_month, day


def fixed_from_chinese(gy: int, month: int, leap: bool, day: int) -> int:
    if not 1 <= month <= 12:
        raise CalcError("chinese month must be 1..12")
    if not 1 <= day <= 30:
        raise CalcError("chinese day must be 1..30")
    if not CHINESE_RANGE[0] <= gy <= CHINESE_RANGE[1] - 1:
        raise CalcError(f"chinese calendar supported for {CHINESE_RANGE[0]}-{CHINESE_RANGE[1]}")
    ny = chinese_new_year_on_or_before(rd(gy, 7, 1))
    p = _cn_new_moon_on_or_after(ny + (month - 1) * 29)
    d = chinese_from_fixed(p)
    start = p if (d[1] == month and d[2] == leap) else _cn_new_moon_on_or_after(p + 1)
    n = start + day - 1
    got = chinese_from_fixed(n)
    if got != (gy, month, leap, day):
        lbl = ("leap " if leap else "") + f"month {month}"
        raise CalcError(f"chinese year {gy} has no {lbl} day {day}"
                        + (" (that leap month does not exist this year)" if leap else ""))
    return n


def chinese_month_length(gy: int, month: int, leap: bool) -> int:
    start = fixed_from_chinese(gy, month, leap, 1)
    return _cn_new_moon_on_or_after(start + 1) - start


def chinese_label(gy: int) -> str:
    return f"{STEMS[(gy - 4) % 10]}-{BRANCHES[(gy - 4) % 12]}, Year of the {ANIMALS[(gy - 4) % 12]}"


# --------------------------------------------------------------------------
# Calendar formatting and parsing of "cal:Y-M-D" tokens
# --------------------------------------------------------------------------

def all_calendars(n: int) -> dict:
    out = {"gregorian": from_rd(n).isoformat()}
    jy, jm, jd = julian_from_fixed(n)
    out["julian"] = f"{jy:04d}-{jm:02d}-{jd:02d}"
    try:
        hy, hm, hd = hebrew_from_fixed(n)
        out["hebrew"] = f"{hd} {hebrew_month_name(hy, hm)} {hy}  (hebrew:{hy}-{hm}-{hd}; Nisan=1 numbering)"
    except Exception as e:  # pragma: no cover
        out["hebrew"] = f"n/a ({e})"
    try:
        uy, um, ud = umalqura_from_fixed(n)
        out["hijri"] = f"{ud} {HIJRI_MONTHS[um-1]} {uy} AH  (Umm al-Qura; hijri:{uy}-{um}-{ud})"
        if not UAQ_CONSENSUS[0] <= uy <= UAQ_CONSENSUS[1]:
            out["hijri"] += "  [estimate: " + UAQ_NOTE + "]"
    except CalcError as e:
        out["hijri"] = f"n/a ({e})"
    iy, im, idd = islamic_tabular_from_fixed(n)
    out["hijri-tabular"] = f"{idd} {HIJRI_MONTHS[im-1]} {iy} AH  (arithmetic; hijri-tabular:{iy}-{im}-{idd})"
    try:
        gy, cm, leap, cd = chinese_from_fixed(n)
        ml = "leap month " + str(cm) if leap else f"month {cm}"
        tag = f"chinese:{gy}-{'L' if leap else ''}{cm}-{cd}"
        out["chinese"] = f"{ml}, day {cd} of the year starting {from_rd(chinese_new_year_on_or_before(n)).isoformat()} ({chinese_label(gy)})  ({tag})"
        if gy < 1929:
            out["chinese"] += "  [pre-1929: " + CHINESE_PRE1929_NOTE + "]"
    except CalcError as e:
        out["chinese"] = f"n/a ({e})"
    return out


CAL_TAGS = {
    "gregorian": "gregorian", "greg": "gregorian", "iso": "gregorian",
    "julian": "julian", "jul": "julian", "os": "julian",
    "hebrew": "hebrew", "jewish": "hebrew", "heb": "hebrew",
    "hijri": "hijri", "umalqura": "hijri", "ummalqura": "hijri", "islamic": "hijri",
    "hijri-tabular": "hijri-tabular", "islamic-civil": "hijri-tabular",
    "islamic-tabular": "hijri-tabular", "tabular": "hijri-tabular",
    "chinese": "chinese", "lunar": "chinese", "cn": "chinese",
}


def parse_cal_token(tok: str) -> int:
    tag, _, body = tok.partition(":")
    cal = CAL_TAGS.get(tag)
    if cal is None:
        raise CalcError(f"unknown calendar '{tag}'. Use one of: gregorian, julian, "
                        "hebrew, hijri, hijri-tabular, chinese")
    parts = body.split("-")
    if len(parts) != 3:
        raise CalcError(f"'{tok}': write calendar dates as {tag}:YEAR-MONTH-DAY")
    ys, ms, ds = parts
    try:
        y, d = int(ys), int(ds)
    except ValueError:
        raise CalcError(f"'{tok}': year and day must be numbers")
    ms_c = ms.replace("_", "").replace(" ", "")
    if cal == "gregorian":
        return rd(y, int(ms_c), d)
    if cal == "julian":
        return fixed_from_julian(y, int(ms_c), d)
    if cal == "hebrew":
        if ms_c.isdigit():
            m = int(ms_c)
        elif ms_c in HEBREW_MONTH_ALIASES:
            m = HEBREW_MONTH_ALIASES[ms_c]
        else:
            raise CalcError(f"unknown hebrew month '{ms}'. Names: "
                            + ", ".join(sorted(HEBREW_MONTH_ALIASES)))
        return fixed_from_hebrew(y, m, d)
    if cal in ("hijri", "hijri-tabular"):
        if ms_c.isdigit():
            m = int(ms_c)
        elif ms_c in HIJRI_MONTH_ALIASES:
            m = HIJRI_MONTH_ALIASES[ms_c]
        else:
            raise CalcError(f"unknown hijri month '{ms}'. Use 1..12 (9 = Ramadan)")
        return fixed_from_umalqura(y, m, d) if cal == "hijri" else fixed_from_islamic_tabular(y, m, d)
    if cal == "chinese":
        leap = False
        mm = ms_c
        if mm.startswith("leap"):
            leap, mm = True, mm[4:]
        elif mm.startswith("l"):
            leap, mm = True, mm[1:]
        elif mm.endswith("l"):
            leap, mm = True, mm[:-1]
        if not mm.isdigit():
            raise CalcError(f"'{tok}': chinese month is 1..12, leap month as L6 (e.g. chinese:2025-L6-1)")
        return fixed_from_chinese(y, int(mm), leap, d)
    raise CalcError("unreachable")


# --------------------------------------------------------------------------
# Holidays (resolved within a Gregorian year)
# --------------------------------------------------------------------------

def _hebrew_in_year(gy: int, m: int, d: int) -> list:
    out = []
    for hy in (gy + 3760, gy + 3761):
        mm = m
        if m == 12 and hebrew_leap(hy):
            mm = 13  # Purim etc. are observed in Adar II in leap years
        try:
            n = fixed_from_hebrew(hy, mm, d)
        except CalcError:
            continue
        if from_rd(n).year == gy:
            out.append(n)
    return sorted(set(out))


def _hijri_in_year(gy: int, m: int, d: int) -> list:
    out = []
    base = islamic_tabular_from_fixed(rd(gy, 1, 1))[0]
    for hy in range(base - 1, base + 3):
        try:
            n = fixed_from_umalqura(hy, m, d)
        except CalcError:
            n = fixed_from_islamic_tabular(hy, m, d)
        if from_rd(n).year == gy:
            out.append(n)
    return sorted(out)


HOLIDAYS = {
    # key: (pretty name, resolver(gy) -> list[RD], note)
    "easter": ("Easter (Western)", lambda y: [easter_gregorian(y).toordinal()], None),
    "orthodoxeaster": ("Orthodox Easter", lambda y: [easter_orthodox(y).toordinal()],
                       "Julian computus, shown as a Gregorian date"),
    "goodfriday": ("Good Friday (Western)", lambda y: [easter_gregorian(y).toordinal() - 2], None),
    "christmas": ("Christmas Day", lambda y: [rd(y, 12, 25)], None),
    "orthodoxchristmas": ("Orthodox Christmas (Julian Dec 25)",
                          lambda y: [n for n in (fixed_from_julian(y - 1, 12, 25), fixed_from_julian(y, 12, 25))
                                     if from_rd(n).year == y], None),
    "thanksgiving": ("US Thanksgiving", lambda y: [nth_weekday_of_month(y, 11, 3, 4).toordinal()], None),
    "roshhashanah": ("Rosh Hashanah (1 Tishrei)", lambda y: _hebrew_in_year(y, 7, 1), "starts at sundown the evening before"),
    "yomkippur": ("Yom Kippur (10 Tishrei)", lambda y: _hebrew_in_year(y, 7, 10), "starts at sundown the evening before"),
    "sukkot": ("Sukkot (15 Tishrei)", lambda y: _hebrew_in_year(y, 7, 15), "starts at sundown the evening before"),
    "hanukkah": ("Hanukkah (25 Kislev)", lambda y: _hebrew_in_year(y, 9, 25), "first candle the evening before"),
    "purim": ("Purim (14 Adar / Adar II)", lambda y: _hebrew_in_year(y, 12, 14), "starts at sundown the evening before"),
    "passover": ("Passover (15 Nisan)", lambda y: _hebrew_in_year(y, 1, 15), "first Seder the evening before"),
    "shavuot": ("Shavuot (6 Sivan)", lambda y: _hebrew_in_year(y, 3, 6), "starts at sundown the evening before"),
    "islamicnewyear": ("Islamic New Year (1 Muharram)", lambda y: _hijri_in_year(y, 1, 1), None),
    "ramadan": ("Ramadan begins (1 Ramadan)", lambda y: _hijri_in_year(y, 9, 1), None),
    "eidalfitr": ("Eid al-Fitr (1 Shawwal)", lambda y: _hijri_in_year(y, 10, 1), None),
    "eidaladha": ("Eid al-Adha (10 Dhu al-Hijjah)", lambda y: _hijri_in_year(y, 12, 10), None),
    "chinesenewyear": ("Chinese New Year", lambda y: [fixed_from_chinese(y, 1, False, 1)], None),
    "lanternfestival": ("Lantern Festival", lambda y: [fixed_from_chinese(y, 1, False, 15)], None),
    "dragonboat": ("Dragon Boat Festival", lambda y: [fixed_from_chinese(y, 5, False, 5)], None),
    "midautumn": ("Mid-Autumn Festival", lambda y: [fixed_from_chinese(y, 8, False, 15)], None),
}
HOLIDAY_ALIASES = [
    (r"orthodox\s+easter|eastern\s+easter|pascha", "orthodoxeaster"),
    (r"good\s+friday", "goodfriday"),
    (r"easter(\s+sunday)?", "easter"),
    (r"(us\s+)?thanksgiving", "thanksgiving"),
    (r"orthodox\s+christmas", "orthodoxchristmas"),
    (r"christmas(\s+day)?|xmas", "christmas"),
    (r"rosh\s*hashanah?|rosh\s*hashana|jewish\s+new\s+year", "roshhashanah"),
    (r"yom\s*kippur", "yomkippur"),
    (r"sukkot|sukkoth", "sukkot"),
    (r"hanukk?ah|chanukk?ah", "hanukkah"),
    (r"purim", "purim"),
    (r"passover|pesach", "passover"),
    (r"shavuot", "shavuot"),
    (r"islamic\s+new\s+year|hijri\s+new\s+year", "islamicnewyear"),
    (r"(start\s+of\s+|first\s+day\s+of\s+)?ramadan", "ramadan"),
    (r"eid\s*(al|ul)?[\s-]*fitr", "eidalfitr"),
    (r"eid\s*(al|ul)?[\s-]*adha", "eidaladha"),
    (r"chinese\s+new\s+year|lunar\s+new\s+year|spring\s+festival", "chinesenewyear"),
    (r"lantern\s+festival", "lanternfestival"),
    (r"dragon\s+boat(\s+festival)?", "dragonboat"),
    (r"mid[\s-]*autumn(\s+festival)?|moon\s+festival", "midautumn"),
]


# --------------------------------------------------------------------------
# Values, context
# --------------------------------------------------------------------------

class Ctx:
    def __init__(self, today: date, now: datetime, tz, holidays: set, order: str | None):
        self.today = today
        self.now = now
        self.tz = tz
        self.holidays = holidays
        self.order = order
        self.steps: list = []
        self.notes: list = []
        self.used_today = False

    def note(self, s: str):
        if s not in self.notes:
            self.notes.append(s)


class Val:
    """A point in time. has_time=False means a plain calendar date."""
    __slots__ = ("dt", "has_time")

    def __init__(self, dt: datetime, has_time: bool):
        self.dt = dt
        self.has_time = has_time

    @staticmethod
    def of_date(d: date) -> "Val":
        return Val(datetime(d.year, d.month, d.day), False)

    def d(self) -> date:
        return self.dt.date()

    def text(self) -> str:
        wd = WEEKDAY_NAMES[self.dt.weekday()]
        if not self.has_time:
            return f"{self.d().isoformat()} ({wd})"
        s = self.dt.isoformat(timespec="seconds")
        if self.dt.tzinfo is not None and hasattr(self.dt.tzinfo, "key"):
            s += f" [{self.dt.tzinfo.key}]"
        return f"{s} ({wd})"

    def iso(self) -> str:
        return self.d().isoformat() if not self.has_time else self.dt.isoformat(timespec="seconds")


def _normalize_local(dt: datetime, ctx: Ctx, why: str) -> datetime:
    """After wall-clock arithmetic on an aware datetime, resolve DST gaps."""
    if dt.tzinfo is None or not hasattr(dt.tzinfo, "key"):
        return dt
    fixed = dt.astimezone(timezone.utc).astimezone(dt.tzinfo)
    if fixed.replace(tzinfo=None) != dt.replace(tzinfo=None):
        ctx.note(f"{dt.replace(tzinfo=None)} does not exist in {dt.tzinfo.key} "
                 f"(DST gap) after {why}; moved to {fixed.isoformat(timespec='seconds')}")
    return fixed


def is_business_day(d: date, ctx: Ctx) -> bool:
    return d.weekday() < 5 and d not in ctx.holidays


def shift(v: Val, n: float, unit: str, ctx: Ctx) -> Val:
    """Apply n units to v. Calendar units move the wall-clock date; time units
    move absolute time (DST-correct when a real zone is attached)."""
    if unit in TIME_UNITS:
        delta = timedelta(**{unit: n})
        dt = v.dt
        if dt.tzinfo is not None:
            dt = (dt.astimezone(timezone.utc) + delta).astimezone(dt.tzinfo)
        else:
            dt = dt + delta
        return Val(dt, True)
    if n != int(n):
        raise CalcError(f"fractional {unit} not supported; use smaller units")
    n = int(n)
    if unit == "fortnights":
        unit, n = "weeks", n * 2
    if unit == "quarters":
        unit, n = "months", n * 3
    if unit == "decades":
        unit, n = "years", n * 10
    if unit in ("days", "weeks"):
        days = n * (7 if unit == "weeks" else 1)
        naive = v.dt.replace(tzinfo=None) + timedelta(days=days)
        dt = naive.replace(tzinfo=v.dt.tzinfo)
        return Val(_normalize_local(dt, ctx, f"adding {n} {unit}"), v.has_time)
    if unit in ("months", "years"):
        months = n * (12 if unit == "years" else 1)
        new, clamped = add_months(v.dt.replace(tzinfo=None), months)
        if clamped:
            ctx.note(f"{v.d().isoformat()} {'+' if months >= 0 else '-'} {abs(n)} {unit if abs(n) != 1 else unit[:-1]}: "
                     f"day {v.dt.day} does not exist in {MONTH_NAMES[new.month-1]} {new.year}, "
                     f"clamped to the last day ({new.day}). This is the same rule as chrono "
                     f"checked_add_months and dateutil relativedelta; Go's AddDate would "
                     f"overflow into the next month instead.")
        dt = new.replace(tzinfo=v.dt.tzinfo)
        return Val(_normalize_local(dt, ctx, f"adding {n} {unit}"), v.has_time)
    if unit == "bdays":
        step = 1 if n >= 0 else -1
        d = v.d()
        for _ in range(abs(n)):
            d += timedelta(days=step)
            while not is_business_day(d, ctx):
                d += timedelta(days=step)
        ctx.note("business days skip Saturday/Sunday"
                 + (f" and {len(ctx.holidays)} --holidays date(s)" if ctx.holidays else
                    " only (no public holidays unless you pass --holidays)"))
        dt = v.dt.replace(year=d.year, month=d.month, day=d.day)
        return Val(dt, v.has_time)
    raise CalcError(f"unknown unit {unit}")


# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"""
    (?P<caldate>(?:gregorian|greg|iso|julian|jul|os|hebrew|jewish|heb|hijri-tabular|islamic-civil|islamic-tabular|tabular|hijri|umalqura|ummalqura|islamic|chinese|lunar|cn):[^\s()+,]+)
  | (?P<datetime>\d{4}-\d{2}-\d{2}(?:[t\s]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:?\d{2})?)?)
  | (?P<yearmonth>\d{4}-\d{2})(?![\d-])
  | (?P<slash>\d{1,4}/\d{1,2}/\d{1,4})
  | (?P<clock>\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)\b)
  | (?P<ordnum>\d+(?:st|nd|rd|th)\b)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<holiday>@[a-z]+)
  | (?P<word>[a-z][a-z']*)
  | (?P<op>[+\-(),])
  | (?P<space>\s+)
  | (?P<other>.)
""", re.X)

FILLER = {"the", "what", "whats", "what's", "is", "date", "will", "be", "it",
          "please", "calculate", "compute", "give", "me", "was"}


def tokenize(text: str) -> list:
    s = text.strip().lower().rstrip("?.!")
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    for pat, key in HOLIDAY_ALIASES:
        # never rewrite inside calendar tokens like hijri:1447-ramadan-1
        s = re.sub(r"(?<![a-z@:\-\d])(?:" + pat + r")(?![a-z])", " @" + key + " ", s)
    toks = []
    for m in _TOKEN_RE.finditer(s):
        kind = m.lastgroup
        val = m.group()
        if kind == "space":
            continue
        if kind == "other":
            raise CalcError(f"unexpected character {val!r} in expression")
        if kind == "word" and val in FILLER:
            continue
        if kind == "word" and val == "plus":
            kind, val = "op", "+"
        if kind == "word" and val == "minus":
            kind, val = "op", "-"
        if kind == "datetime":
            val = val.replace(" ", "t", 1) if re.match(r"\d{4}-\d{2}-\d{2}\s", val) else val
        toks.append((kind, val))
    return toks


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

class Parser:
    def __init__(self, text: str, ctx: Ctx):
        self.text = text
        self.toks = tokenize(text)
        self.i = 0
        self.ctx = ctx

    # -- token helpers --
    def peek(self, k: int = 0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else (None, None)

    def pv(self, k: int = 0):
        return self.peek(k)[1]

    def pk(self, k: int = 0):
        return self.peek(k)[0]

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def accept(self, *words) -> bool:
        if self.pv() in words:
            self.i += 1
            return True
        return False

    def accept_seq(self, *words) -> bool:
        for k, w in enumerate(words):
            if self.pv(k) != w:
                return False
        self.i += len(words)
        return True

    def expect(self, *words):
        if not self.accept(*words):
            raise CalcError(f"expected {' or '.join(repr(w) for w in words)} "
                            f"but found {self.pv()!r}")

    def at_end(self) -> bool:
        return self.i >= len(self.toks)

    def fail(self, what: str):
        rest = " ".join(v for _, v in self.toks[self.i:]) or "<end>"
        raise CalcError(f"could not understand {what} at: '{rest}'. "
                        "Run `datecalc.py examples` for the grammar.")

    def step(self, label: str, v: Val):
        self.ctx.steps.append((label, v.text()))

    def today(self) -> Val:
        self.ctx.used_today = True
        return Val.of_date(self.ctx.today)

    # -- top level --
    def parse_query(self):
        if self.pv() == "every":
            return self.parse_every()
        diff = self.try_parse_diff_query()
        if diff is not None:
            return diff
        v = self.parse_expr()
        if isinstance(v, tuple):  # diff produced by "A - B"
            return v
        if not self.at_end():
            self.fail("the rest of the expression")
        return ("value", v)

    # "days between A and B", "from A to B", "weeks until X", "days since X"
    def try_parse_diff_query(self):
        save = self.i
        unit = None
        if self.accept_seq("how", "many"):
            pass
        if self.pv() in ("business", "working") and self.pv(1) in ("days", "day"):
            self.i += 2
            unit = "bdays"
        elif (self.pv() in UNITS and self.pv(1) in ("between", "until", "till", "to", "since", "from", "before", "after", "left")
              and not (self.pv() == "second" and self.pv(1) == "to" and self.pv(2) == "last")):
            unit = UNITS[self.take()[1]]
        if self.accept("between"):
            a = self.parse_expr(stop_at_and=True)
            self.expect("and")
            b = self.parse_expr()
            return ("diff", a, b, unit)
        if unit and self.accept("until", "till", "to", "before", "left"):
            if self.at_end():
                self.fail("a target date")
            b = self.parse_expr()
            return ("diff", self.today_step(), b, unit)
        if unit and self.accept("since", "after"):
            a = self.parse_expr()
            return ("diff", a, self.today_step(), unit)
        if self.pv() == "from" and unit is None:
            self.i += 1
            a = self.parse_expr(stop_at_to=True)
            if self.accept("to", "until", "till"):
                b = self.parse_expr()
                return ("diff", a, b, unit)
        if unit and self.accept("from"):
            a = self.parse_expr(stop_at_to=True)
            self.expect("to", "until", "till")
            b = self.parse_expr()
            return ("diff", a, b, unit)
        self.i = save
        return None

    def today_step(self) -> Val:
        v = self.today()
        self.step("today", v)
        return v

    # every N unit (after|from|starting) X [count N | until X | for N unit]
    def parse_every(self):
        self.expect("every")
        n, unit = 1, None
        wd = None
        if self.pk() == "num" or self.pv() in NUMBER_WORDS:
            n = self.parse_number()
        elif self.pk() == "ordnum" or (self.pv() in ORDINAL_WORDS and self.pv() not in ("last",)):
            n = self.parse_ordinal()
        if self.pv() in WEEKDAYS:
            wd = WEEKDAYS[self.take()[1]]
            unit = "weeks"
        elif self.pv() in ("business", "working") and self.pv(1) in ("day", "days"):
            self.i += 2
            unit = "bdays"
        elif self.pv() in UNITS:
            unit = UNITS[self.take()[1]]
        else:
            self.fail("a repeat unit (day/week/month/year/weekday name)")
        include_start = True
        if self.accept("after"):
            include_start = False
        elif self.accept("from", "starting", "since", "beginning"):
            self.accept("on", "at")
        elif self.at_end() or self.pv() in ("count", "until", "for", "times", "limit"):
            pass
        else:
            self.fail("'after' or 'from' followed by a start date")
        if self.at_end() or self.pv() in ("count", "until", "for", "times", "limit", ","):
            start = self.today_step()
        else:
            start = self.parse_expr(stop_at_series=True)
        self.accept(",")
        count, until = None, None
        if self.accept("count", "limit", "times", "next"):
            count = int(self.parse_number())
        elif self.accept("until", "through", "till", "to"):
            until = self.parse_expr()
        elif self.accept("for"):
            fn = self.parse_number()
            fu = UNITS.get(self.take()[1])
            if fu is None:
                self.fail("a duration unit after 'for'")
            until = shift(start, fn, fu, self.ctx)
        if not self.at_end():
            self.fail("the end of the 'every' clause")
        if wd is not None:
            first = weekday_on_or_after(start.d(), wd, strict=not include_start)
            base = Val(start.dt.replace(year=first.year, month=first.month, day=first.day), start.has_time)
            include_start = True
            if base.d() != start.d():
                self.ctx.note(f"first {WEEKDAY_NAMES[wd]} on/after the start is {base.d().isoformat()}")
            start = base  # every N <weekday> = every N weeks from that weekday
        if count is None and until is None:
            count = 10
            self.ctx.note("no 'count N' or 'until DATE' given; showing 10 occurrences")
        return ("series", start, n, unit, include_start, count, until)

    def parse_number(self) -> float:
        k, v = self.peek()
        if k == "num":
            self.i += 1
            return float(v) if "." in v else int(v)
        if v in NUMBER_WORDS:
            self.i += 1
            return NUMBER_WORDS[v]
        self.fail("a number")

    def parse_ordinal(self) -> int:
        k, v = self.peek()
        if k == "ordnum":
            self.i += 1
            return int(re.match(r"\d+", v).group())
        if v in ORDINAL_WORDS:
            self.i += 1
            if v == "second" and self.pv() == "to" and self.pv(1) == "last":
                self.i += 2
                return -2
            return ORDINAL_WORDS[v]
        self.fail("an ordinal (first, 2nd, last ...)")

    # -- durations --
    def is_duration_start(self) -> bool:
        k, v = self.peek()
        k1, v1 = self.peek(1)
        if (k == "num" or v in NUMBER_WORDS) and v1 in UNITS:
            # "5 jan" is a date, units never collide with month names; but
            # "a month" etc. is fine. Guard: "1 s" etc. only after a number.
            return True
        if (k == "num" or v in NUMBER_WORDS) and v1 in ("business", "working") and self.pv(2) in ("day", "days"):
            return True
        return False

    def parse_duration(self) -> list:
        parts = []
        while True:
            n = self.parse_number()
            if self.pv() in ("business", "working") and self.pv(1) in ("day", "days"):
                self.i += 2
                unit = "bdays"
            else:
                u = self.take()[1]
                if u not in UNITS:
                    self.fail("a unit")
                unit = UNITS[u]
            parts.append((n, unit))
            save = self.i
            if self.accept("and", ","):
                if self.is_duration_start():
                    continue
                self.i = save
            if self.is_duration_start():
                continue
            return parts

    @staticmethod
    def dur_text(parts, sign=1) -> str:
        out = []
        for n, u in parts:
            uname = {"bdays": "business days"}.get(u, u)
            if abs(n) == 1:
                uname = uname[:-1] if uname.endswith("s") else uname
                uname = uname.replace("business day", "business day")
            out.append(f"{n} {uname}")
        return ("+ " if sign > 0 else "- ") + " ".join(out)

    def apply(self, v: Val, parts, sign: int) -> Val:
        for n, u in parts:
            v = shift(v, sign * n, u, self.ctx)
        return v

    # -- expressions --
    def parse_expr(self, stop_at_and=False, stop_at_to=False, stop_at_series=False):
        v = self.parse_unary(stop_at_and, stop_at_to, stop_at_series)
        while not self.at_end():
            if self.pv() in ("+", "-"):
                sign = 1 if self.take()[1] == "+" else -1
                if self.is_duration_start():
                    parts = self.parse_duration()
                    v = self.apply(v, parts, sign)
                    self.step(self.dur_text(parts, sign), v)
                    continue
                if sign < 0:
                    other = self.parse_unary(stop_at_and, stop_at_to, stop_at_series)
                    return ("diff", other, v, None)
                self.fail("a duration after '+' (e.g. '+ 3 weeks')")
            elif self.pv() == "at" and (self.pk(1) == "clock" or self.pv(1) in ("noon", "midnight")):
                self.i += 1
                v = self.apply_clock(v)
            else:
                break
        return v

    def parse_unary(self, stop_at_and=False, stop_at_to=False, stop_at_series=False) -> Val:
        if self.accept("in"):
            parts = self.parse_duration()
            v = self.apply(self.today_step(), parts, 1)
            self.step(self.dur_text(parts), v)
            return v
        if self.is_duration_start():
            parts = self.parse_duration()
            if self.accept("ago"):
                v = self.apply(self.today_step(), parts, -1)
                self.step(self.dur_text(parts, -1), v)
                return v
            if self.accept_seq("from", "now") or self.accept_seq("from", "today") or self.accept("later", "hence"):
                v = self.apply(self.today_step(), parts, 1)
                self.step(self.dur_text(parts), v)
                return v
            if self.accept("after", "from", "past"):
                base = self.parse_expr(stop_at_and, stop_at_to, stop_at_series)
                if isinstance(base, tuple):
                    self.fail("a single date after 'after'")
                v = self.apply(base, parts, 1)
                self.step(self.dur_text(parts), v)
                return v
            if self.accept("before", "prior", "earlier"):
                self.accept("to", "than")
                base = self.parse_expr(stop_at_and, stop_at_to, stop_at_series)
                if isinstance(base, tuple):
                    self.fail("a single date after 'before'")
                v = self.apply(base, parts, -1)
                self.step(self.dur_text(parts, -1), v)
                return v
            self.fail("'ago', 'after X', 'before X' or 'from now' after a duration")
        return self.parse_primary(stop_at_and, stop_at_to, stop_at_series)

    def apply_clock(self, v: Val) -> Val:
        k, s = self.take()
        if s == "noon":
            hh, mm, ss = 12, 0, 0
        elif s == "midnight":
            hh, mm, ss = 0, 0, 0
        else:
            m = re.match(r"(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?$", s)
            if not m:
                self.fail("a time")
            hh, mm, ss = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
            ap = m.group(4)
            if ap is None and self.pv() in ("am", "pm"):
                ap = self.take()[1]
            if ap == "pm" and hh != 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
                raise CalcError(f"invalid time {s}")
        dt = v.dt.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        if dt.tzinfo is None and self.ctx.tz is not None:
            dt = dt.replace(tzinfo=self.ctx.tz)
        nv = Val(_normalize_local(dt, self.ctx, "setting the time"), True)
        self.step(f"at {hh:02d}:{mm:02d}" + (f":{ss:02d}" if ss else ""), nv)
        return nv

    # month spec -> ("month", y, m) | ("year", y)
    def parse_scope(self):
        k, v = self.peek()
        cy = self.ctx.today.year
        if k == "yearmonth":
            self.i += 1
            y, m = map(int, v.split("-"))
            return ("month", y, m)
        if k == "num" and len(v) == 4:
            self.i += 1
            return ("year", int(v))
        if v in MONTHS:
            self.i += 1
            if self.pk() == "num" and len(self.pv()) == 4:
                return ("month", int(self.take()[1]), MONTHS[v])
            self.ctx.used_today = True
            self.ctx.note(f"no year given for {MONTH_NAMES[MONTHS[v]-1]}; assumed {cy}")
            return ("month", cy, MONTHS[v])
        if v in ("this", "next", "last", "previous", "current") and self.pv(1) in ("month", "year"):
            rel = {"this": 0, "current": 0, "next": 1, "last": -1, "previous": -1}[v]
            what = self.pv(1)
            self.i += 2
            self.ctx.used_today = True
            if what == "month":
                d, _ = add_months(datetime(cy, self.ctx.today.month, 1), rel)
                return ("month", d.year, d.month)
            return ("year", cy + rel)
        if v == "month":
            self.i += 1
            self.ctx.used_today = True
            return ("month", cy, self.ctx.today.month)
        if v == "year":
            self.i += 1
            self.ctx.used_today = True
            return ("year", cy)
        self.fail("a month or year (e.g. 'january 2026', '2026-03', 'next month', '2026')")

    def scope_text(self, sc) -> str:
        return f"{MONTH_NAMES[sc[2]-1]} {sc[1]}" if sc[0] == "month" else str(sc[1])

    def parse_primary(self, stop_at_and=False, stop_at_to=False, stop_at_series=False) -> Val:
        k, v = self.peek()
        if k is None:
            self.fail("a date")
        start_i = self.i

        if v == "(":
            self.i += 1
            r = self.parse_expr()
            self.expect(")")
            if isinstance(r, tuple):
                self.fail("a date inside parentheses")
            return r

        # today / now / tomorrow / yesterday
        if v in ("today", "tomorrow", "yesterday", "now", "tonight"):
            self.i += 1
            if v == "now":
                self.ctx.used_today = True
                r = Val(self.ctx.now, True)
            else:
                r = self.today()
                if v == "tomorrow":
                    r = shift(r, 1, "days", self.ctx)
                elif v == "yesterday":
                    r = shift(r, -1, "days", self.ctx)
            self.step(v, r)
            return r

        if k == "datetime":
            self.i += 1
            r = self.parse_iso(v)
            self.step(v, r)
            return r

        if k == "slash":
            self.i += 1
            r = Val.of_date(self.parse_slash(v))
            self.step(v, r)
            return r

        if k == "caldate":
            self.i += 1
            n = parse_cal_token(v)
            if v.split(":")[0] in ("hijri", "umalqura", "ummalqura", "islamic"):
                uy = umalqura_from_fixed(n)[0]
                if not UAQ_CONSENSUS[0] <= uy <= UAQ_CONSENSUS[1]:
                    self.ctx.note(UAQ_NOTE)
            if v.split(":")[0] in ("chinese", "lunar", "cn") and from_rd(n).year < 1929:
                self.ctx.note("chinese calendar " + CHINESE_PRE1929_NOTE)
            r = Val.of_date(from_rd(n))
            self.step(v, r)
            return r

        if k == "holiday":
            self.i += 1
            key = v[1:]
            name, fn, note = HOLIDAYS[key]
            if self.pk() == "num" and len(self.pv()) == 4:
                y = int(self.take()[1])
            else:
                y = self.ctx.today.year
                self.ctx.used_today = True
                self.ctx.note(f"no year given for {name}; assumed {y}")
            days = fn(y)
            if not days:
                raise CalcError(f"{name} does not fall in Gregorian {y}")
            if len(days) > 1:
                self.ctx.note(f"{name} occurs {len(days)} times in {y}: "
                              + ", ".join(from_rd(x).isoformat() for x in days)
                              + "; using the first")
            if key in ("ramadan", "eidalfitr", "eidaladha", "islamicnewyear"):
                self.ctx.note("Islamic dates use the Umm al-Qura calendar; local moon-sighting may differ by 1-2 days")
                try:
                    if not UAQ_CONSENSUS[0] <= umalqura_from_fixed(days[0])[0] <= UAQ_CONSENSUS[1]:
                        self.ctx.note(UAQ_NOTE)
                except CalcError:
                    pass
            if note:
                self.ctx.note(f"{name}: {note}")
            r = Val.of_date(from_rd(days[0]))
            self.step(f"{name} {y}", r)
            return r

        # yearmonth alone -> first day of that month
        if k == "yearmonth":
            self.i += 1
            y, m = map(int, v.split("-"))
            r = Val.of_date(date(y, m, 1))
            self.step(v, r)
            return r

        # start/end of <scope|week>
        if v in ("start", "beginning", "end") and self.pv(1) == "of":
            self.i += 2
            is_end = v == "end"
            if self.pv() in ("week",) or (self.pv() in ("this", "next", "last", "previous") and self.pv(1) == "week"):
                rel = 0
                if self.pv() != "week":
                    rel = {"this": 0, "next": 1, "last": -1, "previous": -1}[self.take()[1]]
                self.i += 1
                t = self.ctx.today + timedelta(weeks=rel)
                self.ctx.used_today = True
                mon = t - timedelta(days=t.weekday())
                r = Val.of_date(mon + timedelta(days=6) if is_end else mon)
                self.ctx.note("weeks are ISO weeks: Monday to Sunday")
                self.step(f"{v} of week", r)
                return r
            sc = self.parse_scope()
            r = Val.of_date(self.scope_bound(sc, is_end))
            self.step(f"{v} of {self.scope_text(sc)}", r)
            return r

        # day N of YEAR / week N of YEAR
        if v == "day" and self.pk(1) == "num" and self.pv(2) in ("of", "in"):
            n = int(self.pv(1))
            self.i += 3
            sc = self.parse_scope()
            base = date(sc[1], 1, 1) if sc[0] == "year" else date(sc[1], sc[2], 1)
            r = Val.of_date(base + timedelta(days=n - 1))
            self.step(f"day {n} of {self.scope_text(sc)}", r)
            return r
        if v == "week" and self.pk(1) == "num":
            self.i += 2
            n = int(self.toks[self.i - 1][1])
            self.accept("of", "in")
            y = int(self.take()[1])
            try:
                r = Val.of_date(date.fromisocalendar(y, n, 1))
            except ValueError:
                raise CalcError(f"ISO year {y} has no week {n}")
            self.ctx.note("ISO week dates: weeks start Monday; week 1 contains the year's first Thursday")
            self.step(f"ISO week {n} of {y} (Monday)", r)
            return r

        # ordinals: "first monday of january 2026", "last day of feb 2028",
        # "2nd business day of next month", "third friday after 2026-03-01",
        # "5th of march 2026", "15th day of 2026"
        is_ord = k == "ordnum" or (v in ORDINAL_WORDS and v != "last") or (
            v == "last" and (self.pv(1) in ("day", "business", "working")
                             or (self.pv(1) in WEEKDAYS and self.pv(2) in ("of", "in"))))
        if v == "second" and self.pv(1) == "to" and self.pv(2) == "last":
            is_ord = True
        if is_ord:
            n = self.parse_ordinal()
            if self.pv() in WEEKDAYS:
                wd = WEEKDAYS[self.take()[1]]
                if self.accept("of", "in"):
                    sc = self.parse_scope()
                    if sc[0] == "month":
                        d = nth_weekday_of_month(sc[1], sc[2], wd, n)
                    else:
                        d = nth_weekday_of_year(sc[1], wd, n)
                    r = Val.of_date(d)
                    self.step(f"{ordinal_text(n)} {WEEKDAY_NAMES[wd]} of {self.scope_text(sc)}", r)
                    return r
                if self.pv() in ("after", "before") or self.pv() == "on":
                    if n < 1:
                        self.fail("a positive ordinal before 'after/before'")
                    return self.weekday_relative(wd, n)
                self.fail("'of <month>' or 'after <date>' after the weekday")
            if self.pv() in ("business", "working") and self.pv(1) in ("day", "days"):
                self.i += 2
                self.expect("of", "in")
                sc = self.parse_scope()
                r = Val.of_date(self.nth_business_day(sc, n))
                self.step(f"{ordinal_text(n)} business day of {self.scope_text(sc)}", r)
                return r
            if self.accept("day"):
                self.expect("of", "in")
                sc = self.parse_scope()
                if n == -1:
                    d = self.scope_bound(sc, True)
                elif n == -2:
                    d = self.scope_bound(sc, True) - timedelta(days=1)
                elif sc[0] == "month":
                    if n > days_in_month(sc[1], sc[2]):
                        raise CalcError(f"{MONTH_NAMES[sc[2]-1]} {sc[1]} has only {days_in_month(sc[1], sc[2])} days")
                    d = date(sc[1], sc[2], n)
                else:
                    d = date(sc[1], 1, 1) + timedelta(days=n - 1)
                    if d.year != sc[1]:
                        raise CalcError(f"{sc[1]} has only {366 if is_leap(sc[1]) else 365} days")
                r = Val.of_date(d)
                self.step(f"{ordinal_text(n)} day of {self.scope_text(sc)}", r)
                return r
            # "5th of march 2026" / "5th march 2026"
            if n > 0 and (self.pv() in MONTHS or (self.pv() == "of" and self.pv(1) in MONTHS)):
                self.accept("of")
                return self.finish_day_month(n)
            self.i = start_i
            self.fail("what the ordinal refers to (weekday, 'day', 'business day', or month)")

        # relative weekday: [next|last|this|coming|previous] <weekday> [after|before|on or after X]
        if (v in ("next", "last", "this", "coming", "previous", "past") and self.pv(1) in WEEKDAYS) or v in WEEKDAYS:
            mod = None
            if v not in WEEKDAYS:
                mod = self.take()[1]
            wd = WEEKDAYS[self.take()[1]]
            if self.pv() in ("after", "before") or (self.pv() == "on" and self.pv(1) == "or"):
                return self.weekday_relative(wd, 1)
            return self.weekday_from_today(wd, mod)

        # next/last/this week|month|year as a date (today shifted)
        if v in ("next", "last", "this", "previous") and self.pv(1) in ("week", "month", "year", "quarter"):
            self.i += 2
            unit = UNITS[self.toks[self.i - 1][1]]
            rel = {"this": 0, "next": 1, "last": -1, "previous": -1}[v]
            r = shift(self.today(), rel, unit, self.ctx)
            self.ctx.note(f"'{v} {self.toks[self.i-1][1]}' read as today {'+' if rel >= 0 else '-'} {abs(rel)} {unit}; "
                          f"use 'start of {v} {self.toks[self.i-1][1]}' for the boundary")
            self.step(f"{v} {self.toks[self.i-1][1]}", r)
            return r

        # month-name dates: "january 5 2026", "jan 5, 2026", "5 january 2026"
        if v in MONTHS and (self.pk(1) in ("num", "ordnum")):
            m = MONTHS[self.take()[1]]
            day = int(re.match(r"\d+", self.take()[1]).group())
            self.accept(",")
            y = self.maybe_year()
            return self.make_ymd(y, m, day)
        if k in ("num", "ordnum") and self.pv(1) in MONTHS and not self.is_duration_start():
            day = int(re.match(r"\d+", self.take()[1]).group())
            return self.finish_day_month(day)

        self.fail("a date")

    def maybe_year(self):
        if self.pk() == "num" and len(self.pv()) == 4:
            return int(self.take()[1])
        self.ctx.used_today = True
        self.ctx.note(f"no year given; assumed {self.ctx.today.year}")
        return self.ctx.today.year

    def finish_day_month(self, day: int) -> Val:
        m = MONTHS[self.take()[1]]
        self.accept(",")
        y = self.maybe_year()
        return self.make_ymd(y, m, day)

    def make_ymd(self, y, m, d) -> Val:
        if not 1 <= d <= days_in_month(y, m):
            raise CalcError(f"{MONTH_NAMES[m-1]} {y} has {days_in_month(y, m)} days, not {d}")
        r = Val.of_date(date(y, m, d))
        self.step(f"{MONTH_NAMES[m-1]} {d}, {y}", r)
        return r

    def scope_bound(self, sc, is_end: bool) -> date:
        if sc[0] == "month":
            return date(sc[1], sc[2], days_in_month(sc[1], sc[2]) if is_end else 1)
        return date(sc[1], 12, 31) if is_end else date(sc[1], 1, 1)

    def nth_business_day(self, sc, n: int) -> date:
        lo, hi = self.scope_bound(sc, False), self.scope_bound(sc, True)
        days = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
        bd = [d for d in days if is_business_day(d, self.ctx)]
        self.ctx.note("business days skip Saturday/Sunday"
                      + (" and --holidays" if self.ctx.holidays else " only (pass --holidays for public holidays)"))
        try:
            return bd[n - 1] if n > 0 else bd[n]
        except IndexError:
            raise CalcError(f"{self.scope_text(sc)} has only {len(bd)} business days")

    def weekday_relative(self, wd: int, n: int) -> Val:
        if self.accept_seq("on", "or", "after"):
            base = self.parse_expr()
            d = weekday_on_or_after(base.d(), wd, strict=False) + timedelta(weeks=n - 1)
            label = f"{ordinal_text(n) + ' ' if n > 1 else ''}{WEEKDAY_NAMES[wd]} on or after {base.d().isoformat()}"
        elif self.accept_seq("on", "or", "before"):
            base = self.parse_expr()
            d = weekday_on_or_before(base.d(), wd, strict=False) - timedelta(weeks=n - 1)
            label = f"{WEEKDAY_NAMES[wd]} on or before {base.d().isoformat()}"
        elif self.accept("after"):
            base = self.parse_expr()
            d = weekday_on_or_after(base.d(), wd, strict=True) + timedelta(weeks=n - 1)
            label = f"{ordinal_text(n) + ' ' if n > 1 else ''}{WEEKDAY_NAMES[wd]} after {base.d().isoformat()} (strictly after)"
        elif self.accept("before"):
            base = self.parse_expr()
            d = weekday_on_or_before(base.d(), wd, strict=True) - timedelta(weeks=n - 1)
            label = f"{ordinal_text(n) + ' ' if n > 1 else ''}{WEEKDAY_NAMES[wd]} before {base.d().isoformat()} (strictly before)"
        else:
            self.fail("'after X' / 'before X' / 'on or after X'")
        if isinstance(base, tuple):
            self.fail("a single date")
        r = Val(base.dt.replace(year=d.year, month=d.month, day=d.day), base.has_time)
        self.step(label, r)
        return r

    def weekday_from_today(self, wd: int, mod) -> Val:
        t = self.ctx.today
        self.ctx.used_today = True
        name = WEEKDAY_NAMES[wd]
        if mod in ("next", "coming"):
            d = weekday_on_or_after(t, wd, strict=True)
            self.ctx.note(f"'{mod} {name.lower()}' = the first {name} strictly after today")
        elif mod in ("last", "previous", "past"):
            d = weekday_on_or_before(t, wd, strict=True)
            self.ctx.note(f"'{mod} {name.lower()}' = the most recent {name} strictly before today")
        elif mod == "this":
            d = t - timedelta(days=t.weekday()) + timedelta(days=wd)
            self.ctx.note(f"'this {name.lower()}' = the {name} of the current ISO week (Mon-Sun); "
                          "may be in the past")
        else:
            d = weekday_on_or_after(t, wd, strict=False)
            self.ctx.note(f"bare '{name.lower()}' = the next {name} on or after today "
                          "(today counts if it is a {name}); say 'next'/'last' to be explicit".replace("{name}", name))
        r = Val.of_date(d)
        self.step(f"{mod + ' ' if mod else ''}{name.lower()}", r)
        return r

    # -- literal parsing --
    def parse_iso(self, s: str) -> Val:
        s2 = s.upper().replace("Z", "+00:00")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s2):
            try:
                return Val.of_date(date.fromisoformat(s2))
            except ValueError as e:
                raise CalcError(f"invalid date {s}: {e}")
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{1,2}):(\d{2})(?::(\d{2})(\.\d+)?)?([+-]\d{2}:?\d{2})?", s2)
        if not m:
            raise CalcError(f"invalid datetime {s}")
        d = date.fromisoformat(m.group(1))
        hh, mm, ss = int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
        tz = None
        if m.group(6):
            off = m.group(6).replace(":", "")
            sign = 1 if off[0] == "+" else -1
            tz = timezone(sign * timedelta(hours=int(off[1:3]), minutes=int(off[3:5])))
        elif self.ctx.tz is not None:
            tz = self.ctx.tz
        try:
            dt = datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=tz)
        except ValueError as e:
            raise CalcError(f"invalid datetime {s}: {e}")
        return Val(dt, True)

    def parse_slash(self, s: str) -> date:
        a, b, c = s.split("/")
        if len(a) == 4:
            return date(int(a), int(b), int(c))
        x, y, yr = int(a), int(b), int(c)
        if len(c) != 4:
            raise CalcError(f"'{s}': use a 4-digit year, or better, ISO YYYY-MM-DD")
        order = self.ctx.order
        if order is None:
            if x > 12 and y <= 12:
                order = "dmy"
            elif y > 12 and x <= 12:
                order = "mdy"
            elif x == y:
                order = "mdy"
            else:
                raise CalcError(f"'{s}' is ambiguous (MM/DD or DD/MM?). Use ISO "
                                "YYYY-MM-DD or pass --order mdy|dmy")
        mo, dy = (x, y) if order == "mdy" else (y, x)
        self.ctx.note(f"read {s} as {'month/day' if order == 'mdy' else 'day/month'}/year")
        return date(yr, mo, dy)


# --------------------------------------------------------------------------
# Evaluation and output
# --------------------------------------------------------------------------

def calendar_diff(a: date, b: date):
    """Whole years/months/days from a to b (a <= b), clamping like add_months."""
    months = (b.year - a.year) * 12 + (b.month - a.month)
    base = datetime(a.year, a.month, a.day)
    while months > 0 and add_months(base, months)[0].date() > b:
        months -= 1
    anchor = add_months(base, months)[0].date()
    return months // 12, months % 12, (b - anchor).days


def business_days_between(a: date, b: date, ctx: Ctx) -> int:
    """Business days in the half-open range [a, b) (negative if b < a)."""
    sign = 1
    if b < a:
        a, b, sign = b, a, -1
    total_days = (b - a).days
    full_weeks, rem = divmod(total_days, 7)
    count = full_weeks * 5
    for i in range(rem):
        if (a + timedelta(days=full_weeks * 7 + i)).weekday() < 5:
            count += 1
    count -= sum(1 for h in ctx.holidays if a <= h < b and h.weekday() < 5)
    return sign * count


def evaluate(text: str, ctx: Ctx) -> dict:
    p = Parser(text, ctx)
    q = p.parse_query()
    out = {"input": text, "today": f"{ctx.today.isoformat()} ({WEEKDAY_NAMES[ctx.today.weekday()]})"}
    if q[0] == "value":
        v = q[1]
        out.update(kind="datetime" if v.has_time else "date", result=v.iso(),
                   weekday=WEEKDAY_NAMES[v.dt.weekday()], display=v.text())
    elif q[0] == "diff":
        _, a, b, unit = q
        if isinstance(a, tuple) or isinstance(b, tuple):
            raise CalcError("a difference needs two dates")
        out["kind"] = "difference"
        out["from"], out["to"] = a.text(), b.text()
        if a.has_time or b.has_time:
            da = a.dt if a.dt.tzinfo or not b.dt.tzinfo else a.dt.replace(tzinfo=b.dt.tzinfo)
            db = b.dt if b.dt.tzinfo or not a.dt.tzinfo else b.dt.replace(tzinfo=a.dt.tzinfo)
            secs = (db - da).total_seconds()
            out["seconds"] = secs
            out["hours"] = round(secs / 3600, 6)
        days = (b.d() - a.d()).days
        sign = -1 if days < 0 else 1
        lo, hi = (a.d(), b.d()) if days >= 0 else (b.d(), a.d())
        yy, mm, dd = calendar_diff(lo, hi)
        w, rd_ = divmod(abs(days), 7)
        out["days"] = days
        out["weeks_and_days"] = f"{sign * w} weeks {rd_} days" if w else f"{days} days"
        out["weeks_decimal"] = round(days / 7, 4)
        out["years_months_days"] = f"{'-' if sign < 0 else ''}{yy}y {mm}m {dd}d"
        out["months_total"] = sign * (yy * 12 + mm)
        out["business_days"] = business_days_between(a.d(), b.d(), ctx)
        ctx.note("days = to - from (exclusive of the start, inclusive of the end); add 1 if you need both ends counted")
        ctx.note("business_days counts Mon-Fri in [from, to) minus any --holidays")
        if not unit:
            out["answer"] = f"{days} days"
        if unit:
            key = {"days": "days", "weeks": "weeks_decimal", "months": "months_total",
                   "years": "years_months_days", "bdays": "business_days",
                   "hours": "hours", "minutes": "hours", "seconds": "seconds"}.get(unit, "days")
            if unit in ("hours", "minutes", "seconds") and "seconds" not in out:
                secs = days * 86400
                out["seconds"], out["hours"] = secs, secs / 3600
            if unit == "minutes":
                out["minutes"] = out["seconds"] / 60
                key = "minutes"
            out["answer"] = f"{out[key]} {('business days' if unit == 'bdays' else unit) if key not in ('years_months_days',) else ''}".strip()
    elif q[0] == "series":
        _, start, n, unit, include_start, count, until = q
        res = []
        k = 0 if include_start else 1
        limit = 10000
        while len(res) < limit:
            v = shift(start, n * k, unit, ctx)
            if until is not None and v.dt.replace(tzinfo=None) > until.dt.replace(tzinfo=None):
                break
            res.append(v)
            if count is not None and len(res) >= count:
                break
            k += 1
        out["kind"] = "series"
        out["rule"] = (f"every {n} {unit} " + ("starting on" if include_start else "after")
                       + f" {start.text()}")
        out["results"] = [v.iso() for v in res]
        out["display"] = [f"#{i+1}: {v.text()}" for i, v in enumerate(res)]
        if unit in ("months", "years", "quarters"):
            ctx.note("each occurrence is computed from the start date (start + k*step), so a 31st "
                     "start stays on the 31st when possible instead of drifting to the 28th")
        ctx.note("'every N X after D' excludes D; 'every N X from D' includes D")
    out["steps"] = [{"step": s, "value": v} for s, v in ctx.steps]
    out["notes"] = list(ctx.notes)
    return out


def print_human(out: dict):
    kind = out.get("kind")
    print(f"input   : {out['input']}")
    if kind in ("date", "datetime"):
        print(f"RESULT  : {out['display']}")
    elif kind == "difference":
        print(f"from    : {out['from']}")
        print(f"to      : {out['to']}")
        if "answer" in out:
            print(f"RESULT  : {out['answer']}")
        print(f"days    : {out['days']}")
        print(f"weeks   : {out['weeks_and_days']}  ({out['weeks_decimal']} weeks)")
        print(f"y/m/d   : {out['years_months_days']}  ({out['months_total']} whole months)")
        print(f"bus.days: {out['business_days']}")
        if "hours" in out:
            print(f"hours   : {out['hours']}")
    elif kind == "series":
        print(f"rule    : {out['rule']}")
        for line in out["display"]:
            print(f"  {line}")
    if out.get("steps"):
        print("steps   :")
        w = max(len(s["step"]) for s in out["steps"])
        for s in out["steps"]:
            print(f"  {s['step']:<{w}}  -> {s['value']}")
    print(f"today   : {out['today']}")
    for n in out.get("notes", []):
        print(f"note    : {n}")


def info(n: int) -> dict:
    d = from_rd(n)
    iy, iw, idw = d.isocalendar()
    out = {
        "date": d.isoformat(),
        "weekday": WEEKDAY_NAMES[d.weekday()],
        "iso_week": f"{iy}-W{iw:02d}-{idw}",
        "day_of_year": d.timetuple().tm_yday,
        "days_in_year": 366 if is_leap(d.year) else 365,
        "leap_year": is_leap(d.year),
        "quarter": (d.month - 1) // 3 + 1,
        "days_in_month": days_in_month(d.year, d.month),
        "first_of_month": date(d.year, d.month, 1).isoformat(),
        "last_of_month": date(d.year, d.month, days_in_month(d.year, d.month)).isoformat(),
        "first_of_next_month": add_months(datetime(d.year, d.month, 1), 1)[0].date().isoformat(),
        "nth_weekday_in_month": f"{ordinal_text((d.day - 1) // 7 + 1)} {WEEKDAY_NAMES[d.weekday()]} of {MONTH_NAMES[d.month-1]}",
        "unix_midnight_utc": int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()),
        "rata_die": n,
        "julian_day_number": n + 1721425,
        "calendars": all_calendars(n),
    }
    return out


EXAMPLES = r"""
EXPRESSIONS (case-insensitive; 'the' and '?' are ignored)

  anchors
    today | tomorrow | yesterday | now
    2026-01-05 | 2026-01-05T14:30 | 2026-01-05 14:30:00+02:00 | 2026-01-05T14:30Z
    2026-03            (= 2026-03-01)
    january 5 2026 | jan 5, 2026 | 5 january 2026 | 5th of march 2026
    first monday of january 2026     2nd tuesday of 2026-03     last friday of next month
    second to last sunday of october 2026        first monday of 2026 (year scope)
    first day of next month          last day of february 2028    15th day of 2026
    first business day of 2026-06    last business day of this month
    start of month | end of next month | start of 2027 | end of this week (ISO, Sunday)
    next monday   (strictly after today)       last wednesday (strictly before today)
    this friday   (Friday of the current Mon-Sun week)       monday (on or after today)
    monday after 2026-03-01 (strict)   friday before 2026-12-25 (strict)
    monday on or after 2026-03-02      third friday after 2026-01-01
    day 100 of 2026                    week 10 of 2026 (ISO week, Monday)
    hebrew:5787-tishrei-1   hebrew:5786-1-15 (Nisan=1)   julian:2026-01-01
    hijri:1447-9-1 (Umm al-Qura)   hijri-tabular:1447-9-1   chinese:2026-1-1   chinese:2025-L6-1
    easter 2026 | orthodox easter 2026 | passover 2026 | rosh hashanah 2026 | hanukkah 2026
    yom kippur | purim | shavuot | sukkot | ramadan 2026 | eid al-fitr 2026 | eid al-adha 2026
    islamic new year 2026 | chinese new year 2026 | mid-autumn 2026 | dragon boat 2026
    thanksgiving 2026 | good friday 2026

  arithmetic (left to right)
    <anchor> + 3 weeks - 2 days        <anchor> + 1 month (end-of-month clamps)
    <anchor> + 10 business days        <anchor> + 36 hours (absolute time)
    3 weeks after <anchor>             5 days before <anchor>
    90 days from now | 2 weeks ago | in 45 days
    <anchor> at 9:30 | at 5pm | at noon

  differences
    days between 2026-01-01 and 2026-03-15        2026-12-25 - today
    weeks until christmas? -> use: weeks until 2026-12-25
    business days between 2026-01-01 and 2026-02-01        days since 2026-01-01
    from 2026-01-01 to 2026-12-31

  series
    every 2 weeks after 2026-01-05 count 6      (excludes the start)
    every 2 weeks from 2026-01-05 until 2026-04-01  (includes the start)
    every month from 2026-01-31 count 4         (31st clamps per month, no drift)
    every monday from 2026-03-01 count 4        every 3 days from today for 2 weeks
    every 5 business days from 2026-01-02 count 5

SUBCOMMANDS
    convert <expr>     show the date in all calendars
    info <expr>        weekday, ISO week, day of year, month bounds, all calendars
    diff <expr> <expr> difference between two dates
    selftest           run the built-in verification suite
"""


# --------------------------------------------------------------------------
# Self test: facts cross-checked against independent sources/libraries
# --------------------------------------------------------------------------

SELFTEST = [
    # expression, today, expected result (iso) -- arithmetic & parsing
    ("first monday of january 2026 + 3 weeks", "2026-10-31", "2026-01-26"),
    ("first monday of january 2026", "2026-10-31", "2026-01-05"),
    ("today + 90 days", "2026-10-31", "2027-01-29"),
    ("last wednesday + 5 days", "2026-10-31", "2026-11-02"),
    ("next monday", "2026-11-02", "2026-11-09"),
    ("monday", "2026-11-02", "2026-11-02"),
    ("2026-01-31 + 1 month", "2026-10-31", "2026-02-28"),
    ("2024-02-29 + 1 year", "2026-10-31", "2025-02-28"),
    ("first day of next month", "2026-10-31", "2026-11-01"),
    ("last day of february 2028", "2026-10-31", "2028-02-29"),
    ("last friday of november 2026", "2026-10-31", "2026-11-27"),
    ("2026-12-24 + 3 business days", "2026-10-31", "2026-12-29"),
    ("3 weeks after 2026-02-10", "2026-10-31", "2026-03-03"),
    ("week 1 of 2026", "2026-10-31", "2025-12-29"),
    ("day 256 of 2026", "2026-10-31", "2026-09-13"),
    ("thanksgiving 2026", "2026-10-31", "2026-11-26"),
    ("2026-03-08T01:30 + 1 hour", "2026-10-31", "2026-03-08T02:30:00"),
    # holidays / calendars (cross-checked with convertdate, hijridate, lunardate,
    # and published tables)
    ("easter 2026", "2026-10-31", "2026-04-05"),
    ("orthodox easter 2026", "2026-10-31", "2026-04-12"),
    ("easter 2025", "2026-10-31", "2025-04-20"),
    ("rosh hashanah 2026", "2026-10-31", "2026-09-12"),
    ("yom kippur 2026", "2026-10-31", "2026-09-21"),
    ("passover 2026", "2026-10-31", "2026-04-02"),
    ("hanukkah 2026", "2026-10-31", "2026-12-05"),
    ("purim 2027", "2026-10-31", "2027-03-23"),
    ("ramadan 2026", "2026-10-31", "2026-02-18"),
    ("eid al-fitr 2026", "2026-10-31", "2026-03-20"),
    ("chinese new year 2026", "2026-10-31", "2026-02-17"),
    ("chinese new year 2025", "2026-10-31", "2025-01-29"),
    ("chinese new year 2024", "2026-10-31", "2024-02-10"),
    ("mid-autumn 2026", "2026-10-31", "2026-09-25"),
    ("chinese:2025-L6-1", "2026-10-31", "2025-07-25"),
    ("julian:2026-01-01", "2026-10-31", "2026-01-14"),
    ("hebrew:5787-tishrei-1", "2026-10-31", "2026-09-12"),
    ("hijri-tabular:1447-9-1", "2026-10-31", "2026-02-18"),
]


def run_selftest() -> int:
    failures = 0
    for expr, today, expected in SELFTEST:
        ctx = Ctx(date.fromisoformat(today), datetime.fromisoformat(today + "T12:00:00"), None, set(), None)
        try:
            got = evaluate(expr, ctx).get("result")
        except Exception as e:  # pragma: no cover
            got = f"ERROR {e}"
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {expr!r:48} today={today} -> {got} (expected {expected})")
    # diff checks
    ctx = Ctx(date(2026, 10, 31), datetime(2026, 10, 31, 12), None, set(), None)
    d = evaluate("days between 2026-01-01 and 2026-03-15", ctx)
    ok = d["days"] == 73 and d["business_days"] == 52 and d["years_months_days"] == "0y 2m 14d"
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} days between 2026-01-01 and 2026-03-15 -> {d['days']} days, {d['business_days']} bdays, {d['years_months_days']}")
    s = evaluate("every month from 2026-01-31 count 4", Ctx(date(2026, 10, 31), datetime(2026, 10, 31), None, set(), None))
    ok = s["results"] == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'} every month from 2026-01-31 count 4 -> {s['results']}")
    # calendar round trips over a wide range
    bad = 0
    for n in range(rd(1900, 1, 1), rd(2100, 12, 31), 37):
        if fixed_from_julian(*julian_from_fixed(n)) != n: bad += 1
        if fixed_from_hebrew(*hebrew_from_fixed(n)) != n: bad += 1
        if fixed_from_islamic_tabular(*islamic_tabular_from_fixed(n)) != n: bad += 1
    for n in range(rd(1925, 1, 1), rd(2077, 1, 1), 41):
        if fixed_from_umalqura(*umalqura_from_fixed(n)) != n: bad += 1
    for n in range(rd(1901, 3, 1), rd(2099, 12, 1), 997):
        if fixed_from_chinese(*chinese_from_fixed(n)) != n: bad += 1
    failures += bad > 0
    print(f"{'ok  ' if not bad else 'FAIL'} calendar round-trips 1900-2100: {bad} mismatches")
    print(f"\n{'ALL PASSED' if failures == 0 else str(failures) + ' FAILURE(S)'}")
    return 1 if failures else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_ctx(args) -> Ctx:
    tz = None
    if args.tz:
        if ZoneInfo is None:
            raise CalcError("--tz needs Python 3.9+ zoneinfo")
        try:
            tz = ZoneInfo(args.tz)
        except Exception:
            raise CalcError(f"unknown time zone {args.tz!r} (use IANA names like Europe/Bucharest)")
    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None and tz is not None:
            now = now.replace(tzinfo=tz)
    else:
        now = datetime.now(tz) if tz else datetime.now().astimezone()
        now = now.replace(microsecond=0)
    today = date.fromisoformat(args.today) if args.today else now.date()
    if args.today and not args.now:
        now = now.replace(year=today.year, month=today.month, day=today.day)
    hol = set()
    if args.holidays:
        for h in args.holidays.split(","):
            h = h.strip()
            if h:
                hol.add(date.fromisoformat(h))
    return Ctx(today, now, tz, hol, args.order)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="datecalc.py", add_help=False)
    ap.add_argument("--today")
    ap.add_argument("--now")
    ap.add_argument("--tz")
    ap.add_argument("--holidays")
    ap.add_argument("--order", choices=["mdy", "dmy"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    ap.add_argument("--version", action="store_true")
    args, rest = ap.parse_known_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.help or not rest:
        print(__doc__)
        return 0
    cmd = rest[0].lower()
    try:
        if cmd == "selftest":
            return run_selftest()
        if cmd == "examples":
            print(EXAMPLES)
            return 0
        ctx = build_ctx(args)
        if cmd in ("convert", "info"):
            expr = " ".join(rest[1:])
            if not expr:
                raise CalcError(f"usage: datecalc.py {cmd} <date expression>")
            res = evaluate(expr, ctx)
            if res.get("kind") not in ("date", "datetime"):
                raise CalcError(f"{cmd} needs a single date")
            n = date.fromisoformat(res["result"][:10]).toordinal()
            data = info(n) if cmd == "info" else all_calendars(n)
            data = {"input": expr, **({"weekday": WEEKDAY_NAMES[from_rd(n).weekday()]} if cmd == "convert" else {}), **data}
            if args.json:
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                for k, v in data.items():
                    if isinstance(v, dict):
                        print(f"{k}:")
                        for k2, v2 in v.items():
                            print(f"  {k2:<14}: {v2}")
                    else:
                        print(f"{k:<20}: {v}")
            return 0
        if cmd == "diff":
            if len(rest) != 3:
                raise CalcError('usage: datecalc.py diff "<date A>" "<date B>"  (quote each date)')
            expr = f"between ({rest[1]}) and ({rest[2]})"
            res = evaluate(expr, ctx)
            res["input"] = f"diff {rest[1]!r} {rest[2]!r}"
        else:
            res = evaluate(" ".join(rest), ctx)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print_human(res)
        return 0
    except CalcError as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
