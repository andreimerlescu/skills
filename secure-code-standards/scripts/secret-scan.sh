#!/usr/bin/env bash
# secret-scan.sh — secret-exposure gate for the secure-code-standards skill.
#
# Runs every check (never stops early) and prints a SECRET-SCAN SUMMARY block
# that agents must quote verbatim. It NEVER prints a matched secret value: only
# rule IDs, file paths and line numbers. Missing optional tools are SKIP.
#
# Compatible with bash 3.2 (macOS default) and later. Needs grep, find, sort.

set -u

usage() {
	cat <<'EOF'
Usage: secret-scan.sh [options] [dir]

Scans a source tree (default: current directory) for secret exposure.

Options:
  --all                    scan every file (default: files changed vs git HEAD
                           plus untracked files; whole tree if not a git repo)
  --literal-file FILE      FILE holds known secret(s). Every token in it (8+
                           chars) is searched for as a literal in the scanned
                           tree and in each --artifact. The file itself is
                           excluded. Values are never printed.
  --artifact PATH          also scan a built artifact (binary, archive, image
                           tarball, directory). May be repeated.
  --max-bytes N            skip files larger than N bytes (default 2000000)
  -h, --help               show this help

Rules reported (IDs match SKILL.md):
  S1-PATTERN   known credential format (cloud/API key prefixes, private keys,
               JWTs, credentialed URLs)
  S1-ASSIGN    credential-looking assignment with a literal value
  S2-EMBED     embed/include/COPY of a secret-bearing file or broad glob
  S3-DEFAULT   flag/config/env default that looks like a credential, or a
               secret-named flag with a non-empty literal default
  S4-ARGV      secret passed as a flag value, build-arg or ldflags -X
  S8-TRACKED   secret-named file is tracked by git or not ignored
  LITERAL      a known secret literal (from --literal-file) found in tree
  ARTIFACT     pattern or known literal found inside a built artifact

Exit codes: 0 clean · 1 findings · 2 usage error · 3 nothing to scan
EOF
}

ALL=0
LITFILE=""
ARTIFACTS=()
MAXB=2000000
TARGET="."

while [ $# -gt 0 ]; do
	case "$1" in
		--all) ALL=1 ;;
		--literal-file) shift; LITFILE="${1:-}" ;;
		--artifact) shift; ARTIFACTS+=("${1:-}") ;;
		--max-bytes)
			shift
			case "${1:-}" in ''|*[!0-9]*) echo "secret-scan: --max-bytes needs an integer" >&2; exit 2 ;; esac
			MAXB="$1" ;;
		-h|--help) usage; exit 0 ;;
		-*) echo "secret-scan: unknown option: $1" >&2; usage >&2; exit 2 ;;
		*) TARGET="$1" ;;
	esac
	shift
done

[ -d "$TARGET" ] || { echo "secret-scan: not a directory: $TARGET" >&2; exit 2; }
if [ -n "$LITFILE" ] && [ ! -f "$LITFILE" ]; then
	echo "secret-scan: --literal-file not found: $LITFILE" >&2; exit 2
fi
for a in ${ARTIFACTS[@]+"${ARTIFACTS[@]}"}; do
	[ -e "$a" ] || { echo "secret-scan: artifact not found: $a" >&2; exit 2; }
done

cd "$TARGET" || exit 2
ROOT="$(pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/secret-scan.XXXXXX")"
chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT

FINDINGS="$WORK/findings"; : >"$FINDINGS"
FILES="$WORK/files"
COUNT=0

finding() { # rule file line note
	printf '%s\t%s\t%s\t%s\n' "$1" "$2" "${3:-0}" "$4" >>"$FINDINGS"
	COUNT=$((COUNT + 1))
}

# ---------------------------------------------------------------------------
# File list
# ---------------------------------------------------------------------------
IN_GIT=0
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then IN_GIT=1; fi
HAS_HEAD=0
if [ $IN_GIT -eq 1 ] && git rev-parse --verify HEAD >/dev/null 2>&1; then HAS_HEAD=1; fi

