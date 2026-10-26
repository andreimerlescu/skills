# Akeyless Vault Platform: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** Akeyless Vault Platform, V2 API. SaaS endpoint `https://api.akeyless.io`; customer Gateway endpoint `https://<gateway-host>:8000/api/v2` (legacy dedicated port `8081`). Every V2 operation is a `POST` with a JSON body: `/auth`, `/create-secret`, `/get-secret-value`, `/update-secret-val`, `/describe-item`, `/delete-item`  
**Primary authentication:** an **auth method** exchanged for a short-lived session token via `POST /auth` — cloud IAM (`aws_iam`, `azure_ad`, `gcp`, `oci`), `k8s`, `jwt`/`oidc`, `cert`, `universal_identity`, or API Key (`access_key`: access ID + access key); the token travels in the request **body** field `token`  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use Bash, `curl`, `jq`, and the Akeyless CLI)

This guide covers **static secrets** in Akeyless: named items addressed by a folder-style path (`/team/app/DB_PASSWORD`), with optional versioning. It covers auth methods and access roles, complete CRUD workflows, version handling, the Gateway, a full CRUD program in each of ten languages, runtime consumption (Gateway cache, Kubernetes injector, External Secrets, CLI), and troubleshooting. Dynamic secrets, rotated secrets, encryption keys/DFC operations, Secure Remote Access, and PKI are out of scope except where they affect design.

Credentials are assumed to be provisioned already. Do not paste an access key, session token, or UID token into this document, source files, command arguments, or example files.

