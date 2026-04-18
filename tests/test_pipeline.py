"""Tests for the validation pipeline."""

import pytest

from mtg.pipeline import validate_pre, validate_post, run
from mtg.types import GuardSpec


def _gulf_spec(**overrides) -> GuardSpec:
    base = {
        "slot_type": "inflected_request_form",
        "script": "ar",
        "dialect_expected": "gulf",
        "dialect_enforcement": "preserve",
        "transliteration_allowed": False,
        "morphologically_productive": True,
        "canonicalization": "root_pattern",
        "mode": "advisory",
    }
    base.update(overrides)
    return GuardSpec.from_dict(base)


def test_valid_gulf_input_produces_no_high_violations():
    spec = _gulf_spec()
    result = validate_pre("أبي أحجز فندق في دبي", spec)
    severities = {v.severity for v in result.violations}
    assert "high" not in severities


def test_script_violation_when_latin_value():
    spec = _gulf_spec()
    result = validate_pre("abi a7jez funduq", spec)
    codes = {v.code for v in result.violations}
    assert "SCRIPT_VIOLATION" in codes


def test_transliteration_violation():
    # Force a parameter that expects Arabic but got Arabizi — must flag both
    spec = _gulf_spec()
    result = validate_pre("abi a7jez", spec)
    codes = {v.code for v in result.violations}
    assert "SCRIPT_VIOLATION" in codes
    # Transliteration violation only fires if script matched Latin and
    # transliteration_allowed is false; in this case latn script is detected
    # so the transliteration probe will fire on abi a7jez
    assert "TRANSLITERATION_VIOLATION" in codes


def test_dialect_drift_when_wrong_dialect():
    # Gulf expected, Egyptian supplied
    spec = _gulf_spec(dialect_enforcement="preserve")
    result = validate_pre("عايز أبعت رسالة دلوقتي", spec)
    codes = {v.code for v in result.violations}
    assert "DIALECT_DRIFT" in codes


def test_reconciled_mode_not_implemented():
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "ar", "mode": "reconciled"})
    with pytest.raises(NotImplementedError):
        validate_pre("أبي أحجز", spec)


def test_enforced_mode_not_implemented():
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "ar", "mode": "enforced"})
    with pytest.raises(NotImplementedError):
        validate_pre("أبي أحجز", spec)


def test_post_call_surface_corruption():
    spec = _gulf_spec(post_call_contract=["script_match", "no_surface_corruption"])
    pre = validate_pre("أبي أحجز فندق في دبي", spec)
    post = validate_post(pre, "Riyadh hotel booking", spec)
    codes = {v.code for v in post.violations}
    assert "SURFACE_CORRUPTION_POST_CALL" in codes


def test_post_call_preserved_response_no_post_violations():
    spec = _gulf_spec(post_call_contract=["script_match"])
    pre = validate_pre("أبي أحجز فندق في دبي", spec)
    post = validate_post(pre, "أبي أحجز فندق في دبي", spec)
    post_only = [v for v in post.violations if v.phase == "post"]
    assert post_only == []


def test_run_is_validate_pre_alias():
    spec = _gulf_spec()
    r1 = run("أبي أحجز", spec)
    r2 = validate_pre("أبي أحجز", spec)
    assert r1.surface == r2.surface
    assert len(r1.violations) == len(r2.violations)


def test_non_factorable_slot_no_morph_violations():
    spec = GuardSpec.from_dict({
        "slot_type": "named_entity",
        "script": "ar",
        "morphologically_productive": False,
        "mode": "advisory",
    })
    result = validate_pre("الرياض", spec)
    codes = {v.code for v in result.violations}
    assert "MORPH_CANONICALIZATION_FAILURE" not in codes
    assert "MORPH_AMBIGUITY" not in codes


def test_free_text_script_any_is_permissive():
    spec = GuardSpec.from_dict({
        "slot_type": "free_text",
        "script": "any",
        "mode": "advisory",
    })
    result = validate_pre("literally anything you want", spec)
    assert result.violations == ()