list_files() {
	if [ $ALL -eq 0 ] && [ $HAS_HEAD -eq 1 ]; then
		{
			git diff --name-only --relative --diff-filter=ACMR HEAD
			git ls-files --others --exclude-standard
		} | sort -u
		SCOPE="changed files"
	elif [ $IN_GIT -eq 1 ]; then
		# Tracked and untracked-but-not-ignored. Ignored files are excluded on
		# purpose: that is where secrets are supposed to live (see S8).
		{ git ls-files; git ls-files --others --exclude-standard; } | sort -u
		SCOPE="all tracked and unignored files"
	else
		find . -type f \
			-not -path './.git/*' -not -path '*/node_modules/*' -not -path '*/vendor/*' \
			| sed 's|^\./||' | sort -u
		SCOPE="all files (not a git repo)"
	fi
}
SCOPE=""
build_files() {
	list_files >"$WORK/files.raw"
	: >"$FILES"
	while IFS= read -r f; do
		[ -f "$f" ] || continue
		[ -L "$f" ] && continue
		if [ -n "$LITFILE" ] && [ "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" = "$(cd "$(dirname "$LITFILE")" && pwd)/$(basename "$LITFILE")" ]; then
			continue
		fi
		sz=$(wc -c <"$f" | tr -d ' ')
		[ "$sz" -le "$MAXB" ] || continue
		# binaries are skipped in the source scan (artifacts are handled separately)
		grep -Iq . "$f" 2>/dev/null || continue
		printf '%s\n' "$f" >>"$FILES"
	done <"$WORK/files.raw"
}
build_files
# A clean working tree has no "changed" files; scan everything rather than nothing.
if [ ! -s "$FILES" ] && [ $ALL -eq 0 ]; then
	ALL=1
	build_files
	SCOPE="$SCOPE (nothing changed vs HEAD, so the whole tree was scanned)"
fi

NFILES=$(wc -l <"$FILES" | tr -d ' ')

# ---------------------------------------------------------------------------
# Patterns (ERE). Matching text is never echoed.
# ---------------------------------------------------------------------------
PAT_KNOWN='(AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{40,}|xox[abprs]-[0-9A-Za-z-]{10,}|sk-ant-[0-9A-Za-z_-]{20,}|sk-(proj-|live-|test-)?[0-9A-Za-z_-]{24,}|sk_(live|test)_[0-9A-Za-z]{16,}|rk_(live|test)_[0-9A-Za-z]{16,}|pk_live_[0-9A-Za-z]{16,}|SG\.[0-9A-Za-z_-]{16,}\.[0-9A-Za-z_-]{16,}|glpat-[0-9A-Za-z_-]{20,}|npm_[0-9A-Za-z]{36}|-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----|eyJ[0-9A-Za-z_-]{10,}\.eyJ[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}|[a-z][a-z0-9+.-]*://[^[:space:]/:@"]+:[^[:space:]/@"]{3,}@[^[:space:]/"]+'

# name = "value"  /  name: "value"  /  NAME=value  where name looks secret-ish
PAT_ASSIGN='(api[_-]?key|apikey|secret|passwd|password|passphrase|token|auth[_-]?key|private[_-]?key|client[_-]?secret|access[_-]?key|bearer)[A-Za-z0-9_-]*["'"'"']?[[:space:]]*(:=|=|:)[[:space:]]*["'"'"'`][A-Za-z0-9_./+=:@!#$%^&*-]{12,}["'"'"'`]'
PAT_ENVFILE='^[[:space:]]*(export[[:space:]]+)?[A-Z][A-Z0-9_]*(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*=[^[:space:]$"'"'"'][^[:space:]]{11,}'

# Obvious non-secrets that the generic rule should not flag.
is_benign_value_line() {
	# stdin: a matching line; return 0 if it is clearly a placeholder/reference
	grep -Eiq '(example|placeholder|redacted|changeme|change-me|your[_-]|<[a-z_ -]+>|\$\{?[A-Za-z_]|os\.(Getenv|LookupEnv)|getenv|process\.env|secret\.|_FILE|xxxxxxxx|fake|dummy|not[-_ ]real|lorem)'
}

