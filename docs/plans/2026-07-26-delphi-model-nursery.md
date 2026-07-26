# Delphi Model Nursery Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a repeatable Delphi “model nursery” where a stronger parent model generates curriculum, judges/repairs child outputs, produces training/evaluation artifacts, and promotes a quantized child model that fits a 6 GB runtime budget.

**Architecture:** The child model lives in its own inference/runtime process, not inside the Delphi FastAPI process. Delphi talks to the child through an OpenAI-compatible endpoint (`llama-server`, Ollama, or another local server), while nursery jobs run offline as CLI commands that collect traces, ask the parent model to critique, and write datasets/benchmarks. The production gateway remains stable: nursery outputs only change routing config after explicit promotion.

**Tech Stack:** Python 3.12, uv, pytest, pydantic, httpx, llama.cpp GGUF/`llama-server`, OpenAI-compatible chat APIs, optional LoRA/QLoRA tooling in a later phase.

---

## Design decisions

1. **Child runtime is independent.** The 6 GB child model should be a separate service with its own port, logs, context limits, and memory budget. Delphi should not import model weights or run inference calculations inside the FastAPI process.
2. **Quantization is deployment, not learning.** Improvement comes from curriculum, supervised fine-tuning, preference data, and better calibration. Quantization produces the deployable child artifact after each training/evaluation cycle.
3. **Promote only through gates.** A child becomes part of Delphi’s roster only after it passes held-out benchmarks for the relevant task type.
4. **Keep secrets out of artifacts.** Dataset records may include prompts and model outputs, but never API keys, bearer tokens, or private `.env` values.
5. **Start with evaluation before fine-tuning.** The first milestone is a benchmark harness that ranks candidate GGUF children under the 6 GB budget. Fine-tuning is phase two.

---

## Target candidate children

Use these as the initial candidate set unless better GGUFs are discovered before implementation:

| Role | Candidate repo | Quant | Approx GGUF size | Purpose |
|---|---|---:|---:|---|
| generalist | `bartowski/Phi-3.5-mini-instruct-GGUF` | `Q6_K` | 3.14 GB | chat, simple reasoning, tool-step drafting |
| chat/tool | `bartowski/Llama-3.2-3B-Instruct-GGUF` | `Q6_K` or `Q8_0` | 2.64–3.42 GB | fast interaction and formatting discipline |
| code child | `bartowski/Qwen2.5-Coder-7B-Instruct-GGUF` | `Q3_K_M` or `Q4_K_M` | 3.81–4.68 GB | coding/debugging under 6 GB |
| stretch generalist | `bartowski/gemma-2-9b-it-GGUF` | `Q3_K_M` | 4.76 GB | quality comparison, only if runtime memory passes |

Memory budget rule: the GGUF file must be under 6 GB, and measured runtime RSS/VRAM plus KV cache must fit the actual 6 GB operating envelope at the selected context length.

---

## Runtime shape

Preferred first runtime: `llama-server` because it exposes `/v1/chat/completions` and can serve GGUF directly.

Example local dev command:

```bash
llama-server \
  -hf bartowski/Qwen2.5-Coder-7B-Instruct-GGUF:Q4_K_M \
  --ctx-size 4096 \
  --port 18080
```

Delphi nursery talks to this child at:

```text
http://127.0.0.1:18080/v1/chat/completions
```

A second runtime can run on another port for candidate comparison:

```bash
llama-server \
  -hf bartowski/Phi-3.5-mini-instruct-GGUF:Q6_K \
  --ctx-size 4096 \
  --port 18081
```

Production promotion can later choose either:

- OpenAI-compatible routing through `config/routing.yaml`; or
- Ollama model tags in `DELPHI_MODEL_*` if the gateway remains Ollama-first.

Do not couple Delphi boot to nursery runtime until promotion.

---

## File layout

Create these files/directories over the implementation:

```text
nursery/
├── __init__.py
├── candidates.py          # typed child/parent/runtime manifests
├── client.py              # OpenAI-compatible async chat client
├── curriculum.py          # seed task prompts by Delphi task_type
├── judge.py               # parent-model rubric and scoring parser
├── records.py             # JSONL schemas for attempts, critiques, eval summaries
├── runner.py              # orchestration: child answer → parent critique → record
└── cli.py                 # uv run python -m nursery.cli ...

tests/
├── test_nursery_candidates.py
├── test_nursery_records.py
├── test_nursery_judge.py
└── test_nursery_runner.py

docs/
└── model-nursery.md       # operator guide after the code exists

data/
└── nursery/               # local generated JSONL outputs; ignored by git
```

