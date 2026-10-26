# Infisical: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** Infisical (Cloud: `https://app.infisical.com` (US), `https://eu.infisical.com` (EU), or self-hosted). REST: `/api/v4/secrets/{secretName}`; current official SDK releases still call the deprecated `/api/v3/secrets/raw/{secretName}`  
**Primary authentication:** a **machine identity** using Universal Auth (client ID + client secret) or a platform auth method (Kubernetes, AWS, GCP, Azure, OIDC/JWT)  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use Bash and the Infisical CLI)

This guide covers **static secrets** in an Infisical project: key/value pairs addressed by project, **environment** (slug such as `dev`, `staging`, `prod`), and **folder path** (`/`, `/payments`), with per-secret versions and project-level commit history. It covers machine-identity authentication, project roles, complete CRUD workflows, the v3→v4 API transition, a full CRUD program in each of ten languages, runtime consumption (CLI, Agent, Kubernetes Operator), and troubleshooting. Dynamic secrets, secret rotation providers, PKI, and KMS are out of scope except where they affect design.

Credentials are assumed to be provisioned already. Do not paste a client secret or access token into this document, source files, command arguments, or example files.

**Verification boundary:** Endpoints and fields were cross-checked against the Infisical API reference and the official SDK sources in section 14. The Go (`github.com/infisical/go-sdk`, vetted at v0.8.0; v0.9.0 differs only in its `go` directive), Rust (`infisical` 0.0.4), Python (`infisicalsdk` 1.0.18), and TypeScript (`@infisical/sdk` 5.0.2) programs were compiled or type-checked and then **run end-to-end** against a local mock of the Infisical API (Universal Auth login plus the v3 and v4 secret endpoints, with create-only semantics and v4's strict body validation). Because four independent official SDKs passed against the same mock, it was then used to run the C program (v4 REST). The PHP program passed `php -l`; the C#, Java, PHP, and C++ programs were checked against the official SDK sources (`infisical-dotnet-sdk`, `java-sdk`, `php-sdk`, `infisical-cpp-sdk`) but not compiled here; Swift was not compiled (no toolchain). No call was made to a real Infisical instance. Section 12 provides an optional live test.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Authenticate the machine identity](#2-authenticate-the-machine-identity)
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
| Go | `github.com/infisical/go-sdk` | SDK (v3 raw endpoints) | `go vet`, mock run |
| Rust | `infisical` crate | SDK | `cargo check`, mock run |
| PHP | `infisical/php-sdk` | SDK | `php -l`, source check |
| C# | `Infisical.Sdk` | SDK | source check |
| Java | `com.infisical:sdk` | SDK | source check |
| Swift | none | REST v4 via `URLSession` | not compiled |
| Python | `infisicalsdk` | SDK | mock run |
| TypeScript | `@infisical/sdk` | SDK | `tsc --strict`, mock run |
| C++ | `infisical-cpp-sdk` (`libinfisical`) | SDK | header check |
| C | none | REST v4 via libcurl + cJSON | `-Werror`, mock run |

Every program follows the same contract:

- Environment: `INFISICAL_SITE_URL` (default `https://app.infisical.com`), `INFISICAL_UNIVERSAL_AUTH_CLIENT_ID`, `INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE` (path to a `0600` file holding the client secret), `INFISICAL_PROJECT_ID`, `INFISICAL_ENVIRONMENT` (slug), optional `INFISICAL_SECRET_PATH` (default `/`), and `SECRET_NAME` (for example `CRUD_CHECK`).
- It logs in with Universal Auth, **creates** a shared secret (create fails if the key exists), **reads** it with reference expansion disabled and compares in constant time, **updates** it (new version), reads and compares again, then **deletes** it.
- It prints key names and version numbers only.

For CLI snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
infisical --version
export INFISICAL_DOMAIN='https://app.infisical.com'   # EU: https://eu.infisical.com; self-hosted: your instance URL
PROJECT_ID='REPLACE_WITH_PROJECT_ID'
```

## 2. Authenticate the machine identity

### Auth methods

| Platform | Method | What the workload holds |
| --- | --- | --- |
| Kubernetes | Kubernetes Auth | Its service-account token (validated via TokenReview) |
| AWS / GCP / Azure | AWS / GCP / Azure Auth | Its cloud identity; nothing stored |
| CI (GitHub, GitLab), other OIDC issuers | OIDC / JWT Auth | The CI-issued token |
| Anything else | Universal Auth | Client ID (not secret) + **client secret** (secret) |
| Bootstrapped sidecar | Token Auth | A token minted for that identity |

Prefer platform methods. Universal Auth's client secret is a long-lived credential by default (TTL `0` = never expires, max uses `0` = unlimited). Harden it: set a client secret TTL and/or a small max-number-of-uses, restrict **trusted IPs** where your plan allows, keep login **lockout** enabled (default: 3 failures → 5-minute lockout), and for "secret zero" bootstrapping use a periodic, renewable access token with a single-use client secret. [S02]

### Access tokens

Login (`POST /api/v1/auth/universal-auth/login`) returns `accessToken`, `expiresIn`, `accessTokenMaxTTL`, and `tokenType: Bearer`. Tokens can be renewed with `POST /api/v1/auth/universal-auth/renew` up to their max TTL; after that, log in again. The Go SDK refreshes automatically by default; other SDKs and REST clients must re-login or renew. Documentation lists conflicting defaults for access-token TTL (7,200 seconds in one place, 30 days in another); configure TTLs explicitly on the identity. [S02]

### Confirm authentication without displaying the token

```bash
# Reads the client secret from a protected file; the access token stays in a shell variable, never echoed.
INFISICAL_TOKEN="$(INFISICAL_UNIVERSAL_AUTH_CLIENT_ID="$CLIENT_ID" \
  INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET="$(cat /secure/path/client-secret)" \
  infisical login --method=universal-auth --silent --plain)"
export INFISICAL_TOKEN
infisical secrets --projectId "$PROJECT_ID" --env dev --path / --silent > /dev/null && printf 'auth ok\n'
```

The command substitution places the client secret in a child process environment briefly; on shared hosts prefer the SDKs, which read it from a file. Never pass `--client-secret` on the command line.

### Required permissions

Grant the identity a **project role** with only the needed permissions on the needed environments and folder paths. The built-in roles are Admin, Member (Developer), Viewer, and No Access; create a custom role for runtime readers (secrets: read on `prod` at `/payments/**`) and a separate one for writers. [S03]

## 3. Data model and addressing

- **Organization → project → environment → folder path → secret key.** The same key can exist in each environment and folder.
- **Key:** an environment-variable-style name (`DB_PASSWORD`). Values are strings; multi-line values are supported (`skipMultilineEncoding` controls encoding of newlines).
- **Type:** `shared` (visible to all with access) or `personal` (a per-user override). Machine identities use `shared`.
- **References:** values may contain `${KEY}` or `${env.folder.KEY}`; reads expand them unless `expandSecretReferences=false`. Programs that verify writes must disable expansion.
- **Imports:** folders can import secrets from others; `includeImports` controls whether imported values are returned.
- **Versions and commits:** each change increments the secret's `version` and creates a project **commit** (environment/folder scoped); commits can be reverted or rolled back. Point-in-time recovery is a paid feature. [S05]
- **Approval policies:** an environment/path can require approvals; writes then return `{"approval": {...}}` (a change request) instead of `{"secret": {...}}`, and nothing changes until approval.
- **IDs:** the project ID is shown in project settings; programs address secrets by key, environment, and path.

Inventory without values:

```bash
infisical secrets --projectId "$PROJECT_ID" --env prod --path /payments --silent -o json |
  jq '[.[] | {key: .secretKey, type: .type}]'
```

## 4. Safe secret handling

- **Command lines:** `infisical secrets set KEY=value` puts the value in history and the process table. Use `KEY=@/path/to/file` or `--file`. [S06]
- **Output:** `infisical secrets` and `secrets get` print values; `secrets set` masks them unless `--show-values`. Use `--plain` only with redirection into a protected file. `-o json` output contains values even when you only display metadata with `jq`.
- **Error payloads:** the Node SDK puts the server's validation payload into 422 error messages, and SDK request errors include the URL. Log the error class and status code, not the full message (the TypeScript program extracts only the status).
- **References:** reading with expansion enabled can pull values from other environments the identity can access; disable it when you mean "exactly this value."
- **SDK caches:** the Python SDK caches reads for 60 seconds by default (writes through the same client invalidate the entry; the cache key ignores `version`); the Go SDK caches only if `CacheExpiryInSeconds` is set. Account for this in rotation logic.
- **Audit logs** record who read or changed which secret (plan-dependent retention); they do not contain values.
- **Memory:** wipe buffers where possible (`zeroize`, `OPENSSL_cleanse`); minimize copies of managed strings.

## 5. Create secrets

`POST /api/v4/secrets/{secretName}` with `{"projectId", "environment", "secretPath", "secretValue", "secretComment"?, "type"?: "shared", "tagIds"?, "skipMultilineEncoding"?, "secretMetadata"?}`; v4 rejects unknown properties. (The deprecated v3 equivalent is `POST /api/v3/secrets/raw/{secretName}` with `workspaceId`.) Creating a key that already exists in that environment/path fails with **400** — the API's create is create-only. [S04]

```bash
# From a protected file (CLI set is an upsert: it updates if the key exists)
infisical secrets set PARTNER_API_TOKEN=@/secure/path/to/api-token.txt \
  --projectId "$PROJECT_ID" --env dev --path / --type shared --silent > /dev/null
```

Because `infisical secrets set` creates **or updates**, use the API (or check existence first) when you need create-only semantics. The `@file` form reads the file's exact contents, including a trailing newline.

## 6. Read secrets

`GET /api/v4/secrets/{secretName}?projectId=…&environment=…&secretPath=/&type=shared&viewSecretValue=true&expandSecretReferences=false&includeImports=false` returns `{"secret": {"secretKey", "secretValue", "version", ...}}`. Add `version=N` for a specific version. [S04]

```bash
# One value to a new private file
infisical secrets get PARTNER_API_TOKEN --projectId "$PROJECT_ID" --env dev --path / \
  --expand=false --plain --silent > ./partner-api-token.secret

# Metadata only
infisical secrets --projectId "$PROJECT_ID" --env dev --path / --silent -o json |
  jq '.[] | select(.secretKey=="PARTNER_API_TOKEN") | {key: .secretKey, version}'
```

## 7. Update secrets

`PATCH /api/v4/secrets/{secretName}` with `{"projectId", "environment", "secretPath", "secretValue"?, "newSecretName"?, "secretComment"?, "type"?}`. Each update creates a new version. Under an approval policy the response is an approval request, not the secret. [S04]

```bash
infisical secrets set PARTNER_API_TOKEN=@/secure/path/new-token.txt \
  --projectId "$PROJECT_ID" --env dev --path / --type shared --silent > /dev/null

infisical secrets get PARTNER_API_TOKEN --projectId "$PROJECT_ID" --env dev --path / --expand=false --plain --silent |
  cmp -s - /secure/path/new-token.txt && printf 'Secret replacement verified.\n'
```

(`--plain` output may add a trailing newline; compare files written with the same convention, or compare through the SDK.)

Storing a new value does not rotate the credential at its source; Infisical's secret rotation feature (for supported providers) or your own rotation job must change the source first.

## 8. Delete and recover

`DELETE /api/v4/secrets/{secretName}` with the scope in the **JSON body** (`projectId`, `environment`, `secretPath`, `type`). The secret disappears from the environment immediately; the deletion is recorded as a commit and can be reverted through the commits interface (point-in-time recovery is a paid feature). [S04] [S05]

```bash
infisical secrets delete PARTNER_API_TOKEN --projectId "$PROJECT_ID" --env dev --path / --type=shared
```

Without `--type=shared`, the CLI deletes **personal** secrets with that name. Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Expected output for every program:

```text
created: CRUD_CHECK version 1
updated: version 2
deleted: CRUD_CHECK
```

### 9.1 Go

`go get github.com/infisical/go-sdk`. `AutoTokenRefresh` (default on) renews the access token in the background; `SilentMode` suppresses SDK warnings on stdout.

```go
// Infisical secrets CRUD with the official Go SDK (github.com/infisical/go-sdk).
// Auth: Universal Auth machine identity; the client secret is read from a file.
package main

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"fmt"
	"log"
	"os"
	"strings"

	infisical "github.com/infisical/go-sdk"
)

type Store struct {
	client                            infisical.InfisicalClientInterface
	projectID, environment, secretPath string
}

func Connect(ctx context.Context, projectID, environment, secretPath string) (*Store, error) {
	site := os.Getenv("INFISICAL_SITE_URL")
	if site == "" {
		site = "https://app.infisical.com"
	}
	// AutoTokenRefresh (default true) renews the access token in the background.
	client := infisical.NewInfisicalClient(ctx, infisical.Config{SiteUrl: site, SilentMode: true})
	raw, err := os.ReadFile(os.Getenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE"))
	if err != nil {
		return nil, fmt.Errorf("read client secret file: %w", err)
	}
	secret := strings.TrimSpace(string(raw))
	for i := range raw {
		raw[i] = 0
	}
	if _, err := client.Auth().UniversalAuthLogin(os.Getenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"), secret); err != nil {
		return nil, fmt.Errorf("universal auth login: %w", err)
	}
	return &Store{client: client, projectID: projectID, environment: environment, secretPath: secretPath}, nil
}

// Create fails if the key already exists at this path/environment (not an upsert).
func (s *Store) Create(name, value string) (int, error) {
	sec, err := s.client.Secrets().Create(infisical.CreateSecretOptions{
		SecretKey:     name,
		SecretValue:   value,
		SecretComment: "managed by secrets-crud example",
		ProjectID:     s.projectID,
		Environment:   s.environment,
		SecretPath:    s.secretPath,
		Type:          "shared",
	})
	if err != nil {
		return 0, fmt.Errorf("create %s: %w", name, err)
	}
	return sec.Version, nil
}

func (s *Store) Read(name string) (string, error) {
	sec, err := s.client.Secrets().Retrieve(infisical.RetrieveSecretOptions{
		SecretKey:              name,
		ProjectID:              s.projectID,
		Environment:            s.environment,
		SecretPath:             s.secretPath,
		Type:                   "shared",
		ExpandSecretReferences: false, // return exactly what was stored
	})
	if err != nil {
		return "", fmt.Errorf("retrieve %s: %w", name, err)
	}
	return sec.SecretValue, nil
}

// Update writes a new version of the secret.
func (s *Store) Update(name, value string) (int, error) {
	sec, err := s.client.Secrets().Update(infisical.UpdateSecretOptions{
		SecretKey:      name,
		NewSecretValue: value,
		ProjectID:      s.projectID,
		Environment:    s.environment,
		SecretPath:     s.secretPath,
		Type:           "shared",
	})
	if err != nil {
		return 0, fmt.Errorf("update %s: %w", name, err)
	}
	return sec.Version, nil
}

// Delete removes the secret from the environment (project snapshots keep history).
func (s *Store) Delete(name string) error {
	_, err := s.client.Secrets().Delete(infisical.DeleteSecretOptions{
		SecretKey:   name,
		ProjectID:   s.projectID,
		Environment: s.environment,
		SecretPath:  s.secretPath,
		Type:        "shared",
	})
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
	projectID, environment, name := os.Getenv("INFISICAL_PROJECT_ID"), os.Getenv("INFISICAL_ENVIRONMENT"), os.Getenv("SECRET_NAME")
	if projectID == "" || environment == "" || name == "" {
		log.Fatal("set INFISICAL_PROJECT_ID, INFISICAL_ENVIRONMENT, SECRET_NAME")
	}
	path := os.Getenv("INFISICAL_SECRET_PATH")
	if path == "" {
		path = "/"
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	store, err := Connect(ctx, projectID, environment, path)
	if err != nil {
		log.Fatal(err)
	}

	v1 := randomValue()
	ver, err := store.Create(name, v1)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("created:", name, "version", ver)
	if got, err := store.Read(name); err != nil || !equal(got, v1) {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	if ver, err = store.Update(name, v2); err != nil {
		log.Fatal(err)
	}
	if got, err := store.Read(name); err != nil || !equal(got, v2) {
		log.Fatal("read-back after update failed: ", err)
	}
	fmt.Println("updated: version", ver)

	if err := store.Delete(name); err != nil {
		log.Fatal(err)
	}
	fmt.Println("deleted:", name)
}
```

### 9.2 Rust

`Cargo.toml`:

```toml
[package]
name = "infisical-secrets-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
infisical = "0.0"
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
getrandom = "0.3"
base64 = "0.22"
zeroize = "1"
```

```rust
//! Infisical secrets CRUD with the official Rust SDK (crate `infisical`).
//! Auth: Universal Auth machine identity; the client secret is read from a file.
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use infisical::secrets::{CreateSecretRequest, DeleteSecretRequest, GetSecretRequest, UpdateSecretRequest};
use infisical::{AuthMethod, Client};
use std::{env, error::Error};
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

struct Store {
    client: Client,
    project_id: String,
    environment: String,
    path: String,
}

impl Store {
    async fn connect() -> Res<Self> {
        let var = |k: &str| env::var(k).map_err(|_| format!("set {k}"));
        let mut client = Client::builder()
            .base_url(env::var("INFISICAL_SITE_URL").unwrap_or_else(|_| "https://app.infisical.com".into()))
            .build()
            .await?;
        let secret = Zeroizing::new(std::fs::read_to_string(var("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE")?)?);
        let auth = AuthMethod::new_universal_auth(var("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID")?, secret.trim().to_string());
        client.login(auth).await?;
        Ok(Self {
            client,
            project_id: var("INFISICAL_PROJECT_ID")?,
            environment: var("INFISICAL_ENVIRONMENT")?,
            path: env::var("INFISICAL_SECRET_PATH").unwrap_or_else(|_| "/".into()),
        })
    }

    /// Fails if the key already exists at this path/environment (not an upsert).
    async fn create(&self, name: &str, value: &str) -> Res<i32> {
        let req = CreateSecretRequest::builder(name, value, &self.project_id, &self.environment)
            .path(&self.path)
            .r#type("shared")
            .secret_comment("managed by secrets-crud example")
            .build();
        Ok(self.client.secrets().create(req).await?.version)
    }

    async fn read(&self, name: &str) -> Res<Zeroizing<String>> {
        let req = GetSecretRequest::builder(name, &self.project_id, &self.environment)
            .path(&self.path)
            .r#type("shared")
            .expand_secret_references(false) // return exactly what was stored
            .build();
        Ok(Zeroizing::new(self.client.secrets().get(req).await?.secret_value))
    }

    /// Each update creates a new version in the secret's history.
    async fn update(&self, name: &str, value: &str) -> Res<i32> {
        let req = UpdateSecretRequest::builder(name, &self.project_id, &self.environment)
            .path(&self.path)
            .r#type("shared")
            .secret_value(value)
            .build();
        Ok(self.client.secrets().update(req).await?.version)
    }

    /// Removes the secret from the environment (project snapshots keep history).
    async fn delete(&self, name: &str) -> Res<()> {
        let req = DeleteSecretRequest::builder(name, &self.project_id, &self.environment)
            .path(&self.path)
            .r#type("shared")
            .build();
        self.client.secrets().delete(req).await?;
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
    let name = env::var("SECRET_NAME").map_err(|_| "set SECRET_NAME")?;
    let store = Store::connect().await?;

    let v1 = random_value();
    println!("created: {name} version {}", store.create(&name, &v1).await?);
    if !ct_eq(&store.read(&name).await?, &v1) { return Err("read-back after create did not match".into()); }

    let v2 = random_value();
    let version = store.update(&name, &v2).await?;
    if !ct_eq(&store.read(&name).await?, &v2) { return Err("read-back after update did not match".into()); }
    println!("updated: version {version}");

    store.delete(&name).await?;
    println!("deleted: {name}");
    Ok(())
}
```

### 9.3 PHP

`composer require infisical/php-sdk` (PHP 8.1+, Guzzle).

```php
<?php
// Infisical secrets CRUD with the official PHP SDK.
// composer require infisical/php-sdk
// Auth: Universal Auth machine identity; the client secret is read from a file.
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use Infisical\SDK\InfisicalSDK;
use Infisical\SDK\Models\CreateSecretParameters;
use Infisical\SDK\Models\DeleteSecretParameters;
use Infisical\SDK\Models\GetSecretParameters;
use Infisical\SDK\Models\UpdateSecretParameters;

final class InfisicalStore
{
    public function __construct(
        private InfisicalSDK $sdk,
        private string $projectId,
        private string $environment,
        private string $secretPath = '/',
    ) {}

    public static function connect(string $projectId, string $environment, string $secretPath): self
    {
        $sdk = new InfisicalSDK(getenv('INFISICAL_SITE_URL') ?: 'https://app.infisical.com');
        $file = getenv('INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE') ?: throw new RuntimeException('set INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE');
        $clientSecret = trim((string) file_get_contents($file));
        $sdk->auth()->universalAuth()->login((string) getenv('INFISICAL_UNIVERSAL_AUTH_CLIENT_ID'), $clientSecret);
        unset($clientSecret);
        return new self($sdk, $projectId, $environment, $secretPath);
    }

    /** Fails if the key already exists at this path/environment (not an upsert). */
    public function create(string $name, string $value): int
    {
        return $this->sdk->secrets()->create(new CreateSecretParameters(
            environment: $this->environment,
            projectId: $this->projectId,
            secretPath: $this->secretPath,
            secretKey: $name,
            secretValue: $value,
            secretComment: 'managed by secrets-crud example',
        ))->version;
    }

    public function read(string $name): string
    {
        return $this->sdk->secrets()->get(new GetSecretParameters(
            secretKey: $name,
            environment: $this->environment,
            projectId: $this->projectId,
            secretPath: $this->secretPath,
            type: 'shared',
            expandSecretReferences: false,   // return exactly what was stored
        ))->secretValue;
    }

    /** Each update creates a new version in the secret's history. */
    public function update(string $name, string $value): int
    {
        return $this->sdk->secrets()->update(new UpdateSecretParameters(
            secretKey: $name,
            environment: $this->environment,
            projectId: $this->projectId,
            secretPath: $this->secretPath,
            newSecretValue: $value,
        ))->version;
    }

    /** Removes the secret from the environment (project snapshots keep history). */
    public function delete(string $name): void
    {
        $this->sdk->secrets()->delete(new DeleteSecretParameters(
            secretKey: $name,
            environment: $this->environment,
            projectId: $this->projectId,
            secretPath: $this->secretPath,
        ));
    }
}

