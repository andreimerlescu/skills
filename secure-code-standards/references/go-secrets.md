# Go: secrets, flags, embedding, logging

Load for any Go task that reads configuration, flags, env, files, logs, builds binaries, or touches credentials. Rules `S1`–`S8` in SKILL.md are the summary. Pair with `go-engineering-standards/references/boundaries-security.md`.

## 1. The three Go mistakes that leak secrets

### 1.1 `//go:embed` of a secret-bearing file

`//go:embed` copies file bytes into the compiled binary. `strings ./app | grep sk-` recovers them. Anyone who receives the binary, or the container image, or a crash dump, has the key.

```go
// WRONG: bakes keys.txt into the binary and makes it a flag default.
//go:embed keys.txt
var keys string

var apiKey = flag.String("api-key", strings.TrimSpace(keys), "API key")
```

Why it is doubly bad: flag defaults are printed by `-h`/`--help` (`flag.PrintDefaults`), by `flag.VisitAll`, and by any usage dump, so the key is disclosed even to someone who never reads the binary.

Rules:
- Never `embed` a file you have not classified. Embed only specific, named, non-sensitive assets (templates, migrations, static docs).
- Never embed with a directory pattern (`//go:embed assets/*`, `//go:embed all`) if the directory could contain `.env`, `*.pem`, `*.key`, `keys.txt`, `secrets.*`, or a credentials file. Go's `embed` skips files beginning with `.` or `_` only for directories without the `all:` prefix; do not rely on that as a safety measure.
- If a task says "the sample key is in a text file", that file is **input data for the developer**, not an asset for the program.

### 1.2 Secret as flag default or `os.Getenv` fallback

```go
// WRONG
key := flag.String("api-key", "sk-live-...", "API key")
tok := cmp.Or(os.Getenv("TOKEN"), "dev-token")
```

Both put a usable credential in source or binary. Correct: no default; resolve at runtime; fail closed (§3).

### 1.3 `-ldflags -X` and `go generate` secrets

`-ldflags "-X main.apiKey=$KEY"` stores the key in the binary's data section and in the build log. `go generate` steps that write the key into a generated `.go` file commit it to the tree. Neither is an acceptable injection channel.

## 2. A redacting `Secret` type (copy this; adapt the package name)

Every secret in memory is held in a type that cannot print itself by accident. Single point of use calls `Reveal()`.

```go
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
```

`permissionsNotEnforced()` is a build-tagged pair (`perm_unix.go`, `perm_windows.go`). A tested, ready-to-copy version of this package, with its tests, is in `templates/go-secret/`. Copy the directory, change the package path, and run its tests (`go test ./...`).

Notes:
- The `Format` method means `fmt.Printf("%+v", cfg)` on a struct holding a `Secret` field prints the placeholder, because `fmt` calls `Format` on the field. Reflection-based dumpers (`spew`, `go-cmp` diffs, `reflect`) can still read the unexported field; do not feed secret-bearing structs to them in logs or test failure output.
- JSON **unmarshalling** into `Secret` is not provided on purpose. Parse the file or env, then construct with `New`. If a config file format must carry a secret, it should carry a *path* (`api_key_file`) instead.
- Zeroing the string does not erase it (immutable, copied by the runtime). Do not claim memory scrubbing. Minimize lifetime and copies instead.

## 3. Flags: take a path, never a value, never a default

```go
package main

import (
	"errors"
	"flag"
	"fmt"
	"os"

	"example.com/yourmod/secret"
)

func run(args []string, stderr *os.File) error {
	fs := flag.NewFlagSet("app", flag.ContinueOnError)
	fs.SetOutput(stderr)
	// The flag value is a PATH. Its default is empty. Help text names the env
	// fallbacks and never shows a credential.
	keyFile := fs.String("api-key-file", "", "path to a 0600 file holding the API key (or set API_KEY_FILE or API_KEY)")
	if err := fs.Parse(args); err != nil {
		return err
	}

	apiKey, err := secret.Resolve(*keyFile, "API_KEY")
	if err != nil {
		return fmt.Errorf("configure api key: %w", err) // names inputs, not content
	}
	return serve(apiKey)
}

func serve(key secret.Secret) error {
	// Single point of use. Reveal() only when building the header.
	_ = key.Reveal()
	return nil
}

func main() {
	if err := run(os.Args[1:], os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		if errors.Is(err, secret.ErrNotSet) {
			os.Exit(2)
		}
		os.Exit(1)
	}
}
```

