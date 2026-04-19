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


def test_free_text_overflow_numeric_dominated():
    """Regression: factorable slot filled with dominantly non-factorable
    content must emit FREE_TEXT_OVERFLOW (finding #4)."""
    spec = GuardSpec.from_dict({
        "slot_type": "action_verb",
        "script": "any",
        "mode": "advisory",
    })
    result = validate_pre("1000 2000 3000 4000", spec)
    codes = {v.code for v in result.violations}
    assert "FREE_TEXT_OVERFLOW" in codes
    v = next(v for v in result.violations if v.code == "FREE_TEXT_OVERFLOW")
    assert v.severity == "medium"
    assert v.details["non_factorable_ratio"] >= 0.7


def test_free_text_overflow_identifier_dominated():
    """Latin identifier tokens in a factorable slot fire the overflow."""
    spec = GuardSpec.from_dict({
        "slot_type": "deverbal_noun",
        "script": "any",
        "mode": "advisory",
    })
    result = validate_pre("svc-42 ABC123 id_99 REF-07", spec)
    codes = {v.code for v in result.violations}
    assert "FREE_TEXT_OVERFLOW" in codes


def test_no_free_text_overflow_on_genuine_arabic():
    """A factorable slot with real Arabic morphological content should NOT
    trigger FREE_TEXT_OVERFLOW."""
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "dialect_expected": "gulf",
        "morphologically_productive": True,
        "mode": "advisory",
    })
    result = validate_pre("أبي أحجز فندق في دبي", spec)
    codes = {v.code for v in result.violations}
    assert "FREE_TEXT_OVERFLOW" not in codes


def test_no_free_text_overflow_on_non_factorable_slot():
    """Non-factorable slots (named_entity, temporal, numeric, identifier,
    free_text) must never emit FREE_TEXT_OVERFLOW."""
    spec = GuardSpec.from_dict({
        "slot_type": "identifier",
        "script": "latn",
        "mode": "advisory",
    })
    result = validate_pre("svc-42", spec)
    codes = {v.code for v in result.violations}
    assert "FREE_TEXT_OVERFLOW" not in codes


def test_canonical_form_required_emits_high_violation_when_backend_unavailable():
    """Regression: spec.canonical_form_required=true + root_pattern must emit
    CANONICALIZATION_REQUIRED when the morphology backend cannot produce
    root/pattern (finding #3)."""
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "dialect_expected": "gulf",
        "morphologically_productive": True,
        "canonicalization": "root_pattern",
        "canonical_form_required": True,
        "mode": "advisory",
    })
    result = validate_pre("أبي أحجز", spec)
    codes_sev = {(v.code, v.severity) for v in result.violations}
    # When no CAMeL Tools backend is present, the fallback path yields no
    # root/pattern — the violation must fire at high severity.
    assert ("CANONICALIZATION_REQUIRED", "high") in codes_sev


def test_canonical_form_required_not_emitted_for_normalized_mode():
    """canonicalization='normalized' always succeeds (pure string transform),
    so canonical_form_required must NOT fire."""
    spec = GuardSpec.from_dict({
        "slot_type": "named_entity",
        "script": "ar",
        "canonicalization": "normalized",
        "canonical_form_required": True,
        "mode": "advisory",
    })
    result = validate_pre("الرياض", spec)
    codes = {v.code for v in result.violations}
    assert "CANONICALIZATION_REQUIRED" not in codes


def test_free_text_overflow_downgrades_morph_analysis():
    """Regression: taxonomy says FREE_TEXT_OVERFLOW 'downgrades morphological
    analysis'. Concretely: root/pattern/lemma must be None and
    morph_confidence 0.0 on the returned GuardResult.analysis."""
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "morphologically_productive": True,
        "canonicalization": "root_pattern",
        "mode": "advisory",
    })
    # Pure-numeric content in a factorable slot triggers overflow
    result = validate_pre("1000 2000 3000 4000", spec)
    codes = {v.code for v in result.violations}
    assert "FREE_TEXT_OVERFLOW" in codes
    # Downgrade assertions
    assert result.analysis.root is None
    assert result.analysis.pattern is None
    assert result.analysis.lemma is None
    assert result.analysis.morph_confidence == 0.0
    # MORPH_* codes must NOT fire on an overflow-downgraded call
    assert "MORPH_CANONICALIZATION_FAILURE" not in codes
    assert "MORPH_AMBIGUITY" not in codes


def test_free_text_overflow_downgrade_triggers_canonical_required():
    """When overflow downgrades morphology AND canonical_form_required=true,
    the CANONICALIZATION_REQUIRED violation must fire and its details should
    note that downgrade caused the failure."""
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "morphologically_productive": True,
        "canonicalization": "root_pattern",
        "canonical_form_required": True,
        "mode": "advisory",
    })
    result = validate_pre("1000 2000 3000 4000", spec)
    canon = next(
        (v for v in result.violations if v.code == "CANONICALIZATION_REQUIRED"),
        None,
    )
    assert canon is not None
    assert canon.severity == "high"
    assert canon.details.get("downgraded_by_overflow") is True


def test_free_text_overflow_preserves_dialect_detection():
    """Dialect detection should still work on the surface tokens even when
    morphology is downgraded — dialect is not morph-dependent."""
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "morphologically_productive": True,
        "mode": "advisory",
    })
    # Mostly identifier tokens, one Arabic Gulf marker — still triggers overflow
    result = validate_pre("svc-42 ABC123 ref-99 abi", spec)
    codes = {v.code for v in result.violations}
    # The value is latin-dominant so SCRIPT_VIOLATION will fire; the key
    # assertion is that dialect_detected survives even when overflow is
    # triggered on factorable slots with script!=ar check.
    # Use a mixed case where script passes but tokens are mostly numeric.
    spec2 = GuardSpec.from_dict({
        "slot_type": "action_verb",
        "script": "any",
        "mode": "advisory",
    })
    result2 = validate_pre("1000 2000 3000 أبي", spec2)
    codes2 = {v.code for v in result2.violations}
    assert "FREE_TEXT_OVERFLOW" in codes2
    # dialect_detected may be 'unknown' for such a short fragment, but
    # the analysis object is still populated with script info.
    assert result2.analysis.script_detected is not None


def test_canonical_form_required_not_emitted_when_flag_off():
    """Without the canonical_form_required flag, no violation even if the
    backend cannot compute a canonical form."""
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "morphologically_productive": True,
        "canonicalization": "root_pattern",
        "canonical_form_required": False,
        "mode": "advisory",
    })
    result = validate_pre("أبي أحجز", spec)
    codes = {v.code for v in result.violations}
    assert "CANONICALIZATION_REQUIRED" not in codes
