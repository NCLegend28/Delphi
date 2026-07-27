import { useEffect, useRef, useState } from "react";
import "./lib/delphi-sigil.js";
import "./lib/delphi-brain.js";
import { OutputCanvas } from "./components/OutputCanvas";
import { useChatStore } from "./store/chatStore";
import { useDelphiStore } from "./store/delphiStore";
import { cancelDelphiStream, useDelphiStream } from "./hooks/useDelphiStream";
import { useUiState } from "./hooks/useUiState";

const ROOMS = [
  { id: "chat", label: "Chat", icon: "ph-chat-teardrop-dots" },
  { id: "memory", label: "Memory", icon: "ph-brain" },
  { id: "practice", label: "Practice", icon: "ph-exam" },
  { id: "system", label: "System", icon: "ph-circuitry" },
];

function App() {
  const [room, setRoom] = useState("chat");
  const [selectedNode, setSelectedNode] = useState(null);
  const { data, error, loading, refresh } = useUiState();
  const delphiMode = useDelphiStore((s) => s.mode);
  const ttftMs = useDelphiStore((s) => s.ttftMs);

  useKeyboardShortcuts();

  return (
    <div className="home-shell">
      <PresenceBand data={data} mode={delphiMode} ttftMs={ttftMs} loading={loading} error={error} refresh={refresh} />
      <RoomTabs active={room} onChange={setRoom} />
      <div className="home-workspace">
        <main className="room-stage" aria-live="polite">
          {room === "chat" && <ChatRoom data={data} />}
          {room === "memory" && <MemoryRoom data={data} onNodeSelect={setSelectedNode} />}
          {room === "practice" && <PracticeRoom data={data} />}
          {room === "system" && <SystemRoom data={data} loading={loading} error={error} refresh={refresh} />}
        </main>
        <ContextColumn data={data} room={room} selectedNode={selectedNode} loading={loading} error={error} />
      </div>
    </div>
  );
}

function PresenceBand({ data, mode, ttftMs, loading, error, refresh }) {
  const last = data?.system?.last_request;
  const state = presenceState(mode, last);
  const route = last?.task_type ?? "no completed route";
  const model = last?.model ?? firstModel(data) ?? "no model observed";
  const firstToken = ttftMs ?? data?.system?.uplink?.last_ttft_ms;
  const sentence = presenceSentence(mode, data);
  const detail = abbreviatePresenceBlurb(sentence.detail);

  return (
    <header className="presence-band">
      <div className="presence-glow" />
      <div className="presence-sigil-frame">
        <delphi-sigil state={state} aria-label={`Delphi sigil ${state}`} />
      </div>
      <section className="presence-copy">
        <span className="kicker">{state}</span>
        <h1>{sentence.title}</h1>
        <p className="presence-blurb" title={sentence.detail}>{detail}</p>
        <div className="trace-line" aria-label="technical route trace">
          <Trace label="model" value={model} />
          <Trace label="route" value={route} />
          <Trace label="first token" value={firstToken == null ? null : `${Math.round(firstToken)} ms`} />
          <Trace label="source" value={last ? "request log" : "local session"} />
        </div>
      </section>
      <section className="presence-actions">
        <Clock />
        <button type="button" className="btn btn-secondary" onClick={refresh}>{loading ? "Syncing…" : "Sync state"}</button>
        {error ? <span className="fault-line">{error}</span> : null}
      </section>
    </header>
  );
}

function RoomTabs({ active, onChange }) {
  return (
    <nav className="room-tabs" aria-label="Delphi rooms">
      {ROOMS.map((room) => (
        <button key={room.id} type="button" className={active === room.id ? "is-active" : ""} onClick={() => onChange(room.id)}>
          <i className={`ph ${room.icon}`} /> {room.label}
        </button>
      ))}
      <button type="button" className="settings-tab"><i className="ph ph-gear-six" /> Settings</button>
    </nav>
  );
}

