---
type: gre-quant
topic: permutations-vs-combinations
section: counting
difficulty: medium
tags: [gre, quant, combinatorics, counting]
formulas:
  - "P(n, r) = n! / (n - r)!"
  - "C(n, r) = n! / (r! · (n - r)!)"
prereqs: [[factorials]]
added: 2026-05-31
---

# Permutations vs Combinations

## When to use which

- **Order matters → permutation.** Different orderings of the same items
  count as different outcomes.
- **Order doesn't matter → combination.** Different orderings of the same
  items collapse into one outcome.

Rule of thumb: ask "if I swap two of the items, is that a *different*
arrangement?" Yes → permutation. No → combination.

## Worked examples

1. **Permutation.** Five runners compete for gold, silver, bronze.
   `P(5, 3) = 5! / 2! = 60` possible podium orderings.
2. **Combination.** Pick a 3-person committee from 5 people.
   `C(5, 3) = 5! / (3! · 2!) = 10` possible committees.
3. **Mixed.** Choose 3 books from 10 and arrange them on a shelf.
   Two-step: choose `C(10, 3) = 120`, then arrange `3! = 6`, total `720`.
   (Equivalent to `P(10, 3)` directly.)

## Common traps

- "Arrangements", "orderings", "rankings", "sequence" → almost always
  permutation.
- "Groups", "teams", "subsets", "selections" → almost always combination.
- "Select" alone is ambiguous; check whether the problem then *uses* the
  order (assigns roles, ranks, seats them in a row).
- Repetition allowed vs not — both formulas above assume **no repetition**.
  With repetition the formulas change (`n^r` for permutations with
  repetition, `C(n + r - 1, r)` for combinations with repetition).

## Memory hook

`P` has fewer letters in the denominator (`(n-r)!`); `C` has more (`r! ·
(n-r)!`). More denominator = smaller number = fewer combinations than
permutations. Combinations are always ≤ permutations for the same n, r.
