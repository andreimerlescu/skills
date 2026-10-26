# HashiCorp Vault: building software around the API, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages secrets in HashiCorp Vault (self-managed or HCP Vault Dedicated).  
**Companion:** [`../crud/hashicorp-vault-kv-crud-guide.md`](../crud/hashicorp-vault-kv-crud-guide.md) for exact KV v2 calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the secret type and the consumption pattern first

Vault's strongest feature is that many credentials do not need to be stored at all.

| Need | Prefer | Why |
| --- | --- | --- |
| Database credentials | **Database secrets engine** (dynamic, per-lease users) | Unique, short-lived, auto-revoked; leaks expire. |
| Cloud credentials (AWS/GCP/Azure) | Cloud secrets engines | Same, for cloud APIs. |
| TLS certificates | PKI engine | Short-lived certs, no long-lived private keys in KV. |
| Encrypt/sign data | Transit engine | Keys never leave Vault. |
| Third-party API keys, static passwords | **KV v2** (this guide set) | Nothing to mint; versioned storage with CAS. |

Then choose how the workload gets values:

| Pattern | Use when | Hygiene cost |
| --- | --- | --- |
| **Vault Agent** auto-auth + templates (sidecar or daemon) | Apps that read files/env; mixed languages | No token handling in the app; rendered files must be tmpfs and `0600` |
| **Vault Proxy** with `use_auto_auth_token` | Apps that can call HTTP but should not hold tokens | Local listener must bind to loopback/Unix socket only |
| **Direct client** (CRUD guide §9) | Services that need fine control (CAS, dynamic leases) | App owns login, renewal, revocation, caching |
| **Vault Secrets Operator** / Agent Injector / CSI (Kubernetes) | Kubernetes workloads | VSO syncs to Kubernetes `Secret` objects (wider exposure); injector/CSI keep files in pod memory |

**Default:** platform auth method + Vault Agent or Proxy for most apps; direct client when the app manages leases or writes secrets.

## 2. Identity, auth methods, and policy design

1. **Authenticate with platform identity**: Kubernetes, AWS/GCP/Azure IAM, or JWT/OIDC from CI. The workload holds nothing long-lived.
2. **AppRole only when no platform identity exists.** RoleID is configuration; SecretID is a secret: deliver it **response-wrapped** by a trusted orchestrator, limit `secret_id_num_uses` (ideally 1), set short `secret_id_ttl`, and bind `secret_id_bound_cidrs`/`token_bound_cidrs`. Never bake a SecretID into an image.
3. **Short token TTLs** (minutes to hours) with renewal by Agent or a lifetime watcher; set `token_max_ttl`. Use **batch tokens** for high-volume, short-lived workloads that need no renewal.
4. **One role per workload per environment**, mapping to a policy that names exact KV v2 paths:
   - runtime: `read` on `secret/data/<app>/<env>/*`;
   - writer/rotator: `create`, `update`, `patch` on `data/`, `read` on `metadata/`;
   - lifecycle admin: `delete`/`undelete`/`destroy` paths and `metadata` `delete` — separately, and rarely.
5. **Templated policies** (`{{identity.entity.aliases.<mount accessor>.metadata.service_account_namespace}}`) scale per-tenant paths without per-tenant policy files.
6. **Namespaces** (Enterprise/HCP) or separate clusters per environment; never share one mount between dev and prod.
7. **No root tokens** outside break-glass ceremonies; revoke the initial root token after setup and generate root only with quorum when needed. [S01]
8. **Mount settings:** `cas_required=true` on KV mounts with multiple writers; `max_versions` sized to your rollback needs; `delete_version_after` for short-lived data.

## 3. Code structure

```go
// The only interface business code sees; the adapter owns the Vault client.
type SecretSource interface {
    Get(ctx context.Context, path, field string) ([]byte, error) // cached; returns a copy
    Invalidate(path string)
}
```

Adapter rules:

- **One client per process**; HTTP connection reuse; TLS with the Vault CA (`VAULT_CACERT`); no `VAULT_SKIP_VERIFY`.
- **Token lifecycle owned in one place:** login at startup, renew in the background before expiry (`LifetimeWatcher` in Go), re-login at max TTL, revoke-self on graceful shutdown. If Agent/Proxy is present, the app does none of this.
- **Configuration holds mount + path + field names**, never values.
- **Writes use CAS:** `cas=0` to create; `cas=<version read>` to replace; surface CAS conflicts to the caller rather than retrying blindly.
- **Prefer `patch`** for single-field updates so concurrent writers to other fields are not clobbered.
- **Cache** reads with TTLs; refresh on downstream auth failure once.
- **Validate paths** (no `..`, no empty segments) before building URLs; never concatenate user input into a Vault path.
- **Dynamic leases:** track lease IDs and TTLs; renew or re-read before expiry; revoke on shutdown.
- **No token or value in logs, panics, or error strings;** log path, version, request ID, and status only.

## 4. Lifecycle: provision, rotate, retire

**Provisioning:** mounts, auth methods, roles, and policies in Terraform (Vault provider) or another IaC tool, reviewed like code. For values:

- `vault_kv_secret_v2.data_json` is stored in Terraform state in plaintext. Prefer write-only arguments (`data_json_wo` with `data_json_wo_version` in recent Vault provider releases, Terraform 1.11+), ephemeral resources for reads, or populate values from the owning system out of band. [S02]
- Terraform state that ever held secrets must be treated as a secret store itself (encrypted backend, restricted access).

**Rotation:**

