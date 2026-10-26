# Bitwarden Secrets Manager: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** Bitwarden Secrets Manager (cloud US: `https://api.bitwarden.com` + `https://identity.bitwarden.com`; cloud EU: `https://api.bitwarden.eu` + `https://identity.bitwarden.eu`; self-hosted: `https://<host>/api` + `https://<host>/identity`). Secret fields are **end-to-end encrypted**: the SDK encrypts and decrypts on the client, and the server stores only ciphertext  
**Primary authentication:** a **machine account access token** (`0.<id>.<client-secret>:<encryption-key>`), which both authenticates the machine account and carries the key that decrypts its organization's secrets  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use Bash and the `bws` CLI; section 10 covers the Password Manager `bw` CLI/`bw serve` alternative)

This guide covers **secrets** in Bitwarden Secrets Manager: key/value/note records owned by an organization, each assigned to at most one **project**, addressed by **UUID**. It covers machine accounts and access tokens, why every client must use an official SDK (or its native core) rather than plain REST, complete CRUD workflows, a full CRUD program in each of ten languages, runtime consumption (`bws run`, Kubernetes operator, GitHub Action), and troubleshooting. Projects administration, the Password Manager vault, and Bitwarden's organization Public API are covered only where they affect secrets work.

Credentials are assumed to be provisioned already. Do not paste an access token into this document, source files, command arguments, or example files.

