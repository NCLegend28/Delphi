import { useDelphiStore } from "../../store/delphiStore";
import { useSpeechPlayback } from "../../hooks/useSpeechPlayback";

/**
 * Footer — keyboard legend + AUTO-SPEAK toggle + active model badge.
 *
 * The model badge reads delphiStore.model (set when the backend echoes which
 * roster model served the response); falls back to the auto-route label.
 *
 * AUTO-SPEAK pill: persisted in localStorage via delphiStore. When the
 * browser lacks SpeechSynthesis the pill renders muted/disabled.
 */
export function Footer() {
  const model = useDelphiStore((s) => s.model);
  const autoSpeak = useDelphiStore((s) => s.autoSpeakEnabled);
  const setAutoSpeak = useDelphiStore((s) => s.setAutoSpeak);
  const { supported } = useSpeechPlayback();

  return (
    <footer className="flex items-center gap-5 border-t border-[var(--color-border-dim)] bg-[var(--color-bg-deep)] px-3.5 text-[9px] tracking-[0.1em] text-[var(--color-text-faint)]">
      <Key combo="⌘K" label="FOCUS" />
      <Key combo="ESC" label="INTERRUPT" />
      <Key combo="⌘L" label="CLEAR" />
      <button
        type="button"
        onClick={() => supported && setAutoSpeak(!autoSpeak)}
        disabled={!supported}
        aria-pressed={autoSpeak}
        title={
          supported
            ? "Toggle automatic spoken responses"
            : "Speech synthesis unsupported in this browser"
        }
        className={[
          "flex items-center gap-1.5 rounded-sm border px-2 py-[2px] text-[9px] tracking-[0.1em]",
          !supported
            ? "border-[var(--color-border-dim)] bg-transparent text-[var(--color-text-dim)] opacity-50 cursor-not-allowed"
            : autoSpeak
              ? "border-[var(--color-accent-cyan)]/40 bg-[var(--color-accent-cyan)]/[0.08] text-[var(--color-accent-cyan)]"
              : "border-[var(--color-border-dim)] bg-transparent text-[var(--color-text-faint)] hover:text-[var(--color-text-muted)]",
        ].join(" ")}
      >
        <span aria-hidden="true">{autoSpeak ? "♪" : "♪"}</span>
        AUTO-SPEAK {autoSpeak ? "ON" : "OFF"}
      </button>
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
