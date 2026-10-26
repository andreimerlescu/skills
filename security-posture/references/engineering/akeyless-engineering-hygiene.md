# Akeyless Vault Platform: building software around the API, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages static secrets in Akeyless (SaaS or through a customer Gateway).  
**Companion:** [`../crud/akeyless-secrets-crud-guide.md`](../crud/akeyless-secrets-crud-guide.md) for exact calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the consumption pattern first

| Pattern | Use when | Hygiene cost |
| --- | --- | --- |
| **SDK/REST + platform auth method + in-process cache** | Services you own | You own token refresh, timeouts, caching; lowest exposure |
| **Gateway in the workload's network** | Latency, resilience, `k8s` auth, customer fragments (DFC) | Gateway is a high-value component: patch it, restrict its ports (8000 internal only), monitor it |
| **Kubernetes Secrets Injector** | Pods that read files/env vars | Mutating webhook in the data path; values live in pod memory/files, not Kubernetes `Secret` objects |
| **External Secrets Operator / CSI** | Platforms standardized on those tools | `Secret` sync widens exposure to namespace readers |
| **CLI in scripts** | Operator tasks | Values passed as `--value` hit history/process tables; profile files hold credentials |

**Default:** a cloud-IAM, Kubernetes, or JWT/OIDC auth method + SDK/REST adapter (through a Gateway where available). API Keys only where nothing else fits, and Universal Identity for on-prem machines without a platform identity.

## 2. Identity and access design

1. **No static secrets for authentication where avoidable.** Cloud IAM and Kubernetes auth prove identity from the platform; JWT/OIDC suits CI. Universal Identity tokens rotate (default TTL 60 minutes) and should be auto-rotated (`uid-auto-rotate`).
2. **If API Keys are used:** one per workload; bound IPs; access expiration; short JWT TTL; key delivered via file from the orchestrator's secret mechanism; rotate on staff or vendor change.
3. **Roles and paths.** Design the folder hierarchy for access control (`/<env>/<team>/<app>/…`). Reader roles get `read` on exactly their prefix; add `list` only if the app enumerates. Writer roles (provisioning, rotation) are separate and own their prefix. Use `deny` to carve out sensitive sub-paths. Time-boxed rules (`--ttl`) for break-glass access.
4. **Sub-claims** on role associations bind a shared auth method (for example one Kubernetes auth method per cluster) to a specific namespace/service account, or a CI method to a specific repository and branch.
5. **Environments as boundaries.** Separate auth methods and roles per environment; production secrets with delete protection and a distinct protection key.
6. **Encryption keys and DFC.** Use a customer fragment on your Gateway when policy requires that the SaaS cannot decrypt; protect and back up the Gateway configuration accordingly.

## 3. Code structure

```typescript
// Port seen by business code; only the adapter knows Akeyless URLs, tokens, and item paths.
export interface SecretSource {
  get(logicalName: string): Promise<string>;  // maps to a fixed item path; cached with TTL
  invalidate(logicalName: string): void;      // after a downstream authentication failure
}
```

Adapter rules:

- **Map logical names to item paths in configuration;** never accept a path from request input (path traversal across your folder hierarchy is an authorization bypass in your app even if roles would stop it).
- **Token lifecycle in one place:** authenticate at startup; refresh before `expiration`; on an authentication failure re-authenticate once, then fail closed.
- **Batch reads:** `get-secret-value` takes many names; load a service's secrets in one call.
- **Timeouts everywhere.** Configure them explicitly on SDK HTTP clients (Go `Configuration.HTTPClient`, Java `ApiClient.setReadTimeout`, npm `ApiClient.timeout`).
- **Writes:** `create-secret` for new items (create-only); `update-secret-val` with `keep-prev-version=true`; serialize writers per item, since there is no documented compare-and-swap.
- **Logging:** item path, operation, HTTP status, request duration. Never the request body (it contains the token), never SDK error objects (they contain bodies and headers), never values.
- **Generated SDK hygiene:** pin the version; turn off debug logging; review regenerated defaults on upgrade.

## 4. Lifecycle: provision, rotate, retire

