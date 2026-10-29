---
name: gnupg-encryption-standards
description: Mandatory rules for any task that generates, inspects, imports, exports, trusts, rotates or uses OpenPGP keys with GnuPG 2 (gpg, gpgv, gpg-agent, gpgconf), including encrypting, decrypting, signing and verifying in scripts, CI, or agent-driven shell sessions.
---

# GnuPG Encryption Standards for AI Agents

This skill tells an agent how to drive **GnuPG 2.2+ (2.4 preferred)** safely and deterministically: which algorithms to choose, which flags keep it non-interactive, how to parse its output, how to decide whether a signature or key is acceptable, and how to fail closed.

Rule keywords: **MUST** / **MUST NOT** are hard requirements. **SHOULD** means follow unless the user gives an explicit, recorded reason not to.

---

## 1. Overview & Core Principles

### 1.1 Purpose

GnuPG is designed for a human at a terminal. Left at its defaults it will prompt, pop up pinentry dialogs, print output that changes between versions, consult the user's personal keyring, and fetch keys from the network. Each of these breaks or endangers automation. This skill removes all of them.

### 1.2 Core tenets

| # | Tenet | What it means in practice |
|---|-------|---------------------------|
| 1 | **Automation safety** | Every invocation is non-interactive (`--batch`), produces machine-readable output (`--with-colons`, `--status-fd`), and is judged by status lines plus exit code, never by exit code alone. |
| 2 | **Key isolation** | The agent works in its own `--homedir`. It never reads or writes `~/.gnupg` unless the user explicitly asks it to operate on their personal keyring. |
| 3 | **Identity by fingerprint** | Keys are always addressed by full 40-hex-character (v4) fingerprint. Never by email, name, or short/long key ID. |
| 4 | **Modern cryptography** | Ed25519 / Cv25519 by default. RSA-4096 only when a named legacy consumer requires it. |
| 5 | **Fail closed** | Any unexpected status line, missing expected status line, or non-zero exit is a failure. Partial output from a failed operation is deleted. |
| 6 | **Secrets never touch argv, logs, or stdout** | Passphrases go through file descriptors; private key material goes only to `0600` files the user asked for. |

### 1.3 Environment isolation with `--homedir`

**MUST** create a dedicated home directory per task (ephemeral) or per service identity (persistent).

```bash
# Ephemeral, per-task homedir
GNUPGHOME="$(mktemp -d -t gnupg.XXXXXX)"
chmod 700 "$GNUPGHOME"
export GNUPGHOME          # or pass --homedir "$GNUPGHOME" on every call

# ... work ...

# Teardown: stop daemons bound to this homedir, then remove it
gpgconf --homedir "$GNUPGHOME" --kill all
rm -rf -- "$GNUPGHOME"
```

Rules:

- **MUST** set permissions to `700` on the homedir; gpg warns ("unsafe permissions") and some operations misbehave otherwise.
- **MUST** pass the same `--homedir` (or `GNUPGHOME`) to `gpg`, `gpgconf`, `gpg-connect-agent` and `gpgv`, or they will talk to the wrong agent/keyring.
- **SHOULD** keep the homedir path short. gpg-agent sockets live in the homedir when `/run/user/$UID` is unavailable, and Unix socket paths are limited to roughly 108 bytes. Symptom of a too-long path: `can't connect to the agent: File name too long`.
- **MUST** kill the agent (`gpgconf --kill all`) before deleting an ephemeral homedir, otherwise orphaned `gpg-agent`/`keyboxd` processes remain.
- On GnuPG 2.4.1+, a homedir may use `keyboxd` (`use-keyboxd` in `common.conf`). Do not assume `pubring.kbx` exists; always go through `gpg` to export keys rather than copying keyring files.

### 1.4 Baseline configuration files

Write these into every agent-owned homedir before first use.

`$GNUPGHOME/gpg.conf`

```text
# Output stability
keyid-format none
with-fingerprint
with-subkey-fingerprint
charset utf-8
no-comments
no-emit-version
no-greeting

# No surprise network access or key fetching
no-auto-key-retrieve
auto-key-locate local
keyserver-options no-honor-keyserver-url

# Algorithm preferences
personal-cipher-preferences AES256 AES192 AES
personal-digest-preferences SHA512 SHA384 SHA256
personal-compress-preferences ZLIB BZIP2 ZIP Uncompressed
default-preference-list SHA512 SHA384 SHA256 AES256 AES192 AES ZLIB BZIP2 ZIP Uncompressed
cert-digest-algo SHA512
s2k-digest-algo SHA512
s2k-cipher-algo AES256

# Safety
require-cross-certification
no-symkey-cache
```

`$GNUPGHOME/gpg-agent.conf`

```text
allow-loopback-pinentry
default-cache-ttl 300
max-cache-ttl 900
```

Notes:

- `no-auto-key-retrieve` stops `--verify` from contacting keyservers or WKD when it sees an unknown issuer, which would both leak metadata and introduce unvetted keys.
- `no-symkey-cache` stops symmetric passphrases being cached in the agent.
- After editing `gpg-agent.conf` on a running agent: `gpgconf --homedir "$GNUPGHOME" --reload gpg-agent`.

---

## 2. Modern Cryptographic Standards & Key Architecture

### 2.1 Algorithm selection

