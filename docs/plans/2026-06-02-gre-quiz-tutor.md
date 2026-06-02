# Phase 5 — `gre_quiz` Tutor Mode

> **Frame.** The library has shelves (Phase 1), the shelves are stocked
> (Phase 2), the librarian knows to walk them (Phase 3). Phase 5 turns
> the librarian into a **tutor** — Delphi picks cards off the shelf, runs
> a Socratic drill, and writes back what you learned. The substrate
> (2,012 typed vocab cards with SRS-ready frontmatter) is already there.
> What's missing is the loop that walks a card through `ask → grade →
> update → next`.
>
> Analogy: today, Delphi is a flashcard box you can search through. After
> Phase 5, Delphi is the friend sitting across the table flipping the
> cards for you and writing the dates on the back. Same cards, same box —
> a person added.

---

## Locked design decisions (from session intake)

| Decision | Choice | Why |
|---|---|---|
| **State** | Vault state file `state/active-quiz.md` | Single-user box, durable across restarts, debuggable with `cat`, no Redis dependency for quiz core. |
| **Grading** | Model-judged (tutor-style) | More conversational; the soul has guardrails about strictness. User can override by saying "no, that was wrong." |
| **Entry** | Classifier learns it | Matches `vault_query` pattern. UI button is a future polish, not a v1 blocker. |

---

## Scope, hard-cut

Phase 5 ships when:

1. **Routing.** "quiz me on 5 hard GRE words" classifies as `gre_quiz`. Explicit `task_type: gre_quiz` also routes here.
2. **Pick.** Agent picks N cards (default 10) from `knowledge/gre/vocab/` filtered by `difficulty` and SM-2 due-date. Filters can be tightened by the user ("only canonical", "only words tagged intelligence").
3. **Loop.** Agent asks one card at a time. User answers in plain text. Agent grades, says correct/partial/incorrect, reveals the canonical definition + mnemonic + confusion set, moves on.
4. **Update.** Every card → SM-2 update lands in the card's `review:` frontmatter atomically (file rewrite under a tempfile + rename).
5. **Summary.** After N cards or on user "stop": session summary (accuracy by difficulty, weak tags, proposed drill list). Session state file deleted.
6. **Persistence.** The whole exchange writes a normal conversation note with `task_type: gre_quiz`; the per-card SRS updates land in the vocab cards themselves.

**Out of scope for v1:** weighting cards by recency-of-error, leech detection, multi-domain quizzes (`gre_quant` quiz, Spanish verb quiz). All readable upgrades behind the same shape.

---

## Architecture

```
client ──► /v1/chat/completions  (task_type: gre_quiz or classified)
                │
                ▼
          api/chat.py → _handle_gre_quiz(...)
                │
                ▼
        routing/quiz_agent.py  ◄── bounded tool loop
                │
        ┌───────┼──────────────┬──────────────┬──────────────┐
        ▼       ▼              ▼              ▼              ▼
   list_due_   read_note   record_review   end_quiz_   (existing)
   cards     (vault_reader) (memory/srs)   session     search_vault
        │                       │
        │                       ▼
        │                memory/vocab_card.py  ← splice review: block
        ▼
   memory/quiz_state.py ─── reads/writes ──► /vault/state/active-quiz.md
```

Three new modules, one extended:

| Module | Purpose |
|---|---|
| `memory/srs.py` | Pure-function SM-2: `(grade, prev_ease, prev_interval) → (new_ease, new_interval, next_due)`. No I/O. Easy to unit-test. |
| `memory/vocab_card.py` | Read/write a single vocab card's `review:` block. Atomic rewrite via tempfile + rename. Preserves the rest of the file byte-for-byte. |
| `memory/quiz_state.py` | Active-quiz session file. One per `client_id`. YAML frontmatter (deck, current index, asked-so-far, started_at) + markdown body (running transcript). |
| `routing/quiz_agent.py` | Bounded tool loop, same shape as `vault_agent.py`. New tools below. |

Reused: `VaultReader` for `search_vault`/`read_note`, `OllamaClient.chat` for tool-calling, `ConversationRecord` + `run_persist` for the session note.

---

## Tool surface (what the model sees)

The agent exposes these to the model. Schemas mirror OpenAI function-calling.

### `list_due_cards`

Pick N cards to drill. Returns vault paths + lightweight metadata (no full body — the agent calls `read_note` when it's ready to ask).

```
parameters:
  n              integer   default 10
  difficulty     string?   easy|medium|hard|brutal|obscure (any if omitted)
  tags_any       [string]? at least one of these tags (e.g. ["canonical"])
  only_due       boolean   default true; if false, ignore SM-2 due-date
  domain         string    default "gre"; future-proofs for spanish/etc.

