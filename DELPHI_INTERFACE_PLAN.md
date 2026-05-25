# Delphi Interface — Build Plan

> JARVIS-style AI interface for Delphi. Backend is already handled. This plan covers the frontend UI/UX only.

---

## Vision

Delphi doesn't live in a chat box — Delphi **inhabits an environment**. The interface is split into three zones:

- **The Environment** — where Delphi exists, moves, and thinks (majority of the screen)
- **The Preview Box** — what Delphi is currently building or reading
- **The Chat Rail** — how you talk to Delphi

The aesthetic: dark holographic war room. Think JARVIS meets a quantum lab terminal. Everything glows slightly. Nothing is static.

---

## Layout

```
┌──────────────────────────────────────────────────────────────────┐
│                        ENVIRONMENT CANVAS                        │
│  (particle field, node graph, ambient motion — Delphi's space)   │
│                                                                  │
│  ┌──────────────────────┐         ┌──────────────────────────┐   │
│  │     PREVIEW BOX      │         │         HUD / STATUS     │   │
│  │  code / doc / image  │         │  mode · task · memory    │   │
│  │  Delphi is working   │         │  IDLE / THINKING / BUILD │   │
│  └──────────────────────┘         └──────────────────────────┘   │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│                        CHAT RAIL                                 │
│  [ Delphi: .......................... ]  [ You: .............. ]  │
│  [ ______________________________________________ ]  [ SEND ]    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Framework | React (Vite) | Fast dev, component-based, your existing stack |
| Styling | Tailwind CSS + CSS variables | Utility layout + custom theme tokens |
| Animation | Framer Motion | Environment motion, panel transitions |
| Canvas | p5.js or Three.js | Particle field, Delphi's ambient presence |
| Syntax Highlighting | Prism.js | Preview box code rendering |
| Streaming | EventSource / SSE | Real-time Delphi responses |
| State | Zustand or React Context | Chat history, Delphi mode, preview content |

---

## Color System

```css
--bg-deep:        #070b14;   /* canvas base */
--bg-panel:       #0d1424;   /* panels and rail */
--border-glow:    #00d4ff22; /* subtle panel edges */
--accent-cyan:    #00d4ff;   /* Delphi's primary color */
--accent-amber:   #ff9500;   /* alerts, active states */
--accent-violet:  #7c3aed;   /* secondary highlights */
--text-primary:   #e8f4fd;   /* main text */
--text-muted:     #4a6a8a;   /* timestamps, labels */
```

---

## Phase Breakdown

### Phase 1 — Shell & Layout
**Goal:** Full screen layout with correct zone proportions. No logic, just structure and style.

- [ ] Vite + React project scaffold (`uv`-managed if Python tooling needed alongside)
- [ ] CSS grid layout: environment takes ~70% height, chat rail docks to bottom
- [ ] Animated grid background (CSS only, no JS cost)
- [ ] Panel components: `<EnvironmentCanvas>`, `<PreviewBox>`, `<HUD>`, `<ChatRail>`
- [ ] Color tokens + font setup (display font for Delphi name/mode, mono for chat)
- [ ] Subtle scan-line overlay on the canvas area

**Deliverable:** Static shell that looks like a running system.

---

### Phase 2 — Chat Rail Integration
**Goal:** Wire the chat rail to Delphi's existing backend. Real conversation, streamed.

- [ ] `ChatRail` component with message history state
- [ ] Delphi vs. You message bubbles (distinct styling — Delphi glows slightly)
- [ ] SSE / streaming response handler
- [ ] Typewriter text render on Delphi's messages
- [ ] Input box: `Enter` to send, `Shift+Enter` for newline
- [ ] Timestamp and message metadata (subtle, muted)
- [ ] Auto-scroll to latest message

**Deliverable:** Fully functional chat with streaming.

---

### Phase 3 — Preview Box
**Goal:** Delphi can push content into the preview box as it works.

- [ ] `PreviewBox` component with three render modes:
  - `code` — syntax-highlighted block via Prism.js
  - `document` — rendered markdown or plain text
  - `media` — image display with metadata
- [ ] Animated "thinking" shimmer state when Delphi is mid-task
- [ ] Delphi explicitly signals what it's pushing (parse output for `[PREVIEW: ...]` tag or similar)
- [ ] Slide-in transition when new content arrives
- [ ] Copy / expand controls on the preview box

**Deliverable:** Preview box that Delphi can populate live.

---

### Phase 4 — Environment Canvas
**Goal:** The canvas feels like Delphi's actual space — alive, reactive, inhabited.

- [ ] Particle field background: slow-drifting nodes connected by thin lines
- [ ] Particles pulse on Delphi response (burst → settle)
- [ ] Delphi "avatar node" — a distinct glowing node that moves across the canvas
  - Idles near center when waiting
  - Drifts toward Preview Box when building
  - Pulses when speaking
- [ ] Canvas reacts to Delphi's mode:
  - `IDLE` → slow drift, low brightness
  - `THINKING` → faster motion, cyan flicker
  - `BUILDING` → directed movement toward preview, amber accent
  - `SEARCHING` → wide sweep motion
- [ ] Canvas is click-passthrough (doesn't block panels)

**Deliverable:** Environment that reflects Delphi's internal state visually.

---

### Phase 5 — HUD & Status System
**Goal:** At a glance, you know exactly what Delphi is doing.

- [ ] `HUD` panel with:
  - Mode badge: `IDLE` / `THINKING` / `BUILDING` / `SEARCHING`
  - Active task description (set by Delphi's output)
  - Memory indicator (session context usage, optional)
  - Uptime / session timer
- [ ] Mode transitions are animated (badge fades between states)
- [ ] Delphi sets its own mode via structured output tokens (parse from response stream)

**Deliverable:** Live status HUD that updates as Delphi works.

---

### Phase 6 — Polish & Accessibility
**Goal:** Ship-quality finish. Nothing feels rough.

- [ ] Keyboard shortcuts: `Cmd+K` to focus chat, `Esc` to collapse preview
- [ ] Collapsible chat rail (full environment view)
- [ ] Responsive breakpoints (works on 1080p and 1440p)
- [ ] Loading state on first connect
- [ ] Error state if backend is unreachable
- [ ] Optional: ambient audio toggle (subtle hum when Delphi is active)
- [ ] Font load optimization (no FOUT)
- [ ] Reduce-motion media query for accessibility

**Deliverable:** Production-ready, polished interface.

---

## File Structure

```
delphi-ui/
├── src/
│   ├── components/
│   │   ├── EnvironmentCanvas/
│   │   │   ├── index.jsx
│   │   │   ├── particleSystem.js
│   │   │   └── delphiNode.js
│   │   ├── PreviewBox/
│   │   │   ├── index.jsx
│   │   │   ├── CodePreview.jsx
│   │   │   └── DocumentPreview.jsx
│   │   ├── ChatRail/
│   │   │   ├── index.jsx
│   │   │   ├── MessageBubble.jsx
│   │   │   └── InputBar.jsx
│   │   └── HUD/
│   │       └── index.jsx
│   ├── store/
│   │   ├── chatStore.js      # message history, streaming state
│   │   └── delphiStore.js    # mode, active task, preview content
│   ├── hooks/
│   │   ├── useDelphiStream.js
│   │   └── useDelphiMode.js
│   ├── styles/
│   │   └── tokens.css        # all CSS variables
│   ├── App.jsx
│   └── main.jsx
├── public/
├── CLAUDE.md
├── .env
└── vite.config.js
```

---

## CLAUDE.md Conventions (for this project)

```markdown
# Delphi UI — CLAUDE.md

