# Delphi as Domain Tutor — GRE Knowledge Vault Plan

> Working frame: Delphi is a **librarian**, not a textbook. The vault is the
> library. Each GRE word is a card on the shelf. You stock the shelves once,
> then quiz endlessly. The librarian walks the stacks, reads the cards, and
> answers in your voice. GRE is the first domain — the same shape works for
> any curated reference material (algotrading playbooks, Spanish irregulars,
> medical drug cards). Delphi stays general; the vault holds the specialty.

Goal: Turn Delphi into a domain tutor for the GRE without adding any
GRE-specific service code, by reusing the existing `vault_query` agent
(`routing/vault_agent.py`) over a typed, hand-curated `knowledge/` subtree
in the Obsidian vault.

Architecture: Add a fourth top-level namespace to the vault — `knowledge/` —
alongside `conversations/`, `entities/`, `daily/`, and `projects/`. It is
**human/ingestion-script writable, service read-only** (same posture as
`projects/`). The first domain under it is `knowledge/gre/`. Retrieval rides
the existing `vault_query` tool-calling loop unchanged; the only nudges are
a few classifier exemplars and one soul clause that says "prefer notes from
`knowledge/` over recall."

Tech stack: existing FastAPI service, existing `VaultReader` (keyword search
+ path-confined reads), Jinja2 templates for ingestion, Python ingestion
script using `uv run`. No new runtime services in v1. The embedding sidecar
is on the table for v2 if keyword search ever stops being enough.

---

## Why this shape

Three properties make `knowledge/<domain>/<atom>.md` the right substrate:

1. **It piggybacks the work already done.** `vault_query` already searches
   and reads notes in a bounded loop. Stock the shelves, point the loop at
   them, done. No new endpoints, no schema migration.
2. **One fact per file → Obsidian's graph view becomes a study aid.**
   Wikilinks between confusable words (`[[perspicacious]]` vs
   `[[perspicuous]]`) and between quant prereqs (`[[factorials]]` →
   `[[permutations-vs-combinations]]`) turn the vocabulary into a recall
   graph — the way humans actually retain words.
3. **It generalizes.** The exact same shape serves any curated domain. GRE
   today, algotrading patterns tomorrow, medical cards the day after. The
   service learns *zero* GRE-specific facts; it just learns "prefer the
   vault."

The thing this is **not**: a vector DB. Keyword retrieval over markdown is
the baseline. The embedding sidecar (already a future hook in `CLAUDE.md`)
is the upgrade path when keyword search starts missing — but that's a
problem for future-you, not today-you.

---

## Vault layout

```
<vault>/
└── knowledge/
    ├── README.md                    ← what lives here, how to add domains
    └── gre/
        ├── README.md                ← GRE domain index
        ├── vocab/
        │   ├── _index.md            ← alphabetical roll-up, regen on ingest
        │   ├── perspicacious.md
        │   ├── sycophant.md
        │   ├── laconic.md
        │   └── ...
        ├── quant/
        │   ├── _index.md
        │   ├── permutations-vs-combinations.md
        │   ├── exponent-rules.md
        │   └── ...
        ├── verbal/                  ← sentence-equivalence patterns, RC strategy
        └── awa/                     ← argument fallacies, essay templates
```

Slug rule: lowercased, hyphenated, ASCII. Plurals collapse to the singular
canonical form (e.g., `sycophants.md` → `sycophant.md`). The slug **is** the
primary key for ingestion idempotency.

---

## Note schemas

### Vocab

