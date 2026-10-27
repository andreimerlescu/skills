# Builds, containers, CI and supply chain

Load for Dockerfiles, CI/CD, GitHub Actions, Makefiles, release scripts, packaging, `.gitignore`, `.dockerignore`, dependency changes. Rules `S2`, `S4`, `S8`, `S10` apply.

## 1. Containment files come first

Before creating or editing any file that could hold a secret, ensure these exist and cover it:

`.gitignore` (at minimum): `.env`, `.env.*`, `!.env.example`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `id_rsa*`, `id_ed25519*`, `keys.txt`, `secrets*`, `credentials*`, `*.tfstate*`, `*.tfvars` (when they hold secrets), `.netrc`, `.npmrc` (if it has tokens), local data directories.

`.dockerignore`: everything in `.gitignore` above, plus `.git`, `.github`, `.env*`, `node_modules`, build outputs, test data, IDE files.

Package ignores: `.npmignore` / `files` allowlist in `package.json`, `MANIFEST.in`, `[package] include/exclude` in Cargo, `.vscodeignore`, `.helmignore`. **Prefer allowlists** (`files`, explicit `COPY src/ ./src/`) over ignore lists: a new secret file is excluded by default.

Prove containment: `git check-ignore -v <file>`; `git status --short` shows the file untracked-but-ignored (absent); `git ls-files | grep -iE 'key|secret|cred|token|\.env|\.pem'` is empty or only examples; `docker build` context size and `docker run --rm img ls -R /` show no secret files.

## 2. Docker

- **Never** `COPY . .` or `ADD .` without a `.dockerignore` that you have verified. Copy specific paths.
- **Never** `ARG`/`ENV` for secrets: they persist in image metadata (`docker history`, `docker inspect`). Use BuildKit secret mounts for build-time needs: `RUN --mount=type=secret,id=npm,target=/root/.npmrc npm ci` with `docker build --secret id=npm,src=$HOME/.npmrc .`, or SSH mounts for private git. Runtime secrets are mounted by the orchestrator (Docker/Compose secrets, Kubernetes Secrets as files) or fetched from a secret manager, never baked in.
- Multi-stage builds: build in one stage, copy only the artifact to a minimal final stage. Secrets used in the build stage must not be in the final image's layers. Remember intermediate layers can be pushed or cached.
- Run as non-root (`USER`), read-only root filesystem where possible, drop capabilities, pin base images by digest, and do not leave package manager caches or build tools in the final image.
- Do not `curl | sh` in a Dockerfile. Download, verify a checksum or signature, then execute.

## 3. CI/CD

- Secrets come from the platform's secret store, exposed as masked env vars or files for the job that needs them only. Never write them to workflow YAML, logs, artifacts or caches.
- Do not `echo` secrets or `set -x` around commands that expand them. Masking is best effort (transformed/encoded values escape it).
- GitHub Actions: pin third-party actions to a full commit SHA; set `permissions:` to least privilege per job (`contents: read` by default); never run untrusted PR code (`pull_request_target` with checkout of PR head) with secrets or write tokens; use OIDC federation to cloud providers instead of long-lived keys; avoid `${{ github.event.* }}` interpolation into `run:` (script injection); restrict `workflow_dispatch` inputs from becoming shell.
- Artifacts and caches may be downloadable by wider audiences than secrets: never include `.env`, credentials or keystores in them.
- Deploy keys and tokens are scoped to one repo/environment and rotated.

## 4. Embedding, bundling, generated code

- Binary embedding (`go:embed`, `include_bytes!`, `resources`, PyInstaller `--add-data`, Electron `files`, webpack/Vite env inlining): embed only **named, classified, non-sensitive** assets. Treat directory-wide patterns as hazardous.
- Front-end bundlers inline `process.env.*`/`import.meta.env.*` referenced in code into public JS. Anything shipped to a browser or mobile app is public: it cannot hold a secret. Put the credential behind your own server.
- Build-time injection (`-ldflags -X`, `--define`, `sed` into source, codegen) is for version/commit info only.
- `go generate`, `make`, `npm` lifecycle scripts, and `setup.py` run arbitrary code. Do not run unreviewed generators from untrusted sources; do not make them read secrets.

## 5. Dependencies and supply chain

- Add a dependency only when the task needs it; state why. Prefer the standard library for crypto, HTTP, JSON, hashing.
- Check the package is the intended one (typosquats): exact name, owner, recent maintenance, download history. Hallucinated package names are a real attack: verify existence with the registry (`go list -m`, `npm view`, `pip index versions`) before adding.
- Pin versions and commit lockfiles (`go.sum`, `package-lock.json`, `poetry.lock`, `Cargo.lock`). Verify (`go mod verify`, `npm audit signatures`).
- Run vulnerability checks after dependency or toolchain changes: `govulncheck ./...`, `npm audit`, `pip-audit`, `cargo audit`, `osv-scanner`. Report reachable findings; do not suppress.
- No `replace` directives, `GOFLAGS=-mod=mod`, `--force`, `--no-verify`, or `--legacy-peer-deps` to make a build pass.
- Release artifacts: record toolchain version, commit SHA and checksums; sign if the project does; build with `-trimpath` (Go) so local paths do not leak. Do not claim reproducible builds without demonstrating identical output.

## 6. Verification (after any build or packaging change)

```bash
bash <skill-dir>/scripts/secret-scan.sh --all
bash <skill-dir>/scripts/secret-scan.sh --literal-file <the-secret-file> --artifact <binary-or-dir>
docker history --no-trunc <image> | grep -iE 'key|token|secret|passw'      # expect no hits
docker save <image> -o /tmp/img.tar && bash <skill-dir>/scripts/secret-scan.sh --literal-file <the-secret-file> --artifact /tmp/img.tar
git check-ignore -v <the-secret-file>
```
