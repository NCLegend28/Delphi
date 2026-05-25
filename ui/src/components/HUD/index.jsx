import { useEffect, useState } from "react";
import { useDelphiStore } from "../../store/delphiStore";

/**
 * HUD — at-a-glance status panel.
 *
 * Reads mode / activeTask / model from delphiStore. The stream parser is
 * the only writer; this component is a pure consumer.
 */
export function HUD() {
  const mode = useDelphiStore((s) => s.mode);
  const activeTask = useDelphiStore((s) => s.activeTask);
  const model = useDelphiStore((s) => s.model);
  const uptime = useUptime();

  return (
    <div className="panel panel-corner-tl panel-corner-br relative h-full w-full rounded-sm">
      <header className="flex items-center justify-between border-b border-[var(--color-border-glow)] px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-cyan)] animate-pulse-soft" />
          <span className="font-display text-xs tracking-[0.3em] text-[var(--color-text-muted)]">
            STATUS
          </span>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
          session {uptime}
        </span>
      </header>

      <div className="space-y-4 px-4 py-4">
        <ModeBadge mode={mode} />

        <Row label="TASK">
          <span className="max-w-[60%] truncate font-mono text-xs text-[var(--color-text-muted)]">
            {activeTask || "no active task"}
          </span>
        </Row>

        <Row label="MODEL">
          <span className="font-mono text-xs text-[var(--color-text-primary)]">
            {model || "—"}
          </span>
        </Row>

        <Row label="MEMORY">
          <MemoryBar percent={12} />
        </Row>
      </div>
    </div>
  );
}

const MODE_COLOR = {
  IDLE: "var(--color-accent-cyan)",
  THINKING: "var(--color-accent-cyan)",
  BUILDING: "var(--color-accent-amber)",
  SEARCHING: "var(--color-accent-violet)",
};

function ModeBadge({ mode }) {
  const color = MODE_COLOR[mode] ?? "var(--color-accent-cyan)";
  return (
    <div className="flex items-center justify-between">
      <span className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
        mode
      </span>
      <div className="flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ background: color, boxShadow: `0 0 8px ${color}` }}
        />
        <span
          className="font-display text-sm tracking-[0.3em]"
          style={{ color, textShadow: `0 0 8px ${color}` }}
        >
          {mode}
        </span>
      </div>
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between">
      <span className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
        {label}
      </span>
      {children}
    </div>
  );
}

/**
 * CompactHUD — single-row status strip for phone / tiny LCD layouts.
 *
 * Drops everything that needs vertical space; keeps the identity (DELPHI),
 * mode dot, and an inline active-task readout. ~36px tall.
 */
export function CompactHUD() {
  const mode = useDelphiStore((s) => s.mode);
  const activeTask = useDelphiStore((s) => s.activeTask);
  const color = MODE_COLOR[mode] ?? "var(--color-accent-cyan)";

  return (
    <div className="panel flex items-center gap-3 rounded-sm px-3 py-2">
      <h1 className="font-display text-sm tracking-[0.35em] text-[var(--color-accent-cyan)] text-glow-cyan">
        DELPHI
      </h1>
      <span className="h-3 w-px bg-[var(--color-border-glow)]" />
      <div className="flex items-center gap-1.5">
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: color, boxShadow: `0 0 6px ${color}` }}
        />
        <span
          className="font-display text-[10px] tracking-[0.3em]"
          style={{ color }}
        >
          {mode}
        </span>
      </div>
      <span className="ml-auto truncate font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
        {activeTask || "no active task"}
      </span>
    </div>
  );
}

function MemoryBar({ percent }) {
  return (
    <div className="flex w-32 items-center gap-2">
      <div className="relative h-1 flex-1 overflow-hidden rounded-full bg-[var(--color-bg-deep)]">
        <div
          className="absolute inset-y-0 left-0 bg-[var(--color-accent-cyan)]"
          style={{ width: `${percent}%`, boxShadow: "0 0 8px rgba(0,212,255,0.6)" }}
        />
      </div>
      <span className="font-mono text-[10px] text-[var(--color-text-muted)]">
        {percent}%
      </span>
    </div>
  );
}

function useUptime() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(
      () => setElapsed(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(id);
  }, []);
  return formatUptime(elapsed);
}

function formatUptime(s) {
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const sec = String(s % 60).padStart(2, "0");
  return `${h}:${m}:${sec}`;
}
