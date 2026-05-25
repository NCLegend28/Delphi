# Delphi UI — CLAUDE.md

> JARVIS-style interface for Delphi. Lives at `ui/` inside the Delphi project.
> The Delphi FastAPI service (parent dir) is the backend.

---

## Vision

Delphi doesn't live in a chat box — Delphi **inhabits a mission-control
console**. The full-mode shell is a four-region grid (ported from
`delphi_mission_control.html`):

- **Header** — identity, deployment facts (node/protocol/uplink), live status
  dot + session clock; a cyan scan-sweep runs under it
- **Output Canvas** — the grid backdrop where Delphi renders; shows the
  directive-pushed preview (code/document) or the rotating "AWAITING" glyph
- **COMMS (Chat Rail)** — how you talk to Delphi
- **Sidebar** — STATUS / MEMORY / TELEMETRY / TOKENS / TASK LOG telemetry rail
- **Footer** — keyboard legend + active model badge

Aesthetic: dark holographic war room. Cyan/green/amber/violet on near-black,
CRT scanlines + corner vignette, crosshair cursor, a cold-start boot sequence.
Everything glows slightly. Nothing is static.

> **Telemetry honesty.** Readouts are sourced from real state where one
> exists — UPLINK = real TTFT, STREAM = real tokens/sec, MEMORY/TOKENS =
> ≈4 chars/token estimates (the OpenAI-shaped stream carries no usage
> mid-flight), TASK LOG = real stream events. SIGNAL is an explicitly
> decorative ambient oscillator, **not** host CPU.

---

## Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | React 19 + Vite 8 | Fast dev, HMR, project standard |
| Styling | Tailwind v4 + CSS variables | v4 via `@tailwindcss/vite` — no config file, theme in CSS |
| Type | Orbitron (display) · Share Tech Mono (mono) · Rajdhani (sans) | mission-control type system |
| Canvas | CSS grid + scanlines (Phase 4: p5/Three for particle field) | OutputCanvas backdrop |
| Syntax | Prism.js | Code preview rendering inside OutputCanvas |
| Streaming | Native `fetch` + SSE parsing | Same shape as Delphi's `/v1/chat/completions` |
| State | Zustand | Chat history, Delphi mode, preview, events, telemetry |

`framer-motion` is still a dependency but the mission-control shell uses CSS
keyframes (in `index.css`) for its motion; reach for Framer only if a
transition outgrows CSS.

### Component map

```
App.jsx                       ← adaptive shell: compact / landscape / full grids
├── BootOverlay/              ← cold-start intro, self-unmounts
├── Header/                   ← logo, node/protocol/uplink, status dot, clock
├── OutputCanvas/             ← grid backdrop; preview (Prism) or AWAITING glyph
├── ChatRail/                 ← COMMS panel
│   ├── MessageBubble.jsx
│   └── InputBar.jsx          ← listens for `delphi:focus-input` (⌘K)
├── Sidebar/                  ← STATUS / MEMORY / TELEMETRY / TOKENS / TASK LOG
├── Footer/                   ← keyboard legend + model badge
└── CompactBar/               ← phone/tiny status strip

hooks/  useDelphiStream (SSE + directive parser, exports cancelDelphiStream),
        useViewport, useSessionClock
store/  chatStore (history/streaming), delphiStore (mode/preview/events/telemetry)
lib/    modes.js (MODE_COLOR, token estimates)
```

---

## Rules

- All secrets in `.env.local` (gitignored via `*.local`) — never hardcode the bearer token or backend URL. `.env.example` documents the variables.
- Components are single-responsibility — canvas logic stays in `EnvironmentCanvas/`, never leaks into App.
- Delphi mode is global state (`delphiStore`) — read from anywhere, set **only** from the stream parser.
- No inline styles for tokens-able values — use Tailwind classes or the CSS variables declared in `index.css` via `@theme`. Inline `style={{...}}` is OK only for dynamic values that map a runtime mode/color to CSS.
- Streaming responses go through `useDelphiStream` — never `fetch` directly from a component.
- Tailwind v4 has no `tailwind.config.js` — theme tokens live in `src/index.css` under `@theme { … }`.
- **Vite must dedupe React.** `vite.config.js` sets `resolve.dedupe: ['react', 'react-dom']` and `optimizeDeps.include: ['react', 'react-dom', 'react-dom/client', 'zustand']`. Without this, Vite pre-bundles a second React copy alongside zustand and "Invalid hook call" warnings appear. If a new React-consuming dep is added (e.g. swap zustand for jotai), add it to `optimizeDeps.include` too.

---

## Adaptive layout

Same component tree everywhere. `useViewport` (in `hooks/useViewport.js`)
buckets the window into one of five device tiers, and `App.jsx` picks one
of three layout modes:

