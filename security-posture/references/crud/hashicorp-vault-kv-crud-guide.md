# HashiCorp Vault (KV v2): comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** HashiCorp Vault HTTP API `v1`, KV secrets engine **version 2** (also applies to HCP Vault Dedicated and, for these endpoints, to API-compatible OpenBao)  
**Primary authentication:** a Vault token obtained by a machine auth method (AppRole, Kubernetes, JWT/OIDC, cloud IAM) or supplied by Vault Agent  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use Bash and the `vault` CLI)

This guide covers **static secrets in a KV v2 mount**: a logical path holding a versioned map of string keys to values, with soft delete, undelete, destroy, and check-and-set (CAS) concurrency control. It covers authentication and token handling, policies, complete CRUD workflows, a full CRUD program in each of ten languages, runtime consumption (Agent, Proxy, operator, injectors), and troubleshooting. Dynamic secrets engines (database, cloud), PKI, and Transit are out of scope except where they change how you should design (see the engineering guide).

The examples assume a Vault address and a machine identity are already provisioned. Do not paste a root token, AppRole SecretID, or any token into this document, source files, or command arguments.

**Verification boundary:** API semantics were cross-checked against the official KV v2 API and auth method documentation in section 14. The Go program (official `github.com/hashicorp/vault/api` v1.23.0 + `api/auth/approle` v0.12.0), the Rust, PHP, C#, Java, Python (`hvac` 2.4.0), TypeScript, C++, and C programs were all compiled or type-checked and then **run end-to-end** against a local mock of the Vault HTTP API (AppRole login, KV v2 data/metadata endpoints with CAS semantics, soft delete). The mock is not Vault: it reproduces the documented request/response shapes and CAS rules, not Vault's policy engine, storage, or replication. The Swift program was written against the same HTTP surface but not compiled (no Swift toolchain was available). No call was made to a real Vault cluster. Section 12 provides an optional live test against a dev server.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Authenticate and inspect the token](#2-authenticate-and-inspect-the-token)
3. [Data model and addressing](#3-data-model-and-addressing)
4. [Safe secret handling](#4-safe-secret-handling)
5. [Create secrets](#5-create-secrets)
6. [Read secrets](#6-read-secrets)
7. [Update secrets](#7-update-secrets)
8. [Delete, undelete, destroy, and purge](#8-delete-undelete-destroy-and-purge)
9. [Language implementations](#9-language-implementations)
10. [Use secrets in applications](#10-use-secrets-in-applications)
11. [Automation and error handling](#11-automation-and-error-handling)
12. [Optional live CRUD verification](#12-optional-live-crud-verification)
13. [Troubleshooting](#13-troubleshooting)
14. [Accuracy notes and official sources](#14-accuracy-notes-and-official-sources)

## 1. Requirements and conventions

| Language | Client | Transport used here | Verified here |
| --- | --- | --- | --- |
| Go | `github.com/hashicorp/vault/api` (official) + `api/auth/approle` | Official client | `go vet`, mock run |
| Rust | none official (`vaultrs` is community) | HTTP API via `reqwest` | `cargo check`, mock run |
| PHP | none official | HTTP API via ext-curl | mock run |
| C# | none official (`VaultSharp` is community) | HTTP API via `HttpClient` + `System.Text.Json` | built (.NET 8), mock run |
| Java | none official (Spring Vault for Spring apps) | HTTP API via `java.net.http` + Jackson | `javac -Werror`, mock run |
| Swift | none | HTTP API via `URLSession` | not compiled |
| Python | `hvac` (community, de facto standard) | Client library | mock run |
| TypeScript | none official (`node-vault` is community) | HTTP API via `fetch` (Node 18+) | `tsc --strict`, mock run |
| C++ | none | HTTP API via libcurl + nlohmann/json | `-Werror`, mock run |
| C | none | HTTP API via libcurl + cJSON | `-Werror`, mock run |

The HTTP API is the stable contract; HashiCorp maintains the Go client. Using the raw API keeps dependencies small and behavior explicit. Every program follows the same contract:

- Environment: `VAULT_ADDR` (HTTPS, or `http://127.0.0.1:<port>` for a local Vault Agent/Proxy listener only), optional `VAULT_NAMESPACE` (Enterprise/HCP), `VAULT_KV_MOUNT` (default `secret`), `SECRET_PATH` (for example `myapp/dev/crud-check`).
- Authentication: an existing `VAULT_TOKEN`, otherwise **AppRole** with `VAULT_ROLE_ID` and the SecretID read from the file named by `VAULT_SECRET_ID_FILE`.
- The secret is stored as `{"value": "<secret>"}`. The program **creates** it with `cas=0` (fails if the path exists), **reads** and compares in constant time, **updates** with `cas=<version just read>`, reads again, then **soft-deletes** the latest version. With `PURGE_AFTER_DELETE=1` it deletes all versions and metadata.
- Paths are validated (`[A-Za-z0-9_.-]` segments, no empty, `.` or `..` segments) before they are placed in a URL.
- Output contains paths and version numbers only.

For CLI snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
vault version
export VAULT_ADDR='https://vault.example.internal:8200'
MOUNT='secret'
```

## 2. Authenticate and inspect the token

### Machine auth methods

| Platform | Method | Login endpoint | What the workload holds |
| --- | --- | --- | --- |
| Kubernetes | `kubernetes` | `POST /v1/auth/kubernetes/login {role, jwt}` | Its projected service-account token |
| AWS / GCP / Azure | `aws` / `gcp` / `azure` | `POST /v1/auth/<method>/login` | Cloud identity (signed request or identity token) |
| CI (GitHub, GitLab) | `jwt` | `POST /v1/auth/jwt/login {role, jwt}` | The CI OIDC token |
| VMs, legacy apps | `approle` | `POST /v1/auth/approle/login {role_id, secret_id}` | RoleID (not secret) + SecretID (secret, ideally response-wrapped, single use) |
| Anything, via sidecar | Vault Agent / Vault Proxy auto-auth | Agent logs in; app reads a token sink file or uses the local proxy | Nothing, or a short-lived token file |

Prefer platform identity (Kubernetes, cloud, JWT) over AppRole, because the workload then holds no long-lived credential. When AppRole is used, deliver the SecretID through a trusted orchestrator as a **response-wrapped** token, bind it with `secret_id_bound_cidrs`/`token_bound_cidrs`, and keep `secret_id_num_uses` and TTLs small.

### Inspect the current token without printing it

```bash
vault token lookup -format=json |
  jq '.data | {display_name, policies, ttl, renewable, entity_id, accessor}'
```

`vault token lookup` output includes the token itself in `.data.id`; the `jq` filter drops it. Never run `vault print token` or `vault token lookup` without a filter in logs. The accessor identifies a token for audit and revocation without revealing it.

### Required policy

KV v2 uses distinct API paths per operation; policies must name them explicitly. [S02]

```hcl
# myapp-crud.hcl — create/read/update/delete for one application subtree
path "secret/data/myapp/dev/*" {
  capabilities = ["create", "read", "update", "patch", "delete"]
}
path "secret/metadata/myapp/dev/*" {
  capabilities = ["list", "read", "delete"]   # delete here = purge all versions
}
path "secret/delete/myapp/dev/*"   { capabilities = ["update"] }   # soft-delete specific versions
path "secret/undelete/myapp/dev/*" { capabilities = ["update"] }
path "secret/destroy/myapp/dev/*"  { capabilities = ["update"] }   # permanent; grant sparingly
```

A runtime policy usually needs only `read` on `secret/data/<app>/<env>/*` (plus `list` on metadata if it enumerates). `create` is required for a new key and `update` for an existing one; `patch` is a separate capability. [S01]

## 3. Data model and addressing

- **Mount:** a KV v2 engine at a path such as `secret/`. Confirm the version: `vault secrets list -format=json | jq '."secret/".options.version'` must be `"2"`.
- **Key path:** `myapp/dev/db` inside the mount. The API inserts an operation segment after the mount: `secret/data/myapp/dev/db`, `secret/metadata/myapp/dev/db`, `secret/delete/…`, `secret/undelete/…`, `secret/destroy/…`.
- **Data:** each version is a JSON object of keys to values (store several related fields, such as `username` and `password`, together).
- **Versions:** each write creates version *n+1*. The engine keeps **10 versions** by default (`max_versions` 0 means 10); older versions are removed. `delete_version_after` can expire versions automatically. [S01]
- **Metadata:** `current_version`, `oldest_version`, per-version `created_time`/`deletion_time`/`destroyed`, `cas_required`, `max_versions`, `delete_version_after`, and `custom_metadata` (string map, returned with reads even without metadata access; do not put secrets in it).
- **Namespaces** (Enterprise/HCP): sent as `X-Vault-Namespace` or as a path prefix.

Inventory without values:

```bash
vault kv list -mount="$MOUNT" myapp/dev
vault kv metadata get -mount="$MOUNT" -format=json myapp/dev/db |
  jq '.data | {current_version, max_versions, cas_required, versions: (.versions | map_values({created_time, deletion_time, destroyed}))}'
```

## 4. Safe secret handling

- **Command lines:** `vault kv put … password=s3cr3t` puts the value in history and the process table. Use `key=@file` (reads the file) or `key=-` (reads stdin), or a JSON file: `vault kv put -mount=secret path @data.json`.
- **Output:** `vault kv get` prints values. Use `-field=<key>` only when redirecting to a protected file, or `-format=json | jq` filters that drop values.
- **Audit devices** log every request and response with values **HMAC-hashed** (salted SHA-256), not plaintext, so audit logs are safe to centralize; protect the audit HMAC salt and avoid `log_raw`. [S05]
- **Transport:** always TLS to Vault. `VAULT_SKIP_VERIFY=true` disables certificate checks and must never be used outside a throwaway dev server. Use `VAULT_CACERT` for private PKI.
- **Tokens are secrets too.** Keep them in memory or in a `0600` sink file on tmpfs; never log `X-Vault-Token`; revoke on shutdown (`POST /v1/auth/token/revoke-self`) when tokens are not managed by Agent.
- **Client debug logging:** HTTP debug logs of Vault clients include the `X-Vault-Token` header and response bodies. Keep them off.
- **Memory:** wipe buffers where possible (`zeroize`, `OPENSSL_cleanse`); minimize copies of managed strings.

## 5. Create secrets

`POST /v1/<mount>/data/<path>` with `{"options": {"cas": 0}, "data": {...}}` creates the key **only if it does not exist**; otherwise Vault returns **400** "check-and-set parameter did not match the current version." This is a true atomic create — use it. Without `cas`, the write is an upsert (unless `cas_required` is set). [S01]

### A. Create from protected files

```bash
vault kv put -mount="$MOUNT" -cas=0 myapp/dev/api-token \
  token=@/secure/path/to/api-token.txt
```

`@file` reads the file verbatim, including a trailing newline.

### B. Create a structured secret from JSON without printing it

```bash
(
  set -euo pipefail; set +x; umask 077
  work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
  jq -n --rawfile pw /secure/path/db-password.txt \
    '{username: "app_rw", password: ($pw | rtrimstr("\n")), host: "db.internal.example", port: "5432"}' > "$work/data.json"
  vault kv put -mount="$MOUNT" -cas=0 -format=json myapp/dev/db @"$work/data.json" | jq '.data.version'
)
```

### C. Configure metadata at creation

```bash
vault kv metadata put -mount="$MOUNT" -max-versions=5 -cas-required=true \
  -custom-metadata=owner=platform-team -custom-metadata=app=myapp myapp/dev/db
```

`cas_required=true` forces every writer to send `cas`, preventing blind overwrites.

## 6. Read secrets

`GET /v1/<mount>/data/<path>` returns the latest version; `?version=N` returns a specific one. The response is `{"data": {"data": {...}, "metadata": {"version": N, ...}}}`. Reading a soft-deleted or destroyed version returns **404** with metadata but `data: null`. Note the double `data`. [S01]

```bash
# One field to a new private file
vault kv get -mount="$MOUNT" -field=token myapp/dev/api-token > ./api-token.secret

# Version number only (safe to display)
vault kv get -mount="$MOUNT" -format=json myapp/dev/api-token | jq '.data.metadata.version'

# A previous version
vault kv get -mount="$MOUNT" -version=3 -field=token myapp/dev/api-token > ./api-token.v3.secret

# Structure check without printing values
vault kv get -mount="$MOUNT" -format=json myapp/dev/db | jq -e '.data.data | has("username") and has("password")' > /dev/null
```

`-field` prints the raw value without appending a newline. To learn which keys exist without reading values, use the subkeys endpoint (`GET /v1/<mount>/subkeys/<path>`), which returns the key structure with values replaced by `null`; grant `read` on `<mount>/subkeys/*` for that instead of `data/`.

## 7. Update secrets

| Operation | Endpoint | Semantics |
| --- | --- | --- |
| Replace with CAS | `POST <mount>/data/<path>` `{"options":{"cas":N},"data":{...}}` | New version only if current is N; replaces the whole map. |
| Patch | `PATCH <mount>/data/<path>`, `Content-Type: application/merge-patch+json` | Merges fields into a new version; needs the `patch` capability; key must exist. |
| Rollback | `vault kv rollback -version=N` | Writes a copy of version N as a new version. |
| Metadata | `POST`/`PATCH <mount>/metadata/<path>` | Changes settings; does not create a version. |

```bash
# Read the current version, then replace with CAS
CUR="$(vault kv metadata get -mount="$MOUNT" -format=json myapp/dev/api-token | jq -r '.data.current_version')"
vault kv put -mount="$MOUNT" -cas="$CUR" myapp/dev/api-token token=@/secure/path/new-token.txt

# Change one field, keep the others
vault kv patch -mount="$MOUNT" myapp/dev/db password=@/secure/path/new-password.txt

# Roll back to version 3 (creates a new version with v3's data)
vault kv rollback -mount="$MOUNT" -version=3 myapp/dev/api-token
```

A full `put` without `cas` silently drops fields not included in the new map; prefer `patch` for single-field changes and `cas` for replacements. Storing a new value does not rotate the credential at its source; for databases and clouds, consider dynamic secrets engines instead of static KV entries.

Verify a replacement without printing values:

```bash
cmp -s <(vault kv get -mount="$MOUNT" -field=token myapp/dev/api-token) /secure/path/new-token.txt \
  && printf 'Secret replacement verified.\n'
```

## 8. Delete, undelete, destroy, and purge

| Operation | Endpoint | Reversible | Effect |
| --- | --- | --- | --- |
| Soft-delete latest | `DELETE <mount>/data/<path>` | Yes | Latest version marked deleted; reads return 404. |
| Soft-delete versions | `POST <mount>/delete/<path>` `{"versions":[…]}` | Yes | Same for chosen versions. |
| Undelete | `POST <mount>/undelete/<path>` `{"versions":[…]}` | — | Restores soft-deleted versions. |
| Destroy | `PUT <mount>/destroy/<path>` `{"versions":[…]}` | **No** | Version data permanently removed; metadata remains. |
| Purge key | `DELETE <mount>/metadata/<path>` | **No** | All versions and metadata removed. |

```bash
# Inspect the exact target (metadata only)
vault kv metadata get -mount="$MOUNT" -format=json myapp/dev/api-token | jq '.data.current_version'

vault kv delete   -mount="$MOUNT" myapp/dev/api-token               # soft-delete latest
vault kv undelete -mount="$MOUNT" -versions=4 myapp/dev/api-token   # restore v4
vault kv destroy  -mount="$MOUNT" -versions=2,3 myapp/dev/api-token # permanent, chosen versions
vault kv metadata delete -mount="$MOUNT" myapp/dev/api-token        # permanent, everything
```

Soft delete is not destruction: the data still exists and anyone with `undelete` can restore it. When the goal is to eliminate a leaked value, **destroy** the affected versions after rotating. Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Each program is complete and self-checking. Expected output:

```text
created: secret/myapp/dev/crud-check version 1
updated: version 2
soft-deleted latest version
```

A second run against the same path fails at create with the CAS error, which is the intended create-only behavior (the soft-deleted key still exists). Use `PURGE_AFTER_DELETE=1` to remove it completely.

### 9.1 Go (official client)

`go get github.com/hashicorp/vault/api github.com/hashicorp/vault/api/auth/approle`. `vault.DefaultConfig()` reads `VAULT_ADDR`, `VAULT_CACERT`, `VAULT_NAMESPACE`, and `VAULT_TOKEN`; `KVv2` wraps the `data/` and `metadata/` paths; `WithCheckAndSet` sets `options.cas`.

```go
// HashiCorp Vault KV v2 CRUD with the official Go client (github.com/hashicorp/vault/api).
// Authentication: an existing VAULT_TOKEN (e.g. from Vault Agent), or AppRole with the
// SecretID read from a file (VAULT_ROLE_ID + VAULT_SECRET_ID_FILE).
package main

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"log"
	"os"
	"time"

	vault "github.com/hashicorp/vault/api"
	"github.com/hashicorp/vault/api/auth/approle"
)

type Store struct{ kv *vault.KVv2 }

func login(ctx context.Context, client *vault.Client) error {
	if client.Token() != "" { // DefaultConfig/NewClient picked up VAULT_TOKEN
		return nil
	}
	roleID, secretIDFile := os.Getenv("VAULT_ROLE_ID"), os.Getenv("VAULT_SECRET_ID_FILE")
	if roleID == "" || secretIDFile == "" {
		return errors.New("set VAULT_TOKEN, or VAULT_ROLE_ID and VAULT_SECRET_ID_FILE")
	}
	auth, err := approle.NewAppRoleAuth(roleID, &approle.SecretID{FromFile: secretIDFile})
	if err != nil {
		return err
	}
	secret, err := client.Auth().Login(ctx, auth) // sets the client token on success
	if err != nil {
		return fmt.Errorf("approle login: %w", err)
	}
	if secret == nil || secret.Auth == nil {
		return errors.New("approle login returned no auth info")
	}
	return nil
}

// Create writes version 1 with cas=0, which Vault rejects if the path already has data.
func (s *Store) Create(ctx context.Context, path, value string) (int, error) {
	out, err := s.kv.Put(ctx, path, map[string]any{"value": value}, vault.WithCheckAndSet(0))
	if err != nil {
		return 0, fmt.Errorf("create (cas=0) %s: %w", path, err)
	}
	return out.VersionMetadata.Version, nil
}

// Read returns the latest version's "value" field and its version number.
func (s *Store) Read(ctx context.Context, path string) (string, int, error) {
	sec, err := s.kv.Get(ctx, path)
	if errors.Is(err, vault.ErrSecretNotFound) {
		return "", 0, fmt.Errorf("%s not found (or latest version deleted): %w", path, err)
	}
	if err != nil {
		return "", 0, err
	}
	v, ok := sec.Data["value"].(string)
	if !ok {
		return "", 0, errors.New(`secret has no string "value" field`)
	}
	return v, sec.VersionMetadata.Version, nil
}

// Update writes a new version only if the current version is still `expected` (check-and-set).
func (s *Store) Update(ctx context.Context, path, value string, expected int) (int, error) {
	out, err := s.kv.Put(ctx, path, map[string]any{"value": value}, vault.WithCheckAndSet(expected))
	if err != nil {
		return 0, fmt.Errorf("update (cas=%d) %s: %w", expected, path, err)
	}
	return out.VersionMetadata.Version, nil
}

// Delete soft-deletes the latest version (recoverable with Undelete).
func (s *Store) Delete(ctx context.Context, path string) error { return s.kv.Delete(ctx, path) }

// Purge removes all versions and metadata permanently.
func (s *Store) Purge(ctx context.Context, path string) error { return s.kv.DeleteMetadata(ctx, path) }

func randomValue() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		log.Fatal("csprng: ", err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func equal(a, b string) bool { return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1 }

func main() {
	path := os.Getenv("SECRET_PATH") // e.g. myapp/dev/crud-check
	mount := os.Getenv("VAULT_KV_MOUNT")
	if mount == "" {
		mount = "secret"
	}
	if path == "" {
		log.Fatal("set SECRET_PATH (and VAULT_ADDR)")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	// DefaultConfig reads VAULT_ADDR, VAULT_CACERT, VAULT_NAMESPACE, VAULT_TOKEN, etc.
	client, err := vault.NewClient(vault.DefaultConfig())
	if err != nil {
		log.Fatal(err)
	}
	if err := login(ctx, client); err != nil {
		log.Fatal(err)
	}
	store := &Store{kv: client.KVv2(mount)}

	v1 := randomValue()
	ver, err := store.Create(ctx, path, v1)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("created:", mount+"/"+path, "version", ver)
	got, cur, err := store.Read(ctx, path)
	if err != nil || !equal(got, v1) {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	if ver, err = store.Update(ctx, path, v2, cur); err != nil {
		log.Fatal(err)
	}
	if got, _, err = store.Read(ctx, path); err != nil || !equal(got, v2) {
		log.Fatal("read-back after update failed: ", err)
	}
	fmt.Println("updated: version", ver)

	if err := store.Delete(ctx, path); err != nil {
		log.Fatal(err)
	}
	fmt.Println("soft-deleted latest version")
	if os.Getenv("PURGE_AFTER_DELETE") == "1" {
		if err := store.Purge(ctx, path); err != nil {
			log.Fatal(err)
		}
		fmt.Println("purged all versions and metadata")
	}
}
```

### 9.2 Rust

`Cargo.toml`:

```toml
[package]
name = "vault-kv2-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
reqwest = { version = "0.12", default-features = false, features = ["json", "rustls-tls"] }
serde_json = "1"
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
getrandom = "0.3"
base64 = "0.22"
zeroize = "1"
```

`reqwest` with rustls; `https_only` is enforced except for a loopback Agent/Proxy listener. Token and values live in `Zeroizing`.

```rust
//! HashiCorp Vault KV v2 CRUD over the HTTP API with reqwest (HashiCorp ships no official Rust
//! client; `vaultrs` is a community alternative). Auth: VAULT_TOKEN, or AppRole with the
//! SecretID read from VAULT_SECRET_ID_FILE.
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use reqwest::{Client, Method, StatusCode};
use serde_json::{json, Value};
use std::{env, error::Error, time::Duration};
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

struct Vault {
    http: Client,
    addr: String,
    token: Zeroizing<String>,
    namespace: Option<String>,
    mount: String,
}

impl Vault {
    async fn connect() -> Res<Self> {
        let addr = env::var("VAULT_ADDR").map_err(|_| "set VAULT_ADDR")?.trim_end_matches('/').to_string();
        // Plain HTTP only to a loopback Vault Agent/Proxy listener; TLS everywhere else.
        let loopback = addr.starts_with("http://127.0.0.1:") || addr.starts_with("http://localhost:");
        let http = Client::builder().timeout(Duration::from_secs(30)).https_only(!loopback).build()?;
        let namespace = env::var("VAULT_NAMESPACE").ok();
        let mount = env::var("VAULT_KV_MOUNT").unwrap_or_else(|_| "secret".into());
        let token = match env::var("VAULT_TOKEN") {
            Ok(t) => Zeroizing::new(t),
            Err(_) => {
                let role_id = env::var("VAULT_ROLE_ID").map_err(|_| "set VAULT_TOKEN or VAULT_ROLE_ID")?;
                let file = env::var("VAULT_SECRET_ID_FILE").map_err(|_| "set VAULT_SECRET_ID_FILE")?;
                let secret_id = Zeroizing::new(std::fs::read_to_string(file)?.trim().to_string());
                let mut req = http.post(format!("{addr}/v1/auth/approle/login"))
                    .json(&json!({ "role_id": role_id, "secret_id": secret_id.as_str() }));
                if let Some(ns) = &namespace { req = req.header("X-Vault-Namespace", ns); }
                let resp = req.send().await?;
                if !resp.status().is_success() {
                    return Err(format!("approle login failed: HTTP {}", resp.status()).into());
                }
                let body: Value = resp.json().await?;
                Zeroizing::new(body["auth"]["client_token"].as_str().ok_or("no client_token")?.to_string())
            }
        };
        Ok(Self { http, addr, token, namespace, mount })
    }

    async fn call(&self, method: Method, path: &str, body: Option<Value>) -> Res<(StatusCode, Value)> {
        let mut req = self.http.request(method, format!("{}/v1/{}", self.addr, path))
            .header("X-Vault-Token", self.token.as_str());
        if let Some(ns) = &self.namespace { req = req.header("X-Vault-Namespace", ns); }
        if let Some(b) = body { req = req.json(&b); }
        let resp = req.send().await?;
        let status = resp.status();
        let text = Zeroizing::new(resp.text().await?);
        let json = if text.is_empty() { Value::Null } else { serde_json::from_str(&text)? };
        Ok((status, json))
    }

    fn check(path: &str) -> Res<&str> {
        let ok = !path.is_empty()
            && path.split('/').all(|s| !s.is_empty() && s != "." && s != "..")
            && path.chars().all(|c| c.is_ascii_alphanumeric() || "/_-.".contains(c));
        if ok { Ok(path) } else { Err("invalid secret path".into()) }
    }

    /// Write a version with check-and-set. cas=0 means "only if the path has no data" (create).
    async fn write(&self, path: &str, value: &str, cas: u64) -> Res<u64> {
        let (status, body) = self.call(Method::POST, &format!("{}/data/{}", self.mount, Self::check(path)?),
            Some(json!({ "options": { "cas": cas }, "data": { "value": value } }))).await?;
        if !status.is_success() {
            // A cas mismatch (including cas=0 on an existing path) is HTTP 400.
            return Err(format!("write {path} (cas={cas}) failed: HTTP {status} {}", body["errors"]).into());
        }
        Ok(body["data"]["version"].as_u64().unwrap_or_default())
    }

    async fn create(&self, path: &str, value: &str) -> Res<u64> { self.write(path, value, 0).await }

    async fn update(&self, path: &str, value: &str, expected_version: u64) -> Res<u64> {
        self.write(path, value, expected_version).await
    }

    /// Read the latest version: (value, version).
    async fn read(&self, path: &str) -> Res<(Zeroizing<String>, u64)> {
        let (status, mut body) = self.call(Method::GET, &format!("{}/data/{}", self.mount, Self::check(path)?), None).await?;
        if status == StatusCode::NOT_FOUND {
            return Err(format!("{path} not found or latest version deleted").into());
        }
        if !status.is_success() {
            return Err(format!("read {path} failed: HTTP {status}").into());
        }
        let version = body["data"]["metadata"]["version"].as_u64().unwrap_or_default();
        let value = match body["data"]["data"]["value"].take() {
            Value::String(s) => Zeroizing::new(s),
            _ => return Err(r#"secret has no string "value" field"#.into()),
        };
        Ok((value, version))
    }

    /// Soft-delete the latest version (undo with POST {mount}/undelete/{path}).
    async fn delete(&self, path: &str) -> Res<()> {
        let (status, _) = self.call(Method::DELETE, &format!("{}/data/{}", self.mount, Self::check(path)?), None).await?;
        if status != StatusCode::NO_CONTENT { return Err(format!("delete failed: HTTP {status}").into()); }
        Ok(())
    }

    /// Permanently remove all versions and metadata.
    async fn purge(&self, path: &str) -> Res<()> {
        let (status, _) = self.call(Method::DELETE, &format!("{}/metadata/{}", self.mount, Self::check(path)?), None).await?;
        if status != StatusCode::NO_CONTENT { return Err(format!("purge failed: HTTP {status}").into()); }
        Ok(())
    }
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
    let path = env::var("SECRET_PATH").map_err(|_| "set SECRET_PATH")?;
    let vault = Vault::connect().await?;

    let v1 = random_value();
    let ver = vault.create(&path, &v1).await?;
    println!("created: {}/{path} version {ver}", vault.mount);
    let (got, current) = vault.read(&path).await?;
    if !ct_eq(&got, &v1) { return Err("read-back after create did not match".into()); }

    let v2 = random_value();
    let ver = vault.update(&path, &v2, current).await?;
    let (got, _) = vault.read(&path).await?;
    if !ct_eq(&got, &v2) { return Err("read-back after update did not match".into()); }
    println!("updated: version {ver}");

    vault.delete(&path).await?;
    println!("soft-deleted latest version");
    if env::var("PURGE_AFTER_DELETE").as_deref() == Ok("1") {
        vault.purge(&path).await?;
        println!("purged all versions and metadata");
    }
    Ok(())
}
```

### 9.3 PHP

ext-curl only. `VAULT_CACERT` is honored through `CURLOPT_CAINFO`.

```php
<?php
// HashiCorp Vault KV v2 CRUD over the HTTP API with ext-curl (HashiCorp ships no official PHP client).
// Auth: VAULT_TOKEN, or AppRole with the SecretID read from VAULT_SECRET_ID_FILE.
declare(strict_types=1);

final class VaultKv
{
    private string $token;

    public function __construct(
        private string $addr,
        private ?string $namespace = null,
        public readonly string $mount = 'secret',
        private ?string $caFile = null,
    ) {
        $loopback = (bool) preg_match('#^http://(127\.0\.0\.1|localhost):#', $addr);
        if (!str_starts_with($addr, 'https://') && !$loopback) {
            throw new InvalidArgumentException('VAULT_ADDR must use https');
        }
        $this->addr = rtrim($addr, '/');
        $this->token = getenv('VAULT_TOKEN') ?: $this->appRoleLogin();
    }

    private function appRoleLogin(): string
    {
        $secretId = trim((string) file_get_contents(getenv('VAULT_SECRET_ID_FILE') ?: throw new RuntimeException('set VAULT_TOKEN or VAULT_SECRET_ID_FILE')));
        $r = $this->request('POST', 'auth/approle/login', ['role_id' => getenv('VAULT_ROLE_ID'), 'secret_id' => $secretId], false);
        if ($r['status'] !== 200 || !isset($r['json']['auth']['client_token'])) {
            throw new RuntimeException("approle login failed: HTTP {$r['status']}");
        }
        return $r['json']['auth']['client_token'];
    }

    /** @return array{status:int, json:?array} */
    private function request(string $method, string $path, ?array $body = null, bool $auth = true): array
    {
        $headers = ['Content-Type: application/json'];
        if ($auth) {
            $headers[] = 'X-Vault-Token: ' . $this->token;
        }
        if ($this->namespace) {
            $headers[] = 'X-Vault-Namespace: ' . $this->namespace;
        }
        $ch = curl_init("{$this->addr}/v1/{$path}");
        $opts = [
            CURLOPT_CUSTOMREQUEST  => $method,
            CURLOPT_HTTPHEADER     => $headers,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 30,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
        ];
        if ($this->caFile) {
            $opts[CURLOPT_CAINFO] = $this->caFile;   // private PKI for Vault (VAULT_CACERT)
        }
        if ($body !== null) {
            $opts[CURLOPT_POSTFIELDS] = json_encode($body, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
        }
        curl_setopt_array($ch, $opts);
        $out = curl_exec($ch);
        if ($out === false) {
            throw new RuntimeException('transport error: ' . curl_error($ch));
        }
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        return ['status' => $status, 'json' => $out === '' ? null : json_decode((string) $out, true)];
    }

    private static function check(string $path): string
    {
        if (!preg_match('#^[A-Za-z0-9_.\-/]+$#', $path)) {
            throw new InvalidArgumentException('invalid secret path');
        }
        foreach (explode('/', $path) as $seg) {
            if ($seg === '' || $seg === '.' || $seg === '..') {
                throw new InvalidArgumentException('invalid secret path');
            }
        }
        return $path;
    }

    /** Write with check-and-set; cas=0 means "only if the path has no data". Returns the version. */
    private function write(string $path, string $value, int $cas): int
    {
        $r = $this->request('POST', "{$this->mount}/data/" . self::check($path), [
            'options' => ['cas' => $cas],
            'data'    => ['value' => $value],
        ]);
        if ($r['status'] !== 200) {
            $errors = json_encode($r['json']['errors'] ?? []);
            throw new RuntimeException("write {$path} (cas={$cas}) failed: HTTP {$r['status']} {$errors}");
        }
        return (int) $r['json']['data']['version'];
    }

    public function create(string $path, string $value): int
    {
        return $this->write($path, $value, 0);
    }

    public function update(string $path, string $value, int $expectedVersion): int
    {
        return $this->write($path, $value, $expectedVersion);
    }

    /** @return array{0:string, 1:int} value and version of the latest version */
    public function read(string $path): array
    {
        $r = $this->request('GET', "{$this->mount}/data/" . self::check($path));
        if ($r['status'] === 404) {
            throw new RuntimeException("{$path} not found or latest version deleted");
        }
        $value = $r['json']['data']['data']['value'] ?? null;
        if ($r['status'] !== 200 || !is_string($value)) {
            throw new RuntimeException("read {$path} failed: HTTP {$r['status']}");
        }
        return [$value, (int) $r['json']['data']['metadata']['version']];
    }

    /** Soft-delete the latest version (undo with POST {mount}/undelete/{path}). */
    public function delete(string $path): void
    {
        $r = $this->request('DELETE', "{$this->mount}/data/" . self::check($path));
        if ($r['status'] !== 204) {
            throw new RuntimeException("delete failed: HTTP {$r['status']}");
        }
    }

    /** Permanently remove all versions and metadata. */
    public function purge(string $path): void
    {
        $r = $this->request('DELETE', "{$this->mount}/metadata/" . self::check($path));
        if ($r['status'] !== 204) {
            throw new RuntimeException("purge failed: HTTP {$r['status']}");
        }
    }
}

$path = getenv('SECRET_PATH') ?: exit("set SECRET_PATH\n");
$vault = new VaultKv(
    getenv('VAULT_ADDR') ?: exit("set VAULT_ADDR\n"),
    getenv('VAULT_NAMESPACE') ?: null,
    getenv('VAULT_KV_MOUNT') ?: 'secret',
    getenv('VAULT_CACERT') ?: null,
);
$random = fn (): string => rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');

$v1 = $random();
echo "created: {$vault->mount}/{$path} version " . $vault->create($path, $v1) . "\n";
[$got, $current] = $vault->read($path);
hash_equals($v1, $got) || exit("read-back after create did not match\n");

$v2 = $random();
echo 'updated: version ' . $vault->update($path, $v2, $current) . "\n";
hash_equals($v2, $vault->read($path)[0]) || exit("read-back after update did not match\n");
unset($v1, $v2, $got);

$vault->delete($path);
echo "soft-deleted latest version\n";
if (getenv('PURGE_AFTER_DELETE') === '1') {
    $vault->purge($path);
    echo "purged all versions and metadata\n";
}
```

### 9.4 C#

No packages: `HttpClient`, `System.Text.Json.Nodes`, and `CryptographicOperations`. Built with .NET 8. For private PKI, install the CA into the OS trust store or configure `SocketsHttpHandler.SslOptions`; never disable validation.

```csharp
// HashiCorp Vault KV v2 CRUD over the HTTP API with HttpClient + System.Text.Json (no packages).
// HashiCorp ships no official .NET client; VaultSharp is the common community alternative.
// Auth: VAULT_TOKEN, or AppRole with the SecretID read from VAULT_SECRET_ID_FILE.
using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

public sealed class VaultKv
{
    private readonly HttpClient _http;
    public string Mount { get; }

    private VaultKv(HttpClient http, string mount) { _http = http; Mount = mount; }

    public static async Task<VaultKv> FromEnvironmentAsync(CancellationToken ct)
    {
        var addr = (Environment.GetEnvironmentVariable("VAULT_ADDR") ?? throw new InvalidOperationException("set VAULT_ADDR")).TrimEnd('/');
        var loopback = Regex.IsMatch(addr, @"^http://(127\.0\.0\.1|localhost):");
        if (!addr.StartsWith("https://", StringComparison.Ordinal) && !loopback)
            throw new InvalidOperationException("VAULT_ADDR must use https");
        var http = new HttpClient { BaseAddress = new Uri(addr + "/v1/"), Timeout = TimeSpan.FromSeconds(30) };
        if (Environment.GetEnvironmentVariable("VAULT_NAMESPACE") is { Length: > 0 } ns)
            http.DefaultRequestHeaders.Add("X-Vault-Namespace", ns);

        var token = Environment.GetEnvironmentVariable("VAULT_TOKEN");
        if (string.IsNullOrEmpty(token))
        {
            var secretIdFile = Environment.GetEnvironmentVariable("VAULT_SECRET_ID_FILE")
                               ?? throw new InvalidOperationException("set VAULT_TOKEN or VAULT_SECRET_ID_FILE");
            var secretId = (await File.ReadAllTextAsync(secretIdFile, ct)).Trim();
            using var login = await http.PostAsJsonAsync("auth/approle/login",
                new { role_id = Environment.GetEnvironmentVariable("VAULT_ROLE_ID"), secret_id = secretId }, ct);
            if (!login.IsSuccessStatusCode) throw new InvalidOperationException($"approle login failed: HTTP {(int)login.StatusCode}");
            var auth = JsonNode.Parse(await login.Content.ReadAsStringAsync(ct))!;
            token = auth["auth"]!["client_token"]!.GetValue<string>();
        }
        http.DefaultRequestHeaders.Add("X-Vault-Token", token);
        return new VaultKv(http, Environment.GetEnvironmentVariable("VAULT_KV_MOUNT") ?? "secret");
    }

    private static string Check(string path) =>
        Regex.IsMatch(path, @"^[A-Za-z0-9_.\-/]+$") && path.Split('/').All(s => s is not ("" or "." or ".."))
            ? path : throw new ArgumentException("invalid secret path");

    /// <summary>Write with check-and-set; cas=0 means "only if the path has no data".</summary>
    private async Task<int> WriteAsync(string path, string value, int cas, CancellationToken ct)
    {
        using var resp = await _http.PostAsJsonAsync($"{Mount}/data/{Check(path)}",
            new { options = new { cas }, data = new { value } }, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        if (resp.StatusCode != HttpStatusCode.OK)
        {
            var errors = JsonNode.Parse(body)?["errors"]?.ToJsonString() ?? "[]";   // never echoes data
            throw new InvalidOperationException($"write {path} (cas={cas}) failed: HTTP {(int)resp.StatusCode} {errors}");
        }
        return JsonNode.Parse(body)!["data"]!["version"]!.GetValue<int>();
    }

    public Task<int> CreateAsync(string path, string value, CancellationToken ct) => WriteAsync(path, value, 0, ct);

    public Task<int> UpdateAsync(string path, string value, int expectedVersion, CancellationToken ct) =>
        WriteAsync(path, value, expectedVersion, ct);

    public async Task<(string Value, int Version)> ReadAsync(string path, CancellationToken ct)
    {
        using var resp = await _http.GetAsync($"{Mount}/data/{Check(path)}", ct);
        if (resp.StatusCode == HttpStatusCode.NotFound)
            throw new InvalidOperationException($"{path} not found or latest version deleted");
        resp.EnsureSuccessStatusCode();
        var data = JsonNode.Parse(await resp.Content.ReadAsStringAsync(ct))!["data"]!;
        var value = data["data"]?["value"]?.GetValue<string>() ?? throw new InvalidOperationException("no \"value\" field");
        return (value, data["metadata"]!["version"]!.GetValue<int>());
    }

    /// <summary>Soft-delete the latest version (undo: POST {mount}/undelete/{path}).</summary>
    public async Task DeleteAsync(string path, CancellationToken ct)
    {
        using var resp = await _http.DeleteAsync($"{Mount}/data/{Check(path)}", ct);
        if (resp.StatusCode != HttpStatusCode.NoContent) throw new InvalidOperationException($"delete failed: HTTP {(int)resp.StatusCode}");
    }

    /// <summary>Permanently remove all versions and metadata.</summary>
    public async Task PurgeAsync(string path, CancellationToken ct)
    {
        using var resp = await _http.DeleteAsync($"{Mount}/metadata/{Check(path)}", ct);
        if (resp.StatusCode != HttpStatusCode.NoContent) throw new InvalidOperationException($"purge failed: HTTP {(int)resp.StatusCode}");
    }
}

public static class Program
{
    static string RandomValue() =>
        Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    static bool FixedEquals(string a, string b) =>
        CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(a), Encoding.UTF8.GetBytes(b));

    public static async Task<int> Main()
    {
        var path = Environment.GetEnvironmentVariable("SECRET_PATH") ?? throw new InvalidOperationException("set SECRET_PATH");
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        var vault = await VaultKv.FromEnvironmentAsync(cts.Token);

        var v1 = RandomValue();
        Console.WriteLine($"created: {vault.Mount}/{path} version {await vault.CreateAsync(path, v1, cts.Token)}");
        var (got, current) = await vault.ReadAsync(path, cts.Token);
        if (!FixedEquals(v1, got)) throw new InvalidOperationException("read-back after create did not match");

        var v2 = RandomValue();
        var version = await vault.UpdateAsync(path, v2, current, cts.Token);
        if (!FixedEquals(v2, (await vault.ReadAsync(path, cts.Token)).Value))
            throw new InvalidOperationException("read-back after update did not match");
        Console.WriteLine($"updated: version {version}");

        await vault.DeleteAsync(path, cts.Token);
        Console.WriteLine("soft-deleted latest version");
        if (Environment.GetEnvironmentVariable("PURGE_AFTER_DELETE") == "1")
        {
            await vault.PurgeAsync(path, cts.Token);
            Console.WriteLine("purged all versions and metadata");
        }
        return 0;
    }
}
```

### 9.5 Java

`java.net.http.HttpClient` (Java 11+; records require 16+) and Jackson (`com.fasterxml.jackson.core:jackson-databind`). For private PKI, configure an `SSLContext` with your CA or use the JVM truststore.

```java
// HashiCorp Vault KV v2 CRUD over the HTTP API with java.net.http + Jackson.
// HashiCorp ships no official Java client; Spring Vault is the common alternative in Spring apps.
// Maven: com.fasterxml.jackson.core:jackson-databind
// Auth: VAULT_TOKEN, or AppRole with the SecretID read from VAULT_SECRET_ID_FILE.
package example;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.Base64;
import java.util.Map;
import java.util.regex.Pattern;

public final class VaultKvCrud {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Pattern PATH = Pattern.compile("^[A-Za-z0-9_.\\-/]+$");

    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
    private final String addr;
    private final String namespace;
    private final String token;
    final String mount;

    VaultKvCrud() throws IOException, InterruptedException {
        String a = System.getenv("VAULT_ADDR");
        if (a == null) throw new IllegalStateException("set VAULT_ADDR");
        this.addr = a.replaceAll("/+$", "");
        boolean loopback = addr.matches("^http://(127\\.0\\.0\\.1|localhost):.*");
        if (!addr.startsWith("https://") && !loopback) throw new IllegalStateException("VAULT_ADDR must use https");
        this.namespace = System.getenv("VAULT_NAMESPACE");
        this.mount = System.getenv().getOrDefault("VAULT_KV_MOUNT", "secret");
        String t = System.getenv("VAULT_TOKEN");
        this.token = (t != null && !t.isEmpty()) ? t : appRoleLogin();
    }

    private String appRoleLogin() throws IOException, InterruptedException {
        String secretId = Files.readString(Path.of(System.getenv("VAULT_SECRET_ID_FILE"))).trim();
        Response r = send("POST", "auth/approle/login",
                Map.of("role_id", System.getenv("VAULT_ROLE_ID"), "secret_id", secretId), false);
        if (r.status != 200) throw new IllegalStateException("approle login failed: HTTP " + r.status);
        return r.json.path("auth").path("client_token").asText();
    }

    private record Response(int status, JsonNode json) {}

    private Response send(String method, String path, Object body, boolean auth) throws IOException, InterruptedException {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(addr + "/v1/" + path))
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json")
                .method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofByteArray(JSON.writeValueAsBytes(body)));
        if (auth) b.header("X-Vault-Token", token);
        if (namespace != null && !namespace.isEmpty()) b.header("X-Vault-Namespace", namespace);
        HttpResponse<byte[]> resp = http.send(b.build(), HttpResponse.BodyHandlers.ofByteArray());
        JsonNode json = resp.body().length == 0 ? JSON.nullNode() : JSON.readTree(resp.body());
        return new Response(resp.statusCode(), json);
    }

    private static String check(String path) {
        if (!PATH.matcher(path).matches()) throw new IllegalArgumentException("invalid secret path");
        for (String seg : path.split("/", -1)) {
            if (seg.isEmpty() || seg.equals(".") || seg.equals("..")) throw new IllegalArgumentException("invalid secret path");
        }
        return path;
    }

    /** Write with check-and-set; cas=0 means "only if the path has no data". */
    private int write(String path, String value, int cas) throws IOException, InterruptedException {
        Response r = send("POST", mount + "/data/" + check(path),
                Map.of("options", Map.of("cas", cas), "data", Map.of("value", value)), true);
        if (r.status != 200) {
            throw new IllegalStateException("write " + path + " (cas=" + cas + ") failed: HTTP " + r.status + " " + r.json.path("errors"));
        }
        return r.json.path("data").path("version").asInt();
    }

    public int create(String path, String value) throws IOException, InterruptedException {
        return write(path, value, 0);
    }

    public int update(String path, String value, int expectedVersion) throws IOException, InterruptedException {
        return write(path, value, expectedVersion);
    }

    public record Secret(String value, int version) {}

    public Secret read(String path) throws IOException, InterruptedException {
        Response r = send("GET", mount + "/data/" + check(path), null, true);
        if (r.status == 404) throw new IllegalStateException(path + " not found or latest version deleted");
        JsonNode v = r.json.path("data").path("data").path("value");
        if (r.status != 200 || !v.isTextual()) throw new IllegalStateException("read " + path + " failed: HTTP " + r.status);
        return new Secret(v.asText(), r.json.path("data").path("metadata").path("version").asInt());
    }

    /** Soft-delete the latest version (undo: POST {mount}/undelete/{path}). */
    public void delete(String path) throws IOException, InterruptedException {
        Response r = send("DELETE", mount + "/data/" + check(path), null, true);
        if (r.status != 204) throw new IllegalStateException("delete failed: HTTP " + r.status);
    }

    /** Permanently remove all versions and metadata. */
    public void purge(String path) throws IOException, InterruptedException {
        Response r = send("DELETE", mount + "/metadata/" + check(path), null, true);
        if (r.status != 204) throw new IllegalStateException("purge failed: HTTP " + r.status);
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

    public static void main(String[] args) throws Exception {
        String path = System.getenv("SECRET_PATH");
        if (path == null) throw new IllegalArgumentException("set SECRET_PATH");
        VaultKvCrud vault = new VaultKvCrud();

        String v1 = randomValue();
        System.out.println("created: " + vault.mount + "/" + path + " version " + vault.create(path, v1));
        Secret first = vault.read(path);
        if (!fixedEquals(v1, first.value())) throw new IllegalStateException("read-back after create failed");

        String v2 = randomValue();
        int version = vault.update(path, v2, first.version());
        if (!fixedEquals(v2, vault.read(path).value())) throw new IllegalStateException("read-back after update failed");
        System.out.println("updated: version " + version);

        vault.delete(path);
        System.out.println("soft-deleted latest version");
        if ("1".equals(System.getenv("PURGE_AFTER_DELETE"))) {
            vault.purge(path);
            System.out.println("purged all versions and metadata");
        }
    }
}
```

### 9.6 Swift

Foundation only, ephemeral `URLSession`. For private PKI on Apple platforms, add the CA to the system/MDM trust store; on Linux, to the OS bundle.

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
// HashiCorp Vault KV v2 CRUD in Swift over the HTTP API (HashiCorp ships no Swift client).
// Auth: VAULT_TOKEN, or AppRole with the SecretID read from VAULT_SECRET_ID_FILE.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

enum VaultError: Error { case http(Int, String), invalid(String) }

final class VaultKv {
    let addr: String
    let mount: String
    private let namespace: String?
    private var token = ""
    private let session = URLSession(configuration: .ephemeral)

    init() async throws {
        let env = ProcessInfo.processInfo.environment
        guard var a = env["VAULT_ADDR"] else { throw VaultError.invalid("set VAULT_ADDR") }
        while a.hasSuffix("/") { a.removeLast() }
        let loopback = a.hasPrefix("http://127.0.0.1:") || a.hasPrefix("http://localhost:")
        guard a.hasPrefix("https://") || loopback else { throw VaultError.invalid("VAULT_ADDR must use https") }
        addr = a
        mount = env["VAULT_KV_MOUNT"] ?? "secret"
        namespace = env["VAULT_NAMESPACE"]
        if let t = env["VAULT_TOKEN"], !t.isEmpty {
            token = t
        } else {
            guard let roleID = env["VAULT_ROLE_ID"], let file = env["VAULT_SECRET_ID_FILE"] else {
                throw VaultError.invalid("set VAULT_TOKEN, or VAULT_ROLE_ID and VAULT_SECRET_ID_FILE")
            }
            let secretID = try String(contentsOfFile: file, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            let (status, json) = try await call("POST", "auth/approle/login",
                                                body: ["role_id": roleID, "secret_id": secretID], auth: false)
            guard status == 200, let auth = json["auth"] as? [String: Any],
                  let t = auth["client_token"] as? String else { throw VaultError.http(status, "approle login") }
            token = t
        }
    }

    private func call(_ method: String, _ path: String, body: [String: Any]? = nil,
                      auth: Bool = true) async throws -> (Int, [String: Any]) {
        var req = URLRequest(url: URL(string: "\(addr)/v1/\(path)")!)
        req.httpMethod = method
        req.timeoutInterval = 30
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if auth { req.setValue(token, forHTTPHeaderField: "X-Vault-Token") }
        if let namespace { req.setValue(namespace, forHTTPHeaderField: "X-Vault-Namespace") }
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = data.isEmpty ? [:] : ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:])
        return (status, json)
    }

    private static func check(_ path: String) throws -> String {
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-/")
        let segments = path.split(separator: "/", omittingEmptySubsequences: false)
        guard !path.isEmpty, path.unicodeScalars.allSatisfy(allowed.contains),
              segments.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw VaultError.invalid("invalid secret path")
        }
        return path
    }

    /// Write with check-and-set; cas=0 means "only if the path has no data". Returns the version.
    private func write(_ path: String, _ value: String, cas: Int) async throws -> Int {
        let (status, json) = try await call("POST", "\(mount)/data/\(try Self.check(path))",
                                            body: ["options": ["cas": cas], "data": ["value": value]])
        guard status == 200, let data = json["data"] as? [String: Any], let version = data["version"] as? Int else {
            throw VaultError.http(status, "write \(path) (cas=\(cas)): \(json["errors"] ?? [])")
        }
        return version
    }

    func create(_ path: String, _ value: String) async throws -> Int { try await write(path, value, cas: 0) }

    func update(_ path: String, _ value: String, expectedVersion: Int) async throws -> Int {
        try await write(path, value, cas: expectedVersion)
    }

    func read(_ path: String) async throws -> (value: String, version: Int) {
        let (status, json) = try await call("GET", "\(mount)/data/\(try Self.check(path))")
        if status == 404 { throw VaultError.http(404, "\(path) not found or latest version deleted") }
        guard status == 200, let data = json["data"] as? [String: Any],
              let kv = data["data"] as? [String: Any], let value = kv["value"] as? String,
              let md = data["metadata"] as? [String: Any], let version = md["version"] as? Int else {
            throw VaultError.http(status, "read \(path)")
        }
        return (value, version)
    }

    /// Soft-delete the latest version (undo: POST {mount}/undelete/{path}).
    func delete(_ path: String) async throws {
        let (status, _) = try await call("DELETE", "\(mount)/data/\(try Self.check(path))")
        guard status == 204 else { throw VaultError.http(status, "delete") }
    }

    /// Permanently remove all versions and metadata.
    func purge(_ path: String) async throws {
        let (status, _) = try await call("DELETE", "\(mount)/metadata/\(try Self.check(path))")
        guard status == 204 else { throw VaultError.http(status, "purge") }
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

guard let path = ProcessInfo.processInfo.environment["SECRET_PATH"] else { fatalError("set SECRET_PATH") }
let vault = try await VaultKv()

let v1 = randomValue()
print("created: \(vault.mount)/\(path) version \(try await vault.create(path, v1))")
let first = try await vault.read(path)
guard fixedEquals(v1, first.value) else { fatalError("read-back after create failed") }

let v2 = randomValue()
let version = try await vault.update(path, v2, expectedVersion: first.version)
guard fixedEquals(v2, try await vault.read(path).value) else { fatalError("read-back after update failed") }
print("updated: version \(version)")

try await vault.delete(path)
print("soft-deleted latest version")
if ProcessInfo.processInfo.environment["PURGE_AFTER_DELETE"] == "1" {
    try await vault.purge(path)
    print("purged all versions and metadata")
}
```

### 9.7 Python

`pip install hvac`. `hvac.Client()` reads `VAULT_ADDR`, `VAULT_TOKEN`, and `VAULT_CACERT`; `create_or_update_secret(..., cas=0)` gives create-only semantics and raises `InvalidRequest` on a CAS mismatch.

```python
"""HashiCorp Vault KV v2 CRUD with hvac (the de facto Python client; community-maintained).

pip install hvac
Auth: VAULT_TOKEN (e.g. from Vault Agent), or AppRole with the SecretID read from a file.
hvac.Client reads VAULT_ADDR, VAULT_TOKEN, VAULT_NAMESPACE and VAULT_CACERT from the environment.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys

import hvac
from hvac.exceptions import InvalidPath, InvalidRequest


class VaultKv:
    def __init__(self, client: hvac.Client, mount: str = "secret") -> None:
        self.client, self.mount = client, mount
        self.kv = client.secrets.kv.v2

    @classmethod
    def from_environment(cls) -> "VaultKv":
        client = hvac.Client(url=os.environ["VAULT_ADDR"], namespace=os.environ.get("VAULT_NAMESPACE"))
        if not client.token:
            with open(os.environ["VAULT_SECRET_ID_FILE"], encoding="utf-8") as fh:
                secret_id = fh.read().strip()
            client.auth.approle.login(role_id=os.environ["VAULT_ROLE_ID"], secret_id=secret_id)  # sets token
            del secret_id
        if not client.is_authenticated():
            raise RuntimeError("vault authentication failed")
        return cls(client, os.environ.get("VAULT_KV_MOUNT", "secret"))

    def create(self, path: str, value: str) -> int:
        """cas=0: Vault rejects the write if the path already holds data."""
        try:
            resp = self.kv.create_or_update_secret(path=path, secret={"value": value}, cas=0, mount_point=self.mount)
        except InvalidRequest as exc:
            raise RuntimeError(f"{path} already exists (create is not an upsert)") from exc
        return resp["data"]["version"]

    def read(self, path: str) -> tuple[str, int]:
        try:
            resp = self.kv.read_secret_version(path=path, mount_point=self.mount, raise_on_deleted_version=True)
        except InvalidPath as exc:
            raise RuntimeError(f"{path} not found or latest version deleted") from exc
        return resp["data"]["data"]["value"], resp["data"]["metadata"]["version"]

    def update(self, path: str, value: str, expected_version: int) -> int:
        """Check-and-set: fails if someone else wrote a newer version since our read."""
        resp = self.kv.create_or_update_secret(
            path=path, secret={"value": value}, cas=expected_version, mount_point=self.mount
        )
        return resp["data"]["version"]

    def delete(self, path: str) -> None:
        """Soft-delete the latest version (undo with undelete_secret_versions)."""
        self.kv.delete_latest_version_of_secret(path=path, mount_point=self.mount)

    def purge(self, path: str) -> None:
        """Permanently remove every version and the metadata."""
        self.kv.delete_metadata_and_all_versions(path=path, mount_point=self.mount)


def main() -> int:
    path = os.environ.get("SECRET_PATH")
    if not path:
        print("set SECRET_PATH (and VAULT_ADDR)", file=sys.stderr)
        return 2
    vault = VaultKv.from_environment()

    v1 = secrets.token_urlsafe(32)
    version = vault.create(path, v1)
    print(f"created: {vault.mount}/{path} version {version}")
    got, current = vault.read(path)
    if not hmac.compare_digest(v1, got):
        raise RuntimeError("read-back after create did not match")

    v2 = secrets.token_urlsafe(32)
    version = vault.update(path, v2, current)
    got, _ = vault.read(path)
    if not hmac.compare_digest(v2, got):
        raise RuntimeError("read-back after update did not match")
    print(f"updated: version {version}")

    vault.delete(path)
    print("soft-deleted latest version")
    if os.environ.get("PURGE_AFTER_DELETE") == "1":
        vault.purge(path)
        print("purged all versions and metadata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

Built-in `fetch` with `AbortSignal.timeout`. For private PKI, start Node with `NODE_EXTRA_CA_CERTS=/path/ca.pem`.

```typescript
// HashiCorp Vault KV v2 CRUD over the HTTP API with Node's built-in fetch (Node 18+).
// HashiCorp ships no official Node client; `node-vault` is a community alternative.
// Auth: VAULT_TOKEN, or AppRole with the SecretID read from VAULT_SECRET_ID_FILE.
import { readFile } from "node:fs/promises";
import { randomBytes, timingSafeEqual } from "node:crypto";

class VaultError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export class VaultKv {
  private constructor(
    private readonly addr: string,
    private readonly token: string,
    private readonly namespace: string | undefined,
    readonly mount: string,
  ) {}

  static async fromEnvironment(): Promise<VaultKv> {
    const addr = (process.env.VAULT_ADDR ?? "").replace(/\/+$/, "");
    if (!addr) throw new Error("set VAULT_ADDR");
    const loopback = /^http:\/\/(127\.0\.0\.1|localhost):/.test(addr);
    if (!addr.startsWith("https://") && !loopback) throw new Error("VAULT_ADDR must use https");
    const ns = process.env.VAULT_NAMESPACE;
    const mount = process.env.VAULT_KV_MOUNT ?? "secret";
    let token = process.env.VAULT_TOKEN;
    if (!token) {
      const secretId = (await readFile(process.env.VAULT_SECRET_ID_FILE ?? "", "utf8")).trim();
      const resp = await fetch(`${addr}/v1/auth/approle/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(ns ? { "X-Vault-Namespace": ns } : {}) },
        body: JSON.stringify({ role_id: process.env.VAULT_ROLE_ID, secret_id: secretId }),
        signal: AbortSignal.timeout(30_000),
      });
      if (!resp.ok) throw new VaultError("approle login failed", resp.status);
      token = ((await resp.json()) as { auth: { client_token: string } }).auth.client_token;
    }
    return new VaultKv(addr, token, ns, mount);
  }

  private static check(path: string): string {
    const ok = /^[A-Za-z0-9_.\-/]+$/.test(path) && path.split("/").every((s) => s !== "" && s !== "." && s !== "..");
    if (!ok) throw new Error("invalid secret path");
    return path;
  }

  private async call(method: string, path: string, body?: unknown): Promise<{ status: number; json: any }> {
    const resp = await fetch(`${this.addr}/v1/${path}`, {
      method,
      headers: {
        "X-Vault-Token": this.token,
        ...(this.namespace ? { "X-Vault-Namespace": this.namespace } : {}),
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    });
    const text = await resp.text();
    return { status: resp.status, json: text ? JSON.parse(text) : null };
  }

  /** Write with check-and-set. cas=0 means "only if the path has no data" (create). */
  private async write(path: string, value: string, cas: number): Promise<number> {
    const r = await this.call("POST", `${this.mount}/data/${VaultKv.check(path)}`, {
      options: { cas },
      data: { value },
    });
    if (r.status !== 200) {
      // cas mismatch (including cas=0 on an existing path) is HTTP 400; errors never echo data.
      throw new VaultError(`write ${path} (cas=${cas}) failed: ${JSON.stringify(r.json?.errors)}`, r.status);
    }
    return r.json.data.version as number;
  }

  create(path: string, value: string): Promise<number> {
    return this.write(path, value, 0);
  }

  update(path: string, value: string, expectedVersion: number): Promise<number> {
    return this.write(path, value, expectedVersion);
  }

  async read(path: string): Promise<{ value: string; version: number }> {
    const r = await this.call("GET", `${this.mount}/data/${VaultKv.check(path)}`);
    if (r.status === 404) throw new VaultError(`${path} not found or latest version deleted`, 404);
    if (r.status !== 200) throw new VaultError(`read ${path} failed`, r.status);
    const value = r.json?.data?.data?.value;
    if (typeof value !== "string") throw new Error('secret has no string "value" field');
    return { value, version: r.json.data.metadata.version as number };
  }

  /** Soft-delete the latest version (undo: POST {mount}/undelete/{path}). */
  async delete(path: string): Promise<void> {
    const r = await this.call("DELETE", `${this.mount}/data/${VaultKv.check(path)}`);
    if (r.status !== 204) throw new VaultError("delete failed", r.status);
  }

  /** Permanently remove all versions and metadata. */
  async purge(path: string): Promise<void> {
    const r = await this.call("DELETE", `${this.mount}/metadata/${VaultKv.check(path)}`);
    if (r.status !== 204) throw new VaultError("purge failed", r.status);
  }
}

const randomValue = (): string => randomBytes(32).toString("base64url");
const same = (a: string, b: string): boolean => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

async function main(): Promise<void> {
  const path = process.env.SECRET_PATH;
  if (!path) throw new Error("set SECRET_PATH");
  const vault = await VaultKv.fromEnvironment();

  const v1 = randomValue();
  let version = await vault.create(path, v1);
  console.log(`created: ${vault.mount}/${path} version ${version}`);
  const first = await vault.read(path);
  if (!same(v1, first.value)) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  version = await vault.update(path, v2, first.version);
  if (!same(v2, (await vault.read(path)).value)) throw new Error("read-back after update did not match");
  console.log(`updated: version ${version}`);

  await vault.delete(path);
  console.log("soft-deleted latest version");
  if (process.env.PURGE_AFTER_DELETE === "1") {
    await vault.purge(path);
    console.log("purged all versions and metadata");
  }
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? `${err.name}: ${err.message}` : "unknown error");
  process.exitCode = 1;
});
```

### 9.9 C++

`g++ -std=c++17 main.cpp $(pkg-config --cflags --libs libcurl openssl)` with nlohmann/json (header-only).

```cpp
// HashiCorp Vault KV v2 CRUD over the HTTP API with libcurl + nlohmann/json (C++17).
// HashiCorp ships no official C++ client.
//   g++ -std=c++17 -O2 main.cpp -o vault_crud $(pkg-config --cflags --libs libcurl openssl)
// Auth: VAULT_TOKEN, or AppRole with the SecretID read from VAULT_SECRET_ID_FILE.
#include <curl/curl.h>
#include <nlohmann/json.hpp>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>

using json = nlohmann::json;

static void wipe(std::string& s) { OPENSSL_cleanse(s.data(), s.size()); s.clear(); }

class VaultKv {
 public:
  VaultKv() {
    const char* a = std::getenv("VAULT_ADDR");
    if (!a) throw std::runtime_error("set VAULT_ADDR");
    addr_ = a;
    while (!addr_.empty() && addr_.back() == '/') addr_.pop_back();
    bool loopback = std::regex_search(addr_, std::regex("^http://(127\\.0\\.0\\.1|localhost):"));
    if (addr_.rfind("https://", 0) != 0 && !loopback) throw std::runtime_error("VAULT_ADDR must use https");
    https_only_ = !loopback;
    if (const char* ns = std::getenv("VAULT_NAMESPACE")) namespace_ = ns;
    if (const char* m = std::getenv("VAULT_KV_MOUNT")) mount = m;
    if (const char* ca = std::getenv("VAULT_CACERT")) ca_file_ = ca;
    if (const char* t = std::getenv("VAULT_TOKEN"); t && *t) token_ = t;
    else token_ = approle_login();
  }
  ~VaultKv() { wipe(token_); }

  int create(const std::string& path, const std::string& value) { return write(path, value, 0); }
  int update(const std::string& path, const std::string& value, int expected) { return write(path, value, expected); }

  // Returns {value, version} of the latest version.
  std::pair<std::string, int> read(const std::string& path) {
    auto [status, body] = call("GET", mount + "/data/" + check(path), nullptr);
    if (status == 404) throw std::runtime_error(path + " not found or latest version deleted");
    if (status != 200) throw std::runtime_error("read failed: HTTP " + std::to_string(status));
    auto& v = body["data"]["data"]["value"];
    if (!v.is_string()) throw std::runtime_error("secret has no string \"value\" field");
    std::pair<std::string, int> out{v.get<std::string>(), body["data"]["metadata"]["version"].get<int>()};
    OPENSSL_cleanse(v.get_ptr<std::string*>()->data(), v.get_ptr<std::string*>()->size());
    return out;
  }

  // Soft-delete the latest version (undo: POST {mount}/undelete/{path}).
  void remove(const std::string& path) {
    if (call("DELETE", mount + "/data/" + check(path), nullptr).first != 204) throw std::runtime_error("delete failed");
  }

  // Permanently remove all versions and metadata.
  void purge(const std::string& path) {
    if (call("DELETE", mount + "/metadata/" + check(path), nullptr).first != 204) throw std::runtime_error("purge failed");
  }

  std::string mount = "secret";

 private:
  std::string addr_, namespace_, ca_file_, token_;
  bool https_only_ = true;

  static size_t on_body(char* p, size_t s, size_t n, void* u) {
    static_cast<std::string*>(u)->append(p, s * n);
    return s * n;
  }

  static std::string check(const std::string& path) {
    static const std::regex ok("^[A-Za-z0-9_.\\-/]+$");
    if (!std::regex_match(path, ok)) throw std::invalid_argument("invalid secret path");
    std::stringstream ss(path);
    std::string seg;
    while (std::getline(ss, seg, '/'))
      if (seg.empty() || seg == "." || seg == "..") throw std::invalid_argument("invalid secret path");
    if (path.back() == '/') throw std::invalid_argument("invalid secret path");
    return path;
  }

  std::pair<long, json> call(const std::string& method, const std::string& path, const json* body,
                             bool auth = true) {
    std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> h(curl_easy_init(), curl_easy_cleanup);
    struct curl_slist* hdrs = curl_slist_append(nullptr, "Content-Type: application/json");
    std::string tok_hdr = "X-Vault-Token: " + token_;
    std::string ns_hdr = "X-Vault-Namespace: " + namespace_;
    if (auth) hdrs = curl_slist_append(hdrs, tok_hdr.c_str());
    if (!namespace_.empty()) hdrs = curl_slist_append(hdrs, ns_hdr.c_str());
    std::string url = addr_ + "/v1/" + path, payload = body ? body->dump() : std::string(), resp;
    curl_easy_setopt(h.get(), CURLOPT_URL, url.c_str());
    curl_easy_setopt(h.get(), CURLOPT_CUSTOMREQUEST, method.c_str());
    curl_easy_setopt(h.get(), CURLOPT_HTTPHEADER, hdrs);
    if (body) curl_easy_setopt(h.get(), CURLOPT_POSTFIELDS, payload.c_str());
    curl_easy_setopt(h.get(), CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(h.get(), CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(h.get(), CURLOPT_TIMEOUT, 30L);
    if (https_only_) curl_easy_setopt(h.get(), CURLOPT_PROTOCOLS_STR, "https");
    if (!ca_file_.empty()) curl_easy_setopt(h.get(), CURLOPT_CAINFO, ca_file_.c_str());
    CURLcode rc = curl_easy_perform(h.get());
    long status = 0;
    curl_easy_getinfo(h.get(), CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(hdrs);
    wipe(tok_hdr);
    wipe(payload);
    if (rc != CURLE_OK) throw std::runtime_error(std::string("transport error: ") + curl_easy_strerror(rc));
    json parsed = resp.empty() ? json() : json::parse(resp, nullptr, false);
    wipe(resp);
    return {status, parsed};
  }

  std::string approle_login() {
    const char* role = std::getenv("VAULT_ROLE_ID");
    const char* file = std::getenv("VAULT_SECRET_ID_FILE");
    if (!role || !file) throw std::runtime_error("set VAULT_TOKEN, or VAULT_ROLE_ID and VAULT_SECRET_ID_FILE");
    std::ifstream in(file);
    std::string secret_id((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    while (!secret_id.empty() && (secret_id.back() == '\n' || secret_id.back() == '\r')) secret_id.pop_back();
    json body = {{"role_id", role}, {"secret_id", secret_id}};
    wipe(secret_id);
    auto [status, resp] = call("POST", "auth/approle/login", &body, false);
    if (status != 200) throw std::runtime_error("approle login failed: HTTP " + std::to_string(status));
    return resp["auth"]["client_token"].get<std::string>();
  }

  // Write with check-and-set; cas=0 means "only if the path has no data".
  int write(const std::string& path, const std::string& value, int cas) {
    json body = {{"options", {{"cas", cas}}}, {"data", {{"value", value}}}};
    auto [status, resp] = call("POST", mount + "/data/" + check(path), &body);
    OPENSSL_cleanse(body["data"]["value"].get_ptr<std::string*>()->data(), value.size());
    if (status != 200)
      throw std::runtime_error("write " + path + " (cas=" + std::to_string(cas) + ") failed: HTTP " +
                               std::to_string(status) + " " + resp.value("errors", json::array()).dump());
    return resp["data"]["version"].get<int>();
  }
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

static bool same(const std::string& a, const std::string& b) {
  return a.size() == b.size() && CRYPTO_memcmp(a.data(), b.data(), a.size()) == 0;
}

int main() try {
  const char* path = std::getenv("SECRET_PATH");
  if (!path) { std::cerr << "set SECRET_PATH\n"; return 2; }
  curl_global_init(CURL_GLOBAL_DEFAULT);
  VaultKv vault;

  std::string v1 = random_value();
  std::cout << "created: " << vault.mount << "/" << path << " version " << vault.create(path, v1) << "\n";
  auto [got, current] = vault.read(path);
  if (!same(v1, got)) throw std::runtime_error("read-back after create failed");

  std::string v2 = random_value();
  int version = vault.update(path, v2, current);
  auto second = vault.read(path);
  if (!same(v2, second.first)) throw std::runtime_error("read-back after update failed");
  std::cout << "updated: version " << version << "\n";
  wipe(v1); wipe(v2); wipe(got); wipe(second.first);

  vault.remove(path);
  std::cout << "soft-deleted latest version\n";
  if (const char* p = std::getenv("PURGE_AFTER_DELETE"); p && std::string(p) == "1") {
    vault.purge(path);
    std::cout << "purged all versions and metadata\n";
  }
  curl_global_cleanup();
  return 0;
} catch (const std::exception& e) {
  std::cerr << "error: " << e.what() << "\n";
  return 1;
}
```

### 9.10 C

libcurl + cJSON + OpenSSL; HTTPS-only except for loopback; `VAULT_CACERT` honored.

```c
/*
 * HashiCorp Vault KV v2 CRUD in C over the HTTP API: libcurl + cJSON + OpenSSL.
 *
 *   cc -std=c11 -Wall -Wextra -O2 vault_kv_crud.c -o vault_kv_crud \
 *      $(pkg-config --cflags --libs libcurl libcjson openssl)
 *
 * Auth: VAULT_TOKEN, or AppRole with the SecretID read from VAULT_SECRET_ID_FILE.
 * TLS: VAULT_CACERT (PEM bundle) for private PKI; plain HTTP only to a loopback Agent/Proxy.
 */
#define _POSIX_C_SOURCE 200809L
#include <cjson/cJSON.h>
#include <curl/curl.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { char *data; size_t len; } buf_t;

static char *g_token = NULL;

static size_t on_body(char *p, size_t s, size_t n, void *u) {
    buf_t *b = u; size_t k = s * n;
    char *g = realloc(b->data, b->len + k + 1);
    if (!g) return 0;
    b->data = g; memcpy(b->data + b->len, p, k); b->len += k; b->data[b->len] = '\0';
    return k;
}
static void buf_wipe(buf_t *b) { if (b->data) { OPENSSL_cleanse(b->data, b->len); free(b->data); } b->data = NULL; b->len = 0; }
static void str_wipe_free(char *s) { if (s) { OPENSSL_cleanse(s, strlen(s)); free(s); } }

static int loopback(const char *addr) {
    return strncmp(addr, "http://127.0.0.1:", 17) == 0 || strncmp(addr, "http://localhost:", 17) == 0;
}

/* One HTTP call to /v1/<path>. Returns HTTP status (0 on transport error); *out gets parsed JSON. */
static long vault_call(const char *method, const char *path, cJSON *body, cJSON **out, int auth) {
    const char *addr = getenv("VAULT_ADDR"), *ns = getenv("VAULT_NAMESPACE"), *ca = getenv("VAULT_CACERT");
    char url[1024], tok_hdr[512], ns_hdr[256];
    snprintf(url, sizeof url, "%s/v1/%s", addr, path);
    struct curl_slist *h = curl_slist_append(NULL, "Content-Type: application/json");
    if (auth) { snprintf(tok_hdr, sizeof tok_hdr, "X-Vault-Token: %s", g_token); h = curl_slist_append(h, tok_hdr); }
    if (ns && *ns) { snprintf(ns_hdr, sizeof ns_hdr, "X-Vault-Namespace: %s", ns); h = curl_slist_append(h, ns_hdr); }
    char *json = body ? cJSON_PrintUnformatted(body) : NULL;
    buf_t resp = {0};
    CURL *c = curl_easy_init();
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_CUSTOMREQUEST, method);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, h);
    if (json) curl_easy_setopt(c, CURLOPT_POSTFIELDS, json);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 30L);
    if (!loopback(addr)) curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "https");
    if (ca) curl_easy_setopt(c, CURLOPT_CAINFO, ca);
    long status = 0;
    if (curl_easy_perform(c) == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    curl_slist_free_all(h);
    if (auth) OPENSSL_cleanse(tok_hdr, sizeof tok_hdr);
    if (json) { OPENSSL_cleanse(json, strlen(json)); cJSON_free(json); }
    if (out) *out = resp.len ? cJSON_Parse(resp.data) : NULL;
    buf_wipe(&resp);
    return status;
}

static int login(void) {
    const char *tok = getenv("VAULT_TOKEN");
    if (tok && *tok) { g_token = strdup(tok); return 0; }
    const char *role = getenv("VAULT_ROLE_ID"), *file = getenv("VAULT_SECRET_ID_FILE");
    if (!role || !file) { fprintf(stderr, "set VAULT_TOKEN, or VAULT_ROLE_ID and VAULT_SECRET_ID_FILE\n"); return -1; }
    FILE *f = fopen(file, "r");
    if (!f) return -1;
    char sid[512] = {0};
    size_t n = fread(sid, 1, sizeof sid - 1, f);
    fclose(f);
    while (n && (sid[n - 1] == '\n' || sid[n - 1] == '\r')) sid[--n] = '\0';
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "role_id", role);
    cJSON_AddStringToObject(body, "secret_id", sid);
    OPENSSL_cleanse(sid, sizeof sid);
    cJSON *out = NULL;
    long st = vault_call("POST", "auth/approle/login", body, &out, 0);
    cJSON_Delete(body);
    const cJSON *t = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(out, "auth"), "client_token");
    if (st == 200 && cJSON_IsString(t)) g_token = strdup(t->valuestring);
    else fprintf(stderr, "approle login failed: HTTP %ld\n", st);
    cJSON_Delete(out);
    return g_token ? 0 : -1;
}

/* Path segments: [A-Za-z0-9_.-]+, no empty, "." or ".." segments (no traversal). */
static int valid_path(const char *p) {
    const char *start = p;
    if (!*p) return 0;
    for (const char *c = p;; c++) {
        if (*c == '/' || *c == '\0') {
            size_t len = (size_t)(c - start);
            if (len == 0 || (len == 1 && start[0] == '.') || (len == 2 && start[0] == '.' && start[1] == '.')) return 0;
            if (*c == '\0') return 1;
            start = c + 1;
        } else if (!(isalnum((unsigned char)*c) || *c == '_' || *c == '-' || *c == '.')) {
            return 0;
        }
    }
}

/* Write with check-and-set; cas=0 means "only if the path has no data". Returns version or -1. */
static int kv_write(const char *mount, const char *path, const char *value, int cas) {
    char url[600]; snprintf(url, sizeof url, "%s/data/%s", mount, path);
    cJSON *body = cJSON_CreateObject();
    cJSON_AddNumberToObject(cJSON_AddObjectToObject(body, "options"), "cas", cas);
    cJSON_AddStringToObject(cJSON_AddObjectToObject(body, "data"), "value", value);
    cJSON *out = NULL;
    long st = vault_call("POST", url, body, &out, 1);
    cJSON_Delete(body);
    int version = -1;
    if (st == 200) {
        const cJSON *v = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(out, "data"), "version");
        if (cJSON_IsNumber(v)) version = v->valueint;
    } else {
        char *errs = cJSON_PrintUnformatted(cJSON_GetObjectItemCaseSensitive(out, "errors"));
        fprintf(stderr, "write (cas=%d) failed: HTTP %ld %s\n", cas, st, errs ? errs : "");
        cJSON_free(errs);
    }
    cJSON_Delete(out);
    return version;
}

/* READ latest: returns malloc'd value (wipe + free) and sets *version, or NULL. */
static char *kv_read(const char *mount, const char *path, int *version) {
    char url[600]; snprintf(url, sizeof url, "%s/data/%s", mount, path);
    cJSON *out = NULL;
    long st = vault_call("GET", url, NULL, &out, 1);
    cJSON *data = cJSON_GetObjectItemCaseSensitive(out, "data");
    cJSON *val = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(data, "data"), "value");
    const cJSON *ver = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(data, "metadata"), "version");
    char *r = NULL;
    if (st == 200 && cJSON_IsString(val)) {
        r = strdup(val->valuestring);
        OPENSSL_cleanse(val->valuestring, strlen(val->valuestring));
        if (version && cJSON_IsNumber(ver)) *version = ver->valueint;
    } else if (st == 404) {
        fprintf(stderr, "not found or latest version deleted\n");
    }
    cJSON_Delete(out);
    return r;
}

/* kind = "data" soft-deletes the latest version; kind = "metadata" removes everything. */
static int kv_delete(const char *mount, const char *path, const char *kind) {
    char url[600]; snprintf(url, sizeof url, "%s/%s/%s", mount, kind, path);
    return vault_call("DELETE", url, NULL, NULL, 1) == 204 ? 0 : -1;
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
    const char *addr = getenv("VAULT_ADDR"), *path = getenv("SECRET_PATH");
    const char *mount = getenv("VAULT_KV_MOUNT") ? getenv("VAULT_KV_MOUNT") : "secret";
    if (!addr || !path || !valid_path(path)) { fprintf(stderr, "set VAULT_ADDR and a valid SECRET_PATH\n"); return 2; }
    if (strncmp(addr, "https://", 8) != 0 && !loopback(addr)) { fprintf(stderr, "VAULT_ADDR must use https\n"); return 2; }
    curl_global_init(CURL_GLOBAL_DEFAULT);
    int rc = 1, version = 0, current = 0;
    char v1[45], v2[45], *got = NULL;
    if (login() != 0) goto done;

    random_value(v1);
    if ((version = kv_write(mount, path, v1, 0)) < 0) goto done;
    printf("created: %s/%s version %d\n", mount, path, version);
    got = kv_read(mount, path, &current);
    if (!same(v1, got)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    str_wipe_free(got); got = NULL;

    random_value(v2);
    if ((version = kv_write(mount, path, v2, current)) < 0) goto done;
    got = kv_read(mount, path, NULL);
    if (!same(v2, got)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated: version %d\n", version);

    if (kv_delete(mount, path, "data") != 0) goto done;
    printf("soft-deleted latest version\n");
    const char *purge = getenv("PURGE_AFTER_DELETE");
    if (purge && strcmp(purge, "1") == 0) {
        if (kv_delete(mount, path, "metadata") != 0) goto done;
        printf("purged all versions and metadata\n");
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
| Direct API/client call (section 9) | In memory | You own login, token renewal, caching. |
| **Vault Agent** (auto-auth + templates) | Rendered file (tmpfs) or env via `exec` mode | Agent handles login and renewal; templates re-render on change and can signal the app. |
| **Vault Proxy** (auto-auth + API proxy) | App calls `http://127.0.0.1:<port>` without a token | Proxy injects its token (`use_auto_auth_token`); optional response caching. |
| **Vault Secrets Operator** (Kubernetes) | Synced Kubernetes `Secret` | Supports rollout restarts on change; widens exposure to anyone who can read Secrets in the namespace. |
| Agent Injector / CSI provider (Kubernetes) | Files in a shared in-memory volume | Sidecar or CSI driver handles auth. |

Token lifecycle for direct callers: tokens have a TTL and possibly a max TTL. Renew (`POST /v1/auth/token/renew-self`) before expiry while renewable, re-login when max TTL is reached, and revoke on shutdown. The Go client provides `LifetimeWatcher` for this.

Rotation-safe consumption: cache the value with a TTL; on downstream authentication failure, re-read once and retry once; prefer **dynamic secrets** (database, cloud) whose leases Vault rotates and revokes, over static KV entries for credentials Vault can mint.

## 11. Automation and error handling

| Status | Typical cause | Action |
| --- | --- | --- |
| 400 + "check-and-set parameter did not match" | CAS conflict (including create on an existing key) | Re-read, re-decide, retry deliberately; never loop blindly. |
| 400 other | Malformed body; `cas_required` without `cas` | Fix request. |
| 403 "permission denied" | Policy lacks the capability on the exact `data/`/`metadata/` path; expired/revoked token; wrong namespace | `vault token capabilities <path>`; check namespace header. |
| 404 | No such key, or latest version soft-deleted/destroyed (body may include metadata) | Inspect metadata. |
| 412 | Performance standby/replication consistency (Enterprise) | Retry with backoff; consider `X-Vault-Index` consistency headers. |
| 429 | Rate-limit quota | Back off; cache reads. |
| 500/502/503 | Server issue, sealed Vault (503), standby forwarding | Retry with backoff; check `sys/health`. |

Practices:

- Use `cas=0` for creates and `cas=<version read>` for replacements; enable `cas_required` on important paths.
- Keep tokens short-lived; renew or re-authenticate in a background task; never share one token across services.
- Bound every request with a timeout; retry idempotent reads and 5xx/429 with jittered backoff.
- Use `-output-curl-string` (CLI) to see the exact API call a CLI command makes, without executing it, when translating workflows into code.

## 12. Optional live CRUD verification

This **performs writes**. Use a disposable dev server (`vault server -dev`, never for real secrets) or a sandbox mount and a token with the policy from section 2.

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${VAULT_ADDR:?set VAULT_ADDR}"
vault token lookup -format=json | jq -e '.data.ttl >= 0' > /dev/null
MOUNT="${MOUNT:-secret}"

work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
path="crud-check/$(date -u +%Y%m%dT%H%M%SZ)-$$"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v1"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v2"

vault kv put -mount="$MOUNT" -cas=0 "$path" value=@"$work/v1" > /dev/null
vault kv get -mount="$MOUNT" -field=value "$path" | cmp -s - "$work/v1"
! vault kv put -mount="$MOUNT" -cas=0 "$path" value=@"$work/v2" > /dev/null 2>&1   # create-only holds

vault kv put -mount="$MOUNT" -cas=1 "$path" value=@"$work/v2" > /dev/null
vault kv get -mount="$MOUNT" -field=value "$path" | cmp -s - "$work/v2"

vault kv delete -mount="$MOUNT" "$path"
! vault kv get -mount="$MOUNT" "$path" > /dev/null 2>&1
vault kv metadata delete -mount="$MOUNT" "$path"
printf 'PASS: create, read, update, and delete completed.\n'
```

It does not test policies, namespaces, replication, or Agent/Proxy.

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| 403 on a path that "should" work | KV v2 needs `secret/data/...` in policies, not `secret/...`; run `vault token capabilities secret/data/<path>`. |
| 404 on a key that exists | Latest version soft-deleted; or wrong mount/namespace; or KV v1 mount (no `data/` segment). |
| CAS error on every write | `cas_required` set and client omits `cas`; or stale version number. |
| Fields disappeared after an update | A full `put` replaced the map; use `patch` or include all fields. |
| `x509: certificate signed by unknown authority` | Set `VAULT_CACERT` / client CA; never `VAULT_SKIP_VERIFY` in real environments. |
| 503 | Vault sealed or standby without forwarding; check `vault status`. |
| Token expired mid-run | Renew or re-login; max TTL reached; use Agent/Proxy auto-auth. |
| AppRole login fails | SecretID used up (`secret_id_num_uses`), expired, or CIDR-bound; RoleID mismatch. |
| Secret appears in logs | HTTP debug logging; `log_raw` audit option; app logged response. Disable, rotate, destroy versions. |

## 14. Accuracy notes and official sources

- **CAS semantics:** "If set to 0 a write will only be allowed if the key doesn't exist"; soft-deleted keys also require a matching CAS. [S01]
- **Default version retention** is 10 when `max_versions` is 0 or unset. [S01]
- **Read of a soft-deleted latest version** returns 404 in Vault; the API page describes deleted data as not returned by reads without naming the status, and the CLI and clients surface it as not found. The mock reproduced Vault's 404-with-metadata behavior.
- **Mock-based verification** validates request shapes and client logic, not Vault's server behavior. Run section 12 against a real dev server before relying on edge cases.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [KV v2 API][S01] | Paths, CAS, patch, delete/undelete/destroy, metadata defaults |
| S02 | [KV v2 secrets engine and policies][S02] | Path layout and ACL paths |
| S03 | [AppRole auth method][S03] | RoleID/SecretID, response wrapping, CIDR binding |
| S04 | [Kubernetes auth method][S04] | Pod identity login |
| S05 | [Audit devices][S05] | HMAC of sensitive values, `log_raw` |
| S06 | [Vault Agent][S06] | Auto-auth, templates, caching |
| S07 | [Vault Proxy][S07] | API proxy with auto-auth token |
| S08 | [Go client `api` package][S08] | `KVv2`, `WithCheckAndSet`, `ErrSecretNotFound` |
| S09 | [hvac KV v2][S09] | Python method names and CAS |
| S10 | [Token concepts][S10] | TTL, renewal, accessors, revoke-self |
| S11 | [`vault kv` CLI][S11] | `put/get/patch/rollback/delete/undelete/destroy/metadata` |
| S12 | [Production hardening][S12] | TLS, no root tokens, audit |

[S01]: https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2
[S02]: https://developer.hashicorp.com/vault/docs/secrets/kv/kv-v2
[S03]: https://developer.hashicorp.com/vault/docs/auth/approle
[S04]: https://developer.hashicorp.com/vault/docs/auth/kubernetes
[S05]: https://developer.hashicorp.com/vault/docs/audit
[S06]: https://developer.hashicorp.com/vault/docs/agent-and-proxy/agent
[S07]: https://developer.hashicorp.com/vault/docs/agent-and-proxy/proxy
[S08]: https://pkg.go.dev/github.com/hashicorp/vault/api
[S09]: https://python-hvac.org/en/stable/usage/secrets_engines/kv_v2.html
[S10]: https://developer.hashicorp.com/vault/docs/concepts/tokens
[S11]: https://developer.hashicorp.com/vault/docs/commands/kv
[S12]: https://developer.hashicorp.com/vault/docs/concepts/production-hardening
