#!/usr/bin/env bash
# Smoke test for Phase 5b — gre_practice_test mode.
#
# Three checks, mirrors the smoke shape from Phase 5:
#   1. Classifier routes "give me a practice test" to gre_practice_test.
#   2. The generation agent persists a test file under
#      <vault>/knowledge/gre/practice-tests/.
#   3. POST /v1/practice-tests/<id>/grade returns a graded result, the
#      test file gains a "## Take N" section, two graders ran in parallel.
#
# Env resolution, in priority order:
#   1. DELPHI_TOKEN / DELPHI_URL exported in the calling shell
#   2. DELPHI_BEARER_TOKEN read from ./.env.docker (or ./.env)
#   3. Hardcoded defaults for DELPHI_URL and VAULT_HOST_PATH
# So you can just run ``./scripts/smoke_practice_test.sh`` from the
# project root on the VM — no Doppler or env juggling needed.

set -euo pipefail

# Locate repo root (this script's parent's parent) so it can be invoked
# from anywhere on the VM, not just from /root/Delphi.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Slurp .env.docker (preferred for the compose deploy) or .env, picking up
# DELPHI_BEARER_TOKEN at minimum. We do this with set -a so every assigned
# var auto-exports; the file is shell-syntax-compatible by convention.
load_env_file() {
  local f="$1"
  if [[ -f "$f" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$f"; set +a
    echo "loaded $f"
  fi
}
load_env_file "$REPO_ROOT/.env.docker" || true
load_env_file "$REPO_ROOT/.env" || true

URL="${DELPHI_URL:-https://delphi-1.tail6d29ca.ts.net}"
# Accept either DELPHI_TOKEN (smoke-script convention) or the canonical
# DELPHI_BEARER_TOKEN from .env.docker.
TOKEN="${DELPHI_TOKEN:-${DELPHI_BEARER_TOKEN:-}}"
if [[ -z "$TOKEN" ]]; then
  echo "FAIL: no token — set DELPHI_BEARER_TOKEN in .env.docker (or export DELPHI_TOKEN)" >&2
  exit 1
fi
VAULT="${VAULT_HOST_PATH:-/root/Vault}"

bold=$(tput bold 2>/dev/null || true)
reset=$(tput sgr0 2>/dev/null || true)

step() { echo -e "\n${bold}==> $*${reset}"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

# --- 1. Generation -------------------------------------------------------
step "1/4  Generate a 3-question practice test"
RESPONSE=$(curl -sS -X POST "$URL/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-client-id: delphi-ui" \
  -d '{
        "task_type": "gre_practice_test",
        "stream": false,
        "messages": [{"role":"user","content":"give me a 3-question GRE practice test, vocab-heavy"}]
      }')

echo "$RESPONSE" | python3 -c '
import json, sys
body = json.load(sys.stdin)
print(body["choices"][0]["message"]["content"][:400])
' || fail "generation request errored"

# Extract test_id from the [PREVIEW:practice-test:<id>] directive.
TEST_ID=$(echo "$RESPONSE" | python3 -c '
import json, re, sys
body = json.load(sys.stdin)
m = re.search(r"\[PREVIEW:practice-test:([^\]]+)\]", body["choices"][0]["message"]["content"])
if not m:
    sys.exit("no preview directive in response")
print(m.group(1))
') || fail "could not extract test_id from response"

echo "Generated test_id: $TEST_ID"

# --- 2. Test file on disk -----------------------------------------------
step "2/4  Verify the test file landed in the vault"
TEST_PATH="$VAULT/knowledge/gre/practice-tests/$TEST_ID.md"
if [[ ! -f "$TEST_PATH" ]]; then
  fail "no test file at $TEST_PATH — persist_test didn't write"
fi
echo "OK — $(wc -l < "$TEST_PATH") lines, frontmatter:"
head -20 "$TEST_PATH"

# Extract question_ids from the frontmatter to build a plausible answer set.
QUESTION_IDS=$(python3 - "$TEST_PATH" <<'PY'
import sys, yaml
text = open(sys.argv[1]).read()
fm_end = text.find("\n---", 4)
fm = yaml.safe_load(text[4:fm_end])
print(" ".join(fm["answer_key"].keys()))
PY
)
echo "Question IDs: $QUESTION_IDS"

# Build a JSON answers blob using "B" for every question — guarantees a
# meaningful (if wrong) grading run.
ANSWERS_JSON=$(python3 - <<PY
import json
qids = "$QUESTION_IDS".split()
print(json.dumps({"answers": {q: "B" for q in qids}}))
PY
)

# --- 3. Grade ------------------------------------------------------------
step "3/4  Submit answers; expect parallel two-model grading"
GRADE_RESPONSE=$(curl -sS -X POST "$URL/v1/practice-tests/$TEST_ID/grade" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$ANSWERS_JSON")

echo "$GRADE_RESPONSE" | python3 -c '
import json, sys
g = json.load(sys.stdin)
score = g.get("score", {})
print(f"Score: {score.get(\"correct\")}/{score.get(\"total\")} ({score.get(\"percent\")}%)")
graded_by = g.get("graded_by", {})
print(f"Primary: {graded_by.get(\"primary\")}")
print(f"Secondary: {graded_by.get(\"secondary\")}")
disagreements = sum(1 for q in g.get("questions", []) if q.get("disagreement"))
print(f"Disagreements surfaced: {disagreements}/{len(g.get(\"questions\", []))}")
'

# --- 4. Take landed in the file -----------------------------------------
step "4/4  Verify a ## Take 1 section was appended"
if ! grep -q "^## Take 1" "$TEST_PATH"; then
  fail "no ## Take 1 section in $TEST_PATH after grading"
fi
echo "OK — take landed:"
sed -n '/^## Take 1/,/^## Take 2\|\Z/p' "$TEST_PATH" | head -15

# Bonus: confirm classifier + log are healthy.
step "Log tail"
docker exec delphi-delphi-1 tail -3 /var/log/delphi/requests.jsonl 2>/dev/null \
  | jq -r '"\(.task_type) | \(.model) | tokens_out=\(.output_tokens)"' \
  || echo "(skipping log tail — not on the Docker host)"

echo -e "\n${bold}Phase 5b smoke: PASS${reset}"
