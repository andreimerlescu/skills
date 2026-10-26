# AWS Secrets Manager: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 26, 2026  
**Service:** AWS Secrets Manager, API version `2017-10-17`, JSON protocol (`application/x-amz-json-1.1`)  
**Primary authentication:** short-lived IAM role credentials already resolved by the runtime's default credential provider chain  
**Languages:** Go, Rust, PHP, C#, Java, Swift, Python, TypeScript, C++, C (CLI snippets use Bash and the AWS CLI v2)

This guide covers application-owned secrets stored as **Secrets Manager secrets** (a metadata container plus immutable versions addressed by staging labels). It covers identity checks, least-privilege IAM, complete CRUD workflows, safe input/output handling, a full CRUD program in each of ten languages, runtime consumption, and troubleshooting. Parameter Store `SecureString` parameters, KMS key management, and rotation Lambda authoring are out of scope except where they affect CRUD.

The credentials are assumed to be provisioned already (instance profile, task role, IRSA/EKS Pod Identity, SSO session, or workload federation). Do not paste access keys into this document, source files, command arguments, or example files.

**Verification boundary:** Request shapes and semantics were cross-checked against the official API reference and SDK sources listed in section 14. The Go program was type-checked with `go vet` against `aws-sdk-go-v2/service/secretsmanager v1.50.6`; the Rust program passed `cargo check` against `aws-sdk-secretsmanager 1.123.0`; the TypeScript program passed `tsc --strict` against `@aws-sdk/client-secrets-manager 3.1156.0`; the Python program ran end-to-end against botocore's `Stubber`, which validates every parameter against the service model; the C program was compiled with `-Wall -Wextra -Werror` and run end-to-end against a local mock endpoint that recomputed and verified each SigV4 signature with botocore. The PHP file passed `php -l` and its calls were checked against `aws-sdk-php` sources. The C#, Java, Swift, and C++ programs were checked line-by-line against the generated SDK model sources but **not compiled** here (NuGet, Maven Central, and Swift toolchains were unavailable). No call was made to a real AWS account. Section 12 provides an optional live test.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Use the existing credentials](#2-use-the-existing-credentials)
3. [Data model and addressing](#3-data-model-and-addressing)
4. [Safe secret handling](#4-safe-secret-handling)
5. [Create secrets](#5-create-secrets)
6. [Read secrets](#6-read-secrets)
7. [Update secrets](#7-update-secrets)
8. [Delete, restore, and purge](#8-delete-restore-and-purge)
9. [Language implementations](#9-language-implementations)
10. [Use secrets in applications](#10-use-secrets-in-applications)
11. [Automation and error handling](#11-automation-and-error-handling)
12. [Optional live CRUD verification](#12-optional-live-crud-verification)
13. [Troubleshooting](#13-troubleshooting)
14. [Accuracy notes and official sources](#14-accuracy-notes-and-official-sources)

## 1. Requirements and conventions

| Language | Official client | Transport used here | Verified here |
| --- | --- | --- | --- |
| Go | `github.com/aws/aws-sdk-go-v2/service/secretsmanager` | SDK | `go vet` (v1.50.6) |
| Rust | `aws-sdk-secretsmanager` + `aws-config` | SDK | `cargo check` (1.123.0) |
| PHP | `aws/aws-sdk-php` v3 | SDK | `php -l`, source check |
| C# | `AWSSDK.SecretsManager` v4 | SDK | source check |
| Java | `software.amazon.awssdk:secretsmanager` (SDK 2.x) | SDK | source/API check |
| Swift | `aws-sdk-swift`, product `AWSSecretsManager` | SDK | source check |
| Python | `boto3` | SDK | Stubber run |
| TypeScript | `@aws-sdk/client-secrets-manager` (v3) | SDK | `tsc --strict` (3.1156.0) |
| C++ | `aws-sdk-cpp`, component `secretsmanager` | SDK | header check |
| C | none (no official C SDK) | libcurl `CURLOPT_AWS_SIGV4` + cJSON | compiled, mock-verified SigV4 |

Use a current release of each SDK. Every program follows the same contract so that results are comparable:

- Non-secret configuration comes from the environment: `AWS_REGION`, `SECRET_NAME` (for example `myapp/dev/crud-check`), and optionally `AWS_SM_KMS_KEY_ID`.
- The program generates a 256-bit random demo value with the platform CSPRNG, **creates** the secret, **reads** it back and compares in constant time, **updates** it with a new random value, reads and compares again, then **schedules deletion** with a 7-day recovery window.
- It prints only ARNs, version IDs, and dates. It never prints, logs, or passes a secret value on a command line.

For CLI snippets in this Bash session:

```bash
set +x
set -o pipefail
umask 077
aws --version
```

`set +x` prevents command tracing from echoing values, `pipefail` surfaces upstream failures, and `umask 077` keeps newly created files private. The AWS CLI is used only for inspection and operator workflows; applications should use an SDK.

## 2. Use the existing credentials

### Identify the credential source

AWS SDKs resolve credentials through a standardized provider chain. The first source that yields credentials wins. [S10]

| Source (in chain order) | Typical configuration | Notes |
| --- | --- | --- |
| Environment keys | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | Highest precedence; a stale exported key silently overrides a role. |
| Web identity (OIDC) | `AWS_ROLE_ARN`, `AWS_WEB_IDENTITY_TOKEN_FILE` | EKS IRSA, GitHub Actions OIDC, other federated CI. |
| IAM Identity Center (SSO) | profile with `sso_*` settings; `AWS_PROFILE` | Human/operator use. |
| Assume role profile | `role_arn` + `source_profile`/`credential_source` | Cross-account access. |
| Container credentials | `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` / `_FULL_URI` | ECS task roles, EKS Pod Identity. |
| Process credentials | `credential_process` in a profile | External broker. |
| Instance metadata (IMDSv2) | EC2 instance profile | Disable with `AWS_EC2_METADATA_DISABLED=true` where unwanted. |

Prefer role-based, short-lived credentials. Long-term access keys for an application are a finding, not a configuration.

### Confirm identity without displaying credentials

```bash
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json
```

This prints the account and the role/session ARN, never key material. Confirm the ARN is the intended workload role. If it is unexpectedly an IAM user, check whether environment keys are shadowing the role:

```bash
for v in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE; do
  [ -n "${!v:-}" ] && printf '%s is set\n' "$v"
done
```

This reports only which variables are set. A successful identity check proves authentication, not authorization: it does not prove `secretsmanager:GetSecretValue` or `kms:Decrypt` on your key.

### Required permissions

Grant the narrowest action set on the narrowest resource pattern. Secret ARNs end with a hyphen and six random characters, so resource patterns use a trailing wildcard. [S03] [S04]

| Operation | IAM actions |
| --- | --- |
| Create | `secretsmanager:CreateSecret`; `secretsmanager:TagResource` if tags are passed; `kms:GenerateDataKey` + `kms:Decrypt` on a customer managed key |
| Read value | `secretsmanager:GetSecretValue`; `kms:Decrypt` on a customer managed key |
| Read metadata | `secretsmanager:DescribeSecret`, `secretsmanager:ListSecrets` (account-wide action) |
| Update value | `secretsmanager:PutSecretValue` (or `UpdateSecret`); KMS as for create |
| Delete / restore | `secretsmanager:DeleteSecret`, `secretsmanager:RestoreSecret` |

A CRUD role scoped to one application prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AppSecretsCrud",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:CreateSecret",
        "secretsmanager:TagResource",
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:DeleteSecret",
        "secretsmanager:RestoreSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:myapp/dev/*"
    }
  ]
}
```

A runtime (read-only) role should hold only `secretsmanager:GetSecretValue` (and `kms:Decrypt` where needed) on the specific secrets it consumes. Separate the role that writes secrets (provisioning, rotation) from the role that reads them.

## 3. Data model and addressing

- A **secret** has metadata (name, ARN, description, KMS key, tags, rotation settings, resource policy) and up to **100 versions**. Each version holds either `SecretString` or `SecretBinary`, at most **65,536 bytes**. [S01]
- **Staging labels** point at versions: `AWSCURRENT` (what readers get by default), `AWSPREVIOUS` (the prior current), and `AWSPENDING` (used during rotation). A secret can have at most 20 labels across versions. [S01] [S05]
- **Versions are immutable.** "Updating" a value creates a new version and moves `AWSCURRENT`.
- **Names** use ASCII letters, digits, and `/_+=.@-`, 1–512 characters. Hierarchical names such as `myapp/prod/db` make IAM prefixes practical. Do not end a name with a hyphen followed by six characters; the ARN already appends `-XXXXXX`, and partial-ARN lookups become ambiguous. [S03]
- `SecretId` accepts a name or ARN. In automation, persist and use the **full ARN** returned by create; names can be re-created after deletion, and an ARN cannot be confused with a different secret.
- **Structured values:** the console stores key/value pairs as a JSON object in `SecretString`. Your code must parse it; Secrets Manager does not interpret it.

Inventory without values:

```bash
aws secretsmanager list-secrets \
  --filters Key=name,Values=myapp/dev/ \
  --query 'SecretList[].{Name:Name,ARN:ARN,LastChanged:LastChangedDate}' --output json

SECRET_ARN='REPLACE_WITH_SECRET_ARN'
aws secretsmanager describe-secret --secret-id "$SECRET_ARN" \
  --query '{Name:Name,KmsKeyId:KmsKeyId,Versions:VersionIdsToStages,DeletedDate:DeletedDate}'
```

`ListSecrets` and `DescribeSecret` never return values. Treat names, descriptions, and tags as potentially sensitive metadata anyway.

## 4. Safe secret handling

- **CloudTrail:** `SecretString`, `SecretBinary`, and `RotationToken` are marked sensitive and excluded from CloudTrail. All other parameters (name, description, tags, KMS key ID) may be logged. Never put secret material in them. [S03] [S05]
- **CLI arguments:** `--secret-string 'value'` places the value in shell history and in the process table. Use `file://` input from a protected file. [S05]
- **SDK debug logging is a leak path.** botocore at `DEBUG` logs response bodies (which contain `SecretString`); Go v2 `ClientLogMode` with `LogResponseWithBody`, Java wire logging (`software.amazon.awssdk.request`, `org.apache.http.wire`), and .NET `AWSConfigs.LoggingConfig.LogResponses` do the same. Keep these off in any environment that touches real secrets.
- **Serialization:** build request bodies with a JSON serializer (the SDK does this). Never concatenate a secret into a JSON or shell string.
- **Memory:** read the value as late as possible, keep it in the narrowest scope, and where the language allows, wipe buffers after use (`zeroize` in Rust, `OPENSSL_cleanse` in C/C++, `CryptographicOperations.ZeroMemory` for byte arrays in .NET). Managed strings in Go, Java, C#, Python, JavaScript, PHP, and Swift cannot be reliably wiped; minimize copies instead.
- **Errors:** SDK exception messages do not echo the secret you sent, but your own wrappers might. Log error codes, ARNs, and request IDs only.

## 5. Create secrets

`CreateSecret` creates the container and, when a value is supplied, the first version labeled `AWSCURRENT`. Key behavior: [S03]

- `ClientRequestToken` (32–64 characters, a UUID is ideal) becomes the version ID. Retrying with the **same token and same value** is a no-op success; the same token with a different value fails. SDKs generate a token if you omit it, but generate it yourself when you implement your own retry loop so retries reuse it.
- Omitting `KmsKeyId` uses the AWS managed key `aws/secretsmanager`. Cross-account consumers require a customer managed key.
- `ResourceExistsException` means the name is taken. **Create is not an upsert.** While a secret with that name is scheduled for deletion, the name stays reserved and create fails with `InvalidRequestException`.
- Tags require `secretsmanager:TagResource` in addition to `CreateSecret`.

### A. Create from a protected file (CLI)

```bash
SECRET_FILE='/secure/path/to/api-token.txt'   # already exists, mode 0600
aws secretsmanager create-secret \
  --name 'myapp/dev/api-token' \
  --description 'Partner API token for myapp (dev)' \
  --secret-string "file://$SECRET_FILE" \
  --tags Key=app,Value=myapp Key=env,Value=dev \
  --query '{ARN:ARN,VersionId:VersionId}' --output json
```

`file://` reads the file verbatim, including a trailing newline. Strip it when producing the file (`printf '%s'`), not by editing the secret after the fact.

### B. Create a structured (JSON) secret

```bash
(
  set -euo pipefail; set +x; umask 077
  work="$(mktemp -d "${TMPDIR:-/tmp}/sm-create.XXXXXXXX")"
  trap 'rm -rf -- "$work"' EXIT
  jq -n --rawfile pw /secure/path/to/db-password.txt \
     '{username: "app_rw", password: ($pw | rtrimstr("\n")), host: "db.internal.example", port: 5432}' \
     > "$work/secret.json"
  aws secretsmanager create-secret --name 'myapp/dev/db' \
    --secret-string "file://$work/secret.json" \
    --query ARN --output text
)
```

### C. Create with a generated password

`GetRandomPassword` returns the value in its response, so write it straight to a protected file and create from that file; never echo it.

```bash
(
  set -euo pipefail; set +x; umask 077
  work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
  aws secretsmanager get-random-password --password-length 40 \
    --require-each-included-type --query RandomPassword --output text \
    | tr -d '\n' > "$work/pw"
  aws secretsmanager create-secret --name 'myapp/dev/admin' \
    --secret-string "file://$work/pw" --query ARN --output text
)
```

The language programs in section 9 implement create with an explicit `ClientRequestToken`, a description, an `app` tag, and an optional customer managed key.

## 6. Read secrets

`GetSecretValue` returns `AWSCURRENT` unless you pass `VersionStage` or `VersionId` (both must agree if both are set). A secret scheduled for deletion returns `InvalidRequestException`; a decryption problem returns `DecryptionFailure`. [S06]

```bash
# Read metadata only (safe to display)
aws secretsmanager describe-secret --secret-id "$SECRET_ARN" --query '{Name:Name,Versions:VersionIdsToStages}'

# Write the current value to a new private file instead of the terminal
aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" \
  --query SecretString --output text > ./api-token.secret

# Previous version (rollback inspection)
aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --version-stage AWSPREVIOUS \
  --query VersionId --output text
```

`--output text` appends a newline; when exact bytes matter, use `--output json` and extract with `jq -j`. Parse JSON secrets without printing them:

```bash
aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text |
  jq -e 'has("username") and has("password")' > /dev/null && printf 'structure ok\n'
```

For many secrets, `BatchGetSecretValue` (by ID list or filter) reduces calls; it is limited to 100 TPS and still requires `GetSecretValue` on each secret. For hot paths, cache (section 10). `GetSecretValue` supports 10,000 TPS per Region per account. [S01] [S06]

## 7. Update secrets

There are two write paths:

| Call | Changes | Use |
| --- | --- | --- |
| `PutSecretValue` | Creates a new version; moves `AWSCURRENT` (and `AWSPREVIOUS`) unless `VersionStages` says otherwise | Rotating or replacing the value. Shown in all programs. |
| `UpdateSecret` | Description, KMS key, and optionally a new value | Metadata changes; re-encrypting under a new key. |

Rules that matter for correctness: [S05]

- Same `ClientRequestToken` + same value is idempotent; same token + different value fails. Use a new token per intended new value.
- Do not call `PutSecretValue`/`UpdateSecret` at a sustained rate above **once every 10 minutes** per secret; unlabeled versions are pruned only beyond 100 and never within 24 hours, so a tight loop hits `LimitExceededException`. [S01]
- Writing a new value to Secrets Manager does **not** change the credential at the database or API provider. Rotate at the provider first (or use a dual-credential scheme), then store; or use managed rotation / a rotation Lambda, which drives the `AWSPENDING → AWSCURRENT` handoff.

```bash
# Replace the value from a protected file
aws secretsmanager put-secret-value --secret-id "$SECRET_ARN" \
  --secret-string "file://$SECRET_FILE" \
  --client-request-token "$(uuidgen)" --query VersionId --output text

# Metadata-only update
aws secretsmanager update-secret --secret-id "$SECRET_ARN" \
  --description 'Partner API token for myapp (dev); owner: platform-team'

# Roll back: inspect versions, then move AWSCURRENT back to the previous version
aws secretsmanager list-secret-version-ids --secret-id "$SECRET_ARN" \
  --query 'Versions[].{Id:VersionId,Stages:VersionStages,Created:CreatedDate}'
aws secretsmanager update-secret-version-stage --secret-id "$SECRET_ARN" \
  --version-stage AWSCURRENT \
  --move-to-version-id 'REPLACE_WITH_PREVIOUS_VERSION_ID' \
  --remove-from-version-id 'REPLACE_WITH_CURRENT_VERSION_ID'
```

Verify an update without printing either value:

```bash
aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output json |
  jq -j . | cmp -s - "$SECRET_FILE" && printf 'Secret replacement verified.\n'
```

## 8. Delete, restore, and purge

`DeleteSecret` schedules deletion. Defaults and limits: [S04]

- `RecoveryWindowInDays`: 7–30, **default 30** when neither option is supplied.
- `ForceDeleteWithoutRecovery=true`: immediate, unrecoverable deletion. It cannot be combined with a recovery window. Deleting an already deleted or nonexistent secret this way does not raise `ResourceNotFoundException`.
- During the window, reads fail with `InvalidRequestException`, the name remains reserved, and `RestoreSecret` cancels deletion.
- Permanent deletion is an asynchronous background task with no exact timing guarantee; re-creating the same name right after a forced delete needs backoff and retry.
- A primary secret with replicas cannot be deleted until replicas are removed with `RemoveRegionsFromReplication`.
- Individual versions cannot be deleted directly; remove all their staging labels and Secrets Manager deprecates them.

```bash
# Inspect the exact target first
aws secretsmanager describe-secret --secret-id "$SECRET_ARN" --query '{Name:Name,ARN:ARN}'

# Recoverable deletion (recommended)
aws secretsmanager delete-secret --secret-id "$SECRET_ARN" --recovery-window-in-days 7

# Undo during the window
aws secretsmanager restore-secret --secret-id "$SECRET_ARN"

# Irreversible deletion (deliberate, reviewed use only)
aws secretsmanager delete-secret --secret-id "$SECRET_ARN" --force-delete-without-recovery
```

To learn whether anything still reads a secret during its recovery window, alarm on CloudTrail `GetSecretValue` events for that ARN. **Deleting a stored credential does not revoke it** at its issuer; revoke or rotate at the source.

## 9. Language implementations

Each program is complete and self-checking. Set `AWS_REGION` and `SECRET_NAME`, run it in a test account, and expect output like:

```text
created: arn:aws:secretsmanager:us-east-1:123456789012:secret:myapp/dev/crud-check-AbCdEf
updated: new version 3f6c...
scheduled deletion: 2026-11-02T17:04:11Z
```

A second run within the recovery window fails at create with an "already exists"/scheduled-for-deletion error, which is the intended non-upsert behavior.

### 9.1 Go

`go get github.com/aws/aws-sdk-go-v2/config github.com/aws/aws-sdk-go-v2/service/secretsmanager github.com/google/uuid`. Errors are matched with `errors.As` against the generated `types.*Exception` structs.

```go
// AWS Secrets Manager CRUD with the AWS SDK for Go v2.
// Credentials come from the default chain (env, shared config/SSO, web identity, ECS/EC2 roles).
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

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/secretsmanager"
	"github.com/aws/aws-sdk-go-v2/service/secretsmanager/types"
	"github.com/google/uuid"
)

type Store struct{ client *secretsmanager.Client }

func NewStore(ctx context.Context) (*Store, error) {
	cfg, err := config.LoadDefaultConfig(ctx) // region from AWS_REGION / profile
	if err != nil {
		return nil, fmt.Errorf("load AWS config: %w", err)
	}
	return &Store{client: secretsmanager.NewFromConfig(cfg)}, nil
}

// Create stores a new secret. The ClientRequestToken makes a retried call idempotent.
func (s *Store) Create(ctx context.Context, name, value string) (arn string, err error) {
	in := &secretsmanager.CreateSecretInput{
		Name:               aws.String(name),
		SecretString:       aws.String(value),
		ClientRequestToken: aws.String(uuid.NewString()),
		Description:        aws.String("managed by secrets-crud example"),
		Tags:               []types.Tag{{Key: aws.String("app"), Value: aws.String("secrets-crud")}},
	}
	if kms := os.Getenv("AWS_SM_KMS_KEY_ID"); kms != "" {
		in.KmsKeyId = aws.String(kms) // customer managed key; default is aws/secretsmanager
	}
	out, err := s.client.CreateSecret(ctx, in)
	if err != nil {
		var exists *types.ResourceExistsException
		if errors.As(err, &exists) {
			return "", fmt.Errorf("secret %q already exists (create is not an upsert): %w", name, err)
		}
		return "", fmt.Errorf("create secret: %w", err)
	}
	return aws.ToString(out.ARN), nil
}

// Read returns the AWSCURRENT version of the secret string.
func (s *Store) Read(ctx context.Context, id string) (string, error) {
	out, err := s.client.GetSecretValue(ctx, &secretsmanager.GetSecretValueInput{
		SecretId:     aws.String(id),
		VersionStage: aws.String("AWSCURRENT"),
	})
	if err != nil {
		var nf *types.ResourceNotFoundException
		if errors.As(err, &nf) {
			return "", fmt.Errorf("secret %q not found: %w", id, err)
		}
		return "", fmt.Errorf("get secret value: %w", err)
	}
	if out.SecretString == nil {
		return "", errors.New("secret holds SecretBinary, not SecretString")
	}
	return *out.SecretString, nil
}

// Update writes a new version; it becomes AWSCURRENT and the old one AWSPREVIOUS.
func (s *Store) Update(ctx context.Context, id, value string) (versionID string, err error) {
	out, err := s.client.PutSecretValue(ctx, &secretsmanager.PutSecretValueInput{
		SecretId:           aws.String(id),
		SecretString:       aws.String(value),
		ClientRequestToken: aws.String(uuid.NewString()),
	})
	if err != nil {
		return "", fmt.Errorf("put secret value: %w", err)
	}
	return aws.ToString(out.VersionId), nil
}

// Delete schedules deletion; RestoreSecret can undo it during the recovery window.
func (s *Store) Delete(ctx context.Context, id string, recoveryDays int64) (time.Time, error) {
	out, err := s.client.DeleteSecret(ctx, &secretsmanager.DeleteSecretInput{
		SecretId:             aws.String(id),
		RecoveryWindowInDays: aws.Int64(recoveryDays), // 7..30
	})
	if err != nil {
		return time.Time{}, fmt.Errorf("delete secret: %w", err)
	}
	return aws.ToTime(out.DeletionDate), nil
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
	name := os.Getenv("SECRET_NAME")
	if name == "" {
		log.Fatal("set SECRET_NAME, e.g. myapp/dev/crud-check")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	store, err := NewStore(ctx)
	if err != nil {
		log.Fatal(err)
	}

	v1 := randomValue()
	arn, err := store.Create(ctx, name, v1)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("created:", arn)

	got, err := store.Read(ctx, arn)
	if err != nil || !equal(got, v1) {
		log.Fatal("read-back after create failed: ", err)
	}

	v2 := randomValue()
	ver, err := store.Update(ctx, arn, v2)
	if err != nil {
		log.Fatal(err)
	}
	if got, err = store.Read(ctx, arn); err != nil || !equal(got, v2) {
		log.Fatal("read-back after update failed: ", err)
	}
	fmt.Println("updated: new version", ver)

	when, err := store.Delete(ctx, arn, 7)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("scheduled deletion:", when.Format(time.RFC3339))
}
```

### 9.2 Rust

`Cargo.toml`:

```toml
[package]
name = "aws-secrets-crud"
version = "0.1.0"
edition = "2021"

[dependencies]
aws-config = { version = "1", features = ["behavior-version-latest"] }
aws-sdk-secretsmanager = "1"
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
uuid = { version = "1", features = ["v4"] }
getrandom = "0.3"
base64 = "0.22"
zeroize = "1"
```

`into_service_error()` exposes typed checks such as `is_resource_exists_exception()`. Values are held in `Zeroizing<String>` so they are wiped on drop.

```rust
//! AWS Secrets Manager CRUD with the AWS SDK for Rust.
//! Credentials come from the default provider chain.
use aws_sdk_secretsmanager::{primitives::DateTimeFormat, types::Tag, Client};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use std::{env, error::Error};
use zeroize::Zeroizing;

type Res<T> = Result<T, Box<dyn Error + Send + Sync>>;

async fn create(client: &Client, name: &str, value: &str) -> Res<String> {
    let mut req = client
        .create_secret()
        .name(name)
        .secret_string(value)
        .client_request_token(uuid::Uuid::new_v4().to_string()) // idempotent retries
        .description("managed by secrets-crud example")
        .tags(Tag::builder().key("app").value("secrets-crud").build());
    if let Ok(kms) = env::var("AWS_SM_KMS_KEY_ID") {
        req = req.kms_key_id(kms);
    }
    match req.send().await {
        Ok(out) => Ok(out.arn().unwrap_or_default().to_string()),
        Err(e) => {
            let se = e.into_service_error();
            if se.is_resource_exists_exception() {
                return Err(format!("secret {name} already exists (create is not an upsert)").into());
            }
            Err(se.into())
        }
    }
}

async fn read(client: &Client, id: &str) -> Res<Zeroizing<String>> {
    let out = client
        .get_secret_value()
        .secret_id(id)
        .version_stage("AWSCURRENT")
        .send()
        .await
        .map_err(|e| {
            let se = e.into_service_error();
            if se.is_resource_not_found_exception() {
                format!("secret {id} not found").into()
            } else {
                Box::<dyn Error + Send + Sync>::from(se)
            }
        })?;
    let s = out
        .secret_string()
        .ok_or("secret holds SecretBinary, not SecretString")?;
    Ok(Zeroizing::new(s.to_string()))
}

async fn update(client: &Client, id: &str, value: &str) -> Res<String> {
    let out = client
        .put_secret_value()
        .secret_id(id)
        .secret_string(value)
        .client_request_token(uuid::Uuid::new_v4().to_string())
        .send()
        .await
        .map_err(|e| e.into_service_error())?;
    Ok(out.version_id().unwrap_or_default().to_string())
}

async fn delete(client: &Client, id: &str, recovery_days: i64) -> Res<String> {
    let out = client
        .delete_secret()
        .secret_id(id)
        .recovery_window_in_days(recovery_days) // 7..30; RestoreSecret undoes it
        .send()
        .await
        .map_err(|e| e.into_service_error())?;
    Ok(match out.deletion_date() {
        Some(d) => d.fmt(DateTimeFormat::DateTime)?,
        None => String::from("unknown"),
    })
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
    let config = aws_config::load_from_env().await;
    let client = Client::new(&config);

    let v1 = random_value();
    let arn = create(&client, &name, &v1).await?;
    println!("created: {arn}");
    if !ct_eq(&read(&client, &arn).await?, &v1) {
        return Err("read-back after create did not match".into());
    }

    let v2 = random_value();
    let version = update(&client, &arn, &v2).await?;
    if !ct_eq(&read(&client, &arn).await?, &v2) {
        return Err("read-back after update did not match".into());
    }
    println!("updated: new version {version}");

    println!("scheduled deletion: {}", delete(&client, &arn, 7).await?);
    Ok(())
}
```

### 9.3 PHP

`composer require aws/aws-sdk-php`. Results are `Aws\Result` arrays; service errors raise `SecretsManagerException` with `getAwsErrorCode()`. `hash_equals` gives a timing-safe comparison.

```php
<?php
// AWS Secrets Manager CRUD with the AWS SDK for PHP v3.
// composer require aws/aws-sdk-php
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use Aws\SecretsManager\Exception\SecretsManagerException;
use Aws\SecretsManager\SecretsManagerClient;

final class AwsSecretStore
{
    public function __construct(private SecretsManagerClient $client) {}

    public static function fromEnvironment(): self
    {
        // Credentials: default provider chain (env, ini profile, SSO, web identity, ECS/EC2 roles).
        return new self(new SecretsManagerClient([
            'region'  => getenv('AWS_REGION') ?: throw new RuntimeException('set AWS_REGION'),
            'version' => '2017-10-17',
        ]));
    }

    public function create(string $name, string $value): string
    {
        $args = [
            'Name'               => $name,
            'SecretString'       => $value,
            'ClientRequestToken' => self::uuid4(), // idempotent retries
            'Description'        => 'managed by secrets-crud example',
            'Tags'               => [['Key' => 'app', 'Value' => 'secrets-crud']],
        ];
        if ($kms = getenv('AWS_SM_KMS_KEY_ID')) {
            $args['KmsKeyId'] = $kms;
        }
        try {
            return (string) $this->client->createSecret($args)['ARN'];
        } catch (SecretsManagerException $e) {
            if ($e->getAwsErrorCode() === 'ResourceExistsException') {
                throw new RuntimeException("secret {$name} already exists (create is not an upsert)", 0, $e);
            }
            throw $e;
        }
    }

    public function read(string $id): string
    {
        $result = $this->client->getSecretValue(['SecretId' => $id, 'VersionStage' => 'AWSCURRENT']);
        if (!isset($result['SecretString'])) {
            throw new RuntimeException('secret holds SecretBinary, not SecretString');
        }
        return $result['SecretString'];
    }

    public function update(string $id, string $value): string
    {
        $result = $this->client->putSecretValue([
            'SecretId'           => $id,
            'SecretString'       => $value,
            'ClientRequestToken' => self::uuid4(),
        ]);
        return (string) $result['VersionId'];
    }

    public function delete(string $id, int $recoveryDays = 7): string
    {
        $result = $this->client->deleteSecret([
            'SecretId'             => $id,
            'RecoveryWindowInDays' => $recoveryDays, // 7..30; restoreSecret() undoes it
        ]);
        return (string) $result['DeletionDate'];
    }

    private static function uuid4(): string
    {
        $b = random_bytes(16);
        $b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
        $b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($b), 4));
    }
}

function random_value(): string
{
    return rtrim(strtr(base64_encode(random_bytes(32)), '+/', '-_'), '=');
}

$name = getenv('SECRET_NAME') ?: exit("set SECRET_NAME\n");
$store = AwsSecretStore::fromEnvironment();

$v1 = random_value();
$arn = $store->create($name, $v1);
echo "created: {$arn}\n";
if (!hash_equals($v1, $store->read($arn))) {
    exit("read-back after create did not match\n");
}

$v2 = random_value();
$version = $store->update($arn, $v2);
if (!hash_equals($v2, $store->read($arn))) {
    exit("read-back after update did not match\n");
}
echo "updated: new version {$version}\n";

echo 'scheduled deletion: ' . $store->delete($arn, 7) . "\n";
unset($v1, $v2);
```

### 9.4 C#

`dotnet add package AWSSDK.SecretsManager` (v4; value-type properties such as `RecoveryWindowInDays` are nullable). Modeled errors are thrown as typed exceptions (`ResourceExistsException`, `ResourceNotFoundException`).

```csharp
// AWS Secrets Manager CRUD with the AWS SDK for .NET (AWSSDK.SecretsManager v4).
// dotnet add package AWSSDK.SecretsManager
using System.Security.Cryptography;
using System.Text;
using Amazon.SecretsManager;
using Amazon.SecretsManager.Model;

public sealed class AwsSecretStore(IAmazonSecretsManager client)
{
    public async Task<string> CreateAsync(string name, string value, CancellationToken ct = default)
    {
        var request = new CreateSecretRequest
        {
            Name = name,
            SecretString = value,
            ClientRequestToken = Guid.NewGuid().ToString(), // idempotent retries
            Description = "managed by secrets-crud example",
            Tags = [new Tag { Key = "app", Value = "secrets-crud" }],
        };
        var kms = Environment.GetEnvironmentVariable("AWS_SM_KMS_KEY_ID");
        if (!string.IsNullOrEmpty(kms)) request.KmsKeyId = kms;
        try
        {
            var response = await client.CreateSecretAsync(request, ct);
            return response.ARN;
        }
        catch (ResourceExistsException ex)
        {
            throw new InvalidOperationException($"secret {name} already exists (create is not an upsert)", ex);
        }
    }

    public async Task<string> ReadAsync(string id, CancellationToken ct = default)
    {
        var response = await client.GetSecretValueAsync(
            new GetSecretValueRequest { SecretId = id, VersionStage = "AWSCURRENT" }, ct);
        return response.SecretString
            ?? throw new InvalidOperationException("secret holds SecretBinary, not SecretString");
    }

    public async Task<string> UpdateAsync(string id, string value, CancellationToken ct = default)
    {
        var response = await client.PutSecretValueAsync(new PutSecretValueRequest
        {
            SecretId = id,
            SecretString = value,
            ClientRequestToken = Guid.NewGuid().ToString(),
        }, ct);
        return response.VersionId;
    }

    public async Task<DateTime?> DeleteAsync(string id, long recoveryDays = 7, CancellationToken ct = default)
    {
        var response = await client.DeleteSecretAsync(new DeleteSecretRequest
        {
            SecretId = id,
            RecoveryWindowInDays = recoveryDays, // 7..30; RestoreSecretAsync undoes it
        }, ct);
        return response.DeletionDate;
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
        var name = Environment.GetEnvironmentVariable("SECRET_NAME")
                   ?? throw new InvalidOperationException("set SECRET_NAME");
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(60));
        // Region and credentials resolve from the environment/profile/instance role.
        using var client = new AmazonSecretsManagerClient();
        var store = new AwsSecretStore(client);

        var v1 = RandomValue();
        var arn = await store.CreateAsync(name, v1, cts.Token);
        Console.WriteLine($"created: {arn}");
        if (!FixedEquals(v1, await store.ReadAsync(arn, cts.Token)))
            throw new InvalidOperationException("read-back after create did not match");

        var v2 = RandomValue();
        var version = await store.UpdateAsync(arn, v2, cts.Token);
        if (!FixedEquals(v2, await store.ReadAsync(arn, cts.Token)))
            throw new InvalidOperationException("read-back after update did not match");
        Console.WriteLine($"updated: new version {version}");

        var when = await store.DeleteAsync(arn, 7, cts.Token);
        Console.WriteLine($"scheduled deletion: {when:O}");
        return 0;
    }
}
```

### 9.5 Java

Use the SDK BOM and the `secretsmanager` artifact:

```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>software.amazon.awssdk</groupId>
      <artifactId>bom</artifactId>
      <version>${aws.sdk.version}</version> <!-- pin a current 2.x release -->
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
<dependencies>
  <dependency>
    <groupId>software.amazon.awssdk</groupId>
    <artifactId>secretsmanager</artifactId>
  </dependency>
</dependencies>
```

```java
// AWS Secrets Manager CRUD with the AWS SDK for Java 2.x.
// Maven: software.amazon.awssdk:secretsmanager (import the software.amazon.awssdk:bom)
package example;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;
import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import software.amazon.awssdk.services.secretsmanager.model.CreateSecretRequest;
import software.amazon.awssdk.services.secretsmanager.model.DeleteSecretRequest;
import software.amazon.awssdk.services.secretsmanager.model.GetSecretValueRequest;
import software.amazon.awssdk.services.secretsmanager.model.GetSecretValueResponse;
import software.amazon.awssdk.services.secretsmanager.model.PutSecretValueRequest;
import software.amazon.awssdk.services.secretsmanager.model.ResourceExistsException;
import software.amazon.awssdk.services.secretsmanager.model.Tag;

public final class AwsSecretsCrud {
    private final SecretsManagerClient client;

    public AwsSecretsCrud(SecretsManagerClient client) {
        this.client = client;
    }

    public String create(String name, String value) {
        CreateSecretRequest.Builder req = CreateSecretRequest.builder()
                .name(name)
                .secretString(value)
                .clientRequestToken(UUID.randomUUID().toString()) // idempotent retries
                .description("managed by secrets-crud example")
                .tags(Tag.builder().key("app").value("secrets-crud").build());
        String kms = System.getenv("AWS_SM_KMS_KEY_ID");
        if (kms != null && !kms.isEmpty()) {
            req.kmsKeyId(kms);
        }
        try {
            return client.createSecret(req.build()).arn();
        } catch (ResourceExistsException e) {
            throw new IllegalStateException("secret " + name + " already exists (create is not an upsert)", e);
        }
    }

    public String read(String id) {
        GetSecretValueResponse resp = client.getSecretValue(GetSecretValueRequest.builder()
                .secretId(id)
                .versionStage("AWSCURRENT")
                .build());
        if (resp.secretString() == null) {
            throw new IllegalStateException("secret holds SecretBinary, not SecretString");
        }
        return resp.secretString();
    }

    public String update(String id, String value) {
        return client.putSecretValue(PutSecretValueRequest.builder()
                .secretId(id)
                .secretString(value)
                .clientRequestToken(UUID.randomUUID().toString())
                .build()).versionId();
    }

    public Instant delete(String id, long recoveryDays) {
        return client.deleteSecret(DeleteSecretRequest.builder()
                .secretId(id)
                .recoveryWindowInDays(recoveryDays) // 7..30; restoreSecret undoes it
                .build()).deletionDate();
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
        String name = System.getenv("SECRET_NAME");
        if (name == null) throw new IllegalArgumentException("set SECRET_NAME");

        // Region and credentials come from the default provider chains.
        try (SecretsManagerClient client = SecretsManagerClient.create()) {
            AwsSecretsCrud store = new AwsSecretsCrud(client);

            String v1 = randomValue();
            String arn = store.create(name, v1);
            System.out.println("created: " + arn);
            if (!fixedEquals(v1, store.read(arn))) throw new IllegalStateException("read-back after create failed");

            String v2 = randomValue();
            String version = store.update(arn, v2);
            if (!fixedEquals(v2, store.read(arn))) throw new IllegalStateException("read-back after update failed");
            System.out.println("updated: new version " + version);

            System.out.println("scheduled deletion: " + store.delete(arn, 7));
        }
    }
}
```

### 9.6 Swift

`Package.swift`:

```swift
// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "SecretsCrud",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/awslabs/aws-sdk-swift", from: "1.0.0"),
    ],
    targets: [
        .executableTarget(
            name: "SecretsCrud",
            dependencies: [.product(name: "AWSSecretsManager", package: "aws-sdk-swift")]
        ),
    ]
)
```

Model initializers take arguments in alphabetical order; service errors are thrown as typed structs such as `ResourceExistsException`.

```swift
// AWS Secrets Manager CRUD with the AWS SDK for Swift.
import AWSSecretsManager
import Foundation

struct AwsSecretStore {
    let client: SecretsManagerClient

    func create(name: String, value: String) async throws -> String {
        let kms = ProcessInfo.processInfo.environment["AWS_SM_KMS_KEY_ID"]
        do {
            let out = try await client.createSecret(input: CreateSecretInput(
                clientRequestToken: UUID().uuidString, // idempotent retries
                description: "managed by secrets-crud example",
                kmsKeyId: kms,
                name: name,
                secretString: value,
                tags: [SecretsManagerClientTypes.Tag(key: "app", value: "secrets-crud")]
            ))
            return out.arn ?? ""
        } catch is ResourceExistsException {
            throw CrudError.message("secret \(name) already exists (create is not an upsert)")
        }
    }

    func read(id: String) async throws -> String {
        let out = try await client.getSecretValue(input: GetSecretValueInput(
            secretId: id, versionStage: "AWSCURRENT"))
        guard let value = out.secretString else {
            throw CrudError.message("secret holds SecretBinary, not SecretString")
        }
        return value
    }

    func update(id: String, value: String) async throws -> String {
        let out = try await client.putSecretValue(input: PutSecretValueInput(
            clientRequestToken: UUID().uuidString, secretId: id, secretString: value))
        return out.versionId ?? ""
    }

    func delete(id: String, recoveryDays: Int = 7) async throws -> Date? {
        // 7..30 days; restoreSecret(input:) undoes it during the window.
        let out = try await client.deleteSecret(input: DeleteSecretInput(
            recoveryWindowInDays: recoveryDays, secretId: id))
        return out.deletionDate
    }
}

enum CrudError: Error { case message(String) }

func randomValue() -> String {
    var rng = SystemRandomNumberGenerator() // CSPRNG on Apple platforms and Linux
    let bytes = (0..<32).map { _ in UInt8.random(in: .min ... .max, using: &rng) }
    return Data(bytes).base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

func fixedEquals(_ a: String, _ b: String) -> Bool {
    let x = Array(a.utf8), y = Array(b.utf8)
    guard x.count == y.count else { return false }
    return zip(x, y).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
}

guard let name = ProcessInfo.processInfo.environment["SECRET_NAME"] else {
    fatalError("set SECRET_NAME")
}
// Region and credentials resolve from the environment, shared config, SSO or instance role.
let store = AwsSecretStore(client: try await SecretsManagerClient())

let v1 = randomValue()
let arn = try await store.create(name: name, value: v1)
print("created: \(arn)")
guard fixedEquals(v1, try await store.read(id: arn)) else { fatalError("read-back after create failed") }

let v2 = randomValue()
let version = try await store.update(id: arn, value: v2)
guard fixedEquals(v2, try await store.read(id: arn)) else { fatalError("read-back after update failed") }
print("updated: new version \(version)")

let when = try await store.delete(id: arn)
print("scheduled deletion: \(when.map { ISO8601DateFormatter().string(from: $0) } ?? "unknown")")
```

### 9.7 Python

`pip install boto3`. `client.exceptions.<Name>` exposes modeled errors; the `standard` retry mode adds jittered backoff for throttling.

```python
"""AWS Secrets Manager CRUD with boto3.

pip install boto3
Credentials and region come from the default chain (env, profile/SSO, web identity, ECS/EC2 roles).
"""
from __future__ import annotations

import datetime as dt
import hmac
import os
import secrets
import sys
import uuid

import boto3
from botocore.config import Config


class AwsSecretStore:
    def __init__(self, client=None) -> None:
        self.client = client or boto3.client(
            "secretsmanager",
            config=Config(retries={"mode": "standard", "max_attempts": 5}),
        )

    def create(self, name: str, value: str) -> str:
        kwargs = {
            "Name": name,
            "SecretString": value,
            "ClientRequestToken": str(uuid.uuid4()),  # idempotent retries
            "Description": "managed by secrets-crud example",
            "Tags": [{"Key": "app", "Value": "secrets-crud"}],
        }
        if kms := os.environ.get("AWS_SM_KMS_KEY_ID"):
            kwargs["KmsKeyId"] = kms
        try:
            return self.client.create_secret(**kwargs)["ARN"]
        except self.client.exceptions.ResourceExistsException as exc:
            raise RuntimeError(f"secret {name} already exists (create is not an upsert)") from exc

    def read(self, secret_id: str) -> str:
        resp = self.client.get_secret_value(SecretId=secret_id, VersionStage="AWSCURRENT")
        if "SecretString" not in resp:
            raise RuntimeError("secret holds SecretBinary, not SecretString")
        return resp["SecretString"]

    def update(self, secret_id: str, value: str) -> str:
        resp = self.client.put_secret_value(
            SecretId=secret_id,
            SecretString=value,
            ClientRequestToken=str(uuid.uuid4()),
        )
        return resp["VersionId"]

    def delete(self, secret_id: str, recovery_days: int = 7) -> dt.datetime:
        # 7..30 days; restore_secret() undoes it during the window.
        resp = self.client.delete_secret(SecretId=secret_id, RecoveryWindowInDays=recovery_days)
        return resp["DeletionDate"]


def main() -> int:
    name = os.environ.get("SECRET_NAME")
    if not name:
        print("set SECRET_NAME", file=sys.stderr)
        return 2
    store = AwsSecretStore()

    v1 = secrets.token_urlsafe(32)
    arn = store.create(name, v1)
    print(f"created: {arn}")
    if not hmac.compare_digest(v1, store.read(arn)):
        raise RuntimeError("read-back after create did not match")

    v2 = secrets.token_urlsafe(32)
    version = store.update(arn, v2)
    if not hmac.compare_digest(v2, store.read(arn)):
        raise RuntimeError("read-back after update did not match")
    print(f"updated: new version {version}")

    print(f"scheduled deletion: {store.delete(arn).isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 9.8 TypeScript (Node.js)

`npm i @aws-sdk/client-secrets-manager`. Modeled errors are classes exported from the client package, so `instanceof` works.

```typescript
// AWS Secrets Manager CRUD with the AWS SDK for JavaScript v3.
// npm i @aws-sdk/client-secrets-manager
import { randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import {
  CreateSecretCommand,
  DeleteSecretCommand,
  GetSecretValueCommand,
  PutSecretValueCommand,
  ResourceExistsException,
  SecretsManagerClient,
} from "@aws-sdk/client-secrets-manager";

export class AwsSecretStore {
  constructor(private readonly client: SecretsManagerClient = new SecretsManagerClient({})) {}

  async create(name: string, value: string): Promise<string> {
    try {
      const out = await this.client.send(
        new CreateSecretCommand({
          Name: name,
          SecretString: value,
          ClientRequestToken: randomUUID(), // idempotent retries
          Description: "managed by secrets-crud example",
          KmsKeyId: process.env.AWS_SM_KMS_KEY_ID || undefined,
          Tags: [{ Key: "app", Value: "secrets-crud" }],
        }),
      );
      return out.ARN ?? "";
    } catch (err) {
      if (err instanceof ResourceExistsException) {
        throw new Error(`secret ${name} already exists (create is not an upsert)`, { cause: err });
      }
      throw err;
    }
  }

  async read(id: string): Promise<string> {
    const out = await this.client.send(
      new GetSecretValueCommand({ SecretId: id, VersionStage: "AWSCURRENT" }),
    );
    if (out.SecretString === undefined) throw new Error("secret holds SecretBinary, not SecretString");
    return out.SecretString;
  }

  async update(id: string, value: string): Promise<string> {
    const out = await this.client.send(
      new PutSecretValueCommand({ SecretId: id, SecretString: value, ClientRequestToken: randomUUID() }),
    );
    return out.VersionId ?? "";
  }

  async delete(id: string, recoveryDays = 7): Promise<Date | undefined> {
    // 7..30 days; RestoreSecretCommand undoes it during the window.
    const out = await this.client.send(
      new DeleteSecretCommand({ SecretId: id, RecoveryWindowInDays: recoveryDays }),
    );
    return out.DeletionDate;
  }
}

const randomValue = (): string => randomBytes(32).toString("base64url");
const fixedEquals = (a: string, b: string): boolean => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

async function main(): Promise<void> {
  const name = process.env.SECRET_NAME;
  if (!name) throw new Error("set SECRET_NAME");
  const store = new AwsSecretStore();

  const v1 = randomValue();
  const arn = await store.create(name, v1);
  console.log(`created: ${arn}`);
  if (!fixedEquals(v1, await store.read(arn))) throw new Error("read-back after create did not match");

  const v2 = randomValue();
  const version = await store.update(arn, v2);
  if (!fixedEquals(v2, await store.read(arn))) throw new Error("read-back after update did not match");
  console.log(`updated: new version ${version}`);

  console.log(`scheduled deletion: ${(await store.delete(arn))?.toISOString()}`);
}

main().catch((err: unknown) => {
  // Log the error class/message only; SDK errors never contain the secret value you sent.
  console.error(err instanceof Error ? `${err.name}: ${err.message}` : "unknown error");
  process.exitCode = 1;
});
```

### 9.9 C++

CMake:

```cmake
cmake_minimum_required(VERSION 3.16)
project(secrets_crud CXX)
set(CMAKE_CXX_STANDARD 17)
find_package(AWSSDK REQUIRED COMPONENTS secretsmanager)
find_package(OpenSSL REQUIRED)
add_executable(secrets_crud main.cpp)
target_link_libraries(secrets_crud ${AWSSDK_LINK_LIBRARIES} OpenSSL::Crypto)
```

`Aws::String` can use the SDK's custom allocator, so the store API uses `Aws::String` and converts explicitly when building `std::runtime_error` messages. `InitAPI`/`ShutdownAPI` must bracket all client lifetimes.

```cpp
// AWS Secrets Manager CRUD with the AWS SDK for C++.
// Build with CMake: find_package(AWSSDK REQUIRED COMPONENTS secretsmanager)
//                   target_link_libraries(app ${AWSSDK_LINK_LIBRARIES})
#include <aws/core/Aws.h>
#include <aws/core/client/ClientConfiguration.h>
#include <aws/core/utils/DateTime.h>
#include <aws/core/utils/UUID.h>
#include <aws/secretsmanager/SecretsManagerClient.h>
#include <aws/secretsmanager/SecretsManagerErrors.h>
#include <aws/secretsmanager/model/CreateSecretRequest.h>
#include <aws/secretsmanager/model/DeleteSecretRequest.h>
#include <aws/secretsmanager/model/GetSecretValueRequest.h>
#include <aws/secretsmanager/model/PutSecretValueRequest.h>
#include <aws/secretsmanager/model/Tag.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace sm = Aws::SecretsManager;

// Aws::String may use the SDK allocator (CUSTOM_MEMORY_MANAGEMENT), so the store
// API speaks Aws::String and errors convert explicitly to std::string.
static std::string S(const Aws::String& s) { return std::string(s.c_str(), s.size()); }

class AwsSecretStore {
public:
    explicit AwsSecretStore(const Aws::Client::ClientConfiguration& cfg) : client_(cfg) {}

    Aws::String create(const Aws::String& name, const Aws::String& value) {
        sm::Model::CreateSecretRequest req;
        req.SetName(name);
        req.SetSecretString(value);
        req.SetClientRequestToken(Aws::String(Aws::Utils::UUID::RandomUUID()));  // idempotent retries
        req.SetDescription("managed by secrets-crud example");
        sm::Model::Tag tag;
        tag.SetKey("app");
        tag.SetValue("secrets-crud");
        req.AddTags(tag);
        if (const char* kms = std::getenv("AWS_SM_KMS_KEY_ID")) req.SetKmsKeyId(kms);

        auto outcome = client_.CreateSecret(req);
        if (!outcome.IsSuccess()) {
            const auto& err = outcome.GetError();
            if (err.GetErrorType() == sm::SecretsManagerErrors::RESOURCE_EXISTS)
                throw std::runtime_error("secret " + S(name) + " already exists (create is not an upsert)");
            throw std::runtime_error("CreateSecret: " + S(err.GetMessage()));
        }
        return outcome.GetResult().GetARN();
    }

    Aws::String read(const Aws::String& id) {
        sm::Model::GetSecretValueRequest req;
        req.SetSecretId(id);
        req.SetVersionStage("AWSCURRENT");
        auto outcome = client_.GetSecretValue(req);
        if (!outcome.IsSuccess()) {
            const auto& err = outcome.GetError();
            if (err.GetErrorType() == sm::SecretsManagerErrors::RESOURCE_NOT_FOUND)
                throw std::runtime_error("secret " + S(id) + " not found");
            throw std::runtime_error("GetSecretValue: " + S(err.GetMessage()));
        }
        return outcome.GetResult().GetSecretString();
    }

    Aws::String update(const Aws::String& id, const Aws::String& value) {
        sm::Model::PutSecretValueRequest req;
        req.SetSecretId(id);
        req.SetSecretString(value);
        req.SetClientRequestToken(Aws::String(Aws::Utils::UUID::RandomUUID()));
        auto outcome = client_.PutSecretValue(req);
        if (!outcome.IsSuccess()) throw std::runtime_error("PutSecretValue: " + S(outcome.GetError().GetMessage()));
        return outcome.GetResult().GetVersionId();
    }

    Aws::String remove(const Aws::String& id, long long recoveryDays = 7) {
        sm::Model::DeleteSecretRequest req;
        req.SetSecretId(id);
        req.SetRecoveryWindowInDays(recoveryDays);  // 7..30; RestoreSecret undoes it
        auto outcome = client_.DeleteSecret(req);
        if (!outcome.IsSuccess()) throw std::runtime_error("DeleteSecret: " + S(outcome.GetError().GetMessage()));
        return outcome.GetResult().GetDeletionDate().ToGmtString(Aws::Utils::DateFormat::ISO_8601);
    }

private:
    sm::SecretsManagerClient client_;
};

static Aws::String random_value() {
    unsigned char raw[32];
    if (RAND_bytes(raw, sizeof raw) != 1) throw std::runtime_error("RAND_bytes failed");
    unsigned char b64[64];
    int n = EVP_EncodeBlock(b64, raw, sizeof raw);
    OPENSSL_cleanse(raw, sizeof raw);
    Aws::String out(reinterpret_cast<char*>(b64), static_cast<size_t>(n));
    OPENSSL_cleanse(b64, sizeof b64);
    return out;
}

static bool fixed_equals(const Aws::String& a, const Aws::String& b) {
    return a.size() == b.size() && CRYPTO_memcmp(a.data(), b.data(), a.size()) == 0;
}

static void wipe(Aws::String& s) { OPENSSL_cleanse(&s[0], s.size()); s.clear(); }

int main() {
    const char* name = std::getenv("SECRET_NAME");
    if (!name) { std::cerr << "set SECRET_NAME\n"; return 2; }

    Aws::SDKOptions options;
    Aws::InitAPI(options);
    int rc = 0;
    {
        Aws::Client::ClientConfiguration cfg;  // credentials: default provider chain
        if (const char* region = std::getenv("AWS_REGION")) cfg.region = region;
        AwsSecretStore store(cfg);
        try {
            Aws::String v1 = random_value();
            Aws::String arn = store.create(name, v1);
            std::cout << "created: " << arn << "\n";
            Aws::String got = store.read(arn);
            if (!fixed_equals(v1, got)) throw std::runtime_error("read-back after create failed");

            Aws::String v2 = random_value();
            Aws::String version = store.update(arn, v2);
            got = store.read(arn);
            if (!fixed_equals(v2, got)) throw std::runtime_error("read-back after update failed");
            std::cout << "updated: new version " << version << "\n";
            wipe(v1); wipe(v2); wipe(got);

            std::cout << "scheduled deletion: " << store.remove(arn) << "\n";
        } catch (const std::exception& e) {
            std::cerr << "error: " << e.what() << "\n";
            rc = 1;
        }
    }
    Aws::ShutdownAPI(options);
    return rc;
}
```

### 9.10 C

There is no official AWS SDK for C. libcurl (7.75+) signs requests with `CURLOPT_AWS_SIGV4` and signs every user-supplied header, including `X-Amz-Target` and `X-Amz-Security-Token`. The program honors `AWS_ENDPOINT_URL_SECRETS_MANAGER` for VPC or FIPS endpoints, restricts libcurl to HTTPS, and wipes request/response buffers. Because C has no provider chain, the runtime must supply short-lived credentials in the environment; prefer the C++ SDK when you can.

```c
/*
 * AWS Secrets Manager CRUD in C: libcurl (built-in SigV4) + cJSON + OpenSSL.
 * There is no official AWS SDK for C; this calls the documented JSON API directly.
 *
 *   cc -std=c11 -Wall -Wextra -O2 aws_secrets_crud.c -o aws_secrets_crud \
 *      $(pkg-config --cflags --libs libcurl libcjson openssl)
 *
 * Credentials: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN must already be
 * provided by the runtime (short-lived role credentials). C has no default provider chain.
 */
#define _POSIX_C_SOURCE 200809L /* strdup */
#include <cjson/cJSON.h>
#include <curl/curl.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { char *data; size_t len; } buf_t;

static size_t on_body(char *ptr, size_t size, size_t nmemb, void *userdata) {
    buf_t *b = userdata;
    size_t n = size * nmemb;
    char *grown = realloc(b->data, b->len + n + 1);
    if (!grown) return 0;
    b->data = grown;
    memcpy(b->data + b->len, ptr, n);
    b->len += n;
    b->data[b->len] = '\0';
    return n;
}

static void buf_wipe(buf_t *b) {
    if (b->data) { OPENSSL_cleanse(b->data, b->len); free(b->data); }
    b->data = NULL; b->len = 0;
}

/* Wipe and free a cJSON-printed string. */
static void json_text_free(char *s) { if (s) { OPENSSL_cleanse(s, strlen(s)); cJSON_free(s); } }

/* POST one Secrets Manager action. Returns parsed JSON (caller frees) or NULL; *err_type gets
 * the AWS error type on HTTP errors (caller frees). The request body is wiped after sending. */
static cJSON *aws_call(const char *action, cJSON *body, char **err_type) {
    const char *region = getenv("AWS_REGION");
    const char *akid = getenv("AWS_ACCESS_KEY_ID");
    const char *secret = getenv("AWS_SECRET_ACCESS_KEY");
    const char *token = getenv("AWS_SESSION_TOKEN");
    if (!region || !akid || !secret) { fprintf(stderr, "missing AWS_REGION or credentials\n"); return NULL; }

    char url[256], sigv4[128], target[128], userpwd[512], token_hdr[4096];
    const char *endpoint = getenv("AWS_ENDPOINT_URL_SECRETS_MANAGER"); /* e.g. VPC/FIPS endpoint */
    if (endpoint) snprintf(url, sizeof url, "%s", endpoint);
    else snprintf(url, sizeof url, "https://secretsmanager.%s.amazonaws.com/", region);
    snprintf(sigv4, sizeof sigv4, "aws:amz:%s:secretsmanager", region);
    snprintf(target, sizeof target, "X-Amz-Target: secretsmanager.%s", action);
    snprintf(userpwd, sizeof userpwd, "%s:%s", akid, secret);

    char *payload = cJSON_PrintUnformatted(body);
    buf_t resp = {0};
    struct curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/x-amz-json-1.1");
    hdrs = curl_slist_append(hdrs, target);
    if (token) {   /* curl signs every user header, including this one */
        snprintf(token_hdr, sizeof token_hdr, "X-Amz-Security-Token: %s", token);
        hdrs = curl_slist_append(hdrs, token_hdr);
    }

    CURL *h = curl_easy_init();
    curl_easy_setopt(h, CURLOPT_URL, url);
    curl_easy_setopt(h, CURLOPT_AWS_SIGV4, sigv4);
    curl_easy_setopt(h, CURLOPT_USERPWD, userpwd);
    curl_easy_setopt(h, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(h, CURLOPT_POSTFIELDS, payload);
    curl_easy_setopt(h, CURLOPT_WRITEFUNCTION, on_body);
    curl_easy_setopt(h, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(h, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(h, CURLOPT_PROTOCOLS_STR, "https");

    CURLcode rc = curl_easy_perform(h);
    long status = 0;
    curl_easy_getinfo(h, CURLINFO_RESPONSE_CODE, &status);
    curl_easy_cleanup(h);
    curl_slist_free_all(hdrs);
    OPENSSL_cleanse(userpwd, sizeof userpwd);
    OPENSSL_cleanse(token_hdr, sizeof token_hdr);
    json_text_free(payload);

    cJSON *json = NULL;
    if (rc != CURLE_OK) {
        fprintf(stderr, "%s: transport error: %s\n", action, curl_easy_strerror(rc));
    } else if (status != 200) {
        cJSON *e = cJSON_Parse(resp.data ? resp.data : "{}");
        const cJSON *t = cJSON_GetObjectItemCaseSensitive(e, "__type");
        const char *type = cJSON_IsString(t) ? t->valuestring : "UnknownError";
        const char *hash = strrchr(type, '#');           /* strip optional namespace prefix */
        if (err_type) *err_type = strdup(hash ? hash + 1 : type);
        fprintf(stderr, "%s: HTTP %ld %s\n", action, status, hash ? hash + 1 : type);
        cJSON_Delete(e);
    } else {
        json = cJSON_Parse(resp.data);
    }
    buf_wipe(&resp);
    return json;
}

static void uuid4(char out[37]) {
    unsigned char b[16];
    RAND_bytes(b, sizeof b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    snprintf(out, 37, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
             b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15]);
}

/* CREATE: returns malloc'd ARN or NULL */
static char *secret_create(const char *name, const char *value) {
    char token[37]; uuid4(token);
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "Name", name);
    cJSON_AddStringToObject(body, "SecretString", value);
    cJSON_AddStringToObject(body, "ClientRequestToken", token);   /* idempotent retries */
    cJSON_AddStringToObject(body, "Description", "managed by secrets-crud example");
    const char *kms = getenv("AWS_SM_KMS_KEY_ID");
    if (kms) cJSON_AddStringToObject(body, "KmsKeyId", kms);
    cJSON *tags = cJSON_AddArrayToObject(body, "Tags");
    cJSON *tag = cJSON_CreateObject();
    cJSON_AddStringToObject(tag, "Key", "app");
    cJSON_AddStringToObject(tag, "Value", "secrets-crud");
    cJSON_AddItemToArray(tags, tag);

    char *err = NULL;
    cJSON *out = aws_call("CreateSecret", body, &err);
    cJSON_Delete(body);
    if (err && strcmp(err, "ResourceExistsException") == 0)
        fprintf(stderr, "secret already exists (create is not an upsert)\n");
    free(err);
    const cJSON *arn = cJSON_GetObjectItemCaseSensitive(out, "ARN");
    char *result = cJSON_IsString(arn) ? strdup(arn->valuestring) : NULL;
    cJSON_Delete(out);
    return result;
}

/* READ: returns malloc'd secret string (wipe + free it) or NULL */
static char *secret_read(const char *id) {
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "SecretId", id);
    cJSON_AddStringToObject(body, "VersionStage", "AWSCURRENT");
    cJSON *out = aws_call("GetSecretValue", body, NULL);
    cJSON_Delete(body);
    cJSON *v = cJSON_GetObjectItemCaseSensitive(out, "SecretString");
    char *result = cJSON_IsString(v) ? strdup(v->valuestring) : NULL;
    if (cJSON_IsString(v)) OPENSSL_cleanse(v->valuestring, strlen(v->valuestring));
    cJSON_Delete(out);
    return result;
}

/* UPDATE: new version becomes AWSCURRENT; returns 0 on success */
static int secret_update(const char *id, const char *value) {
    char token[37]; uuid4(token);
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "SecretId", id);
    cJSON_AddStringToObject(body, "SecretString", value);
    cJSON_AddStringToObject(body, "ClientRequestToken", token);
    cJSON *out = aws_call("PutSecretValue", body, NULL);
    cJSON_Delete(body);
    int ok = out != NULL;
    cJSON_Delete(out);
    return ok ? 0 : -1;
}

/* DELETE: schedule deletion with a 7..30 day recovery window; returns 0 on success */
static int secret_delete(const char *id, int recovery_days) {
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "SecretId", id);
    cJSON_AddNumberToObject(body, "RecoveryWindowInDays", recovery_days);
    cJSON *out = aws_call("DeleteSecret", body, NULL);
    cJSON_Delete(body);
    int ok = out != NULL;
    cJSON_Delete(out);
    return ok ? 0 : -1;
}

static void random_value(char out[45]) {
    unsigned char raw[32];
    RAND_bytes(raw, sizeof raw);
    EVP_EncodeBlock((unsigned char *)out, raw, sizeof raw);   /* 44 chars + NUL */
    OPENSSL_cleanse(raw, sizeof raw);
}

static int same(const char *a, const char *b) {
    size_t n = strlen(a);
    return b && strlen(b) == n && CRYPTO_memcmp(a, b, n) == 0;
}

int main(void) {
    const char *name = getenv("SECRET_NAME");
    if (!name) { fprintf(stderr, "set SECRET_NAME\n"); return 2; }
    curl_global_init(CURL_GLOBAL_DEFAULT);
    int rc = 1;
    char v1[45], v2[45];
    char *arn = NULL, *got = NULL;

    random_value(v1);
    if (!(arn = secret_create(name, v1))) goto done;
    printf("created: %s\n", arn);
    got = secret_read(arn);
    if (!same(v1, got)) { fprintf(stderr, "read-back after create failed\n"); goto done; }
    if (got) { OPENSSL_cleanse(got, strlen(got)); free(got); got = NULL; }

    random_value(v2);
    if (secret_update(arn, v2) != 0) goto done;
    got = secret_read(arn);
    if (!same(v2, got)) { fprintf(stderr, "read-back after update failed\n"); goto done; }
    printf("updated\n");

    if (secret_delete(arn, 7) != 0) goto done;
    printf("scheduled deletion (7-day recovery window)\n");
    rc = 0;
done:
    if (got) { OPENSSL_cleanse(got, strlen(got)); free(got); }
    OPENSSL_cleanse(v1, sizeof v1);
    OPENSSL_cleanse(v2, sizeof v2);
    free(arn);
    curl_global_cleanup();
    return rc;
}
```

## 10. Use secrets in applications

**Fetch at startup, cache, refresh.** Read secrets once at startup (fail fast if missing), cache in memory with a TTL, and refresh on authentication failure. Options, from least to most code:

| Mechanism | How the app receives the value | Notes |
| --- | --- | --- |
| ECS task definition `secrets` (`valueFrom` = secret ARN or `ARN:json-key::`) | Environment variable at container start | No refresh without a new task; env vars are visible to the process and anything that can read its environment. |
| EKS Secrets Store CSI Driver + AWS provider (ASCP) | Mounted file (optionally synced to a Kubernetes Secret) | Supports rotation polling; mount as tmpfs, read-only. |
| AWS Workload Credentials Provider (formerly Secrets Manager Agent) | `GET http://localhost:2773/secretsmanager/get?secretId=…` with the `X-Aws-Parameters-Secrets-Token` header | Read-only, in-memory cache (default TTL 300 s, max 1000 entries), SSRF token required; no invalidation, use `refreshNow=true` after rotation. [S08] |
| Lambda: Parameters and Secrets extension | Same localhost pattern | Avoids per-invocation API calls. |
| Client-side caching components (Java, Python, .NET, Go, Rust) | In-process cache wrapping `GetSecretValue` | Configure TTL shorter than your rotation overlap. [S17] |
| Direct SDK call (section 9) | In-process | Simplest; add your own TTL cache. |

Rotation-safe consumption: during rotation both `AWSPENDING` and `AWSCURRENT` exist. Consumers should read `AWSCURRENT` only, and on an authentication failure re-read once (bypassing cache) before failing. Never pin a `VersionId` in long-lived configuration.

## 11. Automation and error handling

| Error | Meaning | Action |
| --- | --- | --- |
| `ResourceNotFoundException` | Wrong ID/Region, or no `DescribeSecret`-level visibility | Check ARN, Region, and permissions; do not auto-create. |
| `ResourceExistsException` | Name already taken at create | Look up the existing secret's ARN; create is not an upsert. |
| `InvalidRequestException` | Often: scheduled for deletion; operation invalid in current state | `describe-secret` to see `DeletedDate`; `restore-secret` if intended. |
| `DecryptionFailure` / `AccessDeniedException` (KMS) | Caller lacks `kms:Decrypt` on the CMK, or key disabled | Fix key policy/grants; do not fall back to another key. |
| `LimitExceededException` | Version or quota exceeded | Slow down writes; prune labels. |
| `ThrottlingException` | Request rate above quota | Use the SDK `standard`/`adaptive` retry mode; cache reads. |
| `InternalServiceError` | Server-side | Retry with backoff. |

Practices:

- Keep the ARN returned by create; re-running create is not an upsert.
- If a create times out, `describe-secret` by name before retrying; if retrying, reuse the same `ClientRequestToken` and value.
- Serialize writers to the same secret; staging-label moves are last-writer-wins.
- Re-read after writes when correctness matters and compare in constant time without logging.
- Use VPC interface endpoints (`com.amazonaws.<region>.secretsmanager`) for private connectivity; enforce with `aws:SourceVpce` conditions where appropriate.
- Write-API quotas are 50 TPS (combined for `PutSecretValue`/`UpdateSecret` and related calls); cross-account calls are throttled against the caller's account. [S01]

## 12. Optional live CRUD verification

This **performs writes** in the account and Region you choose. Use a sandbox account and a dedicated prefix. Any program in section 9 is a complete check; the Bash equivalent:

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
: "${AWS_REGION:?set AWS_REGION}"
command -v aws > /dev/null
aws sts get-caller-identity --query Arn --output text > /dev/null

work="$(mktemp -d)"; trap 'rm -rf -- "$work"' EXIT
name="crud-check/$(date -u +%Y%m%dT%H%M%SZ)-$$"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v1"
head -c 32 /dev/urandom | base64 | tr -d '\n' > "$work/v2"

arn="$(aws secretsmanager create-secret --name "$name" \
        --secret-string "file://$work/v1" --query ARN --output text)"
printf 'Created: %s\n' "$arn"
aws secretsmanager get-secret-value --secret-id "$arn" --query SecretString --output json |
  jq -j . | cmp -s - "$work/v1"

aws secretsmanager put-secret-value --secret-id "$arn" \
  --secret-string "file://$work/v2" > /dev/null
aws secretsmanager get-secret-value --secret-id "$arn" --query SecretString --output json |
  jq -j . | cmp -s - "$work/v2"

aws secretsmanager delete-secret --secret-id "$arn" --recovery-window-in-days 7 > /dev/null
aws secretsmanager describe-secret --secret-id "$arn" --query DeletedDate --output text |
  grep -qv None
printf 'PASS: create, read, update, and scheduled delete completed.\n'
```

It does not test rotation, replication, resource policies, or cross-account KMS.

## 13. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| `Unable to locate credentials` / `NoCredentialProviders` | The process does not see the role: check container credential variables, IRSA token file mount, IMDS hop limit (set to 2 for containers on EC2). |
| Identity is an IAM user, not the role | Exported `AWS_ACCESS_KEY_ID` is overriding the chain; unset it in that process. |
| `AccessDeniedException` on read | Missing `GetSecretValue`, resource policy deny, SCP, or permission boundary; with a CMK, missing `kms:Decrypt`. |
| `ResourceNotFoundException` for a secret that exists | Wrong Region, partial ARN ambiguity, or name vs ARN mismatch. |
| Create fails, "scheduled for deletion" | The name is reserved; restore it or wait/force-delete deliberately. |
| `LimitExceededException` on put | Too many versions; reduce write frequency. |
| App still uses old value after rotation | Caches/agents without invalidation; restart or `refreshNow=true`; TTL too long. |
| JSON parse errors in the app | Secret stored as plain text vs JSON object; trailing newline from a file. |
| Secret visible in logs | SDK debug/wire logging enabled, or app logged a config object. Disable, purge logs, rotate the secret. |
| C program: `SignatureDoesNotMatch` | Clock skew; wrong Region in `aws:amz:<region>:secretsmanager`; a header modified after signing by a proxy. |

## 14. Accuracy notes and official sources

- **Version churn guidance** (no sustained writes more than once per 10 minutes) and the 100-version/24-hour pruning rule are from the quotas and `PutSecretValue` pages. [S01] [S05]
- **Default recovery window** is 30 days when no option is passed; all programs here pass 7 explicitly so tests clean up sooner. [S04]
- **Secrets Manager Agent naming:** the agent page is now titled *AWS Workload Credentials Provider (formerly Secrets Manager Agent)*; one setup step on that page shows a mistyped header name, and this guide uses `X-Aws-Parameters-Secrets-Token`, which the page's examples use. [S08]
- **C signing:** curl's SigV4 implementation signs all user headers; the C program was verified against botocore's signer with a session token present.
- **C#/Java/Swift/C++:** not compiled in the authoring environment; verify with your toolchain.

### Source register

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [Secrets Manager quotas][S01] | Size, versions, labels, TPS quotas, churn guidance |
| S02 | [What is Secrets Manager][S02] | Concepts |
| S03 | [CreateSecret API][S03] | Name rules, token semantics, KMS defaults, permissions |
| S04 | [DeleteSecret API][S04] | Recovery window, force delete, restore, replicas |
| S05 | [PutSecretValue API][S05] | Idempotency, staging labels, logging |
| S06 | [GetSecretValue API][S06] | Stage defaults, errors, permissions |
| S07 | [AWS SDK for Go v2 secretsmanager][S07] | Go client and types |
| S08 | [Workload Credentials Provider (Secrets Manager Agent)][S08] | Local cache endpoint, SSRF header, TTL |
| S09 | [Secrets Manager Rust SDK examples][S09] | Rust builder API |
| S10 | [Standardized credential providers][S10] | Credential chain order |
| S11 | [aws-sdk-cpp][S11] | C++ model/request headers |
| S12 | [aws-sdk-swift][S12] | Swift model initializers |
| S13 | [aws-sdk-net][S13] | .NET v4 model types |
| S14 | [aws-sdk-php][S14] | PHP client and exceptions |
| S15 | [libcurl CURLOPT_AWS_SIGV4][S15] | SigV4 option syntax |
| S16 | [Secrets Manager logging with CloudTrail][S16] | Logged events |
| S17 | [Secrets Manager best practices][S17] | Caching components, KMS conditions, resource-policy guidance |

[S01]: https://docs.aws.amazon.com/secretsmanager/latest/userguide/reference_limits.html
[S02]: https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html
[S03]: https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_CreateSecret.html
[S04]: https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_DeleteSecret.html
[S05]: https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_PutSecretValue.html
[S06]: https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
[S07]: https://pkg.go.dev/github.com/aws/aws-sdk-go-v2/service/secretsmanager
[S08]: https://docs.aws.amazon.com/secretsmanager/latest/userguide/secrets-manager-agent.html
[S09]: https://docs.aws.amazon.com/sdk-for-rust/latest/dg/rust_secrets-manager_code_examples.html
[S10]: https://docs.aws.amazon.com/sdkref/latest/guide/standardized-credentials.html
[S11]: https://github.com/aws/aws-sdk-cpp
[S12]: https://github.com/awslabs/aws-sdk-swift
[S13]: https://github.com/aws/aws-sdk-net
[S14]: https://github.com/aws/aws-sdk-php
[S15]: https://curl.se/libcurl/c/CURLOPT_AWS_SIGV4.html
[S16]: https://docs.aws.amazon.com/secretsmanager/latest/userguide/monitoring-cloudtrail.html
[S17]: https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html
