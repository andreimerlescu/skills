# AWS Secrets Manager: building software around the API, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating an application that consumes or manages secrets in AWS Secrets Manager.  
**Companion:** [`../crud/aws-secrets-manager-crud-guide.md`](../crud/aws-secrets-manager-crud-guide.md) for exact API calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

The CRUD guide answers "how do I call the API correctly." This document answers "how should the software around those calls be shaped so that secrets stay secret, rotate cleanly, and fail safely." Every rule here is phrased so an agent can check it in a diff.

## 1. Choose the consumption pattern first

Decide how the running workload receives a secret **before** writing code. Prefer the option that puts the least plaintext in the fewest places while still supporting rotation.

| Pattern | Use when | Rotation story | Hygiene cost |
| --- | --- | --- | --- |
| **In-process SDK fetch + TTL cache** (CRUD guide §9) | Long-running services you own | Re-read on TTL expiry and on auth failure | Lowest exposure; you own retry/caching code |
| **AWS caching component** (Java, Python, .NET, Go, Rust) | Same as above, less code | TTL-driven | Configure TTL < rotation overlap |
| **Workload Credentials Provider / Lambda extension** (localhost:2773) | Lambda, mixed-language fleets, legacy apps | TTL; `refreshNow=true` | Localhost HTTP + SSRF token; cached plaintext in agent memory |
| **EKS Secrets Store CSI Driver (ASCP)** | Kubernetes workloads that must read files | Rotation reconciler polling | Files on tmpfs; avoid syncing to Kubernetes `Secret` unless required |
| **ECS task definition `secrets`** | Simple containers, static config | Requires task restart | Env vars leak via `/proc`, crash reporters, child processes |
| **Build-time injection** | Never | — | Secret baked into image/artifact; treat as a leak |

**Default for new services:** in-process fetch through an abstraction (section 3) with a TTL cache and refresh-on-authentication-failure. Use the CSI driver or task-definition injection only when the application cannot be changed.

## 2. Identity and access design

1. **Workload identity only.** The application authenticates with a role: ECS task role, EKS Pod Identity/IRSA, Lambda execution role, EC2 instance profile, or OIDC federation for CI. No `AWS_ACCESS_KEY_ID` in application configuration, images, or repositories. A long-term key is a finding.
2. **Split reader and writer roles.** Runtime roles get `secretsmanager:GetSecretValue` (plus `kms:Decrypt` for a customer managed key) on named ARNs. Provisioning/rotation roles get `CreateSecret`, `PutSecretValue`, `UpdateSecretVersionStage`, `DeleteSecret`, `RestoreSecret`, `TagResource`. Nobody needs `secretsmanager:*`.
3. **Scope by name prefix and environment.** Use names like `<app>/<env>/<purpose>` and grant `arn:aws:secretsmanager:<region>:<acct>:secret:<app>/<env>/*`. Prefer **separate AWS accounts** per environment over prefixes inside one account; a prefix is a convention, an account is a boundary.
4. **ABAC with care.** Tag-based conditions (`secretsmanager:ResourceTag/app`) scale well, but anyone who can `TagResource` can change access. Restrict tagging to the provisioning role.
5. **Resource policies** only for cross-account access. Any identity allowed `PutResourcePolicy` must have the `secretsmanager:BlockPublicPolicy = true` condition. [S01]
6. **KMS.** `aws/secretsmanager` is fine for single-account use. Use a customer managed key for cross-account access or separation of duties, and constrain it with `kms:ViaService = secretsmanager.<region>.amazonaws.com` and the Secrets Manager encryption context. [S01]
7. **Network.** Use an interface VPC endpoint for Secrets Manager. `aws:SourceVpce`/`aws:SourceVpc` conditions can break AWS services that call on your behalf (for example rotation); test before enforcing. Avoid `aws:SourceIp` for the same reason. [S01]

