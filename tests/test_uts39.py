"""Tests for the UTS #39 restriction-level and confusable-skeleton
module.

Two goals:
- Catch identifier-spoofing attacks (Cyrillic 'а' in 'paypal',
  Arabic-Indic digits in a numeric code).
- Never false-positive on natural Arabic/Persian prose carried by
  `free_text` or `named_entity` slots.
"""

from __future__ import annotations

import pytest

from mtg.pipeline import validate_pre
from mtg.types import GuardSpec
from mtg.uts39 import (
    analyze,
    applies_to,
    classify_restriction_level,
    confusable_codepoints,
    scripts_in,
    skeleton,
)


# ---------- script classification ----------


def test_scripts_in_pure_latin():
    assert scripts_in("paypal") == ("Latin",)


def test_scripts_in_pure_arabic():
    assert scripts_in("أحمد") == ("Arabic",)


def test_scripts_in_cyrillic_latin_mix():
    # Cyrillic 'а' smuggled into Latin "paypal"
    spoof = "p\u0430ypal"  # p + CYRILLIC SMALL A + ypal
    scripts = scripts_in(spoof)
    assert "Cyrillic" in scripts
    assert "Latin" in scripts


def test_scripts_in_ignores_common():
    """ASCII digits and punctuation are Common — don't count as a
    script for restriction-level purposes."""
    assert scripts_in("user-123!") == ("Latin",)


# ---------- restriction-level classification ----------


def test_ascii_only_level():
    assert classify_restriction_level("paypal") == "ascii_only"
    assert classify_restriction_level("user_123") == "ascii_only"


def test_single_script_arabic():
    assert classify_restriction_level("أحمد") == "single_script"


def test_single_script_cyrillic():
    assert classify_restriction_level("Москва") == "single_script"


def test_moderately_restrictive_latin_plus_cyrillic():
    spoof = "p\u0430ypal"
    assert classify_restriction_level(spoof) == "moderately_restrictive"


def test_minimally_restrictive_three_scripts():
    # Latin + Cyrillic + Greek
    value = "aа\u03b1"  # Latin a + Cyrillic а + Greek α
    assert classify_restriction_level(value) == "minimally_restrictive"


def test_empty_string_level():
    assert classify_restriction_level("") == "ascii_only"


# ---------- confusable detection ----------


def test_detects_cyrillic_a_in_paypal():
    spoof = "p\u0430ypal"
    conf = confusable_codepoints(spoof)
    assert len(conf) == 1
    assert conf[0] == "\u0430"


def test_arabic_indic_digits_are_confusable():
    conf = confusable_codepoints("\u0660\u0661\u0662")  # ٠١٢
    assert len(conf) == 3


def test_persian_digits_are_confusable():
    conf = confusable_codepoints("\u06F1\u06F2\u06F3")  # ۱۲۳
    assert len(conf) == 3


def test_plain_ascii_has_no_confusables():
    assert confusable_codepoints("hello") == ()


def test_natural_arabic_has_no_confusables():
    assert confusable_codepoints("أحمد محمود") == ()


# ---------- skeleton ----------


def test_skeleton_collapses_cyrillic_to_latin():
    spoof = "p\u0430ypal"  # с Cyrillic а
    assert skeleton(spoof) == "paypal"


def test_skeleton_normalizes_fullwidth():
    fullwidth = "\uFF50\uFF41\uFF59\uFF50\uFF41\uFF4C"  # ｐａｙｐａｌ
    assert skeleton(fullwidth) == "paypal"


def test_skeleton_collapses_arabic_indic_digits():
    assert skeleton("code-\u0660\u0661\u0662") == "code-012"


def test_skeleton_empty():
    assert skeleton("") == ""


def test_skeleton_identity_on_plain_ascii():
    assert skeleton("hello123") == "hello123"


# ---------- finding.is_suspicious ----------


def test_finding_benign_pure_ascii():
    f = analyze("paypal")
    assert not f.is_suspicious()


def test_finding_benign_pure_arabic():
    f = analyze("أحمد")
    assert not f.is_suspicious()


def test_finding_flags_cyrillic_spoof():
    f = analyze("p\u0430ypal")
    assert f.is_suspicious()


def test_finding_flags_arabic_indic_digits_in_numeric():
    f = analyze("\u0660\u0661\u0662\u0663")
    assert f.is_suspicious()