**Verification boundary:** Request and response fields were taken from the official generated SDKs at **5.0.40** (`akeyless` for Python and npm, `github.com/akeylesslabs/akeyless-go/v5`, `io.akeyless:akeyless-java`) and cross-checked against the API and CLI reference pages in section 14. The Go program was vetted (`go vet`), the TypeScript program type-checked (`tsc --strict`), and both — together with the Python program — **run end-to-end** against a local mock of the six V2 endpoints, as were the REST programs for Rust (`cargo build`), PHP (`php -l`), C# (`dotnet build`, warnings as errors), C++ and C (`-Wall -Wextra -Werror`). The Java program was checked against the SDK sources (Maven Central was unreachable from the build environment); Swift was not compiled (no toolchain). The mock rejects duplicate creates with HTTP 409 and bad tokens with 401; the real service's status codes for those cases are not documented and may differ. No call was made to a real Akeyless account. Section 12 provides an optional live test.

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
10. [Use secrets in applications](#10-use-secrets-in-applications)
11. [Automation and error handling](#11-automation-and-error-handling)
12. [Optional live CRUD verification](#12-optional-live-crud-verification)
13. [Troubleshooting](#13-troubleshooting)
14. [Accuracy notes and official sources](#14-accuracy-notes-and-official-sources)

## 1. Requirements and conventions

| Language | Official client | Transport used here | Verified here |
| --- | --- | --- | --- |
| Go | `github.com/akeylesslabs/akeyless-go/v5` | SDK | `go vet`, mock run |
| Rust | none | REST via `reqwest` (rustls) | `cargo build`, mock run |
| PHP | none | REST via ext-curl | `php -l`, mock run |
| C# | none | REST via `HttpClient` + `System.Text.Json` | `dotnet build -warnaserror`, mock run |
| Java | `io.akeyless:akeyless-java` | SDK (OkHttp + Gson) | source check |
| Swift | none | REST via `URLSession` | not compiled |
| Python | `akeyless` | SDK | mock run |
| TypeScript | `akeyless` (npm, untyped JavaScript) | SDK + local typings | `tsc --strict`, mock run |
| C++ | none | REST via libcurl + nlohmann/json | `-Werror`, mock run |
| C | none | REST via libcurl + cJSON | `-Werror`, mock run |

Akeyless also publishes a Ruby SDK; there is no official .NET, Rust, PHP, Swift, C++, or C client, and the V2 REST API is the documented integration path for them. All SDKs are generated from the same OpenAPI document, so field names are identical across languages (hyphenated in JSON: `keep-prev-version`, `access-id`).

Every program follows the same contract:

- Environment: `AKEYLESS_GATEWAY_URL` (default `https://api.akeyless.io`; for a Gateway use `https://<host>:8000/api/v2`; plain HTTP accepted only for a loopback test server), `AKEYLESS_ACCESS_ID`, `AKEYLESS_ACCESS_KEY_FILE` (path to a `0600` file holding the API key's access key), and `SECRET_NAME` (a full path such as `/sandbox/CRUD_CHECK`).
- It authenticates, **creates** a static secret (create fails if the name exists), reads it back and compares in constant time, **updates** it as a **new version** (`keep-prev-version=true`), reads and compares again, then **deletes** the item with all versions.
- It prints item names and version numbers only. Errors carry the operation and HTTP status; the `{"error": "..."}` body is not printed.

The programs use API Key auth because it runs anywhere; production workloads should use a platform auth method (section 2) — only the `/auth` body changes.

For shell snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
AKL="${AKEYLESS_GATEWAY_URL:-https://api.akeyless.io}"   # Gateway: https://<host>:8000/api/v2
ACCESS_ID='REPLACE_WITH_ACCESS_ID'                         # an identifier, not a secret
```

## 2. Authenticate

### Auth methods

| Platform | `access-type` | What the workload sends |
| --- | --- | --- |
| AWS / Azure / GCP / OCI / Alibaba | `aws_iam`, `azure_ad`, `gcp`, `oci`, `alicloud` | `access-id` + `cloud-id` (a signed proof of the workload's cloud identity, built by the `akeyless-cloud-id` helpers) |
| Kubernetes | `k8s` | Service-account JWT + `k8s-auth-config-name` (validated by the Gateway) |
| CI / OIDC / JWT issuers | `jwt`, `oidc` | The issuer's JWT |
| Machines with certificates | `cert` | Certificate + signed challenge |
| On-prem machines without a platform identity | `universal_identity` | A rotating **UID token** (`uid-token`) |
| Anything else | `access_key` | Access ID + **access key** (secret) |

Prefer platform methods: nothing long-lived is stored. When API Keys are unavoidable, set **bound IPs** (CIDR allow-list), an **access expiration**, and a short **JWT TTL** on the auth method, and deliver the access key as a file. Universal Identity replaces a static key with a UID token (default TTL 60 minutes, reset on every rotation via `uid-rotate-token` or `uid-auto-rotate`), so a stolen copy goes stale; exchange it at `/auth` for a session token rather than sending it on every call. [S02] [S03]

`POST /auth` returns `{"token": "t-…", "expiration": "…"}` (plus `creds` for some flows). Session lifetime comes from the auth method's JWT TTL or the account default; re-authenticate when a call returns an authentication error or before `expiration`. [S04]

### Confirm authentication without displaying the token

```bash
# jq builds the JSON from a file, so the access key never appears on a command line; the token stays in a variable.
AKL_TOKEN="$(jq -n --arg id "$ACCESS_ID" --rawfile key /secure/path/akeyless-access-key \
    '{"access-type":"access_key","access-id":$id,"access-key":($key|rtrimstr("\n"))}' |
  curl -sSf -H 'Content-Type: application/json' --data @- "$AKL/auth" | jq -r .token)"
export AKL_TOKEN
[ -n "$AKL_TOKEN" ] && [ "$AKL_TOKEN" != null ] && printf 'auth ok\n'
```

The CLI equivalent is `akeyless auth --access-id … --access-key …` or a profile created with `akeyless configure`; both put the access key on a command line or into a profile file under `~/.akeyless`, so prefer the snippet above or the SDKs on shared hosts.

### Required permissions

Access is granted by **access roles** associated with auth methods. A role holds rules: `akeyless set-role-rule --role-name <role> --path '/team/app/*' --capability read` (capabilities: `read`, `create`, `update`, `delete`, `list`, `deny`; `--rule-type item-rule` by default; optional `--ttl` for temporary rules). Associate with `akeyless assoc-role-am --role-name <role> --am-name <auth-method>`, optionally narrowed by `--sub-claims` (for example a Kubernetes namespace or a CI repository). Give runtime readers `read` (and `list` only if they enumerate); give provisioning identities `create`/`update`/`delete` on their own paths. [S05]

## 3. Data model and addressing

- **Items** live in a folder hierarchy; the name is the full path (`/team/app/DB_PASSWORD`). Creating a secret in a missing folder creates the folder. [S06]
- **Static secret:** sub-type `generic` (a text, JSON, or key-value value; `format`) or `password` (password-manager style fields). Maximum value size is **16 KB**. [S06]
- **Versions:** `update-secret-val` **overwrites the latest version by default**; with `keep-prev-version=true` (or an account setting) it creates a new version. `max-versions` caps retained versions within account limits. `get-secret-value` reads the latest by default, a specific `version`, or the last N with `version=-N` (max 20). `rollback-secret` (`old-version`) restores an older value as the current one. [S07]
- **Metadata:** `describe-item` returns `item_name`, `item_id`, `item_type`, `last_version`, tags, `delete_protection`, and more — no value.
- **Protection key:** each item is encrypted with a key (`protection_key` on create, `key` on update); the account default applies otherwise. With **Distributed Fragments Cryptography** and a customer fragment on your Gateway, Akeyless SaaS alone cannot decrypt values.
- **Gateway:** an in-network component that proxies the API, caches secrets (reads may be served from cache; `ignore-cache=true` forces a fresh read over REST), and is required for some auth methods (`k8s`) and for customer fragments.

Inventory without values:

```bash
jq -n --arg p /team/app '{path:$p, type:["static-secret"], "minimal-view":true, token:env.AKL_TOKEN}' |
  curl -sSf -H 'Content-Type: application/json' --data @- "$AKL/list-items" |
  jq '[.items[]? | {name: .item_name, last_version}]'
```

## 4. Safe secret handling

- **Command lines:** the CLI takes values only as `--value <value>` (no documented file or stdin option), which puts them in shell history and the process table. Write through the API or SDK with the value read from a file (section 5), or run the CLI only on single-user hosts with history disabled for that command.
- **Tokens in bodies:** the session token is a body field, so anything that logs request bodies leaks it: HTTP debug logging, proxy logs, the Java SDK's `setDebugging(true)`, and SDK error objects. The npm SDK rejects with a plain object that includes the superagent response (and its request); the Java SDK's `ApiException.getMessage()` includes the response body and headers; Python's `ApiException.__str__` includes the body. Log status codes only.
- **Output:** `akeyless get-secret-value` prints the value; redirect to a protected file or pipe directly into the consumer.
- **Caching:** Gateway caching can serve a previous value briefly after an update; account for it in rotation logic or read with `ignore-cache=true` when verifying.
- **Lock on read / one-time secrets:** `lock-on-read` locks a secret after each successful read — useful for hand-off secrets, surprising for applications.
- **Memory:** wipe buffers where possible (`zeroize`, `OPENSSL_cleanse`); minimize copies of managed strings.

## 5. Create secrets

`POST /create-secret` with `{"name", "value", "token", "type"?: "generic", "format"?: "text"|"json"|"key-value", "description"?, "tags"?, "delete_protection"?: "true", "max-versions"?, "protection_key"?, "multiline_value"?}`. Response: `{"name": "<name>"}`. Creating a name that already exists fails — create is create-only. [S04] [S08]

```bash
jq -n --arg n /team/app/PARTNER_API_TOKEN --rawfile v /secure/path/to/api-token.txt \
    '{name:$n, value:($v|rtrimstr("\n")), "delete_protection":"true", token:env.AKL_TOKEN}' |
  curl -sSf -o /dev/null -H 'Content-Type: application/json' --data @- "$AKL/create-secret" &&
  printf 'created\n'
```

## 6. Read secrets

`POST /get-secret-value` with `{"names": ["<name>", ...], "token", "version"?, "ignore-cache"?: "true"}` returns an object mapping each name to its value: `{"/team/app/PARTNER_API_TOKEN": "<value>"}`. Read several secrets in one call by listing several names. [S04] [S09]

```bash
# One value to a new private file (no trailing newline added)
jq -n --arg n /team/app/PARTNER_API_TOKEN '{names:[$n], token:env.AKL_TOKEN}' |
  curl -sSf -H 'Content-Type: application/json' --data @- "$AKL/get-secret-value" |
  jq -j --arg n /team/app/PARTNER_API_TOKEN '.[$n]' > ./partner-api-token.secret

# Metadata only
jq -n --arg n /team/app/PARTNER_API_TOKEN '{name:$n, token:env.AKL_TOKEN}' |
  curl -sSf -H 'Content-Type: application/json' --data @- "$AKL/describe-item" |
  jq '{item_name, item_type, last_version, delete_protection}'
```

CLI: `akeyless get-secret-value --name /team/app/PARTNER_API_TOKEN > ./partner-api-token.secret` (optionally `--version N`).

## 7. Update secrets

`POST /update-secret-val` with `{"name", "value", "token", "keep-prev-version"?: "true", "key"?, "format"?, "multiline"?}`. Response: `{"name"}`. Without `keep-prev-version` (and with the account default unchanged), the latest version is **overwritten** — no history to roll back to. Pass `"keep-prev-version": "true"` for anything you may need to restore. [S07] [S10]

```bash
jq -n --arg n /team/app/PARTNER_API_TOKEN --rawfile v /secure/path/new-token.txt \
    '{name:$n, value:($v|rtrimstr("\n")), "keep-prev-version":"true", token:env.AKL_TOKEN}' |
  curl -sSf -o /dev/null -H 'Content-Type: application/json' --data @- "$AKL/update-secret-val"

jq -n --arg n /team/app/PARTNER_API_TOKEN '{names:[$n], "ignore-cache":"true", token:env.AKL_TOKEN}' |
  curl -sSf -H 'Content-Type: application/json' --data @- "$AKL/get-secret-value" |
  jq -j --arg n /team/app/PARTNER_API_TOKEN '.[$n]' |
  cmp -s - <(tr -d '\n' < /secure/path/new-token.txt) && printf 'Secret replacement verified.\n'
```

**Concurrency:** `update-secret-val` accepts `last-version` ("the last version number before the update"), but the reference does not say that a mismatch is rejected, so do not treat it as compare-and-swap. Serialize writers per secret (one provisioning pipeline or rotation job), or re-read `describe-item` → `last_version` immediately before and after writing and alert on unexpected jumps.

Storing a new value does not rotate the credential at its source; Akeyless **rotated secrets** (for supported targets) or your own rotation job must change the source first.

## 8. Delete and recover

`POST /delete-item` with `{"name", "token", "version"?: -1}`: `version` `-1` (default) deletes the item with all versions, `0` deletes the latest version, `N` deletes version N. `delete-in-days` (default 7) and `delete-immediately` apply to **keys**, not secrets. The response includes `item_name`, `version_deleted`, and `deletion_date`. Items with **delete protection** must have it turned off (`update-item`) before deletion. [S11]

```bash
jq -n --arg n /team/app/PARTNER_API_TOKEN '{name:$n, version:-1, token:env.AKL_TOKEN}' |
  curl -sSf -o /dev/null -H 'Content-Type: application/json' --data @- "$AKL/delete-item"
```

The documentation does not describe a recovery path for deleted static secrets; treat deletion as permanent. To undo a bad **value**, use `rollback-secret` (requires a retained earlier version). Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Expected output for every program:

```text
created: /sandbox/CRUD_CHECK version 1
updated: version 2
deleted: /sandbox/CRUD_CHECK
```

### 9.1 Go

`go get github.com/akeylesslabs/akeyless-go/v5@v5.0.40`. Request structs come from `New<Op>(required…)` constructors, which also set documented defaults (`NewAuth` sets `access-type` `access_key`; `NewDeleteItem` sets `version` `-1`). The configuration's `HTTPClient` is replaced to add a timeout.

```go
// Akeyless static-secret CRUD with the official Go SDK (github.com/akeylesslabs/akeyless-go/v5).
// Auth: API Key auth method; the access key is read from AKEYLESS_ACCESS_KEY_FILE.
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
	"strings"
	"time"

	akeyless "github.com/akeylesslabs/akeyless-go/v5"
)

type Store struct {
	api   *akeyless.V2ApiService
	token string
}

// apiErr reports operation and HTTP status only; GenericOpenAPIError.Body() holds the server's
// {"error": ...} JSON, which names items but should still stay out of routine logs.
func apiErr(op string, resp *http.Response, err error) error {
	var oe *akeyless.GenericOpenAPIError
	if resp != nil {
		return fmt.Errorf("%s: HTTP %d", op, resp.StatusCode)
	}
	if errors.As(err, &oe) {
		return fmt.Errorf("%s: %s", op, oe.Error())
	}
	return fmt.Errorf("%s: %w", op, err)
}

func Login(ctx context.Context, host, accessID, accessKey string) (*Store, error) {
	cfg := akeyless.NewConfiguration()
	cfg.Servers = akeyless.ServerConfigurations{{URL: strings.TrimRight(host, "/")}}
	cfg.HTTPClient = &http.Client{Timeout: 30 * time.Second}
	api := akeyless.NewAPIClient(cfg).V2Api

	body := akeyless.NewAuth() // access-type defaults to "access_key" (API Key)
	body.SetAccessId(accessID)
	body.SetAccessKey(accessKey)
	out, resp, err := api.Auth(ctx).Body(*body).Execute()
	if err != nil {
		return nil, apiErr("auth", resp, err)
	}
	return &Store{api: api, token: out.GetToken()}, nil
}

// Create fails if an item with this name already exists (create-secret is not an upsert).
func (s *Store) Create(ctx context.Context, name, value string) error {
	body := akeyless.NewCreateSecret(name, value)
	body.SetToken(s.token)
	_, resp, err := s.api.CreateSecret(ctx).Body(*body).Execute()
	if err != nil {
		return apiErr("create", resp, err)
	}
	return nil
}

func (s *Store) Read(ctx context.Context, name string) (string, error) {
	body := akeyless.NewGetSecretValue([]string{name})
	body.SetToken(s.token)
	out, resp, err := s.api.GetSecretValue(ctx).Body(*body).Execute()
	if err != nil {
		return "", apiErr("read", resp, err)
	}
	v, ok := out[name].(string)
	if !ok {
		return "", fmt.Errorf("read: no string value for %s", name)
	}
	return v, nil
}

func (s *Store) LastVersion(ctx context.Context, name string) (int32, error) {
	body := akeyless.NewDescribeItem(name)
	body.SetToken(s.token)
	item, resp, err := s.api.DescribeItem(ctx).Body(*body).Execute()
	if err != nil {
		return 0, apiErr("describe", resp, err)
	}
	return item.GetLastVersion(), nil
}

// Update writes a new version (keep-prev-version=true) instead of overwriting the latest one.
func (s *Store) Update(ctx context.Context, name, value string) error {
	body := akeyless.NewUpdateSecretVal(name, value)
	body.SetKeepPrevVersion("true")
	body.SetToken(s.token)
	_, resp, err := s.api.UpdateSecretVal(ctx).Body(*body).Execute()
	if err != nil {
		return apiErr("update", resp, err)
	}
	return nil
}

// Delete removes the item and all versions (version -1 is the constructor default).
func (s *Store) Delete(ctx context.Context, name string) error {
	body := akeyless.NewDeleteItem(name)
	body.SetToken(s.token)
	_, resp, err := s.api.DeleteItem(ctx).Body(*body).Execute()
	if err != nil {
		return apiErr("delete", resp, err)
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

func main() {
	name, accessID := os.Getenv("SECRET_NAME"), os.Getenv("AKEYLESS_ACCESS_ID")
	if name == "" || accessID == "" {
		log.Fatal("set SECRET_NAME, AKEYLESS_ACCESS_ID, AKEYLESS_ACCESS_KEY_FILE")
	}
	raw, err := os.ReadFile(os.Getenv("AKEYLESS_ACCESS_KEY_FILE"))
	if err != nil {
		log.Fatal("read access key file: ", err)
	}
	host := os.Getenv("AKEYLESS_GATEWAY_URL")
	if host == "" {
		host = "https://api.akeyless.io"
	}
	if !strings.HasPrefix(host, "https://") && !strings.HasPrefix(host, "http://127.0.0.1:") {
		log.Fatal("AKEYLESS_GATEWAY_URL must use https")
	}
	ctx := context.Background()
	store, err := Login(ctx, host, accessID, strings.TrimSpace(string(raw)))
	clear(raw)
	if err != nil {
		log.Fatal(err)
	}

	v1 := randomValue()
	if err := store.Create(ctx, name, v1); err != nil {
		log.Fatal(err)
	}
	ver, err := store.LastVersion(ctx, name)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Printf("created: %s version %d\n", name, ver)
	if got, err := store.Read(ctx, name); err != nil || !equal(got, v1) {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	if err := store.Update(ctx, name, v2); err != nil {
		log.Fatal(err)
	}
	if got, err := store.Read(ctx, name); err != nil || !equal(got, v2) {
		log.Fatal("read-back after update failed: ", err)
	}
	if ver, err = store.LastVersion(ctx, name); err != nil {
		log.Fatal(err)
	}
	fmt.Printf("updated: version %d\n", ver)

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
name = "akeyless-secrets-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
reqwest = { version = "0.12", default-features = false, features = ["json", "rustls-tls"] }
serde_json = "1"
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
getrandom = "0.3"
base64 = "0.22"
subtle = "2"
zeroize = "1"
```

```rust
//! Akeyless static-secret CRUD over the V2 REST API with reqwest (Akeyless ships no Rust SDK).
//! Every V2 call is a JSON POST; the session token travels in the body field "token".
//! Auth: API Key auth method; the access key is read from AKEYLESS_ACCESS_KEY_FILE.
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use reqwest::Client;
use serde_json::{json, Value};
use std::{env, error::Error, time::Duration};
use subtle::ConstantTimeEq;
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

struct AkeylessStore {
    http: Client,
    base: String,
    token: Zeroizing<String>,
}

impl AkeylessStore {
    async fn login(base: &str, access_id: &str, access_key: &str) -> Res<Self> {
        // Plain HTTP only to a loopback test server; TLS everywhere else.
        let loopback = base.starts_with("http://127.0.0.1:") || base.starts_with("http://localhost:");
        if !base.starts_with("https://") && !loopback {
            return Err("AKEYLESS_GATEWAY_URL must use https".into());
        }
        let http = Client::builder().timeout(Duration::from_secs(30)).https_only(!loopback).build()?;
        let mut store = Self { http, base: base.trim_end_matches('/').to_string(), token: Zeroizing::new(String::new()) };
        let out = store
            .call("auth", "auth", json!({ "access-type": "access_key", "access-id": access_id, "access-key": access_key }))
            .await?;
        store.token = Zeroizing::new(out["token"].as_str().ok_or("auth: no token in response")?.to_string());
        Ok(store)
    }

    /// POST one V2 command. Error bodies are {"error": "..."}; only the status is surfaced.
    async fn call(&self, op: &str, command: &str, mut body: Value) -> Res<Value> {
        if command != "auth" {
            body["token"] = Value::String(self.token.to_string());
        }
        let resp = self.http.post(format!("{}/{}", self.base, command)).json(&body).send().await?;
        drop(body); // serde_json strings are not zeroized; keep the copy short-lived
        let status = resp.status();
        let text = Zeroizing::new(resp.text().await?);
        if !status.is_success() {
            return Err(format!("{op}: HTTP {}", status.as_u16()).into());
        }
        Ok(if text.is_empty() { Value::Null } else { serde_json::from_str(&text)? })
    }

    /// Fails if an item with this name already exists (create-secret is not an upsert).
    async fn create(&self, name: &str, value: &str) -> Res<()> {
        self.call("create", "create-secret", json!({ "name": name, "value": value })).await.map(|_| ())
    }

    async fn read(&self, name: &str) -> Res<Zeroizing<String>> {
        let mut out = self.call("read", "get-secret-value", json!({ "names": [name] })).await?;
        let v = out[name].take();
        Ok(Zeroizing::new(v.as_str().ok_or("read: no string value")?.to_string()))
    }

    async fn last_version(&self, name: &str) -> Res<i64> {
        let item = self.call("describe", "describe-item", json!({ "name": name })).await?;
        Ok(item["last_version"].as_i64().unwrap_or(0))
    }

    /// keep-prev-version=true writes a new version instead of overwriting the latest one.
    async fn update(&self, name: &str, value: &str) -> Res<()> {
        self.call("update", "update-secret-val", json!({ "name": name, "value": value, "keep-prev-version": "true" }))
            .await
            .map(|_| ())
    }

    /// version -1 deletes the item with all versions.
    async fn delete(&self, name: &str) -> Res<()> {
        self.call("delete", "delete-item", json!({ "name": name, "version": -1 })).await.map(|_| ())
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

#[tokio::main]
async fn main() -> Res<()> {
    let name = env::var("SECRET_NAME").map_err(|_| "set SECRET_NAME")?;
    let access_id = env::var("AKEYLESS_ACCESS_ID").map_err(|_| "set AKEYLESS_ACCESS_ID")?;
    let key_file = env::var("AKEYLESS_ACCESS_KEY_FILE").map_err(|_| "set AKEYLESS_ACCESS_KEY_FILE")?;
    let access_key = Zeroizing::new(std::fs::read_to_string(key_file)?.trim().to_string());
    let base = env::var("AKEYLESS_GATEWAY_URL").unwrap_or_else(|_| "https://api.akeyless.io".into());
    let store = AkeylessStore::login(&base, &access_id, &access_key).await?;
    drop(access_key);

    let v1 = random_value()?;
    store.create(&name, &v1).await?;
    println!("created: {name} version {}", store.last_version(&name).await?);
    if !same(&v1, &store.read(&name).await?) {
        return Err("read-back after create did not match".into());
    }

    let v2 = random_value()?;
    store.update(&name, &v2).await?;
    if !same(&v2, &store.read(&name).await?) {
        return Err("read-back after update did not match".into());
    }
    println!("updated: version {}", store.last_version(&name).await?);

    store.delete(&name).await?;
    println!("deleted: {name}");
    Ok(())
}
```

### 9.3 PHP

PHP 8.2+ with ext-curl.

```php
<?php
// Akeyless static-secret CRUD over the V2 REST API with ext-curl (Akeyless ships no PHP SDK).
// Every V2 call is a JSON POST; the session token travels in the body field "token".
// Auth: API Key auth method; the access key is read from AKEYLESS_ACCESS_KEY_FILE.
declare(strict_types=1);

final class AkeylessException extends RuntimeException
{
    public function __construct(string $op, public readonly int $status)
    {
        parent::__construct(sprintf('%s: HTTP %d', $op, $status)); // the {"error": ...} body is not surfaced
    }
}

final class AkeylessStore
{
    private string $base;
    private string $token = '';

    public function __construct(string $baseUrl = 'https://api.akeyless.io')
    {
        $loopback = (bool)preg_match('#^http://(127\.0\.0\.1|localhost):#', $baseUrl);
        if (!str_starts_with($baseUrl, 'https://') && !$loopback) {
            throw new InvalidArgumentException('AKEYLESS_GATEWAY_URL must use https');
        }
        $this->base = rtrim($baseUrl, '/');
    }

    private function call(string $op, string $command, array $body): array
    {
        if ($command !== 'auth') {
            $body['token'] = $this->token;
        }
        $ch = curl_init($this->base . '/' . $command);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => json_encode($body, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES),
            CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Accept: application/json'],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_PROTOCOLS => str_starts_with($this->base, 'https://') ? CURLPROTO_HTTPS : CURLPROTO_HTTP,
        ]);
        unset($body);
        $raw = curl_exec($ch);
        if ($raw === false) {
            throw new RuntimeException("$op: transport error " . curl_errno($ch));
        }
        $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        if ($status < 200 || $status > 299) {
            throw new AkeylessException($op, $status);
        }
        return $raw === '' ? [] : json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
    }

    public function login(string $accessId, #[\SensitiveParameter] string $accessKey): void
    {
        $out = $this->call('auth', 'auth', ['access-type' => 'access_key', 'access-id' => $accessId, 'access-key' => $accessKey]);
        $this->token = $out['token'] ?? throw new RuntimeException('auth: no token in response');
    }

    /** Fails if an item with this name already exists (create-secret is not an upsert). */
    public function create(string $name, #[\SensitiveParameter] string $value): void
    {
        $this->call('create', 'create-secret', ['name' => $name, 'value' => $value]);
    }

    public function read(string $name): string
    {
        $out = $this->call('read', 'get-secret-value', ['names' => [$name]]);
        return is_string($out[$name] ?? null) ? $out[$name] : throw new RuntimeException("read: no value for $name");
    }

    public function lastVersion(string $name): int
    {
        return (int)($this->call('describe', 'describe-item', ['name' => $name])['last_version'] ?? 0);
    }

    /** keep-prev-version=true writes a new version instead of overwriting the latest one. */
    public function update(string $name, #[\SensitiveParameter] string $value): void
    {
        $this->call('update', 'update-secret-val', ['name' => $name, 'value' => $value, 'keep-prev-version' => 'true']);
    }

    /** version -1 deletes the item with all versions. */
    public function delete(string $name): void
    {
        $this->call('delete', 'delete-item', ['name' => $name, 'version' => -1]);
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

$name = env_or_fail('SECRET_NAME');
try {
    $store = new AkeylessStore(getenv('AKEYLESS_GATEWAY_URL') ?: 'https://api.akeyless.io');
    $store->login(env_or_fail('AKEYLESS_ACCESS_ID'), trim((string)file_get_contents(env_or_fail('AKEYLESS_ACCESS_KEY_FILE'))));

    $v1 = random_value();
    $store->create($name, $v1);
    echo "created: $name version {$store->lastVersion($name)}\n";
    if (!hash_equals($v1, $store->read($name))) {
        throw new RuntimeException('read-back after create did not match');
    }

    $v2 = random_value();
    $store->update($name, $v2);
    if (!hash_equals($v2, $store->read($name))) {
        throw new RuntimeException('read-back after update did not match');
    }
    echo "updated: version {$store->lastVersion($name)}\n";

    $store->delete($name);
    echo "deleted: $name\n";
} catch (Throwable $e) {
    fwrite(STDERR, get_class($e) . ': ' . $e->getMessage() . "\n");
    exit(1);
} finally {
    unset($v1, $v2);
}
```

### 9.4 C#

.NET 8, no packages.

```csharp
// Akeyless static-secret CRUD over the V2 REST API with HttpClient + System.Text.Json (no packages).
// Akeyless ships no official .NET SDK. Every V2 call is a JSON POST; the session token travels in the body.
// Auth: API Key auth method; the access key is read from AKEYLESS_ACCESS_KEY_FILE.
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

public sealed class AkeylessException(string op, int status) : Exception($"{op}: HTTP {status}")
{
    public int Status { get; } = status;
}

public sealed class AkeylessStore
{
    private readonly HttpClient _http;
    private string _token = "";

    public AkeylessStore(string baseUrl)
    {
        var loopback = Regex.IsMatch(baseUrl, @"^http://(127\.0\.0\.1|localhost):");
        if (!baseUrl.StartsWith("https://", StringComparison.Ordinal) && !loopback)
            throw new ArgumentException("AKEYLESS_GATEWAY_URL must use https");
        _http = new HttpClient { BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/"), Timeout = TimeSpan.FromSeconds(30) };
    }

    /// <summary>POST a V2 command. Error bodies are {"error": "..."}; only the status is surfaced.</summary>
    private async Task<JsonNode?> CallAsync(string op, string command, JsonObject body, CancellationToken ct)
    {
        if (command != "auth") body["token"] = _token;
        using var resp = await _http.PostAsJsonAsync(command, body, ct);
        var text = await resp.Content.ReadAsStringAsync(ct);
        if (!resp.IsSuccessStatusCode) throw new AkeylessException(op, (int)resp.StatusCode);
        return text.Length == 0 ? null : JsonNode.Parse(text);
    }

    public async Task LoginAsync(string accessId, string accessKey, CancellationToken ct = default)
    {
        var out_ = await CallAsync("auth", "auth",
            new JsonObject { ["access-type"] = "access_key", ["access-id"] = accessId, ["access-key"] = accessKey }, ct);
        _token = out_?["token"]?.GetValue<string>() ?? throw new InvalidOperationException("auth: no token in response");
    }

    /// <summary>Fails if an item with this name already exists (create-secret is not an upsert).</summary>
    public Task CreateAsync(string name, string value, CancellationToken ct = default) =>
        CallAsync("create", "create-secret", new JsonObject { ["name"] = name, ["value"] = value }, ct);

    public async Task<string> ReadAsync(string name, CancellationToken ct = default)
    {
        var out_ = await CallAsync("read", "get-secret-value", new JsonObject { ["names"] = new JsonArray(name) }, ct);
        return out_?[name]?.GetValue<string>() ?? throw new InvalidOperationException($"read: no value for {name}");
    }

    public async Task<int> LastVersionAsync(string name, CancellationToken ct = default)
    {
        var item = await CallAsync("describe", "describe-item", new JsonObject { ["name"] = name }, ct);
        return item?["last_version"]?.GetValue<int>() ?? 0;
    }

    /// <summary>keep-prev-version=true writes a new version instead of overwriting the latest one.</summary>
    public Task UpdateAsync(string name, string value, CancellationToken ct = default) =>
        CallAsync("update", "update-secret-val",
            new JsonObject { ["name"] = name, ["value"] = value, ["keep-prev-version"] = "true" }, ct);

    /// <summary>version -1 deletes the item with all versions.</summary>
    public Task DeleteAsync(string name, CancellationToken ct = default) =>
        CallAsync("delete", "delete-item", new JsonObject { ["name"] = name, ["version"] = -1 }, ct);
}

public static class Program
{
    private static string Need(string k) =>
        Environment.GetEnvironmentVariable(k) is { Length: > 0 } v ? v : throw new InvalidOperationException($"set {k}");

    private static string RandomValue() =>
        Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private static bool Same(string a, string b) =>
        CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(a), Encoding.UTF8.GetBytes(b));

    public static async Task<int> Main()
    {
        try
        {
            var name = Need("SECRET_NAME");
            var store = new AkeylessStore(Environment.GetEnvironmentVariable("AKEYLESS_GATEWAY_URL") ?? "https://api.akeyless.io");
            await store.LoginAsync(Need("AKEYLESS_ACCESS_ID"), (await File.ReadAllTextAsync(Need("AKEYLESS_ACCESS_KEY_FILE"))).Trim());

            var v1 = RandomValue();
            await store.CreateAsync(name, v1);
            Console.WriteLine($"created: {name} version {await store.LastVersionAsync(name)}");
            if (!Same(v1, await store.ReadAsync(name))) throw new InvalidOperationException("read-back after create did not match");

            var v2 = RandomValue();
            await store.UpdateAsync(name, v2);
            if (!Same(v2, await store.ReadAsync(name))) throw new InvalidOperationException("read-back after update did not match");
            Console.WriteLine($"updated: version {await store.LastVersionAsync(name)}");

            await store.DeleteAsync(name);
            Console.WriteLine($"deleted: {name}");
            return 0;
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"{e.GetType().Name}: {e.Message}");   // status codes and names, never values
            return 1;
        }
    }
}
```

### 9.5 Java

Maven `io.akeyless:akeyless-java:5.0.40` (Java 11+ for `Files.readString`/`List.of`). Never enable `ApiClient.setDebugging(true)` outside a sandbox: it logs bodies, which contain the token and values.

```java
// Akeyless static-secret CRUD with the official Java SDK.
// Maven: io.akeyless:akeyless-java:5.0.40 (OkHttp + Gson; Java 8+).
// Auth: API Key auth method; the access key is read from AKEYLESS_ACCESS_KEY_FILE.
package example;

import io.akeyless.client.ApiClient;
import io.akeyless.client.ApiException;
import io.akeyless.client.api.V2Api;
import io.akeyless.client.model.Auth;
import io.akeyless.client.model.CreateSecret;
import io.akeyless.client.model.DeleteItem;
import io.akeyless.client.model.DescribeItem;
import io.akeyless.client.model.GetSecretValue;
import io.akeyless.client.model.UpdateSecretVal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.List;
import java.util.Map;

public final class AkeylessCrud {
    private final V2Api api;
    private final String token;

    private AkeylessCrud(V2Api api, String token) {
        this.api = api;
        this.token = token;
    }

    static AkeylessCrud login(String host, String accessId, String accessKey) throws ApiException {
        boolean loopback = host.matches("^http://(127\\.0\\.0\\.1|localhost):.*");
        if (!host.startsWith("https://") && !loopback) throw new IllegalArgumentException("AKEYLESS_GATEWAY_URL must use https");
        ApiClient client = new ApiClient();
        client.setBasePath(host.replaceAll("/+$", ""));
        client.setConnectTimeout(10_000);
        client.setReadTimeout(30_000);
        // Never enable client.setDebugging(true) outside a sandbox: it logs request bodies, which carry the token.
        V2Api api = new V2Api(client);
        String token = api.auth(new Auth().accessType("access_key").accessId(accessId).accessKey(accessKey)).getToken();
        return new AkeylessCrud(api, token);
    }

    /** Fails if an item with this name already exists (create-secret is not an upsert). */
    void create(String name, String value) throws ApiException {
        api.createSecret(new CreateSecret().name(name).value(value).token(token));
    }

    String read(String name) throws ApiException {
        Map<String, Object> out = api.getSecretValue(new GetSecretValue().names(List.of(name)).token(token));
        Object v = out.get(name);
        if (!(v instanceof String)) throw new IllegalStateException("no string value for " + name);
        return (String) v;
    }

    int lastVersion(String name) throws ApiException {
        Integer v = api.describeItem(new DescribeItem().name(name).token(token)).getLastVersion();
        return v == null ? 0 : v;
    }

    /** keep-prev-version=true writes a new version instead of overwriting the latest one. */
    void update(String name, String value) throws ApiException {
        api.updateSecretVal(new UpdateSecretVal().name(name).value(value).keepPrevVersion("true").token(token));
    }

    /** version -1 deletes the item with all versions. */
    void delete(String name) throws ApiException {
        api.deleteItem(new DeleteItem().name(name).version(-1).token(token));
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
        try {
            String name = need("SECRET_NAME");
            String accessKey = Files.readString(Path.of(need("AKEYLESS_ACCESS_KEY_FILE"))).strip();
            String host = System.getenv().getOrDefault("AKEYLESS_GATEWAY_URL", "https://api.akeyless.io");
            AkeylessCrud store = login(host, need("AKEYLESS_ACCESS_ID"), accessKey);

            String v1 = randomValue();
            store.create(name, v1);
            System.out.println("created: " + name + " version " + store.lastVersion(name));
            if (!same(v1, store.read(name))) throw new IllegalStateException("read-back after create did not match");

            String v2 = randomValue();
            store.update(name, v2);
            if (!same(v2, store.read(name))) throw new IllegalStateException("read-back after update did not match");
            System.out.println("updated: version " + store.lastVersion(name));

            store.delete(name);
            System.out.println("deleted: " + name);
        } catch (ApiException e) {
            // ApiException.getMessage() includes the response body and headers; log the status code only.
            System.err.println("Akeyless API error: HTTP " + e.getCode());
            System.exit(1);
        } catch (Exception e) {
            System.err.println(e.getClass().getSimpleName() + ": " + e.getMessage());
            System.exit(1);
        }
    }
}
```

### 9.6 Swift

Foundation only; runs on macOS and Linux. Server-side only.

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
// Akeyless static-secret CRUD in Swift over the V2 REST API (Foundation only; no official Swift SDK).
// Every V2 call is a JSON POST; the session token travels in the body field "token".
// Auth: API Key auth method; the access key is read from AKEYLESS_ACCESS_KEY_FILE.
// Server-side use only: never ship an access key inside an app bundle.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
#if canImport(Security)
import Security
#endif

enum AkeylessError: Error, CustomStringConvertible {
    case http(op: String, status: Int)   // the {"error": ...} body is not surfaced
    case config(String)
    var description: String {
        switch self {
        case let .http(op, status): return "\(op): HTTP \(status)"
        case let .config(m): return m
        }
    }
}

final class AkeylessStore {
    private let base: String
    private var token = ""
    private let session = URLSession(configuration: .ephemeral)

    init(baseURL: String = "https://api.akeyless.io") throws {
        let loopback = baseURL.hasPrefix("http://127.0.0.1:") || baseURL.hasPrefix("http://localhost:")
        guard baseURL.hasPrefix("https://") || loopback else { throw AkeylessError.config("AKEYLESS_GATEWAY_URL must use https") }
        var b = baseURL
        while b.hasSuffix("/") { b.removeLast() }
        base = b
    }

    @discardableResult
    private func call(_ op: String, _ command: String, _ body: [String: Any]) async throws -> [String: Any] {
        var payload = body
        if command != "auth" { payload["token"] = token }
        var req = URLRequest(url: URL(string: "\(base)/\(command)")!)
        req.httpMethod = "POST"
        req.timeoutInterval = 30
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200...299).contains(status) else { throw AkeylessError.http(op: op, status: status) }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
    }

    func login(accessID: String, accessKey: String) async throws {
        let out = try await call("auth", "auth", ["access-type": "access_key", "access-id": accessID, "access-key": accessKey])
        guard let t = out["token"] as? String else { throw AkeylessError.config("auth: no token in response") }
        token = t
    }

    /// Fails if an item with this name already exists (create-secret is not an upsert).
    func create(_ name: String, _ value: String) async throws {
        try await call("create", "create-secret", ["name": name, "value": value])
    }

    func read(_ name: String) async throws -> String {
        let out = try await call("read", "get-secret-value", ["names": [name]])
        guard let v = out[name] as? String else { throw AkeylessError.config("read: no value for \(name)") }
        return v
    }

    func lastVersion(_ name: String) async throws -> Int {
        (try await call("describe", "describe-item", ["name": name])["last_version"] as? Int) ?? 0
    }

    /// keep-prev-version=true writes a new version instead of overwriting the latest one.
    func update(_ name: String, _ value: String) async throws {
        try await call("update", "update-secret-val", ["name": name, "value": value, "keep-prev-version": "true"])
    }

    /// version -1 deletes the item with all versions.
    func delete(_ name: String) async throws {
        try await call("delete", "delete-item", ["name": name, "version": -1])
    }
}

func randomValue() throws -> String {
    var bytes = [UInt8](repeating: 0, count: 32)
    #if canImport(Security)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
        throw AkeylessError.config("csprng failure")
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
    guard let v = ProcessInfo.processInfo.environment[k], !v.isEmpty else { throw AkeylessError.config("set \(k)") }
    return v
}

do {
    let name = try need("SECRET_NAME")
    let store = try AkeylessStore(baseURL: ProcessInfo.processInfo.environment["AKEYLESS_GATEWAY_URL"] ?? "https://api.akeyless.io")
    let key = try String(contentsOfFile: try need("AKEYLESS_ACCESS_KEY_FILE"), encoding: .utf8)
        .trimmingCharacters(in: .whitespacesAndNewlines)
    try await store.login(accessID: try need("AKEYLESS_ACCESS_ID"), accessKey: key)

    let v1 = try randomValue()
    try await store.create(name, v1)
    print("created: \(name) version \(try await store.lastVersion(name))")
    guard same(v1, try await store.read(name)) else { throw AkeylessError.config("read-back after create did not match") }

    let v2 = try randomValue()
    try await store.update(name, v2)
    guard same(v2, try await store.read(name)) else { throw AkeylessError.config("read-back after update did not match") }
    print("updated: version \(try await store.lastVersion(name))")

    try await store.delete(name)
    print("deleted: \(name)")
} catch {
    FileHandle.standardError.write("\(error)\n".data(using: .utf8)!)   // operation and status only, never values
    exit(1)
}
```

### 9.7 Python

`pip install akeyless==5.0.40`. Failures raise `akeyless.rest.ApiException` with `status`, `reason`, and `body`.

```python
"""Akeyless static-secret CRUD with the official Python SDK.

pip install akeyless==5.0.40
Auth: API Key auth method (access ID + access key); the access key is read from AKEYLESS_ACCESS_KEY_FILE.
Prefer a cloud/Kubernetes/OIDC auth method in production (see section 2); only the Auth body changes.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys

import akeyless
from akeyless.rest import ApiException


class AkeylessStore:
    def __init__(self, host: str, access_id: str, access_key: str) -> None:
        if not host.startswith("https://") and not host.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("AKEYLESS_GATEWAY_URL must use https")
        cfg = akeyless.Configuration(host=host.rstrip("/"))
        self.api = akeyless.V2Api(akeyless.ApiClient(cfg))
        self._access_id, self._access_key = access_id, access_key
        self._token = ""

    def login(self) -> None:
        """Exchange the API key for a short-lived session token (call again when it expires)."""
        out = self.api.auth(akeyless.Auth(access_type="access_key", access_id=self._access_id,
                                          access_key=self._access_key))
        self._token = out.token

    def create(self, name: str, value: str) -> None:
        """Fails if an item with this name already exists (create-secret is not an upsert)."""
        self.api.create_secret(akeyless.CreateSecret(name=name, value=value, token=self._token))

    def read(self, name: str, version: int | None = None) -> str:
        out = self.api.get_secret_value(akeyless.GetSecretValue(names=[name], version=version, token=self._token))
        return out[name]

    def last_version(self, name: str) -> int:
        return self.api.describe_item(akeyless.DescribeItem(name=name, token=self._token)).last_version

    def update(self, name: str, value: str) -> None:
        """keep-prev-version=true creates a new version instead of overwriting the latest one."""
        self.api.update_secret_val(akeyless.UpdateSecretVal(name=name, value=value, keep_prev_version="true",
                                                            token=self._token))

    def delete(self, name: str) -> None:
        """version=-1 (the SDK default) deletes the item with all of its versions."""
        self.api.delete_item(akeyless.DeleteItem(name=name, version=-1, token=self._token))


def main() -> int:
    env = os.environ
    try:
        name, access_id = env["SECRET_NAME"], env["AKEYLESS_ACCESS_ID"]
        with open(env["AKEYLESS_ACCESS_KEY_FILE"], encoding="utf-8") as fh:
            access_key = fh.read().strip()
    except KeyError as missing:
        print(f"set {missing}", file=sys.stderr)
        return 2
    store = AkeylessStore(env.get("AKEYLESS_GATEWAY_URL", "https://api.akeyless.io"), access_id, access_key)
    del access_key
    try:
        store.login()
        v1 = secrets.token_urlsafe(32)
        store.create(name, v1)
        print(f"created: {name} version {store.last_version(name)}")
        if not hmac.compare_digest(v1, store.read(name)):
            raise RuntimeError("read-back after create did not match")

        v2 = secrets.token_urlsafe(32)
        store.update(name, v2)
        if not hmac.compare_digest(v2, store.read(name)):
            raise RuntimeError("read-back after update did not match")
        print(f"updated: version {store.last_version(name)}")

        store.delete(name)
        print(f"deleted: {name}")
        return 0
    except ApiException as exc:
        # exc.body is the server's {"error": ...} JSON; it names items, not values. Log status + reason only.
        print(f"Akeyless API error: HTTP {exc.status} {exc.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

`npm i akeyless@5.0.40`. The package is generated JavaScript (CommonJS, superagent) without type declarations; import it as a namespace and declare the subset you use:

`akeyless.d.ts`:

```typescript
// Minimal typings for the parts of the untyped "akeyless" npm package (5.0.40) used by crud.ts.
declare module "akeyless" {
  type Body = Record<string, unknown>;
  interface Model { constructFromObject(data: Body): Body }
  export class ApiClient {
    constructor(basePath?: string);
    basePath: string;
    timeout: number;
  }
  export class V2Api {
    constructor(client: ApiClient);
    auth(body: Body): Promise<{ token?: string; expiration?: string }>;
    createSecret(body: Body): Promise<{ name?: string }>;
    getSecretValue(body: Body): Promise<Record<string, unknown>>;
    describeItem(body: Body): Promise<{ last_version?: number }>;
    updateSecretVal(body: Body): Promise<{ name?: string }>;
    deleteItem(body: Body): Promise<{ deletion_date?: string }>;
  }
  export const Auth: Model;
  export const CreateSecret: Model;
  export const GetSecretValue: Model;
  export const DescribeItem: Model;
  export const UpdateSecretVal: Model;
  export const DeleteItem: Model;
}
```

```typescript
// Akeyless static-secret CRUD with the official JavaScript SDK (npm i akeyless@5.0.40; untyped,
// so akeyless.d.ts declares the subset used here). Auth: API Key; access key read from a file.
// Rejections are plain objects holding the superagent response (and request) — never log them.
import { readFile } from "node:fs/promises";
import { randomBytes, timingSafeEqual } from "node:crypto";
import * as akeyless from "akeyless";

class AkeylessError extends Error {}

/** Reduce an SDK rejection to operation + HTTP status (the raw object can include the request body with the token). */
function wrap(op: string): (err: unknown) => never {
  return (err: unknown) => {
    const status = typeof err === "object" && err !== null && "status" in err ? (err as { status?: number }).status : undefined;
    throw new AkeylessError(`${op}: HTTP ${status ?? "transport error"}`);
  };
}

export class AkeylessStore {
  private constructor(private readonly api: InstanceType<typeof akeyless.V2Api>, private readonly token: string) {}

  static async login(host: string, accessId: string, accessKey: string): Promise<AkeylessStore> {
    if (!host.startsWith("https://") && !/^http:\/\/(127\.0\.0\.1|localhost):/.test(host)) {
      throw new Error("AKEYLESS_GATEWAY_URL must use https");
    }
    const client = new akeyless.ApiClient(host.replace(/\/+$/, ""));
    client.timeout = 30_000;
    const api = new akeyless.V2Api(client);
    const out = await api
      .auth(akeyless.Auth.constructFromObject({ "access-type": "access_key", "access-id": accessId, "access-key": accessKey }))
      .catch(wrap("auth"));
    if (!out.token) throw new AkeylessError("auth: no token in response");
    return new AkeylessStore(api, out.token);
  }

  /** Fails if an item with this name already exists (create-secret is not an upsert). */
  async create(name: string, value: string): Promise<void> {
    await this.api.createSecret(akeyless.CreateSecret.constructFromObject({ name, value, token: this.token })).catch(wrap("create"));
  }

  async read(name: string): Promise<string> {
    const out = await this.api
      .getSecretValue(akeyless.GetSecretValue.constructFromObject({ names: [name], token: this.token }))
      .catch(wrap("read"));
    const v = out[name];
    if (typeof v !== "string") throw new AkeylessError(`read: no string value for ${name}`);
    return v;
  }

  async lastVersion(name: string): Promise<number> {
    const item = await this.api.describeItem(akeyless.DescribeItem.constructFromObject({ name, token: this.token })).catch(wrap("describe"));
    return item.last_version ?? 0;
  }

  /** keep-prev-version=true writes a new version instead of overwriting the latest one. */
  async update(name: string, value: string): Promise<void> {
    await this.api
      .updateSecretVal(akeyless.UpdateSecretVal.constructFromObject({ name, value, "keep-prev-version": "true", token: this.token }))
      .catch(wrap("update"));
  }

  /** version -1 deletes the item with all versions. */
  async delete(name: string): Promise<void> {
    await this.api.deleteItem(akeyless.DeleteItem.constructFromObject({ name, version: -1, token: this.token })).catch(wrap("delete"));
  }
}

const randomValue = (): string => randomBytes(32).toString("base64url");
const same = (a: string, b: string): boolean => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

async function main(): Promise<void> {
  const { SECRET_NAME: name, AKEYLESS_ACCESS_ID: accessId, AKEYLESS_ACCESS_KEY_FILE: keyFile } = process.env;
  if (!name || !accessId || !keyFile) throw new Error("set SECRET_NAME, AKEYLESS_ACCESS_ID, AKEYLESS_ACCESS_KEY_FILE");
  const store = await AkeylessStore.login(
    process.env.AKEYLESS_GATEWAY_URL ?? "https://api.akeyless.io",
    accessId,
    (await readFile(keyFile, "utf8")).trim(),
  );

  const v1 = randomValue();
  await store.create(name, v1);
  console.log(`created: ${name} version ${await store.lastVersion(name)}`);
  if (!same(v1, await store.read(name))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  await store.update(name, v2);
  if (!same(v2, await store.read(name))) throw new Error("read-back after update did not match");
  console.log(`updated: version ${await store.lastVersion(name)}`);

  await store.delete(name);
  console.log(`deleted: ${name}`);
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? `${err.name}: ${err.message}` : "unknown error");
  process.exitCode = 1;
});
```

### 9.9 C++

C++17, libcurl, nlohmann/json, OpenSSL.

```cpp
// Akeyless static-secret CRUD over the V2 REST API with libcurl + nlohmann/json (C++17).
// Akeyless ships no C++ SDK. Every V2 call is a JSON POST; the session token travels in the body.
//   g++ -std=c++17 -O2 main.cpp -o akeyless_crud $(pkg-config --cflags --libs libcurl openssl)
// Auth: API Key auth method; the access key is read from AKEYLESS_ACCESS_KEY_FILE.
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

struct AkeylessError : std::runtime_error {
  long status;
  AkeylessError(const std::string& op, long st)  // the {"error": ...} body is not surfaced
      : std::runtime_error(op + ": HTTP " + std::to_string(st)), status(st) {}
};

class AkeylessStore {
 public:
  explicit AkeylessStore(std::string base) : base_(std::move(base)) {
    while (!base_.empty() && base_.back() == '/') base_.pop_back();
    bool loopback = std::regex_search(base_, std::regex("^http://(127\\.0\\.0\\.1|localhost):"));
    if (base_.rfind("https://", 0) != 0 && !loopback) throw std::runtime_error("AKEYLESS_GATEWAY_URL must use https");
    https_only_ = !loopback;
  }
  ~AkeylessStore() { wipe(token_); }
  AkeylessStore(const AkeylessStore&) = delete;
  AkeylessStore& operator=(const AkeylessStore&) = delete;

  void login(const std::string& access_id, const std::string& access_key) {
    json out = call("auth", "auth", {{"access-type", "access_key"}, {"access-id", access_id}, {"access-key", access_key}});
    if (!out.contains("token") || !out["token"].is_string()) throw std::runtime_error("auth: no token in response");
    token_ = out["token"].get<std::string>();
    wipe(*out["token"].get_ptr<std::string*>());
  }

  // Fails if an item with this name already exists (create-secret is not an upsert).
  void create(const std::string& name, const std::string& value) {
    call("create", "create-secret", {{"name", name}, {"value", value}});
  }

  std::string read(const std::string& name) {
    json out = call("read", "get-secret-value", {{"names", json::array({name})}});
    if (!out.contains(name) || !out[name].is_string()) throw std::runtime_error("read: no value for " + name);
    std::string v = out[name].get<std::string>();
    wipe(*out[name].get_ptr<std::string*>());
    return v;
  }

  long last_version(const std::string& name) {
    json item = call("describe", "describe-item", {{"name", name}});
    return item.value("last_version", 0L);
  }

  // keep-prev-version=true writes a new version instead of overwriting the latest one.
  void update(const std::string& name, const std::string& value) {
    call("update", "update-secret-val", {{"name", name}, {"value", value}, {"keep-prev-version", "true"}});
  }

  // version -1 deletes the item with all versions.
  void remove(const std::string& name) { call("delete", "delete-item", {{"name", name}, {"version", -1}}); }

 private:
  std::string base_, token_;
  bool https_only_ = true;

  static size_t on_body(char* p, size_t s, size_t n, void* u) {
    static_cast<std::string*>(u)->append(p, s * n);
    return s * n;
  }

  json call(const char* op, const std::string& command, json body) {
    if (command != "auth") body["token"] = token_;
    std::string payload = body.dump(), resp;
    for (auto& [k, v] : body.items()) {  // wipe string copies held by the json tree
      if (v.is_string()) wipe(*v.get_ptr<std::string*>());
    }
    std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> c(curl_easy_init(), curl_easy_cleanup);
    curl_slist* h = curl_slist_append(nullptr, "Content-Type: application/json");
    h = curl_slist_append(h, "Accept: application/json");
    std::string url = base_ + "/" + command;
    curl_easy_setopt(c.get(), CURLOPT_URL, url.c_str());
    curl_easy_setopt(c.get(), CURLOPT_POSTFIELDS, payload.c_str());
    curl_easy_setopt(c.get(), CURLOPT_HTTPHEADER, h);
    curl_easy_setopt(c.get(), CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(c.get(), CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c.get(), CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(c.get(), CURLOPT_PROTOCOLS_STR, https_only_ ? "https" : "http");
    CURLcode rc = curl_easy_perform(c.get());
    long status = 0;
    curl_easy_getinfo(c.get(), CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(h);
    wipe(payload);
    if (rc != CURLE_OK) throw std::runtime_error(std::string(op) + ": " + curl_easy_strerror(rc));
    if (status < 200 || status > 299) { wipe(resp); throw AkeylessError(op, status); }
    json out = resp.empty() ? json::object() : json::parse(resp, nullptr, false);
    wipe(resp);
    return out;
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

int main() {
  curl_global_init(CURL_GLOBAL_DEFAULT);
  int rc = 1;
  try {
    const std::string name = need("SECRET_NAME");
    std::ifstream f(need("AKEYLESS_ACCESS_KEY_FILE"));
    std::stringstream ss;
    ss << f.rdbuf();
    std::string key = ss.str();
    while (!key.empty() && (key.back() == '\n' || key.back() == '\r' || key.back() == ' ')) key.pop_back();
    const char* base = std::getenv("AKEYLESS_GATEWAY_URL");
    AkeylessStore store(base ? base : "https://api.akeyless.io");
    store.login(need("AKEYLESS_ACCESS_ID"), key);
    wipe(key);

    std::string v1 = random_value();
    store.create(name, v1);
    std::cout << "created: " << name << " version " << store.last_version(name) << "\n";
    std::string got = store.read(name);
    if (!same(v1, got)) throw std::runtime_error("read-back after create did not match");
    wipe(got);

    std::string v2 = random_value();
    store.update(name, v2);
    got = store.read(name);
    if (!same(v2, got)) throw std::runtime_error("read-back after update did not match");
    std::cout << "updated: version " << store.last_version(name) << "\n";
    wipe(got); wipe(v1); wipe(v2);

    store.remove(name);
    std::cout << "deleted: " << name << "\n";
    rc = 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << "\n";  // operation and status only, never values
  }
  curl_global_cleanup();
  return rc;
}
```

### 9.10 C

C11, libcurl, cJSON, OpenSSL. Wipes the access key, token, request bodies, and value buffers.

```c
/*
 * Akeyless static-secret CRUD in C over the V2 REST API: libcurl + cJSON + OpenSSL (no official C SDK).
 * Every V2 call is a JSON POST; the session token travels in the body field "token".
 *
 *   cc -std=c11 -Wall -Wextra -O2 akeyless_crud.c -o akeyless_crud \
 *      $(pkg-config --cflags --libs libcurl libcjson openssl)
 *
 * Auth: API Key auth method; the access key is read from AKEYLESS_ACCESS_KEY_FILE.
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

typedef struct { char *data; size_t len; } buf_t;

static char g_base[512];
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

static int loopback(const char *u) {
    return strncmp(u, "http://127.0.0.1:", 17) == 0 || strncmp(u, "http://localhost:", 17) == 0;
}

/* Wipe every string in a cJSON tree (values and the token) before it is freed. */
static void json_wipe(cJSON *n) {
    for (; n; n = n->next) {
        if (cJSON_IsString(n) && n->valuestring) OPENSSL_cleanse(n->valuestring, strlen(n->valuestring));
        if (n->child) json_wipe(n->child);
    }
}

/* POST one V2 command; consumes body. Returns HTTP status (0 on transport error); *out gets parsed JSON.
 * Error bodies are {"error": "..."}; only the status is printed. */
static long ak_call(const char *op, const char *command, cJSON *body, cJSON **out) {
    if (strcmp(command, "auth") != 0) cJSON_AddStringToObject(body, "token", g_token);
    char url[640];
    snprintf(url, sizeof url, "%s/%s", g_base, command);
    char *json = cJSON_PrintUnformatted(body);
    json_wipe(body);
    cJSON_Delete(body);
    struct curl_slist *h = curl_slist_append(NULL, "Content-Type: application/json");
    h = curl_slist_append(h, "Accept: application/json");
    buf_t resp = {0};
    CURL *c = curl_easy_init();
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_POSTFIELDS, json);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, h);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, loopback(g_base) ? "http" : "https");
    long status = 0;
    if (curl_easy_perform(c) == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    curl_slist_free_all(h);
    if (json) { OPENSSL_cleanse(json, strlen(json)); cJSON_free(json); }
    if (status < 200 || status > 299) fprintf(stderr, "%s: HTTP %ld\n", op, status);
    if (out) *out = (status >= 200 && status <= 299 && resp.len) ? cJSON_Parse(resp.data) : NULL;
    buf_wipe(&resp);
    return status;
}

static int login(const char *access_id, const char *access_key) {
    cJSON *b = cJSON_CreateObject(), *out = NULL;
    cJSON_AddStringToObject(b, "access-type", "access_key");
    cJSON_AddStringToObject(b, "access-id", access_id);
    cJSON_AddStringToObject(b, "access-key", access_key);
    long st = ak_call("auth", "auth", b, &out);
    const cJSON *t = cJSON_GetObjectItemCaseSensitive(out, "token");
    if (st == 200 && cJSON_IsString(t)) g_token = strdup(t->valuestring);
    json_wipe(out);
    cJSON_Delete(out);
    return g_token ? 0 : -1;
}

/* Fails if an item with this name already exists (create-secret is not an upsert). */
static int secret_create(const char *name, const char *value) {
    cJSON *b = cJSON_CreateObject();
    cJSON_AddStringToObject(b, "name", name);
    cJSON_AddStringToObject(b, "value", value);
    return ak_call("create", "create-secret", b, NULL) == 200 ? 0 : -1;
}

/* Returns a malloc'd value (wipe + free), or NULL. */
static char *secret_read(const char *name) {
    cJSON *b = cJSON_CreateObject(), *out = NULL;
    cJSON_AddItemToArray(cJSON_AddArrayToObject(b, "names"), cJSON_CreateString(name));
    long st = ak_call("read", "get-secret-value", b, &out);
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(out, name);
    char *r = (st == 200 && cJSON_IsString(v)) ? strdup(v->valuestring) : NULL;
    json_wipe(out);
    cJSON_Delete(out);
    return r;
}

static int last_version(const char *name) {
    cJSON *b = cJSON_CreateObject(), *out = NULL;
    cJSON_AddStringToObject(b, "name", name);
    ak_call("describe", "describe-item", b, &out);
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(out, "last_version");
    int r = cJSON_IsNumber(v) ? v->valueint : -1;
    cJSON_Delete(out);
    return r;
}

/* keep-prev-version=true writes a new version instead of overwriting the latest one. */
static int secret_update(const char *name, const char *value) {
    cJSON *b = cJSON_CreateObject();
    cJSON_AddStringToObject(b, "name", name);
    cJSON_AddStringToObject(b, "value", value);
    cJSON_AddStringToObject(b, "keep-prev-version", "true");
    return ak_call("update", "update-secret-val", b, NULL) == 200 ? 0 : -1;
}

/* version -1 deletes the item with all versions. */
static int secret_delete(const char *name) {
    cJSON *b = cJSON_CreateObject();
    cJSON_AddStringToObject(b, "name", name);
    cJSON_AddNumberToObject(b, "version", -1);
    return ak_call("delete", "delete-item", b, NULL) == 200 ? 0 : -1;
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

static int read_key(const char *file, char *buf, size_t cap) {
    FILE *f = fopen(file, "r");
    if (!f) return -1;
    size_t n = fread(buf, 1, cap - 1, f);
    fclose(f);
    buf[n] = '\0';
    while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r' || buf[n - 1] == ' ')) buf[--n] = '\0';
    return n ? 0 : -1;
}

int main(void) {
    const char *name = getenv("SECRET_NAME"), *id = getenv("AKEYLESS_ACCESS_ID");
    const char *kf = getenv("AKEYLESS_ACCESS_KEY_FILE"), *base = getenv("AKEYLESS_GATEWAY_URL");
    if (!name || !id || !kf) { fprintf(stderr, "set SECRET_NAME, AKEYLESS_ACCESS_ID, AKEYLESS_ACCESS_KEY_FILE\n"); return 2; }
    snprintf(g_base, sizeof g_base, "%s", base ? base : "https://api.akeyless.io");
    for (size_t n = strlen(g_base); n && g_base[n - 1] == '/'; n--) g_base[n - 1] = '\0';
    if (strncmp(g_base, "https://", 8) != 0 && !loopback(g_base)) { fprintf(stderr, "AKEYLESS_GATEWAY_URL must use https\n"); return 2; }

    curl_global_init(CURL_GLOBAL_DEFAULT);
    int rc = 1;
    char key[512], v1[45], v2[45], *got = NULL;
    if (read_key(kf, key, sizeof key) != 0) { fprintf(stderr, "cannot read access key file\n"); goto done; }
    if (login(id, key) != 0) goto done;
    OPENSSL_cleanse(key, sizeof key);
    if (random_value(v1) || random_value(v2)) goto done;

    if (secret_create(name, v1) != 0) goto done;
    printf("created: %s version %d\n", name, last_version(name));
    got = secret_read(name);
    if (!same(v1, got)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    str_wipe_free(got); got = NULL;

    if (secret_update(name, v2) != 0) goto done;
    got = secret_read(name);
    if (!same(v2, got)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated: version %d\n", last_version(name));

    if (secret_delete(name) != 0) goto done;
    printf("deleted: %s\n", name);
    rc = 0;
done:
    str_wipe_free(got);
    str_wipe_free(g_token);
    OPENSSL_cleanse(key, sizeof key);
    OPENSSL_cleanse(v1, sizeof v1); OPENSSL_cleanse(v2, sizeof v2);
    curl_global_cleanup();
    return rc;
}
```

## 10. Use secrets in applications

| Mechanism | How values arrive | Notes |
| --- | --- | --- |
| SDK/REST at startup + cache (section 9) | In memory | Explicit control; re-auth on expiry. |
| Gateway (in-network) | Same API, served close to the app with caching | Lower latency and resilience; cache staleness after updates. |
| Kubernetes Secrets Injector (mutating webhook) | Files or env vars injected into pods | Uses the `k8s` auth method through the Gateway; no Kubernetes `Secret` object needed. |
| External Secrets Operator / CSI provider | Synced Kubernetes `Secret` or mounted files | `Secret` sync widens exposure to anyone who can read Secrets in the namespace. |
| CLI in scripts (`akeyless get-secret-value`) | Stdout | Redirect to protected files; profile files hold credentials. |

Rotation-safe consumption: cache with a TTL; re-read once (with `ignore-cache=true` if the Gateway is in the path) on downstream authentication failure; read many names in one `get-secret-value` call.

## 11. Automation and error handling

Error responses are JSON objects with one `error` field. Typical causes and actions (exact status codes are not documented in the API reference; branch on 2xx vs not, and log the status):

| Situation | Typical cause | Action |
| --- | --- | --- |
| Auth fails | Wrong access ID/key; bound-IP mismatch; access expired; cloud-id from the wrong account/role | Check the auth method settings; platform methods: check the workload identity. |
| Calls fail after working | Session token expired | Re-run `/auth`; refresh before `expiration`. |
| Permission denied | No role rule with that capability on that path; sub-claims don't match | Add the rule on the narrowest path; check `assoc-role-am --sub-claims`. |
| Create fails | Item already exists | Treat create as create-only; use update for existing items. |
| Read/update/delete fails | Item not found; wrong path (leading slash, folder) | Use the full path returned by `list-items`. |
| Delete refused | Delete protection enabled | Turn it off deliberately via `update-item`, then delete. |
| Value too large | Over 16 KB | Store a reference or split; consider a file store encrypted with an Akeyless key. |

Practices:

- One auth method (or one sub-claim binding) per workload per environment; never share access keys between services.
- Separate reader and writer roles; writers own their path prefix.
- `keep-prev-version=true` on every automated update; delete protection on production secrets.
- Retry transport errors and 5xx for reads with jittered backoff; do not blindly retry writes — re-read and compare.

## 12. Optional live CRUD verification

This **performs writes** under the path you choose (use a sandbox folder your role can create/delete in). With `AKL` and an exported `AKL_TOKEN` from section 2:

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${AKL:?}" "${AKL_TOKEN:?}"
work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
name="/sandbox/CRUD_CHECK_$(date -u +%Y%m%d%H%M%S)_$$"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v1"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v2"
post() { curl -sSf -H 'Content-Type: application/json' --data @- "$AKL/$1"; }
read_val() { jq -n --arg n "$name" '{names:[$n], "ignore-cache":"true", token:env.AKL_TOKEN}' | post get-secret-value | jq -j --arg n "$name" '.[$n]'; }

jq -n --arg n "$name" --rawfile v "$work/v1" '{name:$n, value:$v, token:env.AKL_TOKEN}' | post create-secret > /dev/null
read_val | cmp -s - "$work/v1"
jq -n --arg n "$name" --rawfile v "$work/v2" '{name:$n, value:$v, "keep-prev-version":"true", token:env.AKL_TOKEN}' | post update-secret-val > /dev/null
read_val | cmp -s - "$work/v2"
jq -n --arg n "$name" '{name:$n, version:-1, token:env.AKL_TOKEN}' | post delete-item > /dev/null
printf 'PASS: create, read, update, and delete completed.\n'
```

Or run any program from section 9 with `SECRET_NAME`, `AKEYLESS_ACCESS_ID`, and `AKEYLESS_ACCESS_KEY_FILE` set.

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| Auth works locally, fails in production | Bound IPs on the API key; cloud auth method bound to a different account/role/service account. |
| `k8s` auth fails | Gateway URL and `k8s-auth-config-name`; the Gateway must reach the cluster's TokenReview API. |
| Read returns the previous value | Gateway cache; read with `ignore-cache=true`; check the update actually succeeded. |
| Update "lost" history | Updated without `keep-prev-version=true` (latest version overwritten). |
| Rollback impossible | No earlier version retained (`max-versions`, overwrite updates). |
| Secret not found but visible in the console | Name lacks the folder path or leading slash; personal-folder items need `accessibility=personal`. |
| Secret value or token appears in logs | SDK debug logging; error objects logged whole; CLI `--value` in history. Remove, rotate, and revoke. |
| Delete fails on a production secret | Delete protection (intended); remove it deliberately. |

## 14. Accuracy notes and official sources

- **SDK versions:** Go, Python, npm, Java, and Ruby SDKs were all at **5.0.40** on the verification date and are regenerated frequently; pin versions and review changes, since generated request defaults (for example `delete-in-days`, `accessibility`) are serialized on every call.
- **Status codes:** the API reference documents `200` and a default error response `{"error": "..."}` for the secret operations, and additionally `401` for `/auth`; the mock's 404/409 choices are assumptions used for testing.
- **`last-version` semantics** on `update-secret-val` are not documented beyond one line; this guide does not rely on them.
- **Gateway paths:** port `8000` serves `/api/v2` (and `/api/v1`, `/hvp`, `/console`); older deployments expose the V2 API on `8081`. [S12]
- **CLI:** command and flag names (`create-secret`, `get-secret-value --version`, `update-secret-val --keep-prev-version`, `rollback-secret --old-version`, `set-role-rule`, `assoc-role-am`) are from the CLI reference pages; the CLI itself is not open source and was not run here.
- **Mock-based verification** validates client logic and request shapes, not server-side permissions, caching, or versioning policy.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [SDK overview (Python)][S01] | Hosts (SaaS vs Gateway), token usage |
| S02 | [Auth methods overview][S02] | Method types, TTL, bound IPs, access expiry |
| S03 | [Universal Identity][S03] | Rotating UID tokens |
| S04 | [API reference: auth / secrets][S04] | Bodies and responses |
| S05 | [CLI reference: access roles][S05] | `set-role-rule`, capabilities, `assoc-role-am` |
| S06 | [Create a static secret][S06] | Paths, folders, 16 KB limit |
| S07 | [Update and version static secrets][S07] | Overwrite vs new version, `--version`, rollback |
| S08 | [CLI reference: static secrets][S08] | create/get/update/rollback flags |
| S09 | [Retrieve a static secret][S09] | `get-secret-value` |
| S10 | [API: update-secret-val][S10] | `keep-prev-version`, `last-version` |
| S11 | [API: delete-item][S11] | `version`, `delete-in-days` scope |
| S12 | [Gateway installation][S12] | Port 8000 paths |
| S13 | [Go SDK][S13] | Go client |
| S14 | [Java SDK][S14] | Java client |
| S15 | [JavaScript SDK][S15] | npm client |

[S01]: https://docs.akeyless.io/docs/python-sdk-1
[S02]: https://docs.akeyless.io/docs/access-and-authentication-methods
[S03]: https://docs.akeyless.io/docs/universal-identity
[S04]: https://docs.akeyless.io/reference/auth
[S05]: https://docs.akeyless.io/docs/cli-reference-access-roles
[S06]: https://docs.akeyless.io/docs/create-secret
[S07]: https://docs.akeyless.io/docs/staticversions
[S08]: https://docs.akeyless.io/docs/cli-reference-static-secrets
[S09]: https://docs.akeyless.io/docs/retrievestatic
[S10]: https://docs.akeyless.io/reference/updatesecretval
[S11]: https://docs.akeyless.io/reference/deleteitem
[S12]: https://docs.akeyless.io/docs/install-and-configure-the-gateway
[S13]: https://github.com/akeylesslabs/akeyless-go
[S14]: https://github.com/akeylesslabs/akeyless-java
[S15]: https://github.com/akeylesslabs/akeyless-javascript