function ChatRoom({ data }) {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingId = useChatStore((s) => s.streamingId);
  const error = useChatStore((s) => s.error);
  const { send } = useDelphiStream();
  const [draft, setDraft] = useState("");
  const scrollerRef = useRef(null);

  useEffect(() => {
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isStreaming]);

  const submit = (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || isStreaming) return;
    setDraft("");
    send(text);
  };

  return (
    <section className="chat-room">
      <div ref={scrollerRef} className="conversation-surface">
        {messages.length === 0 ? (
          <div className="empty-conversation">
            <span>Ask me something, or tell me what to build.</span>
            <small>Conversation telemetry appears as real route/tool/latency chips after backend requests complete.</small>
          </div>
        ) : messages.map((message) => (
          <article key={message.id} className={`turn ${message.role === "user" ? "turn-user" : "turn-delphi"}`}>
            <div className="turn-meta">
              <strong>{message.role === "user" ? "You" : "Delphi"}</strong>
              {message.id === streamingId ? <span>streaming</span> : null}
              {message.role !== "user" ? <Trace label="route" value={data?.system?.last_request?.task_type} /> : null}
            </div>
            <p>{message.content}</p>
          </article>
        ))}
        {error ? <p className="fault-line">{error}</p> : null}
      </div>
      <form className="composer" onSubmit={submit}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask me something, or tell me what to build."
          rows={1}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) submit(event);
          }}
        />
        <button type="button" className="icon-button" aria-label="attach image"><i className="ph ph-paperclip" /></button>
        <button type="button" className="icon-button" aria-label="record audio"><i className="ph ph-microphone" /></button>
        <button type="submit" className="btn btn-primary" disabled={isStreaming || !draft.trim()}>Send <i className="ph ph-arrow-up" /></button>
      </form>
    </section>
  );
}

function MemoryRoom({ data, onNodeSelect }) {
  const memory = data?.memory;
  const fill = memory?.fill ?? 0;
  const backendZone = memory?.active_zone_index ?? 0;
  const beads = memory?.beads ?? [];
  const nodes = JSON.stringify(beads);
  const [query, setQuery] = useState("");
  const [zoneOverride, setZoneOverride] = useState(null);
  const [highlightZone, setHighlightZone] = useState(-1);
  const activeZone = zoneOverride ?? backendZone;
  const brainRef = useRef(null);
  const searchMatches = query.trim()
    ? beads.filter((bead) => String(bead.name ?? bead.path ?? "").toLowerCase().includes(query.trim().toLowerCase()))
    : [];

  useEffect(() => {
    const node = brainRef.current;
    if (!node) return undefined;
    const onSelect = (event) => {
      onNodeSelect(event.detail);
      if (Number.isInteger(event.detail?.zoneIndex)) {
        setZoneOverride(event.detail.zoneIndex);
        setHighlightZone(event.detail.zoneIndex);
      }
    };
    const onClear = () => onNodeSelect(null);
    node.addEventListener("node-select", onSelect);
    node.addEventListener("node-clear", onClear);
    return () => {
      node.removeEventListener("node-select", onSelect);
      node.removeEventListener("node-clear", onClear);
    };
  }, [onNodeSelect]);

  const submitSearch = (event) => {
    event.preventDefault();
    const match = brainRef.current?.find?.(query)?.[0];
    if (!match) return;
    brainRef.current.focusNode(match.name);
    setZoneOverride(match.zone);
    setHighlightZone(match.zone);
  };

  const selectZone = (idx) => {
    setZoneOverride(idx);
    setHighlightZone(idx);
  };

  return (
    <section className="memory-room">
      <div className="brain-wrap">
        <delphi-brain
          ref={brainRef}
          fill={String(fill)}
          zone={String(activeZone)}
          highlight={String(highlightZone)}
          query={query}
          data-nodes={nodes}
          className="brain-element"
        />
        <form className="brain-search" onSubmit={submitSearch}>
          <i className="ph ph-magnifying-glass" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search real vault beads"
            aria-label="Search real vault beads"
          />
          {query ? <span>{searchMatches.length} match{searchMatches.length === 1 ? "" : "es"}</span> : null}
        </form>
        <div className="brain-help">drag to spin · click a node · enter opens first match</div>
      </div>
      <section className="zone-panel">
        <PanelTitle title="Zones" detail={memory?.active_zone_source ?? "backend zone state unavailable"} />
        <ZoneList zones={memory?.zones ?? []} active={activeZone} onSelect={selectZone} />
      </section>
    </section>
  );
}

