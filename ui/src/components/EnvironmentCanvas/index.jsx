/**
 * EnvironmentCanvas — Delphi's ambient space.
 *
 * Phase 1: static shell only. The canvas backdrop is CSS (grid + scanlines +
 * a pulsing "presence" node). Phase 4 replaces the static node with a real
 * particle field and a moving avatar node that reacts to Delphi's mode.
 */
export function EnvironmentCanvas({ children }) {
  return (
    <div className="relative h-full w-full overflow-hidden scanlines">
      <div className="absolute inset-0 bg-grid opacity-60" />

      {/* Presence node — placeholder for the Delphi avatar. */}
      <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 animate-drift">
        <div className="relative h-3 w-3 rounded-full bg-[var(--color-accent-cyan)] shadow-[0_0_40px_12px_rgba(0,212,255,0.45)] animate-pulse-soft" />
        <div className="absolute inset-0 -m-8 rounded-full border border-[var(--color-border-strong)] opacity-30" />
        <div className="absolute inset-0 -m-16 rounded-full border border-[var(--color-border-glow)] opacity-40" />
      </div>

      {/* Floating panels live in the canvas's coordinate space. */}
      <div className="relative z-10 h-full w-full">{children}</div>
    </div>
  );
}