- Prefer dynamic engines; for static KV values, rotate at the source, write with CAS, let consumers refresh (Agent re-renders templates), then **destroy** old versions that must not be recoverable.
- Database static roles (`database/static-roles`) let Vault rotate an existing account's password on a schedule.

**Retire:** soft delete first, watch audit logs for reads of the path, then `metadata delete`. Revoke credentials at their source and revoke outstanding leases (`vault lease revoke -prefix`).

## 5. Logging, telemetry, and error hygiene

- **Audit devices on** (at least two, to avoid blocking on one failure). Values are HMAC'd; do not enable `log_raw`. Use `vault write sys/audit-hash/<path> input=...` to correlate a known value with audit entries without exposing it. [S03]
- Application logs carry path, version, lease ID prefix, request ID, status; never `X-Vault-Token`, SecretIDs, or values.
- HTTP client debug logging prints headers (including the token) and bodies; keep it off.
- Telemetry: monitor login failures, 403 rates, lease counts, token TTL distributions, request latency.
- Agent/Proxy logs at `debug` can include template contents in errors; run at `info` in production.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource`; generated values only. |
| Adapter | HTTP-level fakes or a dev server: CAS conflicts, 403, 404-after-soft-delete, token expiry, 503 sealed. |
| Integration | `vault server -dev` in CI (never for real secrets) or a dedicated test namespace; unique paths per run; `metadata delete` in teardown. |
| Policy tests | `vault token capabilities` assertions for each role/path in CI. |
| Leak regression | Sentinel values; assert absence in logs and audit `log_raw` disabled. |

## 7. CI/CD and supply chain

- CI authenticates with the **JWT auth method** using the CI provider's OIDC token, bound by repository, branch, and environment claims.
- Deploy pipelines manage policies/roles; they rarely need to read application secrets.
- Pin client libraries; review upgrades; dependency and secret scanning on every push (Vault tokens have recognizable prefixes such as `hvs.` and `hvb.`, which scanners detect).
- Never echo `VAULT_TOKEN` or run `vault token lookup` unfiltered in CI logs.

## 8. Operations and incident response

- **Health:** monitor seal status, HA state, replication lag, and audit device health (Vault blocks requests if no audit device can log).
- **Alerts:** root token generation, policy changes, auth method changes, `sys/` writes, spikes in 403s or logins, destroy/metadata-delete operations.
- **Leak playbook (KV):** rotate at source → write new version with CAS → confirm consumers refreshed → **destroy** leaked versions → revoke tokens/leases that touched it (by accessor) → investigate via audit HMAC correlation.
- **Leak playbook (token):** `vault token revoke -accessor <accessor>`; for AppRole, destroy the SecretID by accessor and rotate the role's SecretIDs.
- **Break-glass:** sealed envelope/quorum procedures for root generation; rehearse them.

## 9. Review checklist for the engineering agent

- [ ] No tokens, SecretIDs, unseal/recovery keys, or values in code, config, IaC, fixtures, or docs.
- [ ] Platform auth method used; AppRole only with wrapped, single-use, CIDR-bound SecretIDs.
- [ ] Policies name exact `data/`, `metadata/`, `delete/`, `undelete/`, `destroy/` paths; runtime has `read` only.
- [ ] Dynamic secrets considered before storing a static credential in KV.
- [ ] TLS with proper CA; no `VAULT_SKIP_VERIFY`; Agent/Proxy listeners bound to loopback or Unix sockets.
- [ ] Token renewal/re-login/revocation handled (or delegated to Agent/Proxy).
- [ ] Writes use CAS; `cas_required` on shared mounts; `patch` for single-field changes.
- [ ] Paths validated; no user input concatenated into Vault paths.
- [ ] No tokens/values in logs; audit devices on; `log_raw` off.
- [ ] Terraform does not persist values (write-only or out-of-band); state backend protected.
- [ ] Destroy procedure for leaked versions documented.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Long-lived root or admin token in CI | JWT auth with bound claims |
| SecretID in an environment variable baked into an image | Wrapped SecretID delivered at runtime, or platform auth |
| `path "secret/*" { capabilities = ["read"] }` for every service | Per-app, per-env paths on `secret/data/...` |
| Static DB password in KV rotated by hand | Database secrets engine (dynamic or static roles) |
| `vault kv put path password=$PW` | `password=@file` or stdin |
| Full `put` to change one field | `patch` with CAS |
| Soft delete to "remove" a leaked value | Rotate, then `destroy` the versions |
| `VAULT_SKIP_VERIFY=true` "temporarily" | Configure `VAULT_CACERT` |
| Sharing one token across replicas | Each instance authenticates itself |

## Sources

| ID | Source |
| --- | --- |
| S01 | [Production hardening](https://developer.hashicorp.com/vault/docs/concepts/production-hardening) |
| S02 | [Terraform write-only arguments](https://developer.hashicorp.com/terraform/language/resources/ephemeral/write-only) |
| S03 | [Audit devices](https://developer.hashicorp.com/vault/docs/audit) |
| S04 | [AppRole best practices](https://developer.hashicorp.com/vault/docs/auth/approle/approle-pattern) |
| S05 | [Vault Agent and Proxy](https://developer.hashicorp.com/vault/docs/agent-and-proxy) |
| S06 | [Database secrets engine](https://developer.hashicorp.com/vault/docs/secrets/databases) |
| S07 | [Tokens](https://developer.hashicorp.com/vault/docs/concepts/tokens) |
| S08 | [Policies](https://developer.hashicorp.com/vault/docs/concepts/policies) |
