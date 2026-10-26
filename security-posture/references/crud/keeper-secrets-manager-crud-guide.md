# Keeper Secrets Manager: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** Keeper Secrets Manager (KSM), the machine-access API to Keeper vault records. Region hosts: `keepersecurity.com` (US), `keepersecurity.eu`, `keepersecurity.com.au`, plus GovCloud, Japan, and Canada deployments. Transport endpoint: `POST https://<host>/api/rest/sm/v1/<operation>` (`get_secret`, `create_secret`, `update_secret`, `delete_secret`, …) with **end-to-end encrypted** payloads  
**Primary authentication:** a **KSM device configuration** (client ID, device EC private key, application key, server key ID, hostname) created once from a **One-Time Access Token**; every request is signed with the device key  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (operator snippets use the `ksm` CLI)

This guide covers **records** that a KSM **application** can reach through **shared folders**: typed records (`login`, `databaseCredentials`, …) with standard and custom fields, addressed by **record UID**. It covers the device/configuration model and why plain HTTP clients are not an option, complete CRUD workflows (including revision-checked updates and two-phase rotation saves), a full CRUD program in each of ten languages, a JSON-lines bridge for languages without an SDK, runtime consumption, and troubleshooting. Commander administration, Keeper PAM, and files/attachments are covered only where they affect secrets work.

Credentials are assumed to be provisioned already. Do not paste a One-Time Access Token or a KSM configuration into this document, source files, command arguments, or example files.

**Verification boundary:** The Python (`keeper-secrets-manager-core` 17.3.0), TypeScript (`@keeper-security/secrets-manager-core` 17.6.0, `tsc --strict`), and Rust (`keeper-secrets-manager-core` 17.3.0, `cargo build`) programs were **run end-to-end** against a local mock of the KSM protocol: per-request transmission keys wrapped with an EC P-256 server key, ECDSA request signatures checked against the device key registered at binding, AES-GCM payloads, a shared folder and folder key, client-side-encrypted records (the mock stores ciphertext only), revision checks on update, and per-record delete results. The SDKs' documented option for a custom server public key (used by isolated deployments) let them talk to the mock; the Go SDK (v1.7.0, `go vet`) only accepts its built-in server keys, so it could not be run against the mock. The C, C++, and PHP programs were run end-to-end through the bridge in section 9.11 (which uses the official Python SDK). The Java (`com.keepersecurity.secrets-manager:core` 17.4.0) and .NET (`Keeper.SecretsManager` 17.1.2) programs were checked against the SDK sources; Swift was not compiled (no toolchain). No call was made to a real Keeper account. Section 12 provides an optional live test.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Authenticate: applications, devices, and configurations](#2-authenticate-applications-devices-and-configurations)
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
| Go | `github.com/keeper-security/secrets-manager-go/core` | SDK | `go vet` (mock unsupported, see above) |
| Rust | `keeper-secrets-manager-core` (blocking) | SDK | `cargo build`, mock run |
| PHP | none | `ksm_bridge.py` (official Python SDK) over pipes | `php -l`, mock run |
| C# | `Keeper.SecretsManager` | SDK | source check |
| Java | `com.keepersecurity.secrets-manager:core` (Kotlin) | SDK | source check |
| Swift | none | `ksm_bridge.py` over pipes | not compiled |
| Python | `keeper-secrets-manager-core` | SDK | mock run |
| TypeScript | `@keeper-security/secrets-manager-core` | SDK | `tsc --strict`, mock run |
| C++ | none | `ksm_bridge.py` over pipes | `-Werror`, mock run |
| C | none | `ksm_bridge.py` over pipes | `-Werror`, mock run |

Keeper also ships Ruby and PowerShell clients. **Why not plain HTTP:** Keeper's servers hold only ciphertext. A request carries a fresh 256-bit transmission key wrapped to Keeper's public key, an AES-GCM-encrypted body, and an ECDSA signature by the device key; responses are encrypted with the transmission key; records are encrypted with record keys, which are wrapped by shared-folder keys and the application key. Re-implementing that is custom cryptography; use an SDK, or for languages without one, a small process that runs an official SDK (section 9.11).

Every program follows the same contract:

- Environment: `KSM_CONFIG_FILE` (path to a `0600` file holding the device configuration as JSON or base64 JSON), `KSM_FOLDER_UID` (a shared folder the application can edit), and `SECRET_TITLE` (for example `CRUD_CHECK`). Bridge-based programs also need `KSM_BRIDGE` (path to `ksm_bridge.py`) and optionally `KSM_PYTHON`.
- It loads the configuration **into memory** (so the SDK never rewrites the file), **creates** a `login` record with a `password` field (refusing if a record with that title already exists, because titles are not unique), **reads** it by UID and compares in constant time, **updates** it with the record's revision, reads and compares again, then **deletes** it and checks the per-record result.
- It prints titles and UIDs only.

For CLI snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
ksm version
FOLDER_UID='REPLACE_WITH_SHARED_FOLDER_UID'
```

## 2. Authenticate: applications, devices, and configurations

### Model

- A **Secrets Manager application** is created in the Keeper Vault or with Commander and given access to **shared folders** (and individual records), each **read-only** or **can edit**.
- A **client device** is added to the application, which yields a **One-Time Access Token** (`US:…`, `EU:…`, and so on). The SDK redeems it once: it generates an EC P-256 device key pair, authenticates with an HMAC-SHA512 hash of the token, registers the public key, and receives the application key wrapped with the token. "The token is consumed on first use, including on failed attempts." [S02] [S03]
- The resulting **configuration** (`clientId`, `privateKey`, `appKey`, `appOwnerPublicKey`, `serverPublicKeyId`, `hostname`) is the long-term credential. Anyone holding it can read and decrypt everything shared with the application. Store it in the platform's secret store or OS keychain, never in source control or images.
- **IP lock** is on by default: the first IP address that connects is bound to the device. Disable it (`--unlock-ip` in Commander) only for environments with dynamic egress IPs. [S11]
- **Revocation:** each configuration maps to one device; revoke a leaked one by its client ID (vault UI, or Commander `secrets-manager client revoke --client <ClientID>` as documented) without re-keying records. [S11]

### Create a configuration without displaying it

```bash
# Redeem a one-time token into a private configuration file. The token is consumed even on failure.
# The SDK reads the token from a file, so it never appears on a command line.
python3 -I - <<'PY'
import os
from keeper_secrets_manager_core import SecretsManager
from keeper_secrets_manager_core.storage import FileKeyValueStorage
os.umask(0o077)
sm = SecretsManager(token=open("/secure/path/one-time-token").read().strip(),
                    config=FileKeyValueStorage("/secure/path/ksm-config.json"))
sm.get_secrets()  # completes binding
print("bound")
PY
rm -f /secure/path/one-time-token
```

CLI alternatives: `ksm init default --plain <TOKEN> > config.json` prints the configuration (base64 JSON without `--plain`), `ksm init k8s <TOKEN>` prints it as a Kubernetes Secret, and `ksm profile init` writes a CLI profile (`keeper.ini`). They take the token as an argument, so run them only on a single-user workstation, and redirect output straight into a protected file.

### Required permissions

- **Readers:** application with **read-only** access to exactly the shared folders a workload needs.
- **Writers:** a separate application with **can edit** on the target shared folder. Creating requires edit permission for both you and the application, and the folder must already contain at least one record (the SDK discovers the folder key from records it can see). [S03]
- One application per workload per environment; one device (configuration) per running instance or deployment target.

## 3. Data model and addressing

- **Records** have a 22-character URL-safe **UID**, a **type** (`login`, `databaseCredentials`, `serverCredentials`, …), a **title**, **standard fields** (`login`, `password`, `url`, `oneTimeCode`, …), **custom fields** (labeled), notes, and files. Titles are **not unique**.
- **Shared folders** carry folder keys; records inside them are encrypted with record keys wrapped by the folder key.
- **Revision:** every record has a revision number. Updates send it, and the server rejects an update whose revision is stale ("consecutive updates to an already updated record will fail" until you reload). This is KSM's optimistic-concurrency control. [S03]
- **Notation:** `keeper://<UID>/field/password` (or `custom_field/<label>`, `file/<name>`) addresses a single value; SDKs expose `get_notation`, and integrations use it in templates. [S10]
- **Transactions:** an update can be saved as a `rotation` transaction and later committed or rolled back with `complete_transaction(uid, rollback)`, so a failed rotation at the target does not leave a mismatched value in the vault. [S03]

Inventory without values:

```bash
ksm secret list --json | jq '[.[] | {uid, title, record_type}]'
```

(`ksm secret list` without `-v/--show-value` does not print field values.)

## 4. Safe secret handling

