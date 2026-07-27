import { useEffect, useState } from "react";
import { OutputCanvas } from "./components/OutputCanvas";
import { ChatRail } from "./components/ChatRail";
import { useChatStore } from "./store/chatStore";
import { useDelphiStore } from "./store/delphiStore";
import { cancelDelphiStream } from "./hooks/useDelphiStream";
import { useUiState } from "./hooks/useUiState";

const ROOMS = ["Chat", "Memory", "Practice", "System"];

function App() {
  const [room, setRoom] = useState("Chat");
  const { data, error, loading, refresh } = useUiState();
  const delphiMode = useDelphiStore((s) => s.mode);
  const ttftMs = useDelphiStore((s) => s.ttftMs);

  useKeyboardShortcuts();

  return (
    <div className="nocturne-shell">
      <PresenceBand
        state={presenceState(delphiMode)}
        sentence={presenceSentence(delphiMode, data)}
        data={data}
        localTtftMs={ttftMs}
        loading={loading}
        error={error}
        refresh={refresh}
      />

      <nav className="nocturne-tabs" aria-label="Delphi rooms">
        {ROOMS.map((name) => (
          <button
            key={name}
            type="button"
            className={name === room ? "is-active" : ""}
            onClick={() => setRoom(name)}
          >
            {name}
          </button>
        ))}
        <span className="nocturne-settings">Settings</span>
      </nav>

      <div className="nocturne-workspace">
        <main className="nocturne-room" aria-live="polite">
          {room === "Chat" && <ChatRoom />}
          {room === "Memory" && <MemoryRoom data={data} />}
          {room === "Practice" && <PracticeRoom data={data} />}
          {room === "System" && <SystemRoom data={data} loading={loading} error={error} refresh={refresh} />}
        </main>
        <ContextColumn data={data} loading={loading} error={error} />
      </div>
    </div>
  );
}

function PresenceBand({ state, sentence, data, localTtftMs, loading, error, refresh }) {
  const last = data?.system?.last_request;
  const route = last?.task_type ?? "no completed route";
  const model = last?.model ?? firstModel(data) ?? "no model observed";
  const backendTtft = data?.system?.uplink?.last_ttft_ms;
  const ttft = localTtftMs ?? backendTtft;

  return (
    <header className="presence-band">
      <div className={`sigil-mark sigil-${state}`} aria-label={`Delphi presence: ${state}`}>
        <span />
      </div>
      <div className="presence-copy">
        <p className="eyebrow">DELPHI NOCTURNE</p>
        <h1>{state}</h1>
        <p>{sentence}</p>
        <div className="trace-chips" aria-label="backend trace chips">
          <MetricChip label="route" value={route} />
          <MetricChip label="model" value={model} />
          <MetricChip label="first token" value={ttft == null ? null : `${Math.round(ttft)}ms`} />
          <MetricChip label="state source" value={last ? "request log" : "local session"} />
        </div>
      </div>
      <div className="presence-side">
        <Clock />
        <button type="button" onClick={refresh} className="ghost-button">
          {loading ? "syncing…" : "sync state"}
        </button>
        {error ? <span className="fault-line">{error}</span> : null}
      </div>
    </header>
  );
}

function ChatRoom() {
  return (
    <div className="chat-room-grid">
      <section className="room-panel min-h-0">
        <PanelTitle title="Conversation" detail="one surface for the active turn" />
        <ChatRail />
      </section>
      <section className="room-panel min-h-0">
        <PanelTitle title="Artifact" detail="model preview directives only" />
        <OutputCanvas />
      </section>
    </div>
  );
}

function MemoryRoom({ data }) {
  const memory = data?.memory;
  const zones = memory?.zones ?? [];
  return (
    <div className="memory-room-grid">
      <section className="room-panel graph-panel">
        <PanelTitle title="Memory graph" detail="vault zone counts; semantic links not yet built" />
        <div className="honest-graph" style={{ "--fill": memory?.fill ?? 0 }}>
          <div className="graph-core" />
          {zones.map((zone, idx) => (
            <div
              key={zone.name}
              className={`graph-zone zone-${idx} ${idx === memory?.active_zone_index ? "is-active" : ""}`}
              title={`${zone.name}: ${zone.count} notes`}
            >
              <span>{zone.count}</span>
            </div>
          ))}
        </div>
        <div className="metric-row">
          <MetricCard label="vault fill" value={formatPct(memory?.fill)} source="vault bytes ÷ configured allotment" />
          <MetricCard label="notes" value={fmt(memory?.note_count)} source="*.md files in vault" />
          <MetricCard label="entities" value={fmt(memory?.entity_count)} source="vault/entities/*.md" />
          <MetricCard label="projects" value={fmt(memory?.project_count)} source="vault/projects/*.md" />
        </div>
      </section>
      <section className="room-panel">
        <PanelTitle title="Zones" detail={memory?.active_zone_source ?? "waiting for backend state"} />
        <ZoneBars zones={zones} />
      </section>
    </div>
  );
}

