# Phase 5b — GRE Practice Test Mode

> **Frame.** Phase 5 gave you a flashcard tutor — one card at a time, SM-2
> schedule, daily review. Phase 5b gives you a **mock exam** — a full
> multi-section test, take it like the real GRE, submit your answers, get
> graded by two models in parallel that don't see each other's work.
>
> Analogy: Phase 5 is your Anki deck (light, daily, single-card). Phase 5b
> is a Manhattan 5-lb book practice section (heavy, weekly, full-test).
> Different cadences, same library underneath.

---

## Locked design decisions

| Decision | Choice |
|---|---|
| **Answer entry** | Editable preview pane with form inputs per question + "Submit" button |
| **Question source** | Hybrid: vocab + quant from `knowledge/gre/`; RC + SE model-generated |
| **Grading** | Parallel independent two-model cross-check |
| **State** | Each test is a persisted vault artifact under `knowledge/gre/practice-tests/` |
| **Entry** | New task type `gre_practice_test`; classifier learns it |

---

## What Phase 5b ships

1. **Generation.** "Give me a 10-question GRE practice test" → agent composes a
   typed test: pulls vocab text-completion stems from `knowledge/gre/vocab/`,
   quant problems from `knowledge/gre/quant/`, generates RC passages + sentence-
   equivalence + harder verbal from the model. Persists as one markdown file
   under `knowledge/gre/practice-tests/<test_id>.md` with the answer key in YAML
   frontmatter (visible to the service, hidden from the rendered user view).
2. **Editable preview.** UI's `PreviewBlock` learns a new kind `practice-test`
   that renders the test as a form (one input per question, multi-select for
   sentence-equivalence). Submit button POSTs filled answers to a new endpoint.
3. **Grading.** `POST /v1/practice-tests/{test_id}/grade` invokes the grading
   agent: two grader models in parallel, blind to each other. Service reconciles
   — matching grades pass through; disagreements surface a second-opinion note
   per question. Graded result writes back to the same test file under a `## Take N` section.
4. **Routing fix.** Classifier learns "give me a quiz on my GREs" and similar
   vague phrasings — currently they slip through to `vault_query` / `chat`. Adds
   exemplars for both `gre_quiz` (drill mode) and `gre_practice_test` (test mode).

---

## Architecture

```
generation request                              grading request
"give me a 10q practice test"          POST /v1/practice-tests/{id}/grade
       │                                            │
       ▼                                            ▼
classifier → gre_practice_test          api/practice_tests.py
       │                                            │
       ▼                                            │
api/chat.py → _handle_practice_test                 │
       │                                            │
       ▼                                            ▼
   routing/practice_test_agent.py ────► tools: generate_section
                                              │      persist_test
                                              │      grade_answers (uses cross_grade)
                                              │      load_test
                                              ▼
                                       memory/practice_test.py
                                              │
                                              ▼
                                       <vault>/knowledge/gre/practice-tests/
                                            <test_id>.md
```

```
memory/cross_grade.py  — parallel two-model grading helper

    asyncio.gather(
        ollama.chat(model=primary, …grading prompt + answers…),
        ollama.chat(model=secondary, …grading prompt + answers…),
    )
        → reconcile_grades(primary_result, secondary_result)
        → { per_question: { grade, reasoning, second_opinion? }, summary }
```

Five new modules; one extended.

| Module | Purpose |
|---|---|
| `memory/practice_test.py` | Schema + read/write/list of persisted tests. One test = one markdown file with YAML answer key. |
| `memory/cross_grade.py` | Pure helper: take a grading prompt + answer key + user answers, fire two parallel calls, reconcile, return structured grades + disagreement notes. |
| `routing/practice_test_agent.py` | Bounded tool loop for generation. Tools: `generate_vocab_section`, `generate_quant_section`, `generate_rc_section`, `generate_se_section`, `persist_test`. Final agent returns the test markdown framed as `[PREVIEW:practice-test:<id>]…[/PREVIEW]`. |
| `api/practice_tests.py` | New FastAPI router: `POST /v1/practice-tests/{id}/grade`, `GET /v1/practice-tests/{id}` (for the UI to refetch state). Bearer auth, same as chat. |
| `routing/soul.py` | New `PRACTICE_TEST_APPENDIX` block teaching generation procedure + grading rubric. Soul order grows: BASE → CODING → VAULT_QUERY → GRE_QUIZ → PRACTICE_TEST → UI. |

UI changes:
- `ui/src/components/OutputCanvas/PreviewBlock.jsx` — new branch for `kind=practice-test` rendering an answer form
- `ui/src/lib/practiceTest.ts` — client for the grade endpoint
- `ui/src/components/PracticeTestResult.jsx` — graded view with second-opinion badges

---

## Test file schema