```markdown
---
type: gre-vocab
word: perspicacious
pos: adjective
difficulty: hard            # easy | medium | hard | brutal | obscure
synonyms: [astute, shrewd, discerning]
antonyms: [obtuse, dull]
tags: [gre, vocab, intelligence]
mnemonic: "PERSPECtacles let you see clearly → perspicacious sees through things"
added: 2026-05-31
sources: ["Magoosh", "Manhattan 500"]
review:
  last_reviewed: null
  ease: 2.5                 # SM-2 starting ease
  interval_days: 0
---

# perspicacious

> Having keen insight; mentally sharp.

## Examples
- *Her perspicacious analysis caught the flaw nobody else saw.*
- Usually applied to judgment, observation, or critique — not to objects.

## Confusion set
- Not [[perspicuous]] (= "clearly expressed").
- Compare [[sagacious]], [[astute]].
```

Frontmatter is structured so that future tooling — quiz mode, weakness
reports, "show me only the brutal words I've never reviewed" — can query
without parsing the body.

### Quant

```markdown
---
type: gre-quant
topic: permutations-vs-combinations
section: counting
difficulty: medium
tags: [gre, quant, combinatorics]
formulas: ["P(n,r) = n!/(n-r)!", "C(n,r) = n!/(r!(n-r)!)"]
prereqs: [[factorials]]
added: 2026-05-31
---

# Permutations vs Combinations

## When to use which
- Order matters → permutation.
- Order doesn't matter → combination.

## Worked examples
1. Five runners competing for gold/silver/bronze → P(5, 3) = 60.
2. Pick a 3-person committee from 5 → C(5, 3) = 10.

## Common traps
- "Arrangements" / "orderings" → almost always permutation.
- "Groups" / "teams" / "subsets" → almost always combination.
- The word "select" alone is ambiguous; check whether order is asked about.
```

`prereqs` as wikilinks gives you a study DAG for free. Open the graph view,
filter to `type: gre-quant`, see the dependency order.

---

## Ingestion paths

Three, ordered by effort and reach. Do them in order; each unlocks the next.

### 1. Bulk CSV import (start here)

Why first: it lets you absorb an entire 500–1000 word list (Magoosh,
Manhattan, GregMat, Barron's) in a single afternoon. Without bulk, you'll
hand-write 30 cards and lose momentum.

```
scripts/
├── ingest/
│   ├── __init__.py
│   ├── gre_vocab.py             ← CSV reader → renders notes via template
│   ├── gre_quant.py             ← same shape, quant template
│   └── templates/
│       ├── vocab.md.j2
│       └── quant.md.j2
└── data/
    └── gre/
        ├── vocab.csv            ← word,pos,definition,synonyms,...
        └── quant.csv
```

CLI contract:

```bash
uv run python -m scripts.ingest.gre_vocab \
    --csv scripts/data/gre/vocab.csv \
    --vault $OBSIDIAN_VAULT_PATH \
    --domain gre
```

Rules:
- Idempotent on `word` (slug). Re-run = overwrite **only** if content hash
  changed; otherwise skip and report `unchanged`.
- Preserve a manually-edited note's `review:` block on overwrite (read,
  splice into the rendered template).
- Emit a `_ingest.log` next to the domain README so you can audit.

### 2. Chat-driven additions ("Delphi, remember this word")

The conversational path. You say:

> *"Delphi, remember the word **mendacious**. It means lying or untruthful.
> Synonyms: deceitful, dishonest. Antonym: candid."*

Two implementation options, pick one when you get there:

**Option A — conventional directive.** Add a `[REMEMBER: type=gre-vocab;
word=mendacious; ...]` block the user (or the model) emits, parsed in the
gateway like the `[MODE:…]` directives the UI already handles. Vault writer
splices into the template.

**Option B — new task type `vault_write`.** Classifier recognizes
"remember this …" / "save this …" intents. Gateway routes through a small
agent that calls a `write_knowledge_note` tool (mirror of `read_note`,
constrained to `knowledge/<domain>/`).

Option B is the cleaner end state (symmetry with the read-side agent), but
Option A ships in a day. Defer the decision.

### 3. Quiz mode + spaced repetition (later)

`gre_quiz` task type. Agent:

