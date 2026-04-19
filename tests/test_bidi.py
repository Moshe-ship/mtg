"""Security tests for the BiDi / RTL violation family.

Covers CVE-2021-42574 ("Trojan Source"), homoglyph script laundering,
invisible-character padding, and Unicode TAG-character prompt injection
at the tool-argument level.
"""

import pytest

from mtg.bidi import (
    BidiFinding,
    detect_bidi_threats,
    rewrite_homoglyphs,
    strip_bidi,
)
from mtg.pipeline import validate_pre
from mtg.types import GuardSpec


# ---------- primitive detection ----------


def test_detects_rlo_override():
    """U+202E Right-to-Left Override is the Trojan Source pivot."""
    attack = "admin\u202elogin"
    finding = detect_bidi_threats(attack)
    assert finding.bidi_controls == ("\u202e",)
    assert finding.any()


def test_detects_lre_rle_pdf():
    """All explicit-embedding controls flag."""
    for ch in ("\u202a", "\u202b", "\u202c", "\u202d", "\u202e"):
        f = detect_bidi_threats(f"x{ch}y")
        assert ch in f.bidi_controls


def test_detects_isolate_controls():
    """Isolate controls U+2066..U+2069 also flag."""
    for ch in ("\u2066", "\u2067", "\u2068", "\u2069"):
        f = detect_bidi_threats(f"x{ch}y")
        assert ch in f.bidi_controls


def test_detects_zero_width_padding():
    """ZWSP (U+200B) and WJ (U+2060) always flag. ZWNJ/ZWJ are
    deliberately excluded — they are legitimate in Persian, Urdu, Hindi,
    Thai, and emoji sequences."""
    f = detect_bidi_threats("a\u200bb\u2060c\ufeffd\u00ade")
    assert len(f.invisible_chars) == 4
    # ZWSP, WJ, BOM, SHY all detected


def test_zwnj_not_flagged_as_invisible():
    """ZWNJ (U+200C) is a standard Persian orthographic character —
    flagging it would wreck every Persian tool call."""
    persian = "می‌خواهم پرواز رزرو کنم"  # contains U+200C between می and خواهم
    assert "\u200c" in persian
    f = detect_bidi_threats(persian)
    assert f.invisible_chars == ()


def test_zwj_not_flagged_as_invisible():
    """ZWJ (U+200D) is legitimate in Devanagari and emoji sequences."""
    f = detect_bidi_threats("family \U0001f468\u200d\U0001f469\u200d\U0001f466")
    assert f.invisible_chars == ()


def test_detects_bom():
    f = detect_bidi_threats("\ufeffpayload")
    assert "\ufeff" in f.invisible_chars


def test_detects_unicode_tag_characters():
    """Tag characters (U+E0020..U+E007F) are used in LLM prompt-injection."""
    # "hi" encoded with tag chars to smuggle invisible payload
    attack = "ok\U000e0068\U000e0069\U000e007f"
    f = detect_bidi_threats(attack)
    assert len(f.tag_chars) == 3  # h + i + cancel-tag


def test_detects_cyrillic_homoglyphs():
    """Classic 'аdmin' with Cyrillic 'а' (U+0430) vs Latin 'a'."""
    attack = "\u0430dmin"
    f = detect_bidi_threats(attack)
    assert len(f.homoglyphs) == 1
    assert f.homoglyphs[0] == ("\u0430", "a")


def test_detects_arabic_indic_digit_homoglyph_in_latin_context():
    """Arabic-Indic '٠' U+0660 vs Western '0' U+0030 — IS a homoglyph
    attack when the surrounding context is Latin (laundering)."""
    f = detect_bidi_threats("acct\u0660\u0661\u0662")  # "acct" Latin + ٠١٢
    assert len(f.homoglyphs) == 3


def test_arabic_indic_digits_in_arabic_context_are_not_homoglyphs():
    """Regression from scripts/fp_analysis.py: Arabic-Indic digits in
    Arabic-dominant content are normal typography, not attacks.
    `الساعة ٥` is an Arabic phrase, not a script-laundering payload."""
    # Real Arabic phrases with Arabic-Indic digits
    for phrase in [
        "الساعة ٥",
        "١٥ رمضان",
        "تعالى بكره الساعة ٥",
        "احجز فندق من يوم ١٥ رمضان إلى ٢٠ رمضان",
    ]:
        f = detect_bidi_threats(phrase)
        assert f.homoglyphs == (), (
            f"Arabic-Indic digits in Arabic context should not flag: {phrase!r} "
            f"got {f.homoglyphs}"
        )


def test_persian_digits_in_persian_context_are_not_homoglyphs():
    """Same principle for Persian digits U+06F0..U+06F9."""
    phrase = "ساعت \u06f5 بعدازظهر"  # "ساعت ۵ بعدازظهر" — 5 PM
    f = detect_bidi_threats(phrase)
    assert f.homoglyphs == ()