Checklist for any flag/option:
- A flag that names a credential (`key`, `token`, `password`, `secret`, `auth`) is **path-valued** (`--api-key-file`), or reads stdin (`--api-key-stdin`). It is never `--api-key=VALUE`.
- The default is the empty string for a path flag and never a path to a file inside the repo or module that contains a real secret.
- `flag.PrintDefaults` output is part of the disclosure surface. Run `-h` and read the actual output before reporting.
- If a library (cobra/viper/urfave) is already in the repo, the same rules apply: no `SetDefault` for secrets, no `BindEnv` with a fallback, no `viper.Debug()`/`AllSettings()` in logs, `cobra` flags with `MarkHidden` are still disclosed in source.

## 4. Logging and errors in Go

- Use `log/slog` with typed attributes. Secrets only ever appear as `secret.Secret` (prints `[REDACTED]`). Never `slog.String("key", s.Reveal())`.
- Never `log.Printf("%+v", cfg)`, `fmt.Printf("%#v", client)`, `slog.Any("req", httpReq)`. `*http.Request` carries `Authorization`, `Cookie`, and URL query secrets. Use `httputil.DumpRequestOut` only with a redactor, and never in production.
- Wrap errors without re-embedding the URL when it can contain credentials. `url.Error` includes the full URL: strip userinfo and secret query params (`u.User = nil`, delete keys like `token`, `api_key`, `signature`) before logging. Go's `*url.URL.Redacted()` hides only the password in userinfo, not query secrets.
- A `panic` message and stack trace print argument values only for types with exposed formatting; keep secrets in `Secret` so a crash cannot print them.
- Build info: `debug.ReadBuildInfo()` and `go version -m binary` expose `-ldflags` and VCS metadata. Do not put secrets in either, and consider `-trimpath` for released binaries so local paths do not leak.

## 5. HTTP clients: where the secret goes

- Credentials go in the `Authorization` header (or the provider's header), set per request from `Reveal()`, never in the query string (it lands in server logs, proxies, `url.Error`).
- If you must follow redirects with credentials, set `CheckRedirect` to drop `Authorization` on cross-host redirects (Go already strips it on cross-domain redirects; keep that behavior and test it).
- `InsecureSkipVerify: true` is never acceptable outside a unit test of your own TLS config, and never with a credential on the wire.
- One client per destination policy, with timeouts, as in `go-engineering-standards`. A client with a token-injecting `RoundTripper` must clone the request (`req.Clone(ctx)`) before adding headers, because `RoundTripper` must not modify the caller's request.

```go
// authTransport adds a bearer token to each outgoing request. It clones the
// request so the caller's *http.Request is not mutated, as RoundTripper requires.
type authTransport struct {
	base  http.RoundTripper
	token secret.Secret
}

func (t authTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	r2 := r.Clone(r.Context())
	r2.Header.Set("Authorization", "Bearer "+t.token.Reveal())
	return t.base.RoundTrip(r2)
}
```

## 6. Files that the program writes

- Create with `os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)`, directories `0o700`. Do not rely on umask.
- Temp files holding sensitive data: `os.CreateTemp` already uses mode 0600; remove on all paths; do not place in shared directories you do not own.
- Never write a secret to a file whose name or location the user did not request. Never write one into the working tree of a git repository without confirming it is ignored (`git check-ignore -v <path>`).

## 7. Constant-time, randomness, hashing

- Compare secrets and MACs with `subtle.ConstantTimeCompare` / `hmac.Equal`, never `==` or `bytes.Equal`.
- Tokens, session IDs, nonces, API keys you generate: `crypto/rand` (`rand.Text` exists in newer Go; check `go doc crypto/rand.Text` before using). Never `math/rand`.
- Passwords you must store: `golang.org/x/crypto/argon2` (`IDKey`) or `bcrypt`/`scrypt` with per-user salt and tuned cost. Never SHA-256/MD5 for passwords. Never invent crypto.

## 8. Verification commands for Go

```bash
go doc flag.PrintDefaults                    # help text is part of the disclosure surface
go build -trimpath -o /tmp/app ./cmd/app
/tmp/app -h 2>&1 | tee /tmp/help.txt         # then grep for secret-like content
strings -a /tmp/app | grep -F -f <(printf '%s\n' "$FRAGMENT")   # fragment = unique 8+ chars of the secret, from your shell only
go version -m /tmp/app                       # build settings, ldflags, vcs
govulncheck ./...                            # after dependency/toolchain changes
bash <skill-dir>/scripts/secret-scan.sh --artifact /tmp/app
```

When searching an artifact for the literal secret, take the fragment from the secret file inside the shell command (for example, `-f <(tr -d '\n' < keys.txt)`), so the value never enters your own transcript.
