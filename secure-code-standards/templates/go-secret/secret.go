// Package secret holds credential values so they cannot be printed,
// logged, or marshaled by accident.
package secret

import (
	"encoding"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"strings"
)

// Placeholder is what every formatting path prints in place of the value.
const Placeholder = "[REDACTED]"

// Secret is a credential. Its zero value is empty and reports IsZero.
// Secret is a value type; copies share no mutable state. Every standard
// formatting, JSON, text and slog path prints Placeholder. Call Reveal at
// the single point where the raw value is needed.
type Secret struct{ v string }

// New wraps raw. Callers should obtain raw from FromFile or FromEnv.
func New(raw string) Secret { return Secret{v: raw} }

// Reveal returns the raw value. Never pass the result to logs, errors,
// fmt verbs, or long-lived structures.
func (s Secret) Reveal() string { return s.v }

// IsZero reports whether no value is set.
func (s Secret) IsZero() bool { return s.v == "" }

func (Secret) String() string   { return Placeholder }
func (Secret) GoString() string { return "secret.Secret{" + Placeholder + "}" }

// Format catches every verb (%v %+v %#v %s %q %x %d ...), including ones
// that would otherwise reflect over the unexported field.
func (Secret) Format(f fmt.State, _ rune) { _, _ = io.WriteString(f, Placeholder) }

func (Secret) MarshalText() ([]byte, error) { return []byte(Placeholder), nil }
func (Secret) MarshalJSON() ([]byte, error) { return json.Marshal(Placeholder) }

// LogValue makes slog print the placeholder, even under slog.Any/Group.
func (Secret) LogValue() slog.Value { return slog.StringValue(Placeholder) }

var (
	_ fmt.Stringer           = Secret{}
	_ fmt.GoStringer         = Secret{}
	_ fmt.Formatter          = Secret{}
	_ json.Marshaler         = Secret{}
	_ encoding.TextMarshaler = Secret{}
	_ slog.LogValuer         = Secret{}
)

// Sentinel errors. None of them (or their wrappers) contain the value.
var (
	ErrNotSet      = errors.New("secret not set")
	ErrEmpty       = errors.New("secret is empty")
	ErrPlaceholder = errors.New("secret looks like a placeholder")
	ErrTooLarge    = errors.New("secret source too large")
	ErrPermissions = errors.New("secret file permissions too open (require 0600 or stricter)")
	ErrNotRegular  = errors.New("secret source is not a regular file")
)

const maxSecretBytes = 64 << 10 // a credential is never this big; reject blobs

// FromFile reads a credential from path. It opens first and checks the open
// handle (no stat/open race), requires a regular file, rejects group/other
// access on Unix-like systems, bounds the read, trims surrounding
// whitespace, and rejects empty or placeholder content. Errors name the path
// and the failed check, never the content.
func FromFile(path string) (Secret, error) {
	if path == "" {
		return Secret{}, ErrNotSet
	}
	f, err := os.Open(path)
	if err != nil {
		return Secret{}, fmt.Errorf("open secret file %q: %w", path, err)
	}
	defer f.Close() // read-only handle; close error not material

	fi, err := f.Stat()
	if err != nil {
		return Secret{}, fmt.Errorf("stat secret file %q: %w", path, err)
	}
	if !fi.Mode().IsRegular() {
		return Secret{}, fmt.Errorf("secret file %q: %w", path, ErrNotRegular)
	}
	if fi.Mode().Perm()&0o077 != 0 && !permissionsNotEnforced() {
		return Secret{}, fmt.Errorf("secret file %q has mode %04o: %w", path, fi.Mode().Perm(), ErrPermissions)
	}
	b, err := io.ReadAll(io.LimitReader(f, maxSecretBytes+1))
	if err != nil {
		return Secret{}, fmt.Errorf("read secret file %q: %w", path, err)
	}
	if len(b) > maxSecretBytes {
		return Secret{}, fmt.Errorf("secret file %q: %w", path, ErrTooLarge)
	}
	return validate(strings.TrimSpace(string(b)), path)
}

// FromEnv reads a credential from the environment variable name.
func FromEnv(name string) (Secret, error) {
	raw, ok := os.LookupEnv(name)
	if !ok {
		return Secret{}, fmt.Errorf("environment variable %s: %w", name, ErrNotSet)
	}
	return validate(strings.TrimSpace(raw), "$"+name)
}

// Resolve applies the standard precedence: an explicit file path wins, then
// the file named by <ENV>_FILE, then the environment variable itself. There
// is deliberately no default and no fallback literal: if nothing supplies a
// value, the error says which inputs were consulted.
func Resolve(filePath, envName string) (Secret, error) {
	if filePath != "" {
		return FromFile(filePath)
	}
	if p := os.Getenv(envName + "_FILE"); p != "" {
		return FromFile(p)
	}
	if _, ok := os.LookupEnv(envName); ok {
		return FromEnv(envName)
	}
	return Secret{}, fmt.Errorf("no credential supplied: set --%s-file, %s_FILE or %s: %w",
		strings.ToLower(strings.ReplaceAll(envName, "_", "-")), envName, envName, ErrNotSet)
}

func validate(raw, src string) (Secret, error) {
	if raw == "" {
		return Secret{}, fmt.Errorf("secret from %s: %w", src, ErrEmpty)
	}
	if looksLikePlaceholder(raw) {
		return Secret{}, fmt.Errorf("secret from %s: %w", src, ErrPlaceholder)
	}
	return Secret{v: raw}, nil
}

func looksLikePlaceholder(s string) bool {
	switch strings.ToLower(s) {
	case "changeme", "change-me", "replace-me", "your-api-key", "your_api_key",
		"xxx", "todo", "tbd", "none", "null", "<redacted>", "[redacted]":
		return true
	}
	return false
}