function PracticeRoom({ data }) {
  const practice = data?.practice;
  return (
    <section className="room-panel practice-room">
      <PanelTitle title="Practice" detail={practice?.source ?? "backend state unavailable"} />
      <div className="metric-row">
        <MetricCard label="vocab cards" value={fmt(practice?.vocab_card_count)} source="vault GRE vocab files" />
        <MetricCard label="due cards" value={fmt(practice?.due_cards)} source="not built yet" />
        <MetricCard label="accuracy" value={formatPctMaybe(practice?.accuracy_percent)} source="not built yet" />
        <MetricCard label="streak" value={fmt(practice?.streak_days)} source="not built yet" />
      </div>
      <NotBuiltList items={data?.not_built_yet ?? []} />
    </section>
  );
}

function SystemRoom({ data, loading, error, refresh }) {
  return (
    <div className="system-room-grid">
      <section className="room-panel">
        <PanelTitle title="My systems" detail="live backend service contract" />
        <ServiceGrid services={data?.services ?? []} />
      </section>
      <section className="room-panel">
        <PanelTitle title="Roster / routing" detail="config + today's request counts and p50 latency" />
        <RosterTable rows={data?.roster ?? []} />
      </section>
      <section className="room-panel">
        <PanelTitle title="Uplink" detail="request log hourly counts and last completion metrics" />
        <Sparkline counts={data?.system?.uplink?.hourly_counts ?? []} />
        <div className="metric-row compact">
          <MetricCard label="requests today" value={fmt(data?.system?.requests_today)} source="requests.jsonl" />
          <MetricCard label="failures today" value={fmt(data?.system?.failures_today)} source="requests.jsonl error field" />
          <MetricCard label="last TTFT" value={ms(data?.system?.uplink?.last_ttft_ms)} source="request telemetry" />
          <MetricCard label="last tok/s" value={tps(data?.system?.uplink?.last_tokens_per_second)} source="output tokens ÷ latency" />
        </div>
      </section>
      <section className="room-panel">
        <PanelTitle title="Request log" detail="latest durable JSONL records" />
        <RequestLog rows={data?.requests ?? []} />
        <button type="button" className="ghost-button" onClick={refresh}>{loading ? "syncing…" : "refresh"}</button>
        {error ? <p className="fault-line">{error}</p> : null}
      </section>
      <section className="room-panel wide">
        <PanelTitle title="Not built yet" detail="explicitly unavailable; no fabricated readouts" />
        <NotBuiltList items={data?.not_built_yet ?? []} />
      </section>
    </div>
  );
}

function ContextColumn({ data, loading, error }) {
  const context = data?.system?.context;
  const cue = data?.cue_cards?.[0];
  const lastWrite = data?.memory?.last_vault_write;
  return (
    <aside className="context-column">
      <PanelTitle title="Context" detail={loading ? "syncing backend" : error ? "backend fault" : "backend metrics only"} />
      <MetricCard label="context meter" value={contextTokens(context)} source={context?.source ?? "request log unavailable"} />
      <div className="thin-meter" aria-label="context meter fill">
        <span style={{ width: `${Math.min((context?.fill ?? 0) * 100, 100)}%` }} />
      </div>
      <MetricCard label="bitspace" value={formatPct(data?.memory?.fill)} source="vault bytes ÷ configured allotment" />
      <div className="thin-meter memory" aria-label="vault bitspace fill">
        <span style={{ width: `${Math.min((data?.memory?.fill ?? 0) * 100, 100)}%` }} />
      </div>
      <section className="cue-card">
        <p className="eyebrow">Cue card</p>
        {cue ? (
          <>
            <h3>{cue.title}</h3>
            <p>{cue.detail}</p>
          </>
        ) : (
          <p>No backend cue cards.</p>
        )}
      </section>
      <section className="cue-card">
        <p className="eyebrow">Last vault write</p>
        <h3>{lastWrite ? (lastWrite.ok ? "ok" : "failed") : "unavailable"}</h3>
        <p>{lastWrite?.path ?? lastWrite?.error ?? "no vault write in today’s log"}</p>
      </section>
      <ServiceGrid services={(data?.services ?? []).slice(0, 4)} dense />
    </aside>
  );
}

function PanelTitle({ title, detail }) {
  return (
    <div className="panel-title">
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}

function MetricChip({ label, value }) {
  return (
    <span className="metric-chip">
      <b>{label}</b>{value ?? "—"}
    </span>
  );
}

function MetricCard({ label, value, source }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value ?? "—"}</strong>
      <small>{source}</small>
    </div>
  );
}

