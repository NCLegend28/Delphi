import { useEffect, useState } from "react";

/**
 * BootOverlay — the cold-start intro sequence.
 *
 * Plays the mission-control boot lines, then fades out and unmounts. Honors
 * reduced-motion via the global CSS rule (animations collapse to near-zero
 * duration, so it disappears almost immediately).
 */
const LINES = [
  { text: "INITIALIZING DELPHI RUNTIME…", delay: 0.1 },
  { text: "LOADING MODEL CONTEXT LAYER…", delay: 0.4 },
  { text: "ESTABLISHING SECURE CHANNEL…", delay: 0.7 },
  { text: "DELPHI", delay: 1.0, brand: true },
  { text: "● SYSTEM ONLINE — ALL SYSTEMS NOMINAL", delay: 1.4, ok: true },
];

export function BootOverlay() {
  const [gone, setGone] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setGone(true), 2600);
    return () => clearTimeout(id);
  }, []);
  if (gone) return null;

  return (
    <div
      className="fixed inset-0 z-[9000] flex flex-col items-center justify-center gap-1.5 bg-[var(--color-bg-void)]"
      style={{ animation: "boot-fade 0.4s ease 2.2s forwards" }}
    >
      {LINES.map((l) => (
        <div
          key={l.text}
          className={[
            "tracking-[0.15em] opacity-0",
            l.brand
              ? "font-display text-xl tracking-[0.4em] text-[var(--color-accent-cyan)] text-glow-cyan"
              : l.ok
                ? "text-[11px] text-[var(--color-accent-green)]"
                : "text-[11px] text-[var(--color-text-dim)]",
          ].join(" ")}
          style={{ animation: `boot-line 0.3s ease ${l.delay}s forwards` }}
        >
          {l.text}
        </div>
      ))}
    </div>
  );
}