```markdown
---
type: gre-practice-test
test_id: 01HXYZ...
created: 2026-06-03T10:00:00-05:00
sections:
  - {kind: text_completion, n: 2}
  - {kind: sentence_equivalence, n: 2}
  - {kind: reading_comprehension, n: 2, passage_id: rc1}
  - {kind: problem_solving, n: 3}
  - {kind: data_interpretation, n: 1, table_id: di1}
n_questions: 10
sources:
  vocab: [knowledge/gre/vocab/perspicacious.md, knowledge/gre/vocab/sycophant.md]
  quant: [knowledge/gre/quant/permutations-vs-combinations.md]
answer_key:
  q1: {answer: "B", rubric: "conciliatory — desire to please both sides"}
  q2: {answer: "B", rubric: "meandering — leaves reader uncertain"}
  q3: {answer: ["B","D"], rubric: "monotonous, tedious — both = boring"}
  q4: {answer: ["A","F"], rubric: "ambitious + prudent (or A,D)"}
  q5: {answer: "D", rubric: "advances in battery storage isn't in the passage"}
  q6: {answer: "B", rubric: "intermittency → grid complexity"}
  q7: {answer: "3", rubric: "3x - 7 = 2 → x = 3"}
  q8: {answer: "32", rubric: "8 × 4 = 32"}
  q9: {answer: "50", rubric: "70 - 20 = 50"}
  q10: {answer: "2", rubric: "median of 17 values, 9th value"}
takes: []   # appended on each grading run
---

# GRE Practice Test — 10 questions

## Verbal Reasoning

### Text Completion
1. The committee's decision was **______**, …
   - (A) ambiguous (B) conciliatory (C) obstinate (D) equivocal (E) indifferent
…
```

**Why frontmatter for the answer key.** Service-readable, parseable with the
existing `vocab_card` style YAML pattern, hidden from the UI's rendered view
(the UI strips frontmatter on render). The user can `cat` the file if curious,
which is feature, not bug.

**Why no separate Markdown body for answers.** The user's answers come in via
the grade endpoint as JSON, not as edits to the test file. Cleaner separation:
test file = canonical question set + key; graded takes = appended sections.

**Take N format** (appended on each grading):

```markdown
## Take 1 — 2026-06-03 10:14

- Submitted: q1=B, q2=B, q3=B,D, q4=A,F, q5=D, q6=B, q7=3, q8=32, q9=50, q10=2
- **Score: 10/10 (100%)**
- Primary grader: gpt-oss:120b-cloud
- Secondary grader: deepseek-v3.1:671b-cloud
- Reconciliation: all grades matched

| Q | Your answer | Correct | Grade | Notes |
|---|-------------|---------|-------|-------|
| 1 | B           | B       | ✓     | Both graders agree |
| 2 | B           | B       | ✓     | — |
| 3 | B,D         | B,D     | ✓     | — |
…
```

---

## API surface

### `POST /v1/chat/completions` (existing route, new branch)

Triggered by `task_type=gre_practice_test` or classifier routing. The agent
generates a test, persists it, returns the test markdown wrapped in the new
preview directive:

```
[PREVIEW:practice-test:01HXYZ...]
# GRE Practice Test — 10 questions
… full test body …
[/PREVIEW]
```

The UI parses the test_id out of the directive and renders the editable form.

### `POST /v1/practice-tests/{test_id}/grade` (new endpoint)

```json
// request
{
  "answers": {
    "q1": "B", "q2": "B", "q3": ["B","D"], "q4": ["A","F"],
    "q5": "D", "q6": "B", "q7": "3", "q8": "32", "q9": "50", "q10": "2"
  }
}

// response (200)
{
  "test_id": "01HXYZ...",
  "take_n": 1,
  "score": {"correct": 10, "total": 10, "percent": 100},
  "graded_by": {
    "primary": "gpt-oss:120b-cloud",
    "secondary": "deepseek-v3.1:671b-cloud"
  },
  "questions": [
    {
      "id": "q1",
      "your_answer": "B",
      "correct_answer": "B",
      "grade": "correct",
      "primary_reasoning": "B = conciliatory matches the desire to please both",
      "secondary_reasoning": "Agreed; B is the only option that fits both clauses",
      "disagreement": null
    },
    …
  ]
}
```

When primary and secondary disagree:

```json
{
  "id": "q3",
  "your_answer": ["B","D"],
  "correct_answer": ["B","D"],
  "grade": "correct",
  "primary_reasoning": "Both monotonous and tedious mean boring",
  "secondary_reasoning": "Tedious only — monotonous is about sameness not boringness",
  "disagreement": "Secondary marked partial; primary marked correct. Surfacing both for your judgment."
}
```

The service does NOT choose a winner on disagreement — it returns both so Tali
sees the disagreement honestly. (Inflation hurts learning; surfaced
disagreement teaches it.)