1. Picks N words from `knowledge/gre/vocab/` filtered by `difficulty` and
   `review.interval_days` (SM-2 due today or overdue).
2. Asks one at a time; user answers; agent grades.
3. Updates `review:` frontmatter in place (`last_reviewed`, `ease`,
   `interval_days`).
4. Writes the session as a normal conversation note under
   `conversations/YYYY-MM-DD/...` with `task_type: gre_quiz`.

This is Anki in miniature, possible only because every word is its own
file. Implementing this is what makes Delphi a **tutor**, not just a
glossary.

---

## Retrieval — already mostly built

Two small nudges to the existing service:

### Classifier exemplars (`routing/classifier.py`)

Add to the system prompt's example list:

```
"what does perspicacious mean"                       → vault_query
"give me 5 synonyms for praise from my vocab list"    → vault_query
"how do I solve combinations vs permutations"         → vault_query
"quiz me on hard vocab words"                         → vault_query   (until gre_quiz lands)
"remember the word mendacious"                        → vault_write   (when that task type exists)
```

Then add cases to `tests/test_classifier.py` so a future model swap doesn't
silently regress this.

### Soul clause (`routing/soul.py`)

The `vault_query` task-specific addition gets one extra sentence:

> "When the user asks about a GRE word, quant concept, or anything that
> looks like reference material, search the `knowledge/` subtree before
> answering. Prefer a note from `knowledge/gre/` over your own recall, and
> say so when you used one (`Source: knowledge/gre/vocab/<slug>.md`)."

That source-citing habit is what makes the answers trustworthy and turns
wrong cards into trivially findable bugs.

### When keyword search starts failing

The signal is queries like *"give me 10 words that mean 'praise'"* —
keyword can't surface synonyms it doesn't share strings with. That's the
green light for the **embedding sidecar** future hook: a tiny FastAPI
process reads the vault, embeds each note with `nomic-embed-text` via
Ollama, indexes into `sqlite-vec`, exposes `/search?q=…`. `VaultReader`
gains a `semantic_search` variant. Same interface, smarter retrieval.

---

## Disk budget (the 78 GB question)

| Item                                | Size       | Notes                                  |
|-------------------------------------|------------|----------------------------------------|
| 5,000 vocab notes × ~2 KB           | ~10 MB     | Negligible.                            |
| 500 quant notes × ~4 KB             | ~2 MB      | Negligible.                            |
| Existing roster (5 × ~9 GB Q4)      | ~45 GB     | The bulk of disk.                      |
| `nomic-embed-text` (future)         | ~270 MB    | Embedding sidecar.                     |
| Vector index (`sqlite-vec`, future) | <500 MB    | Even at 100k notes.                    |
| Conversation notes growth           | ~1 MB/day  | ~1 GB / 3 years.                       |
| **Total committed today**           | **~45 GB** | Headroom: ~33 GB.                      |

Conclusion: the knowledge layer is free at any reasonable scale. The 33 GB
of headroom fits:

- A second mid-size model (~9 GB) for parallel cross-validation.
- The embedding sidecar + index.
- Years of conversation history.

If pressure ever appears, the eviction order is: old conversation notes →
unused 14B variants → keep the 32B's. The knowledge tree never gets evicted.

---

## Generalization

The pattern is **vault-as-curated-domain-knowledge**:

```
knowledge/<domain>/<topic-folder>/<atom>.md
```

with typed frontmatter, wikilinks between related atoms, and `vault_query`
doing the retrieval. The same shape works for:

- `knowledge/algotrading/` — strategy patterns, indicator definitions,
  backtest learnings. Cross-link with `projects/Financio.md`.
- `knowledge/spanish/` — irregular verbs, conjugation tables, idioms.
- `knowledge/medicine/` — drug → dose → contraindication cards.
- `knowledge/anthropic/` — prompt patterns, model quirks.

