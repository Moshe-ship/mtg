"""Tests for Arabizi / transliteration detection."""

from mtg.translit import looks_like_arabizi, transliteration_violation_detected


def test_arabizi_digits():
    assert looks_like_arabizi("abi a7jez funduq")
    assert looks_like_arabizi("marhaba 3aleykum")


def test_arabizi_markers():
    assert looks_like_arabizi("yalla habibi")
    assert looks_like_arabizi("inshallah")


def test_plain_english_not_arabizi():
    assert not looks_like_arabizi("hello world")
    assert not looks_like_arabizi("i want to book a hotel")


def test_arabic_script_not_arabizi():
    # Arabic-script text is never flagged as Arabizi (wrong script probe)
    assert not looks_like_arabizi("أبي أحجز")


def test_empty_not_arabizi():
    assert not looks_like_arabizi("")


def test_violation_detected_when_not_allowed():
    assert transliteration_violation_detected("abi a7jez", "ar", allowed=False)


def test_violation_not_flagged_when_allowed():
    assert not transliteration_violation_detected("abi a7jez", "ar", allowed=True)


def test_violation_not_flagged_for_latn_script():
    assert not transliteration_violation_detected("abi a7jez", "latn", allowed=False)