| Role | Default (MUST use unless overridden) | Legacy fallback (only when a named consumer requires it) | Forbidden |
|------|--------------------------------------|----------------------------------------------------------|-----------|
| Primary (certify) | `ed25519` | `rsa4096` | DSA, ElGamal, RSA < 4096, `nistp*`/`brainpool*` without a stated compliance reason |
| Signing subkey | `ed25519` | `rsa4096` | same |
| Encryption subkey | `cv25519` (X25519/ECDH) | `rsa4096` | ElGamal, RSA < 4096 |
| Authentication subkey | `ed25519` | `rsa4096` | same |
| Symmetric cipher | AES-256 | AES-128/192 | 3DES, CAST5, IDEA, Blowfish |
| Digest | SHA-512 / SHA-256 | SHA-384 | MD5, SHA-1 (for new signatures) |

Algorithm decision logic:

```text
IF user explicitly requires RSA for a named system (e.g. old appliance, legacy gpg 1.4 recipient)
    -> use rsa4096 for every key and subkey; record the reason in the task output
ELSE IF user explicitly requests post-quantum and GnuPG >= 2.5 and every recipient's
        implementation supports the same composite ML-KEM (Kyber) + X25519 scheme
    -> add a PQC encryption subkey alongside (not instead of) the cv25519 one
ELSE
    -> ed25519 (cert/sign/auth) + cv25519 (encr)
```

Interoperability note: the OpenPGP ecosystem is split between RFC 9580 ("crypto refresh") and LibrePGP (which GnuPG follows). Version 4 keys with Ed25519/Cv25519 work everywhere that matters. **MUST NOT** opt into experimental key/packet versions or AEAD modes (`--force-aead`, v5 keys) unless the user confirms every consumer supports them.

### 2.2 Key architecture: certify-only primary + isolated subkeys

**MUST** generate keys in this shape:

```text
pub  ed25519  [C]       primary: certification only, 2y expiry
sub  ed25519  [S]       signing,        1y expiry
sub  cv25519  [E]       encryption,     1y expiry
sub  ed25519  [A]       authentication, 1y expiry (only if SSH/auth is needed)
```

Why:

| Reason | Explanation |
|--------|-------------|
| Blast-radius control | A compromised signing subkey is revoked and replaced; the identity (primary fingerprint) and its accumulated trust survive. |
| Offline primary | The primary's secret can be moved offline. Day-to-day hosts hold only subkey secrets (`sec#` in listings). |
| Purpose separation | A key used for both signing and encryption can be abused cross-protocol; separate keys with single usage flags remove that class of risk. |
| Independent rotation | Subkeys rotate yearly without re-distributing a new identity. |

### 2.3 Expiry and rotation

| Object | Expiry | Rotation trigger |
|--------|--------|------------------|
| Primary key | 1–2 years (`2y`) | Extend (`--quick-set-expire`) before it lapses; it is not replaced unless compromised. |
| Subkeys | 1 year (`1y`) | Add new subkey ≥ 30 days before expiry, publish updated public key, let old one expire (or revoke if compromised). |
| Ephemeral/CI keys | Days to weeks (`30d`) | Regenerate per pipeline epoch. |

Rules:

- **MUST NOT** create keys with no expiry (`0` / `never`) unless the user explicitly asks and accepts the trade-off. Expiry is a dead-man switch: a lost key eventually stops being usable even if never revoked.
- Expiry is extendable by the primary-key holder, so short expiry costs nothing if the key is well managed.
- **SHOULD** check expiry from field 7 of colon output (epoch seconds) and warn when any usable subkey expires within 30 days.

```bash
# Extend primary key expiry
gpg --batch --pinentry-mode loopback --passphrase-fd 3 \
    --quick-set-expire "$FPR" 2y 3<"$PASSFILE"

# Extend all subkeys
gpg --batch --pinentry-mode loopback --passphrase-fd 3 \
    --quick-set-expire "$FPR" 1y '*' 3<"$PASSFILE"
```

After any change to a key, re-export and redistribute the **public** key; peers only see the new expiry after they import it.

---

## 3. Headless, Non-Interactive & Automation Flags

### 3.1 Required flags

Every agent invocation of `gpg` **MUST** include, at minimum:

```bash
gpg --homedir "$GNUPGHOME" --batch --no-tty --status-fd 2 ...
```

| Flag | Purpose | Failure if omitted |
|------|---------|--------------------|
| `--homedir DIR` | Use isolated keyring/agent | Touches user's personal keyring |
| `--batch` | Never prompt; fail instead | Process hangs waiting on stdin/tty |
| `--no-tty` | Never write to/read from the terminal | Garbled output, hangs under some runners |
| `--status-fd N` | Emit `[GNUPG:]` status lines on fd N | No reliable way to judge success |
| `--with-colons` (listing) | Stable parseable listing | Brittle regex on human output |
| `--yes` | Answer "yes" to overwrite questions (e.g. existing `--output` file) | Fails in batch mode when the output file exists |
| `--pinentry-mode loopback` | Let gpg take the passphrase from fd/file instead of a pinentry program | `Inappropriate ioctl for device` / `No pinentry` |
| `--passphrase-fd N` / `--passphrase-file F` | Supply passphrase without argv exposure | Hang or failure on protected keys |

`--yes` caution: it silently overwrites. Use it only together with an explicit `--output` path the agent itself chose; never with a path derived from untrusted input without validation.

### 3.2 Passphrase handling

Ranked from best to worst:

| Rank | Method | When |
|------|--------|------|
| 1 | No passphrase in the agent at all: key lives on a smartcard/HSM, or the user unlocks via their own agent | Interactive or user-attended work |
| 2 | `--passphrase-fd N` from a pipe or `0600` file | Automation with protected keys |
| 3 | `--passphrase-file PATH` (`0600`, on tmpfs, deleted after use) | When fd plumbing is impossible |
| 4 | Unprotected key (`--passphrase ''` / `%no-protection`) inside a locked-down, ephemeral homedir | Short-lived CI keys whose secrecy rests on the host |
| ✗ | `--passphrase "secret"` on the command line | **NEVER** — visible in `ps aux`, `/proc/*/cmdline`, shell history, CI logs |

