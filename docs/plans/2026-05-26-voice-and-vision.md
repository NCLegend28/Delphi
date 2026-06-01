# Delphi Voice + Vision Implementation Plan

> For Hermes: Use subagent-driven-development to execute this plan task-by-task.

Goal: Add image-aware chat, microphone-driven input, and spoken output to Delphi without breaking the existing OpenAI-compatible chat path, SSE streaming UX, or vault/log persistence pipeline.

Architecture: Ship vision first on the existing JSON chat route by upgrading `messages[].content` from plain strings to OpenAI-style content arrays (`text`, `image_url`, later `input_audio`). Keep the current `/v1/chat/completions` contract for multimodal chat, but add dedicated audio routes for speech workflows so recording/transcription/playback do not distort the chat contract. Preserve durable memory by storing structured message parts internally, then derive safe text summaries for vault notes, entity extraction, and JSONL logs.

Tech Stack: FastAPI, httpx, Ollama OpenAI-compatible chat API, React 19 + Vite 8, Zustand, MediaRecorder, browser audio playback, existing SSE stream parser.

---

## Current-state findings

1. Backend chat accepts an untyped JSON body and treats `messages` as `list[dict]`, but it assumes every persisted `Message.content` is a string (`api/chat.py`, `memory/record.py`, `worker/serde.py`, `memory/persist.py`).
2. The Ollama proxy is almost ready for vision passthrough: `chat()` already accepts `list[dict[str, Any]]`, but `stream_chat()` is still typed as `list[dict[str, str]]`.
3. The UI only submits plain text from `ui/src/components/ChatRail/InputBar.jsx`; there is no file picker, camera capture, microphone capture, or attachment state.
4. The mission-control UI already has a preview concept, but the live output renderer only supports `code` and `document`; `media`/image preview is not wired (`ui/src/components/OutputCanvas/index.jsx`, `routing/soul.py`, `ui/src/hooks/useDelphiStream.js`).
5. Persistence is the main trap: `memory/persist.py` extracts the last user message as a string, and the vault/logger templates expect plain text. Voice/vision work will silently rot unless the persistence boundary is upgraded first.

---

## Product decisions

1. Vision requests use the existing `/v1/chat/completions` endpoint.
   - UI sends OpenAI-style content arrays.
   - Images are resized client-side and embedded as `image_url.url` data URLs for local/dev use.
   - Later, large-image uploads can move to file-backed URLs, but do not block the first milestone on storage.

2. Voice input is split from chat.
   - Add `POST /v1/audio/transcriptions` for mic blobs.
   - UI records audio with `MediaRecorder`, uploads it, receives text, then sends normal chat.
   - This keeps the chat stream text-first and avoids streaming `input_audio` complexity on day one.

3. Voice output is phased.
   - Phase 1: browser-side playback controls and optional speech synthesis for the latest assistant reply.
   - Phase 2: replace browser speech with `POST /v1/audio/speech` once a private TTS provider/model is chosen.

4. Persistence stores structure, not just flattened strings.
   - `Message.content` becomes `str | tuple[ContentPart, ...]` (or equivalent typed union).
   - Vault/log/entity extraction use a derived `text_for_memory()` helper so images/audio do not poison durable notes.

---

## Acceptance criteria

- A user can attach an image in the UI, send it, and Delphi forwards it upstream without stripping the image part.
- The existing text-only chat flow continues to pass all current tests.
- A user can record audio in the UI, receive a transcript, edit it if needed, and send it as a normal message.
- Delphi can optionally read its latest answer aloud from the UI.
- Vault notes and JSONL logs remain readable and do not explode with raw base64 blobs.
- Entity extraction still runs on text summaries only.

---

## Task 1: Lock the multimodal contract with tests

Objective: Add failing tests that define the exact request/record behavior before changing production code.

Files:
- Modify: `tests/test_chat.py`
- Modify: `tests/test_ollama_client.py`
- Modify: `tests/test_record.py`
- Modify: `tests/test_vault.py`
- Create: `tests/test_audio_routes.py`