### `GET /v1/practice-tests/{test_id}`

Returns the test JSON (questions + answer key blank in the response unless
`?include_key=true`) so the UI can re-load a test the user navigated away from.

---

## Cross-check grader (`memory/cross_grade.py`)

```python
@dataclass(frozen=True, slots=True)
class GradedAnswer:
    question_id: str
    user_answer: str | list[str]
    correct_answer: str | list[str]
    grade: Literal["correct", "partial", "wrong"]
    primary_reasoning: str
    secondary_reasoning: str
    disagreement: str | None


async def cross_grade(
    *,
    ollama: OllamaClient,
    primary_model: str,
    secondary_model: str,
    test: PracticeTest,
    answers: dict[str, Any],
) -> list[GradedAnswer]:
    primary_task = ollama.chat(model=primary_model, messages=_grader_prompt(test, answers), …)
    secondary_task = ollama.chat(model=secondary_model, messages=_grader_prompt(test, answers), …)
    primary, secondary = await asyncio.gather(primary_task, secondary_task)
    return _reconcile(primary, secondary, test, answers)
```

Both calls use the same grader prompt — a JSON-schema-constrained output
asking for `{question_id: {grade, reasoning}}`. The reconciler:
- Same `grade` from both → grade passes through, reasoning from both surfaces
- Different `grade` → surface both reasonings + a disagreement note
- One model returned malformed JSON → fall back to the other; log the failure