`--pinentry-mode loopback` is required for ranks 2–4 with GnuPG 2.1+. The agent must allow it (`allow-loopback-pinentry`, the default since 2.1.12).

Bash, using a dedicated fd (keeps stdin free for data):

```bash
gpg --homedir "$GNUPGHOME" --batch --no-tty --status-fd 2 \
    --pinentry-mode loopback --passphrase-fd 3 \
    --output out.sig --detach-sign --local-user "$SIGN_FPR" in.bin \
    3<"$PASSFILE"
```

Bash, from a variable without touching argv (`printf` is a shell builtin, so it never appears in the process table):

```bash
gpg ... --pinentry-mode loopback --passphrase-fd 3 ... 3< <(printf '%s\n' "$PASSPHRASE")
```

Python:

```python
import os, subprocess

def run_gpg(args, passphrase: str | None, homedir: str, stdin=None):
    base = ["gpg", "--homedir", homedir, "--batch", "--no-tty", "--status-fd", "2"]
    pass_fds = ()
    r = None
    if passphrase is not None:
        r, w = os.pipe()
        os.write(w, passphrase.encode() + b"\n")  # small payload fits pipe buffer
        os.close(w)
        base += ["--pinentry-mode", "loopback", "--passphrase-fd", str(r)]
        pass_fds = (r,)
    try:
        return subprocess.run(base + args, input=stdin, pass_fds=pass_fds,
                              capture_output=True, check=False)
    finally:
        if r is not None:
            os.close(r)
```

Rules:

- **MUST NOT** echo, log, or include passphrases in error messages, task summaries, or files the user did not ask for.
- **MUST** run with `set +x` (no shell tracing) around any line that handles a passphrase.
- **MUST** delete passphrase files on exit (`trap 'rm -f -- "$PASSFILE"' EXIT`).
- Cached passphrases persist in gpg-agent for `default-cache-ttl`. To clear immediately: `gpgconf --homedir "$GNUPGHOME" --reload gpg-agent`.

---

## 4. Machine-Parseable Output & Scripting Interfaces

### 4.1 Never parse human-readable output

The output of `--list-keys`, `--fingerprint`, `--verify` (stderr text) and similar is localized, version-dependent, and reformatted between releases (spacing of fingerprints, date formats, bracket notation). **MUST NOT** use regex or column slicing on it in production code. Use:

| Need | Interface |
|------|-----------|
| Key data, validity, capabilities, fingerprints | `--with-colons` listing |
| Outcome of encrypt / decrypt / sign / verify / import | `--status-fd N` (`[GNUPG:] KEYWORD args`) |
| Exact configuration and versions | `gpgconf --list-components`, `gpg --with-colons --list-config` |

Always also set `LC_ALL=C` (or `LANG=C`) in the environment so any diagnostic text you log is predictable.

### 4.2 Colon-listing format

```bash
gpg --homedir "$GNUPGHOME" --batch --with-colons \
    --with-fingerprint --with-subkey-fingerprint --list-keys "$FPR"
```

Sample (truncated):

```text
tru::1:1793000000:1856000000:3:1:5
pub:u:255:22:AB12CD34EF56AB78:1793000000:1856072000::u:::cESCA:::::ed25519:::0:
fpr:::::::::0123456789ABCDEF0123456789ABCDEF01234567:
uid:u::::1793000000::5F3E...::Build Bot <bot@example.org>::::::::::0:
sub:u:255:22:1122334455667788:1793000000:1824536000:::::s::::::ed25519::
fpr:::::::::AAAA...40hex...AAAA:
sub:u:255:18:99AABBCCDDEEFF00:1793000000:1824536000:::::e::::::cv25519::
fpr:::::::::BBBB...40hex...BBBB:
```

Record types (field 1):

| Type | Meaning |
|------|---------|
| `pub` / `sec` | Public / secret primary key |
| `sub` / `ssb` | Public / secret subkey |
| `fpr` | Fingerprint of the immediately preceding key record (field 10) |
| `grp` | Keygrip of the preceding key (field 10) — names the file in `private-keys-v1.d/` |
| `uid` | User ID (field 10, C-escaped UTF-8) |
| `sig` / `rev` | Signature / revocation signature (with `--list-sigs`) |
| `tru` | Trust database info |
| `rvk` | Designated revoker |

Key fields:

| Field | Content | Notes |
|-------|---------|-------|
| 1 | Record type | see above |
| 2 | Validity | see table below |
| 3 | Key length in bits | 255 for Ed25519/Cv25519 |
| 4 | Public-key algorithm ID | 1=RSA, 16=ElGamal, 17=DSA, 18=ECDH, 19=ECDSA, 22=EdDSA |
| 5 | Key ID (64-bit) | **Do not** use as identifier; use `fpr` |
| 6 | Creation date | Epoch seconds |
| 7 | Expiration date | Epoch seconds; empty = none |
| 9 | Ownertrust (primary only) | same letters as validity |
| 10 | User ID / fingerprint / keygrip | depending on record type |
| 12 | Capabilities | lowercase `e s c a` = this (sub)key's own usage; uppercase on `pub` = what the key as a whole can currently do via any valid subkey (e.g. `cESCA` = certify-only primary with S/E/A subkeys); `D` = disabled |
| 15 | Secret key info (`sec`/`ssb`) | `+` secret available, `#` stub (secret absent, e.g. offline primary), `>` card serial |
| 17 | Curve name | `ed25519`, `cv25519`, … |

