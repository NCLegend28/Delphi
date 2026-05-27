# Delphi UI

JARVIS-style mission-control front end for Delphi. React 19 + Vite 8, talks
to the FastAPI service (parent dir) at `/v1/chat/completions` and
`/v1/audio/transcriptions`.

See [`CLAUDE.md`](./CLAUDE.md) for the full architecture, layout system,
and styling conventions. This README only covers the bits an operator
needs day-to-day.

## Run

```bash
cp .env.example .env.local
#   set VITE_DELPHI_BEARER_TOKEN to match the backend's DELPHI_BEARER_TOKEN
npm install
npm run dev          # http://localhost:5173 (Vite proxies /v1 → :8080)
npm run test         # vitest
npm run build        # production bundle to dist/
```

## Voice & Vision UI

The COMMS rail has two media affordances next to the textarea:

- **📎 Attach image** — opens the file picker. Picked files are normalized
  in the browser (`src/lib/attachments.js`, longest-edge cap 1568px,
  JPEG q≈0.85) and previewed inline above the textarea with an ✕ to
  remove. On send, the message goes upstream as an OpenAI-style content
  array: `[{type:"text", text:"…"}, {type:"image_url", image_url:{url:
  "data:image/jpeg;base64,…"}}]`. Point the backend's chat model at a
  vision-capable Ollama tag (e.g. `llama3.2-vision`) first — non-vision
  models will choke on the array.

- **🎙 Record voice note** — first press requests microphone permission
  and starts recording; second press stops, uploads the clip to
  `POST /v1/audio/transcriptions`, and **drops the transcript into the
  textarea so you can edit before sending**. Nothing is sent without an
  explicit SEND. Permission states: `idle` → `recording` → `transcribing`
  → back to `idle`, or `denied` if the user blocked the mic prompt
  (button stays disabled until permissions are re-granted in the browser).

**AUTO-SPEAK** (toggle near the rail header) makes the browser read each
assistant response aloud via the Web Speech API's `SpeechSynthesis`. It
defaults to **off**. Each assistant bubble also has its own SPEAK / STOP
button so you can voice an individual reply without enabling auto-mode.
Canceling a streaming response (`ESC` or the cancel button) interrupts
any in-flight utterance.

There is **no server-side TTS yet** — speech runs entirely in the
browser. A hosted-TTS seam is planned for `api/speech.py`; until then,
voice playback quality depends on the OS voices the browser exposes
(`speechSynthesis.getVoices()`).

### Secure-context caveat

`MediaRecorder` and `navigator.mediaDevices.getUserMedia` are only
available in a **secure context** — `https://` or `localhost`. A phone
reaching Delphi over plain `http://<host>:5173` will see the 🎙 button
do nothing because `navigator.mediaDevices` is `undefined`. This is the
same constraint that forced the `uid()` fallback in `src/lib/uid.js`
(`crypto.randomUUID` is also secure-context-only). For LAN/Tailscale
access from a phone, front the UI with HTTPS (Tailscale serve handles
this for free — see the root README).

## Environment

| Variable | Purpose |
|---|---|
| `VITE_DELPHI_BEARER_TOKEN` | Sent as `Authorization: Bearer …` on every request — chat **and** audio transcription. Must match backend `DELPHI_BEARER_TOKEN`. |
| `VITE_DELPHI_BASE_URL` | Override the API origin. Defaults to `""` (use the Vite dev proxy at `/v1`). Set to e.g. `https://delphi.your-tailnet.ts.net` for production builds served from a different origin. Applies to `/v1/chat/completions` and `/v1/audio/transcriptions` alike. |
| `VITE_DELPHI_PROXY_TARGET` | Where the Vite dev server proxies `/v1`, `/healthz`, `/readyz`. Defaults to `http://localhost:8080`. |

Vite only exposes `VITE_`-prefixed variables to the browser; everything
else in `.env.local` is invisible to the client bundle.

## Stack reference

| Layer | Choice |
|---|---|
| Framework | React 19 + Vite 8 |
| Styling | Tailwind v4 (theme in `src/index.css` via `@theme`) |
| State | Zustand (`chatStore`, `delphiStore`) |
| Streaming | Native `fetch` + SSE parser (`hooks/useDelphiStream.js`) |
| Audio | `MediaRecorder` (input) + `SpeechSynthesis` (output) |
| Tests | Vitest + Testing Library |

For the full layout grid, component map, and styling rules, see
[`CLAUDE.md`](./CLAUDE.md).
