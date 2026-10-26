# Infisical: building software around the API, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages secrets in Infisical (Cloud or self-hosted).  
**Companion:** [`../crud/infisical-secrets-crud-guide.md`](../crud/infisical-secrets-crud-guide.md) for exact calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the consumption pattern first

| Pattern | Use when | Hygiene cost |
| --- | --- | --- |
| **SDK + machine identity + in-process cache** | Services you own | You manage token renewal; lowest exposure |
| **Infisical Agent** (auto-auth + templates) | Apps that read files; polyglot fleets | Rendered files on tmpfs, `0600`; agent holds the identity |
| **`infisical run -- <cmd>`** | Simple processes, local development | Values in child env vars; restart to pick up changes |
| **Kubernetes Operator** (`InfisicalSecret` → Kubernetes `Secret`) | Kubernetes workloads expecting Secrets | Anyone who can read Secrets in the namespace can read values; enable auto-reload deliberately |
| **CI integrations / native syncs** (to cloud secret managers, CI variables) | Pushing values to other platforms | Each sync target becomes another place to protect and audit |

**Default:** a platform-authenticated machine identity (Kubernetes/AWS/GCP/Azure/OIDC) with the SDK or Agent. Universal Auth only where no platform identity exists.

## 2. Identity and access design

1. **One machine identity per workload per environment.** Never share client secrets across services; never use a human user's token in automation. Service tokens (`st.` prefix) are deprecated; migrate to machine identities.
2. **Platform auth over Universal Auth.** If Universal Auth is unavoidable: client secret TTL > 0, low max uses, trusted IPs (plan permitting), lockout on (default), and deliver the client secret via a file from your orchestrator's secret mechanism, not a baked env var. Consider the "secret zero" pattern: single-use client secret + periodic renewable access token held by Agent.
3. **Least-privilege custom roles** scoped by environment **and folder path** (for example read on `prod:/payments/**`). Separate reader and writer identities; only provisioning identities may create/delete.
4. **Environments as boundaries.** Keep `prod` in its own project or at least behind its own roles and approval policies; do not grant cross-environment read just to make references work.
5. **Approval policies (change management)** on production paths for human edits; decide explicitly whether automation writes go through approvals (writes then return an approval request, not an applied change).
6. **Self-hosted:** protect the instance's `ENCRYPTION_KEY`/root encryption configuration and `AUTH_SECRET` in a KMS/HSM; restrict network access; enable SSO and SCIM for humans; keep the instance patched.

## 3. Code structure

```typescript
// Port seen by business code; only the adapter imports @infisical/sdk.
export interface SecretSource {
  get(name: string): Promise<string>;   // cached, scope fixed at construction (project/env/path)
  invalidate(name: string): void;       // after a downstream authentication failure
}
```

Adapter rules:

- **Fix the scope at construction** (project, environment, path) from configuration; never let request input choose environment or path.
- **Token lifecycle in one place:** login at startup; renew before expiry (Go SDK does this automatically; others must call renew or re-login); re-login at max TTL; on 401, re-login once.
- **Disable reference expansion** (`expandSecretReferences=false`) when exact values matter; if you rely on references, document the dependency and grant read on the referenced paths explicitly.
- **Mind SDK caches:** Python caches 60 s by default; set it intentionally and invalidate on auth failure.
- **Handle approval responses:** if a write returns an approval object, report "pending," do not proceed as if applied.
- **Prefer v4 endpoints** in hand-written clients; current SDK releases still call deprecated v3 endpoints, so pin SDK versions and watch release notes for the switch.
- **Log safely:** class, status code, request ID; never full SDK error messages that may contain validation payloads, and never values.

## 4. Lifecycle: provision, rotate, retire

- **Provisioning:** create projects, environments, folders, roles, and identities via Terraform (Infisical provider) or API; keep secret values out of Terraform state (prefer write-only/ephemeral constructs where the provider supports them, or let rotation/syncs populate values).
- **Rotation:** use Infisical secret rotations for supported targets (databases, cloud credentials) so the source and the stored value change together; otherwise rotate at source → update the secret (new version) → let Agent/Operator/app caches refresh → revoke old credential. Use secret reminders (`secretReminderRepeatDays`) as a backstop, not as rotation.
- **Dynamic secrets** for databases/cloud where available: short-lived, per-lease credentials.
- **Retire:** delete the secret (recorded as a commit); revoke at the source; review audit logs for continued reads by identities that should have stopped.