function PracticeRoom({ data }) {
  const practice = data?.practice;
  const unavailable = [practice?.due_cards, practice?.accuracy_percent, practice?.streak_days].every((value) => value == null);
  return (
    <section className="practice-room">
      <div className="practice-card">
        <span className="kicker">Practice</span>
        <h2>{unavailable ? "Spaced repetition is not wired yet." : "Practice is ready."}</h2>
        <p>{practice?.source ?? "Backend practice state unavailable."}</p>
        <div className="metric-grid three">
          <Metric label="vocab cards" value={fmt(practice?.vocab_card_count)} source="vault GRE vocab files" />
          <Metric label="due cards" value={fmt(practice?.due_cards)} source="SRS schedule unavailable" />
          <Metric label="streak" value={fmt(practice?.streak_days)} source="SRS history unavailable" />
        </div>
      </div>
      <NotBuilt items={data?.not_built_yet ?? []} />
    </section>
  );
}

function SystemRoom({ data, loading, error, refresh }) {
  return (
    <section className="system-room">
      <PanelTitle title="Services" detail="health cards backed by gateway probes/config" />
      <ServiceGrid services={data?.services ?? []} />
      <PanelTitle title="Roster and routing" detail="roster config + today's request counts and p50" />
      <RosterTable rows={data?.roster ?? []} />
      <div className="split-panels">
        <section>
          <PanelTitle title="Last requests" detail="durable request JSONL" />
          <RequestLog rows={data?.requests ?? []} />
        </section>
        <section>
          <PanelTitle title="Uplink" detail="last hour from request log" />
          <Sparkline counts={data?.system?.uplink?.hourly_counts ?? []} />
          <div className="uplink-stats">
            <span>{ms(data?.system?.uplink?.last_ttft_ms) ?? "—"} first token</span>
            <span>{tps(data?.system?.uplink?.last_tokens_per_second) ?? "—"}</span>
          </div>
        </section>
      </div>
      <button type="button" className="btn btn-secondary" onClick={refresh}>{loading ? "Syncing…" : "Refresh"}</button>
      {error ? <span className="fault-line">{error}</span> : null}
    </section>
  );
}

function ContextColumn({ data, room, selectedNode, loading, error }) {
  const memory = data?.memory;
  const context = data?.system?.context;
  const cue = data?.cue_cards?.[0] ?? firstUnavailableCue(data);
  return (
    <aside className="context-column">
      {room === "chat" ? <ArtifactPanel /> : null}
      {room === "memory" ? <MemoryReadout memory={memory} selectedNode={selectedNode} /> : null}
      {room === "practice" ? <PracticeReadout practice={data?.practice} /> : null}
      {room === "system" ? <SystemReadout data={data} /> : null}
      <section className="readout-card">
        <PanelTitle title="Right now" detail={loading ? "syncing backend" : error ? "backend fault" : "request log state"} />
        <Readout label="Context" value={contextTokens(context)} />
        <Meter fill={context?.fill} />
        <Readout label="Rate" value={`${tps(data?.system?.uplink?.last_tokens_per_second) ?? "—"} · wrote ${lastVaultWrite(memory)}`} />
      </section>
      <section className="readout-card">
        <PanelTitle title="My systems" detail="live service cards" />
        <MiniServices services={(data?.services ?? []).slice(0, 5)} />
      </section>
      <section className="cue-card">
        <span className="kicker">Cue card</span>
        <h3>{cue.title}</h3>
        <p>{cue.detail}</p>
      </section>
    </aside>
  );
}

function ArtifactPanel() {
  return (
    <section className="artifact-panel" aria-label="Artifact output canvas">
      <OutputCanvas />
    </section>
  );
}