If `data/` is not already ignored, add `data/nursery/` to `.gitignore`.

---

## Phase 1 — Manifest and records, no network calls

### Task 1: Add candidate/runtime data models

**Objective:** Define typed nursery configuration without touching Delphi routing.

**Files:**
- Create: `nursery/__init__.py`
- Create: `nursery/candidates.py`
- Test: `tests/test_nursery_candidates.py`

**Step 1: Write failing tests**

Add tests for:

- candidate rejects `gguf_size_gb > 6.0` by default;
- runtime endpoint normalizes trailing `/v1`;
- parent and child model roles are distinct.

Example test skeleton:

```python
import pytest

from nursery.candidates import ChildCandidate, RuntimeEndpoint


def test_child_candidate_enforces_six_gb_budget():
    with pytest.raises(ValueError, match="6 GB"):
        ChildCandidate(
            name="too-big",
            repo="example/model-GGUF",
            quant="Q8_0",
            gguf_size_gb=8.1,
            task_types=["chat"],
        )


def test_runtime_endpoint_chat_url_normalizes_v1():
    endpoint = RuntimeEndpoint(base_url="http://127.0.0.1:18080/v1")
    assert endpoint.chat_completions_url == "http://127.0.0.1:18080/v1/chat/completions"
```

**Step 2: Run test to verify failure**

```bash
uv run pytest tests/test_nursery_candidates.py -v
```

Expected: FAIL because `nursery.candidates` does not exist.

**Step 3: Implement minimal models**

Use `pydantic.BaseModel` or `dataclasses`. Prefer pydantic if already available in the project.

Required concepts:

```python
class RuntimeEndpoint:
    base_url: str
    api_key_env: str | None = None
    timeout_s: int = 120

class ChildCandidate:
    name: str
    repo: str
    quant: str
    gguf_size_gb: float
    task_types: list[str]
    max_context: int = 4096
    runtime: RuntimeEndpoint | None = None

class ParentModel:
    name: str
    base_url: str
    model: str
    api_key_env: str | None
```

**Step 4: Run test to verify pass**

```bash
uv run pytest tests/test_nursery_candidates.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nursery/__init__.py nursery/candidates.py tests/test_nursery_candidates.py
git commit -m "feat: add nursery candidate manifests"
```

---

### Task 2: Add JSONL record schemas

**Objective:** Define durable records for child attempts, parent critiques, and evaluation summaries.

**Files:**
- Create: `nursery/records.py`
- Test: `tests/test_nursery_records.py`

**Step 1: Write failing tests**

Cover:

- round-trip JSON serialization;
- scores must be between 0 and 1;
- records include `task_type`, `candidate`, `prompt`, `child_output`, `parent_score`, `rubric_notes`;
- no field named `api_key`, `token`, or `secret` is allowed in serialized output.

**Step 2: Run RED**

```bash
uv run pytest tests/test_nursery_records.py -v
```

Expected: FAIL because `nursery.records` does not exist.

**Step 3: Implement minimal schemas**

Create:

```python
class NurseryPromptRecord
class ChildAttemptRecord
class ParentCritiqueRecord
class EvaluationSummary
```

Use ISO timestamps and deterministic JSON dumping.

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_nursery_records.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nursery/records.py tests/test_nursery_records.py
git commit -m "feat: add nursery evaluation records"
```

---

## Phase 2 — Static Delphi curriculum

### Task 3: Add a seed curriculum for Delphi task types

**Objective:** Create a versioned, deterministic prompt set covering Delphi’s known task types.

**Files:**
- Create: `nursery/curriculum.py`
- Test: `tests/test_nursery_curriculum.py`

**Step 1: Write failing tests**

Cover:

- every task type in `routing.roster.TASK_TYPES` has at least three seed prompts;
- prompts include at least one expected failure mode;
- vault-query prompts explicitly require grounding/no hallucinated notes;
- code prompts include one debugging and one implementation request.

**Step 2: Run RED**

```bash
uv run pytest tests/test_nursery_curriculum.py -v
```

Expected: FAIL.

**Step 3: Implement the seed curriculum**

Start small. Do not generate hundreds of examples yet. Use curated examples like:

```python
SEED_CURRICULUM = {
    "chat": [...],
    "code": [...],
    "reason": [...],
    "vault_query": [...],
    "gre_quiz": [...],
    "gre_practice_test": [...],
}
```

Each item should include:

- `id`
- `task_type`
- `prompt`
- `rubric`
- `failure_modes`

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_nursery_curriculum.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nursery/curriculum.py tests/test_nursery_curriculum.py
git commit -m "feat: add Delphi nursery seed curriculum"
```