returns: JSON
  cards: [
    {path: "knowledge/gre/vocab/abjure.md", word: "abjure",
     difficulty: "hard", tags: ["gre","vocab","canonical"],
     ease: 2.5, interval_days: 0, last_reviewed: null}
  ]
  total_matched: 47          # before slicing to n
  filters_applied: {...}
```

### `record_review`

Apply an SM-2 update to one card. Idempotent on (path, grade) within a session — calling it twice for the same card in one quiz overwrites cleanly.

```
parameters:
  path          string    vault-relative path from list_due_cards
  grade         integer   0–5 (SM-2 scale, see grading rubric below)
  user_answer   string?   what the user said, for the session note
  notes         string?   tutor's reasoning, for the session note

returns: JSON
  ok: true
  new_ease: 2.36
  new_interval_days: 6
  next_due: "2026-06-08"
```

### `end_quiz_session`

Close the session: delete the state file, return summary stats so the model can compose its sign-off.

```
parameters:
  reason  string  "completed" | "user_stopped" | "error"

returns: JSON
  cards_total: 10
  cards_graded: 8
  accuracy_overall: 0.625
  accuracy_by_difficulty: {hard: 0.4, brutal: 0.0, medium: 0.83}
  weak_tags: ["philosophy", "speech"]
  drill_suggestion: ["abjure", "extol", "obviate"]   # 3 worst
```

Plus the existing read-only `search_vault` and `read_note` for free-form lookups mid-session ("wait, what's the difference between perspicacious and perspicuous?" → the model can still answer).

---

## State file shape (`<vault>/state/active-quiz.md`)

One file per active session. `client_id` keys the filename when we ever support multi-client; for v1 there's one Tali.

```markdown
---
type: quiz-session
client_id: delphi-ui
session_id: 01HXPQ9...           # ULID
started_at: 2026-06-02T14:23:10-05:00
domain: gre
filters:
  difficulty: hard
  tags_any: [canonical]
  only_due: true
deck:
  - {path: knowledge/gre/vocab/abjure.md, word: abjure, asked: true, grade: 3, user_answer: "to renounce"}
  - {path: knowledge/gre/vocab/extol.md, word: extol, asked: true, grade: 5, user_answer: "to praise highly"}
  - {path: knowledge/gre/vocab/obviate.md, word: obviate, asked: false}
current_index: 2                  # 0-based, points at "obviate"
n_target: 10
---

# Active quiz — gre / hard / canonical

> Started 2026-06-02 14:23. 10 cards. 2 graded so far.

