import { useDelphiStore } from "../../store/delphiStore";

/**
 * Footer — keyboard legend + active model badge.
 *
 * The model badge reads delphiStore.model (set when the backend echoes which
 * roster model served the response); falls back to the auto-route label.
 */
export function Footer() {
  const model = useDelphiStore((s) => s.model);
  return (
    <footer className="flex items-center gap-5 border-t border-[var(--color-border-dim)] bg-[var(--color-bg-deep)] px-3.5 text-[9px] tracking-[0.1em] text-[var(--color-text-faint)]">
      <Key combo="⌘K" label="FOCUS" />
      <Key combo="ESC" label="INTERRUPT" />
      <Key combo="⌘L" label="CLEAR" />
      <div className="ml-auto flex items-center gap-1.5 rounded-sm border border-[rgba(157,111,255,0.2)] bg-[rgba(157,111,255,0.06)] px-2.5 py-[3px] text-[9px] tracking-[0.1em] text-[var(--color-accent-violet)]">
        <span>●</span>
        {model || "delphi · auto-route"}
      </div>
    </footer>
  );
}

function Key({ combo, label }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[var(--color-border-strong)]">{combo}</span>
      {label}
    </div>
  );
}
