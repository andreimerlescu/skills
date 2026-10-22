#!/usr/bin/env bash
# verify-go.sh — quality gate for the go-engineering-standards skill.
#
# Runs every step (never stops early), keeps full logs, and prints a
# VERIFY-GO SUMMARY block that agents must quote verbatim in their report.
# Missing optional tools are reported as SKIP, never as PASS.
#
# Compatible with bash 3.2 (macOS default) and later.

set -u

usage() {
	cat <<'EOF'
Usage: verify-go.sh [options] [module-dir] [-- extra go test args]

Run from a module root (a directory containing go.mod), or pass one.
If the directory has no go.mod, every module below it is checked.

Options:
  --race          also run 'go test -race ./...'
  --all           gofmt-check every .go file (default: only files changed
                  vs git HEAD plus untracked files; whole tree if not git)
  --vuln          run govulncheck ./... (SKIP if not installed)
  --staticcheck   run staticcheck ./... (SKIP if not installed)
  --shuffle       add -shuffle=on to go test
  --count N       add -count=N to go test (e.g. --count 1 to bypass cache)
  --no-scan       skip the heuristic diff scan for red flags
  -h, --help      show this help

Examples:
  verify-go.sh --race
  verify-go.sh --all --race --vuln ./services/api -- -run '^TestStore'
EOF
}

RACE=0; ALL=0; VULN=0; STATIC=0; SHUFFLE=0; COUNT=""; SCAN=1
TARGET="."
EXTRA_TEST_ARGS=()

while [ $# -gt 0 ]; do
	case "$1" in
		--race) RACE=1 ;;
		--all) ALL=1 ;;
		--vuln) VULN=1 ;;
		--staticcheck) STATIC=1 ;;
		--shuffle) SHUFFLE=1 ;;
		--count)
			shift
			case "${1:-}" in
				''|*[!0-9]*) echo "verify-go: --count needs a positive integer" >&2; exit 2 ;;
			esac
			COUNT="$1" ;;
		--no-scan) SCAN=0 ;;
		-h|--help) usage; exit 0 ;;
		--) shift; EXTRA_TEST_ARGS=("$@"); break ;;
		-*) echo "verify-go: unknown option: $1" >&2; usage >&2; exit 2 ;;
		*) TARGET="$1" ;;
	esac
	shift
done

if ! command -v go >/dev/null 2>&1; then
	echo "verify-go: 'go' not found on PATH. No checks were run." >&2
	echo "VERIFY-GO SUMMARY"
	echo "result: BLOCKED (go toolchain not installed)"
	exit 3
fi

if [ ! -d "$TARGET" ]; then
	echo "verify-go: not a directory: $TARGET" >&2
	exit 2
fi
TARGET="$(cd "$TARGET" && pwd)"

LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/verify-go.XXXXXX")"

# Parallel indexed arrays (bash 3.2 has no associative arrays).
S_NAME=(); S_STATUS=(); S_SECS=(); S_NOTE=(); S_LOG=()
FAILED=0
WARNINGS=0

record() { # name status secs note log
	S_NAME+=("$1"); S_STATUS+=("$2"); S_SECS+=("$3"); S_NOTE+=("$4"); S_LOG+=("$5")
	if [ "$2" = "FAIL" ]; then FAILED=$((FAILED + 1)); fi
	if [ "$2" = "WARN" ]; then WARNINGS=$((WARNINGS + 1)); fi
}

slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

# run_step NAME CMD... : runs CMD in the current directory, logs output.
run_step() {
	local name="$1"; shift
	local log start end rc
	log="$LOGDIR/$(slug "$MODLABEL-$name").log"
	start=$(date +%s)
	{
		printf '$'
		printf ' %q' "$@"
		printf '\n'
		"$@"
	} >"$log" 2>&1
	rc=$?
	end=$(date +%s)
	if [ $rc -eq 0 ]; then
		record "$MODLABEL: $name" PASS $((end - start)) "" "$log"
	else
		record "$MODLABEL: $name" FAIL $((end - start)) "exit $rc" "$log"
	fi
	return $rc
}

# version_lt A B : true if Go version A < B (e.g. 1.26.3 < 1.27.1).
version_lt() {
	local a="${1#go}" b="${2#go}"
	local IFS=.
	# shellcheck disable=SC2206
	local x=($a) y=($b)
	local i xa yb
	for i in 0 1 2; do
		xa="${x[$i]:-0}"; yb="${y[$i]:-0}"
		xa="${xa%%[!0-9]*}"; yb="${yb%%[!0-9]*}"
		xa="${xa:-0}"; yb="${yb:-0}"
		if [ "$xa" -lt "$yb" ]; then return 0; fi
		if [ "$xa" -gt "$yb" ]; then return 1; fi
	done
	return 1
}