---

## Phase 3 — OpenAI-compatible child client

### Task 4: Add async chat client for standalone child runtimes

**Objective:** Let nursery code call any independent OpenAI-compatible child model server.

**Files:**
- Create: `nursery/client.py`
- Test: `tests/test_nursery_client.py`

**Step 1: Write failing tests with mocked HTTP**

Use `respx` if already available; otherwise use `pytest` monkeypatch around `httpx.AsyncClient.post`.

Cover:

- request body contains `model`, `messages`, `temperature`, `max_tokens`;
- bearer header is set only when an API key is configured;
- server errors become a typed `NurseryClientError`;
- response parser extracts assistant text from OpenAI-compatible JSON.

**Step 2: Run RED**

```bash
uv run pytest tests/test_nursery_client.py -v
```

Expected: FAIL.

**Step 3: Implement minimal client**

Create:

```python
class NurseryChatClient:
    async def complete(self, *, model: str, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> str:
        ...
```

Do not add streaming yet. Batch/offline nursery eval does not need it.

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_nursery_client.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nursery/client.py tests/test_nursery_client.py
git commit -m "feat: add nursery OpenAI-compatible client"
```

---

## Phase 4 — Parent judge and repair loop

### Task 5: Add parent-model judge prompt and strict parser

**Objective:** Score child outputs with a parent model while keeping parser behavior deterministic.

**Files:**
- Create: `nursery/judge.py`
- Test: `tests/test_nursery_judge.py`

**Step 1: Write failing parser tests**

Cover parent output like:

```json
{
  "score": 0.82,
  "passed": true,
  "rubric_notes": "Grounded answer; minor verbosity.",
  "failure_modes": [],
  "repair": null
}
```

Also cover malformed JSON and out-of-range scores.

**Step 2: Run RED**

```bash
uv run pytest tests/test_nursery_judge.py -v
```

Expected: FAIL.

**Step 3: Implement judge parser and prompt builder**

Rubric dimensions:

- task correctness;
- Delphi style/soul fit;
- tool discipline / groundedness;
- formatting/schema compliance;
- whether the answer should escalate to a stronger model.

The parent should return JSON only. Parser should reject non-JSON, clamp nothing, and fail loudly.

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_nursery_judge.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nursery/judge.py tests/test_nursery_judge.py
git commit -m "feat: add parent judge parser"
```

---

### Task 6: Add child → parent → record runner

**Objective:** Orchestrate one curriculum item through child inference, parent critique, and JSONL persistence.

**Files:**
- Create: `nursery/runner.py`
- Test: `tests/test_nursery_runner.py`

**Step 1: Write failing tests with fake clients**

Use fake child and parent clients. Cover:

- child is called before parent;
- parent receives prompt, child output, rubric, and failure modes;
- output record is written as one JSONL line;
- failed parent parse records an error but preserves child output.

**Step 2: Run RED**

```bash
uv run pytest tests/test_nursery_runner.py -v
```

Expected: FAIL.

**Step 3: Implement minimal runner**

Function shape:

```python
async def run_curriculum_item(
    *,
    item: CurriculumItem,
    child: NurseryChatClient,
    parent: NurseryChatClient,
    candidate: ChildCandidate,
    output_path: Path,
) -> ChildAttemptRecord:
    ...
```

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_nursery_runner.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nursery/runner.py tests/test_nursery_runner.py
git commit -m "feat: add nursery evaluation runner"
```

---

## Phase 5 — CLI and local generated-data hygiene

### Task 7: Ignore local nursery outputs

**Objective:** Prevent generated prompts, traces, and critiques from being accidentally committed.

**Files:**
- Modify: `.gitignore`
- Test: shell verification

**Step 1: Add ignore rule**

Append only if missing:

```gitignore
# Delphi model nursery local outputs
data/nursery/
```

**Step 2: Verify ignore behavior**

```bash
mkdir -p data/nursery
touch data/nursery/.keep-test
git status --short --ignored data/nursery/.keep-test
```

Expected: ignored output contains `!! data/nursery/.keep-test`.

**Step 3: Remove temp file**

```bash
rm data/nursery/.keep-test
```

**Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore nursery generated outputs"
```

---

### Task 8: Add nursery CLI

**Objective:** Provide operator commands for listing candidates and running evals.

**Files:**
- Create: `nursery/cli.py`
- Test: `tests/test_nursery_cli.py`

**Step 1: Write failing tests**

Cover:

- `list-candidates` prints configured child candidates;
- `run-seed --candidate NAME --limit 1 --output PATH` calls runner once;
- CLI refuses unknown candidate names;
- CLI requires explicit child runtime URL unless candidate manifest includes one.

