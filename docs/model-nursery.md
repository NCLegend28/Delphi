# Delphi Model Nursery Operator Notes

The nursery is the offline evaluation/training-data loop for Delphi child models.
It should not run inside the Delphi FastAPI request path.

## Where the nursery should run

Default target: **Google Cloud**.

That is not a model-quality problem; it is an orchestration and networking problem:

- The child model runtime (`llama-server`, Ollama, vLLM, etc.) is one service.
- The nursery runner is a separate batch/eval job.
- The parent judge is another OpenAI-compatible endpoint.
- The nursery only needs HTTP access to both child and parent endpoints.

Recommended production shape:

```text
Google Cloud VM / batch job
  └── uv run delphi-nursery run-seed ...
        ├── child-base-url  → reachable child model endpoint
        └── parent-base-url → reachable parent judge endpoint
```

## Child endpoint location options

### Option A — child also runs on Google Cloud

Use this when benchmarking the child in the same environment where nursery jobs run.
This is the cleanest setup for repeatable latency, memory, and throughput numbers.

```bash
llama-server \
  -hf bartowski/Phi-3.5-mini-instruct-GGUF:Q6_K \
  --ctx-size 4096 \
  --host 127.0.0.1 \
  --port 18080
```

Then the nursery job on the same VM uses:

```bash
uv run delphi-nursery run-seed \
  --candidate phi-3.5-mini-q6 \
  --child-base-url http://127.0.0.1:18080/v1 \
  --parent-base-url <PARENT_OPENAI_COMPATIBLE_BASE_URL> \
  --parent-model <PARENT_MODEL> \
  --child-max-tokens 2048 \
  --parent-max-tokens 2048 \
  --limit 20 \
  --output data/nursery/phi-3.5-mini-q6.seed.jsonl
```

### Option B — child stays on the Delphi server

The Delphi server currently keeps `llama-server` bound to `127.0.0.1:18080`, which is correct for safety but not directly reachable from Google Cloud.

To let a Google Cloud nursery job reach that private loopback endpoint, use one of these private-network paths:

1. **Tailscale on both machines** — preferred for durable private service access.
2. **SSH tunnel from the Google Cloud VM to `delphi`** — good for manual runs.
3. **Delphi-bound public listener behind auth/TLS** — only with an explicit exposure plan.

Do not bind the Delphi child runtime to `0.0.0.0` just to make the nursery work.

## Token limits

`max_tokens` controls generated output length, not model context size. The smoke test used a tiny limit and clipped the response. Nursery evals need higher limits so the child can produce complete answers and the parent can return full JSON critique.

CLI defaults:

```text
--child-max-tokens 2048
--parent-max-tokens 2048
--child-temperature 0.2
--parent-temperature 0.0
```

Override per run when the task requires longer answers or stricter parent JSON repair:

```bash
uv run delphi-nursery run-seed \
  --candidate qwen2.5-coder-7b-q4 \
  --child-base-url http://127.0.0.1:18080/v1 \
  --parent-base-url <PARENT_OPENAI_COMPATIBLE_BASE_URL> \
  --parent-model <PARENT_MODEL> \
  --child-max-tokens 4096 \
  --parent-max-tokens 2048 \
  --limit 20 \
  --output data/nursery/qwen2.5-coder-7b-q4.seed.jsonl
```

## Current Delphi child smoke-test status

Verified on the Delphi server:

```text
GET /health → {"status":"ok"}
GET /v1/models → bartowski/Phi-3.5-mini-instruct-GGUF:Q6_K
```

The model is a standalone child runtime. Nursery jobs can target it once network access is established from the machine running the nursery.

## Doppler secret names

Use Doppler to inject parent/child nursery configuration instead of exporting ad-hoc shell variables. The CLI reads these names automatically when they are present:

```text
DELPHI_NURSERY_PARENT_BASE_URL   # e.g. https://api.openai.com/v1 or another OpenAI-compatible parent
DELPHI_NURSERY_PARENT_MODEL      # e.g. a frontier/teacher model name
DELPHI_NURSERY_PARENT_API_KEY    # bearer token for the parent endpoint, if required

DELPHI_NURSERY_CHILD_BASE_URL    # e.g. http://127.0.0.1:18080/v1 on the Delphi server
DELPHI_NURSERY_CHILD_MODEL       # optional documentation/runtime label for the child
DELPHI_NURSERY_CHILD_API_KEY     # only needed if llama-server is started with an API key
HF_TOKEN                         # only needed for gated/private Hugging Face child repos
```

Example setup from a logged-in Doppler shell. Replace the placeholder values locally; do not paste real keys into chat logs:

```bash
doppler setup --project delphi --config nursery

doppler secrets set \
  DELPHI_NURSERY_PARENT_BASE_URL='https://YOUR_PARENT_OPENAI_COMPATIBLE_BASE_URL/v1' \
  DELPHI_NURSERY_PARENT_MODEL='YOUR_PARENT_MODEL' \
  DELPHI_NURSERY_PARENT_API_KEY='YOUR_PARENT_API_KEY' \
  DELPHI_NURSERY_CHILD_BASE_URL='http://127.0.0.1:18080/v1' \
  DELPHI_NURSERY_CHILD_MODEL='bartowski/Phi-3.5-mini-instruct-GGUF:Q6_K'
```

Then run without passing secrets or parent values on the command line:

```bash
doppler run -- delphi-nursery run-seed \
  --candidate phi-3.5-mini-q6 \
  --child-max-tokens 2048 \
  --parent-max-tokens 2048 \
  --limit 20 \
  --output data/nursery/phi-3.5-mini-q6.seed.jsonl
```

For a local loopback child, `DELPHI_NURSERY_CHILD_API_KEY` should remain unset unless the child runtime is restarted with a matching `llama-server --api-key` value. Storing a child API key in Doppler by itself does not protect the already-running loopback server.
