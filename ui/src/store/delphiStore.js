import { create } from "zustand";

/**
 * delphiStore — Delphi's "ambient state" parsed out of the response stream.
 *
 * Set ONLY from the stream parser (`hooks/useDelphiStream.js`). Components
 * are read-only consumers. This is the single source of truth for the HUD
 * mode badge, active-task label, and preview-box content.
 *
 *   mode         current emission phase  — IDLE / THINKING / BUILDING / SEARCHING
 *   activeTask   short label shown in HUD  ("Refactoring soul.py")
 *   preview      { kind: 'code'|'document', language?: string, content: string }
 *   model        which Ollama model served the last response (from /v1/models or echo)
 *   error        last stream-level error, surfaced in the chat rail
 */
const INITIAL_STATE = {
  mode: "IDLE",
  activeTask: null,
  preview: null,
  model: null,
  error: null,
};

export const useDelphiStore = create((set) => ({
  ...INITIAL_STATE,

  setMode: (mode) => set({ mode }),
  setActiveTask: (activeTask) => set({ activeTask }),
  setPreview: (preview) => set({ preview }),
  clearPreview: () => set({ preview: null }),
  setModel: (model) => set({ model }),
  setError: (error) => set({ error }),

  reset: () => set(INITIAL_STATE),
}));
