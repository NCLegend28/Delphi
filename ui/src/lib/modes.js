/**
 * Shared mode → color mapping and token-estimate helpers.
 *
 * Mode colors mirror the directive grammar in routing/soul.py. The token
 * estimate is a deliberate approximation (≈4 chars/token) — the backend's
 * OpenAI-shaped stream does not carry usage counts mid-stream, so the HUD
 * shows an estimate, not an authoritative tally.
 */
export const MODE_COLOR = {
  IDLE: "var(--color-accent-cyan)",
  THINKING: "var(--color-accent-cyan)",
  BUILDING: "var(--color-accent-amber)",
  SEARCHING: "var(--color-accent-violet)",
};

export function modeColor(mode) {
  return MODE_COLOR[mode] ?? "var(--color-accent-cyan)";
}

/** Rough token estimate from a character count. */
export function estimateTokens(chars) {
  return Math.ceil(chars / 4);
}

/** Sum estimated input/output tokens across a message list. */
export function tokenTotals(messages) {
  let input = 0;
  let output = 0;
  for (const m of messages) {
    const t = estimateTokens(m.content?.length ?? 0);
    if (m.role === "user") input += t;
    else output += t;
  }
  return { input, output, total: input + output };
}