def test_finding_to_dict_shape():
    f = analyze("p\u0430ypal")
    d = f.to_dict()
    assert set(d.keys()) == {
        "restriction_level",
        "scripts",
        "confusable_codepoints",
        "skeleton",
    }
    assert d["skeleton"] == "paypal"
    assert len(d["confusable_codepoints"]) == 1
    entry = d["confusable_codepoints"][0]
    assert set(entry.keys()) == {"char", "codepoint", "prototype"}
    assert entry["prototype"] == "a"


# ---------- slot-type gate ----------


def test_gate_applies_to_identifier():
    assert applies_to("identifier")


def test_gate_applies_to_numeric():
    assert applies_to("numeric")


def test_gate_exempts_free_text():
    assert not applies_to("free_text")


def test_gate_exempts_named_entity():
    assert not applies_to("named_entity")


def test_gate_exempts_factorable_slots():
    assert not applies_to("action_verb")
    assert not applies_to("deverbal_noun")
    assert not applies_to("inflected_request_form")


# ---------- pipeline wire-up ----------


def test_pipeline_fires_on_cyrillic_spoof_in_identifier():
    spec = GuardSpec(
        slot_type="identifier",
        script="any",
    )
    result = validate_pre("p\u0430ypal", spec)
    codes = [v.code for v in result.violations]
    assert "UTS39_RESTRICTION_VIOLATION" in codes
    hit = next(v for v in result.violations if v.code == "UTS39_RESTRICTION_VIOLATION")
    # Confusable present → high severity
    assert hit.severity == "high"
    assert hit.phase == "pre"
    assert hit.details["skeleton"] == "paypal"


def test_pipeline_exempts_arabic_natural_text_in_named_entity():
    spec = GuardSpec(
        slot_type="named_entity",
        script="ar",
    )
    # A normal Arabic name — has only Arabic script, single_script would
    # pass anyway, but the slot-type gate means UTS #39 isn't even run.
    result = validate_pre("أحمد محمود", spec)
    codes = [v.code for v in result.violations]
    assert "UTS39_RESTRICTION_VIOLATION" not in codes


def test_pipeline_exempts_arabic_free_text_with_arabic_indic_digits():
    """Regression: a free_text slot carrying natural Arabic prose that
    HAPPENS to include Arabic-Indic digits ("في ٢٠٢٦") must not trigger
    UTS #39 — the digits are a confusable for numeric IDs, but in
    free_text they're just Arabic."""
    spec = GuardSpec(
        slot_type="free_text",
        script="ar",
    )
    result = validate_pre("في سنة ٢٠٢٦ سيحدث شيء جميل.", spec)
    codes = [v.code for v in result.violations]
    assert "UTS39_RESTRICTION_VIOLATION" not in codes


def test_pipeline_fires_on_arabic_indic_digits_in_numeric_slot():
    """Counterpart: the same Arabic-Indic digits in a numeric slot
    DO trigger — a numeric code that looks like "123" but is actually
    "۱۲۳" is a spoof."""
    spec = GuardSpec(
        slot_type="numeric",
        script="any",
    )
    result = validate_pre("\u06F1\u06F2\u06F3", spec)
    codes = [v.code for v in result.violations]
    assert "UTS39_RESTRICTION_VIOLATION" in codes


def test_pipeline_exempts_persian_name_in_named_entity():
    """Regression: Persian names use the Arabic script. They must not
    trip UTS #39 in named_entity / free_text slots."""
    spec = GuardSpec(
        slot_type="named_entity",
        script="fa",
    )
    result = validate_pre("محمدرضا پهلوی", spec)
    codes = [v.code for v in result.violations]
    assert "UTS39_RESTRICTION_VIOLATION" not in codes


def test_pipeline_pure_ascii_identifier_passes():
    spec = GuardSpec(
        slot_type="identifier",
        script="any",
    )
    result = validate_pre("paypal", spec)
    codes = [v.code for v in result.violations]
    assert "UTS39_RESTRICTION_VIOLATION" not in codes


def test_pipeline_pure_arabic_identifier_passes():
    """A pure-Arabic identifier is single_script — benign by UTS #39.
    (We don't care whether it's a "good idea" at the product level;
    the restriction level is what UTS #39 classifies.)"""
    spec = GuardSpec(
        slot_type="identifier",
        script="any",
    )
    result = validate_pre("أحمد", spec)
    codes = [v.code for v in result.violations]
    assert "UTS39_RESTRICTION_VIOLATION" not in codes
