# Keeper Secrets Manager: building software around the SDK, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages records through Keeper Secrets Manager (KSM).  
**Companion:** [`../crud/keeper-secrets-manager-crud-guide.md`](../crud/keeper-secrets-manager-crud-guide.md) for exact calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the consumption pattern first

| Pattern | Use when | Hygiene cost |
| --- | --- | --- |
| **Official SDK + in-memory configuration + cache** | Services you own in Go, Rust, Python, JS/TS, Java, .NET, Ruby | You protect one device configuration per deployment; lowest exposure |
| **SDK bridge process** (JSON lines over pipes) | C, C++, PHP, Swift, or anything without an SDK | One more process to pin, sandbox, and monitor; values never on argv |
| **`ksm exec` with `keeper://` notation** | Scripts, legacy apps reading env vars | Env-var exposure; config must be present on the host |
| **CI integrations** | Pipelines | Base64 configuration stored as a CI secret |
| **Kubernetes (External Secrets / Secret sync)** | Workloads expecting Kubernetes Secrets | Namespace Secret readers can read values |

**Default:** an official SDK, one KSM application per workload per environment, read-only shares, a configuration loaded from the platform's secret store into in-memory storage.

## 2. Identity and access design

1. **The configuration is the credential.** It contains the device private key and the application key; with it, an attacker can read and decrypt everything shared with the application. Store it like a private key (secret store, `0600` file, OS keychain); prefer a mounted file to a `KSM_CONFIG` environment variable.
2. **One application per workload per environment; one device per deployment target.** Devices are individually revocable by client ID; shared configurations make revocation impossible without collateral damage.
3. **Least privilege by sharing.** Share only the folders/records a workload needs, **read-only** unless it must write. Separate writer applications (provisioning, rotation) with **can edit** on their folders only.
4. **Keep IP lock on** (default). Unlock only for environments with dynamic egress, and compensate with short application access expiry and monitoring.
5. **One-time tokens are provisioning credentials:** redeem immediately, from a file not argv; they are consumed even by failed attempts; never log them.
6. **Expire application access** where the workload is temporary (CI runners, contractors).

## 3. Code structure

```typescript
// Port seen by business code; only the adapter imports the KSM SDK.
export interface SecretSource {
  get(logicalName: string): Promise<string>;  // logical name -> record UID + field from configuration
  invalidate(logicalName: string): void;      // after a downstream authentication failure
}
```

Adapter rules:

- **Address records by UID** (or `keeper://UID/field/...` notation) from configuration; titles are not unique.
- **In-memory storage** for read-mostly services so the SDK never rewrites the config file; if you need SDK-managed state (for example after key rotation), use file storage on a private, writable volume.
- **Batch reads:** `get_secrets([uids])` once per refresh; avoid per-request vault calls (throttling returns HTTP 403 `throttled` with `retry_after`; the SDKs back off).
- **Updates:** always reload before modifying (revision check); on conflict, reload and re-apply. Use `rotation` transactions plus `complete_transaction` for credential rotations.
- **Deletes:** check per-record results; on .NET, read back to confirm.
- **Bridge processes:** spawn without a shell (`posix_spawn`, `proc_open` array form, `Process`), run Python with `-I`, keep values on pipes, read responses line by line, restart on failure.
- **Logging:** logical name, UID, operation, SDK error code. Never field values, the configuration, or one-time tokens; keep SDK debug logging off in production.
- **Timeouts:** set request timeouts explicitly (JS `requestTimeoutMs`, Java `connectTimeoutMillis`/`readTimeoutMillis`).

## 4. Lifecycle: provision, rotate, retire

- **Provisioning:** create applications, shares, and devices with Commander or the vault under a dedicated admin identity; deliver configurations through the platform's secret store; record UIDs in deployment configuration.
- **Rotation of secrets:** Keeper rotation (KeeperPAM) or your job with `rotation` transactions: save (pending) → rotate at target → `complete_transaction(rollback = failed)` → consumers refresh.
- **Rotation of devices:** add a new device → deploy its configuration → verify → revoke the old device by client ID.
- **Retire:** delete records (vault Deleted Items) → revoke at source → remove shares → revoke devices → delete the application.

