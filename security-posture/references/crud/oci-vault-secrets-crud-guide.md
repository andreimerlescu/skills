# OCI Vault secrets: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** Oracle Cloud Infrastructure Vault — management API `20180608` (`vaults.<region>.oci.oraclecloud.com`) for writes and the Secrets retrieval API `20190301` (`secrets.vaults.<region>.oci.oraclecloud.com`) for reads  
**Primary authentication:** OCI principals: instance principals, resource principals, or OKE workload identity inside OCI; an API signing key elsewhere  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use Bash and the OCI CLI 3.x)

This guide covers **secrets in an OCI Vault**: a secret resource encrypted under a symmetric master encryption key in the same vault, with numbered **secret versions** whose content is base64 and whose rotation state (`CURRENT`, `PENDING`, `PREVIOUS`, `LATEST`, `DEPRECATED`) determines what readers get. It covers identity, IAM policy, complete CRUD workflows (including OCI's asynchronous lifecycle and scheduled deletion), OCI HTTP request signing for languages without an SDK, a full CRUD program in each of ten languages, runtime consumption, and troubleshooting. Key management, vault creation, and cross-region replication are covered only where they change CRUD behavior.

Credentials are assumed to be provisioned already. Do not paste API private keys, fingerprints of production keys, or session tokens into documents, source files, or command arguments.

**Verification boundary:** Paths, models, and semantics were cross-checked against the official OCI documentation and the generated SDK sources listed in section 14. The TypeScript program passed `tsc --strict` against `oci-vault`/`oci-secrets` 2.144.0. The Python program (OCI Python SDK 2.189.0), and the Rust, PHP, C++, and C programs, which implement OCI request signing themselves, all ran end-to-end against a local HTTPS mock of the two APIs that **verifies every request signature** (rsa-sha256 over the documented header list, plus the body hash) against the test key's public key; the official Python SDK's signer passed the same check, which validates the mock. The Go program passed `go vet` against `oci-go-sdk/v65` v65.128.0, and the C# and Java programs were checked against the generated SDK sources (`oci-dotnet-sdk`, `oci-java-sdk`) but not compiled here. The Swift program, which signs with swift-crypto, was not compiled (no Swift toolchain was available). No call was made to a real OCI tenancy. Section 12 provides an optional live test.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Use the existing identity](#2-use-the-existing-identity)
3. [Data model and addressing](#3-data-model-and-addressing)
4. [Safe secret handling](#4-safe-secret-handling)
5. [Create secrets](#5-create-secrets)
6. [Read secrets](#6-read-secrets)
7. [Update secrets](#7-update-secrets)
8. [Schedule deletion and cancel](#8-schedule-deletion-and-cancel)
9. [Language implementations](#9-language-implementations)
10. [Use secrets in applications](#10-use-secrets-in-applications)
11. [Automation and error handling](#11-automation-and-error-handling)
12. [Optional live CRUD verification](#12-optional-live-crud-verification)
13. [Troubleshooting](#13-troubleshooting)
14. [Accuracy notes and official sources](#14-accuracy-notes-and-official-sources)

## 1. Requirements and conventions

| Language | Official client | Transport used here | Verified here |
| --- | --- | --- | --- |
| Go | `github.com/oracle/oci-go-sdk/v65` (`vault`, `secrets`) | SDK | `go vet` (v65.128.0) |
| Rust | none (community crates only) | REST + OCI signing (`rsa`, `reqwest`) | `cargo check`, signature-verified mock run |
| PHP | preview SDK covers Object Storage only | REST + OCI signing (`openssl_sign`) | signature-verified mock run |
| C# | `OCI.DotNetSDK.Vault` + `OCI.DotNetSDK.Secrets` | SDK | source check |
| Java | `oci-java-sdk-vault` + `oci-java-sdk-secrets` (3.x) | SDK | source check |
| Swift | none | REST + OCI signing (swift-crypto `_RSA`) | not compiled |
| Python | `oci` | SDK | signature-verified mock run |
| TypeScript | `oci-vault` + `oci-secrets` + `oci-common` | SDK | `tsc --strict` (2.144.0) |
| C++ | none | REST + OCI signing (OpenSSL EVP) | `-Werror`, signature-verified mock run |
| C | none | REST + OCI signing (OpenSSL EVP) | `-Werror`, signature-verified mock run |

Every program follows the same contract:

- Non-secret configuration: `OCI_COMPARTMENT_ID`, `OCI_VAULT_ID`, `OCI_KEY_ID` (a symmetric key in that vault), and `SECRET_NAME`.
- SDK programs choose identity with `OCI_AUTH` = `instance_principal`, `oke_workload_identity`, or (default) the `~/.oci/config` profile. REST programs use an API signing key from `OCI_CLI_USER`, `OCI_CLI_TENANCY`, `OCI_CLI_FINGERPRINT`, `OCI_CLI_KEY_FILE`, `OCI_CLI_REGION` (the OCI CLI's own variable names), with optional `OCI_VAULT_ENDPOINT`/`OCI_SECRETS_ENDPOINT` for private endpoints or other realms.
- The program generates a 256-bit random value, **creates** the secret (with an `opc-retry-token`) and waits for `ACTIVE`, **reads** the `CURRENT` bundle and compares in constant time, **updates** the content (new `CURRENT` version) and waits again, reads and compares, then **schedules deletion** one day out.
- It prints OCIDs, version numbers, and dates only.

For CLI snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
oci --version
COMPARTMENT_ID='REPLACE_WITH_COMPARTMENT_OCID'
VAULT_ID='REPLACE_WITH_VAULT_OCID'
KEY_ID='REPLACE_WITH_SYMMETRIC_KEY_OCID'
```

## 2. Use the existing identity

### Principal types

| Where the code runs | Principal | SDK selection | Long-lived credential on host? |
| --- | --- | --- | --- |
| Compute instance | Instance principal (dynamic group membership) | `InstancePrincipals…Provider` / `auth.InstancePrincipalConfigurationProvider()` | No |
| OKE pod (enhanced cluster) | OKE workload identity | `OkeWorkloadIdentity…Provider` | No |
| Functions, other OCI services | Resource principal | `ResourcePrincipal…Provider` | No |
| Developer workstation | Session token (`oci session authenticate`) or API key | config file profile | Session: short-lived |
| External CI or servers | API signing key (user or service user) | config file / env | **Yes** — protect and rotate |

Prefer principals over API keys. An API key is an RSA private key plus a fingerprint registered on a user; it is a long-lived secret. If a workload outside OCI must use one, create a dedicated service user with only the needed group membership, keep the key on tmpfs or in another secrets manager, and rotate it.

### Confirm identity without displaying keys

```bash
oci iam region list --query 'data[0].name' --raw-output > /dev/null && printf 'auth ok\n'
oci iam user get --user-id "$(awk -F= '/^user=/{print $2}' ~/.oci/config | head -1)" \
  --query 'data.{name:name, id:id}' 2>/dev/null
```

For instance principals, add `--auth instance_principal` to OCI CLI commands; for session tokens, `--auth security_token`. These print identifiers, never key material.

### Required IAM policy

Secrets use the resource types `secrets`, `secret-versions`, and `secret-bundles` (aggregate: `secret-family`). Creating a secret also needs `use vaults` and `use keys`. Reads of values require `read secret-bundles`. [S03]

```text
# Runtime: read only one secret's value
Allow dynamic-group myapp-prod-dg to read secret-bundles in compartment prod
  where target.secret.name = 'myapp-prod-db'

# Provisioning/rotation: create and manage secrets in one vault
Allow group myapp-secret-admins to use vaults in compartment prod where target.vault.id = 'ocid1.vault.oc1..REPLACE'
Allow group myapp-secret-admins to use keys in compartment prod where target.key.id = 'ocid1.key.oc1..REPLACE'
Allow group myapp-secret-admins to manage secrets in compartment prod where target.vault.id = 'ocid1.vault.oc1..REPLACE'
```

`target.secret.name`, `target.secret.id`, `target.vault.id`, and `target.key.id` are available condition variables. Use compartments per environment.

## 3. Data model and addressing

- **Secret OCID:** `ocid1.vaultsecret.oc1.<region>.<unique>`. Names are unique per vault, use letters, digits, `-`, `_`, and `.`, and must not contain confidential information. [S04] [S05]
- **Content:** base64-encoded (`contentType: BASE64`); the secret bundle may be at most **25 KB**. [S04]
- **Encryption:** each secret is encrypted with a **symmetric** master encryption key **in the same vault**. [S04]
- **Versions and stages:** each content update creates a version. Rotation states: `CURRENT` (what readers get by default), `PENDING` (staged), `PREVIOUS`, `LATEST`, `DEPRECATED`. Versions can be read by `versionNumber`, `secretVersionName`, or `stage`.
- **Rules:** optional *secret reuse* rule (forbid reusing old content) and *expiry* rule (version expiry 1–90 days; absolute secret expiry 1–365 days ahead). [S04]
- **Lifecycle:** `CREATING → ACTIVE`, `UPDATING → ACTIVE`, `SCHEDULING_DELETION → PENDING_DELETION → DELETED`, `CANCELLING_DELETION → ACTIVE`, `FAILED`. Create and update are **asynchronous**; read only after `ACTIVE`.
- **Two endpoints:** the management API (vaults host) never returns content; the retrieval API (secrets host) does. Network rules and IAM can treat them separately.

Inventory without values:

```bash
oci vault secret list --compartment-id "$COMPARTMENT_ID" --vault-id "$VAULT_ID" --all \
  --query 'data[].{name:"secret-name", id:id, state:"lifecycle-state"}' --output table
SECRET_ID='REPLACE_WITH_SECRET_OCID'
oci vault secret-version list --secret-id "$SECRET_ID" --all \
  --query 'data[].{v:"version-number", stages:stages, created:"time-created"}' --output table
```

## 4. Safe secret handling

- **CLI arguments:** `oci vault secret create-base64 --secret-content-content <b64>` places the (only base64-encoded) secret in shell history and the process table. Use `--from-json file://request.json` with a `0600` file, or an SDK.
- **Base64 is encoding, not protection.** Treat base64 content exactly like plaintext in logs and files.
- **Names and descriptions** are visible to anyone with `inspect`/`read secrets`; never encode secrets or sensitive context in them.
- **SDK logging:** OCI SDK debug logging (for example Python `oci` logger at `DEBUG`, Java request/response logging, `OCI_GO_SDK_DEBUG`) can include request and response bodies. Keep it off around secret operations.
- **API signing keys:** the REST programs read the PEM once at startup; store it with `0600` permissions, never in the repository or image, and prefer principals inside OCI.
- **Memory:** wipe byte buffers where possible (`zeroize`, `OPENSSL_cleanse`, `CryptographicOperations.ZeroMemory`, `Arrays.fill`, `Buffer.fill`).

### OCI request signing (for REST clients)

All OCI API calls are signed with the [draft-cavage HTTP Signatures](https://tools.ietf.org/html/draft-cavage-http-signatures-08) scheme, `rsa-sha256` (RSASSA-PKCS1-v1_5 with SHA-256). [S06]

1. Build the signing string, one `name: value` line per header, in this order, joined with `\n`:
   - `GET`/`DELETE`/`HEAD`: `date`, `(request-target)`, `host`
   - `POST`/`PUT`/`PATCH`: additionally `content-length`, `content-type`, `x-content-sha256`
2. `(request-target)` is `<lowercase method> <path>?<query>`, for example `get /20190301/secretbundles/ocid1.vaultsecret…?stage=CURRENT`.
3. `x-content-sha256` is the base64 SHA-256 of the exact body bytes (an empty body still needs it for `POST`).
4. Sign with the API private key; send `Authorization: Signature version="1",keyId="<tenancy OCID>/<user OCID>/<key fingerprint>",algorithm="rsa-sha256",headers="<the header list>",signature="<base64>"`, and send the same `date`, `host`, and body headers you signed.

Headers you add but do not sign (such as `opc-retry-token`) are allowed. The REST programs in section 9 implement exactly this and were checked against a verifier that the official SDK's signer also passes.

## 5. Create secrets

`POST /20180608/secrets` on the management endpoint with `CreateSecretDetails`: `compartmentId`, `vaultId`, `keyId`, `secretName`, `secretContent {contentType: BASE64, content}`, optional `description`, `freeformTags`/`definedTags`, `metadata`, `secretRules`, `rotationConfig`, `replicationConfig`. [S02]

- The response is the secret in state `CREATING`. Poll `GET /20180608/secrets/{id}` (or use the SDK waiter) until `ACTIVE` before reading.
- Send `opc-retry-token` so a retried create returns the same secret instead of a duplicate.
- A duplicate name in the same vault fails with **409**. Create is not an upsert.
- OCI can also **generate** secret content (`enableAutoGeneration` with a `secretGenerationContext` for passphrases, SSH keys, or bytes) so the value never passes through your code.

### A. Create from a protected JSON request file

```bash
(
  set -euo pipefail; set +x; umask 077
  work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
  jq -n --arg comp "$COMPARTMENT_ID" --arg vault "$VAULT_ID" --arg key "$KEY_ID" \
        --rawfile v /secure/path/to/api-token.txt '{
      compartmentId: $comp, vaultId: $vault, keyId: $key,
      secretName: "myapp-dev-api-token", description: "Partner API token (dev)",
      freeformTags: {app: "myapp", env: "dev"},
      secretContentContent: ($v | @base64)
    }' > "$work/create.json"
  oci vault secret create-base64 --from-json "file://$work/create.json" \
    --wait-for-state ACTIVE --query 'data.{id:id, state:"lifecycle-state"}'
)
```

`--from-json` uses the CLI's own parameter names in camelCase (`secretContentContent`, not the API's nested `secretContent`); generate the full template with `oci vault secret create-base64 --generate-full-command-json-input`. `@base64` encodes the file's exact text, including a trailing newline if present.

### B. Let OCI generate the value

```bash
oci vault secret create-base64 --compartment-id "$COMPARTMENT_ID" --vault-id "$VAULT_ID" --key-id "$KEY_ID" \
  --secret-name myapp-dev-generated --enable-auto-generation true \
  --secret-generation-context '{"generationType":"PASSPHRASE","generationTemplate":"DBAAS_DEFAULT_PASSWORD"}' \
  --wait-for-state ACTIVE --query 'data.id' --raw-output
```

`--enable-auto-generation` and `--secret-generation-context` are available on current CLI releases (verified on OCI CLI 3.95); the SDK equivalents are `PassphraseGenerationContext`, `SshKeyGenerationContext`, and `BytesGenerationContext`.

## 6. Read secrets

`GET /20190301/secretbundles/{secretId}` on the **secrets** endpoint, optionally with `stage`, `versionNumber`, or `secretVersionName`; or `POST /20190301/secretbundles/actions/getByName?secretName=…&vaultId=…`. The default is the `CURRENT` version. The bundle's `secretBundleContent.content` is base64. [S02]

```bash
# Decode CURRENT content into a new private file (never the terminal)
oci secrets secret-bundle get --secret-id "$SECRET_ID" --stage CURRENT \
  --query 'data."secret-bundle-content".content' --raw-output | base64 -d > ./api-token.secret

# By name within a vault
oci secrets secret-bundle get-secret-bundle-by-name --secret-name myapp-dev-api-token --vault-id "$VAULT_ID" \
  --query 'data."version-number"'

# A previous version
oci secrets secret-bundle get --secret-id "$SECRET_ID" --stage PREVIOUS --query 'data."version-number"'
```

Secrets in `PENDING_DELETION` are inaccessible to readers immediately. [S07]

## 7. Update secrets

`PUT /20180608/secrets/{secretId}` with `UpdateSecretDetails`. New `secretContent` creates a new version (by default promoted to `CURRENT`); the secret passes through `UPDATING`. You can instead set `currentVersionNumber` to promote an existing version (rollback), or change `description`, tags, `metadata`, rules, and rotation configuration. Contents, version number, and rules cannot be changed in the same call. [S02]

```bash
# New content from a protected file (request via JSON to keep it out of argv)
(
  set -euo pipefail; set +x; umask 077
  work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
  jq -n --arg id "$SECRET_ID" --rawfile v /secure/path/new-token.txt \
    '{secretId: $id, secretContentContent: ($v | @base64)}' > "$work/update.json"
  oci vault secret update-base64 --from-json "file://$work/update.json" \
    --wait-for-state ACTIVE --query 'data."current-version-number"'
)

# Roll back by promoting an earlier version
oci vault secret update --secret-id "$SECRET_ID" --current-version-number 3 --wait-for-state ACTIVE \
  --query 'data."current-version-number"'
```

Verify without printing values:

```bash
oci secrets secret-bundle get --secret-id "$SECRET_ID" --stage CURRENT \
  --query 'data."secret-bundle-content".content' --raw-output | base64 -d |
  cmp -s - /secure/path/new-token.txt && printf 'Secret replacement verified.\n'
```

Updating stored content does not rotate the credential at its source. OCI Vault supports **automatic rotation** for supported targets (for example Autonomous Database) and function-based rotation via `rotationConfig`; otherwise rotate at the source and then update.

## 8. Schedule deletion and cancel

Secrets are never deleted immediately. `POST /20180608/secrets/{id}/actions/scheduleDeletion` with `timeOfDeletion` (RFC 3339) schedules deletion **between 1 and 30 days** ahead (default 30 when not specified). The secret moves to `PENDING_DELETION`, becomes unreadable at once, and cannot be updated or rotated. `POST …/actions/cancelDeletion` restores it before the deadline. After deletion the contents are irreversibly destroyed. Deleting a source secret also deletes its replicas. [S07]

Individual versions can be scheduled for deletion with `scheduleSecretVersionDeletion` (the `CURRENT` version cannot).

```bash
# Inspect the exact target first
oci vault secret get --secret-id "$SECRET_ID" --query 'data.{name:"secret-name", state:"lifecycle-state"}'

# Schedule deletion 7 days out
oci vault secret schedule-secret-deletion --secret-id "$SECRET_ID" \
  --time-of-deletion "$(date -u -d '+7 days' +%Y-%m-%dT%H:%M:%SZ)"

# Cancel during the window
oci vault secret cancel-secret-deletion --secret-id "$SECRET_ID"
```

The documentation describes the cancellation window inconsistently (one page says cancellation is possible while deletion is pending; a linked description mentions a 7-day period); test cancellation in your tenancy before relying on a long window. Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Each program is complete and self-checking. Expected output:

```text
created: ocid1.vaultsecret.oc1.iad.amaaaaaa...
updated: current version 2
deletion scheduled for 2026-10-27T18:05:11Z
```

A second run with the same `SECRET_NAME` fails with 409 while the first secret is pending deletion (names are unique per vault). Use a unique name per test run.

### 9.1 Go

`go get github.com/oracle/oci-go-sdk/v65`. `common.IsServiceError` exposes the HTTP status; `common.RetryToken()` generates an `opc-retry-token`.

```go
// OCI Vault secrets CRUD with the OCI Go SDK (github.com/oracle/oci-go-sdk/v65).
// Writes use the Vault management API (vault.VaultsClient); reads use the Secrets retrieval API.
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

	"github.com/oracle/oci-go-sdk/v65/common"
	"github.com/oracle/oci-go-sdk/v65/common/auth"
	"github.com/oracle/oci-go-sdk/v65/secrets"
	"github.com/oracle/oci-go-sdk/v65/vault"
)

func provider() (common.ConfigurationProvider, error) {
	switch os.Getenv("OCI_AUTH") {
	case "instance_principal": // compute instances in a dynamic group
		return auth.InstancePrincipalConfigurationProvider()
	case "oke_workload_identity": // pods on OKE enhanced clusters
		return auth.OkeWorkloadIdentityConfigurationProvider()
	default: // ~/.oci/config DEFAULT profile (developer machines, external CI with API keys)
		return common.DefaultConfigProvider(), nil
	}
}

type Store struct {
	vaults                         vault.VaultsClient
	bundles                        secrets.SecretsClient
	compartmentID, vaultID, keyID string
}

func b64Content(v []byte) vault.Base64SecretContentDetails {
	return vault.Base64SecretContentDetails{Content: common.String(base64.StdEncoding.EncodeToString(v))}
}

// waitActive polls until the asynchronous create/update finishes.
func (s *Store) waitActive(ctx context.Context, id string) error {
	for i := 0; i < 60; i++ {
		r, err := s.vaults.GetSecret(ctx, vault.GetSecretRequest{SecretId: common.String(id)})
		if err != nil {
			return err
		}
		switch r.LifecycleState {
		case vault.SecretLifecycleStateActive:
			return nil
		case vault.SecretLifecycleStateFailed:
			return errors.New("secret entered FAILED")
		}
		time.Sleep(2 * time.Second)
	}
	return errors.New("timed out waiting for ACTIVE")
}

// Create stores a new secret; names are unique per vault (HTTP 409 on duplicates).
func (s *Store) Create(ctx context.Context, name string, value []byte) (string, error) {
	r, err := s.vaults.CreateSecret(ctx, vault.CreateSecretRequest{
		CreateSecretDetails: vault.CreateSecretDetails{
			CompartmentId: common.String(s.compartmentID),
			VaultId:       common.String(s.vaultID),
			KeyId:         common.String(s.keyID), // symmetric master encryption key in the same vault
			SecretName:    common.String(name),
			Description:   common.String("managed by secrets-crud example"),
			FreeformTags:  map[string]string{"app": "secrets-crud"},
			SecretContent: b64Content(value),
		},
		OpcRetryToken: common.String(common.RetryToken()), // idempotent retries
	})
	if se, ok := common.IsServiceError(err); ok && se.GetHTTPStatusCode() == http.StatusConflict {
		return "", fmt.Errorf("secret %q already exists in this vault: %w", name, err)
	}
	if err != nil {
		return "", fmt.Errorf("create secret: %w", err)
	}
	return *r.Id, s.waitActive(ctx, *r.Id)
}

// Read returns the CURRENT version's content.
func (s *Store) Read(ctx context.Context, id string) ([]byte, error) {
	r, err := s.bundles.GetSecretBundle(ctx, secrets.GetSecretBundleRequest{
		SecretId: common.String(id),
		Stage:    secrets.GetSecretBundleStageCurrent,
	})
	if err != nil {
		return nil, fmt.Errorf("get secret bundle: %w", err)
	}
	content, ok := r.SecretBundleContent.(secrets.Base64SecretBundleContentDetails)
	if !ok || content.Content == nil {
		return nil, errors.New("secret bundle has no base64 content")
	}
	return base64.StdEncoding.DecodeString(*content.Content)
}

// Update writes new content, which becomes a new CURRENT version.
func (s *Store) Update(ctx context.Context, id string, value []byte) (int64, error) {
	r, err := s.vaults.UpdateSecret(ctx, vault.UpdateSecretRequest{
		SecretId:            common.String(id),
		UpdateSecretDetails: vault.UpdateSecretDetails{SecretContent: b64Content(value)},
	})
	if err != nil {
		return 0, fmt.Errorf("update secret: %w", err)
	}
	if err := s.waitActive(ctx, id); err != nil {
		return 0, err
	}
	return *r.CurrentVersionNumber, nil
}

// ScheduleDeletion deletes after 1-30 days; CancelSecretDeletion restores it until then.
func (s *Store) ScheduleDeletion(ctx context.Context, id string, days int) (time.Time, error) {
	when := time.Now().UTC().Add(time.Duration(days)*24*time.Hour + time.Minute)
	_, err := s.vaults.ScheduleSecretDeletion(ctx, vault.ScheduleSecretDeletionRequest{
		SecretId:                      common.String(id),
		ScheduleSecretDeletionDetails: vault.ScheduleSecretDeletionDetails{TimeOfDeletion: &common.SDKTime{Time: when}},
	})
	return when, err
}

func randomValue() []byte {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		log.Fatal("csprng: ", err)
	}
	return []byte(base64.RawURLEncoding.EncodeToString(b))
}

func main() {
	comp, vaultID, keyID, name := os.Getenv("OCI_COMPARTMENT_ID"), os.Getenv("OCI_VAULT_ID"), os.Getenv("OCI_KEY_ID"), os.Getenv("SECRET_NAME")
	if comp == "" || vaultID == "" || keyID == "" || name == "" {
		log.Fatal("set OCI_COMPARTMENT_ID, OCI_VAULT_ID, OCI_KEY_ID, SECRET_NAME")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	p, err := provider()
	if err != nil {
		log.Fatal(err)
	}
	vc, err := vault.NewVaultsClientWithConfigurationProvider(p)
	if err != nil {
		log.Fatal(err)
	}
	sc, err := secrets.NewSecretsClientWithConfigurationProvider(p)
	if err != nil {
		log.Fatal(err)
	}
	store := &Store{vaults: vc, bundles: sc, compartmentID: comp, vaultID: vaultID, keyID: keyID}

	v1 := randomValue()
	id, err := store.Create(ctx, name, v1)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("created:", id)
	if got, err := store.Read(ctx, id); err != nil || subtle.ConstantTimeCompare(got, v1) != 1 {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	ver, err := store.Update(ctx, id, v2)
	if err != nil {
		log.Fatal(err)
	}
	if got, err := store.Read(ctx, id); err != nil || subtle.ConstantTimeCompare(got, v2) != 1 {
		log.Fatal("read-back after update failed: ", err)
	}
	fmt.Println("updated: current version", ver)

	when, err := store.ScheduleDeletion(ctx, id, 1)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("deletion scheduled for", when.Format(time.RFC3339))
}
```

### 9.2 Rust

`Cargo.toml`:

```toml
[package]
name = "oci-secrets-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
reqwest = { version = "0.12", default-features = false, features = ["json", "rustls-tls-native-roots"] }
serde_json = "1"
tokio = { version = "1", features = ["macros", "rt-multi-thread", "time"] }
rsa = { version = "0.9", features = ["sha2"] }
sha2 = "0.10"
base64 = "0.22"
httpdate = "1"
uuid = { version = "1", features = ["v4"] }
getrandom = "0.3"
zeroize = "1"
time = { version = "0.3", features = ["formatting"] }
```

Implements OCI signing with the `rsa` crate (PKCS#1 v1.5, SHA-256), accepts PKCS#8 or PKCS#1 PEM keys, uses the OS trust store (`rustls-tls-native-roots`), and is HTTPS-only.

```rust
//! OCI Vault secrets CRUD in Rust over the REST APIs with OCI HTTP request signing
//! (draft-cavage-http-signatures, rsa-sha256). Oracle publishes no official Rust SDK.
//! Identity: an API signing key (OCI_CLI_USER, OCI_CLI_TENANCY, OCI_CLI_FINGERPRINT,
//! OCI_CLI_KEY_FILE, OCI_CLI_REGION). Inside OCI, prefer an SDK language with instance,
//! resource, or workload-identity principals.
use base64::{engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD}, Engine};
use reqwest::{Client, Method, Url};
use rsa::{
    pkcs1::DecodeRsaPrivateKey, pkcs1v15::SigningKey, pkcs8::DecodePrivateKey,
    signature::{SignatureEncoding, Signer}, RsaPrivateKey,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{env, error::Error, time::{Duration, SystemTime}};
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

struct OciClient {
    http: Client,
    key_id: String,
    signer: SigningKey<Sha256>,
    vault_endpoint: String,
    secrets_endpoint: String,
}

impl OciClient {
    fn from_env() -> Res<Self> {
        let var = |k: &str| env::var(k).map_err(|_| format!("set {k}"));
        let region = var("OCI_CLI_REGION")?;
        let pem = Zeroizing::new(std::fs::read_to_string(var("OCI_CLI_KEY_FILE")?)?);
        let key = RsaPrivateKey::from_pkcs8_pem(&pem).or_else(|_| RsaPrivateKey::from_pkcs1_pem(&pem))?;
        Ok(Self {
            http: Client::builder().timeout(Duration::from_secs(30)).https_only(true).build()?,
            key_id: format!("{}/{}/{}", var("OCI_CLI_TENANCY")?, var("OCI_CLI_USER")?, var("OCI_CLI_FINGERPRINT")?),
            signer: SigningKey::<Sha256>::new(key),
            vault_endpoint: env::var("OCI_VAULT_ENDPOINT")
                .unwrap_or_else(|_| format!("https://vaults.{region}.oci.oraclecloud.com")),
            secrets_endpoint: env::var("OCI_SECRETS_ENDPOINT")
                .unwrap_or_else(|_| format!("https://secrets.vaults.{region}.oci.oraclecloud.com")),
        })
    }

    /// Sign and send. GET/DELETE sign date, (request-target), host; POST/PUT also sign
    /// content-length, content-type and x-content-sha256.
    async fn call(&self, method: Method, url: &str, body: Option<&Value>, retry_token: Option<&str>) -> Res<(u16, Value)> {
        let url = Url::parse(url)?;
        let host = match url.port() {
            Some(p) => format!("{}:{p}", url.host_str().unwrap_or_default()),
            None => url.host_str().unwrap_or_default().to_string(),
        };
        let target = match url.query() {
            Some(q) => format!("{} {}?{q}", method.as_str().to_lowercase(), url.path()),
            None => format!("{} {}", method.as_str().to_lowercase(), url.path()),
        };
        let date = httpdate::fmt_http_date(SystemTime::now());
        let mut signing = format!("date: {date}\n(request-target): {target}\nhost: {host}");
        let mut headers = String::from("date (request-target) host");
        let mut req = self.http.request(method.clone(), url.clone()).header("date", &date);

        if let Some(t) = retry_token {
            req = req.header("opc-retry-token", t); // idempotent retries; not part of the signature
        }
        let payload = Zeroizing::new(match body {
            Some(b) => serde_json::to_vec(b)?,
            None => Vec::new(),
        });
        if method == Method::POST || method == Method::PUT {
            let sha = STANDARD.encode(Sha256::digest(&payload[..]));
            signing.push_str(&format!(
                "\ncontent-length: {}\ncontent-type: application/json\nx-content-sha256: {sha}",
                payload.len()
            ));
            headers.push_str(" content-length content-type x-content-sha256");
            req = req
                .header("content-type", "application/json")
                .header("x-content-sha256", sha)
                .header("content-length", payload.len())
                .body(payload.to_vec());
        }
        let signature = STANDARD.encode(self.signer.sign(signing.as_bytes()).to_bytes());
        let auth = format!(
            r#"Signature version="1",keyId="{}",algorithm="rsa-sha256",headers="{headers}",signature="{signature}""#,
            self.key_id
        );
        let resp = req.header("authorization", auth).send().await?;
        let status = resp.status().as_u16();
        let text = Zeroizing::new(resp.text().await?);
        Ok((status, if text.is_empty() { Value::Null } else { serde_json::from_str(&text)? }))
    }
}

struct OciSecretStore { oci: OciClient, compartment_id: String, vault_id: String, key_id: String }

impl OciSecretStore {
    async fn wait_active(&self, secret_id: &str) -> Res<()> {
        for _ in 0..60 {
            let (status, s) = self.oci.call(Method::GET,
                &format!("{}/20180608/secrets/{secret_id}", self.oci.vault_endpoint), None, None).await?;
            match (status, s["lifecycleState"].as_str()) {
                (200, Some("ACTIVE")) => return Ok(()),
                (200, Some("FAILED")) => return Err("secret entered FAILED".into()),
                (200, _) => tokio::time::sleep(Duration::from_secs(2)).await,
                (code, _) => return Err(format!("get secret: HTTP {code}").into()),
            }
        }
        Err("timed out waiting for ACTIVE".into())
    }

    /// Create is asynchronous; names are unique per vault (409 on duplicates).
    async fn create(&self, name: &str, value: &[u8]) -> Res<String> {
        let body = json!({
            "compartmentId": self.compartment_id, "vaultId": self.vault_id, "keyId": self.key_id,
            "secretName": name, "description": "managed by secrets-crud example",
            "freeformTags": { "app": "secrets-crud" },
            "secretContent": { "contentType": "BASE64", "content": STANDARD.encode(value) },
        });
        let token = uuid::Uuid::new_v4().to_string();
        let (status, s) = self.oci.call(Method::POST, &format!("{}/20180608/secrets", self.oci.vault_endpoint),
            Some(&body), Some(&token)).await?;
        if status == 409 { return Err(format!("secret {name} already exists in this vault").into()); }
        if status != 200 { return Err(format!("create secret: HTTP {status} {}", s["code"]).into()); }
        let id = s["id"].as_str().ok_or("no id")?.to_string();
        self.wait_active(&id).await?;
        Ok(id)
    }

    async fn read(&self, secret_id: &str) -> Res<Zeroizing<Vec<u8>>> {
        let (status, b) = self.oci.call(Method::GET,
            &format!("{}/20190301/secretbundles/{secret_id}?stage=CURRENT", self.oci.secrets_endpoint), None, None).await?;
        if status != 200 { return Err(format!("get secret bundle: HTTP {status}").into()); }
        let content = b["secretBundleContent"]["content"].as_str().ok_or("no content")?;
        Ok(Zeroizing::new(STANDARD.decode(content)?))
    }

    /// New content creates a new version that becomes CURRENT.
    async fn update(&self, secret_id: &str, value: &[u8]) -> Res<i64> {
        let body = json!({ "secretContent": { "contentType": "BASE64", "content": STANDARD.encode(value) } });
        let (status, s) = self.oci.call(Method::PUT,
            &format!("{}/20180608/secrets/{secret_id}", self.oci.vault_endpoint), Some(&body), None).await?;
        if status != 200 { return Err(format!("update secret: HTTP {status}").into()); }
        self.wait_active(secret_id).await?;
        Ok(s["currentVersionNumber"].as_i64().unwrap_or_default())
    }

    /// Deletion is scheduled 1-30 days ahead; POST .../actions/cancelDeletion restores it.
    async fn schedule_deletion(&self, secret_id: &str) -> Res<String> {
        let when = time::OffsetDateTime::now_utc() + time::Duration::days(1) + time::Duration::minutes(1);
        let when = when.format(&time::format_description::well_known::Rfc3339)?;
        let (status, _) = self.oci.call(Method::POST,
            &format!("{}/20180608/secrets/{secret_id}/actions/scheduleDeletion", self.oci.vault_endpoint),
            Some(&json!({ "timeOfDeletion": when })), None).await?;
        if status != 200 { return Err(format!("schedule deletion: HTTP {status}").into()); }
        Ok(when)
    }
}

fn random_value() -> Zeroizing<Vec<u8>> {
    let mut b = Zeroizing::new([0u8; 32]);
    getrandom::fill(&mut b[..]).expect("csprng");
    Zeroizing::new(URL_SAFE_NO_PAD.encode(&b[..]).into_bytes())
}

fn ct_eq(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

#[tokio::main]
async fn main() -> Res<()> {
    let var = |k: &str| env::var(k).map_err(|_| format!("set {k}"));
    let store = OciSecretStore {
        oci: OciClient::from_env()?,
        compartment_id: var("OCI_COMPARTMENT_ID")?,
        vault_id: var("OCI_VAULT_ID")?,
        key_id: var("OCI_KEY_ID")?,
    };
    let name = var("SECRET_NAME")?;

    let v1 = random_value();
    let id = store.create(&name, &v1).await?;
    println!("created: {id}");
    if !ct_eq(&store.read(&id).await?, &v1) { return Err("read-back after create did not match".into()); }

    let v2 = random_value();
    let version = store.update(&id, &v2).await?;
    if !ct_eq(&store.read(&id).await?, &v2) { return Err("read-back after update did not match".into()); }
    println!("updated: current version {version}");

    println!("deletion scheduled for {}", store.schedule_deletion(&id).await?);
    Ok(())
}
```

### 9.3 PHP

Signs with `openssl_sign(..., OPENSSL_ALGO_SHA256)`; restricts curl to HTTPS.

```php
<?php
// OCI Vault secrets CRUD in PHP over the REST APIs with OCI request signing (rsa-sha256).
// Oracle's preview PHP SDK covers Object Storage only, so this signs requests directly.
// Requires ext-curl, ext-openssl, ext-json. Identity: API signing key from the
// OCI_CLI_USER / OCI_CLI_TENANCY / OCI_CLI_FINGERPRINT / OCI_CLI_KEY_FILE / OCI_CLI_REGION variables.
declare(strict_types=1);

final class OciClient
{
    private OpenSSLAsymmetricKey $key;
    private string $keyId;
    public string $vaultEndpoint;
    public string $secretsEndpoint;

    public function __construct()
    {
        $env = static fn (string $k): string => getenv($k) ?: throw new RuntimeException("set {$k}");
        $region = $env('OCI_CLI_REGION');
        $pem = file_get_contents($env('OCI_CLI_KEY_FILE'));
        $this->key = openssl_pkey_get_private((string) $pem) ?: throw new RuntimeException('cannot load OCI key');
        $this->keyId = $env('OCI_CLI_TENANCY') . '/' . $env('OCI_CLI_USER') . '/' . $env('OCI_CLI_FINGERPRINT');
        $this->vaultEndpoint = getenv('OCI_VAULT_ENDPOINT') ?: "https://vaults.{$region}.oci.oraclecloud.com";
        $this->secretsEndpoint = getenv('OCI_SECRETS_ENDPOINT') ?: "https://secrets.vaults.{$region}.oci.oraclecloud.com";
        unset($pem);
    }

    /**
     * Sign and send. GET/DELETE sign date, (request-target), host; POST/PUT also sign
     * content-length, content-type and x-content-sha256.
     * @return array{status:int, json:?array}
     */
    public function call(string $method, string $url, ?array $body = null, ?string $retryToken = null): array
    {
        $u = parse_url($url);
        $host = $u['host'] . (isset($u['port']) ? ':' . $u['port'] : '');
        $target = strtolower($method) . ' ' . $u['path'] . (isset($u['query']) ? '?' . $u['query'] : '');
        $date = gmdate('D, d M Y H:i:s') . ' GMT';
        $headers = ["date: {$date}", "host: {$host}"];
        $signing = "date: {$date}\n(request-target): {$target}\nhost: {$host}";
        $signed = 'date (request-target) host';
        $payload = null;
        if ($method === 'POST' || $method === 'PUT') {
            $payload = $body === null ? '' : json_encode($body, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
            $sha = base64_encode(hash('sha256', $payload, true));
            $len = strlen($payload);
            $signing .= "\ncontent-length: {$len}\ncontent-type: application/json\nx-content-sha256: {$sha}";
            $signed .= ' content-length content-type x-content-sha256';
            array_push($headers, "content-length: {$len}", 'content-type: application/json', "x-content-sha256: {$sha}");
        }
        if (!openssl_sign($signing, $signature, $this->key, OPENSSL_ALGO_SHA256)) {
            throw new RuntimeException('signing failed');
        }
        $headers[] = sprintf('authorization: Signature version="1",keyId="%s",algorithm="rsa-sha256",headers="%s",signature="%s"',
            $this->keyId, $signed, base64_encode($signature));
        if ($retryToken !== null) {
            $headers[] = "opc-retry-token: {$retryToken}";   // idempotent retries; not signed
        }
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_CUSTOMREQUEST  => $method,
            CURLOPT_HTTPHEADER     => $headers,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 30,
            CURLOPT_PROTOCOLS      => CURLPROTO_HTTPS,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
        ]);
        if ($payload !== null) {
            curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
        }
        $out = curl_exec($ch);
        if ($out === false) {
            throw new RuntimeException('transport error: ' . curl_error($ch));
        }
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        return ['status' => $status, 'json' => $out === '' ? null : json_decode((string) $out, true)];
    }
}

final class OciSecretStore
{
    public function __construct(
        private OciClient $oci,
        private string $compartmentId,
        private string $vaultId,
        private string $keyId,
    ) {}

    /** Create and update are asynchronous: wait for ACTIVE before reading. */
    private function waitActive(string $secretId): void
    {
        for ($i = 0; $i < 60; $i++) {
            $r = $this->oci->call('GET', "{$this->oci->vaultEndpoint}/20180608/secrets/{$secretId}");
            $state = $r['json']['lifecycleState'] ?? null;
            if ($r['status'] === 200 && $state === 'ACTIVE') {
                return;
            }
            if ($r['status'] !== 200 || $state === 'FAILED') {
                throw new RuntimeException("get secret: HTTP {$r['status']} state {$state}");
            }
            sleep(2);
        }
        throw new RuntimeException('timed out waiting for ACTIVE');
    }

    public function create(string $name, string $value): string
    {
        $r = $this->oci->call('POST', "{$this->oci->vaultEndpoint}/20180608/secrets", [
            'compartmentId' => $this->compartmentId,
            'vaultId'       => $this->vaultId,
            'keyId'         => $this->keyId,
            'secretName'    => $name,
            'description'   => 'managed by secrets-crud example',
            'freeformTags'  => ['app' => 'secrets-crud'],
            'secretContent' => ['contentType' => 'BASE64', 'content' => base64_encode($value)],
        ], bin2hex(random_bytes(16)));
        if ($r['status'] === 409) {
            throw new RuntimeException("secret {$name} already exists in this vault");
        }
        if ($r['status'] !== 200) {
            throw new RuntimeException("create secret: HTTP {$r['status']} " . ($r['json']['code'] ?? ''));
        }
        $this->waitActive($r['json']['id']);
        return $r['json']['id'];
    }

    public function read(string $secretId): string
    {
        $r = $this->oci->call('GET', "{$this->oci->secretsEndpoint}/20190301/secretbundles/{$secretId}?stage=CURRENT");
        $content = $r['json']['secretBundleContent']['content'] ?? null;
        if ($r['status'] !== 200 || !is_string($content)) {
            throw new RuntimeException("get secret bundle: HTTP {$r['status']}");
        }
        return base64_decode($content, true) ?: throw new RuntimeException('invalid base64 content');
    }

    /** New content creates a new version that becomes CURRENT. */
    public function update(string $secretId, string $value): int
    {
        $r = $this->oci->call('PUT', "{$this->oci->vaultEndpoint}/20180608/secrets/{$secretId}", [
            'secretContent' => ['contentType' => 'BASE64', 'content' => base64_encode($value)],
        ]);
        if ($r['status'] !== 200) {
            throw new RuntimeException("update secret: HTTP {$r['status']}");
        }
        $this->waitActive($secretId);
        return (int) $r['json']['currentVersionNumber'];
    }

    /** Deletion is scheduled 1-30 days ahead; POST .../actions/cancelDeletion restores it. */
    public function scheduleDeletion(string $secretId, int $days = 1): string
    {
        $when = gmdate('Y-m-d\TH:i:s\Z', time() + $days * 86400 + 60);
        $r = $this->oci->call('POST', "{$this->oci->vaultEndpoint}/20180608/secrets/{$secretId}/actions/scheduleDeletion",
            ['timeOfDeletion' => $when]);
        if ($r['status'] !== 200) {
            throw new RuntimeException("schedule deletion: HTTP {$r['status']}");
        }
        return $when;
    }
}

$need = static fn (string $k): string => getenv($k) ?: exit("set {$k}\n");
$store = new OciSecretStore(new OciClient(), $need('OCI_COMPARTMENT_ID'), $need('OCI_VAULT_ID'), $need('OCI_KEY_ID'));
$name = $need('SECRET_NAME');
$random = fn (): string => rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');

$v1 = $random();
$id = $store->create($name, $v1);
echo "created: {$id}\n";
hash_equals($v1, $store->read($id)) || exit("read-back after create did not match\n");

$v2 = $random();
echo 'updated: current version ' . $store->update($id, $v2) . "\n";
hash_equals($v2, $store->read($id)) || exit("read-back after update did not match\n");
unset($v1, $v2);

echo 'deletion scheduled for ' . $store->scheduleDeletion($id) . "\n";
```

### 9.4 C#

`dotnet add package OCI.DotNetSDK.Vault` and `OCI.DotNetSDK.Secrets`. Service errors are `Oci.Common.Model.OciException` with `StatusCode` and `ServiceCode`.

```csharp
// OCI Vault secrets CRUD with the OCI .NET SDK.
// dotnet add package OCI.DotNetSDK.Vault
// dotnet add package OCI.DotNetSDK.Secrets
// Writes use the Vault management API (VaultsClient); reads use the Secrets retrieval API.
using System.Net;
using System.Security.Cryptography;
using System.Text;
using Oci.Common.Auth;
using Oci.Common.Model;
using Oci.SecretsService;
using Oci.VaultService;
using SecretsModels = Oci.SecretsService.Models;
using SecretsRequests = Oci.SecretsService.Requests;
using VaultModels = Oci.VaultService.Models;
using VaultRequests = Oci.VaultService.Requests;

public sealed class OciSecretStore(VaultsClient vaults, SecretsClient bundles, string compartmentId, string vaultId, string keyId)
{
    private static VaultModels.Base64SecretContentDetails Content(byte[] v) => new() { Content = Convert.ToBase64String(v) };

    /// <summary>Create and update are asynchronous; wait for ACTIVE before reading.</summary>
    private async Task WaitActiveAsync(string secretId, CancellationToken ct)
    {
        for (var i = 0; i < 60; i++)
        {
            var r = await vaults.GetSecret(new VaultRequests.GetSecretRequest { SecretId = secretId }, cancellationToken: ct);
            if (r.Secret.LifecycleState == VaultModels.Secret.LifecycleStateEnum.Active) return;
            if (r.Secret.LifecycleState == VaultModels.Secret.LifecycleStateEnum.Failed) throw new InvalidOperationException("secret FAILED");
            await Task.Delay(TimeSpan.FromSeconds(2), ct);
        }
        throw new TimeoutException("timed out waiting for ACTIVE");
    }

    public async Task<string> CreateAsync(string name, byte[] value, CancellationToken ct)
    {
        try
        {
            var r = await vaults.CreateSecret(new VaultRequests.CreateSecretRequest
            {
                CreateSecretDetails = new VaultModels.CreateSecretDetails
                {
                    CompartmentId = compartmentId,
                    VaultId = vaultId,
                    KeyId = keyId, // symmetric master encryption key in the same vault
                    SecretName = name,
                    Description = "managed by secrets-crud example",
                    FreeformTags = new Dictionary<string, string> { ["app"] = "secrets-crud" },
                    SecretContent = Content(value),
                },
                OpcRetryToken = Guid.NewGuid().ToString("N"), // idempotent retries
            }, cancellationToken: ct);
            await WaitActiveAsync(r.Secret.Id, ct);
            return r.Secret.Id;
        }
        catch (OciException ex) when (ex.StatusCode == HttpStatusCode.Conflict)
        {
            throw new InvalidOperationException($"secret {name} already exists in this vault", ex);
        }
    }

    public async Task<byte[]> ReadAsync(string secretId, CancellationToken ct)
    {
        var r = await bundles.GetSecretBundle(new SecretsRequests.GetSecretBundleRequest
        {
            SecretId = secretId,
            Stage = SecretsRequests.GetSecretBundleRequest.StageEnum.Current,
        }, cancellationToken: ct);
        if (r.SecretBundle.SecretBundleContent is not SecretsModels.Base64SecretBundleContentDetails { Content: { } b64 })
            throw new InvalidOperationException("secret bundle has no base64 content");
        return Convert.FromBase64String(b64);
    }

    /// <summary>New content creates a new version that becomes CURRENT.</summary>
    public async Task<long?> UpdateAsync(string secretId, byte[] value, CancellationToken ct)
    {
        var r = await vaults.UpdateSecret(new VaultRequests.UpdateSecretRequest
        {
            SecretId = secretId,
            UpdateSecretDetails = new VaultModels.UpdateSecretDetails { SecretContent = Content(value) },
        }, cancellationToken: ct);
        await WaitActiveAsync(secretId, ct);
        return r.Secret.CurrentVersionNumber;
    }

    /// <summary>Deletion is scheduled 1-30 days ahead; CancelSecretDeletion restores it until then.</summary>
    public async Task<DateTime> ScheduleDeletionAsync(string secretId, int days, CancellationToken ct)
    {
        var when = DateTime.UtcNow.AddDays(days).AddMinutes(1);
        await vaults.ScheduleSecretDeletion(new VaultRequests.ScheduleSecretDeletionRequest
        {
            SecretId = secretId,
            ScheduleSecretDeletionDetails = new VaultModels.ScheduleSecretDeletionDetails { TimeOfDeletion = when },
        }, cancellationToken: ct);
        return when;
    }
}

public static class Program
{
    static IBasicAuthenticationDetailsProvider Provider() => Environment.GetEnvironmentVariable("OCI_AUTH") switch
    {
        "instance_principal" => new InstancePrincipalsAuthenticationDetailsProvider(),
        "oke_workload_identity" => OkeWorkloadIdentityAuthenticationDetailsProvider.GetProvider(),
        _ => new ConfigFileAuthenticationDetailsProvider(Environment.GetEnvironmentVariable("OCI_CLI_PROFILE") ?? "DEFAULT"),
    };

    static byte[] RandomValue() => Encoding.ASCII.GetBytes(Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)));

    static string Need(string k) => Environment.GetEnvironmentVariable(k) ?? throw new InvalidOperationException($"set {k}");

    public static async Task<int> Main()
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(5));
        var auth = Provider();
        using var vaults = new VaultsClient(auth);
        using var bundles = new SecretsClient(auth);
        var store = new OciSecretStore(vaults, bundles, Need("OCI_COMPARTMENT_ID"), Need("OCI_VAULT_ID"), Need("OCI_KEY_ID"));
        var name = Need("SECRET_NAME");

        var v1 = RandomValue();
        var id = await store.CreateAsync(name, v1, cts.Token);
        Console.WriteLine($"created: {id}");
        if (!CryptographicOperations.FixedTimeEquals(v1, await store.ReadAsync(id, cts.Token)))
            throw new InvalidOperationException("read-back after create did not match");

        var v2 = RandomValue();
        var version = await store.UpdateAsync(id, v2, cts.Token);
        if (!CryptographicOperations.FixedTimeEquals(v2, await store.ReadAsync(id, cts.Token)))
            throw new InvalidOperationException("read-back after update did not match");
        Console.WriteLine($"updated: current version {version}");
        CryptographicOperations.ZeroMemory(v1);
        CryptographicOperations.ZeroMemory(v2);

        Console.WriteLine($"deletion scheduled for {await store.ScheduleDeletionAsync(id, 1, cts.Token):O}");
        return 0;
    }
}
```

### 9.5 Java

Import the OCI BOM and add `oci-java-sdk-vault`, `oci-java-sdk-secrets`, an HTTP client provider (`oci-java-sdk-common-httpclient-jersey3`), and, for OKE workload identity, `oci-java-sdk-addons-oke-workload-identity`. The client's built-in waiter polls until `ACTIVE`.

```java
// OCI Vault secrets CRUD with the OCI Java SDK (3.x).
// Maven: com.oracle.oci.sdk:oci-java-sdk-vault, oci-java-sdk-secrets, and an HTTP client provider
// such as oci-java-sdk-common-httpclient-jersey3 (import com.oracle.oci.sdk:oci-java-sdk-bom).
package example;

import com.oracle.bmc.ConfigFileReader;
import com.oracle.bmc.auth.AbstractAuthenticationDetailsProvider;
import com.oracle.bmc.auth.ConfigFileAuthenticationDetailsProvider;
import com.oracle.bmc.auth.InstancePrincipalsAuthenticationDetailsProvider;
import com.oracle.bmc.auth.okeworkloadidentity.OkeWorkloadIdentityAuthenticationDetailsProvider;
import com.oracle.bmc.model.BmcException;
import com.oracle.bmc.secrets.SecretsClient;
import com.oracle.bmc.secrets.model.Base64SecretBundleContentDetails;
import com.oracle.bmc.secrets.requests.GetSecretBundleRequest;
import com.oracle.bmc.vault.VaultsClient;
import com.oracle.bmc.vault.model.Base64SecretContentDetails;
import com.oracle.bmc.vault.model.CreateSecretDetails;
import com.oracle.bmc.vault.model.ScheduleSecretDeletionDetails;
import com.oracle.bmc.vault.model.Secret;
import com.oracle.bmc.vault.model.UpdateSecretDetails;
import com.oracle.bmc.vault.requests.CreateSecretRequest;
import com.oracle.bmc.vault.requests.GetSecretRequest;
import com.oracle.bmc.vault.requests.ScheduleSecretDeletionRequest;
import com.oracle.bmc.vault.requests.UpdateSecretRequest;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Arrays;
import java.util.Base64;
import java.util.Date;
import java.util.Map;
import java.util.UUID;

public final class OciSecretsCrud {
    private final VaultsClient vaults;
    private final SecretsClient bundles;
    private final String compartmentId, vaultId, keyId;

    OciSecretsCrud(VaultsClient vaults, SecretsClient bundles, String compartmentId, String vaultId, String keyId) {
        this.vaults = vaults;
        this.bundles = bundles;
        this.compartmentId = compartmentId;
        this.vaultId = vaultId;
        this.keyId = keyId;
    }

    static AbstractAuthenticationDetailsProvider provider() throws Exception {
        String mode = System.getenv().getOrDefault("OCI_AUTH", "config");
        return switch (mode) {
            case "instance_principal" -> InstancePrincipalsAuthenticationDetailsProvider.builder().build();
            case "oke_workload_identity" -> OkeWorkloadIdentityAuthenticationDetailsProvider.builder().build();
            default -> new ConfigFileAuthenticationDetailsProvider(ConfigFileReader.parseDefault());
        };
    }

    private static Base64SecretContentDetails content(byte[] v) {
        return Base64SecretContentDetails.builder().content(Base64.getEncoder().encodeToString(v)).build();
    }

    /** Create and update are asynchronous; wait for ACTIVE before reading. */
    private void waitActive(String secretId) throws Exception {
        vaults.getWaiters()
                .forSecret(GetSecretRequest.builder().secretId(secretId).build(), Secret.LifecycleState.Active)
                .execute();
    }

    public String create(String name, byte[] value) throws Exception {
        try {
            String id = vaults.createSecret(CreateSecretRequest.builder()
                    .createSecretDetails(CreateSecretDetails.builder()
                            .compartmentId(compartmentId)
                            .vaultId(vaultId)
                            .keyId(keyId) // symmetric master encryption key in the same vault
                            .secretName(name)
                            .description("managed by secrets-crud example")
                            .freeformTags(Map.of("app", "secrets-crud"))
                            .secretContent(content(value))
                            .build())
                    .opcRetryToken(UUID.randomUUID().toString()) // idempotent retries
                    .build()).getSecret().getId();
            waitActive(id);
            return id;
        } catch (BmcException e) {
            if (e.getStatusCode() == 409) throw new IllegalStateException("secret " + name + " already exists in this vault", e);
            throw e;
        }
    }

    public byte[] read(String secretId) {
        var bundle = bundles.getSecretBundle(GetSecretBundleRequest.builder()
                .secretId(secretId)
                .stage(GetSecretBundleRequest.Stage.Current)
                .build()).getSecretBundle();
        if (!(bundle.getSecretBundleContent() instanceof Base64SecretBundleContentDetails c) || c.getContent() == null) {
            throw new IllegalStateException("secret bundle has no base64 content");
        }
        return Base64.getDecoder().decode(c.getContent());
    }

    /** New content creates a new version that becomes CURRENT. */
    public Long update(String secretId, byte[] value) throws Exception {
        Long version = vaults.updateSecret(UpdateSecretRequest.builder()
                .secretId(secretId)
                .updateSecretDetails(UpdateSecretDetails.builder().secretContent(content(value)).build())
                .build()).getSecret().getCurrentVersionNumber();
        waitActive(secretId);
        return version;
    }

    /** Deletion is scheduled 1-30 days ahead; cancelSecretDeletion restores it until then. */
    public Instant scheduleDeletion(String secretId, int days) {
        Instant when = Instant.now().plus(days, ChronoUnit.DAYS).plus(1, ChronoUnit.MINUTES);
        vaults.scheduleSecretDeletion(ScheduleSecretDeletionRequest.builder()
                .secretId(secretId)
                .scheduleSecretDeletionDetails(ScheduleSecretDeletionDetails.builder().timeOfDeletion(Date.from(when)).build())
                .build());
        return when;
    }

    private static final SecureRandom RNG = new SecureRandom();

    static byte[] randomValue() {
        byte[] raw = new byte[32];
        RNG.nextBytes(raw);
        byte[] out = Base64.getUrlEncoder().withoutPadding().encode(raw);
        Arrays.fill(raw, (byte) 0);
        return out;
    }

    static String need(String k) {
        String v = System.getenv(k);
        if (v == null || v.isEmpty()) throw new IllegalArgumentException("set " + k);
        return v;
    }

    public static void main(String[] args) throws Exception {
        AbstractAuthenticationDetailsProvider auth = provider();
        try (VaultsClient vaults = VaultsClient.builder().build(auth);
             SecretsClient bundles = SecretsClient.builder().build(auth)) {
            OciSecretsCrud store = new OciSecretsCrud(vaults, bundles,
                    need("OCI_COMPARTMENT_ID"), need("OCI_VAULT_ID"), need("OCI_KEY_ID"));
            String name = need("SECRET_NAME");

            byte[] v1 = randomValue();
            String id = store.create(name, v1);
            System.out.println("created: " + id);
            if (!MessageDigest.isEqual(v1, store.read(id))) throw new IllegalStateException("read-back after create failed");

            byte[] v2 = randomValue();
            Long version = store.update(id, v2);
            if (!MessageDigest.isEqual(v2, store.read(id))) throw new IllegalStateException("read-back after update failed");
            System.out.println("updated: current version " + version);
            Arrays.fill(v1, (byte) 0);
            Arrays.fill(v2, (byte) 0);

            System.out.println("deletion scheduled for " + store.scheduleDeletion(id, 1));
        }
    }
}
```

### 9.6 Swift

Uses swift-crypto's `_RSA.Signing.PrivateKey` with `.insecurePKCS1v1_5` padding (the name reflects that PKCS#1 v1.5 is legacy; OCI's signature scheme requires it). Server-side only.

`Package.swift`:

```swift
// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SecretsCrud",
    platforms: [.macOS(.v13)],
    dependencies: [
        // RSA PKCS#1 v1.5 signing on Apple platforms and Linux (BoringSSL-backed).
        .package(url: "https://github.com/apple/swift-crypto.git", "3.0.0" ..< "6.0.0"),
    ],
    targets: [
        .executableTarget(
            name: "SecretsCrud",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto"),
                .product(name: "_CryptoExtras", package: "swift-crypto"),
            ]
        ),
    ]
)
```

```swift
// OCI Vault secrets CRUD in Swift over the REST APIs with OCI request signing (rsa-sha256).
// Oracle publishes no Swift SDK. Identity: API signing key from OCI_CLI_USER, OCI_CLI_TENANCY,
// OCI_CLI_FINGERPRINT, OCI_CLI_KEY_FILE, OCI_CLI_REGION. Server-side use only: never ship an
// OCI API key inside an iOS/macOS app.
import Crypto
import _CryptoExtras
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

enum OciError: Error { case config(String), http(Int, String) }

final class OciClient {
    let vaultEndpoint: String
    let secretsEndpoint: String
    private let keyID: String
    private let key: _RSA.Signing.PrivateKey
    private let session = URLSession(configuration: .ephemeral)

    init() throws {
        let env = ProcessInfo.processInfo.environment
        func need(_ k: String) throws -> String {
            guard let v = env[k], !v.isEmpty else { throw OciError.config("set \(k)") }
            return v
        }
        let region = try need("OCI_CLI_REGION")
        key = try _RSA.Signing.PrivateKey(pemRepresentation: String(contentsOfFile: try need("OCI_CLI_KEY_FILE"), encoding: .utf8))
        keyID = "\(try need("OCI_CLI_TENANCY"))/\(try need("OCI_CLI_USER"))/\(try need("OCI_CLI_FINGERPRINT"))"
        vaultEndpoint = env["OCI_VAULT_ENDPOINT"] ?? "https://vaults.\(region).oci.oraclecloud.com"
        secretsEndpoint = env["OCI_SECRETS_ENDPOINT"] ?? "https://secrets.vaults.\(region).oci.oraclecloud.com"
    }

    private static let httpDate: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "GMT")
        f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss 'GMT'"
        return f
    }()

    /// Signed request. GET/DELETE sign date, (request-target), host; POST/PUT also sign
    /// content-length, content-type and x-content-sha256.
    func call(_ method: String, _ urlString: String, body: [String: Any]? = nil,
              retryToken: String? = nil) async throws -> (Int, [String: Any]) {
        guard let url = URL(string: urlString), url.scheme == "https", let host0 = url.host else {
            throw OciError.config("endpoint must be an https URL")
        }
        let host = url.port.map { "\(host0):\($0)" } ?? host0
        let target = "\(method.lowercased()) \(url.path)" + (url.query.map { "?\($0)" } ?? "")
        let date = Self.httpDate.string(from: Date())
        var signing = "date: \(date)\n(request-target): \(target)\nhost: \(host)"
        var signedHeaders = "date (request-target) host"
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = 30
        req.setValue(date, forHTTPHeaderField: "date")
        if let retryToken { req.setValue(retryToken, forHTTPHeaderField: "opc-retry-token") }
        if method == "POST" || method == "PUT" {
            let payload = try body.map { try JSONSerialization.data(withJSONObject: $0) } ?? Data()
            let sha = Data(SHA256.hash(data: payload)).base64EncodedString()
            signing += "\ncontent-length: \(payload.count)\ncontent-type: application/json\nx-content-sha256: \(sha)"
            signedHeaders += " content-length content-type x-content-sha256"
            req.setValue(String(payload.count), forHTTPHeaderField: "content-length")
            req.setValue("application/json", forHTTPHeaderField: "content-type")
            req.setValue(sha, forHTTPHeaderField: "x-content-sha256")
            req.httpBody = payload
        }
        let sig = try key.signature(for: Data(signing.utf8), padding: .insecurePKCS1v1_5) // OCI requires PKCS#1 v1.5
        req.setValue("Signature version=\"1\",keyId=\"\(keyID)\",algorithm=\"rsa-sha256\",headers=\"\(signedHeaders)\",signature=\"\(sig.rawRepresentation.base64EncodedString())\"",
                     forHTTPHeaderField: "authorization")
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = data.isEmpty ? [:] : ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:])
        return (status, json)
    }
}

struct OciSecretStore {
    let oci: OciClient
    let compartmentID: String, vaultID: String, keyID: String

    private func waitActive(_ id: String) async throws {
        for _ in 0..<60 {
            let (status, s) = try await oci.call("GET", "\(oci.vaultEndpoint)/20180608/secrets/\(id)")
            let state = s["lifecycleState"] as? String
            if status == 200 && state == "ACTIVE" { return }
            if status != 200 || state == "FAILED" { throw OciError.http(status, "secret state \(state ?? "?")") }
            try await Task.sleep(nanoseconds: 2_000_000_000)
        }
        throw OciError.config("timed out waiting for ACTIVE")
    }

    func create(name: String, value: Data) async throws -> String {
        let (status, s) = try await oci.call("POST", "\(oci.vaultEndpoint)/20180608/secrets", body: [
            "compartmentId": compartmentID, "vaultId": vaultID, "keyId": keyID, "secretName": name,
            "description": "managed by secrets-crud example", "freeformTags": ["app": "secrets-crud"],
            "secretContent": ["contentType": "BASE64", "content": value.base64EncodedString()],
        ], retryToken: UUID().uuidString)
        if status == 409 { throw OciError.http(409, "secret \(name) already exists in this vault") }
        guard status == 200, let id = s["id"] as? String else { throw OciError.http(status, "create secret") }
        try await waitActive(id)
        return id
    }

    func read(id: String) async throws -> Data {
        let (status, b) = try await oci.call("GET", "\(oci.secretsEndpoint)/20190301/secretbundles/\(id)?stage=CURRENT")
        guard status == 200, let content = b["secretBundleContent"] as? [String: Any],
              let enc = content["content"] as? String, let data = Data(base64Encoded: enc) else {
            throw OciError.http(status, "get secret bundle")
        }
        return data
    }

    /// New content creates a new version that becomes CURRENT.
    func update(id: String, value: Data) async throws -> Int {
        let (status, s) = try await oci.call("PUT", "\(oci.vaultEndpoint)/20180608/secrets/\(id)", body: [
            "secretContent": ["contentType": "BASE64", "content": value.base64EncodedString()],
        ])
        guard status == 200 else { throw OciError.http(status, "update secret") }
        try await waitActive(id)
        return s["currentVersionNumber"] as? Int ?? 0
    }

    /// Deletion is scheduled 1-30 days ahead; POST .../actions/cancelDeletion restores it.
    func scheduleDeletion(id: String, days: Int = 1) async throws -> String {
        let when = ISO8601DateFormatter().string(from: Date().addingTimeInterval(Double(days) * 86_400 + 60))
        let (status, _) = try await oci.call("POST", "\(oci.vaultEndpoint)/20180608/secrets/\(id)/actions/scheduleDeletion",
                                             body: ["timeOfDeletion": when])
        guard status == 200 else { throw OciError.http(status, "schedule deletion") }
        return when
    }
}

func randomValue() -> Data {
    var rng = SystemRandomNumberGenerator()
    return Data(Data((0..<32).map { _ in UInt8.random(in: .min ... .max, using: &rng) }).base64EncodedString().utf8)
}

func fixedEquals(_ a: Data, _ b: Data) -> Bool {
    a.count == b.count && zip(a, b).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
}

let env = ProcessInfo.processInfo.environment
guard let comp = env["OCI_COMPARTMENT_ID"], let vaultID = env["OCI_VAULT_ID"], let keyID = env["OCI_KEY_ID"],
      let name = env["SECRET_NAME"] else { fatalError("set OCI_COMPARTMENT_ID, OCI_VAULT_ID, OCI_KEY_ID, SECRET_NAME") }
let store = OciSecretStore(oci: try OciClient(), compartmentID: comp, vaultID: vaultID, keyID: keyID)

let v1 = randomValue()
let id = try await store.create(name: name, value: v1)
print("created: \(id)")
guard fixedEquals(v1, try await store.read(id: id)) else { fatalError("read-back after create failed") }

let v2 = randomValue()
let version = try await store.update(id: id, value: v2)
guard fixedEquals(v2, try await store.read(id: id)) else { fatalError("read-back after update failed") }
print("updated: current version \(version)")

print("deletion scheduled for \(try await store.scheduleDeletion(id: id))")
```

### 9.7 Python

`pip install oci`. `oci.wait_until` polls for `ACTIVE`; `oci.exceptions.ServiceError.status` carries the HTTP status.

```python
"""OCI Vault secrets CRUD with the OCI Python SDK.

pip install oci
Writes go to the Vault management API (VaultsClient); reads go to the Secrets retrieval API.
"""
from __future__ import annotations

import base64
import datetime as dt
import hmac
import os
import secrets
import sys
import uuid

import oci
from oci.secrets.models import Base64SecretBundleContentDetails
from oci.vault.models import (
    Base64SecretContentDetails,
    CreateSecretDetails,
    ScheduleSecretDeletionDetails,
    UpdateSecretDetails,
)


def clients() -> tuple[oci.vault.VaultsClient, oci.secrets.SecretsClient]:
    mode = os.environ.get("OCI_AUTH")
    if mode == "instance_principal":
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    elif mode == "oke_workload_identity":
        signer = oci.auth.signers.get_oke_workload_identity_resource_principal_signer()
    else:  # ~/.oci/config profile (developer machines, external CI with API keys)
        config = oci.config.from_file(profile_name=os.environ.get("OCI_CLI_PROFILE", "DEFAULT"))
        return oci.vault.VaultsClient(config), oci.secrets.SecretsClient(config)
    config = {"region": signer.region}
    return oci.vault.VaultsClient(config, signer=signer), oci.secrets.SecretsClient(config, signer=signer)


def b64(value: bytes) -> Base64SecretContentDetails:
    return Base64SecretContentDetails(content_type="BASE64", content=base64.b64encode(value).decode())


class OciSecretStore:
    def __init__(self, vaults, bundles, compartment_id: str, vault_id: str, key_id: str) -> None:
        self.vaults, self.bundles = vaults, bundles
        self.compartment_id, self.vault_id, self.key_id = compartment_id, vault_id, key_id

    def _wait_active(self, secret_id: str) -> None:
        """Create and update are asynchronous; wait for ACTIVE before reading."""
        oci.wait_until(self.vaults, self.vaults.get_secret(secret_id), "lifecycle_state", "ACTIVE",
                       max_wait_seconds=120)

    def create(self, name: str, value: bytes) -> str:
        """Secret names are unique per vault; a duplicate fails with HTTP 409."""
        details = CreateSecretDetails(
            compartment_id=self.compartment_id,
            vault_id=self.vault_id,
            key_id=self.key_id,  # symmetric master encryption key in the same vault
            secret_name=name,
            description="managed by secrets-crud example",
            freeform_tags={"app": "secrets-crud"},
            secret_content=b64(value),
        )
        try:
            secret = self.vaults.create_secret(details, opc_retry_token=str(uuid.uuid4())).data
        except oci.exceptions.ServiceError as exc:
            if exc.status == 409:
                raise RuntimeError(f"secret {name} already exists in this vault") from exc
            raise
        self._wait_active(secret.id)
        return secret.id

    def read(self, secret_id: str) -> bytes:
        bundle = self.bundles.get_secret_bundle(secret_id, stage="CURRENT").data
        content = bundle.secret_bundle_content
        if not isinstance(content, Base64SecretBundleContentDetails) or not content.content:
            raise RuntimeError("secret bundle has no base64 content")
        return base64.b64decode(content.content)

    def update(self, secret_id: str, value: bytes) -> int:
        """New content creates a new version that becomes CURRENT."""
        secret = self.vaults.update_secret(secret_id, UpdateSecretDetails(secret_content=b64(value))).data
        self._wait_active(secret_id)
        return secret.current_version_number

    def schedule_deletion(self, secret_id: str, days: int = 1) -> dt.datetime:
        """Deletion is scheduled 1-30 days ahead; cancel_secret_deletion() restores it until then."""
        when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days, minutes=1)
        self.vaults.schedule_secret_deletion(secret_id, ScheduleSecretDeletionDetails(time_of_deletion=when))
        return when


def main() -> int:
    env = os.environ
    try:
        comp, vault_id, key_id, name = (env[k] for k in ("OCI_COMPARTMENT_ID", "OCI_VAULT_ID", "OCI_KEY_ID", "SECRET_NAME"))
    except KeyError as missing:
        print(f"set {missing}", file=sys.stderr)
        return 2
    store = OciSecretStore(*clients(), comp, vault_id, key_id)

    v1 = secrets.token_urlsafe(32).encode()
    secret_id = store.create(name, v1)
    print(f"created: {secret_id}")
    if not hmac.compare_digest(v1, store.read(secret_id)):
        raise RuntimeError("read-back after create did not match")

    v2 = secrets.token_urlsafe(32).encode()
    version = store.update(secret_id, v2)
    if not hmac.compare_digest(v2, store.read(secret_id)):
        raise RuntimeError("read-back after update did not match")
    print(f"updated: current version {version}")

    print(f"deletion scheduled for {store.schedule_deletion(secret_id).isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

`npm i oci-common oci-vault oci-secrets`. Errors carry `statusCode` and `serviceCode`.

```typescript
// OCI Vault secrets CRUD with the OCI TypeScript SDK.
// npm i oci-common oci-vault oci-secrets
// Writes go to the Vault management API (VaultsClient); reads go to the Secrets retrieval API.
import { randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import * as common from "oci-common";
import * as vault from "oci-vault";
import * as secrets from "oci-secrets";

async function provider(): Promise<common.AuthenticationDetailsProvider> {
  switch (process.env.OCI_AUTH) {
    case "instance_principal": // compute instances in a dynamic group
      return new common.InstancePrincipalsAuthenticationDetailsProviderBuilder().build();
    case "oke_workload_identity": // pods on OKE enhanced clusters
      return new common.OkeWorkloadIdentityAuthenticationDetailsProvider.OkeWorkloadIdentityAuthenticationDetailsProviderBuilder().build();
    default: // ~/.oci/config profile (developer machines, external CI with API keys)
      return new common.ConfigFileAuthenticationDetailsProvider(undefined, process.env.OCI_CLI_PROFILE);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class OciSecretStore {
  constructor(
    private readonly vaults: vault.VaultsClient,
    private readonly bundles: secrets.SecretsClient,
    private readonly compartmentId: string,
    private readonly vaultId: string,
    private readonly keyId: string,
  ) {}

  /** Create/update are asynchronous: wait until the secret is ACTIVE before reading. */
  private async waitActive(secretId: string): Promise<void> {
    for (let i = 0; i < 60; i++) {
      const { secret } = await this.vaults.getSecret({ secretId });
      if (secret.lifecycleState === vault.models.Secret.LifecycleState.Active) return;
      if (secret.lifecycleState === vault.models.Secret.LifecycleState.Failed) throw new Error("secret FAILED");
      await sleep(2000);
    }
    throw new Error("timed out waiting for ACTIVE");
  }

  /** Secret names are unique per vault; a duplicate name fails with 409. */
  async create(name: string, value: Buffer): Promise<string> {
    const { secret } = await this.vaults.createSecret({
      createSecretDetails: {
        compartmentId: this.compartmentId,
        vaultId: this.vaultId,
        keyId: this.keyId, // symmetric master encryption key in the same vault
        secretName: name,
        description: "managed by secrets-crud example",
        freeformTags: { app: "secrets-crud" },
        secretContent: { contentType: "BASE64", content: value.toString("base64") },
      },
      opcRetryToken: randomUUID(), // makes a retried create idempotent
    });
    await this.waitActive(secret.id);
    return secret.id;
  }

  async read(secretId: string): Promise<Buffer> {
    const { secretBundle } = await this.bundles.getSecretBundle({
      secretId,
      stage: secrets.requests.GetSecretBundleRequest.Stage.Current,
    });
    const content = secretBundle.secretBundleContent as secrets.models.Base64SecretBundleContentDetails | undefined;
    if (!content?.content) throw new Error("secret bundle has no content");
    return Buffer.from(content.content, "base64");
  }

  /** New content creates a new version that becomes CURRENT. Returns the new version number. */
  async update(secretId: string, value: Buffer): Promise<number | undefined> {
    const { secret } = await this.vaults.updateSecret({
      secretId,
      updateSecretDetails: { secretContent: { contentType: "BASE64", content: value.toString("base64") } },
    });
    await this.waitActive(secretId);
    return secret.currentVersionNumber;
  }

  /** Deletion is scheduled 1-30 days out; cancelSecretDeletion restores it until then. */
  async scheduleDeletion(secretId: string, days = 1): Promise<Date> {
    const when = new Date(Date.now() + days * 86_400_000 + 60_000);
    await this.vaults.scheduleSecretDeletion({ secretId, scheduleSecretDeletionDetails: { timeOfDeletion: when } });
    return when;
  }
}

const randomValue = (): Buffer => Buffer.from(randomBytes(32).toString("base64url"));
const same = (a: Buffer, b: Buffer): boolean => a.length === b.length && timingSafeEqual(a, b);

async function main(): Promise<void> {
  const { OCI_COMPARTMENT_ID: comp, OCI_VAULT_ID: vaultId, OCI_KEY_ID: keyId, SECRET_NAME: name } = process.env;
  if (!comp || !vaultId || !keyId || !name) throw new Error("set OCI_COMPARTMENT_ID, OCI_VAULT_ID, OCI_KEY_ID, SECRET_NAME");
  const auth = await provider();
  const store = new OciSecretStore(
    new vault.VaultsClient({ authenticationDetailsProvider: auth }),
    new secrets.SecretsClient({ authenticationDetailsProvider: auth }),
    comp, vaultId, keyId,
  );

  const v1 = randomValue();
  const id = await store.create(name, v1);
  console.log(`created: ${id}`);
  if (!same(v1, await store.read(id))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  const version = await store.update(id, v2);
  if (!same(v2, await store.read(id))) throw new Error("read-back after update did not match");
  console.log(`updated: current version ${version}`);
  v1.fill(0);
  v2.fill(0);

  console.log(`deletion scheduled for ${(await store.scheduleDeletion(id)).toISOString()}`);
}

main().catch((err: unknown) => {
  const e = err as { statusCode?: number; serviceCode?: string; message?: string };
  console.error(`error: ${e.statusCode ?? ""} ${e.serviceCode ?? ""} ${e.message ?? "unknown"}`);
  process.exitCode = 1;
});
```

### 9.9 C++

OpenSSL `EVP_DigestSign` + libcurl + nlohmann/json; `PEM_read_PrivateKey` accepts PKCS#8 and PKCS#1 keys.

```cpp
// OCI Vault secrets CRUD in C++17 over the REST APIs with OCI request signing (rsa-sha256).
// Oracle publishes no official C++ SDK. libcurl + nlohmann/json + OpenSSL 3.
//   g++ -std=c++17 -O2 main.cpp -o oci_crud $(pkg-config --cflags --libs libcurl openssl)
// Identity: API signing key (OCI_CLI_USER, OCI_CLI_TENANCY, OCI_CLI_FINGERPRINT, OCI_CLI_KEY_FILE,
// OCI_CLI_REGION); OCI_VAULT_ENDPOINT / OCI_SECRETS_ENDPOINT optionally override the hosts.
#include <curl/curl.h>
#include <nlohmann/json.hpp>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rand.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using json = nlohmann::json;

static std::string env(const char* k) {
  const char* v = std::getenv(k);
  if (!v || !*v) throw std::runtime_error(std::string("set ") + k);
  return v;
}

static std::string b64(const unsigned char* d, size_t n) {
  std::string out(4 * ((n + 2) / 3), '\0');
  int len = EVP_EncodeBlock(reinterpret_cast<unsigned char*>(out.data()), d, static_cast<int>(n));
  out.resize(static_cast<size_t>(len));
  return out;
}

static std::string unb64(const std::string& s) {
  std::string out(s.size(), '\0');
  int n = EVP_DecodeBlock(reinterpret_cast<unsigned char*>(out.data()),
                          reinterpret_cast<const unsigned char*>(s.data()), static_cast<int>(s.size()));
  if (n < 0) throw std::runtime_error("invalid base64");
  size_t pad = 0;
  for (size_t i = s.size(); i > 0 && s[i - 1] == '='; --i) ++pad;
  out.resize(static_cast<size_t>(n) - pad);
  return out;
}

static void wipe(std::string& s) { OPENSSL_cleanse(s.data(), s.size()); s.clear(); }

class OciClient {
 public:
  OciClient() {
    std::string region = env("OCI_CLI_REGION");
    struct FileCloser { void operator()(FILE* f) const { std::fclose(f); } };
    std::unique_ptr<FILE, FileCloser> f(std::fopen(env("OCI_CLI_KEY_FILE").c_str(), "r"));
    if (!f) throw std::runtime_error("cannot open OCI key file");
    key_.reset(PEM_read_PrivateKey(f.get(), nullptr, nullptr, nullptr));  // PKCS#8 or PKCS#1
    if (!key_) throw std::runtime_error("cannot load OCI private key");
    key_id_ = env("OCI_CLI_TENANCY") + "/" + env("OCI_CLI_USER") + "/" + env("OCI_CLI_FINGERPRINT");
    const char* ve = std::getenv("OCI_VAULT_ENDPOINT");
    const char* se = std::getenv("OCI_SECRETS_ENDPOINT");
    vault_ep = ve ? ve : "https://vaults." + region + ".oci.oraclecloud.com";
    secrets_ep = se ? se : "https://secrets.vaults." + region + ".oci.oraclecloud.com";
  }

  // Signed request. GET/DELETE sign date, (request-target), host; POST/PUT also sign
  // content-length, content-type and x-content-sha256.
  std::pair<long, json> call(const std::string& method, const std::string& url, const json* body = nullptr,
                             const std::string& retry_token = "") {
    auto start = url.find("://") + 3, slash = url.find('/', start);
    std::string host = url.substr(start, slash - start), path = url.substr(slash), lc = method;
    for (auto& c : lc) c = static_cast<char>(c | 0x20);
    char date[64];
    std::time_t now = std::time(nullptr);
    std::tm tm{};
    gmtime_r(&now, &tm);
    std::strftime(date, sizeof date, "%a, %d %b %Y %H:%M:%S GMT", &tm);

    bool has_body = method == "POST" || method == "PUT";
    std::string payload = has_body && body ? body->dump() : std::string();
    std::string signing = std::string("date: ") + date + "\n(request-target): " + lc + " " + path + "\nhost: " + host;
    std::string signed_headers = "date (request-target) host", sha;
    if (has_body) {
      unsigned char dig[32];
      EVP_Digest(payload.data(), payload.size(), dig, nullptr, EVP_sha256(), nullptr);
      sha = b64(dig, sizeof dig);
      signing += "\ncontent-length: " + std::to_string(payload.size()) + "\ncontent-type: application/json" +
                 "\nx-content-sha256: " + sha;
      signed_headers += " content-length content-type x-content-sha256";
    }
    std::vector<unsigned char> sig(EVP_PKEY_get_size(key_.get()));
    size_t siglen = sig.size();
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> md(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (EVP_DigestSignInit(md.get(), nullptr, EVP_sha256(), nullptr, key_.get()) != 1 ||
        EVP_DigestSign(md.get(), sig.data(), &siglen, reinterpret_cast<const unsigned char*>(signing.data()),
                       signing.size()) != 1)
      throw std::runtime_error("signing failed");

    std::vector<std::string> hdrs = {
        std::string("date: ") + date, "host: " + host,
        "authorization: Signature version=\"1\",keyId=\"" + key_id_ + "\",algorithm=\"rsa-sha256\",headers=\"" +
            signed_headers + "\",signature=\"" + b64(sig.data(), siglen) + "\""};
    if (!retry_token.empty()) hdrs.push_back("opc-retry-token: " + retry_token);  // not signed
    if (has_body) {
      hdrs.push_back("content-length: " + std::to_string(payload.size()));
      hdrs.push_back("content-type: application/json");
      hdrs.push_back("x-content-sha256: " + sha);
    }
    struct curl_slist* list = nullptr;
    for (auto& h : hdrs) list = curl_slist_append(list, h.c_str());

    std::string resp;
    std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> c(curl_easy_init(), curl_easy_cleanup);
    curl_easy_setopt(c.get(), CURLOPT_URL, url.c_str());
    curl_easy_setopt(c.get(), CURLOPT_CUSTOMREQUEST, method.c_str());
    curl_easy_setopt(c.get(), CURLOPT_HTTPHEADER, list);
    if (has_body) {
      curl_easy_setopt(c.get(), CURLOPT_POSTFIELDS, payload.c_str());
      curl_easy_setopt(c.get(), CURLOPT_POSTFIELDSIZE, static_cast<long>(payload.size()));
    }
    curl_easy_setopt(c.get(), CURLOPT_WRITEFUNCTION, +[](char* p, size_t s, size_t n, void* u) -> size_t {
      static_cast<std::string*>(u)->append(p, s * n);
      return s * n;
    });
    curl_easy_setopt(c.get(), CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c.get(), CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(c.get(), CURLOPT_PROTOCOLS_STR, "https");
    CURLcode rc = curl_easy_perform(c.get());
    long status = 0;
    curl_easy_getinfo(c.get(), CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(list);
    wipe(payload);
    if (rc != CURLE_OK) throw std::runtime_error(std::string("transport: ") + curl_easy_strerror(rc));
    json parsed = resp.empty() ? json() : json::parse(resp, nullptr, false);
    wipe(resp);
    return {status, parsed};
  }

  std::string vault_ep, secrets_ep;

 private:
  std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> key_{nullptr, EVP_PKEY_free};
  std::string key_id_;
};

class OciSecretStore {
 public:
  OciSecretStore(OciClient& oci, std::string comp, std::string vault, std::string key)
      : oci_(oci), comp_(std::move(comp)), vault_(std::move(vault)), key_(std::move(key)) {}

  std::string create(const std::string& name, const std::string& value) {
    json body = {{"compartmentId", comp_}, {"vaultId", vault_}, {"keyId", key_}, {"secretName", name},
                 {"description", "managed by secrets-crud example"}, {"freeformTags", {{"app", "secrets-crud"}}},
                 {"secretContent", content(value)}};
    unsigned char r[16];
    RAND_bytes(r, sizeof r);
    std::string token;
    for (unsigned char b : r) { char hx[3]; std::snprintf(hx, sizeof hx, "%02x", b); token += hx; }
    auto [status, s] = oci_.call("POST", oci_.vault_ep + "/20180608/secrets", &body, token);
    wipe_content(body);
    if (status == 409) throw std::runtime_error("secret " + name + " already exists in this vault");
    if (status != 200) throw std::runtime_error("create secret: HTTP " + std::to_string(status));
    std::string id = s["id"].get<std::string>();
    wait_active(id);
    return id;
  }

  std::string read(const std::string& id) {
    auto [status, b] = oci_.call("GET", oci_.secrets_ep + "/20190301/secretbundles/" + id + "?stage=CURRENT");
    if (status != 200) throw std::runtime_error("get secret bundle: HTTP " + std::to_string(status));
    auto* enc = b["secretBundleContent"]["content"].get_ptr<std::string*>();
    if (!enc) throw std::runtime_error("no content");
    std::string value = unb64(*enc);
    wipe(*enc);
    return value;
  }

  // New content creates a new version that becomes CURRENT.
  int update(const std::string& id, const std::string& value) {
    json body = {{"secretContent", content(value)}};
    auto [status, s] = oci_.call("PUT", oci_.vault_ep + "/20180608/secrets/" + id, &body);
    wipe_content(body);
    if (status != 200) throw std::runtime_error("update secret: HTTP " + std::to_string(status));
    wait_active(id);
    return s.value("currentVersionNumber", 0);
  }

  // Deletion is scheduled 1-30 days ahead; POST .../actions/cancelDeletion restores it.
  std::string schedule_deletion(const std::string& id, int days = 1) {
    std::time_t when = std::time(nullptr) + static_cast<std::time_t>(days) * 86400 + 60;
    std::tm tm{};
    gmtime_r(&when, &tm);
    char ts[32];
    std::strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%SZ", &tm);
    json body = {{"timeOfDeletion", ts}};
    auto [status, _] = oci_.call("POST", oci_.vault_ep + "/20180608/secrets/" + id + "/actions/scheduleDeletion", &body);
    if (status != 200) throw std::runtime_error("schedule deletion: HTTP " + std::to_string(status));
    return ts;
  }

 private:
  OciClient& oci_;
  std::string comp_, vault_, key_;

  static json content(const std::string& v) {
    return {{"contentType", "BASE64"}, {"content", b64(reinterpret_cast<const unsigned char*>(v.data()), v.size())}};
  }
  static void wipe_content(json& body) {
    if (auto* s = body["secretContent"]["content"].get_ptr<std::string*>()) wipe(*s);
  }
  void wait_active(const std::string& id) {
    for (int i = 0; i < 60; ++i) {
      auto [status, s] = oci_.call("GET", oci_.vault_ep + "/20180608/secrets/" + id);
      std::string state = s.value("lifecycleState", "");
      if (status == 200 && state == "ACTIVE") return;
      if (status != 200 || state == "FAILED") throw std::runtime_error("secret state " + state);
      std::this_thread::sleep_for(std::chrono::seconds(2));
    }
    throw std::runtime_error("timed out waiting for ACTIVE");
  }
};

static std::string random_value() {
  unsigned char raw[32];
  if (RAND_bytes(raw, sizeof raw) != 1) throw std::runtime_error("RAND_bytes failed");
  std::string out = b64(raw, sizeof raw);
  OPENSSL_cleanse(raw, sizeof raw);
  return out;
}

static bool same(const std::string& a, const std::string& b) {
  return a.size() == b.size() && CRYPTO_memcmp(a.data(), b.data(), a.size()) == 0;
}

int main() try {
  curl_global_init(CURL_GLOBAL_DEFAULT);
  OciClient oci;
  OciSecretStore store(oci, env("OCI_COMPARTMENT_ID"), env("OCI_VAULT_ID"), env("OCI_KEY_ID"));
  std::string name = env("SECRET_NAME");

  std::string v1 = random_value();
  std::string id = store.create(name, v1);
  std::cout << "created: " << id << "\n";
  std::string got = store.read(id);
  if (!same(v1, got)) throw std::runtime_error("read-back after create failed");

  std::string v2 = random_value();
  int version = store.update(id, v2);
  got = store.read(id);
  if (!same(v2, got)) throw std::runtime_error("read-back after update failed");
  std::cout << "updated: current version " << version << "\n";
  wipe(v1); wipe(v2); wipe(got);

  std::cout << "deletion scheduled for " << store.schedule_deletion(id) << "\n";
  curl_global_cleanup();
  return 0;
} catch (const std::exception& e) {
  std::cerr << "error: " << e.what() << "\n";
  return 1;
}
```

### 9.10 C

Same signing scheme in C11 with OpenSSL 3, libcurl, and cJSON.

```c
/*
 * OCI Vault secrets CRUD in C over the REST APIs with OCI request signing (rsa-sha256).
 * There is no official OCI SDK for C. libcurl + cJSON + OpenSSL 3.
 *
 *   cc -std=c11 -Wall -Wextra -O2 oci_secrets_crud.c -o oci_secrets_crud \
 *      $(pkg-config --cflags --libs libcurl libcjson openssl)
 *
 * Identity: API signing key (OCI_CLI_USER, OCI_CLI_TENANCY, OCI_CLI_FINGERPRINT, OCI_CLI_KEY_FILE,
 * OCI_CLI_REGION). Optional OCI_VAULT_ENDPOINT / OCI_SECRETS_ENDPOINT override the regional hosts.
 */
#define _POSIX_C_SOURCE 200809L
#include <cjson/cJSON.h>
#include <curl/curl.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct { char *data; size_t len; } buf_t;

static EVP_PKEY *g_key = NULL;
static char g_key_id[1024], g_vault_ep[512], g_secrets_ep[512];

static size_t on_body(char *p, size_t s, size_t n, void *u) {
    buf_t *b = u; size_t k = s * n;
    char *g = realloc(b->data, b->len + k + 1);
    if (!g) return 0;
    b->data = g; memcpy(b->data + b->len, p, k); b->len += k; b->data[b->len] = '\0';
    return k;
}
static void buf_wipe(buf_t *b) { if (b->data) { OPENSSL_cleanse(b->data, b->len); free(b->data); } b->data = NULL; b->len = 0; }

static int b64(const unsigned char *in, size_t n, char *out, size_t cap) {
    if (4 * ((n + 2) / 3) + 1 > cap) return -1;
    return EVP_EncodeBlock((unsigned char *)out, in, (int)n);
}

static int init_identity(void) {
    const char *user = getenv("OCI_CLI_USER"), *ten = getenv("OCI_CLI_TENANCY"), *fp = getenv("OCI_CLI_FINGERPRINT");
    const char *keyf = getenv("OCI_CLI_KEY_FILE"), *region = getenv("OCI_CLI_REGION");
    if (!user || !ten || !fp || !keyf || !region) { fprintf(stderr, "set OCI_CLI_USER/TENANCY/FINGERPRINT/KEY_FILE/REGION\n"); return -1; }
    FILE *f = fopen(keyf, "r");
    if (!f) return -1;
    g_key = PEM_read_PrivateKey(f, NULL, NULL, NULL);   /* PKCS#8 or PKCS#1 */
    fclose(f);
    if (!g_key) { fprintf(stderr, "cannot load private key\n"); return -1; }
    snprintf(g_key_id, sizeof g_key_id, "%s/%s/%s", ten, user, fp);
    const char *ve = getenv("OCI_VAULT_ENDPOINT"), *se = getenv("OCI_SECRETS_ENDPOINT");
    if (ve) snprintf(g_vault_ep, sizeof g_vault_ep, "%s", ve);
    else snprintf(g_vault_ep, sizeof g_vault_ep, "https://vaults.%s.oci.oraclecloud.com", region);
    if (se) snprintf(g_secrets_ep, sizeof g_secrets_ep, "%s", se);
    else snprintf(g_secrets_ep, sizeof g_secrets_ep, "https://secrets.vaults.%s.oci.oraclecloud.com", region);
    return 0;
}

/* Signed request. GET/DELETE sign date, (request-target), host; POST/PUT also sign
 * content-length, content-type, x-content-sha256. Returns HTTP status; *out gets parsed JSON. */
static long oci_call(const char *method, const char *url, cJSON *body, const char *retry_token, cJSON **out) {
    /* split URL into host and path?query */
    const char *p = strstr(url, "://");
    if (!p) return 0;
    p += 3;
    const char *slash = strchr(p, '/');
    if (!slash) return 0;
    char host[256], target[1024], method_lc[16], date[64];
    snprintf(host, sizeof host, "%.*s", (int)(slash - p), p);
    size_t i = 0;
    for (; method[i] && i < sizeof method_lc - 1; i++) method_lc[i] = (char)(method[i] | 0x20);
    method_lc[i] = '\0';
    snprintf(target, sizeof target, "%s %s", method_lc, slash);
    time_t now = time(NULL);
    struct tm tm;
    gmtime_r(&now, &tm);
    strftime(date, sizeof date, "%a, %d %b %Y %H:%M:%S GMT", &tm);

    int has_body = strcmp(method, "POST") == 0 || strcmp(method, "PUT") == 0;
    char *payload = has_body ? (body ? cJSON_PrintUnformatted(body) : strdup("")) : NULL;
    char signing[4096], signed_hdrs[128], sha_b64[64] = "", h_date[96], h_host[300], h_len[64], h_sha[96];
    size_t plen = payload ? strlen(payload) : 0;
    snprintf(signing, sizeof signing, "date: %s\n(request-target): %s\nhost: %s", date, target, host);
    snprintf(signed_hdrs, sizeof signed_hdrs, "date (request-target) host");
    if (has_body) {
        unsigned char dig[32];
        EVP_Digest(payload, plen, dig, NULL, EVP_sha256(), NULL);
        b64(dig, sizeof dig, sha_b64, sizeof sha_b64);
        size_t used = strlen(signing);
        snprintf(signing + used, sizeof signing - used,
                 "\ncontent-length: %zu\ncontent-type: application/json\nx-content-sha256: %s", plen, sha_b64);
        strcat(signed_hdrs, " content-length content-type x-content-sha256");
    }

    unsigned char sig[512]; size_t siglen = sizeof sig;
    EVP_MD_CTX *md = EVP_MD_CTX_new();
    int ok = EVP_DigestSignInit(md, NULL, EVP_sha256(), NULL, g_key) == 1 &&      /* RSA PKCS#1 v1.5 */
             EVP_DigestSign(md, sig, &siglen, (unsigned char *)signing, strlen(signing)) == 1;
    EVP_MD_CTX_free(md);
    if (!ok) { fprintf(stderr, "signing failed\n"); free(payload); return 0; }
    char sig_b64[700], auth[2048];
    b64(sig, siglen, sig_b64, sizeof sig_b64);
    snprintf(auth, sizeof auth,
             "Authorization: Signature version=\"1\",keyId=\"%s\",algorithm=\"rsa-sha256\",headers=\"%s\",signature=\"%s\"",
             g_key_id, signed_hdrs, sig_b64);

    struct curl_slist *h = NULL;
    snprintf(h_date, sizeof h_date, "date: %s", date); h = curl_slist_append(h, h_date);
    snprintf(h_host, sizeof h_host, "host: %s", host); h = curl_slist_append(h, h_host);
    h = curl_slist_append(h, auth);
    char h_retry[128];
    if (retry_token) { snprintf(h_retry, sizeof h_retry, "opc-retry-token: %s", retry_token); h = curl_slist_append(h, h_retry); }
    if (has_body) {
        snprintf(h_len, sizeof h_len, "content-length: %zu", plen); h = curl_slist_append(h, h_len);
        h = curl_slist_append(h, "content-type: application/json");
        snprintf(h_sha, sizeof h_sha, "x-content-sha256: %s", sha_b64); h = curl_slist_append(h, h_sha);
    }
    buf_t resp = {0};
    CURL *c = curl_easy_init();
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_CUSTOMREQUEST, method);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, h);
    if (has_body) { curl_easy_setopt(c, CURLOPT_POSTFIELDS, payload); curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE, (long)plen); }
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "https");
    long status = 0;
    if (curl_easy_perform(c) == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    curl_slist_free_all(h);
    if (payload) { OPENSSL_cleanse(payload, plen); free(payload); }
    if (out) *out = resp.len ? cJSON_Parse(resp.data) : NULL;
    buf_wipe(&resp);
    return status;
}

static int wait_active(const char *id) {
    char url[700]; snprintf(url, sizeof url, "%s/20180608/secrets/%s", g_vault_ep, id);
    for (int i = 0; i < 60; i++) {
        cJSON *out = NULL;
        long st = oci_call("GET", url, NULL, NULL, &out);
        const cJSON *s = cJSON_GetObjectItemCaseSensitive(out, "lifecycleState");
        int active = st == 200 && cJSON_IsString(s) && strcmp(s->valuestring, "ACTIVE") == 0;
        int failed = st != 200 || (cJSON_IsString(s) && strcmp(s->valuestring, "FAILED") == 0);
        cJSON_Delete(out);
        if (active) return 0;
        if (failed) return -1;
        struct timespec ts = {2, 0};
        nanosleep(&ts, NULL);
    }
    return -1;
}

static cJSON *content_json(const unsigned char *v, size_t n) {
    char enc[256];
    if (b64(v, n, enc, sizeof enc) < 0) return NULL;
    cJSON *c = cJSON_CreateObject();
    cJSON_AddStringToObject(c, "contentType", "BASE64");
    cJSON_AddStringToObject(c, "content", enc);
    OPENSSL_cleanse(enc, sizeof enc);
    return c;
}

/* CREATE (asynchronous). Returns malloc'd secret OCID or NULL. */
static char *secret_create(const char *comp, const char *vault, const char *key, const char *name,
                           const unsigned char *v, size_t n) {
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "compartmentId", comp);
    cJSON_AddStringToObject(body, "vaultId", vault);
    cJSON_AddStringToObject(body, "keyId", key);
    cJSON_AddStringToObject(body, "secretName", name);
    cJSON_AddStringToObject(body, "description", "managed by secrets-crud example");
    cJSON_AddStringToObject(cJSON_AddObjectToObject(body, "freeformTags"), "app", "secrets-crud");
    cJSON_AddItemToObject(body, "secretContent", content_json(v, n));
    unsigned char r[16]; char token[33];
    RAND_bytes(r, sizeof r);
    for (int i = 0; i < 16; i++) snprintf(token + 2 * i, 3, "%02x", r[i]);
    char url[600]; snprintf(url, sizeof url, "%s/20180608/secrets", g_vault_ep);
    cJSON *out = NULL;
    long st = oci_call("POST", url, body, token, &out);
    cJSON_Delete(body);
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(out, "id");
    char *res = (st == 200 && cJSON_IsString(id)) ? strdup(id->valuestring) : NULL;
    if (st == 409) fprintf(stderr, "secret already exists in this vault\n");
    else if (!res) fprintf(stderr, "create: HTTP %ld\n", st);
    cJSON_Delete(out);
    if (res && wait_active(res) != 0) { free(res); return NULL; }
    return res;
}

/* READ the CURRENT version; returns malloc'd bytes (wipe + free) and length. */
static unsigned char *secret_read(const char *id, size_t *len) {
    char url[700]; snprintf(url, sizeof url, "%s/20190301/secretbundles/%s?stage=CURRENT", g_secrets_ep, id);
    cJSON *out = NULL;
    long st = oci_call("GET", url, NULL, NULL, &out);
    cJSON *content = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(out, "secretBundleContent"), "content");
    unsigned char *r = NULL;
    if (st == 200 && cJSON_IsString(content)) {
        size_t bl = strlen(content->valuestring);
        r = malloc(bl + 1);
        int n = EVP_DecodeBlock(r, (unsigned char *)content->valuestring, (int)bl);
        if (n < 0) { free(r); r = NULL; }
        else {
            while (bl && content->valuestring[bl - 1] == '=') { n--; bl--; }
            *len = (size_t)n;
        }
        OPENSSL_cleanse(content->valuestring, strlen(content->valuestring));
    }
    cJSON_Delete(out);
    return r;
}

/* UPDATE: new content becomes the CURRENT version (asynchronous). */
static int secret_update(const char *id, const unsigned char *v, size_t n) {
    cJSON *body = cJSON_CreateObject();
    cJSON_AddItemToObject(body, "secretContent", content_json(v, n));
    char url[700]; snprintf(url, sizeof url, "%s/20180608/secrets/%s", g_vault_ep, id);
    long st = oci_call("PUT", url, body, NULL, NULL);
    cJSON_Delete(body);
    return st == 200 ? wait_active(id) : -1;
}

/* DELETE: schedule deletion 1-30 days ahead (cancelDeletion restores it until then). */
static int secret_schedule_deletion(const char *id, int days) {
    time_t when = time(NULL) + (time_t)days * 86400 + 60;
    struct tm tm; char ts[32];
    gmtime_r(&when, &tm);
    strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%SZ", &tm);
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "timeOfDeletion", ts);
    char url[700]; snprintf(url, sizeof url, "%s/20180608/secrets/%s/actions/scheduleDeletion", g_vault_ep, id);
    long st = oci_call("POST", url, body, NULL, NULL);
    cJSON_Delete(body);
    if (st == 200) printf("deletion scheduled for %s\n", ts);
    return st == 200 ? 0 : -1;
}

static void random_value(unsigned char out[45]) {
    unsigned char raw[32];
    RAND_bytes(raw, sizeof raw);
    EVP_EncodeBlock(out, raw, sizeof raw);
    OPENSSL_cleanse(raw, sizeof raw);
}

static int same(const unsigned char *a, size_t an, const unsigned char *b, size_t bn) {
    return b && an == bn && CRYPTO_memcmp(a, b, an) == 0;
}

int main(void) {
    const char *comp = getenv("OCI_COMPARTMENT_ID"), *vault = getenv("OCI_VAULT_ID"), *key = getenv("OCI_KEY_ID");
    const char *name = getenv("SECRET_NAME");
    if (!comp || !vault || !key || !name) { fprintf(stderr, "set OCI_COMPARTMENT_ID, OCI_VAULT_ID, OCI_KEY_ID, SECRET_NAME\n"); return 2; }
    if (init_identity() != 0) return 2;
    curl_global_init(CURL_GLOBAL_DEFAULT);
    int rc = 1;
    unsigned char v1[45], v2[45], *got = NULL;
    size_t got_len = 0;
    char *id = NULL;

    random_value(v1);
    if (!(id = secret_create(comp, vault, key, name, v1, 44))) goto done;
    printf("created: %s\n", id);
    got = secret_read(id, &got_len);
    if (!same(v1, 44, got, got_len)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    OPENSSL_cleanse(got, got_len); free(got); got = NULL;

    random_value(v2);
    if (secret_update(id, v2, 44) != 0) goto done;
    got = secret_read(id, &got_len);
    if (!same(v2, 44, got, got_len)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated\n");

    if (secret_schedule_deletion(id, 1) != 0) goto done;
    rc = 0;
done:
    if (got) { OPENSSL_cleanse(got, got_len); free(got); }
    OPENSSL_cleanse(v1, sizeof v1); OPENSSL_cleanse(v2, sizeof v2);
    free(id);
    EVP_PKEY_free(g_key);
    curl_global_cleanup();
    return rc;
}
```

## 10. Use secrets in applications

| Mechanism | How the value arrives | Notes |
| --- | --- | --- |
| SDK call with a principal + in-process cache | In memory | Preferred inside OCI. |
| OKE: Secrets Store CSI Driver with the OCI provider | Mounted files | Uses workload identity; enable rotation polling. |
| OCI Functions | SDK with resource principal at cold start | Cache across invocations within the container lifetime. |
| Database / service integrations (for example Autonomous Database with Vault secrets) | Service reads the secret itself | No app handling. |

Rotation-safe consumption: read `CURRENT` at startup and cache; on a downstream authentication failure, re-read once and retry once. For coordinated rotation, write the new version as `PENDING`, update consumers or the target system, then promote it with `currentVersionNumber`.

## 11. Automation and error handling

| Status / code | Typical cause | Action |
| --- | --- | --- |
| 401 `NotAuthenticated` | Bad signature: clock skew, wrong key/fingerprint, header mismatch, body hash mismatch | Sync clock (within 5 minutes); check keyId and signed headers. |
| 404 `NotAuthorizedOrNotFound` | Missing IAM permission **or** wrong OCID/region — OCI does not distinguish | Check region endpoint, OCID, and policy (including `use keys`/`use vaults` for create). |
| 409 `Conflict` / `IncorrectState` | Duplicate name; operation during `CREATING`/`UPDATING`/`PENDING_DELETION` | Wait for `ACTIVE`; use a unique name. |
| 429 `TooManyRequests` | Throttling | SDKs retry with backoff; cache reads. |
| 5xx | Service | Retry with backoff (SDK default retry policies cover these). |

Practices:

- Always wait for `ACTIVE` after create and update before reading or issuing another update.
- Use `opc-retry-token` on creates; reuse the same token when retrying the same logical create.
- Use `if-match` with the secret's ETag on update/delete in automation that decided based on an earlier read.
- Keep the secret OCID; names are only unique per vault and can be reused after deletion.
- Use the secrets (retrieval) endpoint for reads and the vaults (management) endpoint for writes; private endpoints may be needed for both.

## 12. Optional live CRUD verification

This **performs writes** in the compartment and vault you choose; the secret ends in `PENDING_DELETION`.

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${COMPARTMENT_ID:?}" "${VAULT_ID:?}" "${KEY_ID:?}"
work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
name="crud-check-$(date -u +%Y%m%d%H%M%S)-$$"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v1"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v2"

jq -n --arg c "$COMPARTMENT_ID" --arg v "$VAULT_ID" --arg k "$KEY_ID" --arg n "$name" --rawfile s "$work/v1" \
  '{compartmentId:$c, vaultId:$v, keyId:$k, secretName:$n, secretContentContent:($s|@base64)}' > "$work/c.json"
id="$(oci vault secret create-base64 --from-json "file://$work/c.json" --wait-for-state ACTIVE --query data.id --raw-output)"
oci secrets secret-bundle get --secret-id "$id" --query 'data."secret-bundle-content".content' --raw-output |
  base64 -d | cmp -s - "$work/v1"

jq -n --arg id "$id" --rawfile s "$work/v2" '{secretId:$id, secretContentContent:($s|@base64)}' > "$work/u.json"
oci vault secret update-base64 --from-json "file://$work/u.json" --wait-for-state ACTIVE > /dev/null
oci secrets secret-bundle get --secret-id "$id" --query 'data."secret-bundle-content".content' --raw-output |
  base64 -d | cmp -s - "$work/v2"

oci vault secret schedule-secret-deletion --secret-id "$id" \
  --time-of-deletion "$(date -u -d '+1 day 5 minutes' +%Y-%m-%dT%H:%M:%SZ)"
printf 'PASS: create, read, update, and scheduled delete completed for %s\n' "$id"
```

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| 401 on every call from a REST client | Clock skew; signing string line order; `(request-target)` must include the query; `x-content-sha256` must hash the exact bytes sent; keyId fingerprint must match the uploaded public key. |
| 404 `NotAuthorizedOrNotFound` | Policy missing (`read secret-bundles`, or `use keys` + `use vaults` + `manage secrets` for create), wrong region host, or wrong compartment. |
| Read fails right after create | Secret still `CREATING`; wait for `ACTIVE`. |
| `IncorrectState` on update | Previous update still `UPDATING`, or secret pending deletion. |
| Instance principal fails | Instance not in the dynamic group; dynamic-group matching rule; IMDS blocked. |
| OKE workload identity fails | Cluster not "enhanced"; service account not referenced in policy (`request.principal.type = 'workload'`, namespace, service account conditions). |
| Wrong value after rotation | Reading a pinned `versionNumber` or `PREVIOUS`; or cache TTL too long. |
| Secret visible in logs | SDK debug logging, CLI `--debug`, or app logging of responses; disable and rotate. |

## 14. Accuracy notes and official sources

- **Deletion window:** the deletion how-to states a 1–30 day range (default 30). A linked description mentions a 7-day cancellation period; the inconsistency is flagged in section 8. [S07]
- **25 KB bundle limit** and the symmetric same-vault key requirement are from the create-secret page. [S04]
- **C#, Java, Swift** were not compiled here.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [Vault overview][S01] | Concepts, endpoints |
| S02 | [Vault and Secrets API reference][S02] | CreateSecret, UpdateSecret, ScheduleSecretDeletion, GetSecretBundle(ByName) |
| S03 | [Vault policy reference][S03] | Resource types, verbs, condition variables, create prerequisites |
| S04 | [Creating a secret][S04] | 25 KB limit, symmetric key, rules, CLI |
| S05 | [CreateSecretDetails model][S05] | Name characters and uniqueness |
| S06 | [Request signatures][S06] | Signing string, headers, keyId format |
| S07 | [Deleting a secret][S07] | 1–30 day schedule, pending state, cancel, replicas |
| S08 | [SDK authentication methods][S08] | Instance, resource, OKE workload identity principals |
| S09 | [OCI Go SDK][S09] | Go packages |
| S10 | [OCI Java SDK][S10] | Java builders and waiters |
| S11 | [OCI .NET SDK][S11] | .NET clients and models |
| S12 | [OCI TypeScript SDK][S12] | TS clients and providers |

[S01]: https://docs.oracle.com/en-us/iaas/Content/KeyManagement/Concepts/keyoverview.htm
[S02]: https://docs.oracle.com/en-us/iaas/api/#/en/secretmgmt/20180608/
[S03]: https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/keypolicyreference.htm
[S04]: https://docs.oracle.com/iaas/Content/KeyManagement/Tasks/managingsecrets_topic-To_create_a_new_secret.htm
[S05]: https://docs.oracle.com/en-us/iaas/api/#/en/secretmgmt/20180608/datatypes/CreateSecretDetails
[S06]: https://docs.oracle.com/en-us/iaas/Content/API/Concepts/signingrequests.htm
[S07]: https://docs.oracle.com/en-us/iaas/Content/KeyManagement/Tasks/managingsecrets_topic-To_delete_a_secret.htm
[S08]: https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdk_authentication_methods.htm
[S09]: https://github.com/oracle/oci-go-sdk
[S10]: https://github.com/oracle/oci-java-sdk
[S11]: https://github.com/oracle/oci-dotnet-sdk
[S12]: https://github.com/oracle/oci-typescript-sdk
