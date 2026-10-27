---
name: security-posture
description: Senior-level secrets handling for software that consumes or manages secrets in 1Password, Keeper, Bitwarden Secrets Manager, AWS Secrets Manager, OCI Vault, GCP Secret Manager, Azure Key Vault, HashiCorp Vault, Infisical, Doppler, or Akeyless. Use when writing, reviewing, testing, or operating code, CI/CD, or infrastructure that creates, reads, updates, deletes, rotates, injects, or logs around secrets, in Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, or C.
---

![Unique](https://counthis.app/github?repository=andreimerlescu/skills&label=Unique) ![Visitors](https://counthis.app/g/qyjy5vwjtjgbjfzy)

# Security posture for secrets consumers

## Objective

Make the agent behave like a senior security engineer whenever software touches secrets as an **application consumer**: it picks the right identity and access model, calls the provider's API correctly in the project's language, keeps secret values out of every place they leak from (argv, environment, logs, errors, files, images, state, memory dumps), designs for rotation and revocation from day one, verifies its work without exposing values, and can explain each decision with a source.

This skill is the entry point. It holds the rules that apply to every provider and routes to two documents per provider:

- **CRUD guide** (`references/crud/…`): exact, verified calls for create/read/update/delete, with a complete program in Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, and C, plus CLI snippets, error tables, and a source register.
- **Engineering hygiene guide** (`references/engineering/…`): how to build software around that provider — consumption patterns, identity design, code structure, lifecycle, logging, testing, CI/CD, incident response, review checklist, anti-patterns.

## When to use

Use this skill when the task involves any of: reading a secret at startup or runtime; writing, rotating, or deleting a secret; designing access (roles, policies, service accounts, machine identities); CI/CD secret delivery; Kubernetes/serverless secret injection; reviewing code or logs for secret exposure; incident response for a leaked credential; or choosing between secrets providers.

## How to use this package

1. **Identify the provider and the language** from the repository (dependencies, IaC, environment variable names, CI config). If several providers are present, handle each with its own guide.
2. **Read the provider's hygiene guide first** (design decisions), then the **CRUD guide section for the operation and language** you need. Copy patterns, not values; keep the program contract (configuration from environment, credentials from files, no values printed).
3. **Apply the universal rules below**; they override convenience in any guide or tutorial.
4. **Verify** with the guide's mock-friendly structure or its optional live test in a sandbox, never against production without explicit approval.
5. **Report** what you changed, which identity and permissions it needs, how it rotates, and what you could not verify.

### Provider routing

| Provider | CRUD guide | Hygiene guide | Auth to prefer | Data addressed by |
| --- | --- | --- | --- | --- |
| 1Password | [1password-cli-secrets-crud-guide.md](references/crud/1password-cli-secrets-crud-guide.md) (original CLI-based reference) | [1password-engineering-hygiene.md](references/engineering/1password-engineering-hygiene.md) | Service account token | `op://vault/item/field` (use IDs) |
| Keeper Secrets Manager | [keeper-secrets-manager-crud-guide.md](references/crud/keeper-secrets-manager-crud-guide.md) | [keeper-secrets-manager-engineering-hygiene.md](references/engineering/keeper-secrets-manager-engineering-hygiene.md) | Device configuration from a one-time token, IP-locked | Record UID / `keeper://` |
| Bitwarden Secrets Manager | [bitwarden-secrets-manager-crud-guide.md](references/crud/bitwarden-secrets-manager-crud-guide.md) | [bitwarden-secrets-manager-engineering-hygiene.md](references/engineering/bitwarden-secrets-manager-engineering-hygiene.md) | Machine account access token (expiring) | Secret UUID |
| AWS Secrets Manager | [aws-secrets-manager-crud-guide.md](references/crud/aws-secrets-manager-crud-guide.md) | [aws-secrets-manager-engineering-hygiene.md](references/engineering/aws-secrets-manager-engineering-hygiene.md) | IAM role (IRSA/Pod Identity, instance/task role) | Name or ARN |
| OCI Vault | [oci-vault-secrets-crud-guide.md](references/crud/oci-vault-secrets-crud-guide.md) | [oci-vault-engineering-hygiene.md](references/engineering/oci-vault-engineering-hygiene.md) | Instance/resource principal, OKE workload identity | Secret OCID |
| GCP Secret Manager | [gcp-secret-manager-crud-guide.md](references/crud/gcp-secret-manager-crud-guide.md) | [gcp-secret-manager-engineering-hygiene.md](references/engineering/gcp-secret-manager-engineering-hygiene.md) | Attached service account / Workload Identity Federation | `projects/…/secrets/…/versions/…` |
| Azure Key Vault | [azure-key-vault-secrets-crud-guide.md](references/crud/azure-key-vault-secrets-crud-guide.md) | [azure-key-vault-engineering-hygiene.md](references/engineering/azure-key-vault-engineering-hygiene.md) | Managed identity / workload identity | Vault URI + name (+ version) |
| HashiCorp Vault (KV v2) | [hashicorp-vault-kv-crud-guide.md](references/crud/hashicorp-vault-kv-crud-guide.md) | [hashicorp-vault-engineering-hygiene.md](references/engineering/hashicorp-vault-engineering-hygiene.md) | Platform auth (Kubernetes, cloud, JWT/OIDC); AppRole otherwise | Mount + path (+ version) |
| Infisical | [infisical-secrets-crud-guide.md](references/crud/infisical-secrets-crud-guide.md) | [infisical-engineering-hygiene.md](references/engineering/infisical-engineering-hygiene.md) | Machine identity with platform auth | Project + environment + path + key |
| Doppler | [doppler-secrets-crud-guide.md](references/crud/doppler-secrets-crud-guide.md) | [doppler-engineering-hygiene.md](references/engineering/doppler-engineering-hygiene.md) | Service account identity (OIDC) or service account | Project + config + name |
| Akeyless | [akeyless-secrets-crud-guide.md](references/crud/akeyless-secrets-crud-guide.md) | [akeyless-engineering-hygiene.md](references/engineering/akeyless-engineering-hygiene.md) | Cloud IAM / Kubernetes / JWT auth method | Item path |

### Write semantics differ — know them before writing code

| Provider | Create-only available? | Optimistic concurrency on update | Delete / recovery |
| --- | --- | --- | --- |
| 1Password | Item IDs are generated; titles can repeat | Edit from a fresh JSON snapshot | Archive or delete; deleted items recoverable 30 days (support policy) |
| Keeper | UID generated; titles can repeat → check first | **Record revision** (stale revision rejected); rotation transactions | Vault Deleted Items (confirm policy) |
| Bitwarden SM | UUID generated; keys can repeat → check first | None (PUT replaces all fields) | Trash, 30 days; bulk delete reports per-ID errors |
| AWS | **Yes** (`CreateSecret` fails if name exists) | Idempotency via `ClientRequestToken`; staging labels | Recovery window 7–30 days (default 30) or forced |
| OCI | **Yes** (409 on duplicate name) | `if-match` ETag | Scheduled deletion 1–30 days |
| GCP | **Yes** (`ALREADY_EXISTS`) | Versions are immutable; `etag` on metadata/delete | Disable → destroy (optionally delayed); `DeleteSecret` immediate |
| Azure | **No** (`SetSecret` upserts) → probe then set | None; last writer wins | Soft delete + purge protection |
| HashiCorp Vault | **Yes** (`cas=0`) | **`cas=<version>`** | Soft delete/undelete per version; destroy; metadata delete purges |
| Infisical | **Yes** (400 if key exists) | None; approvals may defer writes | Commit history / point-in-time recovery (plan) |
| Doppler | **No** (writes upsert) → probe then create | **`originalValue`** guard | Config log rollback |
| Akeyless | **Yes** (item paths are unique; duplicate create fails, status code undocumented) | None documented (`last-version` not a CAS) | Treat as permanent; `rollback-secret` for values with retained versions |

### End-to-end encrypted providers need their SDKs

Keeper, Bitwarden Secrets Manager, and 1Password encrypt on the client; their servers never see plaintext. Do not reimplement their protocols. Use the official SDK; where a language has none, use the provider's native core (Bitwarden `bitwarden_c`) or a small process running an official SDK (the Keeper bridge), with values on pipes only.

## Senior secrets-handler competencies

### 1. Threat model before code

For every secret ask: who must read it, who may write it, where does it travel, where can it rest (memory, disk, cache, logs, state files, images, crash dumps, CI artifacts), how is it rotated, and how fast can it be revoked. Name the blast radius of the credential that unlocks the store itself (role, token, configuration).

### 2. Identity first, secrets second

- Prefer platform identity (cloud roles, Kubernetes service accounts, OIDC federation) so no bootstrap secret exists. Where one must exist (API key, client secret, access token, device configuration), make it short-lived or expiring, IP/CIDR-bound where supported, single-workload, revocable individually, and delivered as a file from the orchestrator's secret mechanism.
- One identity per workload per environment. Separate readers from writers. Never use a human's credentials in automation.
- Least privilege on the narrowest resource (path, project, folder, vault, config, ARN with suffix wildcard). Prove it with a negative test.

### 3. Handle values like hazardous material

- **Never** put values in command-line arguments, URLs, query strings, environment variables of long-lived processes (prefer files or in-memory fetch), logs, exception messages, metrics labels, traces, crash reports, IaC state, container images, or source control.
- Read credentials from files with restrictive permissions (`umask 077`, `0600`), trim exactly one trailing newline when the format requires it, and know whether each tool stores trailing newlines verbatim.
- Generate values with a CSPRNG; compare with constant-time functions; minimize copies; wipe buffers where the language allows (`zeroize`, `OPENSSL_cleanse`, `CryptographicOperations.ZeroMemory`, overwrite `[]byte`).
- Treat SDK error objects, HTTP debug logs, and request dumps as sensitive: many include bodies, headers, or tokens. Log class, status code, request ID, and resource identifiers only.
- HTTPS only; never disable certificate verification; add private CAs to the trust store instead.

### 4. Correct API usage

- Use the official SDK where it exists and is maintained; otherwise use the documented REST API with timeouts, bounded retries, and explicit error mapping.
- Respect create-only vs upsert semantics, concurrency guards, version semantics, eventual consistency, and rate limits (table above).
- Retry reads; do not blindly retry writes — re-read and decide, or use the provider's idempotency token.
- Fix scope (project, environment, path, vault, folder) in configuration; never let request input choose it.

### 5. Lifecycle and rotation

- Every secret has an owner, a rotation method, and a revocation path written down.
- Rotate at the source first (or use dual credentials), then store, then let consumers refresh (TTL caches, reload hooks, restart), then revoke the old credential.
- Prefer managed rotation or dynamic, per-lease credentials when the provider offers them.
- Retire deliberately: disable/soft-delete, watch access logs, then purge.

### 6. Delivery patterns

Choose in this order unless the hygiene guide says otherwise: in-process SDK fetch with cache → agent/sidecar rendering files to tmpfs → CSI/volume mount → synced platform secret (Kubernetes `Secret`) → environment variables injected at launch. Each step outward widens exposure; document why it is needed.

### 7. CI/CD and supply chain

- CI authenticates with OIDC federation to the provider; no long-lived tokens in CI variables. If unavoidable: read-only, expiring, environment-scoped, protected branches only.
- Pin SDK and CLI versions; verify signatures/checksums; review upgrades (generated SDKs change defaults).
- Secret scanning in pre-commit and CI; block merges on findings; treat a committed secret as leaked even after removal.

### 8. Detection and incident response

- Stream provider audit logs to a SIEM; alert on unexpected readers, policy/role changes, new tokens or devices, failed authentications, and unusual read volume.
- Leak playbook: contain (revoke the leaked credential or identity) → rotate every secret it could read → confirm consumers recovered → review audit logs for use → remove the leak path → write the post-incident note.

### 9. Verification without exposure

- Unit-test against fakes with generated values; adapter-test against HTTP-level mocks (each CRUD guide documents the mock used to verify its programs); integration-test in a sandbox scope with unique names and teardown.
- Verify writes by comparing in constant time or with `cmp` on files — never by printing.
- Add leak-regression tests: inject sentinel values and assert they never appear in logs or error output.

## Hard rules for the agent

1. Never print, echo, log, or paste a secret value, token, private key, access key, or configuration — not in code, comments, commits, PR descriptions, tickets, or chat. Refer to secrets by identifier.
2. Never write to or delete from a production secret store, or change production access policy, without explicit approval; use a sandbox scope for tests.
3. Never put secret values on command lines, in URLs, or in environment variables of shells you hand back to the user.
4. Never disable TLS verification, never downgrade to plaintext transport except loopback test servers, never weaken purge protection or recovery windows to make a test pass.
5. Never reimplement a provider's cryptographic protocol; use its SDK or native core.
6. When unsure whether an action could expose or destroy a secret, stop and ask.

## Code review checklist (any provider)

- [ ] No values, tokens, keys, or configurations in code, tests, fixtures, IaC, images, docs, or logs.
- [ ] Workload identity (or a hardened, expiring, file-delivered bootstrap credential) with least privilege; readers and writers separated.
- [ ] Scope fixed in configuration; identifiers (IDs/UUIDs/ARNs/paths) rather than ambiguous names.
- [ ] Correct create/update/delete semantics for the provider; concurrency guard or single-writer design; idempotent retries.
- [ ] Timeouts, bounded retries for reads, explicit handling of not-found, permission, rate-limit, and conflict errors.
- [ ] Values never in argv/env/logs/errors; SDK debug logging off; error objects not logged whole.
- [ ] Cache with TTL and invalidation; rotation path tested; revocation path documented.
- [ ] Tests: fakes/mocks, sandbox integration, negative permission test, leak-regression test.
- [ ] CI uses OIDC or a scoped, expiring credential; versions pinned; secret scanning enabled.

## Anti-patterns

| Don't | Do instead |
| --- | --- |
| `tool secret set NAME=VALUE` in scripts | File/stdin input, or the SDK |
| Long-lived admin tokens in CI | OIDC federation to a read-only identity |
| Logging the SDK exception | Log class, status, request ID |
| Name lookups where names can repeat (Bitwarden keys, Keeper titles, 1Password titles) | Store IDs; refuse ambiguous matches |
| Blind retries of writes | Idempotency tokens or re-read-then-write with a guard |
| Syncing every secret into Kubernetes `Secret` objects | Fetch in process or mount only what the pod needs |
| Disabling soft delete/purge protection for convenience | Keep recovery; purge deliberately |
| Re-implementing E2E-encrypted protocols | Official SDKs / native core / SDK bridge |

## What the guides verified, and what they did not

Each CRUD guide states its verification boundary at the top: which programs were compiled or type-checked, which were run end-to-end against local mocks (and how the mocks were validated against official SDKs or official test fixtures), which were only checked against SDK sources, and that no live provider account was used. Treat unverified items as such, run the optional live test in a sandbox before relying on them, and re-check sources when the documented verification date is old.