changed_go_files() { # prints changed .go files relative to cwd, or nothing
	if [ $ALL -eq 1 ] || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
		|| ! git rev-parse --verify HEAD >/dev/null 2>&1; then
		return 1
	fi
	{
		git diff --name-only --relative --diff-filter=ACMR HEAD -- '*.go'
		git ls-files --others --exclude-standard -- '*.go'
	} | sort -u | while IFS= read -r f; do
		[ -f "$f" ] && printf '%s\n' "$f"
	done
	return 0
}

check_module() {
	local dir="$1"
	cd "$dir" || return
	MODLABEL="$(go list -m -f '{{.Path}}' 2>/dev/null || basename "$dir")"
	local log start end

	# --- toolchain vs go.mod -------------------------------------------------
	local gover modgo
	gover="$(go env GOVERSION 2>/dev/null)"
	modgo="$(go list -m -f '{{.GoVersion}}' 2>/dev/null)"
	log="$LOGDIR/$(slug "$MODLABEL-toolchain").log"
	{
		echo "toolchain: $gover"
		echo "go.mod go: ${modgo:-unknown}"
		go env GOTOOLCHAIN GOOS GOARCH CGO_ENABLED GOFLAGS
	} >"$log" 2>&1
	if [ -n "$modgo" ] && version_lt "$modgo" "1.27.1"; then
		record "$MODLABEL: go.mod go line" WARN 0 "go $modgo is below the skill floor 1.27.1 (do not change it unless the task requires)" "$log"
	else
		record "$MODLABEL: go.mod go line" INFO 0 "go ${modgo:-?} · toolchain $gover" "$log"
	fi

	# --- go mod verify -------------------------------------------------------
	run_step "go mod verify" go mod verify

	# --- gofmt ---------------------------------------------------------------
	log="$LOGDIR/$(slug "$MODLABEL-gofmt").log"
	start=$(date +%s)
	local files scope
	if files="$(changed_go_files)"; then
		scope="changed files"
	else
		files="$(find . -name '*.go' -not -path './vendor/*' -not -path '*/testdata/*' 2>/dev/null)"
		scope="all files"
	fi
	if [ -z "$files" ]; then
		end=$(date +%s)
		echo "no Go files in scope ($scope)" >"$log"
		record "$MODLABEL: gofmt ($scope)" SKIP $((end - start)) "no Go files in scope" "$log"
	else
		local unformatted
		# shellcheck disable=SC2086
		unformatted="$(printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 gofmt -l 2>&1)"
		end=$(date +%s)
		printf '%s\n' "$unformatted" >"$log"
		if [ -n "$unformatted" ]; then
			record "$MODLABEL: gofmt ($scope)" FAIL $((end - start)) "$(printf '%s\n' "$unformatted" | wc -l | tr -d ' ') file(s) need gofmt" "$log"
		else
			record "$MODLABEL: gofmt ($scope)" PASS $((end - start)) "" "$log"
		fi
	fi

	# --- build, vet, test ----------------------------------------------------
	run_step "go build ./..." go build ./...
	run_step "go vet ./..." go vet ./...

	local targs=(./...)
	[ $SHUFFLE -eq 1 ] && targs=(-shuffle=on "${targs[@]}")
	[ -n "$COUNT" ] && targs=(-count="$COUNT" "${targs[@]}")
	if [ ${#EXTRA_TEST_ARGS[@]} -gt 0 ]; then targs=("${targs[@]}" "${EXTRA_TEST_ARGS[@]}"); fi
	run_step "go test" go test "${targs[@]}"

	if [ $RACE -eq 1 ]; then
		if ! run_step "go test -race" go test -race "${targs[@]}"; then
			local i=$((${#S_STATUS[@]} - 1))
			if grep -Eqi 'race.*(requires cgo|not supported)|-race is not supported|cgo.*required' "${S_LOG[$i]}"; then
				S_STATUS[i]="SKIP"
				S_NOTE[i]="race detector unavailable on this platform/config (see log)"
				FAILED=$((FAILED - 1))
			fi
		fi
	fi

	# --- optional analyzers --------------------------------------------------
	if [ $STATIC -eq 1 ]; then
		if command -v staticcheck >/dev/null 2>&1; then
			run_step "staticcheck" staticcheck ./...
		else
			record "$MODLABEL: staticcheck" SKIP 0 "staticcheck not installed" ""
		fi
	fi
	if [ $VULN -eq 1 ]; then
		if command -v govulncheck >/dev/null 2>&1; then
			run_step "govulncheck" govulncheck ./...
		else
			record "$MODLABEL: govulncheck" SKIP 0 "govulncheck not installed" ""
		fi
	fi

	# --- heuristic red-flag scan of changed lines ----------------------------
	if [ $SCAN -eq 1 ]; then
		log="$LOGDIR/$(slug "$MODLABEL-scan").log"
		if git rev-parse --verify HEAD >/dev/null 2>&1 && [ $ALL -eq 0 ]; then
			# Added lines only, in this module's subtree, reported as file:line.
			git diff --relative -U0 HEAD -- '*.go' 2>/dev/null | awk '
				/^\+\+\+ / { file = substr($0, 5); sub(/^b\//, "", file); next }
				/^@@ / {
					# @@ -a,b +c,d @@  -> new-file line number c
					split($3, p, ","); line = substr(p[1], 2) + 0; next
				}
				/^\+/ {
					text = substr($0, 2)
					why = ""
					if (text ~ /panic\("TODO|\/\/ ?TODO|FIXME/)            why = "unfinished marker"
					else if (text ~ /t\.Skip(Now|f)?\(/)                  why = "test skip"
					else if (text ~ /\/\/ ?nolint/)                        why = "lint suppression"
					else if (text ~ /time\.Sleep\(/)                       why = "sleep (sync hack?)"
					else if (text ~ /context\.(Background|TODO)\(\)/)      why = "context root"
					else if (text ~ /http\.DefaultClient|http\.Get\(/)     why = "default HTTP client"
					else if (text ~ /exec\.Command(Context)?\(("|ctx, ")(ba)?sh"/) why = "shell exec"
					else if (text ~ /InsecureSkipVerify: *true/)           why = "TLS verification off"
					else if (text ~ /Sprintf\("%s:%d"/)                    why = "use net.JoinHostPort"
					else if (text ~ /(^|[^A-Za-z0-9_])_ = [A-Za-z_][A-Za-z0-9_.]*\(/) why = "discarded result"
					else {
						t = text; sub(/^[ \t]+/, "", t); n = split(t, f, /[ \t]+/)
						if (n == 3 && f[2] == ":=" && f[1] == f[3] && f[1] ~ /^[a-z][A-Za-z0-9_]*$/) why = "obsolete loop-var copy"
					}
					if (why != "") printf "%s:%d: [%s] %s\n", file, line, why, text
					line++
				}
			' >"$log" 2>/dev/null
			if [ -s "$log" ]; then
				record "$MODLABEL: red-flag scan (added lines)" WARN 0 "$(wc -l <"$log" | tr -d ' ') line(s) to justify in the report" "$log"
			else
				record "$MODLABEL: red-flag scan (added lines)" PASS 0 "" "$log"
			fi
		else
			echo "scan needs git with a HEAD commit and no --all" >"$log"
			record "$MODLABEL: red-flag scan" SKIP 0 "not a git repo, no HEAD, or --all" "$log"
		fi
	fi
}

# --- discover modules --------------------------------------------------------
MODULES=()
if [ -f "$TARGET/go.mod" ]; then
	MODULES=("$TARGET")
else
	while IFS= read -r m; do
		[ -n "$m" ] && MODULES+=("$(dirname "$m")")
	done <<EOF
$(find "$TARGET" -name go.mod -not -path '*/vendor/*' -not -path '*/testdata/*' 2>/dev/null | sort)
EOF
fi

if [ ${#MODULES[@]} -eq 0 ] || [ -z "${MODULES[0]}" ]; then
	echo "verify-go: no go.mod found at or below $TARGET. No checks were run." >&2
	echo "VERIFY-GO SUMMARY"
	echo "result: BLOCKED (no Go module found)"
	exit 3
fi

for m in "${MODULES[@]}"; do
	check_module "$m"
done

# --- summary -----------------------------------------------------------------
{
	echo
	echo "VERIFY-GO SUMMARY"
	echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo "toolchain: $(go env GOVERSION) $(go env GOOS)/$(go env GOARCH)"
	echo "target: $TARGET"
	echo "options: race=$RACE all=$ALL vuln=$VULN staticcheck=$STATIC shuffle=$SHUFFLE count=${COUNT:-default} extra=[${EXTRA_TEST_ARGS[*]:-}]"
	i=0
	while [ $i -lt ${#S_NAME[@]} ]; do
		note="${S_NOTE[$i]}"
		printf '%-5s %4ss  %s%s\n' "${S_STATUS[$i]}" "${S_SECS[$i]}" "${S_NAME[$i]}" "${note:+  — $note}"
		i=$((i + 1))
	done
	echo "logs: $LOGDIR"
	if [ $FAILED -gt 0 ]; then
		echo "result: FAIL ($FAILED failing step(s), $WARNINGS warning(s))"
	else
		echo "result: PASS ($WARNINGS warning(s); SKIP steps were NOT verified)"
	fi
} | tee "$LOGDIR/summary.txt"

# Show the tail of each failing log so the agent does not have to guess.
i=0
while [ $i -lt ${#S_NAME[@]} ]; do
	if [ "${S_STATUS[$i]}" = "FAIL" ] && [ -n "${S_LOG[$i]}" ]; then
		echo
		echo "----- last 40 lines: ${S_NAME[$i]} (${S_LOG[$i]}) -----"
		tail -n 40 "${S_LOG[$i]}"
	fi
	i=$((i + 1))
done

[ $FAILED -eq 0 ]
