# Doppler: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** Doppler SecretOps platform. REST: `https://api.doppler.com/v3/configs/config/secret` (read, delete) and `/v3/configs/config/secrets` (list, create, update, batch)  
**Primary authentication:** a **service account** API token (granular, multi-project), a **service account identity** token obtained by OIDC exchange (short-lived), or a per-config **service token** (`dp.st.` prefix); all sent as `Authorization: Bearer <token>`  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use Bash and the Doppler CLI)

This guide covers **secrets in a Doppler config**: key/value pairs addressed by **project → config** (a config belongs to an environment such as `dev`, `stg`, `prd`; branch configs such as `dev_alice` inherit from their root config). It covers token types and least privilege, complete CRUD workflows with the `change_requests` write format, optimistic concurrency with `originalValue`, a full CRUD program in each of ten languages, runtime consumption (`doppler run`, mounts, fallback files, Kubernetes Operator, integration syncs), and troubleshooting. Dynamic secrets, rotation integrations, and change-request approval flows are out of scope except where they affect design.

Tokens are assumed to be provisioned already. Do not paste a Doppler token into this document, source files, command arguments, or example files.

**Verification boundary:** Endpoints and fields were cross-checked against the Doppler API reference (OpenAPI markdown), the official generated SDK sources (`doppler-sdk` 1.3.0 for Python, `@dopplerhq/node-sdk` 1.3.0 for Node), and the Doppler CLI source (v3.77.1) cited in section 14. Doppler publishes no official Go, Rust, PHP, .NET, Java, Swift, C++, or C SDK, so every program here calls the REST API directly. All ten REST programs except Swift were compiled or type-checked (`go vet`, `cargo build`, `tsc --strict`, `dotnet build` with warnings as errors, `javac -Xlint:all -Werror`, `php -l`, `gcc`/`g++ -Wall -Wextra -Werror`) and then **run end-to-end** against a local mock of the four endpoints; the two official SDK samples (Python, Node) were run against the same mock to confirm the request shapes it accepts. Swift was not compiled (no toolchain). No call was made to the real Doppler API. Section 12 provides an optional live test.

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
| Go | none ("planned" per Doppler docs) | REST via `net/http` | `go vet`, mock run |
| Rust | none | REST via `reqwest` (rustls) | `cargo build`, mock run |
| PHP | none | REST via ext-curl | `php -l`, mock run |
| C# | none | REST via `HttpClient` + `System.Text.Json` | `dotnet build -warnaserror`, mock run |
| Java | none | REST via `java.net.http` + Jackson | `javac -Werror`, mock run |
| Swift | none | REST via `URLSession` | not compiled |
| Python | `doppler-sdk` (generated) | REST via `requests` (SDK alternative shown) | mock run (both) |
| TypeScript | `@dopplerhq/node-sdk` (generated) | REST via `fetch` (SDK alternative shown) | `tsc --strict`, mock run (both) |
| C++ | none | REST via libcurl + nlohmann/json | `-Werror`, mock run |
| C | none | REST via libcurl + cJSON | `-Werror`, mock run |

Why REST first: the API surface for secrets is four calls, the generated SDKs add no authentication or caching logic, and in the versions reviewed they send requests **without a timeout**, retry `500/503/504` (including writes), and put the raw response body into exception messages. A small, reviewed REST adapter is easier to harden. Use the SDKs if you prefer generated models; the caveats are repeated in 9.7 and 9.8.

Every program follows the same contract:

- Environment: `DOPPLER_PROJECT`, `DOPPLER_CONFIG`, `SECRET_NAME` (for example `CRUD_CHECK`), `DOPPLER_TOKEN_FILE` (path to a `0600` file holding the token), and optional `DOPPLER_API_HOST` (default `https://api.doppler.com`; plain HTTP is accepted only for a loopback test server).
- It **creates** the secret (refusing if the name already exists), **reads** the raw value and compares it in constant time, **updates** it with an `originalValue` guard, reads and compares again, then **deletes** it.
- It prints secret names only. Error messages carry the operation, HTTP status, and Doppler's `messages` array, which does not contain values.

For CLI snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
doppler --version
export HISTIGNORE='*doppler secrets set*'   # zsh: HISTORY_IGNORE="(doppler secrets set*)"
PROJECT='REPLACE_WITH_PROJECT'
CONFIG='dev'
```

## 2. Authenticate

### Token types

| Token | Scope | Use for |
| --- | --- | --- |
| **Service account identity** (OIDC) | Granular, from the service account's roles; short-lived | CI and workloads that have an OIDC issuer (GitHub Actions, GitLab, CircleCI, Kubernetes) |
| **Service account** token | Workplace role + per-project roles and environments | Services and automation without OIDC; Team/Enterprise plans |
| **Service token** (`dp.st.<env>.…`) | One config; read-only by default, optionally read/write; optional expiry | A single app reading a single config |
| Personal / CLI token | Everything the human user can do | Humans on their own machines only — **never** in live environments |
| SCIM / Audit | Users and groups | Identity provider sync and audit tooling, not secrets |

Doppler's docs are explicit: do not use CLI or personal tokens in live environments, because they carry the creating user's full permissions. [S01] [S05] [S06]

**OIDC exchange** (preferred where possible): `POST /v3/auth/oidc` with `{"identity": "<service-account-identity-id>", "token": "<OIDC JWT>"}` returns `{"token", "expires_at"}`; the token is short-lived and should not be persisted. CLI equivalent: `doppler oidc login --scope=. --identity=<id> --token="$OIDC_JWT"`. [S07]

**Service tokens** from the CLI (the token is shown once; write it straight to a protected file):

```bash
doppler configs tokens create app-reader -p "$PROJECT" -c "$CONFIG" \
  --access read --max-age 720h --plain > /secure/path/doppler-token
doppler configs tokens revoke -p "$PROJECT" -c "$CONFIG" --slug '<token-slug>'
```

`--access` accepts `read` (default) or `read/write`; `--max-age` makes the token expire and be deleted automatically. [S05] [S15]

### Confirm authentication without displaying the token

```bash
# The token is read from a file into the CLI's environment for this one command; it is never echoed.
DOPPLER_TOKEN="$(cat /secure/path/doppler-token)" doppler me --json | jq '{type, name, workplace: .workplace.name}'   # token_preview is a prefix, still don't log it
```

`GET /v3/me` is the API equivalent. Never pass `--token` on a command line on shared hosts (it appears in the process table).

### Required permissions

- **Service account:** grant no workplace role unless needed; add it to each project under **Members** with a project role and only the environments it needs. Use a read-only role for runtime readers and a separate account for writers. [S06]
- **Service token:** choose `read` unless the workload must write; one token per app per config.
- Restricted-visibility values are returned only to **non-user** tokens (service tokens, service accounts); anyone who can mint such tokens can therefore reveal restricted values. Limit who can create tokens. [S08]

## 3. Data model and addressing

- **Workplace → project → environment → config → secret name.** Root configs are named after the environment (`dev`, `stg`, `prd`); **branch configs** (`dev_feature`) inherit the root's secrets and may override them.
- **Name:** uppercase letters, digits, and underscores by convention (environment-variable style). **Value:** a string; multi-line values are allowed. An optional **value type** (`string`, `json`, `boolean`, `integer`, `url`, `uuidv4`, …) adds validation.
- **raw vs computed:** values may reference other secrets (`${OTHER}`, `${config.OTHER}`, `${project.config.OTHER}`). `raw` is what is stored; `computed` is the value after references are resolved. Programs that verify writes compare `raw`. [S02]
- **Visibility:** `unmasked`, `masked` (default for most secrets), or `restricted` (never shown in the dashboard again; returned only to non-user tokens; can be relaxed only together with a value change). [S08]
- **History:** every change is recorded in the config's **logs**; a log entry can be **rolled back** (`POST /v3/configs/config/logs/log/rollback`), which is also how a deleted secret is recovered. Workplace activity logs record who changed what. [S16]
- **Writes are upserts:** `POST /v3/configs/config/secrets` sets values whether or not the name exists (the simple `secrets` map form) — create-only semantics must be enforced by the client (section 5).

Inventory without values:

```bash
doppler secrets --only-names -p "$PROJECT" -c "$CONFIG"
```

## 4. Safe secret handling

- **Command lines:** `doppler secrets set KEY=value` and `doppler secrets set KEY value` put the value in shell history and the process table. Pipe from a file or stdin instead: `doppler secrets set KEY < file`. [S09]
- **CLI output prints values:** `secrets set` prints the changed secrets, and `secrets delete` prints **all remaining secrets in the config**, unless `--silent` is given. Always add `--silent` to `set` and `delete` in scripts and CI. `doppler secrets` (list) and `secrets get` print values; use `--only-names` for inventory. [S15]
- **Download and fallback files:** `doppler secrets download` writes an encrypted fallback file unless `--no-file`; `doppler run` keeps an encrypted fallback file by default (useful for outages, but a copy of every value on disk that survives token revocation). Choose deliberately: `--no-fallback` for ephemeral jobs, `--fallback-readonly` for read-only file systems. [S10] [S15]
- **Error payloads:** the generated SDKs place the response body into exceptions (`message` in Python, `detail` in Node). Doppler's error bodies (`{"messages": [...], "success": false}`) do not echo values, but log the status and class, not whole SDK exceptions or request objects.
- **References:** reading `computed` can pull values from other configs the token can see; compare `raw` when you mean "exactly this value."
- **Restricted values** appear as `[RESTRICTED]` / `null` to user-tied tokens; do not mistake that for an empty secret.
- **Memory:** wipe buffers where possible (`zeroize`, `OPENSSL_cleanse`); minimize copies of managed strings.

## 5. Create secrets

`POST /v3/configs/config/secrets` with `{"project", "config", "change_requests": [{"name", "originalName": null, "value", "visibility"?, "valueType"?}]}`. Either `secrets` (a name→value map) or `change_requests` is required, never both. `originalName: null` marks a new secret; the API documents no create-only guarantee, so the programs **probe first** (`GET …/secret` must return 404) and then create. A concurrent creator can still win the race between probe and write; if that matters, serialize provisioning through one writer. [S03]

```bash
# From a protected file; stdin input is stored without its trailing newline.
doppler secrets get PARTNER_API_TOKEN -p "$PROJECT" -c "$CONFIG" --plain > /dev/null 2>&1 &&
  { printf 'PARTNER_API_TOKEN already exists\n' >&2; exit 1; }
