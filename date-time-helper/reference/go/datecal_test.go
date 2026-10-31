package datecal

import (
	"encoding/csv"
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

const layout = "2006-01-02"

func d(s string) time.Time {
	t, err := time.Parse(layout, s)
	if err != nil {
		panic(err)
	}
	return t
}

func rows(t *testing.T, name string) [][]string {
	f, err := os.Open("../testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	r, err := csv.NewReader(f).ReadAll()
	if err != nil {
		t.Fatal(err)
	}
	return r[1:]
}

func atoi(s string) int {
	n, err := strconv.Atoi(s)
	if err != nil {
		panic(err)
	}
	return n
}

var weekdays = map[string]time.Weekday{"Mon": time.Monday, "Tue": time.Tuesday,
	"Wed": time.Wednesday, "Thu": time.Thursday, "Fri": time.Friday,
	"Sat": time.Saturday, "Sun": time.Sunday}

func TestSkillExamples(t *testing.T) {
	// "first monday of january 2026 + 3 weeks"
	fm, ok := NthWeekdayOfMonth(2026, time.January, time.Monday, 1)
	if !ok || fm.Format(layout) != "2026-01-05" {
		t.Fatal(fm)
	}
	if got := AddDays(fm, 21).Format(layout); got != "2026-01-26" {
		t.Fatal(got)
	}
	// "today + 90 days" with today = 2026-10-31
	if got := AddDays(d("2026-10-31"), 90).Format(layout); got != "2027-01-29" {
		t.Fatal(got)
	}
	// "last wednesday + 5 days" with today = 2026-10-31 (Saturday)
	if got := AddDays(PrevWeekday(d("2026-10-31"), time.Wednesday), 5).Format(layout); got != "2026-11-02" {
		t.Fatal(got)
	}
}

func TestAddDateOverflowGotcha(t *testing.T) {
	// Go's AddDate normalises instead of clamping. Know which one you want.
	if got := d("2026-01-31").AddDate(0, 1, 0).Format(layout); got != "2026-03-03" {
		t.Fatal(got)
	}
	if got := AddMonths(d("2026-01-31"), 1).Format(layout); got != "2026-02-28" {
		t.Fatal(got)
	}
	got := EveryNMonths(d("2026-01-31"), 1, true, 4)
	want := []string{"2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"}
	for i := range want {
		if got[i].Format(layout) != want[i] {
			t.Fatal(got)
		}
	}
}

func TestDSTSafeDayCount(t *testing.T) {
	ny, _ := time.LoadLocation("America/New_York")
	a := time.Date(2026, 3, 7, 12, 0, 0, 0, ny)
	b := time.Date(2026, 3, 9, 0, 30, 0, 0, ny) // crosses spring-forward
	if DaysBetween(a, b) != 2 {
		t.Fatal(DaysBetween(a, b))
	}
}

func TestArithmeticGolden(t *testing.T) {
	n := 0
	for _, r := range rows(t, "arithmetic.csv") {
		op, a, b, exp := r[0], r[1], r[2], r[3]
		var got string
		switch op {
		case "add_months":
			got = AddMonths(d(a), atoi(b)).Format(layout)
		case "add_days":
			got = AddDays(d(a), atoi(b)).Format(layout)
		case "nth_weekday":
			ys, ms, ok1 := strings.Cut(a, "-")
			w, ks, ok2 := strings.Cut(b, ":")
			wd, ok3 := weekdays[w]
			if !ok1 || !ok2 || !ok3 {
				t.Fatalf("bad row %v", r)
			}
			x, ok := NthWeekdayOfMonth(atoi(ys), time.Month(atoi(ms)), wd, atoi(ks))
			if !ok {
				t.Fatalf("%v", r)
			}
			got = x.Format(layout)
		case "next_weekday_strict":
			got = NextWeekday(d(a), weekdays[b]).Format(layout)
		case "prev_weekday_strict":
			got = PrevWeekday(d(a), weekdays[b]).Format(layout)
		case "add_business_days":
			got = AddBusinessDays(d(a), atoi(b)).Format(layout)
		case "business_days_between":
			got = strconv.Itoa(BusinessDaysBetween(d(a), d(b)))
		case "days_between":
			got = strconv.Itoa(DaysBetween(d(a), d(b)))
		case "iso_week":
			y, w := d(a).ISOWeek()
			got = fmt.Sprintf("%d-W%02d", y, w)
		case "first_of_next_month":
			got = FirstOfNextMonth(d(a)).Format(layout)
		case "last_of_month":
			got = LastOfMonth(d(a)).Format(layout)
		case "easter_western":
			got = EasterWestern(atoi(a)).Format(layout)
		case "easter_orthodox":
			got = EasterOrthodox(atoi(a)).Format(layout)
		default:
			t.Fatalf("unknown op %s", op)
		}
		if got != exp {
			t.Errorf("%s(%s, %s) = %s, want %s", op, a, b, got, exp)
		}
		n++
	}
	if n < 4000 {
		t.Fatal("too few rows", n)
	}
}

func TestHebrewGolden(t *testing.T) {
	for _, r := range rows(t, "hebrew_month_starts.csv") {
		n := RD(d(r[0]))
		y, m := atoi(r[1]), atoi(r[2])
		if gy, gm, gd := HebrewFromFixed(n); gy != y || gm != m || gd != 1 {
			t.Fatalf("%s: got %d-%d-%d", r[0], gy, gm, gd)
		}
		if x, ok := FixedFromHebrew(y, m, 1); !ok || x != n {
			t.Fatalf("%s: FixedFromHebrew", r[0])
		}
		if HebrewMonthLength(y, m) != atoi(r[4]) {
			t.Fatalf("%s: length", r[0])
		}
	}
}

func TestUmmAlQuraGolden(t *testing.T) {
	for _, r := range rows(t, "hijri_umalqura_month_starts.csv") {
		n := RD(d(r[0]))
		y, m := atoi(r[1]), atoi(r[2])
		if gy, gm, gd, ok := UmmAlQuraFromFixed(n); !ok || gy != y || gm != m || gd != 1 {
			t.Fatalf("%s", r[0])
		}
		if x, ok := FixedFromUmmAlQura(y, m, 1); !ok || x != n {
			t.Fatalf("%s", r[0])
		}
	}
}

func TestJulianAndTabularGolden(t *testing.T) {
	for _, r := range rows(t, "julian_and_tabular_hijri.csv") {
		n := RD(d(r[0]))
		y, m, dd := JulianFromFixed(n)
		if fmt.Sprintf("%04d-%02d-%02d", y, m, dd) != r[1] || FixedFromJulian(y, m, dd) != n {
			t.Fatalf("julian %s", r[0])
		}
		y, m, dd = HijriTabularFromFixed(n)
		if fmt.Sprintf("%d-%02d-%02d", y, m, dd) != r[2] || FixedFromHijriTabular(y, m, dd) != n {
			t.Fatalf("tabular %s", r[0])
		}
	}
}

func TestChineseGolden(t *testing.T) {
	for _, r := range rows(t, "chinese_month_starts.csv") {
		n := RD(d(r[0]))
		c := ChineseDate{Year: atoi(r[1]), Month: atoi(r[2]), Leap: r[3] == "1", Day: 1}
		if got := ChineseFromFixed(n); got != c {
			t.Fatalf("%s: got %+v want %+v", r[0], got, c)
		}
		if x, ok := FixedFromChinese(c); !ok || x != n {
			t.Fatalf("%s: FixedFromChinese", r[0])
		}
		length := atoi(r[4])
		if last := ChineseFromFixed(n + length - 1); last.Day != length || last.Month != c.Month || last.Leap != c.Leap {
			t.Fatalf("%s: month length", r[0])
		}
	}
}

// TestConcurrentFirstUse proves the lazily built Umm al-Qura table is safe to
// initialise from many goroutines at once (run with -race). Removing the
// sync.Once in uaq() makes the race detector fail this test.
func TestConcurrentFirstUse(t *testing.T) {
	var wg sync.WaitGroup
	errs := make(chan string, 16)
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if y, m, dd, ok := UmmAlQuraFromFixed(RD(d("2026-02-18"))); !ok || y != 1447 || m != 9 || dd != 1 {
				errs <- fmt.Sprintf("got %d-%d-%d ok=%v", y, m, dd, ok)
			}
		}()
	}
	wg.Wait()
	close(errs)
	for e := range errs {
		t.Error(e)
	}
}