- **Provisioning:** auth methods, roles, rules, folders, and targets via Terraform (`akeyless-community/akeyless` provider) or API. Keep secret **values** out of Terraform state: create the item empty or with a placeholder and let a rotation job set the value, or treat state as a secret store.
- **Rotation:** prefer **rotated secrets** (Akeyless changes the credential at the target and stores the new value) or **dynamic secrets** (per-lease credentials) for databases and cloud keys. For static secrets: rotate at source → `update-secret-val` with `keep-prev-version=true` → wait for caches (Gateway, app) → revoke the old credential → keep `rollback-secret` available until verified.
- **Versions:** set `max-versions` deliberately; enough for rollback, not an unbounded archive of old credentials.
- **Retire:** delete protection off (deliberately) → `delete-item` → revoke at source → watch audit logs for continued access attempts.

## 5. Logging, telemetry, and error hygiene

- Forward Akeyless **audit logs** (via log forwarding/event forwarders) to your SIEM; alert on auth-method changes, role-rule changes, new API keys, reads of production paths by unexpected identities, and spikes in failed authentication.
- Gateway logs and metrics: monitor cache hit rate, upstream errors, and certificate expiry.
- Application logs: path + status only; scrub bodies from HTTP debug logs.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource`; generated values. |
| Adapter | HTTP-level fake of the V2 `POST` endpoints (the CRUD guide's mock passed the Python, Go, and npm SDKs) to test auth failure, not-found, duplicate create, and timeouts. |
| Integration | A sandbox folder and a dedicated auth method + role; unique names per run; delete in teardown. |
| Permission tests | Assert the runtime identity cannot read sibling paths or write at all. |
| Leak regression | Sentinel values and a sentinel token; assert absence from logs and error output. |

## 7. CI/CD and supply chain

- CI authenticates with a **JWT/OIDC auth method** bound by sub-claims to repository and branch; no access keys in CI variables.
- Pin SDK versions (they are regenerated often) and the CLI version; verify downloads.
- Secret scanning (gitleaks/trufflehog with custom rules for Akeyless access IDs/keys) plus pre-commit hooks.

## 8. Operations and incident response

- **Alerts:** auth failures by method, rule changes, Gateway health, approaching UID token expiry (notifications are available for longer-lived tokens).
- **Leak playbook (value):** rotate at source → update with a new version → confirm consumers refreshed → revoke old credential → review audit → remove leak path.
- **Leak playbook (access key/UID token):** delete or regenerate the key / revoke the token → review audit logs for its use → rotate every secret its roles could read.
- **Gateway outage:** decide whether apps may continue on cached values and for how long; test failover between Gateways.

## 9. Review checklist for the engineering agent

- [ ] No values, access keys, UID tokens, or session tokens in code, config, IaC, fixtures, or docs.
- [ ] Platform auth method per workload (or hardened API key with bound IPs and expiry).
- [ ] Role rules on the narrowest path prefix; readers and writers separate; sub-claims bind shared auth methods.
- [ ] Item paths fixed in configuration.
- [ ] Token refresh and one-shot re-auth implemented; timeouts set.
- [ ] Updates keep previous versions; delete protection on production secrets.
- [ ] No request bodies, SDK errors, or values in logs; SDK debug logging off.
- [ ] Rotation plan per secret (rotated/dynamic secrets considered).

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| One API key shared by many services | One auth method or sub-claim binding per workload |
| `akeyless create-secret --value "$SECRET"` in scripts | API/SDK with the value read from a file |
| `update-secret-val` without `keep-prev-version` | Keep versions; set `max-versions` |
| Role rule on `/*` for an app | Rule on `/prod/team/app/*` with `read` |
| Logging `ApiException.getMessage()` / npm rejection objects | Log the status code |
| Gateway port 8000 reachable from the internet | Internal-only, behind network policy |
| Assuming deleted secrets can be restored | Delete protection + documented retirement procedure |

## Sources

| ID | Source |
| --- | --- |
| S01 | [Auth methods overview](https://docs.akeyless.io/docs/access-and-authentication-methods) |
| S02 | [Universal Identity](https://docs.akeyless.io/docs/universal-identity) |
| S03 | [CLI reference: access roles](https://docs.akeyless.io/docs/cli-reference-access-roles) |
| S04 | [Update and version static secrets](https://docs.akeyless.io/docs/staticversions) |
| S05 | [Gateway installation](https://docs.akeyless.io/docs/install-and-configure-the-gateway) |
| S06 | [API: delete-item](https://docs.akeyless.io/reference/deleteitem) |
| S07 | [Static secrets overview](https://docs.akeyless.io/docs/static-secrets) |