- **Command lines:** `ksm secret update --uid … --field password=VALUE` and `ksm secret add field … "password=VALUE"` put values in shell history and the process table. Create from a template file (`ksm secret add file --sf <folder> -f record.json`) or use an SDK; for updates, prefer an SDK. [S09]
- **Output:** `ksm secret get -f <field>` and `--json` unmask values; redirect to protected files only.
- **Configuration = credential:** treat the config file (or `KSM_CONFIG` base64 environment variable that SDKs and integrations accept) like a private key; prefer a mounted file over an environment variable.
- **Caches:** the Python `KSMCache.caching_post_function` (and equivalents) stores encrypted responses on disk to survive outages; know where the cache lives and protect it. [S03]
- **Logging:** SDK exceptions carry server error codes (for example `throttled`, revision mismatch); keep SDK debug logging off in production because debug logs can include record titles and request metadata.
- **Memory:** wipe buffers where possible (`zeroize`, `OPENSSL_cleanse`); the bridge exchanges values over pipes, never argv or environment variables.

## 5. Create secrets

SDK: `create_secret(folder_uid, RecordCreate)` (Python), `createSecret(options, folderUid, recordData)` (JS/Java/.NET), `CreateSecretWithRecordData("", folderUid, record)` (Go), `create_secret(folder_uid, RecordCreate)` (Rust). The SDK generates the record UID and key, encrypts the data, wraps the record key to the application owner's public key and to the folder key, and calls `create_secret`. Create is create-only by UID, but titles can repeat — check `get_secrets_by_title` first. [S03]

```bash
# From a template file (values live in the file, not argv); delete the file afterwards.
ksm secret template record login -o json -f /secure/path/new-login.json   # edit: title, fields[].value
ksm secret add file --sf "$FOLDER_UID" -f /secure/path/new-login.json
rm -f /secure/path/new-login.json
```

## 6. Read secrets

SDK: `get_secrets([uids])` returns decrypted records (all shared records if no filter); `get_secrets_by_title(title)`; `get_notation("keeper://UID/field/password")`. Field helpers: `record.get_standard_field_value("password", single=True)` (Python), `record.getPassword()` (Java), `record.Password()` (Go), `record.FieldValue("password")` (.NET). [S03]

```bash
# One value to a new private file
ksm secret get -u "$RECORD_UID" -f password > ./partner-api-token.secret
```

## 7. Update secrets

SDK: read the record, change the field, then `save(record)` / `updateSecret(options, record)` / `Save(record)`. The update carries the record's **revision**; a stale revision is rejected, so reload after each update and retry the read-modify-write on conflict. For credential rotation, save with transaction type `rotation`, change the credential at the target, then `complete_transaction(uid, rollback=not success)`. [S03]

```bash
# CLI update puts the value in argv: single-user host, history disabled, or use an SDK instead.
ksm secret update --uid "$RECORD_UID" --field "password=$(cat /secure/path/new-token.txt)"
ksm secret get -u "$RECORD_UID" -f password | cmp -s - <(tr -d '\n' < /secure/path/new-token.txt) &&
  printf 'Secret replacement verified.\n'
```

Storing a new value does not rotate the credential at its source; use the rotation transaction above or Keeper's rotation features.

## 8. Delete and recover

SDK: `delete_secret([uids])` returns per-record results (`recordUid`, `responseCode` — `"ok"` on success — and `errorMessage`); Go returns a `map[uid]status`; Rust returns the UIDs that were deleted; the .NET `DeleteSecret` returns nothing, so confirm by reading back. [S03]

```bash
ksm secret delete -u "$RECORD_UID"
```

In the Keeper Vault, deleted records move to **Deleted Items**, from which a vault user can restore them until the trash is emptied; confirm this matches your tenant's policy before relying on it for records deleted through KSM. Deleting a stored credential does not revoke it at its issuer.

## 9. Language implementations

Expected output for every program (UIDs vary):

```text
created: CRUD_CHECK uid 3f1cQ…
updated: CRUD_CHECK
deleted: 3f1cQ…
```

### 9.1 Go

`go get github.com/keeper-security/secrets-manager-go/core@v1.7.0`. `NewMemoryKeyValueStorage(string)` accepts JSON or base64 JSON.

```go
// Keeper Secrets Manager CRUD with the official Go SDK (github.com/keeper-security/secrets-manager-go/core).
// Auth: a KSM device configuration (JSON or base64 JSON, created once from a One-Time Access Token) read from
// KSM_CONFIG_FILE. Records are encrypted and decrypted client-side.
package main

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"fmt"
	"log"
	"os"

	ksm "github.com/keeper-security/secrets-manager-go/core"
)

type Store struct {
	sm        *ksm.SecretsManager
	folderUID string
}

// NewStore builds an in-memory configuration from the file contents, so the SDK never rewrites the file.
func NewStore(configJSON, folderUID string) *Store {
	sm := ksm.NewSecretsManager(&ksm.ClientOptions{Config: ksm.NewMemoryKeyValueStorage(configJSON)})
	return &Store{sm: sm, folderUID: folderUID}
}

// FindUID resolves a title to a UID only if exactly one record has it (titles are not unique).
func (s *Store) FindUID(title string) (string, error) {
	records, err := s.sm.GetSecretsByTitle(title)
	if err != nil {
		return "", err
	}
	switch len(records) {
	case 0:
		return "", nil
	case 1:
		return records[0].Uid, nil
	default:
		return "", fmt.Errorf("%d records share the title %s; address them by UID", len(records), title)
	}
}

// Create refuses an existing title, then creates a login record in the shared folder.
func (s *Store) Create(title, value string) (string, error) {
	existing, err := s.FindUID(title)
	if err != nil {
		return "", err
	}
	if existing != "" {
		return "", fmt.Errorf("a record titled %s already exists", title)
	}
	rc := ksm.NewRecordCreate("login", title)
	rc.Fields = append(rc.Fields, ksm.NewPassword(value))
	return s.sm.CreateSecretWithRecordData("", s.folderUID, rc)
}

func (s *Store) get(uid string) (*ksm.Record, error) {
	records, err := s.sm.GetSecrets([]string{uid})
	if err != nil {
		return nil, err
	}
	if len(records) != 1 {
		return nil, fmt.Errorf("record %s not found or not shared with this application", uid)
	}
	return records[0], nil
}

func (s *Store) Read(uid string) (string, error) {
	r, err := s.get(uid)
	if err != nil {
		return "", err
	}
	return r.Password(), nil
}

// Update is read-modify-write: the record's revision travels with Save, so a concurrent change is rejected.
func (s *Store) Update(uid, value string) error {
	r, err := s.get(uid)
	if err != nil {
		return err
	}
	r.SetPassword(value)
	return s.sm.Save(r)
}

// Delete checks the per-record status map ("ok" on success).
func (s *Store) Delete(uid string) error {
	statuses, err := s.sm.DeleteSecrets([]string{uid})
	if err != nil {
		return err
	}
	if st := statuses[uid]; st != "ok" {
		return fmt.Errorf("delete failed for %s: %q", uid, st)
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
	title, folderUID := os.Getenv("SECRET_TITLE"), os.Getenv("KSM_FOLDER_UID")
	if title == "" || folderUID == "" {
		log.Fatal("set SECRET_TITLE, KSM_FOLDER_UID, KSM_CONFIG_FILE")
	}
	raw, err := os.ReadFile(os.Getenv("KSM_CONFIG_FILE"))
	if err != nil {
		log.Fatal("read config file: ", err)
	}
	store := NewStore(string(raw), folderUID)
	clear(raw)

	v1 := randomValue()
	uid, err := store.Create(title, v1)
	if err != nil {
		log.Fatal("create: ", err)
	}
	fmt.Printf("created: %s uid %s\n", title, uid)
	if got, err := store.Read(uid); err != nil || !equal(got, v1) {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	if err := store.Update(uid, v2); err != nil {
		log.Fatal("update: ", err)
	}
	if got, err := store.Read(uid); err != nil || !equal(got, v2) {
		log.Fatal("read-back after update failed: ", err)
	}
	fmt.Println("updated:", title)

	if err := store.Delete(uid); err != nil {
		log.Fatal("delete: ", err)
	}
	fmt.Println("deleted:", uid)
}
```

### 9.2 Rust

