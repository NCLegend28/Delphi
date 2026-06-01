---
type: gre-quant
topic: exponent-rules
section: arithmetic
difficulty: easy
tags: [gre, quant, exponents, arithmetic]
formulas:
  - "a^m · a^n = a^(m+n)"
  - "a^m / a^n = a^(m-n)"
  - "(a^m)^n = a^(m·n)"
  - "(ab)^n = a^n · b^n"
  - "a^0 = 1   (for a ≠ 0)"
  - "a^(-n) = 1 / a^n"
  - "a^(m/n) = (a^m)^(1/n) = nth-root(a^m)"
prereqs: []
added: 2026-05-31
---

# Exponent Rules

## The seven rules

| Rule | Form | Why |
|------|------|-----|
| Product | `a^m · a^n = a^(m+n)` | Counting factors of `a`. |
| Quotient | `a^m / a^n = a^(m-n)` | Cancellation of factors. |
| Power of a power | `(a^m)^n = a^(m·n)` | Repeated multiplication. |
| Power of a product | `(ab)^n = a^n · b^n` | Distributes across multiplication. |
| Zero | `a^0 = 1` | Forced by the product rule: `a^n / a^n = 1`. |
| Negative | `a^(-n) = 1 / a^n` | Forced by extending the quotient rule. |
| Fractional | `a^(m/n) = nth-root(a^m)` | Forced by the power-of-a-power rule. |

## Worked examples

1. `2^3 · 2^5 = 2^8 = 256`.
2. `(3^2)^4 = 3^8 = 6561`.
3. `5^(-2) = 1/25`.
4. `8^(2/3) = (8^(1/3))^2 = 2^2 = 4`.

## Common traps

- **Power does not distribute across addition.** `(a + b)^n ≠ a^n + b^n`.
  The GRE will dangle this — refuse the bait.
- **Negative base parity matters.** `(-2)^4 = 16` but `(-2)^5 = -32`. Watch
  parentheses: `-2^4 = -16` (the exponent binds tighter than the sign).
- **Zero base, zero exponent** — `0^0` is undefined / context-dependent.
  Not GRE territory, but worth knowing.
- **Bases must match** to combine with the product or quotient rule.
  `2^3 · 3^3` is **not** `6^3` directly via the product rule — that's the
  power-of-a-product rule applied backward: `2^3 · 3^3 = (2·3)^3 = 6^3`.
  Same answer, different rule. Pick the right one when explaining.

## How this shows up on the GRE

- Quantitative-comparison problems where both columns simplify under
  these rules; the trap is doing arithmetic instead of algebra.
- Exponential growth / decay framings that reduce to a single rule
  applied once.
- See also: [[scientific-notation]], [[roots-and-radicals]].