**Step 2: Run RED**

```bash
uv run pytest tests/test_nursery_cli.py -v
```

Expected: FAIL.

**Step 3: Implement CLI**

Use stdlib `argparse` unless the project already has a preferred CLI library.

Required commands:

```bash
uv run python -m nursery.cli list-candidates
uv run python -m nursery.cli run-seed \
  --candidate qwen2.5-coder-7b-q4 \
  --child-base-url http://127.0.0.1:18080/v1 \
  --parent-base-url http://127.0.0.1:8090/v1 \
  --parent-model delphi-auto \
  --limit 5 \
  --output data/nursery/qwen-code-q4.seed.jsonl
```

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_nursery_cli.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add nursery/cli.py tests/test_nursery_cli.py
git commit -m "feat: add nursery evaluation CLI"
```

---

## Phase 6 — Real local smoke test

### Task 9: Run one child model as an independent process

**Objective:** Prove the child can live independently and answer through OpenAI-compatible HTTP.

**Files:**
- No repo changes required unless docs are updated after smoke test.

**Step 1: Start child runtime**

Local terminal:

```bash
llama-server \
  -hf bartowski/Phi-3.5-mini-instruct-GGUF:Q6_K \
  --ctx-size 4096 \
  --port 18080
```

**Step 2: Verify directly**

In another terminal:

```bash
curl http://127.0.0.1:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Phi-3.5-mini-instruct-Q6_K",
    "messages": [{"role": "user", "content": "Reply with exactly: nursery-ok"}],
    "temperature": 0,
    "max_tokens": 16
  }'
