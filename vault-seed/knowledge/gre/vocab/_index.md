---
type: gre-vocab-index
section: vocab
added: 2026-05-31
tags: [gre, vocab, index]
---

# Vocabulary

One note per word. File name is the canonical slug (lowercase, hyphenated,
singular). The slug is the primary key — ingestion is idempotent on it.

## Schema

```yaml
---
type: gre-vocab
word: perspicacious
pos: adjective                   # noun | verb | adjective | adverb | …
difficulty: hard                 # easy | medium | hard | brutal | obscure
synonyms: [astute, shrewd]
antonyms: [obtuse, dull]
tags: [gre, vocab, intelligence]
mnemonic: "memory hook here"
added: 2026-05-31
sources: ["Magoosh", "Manhattan 500"]
review:
  last_reviewed: null
  ease: 2.5                      # SM-2 starting ease
  interval_days: 0
---
```

Body sections (all optional but recommended):

- A one-line definition under a `>` block-quote.
- `## Examples` — 1–3 sentences using the word in context.
- `## Confusion set` — wikilinks to easily-confused words. **This is what
  makes the graph view earn its keep.**

## Seeded examples

- [[perspicacious]]
- [[sycophant]]
- [[laconic]]

(Regenerate this list with the ingestion script.)
