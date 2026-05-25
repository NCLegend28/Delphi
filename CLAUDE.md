# Delphi — CLAUDE.md

> **Project identity.** Delphi is Tali's private, self-hosted LLM gateway:
> an OpenAI-compatible HTTP endpoint backed by a roster of local models on a
> Proxmox GPU VM. A tiny classifier picks the right model per request, an
> Obsidian vault becomes the memory substrate, and structured logs feed
> operational telemetry. Same soul, different bodies.

> **Working principle.** Carpe Diem. As you climb, you must lift. Code is a
> chain — every commit is a link. Build the smallest thing that works
> end-to-end, then make it sharper.

---

## What this service is

A FastAPI server on the Proxmox VM that:

1. Accepts OpenAI-compatible `/v1/chat/completions` requests with bearer auth
2. Classifies the task with a tiny model (Phi-3.5-mini) — code, reason, chat,
   deep-code, deep-reason, vault-query
3. Routes to the appropriate roster model on the local Ollama server
4. Injects the shared system prompt (the "soul")
5. Writes a structured Obsidian note for the exchange, with frontmatter and
   `[[wikilinks]]` to projects and entities
6. Emits a JSONL log line with latency, tokens, model, classification, and
   vault-write outcome

Clients (AgentRig, Open WebUI, the iOS Enchanted app, `llm` CLI, custom Python)
all hit the same endpoint, all benefit from the same routing and memory layer.

---

## Architecture

```
client (any OpenAI-compatible) 
   ↓  HTTPS + Bearer
Tailscale  →  Caddy (TLS + auth)
                ↓
           Delphi FastAPI (this service)
              │
              ├── classifier:  Ollama → phi-3.5-mini → task_type
              ├── router:      task_type → model name + system prompt
              ├── proxy:       Ollama /v1/chat/completions (streaming)
              ├── memory:      Obsidian vault writer (markdown + frontmatter)
              └── logger:      structured JSONL → /var/log/delphi/
```

**Why these boundaries.** Classification, routing, memory, and logging are
independent concerns. Each can be disabled with a config flag (`memory.enabled
= false` for benchmark runs; `classify.enabled = false` when the client
specifies the model directly). The proxy layer is dumb and stable; everything
clever sits above or beside it.

**Variant note (per agentic-saas conventions).** This is the *webhook-only*
variant — every request is stateless from the service's POV. Conversation
history lives client-side, except for the durable memory layer (Obsidian),
which is append-only and read on demand.

---

## Project layout

```
Delphi/
├── CLAUDE.md                    ← this file
├── README.md                    ← setup, deploy, ops runbook
├── pyproject.toml               ← uv-managed deps
├── .env.example                 ← every secret documented
├── .gitignore
│
├── config.py                    ← typed dataclass config (Pydantic Settings)
├── main.py                      ← FastAPI app entrypoint
│
├── routing/
│   ├── __init__.py
│   ├── classifier.py            ← tiny-model task classification
│   ├── roster.py                ← task_type → model + params mapping
│   └── soul.py                  ← shared system prompt (the "soul")
│
├── proxy/
│   ├── __init__.py
│   └── ollama_client.py         ← async httpx wrapper, streaming
│
├── memory/
│   ├── __init__.py
│   ├── vault.py                 ← Obsidian writer: notes + frontmatter
│   ├── entities.py              ← entity extraction + [[wikilink]] resolution
│   └── templates.py             ← Jinja2 templates for note types
│
├── telemetry/
│   ├── __init__.py
│   ├── logger.py                ← structured JSONL logger
│   └── metrics.py               ← Prometheus exposition (optional)
│
├── worker/                      ← out-of-process persistence (arq + Redis)
│   ├── __init__.py
│   ├── queue.py                 ← job name + pool factory (shared producer/consumer)
│   ├── serde.py                 ← ConversationRecord ⇄ JSON for the queue
│   └── main.py                  ← arq WorkerSettings; runs memory.persist.run_persist
│
├── auth/
│   ├── __init__.py
│   └── bearer.py                ← FastAPI dependency for bearer auth
│
├── benchmarks/                  ← ops CLI: rank models per task from leaderboards
│   ├── sources/                 ← one adapter per leaderboard (aider, livebench, …)
│   ├── map.py                   ← task_type → weighted (source, category) blend
│   ├── rank.py                  ← composite scoring + sort
│   └── cli.py                   ← `uv run python -m benchmarks rank --task code`
│
├── tests/
│   ├── test_classifier.py
│   ├── test_roster.py
│   ├── test_vault.py
│   └── test_e2e.py
│
├── Dockerfile                   ← uv multi-stage; one image, gateway + worker
├── docker-compose.yml           ← caddy + delphi + delphi-worker + redis
├── .env.docker.example          ← compose-stack env (Ollama Cloud, token)
│
└── deploy/
    ├── systemd.service          ← delphi.service unit file (bare-metal path)
    ├── Caddyfile                ← TLS + UI static + API proxy (injects bearer)
    ├── Dockerfile.caddy         ← builds UI bundle, serves it behind Caddy
    └── bootstrap.sh             ← one-shot VM setup script
```