`Cargo.toml` (the crate's default features include a blocking HTTP client):

```toml
[package]
name = "keeper-ksm-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
keeper-secrets-manager-core = "17.3.0"
getrandom = "0.3"
base64 = "0.22"
subtle = "2"
zeroize = "1"
serde_json = "1"
```

```rust
//! Keeper Secrets Manager CRUD with the official Rust SDK (`keeper-secrets-manager-core`, blocking API).
//! Auth: a KSM device configuration (JSON or base64 JSON, created once from a One-Time Access Token) read from
//! KSM_CONFIG_FILE. Records are encrypted and decrypted client-side.
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use keeper_secrets_manager_core::{
    core::{ClientOptions, SecretsManager},
    custom_error::KSMRError,
    dto::{dtos::RecordCreate, field_structs::Password},
    storage::InMemoryKeyValueStorage,
};
use serde_json::Value;
use std::{env, error::Error};
use subtle::ConstantTimeEq;
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error>>;

struct KeeperStore {
    sm: SecretsManager,
    folder_uid: String,
}

impl KeeperStore {
    /// In-memory storage built from the config; the SDK never rewrites the file.
    fn new(config_json: String, folder_uid: String) -> Result<Self, KSMRError> {
        let storage = InMemoryKeyValueStorage::new_config_storage(Some(config_json))?;
        let sm = SecretsManager::new(ClientOptions::new_client_options(storage))?;
        Ok(Self { sm, folder_uid })
    }

    /// Titles are not unique in Keeper; resolve a title to a UID only if exactly one record has it.
    fn find_uid(&mut self, title: &str) -> Res<Option<String>> {
        let matches = self.sm.get_secrets_by_title(title)?;
        match matches.len() {
            0 => Ok(None),
            1 => Ok(Some(matches[0].uid.clone())),
            n => Err(format!("{n} records share the title {title}; address them by UID").into()),
        }
    }

    /// Refuses an existing title, then creates a login record in the shared folder. Returns the record UID.
    fn create(&mut self, title: &str, value: &str) -> Res<String> {
        if self.find_uid(title)?.is_some() {
            return Err(format!("a record titled {title} already exists").into());
        }
        let mut record = RecordCreate::new("login", title, None);
        record.append_standard_fields(Password::new(value.to_string(), None, None, None, None, None)?);
        Ok(self.sm.create_secret(self.folder_uid.clone(), record)?)
    }

    fn read(&mut self, uid: &str) -> Res<Zeroizing<String>> {
        let records = self.sm.get_secrets(vec![uid.to_string()])?;
        let record = records.first().ok_or("record not found or not shared with this application")?;
        match record.get_standard_field_value("password", true)? {
            Value::String(s) => Ok(Zeroizing::new(s)),
            _ => Err("password field is not a string".into()),
        }
    }

    /// Read-modify-write: the record's revision travels with `save`, so a concurrent change is rejected.
    fn update(&mut self, uid: &str, value: &str) -> Res<()> {
        let mut record = self
            .sm
            .get_secrets(vec![uid.to_string()])?
            .into_iter()
            .next()
            .ok_or("record not found or not shared with this application")?;
        record.set_standard_field_value_mut("password", Value::String(value.to_string()))?;
        self.sm.save(record, None)?;
        Ok(())
    }

    /// `delete_secret` returns the UIDs that were deleted (comma-separated); anything else failed.
    fn delete(&mut self, uid: &str) -> Res<()> {
        let deleted = self.sm.delete_secret(vec![uid.to_string()])?;
        if !deleted.split(", ").any(|d| d.trim_matches('"') == uid) {
            return Err(format!("delete failed for {uid}").into());
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

fn main() -> Res<()> {
    let title = need("SECRET_TITLE")?;
    let config = Zeroizing::new(std::fs::read_to_string(need("KSM_CONFIG_FILE")?)?);
    let mut store = KeeperStore::new(config.to_string(), need("KSM_FOLDER_UID")?)?;

    let v1 = random_value()?;
    let uid = store.create(&title, &v1)?;
    println!("created: {title} uid {uid}");
    if !same(&v1, &store.read(&uid)?) {
        return Err("read-back after create did not match".into());
    }

    let v2 = random_value()?;
    store.update(&uid, &v2)?;
    if !same(&v2, &store.read(&uid)?) {
        return Err("read-back after update did not match".into());
    }
    println!("updated: {title}");

    store.delete(&uid)?;
    println!("deleted: {uid}");
    Ok(())
}
```

### 9.3 PHP

No official PHP SDK; the program spawns `ksm_bridge.py` (section 9.11) with `proc_open` in array form (no shell) and exchanges JSON lines.

```php
<?php
// Keeper Secrets Manager CRUD in PHP. Keeper ships no PHP SDK and the protocol is end-to-end encrypted, so this
// program drives the official Python SDK through ksm_bridge.py (JSON lines over pipes; values never touch argv,
// the environment, or disk).
// Environment: KSM_CONFIG_FILE (read by the bridge), KSM_FOLDER_UID, SECRET_TITLE, KSM_BRIDGE, optional KSM_PYTHON.
declare(strict_types=1);

final class KsmBridge
{
    /** @var resource */
    private $proc;
    /** @var array<int, resource> */
    private array $pipes;

    public function __construct(string $python, string $script)
    {
        // Array form: no shell is involved; stderr is inherited for diagnostics.
        $proc = proc_open([$python, '-I', $script], [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => STDERR], $pipes);
        if (!is_resource($proc)) {
            throw new RuntimeException('cannot start bridge');
        }
        $this->proc = $proc;
        $this->pipes = $pipes;
    }

    public function call(string $op, #[\SensitiveParameter] array $req): array
    {
        $req['op'] = $op;
        fwrite($this->pipes[0], json_encode($req, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES) . "\n");
        fflush($this->pipes[0]);
        $line = fgets($this->pipes[1]);
        $resp = $line === false ? null : json_decode($line, true);
        if (!is_array($resp) || ($resp['ok'] ?? false) !== true) {
            throw new RuntimeException("$op failed: " . ($resp['error'] ?? 'bridge unavailable'));
        }
        return $resp;
    }

    public function __destruct()
    {
        fclose($this->pipes[0]); // EOF ends the bridge's read loop
        fclose($this->pipes[1]);
        proc_close($this->proc);
    }
}

final class KeeperStore
{
    public function __construct(private KsmBridge $bridge, private string $folderUid)
    {
    }

    /** Titles are not unique in Keeper; refuse to create a second record with the same title. */
    public function create(string $title, #[\SensitiveParameter] string $value): string
    {
        if ($this->bridge->call('find', ['title' => $title])['uids'] !== []) {
            throw new RuntimeException("a record titled $title already exists");
        }
        return $this->bridge->call('create', ['folderUid' => $this->folderUid, 'title' => $title, 'value' => $value])['uid'];
    }

    public function read(string $uid): string
    {
        return $this->bridge->call('read', ['uid' => $uid])['value'];
    }

    /** The bridge saves with the record's revision, so a concurrent change is rejected. */
    public function update(string $uid, #[\SensitiveParameter] string $value): void
    {
        $this->bridge->call('update', ['uid' => $uid, 'value' => $value]);
    }

    public function delete(string $uid): void
    {
        $this->bridge->call('delete', ['uid' => $uid]);
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

$title = env_or_fail('SECRET_TITLE');
env_or_fail('KSM_CONFIG_FILE');
try {
    $bridge = new KsmBridge(getenv('KSM_PYTHON') ?: 'python3', env_or_fail('KSM_BRIDGE'));
    $store = new KeeperStore($bridge, env_or_fail('KSM_FOLDER_UID'));

    $v1 = random_value();
    $uid = $store->create($title, $v1);
    echo "created: $title uid $uid\n";
    if (!hash_equals($v1, $store->read($uid))) {
        throw new RuntimeException('read-back after create did not match');
    }

    $v2 = random_value();
    $store->update($uid, $v2);
    if (!hash_equals($v2, $store->read($uid))) {
        throw new RuntimeException('read-back after update did not match');
    }
    echo "updated: $title\n";

    $store->delete($uid);
    echo "deleted: $uid\n";
} catch (Throwable $e) {
    fwrite(STDERR, get_class($e) . ': ' . $e->getMessage() . "\n");
    exit(1);
} finally {
    unset($v1, $v2);
}
```

### 9.4 C#

`dotnet add package Keeper.SecretsManager --version 17.1.2` (namespace `SecretsManager`, static `SecretsManagerClient`). `UpdateFieldValue` silently ignores a missing field and `DeleteSecret` discards per-record results, so the program checks both explicitly.

```csharp
// Keeper Secrets Manager CRUD with the official .NET SDK (dotnet add package Keeper.SecretsManager --version 17.1.2).
// Auth: a KSM device configuration (JSON or base64 JSON, created once from a One-Time Access Token) read from
// KSM_CONFIG_FILE. Records are encrypted and decrypted client-side.
using System.Security.Cryptography;
using System.Text;
using SecretsManager;

public sealed class KeeperStore
{
    private readonly SecretsManagerOptions _options;
    private readonly string _folderUid;

    public KeeperStore(string configJson, string folderUid)
    {
        // In-memory storage built from the config; the SDK never rewrites the file.
        _options = new SecretsManagerOptions(new InMemoryStorage(configJson));
        _folderUid = folderUid;
    }

    /// <summary>Titles are not unique in Keeper; resolve a title to a UID only if exactly one record has it.</summary>
    public async Task<string?> FindUidAsync(string title)
    {
        var matches = (await SecretsManagerClient.GetSecretsByTitle(_options, title)).ToArray();
        if (matches.Length > 1) throw new InvalidOperationException($"{matches.Length} records share the title {title}");
        return matches.Length == 1 ? matches[0].RecordUid : null;
    }

    /// <summary>Refuses an existing title, then creates a login record in the shared folder.</summary>
    public async Task<string> CreateAsync(string title, string value)
    {
        if (await FindUidAsync(title) is not null) throw new InvalidOperationException($"a record titled {title} already exists");
        var data = new KeeperRecordData
        {
            title = title,
            type = "login",
            fields = new[] { new KeeperRecordField { type = "password", value = new object[] { value } } },
        };
        return await SecretsManagerClient.CreateSecret(_options, _folderUid, data);
    }

    private async Task<KeeperRecord> GetAsync(string uid)
    {
        var records = (await SecretsManagerClient.GetSecrets(_options, new[] { uid })).Records;
        if (records.Length != 1) throw new InvalidOperationException($"record {uid} not found or not shared with this application");
        return records[0];
    }

    public async Task<string> ReadAsync(string uid) =>
        (await GetAsync(uid)).FieldValue("password")?.ToString() ?? throw new InvalidOperationException("no password field");

    /// <summary>Read-modify-write: the revision travels with the update, so a concurrent change is rejected.
    /// UpdateFieldValue silently ignores a missing field, so check for it first.</summary>
    public async Task UpdateAsync(string uid, string value)
    {
        var record = await GetAsync(uid);
        if (record.FieldValue("password") is null) throw new InvalidOperationException("no password field");
        record.UpdateFieldValue("password", value);
        await SecretsManagerClient.UpdateSecret(_options, record);
    }

    /// <summary>The .NET DeleteSecret discards per-record results, so confirm the record is gone.</summary>
    public async Task DeleteAsync(string uid)
    {
        await SecretsManagerClient.DeleteSecret(_options, new[] { uid });
        var left = (await SecretsManagerClient.GetSecrets(_options, new[] { uid })).Records;
        if (left.Length != 0) throw new InvalidOperationException($"delete failed for {uid}");
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
            var title = Need("SECRET_TITLE");
            var store = new KeeperStore(await File.ReadAllTextAsync(Need("KSM_CONFIG_FILE")), Need("KSM_FOLDER_UID"));

            var v1 = RandomValue();
            var uid = await store.CreateAsync(title, v1);
            Console.WriteLine($"created: {title} uid {uid}");
            if (!Same(v1, await store.ReadAsync(uid))) throw new InvalidOperationException("read-back after create did not match");

            var v2 = RandomValue();
            await store.UpdateAsync(uid, v2);
            if (!Same(v2, await store.ReadAsync(uid))) throw new InvalidOperationException("read-back after update did not match");
            Console.WriteLine($"updated: {title}");

            await store.DeleteAsync(uid);
            Console.WriteLine($"deleted: {uid}");
            return 0;
        }
        catch (Exception e)   // SDK exception messages carry server error codes, not record data
        {
            Console.Error.WriteLine($"{e.GetType().Name}: {e.Message}");
            return 1;
        }
    }
}
```

### 9.5 Java

`com.keepersecurity.secrets-manager:core:17.4.0`. The Kotlin top-level functions are static methods on `SecretsManager`; `SecretsManagerOptions` also takes connect/read timeouts.

```java
// Keeper Secrets Manager CRUD with the official Java/Kotlin SDK.
// Maven/Gradle: com.keepersecurity.secrets-manager:core:17.4.0 (Java 8+; Kotlin functions are exposed as
// static methods on com.keepersecurity.secretsManager.core.SecretsManager).
// Auth: a KSM device configuration (JSON or base64 JSON, created once from a One-Time Access Token) read from
// KSM_CONFIG_FILE. Records are encrypted and decrypted client-side.
package example;

import com.keepersecurity.secretsManager.core.InMemoryStorage;
import com.keepersecurity.secretsManager.core.KeeperRecord;
import com.keepersecurity.secretsManager.core.KeeperRecordData;
import com.keepersecurity.secretsManager.core.KeeperRecordField;
import com.keepersecurity.secretsManager.core.Password;
import com.keepersecurity.secretsManager.core.SecretsManager;
import com.keepersecurity.secretsManager.core.SecretsManagerDeleteResponseRecord;
import com.keepersecurity.secretsManager.core.SecretsManagerOptions;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.List;

public final class KeeperCrud {
    private final SecretsManagerOptions options;
    private final String folderUid;

    KeeperCrud(String configJson, String folderUid) {
        // In-memory storage built from the config; the SDK never rewrites the file.
        this.options = new SecretsManagerOptions(new InMemoryStorage(configJson));
        this.folderUid = folderUid;
    }

    /** Titles are not unique in Keeper; resolve a title to a UID only if exactly one record has it. */
    String findUid(String title) {
        List<KeeperRecord> matches = SecretsManager.getSecrets(options).getSecretsByTitle(title);
        if (matches.size() > 1) throw new IllegalStateException(matches.size() + " records share the title " + title);
        return matches.isEmpty() ? null : matches.get(0).getRecordUid();
    }

    /** Refuses an existing title, then creates a login record in the shared folder. Returns the record UID. */
    String create(String title, String value) {
        if (findUid(title) != null) throw new IllegalStateException("a record titled " + title + " already exists");
        List<KeeperRecordField> fields = new ArrayList<>();
        fields.add(new Password(value));
        return SecretsManager.createSecret(options, folderUid, new KeeperRecordData(title, "login", fields));
    }

    private KeeperRecord get(String uid) {
        List<KeeperRecord> records = SecretsManager.getSecrets(options, Collections.singletonList(uid)).getRecords();
        if (records.size() != 1) throw new IllegalStateException("record " + uid + " not found or not shared with this application");
        return records.get(0);
    }

    String read(String uid) {
        return get(uid).getPassword();
    }

    /** Read-modify-write: the record's revision travels with the update, so a concurrent change is rejected. */
    void update(String uid, String value) {
        KeeperRecord record = get(uid);
        record.updatePassword(value);
        SecretsManager.updateSecret(options, record);
    }

    /** deleteSecret returns per-record results; check them. */
    void delete(String uid) {
        for (SecretsManagerDeleteResponseRecord r : SecretsManager.deleteSecret(options, Collections.singletonList(uid)).getRecords()) {
            if (!"ok".equals(r.getResponseCode())) {
                throw new IllegalStateException("delete failed for " + r.getRecordUid() + ": " + r.getResponseCode());
            }
        }
    }

    private static final SecureRandom RNG = new SecureRandom();

    static String randomValue() {
        byte[] b = new byte[32];
        RNG.nextBytes(b);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(b);
    }

    static boolean same(String a, String b) {
        return b != null && MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }

    private static String need(String k) {
        String v = System.getenv(k);
        if (v == null || v.isEmpty()) throw new IllegalStateException("set " + k);
        return v;
    }

    public static void main(String[] args) {
        try {
            String title = need("SECRET_TITLE");
            String config = new String(Files.readAllBytes(Path.of(need("KSM_CONFIG_FILE"))), StandardCharsets.UTF_8);
            KeeperCrud store = new KeeperCrud(config, need("KSM_FOLDER_UID"));

            String v1 = randomValue();
            String uid = store.create(title, v1);
            System.out.println("created: " + title + " uid " + uid);
            if (!same(v1, store.read(uid))) throw new IllegalStateException("read-back after create did not match");

            String v2 = randomValue();
            store.update(uid, v2);
            if (!same(v2, store.read(uid))) throw new IllegalStateException("read-back after update did not match");
            System.out.println("updated: " + title);

            store.delete(uid);
            System.out.println("deleted: " + uid);
        } catch (Exception e) {
            // SecretsManagerException messages carry server error codes, not record data
            System.err.println(e.getClass().getSimpleName() + ": " + e.getMessage());
            System.exit(1);
        }
    }
}
```

### 9.6 Swift

No official Swift SDK; the program drives `ksm_bridge.py` through `Process` and pipes. Server-side only.

`Package.swift`:

```swift
// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SecretsCrud",
    platforms: [.macOS(.v13)],
    targets: [
        // Foundation only (Process + Pipe + JSONSerialization); talks to ksm_bridge.py.
        .executableTarget(name: "SecretsCrud"),
    ]
)
```

```swift
// Keeper Secrets Manager CRUD in Swift. Keeper ships no Swift SDK and the protocol is end-to-end encrypted, so
// this program drives the official Python SDK through ksm_bridge.py (JSON lines over pipes; values never touch
// argv, the environment, or disk). Server-side use only.
// Environment: KSM_CONFIG_FILE (read by the bridge), KSM_FOLDER_UID, SECRET_TITLE, KSM_BRIDGE, optional KSM_PYTHON.
import Foundation
#if canImport(Security)
import Security
#endif

enum KeeperError: Error, CustomStringConvertible {
    case bridge(op: String, message: String)   // class + message from the SDK, never record data
    case config(String)
    var description: String {
        switch self {
        case let .bridge(op, message): return "\(op) failed: \(message)"
        case let .config(m): return m
        }
    }
}

final class KsmBridge {
    private let process = Process()
    private let toBridge = Pipe(), fromBridge = Pipe()
    private var buffer = Data()

    init(python: String, script: String) throws {
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [python, "-I", script]   // no shell involved
        process.standardInput = toBridge
        process.standardOutput = fromBridge
        try process.run()
    }

    deinit {
        try? toBridge.fileHandleForWriting.close()   // EOF ends the bridge's read loop
        process.waitUntilExit()
    }

    func call(_ op: String, _ request: [String: Any]) throws -> [String: Any] {
        var req = request
        req["op"] = op
        var line = try JSONSerialization.data(withJSONObject: req)
        line.append(0x0A)
        try toBridge.fileHandleForWriting.write(contentsOf: line)
        line.resetBytes(in: 0..<line.count)
        while !buffer.contains(0x0A) {
            guard let chunk = try fromBridge.fileHandleForReading.read(upToCount: 4096), !chunk.isEmpty else {
                throw KeeperError.bridge(op: op, message: "bridge unavailable")
            }
            buffer.append(chunk)
        }
        let end = buffer.firstIndex(of: 0x0A)!
        let response = buffer.subdata(in: buffer.startIndex..<end)
        buffer.resetBytes(in: buffer.startIndex..<(end + 1))
        buffer.removeSubrange(buffer.startIndex...end)
        guard let obj = try JSONSerialization.jsonObject(with: response) as? [String: Any], obj["ok"] as? Bool == true else {
            let msg = ((try? JSONSerialization.jsonObject(with: response)) as? [String: Any])?["error"] as? String
            throw KeeperError.bridge(op: op, message: msg ?? "invalid response")
        }
        return obj
    }
}

final class KeeperStore {
    private let bridge: KsmBridge
    private let folderUID: String

    init(bridge: KsmBridge, folderUID: String) {
        self.bridge = bridge
        self.folderUID = folderUID
    }

    /// Titles are not unique in Keeper; refuse to create a second record with the same title.
    func create(_ title: String, _ value: String) throws -> String {
        let found = try bridge.call("find", ["title": title])
        guard (found["uids"] as? [String] ?? []).isEmpty else { throw KeeperError.config("a record titled \(title) already exists") }
        guard let uid = try bridge.call("create", ["folderUid": folderUID, "title": title, "value": value])["uid"] as? String else {
            throw KeeperError.config("create: no uid in response")
        }
        return uid
    }

    func read(_ uid: String) throws -> String {
        guard let v = try bridge.call("read", ["uid": uid])["value"] as? String else { throw KeeperError.config("read: no value") }
        return v
    }

    /// The bridge saves with the record's revision, so a concurrent change is rejected.
    func update(_ uid: String, _ value: String) throws { _ = try bridge.call("update", ["uid": uid, "value": value]) }

    func delete(_ uid: String) throws { _ = try bridge.call("delete", ["uid": uid]) }
}

func randomValue() throws -> String {
    var bytes = [UInt8](repeating: 0, count: 32)
    #if canImport(Security)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
        throw KeeperError.config("csprng failure")
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
    guard let v = ProcessInfo.processInfo.environment[k], !v.isEmpty else { throw KeeperError.config("set \(k)") }
    return v
}

do {
    let title = try need("SECRET_TITLE")
    _ = try need("KSM_CONFIG_FILE")
    let bridge = try KsmBridge(python: ProcessInfo.processInfo.environment["KSM_PYTHON"] ?? "python3",
                               script: try need("KSM_BRIDGE"))
    let store = KeeperStore(bridge: bridge, folderUID: try need("KSM_FOLDER_UID"))

    let v1 = try randomValue()
    let uid = try store.create(title, v1)
    print("created: \(title) uid \(uid)")
    guard same(v1, try store.read(uid)) else { throw KeeperError.config("read-back after create did not match") }

    let v2 = try randomValue()
    try store.update(uid, v2)
    guard same(v2, try store.read(uid)) else { throw KeeperError.config("read-back after update did not match") }
    print("updated: \(title)")

    try store.delete(uid)
    print("deleted: \(uid)")
} catch {
    FileHandle.standardError.write("\(error)\n".data(using: .utf8)!)
    exit(1)
}
```

### 9.7 Python

`pip install keeper-secrets-manager-core==17.3.0`. `InMemoryKeyValueStorage` accepts the JSON or base64 configuration string.

```python
"""Keeper Secrets Manager (KSM) CRUD with the official Python SDK.

pip install keeper-secrets-manager-core==17.3.0
Auth: a KSM device configuration (JSON produced once from a One-Time Access Token, see section 2) read from
KSM_CONFIG_FILE. Records are encrypted and decrypted client-side; the configuration holds the keys.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys

from keeper_secrets_manager_core import SecretsManager
from keeper_secrets_manager_core.dto.dtos import RecordCreate, RecordField
from keeper_secrets_manager_core.exceptions import KeeperError
from keeper_secrets_manager_core.storage import InMemoryKeyValueStorage


class KeeperStore:
    def __init__(self, config_json: str, folder_uid: str) -> None:
        # In-memory storage: the config file is read once and never rewritten by the SDK.
        self.sm = SecretsManager(config=InMemoryKeyValueStorage(config_json))
        self.folder_uid = folder_uid

    def find_uid(self, title: str) -> str | None:
        """Titles are not unique in Keeper; resolve a title to a UID only if exactly one record has it."""
        matches = self.sm.get_secrets_by_title(title)
        if len(matches) > 1:
            raise KeeperError(f"{len(matches)} records share the title {title}; address them by UID")
        return matches[0].uid if matches else None

    def create(self, title: str, value: str) -> str:
        """Refuses an existing title, then creates a login record in the shared folder. Returns the record UID."""
        if self.find_uid(title) is not None:
            raise KeeperError(f"a record titled {title} already exists")
        record = RecordCreate("login", title)
        record.fields = [RecordField(field_type="password", value=[value])]
        return self.sm.create_secret(self.folder_uid, record)

    def read(self, uid: str) -> str:
        records = self.sm.get_secrets([uid])
        if len(records) != 1:
            raise KeeperError(f"record {uid} not found or not shared with this application")
        return records[0].get_standard_field_value("password", single=True)

    def update(self, uid: str, value: str) -> None:
        """Read-modify-write: the record's revision travels with the update, so a concurrent change is rejected."""
        record = self.sm.get_secrets([uid])[0]
        record.set_standard_field_value("password", value)
        self.sm.save(record)

    def delete(self, uid: str) -> None:
        """delete_secret returns per-record results; check them."""
        for result in self.sm.delete_secret([uid]) or []:
            if result.get("responseCode") != "ok":
                raise KeeperError(f"delete failed for {result.get('recordUid')}: {result.get('responseCode')}")


def main() -> int:
    env = os.environ
    try:
        title, folder_uid = env["SECRET_TITLE"], env["KSM_FOLDER_UID"]
        with open(env["KSM_CONFIG_FILE"], encoding="utf-8") as fh:
            config_json = fh.read()
    except KeyError as missing:
        print(f"set {missing}", file=sys.stderr)
        return 2
    try:
        store = KeeperStore(config_json, folder_uid)
        del config_json

        v1 = secrets.token_urlsafe(32)
        uid = store.create(title, v1)
        print(f"created: {title} uid {uid}")
        if not hmac.compare_digest(v1, store.read(uid)):
            raise KeeperError("read-back after create did not match")

        v2 = secrets.token_urlsafe(32)
        store.update(uid, v2)
        if not hmac.compare_digest(v2, store.read(uid)):
            raise KeeperError("read-back after update did not match")
        print(f"updated: {title}")

        store.delete(uid)
        print(f"deleted: {uid}")
        return 0
    except Exception as exc:  # KeeperError messages carry server error codes, not record data
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

`npm i @keeper-security/secrets-manager-core@17.6.0`. `loadJsonConfig` accepts JSON or base64 JSON; `requestTimeoutMs` bounds each call.

```typescript
// Keeper Secrets Manager CRUD with the official JavaScript SDK (npm i @keeper-security/secrets-manager-core@17.6.0).
// Auth: a KSM device configuration (JSON or base64 JSON, created once from a One-Time Access Token) read from
// KSM_CONFIG_FILE. Records are encrypted and decrypted client-side.
import { readFile } from "node:fs/promises";
import { randomBytes, timingSafeEqual } from "node:crypto";
import {
  createSecret,
  deleteSecret,
  getSecrets,
  getSecretsByTitle,
  loadJsonConfig,
  updateSecret,
  type KeeperRecord,
  type SecretManagerOptions,
} from "@keeper-security/secrets-manager-core";

export class KeeperStore {
  private readonly options: SecretManagerOptions;

  constructor(configJson: string, private readonly folderUid: string) {
    // In-memory storage built from the config; the SDK never rewrites the file. A request timeout is set explicitly.
    this.options = { storage: loadJsonConfig(configJson), requestTimeoutMs: 30_000 };
  }

  /** Titles are not unique in Keeper; resolve a title to a UID only if exactly one record has it. */
  async findUid(title: string): Promise<string | undefined> {
    const matches = await getSecretsByTitle(this.options, title);
    if (matches.length > 1) throw new Error(`${matches.length} records share the title ${title}; address them by UID`);
    return matches[0]?.recordUid;
  }

  /** Refuses an existing title, then creates a login record in the shared folder. Returns the record UID. */
  async create(title: string, value: string): Promise<string> {
    if ((await this.findUid(title)) !== undefined) throw new Error(`a record titled ${title} already exists`);
    return createSecret(this.options, this.folderUid, {
      title,
      type: "login",
      fields: [{ type: "password", value: [value] }],
      custom: [],
    });
  }

  private async get(uid: string): Promise<KeeperRecord> {
    const { records } = await getSecrets(this.options, [uid]);
    if (records.length !== 1) throw new Error(`record ${uid} not found or not shared with this application`);
    return records[0];
  }

  async read(uid: string): Promise<string> {
    const field = (await this.get(uid)).data.fields.find((f: { type: string }) => f.type === "password");
    return field.value[0] as string;
  }

  /** Read-modify-write: the record's revision travels with the update, so a concurrent change is rejected. */
  async update(uid: string, value: string): Promise<void> {
    const record = await this.get(uid);
    record.data.fields.find((f: { type: string }) => f.type === "password").value = [value];
    await updateSecret(this.options, record);
  }

  /** deleteSecret returns per-record results; check them. */
  async delete(uid: string): Promise<void> {
    const { records } = await deleteSecret(this.options, [uid]);
    const failed = records.find((r) => r.responseCode !== "ok");
    if (failed) throw new Error(`delete failed for ${failed.recordUid}: ${failed.responseCode}`);
  }
}

const randomValue = (): string => randomBytes(32).toString("base64url");
const same = (a: string, b: string): boolean => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

async function main(): Promise<void> {
  const { SECRET_TITLE: title, KSM_FOLDER_UID: folderUid, KSM_CONFIG_FILE: configFile } = process.env;
  if (!title || !folderUid || !configFile) throw new Error("set SECRET_TITLE, KSM_FOLDER_UID, KSM_CONFIG_FILE");
  const store = new KeeperStore(await readFile(configFile, "utf8"), folderUid);

  const v1 = randomValue();
  const uid = await store.create(title, v1);
  console.log(`created: ${title} uid ${uid}`);
  if (!same(v1, await store.read(uid))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  await store.update(uid, v2);
  if (!same(v2, await store.read(uid))) throw new Error("read-back after update did not match");
  console.log(`updated: ${title}`);

  await store.delete(uid);
  console.log(`deleted: ${uid}`);
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? `${err.name}: ${err.message}` : "unknown error");
  process.exitCode = 1;
});
```

### 9.9 C++

C++17 + nlohmann/json, driving `ksm_bridge.py` via `posix_spawnp` and pipes.

```cpp
// Keeper Secrets Manager CRUD in C++17. Keeper ships no C++ SDK and the protocol is end-to-end encrypted, so
// this program drives the official Python SDK through ksm_bridge.py (JSON lines over pipes; values never
// touch argv, the environment, or disk).
//   g++ -std=c++17 -O2 main.cpp -o ksm_crud $(pkg-config --cflags --libs openssl)
// Environment: KSM_CONFIG_FILE (read by the bridge), KSM_FOLDER_UID, SECRET_TITLE, KSM_BRIDGE, optional KSM_PYTHON.
#include <nlohmann/json.hpp>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