| Tier      | Width × Height                | Layout mode | Visible panels                                                         |
|-----------|-------------------------------|-------------|------------------------------------------------------------------------|
| `tiny`    | w<480 OR h<320 (Pi HAT, etc.) | compact     | CompactHUD strip + ChatRail                                            |
| `phone`   | w<640, h≥320 (handset)        | compact     | CompactHUD strip + ChatRail                                            |
| `pi`      | 640≤w<960, h<540 (Pi 7", car) | landscape   | Header + OutputCanvas + ChatRail (no sidebar/footer telemetry rail)    |
| `laptop`  | 960≤w<1440                    | full        | Full shell: Header / (OutputCanvas+ChatRail ‖ Sidebar) / Footer        |
| `desktop` | w≥1440                        | full        | Same shell, more breathing room                                        |

### Compact mode (phone, tiny LCD)
```
┌─────────────────────────────┐
│ DELPHI │ ●IDLE │ no task    │  ← CompactHUD strip
├─────────────────────────────┤
│                             │
│        ChatRail             │
│  (fills remaining height)   │
│                             │
│  > message delphi…  [SEND]  │
└─────────────────────────────┘
```

### Landscape mode (Pi 7", car displays)
```
┌──────────────────────────────────────────┐
│ DELPHI  v0.1.0              ●IDLE        │
│ ┌──────────────────────────────────────┐ │
│ │  PREVIEW                             │ │
│ │  (drift node visible in canvas)      │ │
│ └──────────────────────────────────────┘ │
├──────────────────────────────────────────┤
│ ChatRail (40-row dock)                   │
│ > message delphi…              [ SEND ]  │
└──────────────────────────────────────────┘
```

### Full mode (laptop, desktop)
```
┌──────────────────────────────────────────────────────────────┐
│ DELPHI v0.2.0 │ NODE │ PROTOCOL │ UPLINK        ●IDLE  SESSION │  ← Header
├────────────────────────────────────────┬─────────────────────┤
│  OUTPUT CANVAS (grid + preview/glyph)   │  STATUS             │
│                                         │  MEMORY             │
│                                         │  TELEMETRY          │  ← Sidebar
├─────────────────────────────────────────┤  TOKENS             │
│  COMMS                                  │  TASK LOG           │
│  > message delphi…              [SEND]  │                     │
├────────────────────────────────────────┴─────────────────────┤
│ ⌘K FOCUS  ESC INTERRUPT  ⌘L CLEAR              ● model-badge  │  ← Footer
└──────────────────────────────────────────────────────────────┘
```

Full-mode outer grid is `grid-template-rows: 38px 1fr 42px` /
`grid-template-columns: 1fr 280px` with named areas (header / main / sidebar /
footer). `main` is itself `grid-rows-[1fr_190px]` — OutputCanvas over COMMS.
Landscape drops the sidebar and footer telemetry; compact is
`grid-rows-[auto_1fr]` (CompactBar on top, COMMS fills). A 1px
`--color-border-dim` gap between regions gives the seam-lit panel look.

### Adding a layout variant

1. Update `classify(w, h)` in `hooks/useViewport.js` if a new tier is
   needed.
2. Branch in `App.jsx` — keep the same components, switch the grid.
3. If a panel needs a smaller variant (e.g. `CompactHUD`), export it
   alongside the main component from the same file. Don't fork
   components; share state via stores.

Reduced-motion is honored via the global CSS rule in `index.css`. New
animations must respect `@media (prefers-reduced-motion: reduce)`.

---

## Backend contract (Delphi `/v1/chat/completions`)

The backend is the parent `Delphi/` FastAPI service. From the UI's perspective:

- **Endpoint:** `POST /v1/chat/completions` — bearer auth, OpenAI-compatible body
- **Streams:** SSE chunks of OpenAI `chat.completion.chunk` shape
- **Headers:** send `x-client-id: delphi-ui`, receive `X-Request-ID` back

Vite dev server proxies `/v1`, `/healthz`, `/readyz` to `http://localhost:8080`. Adjust in `vite.config.js`.

### Mode / preview / task protocol (in-band tokens)

Phase 4/5 introduces a thin protocol layered on top of the existing stream — the model emits inline tokens that the UI parses out before rendering:

```
[MODE:THINKING]            → set delphiStore.mode = "THINKING"
[MODE:BUILDING]            → set delphiStore.mode = "BUILDING"
[MODE:IDLE]                → set delphiStore.mode = "IDLE"

[PREVIEW:code:javascript]  → start preview push, language=javascript, render-mode=code
...content...
[/PREVIEW]                 → end preview push, commit to PreviewBox

[TASK: Analyzing dataset…] → set delphiStore.activeTask
```

The parser lives in `hooks/useDelphiStream.js`. Tokens are stripped from the chat-rendered text and routed to the appropriate store. **Zero backend changes required** — emission is encouraged via a soul-prompt addendum gated on `x-client-id: delphi-ui`.

---

## Phase status

- [x] **Phase 1 — Shell & Layout.** Mission-control four-region grid, color
  tokens, scanlines + vignette, boot sequence.
- [x] **Phase 2 — COMMS Integration.** Real SSE streaming against
  `/v1/chat/completions`, message bubbles (user / delphi), caret, Enter/Shift+Enter,
  auto-scroll, error surface. Inline-token parser strips `[MODE:…]` / `[TASK:…]` /
  `[PREVIEW:…]…[/PREVIEW]` and routes them into `delphiStore`.
- [x] **Phase 3 — Output Canvas.** Preview render (Prism code / document) vs.
  the rotating AWAITING glyph, driven by the preview directive.
- [x] **Phase 5 — HUD & Status System.** Live mode badge, active task, session
  clock, real TTFT / stream-rate telemetry, token estimates, real task-log feed.
- [x] **Phase 6 — Polish & Accessibility.** ⌘K focus, ⌘L clear, Esc interrupt;
  adaptive compact/landscape/full; reduced-motion honored.
- [ ] **Phase 4 — Living canvas.** Replace the static grid backdrop with a
  particle field / avatar node that reacts to `delphiStore.mode` (p5/Three).

---

## Dev

```bash
cd ui
npm install
npm run dev    # http://localhost:5173, proxies to Delphi on :8080
npm run build  # production bundle into ui/dist
```

Backend must be running at `http://localhost:8080` for chat to work. Start it from the parent dir:

```bash
cd ..
uv run python main.py
```