Validity letters (field 2):

| Code | Meaning | Agent decision |
|------|---------|----------------|
| `u` | Ultimate | usable |
| `f` | Full | usable |
| `m` | Marginal | usable only if policy allows marginal |
| `-` / `q` / `o` | Unknown / undefined / new | **not** usable for encryption without explicit trust decision |
| `n` | Never valid | reject |
| `e` | Expired | reject |
| `r` | Revoked | reject |
| `i` | Invalid | reject |
| `d` | Disabled | reject |

### 4.3 Parsing recipes

Primary fingerprint(s) matching a query:

```bash
gpg --homedir "$GNUPGHOME" --batch --with-colons --list-keys -- "$QUERY" |
  awk -F: '$1=="pub"{want=1; next} $1=="fpr" && want {print $10; want=0}'
```

Usable encryption subkey fingerprints (not expired/revoked/invalid/disabled):

```bash
gpg --homedir "$GNUPGHOME" --batch --with-colons \
    --with-subkey-fingerprint --list-keys -- "$FPR" |
  awk -F: '
    $1=="pub"            {want=0}
    $1=="sub"            {want = ($12 ~ /e/ && $2 !~ /[iderna]/)}
    $1=="fpr" && want    {print $10; want=0}'
```

Python parser:

```python
from dataclasses import dataclass, field

@dataclass
class Key:
    kind: str; validity: str; algo: int; created: int; expires: int | None
    caps: str; fpr: str = ""; curve: str = ""; uids: list[str] = field(default_factory=list)
    subkeys: list["Key"] = field(default_factory=list)

def parse_colons(text: str) -> list[Key]:
    keys, cur, last = [], None, None
    for line in text.splitlines():
        f = line.split(":")
        t = f[0]
        if t in ("pub", "sec", "sub", "ssb"):
            k = Key(kind=t, validity=f[1], algo=int(f[3] or 0),
                    created=int(f[5] or 0), expires=int(f[6]) if f[6] else None,
                    caps=f[11], curve=f[16] if len(f) > 16 else "")
            if t in ("pub", "sec"):
                cur = k; keys.append(k)
            else:
                cur.subkeys.append(k)
            last = k
        elif t == "fpr" and last is not None and not last.fpr:
            last.fpr = f[9]
        elif t == "uid" and cur is not None:
            cur.uids.append(f[9])
    return keys
```

### 4.4 Status-fd keywords the agent must understand

| Keyword | Meaning | Decision |
|---------|---------|----------|
| `GOODSIG <keyid> <uid>` | Cryptographically good signature | Necessary, not sufficient |
| `VALIDSIG <fpr> <date> <ts> <exp> <ver> <res> <algo> <hash> <class> <primary-fpr>` | Good sig with details; last field = primary fingerprint | **Pin against `<primary-fpr>`** |
| `BADSIG` | Signature does not match data | Reject, exit 1 |
| `ERRSIG <keyid> … <rc>` | Could not check (rc 9 = missing key) | Reject |
| `NO_PUBKEY <keyid>` | Signer key not in keyring | Reject; do **not** auto-fetch |
| `EXPSIG` | Signature itself expired | Reject |
| `EXPKEYSIG` | Signed by an expired key | Reject unless policy allows historical verification |
| `REVKEYSIG` | Signed by a revoked key | Reject |
| `TRUST_ULTIMATE` / `TRUST_FULLY` | Key validity high | Acceptable |
| `TRUST_MARGINAL` | Marginal | Policy-dependent |
| `TRUST_UNDEFINED` / `TRUST_NEVER` | Not trusted | Reject unless fingerprint is pinned out-of-band |
| `DECRYPTION_OKAY` | Decryption and integrity check succeeded | Required for success |
| `DECRYPTION_FAILED` | Decryption failed | Reject, delete output |
| `GOODMDC` / `BADMDC` | Integrity protection result | `BADMDC` = reject |
| `NO_SECKEY <keyid>` | No secret key for a recipient | Info; failure only if no `DECRYPTION_OKAY` |
| `INV_RECP <reason> <name>` | Invalid recipient (see §7.3) | Reject |
| `KEYEXPIRED <ts>` | A key involved is expired | Investigate |
| `IMPORT_OK` / `IMPORT_PROBLEM` / `IMPORT_RES` | Import result | Check counts in `IMPORT_RES` |
| `KEY_CREATED <type> <fpr>` | Key generation finished; gives the fingerprint | Capture fingerprint from here |
| `FAILURE <location> <code>` / `ERROR` | Operation failed | Reject |

---

## 5. Essential Command Reference Matrix

All commands assume the prefix:

```bash
G=(gpg --homedir "$GNUPGHOME" --batch --no-tty --status-fd 2)
P=(--pinentry-mode loopback --passphrase-fd 3)      # only when a protected secret key is used
```

and `3<"$PASSFILE"` appended when `P` is used.

### 5.1 Key generation

