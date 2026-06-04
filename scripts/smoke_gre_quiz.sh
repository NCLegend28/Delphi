#!/usr/bin/env bash
# Smoke test for Phase 5 — gre_quiz tutor.
#
# Run on the Proxmox VM (or anywhere that can reach the gateway). Sends two
# turns (start the quiz, answer the first card), then inspects three things:
#   1. The route classified / branched into gre_quiz (JSONL log).
#   2. The state file landed in <vault>/state/active-quiz.md.
#   3. The first vocab card's review: frontmatter actually changed on disk.
#
# Env resolution, in priority order:
#   1. DELPHI_TOKEN / DELPHI_URL exported in the calling shell
#   2. DELPHI_BEARER_TOKEN read from ./.env.docker (or ./.env)
#   3. Hardcoded defaults for DELPHI_URL and VAULT_HOST_PATH
# Just run ``./scripts/smoke_gre_quiz.sh`` from the repo root on the VM.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

load_env_file() {
  local f="$1"
  if [[ -f "$f" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$f"; set +a
  fi
}
load_env_file "$REPO_ROOT/.env.docker" || true
load_env_file "$REPO_ROOT/.env" || true

URL="${DELPHI_URL:-https://delphi-1.tail6d29ca.ts.net}"
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

# --- 1. Start a quiz session ---------------------------------------------
step "1/4  Start a 3-card hard-canonical quiz"
curl -sS -X POST "$URL/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "task_type": "gre_quiz",
        "stream": false,
        "messages": [{"role":"user","content":"quiz me on 3 hard canonical GRE words"}]
      }' | tee /tmp/gre_quiz_turn1.json | python3 -c '
import json, sys
body = json.load(sys.stdin)
content = body["choices"][0]["message"]["content"]
print(content)
' || fail "first request errored"

# --- 2. State file exists ------------------------------------------------
step "2/4  state/active-quiz.md exists in the vault"
if [[ ! -f "$VAULT/state/active-quiz.md" ]]; then
  fail "no state file at $VAULT/state/active-quiz.md — agent didn't list_due_cards"
fi
echo "OK — $(wc -l < "$VAULT/state/active-quiz.md") lines"

# Pull the first card's path out of the state frontmatter for the next step.
FIRST_CARD=$(python3 - "$VAULT/state/active-quiz.md" <<'PY'
import sys, yaml
text = open(sys.argv[1]).read()
fm_end = text.find("\n---", 4)
fm = yaml.safe_load(text[4:fm_end])
print(fm["deck"][0]["path"])
PY
)
FIRST_WORD=$(basename "$FIRST_CARD" .md)
echo "First card: $FIRST_WORD ($FIRST_CARD)"

# Snapshot its review block so we can see it change.
BEFORE=$(grep -A 3 "^review:" "$VAULT/$FIRST_CARD" || true)
echo "Before:"
echo "$BEFORE"

# --- 3. Answer the first card -------------------------------------------
step "3/4  Answer the first card; expect a grade + advance"
curl -sS -X POST "$URL/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
        \"task_type\": \"gre_quiz\",
        \"stream\": false,
        \"messages\": [
          {\"role\":\"user\",\"content\":\"quiz me on 3 hard canonical GRE words\"},
          {\"role\":\"assistant\",\"content\":\"Card 1 of 3: $FIRST_WORD. Take your shot.\"},
          {\"role\":\"user\",\"content\":\"I think $FIRST_WORD means something formal and a bit fancy — give me my next card\"}
        ]
      }" | python3 -c 'import json,sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"])' \
  || fail "second request errored"

# --- 4. Card's review block changed -------------------------------------
step "4/4  Confirm the review: block on disk changed"
AFTER=$(grep -A 3 "^review:" "$VAULT/$FIRST_CARD" || true)
echo "After:"
echo "$AFTER"

if [[ "$BEFORE" == "$AFTER" ]]; then
  fail "review: block did not change — record_review didn't write through"
fi
echo "OK — vocab card writeback confirmed."

# Bonus: tail the JSONL log to verify classification.
step "Log tail"
docker exec delphi-delphi-1 tail -2 /var/log/delphi/requests.jsonl \
  | jq -r '"\(.task_type) | \(.model) | output_tokens=\(.output_tokens) | vault_write=\(.vault_write.ok)"' \
  || echo "(skipping log tail — not on the Docker host)"

echo -e "\n${bold}Phase 5 smoke: PASS${reset}"
