"""Tests for dialect classifier."""

from mtg.dialect import KeywordDialectClassifier, get_dialect_backend


def test_keyword_gulf():
    clf = KeywordDialectClassifier()
    dialect, conf = clf.classify("أبي أحجز فندق في دبي بكرا")
    assert dialect == "gulf"
    assert conf > 0.55


def test_keyword_egyptian():
    clf = KeywordDialectClassifier()
    dialect, conf = clf.classify("عايز أبعت رسالة دلوقتي")
    assert dialect == "egy"
    assert conf > 0.55


def test_keyword_levantine():
    clf = KeywordDialectClassifier()
    dialect, conf = clf.classify("بدي أعرف قديش الوقت هلأ")
    assert dialect == "lev"
    assert conf > 0.55


def test_keyword_maghrebi():
    clf = KeywordDialectClassifier()
    dialect, conf = clf.classify("بغيت نشوف الأخبار")
    assert dialect == "maghrebi"
    assert conf > 0.55


def test_keyword_msa_default():
    clf = KeywordDialectClassifier()
    dialect, conf = clf.classify("ابحث عن رحلات من الرياض إلى جدة")
    assert dialect == "msa"
    # Low confidence because no dialect markers
    assert conf < 0.6


def test_empty_returns_unknown():
    clf = KeywordDialectClassifier()
    dialect, conf = clf.classify("")
    assert dialect == "unknown"
    assert conf == 0.0


def test_get_backend_returns_some_classifier():
    backend = get_dialect_backend()
    assert hasattr(backend, "classify")
    dialect, conf = backend.classify("أبي أحجز")
    assert dialect in {"gulf", "egy", "lev", "maghrebi", "msa", "unknown"}
    assert 0.0 <= conf <= 1.0
