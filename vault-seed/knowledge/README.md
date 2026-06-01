---
type: knowledge-index
added: 2026-05-31
---

# knowledge/

Human-curated reference material. The Delphi service **reads** from this
tree (via the `vault_query` agent) but never writes to it — same posture as
`projects/`. Writes happen by hand in Obsidian or via ingestion scripts in
`Delphi/scripts/ingest/`.

## Layout

```
knowledge/
└── <domain>/
    └── <topic-folder>/
        └── <atom>.md
```

One fact per file. Frontmatter typed. Wikilinks between related atoms.
That last rule is what makes the Obsidian graph view a study aid.

## Domains

- [[gre/README|GRE prep]] — vocab, quant, verbal, AWA.

(Add more here as they land — algotrading, spanish, medicine, etc.)

## Why a dedicated namespace

`conversations/` is what Delphi wrote *during* an exchange. `entities/` is
auto-extracted nouns. `daily/` is the rollup. `projects/` is for active
work. `knowledge/` is for **the things you want Delphi to know on
purpose** — durable, queryable, hand-shaped facts. Separating them keeps
the graph readable and lets the `vault_query` agent prefer the curated
substrate over the conversational exhaust.