extern char** environ;
using json = nlohmann::json;

static void wipe(std::string& s) { OPENSSL_cleanse(s.data(), s.size()); s.clear(); }

class KsmBridge {
 public:
  KsmBridge(const std::string& python, const std::string& script) {
    int in[2], out[2];
    if (pipe(in) != 0 || pipe(out) != 0) throw std::runtime_error("pipe failed");
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa, in[0], STDIN_FILENO);
    posix_spawn_file_actions_adddup2(&fa, out[1], STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&fa, in[1]);
    posix_spawn_file_actions_addclose(&fa, out[0]);
    std::string isolated = "-I";
    char* argv[] = {const_cast<char*>(python.c_str()), isolated.data(), const_cast<char*>(script.c_str()), nullptr};
    int rc = posix_spawnp(&pid_, argv[0], &fa, nullptr, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    close(in[0]);
    close(out[1]);
    if (rc != 0) throw std::runtime_error("cannot start bridge");
    to_ = fdopen(in[1], "w");
    from_ = fdopen(out[0], "r");
    if (!to_ || !from_) throw std::runtime_error("fdopen failed");
  }
  ~KsmBridge() {
    if (to_) std::fclose(to_);  // EOF ends the bridge's read loop
    if (from_) std::fclose(from_);
    if (pid_ > 0) waitpid(pid_, nullptr, 0);
  }
  KsmBridge(const KsmBridge&) = delete;
  KsmBridge& operator=(const KsmBridge&) = delete;