function MemoryReadout({ memory, selectedNode }) {
  return (
    <section className="readout-card">
      <PanelTitle title="Bitspace" detail="vault bytes ÷ configured allotment" />
      <div className="big-number">{formatBytes(memory?.vault_bytes)} <span>of {formatBytes(memory?.vault_allotted_bytes)} · {formatPct(memory?.fill) ?? "—"}</span></div>
      <Meter fill={memory?.fill} memory />
      {selectedNode ? <Readout label={selectedNode.kind} value={selectedNode.name} /> : <Readout label="Beads" value={`${memory?.beads?.length ?? 0} real vault paths`} />}
    </section>
  );
}

function PracticeReadout({ practice }) {
  return (
    <section className="readout-card">
      <PanelTitle title="This session" detail="SRS metrics unavailable until backend scheduling lands" />
      <Readout label="Cards in vault" value={fmt(practice?.vocab_card_count)} />
      <Readout label="Due now" value={fmt(practice?.due_cards)} />
      <Readout label="Accuracy" value={formatPctMaybe(practice?.accuracy_percent)} />
    </section>
  );
}

function SystemReadout({ data }) {
  return (
    <section className="readout-card">
      <PanelTitle title="Request summary" detail="today from request log" />
      <Readout label="Requests" value={fmt(data?.system?.requests_today)} />
      <Readout label="Failures" value={fmt(data?.system?.failures_today)} />
      <Readout label="Last route" value={data?.system?.last_request?.task_type} />
    </section>
  );
}

function PanelTitle({ title, detail }) {
  return <div className="panel-title"><h2>{title}</h2><p>{detail}</p></div>;
}

function Trace({ label, value }) {
  const raw = value ?? "—";
  const display = label === "model" ? compactModelName(raw) : abbreviatePresenceBlurb(raw, 30);
  return <span className="trace-chip" title={`${label}: ${raw}`}><b>{label}</b><span>{display}</span></span>;
}

function Metric({ label, value, source }) {
  return <div className="metric-card"><span>{label}</span><strong>{value ?? "—"}</strong><small>{source}</small></div>;
}

function ServiceGrid({ services }) {
  if (!services.length) return <p className="empty-state">No service state reported.</p>;
  return <div className="service-grid">{services.map((service) => <article key={service.id} className={`service-card status-${service.status}`}><span>{service.name}</span><strong>{service.status}</strong><small>{service.detail}</small></article>)}</div>;
}

function MiniServices({ services }) {
  if (!services.length) return <p className="empty-state">No services.</p>;
  return <div className="mini-services">{services.map((service) => <span key={service.id} className={`status-${service.status}`}><i />{service.name}</span>)}</div>;
}

