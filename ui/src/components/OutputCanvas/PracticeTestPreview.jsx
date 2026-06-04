import { useEffect, useMemo, useState } from "react";
import { fetchPracticeTest, gradePracticeTest, PracticeTestApiError } from "../../lib/practiceTest";

/**
 * Practice-test preview — the editable form variant of the preview pane.
 *
 * Lives alongside the document/code/media variants in PreviewBlock and gets
 * picked up when the model emits ``[PREVIEW:practice-test:<test_id>]``. The
 * stream parser stashes the test_id on ``preview.testId``; this component
 * fetches the test metadata (questions + question_ids) and renders one
 * input per question. Submit posts to the grade endpoint and swaps the
 * form out for a per-question graded view.
 *
 * Three states drive the layout:
 *   - "loading"  — fetching the test
 *   - "filling"  — form is up, awaiting submit
 *   - "graded"   — show per-question result + score
 *
 * "error" surfaces inline at the bottom of whichever state was active when
 * it fired (e.g. fetch error during loading, grade error during submit).
 */
export function PracticeTestPreview({ testId, fallbackBody }) {
  // Initial phase depends on whether we even have a test_id — derived in the
  // initializer rather than in an effect to avoid a cascading render.
  const [phase, setPhase] = useState(testId ? "loading" : "filling");
  const [test, setTest] = useState(null);
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState(testId ? null : "Missing test id");

  // Fetch the test on mount. The stream-rendered ``fallbackBody`` is enough
  // to read the questions, but we want the canonical question_id list from
  // the server (so submission keys match the answer key exactly).
  useEffect(() => {
    if (!testId) return undefined;
    let cancelled = false;
    fetchPracticeTest(testId)
      .then((t) => {
        if (cancelled) return;
        setTest(t);
        // Pre-populate every question_id with empty so controlled inputs
        // stay stable from the user's first keystroke.
        const initial = {};
        // The body lives server-side too; trust the server for question_ids
        // by inspecting answer_key when include_key=true was used. We didn't,
        // so we'll derive ids from the rendered body: q1..qN.
        for (let i = 1; i <= (t.n_questions || 0); i += 1) {
          initial[`q${i}`] = "";
        }
        setAnswers(initial);
        setPhase("filling");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(formatError(err));
        setPhase("filling"); // still let them see the fallback body
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testId]);

  const questionIds = useMemo(() => Object.keys(answers).sort(byNaturalOrder), [answers]);

  const setAnswer = (qid, value) =>
    setAnswers((prev) => ({ ...prev, [qid]: value }));

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);
    setPhase("loading");
    try {
      const payload = normalizePayload(answers);
      const graded = await gradePracticeTest(testId, payload);
      setResult(graded);
      setPhase("graded");
    } catch (err) {
      setError(formatError(err));
      setPhase("filling");
    }
  };

  const body = test?.body ?? fallbackBody ?? "";

  return (
    <div className="flex flex-col gap-3">
      {/* The original test body so the user has the questions in front of
          them. Renders as plain markdown-ish prose — same styling as a
          ``[PREVIEW:document]``. */}
      <div className="whitespace-pre-wrap break-words rounded-sm border border-[var(--color-border-dim)] bg-[var(--color-bg-surface)]/80 p-4 text-xs leading-relaxed text-[var(--color-text-primary)]">
        {body || "Loading test…"}
      </div>

      {phase === "filling" && questionIds.length > 0 && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-2 rounded-sm border border-[var(--color-border-dim)] bg-[var(--color-bg-surface)]/60 p-3">
          <div className="text-[8px] tracking-[0.2em] text-[var(--color-accent-amber)]">
            ANSWERS
          </div>
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {questionIds.map((qid) => (
              <AnswerInput
                key={qid}
                qid={qid}
                value={answers[qid]}
                onChange={(v) => setAnswer(qid, v)}
              />
            ))}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="submit"
              className="rounded-sm border border-[var(--color-accent-cyan)] bg-[var(--color-accent-cyan)]/10 px-3 py-1 font-mono text-[10px] tracking-[0.2em] text-[var(--color-accent-cyan)] transition-colors hover:bg-[var(--color-accent-cyan)]/20"
            >
              SUBMIT FOR GRADING
            </button>
            <span className="text-[9px] tracking-[0.1em] text-[var(--color-text-faint)]">
              Two models grade in parallel; disagreements surface per question.
            </span>
          </div>
          {error && (
            <div className="rounded-sm border border-[var(--color-accent-red,#ff6f6f)] bg-[var(--color-accent-red,#ff6f6f)]/10 p-2 text-[10px] text-[var(--color-accent-red,#ff6f6f)]">
              {error}
            </div>
          )}
        </form>
      )}

      {phase === "loading" && (
        <div className="rounded-sm border border-[var(--color-border-dim)] bg-[var(--color-bg-surface)]/60 p-3 text-[10px] tracking-[0.15em] text-[var(--color-text-dim)]">
          {result ? "PERSISTING…" : "WORKING…"}
        </div>
      )}

      {phase === "graded" && result && (
        <GradedResult result={result} onRetake={() => {
          setResult(null);
          setAnswers((prev) => {
            const reset = {};
            for (const qid of Object.keys(prev)) reset[qid] = "";
            return reset;
          });
          setError(null);
          setPhase("filling");
        }} />
      )}
    </div>
  );
}