scan_pattern() { # rule pattern note
	local rule="$1" pat="$2" note="$3" f ln line
	[ -s "$FILES" ] || return 0
	while IFS= read -r f; do
		grep -nE -e "$pat" -- "$f" 2>/dev/null | while IFS= read -r hit; do
			ln="${hit%%:*}"
			line="${hit#*:}"
			if [ "$rule" = "S1-ASSIGN" ] || [ "$rule" = "S1-ENVFILE" ]; then
				if printf '%s' "$line" | is_benign_value_line; then continue; fi
			fi
			printf '%s\t%s\t%s\t%s\n' "$rule" "$f" "$ln" "$note"
		done
	done <"$FILES" >>"$WORK/raw-findings"
}
: >"$WORK/raw-findings"

scan_pattern S1-PATTERN "$PAT_KNOWN" "known credential format (value withheld)"
scan_pattern S1-ASSIGN  "$PAT_ASSIGN" "credential-looking literal assigned to a secret-named identifier (value withheld)"
scan_pattern S1-ASSIGN  "$PAT_ENVFILE" "KEY=VALUE secret line; .env files must never be committed or packaged (value withheld)"

# S2: embed/include/COPY of secret-bearing names or broad globs
SENS_NAME='(^|[/_.-])(keys?|secrets?|creds?|credentials?|tokens?|passwords?|passwd|apikeys?|private|id_rsa|id_ed25519|id_ecdsa|\.env|\.netrc|kubeconfig)([/_.-]|$)|\.(pem|key|p12|pfx|jks|keystore|kdbx|asc|gpg)$'
scan_pattern S2-EMBED '^[[:space:]]*//go:embed[[:space:]].*(keys?|secrets?|creds?|credentials?|tokens?|passwords?|apikey|\.env|\.pem|\.key|\.p12|id_rsa)' "go:embed names a secret-bearing file"
scan_pattern S2-EMBED '^[[:space:]]*//go:embed[[:space:]]+(all:)?[A-Za-z0-9_./-]*(\*|/\.\.\.)[[:space:]]*$' "go:embed with a broad glob can swallow secret files; name specific assets"
scan_pattern S2-EMBED '(include_bytes!|include_str!)[[:space:]]*\([^)]*(key|secret|cred|token|password|\.env|\.pem)' "include_bytes!/include_str! of a secret-bearing file"
scan_pattern S2-EMBED '^[[:space:]]*(COPY|ADD)[[:space:]]+(--[a-z]+=[^[:space:]]+[[:space:]]+)*(\.|\./|\*)[[:space:]]+' "Dockerfile COPY/ADD of the whole context (needs .dockerignore proof for secrets)"
scan_pattern S2-EMBED '^[[:space:]]*(COPY|ADD)[[:space:]].*(\.env|\.pem|id_rsa|credentials|secrets?\.|keys?\.txt)' "Dockerfile COPY/ADD of a secret-bearing file"

# S3: defaults
scan_pattern S3-DEFAULT 'flag\.(String|StringVar)\([^"]*"[^"]*(key|token|secret|passw|credential|auth)[^"]*"[[:space:]]*,[[:space:]]*[^"[:space:]][^,]*,' "secret-named flag takes a non-literal default (possibly embedded or loaded from a file); no defaults for secrets (S3)"
scan_pattern S3-DEFAULT 'flag\.String\([[:space:]]*"[^"]*(key|token|secret|passw|credential)[^"]*"[[:space:]]*,[[:space:]]*"[^"]{4,}"' "secret-named flag has a non-empty literal default (S3)"
scan_pattern S3-DEFAULT '(SetDefault|BindEnv|Getenv\([^)]*\)[[:space:]]*(\|\||or|\?\?)|cmp\.Or\([^)]*Getenv)[^"]*(key|token|secret|passw)[^"]*"[^"]{4,}"' "fallback literal for a secret-named setting (S3)"
scan_pattern S3-DEFAULT 'os\.environ\.get\([[:space:]]*["'"'"'][A-Za-z0-9_]*(KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*["'"'"'][[:space:]]*,[[:space:]]*["'"'"'][^"'"'"']{4,}["'"'"']' "env lookup with a non-empty fallback for a secret (S3)"
scan_pattern S3-DEFAULT '(process\.env\.[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)[[:space:]]*(\|\||\?\?)[[:space:]]*["'"'"'][^"'"'"']{4,}["'"'"']' "env lookup with a non-empty fallback for a secret (S3)"

