# 1Password: building software around service accounts, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages secrets stored as 1Password items, through the `op` CLI, the official SDKs, or a Connect server.  
**Companion:** [`../crud/1password-cli-secrets-crud-guide.md`](../crud/1password-cli-secrets-crud-guide.md) (the original CLI-based CRUD guide this package was modeled on). Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026 (CRUD guide: October 6, 2026)

## 1. Choose the consumption pattern first

| Pattern | Use when | Hygiene cost |
| --- | --- | --- |
| **Official SDK** (Go `onepassword-sdk-go`, JS/TS `@1password/sdk`, Python `onepassword-sdk`) + service account | Services you own in those languages | Token in memory; you own caching and rate-limit budgeting |
| **`op run` / `op read` / `op inject` with `op://` secret references** | Scripts, CLIs, apps in other languages, local development | Child-process env vars or generated files; masking is not a boundary |
| **1Password Connect server** (self-hosted REST + cache) | High read volume, network-isolated workloads, Kubernetes operator | You operate a server holding vault data and Connect tokens |
| **Kubernetes operator / CI integrations** (GitHub Actions `load-secrets-action`, others) | Platform-native delivery | Values land in Kubernetes Secrets or CI env vars |

**Default:** a service account scoped to the minimum vaults, used through an official SDK where one exists and through `op` with secret references elsewhere. Languages without an SDK (Rust, PHP, C#, Java, Swift, C, C++) should call `op read`/`op run` via a subprocess with values on stdout/stdin pipes, or use Connect's REST API.

## 2. Identity and access design

1. **Service accounts, not personal sessions,** for all automation. A service account token (`OP_SERVICE_ACCOUNT_TOKEN`) authenticates *and* can decrypt the vaults it was granted; treat it like a private key.
2. **Grant only the vaults a workload needs,** with read-only permission unless it writes. Service accounts cannot reach Private/Personal/Employee vaults, and vault grants are fixed at creation — create a new service account rather than widening one.
3. **One service account per workload per environment.** Shared tokens make rotation and audit meaningless and pool rate limits.
4. **Rate limits are per account and per token (hourly and daily);** check them with `op service-account ratelimit` and design caching accordingly.
5. **Connect tokens** are scoped per vault and per server; protect the Connect server's credentials file (it contains material that decrypts the granted vaults).
6. **Rotate and revoke** service account tokens on staff changes and on any suspicion; revocation is immediate.

## 3. Code structure

```typescript
// Port seen by business code; only the adapter knows op:// references and the token.
export interface SecretSource {
  get(reference: string): Promise<string>;   // "op://<vault-id>/<item-id>/<field>" from configuration
  invalidate(reference: string): void;       // after a downstream authentication failure
}
```

Adapter rules:

- **Use IDs, not names,** in secret references for anything automated (names change and can collide); keep references in configuration (they are not secrets).
- **Always supply the vault** when reading or writing items; never let request input choose vault or item.
- **Cache reads** (SDK client per process; Connect for fleets) to stay inside rate limits; refresh on a timer or after authentication failures downstream.
- **Writes:** edit from a fresh JSON snapshot (the CRUD guide's workflow) so concurrent fields are not lost; never pass values in command arguments — use JSON on stdin or templates.
- **Subprocess use of `op`:** no shell; values via stdout/stdin pipes; `--no-newline` where exact bytes matter; check exit codes.
- **Log safely:** reference (vault/item IDs and field label), operation, exit code or SDK error class. Never values or the token; `op run` masking is a convenience, not a control.

## 4. Lifecycle: provision, rotate, retire

- **Provisioning:** vaults and service accounts via the admin console or `op service-account create` with explicit `--vault` grants; deliver tokens through the platform's secret store.
- **Rotation of secrets:** rotate at source → edit the item → consumers refresh (restart `op run` processes; they do not see later changes) → revoke old credential.
- **Rotation of tokens:** create a replacement service account (or token) → deploy → verify → revoke the old one.
- **Retire:** archive or delete items (deleted items are recoverable for 30 days per the support policy) → revoke at source → revoke service accounts that no longer need access.

## 5. Logging, telemetry, and error hygiene

- Use 1Password **Events Reporting** (sign-in attempts, item usage, audit events; plan-dependent) with your SIEM; alert on new service accounts, vault grant changes, and item usage by unexpected service accounts.
- CI: never echo `op read` output; prefer masked CI integrations; avoid `--no-masking`.
- Generated files from `op inject` must be `0600`, outside source control, and deleted after use.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource`; generated values. |
| Adapter | Stub the subprocess (`op`) or the SDK client; test missing-item, permission, and rate-limit paths. |
| Integration | A dedicated test vault and service account (the CRUD guide's live test); unique item titles; delete in teardown. |
| Permission tests | Assert the runtime service account cannot read other vaults or write. |
| Leak regression | Sentinel values; assert absence from logs and CI output. |

## 7. CI/CD and supply chain

- Store `OP_SERVICE_ACCOUNT_TOKEN` as a protected, environment-scoped CI secret; use read-only service accounts for CI.
- Pin the `op` CLI version and verify its signature/checksum; pin SDK versions (the SDKs are pre-1.0 and change quickly).
- Secret scanning plus pre-commit hooks (service account tokens have a recognizable `ops_` prefix).

## 8. Operations and incident response

- **Leak playbook (value):** rotate at source → edit item → restart consumers → revoke old credential → review Events Reporting.
- **Leak playbook (service account token):** revoke the service account → treat every item in its vaults as exposed → rotate those → issue a new service account → review usage events.
- **Outage planning:** Connect's local cache or application caches keep reads working briefly; decide acceptable staleness.

## 9. Review checklist for the engineering agent

- [ ] No values or tokens in code, config, IaC, fixtures, images, or docs; reference files contain only `op://` references.
- [ ] Service account per workload/environment with minimal vault grants; read-only where possible.
- [ ] IDs in references; vault always explicit.
- [ ] No values in argv; JSON/stdin or templates for writes.
- [ ] Rate-limit budget understood; caching in place.
- [ ] `op inject` outputs protected and cleaned up; masking not relied upon.
- [ ] Logs contain references and status only.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Personal `op signin` sessions in automation | Service accounts |
| `op item create ... password=$VALUE` | JSON template on stdin |
| One service account for every service | One per workload per environment |
| Expanding `"$SECRET"` in the parent shell of `op run` | Expand inside the child (`sh -c '...'`) |
| Committing `op inject` output | Generate at deploy time, `0600`, delete after use |
| Name-based references in production config | ID-based references |

## Sources

See the source register in the CRUD guide (S01–S25), plus:

| ID | Source |
| --- | --- |
| S26 | [1Password SDKs](https://www.1password.dev/sdks) |
| S27 | [1Password Connect](https://www.1password.dev/connect) |
