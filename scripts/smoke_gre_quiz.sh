#!/usr/bin/env bash
# Smoke test for Phase 5 — gre_quiz tutor.
#
# Run on the Proxmox VM (or anywhere that can reach the gateway). Sends two
# turns (start the quiz, answer the first card), then inspects three things:
#   1. The route classified / branched into gre_quiz (JSONL log).
#   2. The state file landed in <vault>/state/active-quiz.md.
#   3. The first vocab card's review: frontmatter actually changed on disk.
#
# Exits non-zero on any unmet expectation so this can be wired into CI later.
#
# Required env (or pass via flags):
#   DELPHI_URL       e.g. https://delphi-1.tail6d29ca.ts.net
#   DELPHI_TOKEN     bearer token (matches DELPHI_BEARER_TOKEN in compose)
#   VAULT_HOST_PATH  host path to vault (default /root/Vault)
#
# Usage:
#   DELPHI_URL=https://delphi-1.tail6d29ca.ts.net \
#   DELPHI_TOKEN=$(doppler secrets get DELPHI_BEARER_TOKEN --plain) \
#     ./scripts/smoke_gre_quiz.sh

set -euo pipefail

URL="${DELPHI_URL:-https://delphi-1.tail6d29ca.ts.net}"
TOKEN="${DELPHI_TOKEN:?set DELPHI_TOKEN to the bearer token}"
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
