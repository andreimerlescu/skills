# Tests, fixtures, examples and documentation

Load when writing or changing tests, mocks, fixtures, golden files, README/docs, examples, or sample configs. Rules `S1`, `S5`, `S10` apply. Tests and docs are the second most common place for leaked secrets, after config.

## 1. Tests never need a real credential

- Unit tests use **fakes generated at test time** (`"fake-credential-for-tests-" + randomSuffix`) or obviously invalid constants. Fakes must not match real formats: avoid `sk-live-…`, `AKIA…`, `ghp_…`, `eyJ…` shapes, or the secret scanner (and GitHub push protection) will flag them and trained eyes will not know whether they are real.
- Integration tests against a real service read their credential from the environment/file at runtime and **skip visibly** with a reason when it is absent (`t.Skip("set API_KEY_FILE to run integration tests")`). They never pass silently and never fall back to an embedded key.
- Use `httptest.NewServer` / local fakes to exercise client code. Assert the request the client sent (headers present, query string **free** of credentials) rather than calling production.
- Never commit recorded fixtures (HTTP cassettes, golden JSON, HAR files) without scrubbing `Authorization`, `Cookie`, `Set-Cookie`, tokens in bodies and URLs, account IDs, emails. Add a test or script that fails if a cassette contains a secret-looking value.
- Never read the user's real `keys.txt`, `.env` or credentials file from a test. Tests create temp files in `t.TempDir()` with mode `0600`.
- Test the security behavior, not just the feature: missing secret fails closed; invalid secret rejected; redaction holds across `%v/%+v/%#v/json/slog`; `-h` shows no value; permissions enforced; authorization denies cross-tenant access.

## 2. Mutation check (security edition)

Name the one-line change that would make the test fail: remove the redaction method; add a default value; drop the permission check; log the header. If no test would fail, add one.

## 3. Documentation and examples

- Docs show **how to supply** secrets, never a secret: `export API_KEY_FILE=/run/secrets/api_key`, `--api-key-file ~/.config/app/api_key` with `chmod 600`.
- Use unmistakable placeholders: `<your-api-key>`, `REDACTED`, `YOUR_TOKEN_HERE`. Do not use a realistic-looking sample value copied from a real key.
- Screenshots, terminal recordings, GIFs and pasted logs in docs are scrubbed. Check history of the shell and `env` output before capturing.
- README quick-starts must not tell users to paste secrets onto a command line, commit a `.env`, or `curl | sh`.
- Document the security model briefly: what secrets exist, where they come from, how to rotate, permissions required, what is logged.
- A `SECURITY.md` explains how to report vulnerabilities. Do not publish exploit details for unpatched issues in docs.

## 4. Agent transcripts, plans and reports are outputs too

Plans, TODO files, scratch notes, commit messages, PR descriptions and final reports are published somewhere. Describe secrets by kind and location only. If a command's output contained a secret, say that it did, not what it was.

## 5. Commit hygiene

- `git diff --cached` before every commit; scan staged content, not only the working tree.
- Do not commit the secret file "temporarily". Do not `git add -A` or `git add .` without a prior `git status` and an ignore check.
- If a secret is staged or committed, stop. Go to `references/incident-response.md`.
- Use pre-commit scanning where the project supports it (`gitleaks protect --staged`, `detect-secrets`, `trufflehog`); do not bypass hooks with `--no-verify`.
