"""Practice-test storage — one markdown file per generated test.

A practice test is a durable artifact in the vault: questions in the body
(rendered for the user), answer key in YAML frontmatter (visible to the
service, hidden by the UI's frontmatter strip), and graded takes appended
as ``## Take N`` sections after each grading run.

Why one file per test instead of a directory or a database:

- Tali can ``cat`` a test and see the full picture — questions, key,
  every prior take — at once. Same posture as ``state/active-quiz.md``.
- Obsidian's graph view treats each test as a node; future cross-linking
  to the vocab cards a test sourced from is trivial via ``[[wikilinks]]``.
- The test file is the source of truth for grading. The grading endpoint
  loads it, checks the answer key against the user's submission, writes
  the graded take back. No separate "submissions" table; submissions live
  inline in the file as ``## Take N`` blocks.

The frontmatter answer key uses a strict shape so the grader doesn't have
to guess at format. Multi-select answers (sentence equivalence) are lists;
single-select answers (text completion, problem solving) are strings.
Reading comprehension and data interpretation reuse the multi-/single-
select shape — the *kind* of question lives in ``sections``, not in the
answer shape.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# Where tests live within the vault. Created on first save.
_TESTS_DIR = ("knowledge", "gre", "practice-tests")
# Frontmatter fences and the take-section heading prefix.
_FENCE = "---"
_TAKE_HEADING_PREFIX = "## Take "


class PracticeTestError(Exception):
    """Raised when a test file is malformed or missing."""


@dataclass(frozen=True, slots=True)
class AnswerKey:
    """One canonical answer + its rubric note.

    ``answer`` is either a string (single-select) or a list of strings
    (multi-select for sentence equivalence). ``rubric`` is a short
    one-line note the grader passes back to the user with the grade —
    "B = conciliatory matches the desire to please both" — so the
    feedback is grounded in the test author's reasoning, not the
    grader's freelancing.
    """

    answer: str | list[str]
    rubric: str = ""


@dataclass(frozen=True, slots=True)
class Section:
    """One question section's metadata.

    ``kind`` is one of ``text_completion``, ``sentence_equivalence``,
    ``reading_comprehension``, ``problem_solving``, ``data_interpretation``.
    The set is open — adding a new question kind only requires updating the
    generation agent + grader prompt; storage is kind-agnostic.
    """

    kind: str
    n: int
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Take:
    """One graded submission of the test.

    ``answers`` are what the user sent. ``graded`` is the post-grading
    structure: one entry per question_id with the assigned grade and the
    two graders' reasoning + reconciliation. Stored on disk so revisits
    can show the original feedback, not just the score.
    """

    take_n: int
    submitted_at: datetime
    primary_grader: str
    secondary_grader: str | None
    answers: dict[str, Any]
    graded: list[dict[str, Any]]
    score_correct: int
    score_total: int
    notes: str = ""


@dataclass(slots=True)
class PracticeTest:
    """The whole thing — questions, key, sources, takes-to-date."""

    test_id: str
    created: datetime
    sections: list[Section]
    n_questions: int
    sources: dict[str, list[str]]  # {"vocab": [paths], "quant": [paths]}
    answer_key: dict[str, AnswerKey]  # keyed by question_id
    body: str  # the markdown the user sees (everything below frontmatter, above takes)
    takes: list[Take] = field(default_factory=list)
    path: Path | None = None  # absolute path on disk once saved

    @property
    def next_take_n(self) -> int:
        return (max((t.take_n for t in self.takes), default=0)) + 1


# --- (de)serialization helpers -------------------------------------------


def _serialize_answer(ak: AnswerKey) -> dict[str, Any]:
    return {"answer": ak.answer, "rubric": ak.rubric}


def _deserialize_answer(raw: Any) -> AnswerKey:
    if not isinstance(raw, dict):
        raise PracticeTestError(f"answer_key entry must be a mapping, got {type(raw).__name__}")
    answer = raw.get("answer")
    if not isinstance(answer, (str, list)):
        raise PracticeTestError("answer must be a string or list of strings")
    if isinstance(answer, list) and not all(isinstance(x, str) for x in answer):
        raise PracticeTestError("multi-select answer must be all strings")
    rubric = raw.get("rubric") if isinstance(raw.get("rubric"), str) else ""
    return AnswerKey(answer=answer, rubric=rubric)


def _serialize_section(s: Section) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": s.kind, "n": s.n}
    out.update(s.extras)
    return out


def _deserialize_section(raw: Any) -> Section:
    if not isinstance(raw, dict):
        raise PracticeTestError("section must be a mapping")
    kind = raw.get("kind")
    n = raw.get("n")
    if not isinstance(kind, str) or not isinstance(n, int):
        raise PracticeTestError("section missing required 'kind' and 'n'")
    extras = {k: v for k, v in raw.items() if k not in ("kind", "n")}
    return Section(kind=kind, n=n, extras=extras)


def _serialize_take(t: Take) -> dict[str, Any]:
    return {
        "take_n": t.take_n,
        "submitted_at": t.submitted_at.isoformat(),
        "primary_grader": t.primary_grader,
        "secondary_grader": t.secondary_grader,
        "score": {"correct": t.score_correct, "total": t.score_total},
        "answers": t.answers,
        "graded": t.graded,
        "notes": t.notes,
    }


def _render_take_section(t: Take) -> str:
    """One ``## Take N`` markdown block, appended to the test file on grade.

    Format intentionally mirrors what a person would read aloud: header
    with timestamp + score, a one-line grader summary, then a table per
    question. Stored alongside the YAML take block — the markdown is for
    humans, the YAML is the canonical record for the grade endpoint.
    """
    pct = (t.score_correct * 100 // t.score_total) if t.score_total else 0
    grader_line = f"Primary: ``{t.primary_grader}``"
    if t.secondary_grader:
        grader_line += f" + secondary: ``{t.secondary_grader}``"
    else:
        grader_line += " (secondary unavailable — single-grader run)"

    rows = []
    for q in t.graded:
        qid = q.get("id", "?")
        ans = q.get("your_answer", "")
        key = q.get("correct_answer", "")
        grade = q.get("grade", "?")
        marker = {"correct": "✓", "partial": "~", "wrong": "✗"}.get(grade, "?")
        note = ""
        if q.get("disagreement"):
            note = " ⚠ graders disagreed"
        rows.append(f"| {qid} | {ans} | {key} | {marker} {grade} |{note} |")

    table = (
        "| Q | Your answer | Correct | Grade | Notes |\n"
        "|---|-------------|---------|-------|-------|\n" + "\n".join(rows)
    )

    return (
        f"\n{_TAKE_HEADING_PREFIX}{t.take_n} — {t.submitted_at.isoformat()}\n\n"
        f"- Score: **{t.score_correct} / {t.score_total} ({pct}%)**\n"
        f"- {grader_line}\n\n"
        f"{table}\n"
    )


# --- store ---------------------------------------------------------------


class PracticeTestStore:
    """File-backed CRUD for practice tests. One file per ``test_id``.

    All operations are best-effort: ``load`` raises only on a malformed
    file (a missing one is None), ``save`` writes atomically. The store
    is bound to a single vault root; pass the QuizStateStore's pattern.
    """

    def __init__(self, vault_path: str | Path) -> None:
        self._vault = Path(vault_path)

    @property
    def vault_path(self) -> Path:
        return self._vault

    @property
    def tests_dir(self) -> Path:
        return self._vault.joinpath(*_TESTS_DIR)

    def path_for(self, test_id: str) -> Path:
        return self.tests_dir / f"{test_id}.md"

    def exists(self, test_id: str) -> bool:
        return self.path_for(test_id).is_file()

    def load(self, test_id: str) -> PracticeTest | None:
        path = self.path_for(test_id)
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        return self._parse(text, path=path)

    def save(self, test: PracticeTest) -> Path:
        """Atomically write a fresh test (no takes yet). Returns the path."""
        self.tests_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(test.test_id)
        rendered = self._render(test)
        self._atomic_write(path, rendered)
        test.path = path
        return path

    def append_take(self, test_id: str, take: Take) -> PracticeTest:
        """Append one graded take to a saved test. Returns the updated test.

        Reads → mutates in memory → atomic-replaces. Concurrent appends are
        last-writer-wins; the test markdown is the source of truth, so a
        late append simply lands later in the file with a higher ``take_n``.
        """
        test = self.load(test_id)
        if test is None:
            raise PracticeTestError(f"no such test: {test_id}")
        # Assign next take number from on-disk state, not the caller's, so
        # interleaved appends still produce a monotonic sequence.
        take.take_n = test.next_take_n
        test.takes.append(take)
        rendered = self._render(test)
        self._atomic_write(self.path_for(test_id), rendered)
        return test

    # --- internal -------------------------------------------------------

    def _render(self, test: PracticeTest) -> str:
        """Render the whole file: frontmatter + body + each take's markdown."""
        frontmatter = {
            "type": "gre-practice-test",
            "test_id": test.test_id,
            "created": test.created.isoformat(),
            "sections": [_serialize_section(s) for s in test.sections],
            "n_questions": test.n_questions,
            "sources": test.sources,
            "answer_key": {qid: _serialize_answer(ak) for qid, ak in test.answer_key.items()},
            "takes": [_serialize_take(t) for t in test.takes],
        }
        fm = yaml.safe_dump(
            frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
        body = test.body.rstrip() + "\n"
        takes_md = "".join(_render_take_section(t) for t in test.takes)
        return f"{_FENCE}\n{fm}{_FENCE}\n\n{body}{takes_md}"

    def _parse(self, text: str, *, path: Path) -> PracticeTest:
        if not text.startswith(_FENCE + "\n"):
            raise PracticeTestError(f"missing frontmatter fence in {path}")
        end = text.find("\n" + _FENCE, len(_FENCE) + 1)
        if end == -1:
            raise PracticeTestError(f"unterminated frontmatter in {path}")
        try:
            fm = yaml.safe_load(text[len(_FENCE) + 1 : end])
        except yaml.YAMLError as exc:
            raise PracticeTestError(f"bad frontmatter YAML in {path}: {exc}") from exc
        if not isinstance(fm, dict):
            raise PracticeTestError(f"frontmatter must be a mapping in {path}")

        test_id = fm.get("test_id")
        if not isinstance(test_id, str) or not test_id.strip():
            raise PracticeTestError("missing test_id")

        created_raw = fm.get("created")
        if isinstance(created_raw, datetime):
            created = created_raw
        elif isinstance(created_raw, str):
            try:
                created = datetime.fromisoformat(created_raw)
            except ValueError as exc:
                raise PracticeTestError(f"bad created: {created_raw!r}") from exc
        else:
            raise PracticeTestError("created missing or invalid")

        sections_raw = fm.get("sections", [])
        if not isinstance(sections_raw, list):
            raise PracticeTestError("sections must be a list")
        sections = [_deserialize_section(s) for s in sections_raw]

        n_questions = int(fm.get("n_questions", 0))
        sources = fm.get("sources") if isinstance(fm.get("sources"), dict) else {}

        key_raw = fm.get("answer_key", {})
        if not isinstance(key_raw, dict):
            raise PracticeTestError("answer_key must be a mapping")
        answer_key = {str(qid): _deserialize_answer(v) for qid, v in key_raw.items()}

        # Body: everything between closing fence and first ``## Take`` heading.
        rest = text[end + len(_FENCE) + 1 :]
        take_idx = rest.find("\n" + _TAKE_HEADING_PREFIX)
        body = rest if take_idx == -1 else rest[:take_idx]
        body = body.lstrip("\n")

        takes = [_deserialize_take(t) for t in fm.get("takes", [])] or []

        return PracticeTest(
            test_id=test_id,
            created=created,
            sections=sections,
            n_questions=n_questions,
            sources=sources,
            answer_key=answer_key,
            body=body,
            takes=takes,
            path=path,
        )

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _deserialize_take(raw: Any) -> Take:
    if not isinstance(raw, dict):
        raise PracticeTestError("take must be a mapping")
    submitted_raw = raw.get("submitted_at")
    if isinstance(submitted_raw, datetime):
        submitted = submitted_raw
    elif isinstance(submitted_raw, str):
        try:
            submitted = datetime.fromisoformat(submitted_raw)
        except ValueError as exc:
            raise PracticeTestError(f"bad submitted_at: {submitted_raw!r}") from exc
    else:
        raise PracticeTestError("take.submitted_at missing")
    score = raw.get("score") if isinstance(raw.get("score"), dict) else {}
    return Take(
        take_n=int(raw.get("take_n", 0)),
        submitted_at=submitted,
        primary_grader=str(raw.get("primary_grader", "")),
        secondary_grader=raw.get("secondary_grader")
        if isinstance(raw.get("secondary_grader"), str)
        else None,
        answers=raw.get("answers") if isinstance(raw.get("answers"), dict) else {},
        graded=raw.get("graded") if isinstance(raw.get("graded"), list) else [],
        score_correct=int(score.get("correct", 0)),
        score_total=int(score.get("total", 0)),
        notes=str(raw.get("notes", "")),
    )


# --- pure grading helpers (no I/O) ---------------------------------------


def normalize_answer(value: Any) -> str | list[str]:
    """Coerce any answer payload into the canonical ``str`` or ``[str, ...]`` shape.

    User submissions arrive as JSON; the UI may send a string for
    single-select, an array for multi-select, sometimes a comma-separated
    string ("B,D"). This helper makes the grader's comparison shape-stable
    so it doesn't have to handle every variant in the prompt.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        # Split "B, D" into ["B", "D"]; leave bare "B" alone.
        if "," in value:
            return [p.strip() for p in value.split(",") if p.strip()]
        return value.strip()
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return str(value).strip()


def compare_answers(
    user: str | list[str], canonical: str | list[str]
) -> str:
    """Return ``correct`` / ``partial`` / ``wrong`` from a shape-normalized pair.

    Rules:
    - Single-select: exact match (case-insensitive) → correct, else wrong.
    - Multi-select: full match → correct; one-of-two (sentence equivalence)
      → partial; otherwise wrong.
    - Sets compared by membership; order doesn't matter for multi-select.
    """
    def _norm(v: str | list[str]) -> set[str]:
        if isinstance(v, list):
            return {x.upper() for x in v}
        return {v.upper()} if v else set()

    u, c = _norm(user), _norm(canonical)
    if not u or not c:
        return "wrong"
    if u == c:
        return "correct"
    # Partial credit only when *both* sides are multi-select and there's a
    # non-empty proper subset relationship.
    if isinstance(canonical, list) and len(canonical) > 1 and u.issubset(c) and u:
        return "partial"
    return "wrong"