The only per-domain decision is the frontmatter schema (what facts each
atom carries). Everything below — retrieval, ingestion, quizzing — is
domain-agnostic infrastructure.

---

## Phased plan

| Phase | Scope | Effort | Output |
|-------|-------|--------|--------|
| **0** | This doc | — | You are here. |
| **1** | Seed `vault/knowledge/gre/{vocab,quant,verbal,awa}/` with READMEs and ~10 sample notes (shipped today via `vault-seed/` in this repo). | 30 min | Templates the rest of the pipeline targets. |
| **2** | Bulk ingest. `scripts/ingest/gre_vocab.py` + Jinja2 template + a curated 500-word CSV. | 1–2 hrs | A populated `knowledge/gre/vocab/`. |
| **3** | Classifier + soul nudges. Add 5–10 `vault_query` exemplars, update soul clause, extend `tests/test_classifier.py`. | 30 min | "What does X mean?" routes to the vault unprompted. |
| **4** | Chat-driven adds (`[REMEMBER:…]` directive or `vault_write` task type). New decision-log entry. | half day | "Delphi, remember mendacious" creates a card. |
| **5** | Quiz mode (`gre_quiz`) + SM-2 lite in the `review:` frontmatter. | 1–2 days | Daily review session that updates cards in place. |
| **6** | Embedding sidecar (only when keyword search demonstrably breaks). | 1 day | Semantic vault search; `VaultReader.semantic_search`. |

Phases 1–3 are the smoke test: end-to-end GRE Q&A grounded in the vault,
zero new task types. Phases 4–5 are where it becomes a **tutor**.

---

## Open questions

- **Source of truth for the word list?** Magoosh 1000? Manhattan 500?
  GregMat? Pick one canonical list and treat the rest as supplements — the
  schema doesn't care, but mixing curators without a `sources`-aware dedupe
  pass creates duplicate cards with slightly different mnemonics. Pin a
  decision in Phase 2.
- **Quant section coverage?** GRE quant decomposes into ~30 sub-skills.
  Before writing topic notes (Phase 2), list them out in
  `knowledge/gre/quant/_index.md` so coverage is visible.
- **Where does the vault actually live?** `OBSIDIAN_VAULT_PATH` is `/vault`
  in Docker and `/home/tali/vault` bare-metal. The ingestion script must
  default to `$OBSIDIAN_VAULT_PATH` so it works in both deploys without a
  flag.

---

## Decision-log entry (append to `CLAUDE.md` when Phase 1 lands)

> **2026-05-31** — Vault adopts a `knowledge/<domain>/` namespace for
> human-curated reference material, distinct from `conversations/`,
> `entities/`, `daily/`, and `projects/`. First domain is `knowledge/gre/`.
> Rationale: the `vault_query` agent already retrieves over the vault;
> giving it a typed, hand-curated knowledge layer turns Delphi into a
> domain tutor (GRE today, others later) with zero service-level changes.
> Service still writes only to `conversations/`/`entities/`/`daily/`; the
> `knowledge/` tree is human/ingestion-script writable and service
> read-only — same posture as `projects/`. Retrieval rides the existing
> tool-calling loop in `routing/vault_agent.py`; the embedding sidecar
> future hook remains the upgrade path when keyword search demonstrably
> breaks.

---

## Smoke test (when Phase 3 lands)

```bash
curl -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"what does perspicacious mean?"}], "task_type":"auto"}' \
     https://delphi.your-tailnet.ts.net/v1/chat/completions
```

Success when:

1. Classifier returns `vault_query` (check JSONL log).
2. Agent calls `search_vault("perspicacious")`, then `read_note("knowledge/gre/vocab/perspicacious.md")`.
3. The response cites `Source: knowledge/gre/vocab/perspicacious.md`.
4. The definition matches the note, not Wikipedia phrasing.

When this passes for vocab, repeat with a quant prompt
(*"how do I tell permutations from combinations?"*). When both pass, the
tutor is real.
