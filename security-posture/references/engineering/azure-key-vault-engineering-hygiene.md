# Azure Key Vault: building software around the secrets API, and what good hygiene looks like

**Audience:** an engineering agent (or engineer) designing, writing, reviewing, or operating software that consumes or manages secrets in Azure Key Vault.  
**Companion:** [`../crud/azure-key-vault-secrets-crud-guide.md`](../crud/azure-key-vault-secrets-crud-guide.md) for exact calls in ten languages. Cross-provider rules live in [`../../SKILL.md`](../../SKILL.md).  
**Documentation verified:** October 26, 2026

## 1. Choose the consumption pattern first

| Pattern | Use when | Rotation story | Hygiene cost |
| --- | --- | --- | --- |
| **SDK call + in-process cache** | Services you own (AKS, App Service, Functions, Container Apps, VMs) | TTL refresh; refresh on auth failure | Lowest exposure |
| **App Service / Functions Key Vault references** | Apps that read configuration from env/app settings | Versionless refs refresh within ~24 h or on restart | Value lands in environment variables |
| **AKS Secrets Store CSI Driver (Key Vault provider)** | Pods that need files | Enable rotation polling explicitly | tmpfs files; optional sync to Kubernetes `Secret` widens access |
| **Azure App Configuration with Key Vault references** | Centralized config with secrets mixed in | App resolves via its own identity | Two services to secure; still needs `Secrets User` |
| **Pipeline variable groups linked to Key Vault** | Build/deploy-time needs only | Per pipeline run | Never for runtime secrets; logs mask but do not protect |

**Default for new services:** SDK call through a small abstraction (section 3) with a cache, using managed identity or workload identity.

## 2. Identity and access design

1. **Managed identity or workload identity federation only.** No service-principal client secrets or certificates for workloads; a client secret just moves the bootstrap problem.
2. **Azure RBAC permission model** on every vault (not access policies). RBAC can scope to a single secret; access policies cannot, and anyone with `Contributor` on the vault can grant themselves access-policy rights.
3. **Role per purpose:** runtime → `Key Vault Secrets User` on specific secrets; rotation/provisioning → `Key Vault Secrets Officer` on the vault (or specific secrets); compliance → `Key Vault Reader`; purge → nobody by default (break-glass only).
4. **Vault per application per environment** (and per region if needed). Vaults are cheap; a shared vault means shared blast radius, shared throttling (4,000 ops/10 s per vault), and coarse audit trails. [S01]
5. **Network:** disable public network access; use a private endpoint; allow trusted Microsoft services only if a dependent service needs it. A `ForbiddenByFirewall` error is the network control working.
6. **Vault settings for production:** soft delete (default), **purge protection on**, retention set deliberately at creation (cannot change later), diagnostic settings sending `AuditEvent` logs to Log Analytics/SIEM. Enforce with Azure Policy (`Key vaults should have deletion protection enabled`, `Azure Key Vault should use RBAC permission model`, `should disable public network access`). [S02]
7. **Control plane vs data plane:** `Owner`/`Contributor` on the vault resource can change networking and RBAC; restrict these to the platform team and alert on role assignments at vault scope.

## 3. Code structure

```csharp
// Port used by business code; only the adapter references Azure.Security.KeyVault.Secrets.
public interface ISecretSource
{
    ValueTask<string> GetAsync(string name, CancellationToken ct);   // cached
    void Invalidate(string name);                                      // after downstream auth failure
}
```

Adapter rules:

- **One `SecretClient` per vault per process** (thread-safe, pooled). One credential instance shared by all Azure clients.
- **Explicit credential in production** (`ManagedIdentityCredential`/`WorkloadIdentityCredential`) or `DefaultAzureCredential` with `AZURE_TOKEN_CREDENTIALS=prod` (or equivalent exclusion options) so a stray developer credential or `AZURE_CLIENT_SECRET` cannot be picked up.
- **Configuration holds the vault URL and secret names**, never values. Version IDs only if your deploy process manages them.
- **Cache with TTL** (minutes), single-flight on misses, jitter; refresh on downstream authentication failure once.
- **Fail fast at startup** on 401/403/404; serve from the last good cache during brief 429/5xx bursts with a staleness bound.
- **Treat `SetSecret` as an upsert** in any code that writes; implement "create only" deliberately (see the CRUD guide) and serialize writers.
- **Typed parsing** of structured secrets; discard raw strings promptly.
- **Never log SDK response objects;** `SetSecret` responses include the value.

## 4. Lifecycle: provision, rotate, retire

**Provisioning (Bicep/ARM/Terraform):**

- Create vaults, networking, diagnostic settings, RBAC assignments, and secret *placeholders* in IaC.
- Bicep/ARM: secret values passed as parameters must be `@secure()`; never output them. Deployment history stores parameters; secure parameters are not persisted in plaintext, ordinary ones are.
- Terraform `azurerm_key_vault_secret.value` lands in state. Prefer write-only `value_wo` + `value_wo_version` (recent azurerm releases, Terraform 1.11+), or let a rotation job set the first value. [S03]

**Rotation:** Key Vault does not rotate secrets. Set `exp` on secrets that must rotate, subscribe an Event Grid handler to `SecretNearExpiry`, and have it (1) create the new credential at the source, (2) `SetSecret` the new version, (3) leave the old credential valid until consumers refresh, (4) revoke the old credential. For databases, prefer two alternating credentials. Remember `exp` does not block reads; it is a signal. [S04]

