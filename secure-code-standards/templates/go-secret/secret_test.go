package secret

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const raw = "fake-credential-for-tests-0123456789"

type cfg struct {
	Name string
	Key  Secret
}

func TestNeverPrints(t *testing.T) {
	s := New(raw)
	c := cfg{"a", s}
	outs := []string{
		fmt.Sprint(s), fmt.Sprintf("%v %+v %#v %s %q %x %d", s, s, s, s, s, s, s),
		fmt.Sprintf("%v %+v %#v", c, c, c), fmt.Sprintf("%v", &c),
	}
	b, _ := json.Marshal(c)
	outs = append(outs, string(b))
	var buf bytes.Buffer
	slog.New(slog.NewJSONHandler(&buf, nil)).Info("x", "k", s, slog.Any("c", c))
	slog.New(slog.NewTextHandler(&buf, nil)).Info("x", "k", s)
	outs = append(outs, buf.String())
	for i, o := range outs {
		if strings.Contains(o, raw) || strings.Contains(o, "for-tests") {
			t.Fatalf("output %d leaked: %q", i, o)
		}
	}
}

func TestFromFile(t *testing.T) {
	d := t.TempDir()
	good := filepath.Join(d, "k")
	os.WriteFile(good, []byte(" "+raw+"\n"), 0o600)
	s, err := FromFile(good)
	if err != nil || s.Reveal() != raw {
		t.Fatal(err)
	}
	open := filepath.Join(d, "o")
	os.WriteFile(open, []byte(raw), 0o644)
	os.Chmod(open, 0o644)
	if _, err := FromFile(open); !errors.Is(err, ErrPermissions) || strings.Contains(err.Error(), raw) {
		t.Fatalf("want ErrPermissions without value, got %v", err)
	}
	empty := filepath.Join(d, "e")
	os.WriteFile(empty, []byte("\n"), 0o600)
	if _, err := FromFile(empty); !errors.Is(err, ErrEmpty) {
		t.Fatal(err)
	}
	ph := filepath.Join(d, "p")
	os.WriteFile(ph, []byte("changeme"), 0o600)
	if _, err := FromFile(ph); !errors.Is(err, ErrPlaceholder) {
		t.Fatal(err)
	}
	if _, err := FromFile(d); !errors.Is(err, ErrNotRegular) {
		t.Fatal(err)
	}
}

func TestResolveFailsClosed(t *testing.T) {
	t.Setenv("API_KEY", "")
	os.Unsetenv("API_KEY")
	os.Unsetenv("API_KEY_FILE")
	_, err := Resolve("", "API_KEY")
	if !errors.Is(err, ErrNotSet) {
		t.Fatal(err)
	}
	t.Log(err)
	t.Setenv("API_KEY", raw)
	s, err := Resolve("", "API_KEY")
	if err != nil || s.Reveal() != raw {
		t.Fatal(err)
	}
}