  // One request/response; throws with the bridge's error text (class + message, no values).
  json call(const char* op, json req) {
    req["op"] = op;
    std::string line = req.dump() + "\n";
    scrub(req);
    std::fwrite(line.data(), 1, line.size(), to_);
    std::fflush(to_);
    wipe(line);
    char* buf = nullptr;
    size_t cap = 0;
    ssize_t n = getline(&buf, &cap, from_);
    std::string text = n > 0 ? std::string(buf, static_cast<size_t>(n)) : std::string();
    if (buf) { OPENSSL_cleanse(buf, cap); std::free(buf); }
    json resp = json::parse(text, nullptr, false);
    wipe(text);
    if (!resp.is_object() || !resp.value("ok", false)) {
      std::string err = resp.is_object() ? resp.value("error", "unknown error") : "bridge unavailable";
      throw std::runtime_error(std::string(op) + " failed: " + err);
    }
    return resp;
  }

  static void scrub(json& j) {
    if (j.is_string()) wipe(*j.get_ptr<std::string*>());
    else if (j.is_structured()) for (auto& c : j) scrub(c);
  }

 private:
  pid_t pid_ = -1;
  FILE* to_ = nullptr;
  FILE* from_ = nullptr;
};

class KeeperStore {
 public:
  KeeperStore(KsmBridge& bridge, std::string folder_uid) : b_(bridge), folder_(std::move(folder_uid)) {}