$need = static fn (string $k): string => getenv($k) ?: exit("set {$k}\n");
$store = InfisicalStore::connect($need('INFISICAL_PROJECT_ID'), $need('INFISICAL_ENVIRONMENT'), getenv('INFISICAL_SECRET_PATH') ?: '/');
$name = $need('SECRET_NAME');
$random = fn (): string => rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');

$v1 = $random();
echo "created: {$name} version " . $store->create($name, $v1) . "\n";
hash_equals($v1, $store->read($name)) || exit("read-back after create did not match\n");

$v2 = $random();
echo 'updated: version ' . $store->update($name, $v2) . "\n";
hash_equals($v2, $store->read($name)) || exit("read-back after update did not match\n");
unset($v1, $v2);

$store->delete($name);
echo "deleted: {$name}\n";
```

### 9.4 C#

`dotnet add package Infisical.Sdk`. Note: the SDK's internal retry policy retries **every** non-success response (including 4xx such as "already exists" or 404) three times with 2/4/8-second backoff, so failures surface after roughly 14 seconds.

```csharp
// Infisical secrets CRUD with the official .NET SDK.
// dotnet add package Infisical.Sdk
// Auth: Universal Auth machine identity; the client secret is read from a file.
using System.Security.Cryptography;
using System.Text;
using Infisical.Sdk;
using Infisical.Sdk.Model;