## Stack
- React 18 + Vite
- Tailwind CSS (utility), CSS variables (theme)
- Framer Motion (animation)
- p5.js (canvas)
- Zustand (state)

## Rules
- All secrets in .env — never hardcode backend URL
- Components are single-responsibility — canvas logic stays in EnvironmentCanvas/
- Delphi mode is global state (delphiStore) — read from anywhere, set only from stream parser
- No inline styles — use Tailwind or CSS variables
- Streaming responses go through useDelphiStream hook, never directly in components
```

---

## Delphi Communication Protocol (Frontend Expectations)

Since the backend is already built, define the contract the frontend expects:

```
Standard message response:
  Plain text streamed via SSE

Mode signal (parsed from stream):
  [MODE:THINKING]
  [MODE:BUILDING]
  [MODE:IDLE]

Preview push (parsed from stream):
  [PREVIEW:code:javascript]
  ...code content...
  [/PREVIEW]

Task label:
  [TASK: Analyzing KPMP dataset...]
```

The stream parser in `useDelphiStream.js` strips these tokens before rendering to chat and routes them to the appropriate store.

---

## Build Order Summary

| Phase | Focus | Est. Time |
|---|---|---|
| 1 | Shell + Layout | 1–2 days |
| 2 | Chat + Streaming | 1–2 days |
| 3 | Preview Box | 1 day |
| 4 | Environment Canvas | 2–3 days |
| 5 | HUD + Status | 1 day |
| 6 | Polish | 1–2 days |

**Total: ~7–10 days** for a production-quality v1.

---

*Last updated: May 2026 | Project: Delphi UI | Owner: Tali Mosley / BliqByte*