---

## The roster (current — edit `routing/roster.py` to change)

| task_type     | model                              | VRAM | notes                          |
|---------------|------------------------------------|------|--------------------------------|
| `chat`        | `phi-4:14b`                        | 9GB  | default; general conversation  |
| `code`        | `qwen2.5-coder:14b`                | 9GB  | every coding task              |
| `reason`      | `deepseek-r1-distill-qwen:14b`     | 9GB  | math, debugging logic, proofs  |
| `multilingual`| `gemma3:12b`                       | 8GB  | EN↔ES code-switching, prose    |
| `deep_code`   | `qwen2.5-coder:32b` (CPU+GPU)      | 16GB+24GB CPU | slow but capable          |
| `deep_reason` | `deepseek-r1-distill-qwen:32b` (CPU+GPU) | 16GB+24GB CPU | hard reasoning      |
| `classify`    | `phi-3.5-mini:3.8b`                | 3GB  | always loaded (router itself)  |

`OLLAMA_MAX_LOADED_MODELS=3` means up to three of the above are warm at once.
The classifier stays pinned; the other two slots rotate based on recency.

---

## The Soul (shared system prompt)

Stored in `routing/soul.py` as a constant. Every routed request gets this
prepended *unless the client already sent a system message*. The Soul defines:

- Identity: "you are Tali's local assistant"
- Conventions: Python with uv, typed dataclasses, async-first
- Tone: direct, technical, uses analogies to teach
- Mentorship axis: "as you climb, you must lift" — explanations should make
  the next builder smarter, not just solve the immediate problem
- Memory awareness: "your responses are written to an Obsidian vault — when
  introducing a concept, project, or library, surface it cleanly so it can
  become a future link"

When the model is `code` or `deep_code`, an additional block is appended with
Tali's Python conventions (uv, Pydantic, ruff, pytest, no `print` in libs).

---

## Obsidian memory model

The vault path is `OBSIDIAN_VAULT_PATH` in `.env`. The service is
write-primary — Obsidian is the main reader — but the **vault-query agent**
(see below) now also *reads* notes on demand to ground `vault_query` answers.
Writes land in this structure:

```
<vault>/
├── conversations/
│   └── YYYY-MM-DD/
│       └── YYYY-MM-DD_HH-MM_<slug>.md   ← per exchange
├── projects/                            ← human-curated; service reads names
│   ├── AgentRig.md
│   ├── MSA.md
│   └── ...
├── entities/                            ← auto-created on first mention
│   └── <entity>.md
└── daily/
    └── YYYY-MM-DD.md                    ← daily rollup; service appends bullets
```

**Per-conversation note** has YAML frontmatter:

