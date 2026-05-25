# Delphi UI — CLAUDE.md

> JARVIS-style interface for Delphi. Lives at `ui/` inside the Delphi project.
> The Delphi FastAPI service (parent dir) is the backend.

---

## Vision

Delphi doesn't live in a chat box — Delphi **inhabits an environment**. Three zones:

- **Environment** — canvas where Delphi exists, moves, thinks (majority of screen)
- **Preview Box** — what Delphi is currently building or reading
- **Chat Rail** — how you talk to Delphi

Aesthetic: dark holographic war room. Cyan/amber/violet on near-black. Everything glows slightly. Nothing is static.

---

## Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | React 19 + Vite 7 | Fast dev, HMR, project standard |
| Styling | Tailwind v4 + CSS variables | v4 via `@tailwindcss/vite` — no config file, theme in CSS |
| Animation | Framer Motion | Panel transitions, mode badges |
| Canvas | (planned) p5.js or Three.js | Phase 4 particle field + avatar node |
| Syntax | Prism.js | Code preview rendering |
| Streaming | Native `fetch` + SSE parsing | Same shape as Delphi's `/v1/chat/completions` |
| State | Zustand | Chat history, Delphi mode, preview content |

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
| `pi`      | 640≤w<960, h<540 (Pi 7", car) | landscape   | TitleBar + PreviewBox + ChatRail; mode pill in canvas corner           |
| `laptop`  | 960≤w<1440                    | full        | Three-zone: TitleBar / PreviewBox on the left, HUD on the right + ChatRail |
| `desktop` | w≥1440                        | full        | Same three-zone, larger paddings and font sizes                        |

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
┌─────────────────────────────────────────────────────────┐
│  ENVIRONMENT (canvas + grid)                            │
│  ┌─────────────────────┐  ┌────────────────────────┐    │
│  │  TitleBar           │  │     HUD                │    │
│  ├─────────────────────┤  │  mode · task · model   │    │
│  │  PreviewBox         │  │  memory · session      │    │
│  │                     │  │                        │    │
│  └─────────────────────┘  └────────────────────────┘    │
├─────────────────────────────────────────────────────────┤
│  ChatRail                                               │
│  > message delphi…                              [SEND]  │
└─────────────────────────────────────────────────────────┘
```

App-level outer grid is `grid-rows-[1fr_auto]` in full/landscape, and
`grid-rows-[auto_1fr]` in compact (HUD on top, chat fills). Env zone uses
`grid-cols-[1.5fr_1fr]` in full mode and `grid-cols-1` (stacked) in
landscape.

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

- [x] **Phase 1 — Shell & Layout.** Static four-panel scaffold, color tokens, scan-lines.
- [x] **Phase 2 — Chat Rail Integration.** Real SSE streaming against `/v1/chat/completions`, message bubbles (user / delphi), typewriter caret, Enter/Shift+Enter, auto-scroll, error surface. Inline-token parser strips `[MODE:…]` / `[TASK:…]` / `[PREVIEW:…]…[/PREVIEW]` from chat text and routes them into `delphiStore` so the HUD and PreviewBox react live.
- [ ] **Phase 3 — Preview Box.** Three render modes + shimmer state + slide-in (basic Prism rendering is already wired; this phase adds the shimmer + transitions).
- [ ] **Phase 4 — Environment Canvas.** Particle field + avatar node reacting to mode.
- [ ] **Phase 5 — HUD & Status System.** Live mode badge, active task, session timer.
- [ ] **Phase 6 — Polish & Accessibility.** Keyboard shortcuts, responsive, reduced-motion.

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
