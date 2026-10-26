# OCI Vault secrets: building software around the API, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages secrets in Oracle Cloud Infrastructure Vault.  
**Companion:** [`../crud/oci-vault-secrets-crud-guide.md`](../crud/oci-vault-secrets-crud-guide.md) for exact calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the consumption pattern first

| Pattern | Use when | Hygiene cost |
| --- | --- | --- |
| **SDK + principal + in-process cache** | Code running on OCI compute, OKE, Functions | Lowest exposure; no stored credential |
| **OKE Secrets Store CSI Driver (OCI provider)** | Pods that need files | Files on tmpfs; enable rotation polling |
| **Service-native integration** (for example Autonomous Database credentials from Vault) | The OCI service reads the secret itself | Nothing in app code |
| **REST + API signing key** (CRUD guide REST programs) | Workloads outside OCI, or languages without an SDK | The API private key is itself a long-lived secret to protect and rotate |

**Default:** inside OCI, an SDK language with instance, resource, or OKE workload-identity principals. Outside OCI, prefer short-lived **session tokens** for humans and a dedicated service user's API key (kept in a different secrets store, rotated) for machines, or a federation path your organization supports.

## 2. Identity and policy design

1. **Principals over keys.** Dynamic groups for instances; resource principals for Functions; OKE workload identity (policy conditions on namespace and service account) for pods.
2. **Policy per workload, per secret.** `read secret-bundles … where target.secret.name = '<name>'` (or `target.secret.id`) for runtime. Writers get `manage secrets` scoped by `target.vault.id`, plus `use vaults` and `use keys` (required for create). [S01]
3. **Compartments per environment** and, ideally, a vault per environment or application. Vault and key administration (`manage vaults`, `manage keys`) belongs to a separate security group.
4. **Separate read and write endpoints in network design:** the retrieval host (`secrets.vaults.<region>…`) returns contents; the management host (`vaults.<region>…`) does not. Private endpoints and service gateways keep both off the internet.
5. **Master key hygiene:** use a dedicated symmetric key per vault/purpose; restrict `use keys` with `target.key.id`; plan key rotation (OCI re-encrypts new versions with the new key version).
6. **API keys (where unavoidable):** one key per service user, 2048+ bit RSA, stored with `0600` permissions outside the repository and image, rotated on a schedule; remove unused keys from the user. Upload only the public key.

## 3. Code structure

```java
// Port seen by business code; only the adapter imports com.oracle.bmc.*
public interface SecretSource {
    byte[] get(String secretOcid);      // cached, returns a copy
    void invalidate(String secretOcid); // after a downstream auth failure
}
```

Adapter rules:

- **One `VaultsClient` and one `SecretsClient` per process**, sharing one authentication provider; they are thread-safe and refresh principal tokens automatically.
- **Configuration holds OCIDs**, never contents (`DB_SECRET_OCID=ocid1.vaultsecret…`). Prefer OCIDs to names: names are unique only per vault and can be reused after deletion.
- **Respect the asynchronous lifecycle:** after create/update, wait for `ACTIVE` (SDK waiters) before reading or issuing another update.
- **Idempotency:** `opc-retry-token` on creates; `if-match` ETags on updates and deletion scheduling in automation.
- **Cache** reads with TTLs and single-flight; refresh on downstream authentication failure once.
- **Base64 handling:** decode once at the edge, keep bytes, never log either form.
- **For REST signing implementations:** sign exactly the bytes you send; keep the signing key in memory only; enforce HTTPS; fail on clock skew rather than retrying blindly.

## 4. Lifecycle: provision, rotate, retire

**Provisioning:**

- Terraform `oci_vault_secret` takes `secret_content.content` (base64) and stores it in state. Keep secret *values* out of Terraform where possible: let OCI **generate** content (`enable_auto_generation` with a generation context), or set values through a separate, audited pipeline. Treat any state that held a value as secret.
- Use `secret_rules` for expiry (version 1–90 days; absolute 1–365 days) and reuse prevention where policy demands it. [S02]

**Rotation:**

- Use OCI's automatic rotation for supported targets (`rotation_config` with a target system such as Autonomous Database, or a Function).
- Otherwise: create the new credential at the source → write a `PENDING` version → update consumers/target → promote with `currentVersionNumber` → revoke the old credential.
- Consumers read `CURRENT` and refresh on authentication failure.

