# Doppler: building software around the API, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages secrets in Doppler.  
**Companion:** [`../crud/doppler-secrets-crud-guide.md`](../crud/doppler-secrets-crud-guide.md) for exact calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the consumption pattern first

| Pattern | Use when | Hygiene cost |
| --- | --- | --- |
| **REST adapter + service account/OIDC token + in-process cache** | Services you own that need control over refresh and errors | You own timeouts, retries, caching; lowest exposure |
| **`doppler run --mount … -- <cmd>`** | Apps that read a config file; you want values out of the environment | Named pipe, optionally `--mount-max-reads 1`; CLI holds the token |
| **`doppler run -- <cmd>`** | Simple processes, local development | Values in child env vars (visible to the process tree, crash dumps, `/proc`); fallback file on disk |
| **Kubernetes Operator** (`DopplerSecret` → Kubernetes `Secret`) | Kubernetes workloads expecting Secrets | Anyone who can read Secrets in the namespace can read values; enable reloads deliberately |
| **Integration syncs** (cloud secret managers, CI variables, PaaS) | The target platform must hold the values | Each sync target becomes another store to protect, audit, and rotate |

**Default:** an OIDC-backed service account identity (CI, Kubernetes) or a service account token, with a small REST adapter or `doppler run --mount`. Service tokens are fine for a single app on a single config. Personal and CLI tokens never leave a human's workstation.

## 2. Identity and access design

1. **Prefer short-lived tokens.** Service account identities exchange an OIDC JWT for a short-lived Doppler token (`POST /v3/auth/oidc`); bind the identity's trust to specific repositories, branches, or Kubernetes service accounts.
2. **One principal per workload per environment.** A service account (or service token) shared across services makes revocation and audit meaningless.
3. **Least privilege at two levels.** Service accounts start with no workplace role and no project access — keep it that way and add only the projects and environments needed with a read-only project role. Writers (provisioning, rotation jobs) get separate accounts.
4. **Service tokens:** `--access read` unless writes are required; always set `--max-age` for anything temporary; one token per app per config; record the slug so you can revoke it.
5. **Restricted visibility for high-value secrets**, knowing its limit: non-user tokens can still read restricted values, so control **who can create tokens** (workplace roles) as tightly as who can read secrets.
6. **Environments as boundaries.** `prd` configs live behind separate roles; do not use cross-config references (`${prd.DB_URL}` from `dev`) that force broader read access. Use change-request policies (Enterprise) for human edits to production.

## 3. Code structure

```typescript
// Port seen by business code; only the adapter knows Doppler's URLs and token.
export interface SecretSource {
  get(name: string): Promise<string>;   // cached; project/config fixed at construction
  invalidate(name: string): void;       // after a downstream authentication failure
}
```

Adapter rules:

- **Fix project and config at construction** from deployment configuration; never let request input choose them or the secret name.
- **Load once, cache with a TTL.** One `GET /v3/configs/config/secrets` (or download) per config at startup beats N single reads against the lower secret-read rate limit. Refresh on a timer or on a webhook-driven signal.
- **Always set timeouts** (connect and total). The generated SDKs do not.
- **Retries:** retry reads on 429/5xx with jittered backoff honoring `retry-after`. Do not blindly retry writes; re-read and use `originalValue`.
- **Writes:** probe-then-create for new names; `originalValue` on every update; `shouldDelete` or `DELETE` for removal; batch related changes in one `change_requests` array so they land in one config log entry.
- **Read `raw` vs `computed` deliberately** and document which one the application expects.
- **Log safely:** operation, project, config, secret name, HTTP status, request ID; never values, tokens, request bodies, or whole SDK exceptions (they contain the response body).
- **HTTP clients:** use an explicit bearer header via an auth object (Python `requests` can otherwise substitute `~/.netrc`); HTTPS only; no proxy-disabling or TLS-skipping flags (the CLI has `--no-verify-tls` — never use it).

## 4. Lifecycle: provision, rotate, retire

- **Provisioning:** projects, environments, configs, service accounts, and integrations via Terraform (`DopplerHQ/doppler` provider) or API. Keep secret **values** out of Terraform state where possible (generate values in a rotation job or set them via a write-only path), or treat the state file as a secret store with matching controls.
- **Rotation:** use Doppler's rotation integrations where supported (they change the source and the stored value together); otherwise rotate at the source → write the new value with `originalValue` → let caches/`--watch`/operator reloads pick it up → revoke the old credential. Dynamic secrets (where available) avoid long-lived database credentials entirely.
- **Token hygiene:** expiring service tokens, OIDC instead of static tokens in CI, scheduled review of service account tokens; roll tokens after staff changes.
- **Retire:** delete the secret (recoverable from config logs), revoke at the source, remove from integration targets, and check activity logs for continued reads.