## 5. Logging, telemetry, and error hygiene

- Use Keeper's **ARAM / audit events** (plan-dependent) and SIEM integration; alert on new devices, unlocked IPs, share changes, record access by unexpected applications, and failed device authentications.
- CI: never print `ksm secret get` output; pass the configuration as a masked secret.
- Application logs: UIDs and error codes only.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource`; generated values. |
| Adapter | A protocol-level fake (the CRUD guide's mock implements transmission keys, signatures, folder keys, revisions) via the SDKs' custom server-key option; or the Python SDK's `custom_post_function` hook. |
| Integration | A sandbox shared folder with a placeholder record and a dedicated application/device; unique titles per run; delete in teardown. |
| Permission tests | Assert the runtime application cannot see unshared records or write to read-only shares. |
| Leak regression | Sentinel values; assert absence from logs and CI output. |

## 7. CI/CD and supply chain

- Store a CI-specific device configuration (separate application, read-only shares, IP lock where runners have fixed egress, access expiry) as a masked secret.
- Pin SDK and CLI versions; KSM SDKs release independently per language — review changelogs (for example custom server key support differs by language).
- Secret scanning plus pre-commit hooks; add custom patterns for base64 KSM configurations (`eyJ...` JSON with `clientId`, `privateKey`, `appKey`).

## 8. Operations and incident response

- **Leak playbook (value):** rotate at source (transaction) → confirm consumers refreshed → review audit events.
- **Leak playbook (configuration):** revoke the device by client ID immediately → treat every record shared with the application as exposed → rotate those credentials → issue a new device to the legitimate workload → review audit events.
- **Leak playbook (one-time token):** if unredeemed, delete the device/token in the vault; if redeemed by an attacker, revoke that device and proceed as above.
- **Outage planning:** encrypted fallback cache (Python `KSMCache`, equivalents elsewhere) keeps services running; decide the acceptable staleness and protect the cache file.

## 9. Review checklist for the engineering agent

- [ ] No values, configurations, or one-time tokens in code, config, IaC, fixtures, images, or docs.
- [ ] Application per workload/environment; device per deployment; read-only shares unless writing; IP lock on.
- [ ] Records addressed by UID/notation; duplicate titles refused on create.
- [ ] Reload-before-update; conflicts handled; rotation transactions used for rotations.
- [ ] Per-record delete results checked.
- [ ] In-memory configuration (or private writable volume); cache location protected.
- [ ] Bridge (if any): no shell, `python -I`, pinned SDK, pipes only.
- [ ] No values or configs in logs; SDK debug logging off.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Share one configuration across services and environments | One device per deployment; revocable by client ID |
| Look up records by title at runtime | Store UIDs or `keeper://` notation |
| `ksm secret update --field password=$VALUE` in scripts | SDK update (or the bridge) |
| Second `save()` without reloading | Reload, then save |
| Disable IP lock everywhere for convenience | Keep it; unlock only for dynamic-egress environments with compensating controls |
| Re-implement the KSM protocol in a new language | Use an SDK or an SDK bridge |
| Put the base64 config in an image layer or repo | Platform secret store, mounted at runtime |

## Sources

| ID | Source |
| --- | --- |
| S01 | [KSM overview](https://docs.keeper.io/en/keeperpam/secrets-manager/overview) |
| S02 | [One-Time Access Token](https://docs.keeper.io/en/keeperpam/secrets-manager/about/one-time-token) |
| S03 | [Encryption model](https://docs.keeper.io/en/keeperpam/secrets-manager/about/security-encryption-model) |
| S04 | [Python SDK (caching, transactions, revisions)](https://docs.keeper.io/en/keeperpam/secrets-manager/developer-sdk-library/python-sdk) |
| S05 | [CLI: secret command](https://docs.keeper.io/en/keeperpam/secrets-manager/secrets-manager-command-line-interface/secret-command) |
| S06 | [SDK sources](https://github.com/Keeper-Security/secrets-manager) |
