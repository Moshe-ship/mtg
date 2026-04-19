"""Tests for mtg.report — aggregate scorecard rendering."""

import json
from pathlib import Path

from mtg.report import Scorecard, aggregate, load_ndjson, render_html


def _toolproof_receipt(tool="send_message_gulf", outcome="partial",
                       dialect_expected="gulf", dialect_observed="egy",
                       violation_codes=("DIALECT_DRIFT",), repairs=()):
    return {
        "tool_name": tool,
        "outcome": outcome,
        "dialect_expected": dialect_expected,
        "dialect_observed": dialect_observed,
        "mtg_violations": [
            {"code": c, "severity": "medium", "phase": "pre", "message": "...",
             "details": {}}
            for c in violation_codes
        ],
        "mtg_repairs": list(repairs),
    }


def test_aggregate_counts_outcomes():
    receipts = [
        _toolproof_receipt(outcome="pass", dialect_observed="gulf", violation_codes=()),
        _toolproof_receipt(outcome="partial"),
        _toolproof_receipt(outcome="fail", violation_codes=("SCRIPT_VIOLATION",)),
    ]
    card = aggregate(receipts)
    data = card.to_dict()
    assert data["total_receipts"] == 3
    assert data["by_outcome"] == {"pass": 1, "partial": 1, "fail": 1}


def test_aggregate_violation_histogram():
    receipts = [
        _toolproof_receipt(violation_codes=("DIALECT_DRIFT",)),
        _toolproof_receipt(violation_codes=("DIALECT_DRIFT", "SCRIPT_VIOLATION")),
        _toolproof_receipt(violation_codes=("SCRIPT_VIOLATION",)),
    ]
    card = aggregate(receipts)
    assert card.violation_codes["DIALECT_DRIFT"] == 2
    assert card.violation_codes["SCRIPT_VIOLATION"] == 2


def test_aggregate_dialect_drift_pairs():
    receipts = [
        _toolproof_receipt(dialect_expected="gulf", dialect_observed="egy"),
        _toolproof_receipt(dialect_expected="gulf", dialect_observed="egy"),
        _toolproof_receipt(dialect_expected="gulf", dialect_observed="lev"),
        # Same dialect — no drift recorded
        _toolproof_receipt(dialect_expected="gulf", dialect_observed="gulf"),
    ]
    card = aggregate(receipts)
    pairs = card.to_dict()["dialect_drift_pairs"]
    assert pairs.get("gulf→egy") == 2
    assert pairs.get("gulf→lev") == 1
    assert "gulf→gulf" not in pairs


def test_aggregate_repair_actions():
    repair_a = {"action": "arabizi_to_arabic", "original": "x", "proposed": "y",
                "rationale": "...", "needs_review": True, "violation_code": None,
                "details": {}, "param": "message"}
    repair_b = {"action": "attach_canonical", "original": "x", "proposed": "z",
                "rationale": "...", "needs_review": False, "violation_code": None,
                "details": {}, "param": "message"}
    receipts = [
        _toolproof_receipt(repairs=[repair_a, repair_b]),
        _toolproof_receipt(repairs=[repair_a]),
    ]
    card = aggregate(receipts)
    actions = card.to_dict()["repair_actions"]
    assert actions["arabizi_to_arabic"] == 2
    assert actions["attach_canonical"] == 1


def test_aggregate_per_tool_hot_spots():
    receipts = [
        _toolproof_receipt(tool="send_message_gulf", outcome="fail"),
        _toolproof_receipt(tool="send_message_gulf", outcome="fail"),
        _toolproof_receipt(tool="send_message_gulf", outcome="pass",
                           dialect_observed="gulf", violation_codes=()),
        _toolproof_receipt(tool="book_hotel", outcome="pass",
                           dialect_observed="gulf", violation_codes=()),
    ]
    card = aggregate(receipts)
    data = card.to_dict()
    tools = {r["tool"]: r for r in data["per_tool"]}
    assert tools["send_message_gulf"]["total"] == 3
    assert tools["send_message_gulf"]["fail"] == 2
    assert tools["send_message_gulf"]["fail_rate"] > 0.5
    assert tools["book_hotel"]["total"] == 1
    assert tools["book_hotel"]["fail"] == 0
    # Sorted so fail-heavy tool comes first
    assert data["per_tool"][0]["tool"] == "send_message_gulf"


def test_aggregate_handles_mtg_native_guard_shape():
    """mtg/receipts.py receipts use `guards[param].pre_call_violations`
    instead of flat `mtg_violations` — aggregator must handle both."""
    native = {
        "tool": "send_message",
        "outcome": "partial",
        "guards": {
            "message": {
                "pre_call_violations": [
                    {"code": "DIALECT_DRIFT", "severity": "medium", "phase": "pre",
                     "message": "...", "details": {}},
                ],
                "post_call_violations": [],
            },
        },
    }
    card = aggregate([native])
    assert card.violation_codes["DIALECT_DRIFT"] == 1


def test_load_ndjson(tmp_path: Path):
    chain = tmp_path / "chain.ndjson"
    chain.write_text(
        json.dumps({"tool_name": "a", "outcome": "pass"}) + "\n"
        + json.dumps({"tool_name": "b", "outcome": "fail"}) + "\n",
        encoding="utf-8",
    )
    receipts = load_ndjson(chain)
    assert len(receipts) == 2
    assert receipts[0]["tool_name"] == "a"


def test_render_html_contains_key_sections():
    receipts = [_toolproof_receipt(violation_codes=("DIALECT_DRIFT",))]
    card = aggregate(receipts)
    html = render_html(card)
    assert "<!doctype html>" in html.lower()
    assert "MTG scorecard" in html
    assert "DIALECT_DRIFT" in html
    assert "gulf→egy" in html


def test_empty_chain_renders_without_crash():
    card = aggregate([])
    assert card.to_dict()["total_receipts"] == 0
    html = render_html(card)
    assert "0 receipts" in html