def test_detects_mixed_script_within_token():
    """'admin' with one Cyrillic letter embedded should flag as mixed."""
    f = detect_bidi_threats("\u0430dmin")  # Cyrillic а + Latin dmin
    assert f.mixed_script_within_token is True


def test_arabic_with_latin_url_not_flagged_as_mixed():
    """Legitimate Arabic+URL (cross-token) must not be mixed-script flagged."""
    f = detect_bidi_threats("أبي أحجز https://example.com")
    assert f.mixed_script_within_token is False


def test_clean_arabic_returns_empty_finding():
    f = detect_bidi_threats("أبي أحجز فندق في دبي")
    assert not f.any()


def test_clean_latin_returns_empty_finding():
    f = detect_bidi_threats("Hello world")
    assert not f.any()


def test_empty_string_returns_empty_finding():
    assert not detect_bidi_threats("").any()


# ---------- pipeline integration ----------


def test_bidi_violations_fire_on_any_slot():
    """BiDi controls flag regardless of declared script — security first."""
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "any", "mode": "advisory"})
    result = validate_pre("admin\u202elogin", spec)
    codes = {v.code for v in result.violations}
    assert "BIDI_CONTROL_SMUGGLING" in codes
    # Severity must be high
    bidi_v = next(v for v in result.violations if v.code == "BIDI_CONTROL_SMUGGLING")
    assert bidi_v.severity == "high"


def test_bidi_violations_fire_on_arabic_slot():
    """Attackers may target Arabic-declared slots with BiDi overrides."""
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "ar", "mode": "advisory"})
    result = validate_pre("أبي\u202e أحجز", spec)
    codes = {v.code for v in result.violations}
    assert "BIDI_CONTROL_SMUGGLING" in codes


def test_invisible_content_medium_severity():
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "any", "mode": "advisory"})
    result = validate_pre("ok\u200b\u200cdata", spec)
    v = next(v for v in result.violations if v.code == "INVISIBLE_CONTENT")
    assert v.severity == "medium"


def test_homoglyph_attack_on_identifier_slot():
    """Identifier slot with Cyrillic homoglyph — SCRIPT_HOMOGLYPH + SCRIPT_VIOLATION
    both fire, since the slot declared latn but value has Cyrillic."""
    spec = GuardSpec.from_dict({"slot_type": "identifier", "script": "latn", "mode": "advisory"})
    result = validate_pre("\u0430dmin-42", spec)
    codes = {v.code for v in result.violations}
    assert "SCRIPT_HOMOGLYPH" in codes


def test_tag_character_smuggling_flagged():
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "any", "mode": "advisory"})
    result = validate_pre("visible\U000e0068idden", spec)
    codes = {v.code for v in result.violations}
    assert "BIDI_CONTROL_SMUGGLING" in codes


def test_clean_value_no_bidi_violations():
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "ar", "mode": "advisory"})
    result = validate_pre("أبي أحجز فندق في دبي", spec)
    codes = {v.code for v in result.violations}
    assert "BIDI_CONTROL_SMUGGLING" not in codes
    assert "INVISIBLE_CONTENT" not in codes
    assert "SCRIPT_HOMOGLYPH" not in codes


# ---------- transformations ----------


def test_strip_bidi_removes_controls_and_invisible():
    attack = "admin\u202elogin\u200b"
    assert strip_bidi(attack) == "adminlogin"


def test_strip_bidi_removes_tag_chars():
    attack = "visible\U000e0068idden"
    assert strip_bidi(attack) == "visibleidden"


def test_strip_bidi_preserves_legitimate_arabic():
    value = "أبي أحجز فندق في دبي"
    assert strip_bidi(value) == value


def test_rewrite_homoglyphs_maps_cyrillic_to_latin():
    attack = "\u0430dmin"
    assert rewrite_homoglyphs(attack) == "admin"


def test_rewrite_homoglyphs_maps_arabic_indic_digits():
    attack = "account \u0660\u0661\u0662"
    assert rewrite_homoglyphs(attack) == "account 012"


def test_rewrite_homoglyphs_preserves_unrelated_chars():
    value = "normal text 123"
    assert rewrite_homoglyphs(value) == value


# ---------- integrity — verify BiDi violations are captured in receipts ----------


def test_bidi_violations_end_to_end_receipt_flow():
    """Regression: BiDi violations must flow through GuardResult.to_dict()
    so the ToolProof bridge captures them in receipts."""
    spec = GuardSpec.from_dict({"slot_type": "free_text", "script": "any", "mode": "advisory"})
    result = validate_pre("admin\u202elogin", spec)
    serialized = result.to_dict()
    codes = {v["code"] for v in serialized["pre_call_violations"]}
    assert "BIDI_CONTROL_SMUGGLING" in codes
    # Details include codepoints so SOC/auditors can investigate
    bidi_violation = next(
        v for v in serialized["pre_call_violations"]
        if v["code"] == "BIDI_CONTROL_SMUGGLING"
    )
    assert "codepoints" in bidi_violation["details"]
    assert "0x202e" in bidi_violation["details"]["codepoints"]
