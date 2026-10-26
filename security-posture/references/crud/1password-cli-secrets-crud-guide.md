# 1Password CLI: comprehensive guide to creating, reading, updating, and deleting secrets

**Documentation verified:** October 6, 2026  
**Utility:** 1Password CLI, executable `op`, current CLI 2 syntax  
**Primary authentication:** an already exported `OP_SERVICE_ACCOUNT_TOKEN`  
**Examples:** Bash on macOS/Linux; `jq` for JSON processing

This guide covers secrets stored as **items and fields in 1Password vaults**. It includes authentication checks, complete CRUD workflows, secret references, safe input/output handling, runtime use, file secrets, and troubleshooting. The separate **1Password Environments** product is not the storage model used here; service accounts currently have read-only access to Environments. [S02]

The token is assumed to be configured already. Do not paste it into this document, command arguments, or example files. An environment token can mean different things: first confirm the variable name in section 2.

**Verification boundary:** Commands and behavior were cross-checked against the official sources linked throughout and listed at the end. Bash examples were syntax-checked, and the JSON transformations were checked locally with synthetic data. `op` was not installed in the authoring workspace, so no live 1Password authentication, secret retrieval, or CRUD operation was performed. Section 13 provides an optional live test you can run in a permitted test vault.

## Contents

1. [Requirements and conventions](#1-requirements-and-conventions)
2. [Use the existing token](#2-use-the-existing-token)
3. [Select a vault and identify items](#3-select-a-vault-and-identify-items)
4. [Fields, JSON, and safe secret handling](#4-fields-json-and-safe-secret-handling)
5. [Create secrets](#5-create-secrets)
6. [Read secrets](#6-read-secrets)
7. [Update secrets](#7-update-secrets)
8. [Archive, delete, and restore](#8-archive-delete-and-restore)
9. [Move or copy items](#9-move-or-copy-items)
10. [Use secrets in applications](#10-use-secrets-in-applications)
11. [Store and retrieve files](#11-store-and-retrieve-files)
12. [Automation and error handling](#12-automation-and-error-handling)
13. [Optional live CRUD verification](#13-optional-live-crud-verification)
14. [Troubleshooting](#14-troubleshooting)
15. [Accuracy notes and official sources](#15-accuracy-notes-and-official-sources)

## 1. Requirements and conventions

Use a current stable 1Password CLI 2 release. Service-account authentication requires at least **2.18.0**, but that minimum does not imply that every later feature is available in 2.18.0. Check your installed binary's help when a flag is unfamiliar. [S01][S02]

```bash
op --version
op --help
op item create --help
op item get --help
op item edit --help
op item delete --help
jq --version
```

If `op` is missing, follow the [official installation instructions][S01]. The documented Homebrew installation command is:

```bash
brew install 1password-cli
```

The examples are individual workflows, not a single script to paste and execute from beginning to end. Replace example IDs, paths, and names with your own. A command that creates, edits, moves, archives, or deletes an item changes your account unless it explicitly uses a supported `--dry-run` flag.

For this Bash session:

```bash
set +x
set -o pipefail
umask 077
```

`set +x` disables command tracing; `pipefail` makes an upstream pipeline failure visible; `umask 077` restricts permissions on newly created local files. Complete scripts below also use `set -euo pipefail`. These are shell practices, not additional `op` flags.

## 2. Use the existing token

### Identify the authentication mode

| Existing environment variable | Meaning | Applicability here |
| --- | --- | --- |
| `OP_SERVICE_ACCOUNT_TOKEN` | Service-account credential | Main workflow: item CRUD, subject to vault permissions. |
| `OP_CONNECT_HOST` and `OP_CONNECT_TOKEN` | Credentials for a deployed Connect server | The documented CLI integration supports `read`, `run`, `inject`, and `item get --format json`; it is not a full CLI CRUD authentication path. |
| `OP_SESSION` | Session from manual user sign-in | User authentication; not a service-account token. |

These variables are not interchangeable. `--session` accepts a user session token, not a service-account token. [S03][S04][S05]

### Confirm the token is exported without displaying it

```bash
set +x
bash -c ': "${OP_SERVICE_ACCOUNT_TOKEN:?OP_SERVICE_ACCOUNT_TOKEN is not exported or is empty}"'
```

This only checks availability in a child process. It does **not** validate the token, permissions, or network connection. If the variable was assigned but not exported, export the existing value without retyping it:

```bash
export OP_SERVICE_ACCOUNT_TOKEN
```

With service-account authentication, `op` uses the variable directly; you do not need an interactive `op signin` step. The official configuration check is: [S06]

```bash
op user get --me
```

Confirm that the displayed identity is the intended service account. This displays account metadata, not the token.

### Resolve Connect precedence

Connect variables take precedence over the service-account variable. If this shell is intentionally supposed to use the service account, clear the competing variables and repeat the identity check: [S06]

```bash
unset OP_CONNECT_HOST OP_CONNECT_TOKEN
op user get --me
```

Do not do this in a shell that is intentionally configured for Connect. For full CRUD through Connect itself, consult the Connect API; the limited CLI integration is a different interface. [S05]

### Required access

For these service-account workflows, the target vault needs `read_items` for reads and `read_items,write_items` for writes. `write_items` depends on `read_items`. `share_items` is separate and is not needed for ordinary CRUD. [S07]

Service accounts cannot access the built-in Personal/Private/Employee vault or the default Shared vault. Use a permitted custom vault. Existing service-account vault grants and permissions cannot be expanded in place: create a replacement service account with the needed access if necessary. [S02]

A successful identity check proves authentication, not write permission. A successful read does not prove permission to create, edit, or delete.

## 3. Select a vault and identify items

List accessible vaults and use the returned ID: [S08]

```bash
op vault list --format=json | jq '.[] | {id, name}'

VAULT_ID='REPLACE_WITH_VAULT_ID'
op vault get "$VAULT_ID" --format=json | jq '{id, name}'
```

Prefer IDs in automation. Titles can be duplicated or renamed; an item's ID remains stable until it is moved to a different vault. Always scope these examples to a vault, including when using item IDs. [S03][S06]

```bash
op item list --vault "$VAULT_ID" --format=json |
  jq '.[] | {id, title, category}'

# Choose an existing item's ID when reading, updating, or deleting it.
ITEM_ID='REPLACE_WITH_ITEM_ID'
```

Useful inventory filters: [S09]

```bash
op item list --vault "$VAULT_ID" --categories 'Login,Password' --format=json
op item list --vault "$VAULT_ID" --tags 'myapp' --format=json
op item list --vault "$VAULT_ID" --include-archive --format=json
```

An inventory is not a full export of every item's secret fields. Fetch an individual item with `item get` or a field with `read` when you need its value. Treat names and metadata as potentially confidential too.

## 4. Fields, JSON, and safe secret handling

An item belongs to a **category** such as Login, Password, API Credential, Secure Note, Database, or SSH Key. Items contain built-in fields and optional custom fields, which may belong to sections. Discover the actual template instead of guessing a category's built-in field IDs: [S10]

```bash
op item template list
op item template get 'API Credential'
op item template get 'Login' |
  jq '.fields[] | {id, label, type, purpose}'
```

### Assignment syntax

The literal assignment shape is `[section.]field[fieldType]=value`; section and type are optional. These examples contain only non-secret values:

```text
username=worker@example.invalid
Connection.host[text]=db.internal.example
Connection.port[text]=5432
```

For built-in fields, use the template's field ID and omit the type, for example `username=...`. For custom fields, common mappings are: [S10]

| Assignment type | JSON field type | Use |
| --- | --- | --- |
| `password` | `CONCEALED` | Password or API token |
| `text` | `STRING` | Ordinary text |
| `email` | `EMAIL` | Email address |
| `url` | `URL` | URL field |
| `date` | `DATE` | Date, `YYYY-MM-DD` |
| `monthYear` | `MONTH_YEAR` | Month/year |
| `phone` | `PHONE` | Telephone number |
| `otp` | `OTP` | `otpauth://` seed URI |
| `file` | Not a JSON field type | Attachment path; assignment input only |

Quote entire assignments in the shell. Escape literal `.`, `=`, and `\` in section/field **names** using a backslash; do not apply those name-escaping rules to values. Example: `'Connection.host\.name[text]=db.internal.example'`. [S11]

### Put sensitive values in JSON input

Avoid `password=REAL_SECRET`, `--arg secret "$SECRET"`, or similar process arguments. Shell expansion still places the resulting value in an argument even when you use a variable. 1Password recommends JSON templates for sensitive assignments. [S11][S12]

Use one of these paths:

- A protected JSON file supplied with `--template`.
- JSON supplied through standard input.
- A secret file read by `jq --rawfile`, then serialized to JSON.

`CONCEALED` controls field display; it does not make plaintext input, full JSON output, or a resolved file safe to log. Handle all full item JSON as secret-bearing. Human-readable concealment and `op run` output masking are different features. [S13][S14]

## 5. Create secrets

### A. Create a Login with a generated password

This generates the password inside `op`; the password is not passed as an argument. It prints only the created item ID through `jq`:

```bash
ITEM_ID="$(
  op item create \
    --vault "$VAULT_ID" \
    --category Login \
    --title 'myapp-worker' \
    --url 'https://app.example.invalid/login' \
    --tags 'myapp,development' \
    --generate-password='letters,digits,symbols,32' \
    'username=worker@example.invalid' \
    'Connection.host[text]=db.internal.example' \
    --format=json |
  jq -er '.id'
)"
printf 'Created item: %s\n' "$ITEM_ID"
```

Password generation supports Login and Password items. A recipe selects character classes and a length from 1–64; the documented default is 32 characters using letters, digits, and symbols. `--dry-run` previews a create without saving it. Preview output can still contain sensitive data. [S11][S13]

For example, preview an independent dummy item:

```bash
op item create --vault "$VAULT_ID" --category Password \
  --title 'preview-only' --generate-password='letters,digits,40' \
  --dry-run --format=json |
  jq '{title, category}'
```

A generated preview password is not a reservation of the password for a later command. A later create generates its own value.

### B. Create an API token or other existing text secret

This stores an existing UTF-8 text secret in a custom concealed `token` field on a Secure Note. `SECRET_FILE` must already contain the intended value and be protected on disk. The file's contents, including any final newline, are preserved by `--rawfile`. [S15][S16]

```bash
SECRET_FILE='/secure/path/to/api-token.txt'

ITEM_ID="$(
  set -euo pipefail
  set +x
  umask 077
  : "${VAULT_ID:?Set VAULT_ID}"
  test -r "$SECRET_FILE"
  secret_work_dir="$(mktemp -d "${TMPDIR:-/tmp}/op-create.XXXXXXXX")"
  trap 'rm -rf -- "$secret_work_dir"' EXIT

  jq -n --rawfile secret "$SECRET_FILE" '{
    title: "myapp-api-token",
    category: "SECURE_NOTE",
    fields: [
      {label: "token", type: "CONCEALED", value: $secret}
    ]
  }' > "$secret_work_dir/item.json"

  op item create - --vault "$VAULT_ID" --format=json \
    < "$secret_work_dir/item.json" |
    jq -er '.id'
)"
printf 'Created item: %s\n' "$ITEM_ID"
```

The JSON serializer handles quotes, backslashes, and multiline text. Do not manually interpolate an arbitrary secret into JSON. Remove the source secret file when your workflow no longer needs it; the cleanup above only removes the temporary JSON directory.

To read this example's field later:

```bash
op read "op://$VAULT_ID/$ITEM_ID/token"
```

That command prints the actual secret. See section 6 for reads that do not print to the terminal.

### C. Create using a category template and editor

For a category with several built-in fields, fetch its template and fill in the relevant field `value` properties. Preserve the category, field IDs, types, and purposes supplied by the template. [S11][S15]

```bash
(
  set -euo pipefail
  set +x
  umask 077
  secret_work_dir="$(mktemp -d "${TMPDIR:-/tmp}/op-template.XXXXXXXX")"
  trap 'rm -rf -- "$secret_work_dir"' EXIT

  op item template get 'API Credential' \
    --out-file "$secret_work_dir/item.json"

  # Substitute a trusted local editor; account for its backups/swap files.
  vi "$secret_work_dir/item.json"
  jq -e 'type == "object" and (.fields | type == "array")' \
    "$secret_work_dir/item.json" > /dev/null

  op item create --vault "$VAULT_ID" --title 'myapp-integration' \
    --template "$secret_work_dir/item.json" --format=json |
    jq '{id, title, vault: .vault.id}'
)
```

Do not combine `--template` with piped JSON input. If you combine a template with field assignments, the assignments override the template's corresponding values. [S11]

## 6. Read secrets

### Read an item or selected fields

```bash
# Human-readable output; concealed fields are hidden by default on current CLI.
op item get "$ITEM_ID" --vault "$VAULT_ID" --format=human-readable

# Explicitly reveal sensitive values to the terminal.
op item get "$ITEM_ID" --vault "$VAULT_ID" --reveal --format=human-readable

# Select fields; this can expose their values.
op item get "$ITEM_ID" --vault "$VAULT_ID" \
  --fields 'label=username,label=password' --format=json
```

`--fields` supports label or type filters, such as `type=concealed`. Use it on an item that actually has the selected fields. For one precise value, prefer `op read`. [S09]

Inspect structure without printing the `value` properties:

```bash
op item get "$ITEM_ID" --vault "$VAULT_ID" --format=json |
  jq '{id, title, category, fields: [.fields[] | {
    id, label, type, section, reference
  }]}'
```

Full JSON still passes through the pipe. Do not add `tee`, command tracing, or debug logging to secret-bearing pipelines.

### Read one field by secret reference

```text
op://vault/item/field
op://vault/item/section/field
```

Each component can use a name or ID. References are case-insensitive. Supported name characters are alphanumerics, spaces, `.`, `_`, and `-`; use IDs for components containing other characters. Quote references, especially spaces and query strings. Use section IDs/names to disambiguate fields with matching labels. [S17]

```bash
# Password field on a Login/Password item.
op read "op://$VAULT_ID/$ITEM_ID/password"

# Custom field inside a named section.
op read "op://$VAULT_ID/$ITEM_ID/Connection/host"

# Avoid the extra output newline added by op read.
op read --no-newline "op://$VAULT_ID/$ITEM_ID/password"

# Save directly to a new protected file instead of printing the secret.
op read --no-newline --file-mode 0600 --out-file ./password.secret \
  "op://$VAULT_ID/$ITEM_ID/password"
```

`read` resolves a reference; it does not create or update anything. `--no-newline` suppresses the extra output newline, not newlines that are part of the stored value. The output-file default mode is `0600`; use filesystem permissions appropriate to your OS. [S18]

For text secrets where trailing newlines do not matter, capture the value without displaying it:

```bash
set +x
SECRET_VALUE="$(op read --no-newline "op://$VAULT_ID/$ITEM_ID/password")"
# Consume it without logging it or putting it in process arguments.
unset SECRET_VALUE
```

Bash command substitution removes trailing newlines. Use a file or stream when exact text preservation matters.

### OTP codes and SSH keys

For an item with an existing OTP field or SSH private key: [S18]

```bash
op item get "$ITEM_ID" --vault "$VAULT_ID" --otp
op read "op://$VAULT_ID/$ITEM_ID/one-time password?attribute=otp"

op read --out-file ./id_ed25519 --file-mode 0600 \
  "op://$VAULT_ID/$ITEM_ID/private key?ssh-format=openssh"
```

Change labels to the fields actually present on your item. An OTP seed URI is itself a secret; write it through a JSON template rather than a literal shell assignment.

## 7. Update secrets

### Update metadata and non-secret fields

```bash
op item edit "$ITEM_ID" --vault "$VAULT_ID" \
  --title 'myapp-worker-production' \
  --tags 'myapp,production' \
  --url 'https://app.example.invalid/login' \
  'Connection.host[text]=db.production.example' > /dev/null
```

Use `--url` with a compatible item category. `--tags` replaces the tag list; it is not an append operation. `--tags ''` clears tags. An assignment can create a missing custom field or section. Review misspellings so an intended update does not silently become a new field. [S09][S12]

Preview a metadata change:

```bash
op item edit "$ITEM_ID" --vault "$VAULT_ID" \
  --title 'proposed-title' --dry-run --format=json |
  jq '{id, title}'
```

### Replace one secret field using a fresh JSON snapshot

**Passkey limitation:** do not use this JSON round-trip workflow on an item containing a passkey. 1Password explicitly warns that updating such an item with a JSON template overwrites its passkey. Use an appropriate supported editing method for that item instead. [S12]

Set `FIELD_ID` from the structural output in section 6. For a built-in Login password it is `password`; a custom token field normally has its own generated ID.

```bash
FIELD_ID='password'
SECRET_FILE='/secure/path/to/replacement-secret.txt'

(
  set -euo pipefail
  set +x
  umask 077
  : "${VAULT_ID:?Set VAULT_ID}"
  : "${ITEM_ID:?Set ITEM_ID}"
  : "${FIELD_ID:?Set FIELD_ID}"
  test -r "$SECRET_FILE"
  secret_work_dir="$(mktemp -d "${TMPDIR:-/tmp}/op-edit.XXXXXXXX")"
  trap 'rm -rf -- "$secret_work_dir"' EXIT

  op item get "$ITEM_ID" --vault "$VAULT_ID" --format=json \
    > "$secret_work_dir/current.json"

  jq --arg field "$FIELD_ID" --rawfile secret "$SECRET_FILE" '
    if ([.fields[] | select(.id == $field)] | length) != 1 then
      error("Expected exactly one matching field ID")
    else
      (.fields[] | select(.id == $field) | .value) = $secret
    end
  ' "$secret_work_dir/current.json" > "$secret_work_dir/updated.json"

  op item edit "$ITEM_ID" --vault "$VAULT_ID" \
    --template "$secret_work_dir/updated.json" --format=json |
    jq '{id, title, updated_at}'

  # Verify exact text without printing it.
  op read --no-newline \
    --out-file "$secret_work_dir/readback.secret" \
    "op://$VAULT_ID/$ITEM_ID/$FIELD_ID"
  cmp -s "$SECRET_FILE" "$secret_work_dir/readback.secret"
  printf 'Secret replacement verified.\n'
)
```

This retains the fetched item's other JSON fields and changes only the selected value in that snapshot. Perform the fetch and write close together and serialize competing writers; this is not an atomic field patch or a guarantee against concurrent changes. Do not use a blank category template as a replacement for an existing item's complete representation.

Alternatively, after generating a complete updated JSON file, pipe it to `op item edit ITEM_ID --vault VAULT_ID`. `item edit` accepts the JSON through stdin while the positional argument identifies the existing item. Do not also pass `--template`. [S12]

### Generate a replacement password

For a suitable Login or Password item:

```bash
op item edit "$ITEM_ID" --vault "$VAULT_ID" \
  --generate-password='letters,digits,symbols,40' > /dev/null
```

This changes the stored password in 1Password. It does not change the credential at your database, website, or API provider. Coordinate provider-side rotation and application reloads separately.

### Delete a custom field or clear a built-in field

```bash
# Remove a custom field.
op item edit "$ITEM_ID" --vault "$VAULT_ID" \
  'Connection.host[delete]' > /dev/null

# Clear a built-in field on a compatible item.
op item edit "$ITEM_ID" --vault "$VAULT_ID" 'username=' > /dev/null
```

Deleting the last field in a custom section removes the section. Built-in fields cannot be deleted through this mechanism; clear their values instead. [S09]

## 8. Archive, delete, and restore

First inspect the target ID and title. This prints only selected metadata:

```bash
op item get "$ITEM_ID" --vault "$VAULT_ID" --format=json |
  jq '{id, title, vault: .vault.id}'
```

Choose the intended action:

```bash
# Keep the item in Archive.
op item delete "$ITEM_ID" --vault "$VAULT_ID" --archive
```

```bash
# Delete the item.
op item delete "$ITEM_ID" --vault "$VAULT_ID"
```

Archived items can remain in Archive indefinitely. Deleted items remain in Recently Deleted for **30 days**, unless permanently destroyed earlier. Restore archived/deleted items or permanently destroy deleted items through the 1Password apps or 1Password.com. The documented `op item` command set does not provide a restore subcommand. [S19]

To inspect archived items:

```bash
op item list --vault "$VAULT_ID" --include-archive --format=json
op item get "$ITEM_ID" --vault "$VAULT_ID" --include-archive
```

**Archiving is not credential revocation:** archived items can still be retrieved by ID or with archive-inclusive reads. Deleting a stored API token also does not revoke that token at its issuer. Revoke or rotate the actual credential at the provider when necessary. [S09]

For bulk deletion, prepare and review a file containing one intended item ID per line, then deliberately run:

```bash
op item delete - --vault "$VAULT_ID" < reviewed-item-ids.txt
```

Avoid an unreviewed broad list-to-delete pipeline. The item-delete reference does not document a `--dry-run` flag. [S09]

## 9. Move or copy items

Use the dedicated move command and accessible source/destination vaults:

```bash
DESTINATION_VAULT_ID='REPLACE_WITH_DESTINATION_VAULT_ID'

op item move "$ITEM_ID" \
  --current-vault "$VAULT_ID" \
  --destination-vault "$DESTINATION_VAULT_ID" \
  --format=json |
  jq '{id, title, vault: .vault.id}'
```

A move copies the item into the destination and deletes the original, producing a **new item ID**. Update stored IDs and secret references after moving; the destination's access rules also apply. Do not treat `item edit --vault` as the documented move interface. [S09]

You can also create a separate copy from item JSON: [S11]

```bash
op item get "$ITEM_ID" --vault "$VAULT_ID" --format=json |
  op item create - --vault "$DESTINATION_VAULT_ID" \
    --title 'myapp-copy' --format=json |
  jq '{id, title, vault: .vault.id}'
```

Treat this as JSON-based duplication, not a lossless backup strategy for every item feature; the passkey limitation still matters.

## 10. Use secrets in applications

### Environment variables with `op run`

For an item containing a password field:

```bash
export DB_PASSWORD="op://$VAULT_ID/$ITEM_ID/password"
op run -- php ./worker.php
unset DB_PASSWORD
```

Replace the executable with your application's command. The exported value is a reference; the child process receives the resolved value. An already running process does not automatically receive later secret changes. [S20]

Alternatively, store references in `app.env`:

```dotenv
DB_USERNAME="op://Application Secrets/myapp-worker/username"
DB_PASSWORD="op://Application Secrets/myapp-worker/password"
```

```bash
op run --env-file ./app.env -- php ./worker.php
```

A file containing only references can be versioned if its names/metadata are acceptable to disclose. Never put `OP_SERVICE_ACCOUNT_TOKEN` or plaintext secret values in that committed file.

`op run` masks resolved secrets on stdout/stderr by default. `--no-masking` and `OP_RUN_NO_MASKING` can disable masking. Masking is not a security boundary: processes still receive plaintext secrets, and same-user processes may access process environments. [S14][S20]

If a shell must expand a resolved variable, expand it **inside** the child shell:

```bash
DB_PASSWORD="op://$VAULT_ID/$ITEM_ID/password" \
  op run -- sh -c 'test -n "$DB_PASSWORD"'
```

Putting `"$DB_PASSWORD"` directly in the parent command's arguments causes the parent shell to expand it before `op run` resolves the reference. Environment files override exported variables; when several `--env-file` options define the same variable, the last file wins. [S14]

### Template substitution with `op inject`

For example, a plain-text template `token.txt.tpl` can contain:

```text
{{ op://Application Secrets/myapp-api-token/token }}
```

```bash
op inject --in-file ./token.txt.tpl --out-file ./token.txt --file-mode 0600
```

The output contains the actual secret. Keep generated files out of source control and delete them when no longer required. Without an output file, `inject` writes resolved content to stdout. [S21][S22]

For JSON, YAML, shell code, or connection URLs, treat injection as text substitution: arbitrary secret characters may need format-specific encoding. Use an appropriate serializer or environment variables when unrestricted values could break the target syntax. `inject` does not write anything back to the vault.

## 11. Store and retrieve files

Use **Document items** for file payloads and **attachments** for files associated with an ordinary item. The current service-account CLI guide lists `op document` as supported; do not assume documents are categorically unavailable to service accounts. Vault permissions still apply. [S06]

### Document CRUD

```bash
DOCUMENT_ID="$(
  op document create ./service-config.json \
    --vault "$VAULT_ID" --title 'myapp-service-config' \
    --file-name service-config.json --format=json |
    jq -er '.id'
)"

op document list --vault "$VAULT_ID" --format=json

op document get "$DOCUMENT_ID" --vault "$VAULT_ID" \
  --out-file ./downloaded-service-config.json --file-mode 0600

op document edit "$DOCUMENT_ID" ./updated-service-config.json \
  --vault "$VAULT_ID" --file-name service-config.json > /dev/null

op document delete "$DOCUMENT_ID" --vault "$VAULT_ID" --archive
```

Use a new download path. `document edit` replaces the file payload. Create/edit also accept file bytes on stdin using `-`. [S23]

The document command reference describes this separate command as **permanent deletion**:

```bash
op document delete "$DOCUMENT_ID" --vault "$VAULT_ID"
```

There is inconsistent published wording between that reference and the general item-deletion policy. Do not assume a 30-day recovery guarantee for this document command; use archive if recovery is required, or verify the behavior for your installed version with 1Password before relying on it. [S19][S23]

### Attachments

Example for an existing item:

```bash
op item edit "$ITEM_ID" --vault "$VAULT_ID" \
  'client\.pem[file]=/secure/path/to/client.pem' > /dev/null

op read "op://$VAULT_ID/$ITEM_ID/client.pem" \
  --out-file ./downloaded-client.pem --file-mode 0600
```

Escape the period in the **assignment field name**, as shown; the reference uses the actual filename. Attachment input is a file path, not inline file contents. For exact binary payloads, prefer document/attachment file operations over shell variables. [S10][S11][S17]

## 12. Automation and error handling

Use explicit `--format=json` for machine parsing, and select only the metadata you intend to log. `OP_FORMAT` can change defaults, so do not depend on an inherited output format. [S03][S04]

Practical patterns for scripts:

- Stop after an authentication, fetch, JSON parsing, or write failure. Do not hide every error with `|| true`.
- Use exact IDs and vault scope; a not-found result is not sufficient evidence that an item should be created.
- Keep the ID returned by create. Re-running create is not an upsert and can produce another item with the same title.
- If a create times out, determine whether it succeeded before retrying. A blind retry can create duplicates.
- Serialize concurrent writers to an item. Retrying a full JSON snapshot can reapply stale values.
- Re-fetch after a write when correctness matters; compare values without logging them, as in section 7.
- Treat `--dry-run` as a preview, not proof of write/delete permission or an end-to-end test.
- Use a job's secret store to inject the existing token. Do not commit it, dump the environment, or enable shell tracing around secret use.

Check service-account usage when throttled:

```bash
op service-account ratelimit
```

There are separate hourly read/write limits and an account-wide daily request limit; one CLI command can make multiple requests. Use IDs, reduce redundant calls, and apply bounded backoff for transient failures. Consult the current rate-limit page for your plan's numeric limits instead of hardcoding them into a runbook. [S07][S24]

Manage token expiration, rotation, or revocation on the service-account page in 1Password.com. Rotation retains the service account's permissions; changing access requires a new service account. Unsetting a local variable is not token revocation. [S25]

## 13. Optional live CRUD verification

This **performs writes** in the test vault you choose. It creates one disposable Password item, checks a read, updates and reads a custom field, deletes that item, and checks that the ID is absent from the successful archive-inclusive list. It prints IDs/status only.

Save this block as a Bash script, replace the vault placeholder, and run it deliberately. If it stops early, use the printed item ID to inspect or clean up that specific test item. The deletion step is intentionally explicit, not an exit trap.

```bash
#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

: "${OP_SERVICE_ACCOUNT_TOKEN:?Token must already be exported}"
if [[ -n "${OP_CONNECT_HOST:-}" || -n "${OP_CONNECT_TOKEN:-}" ]]; then
  printf 'Choose service-account authentication before this test.\n' >&2
  exit 1
fi

VAULT_ID='REPLACE_WITH_A_PERMITTED_TEST_VAULT_ID'
command -v op > /dev/null
command -v jq > /dev/null
op user get --me > /dev/null

test_title="op-crud-check-$(date -u +%Y%m%dT%H%M%SZ)-$$"
test_item_id="$(
  op item create --vault "$VAULT_ID" --category Password \
    --title "$test_title" --generate-password='letters,digits,32' \
    --format=json |
    jq -er '.id'
)"
printf 'Created test item: %s\n' "$test_item_id"

password_size="$(
  op read --no-newline "op://$VAULT_ID/$test_item_id/password" | wc -c
)"
[[ "$password_size" -eq 32 ]]

op item edit "$test_item_id" --vault "$VAULT_ID" \
  'crud_check[text]=updated' > /dev/null
[[ "$(op read "op://$VAULT_ID/$test_item_id/crud_check")" == 'updated' ]]

op item delete "$test_item_id" --vault "$VAULT_ID"
op item list --vault "$VAULT_ID" --include-archive --format=json |
  jq -e --arg id "$test_item_id" 'all(.[]; .id != $id)' > /dev/null

printf 'PASS: create, read, update, and delete completed.\n'
```

This is an operational check for your installed CLI, token, vault, and network. It does not verify passkeys, Documents, provider-side credential rotation, or every optional feature in this guide.

## 14. Troubleshooting

| Symptom | Check or action |
| --- | --- |
| `op: command not found` | Install the official CLI and confirm the executable is on the current process's `PATH`. [S01] |
| Unexpected sign-in or biometric prompt | Confirm the intended token is exported in this shell, container, or CI step; a variable in another process is not automatically available here. [S04][S06] |
| Wrong authentication backend | Check whether Connect variables are overriding the service-account token. [S06] |
| Reads work; writes fail | Check `write_items` on the target vault and whether you are using the read-oriented Connect CLI integration. [S05][S07] |
| Vault unavailable | Confirm its ID, the service account's immutable grants, supported vault type, and whether service-account access is disabled for that vault. [S02][S25] |
| Ambiguous or missing item | Use its ID and an explicit vault; account for Archive and any prior move. [S03][S09] |
| Field missing or a new field appeared | Check the category template, exact field ID, section, and assignment spelling. [S10][S12] |
| Reference fails with punctuation in a name | Use the relevant component ID; do not assume URL percent-encoding bypasses the documented character restrictions. [S17] |
| Secret is visible despite no `--reveal` | JSON, `op read`, resolved files, and other output paths must be treated as plaintext; human-readable concealment is not universal redaction. [S13][S17][S18] |
| Updated value rejected by the application | Check source-file newlines, application reloads, reference target, and provider-side rotation. |
| Rate-limit error | Inspect `op service-account ratelimit`, reduce calls, and wait/back off according to the applicable limit. [S24] |
| Unknown flag/subcommand | Check the local `--help`, installed version, and current official reference. Do not mix CLI 1 and CLI 2 examples. [S03] |
| Passkey disappeared after JSON edit | Restore an earlier item version using 1Password's supported recovery UI; avoid further JSON-template edits on that item. [S12] |

## 15. Accuracy notes and official sources

The examples intentionally follow the current command reference when a tutorial contains conflicting wording:

- **Vault selection:** the item reference defines `item edit --vault` as the vault containing the item. This guide uses the dedicated `item move` command for moves, even though the edit tutorial also describes changing vaults with `--vault`. [S09][S12]
- **Vault scope:** the service-account guide requires explicit scope when multiple vaults are accessible, while the item-get reference states it more broadly. This guide always supplies the vault. [S06][S09]
- **Field deletion:** the item reference clearly distinguishes custom-field deletion from clearing built-in fields. Its syntax is used here. [S09]
- **Documents:** current documentation lists service-account support, but the document-delete reference's permanence wording conflicts with the broader deletion policy. The guide flags that uncertainty instead of promising recovery. [S06][S19][S23]
- **Passkeys and JSON:** the warning about passkey loss is explicit in official documentation. JSON templates are not a universally lossless editing format. [S12]

The shell workflows and sample names are original examples built from the documented interfaces. The verification here establishes source alignment and local syntax/JSON correctness; it does not establish account-specific permissions or live server behavior.

### Source register

All links below are official 1Password documentation except the separately identified official `jq` manual. The legacy `developer.1password.com/docs/...` documentation URLs redirected to `www.1password.dev/...` during verification.

| ID | Official source | What was checked |
| --- | --- | --- |
| S01 | [Get started with 1Password CLI][S01] | Installation and executable/version check |
| S02 | [Get started with Service Accounts][S02] | Version floor, vault restrictions, immutable grants, Environments access |
| S03 | [CLI reference][S03] | Global flags, IDs, output formats, current command structure |
| S04 | [CLI environment variables][S04] | Authentication and output-related variable names |
| S05 | [Use CLI with a Connect server][S05] | Documented Connect-backed CLI command subset |
| S06 | [Use service accounts with CLI][S06] | Token authentication, identity check, precedence, supported commands |
| S07 | [Service-account command reference][S07] | Permission names and rate-limit command |
| S08 | [Vault command reference][S08] | Vault discovery and lookup |
| S09 | [Item command reference][S09] | CRUD, filtering, flags, fields, movement, archive scope |
| S10 | [Item fields][S10] | Built-in identifiers and custom field types |
| S11 | [Create items][S11] | Generated passwords, assignments, templates, stdin, attachments |
| S12 | [Edit items][S12] | JSON update workflow, input methods, passkey limitation |
| S13 | [CLI release notes][S13] | Human-readable concealment and dry-run behavior |
| S14 | [`op run` reference][S14] | Child environment, masking, expansion order, precedence |
| S15 | [Item JSON template][S15] | JSON structure, optional/generated field IDs, sections |
| S16 | [Official jq manual][S16] | `--rawfile`, `--arg`, JSON mutation, raw output, exit status |
| S17 | [Secret reference syntax][S17] | Name/ID paths, character rules, references, field/file addressing |
| S18 | [`op read` reference][S18] | Exact read flags, OTP, SSH format, output files |
| S19 | [Archive and delete items][S19] | Archive retention, 30-day item recovery, restoration UI |
| S20 | [Load secrets into the environment][S20] | `.env` references, runtime injection, process-environment limits |
| S21 | [`op inject` reference][S21] | Template input/output and file-mode flags |
| S22 | [Load secrets into config files][S22] | Generated plaintext files and cleanup |
| S23 | [Document command reference][S23] | File CRUD, output files, document deletion wording |
| S24 | [Service-account rate limits][S24] | Hourly/daily scopes and request-count behavior |
| S25 | [Manage service accounts][S25] | Access inspection, rotation, revocation, vault access controls |

[S01]: https://www.1password.dev/cli/get-started
[S02]: https://www.1password.dev/service-accounts/get-started
[S03]: https://www.1password.dev/cli/reference
[S04]: https://www.1password.dev/cli/environment-variables
[S05]: https://www.1password.dev/connect/cli
[S06]: https://www.1password.dev/service-accounts/use-with-1password-cli
[S07]: https://www.1password.dev/cli/reference/management-commands/service-account
[S08]: https://www.1password.dev/cli/reference/management-commands/vault
[S09]: https://www.1password.dev/cli/reference/management-commands/item
[S10]: https://www.1password.dev/cli/item-fields
[S11]: https://www.1password.dev/cli/item-create
[S12]: https://www.1password.dev/cli/item-edit
[S13]: https://www.1password.dev/cli/release-notes
[S14]: https://www.1password.dev/cli/reference/commands/run
[S15]: https://www.1password.dev/cli/item-template-json
[S16]: https://jqlang.org/manual/
[S17]: https://www.1password.dev/cli/secret-reference-syntax
[S18]: https://www.1password.dev/cli/reference/commands/read
[S19]: https://support.1password.com/archive-delete-items/
[S20]: https://www.1password.dev/cli/secrets-environment-variables
[S21]: https://www.1password.dev/cli/reference/commands/inject
[S22]: https://www.1password.dev/cli/secrets-config-files
[S23]: https://www.1password.dev/cli/reference/management-commands/document
[S24]: https://www.1password.dev/service-accounts/rate-limits
[S25]: https://www.1password.dev/service-accounts/manage-service-accounts