Least-privilege runtime policy template (agent: fill in exact ARNs; do not widen to `*`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadOwnSecrets",
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:billing/prod/db-??????",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:billing/prod/stripe-??????"
      ]
    },
    {
      "Sid": "DecryptViaSecretsManagerOnly",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/REPLACE_WITH_KEY_ID",
      "Condition": { "StringEquals": { "kms:ViaService": "secretsmanager.us-east-1.amazonaws.com" } }
    }
  ]
}
```

`-??????` matches exactly the six-character suffix Secrets Manager appends to every ARN, so `billing/prod/db-??????` does not also match `billing/prod/db-replica-AbCdEf`, which `db-*` would. Use full ARNs when the secrets already exist.

## 3. Code structure

Isolate Secrets Manager behind a small port so business code never imports the SDK and tests never need AWS.

```go
// secrets/port.go — the only interface business code sees.
type Provider interface {
    // Get returns the current value. Implementations cache and must be safe for concurrent use.
    Get(ctx context.Context, ref string) ([]byte, error)
    // Invalidate drops a cached value, e.g. after the downstream rejects a credential.
    Invalidate(ref string)
}
```

Rules for the adapter (an agent should verify each in review):

- **Construct the SDK client once** per process and reuse it; it is concurrency-safe and pools connections.
- **Reference secrets by ARN** in configuration (`DB_SECRET_ARN=arn:...`), never by value. Configuration files may contain ARNs; they must never contain values.
- **Cache with a TTL** (typically 5–15 minutes) shorter than the rotation overlap window, use single-flight so a cache miss under load produces one API call, and add jitter to expiry.
- **Refresh on authentication failure:** when a downstream returns "invalid credentials," call `Invalidate`, re-fetch once, retry once, then fail. This is what makes rotation seamless.
- **Fail fast at startup** if a required secret is missing or unreadable; do not start in a half-configured state. After startup, prefer serving with the last good cached value during a transient Secrets Manager outage, bounded by a maximum staleness.
- **Timeouts and retries:** set a context deadline on every call; use the SDK `standard` (or `adaptive`) retry mode; never write an unbounded retry loop.
- **Typed parsing:** if the secret is JSON, unmarshal into a struct with only the fields you need, and validate presence. Never pass the raw JSON string around.
- **Narrow lifetime:** return the value to the call site that uses it (DSN builder, HTTP client constructor). Do not store it in global config objects that get logged or serialized.
- **No secrets in exceptions:** wrap errors with the ARN and AWS error code; never with the value or the full request.

## 4. Lifecycle: provision, rotate, revoke, delete

**Provisioning (infrastructure as code).** Create the secret *container* (name, KMS key, policy, tags, rotation config) in IaC. Treat secret *values* separately:

- Terraform/OpenTofu: a value set through `secret_string` lands in plaintext in state. Prefer the write-only `secret_string_wo` with `secret_string_wo_version` (Terraform 1.11+, recent AWS provider) so the value never persists in state or plan, or let rotation populate the first value. Increment the version argument to push a new write-only value. [S02] [S03]
- CloudFormation: use `GenerateSecretString` for generated values, or dynamic references (`{{resolve:secretsmanager:...}}`) to consume without copying.
- Never put a literal value in IaC source, CI variables printed in logs, or pull-request descriptions.

**Rotation.**

- Prefer **managed rotation** (for supported services such as RDS) or a rotation Lambda. Rotation can run as often as every 4 hours. [S01]
- Choose **alternating users** (two credentials, swap which is current) for systems that cannot tolerate a brief window where only the new password works; choose **single user** where clients re-read promptly.
- Consumers must read `AWSCURRENT` only, never pin a `VersionId`, and refresh on auth failure.
- Rotation that only writes Secrets Manager without changing the credential at the source is not rotation. The source change and the `AWSPENDING → AWSCURRENT` move must be one orchestrated flow.

**Revocation and deletion.**

- On suspected exposure: rotate first (new value at source + `PutSecretValue`), confirm consumers picked it up, then revoke the old credential at the source. Deleting the secret does not revoke anything.
- Delete with a recovery window (7–30 days). Alarm on any `GetSecretValue` for that ARN during the window to discover forgotten consumers. Use `ForceDeleteWithoutRecovery` only for secrets that were never used or were created by a test.

## 5. Logging, telemetry, and error hygiene

- **SDK debug logging off in real environments.** botocore `DEBUG`, Go v2 `aws.LogResponseWithBody`, Java wire logging, and .NET response logging print response bodies containing `SecretString`. Guard with configuration that cannot be enabled by an environment variable in production.
- **Structured logs carry identifiers, not values:** secret ARN (or a hash of it), version ID, AWS request ID, error code, latency.
- **Tracing:** do not attach request/response bodies to spans for the Secrets Manager client or for downstream calls that carry the credential (database connect strings, `Authorization` headers).
- **Crash and core dumps:** disable or scrub in production; heap dumps contain cached secrets. Restrict who can trigger profilers and debuggers in production.
- **Redaction as defense in depth:** a log redactor for known secret shapes is useful but is not the control. The control is never handing the value to a logger.
- **CloudTrail is the audit trail.** It records who called `GetSecretValue` on what, but not the value. Keep it enabled organization-wide and route Secrets Manager data events to your SIEM.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Inject a fake `Provider` returning generated values (`crypto/rand`), never real secrets or realistic-looking keys that trip scanners. |
| Adapter | Stub the SDK (botocore `Stubber`, Go `smithy-go` middleware stubs, `aws-sdk-client-mock` for JS) to test error mapping: `ResourceNotFoundException`, `DecryptionFailure`, throttling, scheduled deletion. |
| Integration | A dedicated sandbox account with a unique prefix per test run, cleaned up with `ForceDeleteWithoutRecovery` (test-created secrets only). Emulators such as LocalStack are fine for request shapes, not for IAM/KMS semantics. |
| Rotation | Run rotation in staging and assert that consumers keep working across the `AWSPENDING → AWSCURRENT` transition. |
| Regression for leaks | A test that sets a sentinel secret, exercises error paths, and asserts the sentinel never appears in captured logs. |

## 7. CI/CD and supply chain

- CI authenticates to AWS with **OIDC federation** to a role scoped to the pipeline's needs; no stored AWS keys in CI.
- Pipelines that deploy secret **containers** do not need `GetSecretValue`.
- Pin SDK versions; update them through reviewed dependency PRs; enable dependency vulnerability scanning.
- Run secret scanning (for example gitleaks, trufflehog, GitHub secret scanning, Amazon CodeGuru Reviewer's secrets detector) on every push and on history at onboarding. [S01]
- Do not echo environment variables in CI steps; mask is a display feature, not a control.

## 8. Operations and incident response

- **Inventory:** every secret has `owner`, `app`, `env`, and `rotation` tags (non-sensitive), and a documented consumer list.
- **Alerts:** `GetSecretValue` from unexpected principals or networks; `PutResourcePolicy`, `DeleteSecret`, `RestoreSecret`, KMS key policy changes; failed decrypts.
- **AWS Config / Security Hub:** enable the Secrets Manager controls (rotation enabled, rotation succeeded, unused secrets removed).
- **Leak playbook:** (1) rotate at source and in Secrets Manager; (2) verify consumers refreshed; (3) revoke the old credential; (4) find the leak path and remove the copy (logs, tickets, repos); (5) review CloudTrail for use of the leaked credential; (6) record the incident.
- **Break-glass:** a separate role with `GetSecretValue` on critical secrets, protected by MFA and alerting on every use.

## 9. Review checklist for the engineering agent

- [ ] No secret values, access keys, or realistic test secrets in code, config, IaC, fixtures, or docs.
- [ ] Application uses a role; no `AWS_ACCESS_KEY_ID` configuration path exists.
- [ ] IAM grants only the actions used, on exact ARNs or a tight prefix; reader and writer roles are separate.
- [ ] Secrets referenced by ARN; create stores and reuses the returned ARN.
- [ ] Single SDK client; context deadlines; SDK retry mode set; no unbounded loops.
- [ ] TTL cache, single-flight, refresh-on-auth-failure, fail-fast startup.
- [ ] JSON secrets parsed into typed structures; only needed fields kept.
- [ ] No SDK body/wire logging; no secret values in errors, logs, spans, metrics, or panics.
- [ ] Writes use `ClientRequestToken` correctly; create is never treated as upsert.
- [ ] Deletion uses a recovery window; force delete only for test-created secrets.
- [ ] Terraform does not store values in state (`*_wo` or rotation-populated).
- [ ] Rotation strategy documented and tested; consumers tolerate the transition.
- [ ] Secret scanning and dependency scanning enabled in CI.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| `aws secretsmanager create-secret --secret-string "$PASSWORD"` | `--secret-string file://...` from a `0600` file, or generate in-service |
| Fetch the secret on every request | TTL cache with refresh-on-auth-failure |
| Copy the value into an env var for "convenience" | Pass it directly to the client constructor that needs it |
| Pin `VersionId` in config | Read `AWSCURRENT` |
| One `secretsmanager:*` policy for all services | Per-service roles on exact ARNs |
| `PutSecretValue` in a tight loop (e.g. per deploy) | Write only when the value changes; respect the 10-minute guidance |
| Delete the secret to "revoke" a leaked key | Rotate and revoke at the source; then delete with a window |
| Store dev and prod secrets in one account distinguished by name | Separate accounts per environment |
| Log the parsed config object at startup | Log which ARNs were loaded and their version IDs |

## Sources

| ID | Source |
| --- | --- |
| S01 | [AWS Secrets Manager best practices](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html) |
| S02 | [Terraform write-only arguments](https://developer.hashicorp.com/terraform/language/resources/ephemeral/write-only) |
| S03 | [terraform-provider-aws issue #44590 (write-only secret versions)](https://github.com/hashicorp/terraform-provider-aws/issues/44590) |
| S04 | [Rotation strategies](https://docs.aws.amazon.com/secretsmanager/latest/userguide/rotating-secrets.html) |
| S05 | [Secrets Manager Agent / Workload Credentials Provider](https://docs.aws.amazon.com/secretsmanager/latest/userguide/secrets-manager-agent.html) |
| S06 | [CloudTrail logging for Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/monitoring-cloudtrail.html) |