  // Titles are not unique in Keeper; refuse to create a second record with the same title.
  std::string create(const std::string& title, const std::string& value) {
    json found = b_.call("find", {{"title", title}});
    if (!found["uids"].empty()) throw std::runtime_error("a record titled " + title + " already exists");
    return b_.call("create", {{"folderUid", folder_}, {"title", title}, {"value", value}})["uid"].get<std::string>();
  }

  std::string read(const std::string& uid) {
    json resp = b_.call("read", {{"uid", uid}});
    std::string v = resp["value"].get<std::string>();
    KsmBridge::scrub(resp);
    return v;
  }

  // The bridge saves with the record's revision, so a concurrent change is rejected.
  void update(const std::string& uid, const std::string& value) { b_.call("update", {{"uid", uid}, {"value", value}}); }

  void remove(const std::string& uid) { b_.call("delete", {{"uid", uid}}); }

 private:
  KsmBridge& b_;
  std::string folder_;
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
  signal(SIGPIPE, SIG_IGN);
  try {
    const std::string title = need("SECRET_TITLE");
    need("KSM_CONFIG_FILE");
    const char* py = std::getenv("KSM_PYTHON");
    KsmBridge bridge(py ? py : "python3", need("KSM_BRIDGE"));
    KeeperStore store(bridge, need("KSM_FOLDER_UID"));

    std::string v1 = random_value();
    std::string uid = store.create(title, v1);
    std::cout << "created: " << title << " uid " << uid << "\n";
    std::string got = store.read(uid);
    if (!same(v1, got)) throw std::runtime_error("read-back after create did not match");
    wipe(got);

    std::string v2 = random_value();
    store.update(uid, v2);
    got = store.read(uid);
    if (!same(v2, got)) throw std::runtime_error("read-back after update did not match");
    std::cout << "updated: " << title << "\n";
    wipe(got); wipe(v1); wipe(v2);

    store.remove(uid);
    std::cout << "deleted: " << uid << "\n";
    return 0;
  } catch (const std::exception& e) {
    std::cerr << e.what() << "\n";
    return 1;
  }
}
```

### 9.10 C

C11 + cJSON + OpenSSL, driving `ksm_bridge.py` via `posix_spawnp` and pipes.

```c
/*
 * Keeper Secrets Manager CRUD in C. Keeper ships no C SDK and the protocol is end-to-end encrypted, so this
 * program drives the official Python SDK through ksm_bridge.py (JSON lines over a pipe; values never touch
 * argv, the environment, or disk).
 *
 *   cc -std=c11 -Wall -Wextra -O2 ksm_crud.c -o ksm_crud $(pkg-config --cflags --libs libcjson openssl)
 *
 * Environment: KSM_CONFIG_FILE (read by the bridge), KSM_FOLDER_UID, SECRET_TITLE,
 *              KSM_BRIDGE (path to ksm_bridge.py), optional KSM_PYTHON (default python3).
 */
