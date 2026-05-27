# Voice & Vision smoke checklist

Operator runbook for hand-verifying the multimodal path end to end.
Run this after any change that touches `api/audio.py`, `api/chat.py`,
`proxy/`, `ui/src/hooks/useDelphiStream.js`, `ui/src/lib/attachments.js`,
or the chat-rail components.

Estimated time: ~10 minutes once Ollama has a vision model pulled.

## 0. Prereqs

- Backend `.env` filled in (at minimum `DELPHI_BEARER_TOKEN`,
  `OLLAMA_BASE_URL`, `OBSIDIAN_VAULT_PATH`).
- `SPEECH_TO_TEXT_ENABLED=true` (default).
- A vision-capable model pulled on Ollama, e.g.:
      ollama pull llama3.2-vision
  and `DELPHI_MODEL_CHAT` (or whichever roster slot you'll route to)
  pointed at it.
- Microphone permissions ready to grant in the browser.

## 1. Backend up

    uv run python main.py

In another shell:

    curl -s http://localhost:8080/healthz
    # {"status":"ok"}

    TOKEN=$(grep DELPHI_BEARER_TOKEN .env | cut -d= -f2)
    curl -s -H "Authorization: Bearer $TOKEN" \
         -H "Content-Type: application/json" \
         -d '{"messages":[{"role":"user","content":"ping"}]}' \
         http://localhost:8080/v1/chat/completions | head -c 200

Expect a streamed SSE body (or non-stream JSON depending on the model
config). Then poke the audio endpoint **without** a file to confirm it
is mounted:

    curl -s -o /dev/null -w '%{http_code}\n' \
         -H "Authorization: Bearer $TOKEN" \
         -X POST http://localhost:8080/v1/audio/transcriptions
    # 422 (FastAPI rejects missing form field) — good, endpoint is live

## 2. UI up

    cd ui && npm run dev
    # http://localhost:5173

Vite proxies `/v1` to `:8080`, so the bearer in `.env.local` is enough.

## 3. Text-only regression

Type a plain message and send. Verify:
- Streaming tokens appear in the OutputCanvas.
- Vault note lands under `$OBSIDIAN_VAULT_PATH/conversations/<date>/`.
- `requests.jsonl` got a new line.

This must pass even with the audio/image paths untouched.

## 4. Image upload (vision)

1. Click 📎, pick a JPEG/PNG.
2. Confirm the preview tile appears above the textarea with the ✕
   remove button.
3. Type a prompt ("describe this image") and send.
4. Verify the model actually responds about the image — non-vision
   models will return garbage or error here; that confirms the content
   array reached Ollama.
5. **Check upstream payload shape.** In the backend log (or a tcpdump /
   mitmproxy if you're paranoid), the outbound Ollama request body's
   `messages[-1].content` should be a list with one `text` part and one
   `image_url` part (data-URL).
6. **Check the vault note** for the exchange. The user-message body
   should contain `[image attachment]` placeholder text, NOT a base64
   blob. Same for `requests.jsonl` — `grep -c 'data:image' …` should be 0.
7. Sanity-check the resize: a 4000×3000 photo should be ~1568px on the
   long edge by the time it hits the wire (open devtools → Network →
   request body → image data URL → decode to verify, or just eyeball
   the byte count — should be a few hundred KB, not multiple MB).

## 5. Audio (voice → text)

1. Press 🎙. Browser prompts for mic permission — grant it.
2. Speak a short phrase ("hello delphi, what is two plus two").
3. Press 🎙 again to stop.
4. Status flips to `transcribing`; first-ever transcription may sit here
   10–60 seconds while faster-whisper lazy-downloads the model (`base`
   ≈ 140 MB). Subsequent runs are sub-second.
5. The transcript fills the textarea. **Edit it** if needed.
6. Press SEND. Normal chat flow takes over.

## 6. AUTO-SPEAK

1. Toggle AUTO-SPEAK on in the chat rail.
2. Send any message.
3. As the assistant stream finishes, the browser speaks the response
   aloud via `SpeechSynthesis`.
4. Per-message SPEAK / STOP buttons on assistant bubbles should also
   work independently.

## 7. Mid-stream cancel interrupts speech

1. Send a prompt that produces a long answer.
2. While it streams (and/or while AUTO-SPEAK is reading), press ESC or
   the cancel button.
3. Both the SSE stream **and** any active utterance should stop.
4. Click SPEAK on a different bubble — speech should still work
   afterwards (`speechSynthesis.cancel()` left the queue clean).

## 8. Failure modes

| Scenario | Expected |
|---|---|
| User denies mic prompt | Recorder status flips to `denied`, 🎙 button disabled; reloading the page after granting permission in browser settings re-enables it. |
| Oversize image (> backend body limit, ~25 MB after resize is unrealistic but raw bypass possible) | Backend returns 413; UI surfaces the error in the task log without crashing the rail. |
| Unsupported audio MIME (e.g. forced `audio/aac`) | `POST /v1/audio/transcriptions` returns 415 with `detail` naming the rejected type. |
| `SPEECH_TO_TEXT_ENABLED=false` in backend env | Endpoint returns 503 `"speech-to-text disabled"`; UI shows the error and reverts the rail to `idle` (textarea untouched). |
| Audio over 25 MiB (`SPEECH_TO_TEXT_MAX_UPLOAD_BYTES`) | Endpoint returns 413 before invoking the provider. |
| Non-vision model with an image attached | Ollama returns an error / nonsense; verify Delphi forwards the error cleanly rather than 500-ing. |

## Done

If 3–8 all behave, the multimodal stack is healthy. Capture the time of
the smoke run somewhere (commit message, session log) so the next
regression has a baseline.
