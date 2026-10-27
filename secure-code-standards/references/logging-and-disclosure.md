# Logging, errors and information disclosure

Load for any task that logs, formats errors, panics, traces, emits metrics, exposes debug endpoints, or prints test output. Rule `S5` is the summary.

## 1. Disclosure surfaces (check each one, every time)

Standard output and error · log files and aggregators · error strings returned to callers · HTTP error bodies · panic messages and stack traces · `--help`/`--version`/completions · config and state dumps · metrics labels and trace attributes · `/debug/*` and pprof · crash dumps · CI logs · test failure output (`t.Errorf("%+v", cfg)`) · shell history (command lines) · `ps` · container `inspect` and image history · build logs · git history · editor/AI-agent transcripts.

## 2. What must never be emitted

Passwords, API keys, bearer/refresh/session tokens, cookies, `Authorization` and `Proxy-Authorization` headers, `Set-Cookie`, private keys, signing seeds, connection strings with credentials, full card/bank numbers, government IDs, and personal data not required for the operation. Also avoid emitting secret *derivatives* that let an attacker confirm a guess: unsalted hashes, lengths of short secrets, and the full first/last characters.

When identification of a credential is needed in logs, use a **non-reversible fingerprint** distinct from the secret: the first 4–6 hex chars of an HMAC of the secret under a log-only key, or the provider's key ID / label. Never the first characters of the secret itself beyond a provider-defined prefix such as `sk-`.

## 3. Rules

- **Redact at the type**, not at the call site (SKILL.md S6). A redacting type protects every future log line; a "remember to mask it" convention protects none.
- **Structured logging with allowlisted fields.** Log named attributes you chose. Do not log whole requests, responses, configs, environments or error-wrapped URLs.
- **Errors carry context, not credentials.** Wrap with operation and identifier (`fmt.Errorf("fetch widget %q: %w", id, err)`). When the cause is a URL error, strip userinfo and secret query params first.
- **Do not echo input verbatim into errors** shown to users when it could contain someone else's secret. Truncate and quote untrusted input in logs (`%q`) to stop log injection via newlines and control characters.
- **Separate user-facing from operator-facing detail.** Return a stable, generic message and an error ID to clients; log the detailed cause server-side. Do not leak stack traces, SQL, file paths, library versions or internal hostnames in responses.
- **Panics**: recover at the request/worker boundary, log type and stack **without** argument values, return a generic 500. Do not print panic values that could be formatted structs holding secrets.
- **Authentication failures** log the user/key ID and reason code, never the submitted password/token. Use the same message for "no such user" and "wrong password" to avoid enumeration.
- **Metrics and traces**: label values are low-cardinality identifiers, never user input or secrets. Scrub `http.url` attributes of query strings.
- **Debug endpoints** (`pprof`, `expvar`, `/debug/vars`, health pages with build info) are off by default, bound to loopback or an admin listener, and authenticated. `expvar` can publish `os.Args` and `os.Environ`-derived data: remove `cmdline` exposure or do not import it.
- **Verbose/debug logging** must not weaken redaction. "Debug" is not a licence to print secrets; it is a licence to print more non-sensitive detail.

## 4. HTTP specifics

- Redact headers before logging: `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, `X-Auth-Token`, `X-Amz-Security-Token`, `X-Csrf-Token`, plus any custom header you define.
- Do not log request or response bodies by default. If you must, allowlist fields and cap size.
- Access logs record the path **without** query string, or with an allowlist of safe keys.
- Do not accept credentials in query strings (they leak via logs, `Referer`, history, proxies). If a third party forces it, redact aggressively and say so in the report.

## 5. Tests and logs

- Add a "no leak" test for any new logging path of sensitive types: construct the object with a **sentinel** value (`"SENTINEL-do-not-print-0123"`), log/format/marshal it every way the program can, and assert the sentinel never appears. Keep the sentinel obviously fake and unmatched by secret-scan patterns.
- Test failure messages must not print secret-bearing structs. Use `t.Errorf("config invalid: %v", err)` with sanitized errors, not `%+v` of the config.
- Golden files and recorded HTTP fixtures (VCR/`httptest` recordings) must be scrubbed of auth headers, cookies, and tokens before commit.

## 6. Verify

Run the program through success, failure, missing-secret, bad-secret, panic and `--help` paths with a sentinel configured, capture stdout+stderr+log files, and `grep -F` for the sentinel. Quote the command and the zero-match result.