doppler secrets set PARTNER_API_TOKEN -p "$PROJECT" -c "$CONFIG" --silent < /secure/path/to/api-token.txt
```

`--visibility restricted` and `--type <valueType>` set the corresponding attributes. `doppler secrets upload file.env|file.json` sets many at once (and keeps a file of values on disk — delete it afterwards). [S09]

## 6. Read secrets

`GET /v3/configs/config/secret?project=…&config=…&name=…` returns `{"name", "value": {"raw", "computed", "note", "rawVisibility", "computedVisibility", "rawValueType", "computedValueType"}}`. Read many with `GET /v3/configs/config/secrets?project=…&config=…` (optionally `secrets=A,B`) or the download endpoint (`/v3/configs/config/secrets/download?format=json`). [S02]

```bash
# One raw value to a new private file
doppler secrets get PARTNER_API_TOKEN -p "$PROJECT" -c "$CONFIG" --plain --raw > ./partner-api-token.secret

# Metadata only (names, visibility, types) — the JSON contains values, so filter before display
doppler secrets get PARTNER_API_TOKEN -p "$PROJECT" -c "$CONFIG" --json --raw |
  jq 'map_values({rawVisibility, computedVisibility, rawValueType, note})'
```

## 7. Update secrets

`POST /v3/configs/config/secrets` with a change request whose `originalName` equals `name`. Add `originalValue` (and/or `originalVisibility`, `originalValueType`) to make the write conditional: Doppler processes it **only if the current value matches** — Doppler's equivalent of compare-and-swap. `value: null` leaves the value unchanged (for visibility-only edits); a different `name` renames the secret. [S03]

```json
{"project": "backend", "config": "prd",
 "change_requests": [{"name": "PARTNER_API_TOKEN", "originalName": "PARTNER_API_TOKEN",
                      "value": "<new>", "originalValue": "<expected current>"}]}
```

```bash
doppler secrets set PARTNER_API_TOKEN -p "$PROJECT" -c "$CONFIG" --silent < /secure/path/new-token.txt

doppler secrets get PARTNER_API_TOKEN -p "$PROJECT" -c "$CONFIG" --plain --raw |
  cmp -s - <(tr -d '\n' < /secure/path/new-token.txt) && printf 'Secret replacement verified.\n'
```

The CLI's `set` has no `originalValue` option; use the API when concurrent writers are possible. Storing a new value does not rotate the credential at its source; Doppler's rotation integrations (for supported databases/providers) or your own rotation job must change the source first.

## 8. Delete and recover

`DELETE /v3/configs/config/secret?project=…&config=…&name=…` returns **204**. Alternatively, a change request with `shouldDelete: true` deletes as part of a batch. The deletion is recorded in the config logs and can be undone by rolling back that log entry; there is no separate "deleted secrets" bin. Branch configs that inherited the secret lose it too. [S04] [S16]

```bash
doppler secrets delete PARTNER_API_TOKEN -p "$PROJECT" -c "$CONFIG" --yes --silent
```

Without `--silent`, the CLI prints every remaining secret in the config after the delete. Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Expected output for every program:

```text
created: CRUD_CHECK
updated: CRUD_CHECK
deleted: CRUD_CHECK
```

### 9.1 Go

Standard library only (`net/http`, `encoding/json`, `crypto/subtle`). Doppler has no Go SDK; its docs point Go users to the REST API.

```go
// Doppler secrets CRUD over the v3 REST API with net/http (standard library only).
// Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

type Store struct {
	http            *http.Client
	base, token     string
	project, config string
}

type apiError struct {
	Op       string
	Status   int
	Messages []string `json:"messages"` // Doppler error bodies never echo values
}

func (e *apiError) Error() string { return fmt.Sprintf("%s: HTTP %d %v", e.Op, e.Status, e.Messages) }

func (s *Store) do(ctx context.Context, method, path string, q url.Values, body any, out any, op string) error {
	var rdr io.Reader
	if body != nil {
		buf, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rdr = bytes.NewReader(buf)
	}
	u := s.base + path
	if q != nil {
		u += "?" + q.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, u, rdr)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+s.token)
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := s.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		e := &apiError{Op: op, Status: resp.StatusCode}
		_ = json.NewDecoder(io.LimitReader(resp.Body, 1<<16)).Decode(e)
		return e
	}
	if out != nil {
		return json.NewDecoder(resp.Body).Decode(out)
	}
	return nil
}

func (s *Store) scope(name string) url.Values {
	return url.Values{"project": {s.project}, "config": {s.config}, "name": {name}}
}

func (s *Store) change(ctx context.Context, op string, cr map[string]any) error {
	body := map[string]any{"project": s.project, "config": s.config, "change_requests": []any{cr}}
	return s.do(ctx, http.MethodPost, "/v3/configs/config/secrets", nil, body, nil, op)
}

// Create proves the name is unused (Doppler writes are upserts), then adds it as a new secret.
func (s *Store) Create(ctx context.Context, name, value string) error {
	err := s.do(ctx, http.MethodGet, "/v3/configs/config/secret", s.scope(name), nil, nil, "probe")
	var ae *apiError
	switch {
	case err == nil:
		return fmt.Errorf("secret %s already exists (create is not an upsert)", name)
	case !errors.As(err, &ae) || ae.Status != http.StatusNotFound:
		return err
	}
	return s.change(ctx, "create", map[string]any{"name": name, "originalName": nil, "value": value})
}

// Read returns the stored ("raw") value; "computed" would resolve ${REFERENCES}.
func (s *Store) Read(ctx context.Context, name string) (string, error) {
	var out struct {
		Value struct {
			Raw string `json:"raw"`
		} `json:"value"`
	}
	if err := s.do(ctx, http.MethodGet, "/v3/configs/config/secret", s.scope(name), nil, &out, "read"); err != nil {
		return "", err
	}
	return out.Value.Raw, nil
}

// Update replaces the value; originalValue guards against concurrent modification.
func (s *Store) Update(ctx context.Context, name, value, expected string) error {
	return s.change(ctx, "update", map[string]any{
		"name": name, "originalName": name, "value": value, "originalValue": expected,
	})
}

func (s *Store) Delete(ctx context.Context, name string) error {
	return s.do(ctx, http.MethodDelete, "/v3/configs/config/secret", s.scope(name), nil, nil, "delete")
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
	project, config, name := os.Getenv("DOPPLER_PROJECT"), os.Getenv("DOPPLER_CONFIG"), os.Getenv("SECRET_NAME")
	if project == "" || config == "" || name == "" {
		log.Fatal("set DOPPLER_PROJECT, DOPPLER_CONFIG, SECRET_NAME, DOPPLER_TOKEN_FILE")
	}
	raw, err := os.ReadFile(os.Getenv("DOPPLER_TOKEN_FILE"))
	if err != nil {
		log.Fatal("read token file: ", err)
	}
	base := os.Getenv("DOPPLER_API_HOST")
	if base == "" {
		base = "https://api.doppler.com"
	}
	if !strings.HasPrefix(base, "https://") && !strings.HasPrefix(base, "http://127.0.0.1:") {
		log.Fatal("DOPPLER_API_HOST must use https")
	}
	store := &Store{
		http:  &http.Client{Timeout: 30 * time.Second},
		base:  strings.TrimRight(base, "/"),
		token: strings.TrimSpace(string(raw)), project: project, config: config,
	}
	ctx := context.Background()

	v1 := randomValue()
	if err := store.Create(ctx, name, v1); err != nil {
		log.Fatal(err)
	}
	fmt.Println("created:", name)
	if got, err := store.Read(ctx, name); err != nil || !equal(got, v1) {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	if err := store.Update(ctx, name, v2, v1); err != nil {
		log.Fatal(err)
	}
	if got, err := store.Read(ctx, name); err != nil || !equal(got, v2) {
		log.Fatal("read-back after update failed: ", err)
	}
	fmt.Println("updated:", name)

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
name = "doppler-secrets-crud"
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
//! Doppler secrets CRUD over the v3 REST API with reqwest (Doppler ships no Rust SDK).
//! Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use reqwest::{Client, Method, StatusCode};
use serde_json::{json, Value};
use std::{env, error::Error, time::Duration};
use subtle::ConstantTimeEq;
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

#[derive(Debug)]
struct DopplerError {
    op: &'static str,
    status: StatusCode,
    messages: Value, // Doppler error bodies never echo values
}
impl std::fmt::Display for DopplerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: HTTP {} {}", self.op, self.status.as_u16(), self.messages)
    }
}
impl Error for DopplerError {}

struct DopplerStore {
    http: Client,
    base: String,
    token: Zeroizing<String>,
    project: String,
    config: String,
}

impl DopplerStore {
    fn new(token: Zeroizing<String>, project: String, config: String, api_host: &str) -> Res<Self> {
        // Plain HTTP only to a loopback test server; TLS everywhere else.
        let loopback = api_host.starts_with("http://127.0.0.1:") || api_host.starts_with("http://localhost:");
        if !api_host.starts_with("https://") && !loopback {
            return Err("DOPPLER_API_HOST must use https".into());
        }
        let http = Client::builder().timeout(Duration::from_secs(30)).https_only(!loopback).build()?;
        Ok(Self { http, base: api_host.trim_end_matches('/').to_string(), token, project, config })
    }