| Task | Command |
|------|---------|
| Interactive full generation (human only; agents do **not** use this) | `gpg --full-generate-key` |
| Certify-only primary (agent standard) | `"${G[@]}" "${P[@]}" --quick-gen-key "Name <email>" ed25519 cert 2y` |
| Add signing subkey | `"${G[@]}" "${P[@]}" --quick-add-key "$FPR" ed25519 sign 1y` |
| Add encryption subkey | `"${G[@]}" "${P[@]}" --quick-add-key "$FPR" cv25519 encr 1y` |
| Add auth subkey | `"${G[@]}" "${P[@]}" --quick-add-key "$FPR" ed25519 auth 1y` |
| Legacy RSA primary | `"${G[@]}" "${P[@]}" --quick-gen-key "Name <email>" rsa4096 cert 2y` |
| Unattended via parameter file | `"${G[@]}" --generate-key params.txt` |

Capture the new fingerprint from `[GNUPG:] KEY_CREATED P <fpr>` on the status fd. Do not search the keyring by email afterwards.

Full agent-standard generation:

```bash
set -euo pipefail
UID_STR="Build Bot <bot@example.org>"
STATUS="$(mktemp)"

gpg --homedir "$GNUPGHOME" --batch --no-tty --status-fd 3 \
    --pinentry-mode loopback --passphrase-fd 4 \
    --quick-gen-key "$UID_STR" ed25519 cert 2y \
    3>"$STATUS" 4<"$PASSFILE"

FPR="$(awk '$2=="KEY_CREATED" {print $4}' "$STATUS")"
[[ "$FPR" =~ ^[0-9A-F]{40}$ ]] || { echo "key generation failed" >&2; exit 2; }

for spec in "ed25519 sign" "cv25519 encr" "ed25519 auth"; do
  read -r algo usage <<<"$spec"
  gpg --homedir "$GNUPGHOME" --batch --no-tty \
      --pinentry-mode loopback --passphrase-fd 3 \
      --quick-add-key "$FPR" "$algo" "$usage" 1y 3<"$PASSFILE"
done
```

Parameter-file generation (useful when the primary and one subkey must be created atomically; add further subkeys with `--quick-add-key`):

```text
%echo Generating agent key
Key-Type: EDDSA
Key-Curve: ed25519
Key-Usage: cert
Subkey-Type: ECDH
Subkey-Curve: cv25519
Subkey-Usage: encrypt
Name-Real: Build Bot
Name-Email: bot@example.org
Expire-Date: 2y
# Prefer passing the passphrase via --passphrase-fd with loopback.
# For deliberately unprotected ephemeral keys only:
# %no-protection
%commit
%echo done
```

A revocation certificate is created automatically at `$GNUPGHOME/openpgp-revocs.d/<FPR>.rev`. **MUST** tell the user it exists and that it must be backed up somewhere separate from the secret key.

### 5.2 Key listing & inspection

| Task | Command |
|------|---------|
| List public keys (machine) | `"${G[@]}" --with-colons --with-subkey-fingerprint --list-keys [FPR]` |
| List secret keys (machine) | `"${G[@]}" --with-colons --with-subkey-fingerprint --list-secret-keys [FPR]` (`-K`) |
| Show keygrips | add `--with-keygrip` |
| List signatures on a key | `"${G[@]}" --with-colons --list-sigs FPR` |
| Inspect a key file without importing | `"${G[@]}" --with-colons --import-options show-only --import key.asc` |
| Inspect packets (debug) | `gpg --list-packets file` |

`--import-options show-only --import` is the safe way to read the fingerprint of an untrusted key file before deciding to import it.

### 5.3 Encryption & decryption

| Task | Command |
|------|---------|
| Encrypt to recipient(s) | `"${G[@]}" --yes --recipient "$RFPR" [--recipient "$RFPR2"] --output out.gpg --encrypt in` |
| Encrypt + also to self | add `--recipient "$SELF_FPR"` (or `--encrypt-to`) so the sender can decrypt later |
| Hide recipient key IDs | `--hidden-recipient "$RFPR"` (recipients must then trial-decrypt) |
| ASCII armor | add `--armor` (`-a`) |
| Encrypt and sign | `"${G[@]}" "${P[@]}" --yes --local-user "$SFPR" --recipient "$RFPR" --output out.gpg --sign --encrypt in` |
| Symmetric | `"${G[@]}" "${P[@]}" --yes --symmetric --cipher-algo AES256 --s2k-digest-algo SHA512 --output out.gpg in` |
| Decrypt | `"${G[@]}" "${P[@]}" --yes --output out.bin --decrypt in.gpg` |

Rules:

- **MUST** give `--recipient` as a full fingerprint. Optionally append `!` (`FPR!`) to force that exact (sub)key.
- **MUST** use `--output` (`-o`) with a path the agent controls. Do not rely on stdout redirection for binary data in shells that may mangle it.
- **MUST** treat decryption as successful only if exit code is 0 **and** `DECRYPTION_OKAY` is present **and** no `DECRYPTION_FAILED` / `BADMDC` is present. GnuPG streams plaintext, so on failure a partially written `--output` file may exist: **delete it**.
- **MUST NOT** use `--ignore-mdc-error`, `--allow-old-cipher-algos`, `--allow-weak-digest-algos`, `--rfc2440`, `--pgp6/7/8` or `--no-mdc-warning`.

### 5.4 Signing & verification

| Task | Command |
|------|---------|
| Detached signature (preferred for files/artifacts) | `"${G[@]}" "${P[@]}" --yes --local-user "$SFPR" --armor --output file.asc --detach-sign file` (`-b`) |
| Clear-signed text | `"${G[@]}" "${P[@]}" --yes --local-user "$SFPR" --output msg.asc --clear-sign msg.txt` |
| Inline (opaque) signature | `"${G[@]}" "${P[@]}" --yes --local-user "$SFPR" --output file.gpg --sign file` (`-s`) |
| Verify detached | `"${G[@]}" --verify file.asc file` |
| Verify inline/clearsigned and extract signed content | `"${G[@]}" --yes --output content --decrypt file.asc` |
| Strict automated verification | `gpgv --status-fd 2 --keyring /abs/path/trusted.gpg file.asc file` |