```yaml
---
date: 2026-05-10T14:32:18-05:00
task_type: code
models: [qwen2.5-coder:14b]
classifier_confidence: 0.92
latency_ms: 1840
input_tokens: 412
output_tokens: 1103
project: "[[AgentRig]]"
entities: ["[[cosine-similarity-routing]]", "[[Pydantic]]"]
tags: [routing, debugging]
client_id: agentrig-m4
---
```

Body is the user message and the assistant response, separated by `## User`
and `## Assistant` headers. Inline mentions of known entities become
`[[wikilinks]]` automatically via `memory/entities.py`.

**Daily rollup** is one bullet per conversation, appended to
`daily/YYYY-MM-DD.md`. Lets you scroll a day at a glance.

**Project resolution.** The classifier returns a `project` hint based on
filename mentions, library names, or explicit `project:` in the user message.
If no match in `projects/*.md`, project is left empty (don't auto-create
project notes — those are human-curated).

**Entity creation.** When the assistant response mentions a noun-phrase the
service hasn't seen before *and* it appears in 2+ different conversations,
auto-create `entities/<slug>.md` with a one-line stub. This is what makes the
graph view light up over time.

---

## Logging

Structured JSONL to `/var/log/delphi/requests.jsonl`. One line per request:

```json
{
  "ts": "2026-05-10T14:32:18.123-05:00",
  "request_id": "req_a3f2...",
  "client_id": "agentrig-m4",
  "task_type": "code",
  "classifier_confidence": 0.92,
  "model": "qwen2.5-coder:14b",
  "latency_ms": 1840,
  "ttft_ms": 220,
  "input_tokens": 412,
  "output_tokens": 1103,
  "vault_write": {"ok": true, "path": "conversations/2026-05-10/..."},
  "error": null
}
```

Rotation via logrotate, weekly, keep 12 weeks. Grafana can scrape this later
with Promtail → Loki, but day-one a `jq` pipeline is enough.

---

## Configuration (`config.py`)

Pydantic Settings, loaded from `.env`. Required vars:

| Variable                 | Purpose                                          |
|--------------------------|--------------------------------------------------|
| `DELPHI_BEARER_TOKEN`    | Auth token clients must present                  |
| `OLLAMA_BASE_URL`        | `http://localhost:11434` local, `https://ollama.com` cloud |
| `OBSIDIAN_VAULT_PATH`    | Absolute path to vault on the VM                 |
| `LOG_DIR`                | `/var/log/delphi`                                |
| `TIMEZONE`               | `America/Chicago` (Tali is in Dallas)            |

Optional:

| Variable                       | Default              | Purpose                          |
|--------------------------------|----------------------|----------------------------------|
| `OLLAMA_API_KEY`               | `""`                 | Bearer for Ollama Cloud; empty for local |
| `CLASSIFY_ENABLED`             | `true`               | If false, use `model` from req   |
| `MEMORY_ENABLED`               | `true`               | If false, skip vault writes      |
| `WORKER_ENABLED`               | `false`              | Offload persist to the arq worker; else inline |
| `REDIS_URL`                    | `redis://localhost:6379` | Persist-queue broker         |
| `WORKER_METRICS_PORT`          | `9100`               | Worker's Prometheus port (normal-path metrics) |
| `VAULT_AGENT_ENABLED`          | `true`               | Tool-calling vault search on `vault_query` requests |
| `VAULT_AGENT_MAX_STEPS`        | `5`                  | Max tool rounds before the agent must answer |
| `DELPHI_MODEL_CHAT`            | `phi4:14b`           | Model for `chat` task            |
| `DELPHI_MODEL_CODE`            | `qwen2.5-coder:14b`  | Model for `code` task            |
| `DELPHI_MODEL_REASON`          | `deepseek-r1:14b`    | Model for `reason` task          |
| `DELPHI_MODEL_MULTILINGUAL`    | `gemma3:12b`         | Model for `multilingual` task    |
| `DELPHI_MODEL_DEEP_CODE`       | `qwen2.5-coder:32b`  | Model for `deep_code` task       |
| `DELPHI_MODEL_DEEP_REASON`     | `deepseek-r1:32b`    | Model for `deep_reason` task     |
| `DELPHI_MODEL_VAULT_QUERY`     | `phi4:14b`           | Model for `vault_query` task     |
| `DELPHI_MODEL_CLASSIFIER`      | `phi3.5:3.8b`        | Tiny classifier model            |
| `ENTITY_CREATE_THRESHOLD`      | `2`                  | Mentions before auto-creating    |

