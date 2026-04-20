"""Tests for mtg.trace — workflow-level grading."""

import json
from pathlib import Path

import pytest

from mtg.trace import (
    Rubric,
    Trace,
    Turn,
    grade_trace,
    load_ndjson,
    render_markdown,
)


def _trace(*turns: Turn, trace_id: str = "t1") -> Trace:
    return Trace(trace_id=trace_id, turns=list(turns),
                  metadata={"provider": "test", "model": "m"})


def test_trace_outcome_is_worst_turn_outcome():
    """Single bad turn fails the whole trace. Matches pass^k framing."""
    t = _trace(
        Turn(turn_id=0, outcome="pass"),
        Turn(turn_id=1, outcome="fail"),
        Turn(turn_id=2, outcome="pass"),
    )
    assert t.outcome == "fail"


def test_trace_outcome_ranks_error_worst():
    t = _trace(
        Turn(turn_id=0, outcome="pass"),
        Turn(turn_id=1, outcome="partial"),
        Turn(turn_id=2, outcome="error"),
    )
    assert t.outcome == "error"


def test_grade_default_rubric_passes_clean_trace():
    t = _trace(
        Turn(turn_id=0, outcome="pass"),
        Turn(turn_id=1, outcome="pass"),
    )
    result = grade_trace(t)
    assert result.outcome == "pass"
    assert result.failed_checks == []


def test_grade_rejects_too_many_hard_fail_turns():
    t = _trace(
        Turn(turn_id=0, outcome="pass"),
        Turn(turn_id=1, outcome="fail"),
    )
    result = grade_trace(t)
    assert result.outcome == "fail"
    assert any("hard_fail" in c for c in result.failed_checks)


def test_grade_respects_max_turns():
    t = _trace(*[Turn(turn_id=i, outcome="pass") for i in range(6)])
    result = grade_trace(t, Rubric(max_turns=3))
    assert result.outcome == "fail"
    assert any("too_many_turns" in c for c in result.failed_checks)


def test_grade_rejects_final_turn_failure_by_default():
    t = _trace(
        Turn(turn_id=0, outcome="pass"),
        Turn(turn_id=1, outcome="pass"),
        Turn(turn_id=2, outcome="fail"),
    )
    result = grade_trace(t)
    assert result.outcome == "fail"
    assert any("final_turn_failed" in c for c in result.failed_checks)


def test_grade_allows_failure_when_final_success_not_required():
    """Override: Rubric(require_final_success=False)."""
    t = _trace(
        Turn(turn_id=0, outcome="pass"),
        Turn(turn_id=1, outcome="pass"),
        Turn(turn_id=2, outcome="fail"),
    )
    # Allow one hard-fail AND don't require final success
    result = grade_trace(t, Rubric(
        max_hard_fail_turns=1, require_final_success=False,
    ))
    assert result.outcome == "pass"


def test_grade_rejects_forbidden_violation_codes():
    """Violations like BIDI_CONTROL_SMUGGLING / PROMPT_INJECTION are
    security-critical — any occurrence fails the trace by default."""
    t = _trace(
        Turn(turn_id=0, outcome="partial", violations=[
            {"code": "BIDI_CONTROL_SMUGGLING", "severity": "high",
             "phase": "pre", "message": "..."},
        ]),
        Turn(turn_id=1, outcome="pass"),
    )
    result = grade_trace(t)
    assert result.outcome == "fail"
    assert any("forbidden_violations_present" in c for c in result.failed_checks)


def test_grade_forbid_tool_catches_unsafe_call():
    """Rubric-level forbidden_tools: agent must not call delete_account.
    Useful for abstention rubrics."""
    t = _trace(
        Turn(turn_id=0, outcome="pass", tool_calls=[
            {"function": "delete_account", "arguments": {}}
        ]),
    )
    result = grade_trace(t, Rubric(
        forbidden_tools=("delete_account",),
    ))
    assert result.outcome == "fail"
    assert any("forbidden_tools_called" in c for c in result.failed_checks)


def test_grade_require_tool_catches_missing_call():
    """Rubric-level required_tools: agent must call search_flights."""
    t = _trace(
        Turn(turn_id=0, outcome="pass", tool_calls=[
            {"function": "book_hotel", "arguments": {}}
        ]),
    )
    result = grade_trace(t, Rubric(
        required_tools=("search_flights",),
    ))
    assert result.outcome == "fail"
    assert any("required_tools_missing" in c for c in result.failed_checks)


def test_trace_round_trips_through_json():
    t = _trace(
        Turn(turn_id=0, instruction="أريد حجز فندق",
             tool_calls=[{"function": "book_hotel", "arguments": {"city": "الرياض"}}],
             violations=[{"code": "SCRIPT_VIOLATION", "severity": "high",
                           "phase": "pre", "message": "bad"}],
             outcome="partial"),
    )
    payload = t.to_dict()
    restored = Trace.from_dict(payload)
    assert restored.trace_id == t.trace_id
    assert restored.turns[0].outcome == "partial"
    assert restored.turns[0].violations[0]["code"] == "SCRIPT_VIOLATION"


def test_load_ndjson_reads_multiple_traces(tmp_path: Path):
    ndjson = tmp_path / "chain.ndjson"
    t1 = _trace(Turn(turn_id=0, outcome="pass"), trace_id="t1")
    t2 = _trace(Turn(turn_id=0, outcome="fail"), trace_id="t2")
    ndjson.write_text(
        json.dumps(t1.to_dict()) + "\n" + json.dumps(t2.to_dict()) + "\n",
        encoding="utf-8",
    )
    loaded = load_ndjson(ndjson)
    assert [t.trace_id for t in loaded] == ["t1", "t2"]


def test_render_markdown_includes_turn_details():
    t = _trace(
        Turn(turn_id=0, instruction="test instruction",
             outcome="pass", tool_calls=[{"function": "book_hotel", "arguments": {"city": "الرياض"}}]),
    )
    md = render_markdown(t)
    assert "test instruction" in md
    assert "book_hotel" in md
    assert "الرياض" in md


def test_render_markdown_surfaces_grading():
    t = _trace(Turn(turn_id=0, outcome="fail"))
    grading = grade_trace(t)
    md = render_markdown(t, grading)
    assert "❌ fail" in md
    assert "hard_fail" in md