Rules:

- **MUST** always pass both the signature and the data file to `--verify` for detached signatures. With only one argument gpg guesses the data file, which an attacker can influence.
- For clear-signed / inline-signed input, **MUST** use the content gpg outputs (`--decrypt --output`), never the original file's text: text outside the signed block is not covered by the signature.
- **MUST** sign with a specific `--local-user FPR`, never rely on `default-key` resolution.

`gpgv` for strict automated verification:

`gpgv` treats every key in its keyring as trusted and has no trust database, so the keyring itself is the allow-list. This is ideal for CI/package verification.

```bash
# One-time: build the allow-list keyring from vetted fingerprints (binary, NOT --armor)
gpg --homedir "$GNUPGHOME" --batch --export "$TRUSTED_FPR_1" "$TRUSTED_FPR_2" > /etc/myapp/trusted.gpg

# Every verification
gpgv --status-fd 3 --keyring /etc/myapp/trusted.gpg artifact.tar.gz.asc artifact.tar.gz 3>status.txt
```

- **MUST** give `--keyring` an absolute path; a bare name is resolved relative to the gpgv home directory.
- Still pin `VALIDSIG` to the expected primary fingerprint (see §7.4) when more than one key is in the keyring and only one is allowed to sign this artifact.

### 5.5 Import, export & backup

| Task | Command |
|------|---------|
| Export public key (armored) | `"${G[@]}" --armor --export "$FPR" > pub.asc` |
| Export minimal public key | `"${G[@]}" --armor --export-options export-minimal --export "$FPR"` |
| Import public key | `"${G[@]}" --import pub.asc` (then check `IMPORT_OK` / `IMPORT_RES`) |
| Strip all but matching user IDs on import | `"${G[@]}" --import-filter keep-uid='mbox = bot@example.org' --import pub.asc` (still verify fingerprint first) |
| Export secret subkeys only (for daily hosts) | `"${G[@]}" "${P[@]}" --armor --export-secret-subkeys "$FPR"\! > subkeys.sec.asc` |
| Export full secret key (backup, user-approved only) | `"${G[@]}" "${P[@]}" --armor --export-secret-keys "$FPR" > secret.asc` |
| Export ownertrust | `"${G[@]}" --export-ownertrust > ownertrust.txt` |
| Import ownertrust | `"${G[@]}" --import-ownertrust ownertrust.txt` |
| Generate revocation cert manually | `gpg --homedir "$GNUPGHOME" --gen-revoke "$FPR"` (interactive; prefer the auto-generated one) |

Import safety procedure:

```text
1. Inspect: gpg --with-colons --import-options show-only --import key.asc
2. Extract primary fingerprint(s) from the listing.
3. Compare against the fingerprint obtained out-of-band (user, signed manifest, pinned config).
4. Only if equal -> real import. If the file contains extra keys, import only the matching one
   by staging it in a scratch homedir:
      gpg --homedir "$SCRATCH" --batch --import key.asc
      gpg --homedir "$SCRATCH" --batch --export "$FPR" | gpg --homedir "$GNUPGHOME" --batch --import
5. Check status: IMPORT_OK present, IMPORT_RES counts as expected.
```

Moving the primary key offline (after a full backup exists):

```bash
# 1. Find the keygrip of the primary key
gpg --homedir "$GNUPGHOME" --with-colons --with-keygrip -K "$FPR" |
  awk -F: '$1=="sec"{w=1;next} $1=="grp"&&w{print $10; exit}'
# 2. With explicit user confirmation, remove that one private key file
rm -- "$GNUPGHOME/private-keys-v1.d/<KEYGRIP>.key"
# 3. Verify: field 15 of the sec record is now "#", listings show "sec#"
```

Secret export rules are in §7.1.

---

## 6. Trust Models & Verification Frameworks

### 6.1 Models

| Model (`--trust-model`) | How validity is computed | Agent use |
|-------------------------|--------------------------|-----------|
| `pgp` (default; Web of Trust) | Keys become valid via certifications from keys you assign ownertrust to | Default for persistent homedirs; combine with local signatures |
| `classic` | Older WoT variant | Do not choose |
| `tofu` | Trust On First Use: first binding of email↔key is remembered; conflicts flagged | Messaging-like flows with many peers, when no out-of-band verification is possible |
| `tofu+pgp` | Combination; the higher of the two applies, conflicts flagged | Mixed environments |
| `direct` | Validity = ownertrust set directly on each key | Small, static allow-lists |
| `always` | Every key is valid | **Forbidden** in production (see §7) |
| `auto` | Selects based on trustdb | Avoid; be explicit |

Decision logic:

```text
IF the task is verification of artifacts from a fixed set of signers
    -> use gpgv with a dedicated keyring (no trust model at all) + fingerprint pinning
ELSE IF the set of peers is small and fingerprints are known out-of-band
    -> trust-model pgp; give own key ultimate ownertrust; --quick-lsign-key each verified peer
ELSE IF peers are many and cannot be verified out-of-band, and the user accepts TOFU semantics
    -> trust-model tofu+pgp; treat any TOFU conflict as a hard failure and report it
ELSE
    -> stop and ask the user how keys should be authenticated
```

### 6.2 Ownertrust values

Ownertrust is how much you trust a key's owner to certify **other** keys. It is distinct from validity (whether a key belongs to who it claims).