Per-task sampling options (temperature, etc.) stay in code at
`routing/roster.py:TASK_METADATA`; only the model tag is env-driven. To
evolve a category: change the env var, `ollama pull <new>`, restart, then
`ollama rm <old>` once you're satisfied.

Secrets layering: `.env` for local dev → Doppler in prod. Same pattern as
every other project in `~/projects/`.

---

## Model evolution (`benchmarks/`)

Because every roster slot is now env-driven (`DELPHI_MODEL_*`), the
question "which model should serve `code` next month?" is an evidence
question, not a vibes question. The `benchmarks/` package crawls public
leaderboards, normalizes them onto a common model-name key, and ranks
the available local models per Delphi task type.

```bash
uv run python -m benchmarks tasks                     # show task → blend
uv run python -m benchmarks fetch                     # refresh caches
uv run python -m benchmarks rank --task code --ollama-only
```

Three layers, each replaceable:

1. **`sources/`** — one adapter per leaderboard. Today: Aider polyglot
   (coding), LiveBench (reasoning/coding/math/language/IF/data-analysis),
   Ollama library (availability filter). Add new sources by copying
   `aider.py` and registering in `cli._build_sources`.
2. **`map.py`** — the opinionated blend. For each task type, declares
   which `(source, category)` pairs predict real-world quality and how
   to weight them. Tune as evidence accumulates.
3. **`rank.py`** — joins on the canonical model key, applies weights,
   drops any model missing a required component (no zero-imputation).

Cached payloads live in `~/.cache/delphi-benchmarks` with a 24h TTL.
Source URLs are documented per-module with a "verify on update" note —
leaderboards do rotate file paths between releases.

When a ranking surfaces a clear winner, update the matching
`DELPHI_MODEL_*` in `.env`, `ollama pull` the new tag, restart, then
`ollama rm` the old tag once you're satisfied. No code change required.

## Key conventions

**Async throughout.** Every I/O — Ollama calls, file writes, log appends —
is async. No blocking calls on the request path. Vault writes happen in
`asyncio.create_task()` so the response streams back to the client without
waiting for disk.

**Streaming-first.** The `/v1/chat/completions` endpoint streams SSE chunks
back to the client. The vault writer buffers chunks and writes the complete
note after `[DONE]`. If the client disconnects mid-stream, the buffered
content still gets written (with `truncated: true` in frontmatter).

**Fail open on memory.** If the vault write fails (disk full, permission
issue, vault unmounted), log the error and return the response to the client
anyway. Memory is best-effort; the API contract is sacred.

**Fail closed on auth.** No bearer token, no token match → 401, no exception
detail leaked. Constant-time comparison via `secrets.compare_digest`.

**Classifier is advisory, not authoritative.** If the request body specifies
`model` explicitly, that wins. Classification only fires when the client sends
`task_type: "auto"` or omits both `model` and `task_type`. AgentRig will
always specify model; ad-hoc curl calls and Open WebUI will use auto.

**Project notes are read-only to the service.** The service reads
`projects/*.md` filenames to resolve frontmatter links but never writes to
them. Human-curated. The service writes to `conversations/`, `entities/`,
and `daily/`.