#define _POSIX_C_SOURCE 200809L
#include <cjson/cJSON.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static FILE *g_to, *g_from;
static pid_t g_pid;

static void str_wipe_free(char *s) { if (s) { OPENSSL_cleanse(s, strlen(s)); free(s); } }

static void json_wipe(cJSON *n) {
    for (; n; n = n->next) {
        if (cJSON_IsString(n) && n->valuestring) OPENSSL_cleanse(n->valuestring, strlen(n->valuestring));
        if (n->child) json_wipe(n->child);
    }
}

static int bridge_start(void) {
    const char *script = getenv("KSM_BRIDGE"), *py = getenv("KSM_PYTHON");
    if (!script) { fprintf(stderr, "set KSM_BRIDGE\n"); return -1; }
    int in[2], out[2];
    if (pipe(in) || pipe(out)) return -1;
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_adddup2(&fa, in[0], STDIN_FILENO);
    posix_spawn_file_actions_adddup2(&fa, out[1], STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&fa, in[1]);
    posix_spawn_file_actions_addclose(&fa, out[0]);
    char *argv[] = {(char *)(py ? py : "python3"), "-I", (char *)script, NULL};
    int rc = posix_spawnp(&g_pid, argv[0], &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    close(in[0]); close(out[1]);
    if (rc != 0) { close(in[1]); close(out[0]); return -1; }
    g_to = fdopen(in[1], "w");
    g_from = fdopen(out[0], "r");
    return (g_to && g_from) ? 0 : -1;
}

static void bridge_stop(void) {
    if (g_to) fclose(g_to);   /* EOF ends the bridge's read loop */
    if (g_from) fclose(g_from);
    if (g_pid > 0) waitpid(g_pid, NULL, 0);
}

/* Send one request (consumed); return the parsed response if ok, else NULL (error printed). */
static cJSON *bridge_call(const char *op, cJSON *req) {
    cJSON_AddStringToObject(req, "op", op);
    char *line = cJSON_PrintUnformatted(req);
    json_wipe(req);
    cJSON_Delete(req);
    fprintf(g_to, "%s\n", line);
    fflush(g_to);
    OPENSSL_cleanse(line, strlen(line));
    cJSON_free(line);
    char *buf = NULL;
    size_t cap = 0;
    ssize_t n = getline(&buf, &cap, g_from);
    cJSON *resp = n > 0 ? cJSON_Parse(buf) : NULL;
    if (buf) { OPENSSL_cleanse(buf, cap); free(buf); }
    if (!cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(resp, "ok"))) {
        const cJSON *e = cJSON_GetObjectItemCaseSensitive(resp, "error");
        fprintf(stderr, "%s failed: %s\n", op, cJSON_IsString(e) ? e->valuestring : "bridge unavailable");
        json_wipe(resp);
        cJSON_Delete(resp);
        return NULL;
    }
    return resp;
}

/* Titles are not unique: 0 = absent, 1 = exactly one, -1 = error or ambiguous. */
static int find_uid(const char *title) {
    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "title", title);
    cJSON *resp = bridge_call("find", req);
    if (!resp) return -1;
    int n = cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(resp, "uids"));
    cJSON_Delete(resp);
    if (n > 1) { fprintf(stderr, "%d records share the title %s\n", n, title); return -1; }
    return n;
}

static int secret_create(const char *folder, const char *title, const char *value, char uid[64]) {
    int f = find_uid(title);
    if (f != 0) { if (f == 1) fprintf(stderr, "a record titled %s already exists\n", title); return -1; }
    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "folderUid", folder);
    cJSON_AddStringToObject(req, "title", title);
    cJSON_AddStringToObject(req, "value", value);
    cJSON *resp = bridge_call("create", req);
    const cJSON *u = cJSON_GetObjectItemCaseSensitive(resp, "uid");
    int rc = cJSON_IsString(u) ? (snprintf(uid, 64, "%s", u->valuestring), 0) : -1;
    cJSON_Delete(resp);
    return rc;
}

static char *secret_read(const char *uid) {
    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "uid", uid);
    cJSON *resp = bridge_call("read", req);
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(resp, "value");
    char *r = cJSON_IsString(v) ? strdup(v->valuestring) : NULL;
    json_wipe(resp);
    cJSON_Delete(resp);
    return r;
}

static int secret_update(const char *uid, const char *value) {
    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "uid", uid);
    cJSON_AddStringToObject(req, "value", value);
    cJSON *resp = bridge_call("update", req);
    int rc = resp ? 0 : -1;
    cJSON_Delete(resp);
    return rc;
}

static int secret_delete(const char *uid) {
    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "uid", uid);
    cJSON *resp = bridge_call("delete", req);
    int rc = resp ? 0 : -1;
    cJSON_Delete(resp);
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