public sealed class InfisicalStore(InfisicalClient client, string projectId, string environment, string secretPath)
{
    public static async Task<InfisicalStore> ConnectAsync(string projectId, string environment, string secretPath)
    {
        var settings = new InfisicalSdkSettingsBuilder()
            .WithHostUri(Environment.GetEnvironmentVariable("INFISICAL_SITE_URL") ?? "https://app.infisical.com")
            .Build();
        var client = new InfisicalClient(settings);
        var secretFile = Environment.GetEnvironmentVariable("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE")
                         ?? throw new InvalidOperationException("set INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE");
        var clientSecret = (await File.ReadAllTextAsync(secretFile)).Trim();
        await client.Auth().UniversalAuth().LoginAsync(
            Environment.GetEnvironmentVariable("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID") ?? "", clientSecret);
        return new InfisicalStore(client, projectId, environment, secretPath);
    }

    /// <summary>Fails if the key already exists at this path/environment (not an upsert).</summary>
    public async Task<int> CreateAsync(string name, string value)
    {
        var secret = await client.Secrets().CreateAsync(new CreateSecretOptions
        {
            SecretName = name,
            SecretValue = value,
            SecretComment = "managed by secrets-crud example",
            ProjectId = projectId,
            EnvironmentSlug = environment,
            SecretPath = secretPath,
            Type = SecretType.Shared,
        });
        return secret.Version;
    }

