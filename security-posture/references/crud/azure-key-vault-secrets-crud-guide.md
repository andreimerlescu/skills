# Azure Key Vault secrets: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** Azure Key Vault data plane, secrets API, `api-version=2025-07-01` (the default of the current SDKs)  
**Primary authentication:** Microsoft Entra ID tokens from a managed identity or workload identity federation, resolved by `DefaultAzureCredential` or an explicit credential  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use Bash and the Azure CLI)

This guide covers **secrets in an Azure Key Vault** (not Managed HSM, keys, or certificates): each secret is a named object with an ordered set of immutable **versions**, protected by mandatory-by-default **soft delete**. It covers identity checks, Azure RBAC, complete CRUD workflows (including soft delete, recovery, and purge), a full CRUD program in each of ten languages, runtime consumption, and troubleshooting. Vault provisioning (networking, SKU, purge-protection settings) is covered only where it changes CRUD behavior.

Credentials are assumed to be provisioned already. Do not create client secrets or certificates for application identities to follow this guide; use managed identity or workload identity federation.

**Verification boundary:** Behavior was cross-checked against the official REST reference and SDK sources in section 14. The Go program passed `go vet` against `azsecrets v1.5.0`/`azidentity v1.15.0`; the Rust program passed `cargo check` against `azure_security_keyvault_secrets 1.0.1`/`azure_identity 1.0.0`; the TypeScript program passed `tsc --strict` against `@azure/keyvault-secrets 4.11.2`. The Python SDK program, the PHP REST program, and the C REST program ran end-to-end against a local HTTPS mock of the Key Vault secrets API (including the bearer-challenge flow, soft-delete conflict, and purge) and, for PHP and C, a mock Entra token endpoint exercising the workload-identity client-assertion exchange. The C#, Java, and C++ programs were checked against SDK sources (`Azure.Security.KeyVault.Secrets`, `azure-security-keyvault-secrets` for Java and C++) but not compiled here; Swift was written against the REST surface and not compiled. No call was made to a real Azure tenant. Section 12 provides an optional live test.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Use the existing identity](#2-use-the-existing-identity)
3. [Data model and addressing](#3-data-model-and-addressing)
4. [Safe secret handling](#4-safe-secret-handling)
5. [Create secrets](#5-create-secrets)
6. [Read secrets](#6-read-secrets)
7. [Update secrets](#7-update-secrets)
8. [Delete, recover, and purge](#8-delete-recover-and-purge)
9. [Language implementations](#9-language-implementations)
10. [Use secrets in applications](#10-use-secrets-in-applications)
11. [Automation and error handling](#11-automation-and-error-handling)
12. [Optional live CRUD verification](#12-optional-live-crud-verification)
13. [Troubleshooting](#13-troubleshooting)
14. [Accuracy notes and official sources](#14-accuracy-notes-and-official-sources)

## 1. Requirements and conventions

| Language | Official client | Transport used here | Verified here |
| --- | --- | --- | --- |
| Go | `github.com/Azure/azure-sdk-for-go/sdk/security/keyvault/azsecrets` + `azidentity` | SDK | `go vet` (v1.5.0) |
| Rust | `azure_security_keyvault_secrets` + `azure_identity` | SDK | `cargo check` (1.0.1) |
| PHP | none (no official Azure SDK for PHP) | REST via ext-curl | mock run |
| C# | `Azure.Security.KeyVault.Secrets` + `Azure.Identity` | SDK | source check |
| Java | `com.azure:azure-security-keyvault-secrets` + `azure-identity` | SDK | source check |
| Swift | none | REST via `URLSession` | not compiled |
| Python | `azure-keyvault-secrets` + `azure-identity` | SDK | mock run |
| TypeScript | `@azure/keyvault-secrets` + `@azure/identity` | SDK | `tsc --strict` (4.11.2) |
| C++ | `azure-security-keyvault-secrets-cpp` + `azure-identity-cpp` | SDK | header check |
| C | none | REST via libcurl + cJSON | compiled, mock run |

Every program follows the same contract:

- Non-secret configuration: `AZURE_KEYVAULT_URL` (`https://<vault>.vault.azure.net/`) and `SECRET_NAME`.
- It generates a 256-bit random value with the platform CSPRNG, **creates** the secret only if the name is unused, **reads** and compares in constant time, **updates** (new version), reads and compares again, then **soft-deletes** and waits until the deleted entry is visible. With `PURGE_AFTER_DELETE=1` it also **purges**.
- It prints names and version IDs only, never values.

For CLI snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
az version --query '"azure-cli"' -o tsv
VAULT='REPLACE_WITH_VAULT_NAME'
```

## 2. Use the existing identity

### Credential sources

`DefaultAzureCredential` tries a chain; production workloads should use one explicit source. [S02]

| Environment | Credential | Configuration |
| --- | --- | --- |
| AKS | Workload identity (federated) | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_FEDERATED_TOKEN_FILE`, `AZURE_AUTHORITY_HOST` injected by the webhook |
| VM, VMSS, App Service, Functions, Container Apps | Managed identity | IMDS (`169.254.169.254`) or `IDENTITY_ENDPOINT`/`IDENTITY_HEADER`; `AZURE_CLIENT_ID` selects a user-assigned identity |
| GitHub Actions, other CI | Workload identity federation | OIDC token exchanged for an Entra token |
| Developer workstation | Azure CLI / Developer CLI / IDE login | Human credentials; never shipped to a workload |
| `AZURE_CLIENT_SECRET` / certificate | Service principal secret | Avoid for workloads; it is another secret to rotate and leak |

If `AZURE_CLIENT_SECRET` is set in a workload's environment, `DefaultAzureCredential` may pick an environment credential before managed identity. Remove it rather than relying on chain order.

### Confirm identity without displaying a token

```bash
az account show --query '{tenant:tenantId, user:user.name, type:user.type}' -o json
```

Do not run `az account get-access-token` in shared terminals or CI logs; it prints a bearer token.

### Required permissions (Azure RBAC)

Use the vault's **Azure RBAC** permission model (the legacy access-policy model is still supported but cannot scope to individual secrets). Assign roles at the **secret** scope where practical. [S03]

| Role | Grants | Typical holder |
| --- | --- | --- |
| Key Vault Secrets User | Read secret contents | Runtime workload |
| Key Vault Secrets Officer | All secret operations except permission management (create/set, get, list, delete, recover, backup/restore, purge) | Provisioning/rotation automation |
| Key Vault Reader | Metadata only, no secret values | Inventory/compliance |
| Key Vault Purge Operator / Administrator | Purge deleted objects; full data-plane control | Break-glass only |

```bash
# Runtime identity: read one secret
az role assignment create --role 'Key Vault Secrets User' \
  --assignee-object-id 'REPLACE_WITH_PRINCIPAL_OBJECT_ID' --assignee-principal-type ServicePrincipal \
  --scope "$(az keyvault show -n "$VAULT" --query id -o tsv)/secrets/myapp-prod-db"
```

Data-plane access is also gated by the vault firewall/private endpoint. A `403 ForbiddenByFirewall` is a network problem, not an RBAC problem.

## 3. Data model and addressing

- **Secret identifier:** `https://<vault>.vault.azure.net/secrets/<name>/<version>`. Omitting the version means "current."
- **Name:** 1–127 characters, ASCII letters, digits, and hyphens. Names are case-insensitive. [S04]
- **Value:** stored as octets, up to 25 KB. Binary data must be encoded (for example base64) by the application; set `contentType` to say so. [S04]
- **Versions:** every `SetSecret` (`PUT`) creates a new version (a 32-hex-character ID) that becomes current. Versions cannot be deleted individually; disable one with `UpdateSecretProperties(enabled=false)`. Key Vault does not limit versions, but 500+ versions hurt backup. [S05]
- **Attributes:** `enabled`, `nbf` (not before), `exp` (expires), `recoveryLevel`, `recoverableDays`; plus `contentType` (max 255 characters) and `tags`. For secrets, `nbf`/`exp` are informational: `GetSecret` still returns not-yet-valid and expired secrets, so enforce expiry in your own code or process. A **disabled** version cannot be retrieved. [S04]
- **Soft delete:** on by default for new vaults and cannot be turned off once on. Deleted secrets are retained 7–90 days (set at vault creation, default 90) and the **name stays reserved**. **Purge protection** (optional) blocks purge until retention ends. [S06]

Inventory without values:

```bash
az keyvault secret list --vault-name "$VAULT" \
  --query '[].{name:name, enabled:attributes.enabled, updated:attributes.updated, tags:tags}' -o table
az keyvault secret list-versions --vault-name "$VAULT" --name myapp-dev-api-token \
  --query '[].{version:id, enabled:attributes.enabled, created:attributes.created}' -o table
az keyvault secret list-deleted --vault-name "$VAULT" --query '[].{name:name, purge:scheduledPurgeDate}' -o table
```

List operations never return values.

## 4. Safe secret handling

- **Command lines:** `az keyvault secret set --value '...'` puts the value in shell history and the process table. Use `--file` (with `--encoding utf-8` or `base64`).
- **`show` prints values:** `az keyvault secret show` returns the value in its JSON. Use `az keyvault secret download --file` to write a private file instead.
- **SDK logging:** Azure SDK HTTP logging redacts the `Authorization` header and most query parameters, but request and response **bodies** are logged when content logging is enabled (Python `logging_enable=True`, .NET `IsLoggingContentEnabled`, Java `HttpLogDetailLevel.BODY_AND_HEADERS`, Go `azcore` log with `EventResponse` bodies). Bodies contain secret values. Keep content logging off.
- **Diagnostic logs:** Key Vault `AuditEvent` logs record who called `SecretGet`/`SecretSet` but not values. Route them to Log Analytics or a SIEM.
- **Responses echo values:** a `SetSecret` response includes the value it stored. Do not log or cache full response objects.
- **Memory:** wipe byte buffers where possible (`zeroize`, `OPENSSL_cleanse`, `CryptographicOperations.ZeroMemory`); keep managed strings in narrow scopes.

## 5. Create secrets

**`SetSecret` is an upsert.** If the name exists, it silently adds a new version. Key Vault offers no conditional "create if absent," so every program here implements create as: `GetSecret` → expect 404 → `SetSecret`. That check-then-set is not atomic; serialize creators of the same name (one provisioning pipeline per vault, or a lock) if overwrite would be harmful.

A `409 Conflict` on set means a **soft-deleted** secret with that name exists. Recover it (to keep history) or purge it (if allowed) before reusing the name.

### A. Create from a protected file

```bash
SECRET_FILE='/secure/path/to/api-token.txt'   # exists, mode 0600
if az keyvault secret show --vault-name "$VAULT" --name myapp-dev-api-token --query id -o tsv > /dev/null 2>&1; then
  printf 'already exists; refusing to overwrite\n' >&2
else
  az keyvault secret set --vault-name "$VAULT" --name myapp-dev-api-token \
    --file "$SECRET_FILE" --encoding utf-8 \
    --content-type text/plain --tags app=myapp env=dev \
    --query '{id:id}' -o json
fi
```

(`--query id` keeps the value out of the `show` output.) `--file` stores the file's exact content, including any trailing newline.

### B. Create with an expiry and activation date

```bash
az keyvault secret set --vault-name "$VAULT" --name myapp-dev-partner-key \
  --file "$SECRET_FILE" --encoding utf-8 \
  --expires "$(date -u -d '+90 days' +%Y-%m-%dT%H:%M:%SZ)" \
  --not-before "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --query id -o tsv
```

For secrets, `exp` and `nbf` do not block reads; they drive Event Grid `SecretNearExpiry`/`SecretExpired` events and policy compliance. Pair them with a rotation process and, if expiry must be enforced, check `attributes.exp` in your own code. [S04]

## 6. Read secrets

`GetSecret(name)` returns the current version; `GetSecret(name, version)` returns a specific one. A disabled version returns 403 (`Forbidden`); expired and not-yet-valid secrets are still returned (their dates are informational for secrets). [S04]

```bash
# Write the current value to a new private file
az keyvault secret download --vault-name "$VAULT" --name myapp-dev-api-token \
  --file ./api-token.secret --encoding utf-8

# A specific version
az keyvault secret download --vault-name "$VAULT" --name myapp-dev-api-token \
  --version 'REPLACE_WITH_VERSION_ID' --file ./api-token.prev.secret --encoding utf-8

# Check JSON structure without printing it
az keyvault secret show --vault-name "$VAULT" --name myapp-dev-db --query value -o tsv |
  jq -e 'has("username") and has("password")' > /dev/null && printf 'structure ok\n'
```

Throttling is per vault per region: **4,000 transactions per 10 seconds** for most operations (including gets) and **300 per 10 seconds** collectively for secret creates, certificate imports, and key imports; subscription-wide limits are five times the per-vault limit. Cache values in process. [S05]

## 7. Update secrets

| Operation | Effect |
| --- | --- |
| `SetSecret` (`PUT /secrets/{name}`) | New value → new version, which becomes current. Previous versions remain readable by version ID. |
| `UpdateSecretProperties` (`PATCH /secrets/{name}/{version}`) | Change `enabled`, `exp`, `nbf`, `contentType`, `tags` of one version. Cannot change the value. |

```bash
# New value from a protected file
az keyvault secret set --vault-name "$VAULT" --name myapp-dev-api-token \
  --file "$SECRET_FILE" --encoding utf-8 --query id -o tsv

# Metadata-only update on the current version
az keyvault secret set-attributes --vault-name "$VAULT" --name myapp-dev-api-token \
  --tags app=myapp env=dev owner=platform-team

# Roll back: disable the bad version; then re-set the previous value as a new version
az keyvault secret set-attributes --vault-name "$VAULT" --name myapp-dev-api-token \
  --version 'REPLACE_WITH_BAD_VERSION' --enabled false
```

Disabling the newest version does **not** make the previous version current; `GetSecret(name)` then fails with 403. To roll back, read the previous version by ID and `SetSecret` it again as a new version.

Verify a replacement without printing values:

```bash
(
  set -euo pipefail; umask 077
  work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
  az keyvault secret download --vault-name "$VAULT" --name myapp-dev-api-token \
    --file "$work/readback" --encoding utf-8
  cmp -s "$work/readback" "$SECRET_FILE" && printf 'Secret replacement verified.\n'
)
```

Storing a new value does not rotate the credential at its source. Key Vault has no built-in rotation for secrets; use Event Grid events (`SecretNewVersionCreated`, `SecretNearExpiry`, `SecretExpired`) to trigger a rotation function that changes the credential at the source and then sets the new version.

## 8. Delete, recover, and purge

| Operation | REST | Reversible | Notes |
| --- | --- | --- | --- |
| Delete | `DELETE /secrets/{name}` | Yes, during retention | Soft delete. All versions move to the deleted state; name is reserved. Long-running in SDKs (`StartDeleteSecret`/`beginDeleteSecret`). |
| Recover | `POST /deletedsecrets/{name}/recover` | — | Restores all versions. Long-running. |
| Purge | `DELETE /deletedsecrets/{name}` | **No** | Permanent. Blocked by purge protection until retention ends (`403`). Requires purge permission. |

```bash
# Inspect the exact target (metadata only)
az keyvault secret show --vault-name "$VAULT" --name myapp-dev-api-token --query '{id:id, tags:tags}'

# Soft delete
az keyvault secret delete --vault-name "$VAULT" --name myapp-dev-api-token

# Recover during the retention window
az keyvault secret recover --vault-name "$VAULT" --name myapp-dev-api-token

# Permanent purge (deliberate, reviewed use only; fails with purge protection)
az keyvault secret purge --vault-name "$VAULT" --name myapp-dev-api-token
```

A purge immediately after delete can fail while the delete is still completing; wait for the deleted entry to appear (`az keyvault secret show-deleted`), as the programs do. Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Each program is complete and self-checking. Set `AZURE_KEYVAULT_URL` and `SECRET_NAME` (and the identity variables your environment needs), run it against a sandbox vault, and expect:

```text
created: crud-check-1 version 3b6f0e0c8a0b4c0e9f8d6a3b1c2d4e5f
updated: new version 9a1b2c3d4e5f60718293a4b5c6d7e8f9
soft-deleted: crud-check-1
```

Running it twice with the same name fails on the second run with the soft-delete conflict unless `PURGE_AFTER_DELETE=1` was used (and purge protection is off).

### 9.1 Go

`go get github.com/Azure/azure-sdk-for-go/sdk/security/keyvault/azsecrets github.com/Azure/azure-sdk-for-go/sdk/azidentity`. HTTP failures are `*azcore.ResponseError` with `StatusCode`.

```go
// Azure Key Vault secrets CRUD with azsecrets + azidentity.
// Authentication: DefaultAzureCredential (workload identity, managed identity, or developer login).
package main

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"
	"github.com/Azure/azure-sdk-for-go/sdk/security/keyvault/azsecrets"
)

type Store struct{ client *azsecrets.Client }

func statusCode(err error) int {
	var re *azcore.ResponseError
	if errors.As(err, &re) {
		return re.StatusCode
	}
	return 0
}

// Create refuses to overwrite: SetSecret is an upsert, so check first.
// The check-then-set is not atomic; serialize creators of the same name.
func (s *Store) Create(ctx context.Context, name, value string) (string, error) {
	_, err := s.client.GetSecret(ctx, name, "", nil)
	switch {
	case err == nil:
		return "", fmt.Errorf("secret %q already exists (create is not an upsert)", name)
	case statusCode(err) != http.StatusNotFound:
		return "", fmt.Errorf("probe secret: %w", err)
	}
	return s.Set(ctx, name, value)
}

// Set writes a new version that becomes the current one (the update path).
func (s *Store) Set(ctx context.Context, name, value string) (string, error) {
	resp, err := s.client.SetSecret(ctx, name, azsecrets.SetSecretParameters{
		Value:       to.Ptr(value),
		ContentType: to.Ptr("text/plain"),
		Tags:        map[string]*string{"app": to.Ptr("secrets-crud")},
	}, nil)
	if statusCode(err) == http.StatusConflict {
		return "", fmt.Errorf("%q is soft-deleted; recover or purge it first: %w", name, err)
	}
	if err != nil {
		return "", fmt.Errorf("set secret: %w", err)
	}
	return resp.ID.Version(), nil
}

// Read returns the current version ("" = latest).
func (s *Store) Read(ctx context.Context, name string) (string, error) {
	resp, err := s.client.GetSecret(ctx, name, "", nil)
	if err != nil {
		return "", fmt.Errorf("get secret: %w", err)
	}
	if resp.Value == nil {
		return "", errors.New("secret has no value")
	}
	return *resp.Value, nil
}

// Delete soft-deletes and waits until the deleted entry is visible.
func (s *Store) Delete(ctx context.Context, name string) error {
	if _, err := s.client.DeleteSecret(ctx, name, nil); err != nil {
		return fmt.Errorf("delete secret: %w", err)
	}
	for i := 0; i < 30; i++ {
		_, err := s.client.GetDeletedSecret(ctx, name, nil)
		if err == nil {
			return nil
		}
		if statusCode(err) != http.StatusNotFound {
			return fmt.Errorf("get deleted secret: %w", err)
		}
		time.Sleep(2 * time.Second)
	}
	return errors.New("timed out waiting for soft delete")
}

// Purge permanently removes a soft-deleted secret (fails when purge protection is on).
func (s *Store) Purge(ctx context.Context, name string) error {
	_, err := s.client.PurgeDeletedSecret(ctx, name, nil)
	return err
}

func randomValue() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		log.Fatal("csprng: ", err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func equal(a, b string) bool { return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1 }

func main() {
	vaultURL, name := os.Getenv("AZURE_KEYVAULT_URL"), os.Getenv("SECRET_NAME")
	if vaultURL == "" || name == "" {
		log.Fatal("set AZURE_KEYVAULT_URL (https://<vault>.vault.azure.net/) and SECRET_NAME")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	cred, err := azidentity.NewDefaultAzureCredential(nil)
	if err != nil {
		log.Fatal(err)
	}
	client, err := azsecrets.NewClient(vaultURL, cred, nil)
	if err != nil {
		log.Fatal(err)
	}
	store := &Store{client: client}

	v1 := randomValue()
	ver, err := store.Create(ctx, name, v1)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("created:", name, "version", ver)
	if got, err := store.Read(ctx, name); err != nil || !equal(got, v1) {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	if ver, err = store.Set(ctx, name, v2); err != nil {
		log.Fatal(err)
	}
	if got, err := store.Read(ctx, name); err != nil || !equal(got, v2) {
		log.Fatal("read-back after update failed: ", err)
	}
	fmt.Println("updated: new version", ver)

	if err := store.Delete(ctx, name); err != nil {
		log.Fatal(err)
	}
	fmt.Println("soft-deleted:", name)
	if os.Getenv("PURGE_AFTER_DELETE") == "1" {
		if err := store.Purge(ctx, name); err != nil {
			log.Fatal(err)
		}
		fmt.Println("purged:", name)
	}
}
```

### 9.2 Rust

`Cargo.toml`:

```toml
[package]
name = "azure-secrets-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
azure_security_keyvault_secrets = "1"
azure_identity = "1"
azure_core = "1"
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
getrandom = "0.3"
base64 = "0.22"
zeroize = "1"
```

The Rust SDK has no `DefaultAzureCredential`; choose `WorkloadIdentityCredential` or `ManagedIdentityCredential` explicitly (`DeveloperToolsCredential` for local development). Errors expose `http_status()`.

```rust
//! Azure Key Vault secrets CRUD with the official Rust SDK
//! (azure_security_keyvault_secrets + azure_identity).
use azure_core::{credentials::TokenCredential, http::StatusCode};
use azure_identity::{ManagedIdentityCredential, WorkloadIdentityCredential};
use azure_security_keyvault_secrets::{models::SetSecretParameters, ResourceExt, SecretClient};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use std::{collections::HashMap, env, error::Error, sync::Arc, time::Duration};
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

/// Workload identity on AKS (federated token file), otherwise managed identity.
fn credential() -> Res<Arc<dyn TokenCredential>> {
    if env::var_os("AZURE_FEDERATED_TOKEN_FILE").is_some() {
        Ok(WorkloadIdentityCredential::new(None)?)
    } else {
        Ok(ManagedIdentityCredential::new(None)?)
    }
}

/// SetSecret is an upsert, so "create" first proves the name is unused.
/// The check-then-set is not atomic; serialize creators of the same name.
async fn create(client: &SecretClient, name: &str, value: &str) -> Res<String> {
    match client.get_secret(name, None).await {
        Ok(_) => return Err(format!("secret {name} already exists (create is not an upsert)").into()),
        Err(e) if e.http_status() == Some(StatusCode::NotFound) => {}
        Err(e) => return Err(e.into()),
    }
    set(client, name, value).await
}

/// UPDATE = SetSecret again: Key Vault adds a new version that becomes current.
async fn set(client: &SecretClient, name: &str, value: &str) -> Res<String> {
    let params = SetSecretParameters {
        value: Some(value.to_string()),
        content_type: Some("text/plain".into()),
        tags: Some(HashMap::from([("app".to_string(), "secrets-crud".to_string())])),
        ..Default::default()
    };
    let secret = client
        .set_secret(name, params.try_into()?, None)
        .await
        .map_err(|e| match e.http_status() {
            // 409: a deleted-but-recoverable secret with this name exists (soft delete).
            Some(StatusCode::Conflict) => format!("{name} is soft-deleted; recover or purge it first").into(),
            _ => Box::<dyn Error + Send + Sync>::from(e),
        })?
        .into_model()?;
    Ok(secret.resource_id()?.version.unwrap_or_default())
}

async fn read(client: &SecretClient, name: &str) -> Res<Zeroizing<String>> {
    let secret = client.get_secret(name, None).await?.into_model()?;
    Ok(Zeroizing::new(secret.value.ok_or("secret has no value")?))
}

/// DELETE is a soft delete; the name stays reserved until purge or retention expiry.
async fn delete(client: &SecretClient, name: &str) -> Res<()> {
    client.delete_secret(name, None).await?;
    // Deletion completes asynchronously; wait until the deleted-secret entry is visible.
    for _ in 0..30 {
        match client.get_deleted_secret(name, None).await {
            Ok(_) => return Ok(()),
            Err(e) if e.http_status() == Some(StatusCode::NotFound) => {
                tokio::time::sleep(Duration::from_secs(2)).await
            }
            Err(e) => return Err(e.into()),
        }
    }
    Err("timed out waiting for soft delete".into())
}

/// PURGE permanently removes a soft-deleted secret (fails if purge protection is on).
async fn purge(client: &SecretClient, name: &str) -> Res<()> {
    client.purge_deleted_secret(name, None).await?;
    Ok(())
}

fn random_value() -> Zeroizing<String> {
    let mut b = Zeroizing::new([0u8; 32]);
    getrandom::fill(&mut b[..]).expect("csprng");
    Zeroizing::new(URL_SAFE_NO_PAD.encode(&b[..]))
}

fn ct_eq(a: &str, b: &str) -> bool {
    a.len() == b.len() && a.bytes().zip(b.bytes()).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

#[tokio::main]
async fn main() -> Res<()> {
    let vault = env::var("AZURE_KEYVAULT_URL").map_err(|_| "set AZURE_KEYVAULT_URL")?;
    let name = env::var("SECRET_NAME").map_err(|_| "set SECRET_NAME")?;
    let client = SecretClient::new(&vault, credential()?, None)?;

    let v1 = random_value();
    let version = create(&client, &name, &v1).await?;
    println!("created: {name} version {version}");
    if !ct_eq(&read(&client, &name).await?, &v1) {
        return Err("read-back after create did not match".into());
    }

    let v2 = random_value();
    let version = set(&client, &name, &v2).await?;
    if !ct_eq(&read(&client, &name).await?, &v2) {
        return Err("read-back after update did not match".into());
    }
    println!("updated: new version {version}");

    delete(&client, &name).await?;
    println!("soft-deleted: {name}");
    if env::var("PURGE_AFTER_DELETE").as_deref() == Ok("1") {
        purge(&client, &name).await?;
        println!("purged: {name}");
    }
    Ok(())
}
```

### 9.3 PHP

There is no official Azure SDK for PHP. This program calls the REST API with ext-curl, acquires tokens through AKS workload identity, App Service managed identity, or IMDS (in that order), caches the token until five minutes before expiry, validates names, and maps 404/409 explicitly.

```php
<?php
// Azure Key Vault secrets CRUD in PHP via the REST API (Azure has no official PHP SDK).
// Requires ext-curl and ext-json. Token: AKS workload identity (federated token file),
// App Service managed identity, or the IMDS managed-identity endpoint. No client secrets.
declare(strict_types=1);

final class AzureKeyVault
{
    private const API_VERSION = '2025-07-01';
    private const SCOPE = 'https://vault.azure.net';
    private ?array $token = null; // ['value' => string, 'expires' => int]

    public function __construct(private string $vaultUrl) {}

    // ---- token acquisition -------------------------------------------------------------
    private function accessToken(): string
    {
        if ($this->token !== null && $this->token['expires'] - 300 > time()) {
            return $this->token['value'];
        }
        if ($file = getenv('AZURE_FEDERATED_TOKEN_FILE')) {            // AKS workload identity
            $authority = rtrim(getenv('AZURE_AUTHORITY_HOST') ?: 'https://login.microsoftonline.com/', '/');
            $resp = $this->http('POST', "{$authority}/" . getenv('AZURE_TENANT_ID') . '/oauth2/v2.0/token', null, [
                'Content-Type: application/x-www-form-urlencoded',
            ], http_build_query([
                'grant_type'            => 'client_credentials',
                'client_id'             => getenv('AZURE_CLIENT_ID'),
                'scope'                 => self::SCOPE . '/.default',
                'client_assertion_type' => 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
                'client_assertion'      => trim((string) file_get_contents($file)),
            ]));
        } elseif (($endpoint = getenv('IDENTITY_ENDPOINT')) && ($header = getenv('IDENTITY_HEADER'))) { // App Service
            $resp = $this->http('GET', $endpoint . '?' . http_build_query(['api-version' => '2019-08-01', 'resource' => self::SCOPE]),
                null, ["X-IDENTITY-HEADER: {$header}"]);
        } else {                                                          // VM / VMSS IMDS
            $resp = $this->http('GET', 'http://169.254.169.254/metadata/identity/oauth2/token?' .
                http_build_query(['api-version' => '2018-02-01', 'resource' => self::SCOPE]), null, ['Metadata: true']);
        }
        if ($resp['status'] !== 200) {
            throw new RuntimeException("token request failed: HTTP {$resp['status']}");
        }
        $json = json_decode($resp['body'], true, 16, JSON_THROW_ON_ERROR);
        $expires = isset($json['expires_on']) ? (int) $json['expires_on'] : time() + (int) ($json['expires_in'] ?? 300);
        $this->token = ['value' => $json['access_token'], 'expires' => $expires];
        return $this->token['value'];
    }

    // ---- HTTP --------------------------------------------------------------------------
    /** @return array{status:int, body:string} */
    private function http(string $method, string $url, ?string $bearer, array $headers = [], ?string $body = null): array
    {
        $ch = curl_init($url);
        if ($bearer !== null) {
            $headers[] = "Authorization: Bearer {$bearer}";
        }
        curl_setopt_array($ch, [
            CURLOPT_CUSTOMREQUEST  => $method,
            CURLOPT_HTTPHEADER     => $headers,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 30,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
        ]);
        if ($body !== null) {
            curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
        }
        $out = curl_exec($ch);
        if ($out === false) {
            throw new RuntimeException('transport error: ' . curl_error($ch));
        }
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        return ['status' => $status, 'body' => (string) $out];
    }

    /** @return array{status:int, json:array} */
    private function call(string $method, string $path, ?array $payload = null): array
    {
        $url = rtrim($this->vaultUrl, '/') . $path . '?api-version=' . self::API_VERSION;
        $body = $payload === null ? null : json_encode($payload, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
        $resp = $this->http($method, $url, $this->accessToken(), ['Content-Type: application/json'], $body);
        $json = $resp['body'] === '' ? [] : (json_decode($resp['body'], true) ?? []);
        return ['status' => $resp['status'], 'json' => $json];
    }

    private static function fail(string $op, array $r): never
    {
        // Key Vault error bodies carry code/message only, never the secret value.
        $code = $r['json']['error']['code'] ?? 'unknown';
        throw new RuntimeException("{$op}: HTTP {$r['status']} {$code}");
    }

    private static function path(string $name): string
    {
        if (!preg_match('/^[0-9A-Za-z-]{1,127}$/', $name)) {
            throw new InvalidArgumentException('secret names are 1-127 alphanumerics or hyphens');
        }
        return '/secrets/' . $name;
    }

    // ---- CRUD ----------------------------------------------------------------------------
    /** PUT is an upsert, so prove the name is unused first (not atomic; serialize creators). */
    public function create(string $name, string $value): string
    {
        $probe = $this->call('GET', self::path($name));
        if ($probe['status'] === 200) {
            throw new RuntimeException("secret {$name} already exists (create is not an upsert)");
        }
        if ($probe['status'] !== 404) {
            self::fail('probe', $probe);
        }
        return $this->set($name, $value);
    }

    /** Update path: each PUT adds a new version that becomes current. Returns the version ID. */
    public function set(string $name, string $value): string
    {
        $r = $this->call('PUT', self::path($name), [
            'value'       => $value,
            'contentType' => 'text/plain',
            'tags'        => ['app' => 'secrets-crud'],
        ]);
        if ($r['status'] === 409) {
            throw new RuntimeException("{$name} is soft-deleted; recover or purge it first");
        }
        if ($r['status'] !== 200) {
            self::fail('set', $r);
        }
        return basename((string) $r['json']['id']);
    }

    public function read(string $name): string
    {
        $r = $this->call('GET', self::path($name));
        if ($r['status'] !== 200 || !isset($r['json']['value'])) {
            self::fail('get', $r);
        }
        return $r['json']['value'];
    }

    /** Soft delete, then wait until the deleted entry is visible. */
    public function delete(string $name): void
    {
        $r = $this->call('DELETE', self::path($name));
        if ($r['status'] !== 200) {
            self::fail('delete', $r);
        }
        for ($i = 0; $i < 30; $i++) {
            $d = $this->call('GET', '/deletedsecrets/' . $name);
            if ($d['status'] === 200) {
                return;
            }
            sleep(2);
        }
        throw new RuntimeException('timed out waiting for soft delete');
    }

    /** Permanent removal of a soft-deleted secret (fails if purge protection is on). */
    public function purge(string $name): void
    {
        $r = $this->call('DELETE', '/deletedsecrets/' . $name);
        if ($r['status'] !== 204) {
            self::fail('purge', $r);
        }
    }
}

$vault = getenv('AZURE_KEYVAULT_URL') ?: exit("set AZURE_KEYVAULT_URL\n");
$name = getenv('SECRET_NAME') ?: exit("set SECRET_NAME\n");
$kv = new AzureKeyVault($vault);
$random = fn (): string => rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');

$v1 = $random();
echo "created: {$name} version " . $kv->create($name, $v1) . "\n";
hash_equals($v1, $kv->read($name)) || exit("read-back after create did not match\n");

$v2 = $random();
echo 'updated: new version ' . $kv->set($name, $v2) . "\n";
hash_equals($v2, $kv->read($name)) || exit("read-back after update did not match\n");
unset($v1, $v2);

$kv->delete($name);
echo "soft-deleted: {$name}\n";
if (getenv('PURGE_AFTER_DELETE') === '1') {
    $kv->purge($name);
    echo "purged: {$name}\n";
}
```

### 9.4 C#

`dotnet add package Azure.Security.KeyVault.Secrets Azure.Identity`. Failures are `Azure.RequestFailedException` with `Status`.

```csharp
// Azure Key Vault secrets CRUD with Azure.Security.KeyVault.Secrets + Azure.Identity.
// dotnet add package Azure.Security.KeyVault.Secrets
// dotnet add package Azure.Identity
using System.Security.Cryptography;
using System.Text;
using Azure;
using Azure.Identity;
using Azure.Security.KeyVault.Secrets;

public sealed class AzureSecretStore(SecretClient client)
{
    /// <summary>SetSecret is an upsert, so prove the name is unused first (not atomic).</summary>
    public async Task<string> CreateAsync(string name, string value, CancellationToken ct)
    {
        try
        {
            await client.GetSecretAsync(name, cancellationToken: ct);
            throw new InvalidOperationException($"secret {name} already exists (create is not an upsert)");
        }
        catch (RequestFailedException ex) when (ex.Status == 404)
        {
            return await SetAsync(name, value, ct);
        }
    }

    /// <summary>Update path: each call adds a new version that becomes current.</summary>
    public async Task<string> SetAsync(string name, string value, CancellationToken ct)
    {
        var secret = new KeyVaultSecret(name, value);
        secret.Properties.ContentType = "text/plain";
        secret.Properties.Tags["app"] = "secrets-crud";
        try
        {
            KeyVaultSecret stored = await client.SetSecretAsync(secret, ct);
            return stored.Properties.Version;
        }
        catch (RequestFailedException ex) when (ex.Status == 409)
        {
            throw new InvalidOperationException($"{name} is soft-deleted; recover or purge it first", ex);
        }
    }

    public async Task<string> ReadAsync(string name, CancellationToken ct)
    {
        KeyVaultSecret secret = await client.GetSecretAsync(name, cancellationToken: ct);
        return secret.Value ?? throw new InvalidOperationException("secret has no value");
    }

    /// <summary>Soft delete; completes when the deleted entry exists. The name stays reserved.</summary>
    public async Task DeleteAsync(string name, CancellationToken ct)
    {
        DeleteSecretOperation op = await client.StartDeleteSecretAsync(name, ct);
        await op.WaitForCompletionAsync(ct);
    }

    /// <summary>Permanent removal of a soft-deleted secret (fails if purge protection is on).</summary>
    public Task PurgeAsync(string name, CancellationToken ct) => client.PurgeDeletedSecretAsync(name, ct);
}

public static class Program
{
    static string RandomValue() =>
        Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    static bool FixedEquals(string a, string b) =>
        CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(a), Encoding.UTF8.GetBytes(b));

    public static async Task<int> Main()
    {
        var vaultUrl = Environment.GetEnvironmentVariable("AZURE_KEYVAULT_URL")
                       ?? throw new InvalidOperationException("set AZURE_KEYVAULT_URL");
        var name = Environment.GetEnvironmentVariable("SECRET_NAME")
                   ?? throw new InvalidOperationException("set SECRET_NAME");
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(2));
        var store = new AzureSecretStore(new SecretClient(new Uri(vaultUrl), new DefaultAzureCredential()));

        var v1 = RandomValue();
        var version = await store.CreateAsync(name, v1, cts.Token);
        Console.WriteLine($"created: {name} version {version}");
        if (!FixedEquals(v1, await store.ReadAsync(name, cts.Token)))
            throw new InvalidOperationException("read-back after create did not match");

        var v2 = RandomValue();
        version = await store.SetAsync(name, v2, cts.Token);
        if (!FixedEquals(v2, await store.ReadAsync(name, cts.Token)))
            throw new InvalidOperationException("read-back after update did not match");
        Console.WriteLine($"updated: new version {version}");

        await store.DeleteAsync(name, cts.Token);
        Console.WriteLine($"soft-deleted: {name}");
        if (Environment.GetEnvironmentVariable("PURGE_AFTER_DELETE") == "1")
        {
            await store.PurgeAsync(name, cts.Token);
            Console.WriteLine($"purged: {name}");
        }
        return 0;
    }
}
```

### 9.5 Java

Use the Azure SDK BOM:

```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.azure</groupId>
      <artifactId>azure-sdk-bom</artifactId>
      <version>${azure.sdk.bom.version}</version> <!-- pin a current release -->
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
<dependencies>
  <dependency><groupId>com.azure</groupId><artifactId>azure-security-keyvault-secrets</artifactId></dependency>
  <dependency><groupId>com.azure</groupId><artifactId>azure-identity</artifactId></dependency>
</dependencies>
```

404 surfaces as `ResourceNotFoundException`; other HTTP failures as `HttpResponseException`.

```java
// Azure Key Vault secrets CRUD with azure-security-keyvault-secrets + azure-identity.
// Maven: com.azure:azure-security-keyvault-secrets, com.azure:azure-identity (import com.azure:azure-sdk-bom)
package example;

import com.azure.core.exception.HttpResponseException;
import com.azure.core.exception.ResourceNotFoundException;
import com.azure.identity.DefaultAzureCredentialBuilder;
import com.azure.security.keyvault.secrets.SecretClient;
import com.azure.security.keyvault.secrets.SecretClientBuilder;
import com.azure.security.keyvault.secrets.models.KeyVaultSecret;
import com.azure.security.keyvault.secrets.models.SecretProperties;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Map;

public final class AzureSecretsCrud {
    private final SecretClient client;

    public AzureSecretsCrud(SecretClient client) {
        this.client = client;
    }

    /** setSecret is an upsert, so prove the name is unused first (not atomic). */
    public String create(String name, String value) {
        try {
            client.getSecret(name);
        } catch (ResourceNotFoundException e) {
            return set(name, value);
        }
        throw new IllegalStateException("secret " + name + " already exists (create is not an upsert)");
    }

    /** Update path: each call adds a new version that becomes current. */
    public String set(String name, String value) {
        KeyVaultSecret secret = new KeyVaultSecret(name, value).setProperties(new SecretProperties()
                .setContentType("text/plain")
                .setTags(Map.of("app", "secrets-crud")));
        try {
            return client.setSecret(secret).getProperties().getVersion();
        } catch (HttpResponseException e) {
            if (e.getResponse() != null && e.getResponse().getStatusCode() == 409) {
                throw new IllegalStateException(name + " is soft-deleted; recover or purge it first", e);
            }
            throw e;
        }
    }

    public String read(String name) {
        String value = client.getSecret(name).getValue();
        if (value == null) throw new IllegalStateException("secret has no value");
        return value;
    }

    /** Soft delete; returns once the deleted entry exists. The name stays reserved. */
    public void delete(String name) {
        client.beginDeleteSecret(name).waitForCompletion();
    }

    /** Permanent removal of a soft-deleted secret (fails if purge protection is on). */
    public void purge(String name) {
        client.purgeDeletedSecret(name);
    }

    private static final SecureRandom RNG = new SecureRandom();

    static String randomValue() {
        byte[] b = new byte[32];
        RNG.nextBytes(b);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(b);
    }

    static boolean fixedEquals(String a, String b) {
        return MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }

    public static void main(String[] args) {
        String vaultUrl = System.getenv("AZURE_KEYVAULT_URL");
        String name = System.getenv("SECRET_NAME");
        if (vaultUrl == null || name == null) throw new IllegalArgumentException("set AZURE_KEYVAULT_URL and SECRET_NAME");

        SecretClient client = new SecretClientBuilder()
                .vaultUrl(vaultUrl)
                .credential(new DefaultAzureCredentialBuilder().build())
                .buildClient();
        AzureSecretsCrud store = new AzureSecretsCrud(client);

        String v1 = randomValue();
        System.out.println("created: " + name + " version " + store.create(name, v1));
        if (!fixedEquals(v1, store.read(name))) throw new IllegalStateException("read-back after create failed");

        String v2 = randomValue();
        String version = store.set(name, v2);
        if (!fixedEquals(v2, store.read(name))) throw new IllegalStateException("read-back after update failed");
        System.out.println("updated: new version " + version);

        store.delete(name);
        System.out.println("soft-deleted: " + name);
        if ("1".equals(System.getenv("PURGE_AFTER_DELETE"))) {
            store.purge(name);
            System.out.println("purged: " + name);
        }
    }
}
```

### 9.6 Swift

There is no official Azure Swift SDK for Key Vault. This program calls the REST API with an ephemeral `URLSession`, obtaining tokens through workload identity or IMDS. **Do not embed service-principal secrets in client apps;** mobile and desktop apps should call your backend.

`Package.swift`:

```swift
// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SecretsCrud",
    platforms: [.macOS(.v13)],
    targets: [
        // Foundation only: URLSession + JSONSerialization. No third-party dependencies.
        .executableTarget(name: "SecretsCrud"),
    ]
)
```

```swift
// Azure Key Vault secrets CRUD in Swift via the REST API (there is no official Azure Swift SDK
// for Key Vault). Token: AKS workload identity (federated token file) or the IMDS managed-identity
// endpoint. Never embed client secrets or certificates in an app bundle.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

enum CrudError: Error { case http(Int, String), config(String) }

final class AzureKeyVault {
    private let vaultURL: URL
    private let apiVersion = "2025-07-01"
    private let session = URLSession(configuration: .ephemeral)
    private var token: (value: String, expires: Date)?

    init(vaultURL: URL) { self.vaultURL = vaultURL }

    // MARK: token
    private func accessToken() async throws -> String {
        if let t = token, t.expires.timeIntervalSinceNow > 300 { return t.value }
        let env = ProcessInfo.processInfo.environment
        var req: URLRequest
        if let file = env["AZURE_FEDERATED_TOKEN_FILE"], let tenant = env["AZURE_TENANT_ID"],
           let client = env["AZURE_CLIENT_ID"] {
            let authority = env["AZURE_AUTHORITY_HOST"] ?? "https://login.microsoftonline.com/"
            let base = authority.hasSuffix("/") ? authority : authority + "/"
            req = URLRequest(url: URL(string: "\(base)\(tenant)/oauth2/v2.0/token")!)
            req.httpMethod = "POST"
            req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
            let assertion = try String(contentsOfFile: file, encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            var form = URLComponents()
            form.queryItems = [
                URLQueryItem(name: "grant_type", value: "client_credentials"),
                URLQueryItem(name: "client_id", value: client),
                URLQueryItem(name: "scope", value: "https://vault.azure.net/.default"),
                URLQueryItem(name: "client_assertion_type",
                             value: "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"),
                URLQueryItem(name: "client_assertion", value: assertion),
            ]
            req.httpBody = Data((form.percentEncodedQuery ?? "").utf8)
        } else {
            req = URLRequest(url: URL(string:
                "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net")!)
            req.setValue("true", forHTTPHeaderField: "Metadata")
        }
        let (data, resp) = try await session.data(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw CrudError.config("token request failed") }
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        guard let value = obj["access_token"] as? String else { throw CrudError.config("no access_token") }
        let expiresIn = Double("\(obj["expires_in"] ?? "300")") ?? 300
        token = (value, Date().addingTimeInterval(expiresIn))
        return value
    }

    // MARK: HTTP
    private func call(_ method: String, _ path: String, body: [String: Any]? = nil) async throws -> (Int, [String: Any]) {
        var comps = URLComponents(url: vaultURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "api-version", value: apiVersion)]
        var req = URLRequest(url: comps.url!)
        req.httpMethod = method
        req.timeoutInterval = 30
        req.setValue("Bearer \(try await accessToken())", forHTTPHeaderField: "Authorization")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        return (status, json)
    }

    private static func check(_ name: String) throws -> String {
        guard (1...127).contains(name.count),
              name.unicodeScalars.allSatisfy({ CharacterSet.alphanumerics.contains($0) && $0.isASCII || $0 == "-" })
        else { throw CrudError.config("secret names are 1-127 ASCII alphanumerics or hyphens") }
        return "secrets/\(name)"
    }

    // MARK: CRUD
    /// PUT is an upsert, so prove the name is unused first (not atomic; serialize creators).
    func create(name: String, value: String) async throws -> String {
        let (status, _) = try await call("GET", try Self.check(name))
        if status == 200 { throw CrudError.config("secret \(name) already exists (create is not an upsert)") }
        guard status == 404 else { throw CrudError.http(status, "probe") }
        return try await set(name: name, value: value)
    }

    /// Update path: each PUT adds a new version that becomes current. Returns the version ID.
    func set(name: String, value: String) async throws -> String {
        let (status, json) = try await call("PUT", try Self.check(name), body: [
            "value": value, "contentType": "text/plain", "tags": ["app": "secrets-crud"],
        ])
        if status == 409 { throw CrudError.config("\(name) is soft-deleted; recover or purge it first") }
        guard status == 200, let id = json["id"] as? String else { throw CrudError.http(status, "set") }
        return URL(string: id)?.lastPathComponent ?? ""
    }

    func read(name: String) async throws -> String {
        let (status, json) = try await call("GET", try Self.check(name))
        guard status == 200, let value = json["value"] as? String else { throw CrudError.http(status, "get") }
        return value
    }

    /// Soft delete, then wait until the deleted entry is visible. The name stays reserved.
    func delete(name: String) async throws {
        let (status, _) = try await call("DELETE", try Self.check(name))
        guard status == 200 else { throw CrudError.http(status, "delete") }
        for _ in 0..<30 {
            if try await call("GET", "deletedsecrets/\(name)").0 == 200 { return }
            try await Task.sleep(nanoseconds: 2_000_000_000)
        }
        throw CrudError.config("timed out waiting for soft delete")
    }

    /// Permanent removal of a soft-deleted secret (fails if purge protection is on).
    func purge(name: String) async throws {
        let (status, _) = try await call("DELETE", "deletedsecrets/\(name)")
        guard status == 204 else { throw CrudError.http(status, "purge") }
    }
}

func randomValue() -> String {
    var rng = SystemRandomNumberGenerator()
    let bytes = (0..<32).map { _ in UInt8.random(in: .min ... .max, using: &rng) }
    return Data(bytes).base64EncodedString()
}

func fixedEquals(_ a: String, _ b: String) -> Bool {
    let x = Array(a.utf8), y = Array(b.utf8)
    return x.count == y.count && zip(x, y).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
}

let env = ProcessInfo.processInfo.environment
guard let vault = env["AZURE_KEYVAULT_URL"].flatMap(URL.init(string:)), let name = env["SECRET_NAME"] else {
    fatalError("set AZURE_KEYVAULT_URL and SECRET_NAME")
}
let kv = AzureKeyVault(vaultURL: vault)

let v1 = randomValue()
print("created: \(name) version \(try await kv.create(name: name, value: v1))")
guard fixedEquals(v1, try await kv.read(name: name)) else { fatalError("read-back after create failed") }

let v2 = randomValue()
let version = try await kv.set(name: name, value: v2)
guard fixedEquals(v2, try await kv.read(name: name)) else { fatalError("read-back after update failed") }
print("updated: new version \(version)")

try await kv.delete(name: name)
print("soft-deleted: \(name)")
if env["PURGE_AFTER_DELETE"] == "1" {
    try await kv.purge(name: name)
    print("purged: \(name)")
}
```

### 9.7 Python

`pip install azure-keyvault-secrets azure-identity`. azure-core maps 404 to `ResourceNotFoundError` and 409 to `ResourceExistsError`.

```python
"""Azure Key Vault secrets CRUD with azure-keyvault-secrets.

pip install azure-keyvault-secrets azure-identity
Authentication: DefaultAzureCredential (workload identity, managed identity, or developer login).
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient


class AzureSecretStore:
    def __init__(self, client: SecretClient) -> None:
        self.client = client

    def create(self, name: str, value: str) -> str:
        """set_secret is an upsert, so prove the name is unused first (not atomic)."""
        try:
            self.client.get_secret(name)
        except ResourceNotFoundError:
            return self.set(name, value)
        raise RuntimeError(f"secret {name} already exists (create is not an upsert)")

    def set(self, name: str, value: str) -> str:
        """Update path: each call adds a new version that becomes current."""
        try:
            secret = self.client.set_secret(
                name, value, content_type="text/plain", tags={"app": "secrets-crud"}
            )
        except ResourceExistsError as exc:  # HTTP 409: soft-deleted secret with this name
            raise RuntimeError(f"{name} is soft-deleted; recover or purge it first") from exc
        return secret.properties.version or ""

    def read(self, name: str) -> str:
        value = self.client.get_secret(name).value
        if value is None:
            raise RuntimeError("secret has no value")
        return value

    def delete(self, name: str) -> None:
        """Soft delete; waits until the deleted entry exists. The name stays reserved."""
        self.client.begin_delete_secret(name).wait()

    def purge(self, name: str) -> None:
        """Permanent removal of a soft-deleted secret (fails if purge protection is on)."""
        self.client.purge_deleted_secret(name)


def main() -> int:
    vault_url, name = os.environ.get("AZURE_KEYVAULT_URL"), os.environ.get("SECRET_NAME")
    if not vault_url or not name:
        print("set AZURE_KEYVAULT_URL and SECRET_NAME", file=sys.stderr)
        return 2
    store = AzureSecretStore(SecretClient(vault_url=vault_url, credential=DefaultAzureCredential()))

    v1 = secrets.token_urlsafe(32)
    version = store.create(name, v1)
    print(f"created: {name} version {version}")
    if not hmac.compare_digest(v1, store.read(name)):
        raise RuntimeError("read-back after create did not match")

    v2 = secrets.token_urlsafe(32)
    version = store.set(name, v2)
    if not hmac.compare_digest(v2, store.read(name)):
        raise RuntimeError("read-back after update did not match")
    print(f"updated: new version {version}")

    store.delete(name)
    print(f"soft-deleted: {name}")
    if os.environ.get("PURGE_AFTER_DELETE") == "1":
        store.purge(name)
        print(f"purged: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

`npm i @azure/keyvault-secrets @azure/identity @azure/core-rest-pipeline`. HTTP failures are `RestError` with `statusCode`.

```typescript
// Azure Key Vault secrets CRUD with @azure/keyvault-secrets + @azure/identity.
// npm i @azure/keyvault-secrets @azure/identity @azure/core-rest-pipeline
import { randomBytes, timingSafeEqual } from "node:crypto";
import { DefaultAzureCredential } from "@azure/identity";
import { SecretClient } from "@azure/keyvault-secrets";
import { RestError } from "@azure/core-rest-pipeline";

export class AzureSecretStore {
  constructor(private readonly client: SecretClient) {}

  /** setSecret is an upsert, so prove the name is unused first (not atomic). */
  async create(name: string, value: string): Promise<string> {
    try {
      await this.client.getSecret(name);
    } catch (err) {
      if (err instanceof RestError && err.statusCode === 404) return this.set(name, value);
      throw err;
    }
    throw new Error(`secret ${name} already exists (create is not an upsert)`);
  }

  /** Update path: each call adds a new version that becomes current. */
  async set(name: string, value: string): Promise<string> {
    try {
      const secret = await this.client.setSecret(name, value, {
        contentType: "text/plain",
        tags: { app: "secrets-crud" },
      });
      return secret.properties.version ?? "";
    } catch (err) {
      if (err instanceof RestError && err.statusCode === 409) {
        throw new Error(`${name} is soft-deleted; recover or purge it first`, { cause: err });
      }
      throw err;
    }
  }

  async read(name: string): Promise<string> {
    const secret = await this.client.getSecret(name);
    if (secret.value === undefined) throw new Error("secret has no value");
    return secret.value;
  }

  /** Soft delete; resolves once the deleted entry exists. The name stays reserved. */
  async delete(name: string): Promise<void> {
    const poller = await this.client.beginDeleteSecret(name);
    await poller.pollUntilDone();
  }

  /** Permanent removal of a soft-deleted secret (fails if purge protection is on). */
  async purge(name: string): Promise<void> {
    await this.client.purgeDeletedSecret(name);
  }
}

const randomValue = (): string => randomBytes(32).toString("base64url");
const same = (a: string, b: string): boolean => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

async function main(): Promise<void> {
  const vaultUrl = process.env.AZURE_KEYVAULT_URL, name = process.env.SECRET_NAME;
  if (!vaultUrl || !name) throw new Error("set AZURE_KEYVAULT_URL and SECRET_NAME");
  const store = new AzureSecretStore(new SecretClient(vaultUrl, new DefaultAzureCredential()));

  const v1 = randomValue();
  let version = await store.create(name, v1);
  console.log(`created: ${name} version ${version}`);
  if (!same(v1, await store.read(name))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  version = await store.set(name, v2);
  if (!same(v2, await store.read(name))) throw new Error("read-back after update did not match");
  console.log(`updated: new version ${version}`);

  await store.delete(name);
  console.log(`soft-deleted: ${name}`);
  if (process.env.PURGE_AFTER_DELETE === "1") {
    await store.purge(name);
    console.log(`purged: ${name}`);
  }
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? `${err.name}: ${err.message}` : "unknown error");
  process.exitCode = 1;
});
```

### 9.9 C++

Install with vcpkg (`azure-security-keyvault-secrets-cpp`, `azure-identity-cpp`). Failures throw `Azure::Core::RequestFailedException` with `StatusCode` and `ErrorCode`. Note that Microsoft's own basic-operations sample prints the secret value to stdout; this program does not.

```cpp
// Azure Key Vault secrets CRUD with the Azure SDK for C++.
// vcpkg: azure-security-keyvault-secrets-cpp azure-identity-cpp
// CMake: find_package(azure-security-keyvault-secrets-cpp CONFIG REQUIRED)
//        find_package(azure-identity-cpp CONFIG REQUIRED)
//        target_link_libraries(app Azure::azure-security-keyvault-secrets Azure::azure-identity)
#include <azure/identity.hpp>
#include <azure/keyvault/secrets.hpp>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

using namespace Azure::Security::KeyVault::Secrets;
using namespace std::chrono_literals;

class AzureSecretStore {
 public:
  explicit AzureSecretStore(SecretClient client) : client_(std::move(client)) {}

  // SetSecret is an upsert, so prove the name is unused first (not atomic).
  std::string create(std::string const& name, std::string const& value) {
    try {
      client_.GetSecret(name);
    } catch (Azure::Core::RequestFailedException const& e) {
      if (e.StatusCode != Azure::Core::Http::HttpStatusCode::NotFound) throw;
      return set(name, value);
    }
    throw std::runtime_error("secret " + name + " already exists (create is not an upsert)");
  }

  // Update path: each call adds a new version that becomes current.
  std::string set(std::string const& name, std::string const& value) {
    KeyVaultSecret secret(name, value);
    secret.Properties.ContentType = "text/plain";
    secret.Properties.Tags["app"] = "secrets-crud";
    try {
      return client_.SetSecret(name, secret).Value.Properties.Version;
    } catch (Azure::Core::RequestFailedException const& e) {
      if (e.StatusCode == Azure::Core::Http::HttpStatusCode::Conflict)
        throw std::runtime_error(name + " is soft-deleted; recover or purge it first");
      throw;
    }
  }

  std::string read(std::string const& name) {
    KeyVaultSecret secret = client_.GetSecret(name).Value;
    if (!secret.Value.HasValue()) throw std::runtime_error("secret has no value");
    return secret.Value.Value();
  }

  // Soft delete; waits until the deleted entry exists. The name stays reserved.
  void remove(std::string const& name) {
    DeleteSecretOperation op = client_.StartDeleteSecret(name);
    op.PollUntilDone(2s);
  }

  // Permanent removal of a soft-deleted secret (fails if purge protection is on).
  void purge(std::string const& name) { client_.PurgeDeletedSecret(name); }

 private:
  SecretClient client_;
};

static std::string random_value() {
  unsigned char raw[32], b64[64];
  if (RAND_bytes(raw, sizeof raw) != 1) throw std::runtime_error("RAND_bytes failed");
  int n = EVP_EncodeBlock(b64, raw, sizeof raw);
  std::string out(reinterpret_cast<char*>(b64), static_cast<size_t>(n));
  OPENSSL_cleanse(raw, sizeof raw);
  OPENSSL_cleanse(b64, sizeof b64);
  return out;
}

static bool same(std::string const& a, std::string const& b) {
  return a.size() == b.size() && CRYPTO_memcmp(a.data(), b.data(), a.size()) == 0;
}

static void wipe(std::string& s) { OPENSSL_cleanse(s.data(), s.size()); s.clear(); }

int main() {
  char const* vault = std::getenv("AZURE_KEYVAULT_URL");
  char const* name = std::getenv("SECRET_NAME");
  if (!vault || !name) { std::cerr << "set AZURE_KEYVAULT_URL and SECRET_NAME\n"; return 2; }
  try {
    auto credential = std::make_shared<Azure::Identity::DefaultAzureCredential>();
    AzureSecretStore store(SecretClient(vault, credential));

    std::string v1 = random_value();
    std::cout << "created: " << name << " version " << store.create(name, v1) << "\n";
    std::string got = store.read(name);
    if (!same(v1, got)) throw std::runtime_error("read-back after create failed");

    std::string v2 = random_value();
    std::string version = store.set(name, v2);
    got = store.read(name);
    if (!same(v2, got)) throw std::runtime_error("read-back after update failed");
    std::cout << "updated: new version " << version << "\n";
    wipe(v1); wipe(v2); wipe(got);

    store.remove(name);
    std::cout << "soft-deleted: " << name << "\n";
    if (char const* p = std::getenv("PURGE_AFTER_DELETE"); p && std::string(p) == "1") {
      store.purge(name);
      std::cout << "purged: " << name << "\n";
    }
    return 0;
  } catch (Azure::Core::Credentials::AuthenticationException const& e) {
    std::cerr << "authentication failed: " << e.what() << "\n";
  } catch (Azure::Core::RequestFailedException const& e) {
    std::cerr << "Key Vault request failed: HTTP " << static_cast<int>(e.StatusCode) << " " << e.ErrorCode << "\n";
  } catch (std::exception const& e) {
    std::cerr << "error: " << e.what() << "\n";
  }
  return 1;
}
```

### 9.10 C

There is no official C SDK. This program calls the REST API with libcurl, obtains a token through workload identity (client-assertion exchange) or IMDS, restricts vault calls to HTTPS, validates the name, wipes request/response buffers (the `PUT` response echoes the value), and waits for soft delete before an optional purge.

```c
/*
 * Azure Key Vault secrets CRUD in C via the REST API (no official C SDK; use the C++ SDK when you can).
 * libcurl + cJSON + OpenSSL.
 *
 *   cc -std=c11 -Wall -Wextra -O2 azure_kv_crud.c -o azure_kv_crud \
 *      $(pkg-config --cflags --libs libcurl libcjson openssl)
 *
 * Token: AKS workload identity (AZURE_FEDERATED_TOKEN_FILE + AZURE_TENANT_ID + AZURE_CLIENT_ID),
 * otherwise the IMDS managed-identity endpoint. No client secrets.
 */
#define _POSIX_C_SOURCE 200809L
#include <cjson/cJSON.h>
#include <curl/curl.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define API_VERSION "2025-07-01"

typedef struct { char *data; size_t len; } buf_t;

static size_t on_body(char *p, size_t s, size_t n, void *u) {
    buf_t *b = u; size_t k = s * n;
    char *g = realloc(b->data, b->len + k + 1);
    if (!g) return 0;
    b->data = g; memcpy(b->data + b->len, p, k); b->len += k; b->data[b->len] = '\0';
    return k;
}
static void buf_wipe(buf_t *b) { if (b->data) { OPENSSL_cleanse(b->data, b->len); free(b->data); } b->data = NULL; b->len = 0; }
static void str_wipe_free(char *s) { if (s) { OPENSSL_cleanse(s, strlen(s)); free(s); } }

static long http(const char *method, const char *url, struct curl_slist *hdrs, const char *body, buf_t *out,
                 int https_only) {
    CURL *c = curl_easy_init();
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_CUSTOMREQUEST, method);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, hdrs);
    if (body) curl_easy_setopt(c, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, out);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 30L);
    if (https_only) curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "https");
    long status = 0;
    if (curl_easy_perform(c) == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    return status;
}

/* ---- token (cached until 5 minutes before expiry) ---- */
static char *g_token = NULL;
static time_t g_token_exp = 0;

static char *read_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return NULL;
    char *s = calloc(1, 16384);
    size_t n = fread(s, 1, 16383, f);
    fclose(f);
    while (n && (s[n - 1] == '\n' || s[n - 1] == '\r')) s[--n] = '\0';
    return s;
}

static const char *access_token(void) {
    if (g_token && time(NULL) < g_token_exp - 300) return g_token;
    buf_t resp = {0};
    long st;
    const char *fed = getenv("AZURE_FEDERATED_TOKEN_FILE");
    if (fed) {                                   /* AKS workload identity: client_assertion exchange */
        const char *auth = getenv("AZURE_AUTHORITY_HOST");
        const char *tenant = getenv("AZURE_TENANT_ID"), *client = getenv("AZURE_CLIENT_ID");
        char *assertion = read_file(fed);
        if (!assertion || !tenant || !client) { str_wipe_free(assertion); return NULL; }
        char url[512];
        snprintf(url, sizeof url, "%s%s%s/oauth2/v2.0/token", auth ? auth : "https://login.microsoftonline.com/",
                 (auth && auth[strlen(auth) - 1] != '/') ? "/" : "", tenant);
        CURL *esc = curl_easy_init();
        char *enc = curl_easy_escape(esc, assertion, 0);
        size_t blen = strlen(enc) + strlen(client) + 256;
        char *body = malloc(blen);
        snprintf(body, blen, "grant_type=client_credentials&client_id=%s&scope=https%%3A%%2F%%2Fvault.azure.net%%2F.default"
                 "&client_assertion_type=urn%%3Aietf%%3Aparams%%3Aoauth%%3Aclient-assertion-type%%3Ajwt-bearer"
                 "&client_assertion=%s", client, enc);
        curl_free(enc); curl_easy_cleanup(esc); str_wipe_free(assertion);
        struct curl_slist *h = curl_slist_append(NULL, "Content-Type: application/x-www-form-urlencoded");
        st = http("POST", url, h, body, &resp, 1);
        curl_slist_free_all(h);
        str_wipe_free(body);
    } else {                                     /* VM/VMSS managed identity via IMDS */
        struct curl_slist *h = curl_slist_append(NULL, "Metadata: true");
        st = http("GET", "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01"
                         "&resource=https%3A%2F%2Fvault.azure.net", h, NULL, &resp, 0);
        curl_slist_free_all(h);
    }
    if (st != 200) { fprintf(stderr, "token request failed: HTTP %ld\n", st); buf_wipe(&resp); return NULL; }
    cJSON *j = cJSON_Parse(resp.data);
    buf_wipe(&resp);
    const cJSON *tok = cJSON_GetObjectItemCaseSensitive(j, "access_token");
    const cJSON *exp_on = cJSON_GetObjectItemCaseSensitive(j, "expires_on");
    const cJSON *exp_in = cJSON_GetObjectItemCaseSensitive(j, "expires_in");
    if (cJSON_IsString(tok)) {
        str_wipe_free(g_token);
        g_token = strdup(tok->valuestring);
        OPENSSL_cleanse(tok->valuestring, strlen(tok->valuestring));
        g_token_exp = cJSON_IsString(exp_on) ? (time_t)strtoll(exp_on->valuestring, NULL, 10)
                    : time(NULL) + (cJSON_IsNumber(exp_in) ? (time_t)exp_in->valuedouble
                    : cJSON_IsString(exp_in) ? (time_t)strtoll(exp_in->valuestring, NULL, 10) : 300);
    }
    cJSON_Delete(j);
    return g_token;
}

/* ---- Key Vault call: returns HTTP status; *out gets parsed JSON (caller frees) ---- */
static long kv(const char *method, const char *path, cJSON *body, cJSON **out) {
    const char *vault = getenv("AZURE_KEYVAULT_URL");
    const char *tok = access_token();
    if (!tok) return 0;
    char url[1024], auth[8300];
    snprintf(url, sizeof url, "%s%s%s?api-version=" API_VERSION, vault,
             vault[strlen(vault) - 1] == '/' ? "" : "/", path);
    snprintf(auth, sizeof auth, "Authorization: Bearer %s", tok);
    struct curl_slist *h = curl_slist_append(NULL, auth);
    h = curl_slist_append(h, "Content-Type: application/json");
    char *json = body ? cJSON_PrintUnformatted(body) : NULL;
    buf_t resp = {0};
    long st = http(method, url, h, json, &resp, 1);
    curl_slist_free_all(h);
    OPENSSL_cleanse(auth, sizeof auth);
    if (json) { OPENSSL_cleanse(json, strlen(json)); cJSON_free(json); }
    if (out) *out = resp.len ? cJSON_Parse(resp.data) : NULL;
    buf_wipe(&resp);
    return st;
}

static int valid_name(const char *n) {        /* 1-127 alphanumerics or hyphens */
    size_t len = strlen(n);
    if (len == 0 || len > 127) return 0;
    for (; *n; n++) if (!((*n >= 'a' && *n <= 'z') || (*n >= 'A' && *n <= 'Z') || (*n >= '0' && *n <= '9') || *n == '-')) return 0;
    return 1;
}

/* UPDATE (and second half of CREATE): PUT adds a new current version. Returns 0 on success. */
static int secret_set(const char *name, const char *value) {
    char path[160]; snprintf(path, sizeof path, "secrets/%s", name);
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "value", value);
    cJSON_AddStringToObject(body, "contentType", "text/plain");
    cJSON_AddStringToObject(cJSON_AddObjectToObject(body, "tags"), "app", "secrets-crud");
    cJSON *out = NULL;
    long st = kv("PUT", path, body, &out);
    cJSON_Delete(body);
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(out, "value");
    if (cJSON_IsString(v)) OPENSSL_cleanse(v->valuestring, strlen(v->valuestring));   /* response echoes value */
    cJSON_Delete(out);
    if (st == 409) fprintf(stderr, "%s is soft-deleted; recover or purge it first\n", name);
    else if (st != 200) fprintf(stderr, "set: HTTP %ld\n", st);
    return st == 200 ? 0 : -1;
}

/* CREATE: PUT is an upsert, so prove the name is unused first (not atomic). */
static int secret_create(const char *name, const char *value) {
    char path[160]; snprintf(path, sizeof path, "secrets/%s", name);
    cJSON *out = NULL;
    long st = kv("GET", path, NULL, &out);
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(out, "value");
    if (cJSON_IsString(v)) OPENSSL_cleanse(v->valuestring, strlen(v->valuestring));
    cJSON_Delete(out);
    if (st == 200) { fprintf(stderr, "secret already exists (create is not an upsert)\n"); return -1; }
    if (st != 404) { fprintf(stderr, "probe: HTTP %ld\n", st); return -1; }
    return secret_set(name, value);
}

/* READ current version; returns malloc'd value (wipe + free) or NULL. */
static char *secret_read(const char *name) {
    char path[160]; snprintf(path, sizeof path, "secrets/%s", name);
    cJSON *out = NULL;
    long st = kv("GET", path, NULL, &out);
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(out, "value");
    char *r = (st == 200 && cJSON_IsString(v)) ? strdup(v->valuestring) : NULL;
    if (cJSON_IsString(v)) OPENSSL_cleanse(v->valuestring, strlen(v->valuestring));
    cJSON_Delete(out);
    return r;
}

/* DELETE: soft delete, then wait until the deleted entry is visible. */
static int secret_delete(const char *name) {
    char path[160]; snprintf(path, sizeof path, "secrets/%s", name);
    cJSON *out = NULL;
    long st = kv("DELETE", path, NULL, &out);
    cJSON_Delete(out);
    if (st != 200) { fprintf(stderr, "delete: HTTP %ld\n", st); return -1; }
    snprintf(path, sizeof path, "deletedsecrets/%s", name);
    for (int i = 0; i < 30; i++) {
        out = NULL;
        st = kv("GET", path, NULL, &out);
        cJSON_Delete(out);
        if (st == 200) return 0;
        struct timespec ts = {2, 0};
        nanosleep(&ts, NULL);
    }
    return -1;
}

/* PURGE: permanent; fails (403) when purge protection is enabled. */
static int secret_purge(const char *name) {
    char path[160]; snprintf(path, sizeof path, "deletedsecrets/%s", name);
    long st = kv("DELETE", path, NULL, NULL);
    return st == 204 ? 0 : -1;
}

static void random_value(char out[45]) {
    unsigned char raw[32];
    RAND_bytes(raw, sizeof raw);
    EVP_EncodeBlock((unsigned char *)out, raw, sizeof raw);
    OPENSSL_cleanse(raw, sizeof raw);
}

static int same(const char *a, const char *b) {
    return b && strlen(a) == strlen(b) && CRYPTO_memcmp(a, b, strlen(a)) == 0;
}

int main(void) {
    const char *vault = getenv("AZURE_KEYVAULT_URL"), *name = getenv("SECRET_NAME");
    if (!vault || !*vault || !name || !valid_name(name)) {
        fprintf(stderr, "set AZURE_KEYVAULT_URL and a valid SECRET_NAME\n"); return 2;
    }
    curl_global_init(CURL_GLOBAL_DEFAULT);
    int rc = 1;
    char v1[45], v2[45], *got = NULL;

    random_value(v1);
    if (secret_create(name, v1) != 0) goto done;
    printf("created: %s\n", name);
    got = secret_read(name);
    if (!same(v1, got)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    str_wipe_free(got); got = NULL;

    random_value(v2);
    if (secret_set(name, v2) != 0) goto done;
    got = secret_read(name);
    if (!same(v2, got)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated: new version\n");

    if (secret_delete(name) != 0) goto done;
    printf("soft-deleted: %s\n", name);
    const char *purge = getenv("PURGE_AFTER_DELETE");
    if (purge && strcmp(purge, "1") == 0) {
        if (secret_purge(name) != 0) goto done;
        printf("purged: %s\n", name);
    }
    rc = 0;
done:
    str_wipe_free(got);
    str_wipe_free(g_token);
    OPENSSL_cleanse(v1, sizeof v1); OPENSSL_cleanse(v2, sizeof v2);
    curl_global_cleanup();
    return rc;
}
```

## 10. Use secrets in applications

| Mechanism | How the value arrives | Notes |
| --- | --- | --- |
| Direct SDK call + in-process cache | In memory | Preferred for services you own. |
| App Service / Functions Key Vault references (`@Microsoft.KeyVault(SecretUri=…)`) | App setting → environment variable | Versionless URIs are refreshed periodically (about every 24 hours) or on restart; env exposure applies. |
| AKS Secrets Store CSI Driver (Azure Key Vault provider) | Mounted files (optional sync to Kubernetes Secret) | Rotation polling must be enabled explicitly; tmpfs mount; avoid sync unless needed. |
| Container Apps secrets referencing Key Vault | Env var or volume | Managed identity required. |
| Azure App Configuration Key Vault references | App Config resolves via your identity | The app still needs `Secrets User` on the vault. |

Rotation-safe consumption: read current at startup; cache with a TTL; on downstream authentication failure, refetch once and retry once; never pin a version ID in long-lived configuration unless your deploy process updates it.

## 11. Automation and error handling

| HTTP / code | Meaning | Action |
| --- | --- | --- |
| 401 | Missing or invalid token; first request in SDK challenge flow | SDKs handle the challenge; persistent 401 means a token for the wrong resource/tenant. |
| 403 `Forbidden` | RBAC missing; version disabled; purge protection | Check role at secret/vault scope and the `enabled` attribute. |
| 403 `ForbiddenByFirewall` | Network rules / private endpoint | Fix network path, not RBAC. |
| 404 `SecretNotFound` | Wrong name/vault, or soft-deleted | `az keyvault secret show-deleted`. |
| 409 `Conflict` | Name held by a soft-deleted secret, or delete/recover still in progress | Recover or purge; wait and retry. |
| 429 | Throttled | SDKs retry with backoff; cache reads; reduce creates. |
| 5xx | Service | Retry with backoff. |

Practices:

- Treat `SetSecret` as an upsert everywhere; enforce "create only" in your own code or pipeline.
- Use one writer per secret; concurrent `SetSecret` calls create interleaved versions and the last one wins.
- Re-read after writes when correctness matters; compare in constant time without logging.
- Do not purge in normal operations. Enable purge protection on production vaults.
- Retry policies: the SDKs retry 408/429/5xx with exponential backoff and honor `Retry-After`; REST clients must implement the same.

## 12. Optional live CRUD verification

This **performs writes** in the vault you choose. Use a sandbox vault without purge protection if you want the test to clean up completely.

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${VAULT:?set VAULT}"
az account show --query tenantId -o tsv > /dev/null

work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
name="crud-check-$(date -u +%Y%m%d%H%M%S)-$$"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v1"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v2"

az keyvault secret set --vault-name "$VAULT" --name "$name" --file "$work/v1" --encoding utf-8 --query id -o tsv
az keyvault secret download --vault-name "$VAULT" --name "$name" --file "$work/r1" --encoding utf-8
cmp -s "$work/r1" "$work/v1"

az keyvault secret set --vault-name "$VAULT" --name "$name" --file "$work/v2" --encoding utf-8 --query id -o tsv > /dev/null
az keyvault secret download --vault-name "$VAULT" --name "$name" --file "$work/r2" --encoding utf-8
cmp -s "$work/r2" "$work/v2"

az keyvault secret delete --vault-name "$VAULT" --name "$name" --query recoveryId -o tsv > /dev/null
for _ in $(seq 1 30); do
  az keyvault secret show-deleted --vault-name "$VAULT" --name "$name" --query recoveryId -o tsv > /dev/null 2>&1 && break
  sleep 2
done
az keyvault secret purge --vault-name "$VAULT" --name "$name" || printf 'purge skipped (purge protection?)\n'
printf 'PASS: create, read, update, and delete completed.\n'
```

It does not test RBAC scoping, firewall rules, expiry, or Event Grid notifications.

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| `DefaultAzureCredential failed to retrieve a token` | No managed/workload identity available to this process; check pod labels/service account (AKS), identity assignment (VM/App Service). |
| Works locally, 403 in Azure | Local run used your user account; the workload identity lacks `Key Vault Secrets User`. |
| 403 with RBAC correct | Vault uses access policies, not RBAC; or firewall/private endpoint; or the current version is disabled. |
| 409 on set | Soft-deleted secret with that name; recover or purge. |
| Read fails after disabling newest version | Disabling does not fall back; set the previous value again. |
| App Service still uses old value | Key Vault reference refresh interval; restart or use a versioned URI rollout. |
| Purge returns 403 | Purge protection enabled or missing purge permission. |
| Secret value appears in logs | HTTP content logging enabled, or the app logged a `SetSecret` response. Disable, purge logs, rotate. |
| `ForbiddenByFirewall` | Caller IP/subnet not allowed; use a private endpoint or allow the subnet. |

## 14. Accuracy notes and official sources

- **Upsert semantics** are inherent to `PUT /secrets/{name}`; the "create only" behavior in the programs is application logic, not an API feature.
- **Soft delete:** the overview states it is on by default and cannot be disabled once enabled; older vaults created before the default may differ. Retention 7–90 days (default 90) is fixed at vault creation. [S06]
- **Value size (25 KB)** is from the secrets overview; the service-limits page lists throttling and version guidance but not value size. [S04] [S05]
- **Expiry is informational for secrets:** the secrets overview states that `get` works outside the `nbf`/`exp` window. [S04]
- **Rust:** the official crate has no `DefaultAzureCredential`; the program selects workload or managed identity explicitly.
- **C#, Java, C++, Swift** were not compiled in the authoring environment.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [Key Vault secrets REST API][S01] | Set, Get, Update, Delete, Get Deleted, Purge, Recover |
| S02 | [Azure Identity / DefaultAzureCredential][S02] | Credential chain and environment variables |
| S03 | [Azure RBAC for Key Vault][S03] | Built-in roles and scopes |
| S04 | [About Key Vault secrets][S04] | Names, 25 KB values, attributes, content type |
| S05 | [Key Vault service limits][S05] | Throttling, versions guidance |
| S06 | [Soft-delete overview][S06] | Retention, purge protection, name reservation |
| S07 | [azsecrets (Go)][S07] | Go client |
| S08 | [azure_security_keyvault_secrets (Rust)][S08] | Rust client and models |
| S09 | [Azure.Security.KeyVault.Secrets (.NET) source][S09] | .NET overloads |
| S10 | [azure-security-keyvault-secrets (Java) source][S10] | Java client |
| S11 | [azure-sdk-for-cpp Key Vault secrets][S11] | C++ client and samples |
| S12 | [Key Vault Event Grid events][S12] | NearExpiry, Expired, NewVersionCreated |
| S13 | [Managed identity token endpoint (IMDS)][S13] | REST token acquisition |
| S14 | [Workload identity federation token exchange][S14] | client_assertion flow |

[S01]: https://learn.microsoft.com/en-us/rest/api/keyvault/secrets/operation-groups
[S02]: https://learn.microsoft.com/en-us/azure/developer/intro/passwordless-overview
[S03]: https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide
[S04]: https://learn.microsoft.com/en-us/azure/key-vault/secrets/about-secrets
[S05]: https://learn.microsoft.com/en-us/azure/key-vault/general/service-limits
[S06]: https://learn.microsoft.com/en-us/azure/key-vault/general/soft-delete-overview
[S07]: https://pkg.go.dev/github.com/Azure/azure-sdk-for-go/sdk/security/keyvault/azsecrets
[S08]: https://docs.rs/azure_security_keyvault_secrets
[S09]: https://github.com/Azure/azure-sdk-for-net/tree/main/sdk/keyvault/Azure.Security.KeyVault.Secrets
[S10]: https://github.com/Azure/azure-sdk-for-java/tree/main/sdk/keyvault/azure-security-keyvault-secrets
[S11]: https://github.com/Azure/azure-sdk-for-cpp/tree/main/sdk/keyvault/azure-security-keyvault-secrets
[S12]: https://learn.microsoft.com/en-us/azure/event-grid/event-schema-key-vault
[S13]: https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/how-to-use-vm-token
[S14]: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow
