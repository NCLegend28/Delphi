import { useEffect, useRef, useState } from "react";
import { useChatStore } from "../../store/chatStore";
import { useDelphiStore } from "../../store/delphiStore";
import { modeColor, estimateTokens, tokenTotals } from "../../lib/modes";

/**
 * Sidebar — the mission-control telemetry rail.
 *
 * Every readout is sourced from real state where one exists:
 *   STATUS     mode / task / model / turns      — delphiStore + chatStore
 *   MEMORY     estimated context fill            — token estimate vs window
 *   TELEMETRY  latency (real TTFT), stream t/s   — delphiStore; SIGNAL is a
 *              purely decorative ambient oscillator (NOT host CPU)
 *   TOKENS     estimated input / output          — ≈4 chars/token
 *   TASK LOG   real event feed                    — delphiStore.events
 */
const CONTEXT_WINDOW = 32768; // typical local-roster context; cosmetic ceiling

export function Sidebar() {
  return (
    <aside className="flex min-h-0 flex-col overflow-hidden border-l border-[var(--color-border-dim)] bg-[var(--color-bg-panel)]">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <StatusSection />
        <MemorySection />
        <TelemetrySection />
        <TokensSection />
        <TaskLogSection />
      </div>
    </aside>
  );
}

function Section({ title, children }) {
  return (
    <div className="shrink-0 border-b border-[var(--color-border-dim)] px-3.5 py-2.5">
      <div className="mb-2.5 flex items-center gap-1.5 text-[8px] tracking-[0.25em] text-[var(--color-text-dim)]">
        {title}
        <span className="h-px flex-1 bg-[var(--color-border-dim)]" />
      </div>
      {children}
    </div>
  );
}

function StatusRow({ label, children }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[9px] tracking-[0.1em] text-[var(--color-text-dim)]">{label}</span>
      {children}
    </div>
  );
}

function StatusSection() {
  const mode = useDelphiStore((s) => s.mode);
  const activeTask = useDelphiStore((s) => s.activeTask);
  const model = useDelphiStore((s) => s.model);
  const messages = useChatStore((s) => s.messages);
  const turns = messages.filter((m) => m.role === "user").length;
  const color = modeColor(mode);

  return (
    <Section title="STATUS">
      <StatusRow label="MODE">
        <span className="flex items-center gap-1.5 text-[10px] tracking-[0.05em]" style={{ color }}>
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
          {mode}
        </span>
      </StatusRow>
      <StatusRow label="TASK">
        <span className="max-w-[62%] truncate text-[10px] text-[var(--color-text-muted)]">
          {activeTask || "no active task"}
        </span>
      </StatusRow>
      <StatusRow label="MODEL">
        <span className="max-w-[62%] truncate text-[10px] text-[var(--color-text-muted)]">
          {model || "auto"}
        </span>
      </StatusRow>
      <StatusRow label="CONTEXT">
        <span className="text-[10px] text-[var(--color-text-muted)]">{turns} turns</span>
      </StatusRow>
    </Section>
  );
}

function MemorySection() {
  const messages = useChatStore((s) => s.messages);
  const { total } = tokenTotals(messages);
  const pct = Math.min((total / CONTEXT_WINDOW) * 100, 100);

  return (
    <Section title="MEMORY">
      <div className="mb-1 h-[3px] overflow-hidden rounded-sm bg-[var(--color-border-dim)]">
        <div
          className="h-full rounded-sm transition-[width] duration-1000"
          style={{
            width: `${pct}%`,
            background: "linear-gradient(90deg, var(--color-accent-cyan), var(--color-accent-violet))",
            boxShadow: "0 0 6px rgba(0,212,255,0.5)",
          }}
        />
      </div>
      <div className="flex justify-between text-[8px] text-[var(--color-text-dim)]">
        <span>{total.toLocaleString()} tok</span>
        <span>{pct.toFixed(1)}%</span>
        <span>32K ctx</span>
      </div>
    </Section>
  );
}