| Value in `--export-ownertrust` | Name | Meaning |
|--------------------------------|------|---------|
| 2 | undefined | Don't know |
| 3 | never | Do not trust their certifications |
| 4 | marginal | Partly trust |
| 5 | full | Fully trust their certifications |
| 6 | ultimate | Own key; anything it certifies is valid |

### 6.3 Setting trust programmatically

```bash
# Ultimate ownertrust for the agent's OWN key (gpg already does this on generation)
printf '%s:6:\n' "$OWN_FPR" | gpg --homedir "$GNUPGHOME" --batch --import-ownertrust

# Make a verified peer key valid by locally certifying it (non-exportable, never published)
gpg --homedir "$GNUPGHOME" --batch --no-tty --pinentry-mode loopback --passphrase-fd 3 \
    --local-user "$OWN_FPR" --quick-lsign-key "$PEER_FPR" 3<"$PASSFILE"

# Recompute
gpg --homedir "$GNUPGHOME" --batch --check-trustdb
```

Rules:

- **MUST NOT** give ultimate ownertrust (`6`) to any key the agent or user does not own.
- **SHOULD** use `--quick-lsign-key` (local) rather than `--quick-sign-key` (exportable) unless the user wants to publish a certification.
- **MUST** only certify a peer key after its full fingerprint has been confirmed through a channel other than the key file itself.
- TOFU policy for a known key: `gpg --tofu-policy good|bad|unknown|ask|auto "$FPR"`. In batch mode, `ask` cannot be answered and becomes a failure; use `good` only after out-of-band verification.

---

## 7. Security Guardrails, Anti-Patterns & Error Handling

### 7.1 Hard prohibitions

| # | NEVER | Why / do instead |
|---|-------|------------------|
| 1 | Export secret keys (`--export-secret-keys`, `--export-secret-subkeys`) without an explicit user request for that specific key in this session | Private key material is the crown jewel. When requested: write only to a user-specified path, `umask 077` first, `--armor`, never to stdout, never into logs or chat, and tell the user where the file is and that it should be moved to offline storage. Prefer `--export-secret-subkeys` for daily-use hosts. |
| 2 | Put a passphrase in argv (`--passphrase X`), environment variables passed to child tools, script source, CI YAML, or logs | Visible via `ps aux`, `/proc/<pid>/cmdline`, `/proc/<pid>/environ`, history. Use `--passphrase-fd`. |
| 3 | Use `--trust-model always` or blanket `ownertrust 6` on foreign keys to "make the warning go away" | It turns encryption to any attacker-supplied key into success. Fix trust properly (§6). |
| 4 | Address keys by email, name, or (short/long) key ID | Ambiguous and collision-prone. Use 40-hex fingerprints. |
| 5 | Treat exit code 0 from `--verify` as "trusted" | gpg returns 0 for a good signature from **any** key in the keyring, including unknown-validity ones. Pin `VALIDSIG` fingerprint. |
| 6 | Auto-fetch keys during verification (`--auto-key-retrieve`, `--keyserver` lookups in the trust path) | Fetched keys are attacker-controllable. Keys enter the keyring only through the import procedure in §5.5. |
| 7 | Operate on `~/.gnupg` implicitly | Use an isolated `--homedir`. |
| 8 | Use deprecated or weakening flags (`--ignore-mdc-error`, `--allow-weak-digest-algos`, `--allow-old-cipher-algos`, `--no-require-cross-certification`, `--rfc2440`) | Each disables a protection. |
| 9 | Delete keys, trustdb, or private-key files without explicit user confirmation and a verified backup | Irreversible. |
| 10 | Keep using output from a failed decrypt/verify | Delete partial output; report failure. |

### 7.2 Exit codes

| Code | `gpg` / `gpgv` meaning | Agent action |
|------|------------------------|--------------|
| 0 | No severe errors | Still validate status lines (§7.4) |
| 1 | At least one signature was bad (verification), or a "soft" failure in some operations | Reject |
| 2 | Fatal error (missing key, decryption failure, bad passphrase, unusable recipient, I/O error, etc.) | Reject; diagnose from status lines |
| other | Unexpected | Reject |

Always capture: exit code, the status-fd stream, and stderr (for diagnostics, with secrets redacted).

### 7.3 Common failures and responses

| Symptom (status line / stderr) | Cause | Correct response |
|--------------------------------|-------|------------------|
| `INV_RECP 1 <name>` / `No public key` | Recipient key not in keyring | Run import procedure (§5.5) with out-of-band fingerprint; never auto-fetch |
| `INV_RECP 3` / `unusable public key` | Key has no valid encryption subkey (usage) | Check capabilities field 12; request a key with an `[E]` subkey |
| `INV_RECP 4` | Recipient key revoked | Stop; obtain the owner's new key |
| `INV_RECP 5` / `KEYEXPIRED` | Recipient key or subkey expired | Ask for an updated public key (owner may have extended expiry) and re-import |
| `INV_RECP 10` / `There is no assurance this key belongs to the named user` | Key validity insufficient under batch mode | Verify fingerprint out-of-band, then `--quick-lsign-key`; do **not** switch to `--trust-model always` |
| `INV_RECP 13` | Key disabled | Stop; report |
| `NO_PUBKEY <keyid>` / `ERRSIG … 9` on verify | Signer key absent | Reject; report the issuer key ID; obtain key through trusted channel |
| `EXPKEYSIG` | Signed by expired key | Reject unless user policy explicitly accepts historical signatures made before expiry |
| `REVKEYSIG` | Signed by revoked key | Reject |
| `BADSIG` | Data or signature tampered | Reject; never retry with other data |
| `DECRYPTION_FAILED` / `NO_SECKEY` only | No usable secret key / wrong key | Check `-K` listing; confirm the message was encrypted to this key |
| `BADMDC` / integrity error | Ciphertext modified or corrupted | Reject and delete output |
| `Bad passphrase` / `FAILURE … 11` | Wrong passphrase | Report; do not loop/retry automatically (avoid lockouts and log noise) |
| `Inappropriate ioctl for device`, `No pinentry`, `problem with the agent` | Pinentry tried without a tty | Add `--pinentry-mode loopback` and a passphrase fd; ensure `allow-loopback-pinentry` |
| `can't connect to the agent` | Agent not running / socket path too long / wrong homedir | `gpgconf --homedir "$GNUPGHOME" --launch gpg-agent`; shorten path; check `--homedir` consistency |
| `unsafe permissions on homedir` | Mode not 700 | `chmod 700 "$GNUPGHOME"`; files inside 600 |
| `trustdb.gpg: trust record … bad` / `trustdb is corrupted` | Corrupted trust database | Rebuild procedure below |
| `File exists` on output in batch | Output path exists, no `--yes` | Add `--yes` only if the agent owns that path |

