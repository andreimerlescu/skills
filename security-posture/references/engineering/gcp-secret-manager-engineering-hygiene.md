# Google Cloud Secret Manager: building software around the API, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages secrets in Google Cloud Secret Manager.  
**Companion:** [`../crud/gcp-secret-manager-crud-guide.md`](../crud/gcp-secret-manager-crud-guide.md) for exact calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the consumption pattern first

| Pattern | Use when | Rotation story | Hygiene cost |
| --- | --- | --- | --- |
| **Direct client call + in-process cache** | Services you own on GCE, GKE, Cloud Run, Functions, or elsewhere via Workload Identity Federation | Pinned version rolled by deploy, or `latest` with TTL refresh | Lowest exposure; Google's recommended default [S01] |
| **Cloud Run / Functions secret volume** | You cannot change code to call the API | `latest` re-read from the mount | File on an in-memory mount; path traversal risk |
| **Cloud Run / Functions secret env var** | Legacy apps reading env only | Resolved at instance start; pin a version | Env leaks via debug endpoints, crash reports, child processes [S01] |
| **GKE Secret Manager add-on / CSI driver** | Kubernetes pods that need files | Rotation reconciler | Avoid syncing into Kubernetes `Secret` objects unless you have evaluated access, audit, and encryption parity [S01] |
| **Build-time / image injection** | Never | — | A secret baked into an artifact is a leak |

**Default for new services:** call the API through a small abstraction (section 3) at startup and cache in memory. Pin version numbers in production configuration unless you have a reason to follow `latest`.

## 2. Identity and access design

1. **No service-account keys.** Workloads use the metadata server (attached service account), Workload Identity Federation for GKE, or Workload Identity Federation for AWS/Azure/CI. Enforce with the organization policy `constraints/iam.disableServiceAccountKeyCreation`. [S01] [S02]
2. **One service account per workload**, not a shared "secrets reader." It makes audit logs attributable and blast radius small.
3. **Grant on the secret, not the project.** `roles/secretmanager.secretAccessor` bound on each secret the workload reads. Project-level grants on a shared project give access to every secret in it.
4. **Separate readers from writers.** Runtime: `secretAccessor`. Rotation job: `secretVersionAdder` (adds versions, cannot read). Lifecycle automation: `secretVersionManager` (enable/disable/destroy, cannot read). Only provisioning pipelines hold `secrets.create`/`secrets.delete`.
5. **Separate projects per environment** (and per sensitive domain if needed). Use IAM Conditions on `resource.name` (project **number** form) only as a supplement in shared projects. [S01] [S03]
6. **Org-level guardrails:** `constraints/iam.allowedPolicyMemberDomains` (no external identities on secret policies), `constraints/gcp.resourceLocations` (residency), VPC Service Controls perimeter around `secretmanager.googleapis.com`. [S01]
7. **CMEK only when required** (separation of duties, key revocation as a kill switch). Grant the Secret Manager service agent `roles/cloudkms.cryptoKeyEncrypterDecrypter` on the key; disabling the key makes every version unreadable, so treat key operations as production changes.

## 3. Code structure

Business code depends on a port; only the adapter imports the Google client.

```python
# secrets/port.py
from typing import Protocol

class SecretSource(Protocol):
    def get(self, ref: str) -> bytes:
        """Return the payload for a configured reference such as
        'projects/123/secrets/billing-db/versions/7'. Implementations cache."""
    def invalidate(self, ref: str) -> None:
        """Drop a cached value after a downstream auth failure."""
```

Adapter rules (verify each in review):

- **One client per process**, created at startup and reused (all official clients pool connections and are thread-safe).
- **Configuration holds resource names**, ideally with explicit version numbers: `DB_SECRET=projects/123/secrets/billing-db/versions/7`. Never a value.
- **Verify CRC32C** on every access (the CRUD guide shows how in each language) and send it on every `AddSecretVersion`.
- **Cache** with a TTL appropriate to how you roll versions; use single-flight on misses; jitter refresh across instances to avoid synchronized spikes against the 90,000/min project access quota. [S04]
- **Refresh on downstream authentication failure** once, then fail loudly.
- **Deadlines** on every call; rely on the client library's retry policy for idempotent reads; do not wrap `AddSecretVersion` in a blind retry.
- **Typed parsing:** decode JSON payloads into a struct with only required fields, validate, and drop the raw bytes.
- **Narrow lifetime:** pass the value straight to the consumer (connection pool, HTTP client). Do not store it on global config objects that are logged, serialized, or exposed via debug endpoints.

## 4. Lifecycle: provision, rotate, retire

**Provisioning with Terraform/OpenTofu or Config Connector.** Create the secret resource, replication, IAM bindings, rotation schedule, Pub/Sub topics, and `version_destroy_ttl` in IaC. For values:

- `google_secret_manager_secret_version.secret_data` is stored in state in plaintext. Prefer the write-only `secret_data_wo` with `secret_data_wo_version` (bump the version to push a new value), or let a rotation job add the first version. [S05]
- Set `deletion_policy = "DISABLE"` (or `ABANDON`) on version resources so a Terraform refactor cannot destroy payloads. [S05]
- Use `lifecycle { prevent_destroy = true }` on production secret resources; `DeleteSecret` is immediate and irreversible.

**Rotation.** Secret Manager schedules and **notifies**; it does not rotate. Configure `rotation.rotation_period` + `next_rotation_time` and one or more Pub/Sub `topics`; a subscriber (Cloud Run job or function, running as an identity with `secretVersionAdder`) creates the new credential at the source, adds a version, and, after consumers move, disables the old version. Support two valid credentials during the overlap.

