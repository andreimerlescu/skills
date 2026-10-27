# Secrets lifecycle: from "I was handed a key" to "it ships safely"

Load whenever a task involves a credential in any form. SKILL.md §1–§3 are the summary.

## 1. Recognize sensitive material (before reading it)

**By name** (check with `ls`, never `cat`): `keys.txt`, `key`, `api_key*`, `secret*`, `secrets.*`, `creds*`, `credentials*`, `token*`, `password*`, `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `id_rsa*`, `id_ed25519*`, `.netrc`, `.npmrc`, `.pypirc`, `.dockercfg`, `config.json` under `.docker/`, `kubeconfig`, `terraform.tfvars`, `*.tfstate`, `service-account*.json`, `*.kdbx`, `wallet*`, `seed*`, `mnemonic*`, `.aws/credentials`, `.git-credentials`.

**By content** (when you must open a file): `-----BEGIN ... PRIVATE KEY-----`; high-entropy strings 20+ characters; prefixes `sk-`, `sk_live_`, `pk_live_`, `ghp_`, `github_pat_`, `glpat-`, `xox*-`, `AKIA`, `AIza`, `SG.`, `npm_`, `eyJ` (JWT); `scheme://user:pass@host`; any value next to words `secret`, `token`, `password`, `key`, `bearer`, `auth`.

**By context**: the user says "here's the key", "use this token", "the sample key is in …", "the credentials are in …". Everything the user gives you to *authenticate* is secret, regardless of how casually it was handed over.

## 2. Reading a secret file safely

- Learn what you need from metadata first: `ls -l`, `wc -c`, `file`, line count, and key *names* (`cut -d: -f1`, `sed 's/=.*/=<value>/'`). Often that is enough to write the code that will parse it.
- If you must read values (to verify format), do it in the shell and test properties without echoing: `[ "$(wc -l < keys.txt)" -eq 1 ]`, `grep -c '^sk-' keys.txt`, `head -c 3 keys.txt` (the first three characters, not the key).
- **Never** pass a secret as a literal into a command, tool argument, test or heredoc. Pipe from the file inside the shell command: `curl -H "Authorization: Bearer $(cat keys.txt)"`-style invocations keep the value out of your transcript, but remember `ps` and shell history can still see expanded command lines; for live calls prefer `curl -K -` reading a config from stdin or `--header @file`.
- Do not call a live third-party API with a discovered credential unless the user asked for that exact action. Calling an API "to check the key works" can incur cost, trigger alerts, or act on production data.
- If your tools echo file contents into the conversation (a `Read` tool, `cat`), the secret is now in the transcript. Do not repeat it; tell the user it appeared in tool output if that may be logged; continue by reference.

## 3. Designing how the program gets the secret

Decide, before writing code that uses it:

| Question | Answer to write into the plan |
| --- | --- |
| Who needs it? (process, user, service) | smallest set |
| Where does it live at rest? | outside the repo, outside the image/binary: secret manager, mounted file `0600`, OS keychain |
| How does it reach the process? | file path (preferred), env var, stdin; see SKILL.md §3 |
| What happens when it is missing/invalid/expired? | fail closed with a secret-free message naming the input |
| Who can see it at runtime? | process owner only; not children unless required |
| How is it rotated? | restart or reload on file change; document the procedure; never require a rebuild |
| How do tests get a credential? | they do not need a real one: fakes, `httptest`, recorded fixtures with scrubbed headers, or a visibly skipped integration test |

## 4. Rotating and revoking

Design every integration so the credential can be replaced without a code change or rebuild. If the secret is read once at startup, say so in docs and provide a reload path or a restart procedure. Prefer short-lived credentials (OIDC, workload identity, STS tokens) over long-lived keys where the provider supports them. Scope keys to least privilege (read-only, one resource, one IP range) and say in the report which scope is required.

## 5. Handling a secret the user pasted into chat

Treat it as exposed to everything that logs the chat. Do not write it to disk "for convenience". Ask the user to put it in a file or environment variable instead, and tell them to rotate it if it is a real production credential. If the task cannot continue without it, accept it *only into a runtime channel* (an env var for the single command), never into the repo.

## 6. What "done" means for a secret-touching task

1. The secret appears nowhere in the diff, the built artifact, `--help`, logs or the report.
2. The program works when the secret is supplied through the documented channel and fails clearly when it is not.
3. The source file is ignored by VCS, Docker and package builds.
4. Tests run with fakes and pass offline.
5. The user knows exactly how to supply the secret and what to rotate if it was exposed earlier.