    public async Task<string> ReadAsync(string name)
    {
        var secret = await client.Secrets().GetAsync(new GetSecretOptions
        {
            SecretName = name,
            ProjectId = projectId,
            EnvironmentSlug = environment,
            SecretPath = secretPath,
            Type = SecretType.Shared,
            ExpandSecretReferences = false, // return exactly what was stored
            ViewSecretValue = true,
        });
        return secret.SecretValue;
    }

    /// <summary>Each update creates a new version in the secret's history.</summary>
    public async Task<int> UpdateAsync(string name, string value)
    {
        var secret = await client.Secrets().UpdateAsync(new UpdateSecretOptions
        {
            SecretName = name,
            NewSecretValue = value,
            ProjectId = projectId,
            EnvironmentSlug = environment,
            SecretPath = secretPath,
            Type = SecretType.Shared,
        });
        return secret.Version;
    }

    /// <summary>Removes the secret from the environment (project snapshots keep history).</summary>
    public Task DeleteAsync(string name) => client.Secrets().DeleteAsync(new DeleteSecretOptions
    {
        SecretName = name,
        ProjectId = projectId,
        EnvironmentSlug = environment,
        SecretPath = secretPath,
    });
}

public static class Program
{
    static string RandomValue() =>
        Convert.ToBase64String(RandomNumberGenerator.GetBytes(32)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    static bool FixedEquals(string a, string b) =>
        CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(a), Encoding.UTF8.GetBytes(b));

    static string Need(string k) => Environment.GetEnvironmentVariable(k) ?? throw new InvalidOperationException($"set {k}");

    public static async Task<int> Main()
    {
        var store = await InfisicalStore.ConnectAsync(Need("INFISICAL_PROJECT_ID"), Need("INFISICAL_ENVIRONMENT"),
            Environment.GetEnvironmentVariable("INFISICAL_SECRET_PATH") ?? "/");
        var name = Need("SECRET_NAME");

        var v1 = RandomValue();
        Console.WriteLine($"created: {name} version {await store.CreateAsync(name, v1)}");
        if (!FixedEquals(v1, await store.ReadAsync(name)))
            throw new InvalidOperationException("read-back after create did not match");

        var v2 = RandomValue();
        var version = await store.UpdateAsync(name, v2);
        if (!FixedEquals(v2, await store.ReadAsync(name)))
            throw new InvalidOperationException("read-back after update did not match");
        Console.WriteLine($"updated: version {version}");

        await store.DeleteAsync(name);
        Console.WriteLine($"deleted: {name}");
        return 0;
    }
}
```

### 9.5 Java

Maven `com.infisical:sdk`. `Secret.getVersion()` is a `String` in this SDK.

```java
// Infisical secrets CRUD with the official Java SDK.
// Maven: com.infisical:sdk
// Auth: Universal Auth machine identity; the client secret is read from a file.
package example;

import com.infisical.sdk.InfisicalSdk;
import com.infisical.sdk.config.SdkConfig;
import com.infisical.sdk.models.Secret;
import com.infisical.sdk.util.InfisicalException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

public final class InfisicalCrud {
    private final InfisicalSdk sdk;
    private final String projectId, environment, secretPath;

    InfisicalCrud(InfisicalSdk sdk, String projectId, String environment, String secretPath) {
        this.sdk = sdk;
        this.projectId = projectId;
        this.environment = environment;
        this.secretPath = secretPath;
    }