## 5. Logging, telemetry, and error hygiene

- Stream Infisical **audit logs** to your SIEM (plan-dependent); alert on reads of production paths by unexpected identities, role changes, identity creation, and client secret creation.
- Application logs: project ID, environment, path, key name, version, status code; never values or tokens.
- CI: `--silent` on CLI commands; never `--show-values` or `--plain` into logs.
- Agent: run at `info` level; render to tmpfs; restrict file permissions.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource`; generated values. |
| Adapter | HTTP-level fake of the endpoints you call (the CRUD guide's mock passed four official SDKs) to test 400/401/403/404/422 and approval responses. |
| Integration | A sandbox project/environment with a dedicated identity; unique key names per run; delete in teardown. |
| Permission tests | Assert the runtime identity gets 403 on paths it must not read. |
| Leak regression | Sentinel values; assert absence from logs and error output. |

## 7. CI/CD and supply chain

- CI uses **OIDC Auth** with the CI provider's token, bound to repository/branch/environment claims; no stored client secrets.
- Pin `@infisical/sdk`, `infisicalsdk`, `go-sdk`, and CLI versions; review upgrades (watch for the v3→v4 endpoint migration).
- Secret scanning in CI (Infisical's own `infisical scan` or gitleaks/trufflehog) plus pre-commit hooks.

## 8. Operations and incident response

- **Alerts:** failed machine-identity logins/lockouts, new client secrets, role changes, approval-policy bypasses, unusual read volume.
- **Leak playbook:** rotate at source → update value → confirm consumers refreshed → revoke old credential → revoke or rotate any identity/client secret involved → review audit logs → remove the leak path. If a client secret leaked, delete it from the identity immediately and issue a new one.
- **Backups (self-hosted):** encrypted database backups plus the encryption key material, stored separately; test restore.

## 9. Review checklist for the engineering agent

- [ ] No values, client secrets, access tokens, or service tokens in code, config, IaC, fixtures, or docs.
- [ ] Machine identity per workload/environment; platform auth or hardened Universal Auth (TTL, uses, IPs, lockout).
- [ ] Custom role limited to the required environment and folder paths; readers and writers separate.
- [ ] Scope fixed in configuration; no request-controlled environment/path.
- [ ] Token renewal/re-login handled; 401 path tested.
- [ ] Reference expansion intentional; SDK cache behavior understood.
- [ ] Approval responses handled.
- [ ] No values or full error payloads in logs; CLI used with `--silent` in CI.
- [ ] Rotation plan per secret; dynamic secrets considered.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Personal access token or user login in CI | OIDC machine identity |
| One Universal Auth client secret shared by many services | One identity per workload |
| `infisical secrets set KEY=value` | `KEY=@file` or SDK |
| Admin role for a runtime service | Custom read-only role on one environment/path |
| Rely on CLI `set` for create-only provisioning | API/SDK create (fails if the key exists) |
| Leave references expanding across environments by accident | Explicit `expandSecretReferences` choice |
| Sync everything into Kubernetes Secrets "just in case" | Sync only what pods need, or use the SDK/Agent |

## Sources

| ID | Source |
| --- | --- |
| S01 | [Universal Auth](https://infisical.com/docs/documentation/platform/identities/universal-auth) |
| S02 | [Machine identities](https://infisical.com/docs/documentation/platform/identities/machine-identities) |
| S03 | [Role-based access controls](https://infisical.com/docs/documentation/platform/access-controls/role-based-access-controls) |
| S04 | [Point-in-time recovery](https://infisical.com/docs/documentation/platform/pit-recovery) |
| S05 | [Infisical Agent](https://infisical.com/docs/integrations/platforms/infisical-agent) |
| S06 | [Kubernetes Operator](https://infisical.com/docs/integrations/platforms/kubernetes/overview) |
| S07 | [API reference (v4 secrets)](https://infisical.com/docs/api-reference/endpoints/secrets/create) |
