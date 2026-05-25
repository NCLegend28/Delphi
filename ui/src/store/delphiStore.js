import { create } from "zustand";

/**
 * delphiStore — Delphi's "ambient state" parsed out of the response stream
 * plus the real per-request telemetry the mission-control HUD renders.
 *
 * Set ONLY from the stream layer (`hooks/useDelphiStream.js`). Components are
 * read-only consumers. This is the single source of truth for the mode badge,
 * active-task label, preview-box content, the task-log feed, and the telemetry
 * sidebar.
 *
 *   mode          current emission phase — IDLE / THINKING / BUILDING / SEARCHING
 *   activeTask    short label shown in HUD ("Refactoring soul.py")
 *   preview       { kind: 'code'|'document', language?: string, content: string }
 *   model         which model served the last response
 *   error         last stream-level error, surfaced in the chat rail
 *   events        rolling task-log feed — { id, ts, text } (newest last)
 *   ttftMs        time-to-first-token for the in-flight / last request (real)
 *   streamChars   characters streamed in the current request (real)
 *   streamStartedAt  perf timestamp of first streamed byte (real, for t/s)
 */
const INITIAL_STATE = {
  mode: "IDLE",
  activeTask: null,
  preview: null,
  model: null,
  error: null,
  events: [],
  ttftMs: null,
  streamChars: 0,
  streamStartedAt: null,
};

const MAX_EVENTS = 60;

export const useDelphiStore = create((set) => ({
  ...INITIAL_STATE,

  setMode: (mode) => set({ mode }),
  setActiveTask: (activeTask) => set({ activeTask }),
  setPreview: (preview) => set({ preview }),
  clearPreview: () => set({ preview: null }),
  setModel: (model) => set({ model }),
  setError: (error) => set({ error }),

  /** Append a line to the task-log feed. Caps to the most recent MAX_EVENTS. */
  pushEvent: (text) =>
    set((s) => {
      const event = { id: crypto.randomUUID(), ts: Date.now(), text };
      const events = [...s.events, event];
      return { events: events.slice(-MAX_EVENTS) };
    }),
  clearEvents: () => set({ events: [] }),

  /** Reset per-request telemetry at the start of a send. */
  beginStream: () => set({ ttftMs: null, streamChars: 0, streamStartedAt: null }),
  /** Record time-to-first-token (ms) once on the first streamed byte. */
  setTtft: (ttftMs) =>
    set((s) => (s.ttftMs == null ? { ttftMs, streamStartedAt: performance.now() } : {})),
  /** Accumulate streamed character count (drives the t/s readout). */
  recordStreamChars: (n) => set((s) => ({ streamChars: s.streamChars + n })),

  reset: () => set({ ...INITIAL_STATE }),
}));
