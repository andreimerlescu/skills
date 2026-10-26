# Google Cloud Secret Manager: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** Secret Manager API `v1` (`secretmanager.googleapis.com`), gRPC and REST  
**Primary authentication:** Application Default Credentials (ADC) resolved from an attached service account, GKE Workload Identity, or Workload Identity Federation  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use Bash and `gcloud`)

This guide covers **global (automatically or user-managed replicated) secrets** in Secret Manager: a secret resource that holds metadata and IAM policy, plus immutable, numbered **secret versions** that hold payloads. It covers identity checks, IAM, complete CRUD workflows, payload integrity (CRC32C), a full CRUD program in each of ten languages, runtime consumption, and troubleshooting. Regional secrets (`projects/*/locations/*/secrets/*`) behave the same apart from endpoint, rate limits, and replication; differences are noted. Parameter Manager is out of scope.

Credentials are assumed to be provisioned already. Do not create or download service-account key files for this; Google recommends ADC via the metadata server, Workload Identity, or Workload Identity Federation instead of exported keys. [S02]

**Verification boundary:** API semantics were cross-checked against the official reference and client sources in section 14. The Go program passed `go vet` against `cloud.google.com/go/secretmanager v1.23.0`; the Rust program passed `cargo check` against `google-cloud-secretmanager-v1 1.14.0`; the TypeScript program passed `tsc --strict` against `@google-cloud/secret-manager 7.2.0`; the Python program ran end-to-end against a fake client that builds every request as the real `CreateSecretRequest`/`AddSecretVersionRequest`/… proto types; the C program compiled with `-Werror` and ran end-to-end against a local mock of the REST surface (including CRC32C validation). PHP passed `php -l` and was checked against `google/cloud-secret-manager` sources; C#, Java, and C++ were checked against the generated client sources (`Google.Cloud.SecretManager.V1`, `google-cloud-secretmanager`, `google-cloud-cpp`) but not compiled here; Swift was written against the documented REST surface and not compiled (no Swift toolchain was available). No call was made to a real Google Cloud project. Section 12 provides an optional live test.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Use the existing credentials](#2-use-the-existing-credentials)
3. [Data model and addressing](#3-data-model-and-addressing)
4. [Safe secret handling](#4-safe-secret-handling)
5. [Create secrets](#5-create-secrets)
6. [Read secrets](#6-read-secrets)
7. [Update secrets](#7-update-secrets)
8. [Disable, destroy, and delete](#8-disable-destroy-and-delete)
9. [Language implementations](#9-language-implementations)
10. [Use secrets in applications](#10-use-secrets-in-applications)
11. [Automation and error handling](#11-automation-and-error-handling)
12. [Optional live CRUD verification](#12-optional-live-crud-verification)
13. [Troubleshooting](#13-troubleshooting)
14. [Accuracy notes and official sources](#14-accuracy-notes-and-official-sources)

## 1. Requirements and conventions

| Language | Official client | Transport used here | Verified here |
| --- | --- | --- | --- |
| Go | `cloud.google.com/go/secretmanager/apiv1` | gRPC | `go vet` (v1.23.0) |
| Rust | `google-cloud-secretmanager-v1` | HTTP/JSON | `cargo check` (1.14.0) |
| PHP | `google/cloud-secret-manager` (V1 `Client\SecretManagerServiceClient`) | gRPC or REST | `php -l`, source check |
| C# | `Google.Cloud.SecretManager.V1` | gRPC | source check |
| Java | `com.google.cloud:google-cloud-secretmanager` | gRPC | source/API check |
| Swift | none (no official client) | REST via `URLSession` | not compiled |
| Python | `google-cloud-secret-manager` (+ `google-crc32c`) | gRPC | fake-client run |
| TypeScript | `@google-cloud/secret-manager` | gRPC | `tsc --strict` (7.2.0) |
| C++ | `google-cloud-cpp`, `secretmanager_v1` | gRPC | header check |
| C | none | REST via libcurl + cJSON | compiled, mock-run |

Every program follows the same contract:

- Non-secret configuration: `GOOGLE_CLOUD_PROJECT` (project ID) and `SECRET_ID` (for example `myapp-dev-crud-check`).
- It generates a 256-bit random demo value with the platform CSPRNG, **creates** the secret and its first version, **reads** `latest` and compares in constant time, **updates** by adding a version, reads and compares again, then **deletes** the secret.
- Every write sends `data_crc32c`; every read verifies the returned checksum.
- It prints resource names only. It never prints, logs, or passes a payload on a command line.

For `gcloud` snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
gcloud --version
PROJECT_ID='REPLACE_WITH_PROJECT_ID'
```

## 2. Use the existing credentials

### Where ADC comes from

| Environment | Credential source | Notes |
| --- | --- | --- |
| Compute Engine, Cloud Run, Cloud Functions, App Engine | Metadata server (attached service account) | Preferred. No key material on disk. |
| GKE | Workload Identity Federation for GKE | Bind the Kubernetes service account to an IAM principal. |
| AWS, Azure, on-prem, CI (GitHub Actions, GitLab) | Workload Identity Federation (credential configuration file, no secret) | Exchanges an external token for a short-lived Google token. |
| Developer workstation | `gcloud auth application-default login` | Human credentials; never ship them to a workload. |
| `GOOGLE_APPLICATION_CREDENTIALS` pointing to a key file | Service-account key | Avoid; a long-lived key is a finding. |

`GOOGLE_APPLICATION_CREDENTIALS` takes precedence over the metadata server. If a workload unexpectedly runs as the wrong identity, check whether that variable points at a stale file.

### Confirm identity without displaying a token

```bash
# Workstation / CI: which account gcloud uses (no token printed)
gcloud config get-value account
gcloud auth list --filter=status:ACTIVE --format='value(account)'

# Inside a GCP workload: the attached service account email
curl -s -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email'; echo
```

Do not run `gcloud auth print-access-token` or `print-identity-token` in shared terminals or CI logs; they print bearer tokens.

### Required IAM

Grant roles on the **individual secret** where possible, or use IAM Conditions on resource name prefixes in shared projects. [S03]

| Operation | Permission | Narrowest predefined role |
| --- | --- | --- |
| Create secret | `secretmanager.secrets.create` | `roles/secretmanager.admin` or a custom role (Editor also has it) |
| Add version (update) | `secretmanager.versions.add` | `roles/secretmanager.secretVersionAdder` |
| Access payload (read) | `secretmanager.versions.access` | `roles/secretmanager.secretAccessor` |
| Read metadata | `secretmanager.secrets.get`, `secretmanager.versions.list` | `roles/secretmanager.viewer` |
| Disable/enable/destroy versions | `secretmanager.versions.disable/enable/destroy` | `roles/secretmanager.secretVersionManager` |
| Delete secret | `secretmanager.secrets.delete` | `roles/secretmanager.admin` or custom |

Grant a runtime identity exactly `roles/secretmanager.secretAccessor` on the secrets it reads:

```bash
gcloud secrets add-iam-policy-binding myapp-prod-db \
  --project "$PROJECT_ID" \
  --member 'serviceAccount:myapp-runtime@REPLACE_PROJECT.iam.gserviceaccount.com' \
  --role 'roles/secretmanager.secretAccessor'
```

A creator/rotator identity in a shared project can be limited to a prefix with an IAM Condition (custom role with `secrets.create`, `versions.add`, `secrets.delete`):

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member 'serviceAccount:myapp-provisioner@REPLACE_PROJECT.iam.gserviceaccount.com' \
  --role 'projects/REPLACE_PROJECT/roles/secretCrudPrefixed' \
  --condition='title=myapp-only,expression=resource.name.startsWith("projects/REPLACE_PROJECT_NUMBER/secrets/myapp-")'
```

IAM resource names in conditions use the **project number**, not the project ID. Separate projects per environment are a stronger boundary than conditions. [S03] [S04]

## 3. Data model and addressing

- **Secret:** `projects/{project}/secrets/{secret_id}` (global) or `projects/{project}/locations/{location}/secrets/{secret_id}` (regional). Holds replication policy, labels, annotations, optional CMEK, rotation schedule and Pub/Sub topics, optional expiration, `version_destroy_ttl`, version aliases, an `etag`, and its own IAM policy.
- **Secret ID:** up to 255 characters of letters, digits, `-`, and `_`. [S08]
- **Secret version:** `.../secrets/{id}/versions/{n}`, numbered from 1, immutable, payload up to **64 KiB**. States: `ENABLED`, `DISABLED`, `DESTROYED`. [S01]
- **`latest`** is an alias for the most recently created **enabled** version. Custom aliases (up to 50 per version) can name versions such as `current` or `canary`. [S01]
- **Replication** is fixed at creation: `automatic` (Google chooses regions) or `userManaged` (you list regions, optionally with per-region CMEK).
- **CRC32C:** `SecretPayload.data_crc32c` lets the server reject a corrupted write and lets the client verify a read end to end.

Inventory metadata (no payloads):

```bash
gcloud secrets list --project "$PROJECT_ID" --filter='labels.app=myapp' \
  --format='table(name,createTime,labels)'
SECRET_ID='REPLACE_WITH_SECRET_ID'
gcloud secrets describe "$SECRET_ID" --project "$PROJECT_ID" --format=json |
  jq '{name, replication, etag, labels, versionDestroyTtl, expireTime}'
gcloud secrets versions list "$SECRET_ID" --project "$PROJECT_ID" \
  --format='table(name,state,createTime,destroyTime)'
```

## 4. Safe secret handling

- **Payloads are bytes.** Text is UTF-8 by convention; the API does not interpret it. Preserve exact bytes (newlines included) by reading and writing files, not shell variables.
- **Command lines:** `gcloud secrets create --data-file=FILE` and `versions add --data-file=FILE` read a file (`-` for stdin). Never use `echo "$SECRET" |` with tracing on, and never pass the value as an argument.
- **Audit logs:** `AccessSecretVersion` is a **Data Access** audit log type; enable it (organization or folder level) so reads are attributable. Admin Activity logs (create, add version, delete) are always on. Payloads are not written to audit logs. [S04]
- **Client logging:** gRPC/HTTP debug logging (`GRPC_TRACE`, `GOOGLE_SDK_*_LOGGING`, HTTP wire logs) can print request and response bodies. Keep it off around real secrets.
- **Environment variables and files:** Google's best practices discourage delivering secrets through the filesystem or environment variables when a direct API call is possible, because of directory traversal and debug-endpoint leaks. [S04]
- **Memory:** keep payload bytes in the narrowest scope; wipe byte buffers where the language allows (`zeroize`, `OPENSSL_cleanse`, `CryptographicOperations.ZeroMemory`, `Arrays.fill`, `Buffer.fill`). Protobuf message internals cannot be wiped; minimize copies.

## 5. Create secrets

Creation is two steps: **`CreateSecret`** makes the container (replication cannot be changed later), then **`AddSecretVersion`** stores the first payload. A secret with no enabled version cannot be accessed. [S05]

- `ALREADY_EXISTS` (HTTP 409) means the ID is taken in that project/location. **Create is not an upsert.**
- Deletion is immediate (section 8), so the ID becomes reusable as soon as the delete completes.
- Labels and annotations are metadata visible to anyone with `secrets.get`; never put secret material in them.

### A. Create from a protected file

```bash
SECRET_FILE='/secure/path/to/api-token.txt'   # exists, mode 0600
gcloud secrets create myapp-dev-api-token \
  --project "$PROJECT_ID" \
  --replication-policy=automatic \
  --labels=app=myapp,env=dev \
  --data-file="$SECRET_FILE" \
  --format='value(name)'
```

`--data-file` stores the file's exact bytes, including a trailing newline. Produce the file with `printf '%s'` if the consumer expects no newline.

### B. Create with user-managed replication and CMEK

```bash
gcloud secrets create myapp-prod-db \
  --project "$PROJECT_ID" \
  --replication-policy=user-managed \
  --locations=europe-west1,europe-west4 \
  --labels=app=myapp,env=prod
gcloud secrets versions add myapp-prod-db --project "$PROJECT_ID" --data-file=/secure/path/db.json
```

Per-location CMEK uses `--replication-policy-file` with `customerManagedEncryption.kmsKeyName` entries; the Secret Manager service agent needs `roles/cloudkms.cryptoKeyEncrypterDecrypter` on each key.

### C. Create a structured (JSON) secret without printing it

```bash
(
  set -euo pipefail; set +x; umask 077
  work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
  jq -n --rawfile pw /secure/path/db-password.txt \
    '{username: "app_rw", password: ($pw | rtrimstr("\n")), host: "10.0.0.5", port: 5432}' > "$work/s.json"
  gcloud secrets create myapp-dev-db --project "$PROJECT_ID" \
    --replication-policy=automatic --data-file="$work/s.json" --format='value(name)'
)
```

## 6. Read secrets

`AccessSecretVersion` returns the payload of a specific version number, an alias, or `latest`. Disabled and destroyed versions cannot be accessed (`FAILED_PRECONDITION`). The response carries `data_crc32c`; verify it. [S05]

```bash
# Write the payload to a new private file, not the terminal
gcloud secrets versions access latest --secret=myapp-dev-api-token \
  --project "$PROJECT_ID" --out-file=./api-token.secret

# Without --out-file, gcloud prints the payload as UTF-8 text, which can corrupt binary secrets.

# Pin a specific version (recommended for production releases)
gcloud secrets versions access 3 --secret=myapp-dev-api-token \
  --project "$PROJECT_ID" --out-file=./api-token.v3.secret

# Check JSON structure without printing values
gcloud secrets versions access latest --secret=myapp-dev-db --project "$PROJECT_ID" |
  jq -e 'has("username") and has("password")' > /dev/null && printf 'structure ok\n'
```

**`latest` versus pinned versions.** Google's best practices recommend pinning a version number in production configuration and rolling a new version out through your normal release process, so a bad value cannot break every instance at once. Use `latest` when you deliberately want instances to pick up new versions on refresh. [S04] The programs in section 9 read `latest` because they verify their own writes.

Access quota is **90,000 requests per minute per project**, shared by all callers; cache values in process (section 10). [S01]

## 7. Update secrets

Payloads are immutable. "Update" means **`AddSecretVersion`**, after which `latest` resolves to the new version. Metadata changes (labels, annotations, rotation, expiration, aliases, `version_destroy_ttl`) use **`UpdateSecret`** with an update mask and optionally the current `etag` for optimistic concurrency. [S05]

```bash
# New payload version from a protected file
gcloud secrets versions add myapp-dev-api-token --project "$PROJECT_ID" \
  --data-file="$SECRET_FILE" --format='value(name)'

# Metadata-only update
gcloud secrets update myapp-dev-api-token --project "$PROJECT_ID" \
  --update-labels=owner=platform-team

# Roll back: disable the bad version so `latest` falls back to the previous enabled one
gcloud secrets versions disable 4 --secret=myapp-dev-api-token --project "$PROJECT_ID"
```

Verify a replacement without printing either value:

```bash
(
  set -euo pipefail; umask 077
  work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
  gcloud secrets versions access latest --secret=myapp-dev-api-token --project "$PROJECT_ID" \
    --out-file="$work/readback"
  cmp -s "$work/readback" "$SECRET_FILE" && printf 'Secret replacement verified.\n'
)
```

Write rate per secret is soft-limited (global secrets: about 2 QPS / 120 QPM for `AddSecretVersion`/`UpdateSecret`; regional secrets are higher). Project-wide write quota is 600 per minute. [S01]

Adding a version does **not** change the credential at the database or API provider. Rotate at the source, add the version, let consumers refresh, then disable the old version. Secret Manager's `rotation` field only **publishes notifications** to Pub/Sub topics on schedule; your rotation function does the actual work.

## 8. Disable, destroy, and delete

| Action | Scope | Reversible | Effect |
| --- | --- | --- | --- |
| `DisableSecretVersion` | one version | Yes (`EnableSecretVersion`) | Version cannot be accessed; `latest` skips it. |
| `DestroySecretVersion` | one version | **No** (unless delayed destruction is configured and you re-enable before `scheduled_destroy_time`) | Payload permanently removed; metadata remains with state `DESTROYED`. |
| `DeleteSecret` | the secret and **all** versions | **No** | Immediate, irreversible. |

Recommended order: disable → wait (for example a week) while watching Data Access logs for failed reads → destroy or delete. Google's best practices recommend disabling before destroying for exactly this reason. [S04]

**Delayed destruction:** setting `version_destroy_ttl` on a secret makes `DestroySecretVersion` move the version to `DISABLED` with a `scheduled_destroy_time`; destruction happens only after the TTL, and re-enabling first cancels it. This protects individual versions; `DeleteSecret` remains immediate. Enable it at creation with `gcloud secrets create … --version-destroy-ttl=86400s` (or later with `gcloud secrets update`). [S06]

**Concurrency:** `DeleteSecretRequest.etag` (and `DestroySecretVersionRequest.etag`) make the call succeed only if the stored object still matches; use it in automation that decided to delete based on an earlier read.

```bash
# Inspect the exact target and capture its etag
ETAG="$(gcloud secrets describe myapp-dev-api-token --project "$PROJECT_ID" --format='value(etag)')"

# Disable a version (reversible)
gcloud secrets versions disable 3 --secret=myapp-dev-api-token --project "$PROJECT_ID"

# Destroy a version (irreversible unless delayed destruction is configured)
gcloud secrets versions destroy 3 --secret=myapp-dev-api-token --project "$PROJECT_ID"

# Delete the whole secret, only if unchanged since inspection (irreversible)
gcloud secrets delete myapp-dev-api-token --project "$PROJECT_ID" --etag="$ETAG" --quiet
```

`expire_time`/`ttl` on a secret deletes it automatically at expiry. Do not set expiration on production secrets unless permanent deletion is intended; use time-bound IAM Conditions for time-limited access instead. [S04] Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Each program is complete and self-checking. Set `GOOGLE_CLOUD_PROJECT` and `SECRET_ID`, run it against a sandbox project, and expect:

```text
created: projects/my-sandbox/secrets/crud-check-20261026
updated: projects/123456789012/secrets/crud-check-20261026/versions/2
deleted: projects/my-sandbox/secrets/crud-check-20261026
```

(Responses may use the project number in resource names.) A second run fails at create with `ALREADY_EXISTS` only if the first run stopped before delete.

### 9.1 Go

`go get cloud.google.com/go/secretmanager/apiv1`. gRPC status codes are inspected with `status.Code(err)`; the standard library's Castagnoli table computes CRC32C.

```go
// Google Cloud Secret Manager CRUD with cloud.google.com/go/secretmanager.
// Authentication: Application Default Credentials (attached service account,
// workload identity federation, or gcloud ADC on a workstation).
package main

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"hash/crc32"
	"log"
	"os"
	"time"

	secretmanager "cloud.google.com/go/secretmanager/apiv1"
	"cloud.google.com/go/secretmanager/apiv1/secretmanagerpb"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

var castagnoli = crc32.MakeTable(crc32.Castagnoli)

type Store struct{ client *secretmanager.Client }

// Create makes the secret container and adds the first version.
func (s *Store) Create(ctx context.Context, project, id string, value []byte) (string, error) {
	secret, err := s.client.CreateSecret(ctx, &secretmanagerpb.CreateSecretRequest{
		Parent:   "projects/" + project,
		SecretId: id,
		Secret: &secretmanagerpb.Secret{
			Replication: &secretmanagerpb.Replication{
				Replication: &secretmanagerpb.Replication_Automatic_{
					Automatic: &secretmanagerpb.Replication_Automatic{},
				},
			},
			Labels: map[string]string{"app": "secrets-crud"},
		},
	})
	if status.Code(err) == codes.AlreadyExists {
		return "", fmt.Errorf("secret %q already exists (create is not an upsert): %w", id, err)
	}
	if err != nil {
		return "", fmt.Errorf("create secret: %w", err)
	}
	if _, err := s.AddVersion(ctx, secret.GetName(), value); err != nil {
		return "", err
	}
	return secret.GetName(), nil
}

// AddVersion is the update path: versions are immutable and "latest" moves forward.
func (s *Store) AddVersion(ctx context.Context, secretName string, value []byte) (string, error) {
	crc := int64(crc32.Checksum(value, castagnoli))
	v, err := s.client.AddSecretVersion(ctx, &secretmanagerpb.AddSecretVersionRequest{
		Parent:  secretName,
		Payload: &secretmanagerpb.SecretPayload{Data: value, DataCrc32C: &crc},
	})
	if err != nil {
		return "", fmt.Errorf("add secret version: %w", err)
	}
	return v.GetName(), nil
}

// Read accesses the newest enabled version and verifies its checksum.
func (s *Store) Read(ctx context.Context, secretName string) ([]byte, error) {
	resp, err := s.client.AccessSecretVersion(ctx, &secretmanagerpb.AccessSecretVersionRequest{
		Name: secretName + "/versions/latest",
	})
	if status.Code(err) == codes.NotFound {
		return nil, fmt.Errorf("secret or version not found: %w", err)
	}
	if err != nil {
		return nil, fmt.Errorf("access secret version: %w", err)
	}
	data := resp.GetPayload().GetData()
	if int64(crc32.Checksum(data, castagnoli)) != resp.GetPayload().GetDataCrc32C() {
		return nil, errors.New("payload checksum mismatch")
	}
	return data, nil
}

// Delete removes the secret and every version, immediately and irreversibly.
func (s *Store) Delete(ctx context.Context, secretName string) error {
	if err := s.client.DeleteSecret(ctx, &secretmanagerpb.DeleteSecretRequest{Name: secretName}); err != nil {
		return fmt.Errorf("delete secret: %w", err)
	}
	return nil
}

func randomValue() []byte {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		log.Fatal("csprng: ", err)
	}
	return []byte(base64.RawURLEncoding.EncodeToString(b))
}

func wipe(b []byte) {
	for i := range b {
		b[i] = 0
	}
}

func main() {
	project, id := os.Getenv("GOOGLE_CLOUD_PROJECT"), os.Getenv("SECRET_ID")
	if project == "" || id == "" {
		log.Fatal("set GOOGLE_CLOUD_PROJECT and SECRET_ID")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	client, err := secretmanager.NewClient(ctx)
	if err != nil {
		log.Fatal(err)
	}
	defer client.Close()
	store := &Store{client: client}

	v1 := randomValue()
	name, err := store.Create(ctx, project, id, v1)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("created:", name)
	got, err := store.Read(ctx, name)
	if err != nil || subtle.ConstantTimeCompare(got, v1) != 1 {
		log.Fatal("read-back after create failed: ", err)
	}
	wipe(got)

	v2 := randomValue()
	version, err := store.AddVersion(ctx, name, v2)
	if err != nil {
		log.Fatal(err)
	}
	if got, err = store.Read(ctx, name); err != nil || subtle.ConstantTimeCompare(got, v2) != 1 {
		log.Fatal("read-back after update failed: ", err)
	}
	wipe(got)
	wipe(v1)
	wipe(v2)
	fmt.Println("updated:", version)

	if err := store.Delete(ctx, name); err != nil {
		log.Fatal(err)
	}
	fmt.Println("deleted:", name)
}
```

### 9.2 Rust

`Cargo.toml`:

```toml
[package]
name = "gcp-secrets-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
google-cloud-secretmanager-v1 = "1"
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
crc32c = "0.6"
google-cloud-gax = "1"
getrandom = "0.3"
base64 = "0.22"
zeroize = "1"
```

The client uses ADC by default and holds a connection pool internally; build it once and clone it freely. Errors expose `status().code`.

```rust
//! Google Cloud Secret Manager CRUD with the official Rust client
//! (google-cloud-secretmanager-v1). Authentication: Application Default Credentials.
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use google_cloud_gax::error::rpc::Code;
use google_cloud_secretmanager_v1::client::SecretManagerService;
use google_cloud_secretmanager_v1::model::{replication::Automatic, Replication, Secret, SecretPayload};
use std::{env, error::Error};
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

/// CREATE = create the secret container, then add the first version.
async fn create(client: &SecretManagerService, project: &str, id: &str, value: &[u8]) -> Res<String> {
    let secret = client
        .create_secret()
        .set_parent(format!("projects/{project}"))
        .set_secret_id(id)
        .set_secret(
            Secret::new()
                .set_replication(Replication::new().set_automatic(Automatic::new()))
                .set_labels([("app", "secrets-crud")]),
        )
        .send()
        .await
        .map_err(|e| match e.status().map(|s| s.code) {
            Some(Code::AlreadyExists) => format!("secret {id} already exists (create is not an upsert)").into(),
            _ => Box::<dyn Error + Send + Sync>::from(e),
        })?;
    add_version(client, &secret.name, value).await?;
    Ok(secret.name)
}

/// UPDATE = add a new version; `latest` now resolves to it. Versions are immutable.
async fn add_version(client: &SecretManagerService, secret_name: &str, value: &[u8]) -> Res<String> {
    let version = client
        .add_secret_version()
        .set_parent(secret_name)
        .set_payload(
            SecretPayload::new()
                .set_data(value.to_vec())
                .set_data_crc32c(crc32c::crc32c(value) as i64), // server rejects corrupted payloads
        )
        .send()
        .await?;
    Ok(version.name)
}

/// READ the newest enabled version and verify its checksum.
async fn read(client: &SecretManagerService, secret_name: &str) -> Res<Zeroizing<Vec<u8>>> {
    let resp = client
        .access_secret_version()
        .set_name(format!("{secret_name}/versions/latest"))
        .send()
        .await?;
    let payload = resp.payload.ok_or("response had no payload")?;
    let data = Zeroizing::new(payload.data.to_vec());
    if payload.data_crc32c != Some(crc32c::crc32c(&data) as i64) {
        return Err("payload checksum mismatch".into());
    }
    Ok(data)
}

/// DELETE removes the secret and all versions immediately and irreversibly.
async fn delete(client: &SecretManagerService, secret_name: &str) -> Res<()> {
    client.delete_secret().set_name(secret_name).send().await?;
    Ok(())
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
    let project = env::var("GOOGLE_CLOUD_PROJECT").map_err(|_| "set GOOGLE_CLOUD_PROJECT")?;
    let id = env::var("SECRET_ID").map_err(|_| "set SECRET_ID")?;
    let client = SecretManagerService::builder().build().await?;

    let v1 = random_value();
    let name = create(&client, &project, &id, &v1).await?;
    println!("created: {name}");
    if !ct_eq(&read(&client, &name).await?, &v1) {
        return Err("read-back after create did not match".into());
    }

    let v2 = random_value();
    let version = add_version(&client, &name, &v2).await?;
    if !ct_eq(&read(&client, &name).await?, &v2) {
        return Err("read-back after update did not match".into());
    }
    println!("updated: {version}");

    delete(&client, &name).await?;
    println!("deleted: {name}");
    Ok(())
}
```

### 9.3 PHP

`composer require google/cloud-secret-manager`. The V1 `Client\SecretManagerServiceClient` takes request objects built with `::build(...)`. `hash('crc32c', …)` is built into PHP 7.4+.

```php
<?php
// Google Cloud Secret Manager CRUD with google/cloud-secret-manager (V1 "Client" surface).
// composer require google/cloud-secret-manager      Authentication: Application Default Credentials.
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use Google\ApiCore\ApiException;
use Google\Cloud\SecretManager\V1\AccessSecretVersionRequest;
use Google\Cloud\SecretManager\V1\AddSecretVersionRequest;
use Google\Cloud\SecretManager\V1\Client\SecretManagerServiceClient;
use Google\Cloud\SecretManager\V1\CreateSecretRequest;
use Google\Cloud\SecretManager\V1\DeleteSecretRequest;
use Google\Cloud\SecretManager\V1\Replication;
use Google\Cloud\SecretManager\V1\Replication\Automatic;
use Google\Cloud\SecretManager\V1\Secret;
use Google\Cloud\SecretManager\V1\SecretPayload;

final class GcpSecretStore
{
    public function __construct(private SecretManagerServiceClient $client) {}

    public function create(string $project, string $secretId, string $value): string
    {
        $secret = (new Secret())
            ->setReplication((new Replication())->setAutomatic(new Automatic()))
            ->setLabels(['app' => 'secrets-crud']);
        try {
            $created = $this->client->createSecret(
                CreateSecretRequest::build("projects/{$project}", $secretId, $secret)
            );
        } catch (ApiException $e) {
            if ($e->getStatus() === 'ALREADY_EXISTS') {
                throw new RuntimeException("secret {$secretId} already exists (create is not an upsert)", 0, $e);
            }
            throw $e;
        }
        $this->addVersion($created->getName(), $value);
        return $created->getName();
    }

    /** Update path: versions are immutable; "latest" moves to the new one. */
    public function addVersion(string $secretName, string $value): string
    {
        $payload = (new SecretPayload())
            ->setData($value)
            ->setDataCrc32C(self::crc32c($value));
        return $this->client->addSecretVersion(AddSecretVersionRequest::build($secretName, $payload))->getName();
    }

    public function read(string $secretName): string
    {
        $resp = $this->client->accessSecretVersion(AccessSecretVersionRequest::build("{$secretName}/versions/latest"));
        $data = $resp->getPayload()->getData();
        if ((int) $resp->getPayload()->getDataCrc32C() !== self::crc32c($data)) {
            throw new RuntimeException('payload checksum mismatch');
        }
        return $data;
    }

    /** Deletes the secret and all versions immediately and irreversibly. */
    public function delete(string $secretName): void
    {
        $this->client->deleteSecret(DeleteSecretRequest::build($secretName));
    }

    private static function crc32c(string $data): int
    {
        return (int) hexdec(hash('crc32c', $data));
    }
}

$project = getenv('GOOGLE_CLOUD_PROJECT') ?: exit("set GOOGLE_CLOUD_PROJECT\n");
$secretId = getenv('SECRET_ID') ?: exit("set SECRET_ID\n");
$store = new GcpSecretStore(new SecretManagerServiceClient());
$random = fn (): string => rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');

$v1 = $random();
$name = $store->create($project, $secretId, $v1);
echo "created: {$name}\n";
hash_equals($v1, $store->read($name)) || exit("read-back after create did not match\n");

$v2 = $random();
$version = $store->addVersion($name, $v2);
hash_equals($v2, $store->read($name)) || exit("read-back after update did not match\n");
echo "updated: {$version}\n";
unset($v1, $v2);

$store->delete($name);
echo "deleted: {$name}\n";
```

### 9.4 C#

`dotnet add package Google.Cloud.SecretManager.V1`. RPC failures surface as `Grpc.Core.RpcException`; the BCL has no CRC32C, so a 256-entry table is included.

```csharp
// Google Cloud Secret Manager CRUD with Google.Cloud.SecretManager.V1.
// dotnet add package Google.Cloud.SecretManager.V1      Authentication: Application Default Credentials.
using System.Security.Cryptography;
using System.Text;
using Google.Cloud.SecretManager.V1;
using Google.Protobuf;
using Grpc.Core;

public sealed class GcpSecretStore(SecretManagerServiceClient client)
{
    public async Task<string> CreateAsync(string project, string secretId, byte[] value, CancellationToken ct)
    {
        var secret = new Secret
        {
            Replication = new Replication { Automatic = new Replication.Types.Automatic() },
            Labels = { ["app"] = "secrets-crud" },
        };
        Secret created;
        try
        {
            created = await client.CreateSecretAsync($"projects/{project}", secretId, secret, ct);
        }
        catch (RpcException ex) when (ex.StatusCode == StatusCode.AlreadyExists)
        {
            throw new InvalidOperationException($"secret {secretId} already exists (create is not an upsert)", ex);
        }
        await AddVersionAsync(created.Name, value, ct);
        return created.Name;
    }

    /// <summary>Update path: versions are immutable; "latest" moves to the new one.</summary>
    public async Task<string> AddVersionAsync(string secretName, byte[] value, CancellationToken ct)
    {
        var payload = new SecretPayload { Data = ByteString.CopyFrom(value), DataCrc32C = Crc32C(value) };
        var version = await client.AddSecretVersionAsync(secretName, payload, ct);
        return version.Name;
    }

    public async Task<byte[]> ReadAsync(string secretName, CancellationToken ct)
    {
        var resp = await client.AccessSecretVersionAsync($"{secretName}/versions/latest", ct);
        var data = resp.Payload.Data.ToByteArray();
        if (!resp.Payload.HasDataCrc32C || resp.Payload.DataCrc32C != Crc32C(data))
            throw new InvalidOperationException("payload checksum mismatch");
        return data;
    }

    /// <summary>Deletes the secret and all versions immediately and irreversibly.</summary>
    public Task DeleteAsync(string secretName, CancellationToken ct) => client.DeleteSecretAsync(secretName, ct);

    private static readonly uint[] Table = Enumerable.Range(0, 256).Select(i =>
    {
        uint c = (uint)i;
        for (int k = 0; k < 8; k++) c = (c & 1) != 0 ? 0x82F63B78u ^ (c >> 1) : c >> 1;
        return c;
    }).ToArray();

    private static long Crc32C(ReadOnlySpan<byte> data)
    {
        uint c = 0xFFFFFFFFu;
        foreach (var b in data) c = Table[(c ^ b) & 0xFF] ^ (c >> 8);
        return c ^ 0xFFFFFFFFu;
    }
}

public static class Program
{
    static byte[] RandomValue() => Encoding.ASCII.GetBytes(
        Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_'));

    public static async Task<int> Main()
    {
        var project = Environment.GetEnvironmentVariable("GOOGLE_CLOUD_PROJECT")
                      ?? throw new InvalidOperationException("set GOOGLE_CLOUD_PROJECT");
        var secretId = Environment.GetEnvironmentVariable("SECRET_ID")
                       ?? throw new InvalidOperationException("set SECRET_ID");
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        var store = new GcpSecretStore(await SecretManagerServiceClient.CreateAsync(cts.Token));

        var v1 = RandomValue();
        var name = await store.CreateAsync(project, secretId, v1, cts.Token);
        Console.WriteLine($"created: {name}");
        var got = await store.ReadAsync(name, cts.Token);
        if (!CryptographicOperations.FixedTimeEquals(v1, got))
            throw new InvalidOperationException("read-back after create did not match");
        CryptographicOperations.ZeroMemory(got);

        var v2 = RandomValue();
        var version = await store.AddVersionAsync(name, v2, cts.Token);
        got = await store.ReadAsync(name, cts.Token);
        if (!CryptographicOperations.FixedTimeEquals(v2, got))
            throw new InvalidOperationException("read-back after update did not match");
        Console.WriteLine($"updated: {version}");
        CryptographicOperations.ZeroMemory(got);
        CryptographicOperations.ZeroMemory(v1);
        CryptographicOperations.ZeroMemory(v2);

        await store.DeleteAsync(name, cts.Token);
        Console.WriteLine($"deleted: {name}");
        return 0;
    }
}
```

### 9.5 Java

Use the libraries BOM:

```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.google.cloud</groupId>
      <artifactId>libraries-bom</artifactId>
      <version>${google.libraries.bom.version}</version> <!-- pin a current release -->
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
<dependencies>
  <dependency>
    <groupId>com.google.cloud</groupId>
    <artifactId>google-cloud-secretmanager</artifactId>
  </dependency>
</dependencies>
```

`java.util.zip.CRC32C` (Java 9+) computes the checksum; gax maps gRPC codes to exceptions such as `AlreadyExistsException`.

```java
// Google Cloud Secret Manager CRUD with google-cloud-secretmanager.
// Maven: com.google.cloud:google-cloud-secretmanager (import com.google.cloud:libraries-bom)
// Authentication: Application Default Credentials.
package example;

import com.google.api.gax.rpc.AlreadyExistsException;
import com.google.cloud.secretmanager.v1.AccessSecretVersionResponse;
import com.google.cloud.secretmanager.v1.ProjectName;
import com.google.cloud.secretmanager.v1.Replication;
import com.google.cloud.secretmanager.v1.Secret;
import com.google.cloud.secretmanager.v1.SecretManagerServiceClient;
import com.google.cloud.secretmanager.v1.SecretName;
import com.google.cloud.secretmanager.v1.SecretPayload;
import com.google.cloud.secretmanager.v1.SecretVersionName;
import com.google.protobuf.ByteString;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;
import java.util.zip.CRC32C;

public final class GcpSecretsCrud {
    private final SecretManagerServiceClient client;

    public GcpSecretsCrud(SecretManagerServiceClient client) {
        this.client = client;
    }

    public SecretName create(String project, String secretId, byte[] value) {
        Secret secret = Secret.newBuilder()
                .setReplication(Replication.newBuilder()
                        .setAutomatic(Replication.Automatic.newBuilder().build()))
                .putLabels("app", "secrets-crud")
                .build();
        Secret created;
        try {
            created = client.createSecret(ProjectName.of(project), secretId, secret);
        } catch (AlreadyExistsException e) {
            throw new IllegalStateException("secret " + secretId + " already exists (create is not an upsert)", e);
        }
        SecretName name = SecretName.parse(created.getName());
        addVersion(name, value);
        return name;
    }

    /** Update path: versions are immutable; "latest" moves to the new one. */
    public String addVersion(SecretName secret, byte[] value) {
        SecretPayload payload = SecretPayload.newBuilder()
                .setData(ByteString.copyFrom(value))
                .setDataCrc32C(crc32c(value))
                .build();
        return client.addSecretVersion(secret, payload).getName();
    }

    public byte[] read(SecretName secret) {
        AccessSecretVersionResponse resp = client.accessSecretVersion(
                SecretVersionName.of(secret.getProject(), secret.getSecret(), "latest"));
        byte[] data = resp.getPayload().getData().toByteArray();
        if (!resp.getPayload().hasDataCrc32C() || resp.getPayload().getDataCrc32C() != crc32c(data)) {
            throw new IllegalStateException("payload checksum mismatch");
        }
        return data;
    }

    /** Deletes the secret and all versions immediately and irreversibly. */
    public void delete(SecretName secret) {
        client.deleteSecret(secret);
    }

    private static long crc32c(byte[] data) {
        CRC32C crc = new CRC32C();
        crc.update(data);
        return crc.getValue();
    }

    private static final SecureRandom RNG = new SecureRandom();

    static byte[] randomValue() {
        byte[] raw = new byte[32];
        RNG.nextBytes(raw);
        byte[] out = Base64.getUrlEncoder().withoutPadding().encode(raw);
        Arrays.fill(raw, (byte) 0);
        return out;
    }

    public static void main(String[] args) throws IOException {
        String project = System.getenv("GOOGLE_CLOUD_PROJECT");
        String secretId = System.getenv("SECRET_ID");
        if (project == null || secretId == null) throw new IllegalArgumentException("set GOOGLE_CLOUD_PROJECT and SECRET_ID");

        try (SecretManagerServiceClient client = SecretManagerServiceClient.create()) {
            GcpSecretsCrud store = new GcpSecretsCrud(client);

            byte[] v1 = randomValue();
            SecretName name = store.create(project, secretId, v1);
            System.out.println("created: " + name);
            byte[] got = store.read(name);
            if (!MessageDigest.isEqual(v1, got)) throw new IllegalStateException("read-back after create failed");
            Arrays.fill(got, (byte) 0);

            byte[] v2 = randomValue();
            String version = store.addVersion(name, v2);
            got = store.read(name);
            if (!MessageDigest.isEqual(v2, got)) throw new IllegalStateException("read-back after update failed");
            System.out.println("updated: " + version);
            Arrays.fill(got, (byte) 0);
            Arrays.fill(v1, (byte) 0);
            Arrays.fill(v2, (byte) 0);

            store.delete(name);
            System.out.println("deleted: " + name);
        }
    }
}
```

### 9.6 Swift

There is no official Google Cloud client for Swift. This program calls the REST API with `URLSession` (ephemeral configuration: no disk cache, no cookies). It obtains a token from the metadata server, or from a file written by a trusted token broker (`GCP_ACCESS_TOKEN_FILE`) when running outside Google Cloud. **Never ship service-account keys inside an iOS/macOS app;** client apps should call your backend, which holds the identity.

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
// Google Cloud Secret Manager CRUD in Swift via the REST API (there is no official Swift client).
// Access token: the GCE/Cloud Run/GKE metadata server, or a file written by a trusted token broker
// (GCP_ACCESS_TOKEN_FILE). Never embed a service-account key in a Swift binary or app bundle.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

enum CrudError: Error { case http(Int, String), integrity, config(String) }

struct GcpSecretStore {
    let base = URL(string: "https://secretmanager.googleapis.com/v1/")!
    let session = URLSession(configuration: .ephemeral) // no on-disk cache or cookies

    // MARK: auth
    func accessToken() async throws -> String {
        if let path = ProcessInfo.processInfo.environment["GCP_ACCESS_TOKEN_FILE"] {
            return try String(contentsOfFile: path, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        var req = URLRequest(url: URL(string:
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token")!)
        req.setValue("Google", forHTTPHeaderField: "Metadata-Flavor")
        let (data, _) = try await session.data(for: req)
        struct Token: Decodable { let access_token: String }
        return try JSONDecoder().decode(Token.self, from: data).access_token
    }

    func call(_ method: String, _ path: String, body: [String: Any]? = nil) async throws -> Data {
        var req = URLRequest(url: URL(string: path, relativeTo: base)!)
        req.httpMethod = method
        req.timeoutInterval = 30
        req.setValue("Bearer \(try await accessToken())", forHTTPHeaderField: "Authorization")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            // Error bodies are google.rpc.Status JSON; they never echo the payload.
            throw CrudError.http(status, String(decoding: data, as: UTF8.self))
        }
        return data
    }

    // MARK: CRUD
    func create(project: String, secretId: String, value: Data) async throws -> String {
        let id = secretId.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? secretId
        do {
            let data = try await call("POST", "projects/\(project)/secrets?secretId=\(id)",
                body: ["replication": ["automatic": [String: Any]()], "labels": ["app": "secrets-crud"]])
            struct Secret: Decodable { let name: String }
            let name = try JSONDecoder().decode(Secret.self, from: data).name
            _ = try await addVersion(secretName: name, value: value)
            return name
        } catch CrudError.http(409, _) {
            throw CrudError.config("secret \(secretId) already exists (create is not an upsert)")
        }
    }

    /// Update path: versions are immutable; "latest" moves to the new one.
    func addVersion(secretName: String, value: Data) async throws -> String {
        let data = try await call("POST", "\(secretName):addVersion", body: [
            "payload": ["data": value.base64EncodedString(), "dataCrc32c": String(crc32c(value))],
        ])
        struct Version: Decodable { let name: String }
        return try JSONDecoder().decode(Version.self, from: data).name
    }

    func read(secretName: String) async throws -> Data {
        let data = try await call("GET", "\(secretName)/versions/latest:access")
        struct Access: Decodable {
            struct Payload: Decodable { let data: String; let dataCrc32c: String? }
            let payload: Payload
        }
        let payload = try JSONDecoder().decode(Access.self, from: data).payload
        guard let bytes = Data(base64Encoded: payload.data),
              payload.dataCrc32c == String(crc32c(bytes)) else { throw CrudError.integrity }
        return bytes
    }

    /// Deletes the secret and all versions immediately and irreversibly.
    func delete(secretName: String) async throws {
        _ = try await call("DELETE", secretName)
    }
}

func crc32c(_ data: Data) -> UInt32 {
    var crc: UInt32 = 0xFFFF_FFFF
    for byte in data {
        crc ^= UInt32(byte)
        for _ in 0..<8 { crc = (crc & 1) != 0 ? (crc >> 1) ^ 0x82F6_3B78 : crc >> 1 }
    }
    return crc ^ 0xFFFF_FFFF
}

func randomValue() -> Data {
    var rng = SystemRandomNumberGenerator()
    let raw = Data((0..<32).map { _ in UInt8.random(in: .min ... .max, using: &rng) })
    return Data(raw.base64EncodedString().utf8)
}

func fixedEquals(_ a: Data, _ b: Data) -> Bool {
    a.count == b.count && zip(a, b).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
}

let env = ProcessInfo.processInfo.environment
guard let project = env["GOOGLE_CLOUD_PROJECT"], let secretId = env["SECRET_ID"] else {
    fatalError("set GOOGLE_CLOUD_PROJECT and SECRET_ID")
}
let store = GcpSecretStore()

let v1 = randomValue()
let name = try await store.create(project: project, secretId: secretId, value: v1)
print("created: \(name)")
guard fixedEquals(v1, try await store.read(secretName: name)) else { fatalError("read-back after create failed") }

let v2 = randomValue()
let version = try await store.addVersion(secretName: name, value: v2)
guard fixedEquals(v2, try await store.read(secretName: name)) else { fatalError("read-back after update failed") }
print("updated: \(version)")

try await store.delete(secretName: name)
print("deleted: \(name)")
```

### 9.7 Python

`pip install google-cloud-secret-manager google-crc32c`. `google.api_core.exceptions` maps gRPC codes to classes such as `AlreadyExists` and `NotFound`.

```python
"""Google Cloud Secret Manager CRUD with google-cloud-secret-manager.

pip install google-cloud-secret-manager google-crc32c
Authentication: Application Default Credentials.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys

import google_crc32c
from google.api_core import exceptions as gexc
from google.cloud import secretmanager


class GcpSecretStore:
    def __init__(self, client: secretmanager.SecretManagerServiceClient | None = None) -> None:
        self.client = client or secretmanager.SecretManagerServiceClient()

    def create(self, project: str, secret_id: str, value: bytes) -> str:
        try:
            secret = self.client.create_secret(
                request={
                    "parent": f"projects/{project}",
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}, "labels": {"app": "secrets-crud"}},
                }
            )
        except gexc.AlreadyExists as exc:
            raise RuntimeError(f"secret {secret_id} already exists (create is not an upsert)") from exc
        self.add_version(secret.name, value)
        return secret.name

    def add_version(self, secret_name: str, value: bytes) -> str:
        """Update path: versions are immutable; `latest` moves to the new one."""
        crc = int(google_crc32c.value(value))
        version = self.client.add_secret_version(
            request={"parent": secret_name, "payload": {"data": value, "data_crc32c": crc}}
        )
        return version.name

    def read(self, secret_name: str) -> bytes:
        resp = self.client.access_secret_version(request={"name": f"{secret_name}/versions/latest"})
        data = resp.payload.data
        if int(google_crc32c.value(data)) != resp.payload.data_crc32c:
            raise RuntimeError("payload checksum mismatch")
        return data

    def delete(self, secret_name: str) -> None:
        """Deletes the secret and all versions immediately and irreversibly."""
        self.client.delete_secret(request={"name": secret_name})


def main() -> int:
    project, secret_id = os.environ.get("GOOGLE_CLOUD_PROJECT"), os.environ.get("SECRET_ID")
    if not project or not secret_id:
        print("set GOOGLE_CLOUD_PROJECT and SECRET_ID", file=sys.stderr)
        return 2
    store = GcpSecretStore()

    v1 = secrets.token_urlsafe(32).encode()
    name = store.create(project, secret_id, v1)
    print(f"created: {name}")
    if not hmac.compare_digest(v1, store.read(name)):
        raise RuntimeError("read-back after create did not match")

    v2 = secrets.token_urlsafe(32).encode()
    version = store.add_version(name, v2)
    if not hmac.compare_digest(v2, store.read(name)):
        raise RuntimeError("read-back after update did not match")
    print(f"updated: {version}")

    store.delete(name)
    print(f"deleted: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

`npm i @google-cloud/secret-manager`. Errors carry a numeric gRPC `code` (6 = `ALREADY_EXISTS`, 5 = `NOT_FOUND`). Node has no built-in CRC32C, so a small table implementation is included (verified against the standard check value `0xE3069283` for `"123456789"`).

```typescript
// Google Cloud Secret Manager CRUD with @google-cloud/secret-manager.
// npm i @google-cloud/secret-manager      Authentication: Application Default Credentials.
import { randomBytes, timingSafeEqual } from "node:crypto";
import { SecretManagerServiceClient } from "@google-cloud/secret-manager";

// CRC32C (Castagnoli) for end-to-end payload integrity checks.
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0x82f63b78 ^ (c >>> 1) : c >>> 1;
    t[i] = c >>> 0;
  }
  return t;
})();
function crc32c(buf: Uint8Array): number {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

export class GcpSecretStore {
  constructor(private readonly client = new SecretManagerServiceClient()) {}

  async create(project: string, secretId: string, value: Buffer): Promise<string> {
    let name: string;
    try {
      const [secret] = await this.client.createSecret({
        parent: `projects/${project}`,
        secretId,
        secret: { replication: { automatic: {} }, labels: { app: "secrets-crud" } },
      });
      name = secret.name ?? "";
    } catch (err) {
      if ((err as { code?: number }).code === 6 /* ALREADY_EXISTS */) {
        throw new Error(`secret ${secretId} already exists (create is not an upsert)`, { cause: err });
      }
      throw err;
    }
    await this.addVersion(name, value);
    return name;
  }

  /** Update path: versions are immutable; `latest` moves to the new one. */
  async addVersion(secretName: string, value: Buffer): Promise<string> {
    const [version] = await this.client.addSecretVersion({
      parent: secretName,
      payload: { data: value, dataCrc32c: crc32c(value) },
    });
    return version.name ?? "";
  }

  async read(secretName: string): Promise<Buffer> {
    const [resp] = await this.client.accessSecretVersion({ name: `${secretName}/versions/latest` });
    const data = Buffer.from(resp.payload?.data ?? new Uint8Array());
    if (Number(resp.payload?.dataCrc32c) !== crc32c(data)) throw new Error("payload checksum mismatch");
    return data;
  }

  /** Deletes the secret and every version immediately and irreversibly. */
  async delete(secretName: string): Promise<void> {
    await this.client.deleteSecret({ name: secretName });
  }
}

const randomValue = (): Buffer => Buffer.from(randomBytes(32).toString("base64url"));
const same = (a: Buffer, b: Buffer): boolean => a.length === b.length && timingSafeEqual(a, b);

async function main(): Promise<void> {
  const project = process.env.GOOGLE_CLOUD_PROJECT, secretId = process.env.SECRET_ID;
  if (!project || !secretId) throw new Error("set GOOGLE_CLOUD_PROJECT and SECRET_ID");
  const store = new GcpSecretStore();

  const v1 = randomValue();
  const name = await store.create(project, secretId, v1);
  console.log(`created: ${name}`);
  if (!same(v1, await store.read(name))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  const version = await store.addVersion(name, v2);
  if (!same(v2, await store.read(name))) throw new Error("read-back after update did not match");
  console.log(`updated: ${version}`);
  v1.fill(0);
  v2.fill(0);

  await store.delete(name);
  console.log(`deleted: ${name}`);
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? `${err.name}: ${err.message}` : "unknown error");
  process.exitCode = 1;
});
```

### 9.9 C++

CMake (with `google-cloud-cpp` installed via vcpkg, Conan, or from source):

```cmake
cmake_minimum_required(VERSION 3.16)
project(secrets_crud CXX)
set(CMAKE_CXX_STANDARD 17)
find_package(google_cloud_cpp_secretmanager REQUIRED)
find_package(OpenSSL REQUIRED)
add_executable(secrets_crud main.cpp)
target_link_libraries(secrets_crud google-cloud-cpp::secretmanager OpenSSL::Crypto)
```

Calls return `StatusOr<T>`; check before dereferencing. Abseil (a dependency of `google-cloud-cpp`) provides `absl::ComputeCrc32c`.

```cpp
// Google Cloud Secret Manager CRUD with google-cloud-cpp (secretmanager_v1).
// CMake: find_package(google_cloud_cpp_secretmanager REQUIRED)
//        target_link_libraries(app google-cloud-cpp::secretmanager)
// Authentication: Application Default Credentials.
#include "google/cloud/secretmanager/v1/secret_manager_client.h"
#include <absl/crc/crc32c.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace sm = ::google::cloud::secretmanager_v1;
namespace smpb = ::google::cloud::secretmanager::v1;

static std::int64_t crc32c(std::string const& data) {
  return static_cast<std::int64_t>(static_cast<std::uint32_t>(absl::ComputeCrc32c(data)));
}

class GcpSecretStore {
 public:
  explicit GcpSecretStore(sm::SecretManagerServiceClient client) : client_(std::move(client)) {}

  std::string create(std::string const& project, std::string const& secret_id, std::string const& value) {
    smpb::Secret secret;
    secret.mutable_replication()->mutable_automatic();
    (*secret.mutable_labels())["app"] = "secrets-crud";
    auto created = client_.CreateSecret("projects/" + project, secret_id, secret);
    if (!created) {
      if (created.status().code() == google::cloud::StatusCode::kAlreadyExists)
        throw std::runtime_error("secret " + secret_id + " already exists (create is not an upsert)");
      throw std::runtime_error("CreateSecret: " + created.status().message());
    }
    add_version(created->name(), value);
    return created->name();
  }

  // Update path: versions are immutable; "latest" moves to the new one.
  std::string add_version(std::string const& secret_name, std::string const& value) {
    smpb::SecretPayload payload;
    payload.set_data(value);
    payload.set_data_crc32c(crc32c(value));
    auto version = client_.AddSecretVersion(secret_name, payload);
    if (!version) throw std::runtime_error("AddSecretVersion: " + version.status().message());
    return version->name();
  }

  std::string read(std::string const& secret_name) {
    auto resp = client_.AccessSecretVersion(secret_name + "/versions/latest");
    if (!resp) throw std::runtime_error("AccessSecretVersion: " + resp.status().message());
    std::string data = resp->payload().data();
    if (!resp->payload().has_data_crc32c() || resp->payload().data_crc32c() != crc32c(data))
      throw std::runtime_error("payload checksum mismatch");
    return data;
  }

  // Deletes the secret and all versions immediately and irreversibly.
  void remove(std::string const& secret_name) {
    auto status = client_.DeleteSecret(secret_name);
    if (!status.ok()) throw std::runtime_error("DeleteSecret: " + status.message());
  }

 private:
  sm::SecretManagerServiceClient client_;
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

int main() try {
  char const* project = std::getenv("GOOGLE_CLOUD_PROJECT");
  char const* secret_id = std::getenv("SECRET_ID");
  if (!project || !secret_id) { std::cerr << "set GOOGLE_CLOUD_PROJECT and SECRET_ID\n"; return 2; }

  GcpSecretStore store(sm::SecretManagerServiceClient(sm::MakeSecretManagerServiceConnection()));

  std::string v1 = random_value();
  std::string name = store.create(project, secret_id, v1);
  std::cout << "created: " << name << "\n";
  std::string got = store.read(name);
  if (!same(v1, got)) throw std::runtime_error("read-back after create failed");

  std::string v2 = random_value();
  std::string version = store.add_version(name, v2);
  got = store.read(name);
  if (!same(v2, got)) throw std::runtime_error("read-back after update failed");
  std::cout << "updated: " << version << "\n";
  wipe(v1); wipe(v2); wipe(got);

  store.remove(name);
  std::cout << "deleted: " << name << "\n";
  return 0;
} catch (std::exception const& e) {
  std::cerr << "error: " << e.what() << "\n";
  return 1;
}
```

### 9.10 C

There is no official C client. This program calls the REST API with libcurl, restricts the API host to HTTPS, encodes the payload as base64 with OpenSSL, sends `dataCrc32c` as a string (int64 values are strings in proto3 JSON), validates the secret ID's character set, and wipes buffers. `SECRET_MANAGER_ENDPOINT` selects a regional or private endpoint.

```c
/*
 * Google Cloud Secret Manager CRUD in C via the REST API (no official C client exists).
 * libcurl + cJSON + OpenSSL.
 *
 *   cc -std=c11 -Wall -Wextra -O2 gcp_secrets_crud.c -o gcp_secrets_crud \
 *      $(pkg-config --cflags --libs libcurl libcjson openssl)
 *
 * Access token: from the metadata server (GCE, GKE Workload Identity, Cloud Run, Cloud Functions),
 * or from a file written by a trusted broker (GCP_ACCESS_TOKEN_FILE). Never embed key files.
 */
#define _POSIX_C_SOURCE 200809L
#include <cjson/cJSON.h>
#include <curl/curl.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { char *data; size_t len; } buf_t;

static size_t on_body(char *p, size_t s, size_t n, void *u) {
    buf_t *b = u; size_t k = s * n;
    char *g = realloc(b->data, b->len + k + 1);
    if (!g) return 0;
    b->data = g; memcpy(b->data + b->len, p, k); b->len += k; b->data[b->len] = '\0';
    return k;
}
static void buf_wipe(buf_t *b) { if (b->data) { OPENSSL_cleanse(b->data, b->len); free(b->data); } b->data = NULL; b->len = 0; }

static uint32_t crc32c(const unsigned char *d, size_t n) {
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++) {
        c ^= d[i];
        for (int k = 0; k < 8; k++) c = (c & 1u) ? (c >> 1) ^ 0x82F63B78u : c >> 1;
    }
    return c ^ 0xFFFFFFFFu;
}

static const char *endpoint(void) {
    const char *e = getenv("SECRET_MANAGER_ENDPOINT");   /* e.g. regional https://secretmanager.<loc>.rep.googleapis.com */
    return e ? e : "https://secretmanager.googleapis.com";
}

/* Perform one HTTP request. Returns HTTP status (0 on transport error); body in *out. */
static long http(const char *method, const char *url, const char *bearer, const char *json, buf_t *out,
                 int metadata) {
    struct curl_slist *h = NULL;
    char auth[4200];
    if (metadata) h = curl_slist_append(h, "Metadata-Flavor: Google");
    if (bearer) { snprintf(auth, sizeof auth, "Authorization: Bearer %s", bearer); h = curl_slist_append(h, auth); }
    if (json) h = curl_slist_append(h, "Content-Type: application/json");
    CURL *c = curl_easy_init();
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_CUSTOMREQUEST, method);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, h);
    if (json) curl_easy_setopt(c, CURLOPT_POSTFIELDS, json);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, out);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 30L);
    if (!metadata) curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "https");
    long status = 0;
    if (curl_easy_perform(c) == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    curl_slist_free_all(h);
    OPENSSL_cleanse(auth, sizeof auth);
    return status;
}

/* Returns a malloc'd access token (wipe + free), or NULL. */
static char *access_token(void) {
    const char *path = getenv("GCP_ACCESS_TOKEN_FILE");
    if (path) {
        FILE *f = fopen(path, "r");
        if (!f) return NULL;
        char tok[4096] = {0};
        size_t n = fread(tok, 1, sizeof tok - 1, f);
        fclose(f);
        while (n && (tok[n - 1] == '\n' || tok[n - 1] == '\r' || tok[n - 1] == ' ')) tok[--n] = '\0';
        char *r = strdup(tok);
        OPENSSL_cleanse(tok, sizeof tok);
        return r;
    }
    buf_t b = {0};
    long st = http("GET", "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                   NULL, NULL, &b, 1);
    char *r = NULL;
    if (st == 200) {
        cJSON *j = cJSON_Parse(b.data);
        const cJSON *t = cJSON_GetObjectItemCaseSensitive(j, "access_token");
        if (cJSON_IsString(t)) { r = strdup(t->valuestring); OPENSSL_cleanse(t->valuestring, strlen(t->valuestring)); }
        cJSON_Delete(j);
    }
    buf_wipe(&b);
    return r;
}

/* Authenticated Secret Manager call; returns parsed JSON (or an empty object for empty bodies). */
static cJSON *sm_call(const char *method, const char *path, cJSON *body, long *status_out) {
    char url[1024];
    snprintf(url, sizeof url, "%s/v1/%s", endpoint(), path);
    char *token = access_token();
    if (!token) { fprintf(stderr, "no access token available\n"); return NULL; }
    char *json = body ? cJSON_PrintUnformatted(body) : NULL;
    buf_t resp = {0};
    long st = http(method, url, token, json, &resp, 0);
    OPENSSL_cleanse(token, strlen(token)); free(token);
    if (json) { OPENSSL_cleanse(json, strlen(json)); cJSON_free(json); }
    if (status_out) *status_out = st;
    cJSON *out = NULL;
    if (st >= 200 && st < 300) out = resp.len ? cJSON_Parse(resp.data) : cJSON_CreateObject();
    else fprintf(stderr, "%s %s: HTTP %ld\n", method, path, st);   /* body is google.rpc.Status; omit */
    buf_wipe(&resp);
    return out;
}

static char *add_version(const char *secret_name, const unsigned char *value, size_t n) {
    unsigned char b64[4 * ((4096 + 2) / 3) + 1];
    if (n > 4096) return NULL;
    EVP_EncodeBlock(b64, value, (int)n);
    char crc[16]; snprintf(crc, sizeof crc, "%u", (unsigned)crc32c(value, n));
    cJSON *body = cJSON_CreateObject();
    cJSON *payload = cJSON_AddObjectToObject(body, "payload");
    cJSON_AddStringToObject(payload, "data", (char *)b64);
    cJSON_AddStringToObject(payload, "dataCrc32c", crc);   /* int64 is a string in proto3 JSON */
    OPENSSL_cleanse(b64, sizeof b64);
    char path[600]; snprintf(path, sizeof path, "%s:addVersion", secret_name);
    cJSON *out = sm_call("POST", path, body, NULL);
    cJSON_Delete(body);
    const cJSON *nm = cJSON_GetObjectItemCaseSensitive(out, "name");
    char *r = cJSON_IsString(nm) ? strdup(nm->valuestring) : NULL;
    cJSON_Delete(out);
    return r;
}

/* CREATE: container + first version. Returns malloc'd "projects/<n>/secrets/<id>" or NULL. */
static char *secret_create(const char *project, const char *secret_id, const unsigned char *v, size_t n) {
    cJSON *body = cJSON_CreateObject();
    cJSON_AddObjectToObject(cJSON_AddObjectToObject(body, "replication"), "automatic");
    cJSON_AddStringToObject(cJSON_AddObjectToObject(body, "labels"), "app", "secrets-crud");
    char path[600]; snprintf(path, sizeof path, "projects/%s/secrets?secretId=%s", project, secret_id);
    long st = 0;
    cJSON *out = sm_call("POST", path, body, &st);
    cJSON_Delete(body);
    if (st == 409) fprintf(stderr, "secret already exists (create is not an upsert)\n");
    const cJSON *nm = cJSON_GetObjectItemCaseSensitive(out, "name");
    char *name = cJSON_IsString(nm) ? strdup(nm->valuestring) : NULL;
    cJSON_Delete(out);
    if (name) {
        char *ver = add_version(name, v, n);
        if (!ver) { free(name); return NULL; }
        free(ver);
    }
    return name;
}

/* READ latest; returns malloc'd bytes (wipe + free) and length, verifying CRC32C. */
static unsigned char *secret_read(const char *secret_name, size_t *len) {
    char path[600]; snprintf(path, sizeof path, "%s/versions/latest:access", secret_name);
    cJSON *out = sm_call("GET", path, NULL, NULL);
    const cJSON *payload = cJSON_GetObjectItemCaseSensitive(out, "payload");
    const cJSON *data = cJSON_GetObjectItemCaseSensitive(payload, "data");
    const cJSON *crc = cJSON_GetObjectItemCaseSensitive(payload, "dataCrc32c");
    unsigned char *r = NULL;
    if (cJSON_IsString(data) && cJSON_IsString(crc)) {
        size_t b64len = strlen(data->valuestring);
        r = malloc(b64len + 1);
        int n = EVP_DecodeBlock(r, (unsigned char *)data->valuestring, (int)b64len);
        if (n >= 0) {
            while (b64len && data->valuestring[b64len - 1] == '=') { n--; b64len--; }  /* drop pad bytes */
            *len = (size_t)n;
            if (strtoul(crc->valuestring, NULL, 10) != crc32c(r, *len)) { OPENSSL_cleanse(r, *len); free(r); r = NULL; }
        } else { free(r); r = NULL; }
        OPENSSL_cleanse(data->valuestring, strlen(data->valuestring));
    }
    cJSON_Delete(out);
    return r;
}

/* DELETE: removes the secret and all versions immediately and irreversibly. */
static int secret_delete(const char *secret_name) {
    cJSON *out = sm_call("DELETE", secret_name, NULL, NULL);
    int ok = out != NULL;
    cJSON_Delete(out);
    return ok ? 0 : -1;
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
    const char *project = getenv("GOOGLE_CLOUD_PROJECT"), *secret_id = getenv("SECRET_ID");
    if (!project || !secret_id) { fprintf(stderr, "set GOOGLE_CLOUD_PROJECT and SECRET_ID\n"); return 2; }
    for (const char *p = secret_id; *p; p++)   /* IDs: letters, digits, '-', '_' (max 255) */
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') || (*p >= '0' && *p <= '9') || *p == '-' || *p == '_')) {
            fprintf(stderr, "invalid SECRET_ID\n"); return 2;
        }
    curl_global_init(CURL_GLOBAL_DEFAULT);
    int rc = 1;
    unsigned char v1[45], v2[45], *got = NULL;
    size_t got_len = 0;
    char *name = NULL, *ver = NULL;

    random_value(v1);
    if (!(name = secret_create(project, secret_id, v1, 44))) goto done;
    printf("created: %s\n", name);
    got = secret_read(name, &got_len);
    if (!same(v1, 44, got, got_len)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    OPENSSL_cleanse(got, got_len); free(got); got = NULL;

    random_value(v2);
    if (!(ver = add_version(name, v2, 44))) goto done;
    got = secret_read(name, &got_len);
    if (!same(v2, 44, got, got_len)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated: %s\n", ver);

    if (secret_delete(name) != 0) goto done;
    printf("deleted: %s\n", name);
    rc = 0;
done:
    if (got) { OPENSSL_cleanse(got, got_len); free(got); }
    OPENSSL_cleanse(v1, sizeof v1); OPENSSL_cleanse(v2, sizeof v2);
    free(name); free(ver);
    curl_global_cleanup();
    return rc;
}
```

## 10. Use secrets in applications

| Mechanism | How the value arrives | Notes |
| --- | --- | --- |
| Direct client call at startup + in-process cache (section 9) | In memory | Google's recommended pattern; refresh on a timer or on auth failure. |
| Cloud Run / Cloud Functions secret references | Env var (resolved at instance start) or mounted volume (re-read on access) | Pin a version number for env vars; volumes with `latest` pick up new versions. |
| GKE: Secret Manager add-on / Secrets Store CSI Driver | Mounted files | Optional sync to Kubernetes Secrets widens exposure; evaluate before enabling. [S04] |
| Config Connector / Terraform | Provisioning only | Values in Terraform state are plaintext; see the engineering guide. |

Rotation-safe consumption:

1. Read once at startup; fail fast on `PERMISSION_DENIED`, `NOT_FOUND`, or `FAILED_PRECONDITION`.
2. Cache with a TTL. With `latest`, refresh on a timer and immediately after a downstream authentication failure (once, then fail).
3. With pinned versions, roll the new version number through deployment; keep the old version enabled until all instances move.
4. Subscribe to the secret's Pub/Sub topic (`SECRET_VERSION_ADD`, `SECRET_ROTATE`, …) to trigger refresh or rotation work instead of polling aggressively.

## 11. Automation and error handling

| gRPC code (HTTP) | Typical cause | Action |
| --- | --- | --- |
| `ALREADY_EXISTS` (409) | Secret ID taken | Read the existing secret; create is not an upsert. |
| `NOT_FOUND` (404) | Wrong project/location/ID, or deleted | Check resource name; regional secrets need the regional endpoint. |
| `PERMISSION_DENIED` (403) | Missing role, VPC-SC perimeter, org policy | Check IAM on the secret, conditions, and perimeter logs. |
| `FAILED_PRECONDITION` (400) | Accessing a disabled/destroyed version; no enabled version for `latest` | Enable a version or add one. |
| `INVALID_ARGUMENT` (400) | Bad ID characters, payload > 64 KiB, CRC32C mismatch | Fix input; never "retry" a checksum mismatch without re-reading the source. |
| `RESOURCE_EXHAUSTED` (429) | Quota exceeded | Cache reads; spread writes; request quota. |
| `UNAVAILABLE`, `DEADLINE_EXCEEDED` | Transient | Client libraries retry idempotent calls; set deadlines. |
| `ABORTED` (409) | `etag` mismatch | Re-read, re-decide, retry deliberately. |

Practices:

- Keep the resource name returned by create; a timed-out create should be followed by `GetSecret` before retrying.
- `AddSecretVersion` is not idempotent: a blind retry after a timeout can create two versions (harmless for value, but it moves `latest` twice and consumes version-add quota). Check the newest version's `createTime` before retrying if that matters.
- Use `etag` on `UpdateSecret`, `DestroySecretVersion`, and `DeleteSecret` in automation.
- Re-read after writes when correctness matters and compare in constant time without logging.
- Plan for thundering herds at deploy/autoscale time against the shared 90,000/min access quota. [S04]

## 12. Optional live CRUD verification

This **performs writes** in the project you choose. Use a sandbox project.

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${PROJECT_ID:?set PROJECT_ID}"
gcloud config get-value account > /dev/null

work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
id="crud-check-$(date -u +%Y%m%dt%H%M%Sz)-$$"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v1"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v2"

gcloud secrets create "$id" --project "$PROJECT_ID" --replication-policy=automatic \
  --data-file="$work/v1" --format='value(name)'
gcloud secrets versions access latest --secret="$id" --project "$PROJECT_ID" --out-file="$work/r1"
cmp -s "$work/r1" "$work/v1"

gcloud secrets versions add "$id" --project "$PROJECT_ID" --data-file="$work/v2" > /dev/null
gcloud secrets versions access latest --secret="$id" --project "$PROJECT_ID" --out-file="$work/r2"
cmp -s "$work/r2" "$work/v2"

gcloud secrets delete "$id" --project "$PROJECT_ID" --quiet
! gcloud secrets describe "$id" --project "$PROJECT_ID" > /dev/null 2>&1
printf 'PASS: create, read, update, and delete completed.\n'
```

It does not test CMEK, user-managed replication, rotation notifications, or regional endpoints.

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| `Could not automatically determine credentials` | No ADC: attach a service account, configure Workload Identity, or run `gcloud auth application-default login` on a workstation. |
| Runs as the wrong identity | `GOOGLE_APPLICATION_CREDENTIALS` overrides the metadata server; unset it in that process. |
| `PERMISSION_DENIED` despite the right role | Role granted on another secret/project; IAM Condition uses project ID instead of number; VPC Service Controls perimeter. |
| `NOT_FOUND` for a regional secret | Use `projects/*/locations/*/secrets/*` and the regional endpoint `secretmanager.<location>.rep.googleapis.com`. |
| `FAILED_PRECONDITION` on access | The version (or every version, for `latest`) is disabled or destroyed. |
| Checksum mismatch | Corruption or a client bug; do not use the value; re-read; report. |
| App sees old value | Cached value, env-var delivery resolved at start, or a pinned version number. |
| Unexpected trailing newline | File created with `echo`; recreate with `printf '%s'`. |
| `RESOURCE_EXHAUSTED` | Uncached reads at startup/autoscale; add caching and jittered startup. |
| Secret visible in logs | Debug logging or app logging config objects; disable, purge, rotate. |

## 14. Accuracy notes and official sources

- **Pinning vs `latest`:** Google's best-practices page recommends pinning version numbers in production; the CRUD programs use `latest` only to verify their own writes. [S04]
- **Delayed destruction** behavior is from the `Secret.version_destroy_ttl` and `SecretVersion.scheduled_destroy_time` field documentation in the published API model; the dedicated how-to page could not be retrieved during verification. [S06]
- **Soft rate limits** per secret (2 QPS for adds on global secrets) are documented as soft-enforced. [S01]
- **Swift and C** use REST because no official client exists; the C program was validated against a mock, the Swift program was not compiled.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [Secret Manager quotas][S01] | Access/read/write quotas, 64 KiB payload, alias limit, per-secret soft limits |
| S02 | [Authentication / ADC][S02] | Credential sources and precedence |
| S03 | [Access control with IAM][S03] | Roles, permissions, conditions |
| S04 | [Best practices][S04] | Least privilege, pinning, disable-before-destroy, audit logs, VPC-SC, file/env guidance |
| S05 | [REST reference: projects.secrets][S05] | create, addVersion, access, delete, etag |
| S06 | [API model: Secret / SecretVersion][S06] | `version_destroy_ttl`, `scheduled_destroy_time`, etag semantics |
| S07 | [Go client][S07] | Go API |
| S08 | [PHP client samples][S08] | Secret ID rules, V1 Client surface |
| S09 | [google-cloud-rust][S09] | Rust client builders |
| S10 | [google-cloud-cpp secretmanager][S10] | C++ client signatures |
| S11 | [google-cloud-dotnet Secret Manager][S11] | .NET overloads |
| S12 | [Node.js client][S12] | TypeScript API |
| S13 | [Rotation notifications][S13] | Pub/Sub topics and event types |

[S01]: https://docs.cloud.google.com/secret-manager/quotas
[S02]: https://cloud.google.com/docs/authentication/application-default-credentials
[S03]: https://docs.cloud.google.com/secret-manager/docs/access-control
[S04]: https://docs.cloud.google.com/secret-manager/docs/best-practices
[S05]: https://cloud.google.com/secret-manager/docs/reference/rest/v1/projects.secrets
[S06]: https://docs.rs/google-cloud-secretmanager-v1/latest/google_cloud_secretmanager_v1/model/struct.Secret.html
[S07]: https://pkg.go.dev/cloud.google.com/go/secretmanager/apiv1
[S08]: https://github.com/googleapis/google-cloud-php/tree/main/SecretManager
[S09]: https://github.com/googleapis/google-cloud-rust
[S10]: https://github.com/googleapis/google-cloud-cpp/tree/main/google/cloud/secretmanager
[S11]: https://github.com/googleapis/google-cloud-dotnet/tree/main/apis/Google.Cloud.SecretManager.V1
[S12]: https://github.com/googleapis/google-cloud-node/tree/main/packages/google-cloud-secretmanager
[S13]: https://cloud.google.com/secret-manager/docs/event-notifications