function ServiceGrid({ services, dense = false }) {
  if (!services.length) return <p className="empty-state">No backend service state yet.</p>;
  return (
    <div className={dense ? "service-grid dense" : "service-grid"}>
      {services.map((service) => (
        <div key={service.id} className={`service-card status-${service.status}`}>
          <span>{service.name}</span>
          <strong>{service.status}</strong>
          <small>{service.detail}</small>
        </div>
      ))}
    </div>
  );
}

function RosterTable({ rows }) {
  if (!rows.length) return <p className="empty-state">No roster state yet.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>Route</th><th>Model</th><th>Req</th><th>p50</th><th>Err</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.task_type}>
              <td>{row.task_type}</td>
              <td>{row.model}</td>
              <td>{row.request_count}</td>
              <td>{ms(row.p50_latency_ms)}</td>
              <td>{row.error_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RequestLog({ rows }) {
  if (!rows.length) return <p className="empty-state">No requests in today’s JSONL log.</p>;
  return (
    <div className="request-log">
      {rows.map((row) => (
        <div key={row.request_id} className={row.error ? "is-error" : ""}>
          <span>{timeOf(row.ts)}</span>
          <b>{row.task_type}</b>
          <small>{row.model}</small>
          <em>{row.error ? row.error : `${row.output_tokens ?? "—"} out tok`}</em>
        </div>
      ))}
    </div>
  );
}

function ZoneBars({ zones }) {
  if (!zones.length) return <p className="empty-state">No vault zone counts yet.</p>;
  const max = Math.max(...zones.map((z) => z.count), 1);
  return (
    <div className="zone-bars">
      {zones.map((zone) => (
        <div key={zone.name}>
          <span>{zone.name}</span>
          <div><i style={{ width: `${(zone.count / max) * 100}%` }} /></div>
          <b>{zone.count}</b>
        </div>
      ))}
    </div>
  );
}

function Sparkline({ counts }) {
  const max = Math.max(...counts, 1);
  return (
    <div className="sparkline" aria-label="hourly request counts">
      {Array.from({ length: 24 }, (_, idx) => {
        const count = counts[idx] ?? 0;
        return <span key={idx} title={`${idx}:00 ${count}`} style={{ height: `${8 + (count / max) * 42}px` }} />;
      })}
    </div>
  );
}

function NotBuiltList({ items }) {
  if (!items.length) return <p className="empty-state">Backend did not report unavailable metrics.</p>;
  return <ul className="not-built-list">{items.map((item) => <li key={item}>{item}</li>)}</ul>;
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return <time>{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>;
}

function useKeyboardShortcuts() {
  useEffect(() => {
    const onKey = (e) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === "k") {
        e.preventDefault();
        window.dispatchEvent(new Event("delphi:focus-input"));
      } else if (meta && e.key.toLowerCase() === "l") {
        e.preventDefault();
        clearSession();
      } else if (e.key === "Escape" && useChatStore.getState().isStreaming) {
        cancelDelphiStream();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function clearSession() {
  useChatStore.getState().clear();
  const delphi = useDelphiStore.getState();
  delphi.reset();
  delphi.pushEvent("Session cleared by operator");
}

function presenceState(mode) {
  const m = String(mode || "IDLE").toUpperCase();
  if (m === "THINKING" || m === "SEARCHING") return "thinking";
  if (m === "BUILDING") return "creating";
  if (m === "DREAMING") return "dreaming";
  return "listening";
}

function presenceSentence(mode, data) {
  const last = data?.system?.last_request;
  if (String(mode || "").toUpperCase() !== "IDLE") return "I am working through the active request.";
  if (last) return `Last routed request: ${last.task_type} via ${last.model}.`;
  return "I am listening; no completed backend request is logged for today yet.";
}

function firstModel(data) {
  return data?.roster?.find((row) => row.model)?.model;
}

function fmt(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

function ms(value) {
  return value === null || value === undefined ? null : `${Math.round(value)}ms`;
}

function tps(value) {
  return value === null || value === undefined ? null : `${value} tok/s`;
}

function formatPct(value) {
  return value === null || value === undefined ? null : `${Math.round(value * 100)}%`;
}

function formatPctMaybe(value) {
  return value === null || value === undefined ? null : `${Math.round(value)}%`;
}

function contextTokens(context) {
  if (!context || context.last_request_tokens == null) return null;
  return `${context.last_request_tokens.toLocaleString()} / ${context.window_tokens.toLocaleString()} tok`;
}

function timeOf(ts) {
  if (!ts) return "—";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default App;
