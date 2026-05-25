import { useChatStore } from "../../store/chatStore";
import { useDelphiStore } from "../../store/delphiStore";
import { modeColor } from "../../lib/modes";

/**
 * CompactBar — single-row status strip for phone / tiny-LCD layouts.
 *
 * Keeps the identity, mode dot, and an inline active-task readout; drops
 * everything that needs vertical space. ~34px tall.
 */
export function CompactBar() {
  const mode = useDelphiStore((s) => s.mode);
  const activeTask = useDelphiStore((s) => s.activeTask);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const color = modeColor(mode);

  return (
    <div className="panel flex items-center gap-3 px-3 py-2">
      <span className="font-display text-sm font-bold tracking-[0.35em] text-[var(--color-accent-cyan)] text-glow-cyan">
        DELPHI
      </span>
      <span className="h-3 w-px bg-[var(--color-border-dim)]" />
      <span className="flex items-center gap-1.5 text-[10px] tracking-[0.3em]" style={{ color }}>
        <span
          className={`h-1.5 w-1.5 rounded-full ${isStreaming ? "animate-pulse-fast" : "animate-pulse-soft"}`}
          style={{ background: color, boxShadow: `0 0 6px ${color}` }}
        />
        {mode}
      </span>
      <span className="ml-auto truncate text-[10px] tracking-[0.1em] text-[var(--color-text-dim)]">
        {activeTask || "no active task"}
      </span>
    </div>
  );
}
