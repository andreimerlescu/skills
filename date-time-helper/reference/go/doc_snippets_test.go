package datecal

import (
	"testing"
	"time"
)

// TestGoMDSnippets compiles and checks the inline examples in reference/go.md.
func TestGoMDSnippets(t *testing.T) {
	d := Date(2026, time.January, 5)
	checks := map[string]time.Time{
		"2026-04-05": d.AddDate(0, 0, 90),
		"2026-02-05": AddMonths(d, 1),
		"2026-02-01": FirstOfNextMonth(d),
		"2026-01-31": LastOfMonth(d),
		"2026-03-02": Date(2026, time.February, 30), // silent normalisation
	}
	for want, got := range checks {
		if got.Format(layout) != want {
			t.Errorf("got %s want %s", got.Format(layout), want)
		}
	}
	if lf, ok := NthWeekdayOfMonth(2026, time.November, time.Friday, -1); !ok || lf.Format(layout) != "2026-11-27" {
		t.Error(lf)
	}
	if Date(2026, 13, 1).Format(layout) != "2027-01-01" || Date(2026, 3, 0).Day() != 28 {
		t.Error("normalisation idioms")
	}
	start, end := FirstOfMonth(d), FirstOfNextMonth(d)
	x := Date(2026, time.January, 31)
	if !(!x.Before(start) && x.Before(end)) {
		t.Error("half-open month filter")
	}
	if y, w := d.ISOWeek(); y != 2026 || w != 2 {
		t.Error(y, w)
	}
}
