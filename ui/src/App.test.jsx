import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import App from "./App";

vi.mock("./components/ChatRail", () => ({
  ChatRail: () => <div>chat rail</div>,
}));
vi.mock("./components/OutputCanvas", () => ({
  OutputCanvas: () => <div>artifact canvas</div>,
}));

const UI_STATE = {
  system: {
    requests_today: 3,
    failures_today: 1,
    last_request: { request_id: "r3", task_type: "code", model: "phi-local" },
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
    { id: "gateway", name: "Gateway", status: "ok", detail: "healthz ok" },
    { id: "worker", name: "Worker", status: "ok", detail: "queue connected" },
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
      output_tokens: 80,
      error: null,
    },
  ],
  memory: {
    fill: 0.42,
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
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => UI_STATE }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Nocturne App", () => {
  it("renders exported interface metrics from /ui/state instead of fabricated values", async () => {
    render(<App />);

    await screen.findByText("DELPHI NOCTURNE");
    expect(fetch.mock.calls[0][0]).toBe("/ui/state");
    expect(screen.getByText("120 / 1,000 tok")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Request failures today")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "System" }));
    expect(await screen.findByText("Roster / routing")).toBeInTheDocument();
    expect(screen.getByText("requests today")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2000ms")).toBeInTheDocument();
    expect(screen.getByText("Tool-call trace chips in request telemetry")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Practice" }));
    expect(await screen.findByText("vocab cards")).toBeInTheDocument();
    expect(screen.getAllByText("not built yet").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