```

Expected: response includes `nursery-ok` or a close exact echo.

**Step 3: Measure process memory**

macOS local check:

```bash
ps -o pid,rss,command -ax | grep '[l]lama-server'
```

Linux/GPU host check:

```bash
ps -o pid,rss,command -C llama-server
nvidia-smi
```

Expected: recorded RSS/VRAM plus KV cache fits the selected 6 GB target.

**Step 4: Commit docs note if needed**

If the actual command or memory behavior differs from this plan, update `docs/model-nursery.md` later with verified values.

---

## Phase 7 — Benchmark candidates and decide first child

### Task 10: Run seed benchmark against at least two candidates

**Objective:** Produce real scorecards for candidate children under the same curriculum.

**Files:**
- Generated only: `data/nursery/*.jsonl` ignored by git
- Optional summary doc: `docs/model-nursery.md`

**Step 1: Run candidate A**

```bash
uv run python -m nursery.cli run-seed \
  --candidate phi-3.5-mini-q6 \
  --child-base-url http://127.0.0.1:18080/v1 \
  --parent-base-url http://127.0.0.1:8090/v1 \
  --parent-model delphi-auto \
  --limit 20 \
  --output data/nursery/phi-3.5-mini-q6.seed.jsonl
```

**Step 2: Run candidate B**

```bash
uv run python -m nursery.cli run-seed \
  --candidate qwen2.5-coder-7b-q4 \
  --child-base-url http://127.0.0.1:18081/v1 \
  --parent-base-url http://127.0.0.1:8090/v1 \
  --parent-model delphi-auto \
  --limit 20 \
  --output data/nursery/qwen2.5-coder-7b-q4.seed.jsonl
```

**Step 3: Summarize results**

Add a CLI command or short script to compute:

- mean parent score by task type;
- pass rate by task type;
- escalation-needed rate;
- invalid/malformed response rate;
- average latency if captured;
- measured memory if captured.

**Step 4: Decide promotion candidate**

Promotion rule for first child:

- mean score >= 0.80 on intended task type;
- invalid output rate <= 5%;
- hallucinated vault note rate = 0 for `vault_query`;
- measured runtime memory within the 6 GB envelope;
- no boot/runtime instability during the smoke test.

---

## Phase 8 — Promotion without fine-tuning

### Task 11: Add optional nursery child to routing config

**Objective:** Make the winning child available to Delphi without replacing defaults yet.

**Files:**
- Modify: `config/routing.yaml` if OpenAI-compatible routing is active
- Or modify: `.env.example` / operator docs if using Ollama model tags
- Test: existing routing config tests

**Option A: OpenAI-compatible local tier**

Add a tier like:

```yaml
nursery_child_code:
  backend: hermes
  base_url: "http://127.0.0.1:18080/v1"
  model: "qwen2.5-coder-7b-q4"
  api_key_secret: null
  max_context: 4096
  timeout_s: 120
```

Then map only the intended tag:

```yaml
tag_overrides:
  code: nursery_child_code
```

**Option B: Ollama roster tag**

Create/import the child as an Ollama model tag and set:

```bash
DELPHI_MODEL_CODE=delphi-child-code:q4
```

**Step 2: Run tests**

```bash
uv run pytest tests/test_routing_config.py tests/test_roster.py -v
```

Expected: PASS or only known unrelated baseline failures.

**Step 3: Run a live request**

Use Delphi’s existing authenticated local endpoint and verify the response logs show the child model/tier.

**Step 4: Commit**

Commit only after the promotion path is verified.

---

## Phase 9 — Parent-generated training data

### Task 12: Add curriculum expansion command

**Objective:** Let the parent model create more Delphi-specific training/eval examples from the seed curriculum.

**Files:**
- Modify: `nursery/curriculum.py`
- Modify: `nursery/cli.py`
- Test: `tests/test_nursery_curriculum.py`, `tests/test_nursery_cli.py`

**Command shape:**

```bash
uv run python -m nursery.cli expand-curriculum \
  --parent-base-url http://127.0.0.1:8090/v1 \
  --parent-model delphi-auto \
  --task-type code \
  --count 25 \
  --output data/nursery/code.generated-prompts.jsonl
```

Generated prompt records must include:

- seed source id;
- parent model id;
- task type;
- rubric;
- failure modes;
- synthetic/private flag;
- timestamp.

Do not fine-tune on private vault excerpts until there is a redaction policy.

---

### Task 13: Export SFT and preference datasets

**Objective:** Transform judged records into training-ready data.

**Files:**
- Create: `nursery/export.py`
- Test: `tests/test_nursery_export.py`

**Exports:**

1. SFT JSONL:

```json
{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "parent repair or high-scoring child output"}]}
```

2. Preference JSONL:

```json
{"prompt": "...", "chosen": "parent repair", "rejected": "child output", "score": 0.42}
```

Rules:

- high-scoring child outputs can become `chosen` examples;
- low-scoring outputs with parent repairs become preference pairs;
- records with parser errors are excluded;
- private data stays marked and separate.

---

## Phase 10 — Fine-tune, quantize, and rerun gates

This phase can happen outside the Delphi repo if training hardware/tooling lives elsewhere.

### Task 14: Train LoRA child

**Objective:** Improve the child before quantizing.

Expected external flow:

```text
base instruct model
→ SFT LoRA on parent-approved Delphi examples
→ optional DPO/ORPO on parent preference pairs
→ merge LoRA
→ export HF weights
→ convert to GGUF
→ quantize to Q4/Q5/Q6 or IQ variant
→ rerun nursery benchmark
```

Training framework candidates:

- Unsloth for fast local QLoRA;
- Axolotl for repeatable YAML-driven training;
- llama.cpp conversion/quantization for GGUF deployment.

Do not store large model artifacts in this repo.

---

### Task 15: Quantize with Delphi-specific calibration

**Objective:** Preserve Delphi behavior after GGUF quantization.

Calibration text should be built from:

- synthetic seed/generated curriculum;
- parent-approved outputs;
- non-secret Delphi style examples;
- code and tool-use examples;
- vault-query rubrics without private vault contents unless explicitly approved.

Use llama.cpp imatrix flow for aggressive Q3/Q4 variants:

```bash
./llama-imatrix \
  -m child-f16.gguf \
  -f data/nursery/calibration.txt \
  -o child.imatrix

./llama-quantize \
  --imatrix child.imatrix \
  child-f16.gguf \
  delphi-child-Q4_K_M.gguf \
  Q4_K_M
```

Then rerun Phase 7 benchmark before any promotion.

---

## Acceptance criteria

The nursery is usable when:

- [ ] `uv run pytest tests/test_nursery_*.py -v` passes.
- [ ] At least one child model runs in an independent OpenAI-compatible process.
- [ ] Nursery CLI can run a seed benchmark against that child.
- [ ] Parent judge writes deterministic JSONL critique records.
- [ ] Generated outputs are ignored by git.
- [ ] A score summary identifies which task types the child can safely handle.
- [ ] Any promoted child has measured memory within the 6 GB envelope.
- [ ] Promotion is explicit and reversible through routing config or env vars.

---

## First implementation slice

Implement only Phases 1–5 first. That gives Delphi a safe, testable nursery harness without requiring model downloads, training jobs, or route changes. Then run Phase 6 manually with one `llama-server` child and use the real results to decide whether the first promoted child should be Phi-3.5-mini, Llama-3.2-3B, or Qwen2.5-Coder-7B.