/** One question's input. Hints multi-select via comma in placeholder. */
function AnswerInput({ qid, value, onChange }) {
  return (
    <label className="flex items-center gap-2 rounded-sm border border-[var(--color-border-dim)] bg-[var(--color-bg-base)]/60 px-2 py-1">
      <span className="font-mono text-[9px] tracking-[0.15em] text-[var(--color-text-dim)] w-7">
        {qid.toUpperCase()}
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="answer (e.g. B or B,D)"
        className="flex-1 bg-transparent text-[10px] text-[var(--color-text-primary)] outline-none placeholder:text-[var(--color-text-faint)]"
        autoComplete="off"
      />
    </label>
  );
}

function GradedResult({ result, onRetake }) {
  const { score, graded_by, questions, take_n } = result;
  const pct = score?.percent ?? 0;
  return (
    <div className="flex flex-col gap-2 rounded-sm border border-[var(--color-accent-amber)]/60 bg-[var(--color-bg-surface)]/80 p-3">
      <div className="flex items-baseline gap-3">
        <span className="text-[8px] tracking-[0.2em] text-[var(--color-accent-amber)]">
          TAKE {take_n} · SCORE
        </span>
        <span className="font-mono text-base text-[var(--color-text-primary)]">
          {score?.correct ?? 0} / {score?.total ?? 0}
        </span>
        <span className="font-mono text-[10px] text-[var(--color-text-dim)]">
          ({pct}%)
        </span>
        <button
          type="button"
          onClick={onRetake}
          className="ml-auto rounded-sm border border-[var(--color-border-dim)] bg-[var(--color-bg-surface)]/60 px-2 py-0.5 font-mono text-[8px] tracking-[0.2em] text-[var(--color-text-dim)] hover:border-[var(--color-accent-amber)] hover:text-[var(--color-accent-amber)]"
        >
          RETAKE
        </button>
      </div>
      <div className="text-[9px] tracking-[0.15em] text-[var(--color-text-faint)]">
        Primary: <span className="text-[var(--color-text-dim)]">{graded_by?.primary ?? "—"}</span>
        {graded_by?.secondary
          ? <>{" "}· Secondary: <span className="text-[var(--color-text-dim)]">{graded_by.secondary}</span></>
          : <>{" "}· Single-grader run</>}
      </div>
      <div className="mt-1 flex flex-col gap-1">
        {questions.map((q) => (
          <QuestionResult key={q.id} q={q} />
        ))}
      </div>
    </div>
  );
}

function QuestionResult({ q }) {
  const tint =
    q.grade === "correct"
      ? "text-[var(--color-accent-cyan)] border-[var(--color-accent-cyan)]/50"
      : q.grade === "partial"
        ? "text-[var(--color-accent-amber)] border-[var(--color-accent-amber)]/50"
        : "text-[var(--color-accent-red,#ff6f6f)] border-[var(--color-accent-red,#ff6f6f)]/50";
  const marker = q.grade === "correct" ? "✓" : q.grade === "partial" ? "~" : "✗";
  return (
    <div className={`rounded-sm border bg-[var(--color-bg-base)]/40 p-2 text-[10px] ${tint}`}>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[9px] tracking-[0.15em]">
          {q.id.toUpperCase()}
        </span>
        <span className="font-mono">{marker}</span>
        <span className="text-[var(--color-text-dim)]">
          your: <span className="text-[var(--color-text-primary)]">{formatAnswer(q.your_answer)}</span>
          {" "}· correct: <span className="text-[var(--color-text-primary)]">{formatAnswer(q.correct_answer)}</span>
        </span>
      </div>
      {(q.primary_reasoning || q.secondary_reasoning) && (
        <div className="mt-1 space-y-0.5 text-[9px] text-[var(--color-text-dim)]">
          {q.primary_reasoning && (
            <div><span className="text-[var(--color-text-faint)]">primary:</span> {q.primary_reasoning}</div>
          )}
          {q.secondary_reasoning && (
            <div><span className="text-[var(--color-text-faint)]">secondary:</span> {q.secondary_reasoning}</div>
          )}
        </div>
      )}
      {q.disagreement && (
        <div className="mt-1 text-[9px] text-[var(--color-accent-amber)]">
          ⚠ {q.disagreement}
        </div>
      )}
    </div>
  );
}

// --- helpers ------------------------------------------------------------

function byNaturalOrder(a, b) {
  // "q1" < "q2" < ... < "q10". Plain string sort would put q10 between q1 and q2.
  const ai = parseInt(a.replace(/\D/g, ""), 10);
  const bi = parseInt(b.replace(/\D/g, ""), 10);
  return ai - bi;
}

function normalizePayload(answers) {
  // Convert each value: split "B, D" → ["B","D"]; leave "B" alone.
  const out = {};
  for (const [qid, raw] of Object.entries(answers)) {
    const trimmed = (raw ?? "").trim();
    if (!trimmed) {
      out[qid] = "";
      continue;
    }
    if (trimmed.includes(",")) {
      out[qid] = trimmed.split(",").map((s) => s.trim()).filter(Boolean);
    } else {
      out[qid] = trimmed;
    }
  }
  return out;
}

function formatAnswer(value) {
  if (Array.isArray(value)) return value.join(", ");
  return value ?? "—";
}

function formatError(err) {
  if (err instanceof PracticeTestApiError) {
    const codeBit = err.code ? ` [${err.code}]` : "";
    return `${err.message}${codeBit}`;
  }
  return err?.message || String(err);
}