Step 1: Add a chat-route test for OpenAI-style content arrays.

Use a request body like:

```python
{
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is in this image?"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AAA..."},
                },
            ],
        }
    ],
    "stream": True,
}
```

Assert:
- Delphi returns `200`
- the upstream Ollama mock receives the content array intact
- no code path coerces the array to `"[object Object]"` or `""`

Step 2: Add proxy tests proving `OllamaClient.stream_chat()` accepts structured message content.

Run:

```bash
uv run pytest tests/test_ollama_client.py -v
```

Expected: new test fails until `stream_chat()` typing/body handling are widened.

Step 3: Add record/persistence tests for structured content.

Assert:
- structured message parts round-trip through `worker/serde.py`
- vault-facing helper returns a clean text summary
- base64 image data does not land in rendered notes/logs

Step 4: Add an audio-route contract test.

Define:
- multipart upload with `file`
- optional `model` form field
- response shape compatible with OpenAI transcription-style JSON, e.g. `{"text": "..."}`

Step 5: Run the targeted suite.

Run:

```bash
uv run pytest tests/test_chat.py tests/test_ollama_client.py tests/test_record.py tests/test_vault.py tests/test_audio_routes.py -v
```

Expected: FAIL on the new multimodal/audio assertions.

Commit:

```bash
git add tests/test_chat.py tests/test_ollama_client.py tests/test_record.py tests/test_vault.py tests/test_audio_routes.py
git commit -m "test: define voice and vision contracts"
```

---

## Task 2: Upgrade the persistence boundary for structured content

Objective: Make Delphi capable of carrying image/audio parts internally without breaking vault notes, entity extraction, or worker serialization.

Files:
- Modify: `memory/record.py`
- Modify: `worker/serde.py`
- Modify: `memory/persist.py`
- Modify: `memory/vault.py`
- Modify: `telemetry/logger.py`
- Modify: `tests/test_record.py`
- Modify: `tests/test_vault.py`

Step 1: Introduce typed content parts in `memory/record.py`.

Suggested shape:

```python
@dataclass(frozen=True, slots=True)
class TextPart:
    type: Literal["text"]
    text: str

@dataclass(frozen=True, slots=True)
class ImageUrlPart:
    type: Literal["image_url"]
    url: str

@dataclass(frozen=True, slots=True)
class InputAudioPart:
    type: Literal["input_audio"]
    transcript: str | None = None
    mime_type: str | None = None

MessageContent = str | tuple[TextPart | ImageUrlPart | InputAudioPart, ...]
```

Step 2: Add helper functions in `memory/record.py` or `memory/persist.py`.

Required helpers:
- `message_text(content) -> str`
- `has_media(content) -> bool`
- `redact_for_log(content) -> str | list[dict[str, str]]`

Rule: images/audio may be mentioned in summaries, but never dump base64 into durable memory.

Step 3: Update `worker/serde.py` so structured content survives queue round-trips.

Run:

```bash
uv run pytest tests/test_record.py -v
```

Expected: PASS.

Step 4: Update `memory/persist.py` to feed entity extraction only human-readable text.

Rules:
- `text` parts concatenate normally
- image parts become a marker like `[image attachment]`
- audio parts use transcript text when available, otherwise `[audio attachment]`

Step 5: Update vault/log formatting to stay compact.

Add extras like:
- `has_media`
- `attachment_kinds`

Do not add raw blobs to:
- `ConversationNote.user_message`
- `ConversationNote.assistant_message`
- `requests.jsonl`

Step 6: Run verification.

```bash
uv run pytest tests/test_record.py tests/test_vault.py tests/test_chat.py -v
```

Commit:

```bash
git add memory/record.py worker/serde.py memory/persist.py memory/vault.py telemetry/logger.py tests/test_record.py tests/test_vault.py tests/test_chat.py
git commit -m "refactor: support structured multimodal message content"
```

---

## Task 3: Enable vision on the existing chat route