Corrupted trustdb rebuild:

```bash
H="$GNUPGHOME"
gpg --homedir "$H" --batch --export-ownertrust > "$H/ownertrust.bak" || true
gpgconf --homedir "$H" --kill all
mv -- "$H/trustdb.gpg" "$H/trustdb.gpg.corrupt.$(date +%s)"
gpg --homedir "$H" --batch --import-ownertrust "$H/ownertrust.bak"
gpg --homedir "$H" --batch --check-trustdb
```

If the ownertrust export itself fails, stop and ask the user before rebuilding: their ownertrust assignments will need to be re-entered.

### 7.4 Verification acceptance algorithm

A signature is ACCEPTED only if **all** of the following hold:

```text
1. exit_code == 0
2. exactly one VALIDSIG line is present (or one per expected signer)
3. VALIDSIG.primary_fpr (last field) is in the pinned allow-list for THIS artifact
4. GOODSIG is present
5. none of: BADSIG, ERRSIG, EXPSIG, EXPKEYSIG, REVKEYSIG, NO_PUBKEY, FAILURE
6. (gpg only) a TRUST_FULLY or TRUST_ULTIMATE line is present,
   OR the primary_fpr was pinned out-of-band (rule 3) and policy says pinning suffices
7. (optional) signature timestamp (VALIDSIG field 3) is not in the future and
   is within the policy's freshness window
Otherwise: REJECTED. Report which rule failed.
```

Reference implementation:

```bash
verify_detached() {   # usage: verify_detached SIG DATA EXPECTED_PRIMARY_FPR
  local sig="$1" data="$2" want="$3" st rc
  st="$(mktemp)"
  gpgv --status-fd 3 --keyring "$TRUSTED_KEYRING" -- "$sig" "$data" 3>"$st" 2>/dev/null
  rc=$?
  if (( rc != 0 )); then echo "REJECT: gpgv exit $rc" >&2; rm -f "$st"; return 1; fi
  if grep -Eq '^\[GNUPG:\] (BADSIG|ERRSIG|EXPSIG|EXPKEYSIG|REVKEYSIG|NO_PUBKEY|FAILURE)' "$st"; then
    echo "REJECT: negative status" >&2; rm -f "$st"; return 1
  fi
  local got
  got="$(awk '$2=="VALIDSIG"{print $NF}' "$st")"
  rm -f "$st"
  if [[ "$(wc -l <<<"$got")" -ne 1 || "$got" != "$want" ]]; then
    echo "REJECT: signer '$got' != pinned '$want'" >&2; return 1
  fi
  echo "ACCEPT: $got"
}
```

### 7.5 Decryption acceptance algorithm

```text
1. Write output to a fresh path inside a 700 directory.
2. Run gpg --decrypt with --status-fd.
3. SUCCESS only if exit_code == 0 AND DECRYPTION_OKAY present AND
   no DECRYPTION_FAILED / BADMDC / FAILURE present.
4. If the message was also signed, apply §7.4 to its signature status lines;
   if a signature was REQUIRED by the task and none is present, FAIL.
5. On any failure: delete the output file, report the failing condition.
```

### 7.6 Pre-flight checklist (run before any operation)

```text
[ ] gpg --version reports 2.2 or newer (2.4 preferred); record version in task output
[ ] GNUPGHOME / --homedir set, exists, mode 700, path short
[ ] gpg.conf and gpg-agent.conf from §1.4 present
[ ] All key references are 40-hex fingerprints
[ ] --batch --no-tty --status-fd present on every gpg call
[ ] Passphrase (if any) supplied via fd/file with --pinentry-mode loopback; tracing off
[ ] Output paths chosen by the agent; --yes only on those paths
[ ] Trust decision path chosen per §6.1 decision logic
[ ] No prohibited flag from §7.1 present
[ ] Teardown planned: gpgconf --kill all, remove ephemeral homedir and passphrase files
```

### 7.7 Reporting to the user

After any GnuPG operation, the agent reports:

- what was done, with full fingerprints of every key involved;
- expiry dates of any key created or modified (ISO 8601, from colon field 7);
- location of any revocation certificate or secret export it created, with a reminder to store it offline;
- for failures, the specific status keyword and the remediation from §7.3.

The agent never reports passphrases, secret key material, or full plaintext of decrypted content unless the user asked for that content.
