"""Tests for script detection."""

from mtg.script import detect_script, matches_required_script, is_arabic_char


def test_detect_arabic():
    assert detect_script("مرحبا بالعالم") == "ar"
    assert detect_script("السلام عليكم") == "ar"


def test_detect_latin():
    assert detect_script("Hello world") == "latn"
    assert detect_script("Claude is here") == "latn"


def test_detect_mixed():
    assert detect_script("Hello مرحبا") == "mixed"


def test_detect_empty():
    assert detect_script("") == "empty"
    assert detect_script("   ") == "empty"
    assert detect_script("12345") == "empty"


def test_detect_hebrew():
    assert detect_script("שלום עולם") == "he"


def test_detect_persian_specific():
    # Persian specific letters pushes detection from ar to fa
    assert detect_script("چگونه هستید؟") == "fa"


def test_is_arabic_char():
    assert is_arabic_char("ا")
    assert is_arabic_char("ي")
    assert not is_arabic_char("a")
    assert not is_arabic_char("1")


def test_matches_required_script():
    assert matches_required_script("مرحبا", "ar")
    assert not matches_required_script("hello", "ar")
    assert matches_required_script("hello", "latn")
    assert matches_required_script("anything", "any")
    assert matches_required_script("", "ar")  # Empty is permissive
