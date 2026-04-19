"""Tests for mtg.repair — reconciled-mode repair primitives."""

from mtg.repair import (
    RepairSuggestion,
    arabizi_to_arabic_naive,
    pick_repaired_value,
    suggest_repairs,
)
from mtg.types import Analysis, GuardSpec, Violation


def test_arabizi_to_arabic_naive_digit_substitutions():
    # "a7jez" → ayn/hamza are digit subs, others are letter subs
    result = arabizi_to_arabic_naive("a7jez")
    # The `7` should have become ح
    assert "ح" in result
    # No latin characters should remain
    assert not any(c.isascii() and c.isalpha() for c in result)


def test_arabizi_to_arabic_naive_digraphs():
    result = arabizi_to_arabic_naive("sharik")
    assert "ش" in result  # sh digraph collapses to shin
    result2 = arabizi_to_arabic_naive("khobz")
    assert "خ" in result2
    result3 = arabizi_to_arabic_naive("ghaliya")
    assert "غ" in result3


def test_arabizi_to_arabic_naive_preserves_unicode():
    """Non-latin characters pass through unchanged."""
    assert arabizi_to_arabic_naive("أحمد") == "أحمد"


def test_arabizi_to_arabic_naive_empty():
    assert arabizi_to_arabic_naive("") == ""


def test_suggest_repairs_for_script_violation():
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "transliteration_allowed": False,
        "mode": "reconciled",
    })
    violations = [
        Violation(code="SCRIPT_VIOLATION", severity="high", phase="pre",
                  message="..."),
        Violation(code="TRANSLITERATION_VIOLATION", severity="high", phase="pre",
                  message="..."),
    ]
    analysis = Analysis(script_detected="latn")
    sugs = suggest_repairs("abi a7jez", spec, analysis, violations)
    actions = {s.action for s in sugs}
    assert "arabizi_to_arabic" in actions
    sug = next(s for s in sugs if s.action == "arabizi_to_arabic")
    assert sug.proposed is not None
    assert sug.needs_review is True


def test_suggest_repairs_for_canonical_required():
    spec = GuardSpec.from_dict({
        "slot_type": "action_verb",
        "script": "ar",
        "morphologically_productive": True,
        "canonicalization": "lemma",
        "canonical_form_required": True,
        "mode": "reconciled",
    })
    violations = [
        Violation(code="CANONICALIZATION_REQUIRED", severity="high", phase="pre",
                  message="..."),
    ]
    analysis = Analysis(script_detected="ar")
    sugs = suggest_repairs("أحجز", spec, analysis, violations)
    actions = {s.action for s in sugs}
    assert "attach_canonical" in actions
    sug = next(s for s in sugs if s.action == "attach_canonical")
    assert sug.proposed is not None  # normalized surface always derivable


def test_suggest_repairs_for_dialect_drift_is_advisory():
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "dialect_expected": "gulf",
        "mode": "reconciled",
    })
    violations = [
        Violation(code="DIALECT_DRIFT", severity="medium", phase="pre",
                  message="..."),
    ]
    analysis = Analysis(script_detected="ar", dialect_detected="egy", dialect_confidence=0.85)
    sugs = suggest_repairs("عايز أبعت", spec, analysis, violations)
    # Dialect rewrite is advisory — proposed is None
    dialect_sug = next(s for s in sugs if s.action == "suggest_dialect_rewrite")
    assert dialect_sug.proposed is None


def test_suggest_repairs_no_violations_returns_empty():
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "ar", "mode": "reconciled"})
    analysis = Analysis(script_detected="ar")
    assert suggest_repairs("أبي", spec, analysis, []) == []


def test_pick_repaired_value_prefers_arabic_reverse():
    suggestions = [
        RepairSuggestion(
            original="abi", proposed="أبي", action="arabizi_to_arabic",
            rationale="...",
        ),
        RepairSuggestion(
            original="abi", proposed=None, action="suggest_dialect_rewrite",
            rationale="...",
        ),
    ]
    assert pick_repaired_value("abi", suggestions) == "أبي"


def test_pick_repaired_value_returns_none_when_no_concrete_proposal():
    suggestions = [
        RepairSuggestion(
            original="x", proposed=None, action="suggest_dialect_rewrite",
            rationale="...",
        ),
    ]
    assert pick_repaired_value("x", suggestions) is None


def test_repair_suggestion_to_dict_round_trip():
    s = RepairSuggestion(
        original="abc", proposed="xyz", action="arabizi_to_arabic",
        rationale="...", needs_review=True, violation_code="SCRIPT_VIOLATION",
        details={"k": "v"},
    )
    d = s.to_dict()
    assert d["original"] == "abc"
    assert d["proposed"] == "xyz"
    assert d["action"] == "arabizi_to_arabic"
    assert d["violation_code"] == "SCRIPT_VIOLATION"
    assert d["details"] == {"k": "v"}


def test_guard_result_to_dict_includes_repairs():
    """Regression: GuardResult.to_dict must surface repairs for downstream
    receipt integration."""
    from mtg.pipeline import validate_pre

    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "transliteration_allowed": False,
        "mode": "reconciled",
    })
    result = validate_pre("abi a7jez", spec)
    d = result.to_dict()
    assert "repairs" in d
    assert any(r["action"] == "arabizi_to_arabic" for r in d["repairs"])
    assert d.get("repaired_surface") is not None