## Log
- **abjure** — user: "to renounce" — grade 3 (Good). ✓
- **extol** — user: "to praise highly" — grade 5 (Easy). ✓
```

Two reasons this file exists rather than Redis:

1. **Resumable across restarts.** `docker compose restart` mid-quiz doesn't lose the session.
2. **Inspectable.** When something looks wrong, `cat /root/Vault/state/active-quiz.md` shows exactly what the model thinks the state is.

**Concurrency.** v1 is single-user. If two clients ever quiz simultaneously, the filename becomes `state/active-quiz-<client_id>.md`. Today: one file, last-writer-wins, fine.

**Eviction.** A stale state file >24h old is treated as abandoned; on a new "quiz me" request the agent rolls a new session and overwrites. (Soul rule.)

---

## SM-2 update (the `srs.py` math)

Textbook SM-2 with one simplification — we don't track "repetitions" as a separate counter; `interval_days` doubles as the repetition signal (0 = brand new, ≥1 = seen).

```python
def update(prev: ReviewState, grade: int) -> ReviewState:
    """
    grade: 0–5
      0 = total blackout
      1 = wrong answer, but the right one felt familiar on reveal
      2 = wrong, but easy to remember once seen
      3 = correct with serious difficulty           ← passing threshold
      4 = correct after a hesitation
      5 = correct, easy, immediate
    """
    if grade < 3:
        # Fail: reset interval, keep ease but floor it
        new_interval = 1
        new_ease = max(1.3, prev.ease - 0.2)
    else:
        # Pass: extend interval geometrically
        if prev.interval_days == 0:
            new_interval = 1
        elif prev.interval_days == 1:
            new_interval = 6
        else:
            new_interval = round(prev.interval_days * prev.ease)
        # SM-2 ease adjustment
        delta = 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)
        new_ease = max(1.3, prev.ease + delta)
    return ReviewState(
        ease=round(new_ease, 2),
        interval_days=new_interval,
        last_reviewed=now_local(),
    )
```

Properties this gives:

- **Lapse penalty.** Wrong answer → next review tomorrow, ease drops.
- **Slow ramp.** First correct → 1 day; second correct → 6 days; then geometric on ease.
- **Floor at 1.3.** Cards never reach "trivial" — even leeches stay scheduled.

This is the same shape Anki uses. We're not innovating here; we're using a known-good algorithm so we don't accidentally invent a worse one.

**Grading rubric handed to the model** (lives in the soul appendix):

| User behavior | Grade |
|---|---|
| User: "no idea" / "skip" / says nothing meaningful | 0 |
| Wrong, but recognizes the right answer on reveal ("oh right!") | 1 |
| Wrong, but a near-synonym or right-family ("means like, bossy?" for "imperious") | 2 |
| Right with effort or hedging ("I think… contradiction?" for "paradox") | 3 |
| Right, slight pause | 4 |
| Right, instant, full definition | 5 |

The model judges. Tutor-style. If the user objects ("no I got that one right"), the model can call `record_review` again with the corrected grade — `record_review` is idempotent within a session.

---

## Conversation flow (worked example)

```
USER:    quiz me on 5 hard GRE words from the canonical list

[classifier → gre_quiz]
[agent starts, no active state file → fresh session]

AGENT (internally):
  list_due_cards(n=5, difficulty="hard", tags_any=["canonical"], only_due=false)
  → [abjure, extol, obviate, perfunctory, recalcitrant]
  write state/active-quiz.md
  read_note("knowledge/gre/vocab/abjure.md")

AGENT (to user):
  Quiz on. 5 hard canonical words. Card 1 of 5: **abjure**.
  (Take your shot — definition, part of speech, however you want to answer.)

USER:    to renounce something formally, like a belief

AGENT (internally):
  read_note for the card was already cached in conversation; it judges:
  "to renounce something formally, like a belief" matches
  "to renounce a claim, opinion, or course of conduct" → grade 4
  record_review(path=".../abjure.md", grade=4, user_answer="...",
                notes="hit the renounce sense; missed the 'under oath' nuance")
  read_note("knowledge/gre/vocab/extol.md")

AGENT (to user):
  ✓ Solid — that's the renounce/recant sense. Worth knowing it often
  carries a formal "under oath" flavor too (you abjure heresy in court,
  not just at brunch). Card 2 of 5: **extol**.

… (3 more cards) …

USER:    stop, I'm tired

AGENT (internally):
  end_quiz_session(reason="user_stopped")
  → {cards_graded: 3, accuracy_overall: 0.66, weak_tags: ["philosophy"]}

AGENT (to user):
  Stopping at card 3 of 5. You graded 3 cards, 2 hits (66%). Your weak
  spot today was philosophy-flavored words — `obviate` and `recalcitrant`
  both fell into it. Want me to queue 5 more on that theme next session?
  Source: knowledge/gre/vocab/abjure.md,
          knowledge/gre/vocab/extol.md,
          knowledge/gre/vocab/obviate.md
