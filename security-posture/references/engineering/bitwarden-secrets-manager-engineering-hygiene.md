# Bitwarden Secrets Manager: building software around the SDK, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages secrets in Bitwarden Secrets Manager (cloud or self-hosted).  
**Companion:** [`../crud/bitwarden-secrets-manager-crud-guide.md`](../crud/bitwarden-secrets-manager-crud-guide.md) for exact calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the consumption pattern first

| Pattern | Use when | Hygiene cost |
| --- | --- | --- |
| **Official SDK (or `bitwarden_c`) + machine account + in-process cache** | Services you own | Token and state file are your responsibility; lowest exposure |
| **`bws run -- <cmd>`** | Simple processes, scripts | Values in child env vars; restart to pick up changes |
| **sm-operator** (`BitwardenSecret` → Kubernetes `Secret`) | Kubernetes workloads expecting Secrets | Namespace Secret readers can read values; operator holds a token |
| **sm-action / CI integrations** | CI jobs | Token stored in CI; values become step env vars |
| **Password Manager `bw serve`** | Never for production machine workloads | Unauthenticated local API over an unlocked vault |

**Default:** an official SDK with a dedicated machine account per workload per environment, values cached in memory and refreshed with `sync`.

## 2. Identity and access design

1. **The access token is also a decryption key.** Whoever holds it can authenticate *and* decrypt everything the machine account can read. Treat it like a private key: secret store of the orchestrator, file mount with `0600`, never an image layer, never a log.
2. **One machine account per workload per environment**, with **Can read** on exactly its project(s). Separate machine accounts (and tokens) for writers.
3. **Projects are the permission boundary.** Design projects around workloads and environments (`payments-prod`, `payments-staging`), not around teams; each secret belongs to one project.
4. **Expiring tokens.** Set an expiration on every access token; rotate by creating a new token, deploying it, verifying, then revoking the old one.
5. **Self-hosted:** protect the server's database and key material, keep it patched, restrict network access, and enable SSO for human administrators.

## 3. Code structure

```typescript
// Port seen by business code; only the adapter imports the Bitwarden SDK.
export interface SecretSource {
  get(logicalName: string): Promise<string>;  // logical name -> secret UUID from configuration
  invalidate(logicalName: string): void;      // after a downstream authentication failure
}
```

Adapter rules:

- **Address secrets by UUID** from configuration. Keys are not unique; if you must look up by key, fail on zero or multiple matches.
- **One SDK client per machine account,** created at startup; close it on shutdown (`Close()`/`Dispose()`/`free_mem`).
- **Use a state file** (encrypted volume, `0600`) for long-running services to avoid re-authenticating on every restart, or accept an identity call per start; never share state files between accounts.
- **Refresh efficiently:** `sync(organizationId, lastSyncedDate)` returns data only when something changed; `getByIds` batches reads.
- **Writes:** full-replacement updates (pass current key/note/project); check bulk-delete per-ID errors; refuse duplicate keys on create.
- **HTTPS only;** custom CAs belong in the OS trust store (the core uses the platform verifier). Never patch around TLS.
- **Log safely:** logical name, secret UUID, operation, SDK error text. Never values, tokens, state files, or raw command/response JSON from the C ABI.

## 4. Lifecycle: provision, rotate, retire

- **Provisioning:** create projects and machine accounts through the web app or automation with a dedicated admin identity; record secret UUIDs in deployment configuration. Keep values out of IaC state.
- **Rotation of secrets:** rotate at source → `update` with the new value → caches refresh via `sync` → revoke old credential.
- **Rotation of access tokens:** new token → deploy → verify → revoke old; alert on tokens nearing expiry.
- **Retire:** delete (Trash, 30 days) → revoke at source → purge from Trash when no rollback is needed → remove the UUID from configuration.

## 5. Logging, telemetry, and error hygiene

- **Event logs** (plan-dependent) record secret access and changes by machine accounts; stream them to your SIEM and alert on access by unexpected accounts, token creation, and permission changes.
- CI: `-o none` on `bws` write commands; never print `bws secret get` output.
- SDK log level Warn or higher in production.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource`; generated values. |
| Adapter | HTTP-level fake of `/identity/connect/token` and `/api/secrets` using the official sdk-sm fake-server fixture token (the CRUD guide's mock): the SDK still performs real encryption. |
| Integration | A sandbox project and machine account; unique keys per run; delete and purge from Trash in teardown. |
| Permission tests | Assert the runtime account cannot read other projects or write. |
| Leak regression | Sentinel values; assert absence from logs and CI output. |

## 7. CI/CD and supply chain

- Store the access token as a protected CI secret scoped to protected branches/environments; prefer a read-only account and a short-lived token for CI.
- Pin SDK versions and native binaries (they contain the cryptographic core); verify checksums where provided.
- Secret scanning (GitHub secret scanning, gitleaks/trufflehog) plus pre-commit hooks; Bitwarden access tokens have a recognizable `0.<uuid>.` prefix.

## 8. Operations and incident response

- **Leak playbook (value):** rotate at source → update → confirm consumers refreshed → revoke old credential → review event logs.
- **Leak playbook (access token):** revoke the token immediately → treat **every secret the machine account could read** as exposed (the token decrypts them) → rotate those at source → issue a new token → review event logs.
- **Outage planning:** cached values and state files keep services running during API outages; decide the maximum staleness you accept.

## 9. Review checklist for the engineering agent

- [ ] No values or access tokens in code, config, IaC, fixtures, images, or docs.
- [ ] Machine account per workload/environment; read-only where possible; tokens expire.
- [ ] Secrets addressed by UUID; duplicate keys refused.
- [ ] Updates pass all fields; bulk-delete errors checked.
- [ ] State file (if any) protected and not shared.
- [ ] HTTPS only; no TLS workarounds.
- [ ] No values, tokens, or raw C-ABI JSON in logs; `bws` output suppressed in CI.
- [ ] No `bw serve` in production paths.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Call the REST API directly and reimplement the encryption | Use an official SDK or the `bitwarden_c` core |
| Look up secrets by key at runtime | Store UUIDs in configuration |
| One machine account shared across services | One per workload per environment |
| `bws secret create KEY "$VALUE" …` in CI logs | SDK writes; `-o none` |
| Ignore the bulk-delete response | Check `data[].error` |
| `bw serve --hostname all` | Secrets Manager SDK; `bw serve` only on localhost in a sandbox |
| Long-lived, non-expiring access tokens | Expiring tokens with scheduled rotation |

## Sources

| ID | Source |
| --- | --- |
| S01 | [Secrets](https://bitwarden.com/help/secrets/) |
| S02 | [Machine accounts](https://bitwarden.com/help/machine-accounts/) |
| S03 | [Access tokens](https://bitwarden.com/help/access-tokens/) |
| S04 | [Secrets Manager CLI](https://bitwarden.com/help/secrets-manager-cli/) |
| S05 | [SDK sources (sdk-sm)](https://github.com/bitwarden/sdk-sm) |
| S06 | [Password Manager CLI](https://bitwarden.com/help/cli/) |
