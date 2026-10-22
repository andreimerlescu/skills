# Application boundaries and security

Load when the task touches HTTP clients or servers, files and paths, `database/sql`, JSON, subprocesses, CLIs, authentication, secrets, crypto, or any untrusted input. Rules `R3` and `R5` in SKILL.md are the summary.

## 1. Trust-boundary inventory

Before handling external input, write down: source, identity/authorization context, expected grammar, size and rate budget, and where it flows (storage, logs, network, subprocesses). Validate once, at the boundary, consistently.

## 2. HTTP clients

- Build one configured `http.Client` (and `Transport`) per destination policy and reuse it. Never create a client or transport per request. Avoid `http.DefaultClient` for production I/O: it has no timeout.
- Configure dial, TLS handshake, response-header and idle timeouts. `Client.Timeout` covers the **whole** exchange including body reads; for streaming, use per-request contexts instead.
- `http.NewRequestWithContext` always. Validate scheme and host for attacker-influenced URLs (SSRF). Control redirects (`CheckRedirect`) when credentials are attached.
- Always `resp.Body.Close()`. In Go 1.27, closing an HTTP/1 body drains a bounded amount automatically for connection reuse, so manual drain loops are usually unnecessary.
- Check status before decoding. Bound body size. Reject trailing data when the protocol says one JSON value.
- Build `host:port` with `net.JoinHostPort` (vet's `hostport` check flags `Sprintf`).

```go
// FetchJSON GETs endpoint and decodes exactly one JSON value of at most
// maxBody bytes from a 200 response. The caller owns client configuration
// (timeouts, redirects) and must validate endpoint against its SSRF policy.
func FetchJSON[T any](ctx context.Context, c *http.Client, endpoint string, maxBody int64) (T, error) {
	var zero T
	if c == nil {
		return zero, errors.New("nil http client")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return zero, fmt.Errorf("build request: %w", err)
	}
	resp, err := c.Do(req)
	if err != nil {
		return zero, fmt.Errorf("GET: %w", err)
	}
	defer resp.Body.Close() // read side; close error not material

	if resp.StatusCode != http.StatusOK {
		return zero, fmt.Errorf("GET: unexpected status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBody+1))
	if err != nil {
		return zero, fmt.Errorf("read body: %w", err)
	}
	if int64(len(body)) > maxBody {
		return zero, fmt.Errorf("response exceeds %d bytes", maxBody)
	}

	dec := json.NewDecoder(bytes.NewReader(body))
	var out T
	if err := dec.Decode(&out); err != nil {
		return zero, fmt.Errorf("decode: %w", err)
	}
	var extra json.RawMessage
	if err := dec.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return zero, errors.New("decode: multiple JSON values")
		}
		return zero, fmt.Errorf("decode trailing data: %w", err)
	}
	return out, nil
}
```

The limit applies to the decoded (decompressed) body. Endpoint allowlisting, auth, content-type and redirect policy are the caller's job. A typed, endpoint-specific client is often clearer than a generic helper.

## 3. HTTP servers

- Explicit `http.Server`: `ReadHeaderTimeout` always; `ReadTimeout`, `WriteTimeout`, `IdleTimeout` according to streaming needs; `MaxHeaderBytes`; `MaxHeaderValueCount` (1.27) if defaults are wrong for you.
- Per-endpoint body limits with `http.MaxBytesReader`, plus validation.
- Validate fully before writing a success status. 4xx for client errors, 5xx for server faults; consistent content types.
- Middleware only for cross-cutting concerns (request ID, auth, logging, metrics, panic isolation). Business logic lives in handlers/services.
- Request-boundary panic recovery may isolate one request; it must log safely and must not hide corrupted shared state.
- `net/http/pprof`, `/debug/pprof/goroutineleak` (1.27), metrics and admin routes stay on a private listener or behind auth. Tracebacks now include goroutine labels: keep labels free of secrets.
- Trust `X-Forwarded-For`/`Forwarded` only from configured proxies.
- Use `http.CrossOriginProtection` (1.25+) for browser-facing state-changing endpoints instead of hand-rolled CSRF checks where it fits.

## 4. Files and paths

- `filepath` for OS paths, `path` for slash-separated URL/protocol paths.
- **Confinement:** `filepath.Clean` + prefix checks do not stop symlink escapes or TOCTOU races. Use `os.Root` / `os.OpenInRoot` (1.24+; more methods in 1.25) for access under an untrusted-name directory.
- `os.OpenFile` with deliberate flags and permissions. Bounded reads for untrusted input.
- Persistence must survive a crash mid-write: atomic replace (see errors-lifecycle.md), append logs with checksums, tests for truncated files.

## 5. `database/sql`

- One `*sql.DB` per database, reused. Set `SetMaxOpenConns`, `SetMaxIdleConns`, `SetConnMaxLifetime` from real limits.
- Always the `Context` variants. `defer rows.Close()`; check `rows.Err()` after the loop; check every `Scan`.
- Placeholders for values. Identifiers cannot be parameterized: allowlist them. Never `fmt.Sprintf` user input into SQL.
- Bound result sets (pagination), avoid N+1 queries.
- Document isolation level and retry policy for serialization failures. In-process mutexes do not protect cross-process data.
- Instrument pool use and latency without logging credentials or sensitive parameters.

## 6. JSON, text, time, numbers

- Typed request/response structs with explicit tags; `map[string]any` only for truly dynamic shapes.
- Decide whether missing and `null` differ; know how `omitempty`, pointers, nil vs empty slices affect the wire.
- `DisallowUnknownFields` only where the protocol is strict; forward-compatible protocols should not reject unknown fields.
- Go 1.27: `encoding/json` runs on the v2 engine with v1 behavior, but **error strings changed**. `encoding/json/v2` rejects invalid UTF-8 and duplicate names by default. Do not switch packages without compatibility tests on real fixtures.
- Money and token amounts: integers in smallest units or a vetted decimal type, never `float64`. Use `Decoder.UseNumber` when precision matters in untyped decoding.
- `time.Time` for instants, `time.Duration` for intervals; compare instants with `Equal`; persist in UTC.
- `net/url` for URLs and queries; `url.URL.Clone` (1.27) for deep copies.
- `crypto/rand` (or `uuid` package, 1.27) for identifiers that must be unguessable; `math/rand/v2` only for non-security randomness.

## 7. CLI, signals, subprocesses

- Thin `main` → `run() error` (see errors-lifecycle.md).
- `exec.CommandContext(ctx, name, args...)` with an argument slice. Never `sh -c` with interpolated input.
- Bound child output; define what cancellation does to the child.
- Diagnostics to stderr; stable machine-readable output when it is a contract; meaningful exit codes; redacted settings.

## 8. Security defaults (R5)

- Least privilege for files, processes and credentials; no root unless required.
- Never log: passwords, API keys, bearer tokens, cookies, auth headers, private keys, signing seeds, raw payment data, personal secrets.
- Use vetted crypto and TLS from the standard library or reviewed modules. Never invent crypto, password hashing, JWT verification or key storage.
- `subtle.ConstantTimeCompare` for secret comparisons.
- Allowlist URLs, file roots, CLI options and plugin loading when input is untrusted.
- Rate-limit expensive endpoints; bound reads, writes, connections, queues, recursion depth and decompression output.
- Authentication is not authorization: check ownership on every resource access.
- Audit-log security-relevant events with redaction.
- Run `govulncheck ./...` after dependency or toolchain changes and report reachable findings.

### Sensitive concurrency

- Never share signers, nonce/sequence allocators, key stores, or balances across goroutines without a written invariant design.
- A locked map is not an accounting system: uniqueness, sequencing, reservations and idempotency belong in a durable transactional layer.
- Authorization caches need race-safe revocation; test revoked credentials with requests in flight.
- Zeroing a Go byte slice does not guarantee the secret is gone (copies, GC, runtime). Use vetted key-management APIs; consider `runtime/secret` only after reading its docs.

## 9. Supply chain and builds

- Record `go version`, module graph and commit SHA for each artifact.
- `go mod verify`; `govulncheck`; pinned tool versions; pinned CI actions.
- No `curl | sh` in setup docs. Do not run unreviewed `go:generate` commands.
- Protect CI secrets; never run untrusted PR code with write tokens.
- Do not claim reproducible builds without demonstrating identical output.
