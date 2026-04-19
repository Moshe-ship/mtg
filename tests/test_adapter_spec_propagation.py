"""Regression: adapter ValidationReport.to_dict() must carry GuardSpec alongside
GuardResult so the ToolProof bridge can set dialect_expected correctly and
filter dialect_observed to Arabic slots (review finding #5)."""

import json
from pathlib import Path

from mtg.adapters.openai import guard_tool

FIXTURES = Path(__file__).resolve().parent.parent / "examples"


def test_validation_report_carries_specs():
    tool = json.load((FIXTURES / "book_service.json").open(encoding="utf-8"))
    wrapped = guard_tool(tool)
    report = wrapped.validate_call({
        "arguments": {
            "intent_phrase": "أبي أحجز",
            "service_id": "svc-42",
        }
    })

    # In-memory report carries specs keyed by param name
    assert "intent_phrase" in report.specs
    assert report.specs["intent_phrase"].script == "ar"
    assert report.specs["intent_phrase"].dialect_expected == "gulf"

    # to_dict() must expose spec alongside the guard so downstream consumers
    # (e.g. toolproof.mtg_bridge) can read dialect_expected without needing
    # a live reference to the GuardedTool.
    serialized = report.to_dict()
    intent = serialized["per_param"]["intent_phrase"]
    assert "spec" in intent
    assert intent["spec"]["dialect_expected"] == "gulf"
    assert intent["spec"]["script"] == "ar"


def test_validation_report_service_id_has_spec_too():
    tool = json.load((FIXTURES / "book_service.json").open(encoding="utf-8"))
    wrapped = guard_tool(tool)
    report = wrapped.validate_call({
        "arguments": {"intent_phrase": "أبي", "service_id": "svc-42"}
    })
    svc = report.to_dict()["per_param"]["service_id"]
    assert svc["spec"]["slot_type"] == "identifier"
    assert svc["spec"]["script"] == "latn"