func TestInvalidDatesRejected(t *testing.T) {
	if _, ok := FixedFromHebrew(5786, 13, 1); ok { // 5786 is a common year: no Adar II
		t.Error("Adar II accepted in a common year")
	}
	if _, ok := FixedFromChinese(ChineseDate{Year: 2026, Month: 6, Leap: true, Day: 1}); ok {
		t.Error("nonexistent leap month accepted")
	}
	if _, ok := FixedFromUmmAlQura(1501, 1, 1); ok {
		t.Error("out-of-table year accepted")
	}
	if _, ok := NthWeekdayOfMonth(2026, time.February, time.Monday, 5); ok {
		t.Error("5th Monday of Feb 2026 accepted")
	}
}

func TestCalendarDayVsDurationAcrossDST(t *testing.T) {
	ny, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Skipf("tzdata unavailable: %v", err)
	}
	start := time.Date(2026, 3, 7, 12, 0, 0, 0, ny)
	// AddDate is wall-clock: same local time tomorrow.
	if got := start.AddDate(0, 0, 1).Format(time.RFC3339); got != "2026-03-08T12:00:00-04:00" {
		t.Error(got)
	}
	// Add(24h) is absolute elapsed time.
	if got := start.Add(24 * time.Hour).Format(time.RFC3339); got != "2026-03-08T13:00:00-04:00" {
		t.Error(got)
	}
	// "Today" in a zone: take the date in that zone, not in UTC.
	lateUTC := time.Date(2026, 11, 1, 2, 0, 0, 0, time.UTC)
	if got := Civil(lateUTC.In(ny)).Format(layout); got != "2026-10-31" {
		t.Error(got)
	}
}