# S4: argv / build args / ldflags
scan_pattern S4-ARGV '-ldflags[^|]*-X[[:space:]]+[A-Za-z0-9_./]*\.[A-Za-z0-9_]*(key|token|secret|passw|cred)' "ldflags -X injects a secret into the binary (S4)"
scan_pattern S4-ARGV '^[[:space:]]*(ARG|ENV)[[:space:]]+[A-Za-z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Za-z0-9_]*(=|[[:space:]]+)[^[:space:]$]' "Dockerfile ARG/ENV with secret-looking name and a value (visible in image history)"
scan_pattern S4-ARGV '(--build-arg|--password|--token|--api-?key|--secret)[= ][A-Za-z0-9_./+=-]{12,}' "secret value on a command line (visible in ps/history) (S4)"
scan_pattern S4-ARGV '(curl|wget|http)[^|#]*[?&](api[_-]?key|token|access_token|secret|password|sig(nature)?)=[A-Za-z0-9_./+=-]{8,}' "secret in a URL query string (logged by servers/proxies) (S4)"

# Filter obviously benign hits (tests/docs placeholder lines) from non-assign rules too
sort -u "$WORK/raw-findings" >"$WORK/dedup"
while IFS="$(printf '\t')" read -r rule f ln note; do
	[ -n "${rule:-}" ] || continue
	finding "$rule" "$f" "$ln" "$note"
done <"$WORK/dedup"

# ---------------------------------------------------------------------------
# S8: secret-named files tracked / not ignored
# ---------------------------------------------------------------------------
if [ $IN_GIT -eq 1 ]; then
	{ git ls-files; git ls-files --others --exclude-standard; } | sort -u | while IFS= read -r f; do
		base="$(basename "$f")"
		case "$base" in
			*.example|*.sample|*.template|*.tmpl|*.dist|.env.example) continue ;;
			# Source, docs and scripts named after a concept (secret.go) are code, not data.
			*.go|*.md|*.rst|*.sh|*.bash|*.py|*.rb|*.js|*.mjs|*.ts|*.tsx|*.jsx|*.rs|*.java|*.kt|*.c|*.h|*.cc|*.cpp|*.cs|*.php|*.swift|*.lua|*.html|*.css) continue ;;
		esac
		if printf '%s' "$f" | grep -Eiq "$SENS_NAME"; then
			printf '%s\n' "$f"
		fi
	done >"$WORK/sensitive-names"
	while IFS= read -r f; do
		[ -n "$f" ] || continue
		if git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then
			finding S8-TRACKED "$f" 0 "secret-named file is TRACKED by git: remove from index, add to .gitignore, rotate, rewrite history if pushed"
		else
			finding S8-TRACKED "$f" 0 "secret-named file is NOT ignored (will be committed by git add .): add a .gitignore rule"
		fi
	done <"$WORK/sensitive-names"
	# Also: secret-named files that exist but are properly ignored are fine; report as info
fi

# ---------------------------------------------------------------------------
# Literals (from --literal-file) and artifacts
# ---------------------------------------------------------------------------
TOKENS=""
if [ -n "$LITFILE" ]; then
	TOKENS="$WORK/tokens"
	# Split on whitespace and separators, keep tokens of 8+ chars. Order
	# preserved; no value is ever printed.
	tr -s '[:space:]=:,;"'"'"'' '\n' <"$LITFILE" | grep -E '.{8,}' | sort -u >"$TOKENS"
	chmod 600 "$TOKENS"
	if [ ! -s "$TOKENS" ]; then
		echo "secret-scan: --literal-file has no tokens of 8+ characters; literal search skipped" >&2
		TOKENS=""
	fi
fi

