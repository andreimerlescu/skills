# Application security: boundaries, input, auth, crypto

Load for code that accepts external input, talks over a network, runs subprocesses, queries a database, renders templates, parses untrusted data, authenticates users, or uses cryptography. Rule `S9` is the summary. Go-specific depth is in `go-engineering-standards/references/boundaries-security.md`; this file is language-neutral and covers the decisions agents most often get wrong.

## 1. Threat-model in five lines (write them in the plan)

1. **Assets**: what is worth stealing or corrupting (credentials, user data, money, availability, code execution).
2. **Entry points**: every place bytes arrive (HTTP, CLI args, env, files, queues, webhooks, deserialized blobs, third-party API responses, the filesystem).
3. **Trust levels**: who is allowed to call each entry point; what is attacker-controlled.
4. **Sinks**: where data lands (SQL, shell, filesystem paths, templates, logs, redirects, outbound requests, memory).
5. **Failure mode**: what happens on malformed, huge, slow, repeated, or concurrent input.

## 2. Injection: separate code from data at every sink

| Sink | Safe pattern | Never |
| --- | --- | --- |
| SQL | parameterized queries/prepared statements; allowlist identifiers (table, column, sort) | string concatenation / `Sprintf` of input |
| Shell/subprocess | argv list, no shell (`exec.Command(name, args...)`, `subprocess.run([...])`) | `sh -c "<interpolated>"`, `shell=True`, `os.system` |
| Filesystem paths | resolve under a fixed root with confinement APIs (`os.Root`, `openat2`, realpath + prefix check + no symlink follow); generated filenames | joining user input into paths; trusting `..` filtering |
| HTML | context-aware auto-escaping templates (`html/template`, framework defaults); CSP | building HTML with string concat; `innerHTML`/`template.HTML` of input |
| URLs/redirects | allowlist hosts/schemes; parse then compare; relative-only redirects | open redirects; `url.Parse` then fetch without a policy (SSRF) |
| Headers/logs | strip CR/LF; quote untrusted values | writing raw input to headers or log lines |
| Deserialization | typed schemas; size/depth limits; no object-graph deserializers on untrusted data (`pickle`, Java native, `yaml.load` unsafe) | decoding into `interface{}`/`Object` then trusting shape |
| Regex | linear-time engines or bounded input | user-supplied patterns; nested quantifiers on untrusted input (ReDoS) |
| XML | disable external entities and DTDs | default parsers on untrusted XML |

## 3. Validate at the boundary, bound everything

- Validate once at the edge into a typed value; inside the program, types carry the guarantee.
- **Allowlist** over blocklist. Define the grammar (charset, length, range, enum).
- Bound sizes, counts, depth, time and rate: request bodies, uploads, decompressed output (zip bombs), JSON nesting, pagination, retries, concurrent connections, per-user and global.
- Reject, do not "fix up" ambiguous input (double-encoding, mixed Unicode normalization, duplicate JSON keys, header smuggling).
- Treat data from your own database, queue, or an upstream service as untrusted at the sink; stored XSS and second-order injection come from "trusted" storage.

## 4. Outbound requests and SSRF

When the server fetches a URL that influences, even partly, from input: allowlist scheme (`https`) and host; resolve DNS and **verify the IP** is not loopback/link-local/private/metadata (`169.254.169.254`, `fd00::/8`) at connect time (dial control hook) to defeat DNS rebinding and redirects; limit redirects; limit response size and time; do not forward the caller's credentials.

## 5. Authentication and authorization

- Authentication ≠ authorization. Check **ownership/permission on every object access** (IDOR/BOLA), server-side, deny by default.
- Use vetted libraries and standards (OIDC/OAuth2, WebAuthn, session frameworks). Do not invent login, session, password reset or JWT verification.
- JWT: pin algorithm and key; verify `exp`, `nbf`, `aud`, `iss`; reject `alg: none`; never use the token's own header to choose the key type.
- Passwords: Argon2id (or bcrypt/scrypt) with per-user salt and tuned cost; constant-time comparison; rate limit and lock out; no password in logs; breach-password checks where appropriate.
- Sessions: random 128+ bit IDs from the CSPRNG; `HttpOnly`, `Secure`, `SameSite`; rotate on privilege change; server-side invalidation; CSRF protection for cookie-authenticated state changes.
- API keys you issue: show once, store only a hash (SHA-256 of a high-entropy key is acceptable; the key is not a password), include a prefix/ID for lookup, support revocation and rotation, scope them.
- Compare secrets and MACs in constant time. Add rate limiting and uniform responses to resist enumeration and timing oracles.

## 6. Cryptography

- Use the platform's high-level, vetted primitives: AES-GCM or ChaCha20-Poly1305 via AEAD APIs; Ed25519/ECDSA P-256 signatures; HKDF; `crypto/rand`/`secrets`/`SecureRandom`.
- **Never** invent crypto, use ECB, reuse nonces/IVs with the same key, roll your own KDF, use MD5/SHA-1 for security, use `math/rand`/`random` for tokens, hardcode keys or IVs, or compare MACs with `==`.
- TLS: verification on, modern minimum version (1.2+, prefer 1.3), no `InsecureSkipVerify`/`verify=False`/`rejectUnauthorized:false` outside a test of your own transport, certificate pinning only with a rotation plan.
- Keys: generated with a CSPRNG, stored in a KMS/HSM/secret manager or protected file, never in source, with a rotation plan and distinct keys per purpose and environment.
- Do not claim memory zeroization works in garbage-collected runtimes; minimize secret lifetime and copies.

## 7. Resource safety (DoS is a security bug)

Timeouts on every network call and server read; bounded worker pools and queues; context cancellation; backpressure; circuit breakers for dependencies; per-client rate limits; max concurrent expensive operations; bounded memory per request. See `go-engineering-standards` rules R2–R3.

## 8. Privacy by default

Collect the minimum personal data; keep it out of logs and URLs; set retention; encrypt at rest and in transit where sensitive; make deletion possible; never ship real customer data in fixtures. Anonymize or synthesize test data.

## 9. Review prompts for any diff

Where does each new external byte flow? What is the worst thing an attacker-controlled value can do at its sink? What does an unauthenticated caller reach? What if the request is 1000× larger, 1000× more frequent, or concurrent with itself? What is logged? What does the error tell an attacker?