function TelemetrySection() {
  const ttftMs = useDelphiStore((s) => s.ttftMs);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const signal = useAmbientSignal(isStreaming);
  const tps = useStreamRate(isStreaming);

  return (
    <Section title="TELEMETRY">
      <TelemRow name="SIGNAL" pct={signal} value={`${Math.round(signal)}%`} color="var(--color-accent-cyan)" />
      <TelemRow
        name="LATENCY"
        pct={ttftMs != null ? Math.min((ttftMs / 4000) * 100, 100) : 0}
        value={ttftMs != null ? `${Math.round(ttftMs)}ms` : "—"}
        color="var(--color-accent-green)"
      />
      <TelemRow
        name="STREAM"
        pct={Math.min((tps / 80) * 100, 100)}
        value={`${tps} t/s`}
        color="var(--color-accent-violet)"
      />
    </Section>
  );
}

function TelemRow({ name, pct, value, color }) {
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="min-w-[56px] text-[9px] tracking-[0.08em] text-[var(--color-text-dim)]">{name}</span>
      <div className="h-0.5 flex-1 overflow-hidden rounded-sm bg-[var(--color-border-dim)]">
        <div
          className="h-full rounded-sm transition-[width] duration-700"
          style={{ width: `${Math.min(pct, 100)}%`, background: color }}
        />
      </div>
      <span className="min-w-[34px] text-right text-[9px] text-[var(--color-text-muted)]">{value}</span>
    </div>
  );
}

function TokensSection() {
  const messages = useChatStore((s) => s.messages);
  const { input, output } = tokenTotals(messages);
  return (
    <Section title="TOKENS">
      <div className="grid grid-cols-2 gap-1.5">
        <TokenCard label="INPUT" value={input} />
        <TokenCard label="OUTPUT" value={output} />
      </div>
    </Section>
  );
}

function TokenCard({ label, value }) {
  return (
    <div className="rounded-sm border border-[var(--color-border-dim)] bg-[var(--color-bg-raised)] px-2 py-1.5">
      <div className="mb-0.5 text-[8px] text-[var(--color-text-dim)]">{label}</div>
      <div className="font-display text-[13px] font-medium tracking-[0.05em] text-[var(--color-text-muted)]">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function TaskLogSection() {
  const events = useDelphiStore((s) => s.events);
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events]);

  return (
    <Section title="TASK LOG">
      <div ref={ref} className="flex max-h-32 flex-col gap-1 overflow-y-auto">
        {events.length === 0 ? (
          <LogLine ts={null} text="Awaiting operator input" />
        ) : (
          events.map((e) => <LogLine key={e.id} ts={e.ts} text={e.text} />)
        )}
      </div>
    </Section>
  );
}

function LogLine({ ts, text }) {
  return (
    <div className="flex items-start gap-1.5 border-l border-[var(--color-border-dim)] px-1.5 py-1 text-[9px] leading-snug tracking-[0.04em] text-[var(--color-text-dim)] animate-fade-up">
      <span className="shrink-0 text-[8px] text-[var(--color-text-faint)]">{fmtTs(ts)}</span>
      <span>{text}</span>
    </div>
  );
}

function fmtTs(ts) {
  const d = ts ? new Date(ts) : new Date();
  return `${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

/**
 * useStreamRate — real output rate in tokens/sec for the current request.
 *
 * Sampled in an effect (timing reads are impure, so they can't live in render)
 * from delphiStore's running char count and first-byte timestamp. Resets to 0
 * shortly after streaming stops.
 */
function useStreamRate(isStreaming) {
  const [tps, setTps] = useState(0);
  useEffect(() => {
    const sample = () => {
      const { streamChars, streamStartedAt } = useDelphiStore.getState();
      if (streamStartedAt == null) {
        setTps(0);
        return;
      }
      const elapsed = (performance.now() - streamStartedAt) / 1000;
      setTps(elapsed > 0 ? Math.round(estimateTokens(streamChars) / elapsed) : 0);
    };
    sample();
    if (!isStreaming) return;
    const id = setInterval(sample, 400);
    return () => clearInterval(id);
  }, [isStreaming]);
  return tps;
}

/**
 * useAmbientSignal — decorative link-activity oscillator (NOT host CPU).
 * Idles low, climbs while streaming. Pure cosmetic motion for the HUD.
 */
function useAmbientSignal(active) {
  const [v, setV] = useState(14);
  useEffect(() => {
    const id = setInterval(() => {
      setV((prev) => {
        const target = active ? 55 + Math.random() * 35 : 12 + Math.random() * 14;
        return prev + (target - prev) * 0.4;
      });
    }, 800);
    return () => clearInterval(id);
  }, [active]);
  return v;
}