int main(void) {
    const char *title = getenv("SECRET_TITLE"), *folder = getenv("KSM_FOLDER_UID");
    if (!title || !folder || !getenv("KSM_CONFIG_FILE")) {
        fprintf(stderr, "set SECRET_TITLE, KSM_FOLDER_UID, KSM_CONFIG_FILE, KSM_BRIDGE\n");
        return 2;
    }
    signal(SIGPIPE, SIG_IGN);
    if (bridge_start() != 0) { fprintf(stderr, "cannot start bridge\n"); return 1; }

    int rc = 1;
    char uid[64] = {0}, v1[45], v2[45], *got = NULL;
    if (random_value(v1) || random_value(v2)) goto done;

    if (secret_create(folder, title, v1, uid) != 0) goto done;
    printf("created: %s uid %s\n", title, uid);
    got = secret_read(uid);
    if (!same(v1, got)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    str_wipe_free(got); got = NULL;

    if (secret_update(uid, v2) != 0) goto done;
    got = secret_read(uid);
    if (!same(v2, got)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated: %s\n", title);

    if (secret_delete(uid) != 0) goto done;
    printf("deleted: %s\n", uid);
    rc = 0;
done:
    str_wipe_free(got);
    OPENSSL_cleanse(v1, sizeof v1); OPENSSL_cleanse(v2, sizeof v2);
    bridge_stop();
    return rc;
}
```

### 9.11 The bridge for languages without an SDK

A ~60-line front end to the official Python SDK. It reads one JSON request per line on stdin and writes one JSON response per line on stdout, keeps one SDK client for its lifetime, and reports errors as `{"ok": false, "error": "<class>: <message>"}`. Run it with `python3 -I` (isolated mode) from a read-only location, and pin the SDK version. The same pattern works with any official SDK (for example a Go binary for environments without Python).

```python
#!/usr/bin/env python3
"""ksm_bridge: a tiny JSON-lines front end to the official Keeper Secrets Manager Python SDK.

Languages without a KSM SDK (C, C++, PHP, Swift) spawn this process and exchange one JSON object per line
over stdin/stdout, so record values never appear in argv, environment variables, or temporary files.

  pip install keeper-secrets-manager-core==17.3.0
  KSM_CONFIG_FILE=/run/secrets/ksm-config.json python3 -I ksm_bridge.py

Requests  : {"op":"find","title":T} | {"op":"create","folderUid":F,"title":T,"value":V}
            {"op":"read","uid":U} | {"op":"update","uid":U,"value":V} | {"op":"delete","uid":U}
Responses : {"ok":true, ...result} or {"ok":false,"error":"<class>: <message>"}
The bridge stores only the "password" field of "login" records, matching the CRUD guide's programs.
"""
import json
import os
import sys

from keeper_secrets_manager_core import SecretsManager
from keeper_secrets_manager_core.dto.dtos import RecordCreate, RecordField
from keeper_secrets_manager_core.exceptions import KeeperError
from keeper_secrets_manager_core.storage import InMemoryKeyValueStorage


def handle(sm: SecretsManager, req: dict) -> dict:
    op = req.get("op")
    if op == "find":
        uids = [r.uid for r in sm.get_secrets_by_title(req["title"])]
        return {"uids": uids}
    if op == "create":
        rec = RecordCreate("login", req["title"])
        rec.fields = [RecordField(field_type="password", value=[req["value"]])]
        return {"uid": sm.create_secret(req["folderUid"], rec)}
    if op in ("read", "update"):
        records = sm.get_secrets([req["uid"]])
        if len(records) != 1:
            raise KeeperError("record not found or not shared with this application")
        if op == "read":
            return {"value": records[0].get_standard_field_value("password", single=True)}
        records[0].set_standard_field_value("password", req["value"])
        sm.save(records[0])  # carries the record revision: concurrent edits are rejected
        return {}
    if op == "delete":
        results = sm.delete_secret([req["uid"]]) or []
        bad = [r for r in results if r.get("responseCode") != "ok"]
        if bad or not results:
            raise KeeperError(f"delete failed: {bad[0].get('responseCode') if bad else 'no result'}")
        return {}
    raise ValueError(f"unknown op {op!r}")


def main() -> int:
    with open(os.environ["KSM_CONFIG_FILE"], encoding="utf-8") as fh:
        sm = SecretsManager(config=InMemoryKeyValueStorage(fh.read()))
    for line in sys.stdin:
        try:
            out = {"ok": True, **handle(sm, json.loads(line))}
        except Exception as exc:  # report class and message; KSM messages carry error codes, not record data
            out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## 10. Use secrets in applications

| Mechanism | How values arrive | Notes |
| --- | --- | --- |
| SDK at startup + cache (section 9) | In memory | One device configuration per deployment; optional encrypted fallback cache. |
| `ksm exec -- <command>` with `keeper://` notation in env vars | Environment variables of the child | Replaces `keeper://` references at launch; env-var exposure applies. |
| Kubernetes (External Secrets Operator Keeper provider, or KSM config as a Kubernetes Secret) | Synced Kubernetes `Secret` | Widens exposure to namespace Secret readers. |
| CI integrations (GitHub Actions, GitLab, Jenkins, Azure DevOps, …) | Masked job variables | Store the configuration (base64) as a protected CI secret. |
| Infrastructure tools (Terraform provider, Ansible, Docker) | Tool-specific | Values may land in tool state; protect it. |

Rotation-safe consumption: cache with a TTL; re-read once on downstream authentication failure; use rotation transactions for credentials Keeper rotates.

## 11. Automation and error handling

| Situation | Typical cause | Action |
| --- | --- | --- |
| Binding fails | Token already used (even by a failed attempt), expired, wrong region host | Issue a new one-time token; check the region prefix. |
| Access denied after working | IP lock (egress IP changed), device revoked, application access expired | Re-provision the device; unlock IP only where egress is dynamic. |
| `throttled` (HTTP 403 with `retry_after`) | Request rate | The SDKs back off and retry; cache reads and batch by UID. |
| Revision mismatch on update | Record changed since you read it, or a second update without reloading | Reload, re-apply, save again. |
| Create fails: folder key not found | Folder not shared with the app, app lacks edit, or folder empty | Grant edit; ensure at least one record exists in the folder. |
| Record missing from results | Not shared with the application, or filtered | Share the record or its folder with the application. |

Practices:

- One application per workload per environment; one device configuration per deployment target; IP lock on.
- Address records by UID from configuration; refuse duplicate titles on create.
- Reload before every update; use rotation transactions for rotations.
- Check per-record delete results (or read back where the SDK hides them).

## 12. Optional live CRUD verification

This **performs writes** in the shared folder you choose (use a sandbox folder with one placeholder record). With a configuration for an application that can edit that folder:

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${KSM_CONFIG_FILE:?}" "${KSM_FOLDER_UID:?}"
export SECRET_TITLE="CRUD_CHECK_$(date -u +%Y%m%d%H%M%S)_$$"
python3 crud.py        # the section 9.7 program; values never appear on a command line
printf 'PASS: create, read, update, and delete completed.\n'
```

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| "public key id … does not exist" | Configuration copied from another region or a custom deployment; re-provision against the right host. |
| Works on a laptop, fails in production | IP lock bound the device to the laptop's IP; provision a separate device for production. |
| Two records with the same title | Created without a title check; address by UID. |
| Second update in a row fails | Revision mismatch; reload after each update. |
| Create cannot find the folder | Application lacks edit on the shared folder, or the folder has no records yet. |
| Config file changed unexpectedly | File-backed storage persists SDK state; load configs into in-memory storage for read-mostly services. |
| Values in logs | CLI `--field` values in history, `ksm secret get` output captured, debug logging; remove, rotate, revoke the device. |

## 14. Accuracy notes and official sources

- **Versions:** Python 17.3.0, JavaScript 17.6.0, Rust 17.3.0, Go v1.7.0, Java 17.4.0 (repository `build.gradle.kts`), .NET 17.1.2 (repository `.csproj`); KSM SDKs are released independently per language.
- **Custom server keys:** Python, JavaScript, Rust, and Java accept a `serverPublicKey`/`serverPublicKeyId` pair (isolated deployments, IL5 tokens); Go v1.7.0 uses only its built-in table. The JavaScript SDK requires a numeric key ID.
- **Rust host handling:** in testing, Rust 17.3.0 dropped a `:port` suffix from the configured hostname; standard Keeper hosts are unaffected.
- **Revision conflicts and transactions** are documented in the Python SDK page; the mock's error code for a conflict is an assumption. [S03]
- **CLI syntax** (`ksm init default|k8s`, `ksm profile init`, `ksm secret list/get/add file/update/delete`, `ksm secret template record`, `ksm exec`) was checked against `--help` output of `keeper-secrets-manager-cli` 1.5.0 and the CLI reference; the CLI was not run against the mock (its profile loader does not carry a custom server key). [S09]
- **Mock-based verification** validates client logic, request shapes, and the SDKs' client-side cryptography, not server-side permissions, IP locking, or throttling.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [KSM overview][S01] | Applications, shared folders, devices |
| S02 | [One-Time Access Token][S02] | Binding, single use, IP lock |
| S03 | [Python SDK][S03] | Init, caching, save/transactions, delete, create prerequisites, revision conflicts |
| S04 | [JavaScript SDK][S04] | Node client |
| S05 | [Java SDK][S05] | Java/Kotlin client |
| S06 | [.NET SDK][S06] | .NET client |
| S07 | [Go SDK][S07] | Go client |
| S08 | [Rust SDK][S08] | Rust client |
| S09 | [CLI: secret command][S09] | list/get/add/update/delete |
| S10 | [Keeper notation][S10] | `keeper://` URIs |
| S11 | [Encryption model][S11] | Keys, signatures, IP lock, revocation |
| S12 | [SDK sources][S12] | Payloads, defaults |

[S01]: https://docs.keeper.io/en/keeperpam/secrets-manager/overview
[S02]: https://docs.keeper.io/en/keeperpam/secrets-manager/about/one-time-token
[S03]: https://docs.keeper.io/en/keeperpam/secrets-manager/developer-sdk-library/python-sdk
[S04]: https://docs.keeper.io/en/keeperpam/secrets-manager/developer-sdk-library/javascript-sdk
[S05]: https://docs.keeper.io/en/keeperpam/secrets-manager/developer-sdk-library/java-sdk
[S06]: https://docs.keeper.io/en/keeperpam/secrets-manager/developer-sdk-library/.net-sdk
[S07]: https://docs.keeper.io/en/keeperpam/secrets-manager/developer-sdk-library/golang-sdk
[S08]: https://docs.keeper.io/en/keeperpam/secrets-manager/developer-sdk-library/rust-sdk
[S09]: https://docs.keeper.io/en/keeperpam/secrets-manager/secrets-manager-command-line-interface/secret-command
[S10]: https://docs.keeper.io/en/keeperpam/secrets-manager/about/keeper-notation
[S11]: https://docs.keeper.io/en/keeperpam/secrets-manager/about/security-encryption-model
[S12]: https://github.com/Keeper-Security/secrets-manager
