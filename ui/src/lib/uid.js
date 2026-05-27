/**
 * uid — collision-resistant id that works in ANY context.
 *
 * `crypto.randomUUID()` is only defined in a *secure context* (HTTPS, or
 * localhost). A phone reaching Delphi over plain HTTP — e.g. http://<host>
 * instead of the Tailscale HTTPS URL — has `crypto.randomUUID === undefined`,
 * so calling it throws and the send handler dies silently ("works on desktop,
 * dead on phone"). This degrades gracefully: real UUID when available, a
 * getRandomValues-built v4 next, and a timestamp+random last resort.
 */
export function uid() {
  const c = globalThis.crypto;
  if (typeof c?.randomUUID === "function") return c.randomUUID();
  if (typeof c?.getRandomValues === "function") {
    const b = c.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40; // version 4
    b[8] = (b[8] & 0x3f) | 0x80; // variant 10
    const h = Array.from(b, (x) => x.toString(16).padStart(2, "0"));
    return `${h.slice(0, 4).join("")}-${h.slice(4, 6).join("")}-${h
      .slice(6, 8)
      .join("")}-${h.slice(8, 10).join("")}-${h.slice(10, 16).join("")}`;
  }
  return `id-${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}