    async fn call(&self, op: &'static str, method: Method, path: &str, name: Option<&str>, body: Option<Value>) -> Res<Value> {
        let mut req = self.http.request(method, format!("{}{}", self.base, path))
            .bearer_auth(self.token.as_str())
            .header("Accept", "application/json");
        if let Some(n) = name {
            req = req.query(&[("project", self.project.as_str()), ("config", self.config.as_str()), ("name", n)]);
        }
        if let Some(b) = body {
            req = req.json(&b);
        }
        let resp = req.send().await?;
        let status = resp.status();
        let text = Zeroizing::new(resp.text().await?);
        let json: Value = if text.is_empty() { Value::Null } else { serde_json::from_str(&text)? };
        if !status.is_success() {
            return Err(Box::new(DopplerError { op, status, messages: json["messages"].clone() }));
        }
        Ok(json)
    }

    async fn change(&self, op: &'static str, change: Value) -> Res<()> {
        let body = json!({ "project": self.project, "config": self.config, "change_requests": [change] });
        self.call(op, Method::POST, "/v3/configs/config/secrets", None, Some(body)).await.map(|_| ())
    }

    /// Doppler writes are upserts; prove the name is unused, then add it as a new secret.
    async fn create(&self, name: &str, value: &str) -> Res<()> {
        match self.call("probe", Method::GET, "/v3/configs/config/secret", Some(name), None).await {
            Ok(_) => Err(format!("secret {name} already exists (create is not an upsert)").into()),
            Err(e) => match e.downcast_ref::<DopplerError>() {
                Some(d) if d.status == StatusCode::NOT_FOUND => {
                    self.change("create", json!({ "name": name, "originalName": null, "value": value })).await
                }
                _ => Err(e),
            },
        }
    }

    /// Returns the stored ("raw") value; "computed" would resolve ${REFERENCES}.
    async fn read(&self, name: &str) -> Res<Zeroizing<String>> {
        let mut json = self.call("read", Method::GET, "/v3/configs/config/secret", Some(name), None).await?;
        let raw = json["value"]["raw"].take();
        let s = raw.as_str().ok_or("response has no value.raw")?;
        Ok(Zeroizing::new(s.to_string()))
    }

    /// originalValue guards against a concurrent modification.
    async fn update(&self, name: &str, value: &str, expected: &str) -> Res<()> {
        self.change("update", json!({ "name": name, "originalName": name, "value": value, "originalValue": expected })).await
    }

