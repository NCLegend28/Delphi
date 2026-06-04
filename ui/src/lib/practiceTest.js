/**
 * Practice-test API client.
 *
 * Caddy injects the bearer token onto proxied /v1 requests at the edge, so
 * the browser never sees the secret. These fetches go to the same origin;
 * during ``npm run dev`` the Vite proxy forwards them to the gateway.
 *
 * Two endpoints:
 *   - GET  /v1/practice-tests/<id>       → test metadata + body (no key)
 *   - POST /v1/practice-tests/<id>/grade → submit answers, get graded result
 *
 * Both return JSON; non-2xx responses throw a ``PracticeTestApiError`` with
 * the server's typed ``detail.code`` and ``detail.message`` when available,
 * so the form can render specific UX ("TEST_NOT_FOUND" → "this test was
 * deleted; regenerate?") rather than generic "something went wrong".
 */

export class PracticeTestApiError extends Error {
  constructor(message, { status, code } = {}) {
    super(message);
    this.name = "PracticeTestApiError";
    this.status = status;
    this.code = code;
  }
}

async function readJsonOrThrow(resp) {
  let body = null;
  try {
    body = await resp.json();
  } catch {
    // Non-JSON error body (502 from caddy, etc.) — fall through.
  }
  if (!resp.ok) {
    const detail = body?.detail;
    const code =
      typeof detail === "object" && detail && "code" in detail ? detail.code : undefined;
    const message =
      (typeof detail === "object" && detail && "message" in detail && detail.message) ||
      (typeof detail === "string" ? detail : null) ||
      `HTTP ${resp.status}`;
    throw new PracticeTestApiError(message, { status: resp.status, code });
  }
  return body;
}

export async function fetchPracticeTest(testId, { includeKey = false } = {}) {
  const qs = includeKey ? "?include_key=true" : "";
  const resp = await fetch(`/v1/practice-tests/${encodeURIComponent(testId)}${qs}`, {
    headers: { Accept: "application/json" },
  });
  return readJsonOrThrow(resp);
}

export async function gradePracticeTest(testId, answers) {
  const resp = await fetch(
    `/v1/practice-tests/${encodeURIComponent(testId)}/grade`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ answers }),
    }
  );
  return readJsonOrThrow(resp);
}