Objective: Let `/v1/chat/completions` accept and forward image-bearing content arrays end-to-end.

Files:
- Modify: `api/chat.py`
- Modify: `proxy/ollama_client.py`
- Modify: `routing/resolver.py`
- Modify: `tests/test_chat.py`
- Modify: `tests/test_ollama_client.py`

Step 1: Widen chat-route normalization.

In `api/chat.py`:
- validate `messages` remains a list
- preserve `content` as either string or structured list
- build `record_messages` with structured content instead of coercing to `str`

Step 2: Fix proxy typing and passthrough.

In `proxy/ollama_client.py`:
- change `stream_chat(messages=...)` to accept `list[dict[str, Any]]`
- do not transform message content on the way to Ollama

Step 3: Update resolver assumptions.

`routing/resolver._last_user_message()` currently extracts only string content. Change it to flatten text parts and ignore image/audio parts so classifier routing still works.

Step 4: Add safe guardrails.

Reject obviously bad content with `400`:
- unknown part `type`
- malformed `image_url`
- empty content arrays

Step 5: Run verification.

```bash
uv run pytest tests/test_chat.py tests/test_ollama_client.py tests/test_resolver.py -v
```

Expected: all text-only tests still pass; new multimodal chat tests pass.

Commit:

```bash
git add api/chat.py proxy/ollama_client.py routing/resolver.py tests/test_chat.py tests/test_ollama_client.py tests/test_resolver.py
git commit -m "feat: pass image-aware chat messages through delphi"
```

---

## Task 4: Add backend audio transcription support

Objective: Create a dedicated transcription endpoint for mic uploads.

Files:
- Create: `api/audio.py`
- Modify: `main.py`
- Modify: `config.py`
- Modify: `.env.example`
- Modify: `api/deps.py`
- Modify: `tests/test_audio_routes.py`

Step 1: Add config for speech-to-text.

Add settings such as:
- `speech_to_text_provider`
- `speech_to_text_model`
- `speech_to_text_enabled`
- size/time limits for uploads

Do not hardcode a provider in route code.

Step 2: Add `POST /v1/audio/transcriptions`.

Contract:
- accepts multipart `file`
- optional `model`
- returns JSON: `{"text": "..."}`
- authenticated with existing bearer token

Step 3: Keep the provider boundary narrow.

Either:
- add a new small proxy helper module, or
- extend `proxy/ollama_client.py` only if Ollama/provider support is proven

Do not bury provider-specific request formatting in the FastAPI route.

Step 4: Add request-size validation and explicit errors.

Return:
- `400` for missing file
- `413` for file too large
- `415` for unsupported MIME type
- `502` for upstream/provider failure

Step 5: Run verification.

```bash
uv run pytest tests/test_audio_routes.py -v
```

Commit:

```bash
git add api/audio.py main.py config.py .env.example api/deps.py tests/test_audio_routes.py
git commit -m "feat: add audio transcription endpoint"
```

---

## Task 5: Add attachment and microphone state to the UI

Objective: Teach the chat UI to hold text, image attachments, and recorded audio before send.

Files:
- Modify: `ui/src/store/chatStore.js`
- Modify: `ui/src/components/ChatRail/InputBar.jsx`
- Modify: `ui/src/components/ChatRail/index.jsx`
- Create: `ui/src/lib/attachments.js`
- Create: `ui/src/hooks/useRecorder.js`
- Modify: `ui/src/components/ChatRail/MessageBubble.jsx`

Step 1: Extend `chatStore` message shape.

Suggested additions:
- `attachments?: Attachment[]`
- `transcript?: string | null`
- `audioUrl?: string | null`

Keep existing text-only messages valid.

Step 2: Add image attachment UX in `InputBar.jsx`.

Include:
- hidden file input for `image/*`
- thumbnail strip with remove buttons
- client-side resize/compress utility in `ui/src/lib/attachments.js`

Step 3: Add microphone recording UX.

In `useRecorder.js`:
- request mic permission
- start/stop/cancel recording via `MediaRecorder`
- expose blob URL for playback before upload

