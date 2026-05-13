# Delphi

Tali's private, self-hosted LLM gateway — an OpenAI-compatible HTTP endpoint
that routes requests across a roster of local Ollama models, injects a shared
system prompt, and writes a structured Obsidian note per exchange.

See [`CLAUDE.md`](CLAUDE.md) for architecture, conventions, and the operational
runbook. This README only covers getting the skeleton running.

## Quickstart

```bash
# Install deps + create the project venv
uv sync

# Copy env template and fill in DELPHI_BEARER_TOKEN at minimum
cp .env.example .env

# Run the service locally
uv run python main.py

# Verify
curl http://localhost:8080/healthz
# {"status":"ok"}
```

## Tests

```bash
# Unit + integration suite (no Ollama needed — proxy is mocked):
uv run pytest

# End-to-end smoke against a real local Ollama (must be running with the
# classifier model and at least one roster model pulled):
DELPHI_SMOKE_OLLAMA=1 uv run pytest tests/test_smoke_ollama.py -v
```

## Over-the-wire smoke (the "First milestone" curl)

```bash
# 1. Start the service.
uv run uvicorn main:app --host 0.0.0.0 --port 8080

# 2. From another terminal:
curl -N -H "Authorization: Bearer $(grep DELPHI_BEARER_TOKEN .env | cut -d= -f2)" \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"refactor this Python: def f(x): return x*2 if x>0 else 0"}], "task_type":"auto"}' \
     http://localhost:8080/v1/chat/completions

# 3. Verify the side effects.
ls -la $OBSIDIAN_VAULT_PATH/conversations/$(date +%Y-%m-%d)/
tail -1 $LOG_DIR/requests.jsonl | jq
curl -s http://localhost:8080/metrics | grep delphi_requests_total
```

Success looks like: streamed response in the terminal, a fresh `.md` in the
date-stamped conversations folder, a JSONL line in `requests.jsonl`, and a
non-zero counter on the metrics endpoint.

## Status

End-to-end: auth → resolver → soul → proxy → vault (with entity wikilinks
and threshold-promoted entity stubs) → JSONL log → Prometheus metrics.
Templates are user-overridable via a directory passed to `TemplateRenderer`.

Not yet built: `/admin/reload-roster`, per-client roster overrides, the
embedding sidecar for semantic vault search, function-calling translation.