    static InfisicalSdk connect() throws Exception {
        String site = System.getenv().getOrDefault("INFISICAL_SITE_URL", "https://app.infisical.com");
        InfisicalSdk sdk = new InfisicalSdk(new SdkConfig.Builder().withSiteUrl(site).build());
        String clientSecret = Files.readString(Path.of(System.getenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE"))).trim();
        sdk.Auth().UniversalAuthLogin(System.getenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"), clientSecret);
        return sdk;
    }

    /** Fails if the key already exists at this path/environment (not an upsert). */
    public String create(String name, String value) throws InfisicalException {
        Secret s = sdk.Secrets().CreateSecret(name, value, projectId, environment, secretPath);
        return s.getVersion();
    }

    public String read(String name) throws InfisicalException {
        // expandSecretReferences=false returns exactly what was stored; includeImports=false
        Secret s = sdk.Secrets().GetSecret(name, projectId, environment, secretPath, false, false, "shared");
        return s.getSecretValue();
    }

    /** Each update creates a new version in the secret's history. */
    public String update(String name, String value) throws InfisicalException {
        Secret s = sdk.Secrets().UpdateSecret(name, projectId, environment, secretPath, value, null);
        return s.getVersion();
    }

    /** Removes the secret from the environment (project snapshots keep history). */
    public void delete(String name) throws InfisicalException {
        sdk.Secrets().DeleteSecret(name, projectId, environment, secretPath);
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

    static String need(String k) {
        String v = System.getenv(k);
        if (v == null || v.isEmpty()) throw new IllegalArgumentException("set " + k);
        return v;
    }

    public static void main(String[] args) throws Exception {
        InfisicalCrud store = new InfisicalCrud(connect(), need("INFISICAL_PROJECT_ID"), need("INFISICAL_ENVIRONMENT"),
                System.getenv().getOrDefault("INFISICAL_SECRET_PATH", "/"));
        String name = need("SECRET_NAME");

        String v1 = randomValue();
        System.out.println("created: " + name + " version " + store.create(name, v1));
        if (!fixedEquals(v1, store.read(name))) throw new IllegalStateException("read-back after create failed");

        String v2 = randomValue();
        String version = store.update(name, v2);
        if (!fixedEquals(v2, store.read(name))) throw new IllegalStateException("read-back after update failed");
        System.out.println("updated: version " + version);

        store.delete(name);
        System.out.println("deleted: " + name);
    }
}
```

### 9.6 Swift

No official Swift SDK; this program calls the v4 REST API with an ephemeral `URLSession` and treats an `approval` response as "not applied." Server-side only.

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
// Infisical secrets CRUD in Swift over the REST API (/api/v4/secrets; the /api/v3/secrets/raw endpoints
// that current SDK releases call are deprecated).
// There is no official Infisical Swift SDK. Auth: Universal Auth; the client secret is read from a file.
// Server-side use only: never ship a machine-identity client secret inside an app bundle.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

enum InfisicalError: Error { case http(Int, String), config(String) }

final class InfisicalStore {
    private let site: String
    private let projectID: String, environment: String, secretPath: String
    private var token = ""
    private let session = URLSession(configuration: .ephemeral)

    init(projectID: String, environment: String, secretPath: String) async throws {
        let env = ProcessInfo.processInfo.environment
        site = env["INFISICAL_SITE_URL"] ?? "https://app.infisical.com"
        self.projectID = projectID
        self.environment = environment
        self.secretPath = secretPath
        let loopback = site.hasPrefix("http://127.0.0.1:") || site.hasPrefix("http://localhost:")
        guard site.hasPrefix("https://") || loopback else { throw InfisicalError.config("INFISICAL_SITE_URL must use https") }
        guard let clientID = env["INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"],
              let file = env["INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE"] else {
            throw InfisicalError.config("set INFISICAL_UNIVERSAL_AUTH_CLIENT_ID and _CLIENT_SECRET_FILE")
        }
        let secret = try String(contentsOfFile: file, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        let (status, json) = try await call("POST", "/api/v1/auth/universal-auth/login",
                                            body: ["clientId": clientID, "clientSecret": secret])
        guard status == 200, let t = json["accessToken"] as? String else { throw InfisicalError.http(status, "login") }
        token = t
    }

    private func call(_ method: String, _ path: String, query: [URLQueryItem] = [],
                      body: [String: Any]? = nil) async throws -> (Int, [String: Any]) {
        var comps = URLComponents(string: site + path)!
        if !query.isEmpty { comps.queryItems = query }
        var req = URLRequest(url: comps.url!)
        req.httpMethod = method
        req.timeoutInterval = 30
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !token.isEmpty { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        return (status, json)
    }

    private func path(_ name: String) -> String {
        "/api/v4/secrets/" + (name.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? name)
    }

    private var scope: [String: Any] {
        ["projectId": projectID, "environment": environment, "secretPath": secretPath, "type": "shared"]
    }

    /// Under a secret-approval policy, writes return {"approval": ...}: the change is pending, not applied.
    private static func version(_ json: [String: Any]) throws -> Int {
        if json["approval"] != nil { throw InfisicalError.config("change request created; pending approval") }
        return (json["secret"] as? [String: Any])?["version"] as? Int ?? -1
    }

    /// Fails (HTTP 400) if the key already exists at this path/environment (not an upsert).
    func create(_ name: String, _ value: String) async throws -> Int {
        let (status, json) = try await call("POST", path(name), body: scope.merging(
            ["secretValue": value, "secretComment": "managed by secrets-crud example"]) { $1 })
        guard status == 200 else { throw InfisicalError.http(status, json["message"] as? String ?? "create") }
        return try Self.version(json)
    }

    func read(_ name: String) async throws -> String {
        let (status, json) = try await call("GET", path(name), query: [
            URLQueryItem(name: "projectId", value: projectID),
            URLQueryItem(name: "environment", value: environment),
            URLQueryItem(name: "secretPath", value: secretPath),
            URLQueryItem(name: "type", value: "shared"),
            URLQueryItem(name: "viewSecretValue", value: "true"),
            URLQueryItem(name: "expandSecretReferences", value: "false"),
            URLQueryItem(name: "includeImports", value: "false"),
        ])
        guard status == 200, let secret = json["secret"] as? [String: Any],
              let value = secret["secretValue"] as? String else {
            throw InfisicalError.http(status, json["message"] as? String ?? "read")
        }
        return value
    }

    /// Each update creates a new version in the secret's history.
    func update(_ name: String, _ value: String) async throws -> Int {
        let (status, json) = try await call("PATCH", path(name), body: scope.merging(["secretValue": value]) { $1 })
        guard status == 200 else { throw InfisicalError.http(status, json["message"] as? String ?? "update") }
        return try Self.version(json)
    }

    /// Removes the secret from the environment (project snapshots keep history).
    func delete(_ name: String) async throws {
        let (status, json) = try await call("DELETE", path(name), body: scope)
        guard status == 200 else { throw InfisicalError.http(status, json["message"] as? String ?? "delete") }
        _ = try Self.version(json)
    }
}

func randomValue() -> String {
    var rng = SystemRandomNumberGenerator()
    return Data((0..<32).map { _ in UInt8.random(in: .min ... .max, using: &rng) }).base64EncodedString()
}

func fixedEquals(_ a: String, _ b: String) -> Bool {
    let x = Array(a.utf8), y = Array(b.utf8)
    return x.count == y.count && zip(x, y).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
}

let env = ProcessInfo.processInfo.environment
guard let project = env["INFISICAL_PROJECT_ID"], let environment = env["INFISICAL_ENVIRONMENT"],
      let name = env["SECRET_NAME"] else { fatalError("set INFISICAL_PROJECT_ID, INFISICAL_ENVIRONMENT, SECRET_NAME") }
let store = try await InfisicalStore(projectID: project, environment: environment,
                                     secretPath: env["INFISICAL_SECRET_PATH"] ?? "/")

let v1 = randomValue()
print("created: \(name) version \(try await store.create(name, v1))")
guard fixedEquals(v1, try await store.read(name)) else { fatalError("read-back after create failed") }

let v2 = randomValue()
let version = try await store.update(name, v2)
guard fixedEquals(v2, try await store.read(name)) else { fatalError("read-back after update failed") }
print("updated: version \(version)")

try await store.delete(name)
print("deleted: \(name)")
```

### 9.7 Python

`pip install infisicalsdk`. Request failures raise `infisical_sdk.infisical_requests.APIError` with `status_code`.

```python
"""Infisical secrets CRUD with the official Python SDK (infisicalsdk).

pip install infisicalsdk
Auth: Universal Auth machine identity; the client secret is read from a file.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys

from infisical_sdk import InfisicalSDKClient
from infisical_sdk.infisical_requests import APIError


class InfisicalStore:
    def __init__(self, client: InfisicalSDKClient, project_id: str, environment: str, secret_path: str = "/") -> None:
        self.client = client
        self.scope = {"project_id": project_id, "environment_slug": environment, "secret_path": secret_path}

    @classmethod
    def connect(cls, project_id: str, environment: str, secret_path: str) -> "InfisicalStore":
        # The SDK caches reads for 60 s by default; writes through the same client invalidate it.
        client = InfisicalSDKClient(host=os.environ.get("INFISICAL_SITE_URL", "https://app.infisical.com"), cache_ttl=60)
        with open(os.environ["INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE"], encoding="utf-8") as fh:
            client_secret = fh.read().strip()
        client.auth.universal_auth.login(client_id=os.environ["INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"],
                                         client_secret=client_secret)
        del client_secret
        return cls(client, project_id, environment, secret_path)

    def create(self, name: str, value: str) -> int:
        """Fails if the key already exists at this path/environment (not an upsert)."""
        try:
            secret = self.client.secrets.create_secret_by_name(
                secret_name=name, secret_value=value, secret_comment="managed by secrets-crud example", **self.scope)
        except APIError as exc:
            raise RuntimeError(f"create {name} failed (HTTP {exc.status_code}); it may already exist") from None
        return secret.version

    def read(self, name: str) -> str:
        secret = self.client.secrets.get_secret_by_name(
            secret_name=name, expand_secret_references=False, view_secret_value=True, include_imports=False,
            **self.scope)
        return secret.secretValue

    def update(self, name: str, value: str) -> int:
        """Each update creates a new version in the secret's history."""
        secret = self.client.secrets.update_secret_by_name(current_secret_name=name, secret_value=value, **self.scope)
        return secret.version

    def delete(self, name: str) -> None:
        """Removes the secret from the environment; project snapshots keep history."""
        self.client.secrets.delete_secret_by_name(secret_name=name, **self.scope)


def main() -> int:
    env = os.environ
    project_id, environment, name = env.get("INFISICAL_PROJECT_ID"), env.get("INFISICAL_ENVIRONMENT"), env.get("SECRET_NAME")
    if not (project_id and environment and name):
        print("set INFISICAL_PROJECT_ID, INFISICAL_ENVIRONMENT, SECRET_NAME", file=sys.stderr)
        return 2
    store = InfisicalStore.connect(project_id, environment, env.get("INFISICAL_SECRET_PATH", "/"))

    v1 = secrets.token_urlsafe(32)
    print(f"created: {name} version {store.create(name, v1)}")
    if not hmac.compare_digest(v1, store.read(name)):
        raise RuntimeError("read-back after create did not match")

    v2 = secrets.token_urlsafe(32)
    version = store.update(name, v2)
    if not hmac.compare_digest(v2, store.read(name)):
        raise RuntimeError("read-back after update did not match")
    print(f"updated: version {version}")

    store.delete(name)
    print(f"deleted: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

`npm i @infisical/sdk`. Use the exported `SecretType` enum.

```typescript
// Infisical secrets CRUD with the official Node SDK (@infisical/sdk).
// npm i @infisical/sdk
// Auth: Universal Auth machine identity; the client secret is read from a file, not the environment.
import { readFile } from "node:fs/promises";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { InfisicalSDK, SecretType } from "@infisical/sdk";

interface Scope {
  projectId: string;
  environment: string; // environment slug, e.g. "dev"
  secretPath: string; // folder, e.g. "/" or "/payments"
}

export class InfisicalStore {
  constructor(private readonly sdk: InfisicalSDK, private readonly scope: Scope) {}

  static async connect(scope: Scope): Promise<InfisicalStore> {
    const sdk = new InfisicalSDK({ siteUrl: process.env.INFISICAL_SITE_URL ?? "https://app.infisical.com" });
    const clientSecret = (await readFile(process.env.INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE ?? "", "utf8")).trim();
    await sdk.auth().universalAuth.login({
      clientId: process.env.INFISICAL_UNIVERSAL_AUTH_CLIENT_ID ?? "",
      clientSecret,
    });
    return new InfisicalStore(sdk, scope);
  }

  /** Create fails if the key already exists at this path/environment (not an upsert). */
  async create(name: string, value: string): Promise<number> {
    const { secret } = await this.sdk.secrets().createSecret(name, {
      ...this.scope,
      secretValue: value,
      secretComment: "managed by secrets-crud example",
      type: SecretType.Shared,
    });
    return secret.version;
  }

  async read(name: string): Promise<string> {
    const secret = await this.sdk.secrets().getSecret({
      ...this.scope,
      secretName: name,
      type: SecretType.Shared,
      expandSecretReferences: false, // return exactly what was stored
      viewSecretValue: true,
    });
    return secret.secretValue;
  }

  /** Each update creates a new secret version in Infisical's history. */
  async update(name: string, value: string): Promise<number> {
    const { secret } = await this.sdk.secrets().updateSecret(name, { ...this.scope, secretValue: value, type: SecretType.Shared });
    return secret.version;
  }

  /** Delete removes the secret from the environment; history is kept in project snapshots. */
  async delete(name: string): Promise<void> {
    await this.sdk.secrets().deleteSecret(name, { ...this.scope, type: SecretType.Shared });
  }
}

const randomValue = (): string => randomBytes(32).toString("base64url");
const same = (a: string, b: string): boolean => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

async function main(): Promise<void> {
  const { INFISICAL_PROJECT_ID: projectId, INFISICAL_ENVIRONMENT: environment, SECRET_NAME: name } = process.env;
  if (!projectId || !environment || !name) throw new Error("set INFISICAL_PROJECT_ID, INFISICAL_ENVIRONMENT, SECRET_NAME");
  const store = await InfisicalStore.connect({
    projectId,
    environment,
    secretPath: process.env.INFISICAL_SECRET_PATH ?? "/",
  });

  const v1 = randomValue();
  console.log(`created: ${name} version ${await store.create(name, v1)}`);
  if (!same(v1, await store.read(name))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  const version = await store.update(name, v2);
  if (!same(v2, await store.read(name))) throw new Error("read-back after update did not match");
  console.log(`updated: version ${version}`);

  await store.delete(name);
  console.log(`deleted: ${name}`);
}

main().catch((err: unknown) => {
  // Request errors embed URL, method, status and (for 422) the server's validation payload;
  // log only the class and status code.
  const status = err instanceof Error ? /\[StatusCode=(\d+)\]/.exec(err.message)?.[1] : undefined;
  console.error(`${err instanceof Error ? err.name : "unknown error"}${status ? ` (HTTP ${status})` : ""}`);
  process.exitCode = 1;
});
```

### 9.9 C++

Built with CMake `FetchContent` from the official repository (C++17, libcurl, OpenSSL). Errors are thrown as `Infisical::InfisicalError`.

```cpp
// Infisical secrets CRUD with the official C++ SDK (libinfisical, C++17).
// CMake: FetchContent_Declare(infisical GIT_REPOSITORY https://github.com/Infisical/infisical-cpp-sdk.git
//                             GIT_TAG <pinned release>) ; target_link_libraries(app infisical OpenSSL::Crypto)
// Auth: Universal Auth machine identity; the client secret is read from a file.
#include <libinfisical/InfisicalClient.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

static std::string env(const char* k, const char* fallback = nullptr) {
  const char* v = std::getenv(k);
  if (v && *v) return v;
  if (fallback) return fallback;
  throw std::runtime_error(std::string("set ") + k);
}

static void wipe(std::string& s) { OPENSSL_cleanse(s.data(), s.size()); s.clear(); }

class InfisicalStore {
 public:
  InfisicalStore(Infisical::InfisicalClient& client, std::string project, std::string environment, std::string path)
      : client_(client), project_(std::move(project)), env_(std::move(environment)), path_(std::move(path)) {}

  // Fails if the key already exists at this path/environment (not an upsert).
  unsigned int create(const std::string& name, const std::string& value) {
    auto opts = Infisical::Input::CreateSecretOptionsBuilder()
                    .withProjectId(project_)
                    .withEnvironment(env_)
                    .withSecretPath(path_)
                    .withSecretKey(name)
                    .withSecretValue(value)
                    .withSecretComment("managed by secrets-crud example")
                    .build();
    return client_.secrets().createSecret(opts).getVersion();
  }

  std::string read(const std::string& name) {
    auto opts = Infisical::Input::GetSecretOptionsBuilder()
                    .withProjectId(project_)
                    .withEnvironment(env_)
                    .withSecretPath(path_)
                    .withSecretKey(name)
                    .withType("shared")
                    .withExpandSecretReferences(false)  // return exactly what was stored
                    .build();
    return client_.secrets().getSecret(opts).getSecretValue();
  }

  // Each update creates a new version in the secret's history.
  unsigned int update(const std::string& name, const std::string& value) {
    auto opts = Infisical::Input::UpdateSecretOptionsBuilder()
                    .withProjectId(project_)
                    .withEnvironment(env_)
                    .withSecretPath(path_)
                    .withSecretKey(name)
                    .withType("shared")
                    .withSecretValue(value)
                    .build();
    return client_.secrets().updateSecret(opts).getVersion();
  }

  // Removes the secret from the environment (project snapshots keep history).
  void remove(const std::string& name) {
    auto opts = Infisical::Input::DeleteSecretOptionsBuilder()
                    .withProjectId(project_)
                    .withEnvironment(env_)
                    .withSecretPath(path_)
                    .withSecretKey(name)
                    .withType("shared")
                    .build();
    client_.secrets().deleteSecret(opts);
  }

 private:
  Infisical::InfisicalClient& client_;
  std::string project_, env_, path_;
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
  std::ifstream in(env("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE"));
  std::string client_secret((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  while (!client_secret.empty() && (client_secret.back() == '\n' || client_secret.back() == '\r')) client_secret.pop_back();

  Infisical::InfisicalClient client(
      Infisical::ConfigBuilder()
          .withHostUrl(env("INFISICAL_SITE_URL", "https://app.infisical.com"))
          .withAuthentication(Infisical::AuthenticationBuilder()
                                  .withUniversalAuth(env("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"), client_secret)
                                  .build())
          .build());
  wipe(client_secret);

  InfisicalStore store(client, env("INFISICAL_PROJECT_ID"), env("INFISICAL_ENVIRONMENT"),
                       env("INFISICAL_SECRET_PATH", "/"));
  std::string name = env("SECRET_NAME");

  std::string v1 = random_value();
  std::cout << "created: " << name << " version " << store.create(name, v1) << "\n";
  std::string got = store.read(name);
  if (!same(v1, got)) throw std::runtime_error("read-back after create failed");

  std::string v2 = random_value();
  unsigned int version = store.update(name, v2);
  got = store.read(name);
  if (!same(v2, got)) throw std::runtime_error("read-back after update failed");
  std::cout << "updated: version " << version << "\n";
  wipe(v1); wipe(v2); wipe(got);

  store.remove(name);
  std::cout << "deleted: " << name << "\n";
  return 0;
} catch (const Infisical::InfisicalError& e) {
  std::cerr << "Infisical error: " << e.what() << "\n";
  return 1;
} catch (const std::exception& e) {
  std::cerr << "error: " << e.what() << "\n";
  return 1;
}
```

### 9.10 C

v4 REST with libcurl + cJSON; HTTPS-only except for loopback; wipes the client secret, token, and value buffers; reports approval-gated writes.

```c
/*
 * Infisical secrets CRUD in C over the REST API (/api/v4/secrets; the older /api/v3/secrets/raw
 * endpoints that current SDK releases call are deprecated). libcurl + cJSON + OpenSSL.
 *
 *   cc -std=c11 -Wall -Wextra -O2 infisical_crud.c -o infisical_crud \
 *      $(pkg-config --cflags --libs libcurl libcjson openssl)
 *
 * Auth: Universal Auth (INFISICAL_UNIVERSAL_AUTH_CLIENT_ID + client secret read from
 * INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE). Plain HTTP is allowed only to loopback.
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

static char g_site[512];
static char *g_token = NULL;
static const char *g_project, *g_env, *g_path;

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

/* One API call. Returns HTTP status; *out gets parsed JSON (caller frees). */
static long api(const char *method, const char *url, cJSON *body, cJSON **out) {
    struct curl_slist *h = curl_slist_append(NULL, "Content-Type: application/json");
    char auth[4096];
    if (g_token) { snprintf(auth, sizeof auth, "Authorization: Bearer %s", g_token); h = curl_slist_append(h, auth); }
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
    if (!loopback(g_site)) curl_easy_setopt(c, CURLOPT_PROTOCOLS_STR, "https");
    long st = 0;
    if (curl_easy_perform(c) == CURLE_OK) curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &st);
    curl_easy_cleanup(c);
    curl_slist_free_all(h);
    OPENSSL_cleanse(auth, sizeof auth);
    if (json) { OPENSSL_cleanse(json, strlen(json)); cJSON_free(json); }
    if (out) *out = resp.len ? cJSON_Parse(resp.data) : NULL;
    buf_wipe(&resp);
    return st;
}

static int login(void) {
    const char *id = getenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"), *file = getenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET_FILE");
    if (!id || !file) { fprintf(stderr, "set INFISICAL_UNIVERSAL_AUTH_CLIENT_ID and _CLIENT_SECRET_FILE\n"); return -1; }
    FILE *f = fopen(file, "r");
    if (!f) return -1;
    char secret[512] = {0};
    size_t n = fread(secret, 1, sizeof secret - 1, f);
    fclose(f);
    while (n && (secret[n - 1] == '\n' || secret[n - 1] == '\r')) secret[--n] = '\0';
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "clientId", id);
    cJSON_AddStringToObject(body, "clientSecret", secret);
    OPENSSL_cleanse(secret, sizeof secret);
    char url[600]; snprintf(url, sizeof url, "%s/api/v1/auth/universal-auth/login", g_site);
    cJSON *out = NULL;
    long st = api("POST", url, body, &out);
    cJSON_Delete(body);
    cJSON *tok = cJSON_GetObjectItemCaseSensitive(out, "accessToken");
    if (st == 200 && cJSON_IsString(tok)) { g_token = strdup(tok->valuestring); OPENSSL_cleanse(tok->valuestring, strlen(tok->valuestring)); }
    else fprintf(stderr, "login failed: HTTP %ld\n", st);
    cJSON_Delete(out);
    return g_token ? 0 : -1;
}

static void secret_url(char *url, size_t cap, const char *name, int with_query) {
    CURL *c = curl_easy_init();
    char *n = curl_easy_escape(c, name, 0), *p = curl_easy_escape(c, g_path, 0);
    char *w = curl_easy_escape(c, g_project, 0), *e = curl_easy_escape(c, g_env, 0);
    if (with_query)
        snprintf(url, cap, "%s/api/v4/secrets/%s?projectId=%s&environment=%s&secretPath=%s&type=shared"
                 "&viewSecretValue=true&expandSecretReferences=false&includeImports=false", g_site, n, w, e, p);
    else
        snprintf(url, cap, "%s/api/v4/secrets/%s", g_site, n);
    curl_free(n); curl_free(p); curl_free(w); curl_free(e);
    curl_easy_cleanup(c);
}

static cJSON *scope_body(void) {
    cJSON *b = cJSON_CreateObject();
    cJSON_AddStringToObject(b, "projectId", g_project);
    cJSON_AddStringToObject(b, "environment", g_env);
    cJSON_AddStringToObject(b, "secretPath", g_path);
    cJSON_AddStringToObject(b, "type", "shared");
    return b;
}

/* A write under a secret-approval policy returns {"approval": ...} instead of {"secret": ...}:
 * the change is pending review and has NOT been applied. */
static int version_of(cJSON *out) {
    if (cJSON_GetObjectItemCaseSensitive(out, "approval")) {
        fprintf(stderr, "change request created; pending approval (not applied)\n");
        return -1;
    }
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(out, "secret"), "version");
    return cJSON_IsNumber(v) ? v->valueint : -1;
}

/* Returns the HTTP status and logs the server message (Infisical errors never echo values). */
static long report(const char *op, long st, cJSON *out) {
    if (st != 200) {
        const cJSON *m = cJSON_GetObjectItemCaseSensitive(out, "message");
        fprintf(stderr, "%s: HTTP %ld %s\n", op, st, cJSON_IsString(m) ? m->valuestring : "");
    }
    return st;
}

/* CREATE: fails (400) if the key already exists at this path/environment. Returns version or -1. */
static int secret_create(const char *name, const char *value) {
    char url[1200]; secret_url(url, sizeof url, name, 0);
    cJSON *b = scope_body();
    cJSON_AddStringToObject(b, "secretValue", value);
    cJSON_AddStringToObject(b, "secretComment", "managed by secrets-crud example");
    cJSON *out = NULL;
    long st = report("create", api("POST", url, b, &out), out);
    cJSON_Delete(b);
    int v = st == 200 ? version_of(out) : -1;
    cJSON_Delete(out);
    return v;
}

/* READ: returns malloc'd value (wipe + free) or NULL. */
static char *secret_read(const char *name) {
    char url[1200]; secret_url(url, sizeof url, name, 1);
    cJSON *out = NULL;
    long st = report("read", api("GET", url, NULL, &out), out);
    cJSON *v = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(out, "secret"), "secretValue");
    char *r = (st == 200 && cJSON_IsString(v)) ? strdup(v->valuestring) : NULL;
    if (cJSON_IsString(v)) OPENSSL_cleanse(v->valuestring, strlen(v->valuestring));
    cJSON_Delete(out);
    return r;
}

/* UPDATE: new version. Returns version or -1. */
static int secret_update(const char *name, const char *value) {
    char url[1200]; secret_url(url, sizeof url, name, 0);
    cJSON *b = scope_body();
    cJSON_AddStringToObject(b, "secretValue", value);
    cJSON *out = NULL;
    long st = report("update", api("PATCH", url, b, &out), out);
    cJSON_Delete(b);
    int v = st == 200 ? version_of(out) : -1;
    if (out) {   /* response echoes the value; wipe it */
        cJSON *sv = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(out, "secret"), "secretValue");
        if (cJSON_IsString(sv)) OPENSSL_cleanse(sv->valuestring, strlen(sv->valuestring));
    }
    cJSON_Delete(out);
    return v;
}

/* DELETE: removes the secret from the environment. */
static int secret_delete(const char *name) {
    char url[1200]; secret_url(url, sizeof url, name, 0);
    cJSON *b = scope_body();
    cJSON *out = NULL;
    long st = report("delete", api("DELETE", url, b, &out), out);
    cJSON_Delete(b);
    int ok = st == 200 && version_of(out) >= 0;
    cJSON_Delete(out);
    return ok ? 0 : -1;
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
    const char *site = getenv("INFISICAL_SITE_URL"), *name = getenv("SECRET_NAME");
    g_project = getenv("INFISICAL_PROJECT_ID"); g_env = getenv("INFISICAL_ENVIRONMENT");
    g_path = getenv("INFISICAL_SECRET_PATH") ? getenv("INFISICAL_SECRET_PATH") : "/";
    if (!g_project || !g_env || !name) { fprintf(stderr, "set INFISICAL_PROJECT_ID, INFISICAL_ENVIRONMENT, SECRET_NAME\n"); return 2; }
    snprintf(g_site, sizeof g_site, "%s", site ? site : "https://app.infisical.com");
    if (strncmp(g_site, "https://", 8) != 0 && !loopback(g_site)) { fprintf(stderr, "INFISICAL_SITE_URL must use https\n"); return 2; }
    curl_global_init(CURL_GLOBAL_DEFAULT);
    int rc = 1, v;
    char v1[45], v2[45], *got = NULL;
    if (login() != 0) goto done;

    random_value(v1);
    if ((v = secret_create(name, v1)) < 0) goto done;
    printf("created: %s version %d\n", name, v);
    got = secret_read(name);
    if (!same(v1, got)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    str_wipe_free(got); got = NULL;

    random_value(v2);
    if ((v = secret_update(name, v2)) < 0) goto done;
    got = secret_read(name);
    if (!same(v2, got)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated: version %d\n", v);

    if (secret_delete(name) != 0) goto done;
    printf("deleted: %s\n", name);
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

| Mechanism | How values arrive | Notes |
| --- | --- | --- |
| SDK at startup + cache (section 9) | In memory | Explicit control; handle token renewal. |
| `infisical run -- <command>` | Environment variables of the child process | Simple; env-var exposure applies; restart to pick up changes (or `--watch`). |
| Infisical Agent | Templated files; auto-auth and token renewal | Files on tmpfs, `0600`; template re-render on change. |
| Kubernetes Operator (`InfisicalSecret` CRD) | Synced Kubernetes `Secret`; optional auto-reload of Deployments | Widens exposure to anyone who can read Secrets in the namespace. |
| CSI provider / injectors (where available) | Files | Pod-scoped. |

Rotation-safe consumption: cache values with a TTL; re-read once on downstream authentication failure; keep `expandSecretReferences` consistent between writers and readers.

## 11. Automation and error handling

| Status | Typical cause | Action |
| --- | --- | --- |
| 400 | Create on an existing key; bad environment/path | Treat create as create-only; verify environment slug and folder exist. |
| 401 | Expired/invalid access token; lockout after failed logins | Renew or re-login; check client secret TTL/uses; wait out lockout. |
| 403 | Role lacks the permission on that environment/path; IP not trusted | Adjust custom role; check trusted IPs. |
| 404 | Key, folder, environment, or project not found | Check scope; folders are not created implicitly by reads. |
| 422 | v4 validation: unknown property (for example `workspaceId` on v4), wrong types | Use v4 field names (`projectId`, `includeImports`). |
| 429 | Plan rate limits | Back off; cache reads. |
| 200 with `approval` | Approval policy on the environment/path | The change is pending; do not assume it applied. |

Practices:

- One machine identity per workload per environment; never share client secrets between services.
- Keep the access token in memory; renew before expiry; re-login when the max TTL is reached.
- Use API create (create-only) for provisioning; reserve CLI `set` (upsert) for deliberate overwrites.
- Read with `expandSecretReferences=false` when verifying or comparing values.

## 12. Optional live CRUD verification

This **performs writes** in the project/environment you choose (use a sandbox environment). With an access token already exported as `INFISICAL_TOKEN` (section 2):

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${PROJECT_ID:?}" "${INFISICAL_TOKEN:?}"
ENV_SLUG="${ENV_SLUG:-dev}"
work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
key="CRUD_CHECK_$(date -u +%Y%m%d%H%M%S)_$$"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v1"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v2"

infisical secrets set "$key=@$work/v1" --projectId "$PROJECT_ID" --env "$ENV_SLUG" --path / --type shared --silent > /dev/null
infisical secrets get "$key" --projectId "$PROJECT_ID" --env "$ENV_SLUG" --path / --expand=false --plain --silent | tr -d '\n' | cmp -s - "$work/v1"
infisical secrets set "$key=@$work/v2" --projectId "$PROJECT_ID" --env "$ENV_SLUG" --path / --type shared --silent > /dev/null
infisical secrets get "$key" --projectId "$PROJECT_ID" --env "$ENV_SLUG" --path / --expand=false --plain --silent | tr -d '\n' | cmp -s - "$work/v2"
infisical secrets delete "$key" --projectId "$PROJECT_ID" --env "$ENV_SLUG" --path / --type=shared > /dev/null
printf 'PASS: create, read, update, and delete completed.\n'
```

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| Login fails, then keeps failing | Lockout after 3 failures (5 minutes); client secret expired or out of uses; trusted IPs. |
| 403 on read | Custom role does not cover that environment or folder path; identity not added to the project. |
| Value contains `${...}` text or wrong value | Reference expansion differs between writer and reader. |
| Read returns an old value | SDK cache (Python 60 s default); approval-gated write still pending. |
| 422 from a hand-written v4 client | v3 field names (`workspaceId`, `include_imports`) sent to v4. |
| CLI delete "did nothing" | Deleted personal, not shared; use `--type=shared`. |
| Folder not found | Create the folder first; paths are exact. |
| Secret value appears in logs | Logged SDK error messages or `--plain` output in CI logs; remove, rotate. |

## 14. Accuracy notes and official sources

- **v3 vs v4:** the API reference marks `GET /api/v3/secrets/raw/{secretName}` deprecated in favor of `/api/v4/secrets/{secretName}`. The Go, Python, Node, Java, .NET, PHP, Rust, and C++ SDK sources reviewed still call v3; the REST programs here use v4. [S04] [S07]
- **Access token TTL default:** the Universal Auth page lists both 7,200 seconds and 2,592,000 seconds as defaults; set TTLs explicitly. [S02]
- **CLI flags** (`secrets get/set/delete`, `--expand`, `--plain`, `--type`, `@file`, `-o json`, `login --method=universal-auth --plain`) were checked against `infisical --help` output of CLI 0.44.9. Some newer documentation pages show an `infisical sm` prefix; `infisical secrets` remains available in that release.
- **Mock-based verification** validates client logic and request shapes, not server-side permissions or approval workflows.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [SDK overview][S01] | Official SDK languages |
| S02 | [Universal Auth][S02] | Login/renew endpoints, TTLs, uses, trusted IPs, lockout |
| S03 | [Role-based access controls][S03] | Project roles and custom roles |
| S04 | [API reference: secrets (v4)][S04] | Create, read, update, delete bodies and responses |
| S05 | [Point-in-time recovery][S05] | Commits, revert/rollback, plan availability |
| S06 | [CLI: secrets][S06] | get/set/delete, `@file`, `--type` |
| S07 | [Deprecated v3 read endpoint][S07] | Deprecation notice |
| S08 | [Go SDK][S08] | Go client |
| S09 | [Node SDK][S09] | TypeScript client |
| S10 | [Python SDK][S10] | Python client and cache |
| S11 | [Infisical Agent][S11] | Templates, auto-auth |
| S12 | [Kubernetes Operator][S12] | InfisicalSecret CRD |

[S01]: https://infisical.com/docs/sdks/overview
[S02]: https://infisical.com/docs/documentation/platform/identities/universal-auth
[S03]: https://infisical.com/docs/documentation/platform/access-controls/role-based-access-controls
[S04]: https://infisical.com/docs/api-reference/endpoints/secrets/create
[S05]: https://infisical.com/docs/documentation/platform/pit-recovery
[S06]: https://infisical.com/docs/cli/commands/secrets
[S07]: https://infisical.com/docs/api-reference/endpoints/deprecated/secrets/read
[S08]: https://github.com/Infisical/go-sdk
[S09]: https://github.com/Infisical/node-sdk-v2
[S10]: https://github.com/Infisical/python-sdk-official
[S11]: https://infisical.com/docs/integrations/platforms/infisical-agent
[S12]: https://infisical.com/docs/integrations/platforms/kubernetes/overview
