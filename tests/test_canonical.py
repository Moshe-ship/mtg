"""Tests for canonicalization."""

from mtg.canonical import canonicalize, normalize, strip_diacritics
from mtg.types import Analysis


def test_normalize_alef_variants():
    assert normalize("أحمد") == normalize("احمد")
    assert normalize("إبراهيم") == normalize("ابراهيم")
    assert normalize("آية") == normalize("اية")


def test_normalize_ya():
    assert normalize("مكتبى") == normalize("مكتبي")


def test_normalize_ta_marbuta():
    assert normalize("فاطمة") == normalize("فاطمه")


def test_normalize_strips_tatweel():
    assert normalize("مــرحبا") == "مرحبا"


def test_strip_diacritics():
    with_harakat = "بِسْمِ اللَّهِ"
    without = strip_diacritics(with_harakat)
    assert "\u064B" not in without
    assert "\u064F" not in without
    assert "م" in without  # non-diacritic Arabic letters survive


def test_canonicalize_none_returns_surface():
    text, ok = canonicalize("أبي أحجز", "none", [])
    assert text == "أبي أحجز"
    assert ok is True


def test_canonicalize_normalized_applies_normalization():
    text, ok = canonicalize("أبي أحجز", "normalized", [])
    assert text == normalize("أبي أحجز")
    assert ok is True


def test_canonicalize_root_pattern_without_analysis_falls_back():
    text, ok = canonicalize("أبي أحجز", "root_pattern", [])
    assert ok is False
    assert text == normalize("أبي أحجز")


def test_canonicalize_root_pattern_with_analysis():
    analysis = Analysis(root="ح-ج-ز", pattern="Form-I-imperfect")
    text, ok = canonicalize("أحجز", "root_pattern", [analysis])
    assert ok is True
    assert text == "ح-ج-ز/Form-I-imperfect"


def test_canonicalize_lemma_with_analysis():
    analysis = Analysis(lemma="حجز")
    text, ok = canonicalize("أحجز", "lemma", [analysis])
    assert ok is True
    assert text == "حجز"