function RosterTable({ rows }) {
  if (!rows.length) return <p className="empty-state">No roster rows reported.</p>;
  return (
    <div className="table-shell">
      <table className="table">
        <thead><tr><th>Route</th><th>Model</th><th>Requests</th><th>p50</th><th>Errors</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.task_type}><td>{row.task_type}</td><td>{row.model}</td><td>{row.request_count}</td><td>{ms(row.p50_latency_ms) ?? "—"}</td><td>{row.error_count}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function RequestLog({ rows }) {
  if (!rows.length) return <p className="empty-state">No requests in today's durable JSONL log.</p>;
  return <div className="request-log">{rows.map((row) => <div key={row.request_id ?? `${row.ts}-${row.task_type}`}><span>{timeOf(row.ts)}</span><b>{row.task_type}</b><small>{row.model}</small><em>{row.error ? row.error : `${fmt(row.output_tokens)} out tok · ${ms(row.latency_ms) ?? "—"}`}</em></div>)}</div>;
}

function ZoneList({ zones, active, onSelect }) {
  if (!zones.length) return <p className="empty-state">No vault zones reported.</p>;
  return (
    <div className="zone-list">
      {zones.map((zone, idx) => (
        <button
          key={zone.name}
          type="button"
          className={idx === active ? "is-active" : ""}
          onClick={() => onSelect?.(idx)}
          onMouseEnter={() => onSelect?.(idx)}
        >
          <i />
          <span>{zone.name}</span>
          <b>{zone.count}</b>
        </button>
      ))}
    </div>
  );
}

function Sparkline({ counts }) {
  const max = Math.max(...counts, 1);
  return <div className="sparkline" aria-label="hourly request counts">{Array.from({ length: 24 }, (_, idx) => <span key={idx} title={`${idx}:00 ${counts[idx] ?? 0}`} style={{ height: `${8 + ((counts[idx] ?? 0) / max) * 46}px` }} />)}</div>;
}

function NotBuilt({ items }) {
  if (!items.length) return <p className="empty-state">No unavailable metrics reported.</p>;
  return <section className="not-built"><PanelTitle title="Not built yet" detail="explicitly unavailable; no fabricated readouts" /><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></section>;
}

function Readout({ label, value }) {
  return <div className="readout"><span>{label}</span><b>{value ?? "—"}</b></div>;
}

function Meter({ fill, memory = false }) {
  const pct = fill == null ? 0 : Math.max(0, Math.min(fill, 1)) * 100;
  return <div className={`meter ${memory ? "memory" : ""}`}><span style={{ width: `${pct}%` }} /></div>;
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
    const onKey = (event) => {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.querySelector(".composer textarea")?.focus();
      } else if (meta && event.key.toLowerCase() === "l") {
        event.preventDefault();
        clearSession();
      } else if (event.key === "Escape" && useChatStore.getState().isStreaming) {
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

function presenceState(mode, last) {
  const current = String(mode || "IDLE").toUpperCase();
  if (["THINKING", "SEARCHING"].includes(current)) return "thinking";
  if (current === "BUILDING") return "creating";
  if (current === "DREAMING") return "dreaming";
  if (last?.error) return "thinking";
  return "listening";
}

function presenceSentence(mode, data) {
  const current = String(mode || "IDLE").toUpperCase();
  const last = data?.system?.last_request;
  if (current !== "IDLE") return { title: "I'm working through the active request.", detail: "Telemetry writes on completion." };
  if (last) {
    const tokens = fmt((last.input_tokens ?? 0) + (last.output_tokens ?? 0)) ?? "—";
    return { title: `Last routed as ${last.task_type}.`, detail: `${compactModelName(last.model)} · ${ms(last.latency_ms) ?? "latency unavailable"} · ${tokens} tokens` };
  }
  return { title: "I'm listening.", detail: "No request logged today." };
}

function compactModelName(model) {
  if (!model) return "model unavailable";
  const cleaned = String(model)
    .replace(/^.*\//, "")
    .replace(/-instruct/i, "")
    .replace(/-GGUF/i, "")
    .replace(/bartowski\//i, "")
    .replace(/mini/i, "mini")
    .replace(/:{1,2}/g, " · ");
  return abbreviatePresenceBlurb(cleaned, 26);
}

function abbreviatePresenceBlurb(value, maxLength = 54) {
  const text = String(value ?? "");
  if (text.length <= maxLength) return text;
  const head = Math.max(12, Math.ceil((maxLength - 1) * 0.62));
  const tail = Math.max(6, maxLength - head - 1);
  return `${text.slice(0, head).trimEnd()}…${text.slice(-tail).trimStart()}`;
}

function firstModel(data) {
  return data?.roster?.find((row) => row.model)?.model;
}

function firstUnavailableCue(data) {
  const item = data?.not_built_yet?.[0];
  return item ? { title: item, detail: "Reported unavailable by /ui/state." } : { title: "No cue cards", detail: "The backend has nothing to surface right now." };
}

function lastVaultWrite(memory) {
  const write = memory?.last_vault_write;
  if (!write) return "unavailable";
  if (!write.ok) return write.error ?? "failed";
  return timeAgo(write.modified_at);
}

function contextTokens(context) {
  if (!context || context.last_request_tokens == null) return null;
  return `${context.last_request_tokens.toLocaleString()} / ${context.window_tokens.toLocaleString()} · ${formatPct(context.fill)}`;
}

function timeAgo(value) {
  if (!value) return "unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unavailable";
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 90) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

function timeOf(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmt(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

function ms(value) {
  return value === null || value === undefined ? null : `${Math.round(value)} ms`;
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

function formatBytes(value) {
  if (value === null || value === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Number(value);
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? Math.round(size) : size.toFixed(1)} ${units[unit]}`;
}

export default App;
