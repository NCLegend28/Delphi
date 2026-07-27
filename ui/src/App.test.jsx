import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

vi.mock("./components/OutputCanvas", () => ({
  OutputCanvas: () => <div>artifact canvas</div>,
}));
vi.mock("./hooks/useDelphiStream", () => ({
  cancelDelphiStream: vi.fn(),
  useDelphiStream: () => ({ send: vi.fn() }),
}));

const UI_STATE = {
  system: {
    requests_today: 3,
    failures_today: 1,
    last_request: {
      request_id: "r3",
      task_type: "code",
      model: "bartowski/Phi-3.5-mini-instruct-GGUF:Q6_K",
      latency_ms: 5000,
      input_tokens: 40,
      output_tokens: 80,
    },
    context: {
      last_request_tokens: 120,
      window_tokens: 1000,
      fill: 0.12,
      source: "last completed request input_tokens + output_tokens",
    },
    uplink: {
      last_ttft_ms: 1000,
      last_latency_ms: 5000,
      last_tokens_per_second: 16,
      hourly_counts: Array.from({ length: 24 }, (_, i) => (i === 11 ? 3 : 0)),
    },
  },
  services: [
    { id: "caddy", name: "Caddy", status: "ok", detail: "serving this UI" },
    { id: "gateway", name: "Gateway", status: "ok", detail: "healthz ok" },
    { id: "worker", name: "Worker", status: "ok", detail: "queue connected" },
    { id: "redis", name: "Redis", status: "ok", detail: "redis://test" },
    { id: "inference", name: "Inference", status: "ok", detail: "1 model available" },
    { id: "whisper", name: "Whisper", status: "idle", detail: "base" },
  ],
  roster: [
    { task_type: "chat", model: "phi-local", request_count: 2, p50_latency_ms: 2000, error_count: 1 },
    { task_type: "code", model: "phi-local", request_count: 1, p50_latency_ms: 5000, error_count: 0 },
  ],
  requests: [
    {
      ts: "2026-07-27T11:00:00-05:00",
      request_id: "r3",
      task_type: "code",
      model: "phi-local",
      latency_ms: 5000,
      output_tokens: 80,
      error: null,
    },
  ],
  memory: {
    fill: 0.42,
    vault_bytes: 430,
    vault_allotted_bytes: 1024,
    note_count: 4,
    entity_count: 1,
    project_count: 1,
    active_zone_index: 4,
    active_zone_source: "largest vault note-count zone",
    zones: [
      { name: "Code & models", count: 1 },
      { name: "Trading", count: 0 },
      { name: "Language", count: 1 },
      { name: "Infra & deploy", count: 0 },
      { name: "Delphi herself", count: 2 },
    ],
    beads: [
      { name: "Delphi", kind: "entity", path: "entities/Delphi.md", zone: "Delphi herself", zone_index: 4 },
      { name: "Nursery", kind: "project", path: "projects/Nursery.md", zone: "Code & models", zone_index: 0 },
      { name: "obviate", kind: "note", path: "knowledge/gre/vocab/obviate.md", zone: "Language", zone_index: 2 },
    ],
    last_vault_write: { ok: false, path: null, error: "disk full" },
  },
  practice: {
    vocab_card_count: 1,
    due_cards: null,
    accuracy_percent: null,
    streak_days: null,
    source: "vault vocabulary files; SRS scheduling is not built yet",
  },
  cue_cards: [{ kind: "system", title: "Request failures today", detail: "1 failed request" }],
  not_built_yet: ["SRS due-card scheduling and streak calculation", "Tool-call trace chips in request telemetry"],
};

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class ResizeObserver { observe() {} disconnect() {} });
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
    setTransform: vi.fn(), clearRect: vi.fn(), createRadialGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
    fillRect: vi.fn(), beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(), moveTo: vi.fn(),
    lineTo: vi.fn(), createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })), measureText: vi.fn(() => ({ width: 20 })),
    fillText: vi.fn(), setLineDash: vi.fn(), quadraticCurveTo: vi.fn(), closePath: vi.fn(),
  }));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => UI_STATE }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Delphi AI Home UI", () => {
  it("implements the attached zip shell and renders only /ui/state backed metrics", async () => {
    const { container } = render(<App />);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/ui/state", expect.any(Object)));
    expect(container.querySelector(".presence-band")).toBeInTheDocument();
    expect(container.querySelector("delphi-sigil")).toHaveAttribute("state", "listening");
    expect(screen.getByText("Last routed as code.")).toBeInTheDocument();
    expect(screen.getByText(/Phi-3\.5-mini · Q6_K · 5000 ms · 120 tokens/)).toBeInTheDocument();
    expect(screen.queryByText(/bartowski\/Phi-3\.5-mini-instruct-GGUF:Q6_K · 5000 ms/)).not.toBeInTheDocument();
    expect(screen.getByText("1000 ms")).toBeInTheDocument();
    expect(screen.getByText("120 / 1,000 · 12%")).toBeInTheDocument();
    expect(screen.getByText("Request failures today")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Memory/ }));
    const brain = container.querySelector("delphi-brain");
    expect(brain).toBeInTheDocument();
    expect(brain).toHaveAttribute("fill", "0.42");
    expect(brain).toHaveAttribute("zone", "4");
    expect(brain.getAttribute("data-nodes")).toContain("entities/Delphi.md");
    expect(screen.getByText("3 real vault paths")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Practice/ }));
    expect(screen.getByText("Spaced repetition is not wired yet.")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText("SRS due-card scheduling and streak calculation")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /System/ }));
    expect(await screen.findByText("Roster and routing")).toBeInTheDocument();
    expect(screen.getByText("Request summary")).toBeInTheDocument();
    expect(screen.getByText("2000 ms")).toBeInTheDocument();
    expect(screen.queryByText("DELPHI NOCTURNE")).not.toBeInTheDocument();
  });
});