## 5. Logging, telemetry, and error hygiene

- Stream **workplace activity logs** to your SIEM (plan-dependent); alert on token creation, role changes, visibility changes away from restricted, and reads of production configs by unexpected principals.
- CLI in automation: `--silent` on `secrets set` and `secrets delete` (otherwise values are printed), `--only-names` for inventory, never `--plain` output into CI logs.
- Fallback files: decide per workload (`--no-fallback` for CI, `--fallback-readonly` for read-only file systems); clean old ones with `doppler run clean`.
- Application logs: names and status codes only; scrub `Authorization` headers from HTTP debug logging.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource`; generated values. |
| Adapter | HTTP-level fake of `GET/DELETE …/secret` and `POST …/secrets` (the CRUD guide's mock accepts both REST and official SDK request shapes) to test 401/403/404/429 and guard failures. |
| Integration | A dedicated sandbox project/config and a dedicated service account; unique names per run; delete in teardown. |
| Permission tests | Assert the runtime token gets 403 on writes and on configs it must not read. |
| Leak regression | Sentinel values; assert absence from logs, error output, and CI output. |

## 7. CI/CD and supply chain

- CI authenticates with a **service account identity (OIDC)**; no long-lived Doppler token in CI variables. If unavoidable, a read-only, expiring service token for one config.
- Pin the Doppler CLI version and verify its signature/checksum per Doppler's install instructions; pin SDK versions if used.
- Secret scanning (GitHub secret scanning recognizes Doppler token formats; also gitleaks/trufflehog) plus pre-commit hooks.

## 8. Operations and incident response

- **Alerts:** new tokens, role grants, 401/403 spikes, 429 storms during deploys, integration sync failures.
- **Leak playbook (value):** rotate at source → write new value → confirm consumers refreshed → revoke old credential → review activity logs → remove the leak path.
- **Leak playbook (Doppler token):** revoke the token (service token revoke, service account token delete, OIDC token revoke via `/v3/auth/revoke`) → review what it could read → rotate every secret it could read (revocation does not erase fallback files or values already exported).
- **Outage planning:** fallback files and in-process caches keep apps running during API outages; decide the maximum staleness you accept.

## 9. Review checklist for the engineering agent

- [ ] No values or Doppler tokens in code, config, IaC, fixtures, Dockerfiles, or docs.
- [ ] OIDC identity or service account per workload; service tokens read-only and expiring; no personal/CLI tokens in live environments.
- [ ] Project/config fixed in configuration; no request-controlled scope.
- [ ] Adapter has timeouts, bounded retries for reads only, and a TTL cache.
- [ ] Updates use `originalValue`; creates probe first.
- [ ] `raw` vs `computed` choice documented.
- [ ] CLI calls in automation use `--silent`; fallback-file policy explicit.
- [ ] Logs contain names and status codes only.
- [ ] Rotation plan per secret; integration targets inventoried.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Personal or CLI token in a server or CI | Service account identity (OIDC) or service account token |
| `doppler secrets set KEY=value` in scripts | `doppler secrets set KEY --silent < file` or the API |
| `doppler secrets delete KEY -y` in CI logs | Add `--silent` (otherwise all remaining secrets print) |
| One read/write service token for every app | One read-only token per app per config |
| Sync every config into Kubernetes Secrets | Sync only what pods need, or read via adapter/`--mount` |
| Blind retries of writes after a 5xx | Re-read, then write with `originalValue` |
| Relying on `restricted` as an access control | Restrict who can create non-user tokens; use project roles |
| Logging SDK exceptions verbatim | Log class and status only |

## Sources

| ID | Source |
| --- | --- |
| S01 | [API reference overview (auth, token types, rate limits)](https://docs.doppler.com/reference/api) |
| S02 | [Service accounts](https://docs.doppler.com/docs/service-accounts) |
| S03 | [Service account identities (OIDC)](https://docs.doppler.com/docs/service-account-identities) |
| S04 | [Service tokens](https://docs.doppler.com/docs/service-tokens) |
| S05 | [Secret visibility](https://docs.doppler.com/docs/visibility-types) |
| S06 | [Automatic fallbacks](https://docs.doppler.com/docs/automatic-fallbacks) |
| S07 | [Kubernetes Operator](https://docs.doppler.com/docs/kubernetes-operator) |
| S08 | [Secrets rotation](https://docs.doppler.com/docs/secrets-rotation) |
| S09 | [Change request policies](https://docs.doppler.com/docs/change-request-policies) |
| S10 | [Webhooks](https://docs.doppler.com/docs/webhooks) |
| S11 | [Doppler CLI source](https://github.com/DopplerHQ/cli) |
