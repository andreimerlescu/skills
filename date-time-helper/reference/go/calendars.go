package datecal

// Calendar conversions. Everything goes through RD ("rata die"): an integer
// day number with RD 1 = 0001-01-01 (proleptic Gregorian). Convert a calendar
// date to RD, do arithmetic on the integer, convert back.
//
// All functions are pure and safe for concurrent use. The Umm al-Qura table is
// built once (sync.Once) and is read-only afterwards.
//
// Month numbering (same as scripts/datecalc.py):
//   - Julian: 1..12, astronomical years (year 0 = 1 BCE).
//   - Hebrew: Nisan = 1 ... Elul = 6, Tishrei = 7 ... Adar (Adar I in leap
//     years) = 12, Adar II = 13. The year number changes on 1 Tishrei.
//   - Hijri: Muharram = 1 ... Ramadan = 9 ... Dhu al-Hijjah = 12.
//   - Chinese: Year = Gregorian year in which that Chinese New Year falls;
//     Month 1..12 plus Leap flag; Day 1..30. Valid 1929..2100.

import (
	_ "embed"
	"math"
	"strings"
	"sync"
	"time"
)

const unixEpochRD = 719163 // RD of 1970-01-01

func floorDiv(a, b int) int {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

func mod(a, b int) int { return a - b*floorDiv(a, b) }

// RD returns the day number of t's civil date.
func RD(t time.Time) int {
	c := Civil(t)
	return floorDiv(int(c.Unix()), 86400) + unixEpochRD
}

// FromRD returns the civil date (UTC midnight) for day number n.
func FromRD(n int) time.Time { return Date(1970, 1, 1+(n-unixEpochRD)) }

// ---------------------------------------------------------------- Julian

const julianEpoch = -1

// JulianLeap reports whether Julian year y (astronomical numbering) is a leap year.
func JulianLeap(y int) bool { return mod(y, 4) == 0 }

// FixedFromJulian converts a Julian calendar date to RD. It does not validate m/d.
func FixedFromJulian(y, m, d int) int {
	corr := 0
	if m > 2 {
		if JulianLeap(y) {
			corr = -1
		} else {
			corr = -2
		}
	}
	return julianEpoch - 1 + 365*(y-1) + floorDiv(y-1, 4) + floorDiv(367*m-362, 12) + corr + d
}

// JulianFromFixed converts RD to a Julian calendar date.
func JulianFromFixed(n int) (y, m, d int) {
	y = floorDiv(4*(n-julianEpoch)+1464, 1461)
	prior := n - FixedFromJulian(y, 1, 1)
	corr := 0
	if n >= FixedFromJulian(y, 3, 1) {
		if JulianLeap(y) {
			corr = 1
		} else {
			corr = 2
		}
	}
	m = floorDiv(12*(prior+corr)+373, 367)
	d = n - FixedFromJulian(y, m, 1) + 1
	return
}

// ---------------------------------------------------------------- Hebrew

const hebrewEpoch = -1373427 // RD of 1 Tishrei AM 1

// HebrewLeap reports whether Hebrew year y has 13 months (Adar I and Adar II).
func HebrewLeap(y int) bool { return mod(7*y+1, 19) < 7 }

// HebrewLastMonth returns 13 in leap years, else 12 (Nisan = 1 numbering).
func HebrewLastMonth(y int) int {
	if HebrewLeap(y) {
		return 13
	}
	return 12
}

func hebrewElapsedDays(y int) int {
	months := floorDiv(235*y-234, 19)
	parts := 12084 + 13753*months
	days := 29*months + floorDiv(parts, 25920)
	if mod(3*(days+1), 7) < 3 {
		return days + 1
	}
	return days
}

func hebrewYearLengthCorrection(y int) int {
	ny0, ny1, ny2 := hebrewElapsedDays(y-1), hebrewElapsedDays(y), hebrewElapsedDays(y+1)
	switch {
	case ny2-ny1 == 356:
		return 2
	case ny1-ny0 == 382:
		return 1
	}
	return 0
}

// HebrewNewYear returns the RD of 1 Tishrei of year y.
func HebrewNewYear(y int) int {
	return hebrewEpoch + hebrewElapsedDays(y) + hebrewYearLengthCorrection(y)
}

// HebrewDaysInYear returns 353-355 (common) or 383-385 (leap).
func HebrewDaysInYear(y int) int { return HebrewNewYear(y+1) - HebrewNewYear(y) }

// HebrewMonthLength returns 29 or 30 for month m (Nisan = 1) of year y.
func HebrewMonthLength(y, m int) int {
	yl := HebrewDaysInYear(y)
	switch {
	case m == 2 || m == 4 || m == 6 || m == 10 || m == 13:
		return 29
	case m == 12 && !HebrewLeap(y):
		return 29
	case m == 8 && yl != 355 && yl != 385:
		return 29
	case m == 9 && (yl == 353 || yl == 383):
		return 29
	}
	return 30
}

// FixedFromHebrew returns ok=false for a date that does not exist
// (e.g. Adar II in a common year).
func FixedFromHebrew(y, m, d int) (int, bool) {
	if m < 1 || m > HebrewLastMonth(y) || d < 1 || d > HebrewMonthLength(y, m) {
		return 0, false
	}
	n := HebrewNewYear(y) + d - 1
	if m < 7 {
		for mm := 7; mm <= HebrewLastMonth(y); mm++ {
			n += HebrewMonthLength(y, mm)
		}
		for mm := 1; mm < m; mm++ {
			n += HebrewMonthLength(y, mm)
		}
	} else {
		for mm := 7; mm < m; mm++ {
			n += HebrewMonthLength(y, mm)
		}
	}
	return n, true
}

// mustHebrew is only called with dates derived from valid year/month bounds.
func mustHebrew(y, m, d int) int {
	n, _ := FixedFromHebrew(y, m, d)
	return n
}

// HebrewFromFixed converts RD to (year, month with Nisan = 1, day).
func HebrewFromFixed(n int) (y, m, d int) {
	approx := int(math.Floor(float64(n-hebrewEpoch)/(35975351.0/98496.0))) + 1
	y = approx - 1
	for HebrewNewYear(y+1) <= n {
		y++
	}
	m = 1
	if n < mustHebrew(y, 1, 1) {
		m = 7
	}
	for n > mustHebrew(y, m, HebrewMonthLength(y, m)) {
		m++
	}
	d = n - mustHebrew(y, m, 1) + 1
	return
}

// ---------------------------------------------------------------- Hijri

const islamicEpoch = 227015 // 1 Muharram 1 AH

// FixedFromHijriTabular: arithmetic ("civil") Islamic calendar.
func FixedFromHijriTabular(y, m, d int) int {
	return islamicEpoch - 1 + (y-1)*354 + floorDiv(3+11*y, 30) + 29*(m-1) + floorDiv(m, 2) + d
}

// HijriTabularFromFixed converts RD to the arithmetic Islamic calendar.
func HijriTabularFromFixed(n int) (y, m, d int) {
	y = floorDiv(30*(n-islamicEpoch)+10646, 10631)
	prior := n - FixedFromHijriTabular(y, 1, 1)
	m = floorDiv(11*prior+330, 325)
	d = n - FixedFromHijriTabular(y, m, 1) + 1
	return
}

//go:embed umalqura_month_lengths.txt
var uaqData string

const uaqFirstRD = 702574 // 1924-08-01 = 1 Muharram 1343
const uaqFirstYear = 1343

var uaqOnce sync.Once
var uaqStarts []int

func uaq() []int {
	uaqOnce.Do(func() {
		uaqStarts = []int{uaqFirstRD}
		for _, line := range strings.Split(uaqData, "\n") {
			if strings.HasPrefix(line, "#") {
				continue
			}
			for _, c := range strings.TrimSpace(line) {
				uaqStarts = append(uaqStarts, uaqStarts[len(uaqStarts)-1]+28+int(c-'0'))
			}
		}
	})
	return uaqStarts
}

// FixedFromUmmAlQura: official Saudi calendar, 1343..1500 AH (ok=false outside).
func FixedFromUmmAlQura(y, m, d int) (int, bool) {
	s := uaq()
	idx := (y-uaqFirstYear)*12 + (m - 1)
	if m < 1 || m > 12 || idx < 0 || idx+1 >= len(s) || d < 1 || d > s[idx+1]-s[idx] {
		return 0, false
	}
	return s[idx] + d - 1, true
}

// UmmAlQuraFromFixed converts RD to Umm al-Qura; ok is false outside 1924-08-01..2077-11-16.
func UmmAlQuraFromFixed(n int) (y, m, d int, ok bool) {
	s := uaq()
	if n < s[0] || n >= s[len(s)-1] {
		return 0, 0, 0, false
	}
	lo, hi := 0, len(s)-1
	for hi-lo > 1 {
		mid := (lo + hi) / 2
		if s[mid] <= n {
			lo = mid
		} else {
			hi = mid
		}
	}
	return lo/12 + uaqFirstYear, lo%12 + 1, n - s[lo] + 1, true
}

// ---------------------------------------------------------------- Chinese
// Astronomical rules (Reingold & Dershowitz) with Meeus new moons, Beijing
// time. Validated day-by-day against sxtwl and ICU4X for 1929-2100.

const msm = 29.530588861
const mty = 365.242189

func approxYear(t float64) float64 { return 2000.0 + (t-730120.5)/365.2425 }

func deltaTSeconds(y float64) float64 {
	p := math.Pow
	switch {
	case y >= 2005 && y < 2050:
		t := y - 2000
		return 62.92 + 0.32217*t + 0.005589*t*t
	case y >= 1986 && y < 2005:
		t := y - 2000
		return 63.86 + 0.3345*t - 0.060374*p(t, 2) + 0.0017275*p(t, 3) + 0.000651814*p(t, 4) + 0.00002373599*p(t, 5)
	case y >= 1961 && y < 1986:
		t := y - 1975
		return 45.45 + 1.067*t - p(t, 2)/260 - p(t, 3)/718
	case y >= 1941 && y < 1961:
		t := y - 1950
		return 29.07 + 0.407*t - p(t, 2)/233 + p(t, 3)/2547
	case y >= 1920 && y < 1941:
		t := y - 1920
		return 21.20 + 0.84493*t - 0.076100*p(t, 2) + 0.0020936*p(t, 3)
	case y >= 1900 && y < 1920:
		t := y - 1900
		return -2.79 + 1.494119*t - 0.0598939*p(t, 2) + 0.0061966*p(t, 3) - 0.000197*p(t, 4)
	case y >= 2050 && y < 2150:
		return -20 + 32*p((y-1820)/100, 2) - 0.5628*(2150-y)
	}
	u := (y - 1820) / 100
	return -20 + 32*u*u
}

func sind(x float64) float64 { return math.Sin(x * math.Pi / 180) }

func fmod360(x float64) float64 {
	r := math.Mod(x, 360)
	if r < 0 {
		r += 360
	}
	return r
}

// SolarLongitude returns the apparent solar longitude (degrees) at UT moment t (RD).
func SolarLongitude(t float64) float64 {
	tt := t + deltaTSeconds(approxYear(t))/86400
	c := (tt - 730120.5) / 36525
	l0 := 280.46646 + 36000.76983*c + 0.0003032*c*c
	m := 357.52911 + 35999.05029*c - 0.0001537*c*c
	eq := (1.914602-0.004817*c-0.000014*c*c)*sind(m) + (0.019993-0.000101*c)*sind(2*m) + 0.000289*sind(3*m)
	omega := 125.04 - 1934.136*c
	return fmod360(l0 + eq - 0.00569 - 0.00478*sind(omega))
}

var nmA = [14][3]float64{
	{299.77, 0.107408, -0.009173}, {251.88, 0.016321, 0}, {251.83, 26.651886, 0},
	{349.42, 36.412478, 0}, {84.66, 18.206239, 0}, {141.74, 53.303771, 0},
	{207.14, 2.453732, 0}, {154.84, 7.306860, 0}, {34.52, 27.261239, 0},
	{207.19, 0.121824, 0}, {291.34, 1.844379, 0}, {161.72, 24.198154, 0},
	{239.56, 25.513099, 0}, {331.55, 3.592518, 0},
}
var nmAC = [14]float64{0.000325, 0.000165, 0.000164, 0.000126, 0.000110, 0.000062, 0.000060,
	0.000056, 0.000047, 0.000042, 0.000040, 0.000037, 0.000035, 0.000023}

// NthNewMoon returns the UT moment (RD) of new moon k (k = 0 near 2000-01-06). Meeus ch. 49.
func NthNewMoon(k int) float64 {
	kf := float64(k)
	t := kf / 1236.85
	p := math.Pow
	jde := 2451550.09766 + 29.530588861*kf + 0.00015437*t*t - 0.000000150*p(t, 3) + 0.00000000073*p(t, 4)
	e := 1 - 0.002516*t - 0.0000074*t*t
	m := 2.5534 + 29.10535670*kf - 0.0000014*t*t - 0.00000011*p(t, 3)
	mp := 201.5643 + 385.81693528*kf + 0.0107582*t*t + 0.00001238*p(t, 3) - 0.000000058*p(t, 4)
	f := 160.7108 + 390.67050284*kf - 0.0016118*t*t - 0.00000227*p(t, 3) + 0.000000011*p(t, 4)
	om := 124.7746 - 1.56375588*kf + 0.0020672*t*t + 0.00000215*p(t, 3)
	corr := -0.40720*sind(mp) + 0.17241*e*sind(m) + 0.01608*sind(2*mp) + 0.01039*sind(2*f) +
		0.00739*e*sind(mp-m) - 0.00514*e*sind(mp+m) + 0.00208*e*e*sind(2*m) -
		0.00111*sind(mp-2*f) - 0.00057*sind(mp+2*f) + 0.00056*e*sind(2*mp+m) -
		0.00042*sind(3*mp) + 0.00042*e*sind(m+2*f) + 0.00038*e*sind(m-2*f) -
		0.00024*e*sind(2*mp-m) - 0.00017*sind(om) - 0.00007*sind(mp+2*m) +
		0.00004*sind(2*mp-2*f) + 0.00004*sind(3*m) + 0.00003*sind(mp+m-2*f) +
		0.00003*sind(2*mp+2*f) - 0.00003*sind(mp+m+2*f) + 0.00003*sind(mp-m+2*f) -
		0.00002*sind(mp-m-2*f) - 0.00002*sind(3*mp+m) + 0.00002*sind(4*mp)
	extra := 0.0
	for i, a := range nmA {
		extra += nmAC[i] * sind(a[0]+a[1]*kf+a[2]*t*t)
	}
	jde += corr + extra
	tTT := jde - 1721424.5
	return tTT - deltaTSeconds(approxYear(tTT))/86400
}

const nm0 = 2451550.09766 - 1721424.5

func newMoonAtOrAfter(t float64) float64 {
	k := int(math.Floor((t-nm0)/msm)) - 2
	for NthNewMoon(k) < t {
		k++
	}
	return NthNewMoon(k)
}

func newMoonBefore(t float64) float64 {
	k := int(math.Floor((t-nm0)/msm)) + 2
	for NthNewMoon(k) >= t {
		k--
	}
	return NthNewMoon(k)
}

func chinaOffset(n float64) float64 {
	if n >= 704731 { // 1929-01-01: Beijing standard time UTC+8
		return 8.0 / 24
	}
	return (1397.0 / 180) / 24 // Beijing local mean time before 1929
}

func midnightInChina(n int) float64 { return float64(n) - chinaOffset(float64(n)) }
func chinaDateOf(t float64) int     { return int(math.Floor(t + chinaOffset(t))) }

func estimatePriorSolarLongitude(lam, tau float64) float64 {
	rate := mty / 360
	tau1 := tau - rate*fmod360(SolarLongitude(tau)-lam)
	delta := fmod360(SolarLongitude(tau1)-lam+180) - 180
	return math.Min(tau, tau1-rate*delta)
}

func winterSolsticeOnOrBefore(n int) int {
	i := int(math.Floor(estimatePriorSolarLongitude(270, midnightInChina(n+1)))) - 1
	for {
		s := SolarLongitude(midnightInChina(i + 1))
		if s > 270 && s < 300 {
			return i
		}
		i++
	}
}

func cnNewMoonOnOrAfter(n int) int { return chinaDateOf(newMoonAtOrAfter(midnightInChina(n))) }
func cnNewMoonBefore(n int) int    { return chinaDateOf(newMoonBefore(midnightInChina(n))) }

func majorSolarTerm(n int) int {
	s := SolarLongitude(midnightInChina(n))
	return mod(2+int(math.Floor(s/30))-1, 12) + 1
}

func noMajorSolarTerm(n int) bool {
	return majorSolarTerm(n) == majorSolarTerm(cnNewMoonOnOrAfter(n+1))
}

func priorLeapMonth(mPrime, m int) bool {
	for m >= mPrime {
		if noMajorSolarTerm(m) {
			return true
		}
		m = cnNewMoonBefore(m)
	}
	return false
}

func cnNewYearInSui(n int) int {
	s1 := winterSolsticeOnOrBefore(n)
	s2 := winterSolsticeOnOrBefore(s1 + 370)
	m12 := cnNewMoonOnOrAfter(s1 + 1)
	m13 := cnNewMoonOnOrAfter(m12 + 1)
	nextM11 := cnNewMoonBefore(s2 + 1)
	if math.Round(float64(nextM11-m12)/msm) == 12 && (noMajorSolarTerm(m12) || noMajorSolarTerm(m13)) {
		return cnNewMoonOnOrAfter(m13 + 1)
	}
	return m13
}

// ChineseNewYearOnOrBefore returns the RD of the Chinese New Year on or before n.
func ChineseNewYearOnOrBefore(n int) int {
	ny := cnNewYearInSui(n)
	if n >= ny {
		return ny
	}
	return cnNewYearInSui(n - 180)
}

// ChineseDate: Year is the Gregorian year in which that Chinese New Year falls.
type ChineseDate struct {
	Year  int
	Month int
	Leap  bool
	Day   int
}

// ChineseFromFixed converts RD to the Chinese calendar. Results are validated
// for 1929-2100 only; earlier years differ from historical almanacs.
func ChineseFromFixed(n int) ChineseDate {
	s1 := winterSolsticeOnOrBefore(n)
	s2 := winterSolsticeOnOrBefore(s1 + 370)
	m12 := cnNewMoonOnOrAfter(s1 + 1)
	nextM11 := cnNewMoonBefore(s2 + 1)
	m := cnNewMoonBefore(n + 1)
	leapYear := math.Round(float64(nextM11-m12)/msm) == 12
	raw := int(math.Round(float64(m-m12) / msm))
	if leapYear && priorLeapMonth(m12, m) {
		raw--
	}
	leap := leapYear && noMajorSolarTerm(m) && !priorLeapMonth(m12, cnNewMoonBefore(m))
	return ChineseDate{
		Year:  FromRD(ChineseNewYearOnOrBefore(n)).Year(),
		Month: mod(raw-1, 12) + 1,
		Leap:  leap,
		Day:   n - m + 1,
	}
}

// FixedFromChinese returns ok=false if that (leap) month/day does not exist.
func FixedFromChinese(c ChineseDate) (int, bool) {
	ny := ChineseNewYearOnOrBefore(RD(Date(c.Year, time.July, 1)))
	p := cnNewMoonOnOrAfter(ny + (c.Month-1)*29)
	d := ChineseFromFixed(p)
	start := p
	if d.Month != c.Month || d.Leap != c.Leap {
		start = cnNewMoonOnOrAfter(p + 1)
	}
	n := start + c.Day - 1
	return n, ChineseFromFixed(n) == c
}