if [ -n "$TOKENS" ]; then
	# Source tree: every non-ignored file, binary or not, except the literal file.
	litabs="$(cd "$(dirname "$LITFILE")" && pwd)/$(basename "$LITFILE")"
	if [ $IN_GIT -eq 1 ]; then
		{ git ls-files; git ls-files --others --exclude-standard; } | sort -u
	else
		find . -type f -not -path './.git/*' | sed 's|^\./||'
	fi | while IFS= read -r f; do
		[ -f "$f" ] || continue
		[ "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" = "$litabs" ] && continue
		if grep -aqF -f "$TOKENS" -- "$f" 2>/dev/null; then
			printf '%s\n' "$f"
		fi
	done >"$WORK/lit-hits"
	while IFS= read -r f; do
		[ -n "$f" ] && finding LITERAL "$f" 0 "contains a known secret literal from --literal-file (value withheld)"
	done <"$WORK/lit-hits"
	# Git history (only if available): has the literal ever been committed?
	if [ $HAS_HEAD -eq 1 ]; then
		if git log --all -p -G"$(head -n1 "$TOKENS" | sed 's/[][\.*^$(){}?+|/]/\\&/g')" --format=%h 2>/dev/null | grep -q .; then
			finding LITERAL "(git history)" 0 "first known secret token appears in git history: treat as EXPOSED, rotate it"
		fi
	fi
fi

for a in ${ARTIFACTS[@]+"${ARTIFACTS[@]}"}; do
	if [ -d "$a" ]; then
		alist="$WORK/alist"; find "$a" -type f >"$alist"
	else
		alist="$WORK/alist"; printf '%s\n' "$a" >"$alist"
	fi
	while IFS= read -r af; do
		[ -f "$af" ] || continue
		if [ -n "$TOKENS" ] && grep -aqF -f "$TOKENS" -- "$af" 2>/dev/null; then
			finding ARTIFACT "$af" 0 "built artifact contains a known secret literal (value withheld): the secret is in the artifact; rotate it"
		fi
		# Pattern scan over printable strings
		if command -v strings >/dev/null 2>&1; then
			if strings -a -n 12 -- "$af" 2>/dev/null | grep -Eq -e "$PAT_KNOWN"; then
				finding ARTIFACT "$af" 0 "built artifact contains a known credential format (value withheld)"
			fi
		else
			if LC_ALL=C grep -aEq -e "$PAT_KNOWN" -- "$af" 2>/dev/null; then
				finding ARTIFACT "$af" 0 "built artifact contains a known credential format (value withheld)"
			fi
		fi
	done <"$alist"
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "SECRET-SCAN SUMMARY"
echo "root:      $ROOT"
echo "scope:     $SCOPE ($NFILES text file(s) scanned)"
if [ -n "$LITFILE" ]; then
	if [ -n "$TOKENS" ]; then echo "literals:  checked against $(wc -l <"$TOKENS" | tr -d ' ') token(s) from the literal file"
	else echo "literals:  SKIP (literal file had no usable tokens)"; fi
else
	echo "literals:  SKIP (no --literal-file given: known-literal search not performed)"
fi
if [ ${#ARTIFACTS[@]} -gt 0 ]; then echo "artifacts: ${ARTIFACTS[*]}"; else echo "artifacts: none"; fi
echo "optional:  gitleaks/trufflehog — $(command -v gitleaks >/dev/null 2>&1 && echo "gitleaks present (run it too)" || { command -v trufflehog >/dev/null 2>&1 && echo "trufflehog present (run it too)" || echo "SKIP (not installed)"; })"
echo "findings:  $COUNT"
if [ "$COUNT" -gt 0 ]; then
	echo
	printf '%-12s %-48s %-6s %s\n' RULE FILE LINE NOTE
	sort -t "$(printf '\t')" -k1,1 -k2,2 -k3,3n "$FINDINGS" | while IFS="$(printf '\t')" read -r rule f ln note; do
		printf '%-12s %-48s %-6s %s\n' "$rule" "$f" "$ln" "$note"
	done
	echo
	echo "result: FAIL ($COUNT finding(s)). Values are withheld. Fix the cause; do not suppress. If a real secret was exposed, rotate it."
	exit 1
fi
if [ "$NFILES" -eq 0 ] && [ ${#ARTIFACTS[@]} -eq 0 ]; then
	echo "result: NOTHING SCANNED (no text files in scope). Use --all if you expected files."
	exit 3
fi
echo "result: PASS (no findings in scope; this is a heuristic gate, not proof of absence)"
exit 0