**One soul, many bodies.** The system prompt in `routing/soul.py` is the
*only* persona definition. Per-task additions (e.g., the coding conventions
block for `code`/`deep_code`) are appended, never replacing. If you find
yourself wanting a different tone for a different task, that's a smell —
add a context note in the soul instead.

---

## Tech stack

- **Python 3.12+** via `uv` (never plain `pip`, never `venv` directly)
- **FastAPI** + **uvicorn** for the HTTP layer
- **httpx** (async) for Ollama calls — never `requests`
- **Pydantic v2** for settings and request/response models
- **Jinja2** for Obsidian note templates
- **structlog** for the JSONL logger
- **pytest** + **pytest-asyncio** for tests
- **ruff** for lint + format (no black, no isort)
- **mypy --strict** on `routing/`, `memory/`, `config.py`

Deps installed exclusively via `uv add`. Lockfile committed.

---

## Boot sequence (`main.py`)

1. Load `.env` → build `Config` (Pydantic Settings) → log redacted summary
2. Probe Ollama `/api/tags` — fail fast if Ollama isn't reachable
3. Verify roster: every model in `roster.py` must appear in Ollama's tag list
   (warn but don't crash if a non-default model is missing — pull-on-demand)
4. Ensure `OBSIDIAN_VAULT_PATH` exists and is writable
5. Initialize the structured logger
6. Register FastAPI routes, start uvicorn on `0.0.0.0:8080`

---

## Endpoints

| Method | Path                          | Purpose                                |
|--------|-------------------------------|----------------------------------------|
| POST   | `/v1/chat/completions`        | Main entrypoint (OpenAI-compatible)    |
| GET    | `/v1/models`                  | List roster — clients use to discover  |
| GET    | `/healthz`                    | Liveness — no auth                     |
| GET    | `/readyz`                     | Readiness — auth, probes Ollama        |
| GET    | `/metrics`                    | Prometheus exposition (if enabled)     |
| POST   | `/admin/reload-roster`        | Hot-reload `roster.py` — auth          |

The `task_type` field is a non-standard extension to the OpenAI request
schema. Clients that don't know about it just don't send it. Routing falls
back to classification or the `DEFAULT_MODEL`.

---

## UI (`ui/` — delphi-ui)

Delphi ships with a first-party interface. It lives at `ui/` inside this
repo and talks to the FastAPI service as just another OpenAI-compatible
client. Aesthetic: dark holographic war room — a three-zone environment
(canvas + preview + chat rail) rather than a chat box. See `ui/CLAUDE.md`
for stack, layout, and phase plan.

**Multi-device, adaptive shell.** The same UI runs everywhere Tali wants
Delphi to surface:

| Device class      | Typical viewport       | Layout mode                                 |
|-------------------|------------------------|---------------------------------------------|
| Phone             | 360–430 × 800+         | chat-first, preview as full-screen overlay  |
| Small LCD / Pi HAT | 320 × 240 – 800 × 480 | compact: chat rail + minimal HUD strip      |
| Raspberry Pi 7"   | 800 × 480              | two-zone: chat + collapsible preview        |
| Laptop            | 1280 × 800 – 1440 × 900| full three-zone layout                      |
| Desktop / wall    | 1920+ × 1080+          | full layout, larger canvas, more breathing  |

The layout uses CSS container queries / responsive grid — same component
tree everywhere, no separate mobile build. Reduced-motion is honored.

**Client identification.** The UI sends `x-client-id: delphi-ui` on every
request. The service uses this in two places:

1. `routing/soul.py:soul_for(task_type, client_id=…)` appends a UI protocol
   block (see `UI_PROTOCOL_APPENDIX`) teaching the model the inline
   directive grammar — `[MODE:…]`, `[TASK:…]`, `[PREVIEW:…]…[/PREVIEW]`.
   The UI parses these out of the stream and routes them to mode badge,
   active-task label, and preview box.
2. Telemetry (`request.client_id`) so UI requests are filterable in logs.

Directives are opt-in. The model may emit none — plain text still
renders fine; the UI just stays in `IDLE` mode with an empty preview.

**Dev loop.** `cd ui && npm run dev` runs Vite at `:5173`, proxying
`/v1`, `/healthz`, `/readyz` to `localhost:8080`. The backend must be
running locally for chat to work end-to-end.

---

## Human-in-the-loop hooks

This service has no real-world side effects beyond writing to the vault and
log. No `approval_required` flag needed. **But:** when a future tool-calling
upgrade lands (function calling proxied through to the local models), any
tool that triggers real-world action gets the AgentRig `approval_required`
pattern.

---

## Testing strategy

- **`test_classifier.py`** — 30 hand-labeled prompts, assert classification
  matches with ≥80% accuracy. Run against real Ollama in CI (a small
  containerized Ollama with phi-3.5-mini).
- **`test_roster.py`** — pure unit, no network. Asserts every task_type maps
  to a model, soul is non-empty, additions don't replace base soul.
- **`test_vault.py`** — uses `tmp_path` to write notes; asserts frontmatter
  parses, wikilinks resolve, daily rollup appends correctly.
- **`test_e2e.py`** — spins up the FastAPI test client, mocks Ollama with
  `respx`, runs three full request scenarios (auto-classify, explicit model,
  streaming).

`uv run pytest` must pass before any commit. CI runs lint + types + tests.

---

## Deployment

Single systemd service on the Proxmox VM. Caddy in front for TLS + bearer
auth at the edge (defense in depth — the service also checks the token).
Tailscale on the VM for private network access.

```bash
# Pull weights (one-time)
ollama pull phi-3.5-mini:3.8b
ollama pull phi-4:14b
ollama pull qwen2.5-coder:14b
ollama pull deepseek-r1-distill-qwen:14b
ollama pull gemma3:12b
# 32B models: pull when first needed

# Install service
sudo cp deploy/delphi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now delphi

# Caddy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

`deploy/bootstrap.sh` is idempotent — re-running it on a fresh VM produces
a working install. Read it before running it.

---

## Operational runbook

| Symptom                              | First thing to check                              |
|--------------------------------------|---------------------------------------------------|
| Client gets 401                      | Bearer token mismatch — Doppler vs `.env`         |
| Client gets 502                      | Ollama not running: `systemctl status ollama`     |
| Classifier always returns `chat`     | phi-3.5-mini not loaded: `ollama ps`              |
| Vault notes not appearing            | Permissions: `ls -la $OBSIDIAN_VAULT_PATH`        |
| Slow first response after idle       | Model unloaded; bump `OLLAMA_KEEP_ALIVE`          |
| Out of VRAM mid-request              | Too many loaded models; lower `MAX_LOADED_MODELS` |
| Daily rollup duplicated entries      | Service restarted mid-write; check `error` in log |

---

## What this service is NOT

- **Not a Claude failover destination by itself.** AgentRig's failover logic
  treats this as one of several local options — same as the M4 MLX path.
- **Not a vector database.** Obsidian is markdown + graph. If semantic search
  over the vault is needed later, add a separate service that reads the vault
  and exposes a `/search` endpoint. Don't bloat Delphi.
- **Not multi-tenant.** It's Tali's box. If a collaborator gets access via
  Tailscale share, they get the same models and the same vault. If isolation
  is ever needed, fork the service per tenant — don't add tenant logic here.

---

## Decision log

Append to this section whenever an architectural decision is made. Format:
date, decision, rationale.

- **2026-05-10** — Phi-3.5-mini chosen as classifier over Qwen2.5-3B. Rationale:
  Microsoft tuned Phi specifically for short instruction-following tasks; the
  3-class to 7-class classification we need is its sweet spot. Revisit if
  accuracy on `test_classifier.py` drops below 80%.
- **2026-05-10** — Obsidian vault as memory substrate, not SQLite or vector
  DB. Rationale: the graph view is the visualization goal. Markdown is durable,
  greppable, syncable, and Tali already lives in Obsidian. Vector search can
  be added as a sidecar later without disturbing this service.
- **2026-05-10** — Service writes only to `conversations/`, `entities/`,
  `daily/`. Project notes stay human-curated. Rationale: auto-generating
  project notes would create noise; let Tali shape the project taxonomy.
- **2026-05-10** — Streaming-first endpoint. Rationale: matches OpenAI API
  parity; long 32B responses need TTFT feedback or the client looks frozen.
- **2026-05-17** — First-party UI (`ui/`) added; "not a chat UI" line
  removed from `What this service is NOT`. Rationale: Open WebUI is a fine
  generic client but Delphi has earned a dedicated surface — a JARVIS-style
  three-zone environment (canvas + preview + chat rail) that adapts from
  small LCDs and Raspberry Pi screens up through desktops. The UI is just
  another OpenAI-compatible client (`x-client-id: delphi-ui`); the service
  remains backend-only. No multi-tenancy is introduced.
- **2026-05-17** — `soul_for(task_type, *, client_id=…)` gains a UI
  protocol appendix gated on `client_id == "delphi-ui"`. Rationale:
  models need to learn the `[MODE:…]` / `[TASK:…]` / `[PREVIEW:…]`
  directive grammar only when an interface is listening. Other clients
  (AgentRig, raw curl) get the unmodified soul.
- **2026-05-24** — Inference can run on **Ollama Cloud**, not just a local
  GPU box. `OllamaClient` gains an optional `api_key` → `Authorization: Bearer`
  header; `OLLAMA_BASE_URL=https://ollama.com` + `OLLAMA_API_KEY` selects it.
  Rationale: the target deploy is an 8 GB CPU VPS that physically cannot load
  the 14B local roster (a 9 GB model needs >8 GB RAM, no GPU). Same wire
  protocol; only the bearer header and model tags change. Local-GPU operation
  is unchanged (empty key, localhost URL). Caveat: cloud hosts large models
  under different tags and has no tiny classifier model — the classifier
  becomes a cloud call (use a smaller cloud tag, or set `CLASSIFY_ENABLED=false`
  and have clients send `task_type`).
- **2026-05-24** — Persistence moves **out of process to a worker** over a
  Redis-backed arq queue (`worker/`). The gateway streams the response, then
  enqueues a serialized `ConversationRecord`; the worker runs the same
  `run_persist` pipeline (entity extraction, vault write, JSONL log, metrics).
  Rationale: keep disk I/O and entity-index scans off the request path on a
  small box. **Fail-open:** when `WORKER_ENABLED=false` or Redis is
  unreachable, the gateway runs `run_persist` inline — memory is best-effort,
  the API contract is sacred. The `_persist` helpers moved from `api/chat.py`
  to `memory/persist.py` so gateway and worker share one implementation.
  Metrics stay symmetric: worker owns the normal path (`:9100/metrics`),
  gateway owns the inline-fallback path (`/metrics`); Prometheus scrapes both.
- **2026-05-24** — **Docker full-stack deploy** added: `Dockerfile` (uv
  multi-stage, one image for gateway + worker), `deploy/Dockerfile.caddy`
  (builds the UI, serves it + reverse-proxies the API), `docker-compose.yml`
  (caddy + delphi + delphi-worker + redis, with mem limits for an 8 GB box),
  `.env.docker.example`. Caddy injects the bearer token onto proxied `/v1`
  calls server-side, so the secret never enters the browser bundle or the
  image (single-tenant, Tailscale-gated trust model).
- **2026-05-25** — **Vault-query agent.** `vault_query` was a recognized task
  type that routed to a model but never consulted the vault — answers were
  ungrounded. It now runs a bounded tool-calling loop: the model is given
  read-only `search_vault` / `read_note` tools (`memory/vault_reader.py`,
  `routing/vault_agent.py`) and drives search→read→answer over the vault, the
  way a person (or Claude) would. Chosen over keyword-RAG-injection and an
  embedding sidecar because it matches how the vault is actually explored;
  retrieval stays keyword-based under the hood (swap for embeddings behind the
  same `VaultReader` interface later). Bounded by `VAULT_AGENT_MAX_STEPS` so a
  model can't loop or run up cloud cost; the loop runs non-streaming, then the
  final answer is framed as SSE for streaming clients. This is the first time
  the service *reads* note content (was write-primary). `read_note` is
  path-confined to the vault — traversal/symlink escapes are refused. Requires
  a tool-capable `DELPHI_MODEL_VAULT_QUERY`; if the model ignores the tools the
  answer flows through ungrounded. Still **not** a vector DB — the embedding
  sidecar future hook remains the upgrade path for semantic recall.
- **2026-05-25** — **UI reskinned to "Mission Control."** The three-zone JARVIS
  shell (`EnvironmentCanvas` + `PreviewBox` + `HUD`) was replaced by a
  four-region mission-control console (Header / OutputCanvas / COMMS / Sidebar +
  Footer), ported from a `delphi_mission_control.html` design mockup into the
  React app. Rationale: the mockup is a denser, more legible war-room surface
  (live status dot, telemetry rail, task-log feed, boot sequence) than the
  previous floating-panel layout. **What was preserved:** the entire backend
  contract — `useDelphiStream`'s SSE + `[MODE]/[TASK]/[PREVIEW]` directive
  parser, `chatStore`/`delphiStore`, bearer auth, `x-client-id: delphi-ui`, and
  the adaptive viewport tiers. **What was discarded:** the mockup's
  direct-to-`api.anthropic.com` fetch and its simulated character-by-character
  streaming — the UI remains a pure OpenAI-compatible client of *this* service.
  Telemetry is real where it can be (TTFT, stream t/s, token estimates, event
  feed); the SIGNAL bar is explicitly decorative. No backend or multi-tenancy
  change. See `ui/CLAUDE.md` for the component map.

---

## First milestone: end-to-end smoke test

The success condition for "Delphi is real":

1. `curl -H "Authorization: Bearer $TOKEN" \
       -d '{"messages":[{"role":"user","content":"refactor this Python: ..."}], "task_type":"auto"}' \
       https://delphi.your-tailnet.ts.net/v1/chat/completions`
   returns a streamed code-focused response
2. The classifier picked `code` (verifiable in the JSONL log)
3. The model used was `qwen2.5-coder:14b`
4. A new note appeared at `conversations/2026-05-10/2026-05-10_HH-MM_*.md`
5. The Obsidian graph view shows the new note linked to entities and any
   matched project

When this works end-to-end, ship to AgentRig. Iterate from there.

---

## Future hooks (don't build yet, but the architecture should not preclude)

- **Embedding sidecar** for semantic vault search → exposes `/search`,
  Delphi queries it before answering when the user asks "do I have notes
  on X?"
- **Function calling proxy** — translate OpenAI tool-call schema into model-
  specific formats (Qwen vs DeepSeek differ slightly)
- **Per-client roster overrides** — `client_id` → custom roster (AgentRig
  gets different defaults than Open WebUI)
- **MSA-style sparse attention** for ultra-long vault recall — when MSA lands,
  the vault becomes the document memory bank and Delphi becomes its query
  interface. This is the bridge to EverMind.
- **Cross-validation hook** — for hard problems, route to two models in
  parallel and compare. Mirrors AgentRig's escalation pattern.

---

## Mentorship note

This file is also for the next builder — present-you, future-you, or a
collaborator. Every section should answer "why" as well as "what." When you
add a feature, update the relevant section *and* add a decision log entry.
If a decision is reversed, leave the original entry and add the new one
below. The chain is forward-only.