**Verification boundary:** The Python (`bitwarden-sdk` 2.1.0), TypeScript (`@bitwarden/sdk-napi` 1.0.0, `tsc --strict`), Rust (`bitwarden` 2.1.0, `cargo build`), and Go (`github.com/bitwarden/sdk-go/v2` v2.1.0, `go vet`, cgo) programs, and the C and C++ programs (official `bitwarden_c` FFI, `-Wall -Wextra -Werror`, linked against the `libbitwarden_c.a` shipped in the Go module), were **run end-to-end** against a local, stateful mock of the identity token endpoint and the `/api/secrets` endpoints. The mock reuses the official test fixture from `bitwarden/sdk-sm` (`crates/fake-server`): a fake access token and the matching encrypted payload, so the SDKs performed real client-side encryption and decryption and the mock only ever stored ciphertext. The C#, Java, and PHP programs were checked against the official SDK sources at their release tags (package registries for NuGet, Maven, and Packagist were not reachable from the build environment); Swift was not compiled (no toolchain), but its C shim header was compiled and linked against the same library. No call was made to a real Bitwarden server. Section 12 provides an optional live test.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Authenticate](#2-authenticate)
3. [Data model and addressing](#3-data-model-and-addressing)
4. [Safe secret handling](#4-safe-secret-handling)
5. [Create secrets](#5-create-secrets)
6. [Read secrets](#6-read-secrets)
7. [Update secrets](#7-update-secrets)
8. [Delete and recover](#8-delete-and-recover)
9. [Language implementations](#9-language-implementations)
10. [Use secrets in applications (and the Password Manager alternative)](#10-use-secrets-in-applications-and-the-password-manager-alternative)
11. [Automation and error handling](#11-automation-and-error-handling)
12. [Optional live CRUD verification](#12-optional-live-crud-verification)
13. [Troubleshooting](#13-troubleshooting)
14. [Accuracy notes and official sources](#14-accuracy-notes-and-official-sources)

## 1. Requirements and conventions

| Language | Official client | Transport used here | Verified here |
| --- | --- | --- | --- |
| Go | `github.com/bitwarden/sdk-go/v2` (cgo + bundled static core) | SDK | `go vet`, mock run |
| Rust | `bitwarden` crate (feature `secrets`) | SDK | `cargo build`, mock run |
| PHP | `bitwarden/sdk-secrets` (beta, ext-ffi) | SDK | `php -l`, source check |
| C# | `Bitwarden.Secrets.Sdk` 1.0.0 | SDK | source check |
| Java | `com.bitwarden:sdk-secrets` (beta, JNA) | SDK | source check |
| Swift | none (no Secrets Manager Swift SDK) | official `bitwarden_c` FFI | shim compiled; Swift not compiled |
| Python | `bitwarden-sdk` | SDK | mock run |
| TypeScript | `@bitwarden/sdk-napi` (native addon) | SDK | `tsc --strict`, mock run |
| C++ | beta wrapper in `sdk-sm/languages/cpp` (Boost) | official `bitwarden_c` FFI directly | `-Werror`, mock run |
| C | `bitwarden_c` (the shared Rust core) | FFI | `-Werror`, mock run |

**Why not plain REST:** the server never sees plaintext. Login returns an `encrypted_payload` that only the encryption key inside the access token can open; it yields the organization key, and every `key`, `value`, and `note` is an encrypted string (`2.<iv>|<ciphertext>|<mac>`, AES-256-CBC + HMAC-SHA256). Re-implementing this is possible but is exactly the kind of custom cryptography to avoid. Every official SDK — and the C ABI used here for C, C++, and Swift — runs the same audited Rust core. The core's HTTP client uses the platform certificate verifier and, in release builds, refuses non-HTTPS URLs.

Every program follows the same contract:

- Environment: `BWS_ORGANIZATION_ID`, `BWS_PROJECT_ID` (the project the machine account can write to), `BWS_ACCESS_TOKEN_FILE` (path to a `0600` file holding the access token), `SECRET_KEY_NAME` (for example `CRUD_CHECK`), and optional `BWS_API_URL` / `BWS_IDENTITY_URL` (defaults: US cloud).
- It logs in, **creates** a secret in the project (refusing if a secret with that key already exists, because Bitwarden allows duplicate keys), **reads** it by ID and compares in constant time, **updates** it, reads and compares again, then **deletes** it and checks the per-ID result.
- It prints keys and IDs only.

For CLI snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
bws --version
export BWS_SERVER_URL='https://vault.bitwarden.com'   # EU: https://vault.bitwarden.eu; self-hosted: https://<host>
ORG_ID='REPLACE_WITH_ORGANIZATION_ID'
PROJECT_ID='REPLACE_WITH_PROJECT_ID'
```

## 2. Authenticate

### Machine accounts and access tokens

A **machine account** is a non-human identity in the organization. It is granted access to **projects** (or individual secrets) with **Can read** or **Can read, write**. Each machine account can have several **access tokens**; each is shown once at creation, can have an expiration date, and can be revoked individually. [S02] [S03]

The access token string contains three parts: a token ID, a client secret (used at `POST <identity>/connect/token` with `grant_type=client_credentials`, `scope=api.secrets`), and an **encryption key** that decrypts the organization key returned in `encrypted_payload`. Possession of the token therefore grants both API access and the ability to decrypt everything the machine account can read. Store it like a private key. [S04]

The SDKs refresh the short-lived bearer token automatically. Pass a **state file** path to `login_access_token` to cache the session (bearer token and decrypted keys) across process restarts and reduce identity calls; the file must be protected like the access token (`0600`, never shared between machine accounts).

### Confirm authentication without displaying the token

```bash
# bws reads the token from BWS_ACCESS_TOKEN; scope it to one command instead of exporting it.
BWS_ACCESS_TOKEN="$(cat /secure/path/bws-token)" bws project list -o none && printf 'auth ok\n'
```

Never pass `--access-token` on a command line on shared hosts. Use `-o none` (or redirect) on commands whose output contains values.

### Required permissions

- **Runtime readers:** machine account with **Can read** on exactly the project(s) the workload needs.
- **Writers/provisioners:** a separate machine account with **Can read, write** on the target project. Creating a secret requires write access to the project it is created in.
- Each secret belongs to at most one project; grant by project, not by individual secret, so permissions are reviewable.

## 3. Data model and addressing

- **Organization → project → secret.** Secrets are addressed by **UUID**. The **key** is a display name and is **not unique** — creating the same key twice produces two secrets. Programs must resolve key → ID deliberately and refuse ambiguous matches (section 9 programs do).
- **Fields:** `key`, `value`, `note` (all encrypted client-side), `projectIds` (zero or one project), `creationDate`, `revisionDate`.
- **Environment-variable mapping:** `bws run` injects secrets as environment variables named by key; keys that are not valid POSIX names, or duplicates, need `--uuids-as-keynames` (`BWS_UUIDS_AS_KEYNAMES`).
- **Trash:** a deleted secret moves to **Trash for 30 days**, where an administrator can restore it or delete it permanently. [S01]
- **IDs:** organization and project IDs appear in the web app URLs and `bws project list`.

Inventory without values:

```bash
BWS_ACCESS_TOKEN="$(cat /secure/path/bws-token)" bws secret list "$PROJECT_ID" -o json |
  jq '[.[] | {id, key, projectId}]'
```

(`bws secret list` returns values in its JSON; the `jq` filter must run in the same pipeline and nothing upstream may log the stream.)

## 4. Safe secret handling

- **Command lines:** `bws secret create KEY VALUE PROJECT_ID` and `bws secret edit --value VALUE` take the value as an argument, which lands in shell history and the process table. Use an SDK for writes, or run `bws` only on single-user hosts with history disabled for that command. [S06]
- **Output:** `bws secret get`/`list`/`create`/`edit` print values in every output format except `-o none`. Use `-o none` in CI for writes.
- **Access token = decryption key.** Never log it, never put it in an image, a repository, or a CI variable visible to forks. Rotate (create new token → deploy → revoke old) on any suspicion.
- **State files** contain session material; keep them on encrypted storage with `0600` permissions, one per machine account.
- **Logging:** the SDKs' error messages describe the failure (HTTP status, validation) without values; keep SDK log levels at Warn or higher in production (the Node SDK takes a `LogLevel` in its constructor).
- **Memory:** wipe buffers where possible (`zeroize`, `OPENSSL_cleanse`); the C ABI returns JSON strings that contain values, so wipe them before `free()`.

## 5. Create secrets

SDK: `secrets.create(organizationId, key, value, note, projectIds)` → `SecretResponse {id, organizationId, projectId, key, value, note, creationDate, revisionDate}`. The SDK encrypts `key`, `value`, and `note` and calls `POST /api/organizations/{organizationId}/secrets`. Because keys are not unique, check `secrets.list(organizationId)` for the key first. [S04]

```bash
# Value on the command line: only on a single-user host, history disabled.
BWS_ACCESS_TOKEN="$(cat /secure/path/bws-token)" \
  bws secret create PARTNER_API_TOKEN "$(cat /secure/path/to/api-token.txt)" "$PROJECT_ID" -o none
```

The command substitution still places the value in `bws`'s argument list; prefer the SDK programs in section 9 for anything automated.

## 6. Read secrets

SDK: `secrets.get(id)` → `SecretResponse`; `secrets.getByIds([ids])` for several in one request; `secrets.list(organizationId)` → identifiers (`id`, `key`, `projectIds`), decrypted keys but **no values**; `secrets.sync(organizationId, lastSyncedDate)` returns all accessible secrets only if something changed since `lastSyncedDate` — the efficient way to refresh a cache. [S04]

```bash
# One value to a new private file
BWS_ACCESS_TOKEN="$(cat /secure/path/bws-token)" bws secret get "$SECRET_ID" -o json |
  jq -j .value > ./partner-api-token.secret
```

## 7. Update secrets

SDK: `secrets.update(organizationId, id, key, value, note, projectIds)` replaces **all** fields (PUT semantics) — pass the current key, note, and project when you only mean to change the value. There is no compare-and-swap; if concurrent writers are possible, read `revisionDate` before and after and serialize writers per secret. [S04]

```bash
BWS_ACCESS_TOKEN="$(cat /secure/path/bws-token)" \
  bws secret edit "$SECRET_ID" --value "$(cat /secure/path/new-token.txt)" -o none

BWS_ACCESS_TOKEN="$(cat /secure/path/bws-token)" bws secret get "$SECRET_ID" -o json | jq -j .value |
  cmp -s - <(tr -d '\n' < /secure/path/new-token.txt) && printf 'Secret replacement verified.\n'
```

`bws secret edit` changes only the fields you pass. Storing a new value does not rotate the credential at its source.

## 8. Delete and recover

SDK: `secrets.delete([ids])` → `{data: [{id, error}]}`. It is a bulk operation: **the call succeeds even when individual IDs fail**, so check each entry's `error`. Deleted secrets go to **Trash** for 30 days; restore or permanently delete them in the web app. [S01] [S04]

```bash
# bws prints a count, lists per-ID errors on stderr, and exits non-zero if any ID failed.
BWS_ACCESS_TOKEN="$(cat /secure/path/bws-token)" bws secret delete "$SECRET_ID"
```

Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Expected output for every program (IDs vary):

```text
created: CRUD_CHECK id 3f1c…
updated: CRUD_CHECK
deleted: 3f1c…
```

### 9.1 Go

`go get github.com/bitwarden/sdk-go/v2@v2.1.0`. The module wraps the Rust core through cgo and ships static libraries for Linux, macOS, and Windows (x64/arm64), so `CGO_ENABLED=1` and a C toolchain are required. Call `Close()` to free the native client.

```go
// Bitwarden Secrets Manager CRUD with the official Go SDK (github.com/bitwarden/sdk-go/v2).
// The SDK is a cgo wrapper around the Rust core (static libbitwarden_c shipped in the module), so
// CGO_ENABLED=1 and a C toolchain are required. Auth: a machine-account access token read from a file.
package main

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"fmt"
	"log"
	"os"
	"strings"

	sdk "github.com/bitwarden/sdk-go/v2"
)

type Store struct {
	client  sdk.BitwardenClientInterface
	org     string
	project string
}

func NewStore(apiURL, identityURL, org, project string) (*Store, error) {
	if !strings.HasPrefix(apiURL, "https://") || !strings.HasPrefix(identityURL, "https://") {
		return nil, fmt.Errorf("bitwarden URLs must use https")
	}
	client, err := sdk.NewBitwardenClient(&apiURL, &identityURL)
	if err != nil {
		return nil, err
	}
	return &Store{client: client, org: org, project: project}, nil
}

// Login authenticates; pass a state file path (protected like the token, 0600) to cache the session.
func (s *Store) Login(accessToken string) error { return s.client.AccessTokenLogin(accessToken, nil) }

func (s *Store) Close() { s.client.Close() }

// FindID resolves a key to an ID only if exactly one secret has it (keys are not unique in Bitwarden).
func (s *Store) FindID(key string) (string, error) {
	list, err := s.client.Secrets().List(s.org)
	if err != nil {
		return "", err
	}
	var ids []string
	for _, item := range list.Data {
		if item.Key == key {
			ids = append(ids, item.ID)
		}
	}
	switch len(ids) {
	case 0:
		return "", nil
	case 1:
		return ids[0], nil
	default:
		return "", fmt.Errorf("%d secrets share the key %s; address them by ID", len(ids), key)
	}
}

// Create refuses a key that already exists (Bitwarden would create a duplicate) and returns the new ID.
func (s *Store) Create(key, value string) (string, error) {
	existing, err := s.FindID(key)
	if err != nil {
		return "", err
	}
	if existing != "" {
		return "", fmt.Errorf("a secret with key %s already exists", key)
	}
	secret, err := s.client.Secrets().Create(key, value, "", s.org, []string{s.project})
	if err != nil {
		return "", err
	}
	return secret.ID, nil
}

func (s *Store) Read(id string) (string, error) {
	secret, err := s.client.Secrets().Get(id)
	if err != nil {
		return "", err
	}
	return secret.Value, nil
}

// Update has PUT semantics: key, value, note, and projects are all replaced.
func (s *Store) Update(id, key, value string) error {
	_, err := s.client.Secrets().Update(id, key, value, "", s.org, []string{s.project})
	return err
}

// Delete checks the per-ID errors that bulk delete reports inside a successful response.
func (s *Store) Delete(id string) error {
	out, err := s.client.Secrets().Delete([]string{id})
	if err != nil {
		return err
	}
	for _, r := range out.Data {
		if r.Error != nil {
			return fmt.Errorf("delete failed for %s: %s", r.ID, *r.Error)
		}
	}
	return nil
}

func randomValue() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		log.Fatal("csprng: ", err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func equal(a, b string) bool { return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1 }

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func main() {
	key, org, project := os.Getenv("SECRET_KEY_NAME"), os.Getenv("BWS_ORGANIZATION_ID"), os.Getenv("BWS_PROJECT_ID")
	if key == "" || org == "" || project == "" {
		log.Fatal("set SECRET_KEY_NAME, BWS_ORGANIZATION_ID, BWS_PROJECT_ID, BWS_ACCESS_TOKEN_FILE")
	}
	raw, err := os.ReadFile(os.Getenv("BWS_ACCESS_TOKEN_FILE"))
	if err != nil {
		log.Fatal("read access token file: ", err)
	}
	store, err := NewStore(getenv("BWS_API_URL", "https://api.bitwarden.com"),
		getenv("BWS_IDENTITY_URL", "https://identity.bitwarden.com"), org, project)
	if err != nil {
		log.Fatal(err)
	}
	defer store.Close()
	err = store.Login(strings.TrimSpace(string(raw)))
	clear(raw)
	if err != nil {
		log.Fatal("login: ", err)
	}

	v1 := randomValue()
	id, err := store.Create(key, v1)
	if err != nil {
		log.Fatal("create: ", err)
	}
	fmt.Printf("created: %s id %s\n", key, id)
	if got, err := store.Read(id); err != nil || !equal(got, v1) {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	if err := store.Update(id, key, v2); err != nil {
		log.Fatal("update: ", err)
	}
	if got, err := store.Read(id); err != nil || !equal(got, v2) {
		log.Fatal("read-back after update failed: ", err)
	}
	fmt.Println("updated:", key)

	if err := store.Delete(id); err != nil {
		log.Fatal("delete: ", err)
	}
	fmt.Println("deleted:", id)
}
```

### 9.2 Rust

`Cargo.toml`:

```toml
[package]
name = "bitwarden-sm-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
bitwarden = { version = "2.1.0", features = ["secrets"] }
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
uuid = "1"
getrandom = "0.3"
base64 = "0.22"
subtle = "2"
zeroize = "1"
```

```rust
//! Bitwarden Secrets Manager CRUD with the official Rust SDK (`bitwarden` crate, feature "secrets").
//! Auth: a machine-account access token read from BWS_ACCESS_TOKEN_FILE. Secret fields are encrypted and
//! decrypted client-side with the key embedded in the access token.
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use bitwarden::secrets_manager::{
    secrets::{
        SecretCreateRequest, SecretGetRequest, SecretIdentifiersRequest, SecretPutRequest, SecretsDeleteRequest,
    },
    AccessTokenLoginRequest, ClientSettings, DeviceType, SecretsManagerClient,
};
use std::{env, error::Error};
use subtle::ConstantTimeEq;
use uuid::Uuid;
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

struct BitwardenStore {
    client: SecretsManagerClient,
    org: Uuid,
    project: Uuid,
}

impl BitwardenStore {
    fn new(api_url: String, identity_url: String, org: Uuid, project: Uuid) -> Res<Self> {
        // Release builds of the SDK refuse non-HTTPS URLs; enforce it here for debug builds too.
        if !api_url.starts_with("https://") || !identity_url.starts_with("https://") {
            return Err("Bitwarden URLs must use https".into());
        }
        let settings = ClientSettings {
            api_url,
            identity_url,
            user_agent: "secrets-crud".into(),
            device_type: DeviceType::SDK,
            ..Default::default()
        };
        Ok(Self { client: SecretsManagerClient::new(Some(settings)), org, project })
    }

    /// `state_file` (optional) caches the session across restarts; protect it like the token (0600).
    async fn login(&self, access_token: &str) -> Res<()> {
        let req = AccessTokenLoginRequest { access_token: access_token.to_string(), state_file: None };
        self.client.auth().login_access_token(&req).await?;
        Ok(())
    }

    /// Keys are not unique in Bitwarden; resolve a key to an ID only if exactly one secret has it.
    async fn find_id(&self, key: &str) -> Res<Option<Uuid>> {
        let list = self.client.secrets().list(&SecretIdentifiersRequest { organization_id: self.org }).await?;
        let ids: Vec<Uuid> = list.data.iter().filter(|s| s.key == key).map(|s| s.id).collect();
        match ids.len() {
            0 => Ok(None),
            1 => Ok(Some(ids[0])),
            n => Err(format!("{n} secrets share the key {key}; address them by ID").into()),
        }
    }

    /// Bitwarden allows duplicate keys, so refuse to create one that already exists. Returns the new ID.
    async fn create(&self, key: &str, value: &str) -> Res<Uuid> {
        if self.find_id(key).await?.is_some() {
            return Err(format!("a secret with key {key} already exists").into());
        }
        let req = SecretCreateRequest {
            organization_id: self.org,
            key: key.into(),
            value: value.into(),
            note: String::new(),
            project_ids: Some(vec![self.project]),
        };
        Ok(self.client.secrets().create(&req).await?.id)
    }

    async fn read(&self, id: Uuid) -> Res<Zeroizing<String>> {
        let secret = self.client.secrets().get(&SecretGetRequest { id }).await?;
        Ok(Zeroizing::new(secret.value))
    }

    /// PUT semantics: key, value, note, and projects are all replaced.
    async fn update(&self, id: Uuid, key: &str, value: &str) -> Res<()> {
        let req = SecretPutRequest {
            id,
            organization_id: self.org,
            key: key.into(),
            value: value.into(),
            note: String::new(),
            project_ids: Some(vec![self.project]),
        };
        self.client.secrets().update(&req).await?;
        Ok(())
    }

    /// Bulk delete reports per-ID errors inside a successful response; check them.
    async fn delete(&self, id: Uuid) -> Res<()> {
        let out = self.client.secrets().delete(SecretsDeleteRequest { ids: vec![id] }).await?;
        if let Some(failed) = out.data.iter().find(|r| r.error.is_some()) {
            return Err(format!("delete failed for {}: {}", failed.id, failed.error.as_deref().unwrap_or("")).into());
        }
        Ok(())
    }
}

fn random_value() -> Res<Zeroizing<String>> {
    let mut raw = Zeroizing::new([0u8; 32]);
    getrandom::fill(raw.as_mut()).map_err(|e| format!("csprng: {e}"))?;
    Ok(Zeroizing::new(URL_SAFE_NO_PAD.encode(raw.as_ref())))
}

fn same(a: &str, b: &str) -> bool {
    a.len() == b.len() && bool::from(a.as_bytes().ct_eq(b.as_bytes()))
}

fn need(k: &str) -> Res<String> {
    env::var(k).map_err(|_| format!("set {k}").into())
}

#[tokio::main]
async fn main() -> Res<()> {
    let key = need("SECRET_KEY_NAME")?;
    let org: Uuid = need("BWS_ORGANIZATION_ID")?.parse()?;
    let project: Uuid = need("BWS_PROJECT_ID")?.parse()?;
    let token = Zeroizing::new(std::fs::read_to_string(need("BWS_ACCESS_TOKEN_FILE")?)?.trim().to_string());
    let store = BitwardenStore::new(
        env::var("BWS_API_URL").unwrap_or_else(|_| "https://api.bitwarden.com".into()),
        env::var("BWS_IDENTITY_URL").unwrap_or_else(|_| "https://identity.bitwarden.com".into()),
        org,
        project,
    )?;
    store.login(&token).await?;
    drop(token);

    let v1 = random_value()?;
    let id = store.create(&key, &v1).await?;
    println!("created: {key} id {id}");
    if !same(&v1, &store.read(id).await?) {
        return Err("read-back after create did not match".into());
    }

    let v2 = random_value()?;
    store.update(id, &key, &v2).await?;
    if !same(&v2, &store.read(id).await?) {
        return Err("read-back after update did not match".into());
    }
    println!("updated: {key}");

    store.delete(id).await?;
    println!("deleted: {id}");
    Ok(())
}
```

### 9.3 PHP

`composer require bitwarden/sdk-secrets` (beta). Requires `ext-ffi` and the `bitwarden_c` shared library for your platform in the package's `src/lib/<os-arch>/` directory (see the package's INSTALL notes). Methods return `stdClass` objects decoded from the core's JSON.

```php
<?php
// Bitwarden Secrets Manager CRUD with the official PHP SDK (composer require bitwarden/sdk-secrets; beta).
// Requires ext-ffi and the bitwarden_c shared library for your platform in the package's src/lib/<os-arch>/
// directory (see the package's INSTALL.md). Auth: a machine-account access token read from a file.
declare(strict_types=1);

require_once __DIR__ . '/vendor/autoload.php';

use Bitwarden\Sdk\BitwardenClient;
use Bitwarden\Sdk\BitwardenSettings;

final class BitwardenStore
{
    private BitwardenClient $client;

    public function __construct(string $apiUrl, string $identityUrl, private string $org, private string $project)
    {
        if (!str_starts_with($apiUrl, 'https://') || !str_starts_with($identityUrl, 'https://')) {
            throw new InvalidArgumentException('Bitwarden URLs must use https');
        }
        $this->client = new BitwardenClient(new BitwardenSettings($apiUrl, $identityUrl));
    }

    /** $stateFile (optional) caches the session across runs; protect it like the token (0600). */
    public function login(#[\SensitiveParameter] string $accessToken, ?string $stateFile = null): void
    {
        $this->client->auth->login_access_token($accessToken, $stateFile);
    }

    /** Keys are not unique in Bitwarden; resolve a key to an ID only if exactly one secret has it. */
    public function findId(string $key): ?string
    {
        $ids = array_values(array_map(fn($s) => $s->id,
            array_filter($this->client->secrets->list($this->org)->data, fn($s) => $s->key === $key)));
        if (count($ids) > 1) {
            throw new RuntimeException(count($ids) . " secrets share the key $key; address them by ID");
        }
        return $ids[0] ?? null;
    }

    /** Bitwarden allows duplicate keys, so refuse to create one that already exists. Returns the new ID. */
    public function create(string $key, #[\SensitiveParameter] string $value): string
    {
        if ($this->findId($key) !== null) {
            throw new RuntimeException("a secret with key $key already exists");
        }
        return $this->client->secrets->create($this->org, $key, $value, '', [$this->project])->id;
    }

    public function read(string $id): string
    {
        return $this->client->secrets->get($id)->value;
    }

    /** PUT semantics: key, value, note, and projects are all replaced. */
    public function update(string $id, string $key, #[\SensitiveParameter] string $value): void
    {
        $this->client->secrets->update($this->org, $id, $key, $value, '', [$this->project]);
    }

    /** Bulk delete reports per-ID errors inside a successful response; check them. */
    public function delete(string $id): void
    {
        foreach ($this->client->secrets->delete([$id])->data as $r) {
            if (!empty($r->error)) {
                throw new RuntimeException("delete failed for {$r->id}: {$r->error}");
            }
        }
    }
}

function random_value(): string
{
    return rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');
}

function env_or_fail(string $k): string
{
    $v = getenv($k);
    if ($v === false || $v === '') {
        fwrite(STDERR, "set $k\n");
        exit(2);
    }
    return $v;
}

$key = env_or_fail('SECRET_KEY_NAME');
try {
    $store = new BitwardenStore(
        getenv('BWS_API_URL') ?: 'https://api.bitwarden.com',
        getenv('BWS_IDENTITY_URL') ?: 'https://identity.bitwarden.com',
        env_or_fail('BWS_ORGANIZATION_ID'),
        env_or_fail('BWS_PROJECT_ID'),
    );
    $store->login(trim((string)file_get_contents(env_or_fail('BWS_ACCESS_TOKEN_FILE'))));

    $v1 = random_value();
    $id = $store->create($key, $v1);
    echo "created: $key id $id\n";
    if (!hash_equals($v1, $store->read($id))) {
        throw new RuntimeException('read-back after create did not match');
    }

    $v2 = random_value();
    $store->update($id, $key, $v2);
    if (!hash_equals($v2, $store->read($id))) {
        throw new RuntimeException('read-back after update did not match');
    }
    echo "updated: $key\n";

    $store->delete($id);
    echo "deleted: $id\n";
} catch (Throwable $e) {
    fwrite(STDERR, get_class($e) . ': ' . $e->getMessage() . "\n"); // SDK messages carry no values
    exit(1);
} finally {
    unset($v1, $v2);
}
```

### 9.4 C#

`dotnet add package Bitwarden.Secrets.Sdk --version 1.0.0` (native libraries included). 1.0.0 exposes synchronous methods; the `main` branch of `sdk-sm` has moved to `*Async` variants, so check the version you install. Errors are `BitwardenException` / `BitwardenAuthException`.

```csharp
// Bitwarden Secrets Manager CRUD with the official .NET SDK (dotnet add package Bitwarden.Secrets.Sdk --version 1.0.0).
// The package wraps the Rust core (bitwarden_c) and ships native libraries for common platforms.
// Version 1.0.0 exposes synchronous methods; the sdk-sm main branch has moved to *Async variants.
// Auth: a machine-account access token read from BWS_ACCESS_TOKEN_FILE.
using System.Security.Cryptography;
using System.Text;
using Bitwarden.Sdk;

public sealed class BitwardenStore : IDisposable
{
    private readonly BitwardenClient _client;
    private readonly Guid _org, _project;

    public BitwardenStore(string apiUrl, string identityUrl, Guid org, Guid project)
    {
        if (!apiUrl.StartsWith("https://", StringComparison.Ordinal) || !identityUrl.StartsWith("https://", StringComparison.Ordinal))
            throw new ArgumentException("Bitwarden URLs must use https");
        _client = new BitwardenClient(new BitwardenSettings { ApiUrl = apiUrl, IdentityUrl = identityUrl });
        (_org, _project) = (org, project);
    }

    /// <summary>stateFile (optional) caches the session across restarts; protect it like the token (0600).</summary>
    public void Login(string accessToken, string stateFile = "") => _client.Auth.LoginAccessToken(accessToken, stateFile);

    /// <summary>Keys are not unique in Bitwarden; resolve a key to an ID only if exactly one secret has it.</summary>
    public Guid? FindId(string key)
    {
        var ids = _client.Secrets.List(_org).Data.Where(s => s.Key == key).Select(s => s.Id).ToArray();
        if (ids.Length > 1) throw new InvalidOperationException($"{ids.Length} secrets share the key {key}; address them by ID");
        return ids.Length == 1 ? ids[0] : null;
    }

    /// <summary>Bitwarden allows duplicate keys, so refuse to create one that already exists.</summary>
    public Guid Create(string key, string value)
    {
        if (FindId(key) is not null) throw new InvalidOperationException($"a secret with key {key} already exists");
        return _client.Secrets.Create(_org, key, value, "", new[] { _project }).Id;
    }

    public string Read(Guid id) => _client.Secrets.Get(id).Value;

    /// <summary>PUT semantics: key, value, note, and projects are all replaced.</summary>
    public void Update(Guid id, string key, string value) =>
        _client.Secrets.Update(_org, id, key, value, "", new[] { _project });

    /// <summary>Bulk delete reports per-ID errors inside a successful response; check them.</summary>
    public void Delete(Guid id)
    {
        var failed = _client.Secrets.Delete(new[] { id }).Data.FirstOrDefault(r => !string.IsNullOrEmpty(r.Error));
        if (failed is not null) throw new InvalidOperationException($"delete failed for {failed.Id}: {failed.Error}");
    }

    public void Dispose() => _client.Dispose();
}

public static class Program
{
    private static string Need(string k) =>
        Environment.GetEnvironmentVariable(k) is { Length: > 0 } v ? v : throw new InvalidOperationException($"set {k}");

    private static string Env(string k, string def) => Environment.GetEnvironmentVariable(k) is { Length: > 0 } v ? v : def;

    private static string RandomValue() =>
        Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private static bool Same(string a, string b) =>
        CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(a), Encoding.UTF8.GetBytes(b));

    public static int Main()
    {
        try
        {
            var key = Need("SECRET_KEY_NAME");
            using var store = new BitwardenStore(Env("BWS_API_URL", "https://api.bitwarden.com"),
                Env("BWS_IDENTITY_URL", "https://identity.bitwarden.com"),
                Guid.Parse(Need("BWS_ORGANIZATION_ID")), Guid.Parse(Need("BWS_PROJECT_ID")));
            store.Login(File.ReadAllText(Need("BWS_ACCESS_TOKEN_FILE")).Trim());

            var v1 = RandomValue();
            var id = store.Create(key, v1);
            Console.WriteLine($"created: {key} id {id}");
            if (!Same(v1, store.Read(id))) throw new InvalidOperationException("read-back after create did not match");

            var v2 = RandomValue();
            store.Update(id, key, v2);
            if (!Same(v2, store.Read(id))) throw new InvalidOperationException("read-back after update did not match");
            Console.WriteLine($"updated: {key}");

            store.Delete(id);
            Console.WriteLine($"deleted: {id}");
            return 0;
        }
        catch (Exception e)   // BitwardenException / BitwardenAuthException carry the SDK error text, not values
        {
            Console.Error.WriteLine($"{e.GetType().Name}: {e.Message}");
            return 1;
        }
    }
}
```

### 9.5 Java

`com.bitwarden:sdk-secrets` (beta; JNA loads the bundled native library). Generated schema getters use `getID()`. Errors are `BitwardenClientException`.

```java
// Bitwarden Secrets Manager CRUD with the official Java SDK (com.bitwarden:sdk-secrets; beta; JNA + bundled
// native bitwarden_c). Auth: a machine-account access token read from BWS_ACCESS_TOKEN_FILE.
package example;

import com.bitwarden.sdk.BitwardenClient;
import com.bitwarden.sdk.BitwardenSettings;
import com.bitwarden.sdk.schema.SecretDeleteResponse;
import com.bitwarden.sdk.schema.SecretIdentifierResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;
import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

public final class BitwardenCrud implements AutoCloseable {
    private final BitwardenClient client;
    private final UUID org;
    private final UUID project;

    BitwardenCrud(String apiUrl, String identityUrl, UUID org, UUID project) {
        if (!apiUrl.startsWith("https://") || !identityUrl.startsWith("https://")) {
            throw new IllegalArgumentException("Bitwarden URLs must use https");
        }
        this.client = new BitwardenClient(new BitwardenSettings(apiUrl, identityUrl));
        this.org = org;
        this.project = project;
    }

    /** stateFile (may be null) caches the session across restarts; protect it like the token (0600). */
    void login(String accessToken, String stateFile) {
        client.auth().loginAccessToken(accessToken, stateFile);
    }

    /** Keys are not unique in Bitwarden; resolve a key to an ID only if exactly one secret has it. */
    UUID findId(String key) {
        List<UUID> ids = Arrays.stream(client.secrets().list(org).getData())
                .filter(s -> key.equals(s.getKey()))
                .map(SecretIdentifierResponse::getID)
                .collect(Collectors.toList());
        if (ids.size() > 1) throw new IllegalStateException(ids.size() + " secrets share the key " + key);
        return ids.isEmpty() ? null : ids.get(0);
    }

    /** Bitwarden allows duplicate keys, so refuse to create one that already exists. Returns the new ID. */
    UUID create(String key, String value) {
        if (findId(key) != null) throw new IllegalStateException("a secret with key " + key + " already exists");
        return client.secrets().create(org, key, value, "", new UUID[] {project}).getID();
    }

    String read(UUID id) {
        return client.secrets().get(id).getValue();
    }

    /** PUT semantics: key, value, note, and projects are all replaced. */
    void update(UUID id, String key, String value) {
        client.secrets().update(org, id, key, value, "", new UUID[] {project});
    }

    /** Bulk delete reports per-ID errors inside a successful response; check them. */
    void delete(UUID id) {
        for (SecretDeleteResponse r : client.secrets().delete(new UUID[] {id}).getData()) {
            if (r.getError() != null && !r.getError().isEmpty()) {
                throw new IllegalStateException("delete failed for " + r.getID() + ": " + r.getError());
            }
        }
    }

    @Override
    public void close() {
        client.close();
    }

    private static final SecureRandom RNG = new SecureRandom();

    static String randomValue() {
        byte[] b = new byte[32];
        RNG.nextBytes(b);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(b);
    }

    static boolean same(String a, String b) {
        return MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }

    private static String need(String k) {
        String v = System.getenv(k);
        if (v == null || v.isEmpty()) throw new IllegalStateException("set " + k);
        return v;
    }

    public static void main(String[] args) {
        String key = need("SECRET_KEY_NAME");
        try (BitwardenCrud store = new BitwardenCrud(
                System.getenv().getOrDefault("BWS_API_URL", "https://api.bitwarden.com"),
                System.getenv().getOrDefault("BWS_IDENTITY_URL", "https://identity.bitwarden.com"),
                UUID.fromString(need("BWS_ORGANIZATION_ID")), UUID.fromString(need("BWS_PROJECT_ID")))) {
            store.login(Files.readString(Path.of(need("BWS_ACCESS_TOKEN_FILE"))).strip(), null);

            String v1 = randomValue();
            UUID id = store.create(key, v1);
            System.out.println("created: " + key + " id " + id);
            if (!same(v1, store.read(id))) throw new IllegalStateException("read-back after create did not match");

            String v2 = randomValue();
            store.update(id, key, v2);
            if (!same(v2, store.read(id))) throw new IllegalStateException("read-back after update did not match");
            System.out.println("updated: " + key);

            store.delete(id);
            System.out.println("deleted: " + id);
        } catch (Exception e) {
            // BitwardenClientException carries the SDK error text, not values
            System.err.println(e.getClass().getSimpleName() + ": " + e.getMessage());
            System.exit(1);
        }
    }
}
```

### 9.6 Swift

No official Secrets Manager SDK exists for Swift; this program calls the same `bitwarden_c` core that the Go, PHP, Java, and C# SDKs wrap, through a system-library target. A tiny C header gives the exports unambiguous names, because a C function called `init` collides with Swift's initializer keyword. Server-side only.

`Package.swift`, `Sources/CBitwarden/module.modulemap`, and `Sources/CBitwarden/bitwarden_c.h`:

```swift
// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SecretsCrud",
    platforms: [.macOS(.v13)],
    targets: [
        // The official bitwarden_c library (Rust core of every Bitwarden SM SDK). Point the linker at it, e.g.
        // swift build -Xlinker -L/path/to/lib   (libbitwarden_c.a / .so / .dylib)
        .systemLibrary(name: "CBitwarden", path: "Sources/CBitwarden"),
        .executableTarget(name: "SecretsCrud", dependencies: ["CBitwarden"]),
    ]
)
```

```text
module CBitwarden [system] {
    header "bitwarden_c.h"
    link "bitwarden_c"
    export *
}
```

```c
/* Exports of the official bitwarden_c library (bitwarden/sdk-sm, crates/bitwarden-c/src/c.rs). */
#include <stdlib.h>
void *init(const char *client_settings_json);
char *run_command(const char *command_json, void *client);
void free_mem(void *client);

/* A C function named "init" collides with Swift's initializer keyword; wrap the three exports with unambiguous names. */
static inline void *bw_init(const char *settings) { return init(settings); }
static inline char *bw_run_command(const char *command, void *client) { return run_command(command, client); }
static inline void bw_free_mem(void *client) { free_mem(client); }
```

```swift
// Bitwarden Secrets Manager CRUD in Swift through the official bitwarden_c FFI (there is no official Swift
// Secrets Manager SDK; bitwarden/sdk-swift serves the Password Manager apps). Commands and results are JSON.
// Auth: a machine-account access token read from BWS_ACCESS_TOKEN_FILE. Server-side use only.
import CBitwarden
import Foundation
#if canImport(Security)
import Security
#endif

enum BitwardenError: Error, CustomStringConvertible {
    case sdk(op: String, message: String)   // SDK error text (HTTP status, validation), never values
    case config(String)
    var description: String {
        switch self {
        case let .sdk(op, message): return "\(op) failed: \(message)"
        case let .config(m): return m
        }
    }
}

final class BitwardenStore {
    private let client: UnsafeMutableRawPointer
    private let org: String, project: String

    init(apiURL: String, identityURL: String, organizationID: String, projectID: String) throws {
        guard apiURL.hasPrefix("https://"), identityURL.hasPrefix("https://") else {
            throw BitwardenError.config("Bitwarden URLs must use https")
        }
        let settings: [String: Any] = ["apiUrl": apiURL, "identityUrl": identityURL, "deviceType": "SDK",
                                       "userAgent": "secrets-crud-swift"]
        let json = String(data: try JSONSerialization.data(withJSONObject: settings), encoding: .utf8)!
        guard let ptr = bw_init(json) else { throw BitwardenError.config("bitwarden_c init failed") }
        client = ptr
        org = organizationID
        project = projectID
    }

    deinit { bw_free_mem(client) }

    /// Runs one command; returns the "data" member of a successful response.
    @discardableResult
    private func run(_ op: String, _ command: [String: Any]) throws -> Any? {
        let json = String(data: try JSONSerialization.data(withJSONObject: command), encoding: .utf8)!
        guard let raw = bw_run_command(json, client) else { throw BitwardenError.sdk(op: op, message: "no response") }
        let data = Data(bytes: raw, count: strlen(raw))
        memset(raw, 0, strlen(raw))
        free(raw)   // the library allocates with the system allocator (the Go SDK also free()s it)
        guard let resp = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BitwardenError.sdk(op: op, message: "unparseable response")
        }
        guard resp["success"] as? Bool == true else {
            throw BitwardenError.sdk(op: op, message: resp["errorMessage"] as? String ?? "unknown error")
        }
        return resp["data"]
    }

    private func secrets(_ verb: String, _ args: [String: Any]) -> [String: Any] { ["secrets": [verb: args]] }

    private func writeArgs(id: String?, key: String, value: String) -> [String: Any] {
        var a: [String: Any] = ["organizationId": org, "key": key, "value": value, "note": "", "projectIds": [project]]
        if let id { a["id"] = id }
        return a
    }

    func login(accessToken: String) throws {
        try run("login", ["loginAccessToken": ["accessToken": accessToken]])
    }

    /// Keys are not unique in Bitwarden; resolve a key to an ID only if exactly one secret has it.
    func findID(_ key: String) throws -> String? {
        let data = try run("list", secrets("list", ["organizationId": org])) as? [String: Any]
        let items = data?["data"] as? [[String: Any]] ?? []
        let ids = items.filter { $0["key"] as? String == key }.compactMap { $0["id"] as? String }
        guard ids.count <= 1 else { throw BitwardenError.config("\(ids.count) secrets share the key \(key)") }
        return ids.first
    }

    /// Bitwarden allows duplicate keys, so refuse to create one that already exists. Returns the new ID.
    func create(_ key: String, _ value: String) throws -> String {
        guard try findID(key) == nil else { throw BitwardenError.config("a secret with key \(key) already exists") }
        let data = try run("create", secrets("create", writeArgs(id: nil, key: key, value: value))) as? [String: Any]
        guard let id = data?["id"] as? String else { throw BitwardenError.config("create: no id in response") }
        return id
    }

    func read(_ id: String) throws -> String {
        let data = try run("get", secrets("get", ["id": id])) as? [String: Any]
        guard let value = data?["value"] as? String else { throw BitwardenError.config("get: no value") }
        return value
    }

    /// PUT semantics: key, value, note, and projects are all replaced.
    func update(_ id: String, _ key: String, _ value: String) throws {
        try run("update", secrets("update", writeArgs(id: id, key: key, value: value)))
    }

    /// Bulk delete reports per-ID errors inside a successful response; check them.
    func delete(_ id: String) throws {
        let data = try run("delete", secrets("delete", ["ids": [id]])) as? [String: Any]
        for r in data?["data"] as? [[String: Any]] ?? [] {
            if let e = r["error"] as? String, !e.isEmpty { throw BitwardenError.sdk(op: "delete", message: e) }
        }
    }
}

func randomValue() throws -> String {
    var bytes = [UInt8](repeating: 0, count: 32)
    #if canImport(Security)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
        throw BitwardenError.config("csprng failure")
    }
    #else
    var rng = SystemRandomNumberGenerator()   // getrandom(2) on Linux: cryptographically secure
    for i in bytes.indices { bytes[i] = rng.next() }
    #endif
    defer { for i in bytes.indices { bytes[i] = 0 } }
    return Data(bytes).base64EncodedString()
        .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

/// Constant-time comparison (no early exit on the first differing byte).
func same(_ a: String, _ b: String) -> Bool {
    let x = Array(a.utf8), y = Array(b.utf8)
    guard x.count == y.count else { return false }
    var diff: UInt8 = 0
    for i in x.indices { diff |= x[i] ^ y[i] }
    return diff == 0
}

func need(_ k: String) throws -> String {
    guard let v = ProcessInfo.processInfo.environment[k], !v.isEmpty else { throw BitwardenError.config("set \(k)") }
    return v
}

do {
    let env = ProcessInfo.processInfo.environment
    let key = try need("SECRET_KEY_NAME")
    let store = try BitwardenStore(apiURL: env["BWS_API_URL"] ?? "https://api.bitwarden.com",
                                   identityURL: env["BWS_IDENTITY_URL"] ?? "https://identity.bitwarden.com",
                                   organizationID: try need("BWS_ORGANIZATION_ID"), projectID: try need("BWS_PROJECT_ID"))
    let token = try String(contentsOfFile: try need("BWS_ACCESS_TOKEN_FILE"), encoding: .utf8)
        .trimmingCharacters(in: .whitespacesAndNewlines)
    try store.login(accessToken: token)

    let v1 = try randomValue()
    let id = try store.create(key, v1)
    print("created: \(key) id \(id)")
    guard same(v1, try store.read(id)) else { throw BitwardenError.config("read-back after create did not match") }

    let v2 = try randomValue()
    try store.update(id, key, v2)
    guard same(v2, try store.read(id)) else { throw BitwardenError.config("read-back after update did not match") }
    print("updated: \(key)")

    try store.delete(id)
    print("deleted: \(id)")
} catch {
    FileHandle.standardError.write("\(error)\n".data(using: .utf8)!)
    exit(1)
}
```

### 9.7 Python

`pip install bitwarden-sdk==2.1.0` (wheels include the native core). Failures raise `Exception(errorMessage)`.

```python
"""Bitwarden Secrets Manager CRUD with the official Python SDK.

pip install bitwarden-sdk==2.1.0
Auth: a machine-account access token read from BWS_ACCESS_TOKEN_FILE. The SDK decrypts with the key embedded
in the access token; secret fields are encrypted and decrypted client-side.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys

from bitwarden_sdk import BitwardenClient, DeviceType, client_settings_from_dict


class BitwardenStore:
    def __init__(self, api_url: str, identity_url: str, organization_id: str, project_id: str) -> None:
        for url in (api_url, identity_url):
            if not url.startswith("https://"):
                raise ValueError("Bitwarden URLs must use https")
        self.client = BitwardenClient(client_settings_from_dict({
            "apiUrl": api_url, "identityUrl": identity_url, "deviceType": DeviceType.SDK, "userAgent": "secrets-crud",
        }))
        self.org, self.project = organization_id, project_id

    def login(self, access_token: str, state_file: str | None = None) -> None:
        """state_file (optional) caches the session so restarts skip a login; protect it like the token (0600)."""
        self.client.auth().login_access_token(access_token, state_file)

    def find_id(self, key: str) -> str | None:
        """Keys are not unique in Bitwarden; resolve a key to an ID only if exactly one secret has it."""
        matches = [s.id for s in self.client.secrets().list(self.org).data.data if s.key == key]
        if len(matches) > 1:
            raise RuntimeError(f"{len(matches)} secrets share the key {key}; address them by ID")
        return str(matches[0]) if matches else None

    def create(self, key: str, value: str, note: str = "") -> str:
        """Bitwarden allows duplicate keys, so refuse to create one that already exists. Returns the new ID."""
        if self.find_id(key) is not None:
            raise RuntimeError(f"a secret with key {key} already exists")
        return str(self.client.secrets().create(self.org, key, value, note, [self.project]).data.id)

    def read(self, secret_id: str) -> str:
        return self.client.secrets().get(secret_id).data.value

    def update(self, secret_id: str, key: str, value: str, note: str = "") -> None:
        """PUT semantics: key, value, note, and projects are all replaced."""
        self.client.secrets().update(self.org, secret_id, key, value, note, [self.project])

    def delete(self, secret_id: str) -> None:
        """Bulk delete reports per-ID errors inside a successful response; check them."""
        result = self.client.secrets().delete([secret_id]).data.data
        failed = [r for r in result if r.error]
        if failed:
            raise RuntimeError(f"delete failed for {failed[0].id}: {failed[0].error}")


def main() -> int:
    env = os.environ
    try:
        key, org, project = env["SECRET_KEY_NAME"], env["BWS_ORGANIZATION_ID"], env["BWS_PROJECT_ID"]
        with open(env["BWS_ACCESS_TOKEN_FILE"], encoding="utf-8") as fh:
            token = fh.read().strip()
    except KeyError as missing:
        print(f"set {missing}", file=sys.stderr)
        return 2
    store = BitwardenStore(env.get("BWS_API_URL", "https://api.bitwarden.com"),
                           env.get("BWS_IDENTITY_URL", "https://identity.bitwarden.com"), org, project)
    try:
        store.login(token)
        del token

        v1 = secrets.token_urlsafe(32)
        sid = store.create(key, v1)
        print(f"created: {key} id {sid}")
        if not hmac.compare_digest(v1, store.read(sid)):
            raise RuntimeError("read-back after create did not match")

        v2 = secrets.token_urlsafe(32)
        store.update(sid, key, v2)
        if not hmac.compare_digest(v2, store.read(sid)):
            raise RuntimeError("read-back after update did not match")
        print(f"updated: {key}")

        store.delete(sid)
        print(f"deleted: {sid}")
        return 0
    except Exception as exc:  # the SDK raises plain Exception(errorMessage); messages carry no values
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

`npm i @bitwarden/sdk-napi@1.0.0` (prebuilt native addon per platform). Methods return the decoded `data` directly and throw `Error(errorMessage)` on failure.

```typescript
// Bitwarden Secrets Manager CRUD with the official Node SDK (npm i @bitwarden/sdk-napi@1.0.0; native addon).
// Auth: a machine-account access token read from BWS_ACCESS_TOKEN_FILE. Secret fields are encrypted and
// decrypted inside the SDK with the key embedded in the access token.
import { readFile } from "node:fs/promises";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { BitwardenClient, DeviceType, LogLevel } from "@bitwarden/sdk-napi";

export class BitwardenStore {
  private readonly client: BitwardenClient;

  constructor(apiUrl: string, identityUrl: string, private readonly org: string, private readonly project: string) {
    if (![apiUrl, identityUrl].every((u) => u.startsWith("https://"))) throw new Error("Bitwarden URLs must use https");
    // LogLevel.Warn or higher: Debug/Trace logging is for local troubleshooting only.
    this.client = new BitwardenClient({ apiUrl, identityUrl, deviceType: DeviceType.SDK, userAgent: "secrets-crud" }, LogLevel.Warn);
  }

  /** stateFile (optional) caches the session across restarts; protect it like the token (0600). */
  async login(accessToken: string, stateFile?: string): Promise<void> {
    await this.client.auth().loginAccessToken(accessToken, stateFile);
  }

  /** Keys are not unique in Bitwarden; resolve a key to an ID only if exactly one secret has it. */
  async findId(key: string): Promise<string | undefined> {
    const matches = (await this.client.secrets().list(this.org)).data.filter((s) => s.key === key);
    if (matches.length > 1) throw new Error(`${matches.length} secrets share the key ${key}; address them by ID`);
    return matches[0]?.id;
  }

  /** Bitwarden allows duplicate keys, so refuse to create one that already exists. Returns the new ID. */
  async create(key: string, value: string, note = ""): Promise<string> {
    if ((await this.findId(key)) !== undefined) throw new Error(`a secret with key ${key} already exists`);
    return (await this.client.secrets().create(this.org, key, value, note, [this.project])).id;
  }

  async read(id: string): Promise<string> {
    return (await this.client.secrets().get(id)).value;
  }

  /** PUT semantics: key, value, note, and projects are all replaced. */
  async update(id: string, key: string, value: string, note = ""): Promise<void> {
    await this.client.secrets().update(this.org, id, key, value, note, [this.project]);
  }

  /** Bulk delete reports per-ID errors inside a successful response; check them. */
  async delete(id: string): Promise<void> {
    const failed = (await this.client.secrets().delete([id])).data.filter((r) => r.error);
    if (failed.length) throw new Error(`delete failed for ${failed[0].id}: ${failed[0].error}`);
  }
}

const randomValue = (): string => randomBytes(32).toString("base64url");
const same = (a: string, b: string): boolean => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

async function main(): Promise<void> {
  const env = process.env;
  const { SECRET_KEY_NAME: key, BWS_ORGANIZATION_ID: org, BWS_PROJECT_ID: project, BWS_ACCESS_TOKEN_FILE: tokenFile } = env;
  if (!key || !org || !project || !tokenFile) {
    throw new Error("set SECRET_KEY_NAME, BWS_ORGANIZATION_ID, BWS_PROJECT_ID, BWS_ACCESS_TOKEN_FILE");
  }
  const store = new BitwardenStore(
    env.BWS_API_URL ?? "https://api.bitwarden.com",
    env.BWS_IDENTITY_URL ?? "https://identity.bitwarden.com",
    org,
    project,
  );
  await store.login((await readFile(tokenFile, "utf8")).trim());

  const v1 = randomValue();
  const id = await store.create(key, v1);
  console.log(`created: ${key} id ${id}`);
  if (!same(v1, await store.read(id))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  await store.update(id, key, v2);
  if (!same(v2, await store.read(id))) throw new Error("read-back after update did not match");
  console.log(`updated: ${key}`);

  await store.delete(id);
  console.log(`deleted: ${id}`);
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? `${err.name}: ${err.message}` : "unknown error");
  process.exitCode = 1;
});
```

### 9.9 C++

C++17 + nlohmann/json, calling the three `bitwarden_c` exports directly (`init`, `run_command`, `free_mem`). The beta C++ wrapper in `sdk-sm/languages/cpp` offers typed methods on top of the same calls but requires Boost and a CMake build.

```cpp
// Bitwarden Secrets Manager CRUD in C++17 through the official bitwarden_c FFI + nlohmann/json.
// (The sdk-sm repository also has a beta C++ wrapper, languages/cpp, that dlopen()s the same library and
// needs Boost; calling the three C functions directly keeps dependencies minimal.)
//   g++ -std=c++17 -O2 main.cpp -o bws_crud -L<libdir> -lbitwarden_c $(pkg-config --cflags --libs openssl) -lpthread -ldl -lm
// Auth: a machine-account access token read from BWS_ACCESS_TOKEN_FILE.
#include <nlohmann/json.hpp>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" {
void* init(const char* client_settings_json);
char* run_command(const char* command_json, void* client);
void free_mem(void* client);
}

using json = nlohmann::json;

static void wipe(std::string& s) { OPENSSL_cleanse(s.data(), s.size()); s.clear(); }

class BitwardenStore {
 public:
  BitwardenStore(const std::string& api_url, const std::string& identity_url, std::string org, std::string project)
      : org_(std::move(org)), project_(std::move(project)) {
    if (api_url.rfind("https://", 0) != 0 || identity_url.rfind("https://", 0) != 0)
      throw std::runtime_error("Bitwarden URLs must use https");
    std::string settings = json{{"apiUrl", api_url}, {"identityUrl", identity_url}, {"deviceType", "SDK"},
                                {"userAgent", "secrets-crud-cpp"}}.dump();
    client_ = init(settings.c_str());
    if (!client_) throw std::runtime_error("bitwarden_c init failed");
  }
  ~BitwardenStore() { if (client_) free_mem(client_); }
  BitwardenStore(const BitwardenStore&) = delete;
  BitwardenStore& operator=(const BitwardenStore&) = delete;

  void login(const std::string& access_token) { run("login", {{"loginAccessToken", {{"accessToken", access_token}}}}); }

  // Keys are not unique in Bitwarden; resolve a key to an ID only if exactly one secret has it.
  std::optional<std::string> find_id(const std::string& key) {
    json data = run("list", secrets("list", {{"organizationId", org_}}));
    std::vector<std::string> ids;
    for (const auto& s : data["data"]) if (s.value("key", "") == key) ids.push_back(s["id"].get<std::string>());
    if (ids.size() > 1) throw std::runtime_error(std::to_string(ids.size()) + " secrets share the key " + key);
    if (ids.empty()) return std::nullopt;
    return ids.front();
  }

  // Bitwarden allows duplicate keys, so refuse to create one that already exists. Returns the new ID.
  std::string create(const std::string& key, const std::string& value) {
    if (find_id(key)) throw std::runtime_error("a secret with key " + key + " already exists");
    json data = run("create", secrets("create", write_args("", key, value)));
    std::string id = data["id"].get<std::string>();
    scrub(data);
    return id;
  }

  std::string read(const std::string& id) {
    json data = run("get", secrets("get", {{"id", id}}));
    std::string v = data["value"].get<std::string>();
    scrub(data);
    return v;
  }

  // PUT semantics: key, value, note, and projects are all replaced.
  void update(const std::string& id, const std::string& key, const std::string& value) {
    json data = run("update", secrets("update", write_args(id, key, value)));
    scrub(data);
  }

  // Bulk delete reports per-ID errors inside a successful response; check them.
  void remove(const std::string& id) {
    json data = run("delete", secrets("delete", {{"ids", json::array({id})}}));
    for (const auto& r : data["data"])
      if (r.contains("error") && r["error"].is_string())
        throw std::runtime_error("delete failed for " + id + ": " + r["error"].get<std::string>());
  }

 private:
  void* client_ = nullptr;
  std::string org_, project_;

  static json secrets(const char* verb, json args) { return {{"secrets", {{verb, std::move(args)}}}}; }

  json write_args(const std::string& id, const std::string& key, const std::string& value) const {
    json a = {{"organizationId", org_}, {"key", key}, {"value", value}, {"note", ""}, {"projectIds", json::array({project_})}};
    if (!id.empty()) a["id"] = id;
    return a;
  }

  // Wipe every string held by a json tree (values, keys of secrets, the token).
  static void scrub(json& j) {
    if (j.is_string()) wipe(*j.get_ptr<std::string*>());
    else if (j.is_structured()) for (auto& c : j) scrub(c);
  }

  json run(const char* op, json command) {
    std::string cmd = command.dump();
    scrub(command);
    char* raw = run_command(cmd.c_str(), client_);
    wipe(cmd);
    if (!raw) throw std::runtime_error(std::string(op) + ": no response");
    std::string text(raw);
    OPENSSL_cleanse(raw, std::strlen(raw));
    std::free(raw);  // allocated by the library with the system allocator (the Go SDK also free()s it)
    json resp = json::parse(text, nullptr, false);
    wipe(text);
    if (!resp.is_object() || !resp.value("success", false)) {
      // errorMessage describes the failure (HTTP status, validation); it does not contain values
      std::string msg = resp.is_object() ? resp.value("errorMessage", "unknown error") : "unparseable response";
      throw std::runtime_error(std::string(op) + " failed: " + msg);
    }
    json data = resp.contains("data") ? std::move(resp["data"]) : json();
    scrub(resp);
    return data;
  }
};

static std::string random_value() {
  unsigned char raw[32];
  if (RAND_bytes(raw, sizeof raw) != 1) throw std::runtime_error("csprng failure");
  char b64[45];
  EVP_EncodeBlock(reinterpret_cast<unsigned char*>(b64), raw, sizeof raw);
  OPENSSL_cleanse(raw, sizeof raw);
  std::string s(b64);
  OPENSSL_cleanse(b64, sizeof b64);
  return s;
}

static bool same(const std::string& a, const std::string& b) {
  return a.size() == b.size() && CRYPTO_memcmp(a.data(), b.data(), a.size()) == 0;
}

static std::string need(const char* k) {
  const char* v = std::getenv(k);
  if (!v || !*v) throw std::runtime_error(std::string("set ") + k);
  return v;
}

static std::string env_or(const char* k, const char* def) {
  const char* v = std::getenv(k);
  return v && *v ? v : def;
}

int main() {
  try {
    const std::string key = need("SECRET_KEY_NAME");
    std::ifstream f(need("BWS_ACCESS_TOKEN_FILE"));
    std::stringstream ss;
    ss << f.rdbuf();
    std::string token = ss.str();
    while (!token.empty() && (token.back() == '\n' || token.back() == '\r' || token.back() == ' ')) token.pop_back();

    BitwardenStore store(env_or("BWS_API_URL", "https://api.bitwarden.com"),
                         env_or("BWS_IDENTITY_URL", "https://identity.bitwarden.com"),
                         need("BWS_ORGANIZATION_ID"), need("BWS_PROJECT_ID"));
    store.login(token);
    wipe(token);

    std::string v1 = random_value();
    std::string id = store.create(key, v1);
    std::cout << "created: " << key << " id " << id << "\n";
    std::string got = store.read(id);
    if (!same(v1, got)) throw std::runtime_error("read-back after create did not match");
    wipe(got);

    std::string v2 = random_value();
    store.update(id, key, v2);
    got = store.read(id);
    if (!same(v2, got)) throw std::runtime_error("read-back after update did not match");
    std::cout << "updated: " << key << "\n";
    wipe(got); wipe(v1); wipe(v2);

    store.remove(id);
    std::cout << "deleted: " << id << "\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << "\n";  // operation and SDK error text, never values
    return 1;
  }
}
```

### 9.10 C

C11 + cJSON + OpenSSL, linked against `libbitwarden_c`. Commands are JSON objects such as `{"secrets":{"get":{"id":"…"}}}`; results are `{"success":…, "errorMessage":…, "data":…}`.

```c
/*
 * Bitwarden Secrets Manager CRUD in C through the official bitwarden_c FFI (the Rust core that the Go,
 * C++, PHP, Java, and Ruby SDKs wrap). Commands and results are JSON strings; cJSON builds and parses them.
 *
 * libbitwarden_c ships prebuilt in the Go SDK module (internal/cinterface/lib/<os-arch>/) and can be built
 * from bitwarden/sdk-sm (crates/bitwarden-c). Linux:
 *   cc -std=c11 -Wall -Wextra -O2 bws_crud.c -o bws_crud -L<libdir> -lbitwarden_c \
 *      $(pkg-config --cflags --libs libcjson openssl) -lpthread -ldl -lm
 *
 * Auth: a machine-account access token read from BWS_ACCESS_TOKEN_FILE.
 */
#define _POSIX_C_SOURCE 200809L
#include <cjson/cJSON.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* bitwarden_c exports (see crates/bitwarden-c/src/c.rs) */
typedef void *ClientPtr;
extern ClientPtr init(const char *client_settings_json);
extern char *run_command(const char *command_json, ClientPtr client);
extern void free_mem(ClientPtr client);

static ClientPtr g_client;
static const char *g_org, *g_project;

static void str_wipe_free(char *s) { if (s) { OPENSSL_cleanse(s, strlen(s)); free(s); } }

/* Wipe every string in a cJSON tree before it is freed (commands and results carry values and the token). */
static void json_wipe(cJSON *n) {
    for (; n; n = n->next) {
        if (cJSON_IsString(n) && n->valuestring) OPENSSL_cleanse(n->valuestring, strlen(n->valuestring));
        if (n->child) json_wipe(n->child);
    }
}

/* Run one command (consumed). Returns the "data" member detached from the response, or NULL on failure.
 * The SDK's errorMessage describes the failure (HTTP status, validation); it does not contain values. */
static cJSON *bw_run(const char *op, cJSON *command) {
    char *json = cJSON_PrintUnformatted(command);
    json_wipe(command);
    cJSON_Delete(command);
    char *raw = run_command(json, g_client);
    OPENSSL_cleanse(json, strlen(json));
    cJSON_free(json);
    if (!raw) { fprintf(stderr, "%s: no response\n", op); return NULL; }
    cJSON *resp = cJSON_Parse(raw);
    str_wipe_free(raw); /* the library allocates with the system allocator (the Go SDK also free()s it) */
    cJSON *data = NULL;
    if (cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(resp, "success"))) {
        data = cJSON_DetachItemFromObjectCaseSensitive(resp, "data");
        if (!data) data = cJSON_CreateNull();
    } else {
        const cJSON *m = cJSON_GetObjectItemCaseSensitive(resp, "errorMessage");
        fprintf(stderr, "%s failed: %s\n", op, cJSON_IsString(m) ? m->valuestring : "unknown error");
    }
    json_wipe(resp);
    cJSON_Delete(resp);
    return data;
}

static cJSON *secrets_cmd(const char *verb, cJSON *args) {
    cJSON *cmd = cJSON_CreateObject();
    cJSON_AddItemToObject(cJSON_AddObjectToObject(cmd, "secrets"), verb, args);
    return cmd;
}

static int login(const char *token) {
    cJSON *cmd = cJSON_CreateObject();
    cJSON_AddStringToObject(cJSON_AddObjectToObject(cmd, "loginAccessToken"), "accessToken", token);
    cJSON *data = bw_run("login", cmd);
    int ok = data != NULL;
    cJSON_Delete(data);
    return ok ? 0 : -1;
}

/* Keys are not unique: returns 0 if absent, 1 if exactly one exists (id copied out), -1 on error/ambiguity. */
static int find_id(const char *key, char id[37]) {
    cJSON *args = cJSON_CreateObject();
    cJSON_AddStringToObject(args, "organizationId", g_org);
    cJSON *data = bw_run("list", secrets_cmd("list", args));
    if (!data) return -1;
    int found = 0;
    const cJSON *item;
    cJSON_ArrayForEach(item, cJSON_GetObjectItemCaseSensitive(data, "data")) {
        const cJSON *k = cJSON_GetObjectItemCaseSensitive(item, "key"), *i = cJSON_GetObjectItemCaseSensitive(item, "id");
        if (cJSON_IsString(k) && strcmp(k->valuestring, key) == 0 && cJSON_IsString(i)) {
            if (++found == 1) snprintf(id, 37, "%s", i->valuestring);
        }
    }
    cJSON_Delete(data);
    if (found > 1) { fprintf(stderr, "%d secrets share the key %s; address them by ID\n", found, key); return -1; }
    return found;
}

static cJSON *write_args(const char *id, const char *key, const char *value) {
    cJSON *a = cJSON_CreateObject();
    if (id) cJSON_AddStringToObject(a, "id", id);
    cJSON_AddStringToObject(a, "organizationId", g_org);
    cJSON_AddStringToObject(a, "key", key);
    cJSON_AddStringToObject(a, "value", value);
    cJSON_AddStringToObject(a, "note", "");
    cJSON_AddItemToArray(cJSON_AddArrayToObject(a, "projectIds"), cJSON_CreateString(g_project));
    return a;
}

/* Refuses an existing key (Bitwarden would create a duplicate); writes the new ID into id. */
static int secret_create(const char *key, const char *value, char id[37]) {
    int f = find_id(key, id);
    if (f != 0) { if (f == 1) fprintf(stderr, "a secret with key %s already exists\n", key); return -1; }
    cJSON *data = bw_run("create", secrets_cmd("create", write_args(NULL, key, value)));
    const cJSON *i = cJSON_GetObjectItemCaseSensitive(data, "id");
    int rc = cJSON_IsString(i) ? (snprintf(id, 37, "%s", i->valuestring), 0) : -1;
    json_wipe(data);
    cJSON_Delete(data);
    return rc;
}

/* Returns a malloc'd value (wipe + free), or NULL. */
static char *secret_read(const char *id) {
    cJSON *args = cJSON_CreateObject();
    cJSON_AddStringToObject(args, "id", id);
    cJSON *data = bw_run("get", secrets_cmd("get", args));
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(data, "value");
    char *r = cJSON_IsString(v) ? strdup(v->valuestring) : NULL;
    json_wipe(data);
    cJSON_Delete(data);
    return r;
}

/* PUT semantics: key, value, note, and projects are all replaced. */
static int secret_update(const char *id, const char *key, const char *value) {
    cJSON *data = bw_run("update", secrets_cmd("update", write_args(id, key, value)));
    int rc = data ? 0 : -1;
    json_wipe(data);
    cJSON_Delete(data);
    return rc;
}

/* Bulk delete reports per-ID errors inside a successful response; check them. */
static int secret_delete(const char *id) {
    cJSON *args = cJSON_CreateObject();
    cJSON_AddItemToArray(cJSON_AddArrayToObject(args, "ids"), cJSON_CreateString(id));
    cJSON *data = bw_run("delete", secrets_cmd("delete", args));
    if (!data) return -1;
    int rc = 0;
    const cJSON *r;
    cJSON_ArrayForEach(r, cJSON_GetObjectItemCaseSensitive(data, "data")) {
        const cJSON *e = cJSON_GetObjectItemCaseSensitive(r, "error");
        if (cJSON_IsString(e)) { fprintf(stderr, "delete failed for %s: %s\n", id, e->valuestring); rc = -1; }
    }
    cJSON_Delete(data);
    return rc;
}

static int random_value(char out[45]) {
    unsigned char raw[32];
    if (RAND_bytes(raw, sizeof raw) != 1) return -1;
    EVP_EncodeBlock((unsigned char *)out, raw, sizeof raw);
    OPENSSL_cleanse(raw, sizeof raw);
    return 0;
}

static int same(const char *a, const char *b) {
    return b && strlen(a) == strlen(b) && CRYPTO_memcmp(a, b, strlen(a)) == 0;
}

static const char *env_or(const char *k, const char *def) { const char *v = getenv(k); return v && *v ? v : def; }

int main(void) {
    const char *key = getenv("SECRET_KEY_NAME"), *tf = getenv("BWS_ACCESS_TOKEN_FILE");
    g_org = getenv("BWS_ORGANIZATION_ID"); g_project = getenv("BWS_PROJECT_ID");
    const char *api = env_or("BWS_API_URL", "https://api.bitwarden.com");
    const char *identity = env_or("BWS_IDENTITY_URL", "https://identity.bitwarden.com");
    if (!key || !tf || !g_org || !g_project) {
        fprintf(stderr, "set SECRET_KEY_NAME, BWS_ORGANIZATION_ID, BWS_PROJECT_ID, BWS_ACCESS_TOKEN_FILE\n");
        return 2;
    }
    if (strncmp(api, "https://", 8) != 0 || strncmp(identity, "https://", 8) != 0) {
        fprintf(stderr, "Bitwarden URLs must use https\n");
        return 2;
    }

    cJSON *settings = cJSON_CreateObject();
    cJSON_AddStringToObject(settings, "apiUrl", api);
    cJSON_AddStringToObject(settings, "identityUrl", identity);
    cJSON_AddStringToObject(settings, "deviceType", "SDK");
    cJSON_AddStringToObject(settings, "userAgent", "secrets-crud-c");
    char *settings_json = cJSON_PrintUnformatted(settings);
    cJSON_Delete(settings);
    g_client = init(settings_json);
    cJSON_free(settings_json);
    if (!g_client) { fprintf(stderr, "init failed\n"); return 1; }

    int rc = 1;
    char token[1024], id[37] = {0}, v1[45], v2[45], *got = NULL;
    FILE *f = fopen(tf, "r");
    size_t n = f ? fread(token, 1, sizeof token - 1, f) : 0;
    if (f) fclose(f);
    token[n] = '\0';
    while (n && (token[n - 1] == '\n' || token[n - 1] == '\r' || token[n - 1] == ' ')) token[--n] = '\0';
    if (!n || login(token) != 0) goto done;
    OPENSSL_cleanse(token, sizeof token);
    if (random_value(v1) || random_value(v2)) goto done;

    if (secret_create(key, v1, id) != 0) goto done;
    printf("created: %s id %s\n", key, id);
    got = secret_read(id);
    if (!same(v1, got)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    str_wipe_free(got); got = NULL;

    if (secret_update(id, key, v2) != 0) goto done;
    got = secret_read(id);
    if (!same(v2, got)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated: %s\n", key);

    if (secret_delete(id) != 0) goto done;
    printf("deleted: %s\n", id);
    rc = 0;
done:
    str_wipe_free(got);
    OPENSSL_cleanse(token, sizeof token);
    OPENSSL_cleanse(v1, sizeof v1); OPENSSL_cleanse(v2, sizeof v2);
    free_mem(g_client);
    return rc;
}
```

## 10. Use secrets in applications (and the Password Manager alternative)

| Mechanism | How values arrive | Notes |
| --- | --- | --- |
| SDK at startup + `sync` refresh (section 9) | In memory | Explicit control; one client per machine account. |
| `bws run --project-id <id> -- <command>` | Environment variables of the child | `--no-inherit-env` limits what the child sees; env-var exposure applies. |
| Kubernetes **sm-operator** (`BitwardenSecret` CRD) | Synced Kubernetes `Secret` | Widens exposure to anyone who can read Secrets in the namespace. |
| GitHub Action `bitwarden/sm-action` | Masked step outputs/env vars | Store the access token as a repository/environment secret scoped to protected branches. |
| Ansible lookup (`bitwarden.secrets`) | Play variables | Use `no_log` on tasks that handle values. |

**Password Manager instead of Secrets Manager.** Vault items (logins, secure notes) are a different product. Automate them with the `bw` CLI: `bw login --apikey` (with `BW_CLIENTID`/`BW_CLIENTSECRET`), `bw unlock --passwordfile <file>` to get a `BW_SESSION` key, then `bw get item <id>`, `bw get template item | jq … | bw encode | bw create item` (base64 JSON via stdin), `bw edit item <id>`, and `bw delete item <id>` (to trash; `--permanent` to purge). `bw serve` exposes the same operations as a local REST API (default `localhost:8087`; routes such as `GET/PUT/DELETE /object/item/:id`, `POST /object/item`, `GET /list/object/items`, `POST /unlock`). It has **no authentication** beyond host binding and rejecting requests with an `Origin` header: any local process can read the unlocked vault through it. Never use `--hostname all` or `--disable-origin-protection`, run it only inside a dedicated, single-tenant sandbox, and prefer Secrets Manager for machine workloads. [S08] [S09]

## 11. Automation and error handling

The SDKs surface server and validation errors as the core's `errorMessage` (for example an HTTP status from the API or "Doesn't contain a decryption key" for a malformed token). Typical cases:

| Situation | Typical cause | Action |
| --- | --- | --- |
| Login fails | Revoked/expired token; wrong identity URL (US vs EU vs self-hosted); malformed token | Check URLs and token expiry; issue a new token. |
| 404 on get/update | Wrong ID; machine account lacks access; secret in Trash | Verify project access; check Trash. |
| 403/400 on create | No write access to the project; missing project for a machine account | Grant **Can read, write**; pass the project ID. |
| Delete "succeeded" but secret remains | Per-ID `error` in the bulk response | Inspect `data[].error`. |
| Duplicate keys | Create without a key check | Resolve by ID; delete the duplicate. |
| Rate limited (429) | Many replicas logging in or reading individually | Use state files, `sync`, `getByIds`, and caching. |

Practices:

- One machine account per workload per environment; separate read and write accounts.
- Resolve keys to IDs once and store IDs in configuration; refuse ambiguous keys.
- Check bulk-delete results; treat updates as full replacements.
- Expiring access tokens with a documented rotation (new token → deploy → revoke old).

## 12. Optional live CRUD verification

This **performs writes** in the project you choose (use a sandbox project). It uses the Python program from section 9.7 because the CLI would put values on command lines:

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${BWS_ORGANIZATION_ID:?}" "${BWS_PROJECT_ID:?}" "${BWS_ACCESS_TOKEN_FILE:?}"
export SECRET_KEY_NAME="CRUD_CHECK_$(date -u +%Y%m%d%H%M%S)_$$"
python3 crud.py
printf 'PASS: create, read, update, and delete completed.\n'
```

Then empty the Trash entry from the web app if you do not want it retained for 30 days.

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| `builder error for url` / HTTPS errors | Release builds refuse `http://` URLs; use HTTPS and a trusted certificate (the core uses the platform verifier; custom CAs go in the OS trust store). |
| Works on US cloud, fails self-hosted | Set both API and identity URLs (`/api`, `/identity`); `bws` uses `BWS_SERVER_URL`. |
| Secret not found after delete | It is in Trash (restore there). |
| Two secrets with the same key | Created without a key check; consolidate and use IDs. |
| `bws run` skips some secrets | Key not a valid environment variable name or duplicated; use `--uuids-as-keynames`. |
| Native library load errors (PHP, Java, C#) | Missing platform binary or architecture mismatch; install the package's native library for your OS/arch. |
| Value appears in logs | CLI output not suppressed (`-o none`), value on a command line, or debug logging; remove, rotate, revoke. |

## 14. Accuracy notes and official sources

- **Versions:** SDK releases are tagged per language in `bitwarden/sdk-sm` (for example `python-v2.1.0`, `rust-v2.1.0`, `napi-v1.0.0`, `dotnet-v1.0.0`); the Go module is `sdk-go` v2.1.0. PHP, Java, and C++ bindings are labeled beta.
- **`update` behavior:** the released 2.1.0 core does not send a `valueChanged` flag; newer sources on `main` fetch the old secret first to set it (for server-side version history). Check release notes before relying on version history.
- **HTTPS enforcement** and the platform verifier were read from `bitwarden-core` 3.0.0 (`new_http_client_builder`). [S05]
- **bws flags and environment variables** (`BWS_ACCESS_TOKEN`, `BWS_SERVER_URL`, `BWS_UUIDS_AS_KEYNAMES`, `-o none`, `secret create KEY VALUE PROJECT_ID`, `run --no-inherit-env --project-id`) were checked in the `bws` sources. [S06]
- **`bw serve`** routes and its lack of authentication were checked in the Bitwarden CLI sources (2026.10.1). [S09]
- **Mock-based verification** validates client logic, request shapes, and client-side cryptography with the official fixture, not server-side permissions or rate limits.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [Secrets][S01] | Projects, Trash (30 days), one project per secret |
| S02 | [Machine accounts][S02] | Project access levels |
| S03 | [Access tokens][S03] | Creation, expiry, revocation |
| S04 | [SDK sources (sdk-sm)][S04] | Commands, request/response models |
| S05 | [bitwarden-core][S05] | HTTP client, HTTPS enforcement |
| S06 | [bws CLI][S06] | Commands, flags, env vars |
| S07 | [Go SDK][S07] | Go client, bundled native libraries |
| S08 | [Password Manager CLI][S08] | `bw` login/unlock/serve |
| S09 | [Bitwarden CLI source][S09] | `bw serve` routes and middleware |
| S10 | [Kubernetes operator][S10] | `BitwardenSecret` sync |
| S11 | [GitHub Actions integration][S11] | `sm-action` |

[S01]: https://bitwarden.com/help/secrets/
[S02]: https://bitwarden.com/help/machine-accounts/
[S03]: https://bitwarden.com/help/access-tokens/
[S04]: https://github.com/bitwarden/sdk-sm
[S05]: https://crates.io/crates/bitwarden-core
[S06]: https://bitwarden.com/help/secrets-manager-cli/
[S07]: https://github.com/bitwarden/sdk-go
[S08]: https://bitwarden.com/help/cli/
[S09]: https://github.com/bitwarden/clients/tree/main/apps/cli
[S10]: https://bitwarden.com/help/secrets-manager-kubernetes-operator/
[S11]: https://bitwarden.com/help/github-actions-integration/
