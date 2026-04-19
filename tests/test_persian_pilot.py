"""Persian (Farsi) non-Arabic pilot.

Proves the MTG primitive travels beyond Arabic without adding
language-specific code. Uses `script: "fa"` — the detector already
distinguishes Persian from Arabic via the Persian-specific letters
پ چ ژ گ (U+067E U+0686 U+0698 U+06AF). Dataset: 10 Persian items in
datasets/persian_v1.jsonl. Tool schema: examples/book_flight_persian.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtg.adapters.openai import guard_tool
from mtg.pipeline import validate_pre
from mtg.script import detect_script
from mtg.types import GuardSpec


ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "datasets" / "persian_v1.jsonl"
TOOL = ROOT / "examples" / "book_flight_persian.json"


def _load_items():
    with DATASET.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_dataset_exists_with_10_items():
    items = _load_items()
    assert len(items) == 10
    assert all(item["language"] == "fa" for item in items)


def test_every_persian_item_declares_fa_script():
    items = _load_items()
    for item in items:
        assert item["x_mtg"]["script"] == "fa", f"{item['id']} missing script=fa"


@pytest.mark.parametrize(
    "persian_value,expected_script",
    [
        ("پارسی", "fa"),
        ("چطوری", "fa"),
        ("ژاله", "fa"),
        ("گل سرخ", "fa"),
        ("می‌خواهم پرواز رزرو کنم", "fa"),
    ],
)
def test_persian_specific_chars_trigger_fa_detection(persian_value, expected_script):
    """Persian-specific letters (پ چ ژ گ) identify the value as Farsi,
    not Arabic — this is the whole point of declaring script='fa'."""
    assert detect_script(persian_value) == expected_script


def test_persian_value_in_arabic_slot_flags_script_violation():
    """A Persian value in a slot that declared script='ar' must fail —
    otherwise Arabic-only validation would wrongly accept Persian.
    This is the 'script alone is not enough' thesis made concrete."""
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "ar",
        "mode": "advisory",
    })
    result = validate_pre("می‌خواهم پرواز رزرو کنم", spec)
    codes = {v.code for v in result.violations}
    assert "SCRIPT_VIOLATION" in codes


def test_persian_value_in_persian_slot_passes():
    """Correct Persian value in a Persian slot — clean pass."""
    spec = GuardSpec.from_dict({
        "slot_type": "inflected_request_form",
        "script": "fa",
        "mode": "advisory",
    })
    result = validate_pre("می‌خواهم پرواز رزرو کنم", spec)
    high_severity = [v for v in result.violations if v.severity == "high"]
    assert high_severity == []


def test_persian_tool_schema_validates_clean_call():
    """book_flight_persian.json → Persian call with Persian cities → pass."""
    tool = json.loads(TOOL.read_text(encoding="utf-8"))
    wrapped = guard_tool(tool)
    report = wrapped.validate_call({
        "arguments": {
            "intent_phrase": "می‌خواهم پرواز از تهران به مشهد رزرو کنم",
            "origin_city": "تهران",
            "destination_city": "مشهد",
            "flight_class": "economy",
        }
    })
    assert not report.has_violations


def test_persian_tool_schema_catches_english_value_in_city_slot():
    """Latin value where Persian was declared — SCRIPT_VIOLATION fires."""
    tool = json.loads(TOOL.read_text(encoding="utf-8"))
    wrapped = guard_tool(tool)
    report = wrapped.validate_call({
        "arguments": {
            "intent_phrase": "می‌خواهم پرواز رزرو کنم",
            "origin_city": "Tehran",  # Persian slot, Latin value
            "destination_city": "مشهد",
            "flight_class": "economy",
        }
    })
    origin_codes = {v.code for v in report.per_param["origin_city"].violations}
    assert "SCRIPT_VIOLATION" in origin_codes


def test_persian_slot_accepts_pure_arabic_as_subset():
    """Design decision: Persian uses Arabic script as a strict superset,
    so a value without Persian-specific letters (پ چ ژ گ) but in the
    Arabic block is a valid Persian surface. matches_required_script('fa')
    therefore accepts detected 'ar'. This is the honest script-level
    story — distinguishing Persian from Arabic when neither has
    Persian-specific letters requires DIALECT / MORPHOLOGY, not script."""
    tool = json.loads(TOOL.read_text(encoding="utf-8"))
    wrapped = guard_tool(tool)
    report = wrapped.validate_call({
        "arguments": {
            "intent_phrase": "أريد السفر",  # pure Arabic, no پ چ ژ گ
            "origin_city": "تهران",
            "destination_city": "مشهد",
            "flight_class": "economy",
        }
    })
    intent_codes = {v.code for v in report.per_param["intent_phrase"].violations}
    # No SCRIPT_VIOLATION — pure Arabic-block is a legitimate Persian subset
    assert "SCRIPT_VIOLATION" not in intent_codes


def test_persian_slot_rejects_latin_value():
    """But Latin content in a Persian slot must still fail — script
    semantics only widen 'fa' to include 'ar', not other scripts."""
    tool = json.loads(TOOL.read_text(encoding="utf-8"))
    wrapped = guard_tool(tool)
    report = wrapped.validate_call({
        "arguments": {
            "intent_phrase": "I want to travel",
            "origin_city": "تهران",
            "destination_city": "مشهد",
            "flight_class": "economy",
        }
    })
    intent_codes = {v.code for v in report.per_param["intent_phrase"].violations}
    assert "SCRIPT_VIOLATION" in intent_codes


def test_persian_slot_rejects_hebrew_value():
    """Hebrew in a Persian slot — different script block entirely."""
    tool = json.loads(TOOL.read_text(encoding="utf-8"))
    wrapped = guard_tool(tool)
    report = wrapped.validate_call({
        "arguments": {
            "intent_phrase": "אני רוצה לנסוע",  # Hebrew
            "origin_city": "תל אביב",
            "destination_city": "ירושלים",
            "flight_class": "economy",
        }
    })
    intent_codes = {v.code for v in report.per_param["intent_phrase"].violations}
    assert "SCRIPT_VIOLATION" in intent_codes


def test_bidi_layer_also_guards_persian_values():
    """Security layer is language-agnostic — BiDi controls in a Persian
    value still flag, proving the primitive travels."""
    spec = GuardSpec.from_dict({
        "slot_type": "free_text",
        "script": "fa",
        "mode": "advisory",
    })
    result = validate_pre("سلام\u202eدنیا", spec)
    codes = {v.code for v in result.violations}
    assert "BIDI_CONTROL_SMUGGLING" in codes