Step 4: Render richer bubbles.

In `MessageBubble.jsx`:
- show image thumbnails for user messages
- show transcript badge for audio-origin messages
- keep assistant rendering text-first for now

Step 5: Run UI verification.

```bash
cd ui && npm test -- --runInBand
```

If no UI test harness exists yet, add Vitest coverage for `attachments.js` and `useRecorder.js`, then run:

```bash
cd ui && npm run test
```

Commit:

```bash
git add ui/src/store/chatStore.js ui/src/components/ChatRail/InputBar.jsx ui/src/components/ChatRail/index.jsx ui/src/components/ChatRail/MessageBubble.jsx ui/src/lib/attachments.js ui/src/hooks/useRecorder.js
git commit -m "feat: add image and microphone draft state to ui"
```

---

## Task 6: Teach the UI stream hook to send vision requests and consume transcripts

Objective: Upgrade the only UI→backend path so it can submit text+image messages and use the transcription endpoint.

Files:
- Modify: `ui/src/hooks/useDelphiStream.js`
- Modify: `ui/src/components/ChatRail/InputBar.jsx`
- Modify: `ui/src/store/chatStore.js`
- Modify: `ui/.env.example`

Step 1: Change `send()` to accept a draft object, not just plain text.

Suggested draft shape:

```javascript
{
  text: string,
  images: [{ mimeType, dataUrl, width, height }],
  audio: null | { blob, mimeType, durationMs }
}
```

Step 2: Build OpenAI-style content arrays.

For a message with text + image:

```javascript
[
  { type: "text", text },
  { type: "image_url", image_url: { url: dataUrl } },
]
```

For audio drafts:
- call `/v1/audio/transcriptions`
- populate the textarea/draft with returned text
- let the operator edit before final send

Step 3: Keep history serialization correct.

When mapping `chatStore.messages` into request history, preserve prior user image content arrays instead of collapsing them to plain text.

Step 4: Preserve streaming behavior.

Do not change:
- SSE parsing
- assistant bubble start-on-first-byte logic
- ESC cancel behavior

Step 5: Verify manually and with tests.

Manual smoke:

```bash
cd ui && npm run dev
# Attach image → send → confirm backend receives content array.
# Record audio → transcript appears → send edited transcript.
```

Commit:

```bash
git add ui/src/hooks/useDelphiStream.js ui/src/components/ChatRail/InputBar.jsx ui/src/store/chatStore.js ui/.env.example
git commit -m "feat: wire ui streaming path for vision and speech input"
```

---

## Task 7: Add image/media preview support to the mission-control shell

Objective: Make the existing preview system visually reflect image inputs/outputs.

Files:
- Modify: `ui/src/components/OutputCanvas/index.jsx`
- Modify: `ui/src/store/delphiStore.js`
- Modify: `ui/src/hooks/useDelphiStream.js`
- Modify: `routing/soul.py`

Step 1: Extend preview kinds.

Support:
- `code`
- `document`
- `media`

Preview shape:

```javascript
{ kind: "media", url: "...", alt: "...", mimeType: "image/png" }
```

Step 2: Update parser and soul docs.

In `routing/soul.py`, add:
- `[PREVIEW:media]...[/PREVIEW]`

In `useDelphiStream.js`, parse that into `delphiStore.setPreview(...)`.

Step 3: Render media in `OutputCanvas`.

Show:
- image preview
- alt/caption metadata when present
- graceful fallback for unsupported media

Step 4: Ensure user-attached images are also visible somewhere in the canvas/chat rail.

The operator should be able to verify which image Delphi saw.

Step 5: Run verification.

```bash
cd ui && npm run test
uv run pytest tests/test_templates.py tests/test_chat.py -v
```

Commit:

```bash
git add ui/src/components/OutputCanvas/index.jsx ui/src/store/delphiStore.js ui/src/hooks/useDelphiStream.js routing/soul.py
git commit -m "feat: add media preview to delphi mission control ui"
```

---