    async fn delete(&self, name: &str) -> Res<()> {
        self.call("delete", Method::DELETE, "/v3/configs/config/secret", Some(name), None).await.map(|_| ())
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
    let project = env::var("DOPPLER_PROJECT").map_err(|_| "set DOPPLER_PROJECT")?;
    let config = env::var("DOPPLER_CONFIG").map_err(|_| "set DOPPLER_CONFIG")?;
    let name = env::var("SECRET_NAME").map_err(|_| "set SECRET_NAME")?;
    let token_file = env::var("DOPPLER_TOKEN_FILE").map_err(|_| "set DOPPLER_TOKEN_FILE")?;
    let token = Zeroizing::new(std::fs::read_to_string(token_file)?.trim().to_string());
    let host = env::var("DOPPLER_API_HOST").unwrap_or_else(|_| "https://api.doppler.com".into());
    let store = DopplerStore::new(token, project, config, &host)?;

    let v1 = random_value()?;
    store.create(&name, &v1).await?;
    println!("created: {name}");
    if !same(&v1, &store.read(&name).await?) {
        return Err("read-back after create did not match".into());
    }

    let v2 = random_value()?;
    store.update(&name, &v2, &v1).await?;
    if !same(&v2, &store.read(&name).await?) {
        return Err("read-back after update did not match".into());
    }
    println!("updated: {name}");

    store.delete(&name).await?;
    println!("deleted: {name}");
    Ok(())
}
```

### 9.3 PHP

PHP 8.2+ with ext-curl. `#[\SensitiveParameter]` keeps the token and values out of stack traces.

```php
<?php
// Doppler secrets CRUD over the v3 REST API with ext-curl (Doppler ships no PHP SDK).
// Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
declare(strict_types=1);

final class DopplerException extends RuntimeException
{
    public function __construct(string $op, public readonly int $status, array $messages)
    {
        // Doppler error bodies never echo values
        parent::__construct(sprintf('%s: HTTP %d %s', $op, $status, json_encode($messages)));
    }
}

final class DopplerStore
{
    private string $base;

    public function __construct(
        #[\SensitiveParameter] private string $token,
        private string $project,
        private string $config,
        string $apiHost = 'https://api.doppler.com',
    ) {
        $loopback = (bool)preg_match('#^http://(127\.0\.0\.1|localhost):#', $apiHost);
        if (!str_starts_with($apiHost, 'https://') && !$loopback) {
            throw new InvalidArgumentException('DOPPLER_API_HOST must use https');
        }
        $this->base = rtrim($apiHost, '/');
    }

    private function call(string $op, string $method, string $path, ?string $name = null, ?array $body = null): array
    {
        $url = $this->base . $path;
        if ($name !== null) {
            $url .= '?' . http_build_query(['project' => $this->project, 'config' => $this->config, 'name' => $name]);
        }
        $headers = ['Authorization: Bearer ' . $this->token, 'Accept: application/json'];
        $ch = curl_init($url);
        $opts = [
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_PROTOCOLS => str_starts_with($url, 'https://') ? CURLPROTO_HTTPS : CURLPROTO_HTTP,
        ];
        if ($body !== null) {
            $opts[CURLOPT_POSTFIELDS] = json_encode($body, JSON_THROW_ON_ERROR);
            $headers[] = 'Content-Type: application/json';
        }
        $opts[CURLOPT_HTTPHEADER] = $headers;
        curl_setopt_array($ch, $opts);
        $raw = curl_exec($ch);
        if ($raw === false) {
            throw new RuntimeException("$op: transport error " . curl_errno($ch));
        }
        $status = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $json = $raw === '' ? [] : json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if ($status < 200 || $status > 299) {
            throw new DopplerException($op, $status, $json['messages'] ?? []);
        }
        return $json;
    }

    private function change(string $op, array $change): void
    {
        $this->call($op, 'POST', '/v3/configs/config/secrets', null, [
            'project' => $this->project,
            'config' => $this->config,
            'change_requests' => [$change],
        ]);
    }

    /** Doppler writes are upserts; prove the name is unused, then add it as a new secret. */
    public function create(string $name, #[\SensitiveParameter] string $value): void
    {
        try {
            $this->call('probe', 'GET', '/v3/configs/config/secret', $name);
        } catch (DopplerException $e) {
            if ($e->status !== 404) {
                throw $e;
            }
            $this->change('create', ['name' => $name, 'originalName' => null, 'value' => $value]);
            return;
        }
        throw new RuntimeException("secret $name already exists (create is not an upsert)");
    }

    /** Returns the stored ("raw") value; "computed" would resolve ${REFERENCES}. */
    public function read(string $name): string
    {
        return $this->call('read', 'GET', '/v3/configs/config/secret', $name)['value']['raw'];
    }

    /** originalValue guards against a concurrent modification. */
    public function update(string $name, #[\SensitiveParameter] string $value, #[\SensitiveParameter] ?string $expected = null): void
    {
        $change = ['name' => $name, 'originalName' => $name, 'value' => $value];
        if ($expected !== null) {
            $change['originalValue'] = $expected;
        }
        $this->change('update', $change);
    }

    public function delete(string $name): void
    {
        $this->call('delete', 'DELETE', '/v3/configs/config/secret', $name);
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

$project = env_or_fail('DOPPLER_PROJECT');
$config = env_or_fail('DOPPLER_CONFIG');
$name = env_or_fail('SECRET_NAME');
$token = trim((string)file_get_contents(env_or_fail('DOPPLER_TOKEN_FILE')));
$store = new DopplerStore($token, $project, $config, getenv('DOPPLER_API_HOST') ?: 'https://api.doppler.com');
unset($token);

try {
    $v1 = random_value();
    $store->create($name, $v1);
    echo "created: $name\n";
    if (!hash_equals($v1, $store->read($name))) {
        throw new RuntimeException('read-back after create did not match');
    }

    $v2 = random_value();
    $store->update($name, $v2, $v1);
    if (!hash_equals($v2, $store->read($name))) {
        throw new RuntimeException('read-back after update did not match');
    }
    echo "updated: $name\n";

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
// Doppler secrets CRUD over the v3 REST API with HttpClient + System.Text.Json (no packages).
// Doppler ships no .NET SDK. Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

public sealed class DopplerException(string op, HttpStatusCode status, string messages)
    : Exception($"{op}: HTTP {(int)status} {messages}")   // Doppler error bodies never echo values
{
    public HttpStatusCode Status { get; } = status;
}

public sealed class DopplerStore
{
    private readonly HttpClient _http;
    private readonly string _project, _config;

    public DopplerStore(string token, string project, string config, string apiHost = "https://api.doppler.com")
    {
        var loopback = Regex.IsMatch(apiHost, @"^http://(127\.0\.0\.1|localhost):");
        if (!apiHost.StartsWith("https://", StringComparison.Ordinal) && !loopback)
            throw new ArgumentException("DOPPLER_API_HOST must use https");
        _http = new HttpClient { BaseAddress = new Uri(apiHost.TrimEnd('/') + "/"), Timeout = TimeSpan.FromSeconds(30) };
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        (_project, _config) = (project, config);
    }

    private string SecretUri(string name) =>
        $"v3/configs/config/secret?project={Uri.EscapeDataString(_project)}&config={Uri.EscapeDataString(_config)}&name={Uri.EscapeDataString(name)}";

    private static async Task<JsonNode?> CheckAsync(string op, HttpResponseMessage resp, CancellationToken ct)
    {
        var body = await resp.Content.ReadAsStringAsync(ct);
        var json = body.Length == 0 ? null : JsonNode.Parse(body);
        if (!resp.IsSuccessStatusCode)
            throw new DopplerException(op, resp.StatusCode, json?["messages"]?.ToJsonString() ?? "[]");
        return json;
    }

    private async Task ChangeAsync(string op, object change, CancellationToken ct)
    {
        using var resp = await _http.PostAsJsonAsync("v3/configs/config/secrets",
            new { project = _project, config = _config, change_requests = new[] { change } }, ct);
        await CheckAsync(op, resp, ct);
    }

    /// <summary>Doppler writes are upserts; prove the name is unused, then add it as a new secret.</summary>
    public async Task CreateAsync(string name, string value, CancellationToken ct = default)
    {
        using (var probe = await _http.GetAsync(SecretUri(name), ct))
        {
            if (probe.IsSuccessStatusCode)
                throw new InvalidOperationException($"secret {name} already exists (create is not an upsert)");
            if (probe.StatusCode != HttpStatusCode.NotFound) await CheckAsync("probe", probe, ct);
        }
        await ChangeAsync("create", new Dictionary<string, string?> { ["name"] = name, ["originalName"] = null, ["value"] = value }, ct);
    }

    /// <summary>Returns the stored ("raw") value; "computed" would resolve ${REFERENCES}.</summary>
    public async Task<string> ReadAsync(string name, CancellationToken ct = default)
    {
        using var resp = await _http.GetAsync(SecretUri(name), ct);
        var json = await CheckAsync("read", resp, ct);
        return json!["value"]!["raw"]!.GetValue<string>();
    }

    /// <summary>originalValue guards against a concurrent modification.</summary>
    public Task UpdateAsync(string name, string value, string expected, CancellationToken ct = default) =>
        ChangeAsync("update", new { name, originalName = name, value, originalValue = expected }, ct);

    public async Task DeleteAsync(string name, CancellationToken ct = default)
    {
        using var resp = await _http.DeleteAsync(SecretUri(name), ct);
        await CheckAsync("delete", resp, ct);
    }
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
            var token = (await File.ReadAllTextAsync(Need("DOPPLER_TOKEN_FILE"))).Trim();
            var store = new DopplerStore(token, Need("DOPPLER_PROJECT"), Need("DOPPLER_CONFIG"),
                Environment.GetEnvironmentVariable("DOPPLER_API_HOST") ?? "https://api.doppler.com");

            var v1 = RandomValue();
            await store.CreateAsync(name, v1);
            Console.WriteLine($"created: {name}");
            if (!Same(v1, await store.ReadAsync(name))) throw new InvalidOperationException("read-back after create did not match");

            var v2 = RandomValue();
            await store.UpdateAsync(name, v2, v1);
            if (!Same(v2, await store.ReadAsync(name))) throw new InvalidOperationException("read-back after update did not match");
            Console.WriteLine($"updated: {name}");

            await store.DeleteAsync(name);
            Console.WriteLine($"deleted: {name}");
            return 0;
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"{e.GetType().Name}: {e.Message}");   // never the value
            return 1;
        }
    }
}
```

### 9.5 Java

Java 17+ with Jackson (`com.fasterxml.jackson.core:jackson-databind`). `Map.of` rejects `null`, so the create request uses a `HashMap` for `originalName: null`.

```java
// Doppler secrets CRUD over the v3 REST API with java.net.http + Jackson (Doppler ships no Java SDK).
// Maven: com.fasterxml.jackson.core:jackson-databind
// Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
package example;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
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
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class DopplerCrud {
    private static final ObjectMapper JSON = new ObjectMapper();

    /** Carries status and Doppler's messages; Doppler error bodies never echo values. */
    static final class DopplerException extends IOException {
        private static final long serialVersionUID = 1L;
        final int status;
        DopplerException(String op, int status, String messages) {
            super(op + ": HTTP " + status + " " + messages);
            this.status = status;
        }
    }

    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
    private final String base, token, project, config;

    DopplerCrud(String token, String project, String config, String apiHost) {
        boolean loopback = apiHost.matches("^http://(127\\.0\\.0\\.1|localhost):.*");
        if (!apiHost.startsWith("https://") && !loopback) throw new IllegalArgumentException("DOPPLER_API_HOST must use https");
        this.base = apiHost.replaceAll("/+$", "");
        this.token = token;
        this.project = project;
        this.config = config;
    }

    private JsonNode call(String op, String method, String path, String name, Object body)
            throws IOException, InterruptedException {
        String url = base + path;
        if (name != null) {
            url += "?project=" + enc(project) + "&config=" + enc(config) + "&name=" + enc(name);
        }
        HttpRequest.BodyPublisher pub = body == null
                ? HttpRequest.BodyPublishers.noBody()
                : HttpRequest.BodyPublishers.ofByteArray(JSON.writeValueAsBytes(body));
        HttpRequest.Builder req = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(30))
                .header("Authorization", "Bearer " + token)
                .header("Accept", "application/json")
                .method(method, pub);
        if (body != null) req.header("Content-Type", "application/json");
        HttpResponse<byte[]> resp = http.send(req.build(), HttpResponse.BodyHandlers.ofByteArray());
        JsonNode json = resp.body().length == 0 ? JSON.createObjectNode() : JSON.readTree(resp.body());
        if (resp.statusCode() / 100 != 2) {
            throw new DopplerException(op, resp.statusCode(), String.valueOf(json.path("messages")));
        }
        return json;
    }

    private static String enc(String s) { return URLEncoder.encode(s, StandardCharsets.UTF_8); }

    private void change(String op, Map<String, Object> change) throws IOException, InterruptedException {
        call(op, "POST", "/v3/configs/config/secrets", null,
                Map.of("project", project, "config", config, "change_requests", List.of(change)));
    }

    /** Doppler writes are upserts; prove the name is unused, then add it as a new secret. */
    void create(String name, String value) throws IOException, InterruptedException {
        try {
            call("probe", "GET", "/v3/configs/config/secret", name, null);
        } catch (DopplerException e) {
            if (e.status != 404) throw e;
            Map<String, Object> cr = new HashMap<>();   // Map.of rejects the null originalName
            cr.put("name", name);
            cr.put("originalName", null);
            cr.put("value", value);
            change("create", cr);
            return;
        }
        throw new IllegalStateException("secret " + name + " already exists (create is not an upsert)");
    }

    /** Returns the stored ("raw") value; "computed" would resolve ${REFERENCES}. */
    String read(String name) throws IOException, InterruptedException {
        return call("read", "GET", "/v3/configs/config/secret", name, null).path("value").path("raw").asText();
    }

    /** originalValue guards against a concurrent modification. */
    void update(String name, String value, String expected) throws IOException, InterruptedException {
        change("update", Map.of("name", name, "originalName", name, "value", value, "originalValue", expected));
    }

    void delete(String name) throws IOException, InterruptedException {
        call("delete", "DELETE", "/v3/configs/config/secret", name, null);
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
            String token = Files.readString(Path.of(need("DOPPLER_TOKEN_FILE"))).strip();
            String host = System.getenv().getOrDefault("DOPPLER_API_HOST", "https://api.doppler.com");
            DopplerCrud store = new DopplerCrud(token, need("DOPPLER_PROJECT"), need("DOPPLER_CONFIG"), host);

            String v1 = randomValue();
            store.create(name, v1);
            System.out.println("created: " + name);
            if (!same(v1, store.read(name))) throw new IllegalStateException("read-back after create did not match");

            String v2 = randomValue();
            store.update(name, v2, v1);
            if (!same(v2, store.read(name))) throw new IllegalStateException("read-back after update did not match");
            System.out.println("updated: " + name);

            store.delete(name);
            System.out.println("deleted: " + name);
        } catch (Exception e) {
            System.err.println(e.getClass().getSimpleName() + ": " + e.getMessage());   // never the value
            System.exit(1);
        }
    }
}
```

### 9.6 Swift

Foundation only (`URLSession` with an ephemeral configuration); runs on macOS and Linux. Server-side only: never embed a Doppler token in an app bundle.

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
// Doppler secrets CRUD in Swift over the v3 REST API (Foundation only; Doppler ships no Swift SDK).
// Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
// Server-side use only: never ship a Doppler token inside an app bundle.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
#if canImport(Security)
import Security
#endif

enum DopplerError: Error, CustomStringConvertible {
    case http(op: String, status: Int, messages: [String])   // Doppler error bodies never echo values
    case config(String)
    var description: String {
        switch self {
        case let .http(op, status, messages): return "\(op): HTTP \(status) \(messages)"
        case let .config(m): return m
        }
    }
}

final class DopplerStore {
    private let base: String, token: String, project: String, config: String
    private let session = URLSession(configuration: .ephemeral)

    init(token: String, project: String, config: String, apiHost: String = "https://api.doppler.com") throws {
        let loopback = apiHost.hasPrefix("http://127.0.0.1:") || apiHost.hasPrefix("http://localhost:")
        guard apiHost.hasPrefix("https://") || loopback else { throw DopplerError.config("DOPPLER_API_HOST must use https") }
        var b = apiHost
        while b.hasSuffix("/") { b.removeLast() }
        (base, self.token, self.project, self.config) = (b, token, project, config)
    }