**Retire:** schedule deletion (1–30 days; choose the longest window your process tolerates), watch audit events for failed reads, cancel if something breaks. Revoke at the source separately.

## 5. Logging, telemetry, and error hygiene

- **OCI Audit** records Vault and Secrets API calls (who, what, when, which OCID); it does not record contents. Route audit logs to Logging Analytics or your SIEM and alert on reads by unexpected principals.
- Keep SDK debug logging and CLI `--debug` off around secret operations; they can print request/response bodies.
- Application logs carry OCIDs, version numbers, `opc-request-id`, and status codes only.
- Disable or scrub heap/core dumps of processes that cache secrets.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `SecretSource`; generated bytes. |
| Adapter | SDK mocks or a signature-verifying HTTPS mock (as used for the CRUD guide) to test 401/404/409 handling and `ACTIVE` waits. |
| Integration | A sandbox compartment and vault; unique secret names per run; schedule deletion (1 day) in teardown. |
| Rotation | Exercise `PENDING → CURRENT` promotion against a staging target. |
| Leak regression | Sentinel content; assert absence from logs, including the base64 form. |

## 7. CI/CD and supply chain

- CI outside OCI: a dedicated service user with an API key held in the CI platform's secret store, scoped to the minimal group; rotate the key; or OCI's identity-propagation/federation options if your tenancy supports them for your CI.
- CI that deploys infrastructure needs `manage secret-family` only if it manages secrets; most deploy jobs need neither `read secret-bundles` nor key permissions.
- Pin SDK versions (they release frequently); review upgrades; scan dependencies and repositories (OCI API private keys and config files are high-severity findings).

## 8. Operations and incident response

- **Alerts:** reads of production secret bundles by new principals; policy changes touching `secret-family`, `keys`, or `vaults`; `ScheduleSecretDeletion`; key disable/schedule-deletion (which makes secrets unreadable).
- **Cloud Guard** detectors for IAM and Vault misconfiguration.
- **Leak playbook:** rotate at source → update secret (new `CURRENT`) → confirm consumers moved → schedule deletion of old versions where policy allows → revoke the old credential → find and remove the leak path → review Audit.
- **API key leak:** delete the key from the user immediately (`oci iam user api-key delete`), review Audit for its fingerprint, rotate anything it could read.

## 9. Review checklist for the engineering agent

- [ ] No secret contents, API private keys, or `~/.oci/config` files in code, images, IaC, fixtures, or docs.
- [ ] Principals used inside OCI; API keys only outside OCI, scoped and rotated.
- [ ] Policies grant `read secret-bundles` per secret for runtime; `manage secrets` + `use vaults` + `use keys` only for writers.
- [ ] OCIDs (not names) in configuration.
- [ ] Waits for `ACTIVE`; `opc-retry-token` on creates; ETags in automation.
- [ ] Cache + refresh-on-auth-failure; fail-fast startup.
- [ ] No debug logging; no contents (raw or base64) in logs, errors, or traces.
- [ ] Terraform does not carry values (generation, or out-of-band writes); state protected.
- [ ] Deletion window chosen deliberately; cancellation tested.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Copy a developer's `~/.oci/config` and key into a container | Instance/resource/workload principal |
| `--secret-content-content` on the CLI | `--from-json file://…` with a `0600` file, or SDK |
| Read immediately after create/update | Wait for `ACTIVE` |
| Address secrets by name in long-lived config | Address by OCID |
| One tenancy-wide `manage secret-family` policy for apps | Per-secret `read secret-bundles` conditions |
| Treat base64 as obfuscation | Treat it as plaintext |
| Schedule deletion with the minimum window "to clean up fast" | Longest acceptable window; watch for failed reads |

## Sources

| ID | Source |
| --- | --- |
| S01 | [Vault policy reference](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/keypolicyreference.htm) |
| S02 | [Creating a secret (rules, limits)](https://docs.oracle.com/iaas/Content/KeyManagement/Tasks/managingsecrets_topic-To_create_a_new_secret.htm) |
| S03 | [SDK authentication methods](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdk_authentication_methods.htm) |
| S04 | [Request signatures](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/signingrequests.htm) |
| S05 | [Deleting a secret](https://docs.oracle.com/en-us/iaas/Content/KeyManagement/Tasks/managingsecrets_topic-To_delete_a_secret.htm) |
| S06 | [OCI Audit overview](https://docs.oracle.com/en-us/iaas/Content/Audit/Concepts/auditoverview.htm) |