## Task 8: Add spoken-output controls

Objective: Let Delphi speak its latest answer aloud, but keep the first version low-risk.

Files:
- Create: `ui/src/hooks/useSpeechPlayback.js`
- Modify: `ui/src/components/Footer/index.jsx`
- Modify: `ui/src/components/ChatRail/MessageBubble.jsx`
- Modify: `ui/src/store/delphiStore.js`
- Create later if needed: `api/speech.py`

Step 1: Ship browser playback first.

Implement in `useSpeechPlayback.js`:
- play latest assistant text
- stop current playback on new stream or operator cancel
- expose `supported`, `playing`, `speak(text)`, `stop()`

Step 2: Add operator controls.

Place controls in the footer and/or assistant message bubble:
- SPEAK
- STOP
- AUTO-SPEAK toggle (off by default)

Step 3: Wire stream lifecycle.

Rules:
- never speak partial streaming deltas
- only speak after the assistant response completes
- interrupt speech if a new request starts

Step 4: Leave a clear seam for server TTS.

If privacy/voice quality becomes important, add `api/speech.py` later with the same UI hook interface so only the hook changes.

Step 5: Verify manually.

- Send text request
- Wait for full response
- Click SPEAK
- Start a new request and confirm old playback stops

Commit:

```bash
git add ui/src/hooks/useSpeechPlayback.js ui/src/components/Footer/index.jsx ui/src/components/ChatRail/MessageBubble.jsx ui/src/store/delphiStore.js
git commit -m "feat: add spoken response controls to ui"
```

---

## Task 9: Finish docs, envs, and smoke tests

Objective: Make the feature operable by future you.

Files:
- Modify: `README.md`
- Modify: `ui/README.md`
- Modify: `.env.example`
- Modify: `ui/.env.example`
- Create: `docs/sessions/voice-vision-smoke.md` (optional checklist)

Step 1: Document required models/providers.

Include:
- which chat model supports vision
- which transcription provider/model is configured
- browser permissions needed for mic/camera/file access

Step 2: Add end-to-end smoke steps.

```bash
# backend
uv run python main.py

# ui
cd ui && npm run dev

# manual checks
# 1. text-only chat still works
# 2. image upload works
# 3. audio transcription works
# 4. spoken playback works
```

Step 3: Add failure-mode notes.

Document expected UX for:
- mic permission denied
- image too large
- unsupported browser
- STT provider unavailable

Step 4: Run final regression.

```bash
uv run pytest
cd ui && npm run build
```

Commit:

```bash
git add README.md ui/README.md .env.example ui/.env.example docs/sessions/voice-vision-smoke.md
git commit -m "docs: document delphi voice and vision workflows"
```

---

## Recommended execution order

1. Task 1 — tests
2. Task 2 — persistence boundary
3. Task 3 — vision backend passthrough
4. Task 5 — UI attachment/mic draft state
5. Task 6 — UI streaming/transcription wiring
6. Task 7 — media preview
7. Task 4 — transcription backend if not already needed for Task 6
8. Task 8 — spoken output
9. Task 9 — docs/regression

Reason: the biggest technical risk is silent data loss in persistence, not the UI widgets.

---

## Risks and pitfalls

- `memory/persist.py` is currently string-only. If this is skipped, media support will appear to work but produce broken notes/logs.
- Large base64 images can bloat request bodies and session history. Add client-side resize caps early.
- Browser mic APIs are permission-heavy and vary by browser. Feature-detect and surface clear failures.
- Do not add raw media payloads to the vault or JSONL logs.
- Do not teach the classifier from image parts; route off text only.
- Do not block the first milestone on perfect TTS. Vision + transcription are the more valuable path.

---

## Definition of done

- Text-only Delphi is unchanged for existing users.
- Delphi can see images in chat.
- Delphi can accept spoken input via transcript.
- Delphi can optionally speak responses.
- Durable memory remains compact, searchable, and blob-free.

Plan complete. Saved at `docs/plans/2026-05-26-voice-and-vision.md`.