```

The conversation note that `run_persist` writes captures the whole exchange under `conversations/2026-06-02/14-23_quiz-on-5-hard-gre-words.md` with `task_type: gre_quiz` in its frontmatter, plus the entity wikilinks to each card.

---

## Soul appendix (the `GRE_QUIZ_APPENDIX`)

Appended to `BASE_SOUL` when `task_type == gre_quiz`. Three concerns:

1. **Procedure** — explicit step order so the model doesn't skip writes.
2. **Grading rubric** — the 0–5 scale + behavior table above.
3. **Tutor voice** — terse, kind, calibrated. Not a cheerleader. Reveals the canonical definition + mnemonic + confusion set on every card so the user *learns*, not just gets quizzed.

Soul ordering becomes: `BASE → CODING (if applicable) → VAULT_QUERY (if applicable) → GRE_QUIZ (if applicable) → UI (if applicable)`. Tests pin this.

---

## Classifier nudges (the smallest part)

Add to `_system_prompt()`'s exemplars:

```
"quiz me on 10 hard GRE words"           → gre_quiz
"run me through some vocab cards"         → gre_quiz
"drill me on canonical GRE words"         → gre_quiz
"start a vocab review session"            → gre_quiz
"keep going" / "stop" / "next"            → gre_quiz   (mid-session continuation)
```

Mid-session continuation is the trick. "next card" alone is ambiguous, but if the previous classifier history is `gre_quiz` we'd want to stay there. v1 punt: the model in a quiz session almost always has the user reply parse as `gre_quiz` because the user's turns reference vocabulary. If it misclassifies as `chat`, the user simply re-asks "next" and it re-routes. Better fix in v2: classifier sees the prior assistant turn.

`TASK_TYPES` in `routing/roster.py` grows by one: `"gre_quiz"`. `TASK_METADATA` adds an entry (`{"temperature": 0.3}`). `_FALLBACK_MODELS` and `Config.delphi_model_gre_quiz` both point at the same tool-capable cloud tag as `vault_query` (default `gpt-oss:120b-cloud`).

---

## File layout

```
routing/
├── quiz_agent.py          ← new, mirrors vault_agent.py
└── (soul.py, classifier.py, roster.py — modified)

memory/
├── srs.py                 ← new, pure SM-2
├── vocab_card.py          ← new, frontmatter splicer
└── quiz_state.py          ← new, active-quiz.md handler

api/
└── chat.py                ← modified, branch to _handle_gre_quiz

config.py                  ← modified, delphi_model_gre_quiz

tests/
├── test_srs.py            ← new, SM-2 math
├── test_vocab_card.py     ← new, round-trip splicer
├── test_quiz_state.py     ← new, state-file read/write
├── test_quiz_agent.py     ← new, mocked Ollama
└── test_gre_quiz_route.py ← new, end-to-end with respx