    @discardableResult
    private func call(_ op: String, _ method: String, _ path: String, name: String? = nil,
                      body: [String: Any]? = nil) async throws -> [String: Any] {
        var comps = URLComponents(string: base + path)!
        if let name {
            comps.queryItems = [URLQueryItem(name: "project", value: project),
                                URLQueryItem(name: "config", value: config),
                                URLQueryItem(name: "name", value: name)]
        }
        var req = URLRequest(url: comps.url!)
        req.httpMethod = method
        req.timeoutInterval = 30
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        guard (200...299).contains(status) else {
            throw DopplerError.http(op: op, status: status, messages: json["messages"] as? [String] ?? [])
        }
        return json
    }

    private func change(_ op: String, _ cr: [String: Any]) async throws {
        try await call(op, "POST", "/v3/configs/config/secrets",
                       body: ["project": project, "config": config, "change_requests": [cr]])
    }

    /// Doppler writes are upserts; prove the name is unused, then add it as a new secret.
    func create(_ name: String, _ value: String) async throws {
        do {
            try await call("probe", "GET", "/v3/configs/config/secret", name: name)
        } catch DopplerError.http(_, 404, _) {
            try await change("create", ["name": name, "originalName": NSNull(), "value": value])
            return
        }
        throw DopplerError.config("secret \(name) already exists (create is not an upsert)")
    }

    /// Returns the stored ("raw") value; "computed" would resolve ${REFERENCES}.
    func read(_ name: String) async throws -> String {
        let json = try await call("read", "GET", "/v3/configs/config/secret", name: name)
        guard let raw = (json["value"] as? [String: Any])?["raw"] as? String else {
            throw DopplerError.config("response has no value.raw")
        }
        return raw
    }

    /// originalValue guards against a concurrent modification.
    func update(_ name: String, _ value: String, expected: String) async throws {
        try await change("update", ["name": name, "originalName": name, "value": value, "originalValue": expected])
    }

    func delete(_ name: String) async throws {
        try await call("delete", "DELETE", "/v3/configs/config/secret", name: name)
    }
}

func randomValue() throws -> String {
    var bytes = [UInt8](repeating: 0, count: 32)
    #if canImport(Security)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
        throw DopplerError.config("csprng failure")
    }
    #else
    var rng = SystemRandomNumberGenerator()   // getrandom(2)/arc4random on Linux: cryptographically secure
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
    guard let v = ProcessInfo.processInfo.environment[k], !v.isEmpty else { throw DopplerError.config("set \(k)") }
    return v
}

do {
    let name = try need("SECRET_NAME")
    let token = try String(contentsOfFile: try need("DOPPLER_TOKEN_FILE"), encoding: .utf8)
        .trimmingCharacters(in: .whitespacesAndNewlines)
    let store = try DopplerStore(token: token, project: try need("DOPPLER_PROJECT"), config: try need("DOPPLER_CONFIG"),
                                 apiHost: ProcessInfo.processInfo.environment["DOPPLER_API_HOST"] ?? "https://api.doppler.com")

    let v1 = try randomValue()
    try await store.create(name, v1)
    print("created: \(name)")
    guard same(v1, try await store.read(name)) else { throw DopplerError.config("read-back after create did not match") }

    let v2 = try randomValue()
    try await store.update(name, v2, expected: v1)
    guard same(v2, try await store.read(name)) else { throw DopplerError.config("read-back after update did not match") }
    print("updated: \(name)")

    try await store.delete(name)
    print("deleted: \(name)")
} catch {
    FileHandle.standardError.write("\(error)\n".data(using: .utf8)!)   // status codes and names, never values
    exit(1)
}
```

### 9.7 Python

`pip install requests`. The session uses an `AuthBase` object so that `requests` never substitutes `~/.netrc` credentials for the bearer token.

```python
"""Doppler secrets CRUD over the v3 REST API with requests.

pip install requests
Auth: a Doppler API token (service account token, read/write service token, or a short-lived
OIDC-exchanged token) read from the file named by DOPPLER_TOKEN_FILE.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys

import requests


class DopplerError(RuntimeError):
    def __init__(self, op: str, resp: requests.Response) -> None:
        try:
            messages = resp.json().get("messages", [])  # Doppler error bodies never echo values
        except ValueError:
            messages = []
        super().__init__(f"{op}: HTTP {resp.status_code} {messages}")
        self.status = resp.status_code


class _Bearer(requests.auth.AuthBase):
    """Session-level auth object: requests then never substitutes ~/.netrc credentials."""

    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        r.headers["Authorization"] = f"Bearer {self._token}"
        return r


class DopplerStore:
    def __init__(self, token: str, project: str, config: str, api_host: str = "https://api.doppler.com") -> None:
        if not api_host.startswith("https://") and not api_host.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("DOPPLER_API_HOST must use https")
        self.base, self.project, self.config = api_host.rstrip("/"), project, config
        self.http = requests.Session()
        self.http.auth = _Bearer(token)
        self.http.headers["Accept"] = "application/json"

    def _get(self, name: str) -> requests.Response:
        return self.http.get(f"{self.base}/v3/configs/config/secret", timeout=30,
                             params={"project": self.project, "config": self.config, "name": name})

    def _change(self, op: str, change: dict) -> None:
        resp = self.http.post(f"{self.base}/v3/configs/config/secrets", timeout=30,
                              json={"project": self.project, "config": self.config, "change_requests": [change]})
        if not resp.ok:
            raise DopplerError(op, resp)

    def create(self, name: str, value: str) -> None:
        """Doppler writes are upserts; prove the name is unused, then add it as a new secret."""
        probe = self._get(name)
        if probe.status_code == 200:
            raise RuntimeError(f"secret {name} already exists (create is not an upsert)")
        if probe.status_code != 404:
            raise DopplerError("probe", probe)
        self._change("create", {"name": name, "originalName": None, "value": value})

    def read(self, name: str) -> str:
        resp = self._get(name)
        if not resp.ok:
            raise DopplerError("read", resp)
        return resp.json()["value"]["raw"]  # raw = stored value; computed = references resolved

    def update(self, name: str, value: str, expected: str | None = None) -> None:
        change = {"name": name, "originalName": name, "value": value}
        if expected is not None:
            change["originalValue"] = expected  # optimistic-concurrency guard
        self._change("update", change)

    def delete(self, name: str) -> None:
        resp = self.http.delete(f"{self.base}/v3/configs/config/secret", timeout=30,
                                params={"project": self.project, "config": self.config, "name": name})
        if not resp.ok:
            raise DopplerError("delete", resp)


def main() -> int:
    env = os.environ
    try:
        project, config, name = env["DOPPLER_PROJECT"], env["DOPPLER_CONFIG"], env["SECRET_NAME"]
        with open(env["DOPPLER_TOKEN_FILE"], encoding="utf-8") as fh:
            token = fh.read().strip()
    except KeyError as missing:
        print(f"set {missing}", file=sys.stderr)
        return 2
    store = DopplerStore(token, project, config, env.get("DOPPLER_API_HOST", "https://api.doppler.com"))
    del token

    v1 = secrets.token_urlsafe(32)
    store.create(name, v1)
    print(f"created: {name}")
    if not hmac.compare_digest(v1, store.read(name)):
        raise RuntimeError("read-back after create did not match")

    v2 = secrets.token_urlsafe(32)
    store.update(name, v2, expected=v1)
    if not hmac.compare_digest(v2, store.read(name)):
        raise RuntimeError("read-back after update did not match")
    print(f"updated: {name}")

    store.delete(name)
    print(f"deleted: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

With the official generated SDK (`pip install doppler-sdk==1.3.0`): note that it sends requests without a timeout, retries `500/503/504` up to three times (including `POST`), serializes unset fields as `null`, and raises `http_exceptions` errors whose message is the response body.

```python
"""Doppler secrets CRUD with the official generated Python SDK (pip install doppler-sdk==1.3.0).

