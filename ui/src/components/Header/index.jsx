import { useChatStore } from "../../store/chatStore";
import { useDelphiStore } from "../../store/delphiStore";
import { useSessionClock } from "../../hooks/useSessionClock";

/**
 * Header — top command bar.
 *
 * Identity + fixed deployment facts (node / protocol) on the left, a live
 * status dot and session clock on the right. The status dot reflects real
 * state: amber+fast while streaming, red on error, green when idle/ready.
 */
export function Header() {
  const isStreaming = useChatStore((s) => s.isStreaming);
  const error = useDelphiStore((s) => s.error);
  const mode = useDelphiStore((s) => s.mode);
  const ttftMs = useDelphiStore((s) => s.ttftMs);
  const clock = useSessionClock();

  const status = error ? "error" : isStreaming ? "busy" : "online";
  const statusLabel = error ? "ERROR" : isStreaming ? mode : "IDLE";

  return (
    <header className="relative flex items-center gap-5 overflow-hidden border-b border-[var(--color-border-mid)] bg-[var(--color-bg-deep)] px-4 scan-sweep">
      <span className="shrink-0 font-display text-[15px] font-bold tracking-[0.3em] text-[var(--color-accent-cyan)] text-glow-cyan">
        DELPHI
      </span>
      <span className="-ml-3 self-end pb-[3px] text-[9px] tracking-[0.2em] text-[var(--color-text-dim)]">
        V0.2.0
      </span>

      <Divider />
      <Stat label="NODE" value="LOCAL" />
      <Divider />
      <Stat label="PROTOCOL" value="TAILNET · TLS" />
      <Divider />
      <Stat label="UPLINK" value={ttftMs != null ? `${Math.round(ttftMs)} ms` : "— ms"} />

      <div className="ml-auto flex items-center gap-5">
        <StatusDot status={status} label={statusLabel} />
        <span className="font-display text-[11px] tracking-[0.15em] text-[var(--color-text-dim)]">
          SESSION {clock}
        </span>
      </div>
    </header>
  );
}

function Divider() {
  return <span className="h-5 w-px shrink-0 bg-[var(--color-border-mid)]" />;
}

function Stat({ label, value }) {
  return (
    <div className="flex flex-col gap-px">
      <span className="text-[8px] tracking-[0.15em] text-[var(--color-text-dim)]">{label}</span>
      <span className="text-[11px] tracking-[0.05em] text-[var(--color-text-muted)]">{value}</span>
    </div>
  );
}

const DOT_COLOR = {
  online: "var(--color-accent-green)",
  busy: "var(--color-accent-amber)",
  error: "var(--color-accent-red)",
};

function StatusDot({ status, label }) {
  const color = DOT_COLOR[status];
  return (
    <span className="flex items-center gap-1.5 text-[10px] tracking-[0.12em] text-[var(--color-text-muted)]">
      <span
        className={[
          "h-1.5 w-1.5 rounded-full",
          status === "busy" ? "animate-pulse-fast" : status === "error" ? "" : "animate-pulse-soft",
        ].join(" ")}
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
      />
      {label}
    </span>
  );
}