docs/plans/2026-06-02-gre-quiz-tutor.md   ← this file
```

No `vault-seed/` changes required — the vocab cards already carry the schema.

---

## Test strategy

| Layer | Test | What it pins |
|---|---|---|
| `srs.py` | Table-driven: grade 0..5 × initial (0,1,6,30) day intervals | Lapse resets, ease floors at 1.3, geometric ramp matches Anki reference. |
| `vocab_card.py` | Round-trip: parse → update review block → re-parse, body bytes unchanged outside frontmatter | No collateral damage to hand-curated cards. |
| `quiz_state.py` | Write → read → mutate → write → read | Idempotency, atomic rename, empty-deck case. |
| `quiz_agent.py` | Mock Ollama returning a scripted tool-call sequence (`list_due_cards` → `read_note` → no-tools-final) | Loop bounded by max_steps. |
| `test_gre_quiz_route.py` | respx-mocked Ollama, in-memory vault under tmp_path, full 3-card session | The whole chain, including persist. |
| Smoke run | `docker compose` + curl + tail JSONL log | Production wiring actually works. |

Coverage target: every public function in the three new memory modules has a happy-path test and at least one edge case. Agent loop has a "model never calls a tool" test and a "model loops forever" test.

---

## Failure modes and what we do about them

| Failure | Behavior |
|---|---|
| State file unreadable mid-session | Treat as no active session; agent rolls a new one. Tali sees one card repeated; harmless. |
| `record_review` succeeds but `quiz_state.py` write fails | Card update sticks (source of truth is the card itself), session log loses one entry. Log a warning. |
| Model picks a card that doesn't exist on disk | `read_note` errors → agent retries with a different card from `list_due_cards`. Bounded by `max_steps`. |
| User answers in Spanish or with an emoji | Model's call; grading rubric covers "wrong" gracefully. |
| Agent hits `max_steps` | Final answer is forced (existing vault-agent pattern). User sees the partial summary; state file remains for next request. |
| Vocab card frontmatter malformed | `vocab_card.read` raises; agent treats card as ungradeable; record_review returns error. Drop it from the deck and continue. |

---

## Phased delivery within Phase 5

1. **5a — SRS + card splicer.** `memory/srs.py` + `memory/vocab_card.py` + tests. Doesn't ship a feature, but unblocks everything else and is testable in isolation. ~2h.
2. **5b — State file.** `memory/quiz_state.py` + tests. ~1h.
3. **5c — Tools + agent.** `routing/quiz_agent.py` + the three new tools. Tested with mocked Ollama. ~3h.
4. **5d — Routing.** Roster entry + classifier exemplars + soul appendix + config. ~1h.
5. **5e — Route branch.** `api/chat.py` learns to call `_handle_gre_quiz`. End-to-end test passes. ~1h.
6. **5f — Smoke run.** Docker deploy, real quiz session, tail log, verify a vocab card's `review:` block changed on disk. ~30m.

Total: ~1.5 days of focused work. Each slice ships green CI; no slice depends on speculative parts of the next.

---

## What this unlocks

The same `gre_quiz` shape generalizes the moment a second `knowledge/<domain>/` arrives. Rename to `quiz` (no `gre_` prefix), parameterize `domain="gre"` in `list_due_cards`, done. Spanish irregular verbs, algotrading flashcards, drug-dosage cards — the substrate is already domain-agnostic; only the soul rubric for "what counts as a correct answer" needs per-domain tuning.

It also feeds back into the **embedding sidecar** decision. Once Tali is quizzing daily, mis-grades and weak-tag clusters expose where keyword retrieval is failing the tutor (e.g. "the model can't find the right card when I describe a synonym"). That's the evidence we'd point at to justify the embedding work.

---

## Open question — needs Tali's call before 5c

The soul rubric defaults to **fail-on-anything-below-grade-3** (SM-2 standard). For a vocab-only domain, that means hedged-but-correct answers ("uh… something like astute?") get re-queued tomorrow. If Tali wants a gentler curve for vocab specifically — "if you got the *sense* right, that's a 3 regardless of confidence" — that lives in the soul appendix, not the math. Decide when 5d lands.

---

## Decision-log entry (append to `CLAUDE.md` when 5f ships)

> **2026-06-02** — `gre_quiz` task type added. Tool-calling agent loop
> (`routing/quiz_agent.py`) walks N cards from `knowledge/gre/vocab/`,
> grades model-side (tutor-style), and updates each card's `review:`
> frontmatter via the new `memory/srs.py` (SM-2 lite) +
> `memory/vocab_card.py` (atomic frontmatter splicer). Session state
> lives at `state/active-quiz.md` inside the vault — survives container
> restarts, inspectable with `cat`. Rationale: turns the read-only
> `vault_query` librarian into a writeback tutor without introducing
> Redis-as-source-of-truth; the cards remain the durable record. Same
> shape generalizes to any future `knowledge/<domain>/` quiz; rename
> `gre_quiz` → `quiz` with a `domain` parameter when the second domain
> arrives.