**Retire:** soft delete; watch `AuditEvent` logs for failed `SecretGet` during the retention window; never purge in production (purge protection makes this a non-option). Revoke the credential at the issuer separately.

## 5. Logging, telemetry, and error hygiene

- Keep SDK **content logging off** (`IsLoggingContentEnabled=false`, Python `logging_enable` off, Java `HttpLogDetailLevel.BASIC` or `NONE`). Headers are redacted by default; bodies are not.
- Application logs record vault name, secret name, version ID, status code, `x-ms-request-id`; never values.
- `AuditEvent` diagnostic logs are the authoritative access trail; they do not contain values.
- Application Insights / OpenTelemetry: do not add request/response bodies of Key Vault or of downstream calls that carry the credential.
- Disable or scrub memory dumps (App Service "auto-heal" dumps, Kubernetes core dumps) for processes that cache secrets.

## 6. Testing strategy

| Layer | Approach |
| --- | --- |
| Unit | Fake `ISecretSource` returning generated values. |
| Adapter | SDK test transports/mocks (Azure SDKs accept custom HTTP pipelines/transports) to exercise 404, 409 (soft-deleted), 403 (disabled), 429. The CRUD guide's HTTPS mock approach works for REST clients. |
| Integration | Sandbox vault **without** purge protection, unique names per run, purge in teardown. |
| Rotation | Event Grid → rotation function in staging; consumers must survive the switch. |
| Leak regression | Sentinel value + captured logs/telemetry must never contain it. |

## 7. CI/CD and supply chain

- Pipelines authenticate with **workload identity federation** service connections (Azure DevOps, GitHub OIDC); no client secrets in pipeline variables.
- Separate the deploy identity (control plane) from the identity that can read secret values; most deploys never need `Secrets User`.
- Pin SDK versions; review upgrades; run dependency and secret scanning.
- Do not `az keyvault secret show` in pipeline steps; use `download --file` into a temp directory removed at step end if a value must be materialized.

## 8. Operations and incident response

- **Alerts:** RBAC role assignments at vault scope, network rule changes, `SecretDelete`/`SecretPurge`, unusual `SecretGet` volume or principals, throttling.
- **Defender for Key Vault:** enable for anomaly detection.
- **Inventory:** tags `app`, `env`, `owner`, `rotation` on secrets; Azure Policy for expiration dates where rotation is required.
- **Leak playbook:** rotate at source → `SetSecret` → confirm consumers refreshed → disable the old version → revoke old credential → find and remove the leak path → review `AuditEvent` and source-system logs.
- **Break-glass:** PIM-eligible `Key Vault Secrets Officer`/`Administrator` with approval and alerting.

## 9. Review checklist for the engineering agent

- [ ] No values, client secrets, certificates, or realistic test secrets in code, config, IaC, fixtures, or docs.
- [ ] Workload uses managed identity or workload identity; no `AZURE_CLIENT_SECRET` in any deployment config.
- [ ] Vault uses RBAC; runtime role is `Secrets User` scoped as narrowly as practical.
- [ ] One vault per app per environment; public network access disabled or justified.
- [ ] Purge protection on for production; retention chosen deliberately.
- [ ] Single client; explicit credential; cache; refresh on auth failure; fail-fast startup.
- [ ] `SetSecret` treated as upsert; creators serialized; no logging of SDK responses.
- [ ] SDK content logging off; no values in logs, spans, errors, dumps.
- [ ] IaC does not persist values (secure params / `value_wo`).
- [ ] Rotation process documented; `exp` used as a signal with Event Grid, not as enforcement.

## 10. Anti-patterns

| Don't | Do instead |
| --- | --- |
| Service principal + client secret stored in App Settings to reach Key Vault | Managed identity |
| One shared vault for all apps and environments | Vault per app per environment |
| Access policies granting `get, list, set, delete` to everyone in a team | RBAC roles scoped to secrets |
| Rely on `exp` to stop use of an old secret | Rotate and revoke at the source |
| Disable the newest version to roll back | Re-set the previous value as a new version |
| `az keyvault secret show` in scripts | `download --file` or `--query id` |
| Purge in production cleanup scripts | Soft delete; let retention expire |
| Log the `KeyVaultSecret` object | Log name and version only |

## Sources

| ID | Source |
| --- | --- |
| S01 | [Key Vault service limits](https://learn.microsoft.com/en-us/azure/key-vault/general/service-limits) |
| S02 | [Secure your Azure Key Vault](https://learn.microsoft.com/en-us/azure/key-vault/general/secure-key-vault) |
| S03 | [Terraform write-only arguments](https://developer.hashicorp.com/terraform/language/resources/ephemeral/write-only) |
| S04 | [About Key Vault secrets](https://learn.microsoft.com/en-us/azure/key-vault/secrets/about-secrets) |
| S05 | [Azure RBAC for Key Vault](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide) |
| S06 | [Soft-delete overview](https://learn.microsoft.com/en-us/azure/key-vault/general/soft-delete-overview) |
| S07 | [Key Vault Event Grid events](https://learn.microsoft.com/en-us/azure/event-grid/event-schema-key-vault) |