Failure modes that don't block grading:
- One model 502s → use the other alone with a `single_grader=true` flag
- Both 502 → return 502 to the client (don't fake a grade)
- Reconciler can't parse either → return 502; the test record gets a take with
  `error: "graders returned unparseable output"` so it's debuggable

---

## Soul appendix — `PRACTICE_TEST_APPENDIX`

Two distinct concerns, both addressed:

**Generation procedure.** Forces the agent to:
- Call `generate_vocab_section` first (must consume from `knowledge/gre/vocab/`)
- Then `generate_quant_section` (from `knowledge/gre/quant/`)
- Then `generate_rc_section` and `generate_se_section` (model-generated)
- Finally `persist_test` with the full assembly
- Return the test wrapped in `[PREVIEW:practice-test:<id>]`

**Grading rubric** (only loaded for the grader prompt, not chat):
- `correct` — answer matches the key, including multi-select cardinality
- `partial` — for sentence-equivalence, one of two correct selections (worth half)
- `wrong` — none of the above
- Reasoning must reference the key's rubric note, not freelance

---

## Classifier nudges (the routing-fix bit)

Add to `_system_prompt()` exemplars:

```
"give me a quiz on my GREs"           → gre_quiz       (vague; default to drill)
"test me on my GRE vocab"             → gre_quiz
"give me a 10-question practice test" → gre_practice_test
"generate a GRE mock exam"            → gre_practice_test
"I want a full practice section"      → gre_practice_test
"grade my answers"                    → gre_practice_test (continuation)
```

Add `gre_practice_test` to `TASK_TYPES`, `TASK_METADATA`, `_FALLBACK_MODELS`,
`Config.delphi_model_gre_practice_test`, `Config.delphi_model_gre_practice_secondary`,
and `Roster.from_config`.

Two new env vars because grading needs both:

```bash
DELPHI_MODEL_GRE_PRACTICE_TEST=gpt-oss:120b-cloud      # generator + primary grader
DELPHI_MODEL_GRE_PRACTICE_SECONDARY=deepseek-v3.1:671b-cloud  # secondary grader
```

---

## File layout

```
memory/
├── practice_test.py     ← schema, read/save/list/append-take
└── cross_grade.py       ← parallel two-model grader

routing/
├── practice_test_agent.py  ← generation tool loop
└── (soul.py, classifier.py, roster.py — modified)

api/
├── practice_tests.py    ← grading endpoint + GET test endpoint
└── chat.py              ← branch to _handle_practice_test for generation
                          + import the new router

config.py                ← delphi_model_gre_practice_test + _secondary

tests/
├── test_practice_test.py        ← schema + storage round-trip
├── test_cross_grade.py          ← reconciliation logic (mocked Ollama)
├── test_practice_test_agent.py  ← generation tool loop (mocked)
└── test_practice_test_route.py  ← full e2e: generate → submit → grade

ui/src/components/
├── OutputCanvas/PreviewBlock.jsx   ← new kind=practice-test branch
├── PracticeTestForm.jsx            ← editable form
└── PracticeTestResult.jsx          ← graded view

ui/src/lib/practiceTest.ts          ← grade endpoint client

scripts/smoke_practice_test.sh      ← VM smoke (generate, submit, grade)
docs/plans/2026-06-03-gre-practice-test.md  ← this file
```

---

## Phased delivery within Phase 5b

1. **5b-a — Storage + schema.** `memory/practice_test.py` + tests. ~2h.
2. **5b-b — Cross-check grader.** `memory/cross_grade.py` + tests. ~3h.
3. **5b-c — Generation agent.** `routing/practice_test_agent.py` with the four
   `generate_*_section` tools + `persist_test`. Tests with mocked Ollama. ~4h.
4. **5b-d — Routing.** Roster entry + classifier exemplars (incl. the
   `gre_quiz` tightening) + soul appendix + config. ~1h.
5. **5b-e — Endpoints.** `api/practice_tests.py` + chat-route generation
   branch. End-to-end test passes. ~3h.
6. **5b-f — UI.** Editable preview + submit + graded result. ~6h.
7. **5b-g — Smoke.** Docker deploy, real generate → real grade, verify two
   models actually ran in parallel (JSONL log shows two model tags), verify
   the test file got a `## Take 1` section. ~1h.

Total: ~2.5 days of focused work. Splitable across days; each slice ships CI-green.

---

## Failure modes and what we do about them

| Failure | Behavior |
|---|---|
| Classifier sends ambiguous "give me a quiz" to `vault_query` | After the exemplar tightening, vague phrasings default to `gre_quiz` (drill); only explicit "practice test" / "mock exam" reach `gre_practice_test`. Tali can still force either via `task_type` from the UI. |
| Generation agent loops calling section tools forever | Bounded by `max_steps` (8). Final forced call returns whatever's assembled, with `persist_test` not called → 502 to client; no orphan files. |
| User submits answers for a test that doesn't exist | Grade endpoint returns 404. The test_id is opaque (ULID); only the UI sees real IDs from `[PREVIEW:practice-test:<id>]`. |
| One grader 502s mid-grade | Service falls back to single-grader, marks the take with `graders.secondary: null`. UI shows a small "single grader" badge. |
| Both graders 502 | 502 to the client, no take appended. |
| Two graders disagree on every single question | Surfaced as second-opinion notes per question; user adjudicates. No service-side opinion. |
| Test file deleted between generate and grade | 404 from the grade endpoint. UI offers to regenerate. |
| Two different clients grade the same test concurrently | Take append is a file-rewrite under tempfile + rename. Last writer wins on the takes list; both takes are visible afterwards if the appends interleave at the file-content level (they shouldn't — atomic). |

---

## What this unlocks

Once 5b ships, "give me a 10-question test" produces a real, gradable, two-model-
verified mock exam grounded in your vault material. The grading record stays
under `knowledge/gre/practice-tests/<id>.md` so you can revisit any prior take.
Combined with Phase 5's daily drill, the GRE substrate is now bi-modal:
spaced-repetition for retention, full-test for performance practice.

It also pioneers the **parallel two-model grading** primitive that
`memory/cross_grade.py` provides. That same primitive will land downstream
agentic patterns — algotrading signal cross-validation, document review,
anywhere "second opinion" is valuable.

---

## Out of scope for v1 (flagged for follow-ups)

- **Timed sections** — real GRE is section-timed. v1 has no timer. Add a UI
  countdown later; the test file's frontmatter can carry `time_limit_minutes`.
- **Reading-comprehension passage reuse** — generating a fresh passage per test
  is expensive. After v1 lands, harvest model-generated passages to
  `knowledge/gre/passages/` so the agent picks from a growing pool.
- **Adaptive difficulty** — real GRE adapts within a section based on
  performance. We'd need a question difficulty signal and an adaptive
  question-selection algorithm. Far future.
- **Score equating to scaled 130–170 range** — the official scoring algorithm
  is non-trivial. v1 reports raw correct/total + percent.

---

## Decision-log entry (append when 5b-g ships)

> **2026-06-03** — `gre_practice_test` task type added alongside `gre_quiz`,
> rounding the GRE substrate from spaced-repetition daily drill into full
> mock-exam practice. Hybrid question sourcing: vocab + quant pull from
> `knowledge/gre/`; RC + sentence-equivalence are model-generated. Tests
> persist as one markdown-with-YAML file each under
> `knowledge/gre/practice-tests/<test_id>.md` (answer key in frontmatter,
> questions in body, graded takes appended as `## Take N` sections). Grading
> uses parallel independent two-model cross-check
> (`memory/cross_grade.py`) — primary + secondary call in parallel, blind
> to each other; service reconciles and surfaces disagreements honestly
> rather than picking a winner. UI gains an editable `PreviewBlock` variant
> + a new endpoint `POST /v1/practice-tests/<id>/grade`. Rationale:
> Phase 5's vocab drill answers the daily-review question; Phase 5b answers
> the "am I ready for the real test?" question. The cross-grade primitive
> is reusable beyond GRE — any future tool needing a second opinion
> (algotrading signals, document review) inherits it.
