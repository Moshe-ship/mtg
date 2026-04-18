"""Tests for framework adapters."""

import json
from pathlib import Path

from adapters.anthropic import guard_tool as anthropic_guard
from adapters.hermes_fc import guard_tool as hermes_guard
from adapters.openai import guard_tool as openai_guard

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_openai_adapter_extracts_guards():
    tool = json.loads((EXAMPLES / "book_service.json").read_text(encoding="utf-8"))
    wrapped = openai_guard(tool)
    assert wrapped.name == "book_service"
    # book_service declares x-mtg on intent_phrase, service_id, date
    assert "intent_phrase" in wrapped.guards
    assert "service_id" in wrapped.guards
    assert "date" in wrapped.guards


def test_openai_adapter_validates_call():
    tool = json.loads((EXAMPLES / "book_service.json").read_text(encoding="utf-8"))
    call = json.loads((EXAMPLES / "sample_call.json").read_text(encoding="utf-8"))
    wrapped = openai_guard(tool)
    report = wrapped.validate_call(call)
    assert report.tool == "book_service"
    assert "intent_phrase" in report.per_param
    # Arabic Gulf phrase should not emit SCRIPT_VIOLATION
    codes = {v.code for v in report.per_param["intent_phrase"].violations}
    assert "SCRIPT_VIOLATION" not in codes


def test_openai_adapter_catches_script_violation():
    tool = json.loads((EXAMPLES / "book_service.json").read_text(encoding="utf-8"))
    wrapped = openai_guard(tool)
    # Latin value in a slot that expects ar
    report = wrapped.validate_call({
        "arguments": {
            "intent_phrase": "book a hotel",
            "service_id": "svc-42",
        }
    })
    codes = {v.code for v in report.per_param["intent_phrase"].violations}
    assert "SCRIPT_VIOLATION" in codes


def test_openai_adapter_response_corruption():
    tool = json.loads((EXAMPLES / "book_service.json").read_text(encoding="utf-8"))
    wrapped = openai_guard(tool)
    call = {"arguments": {"intent_phrase": "أبي أحجز", "service_id": "svc-42"}}
    response = {"arguments": {"intent_phrase": "Riyadh hotel", "service_id": "svc-42"}}
    report = wrapped.validate_response(call, response)
    post_codes = {v.code for v in report.per_param["intent_phrase"].violations if v.phase == "post"}
    assert "SURFACE_CORRUPTION_POST_CALL" in post_codes


def test_anthropic_adapter_uses_input_schema():
    anthropic_tool = {
        "name": "book_service",
        "description": "...",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent_phrase": {
                    "type": "string",
                    "x-mtg": {
                        "slot_type": "inflected_request_form",
                        "script": "ar",
                        "dialect_expected": "gulf",
                        "morphologically_productive": True,
                        "mode": "advisory",
                    },
                },
            },
        },
    }
    wrapped = anthropic_guard(anthropic_tool)
    assert wrapped.name == "book_service"
    assert "intent_phrase" in wrapped.guards


def test_hermes_adapter_aliases_openai():
    tool = json.loads((EXAMPLES / "book_service.json").read_text(encoding="utf-8"))
    wrapped = hermes_guard(tool)
    assert wrapped.name == "book_service"
    assert "intent_phrase" in wrapped.guards


def test_adapter_ignores_properties_without_xmtg():
    tool = {
        "name": "simple",
        "parameters": {
            "type": "object",
            "properties": {
                "no_guards_here": {"type": "string"},
                "has_guards": {
                    "type": "string",
                    "x-mtg": {"slot_type": "free_text", "script": "ar", "mode": "advisory"},
                },
            },
        },
    }
    wrapped = openai_guard(tool)
    assert "no_guards_here" not in wrapped.guards
    assert "has_guards" in wrapped.guards