Caveats verified in 1.3.0: requests are sent without a timeout, 500/503/504 are retried
(including POST), and some exceptions carry the raw response body. Wrap calls accordingly.
"""
import hmac
import os
import secrets

from dopplersdk import DopplerSDK
from dopplersdk.models.SecretsUpdateRequest import SecretsUpdateRequest, SecretsUpdateRequestChangeRequests


def main() -> None:
    project, config, name = os.environ["DOPPLER_PROJECT"], os.environ["DOPPLER_CONFIG"], os.environ["SECRET_NAME"]
    with open(os.environ["DOPPLER_TOKEN_FILE"], encoding="utf-8") as fh:
        sdk = DopplerSDK(access_token=fh.read().strip())
    if host := os.environ.get("DOPPLER_API_HOST"):  # tests only; production uses the default https://api.doppler.com
        sdk.set_base_url(host)

    def write(change: SecretsUpdateRequestChangeRequests) -> None:
        sdk.secrets.update(SecretsUpdateRequest(project=project, config=config, change_requests=[change]))

    v1 = secrets.token_urlsafe(32)
    write(SecretsUpdateRequestChangeRequests(name=name, originalName=None, value=v1))
    print(f"created: {name}")
    if not hmac.compare_digest(v1, sdk.secrets.get(name, config, project).value["raw"]):
        raise RuntimeError("read-back after create did not match")

    v2 = secrets.token_urlsafe(32)
    write(SecretsUpdateRequestChangeRequests(name=name, originalName=name, value=v2, originalValue=v1))
    if not hmac.compare_digest(v2, sdk.secrets.get(name, config, project).value["raw"]):
        raise RuntimeError("read-back after update did not match")
    print(f"updated: {name}")

    sdk.secrets.delete(name, config, project)
    print(f"deleted: {name}")


if __name__ == "__main__":
    main()
```

### 9.8 TypeScript (Node.js)

Node 18+ built-in `fetch`, no dependencies.

```typescript
// Doppler secrets CRUD over the v3 REST API with Node's built-in fetch (Node 18+).
// Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
import { readFile } from "node:fs/promises";
import { randomBytes, timingSafeEqual } from "node:crypto";

class DopplerError extends Error {
  constructor(op: string, readonly status: number, messages: string[]) {
    super(`${op}: HTTP ${status} ${JSON.stringify(messages)}`); // Doppler error bodies never echo values
  }
}

export class DopplerStore {
  private readonly base: string;

  constructor(
    private readonly token: string,
    private readonly project: string,
    private readonly config: string,
    apiHost = "https://api.doppler.com",
  ) {
    if (!apiHost.startsWith("https://") && !/^http:\/\/(127\.0\.0\.1|localhost):/.test(apiHost)) {
      throw new Error("DOPPLER_API_HOST must use https");
    }
    this.base = apiHost.replace(/\/+$/, "");
  }

  private async call(op: string, method: string, path: string, query?: Record<string, string>, body?: unknown) {
    const url = new URL(this.base + path);
    for (const [k, v] of Object.entries(query ?? {})) url.searchParams.set(k, v);
    const resp = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    });
    const text = await resp.text();
    const json = text ? JSON.parse(text) : {};
    if (!resp.ok) throw new DopplerError(op, resp.status, json.messages ?? []);
    return json;
  }

  private scope(name: string) {
    return { project: this.project, config: this.config, name };
  }

  private change(op: string, cr: Record<string, unknown>) {
    return this.call(op, "POST", "/v3/configs/config/secrets", undefined, {
      project: this.project,
      config: this.config,
      change_requests: [cr],
    });
  }

  /** Doppler writes are upserts; prove the name is unused, then add it as a new secret. */
  async create(name: string, value: string): Promise<void> {
    try {
      await this.call("probe", "GET", "/v3/configs/config/secret", this.scope(name));
    } catch (err) {
      if (err instanceof DopplerError && err.status === 404) {
        await this.change("create", { name, originalName: null, value });
        return;
      }
      throw err;
    }
    throw new Error(`secret ${name} already exists (create is not an upsert)`);
  }

  /** Returns the stored ("raw") value; "computed" would resolve ${REFERENCES}. */
  async read(name: string): Promise<string> {
    const json = await this.call("read", "GET", "/v3/configs/config/secret", this.scope(name));
    return json.value.raw as string;
  }

  /** originalValue guards against a concurrent modification. */
  async update(name: string, value: string, expected?: string): Promise<void> {
    await this.change("update", {
      name,
      originalName: name,
      value,
      ...(expected === undefined ? {} : { originalValue: expected }),
    });
  }

  async delete(name: string): Promise<void> {
    await this.call("delete", "DELETE", "/v3/configs/config/secret", this.scope(name));
  }
}

const randomValue = (): string => randomBytes(32).toString("base64url");
const same = (a: string, b: string): boolean => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

async function main(): Promise<void> {
  const { DOPPLER_PROJECT: project, DOPPLER_CONFIG: config, SECRET_NAME: name, DOPPLER_TOKEN_FILE: tokenFile } = process.env;
  if (!project || !config || !name || !tokenFile) {
    throw new Error("set DOPPLER_PROJECT, DOPPLER_CONFIG, SECRET_NAME, DOPPLER_TOKEN_FILE");
  }
  const token = (await readFile(tokenFile, "utf8")).trim();
  const store = new DopplerStore(token, project, config, process.env.DOPPLER_API_HOST);

  const v1 = randomValue();
  await store.create(name, v1);
  console.log(`created: ${name}`);
  if (!same(v1, await store.read(name))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  await store.update(name, v2, v1);
  if (!same(v2, await store.read(name))) throw new Error("read-back after update did not match");
  console.log(`updated: ${name}`);

  await store.delete(name);
  console.log(`deleted: ${name}`);
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? `${err.name}: ${err.message}` : "unknown error");
  process.exitCode = 1;
});
```

With the official generated SDK (`npm i @dopplerhq/node-sdk@1.3.0`): the constructor takes `{ accessToken }`; `originalName` is typed `string` although the API expects `null` for new secrets; errors carry the body in `detail`; there is no request timeout.

```typescript
// Doppler secrets CRUD with the official generated Node SDK (npm i @dopplerhq/node-sdk@1.3.0).
// Caveats verified in 1.3.0: no request timeout, 500/503/504 are retried, and thrown errors
// carry the response body in `detail`. Log only the status/class, never the error object.
import { readFile } from "node:fs/promises";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { DopplerSDK } from "@dopplerhq/node-sdk";

const same = (a: string, b: string | undefined): boolean =>
  b !== undefined && a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b));

async function main(): Promise<void> {
  const { DOPPLER_PROJECT: project, DOPPLER_CONFIG: config, SECRET_NAME: name, DOPPLER_TOKEN_FILE: tokenFile } = process.env;
  if (!project || !config || !name || !tokenFile) throw new Error("set DOPPLER_PROJECT, DOPPLER_CONFIG, SECRET_NAME, DOPPLER_TOKEN_FILE");
  const sdk = new DopplerSDK({ accessToken: (await readFile(tokenFile, "utf8")).trim() });
  if (process.env.DOPPLER_API_HOST) sdk.setBaseUrl(process.env.DOPPLER_API_HOST); // tests only

  const v1 = randomBytes(32).toString("base64url");
  // The type declares originalName as string, but the API wants null for a new secret.
  await sdk.secrets.update({ project, config, change_requests: [{ name, originalName: null as unknown as string, value: v1 }] });
  console.log(`created: ${name}`);
  if (!same(v1, (await sdk.secrets.get(project, config, name)).value?.raw)) throw new Error("read-back after create did not match");

  const v2 = randomBytes(32).toString("base64url");
  await sdk.secrets.update({ project, config, change_requests: [{ name, originalName: name, value: v2, originalValue: v1 }] });
  if (!same(v2, (await sdk.secrets.get(project, config, name)).value?.raw)) throw new Error("read-back after update did not match");
  console.log(`updated: ${name}`);

  await sdk.secrets.delete(project, config, name);
  console.log(`deleted: ${name}`);
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? err.constructor.name : "unknown error"); // not err.message: it may hold the body
  process.exitCode = 1;
});
```

### 9.9 C++

C++17, libcurl, nlohmann/json, OpenSSL (for `RAND_bytes`, `CRYPTO_memcmp`, `OPENSSL_cleanse`).

```cpp
// Doppler secrets CRUD over the v3 REST API with libcurl + nlohmann/json (C++17).
// Doppler ships no C++ SDK.
//   g++ -std=c++17 -O2 main.cpp -o doppler_crud $(pkg-config --cflags --libs libcurl openssl)
// Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
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

struct DopplerError : std::runtime_error {
  long status;
  DopplerError(const std::string& op, long st, const std::string& messages)  // never contains values
      : std::runtime_error(op + ": HTTP " + std::to_string(st) + " " + messages), status(st) {}
};

class DopplerStore {
 public:
  DopplerStore(std::string token, std::string project, std::string config, std::string api_host)
      : token_(std::move(token)), project_(std::move(project)), config_(std::move(config)), base_(std::move(api_host)) {
    while (!base_.empty() && base_.back() == '/') base_.pop_back();
    bool loopback = std::regex_search(base_, std::regex("^http://(127\\.0\\.0\\.1|localhost):"));
    if (base_.rfind("https://", 0) != 0 && !loopback) throw std::runtime_error("DOPPLER_API_HOST must use https");
    https_only_ = !loopback;
  }
  ~DopplerStore() { wipe(token_); }
  DopplerStore(const DopplerStore&) = delete;
  DopplerStore& operator=(const DopplerStore&) = delete;

  // Doppler writes are upserts; prove the name is unused, then add it as a new secret.
  void create(const std::string& name, const std::string& value) {
    try {
      call("probe", "GET", secret_url(name), nullptr);
    } catch (const DopplerError& e) {
      if (e.status != 404) throw;
      change("create", {{"name", name}, {"originalName", nullptr}, {"value", value}});
      return;
    }
    throw std::runtime_error("secret " + name + " already exists (create is not an upsert)");
  }

  // Returns the stored ("raw") value; "computed" would resolve ${REFERENCES}.
  std::string read(const std::string& name) {
    json body = call("read", "GET", secret_url(name), nullptr);
    auto& raw = body["value"]["raw"];
    if (!raw.is_string()) throw std::runtime_error("response has no value.raw");
    std::string out = raw.get<std::string>();
    wipe(*raw.get_ptr<std::string*>());
    return out;
  }

  // originalValue guards against a concurrent modification.
  void update(const std::string& name, const std::string& value, const std::string& expected) {
    change("update", {{"name", name}, {"originalName", name}, {"value", value}, {"originalValue", expected}});
  }

  void remove(const std::string& name) { call("delete", "DELETE", secret_url(name), nullptr); }

 private:
  std::string token_, project_, config_, base_;
  bool https_only_ = true;

  static size_t on_body(char* p, size_t s, size_t n, void* u) {
    static_cast<std::string*>(u)->append(p, s * n);
    return s * n;
  }

  std::string esc(const std::string& s) const {
    char* e = curl_easy_escape(nullptr, s.c_str(), static_cast<int>(s.size()));
    std::string out(e ? e : "");
    curl_free(e);
    return out;
  }

  std::string secret_url(const std::string& name) const {
    return base_ + "/v3/configs/config/secret?project=" + esc(project_) + "&config=" + esc(config_) + "&name=" + esc(name);
  }

  void change(const char* op, json cr) {
    json body = {{"project", project_}, {"config", config_}, {"change_requests", json::array({std::move(cr)})}};
    call(op, "POST", base_ + "/v3/configs/config/secrets", &body);
  }

  json call(const char* op, const char* method, const std::string& url, const json* body) {
    std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> c(curl_easy_init(), curl_easy_cleanup);
    std::string auth = "Authorization: Bearer " + token_, payload, resp;
    curl_slist* h = curl_slist_append(nullptr, auth.c_str());
    h = curl_slist_append(h, "Accept: application/json");
    if (body) {
      payload = body->dump();
      h = curl_slist_append(h, "Content-Type: application/json");
      curl_easy_setopt(c.get(), CURLOPT_POSTFIELDS, payload.c_str());
    }
    curl_easy_setopt(c.get(), CURLOPT_URL, url.c_str());
    curl_easy_setopt(c.get(), CURLOPT_CUSTOMREQUEST, method);
    curl_easy_setopt(c.get(), CURLOPT_HTTPHEADER, h);
    curl_easy_setopt(c.get(), CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(c.get(), CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c.get(), CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(c.get(), CURLOPT_PROTOCOLS_STR, https_only_ ? "https" : "http");
    CURLcode rc = curl_easy_perform(c.get());
    long status = 0;
    curl_easy_getinfo(c.get(), CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(h);
    wipe(auth);
    wipe(payload);
    if (rc != CURLE_OK) throw std::runtime_error(std::string(op) + ": " + curl_easy_strerror(rc));
    json out = resp.empty() ? json::object() : json::parse(resp, nullptr, false);
    wipe(resp);
    if (status < 200 || status > 299) {
      std::string msgs = out.is_object() && out.contains("messages") ? out["messages"].dump() : "[]";
      throw DopplerError(op, status, msgs);
    }
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
    std::ifstream f(need("DOPPLER_TOKEN_FILE"));
    std::stringstream ss;
    ss << f.rdbuf();
    std::string token = ss.str();
    while (!token.empty() && (token.back() == '\n' || token.back() == '\r' || token.back() == ' ')) token.pop_back();
    const char* host = std::getenv("DOPPLER_API_HOST");
    DopplerStore store(token, need("DOPPLER_PROJECT"), need("DOPPLER_CONFIG"), host ? host : "https://api.doppler.com");
    wipe(token);

    std::string v1 = random_value();
    store.create(name, v1);
    std::cout << "created: " << name << "\n";
    std::string got = store.read(name);
    if (!same(v1, got)) throw std::runtime_error("read-back after create did not match");
    wipe(got);

    std::string v2 = random_value();
    store.update(name, v2, v1);
    got = store.read(name);
    if (!same(v2, got)) throw std::runtime_error("read-back after update did not match");
    std::cout << "updated: " << name << "\n";
    wipe(got); wipe(v1); wipe(v2);

    store.remove(name);
    std::cout << "deleted: " << name << "\n";
    rc = 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << "\n";  // messages carry status codes and names, never values
  }
  curl_global_cleanup();
  return rc;
}
```

### 9.10 C

C11, libcurl, cJSON, OpenSSL. HTTPS-only except for loopback; wipes the token, request bodies, and value buffers.

```c
/*
 * Doppler secrets CRUD in C over the v3 REST API: libcurl + cJSON + OpenSSL (Doppler ships no C SDK).
 *
 *   cc -std=c11 -Wall -Wextra -O2 doppler_crud.c -o doppler_crud \
 *      $(pkg-config --cflags --libs libcurl libcjson openssl)
 *
 * Auth: a Doppler API token read from the file named by DOPPLER_TOKEN_FILE.
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

static char g_token[512];
static char g_base[256];
static const char *g_project, *g_config;

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

/* GET/DELETE /v3/configs/config/secret?project&config&name (name != NULL), or POST .../secrets with body.
 * Returns HTTP status (0 on transport error); on non-2xx prints Doppler's "messages" (never values). */
static long doppler_call(const char *op, const char *method, const char *name, cJSON *body, cJSON **out) {
    char url[1024], auth[600];
    CURL *c = curl_easy_init();
    if (name) {
        char *p = curl_easy_escape(c, g_project, 0), *f = curl_easy_escape(c, g_config, 0), *n = curl_easy_escape(c, name, 0);
        snprintf(url, sizeof url, "%s/v3/configs/config/secret?project=%s&config=%s&name=%s", g_base, p, f, n);
        curl_free(p); curl_free(f); curl_free(n);
    } else {
        snprintf(url, sizeof url, "%s/v3/configs/config/secrets", g_base);
    }
    snprintf(auth, sizeof auth, "Authorization: Bearer %s", g_token);
    struct curl_slist *h = curl_slist_append(NULL, auth);
    h = curl_slist_append(h, "Accept: application/json");
    char *json = body ? cJSON_PrintUnformatted(body) : NULL;
    if (json) { h = curl_slist_append(h, "Content-Type: application/json"); curl_easy_setopt(c, CURLOPT_POSTFIELDS, json); }
    buf_t resp = {0};
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_CUSTOMREQUEST, method);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, h);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, loopback(g_base) ? "http" : "https");
    long status = 0;
    if (curl_easy_perform(c) == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(c);
    curl_slist_free_all(h);
    OPENSSL_cleanse(auth, sizeof auth);
    if (json) { OPENSSL_cleanse(json, strlen(json)); cJSON_free(json); }
    cJSON *parsed = resp.len ? cJSON_Parse(resp.data) : NULL;
    buf_wipe(&resp);
    if ((status < 200 || status > 299) && status != 404) {
        char *m = cJSON_PrintUnformatted(cJSON_GetObjectItemCaseSensitive(parsed, "messages"));
        fprintf(stderr, "%s: HTTP %ld %s\n", op, status, m ? m : "");
        cJSON_free(m);
    }
    if (out) *out = parsed; else cJSON_Delete(parsed);
    return status;
}

/* POST one change request. original_name NULL = new secret; expected != NULL = optimistic-concurrency guard. */
static int change(const char *op, const char *name, const char *original_name, const char *value, const char *expected) {
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "project", g_project);
    cJSON_AddStringToObject(body, "config", g_config);
    cJSON *cr = cJSON_CreateObject();
    cJSON_AddStringToObject(cr, "name", name);
    if (original_name) cJSON_AddStringToObject(cr, "originalName", original_name);
    else cJSON_AddNullToObject(cr, "originalName");
    cJSON_AddStringToObject(cr, "value", value);
    if (expected) cJSON_AddStringToObject(cr, "originalValue", expected);
    cJSON_AddItemToArray(cJSON_AddArrayToObject(body, "change_requests"), cr);
    long st = doppler_call(op, "POST", NULL, body, NULL);
    /* wipe value copies held by the cJSON tree before freeing it */
    cJSON *v = cJSON_GetObjectItemCaseSensitive(cr, "value"), *o = cJSON_GetObjectItemCaseSensitive(cr, "originalValue");
    OPENSSL_cleanse(v->valuestring, strlen(v->valuestring));
    if (o) OPENSSL_cleanse(o->valuestring, strlen(o->valuestring));
    cJSON_Delete(body);
    return st == 200 ? 0 : -1;
}

/* Doppler writes are upserts; prove the name is unused, then add it as a new secret. */
static int secret_create(const char *name, const char *value) {
    long st = doppler_call("probe", "GET", name, NULL, NULL);
    if (st == 200) { fprintf(stderr, "secret %s already exists (create is not an upsert)\n", name); return -1; }
    if (st != 404) return -1;
    return change("create", name, NULL, value, NULL);
}

/* Returns malloc'd stored ("raw") value (wipe + free), or NULL. */
static char *secret_read(const char *name) {
    cJSON *out = NULL;
    long st = doppler_call("read", "GET", name, NULL, &out);
    cJSON *raw = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(out, "value"), "raw");
    cJSON *computed = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(out, "value"), "computed");
    char *r = NULL;
    if (st == 200 && cJSON_IsString(raw)) r = strdup(raw->valuestring);
    if (st == 404) fprintf(stderr, "read: %s not found\n", name);
    if (cJSON_IsString(raw)) OPENSSL_cleanse(raw->valuestring, strlen(raw->valuestring));
    if (cJSON_IsString(computed)) OPENSSL_cleanse(computed->valuestring, strlen(computed->valuestring));
    cJSON_Delete(out);
    return r;
}

static int secret_update(const char *name, const char *value, const char *expected) {
    return change("update", name, name, value, expected);
}

static int secret_delete(const char *name) {
    long st = doppler_call("delete", "DELETE", name, NULL, NULL);
    return (st >= 200 && st <= 299) ? 0 : -1;
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

static int load_token(const char *file) {
    FILE *f = fopen(file, "r");
    if (!f) return -1;
    size_t n = fread(g_token, 1, sizeof g_token - 1, f);
    fclose(f);
    g_token[n] = '\0';
    while (n && (g_token[n - 1] == '\n' || g_token[n - 1] == '\r' || g_token[n - 1] == ' ')) g_token[--n] = '\0';
    return n ? 0 : -1;
}

int main(void) {
    const char *name = getenv("SECRET_NAME"), *tf = getenv("DOPPLER_TOKEN_FILE"), *host = getenv("DOPPLER_API_HOST");
    g_project = getenv("DOPPLER_PROJECT"); g_config = getenv("DOPPLER_CONFIG");
    if (!name || !tf || !g_project || !g_config) {
        fprintf(stderr, "set DOPPLER_PROJECT, DOPPLER_CONFIG, SECRET_NAME, DOPPLER_TOKEN_FILE\n");
        return 2;
    }
    snprintf(g_base, sizeof g_base, "%s", host ? host : "https://api.doppler.com");
    for (size_t n = strlen(g_base); n && g_base[n - 1] == '/'; n--) g_base[n - 1] = '\0';
    if (strncmp(g_base, "https://", 8) != 0 && !loopback(g_base)) { fprintf(stderr, "DOPPLER_API_HOST must use https\n"); return 2; }
    if (load_token(tf) != 0) { fprintf(stderr, "cannot read token file\n"); return 2; }

    curl_global_init(CURL_GLOBAL_DEFAULT);
    int rc = 1;
    char v1[45], v2[45], *got = NULL;
    if (random_value(v1) || random_value(v2)) goto done;

    if (secret_create(name, v1) != 0) goto done;
    printf("created: %s\n", name);
    got = secret_read(name);
    if (!same(v1, got)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    str_wipe_free(got); got = NULL;

    if (secret_update(name, v2, v1) != 0) goto done;
    got = secret_read(name);
    if (!same(v2, got)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated: %s\n", name);

    if (secret_delete(name) != 0) goto done;
    printf("deleted: %s\n", name);
    rc = 0;
done:
    str_wipe_free(got);
    OPENSSL_cleanse(g_token, sizeof g_token);
    OPENSSL_cleanse(v1, sizeof v1); OPENSSL_cleanse(v2, sizeof v2);
    curl_global_cleanup();
    return rc;
}
```

## 10. Use secrets in applications

| Mechanism | How values arrive | Notes |
| --- | --- | --- |
| REST/SDK at startup + cache (section 9) | In memory | Explicit control; one config per token keeps blast radius small. |
| `doppler run -- <command>` | Environment variables of the child process | Simple; env-var exposure applies; `--watch` (beta) restarts on change; fallback file on disk by default. |
| `doppler run --mount secrets.json -- <command>` | Ephemeral named pipe (Linux/macOS) at `DOPPLER_CLI_SECRETS_PATH`, not env vars | `--mount-max-reads 1` limits reads; `--mount-template` renders a config file. |
| Kubernetes Operator (`DopplerSecret` CRD) | Synced Kubernetes `Secret`; optional rolling restart on change | Anyone who can read Secrets in the namespace can read values. |
| Integration syncs (AWS, GCP, Azure, Vercel, GitHub Actions, …) | Pushed into the target platform | Each target is another store to protect and audit. |

Rotation-safe consumption: cache values with a TTL; re-read once on downstream authentication failure; subscribe to Doppler **webhooks** (config change events) to invalidate caches instead of polling aggressively (secret reads have their own, lower rate limit).

## 11. Automation and error handling

| Status | Typical cause | Action |
| --- | --- | --- |
| 400 | Malformed body; both `secrets` and `change_requests`; invalid name or value type | Fix the request. |
| 4xx on a guarded write | `originalValue`/`originalVisibility` did not match (exact status not documented) | Re-read, then decide whether to retry; never retry blindly. |
| 401 | Invalid, expired, or revoked token | Re-exchange OIDC token or use a valid token; check `--max-age` expiry. |
| 403 | Token lacks access to that project/environment; write with a read-only service token; restricted value with a user token | Grant the role/environment; use a read/write token for writers. |
| 404 | Project, config, or secret not found | Check names; the probe in create expects this. |
| 429 | Rate limit (per IP and per token; separate, lower limit for secret reads) | Honor `retry-after`; cache; batch reads with the list/download endpoints. |
| 5xx | Service error | Retry reads with backoff; for writes, re-read before retrying (the earlier attempt may have applied). |

Rate limits (requests per minute, per the API reference): Developer 240 reads / 120 secret reads / 60 writes; Team 480 / 240 / 120; Enterprise 480 / 480 / 240. Responses carry `x-ratelimit-limit`, `x-ratelimit-remaining`, and `x-ratelimit-reset`. [S01]

Practices:

- One service account (or OIDC identity) per workload; service tokens scoped to one config; readers and writers separate.
- Use `originalValue` on every automated update; probe before create.
- Read `raw` when verifying; read `computed` when the application intends reference expansion.
- Prefer one list/download call per config at startup over many single-secret reads.

## 12. Optional live CRUD verification

This **performs writes** in the project/config you choose (use a dedicated sandbox config). With a read/write token in `/secure/path/doppler-token`:

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${PROJECT:?}" "${CONFIG:?}"
export DOPPLER_TOKEN; DOPPLER_TOKEN="$(cat /secure/path/doppler-token)"
work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
key="CRUD_CHECK_$(date -u +%Y%m%d%H%M%S)_$$"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v1"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v2"

if doppler secrets get "$key" -p "$PROJECT" -c "$CONFIG" --plain > /dev/null 2>&1; then exit 1; fi
doppler secrets set "$key" -p "$PROJECT" -c "$CONFIG" --silent < "$work/v1"
doppler secrets get "$key" -p "$PROJECT" -c "$CONFIG" --plain --raw | cmp -s - "$work/v1"
doppler secrets set "$key" -p "$PROJECT" -c "$CONFIG" --silent < "$work/v2"
doppler secrets get "$key" -p "$PROJECT" -c "$CONFIG" --plain --raw | cmp -s - "$work/v2"
doppler secrets delete "$key" -p "$PROJECT" -c "$CONFIG" --yes --silent
printf 'PASS: create, read, update, and delete completed.\n'
```

Or run any program from section 9 with `DOPPLER_PROJECT`, `DOPPLER_CONFIG`, `SECRET_NAME`, and `DOPPLER_TOKEN_FILE` set.

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| 403 on write | Service token is `read`; service account role lacks write on that environment. |
| 403 / `[RESTRICTED]` / `null` value | Restricted visibility with a personal or CLI token; use a service account or service token. |
| Value contains `${...}` text, or differs from what was written | You read `raw` where the app expects `computed` (or the reverse). |
| Secret "missing" in a branch config | It was deleted in the root config, or the branch overrides it; check `doppler secrets --only-names` in both. |
| Old value still served | Fallback file used during an API failure; app cache; `doppler run` without `--watch` needs a restart. |
| CI log shows secret values | `secrets set`/`delete` without `--silent`; `secrets`/`get` output captured; remove the log, rotate. |
| Token works locally but not in CI | Local CLI is using a scoped personal login (`doppler configure`); CI must set `DOPPLER_TOKEN` or use OIDC. |
| 429 bursts at deploy time | Many replicas reading individually; read once per config, cache, stagger starts. |

## 14. Accuracy notes and official sources

- **SDKs:** Doppler documents Node.js and Python SDKs and states that a Go SDK is planned; no official SDK exists for the other languages, so REST is the correct integration path for them. The SDK caveats in 9.7/9.8 come from reading `doppler-sdk` 1.3.0 and `@dopplerhq/node-sdk` 1.3.0 sources. [S11] [S12] [S13]
- **Create semantics:** the API reference describes `originalName: null` as "new secret" but does not document a failure when the name already exists; the probe-then-create pattern is a client-side safeguard. The mock used here rejects that case, so it does not prove server behavior.
- **CLI flags** (`--silent`, `--plain`, `--raw`, `--only-names`, `--yes`, `--no-interactive`, `--visibility`, `--type`, `--no-file`, `--no-fallback`, `--mount`, `--watch`, `configs tokens create --access/--max-age`, `oidc login --identity/--token/--scope`) and the stdin and output behavior of `secrets set`/`delete` were checked in the CLI source at v3.77.1. [S15]
- **Rate limits** are from the API reference on the verification date and vary by plan. [S01]
- **Mock-based verification** validates client logic and request shapes, not server-side permissions, visibility, or rate limiting.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [API reference: overview][S01] | Bearer auth, token types, rate limits, HTTPS-only |
| S02 | [Retrieve secret][S02] | `GET …/secret` query and response fields |
| S03 | [Update secrets][S03] | `secrets` vs `change_requests`, `originalValue`, `shouldDelete` |
| S04 | [Delete secret][S04] | `DELETE …/secret`, 204 |
| S05 | [Service tokens][S05] | Scope, access, expiry, revocation |
| S06 | [Service accounts][S06] | Workplace and project roles, tokens |
| S07 | [Service account identities (OIDC)][S07] | `POST /v3/auth/oidc`, CLI `oidc login` |
| S08 | [Secret visibility][S08] | masked/unmasked/restricted behavior |
| S09 | [Setting secrets][S09] | stdin input, `--visibility`, `--type`, history guidance |
| S10 | [CLI guide][S10] | `run`, `secrets download --no-file`, fallback files |
| S11 | [Node.js SDK][S11] | `@dopplerhq/node-sdk` |
| S12 | [Python SDK][S12] | `doppler-sdk` |
| S13 | [Go SDK status][S13] | "planned"; use REST |
| S14 | [Kubernetes Operator][S14] | `DopplerSecret` sync and reloads |
| S15 | [Doppler CLI source][S15] | Flags and output behavior (v3.77.1) |
| S16 | [Config logs rollback][S16] | History and recovery |

[S01]: https://docs.doppler.com/reference/api
[S02]: https://docs.doppler.com/reference/secrets-get
[S03]: https://docs.doppler.com/reference/secrets-update
[S04]: https://docs.doppler.com/reference/secrets-delete
[S05]: https://docs.doppler.com/docs/service-tokens
[S06]: https://docs.doppler.com/docs/service-accounts
[S07]: https://docs.doppler.com/docs/service-account-identities
[S08]: https://docs.doppler.com/docs/visibility-types
[S09]: https://docs.doppler.com/docs/setting-secrets
[S10]: https://docs.doppler.com/docs/cli
[S11]: https://docs.doppler.com/docs/sdk-javascript
[S12]: https://docs.doppler.com/docs/sdk-python
[S13]: https://docs.doppler.com/docs/sdk-go
[S14]: https://docs.doppler.com/docs/kubernetes-operator
[S15]: https://github.com/DopplerHQ/cli
[S16]: https://docs.doppler.com/reference/config_logs-rollback
