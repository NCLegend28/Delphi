# vault-seed

Tree mirroring what should land in the production Obsidian vault. Not
shipped with the service — copy or `rsync` into `$OBSIDIAN_VAULT_PATH`
when seeding a fresh box or adding a domain.

```bash
rsync -av --ignore-existing \
    vault-seed/knowledge/ \
    $OBSIDIAN_VAULT_PATH/knowledge/
```

`--ignore-existing` is the safe default: it never overwrites a note you've
since edited in Obsidian. Drop it if you want the seed templates to win.

See `docs/plans/2026-05-31-gre-knowledge-vault.md` for the design.