**Retirement.** Disable → wait and watch Data Access logs for `FAILED_PRECONDITION` reads → destroy (with delayed destruction configured) → delete the secret. Revoke the credential at its issuer independently; deleting a stored secret revokes nothing.

## 5. Logging, telemetry, and error hygiene

- Turn on **Data Access audit logs** for Secret Manager at the folder/organization level so every `AccessSecretVersion` is attributable; Admin Activity logs are always on. [S01]
- Application logs carry resource names, version numbers, gRPC codes, and latencies, never payloads.
- Keep gRPC/HTTP debug logging (`GRPC_TRACE`, `GRPC_VERBOSITY=debug`, client-library debug env vars, HTTP wire logs) off in environments with real secrets.
- Exclude secret-bearing fields from OpenTelemetry span attributes; the Google client libraries' tracing does not record payloads, but your own instrumentation might.
- Disable or scrub heap/core dumps; they contain cached payloads.
- Error Reporting: make sure exception messages and local variables captured by error reporters cannot include payloads.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource` returning generated bytes; never real or realistic secrets in fixtures. |
| Adapter | Use the client's stub/mock support (Rust `from_stub`, Go interface wrapper, Python fake client building real request protos as in the CRUD guide) to test `ALREADY_EXISTS`, `NOT_FOUND`, `FAILED_PRECONDITION`, `PERMISSION_DENIED`, CRC mismatch. |
| Integration | A sandbox project; unique secret IDs per run (`ci-<run-id>-…`); delete in teardown. |
| Rotation | Exercise the Pub/Sub-driven rotation in staging; assert consumers survive the version change. |
| Leak regression | Sentinel payload + log capture asserting the sentinel never appears. |

## 7. CI/CD and supply chain

- CI authenticates through **Workload Identity Federation** (GitHub/GitLab OIDC) to a dedicated service account; no JSON keys in CI variables.
- Deploy pipelines manage secret containers and IAM; they rarely need `versions.access`.
- Pin client library versions (Go modules, Cargo.lock, package-lock, BOM versions); review upgrades.
- Secret scanning on push and pre-commit; GCP key file patterns (`"type": "service_account"`) are high-severity findings.
- Never `gcloud secrets versions access` in a CI step whose logs are retained; if a job must materialize a value, write it with `--out-file` into a tmpfs path and delete it.

## 8. Operations and incident response

- **Inventory:** Cloud Asset Inventory queries for secrets without rotation, without CMEK where required, or outside allowed locations. [S01]
- **Labels:** `app`, `env`, `owner`, `data-class` (non-sensitive) on every secret.
- **Alerts:** access by unexpected principals; `SetIamPolicy` on secrets; `DeleteSecret`/`DestroySecretVersion`; KMS key disable/destroy; spikes in `PERMISSION_DENIED`.
- **Leak playbook:** rotate at source → add version → move consumers (pinned-version deploy or refresh) → disable old version → revoke old credential at issuer → find and purge the leak path → review Data Access logs for misuse.
- **Break-glass:** a separately monitored group with time-bound `secretAccessor` via IAM Conditions.

## 9. Review checklist for the engineering agent

- [ ] No payloads, service-account key files, or realistic test secrets in code, config, IaC, fixtures, or docs.
- [ ] Workload uses ADC from metadata/Workload Identity; no `GOOGLE_APPLICATION_CREDENTIALS` key file path in deploy config.
- [ ] `secretAccessor` granted per secret to a per-workload service account; writers and lifecycle roles separate.
- [ ] Production configuration references explicit version numbers (or a documented decision to follow `latest`).
- [ ] CRC32C sent on writes and verified on reads.
- [ ] Single client; deadlines; cache with jitter; refresh on auth failure; fail-fast startup.
- [ ] No debug/wire logging; no payloads in logs, errors, spans, metrics, dumps.
- [ ] `etag` used for automated delete/destroy/update decisions.
- [ ] Terraform uses `secret_data_wo`; versions have a non-`DELETE` `deletion_policy`; production secrets have `prevent_destroy`.
- [ ] Disable-before-destroy procedure documented; `version_destroy_ttl` set on important secrets.
- [ ] Data Access audit logs on; VPC-SC/org policies considered.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Download a service-account key to "test quickly" | `gcloud auth application-default login` locally; Workload Identity Federation elsewhere |
| Grant `secretAccessor` at project level in a shared project | Bind per secret |
| `echo "$TOKEN" \| gcloud secrets versions add …` in CI | `--data-file` from a tmpfs file, or add versions from the rotation job |
| Read `latest` on every request | Startup read + cache; pinned versions for production |
| Destroy a version to "roll back" | Disable the bad version; `latest` falls back to the previous enabled one |
| Expiration on production secrets | IAM Conditions for time-bound access |
| Sync every secret into Kubernetes `Secret` objects | Mount via CSI only what is needed, or call the API |
| Treat `DeleteSecret` as revocation | Revoke at the issuer, then retire the secret |

## Sources

| ID | Source |
| --- | --- |
| S01 | [Secret Manager best practices](https://docs.cloud.google.com/secret-manager/docs/best-practices) |
| S02 | [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) |
| S03 | [Secret Manager access control](https://docs.cloud.google.com/secret-manager/docs/access-control) |
| S04 | [Secret Manager quotas](https://docs.cloud.google.com/secret-manager/quotas) |
| S05 | [SecretVersion resource (Terraform/Pulumi registry, write-only and deletion policy)](https://www.pulumi.com/registry/packages/gcp/api-docs/secretmanager/secretversion) |
| S06 | [Rotation and event notifications](https://cloud.google.com/secret-manager/docs/event-notifications) |
