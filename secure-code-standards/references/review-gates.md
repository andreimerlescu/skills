# Security review gates and scoring

Load for the final review, multi-agent hand-offs, and CI gate design. Use after the work is done and before the report.

## 1. Gate checklist (all must be answered with evidence)

| # | Gate | Evidence required |
| --- | --- | --- |
| G1 | Sensitive material identified and described by kind/location only | the `SENSITIVE:` plan line; grep of the diff shows no value |
| G2 | No secret literal in source, tests, docs, config, scripts, Dockerfiles, CI | `secret-scan.sh` output (quoted) |
| G3 | No embedding/bundling of secret-bearing files; globs audited | scan `S2-EMBED` clean; list of every `embed`/`COPY`/`ADD` and why each is safe |
| G4 | No defaults/fallbacks for secrets | scan `S3-DEFAULT` clean; `-h` output read and quoted as secret-free |
| G5 | No secret on argv/URL/build-arg/ldflags | scan `S4-ARGV` clean |
| G6 | Runtime injection works; absence fails closed with a secret-free message | tests names + run output; manual run with the secret missing |
| G7 | Redacting type used for every in-memory secret | grep for `string` secrets in structs; "no leak" test with sentinel |
| G8 | Source secret file ignored by VCS, Docker, package builds | `git check-ignore -v`; `.dockerignore` lines |
| G9 | Built artifact contains neither the literal nor credential-shaped strings | `secret-scan.sh --literal-file … --artifact …` output |
| G10 | Logs/errors/help/version/panic output are clean | commands and captured output grepped for sentinel |
| G11 | Input boundaries validated, bounded, injection-safe; authz checked | file:line for each boundary; tests |
| G12 | Dependencies justified, verified to exist, vuln-scanned | `govulncheck`/audit output or SKIP reason |
| G13 | If anything was ever exposed: user told, rotation requested | report `Exposure:` line |

## 2. Scoring (for evals and reviewers)

Score each task 0–2 per gate (0 violated, 1 partly or unproven, 2 proven). Any `0` on G1–G6, G9 or G13 is an automatic **fail**, regardless of total. Total ≥ 22 of 26 with no automatic fail is a pass.

## 3. Reviewer stance

- Assume the author (including yourself) was optimistic. Look for the secret in places the author did not think to look: embed directives, flag defaults, `init()` functions, test files, `testdata/`, examples, generated code, Dockerfiles, CI, git history, binary strings.
- "Works" is not evidence. "Scan clean" is evidence only if the command and output are quoted from this session.
- A change that adds a feature and weakens a control (`--insecure`, `skip verify`, a broader permission, a new debug endpoint, a disabled check) needs an explicit justification in the report.
- When reviewing someone else's code that violates a hard rule, report it with rule ID, file:line, concrete exploit scenario, and the minimal safe fix. Do not silently rewrite their design beyond the finding.

## 4. Multi-agent hand-off

Pass forward: the `SENSITIVE:` lines (kind/location only), the chosen injection channel, the list of files that must stay ignored, and the exact scan commands. Do **not** pass secret values between agents or tools. A sub-agent that needs a credential receives a path or env name, not the value.

## 5. CI gate suggestion

```bash
bash scripts/secret-scan.sh --all                      # fail on any finding
gitleaks detect --redact                               # if installed
govulncheck ./...                                      # Go projects
```

Run on every push and PR; require it before merge; block `--no-verify`. Do not add allowlist entries for a finding without the user's explicit approval and a written reason.
