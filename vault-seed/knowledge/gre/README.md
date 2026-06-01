---
type: gre-index
domain: gre
added: 2026-05-31
tags: [gre, index]
---

# GRE Prep

Tali's GRE knowledge base. Four sections, mirroring the test:

- [[vocab/_index|Vocabulary]] — one note per word, frontmatter-typed, with
  synonyms, antonyms, mnemonic, confusion set, and SM-2 review state.
- [[quant/_index|Quantitative]] — one note per sub-skill (arithmetic,
  algebra, geometry, counting, probability, data interpretation), with
  formulas, worked examples, and traps.
- [[verbal/_index|Verbal reasoning]] — sentence-equivalence patterns,
  text-completion heuristics, RC strategy notes.
- [[awa/_index|Analytical Writing]] — argument-essay fallacies, issue-essay
  templates, time budgets.

## Querying this

Any prompt that looks like *"what does X mean?"*, *"how do I solve Y?"*,
*"quiz me on Z"* should classify as `vault_query` and route through
`routing/vault_agent.py`. The agent calls `search_vault` then `read_note`
against this tree. Responses cite their source note path.

## Adding a card

Three paths, in order of effort (see `docs/plans/2026-05-31-gre-knowledge-vault.md`):

1. **Bulk** — drop a CSV in `Delphi/scripts/data/gre/` and run
   `uv run python -m scripts.ingest.gre_vocab --csv … --vault $OBSIDIAN_VAULT_PATH`.
2. **By hand** — create the note in Obsidian using the schema below.
3. **By voice/chat** — *"Delphi, remember the word **mendacious**…"*
   (Phase 4; not live yet).

## Schemas

Vocab and quant carry different frontmatter — see `vocab/_index.md` and
`quant/_index.md` for the canonical shape and a worked example.
