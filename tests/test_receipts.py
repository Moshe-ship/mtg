"""Tests for receipt emission and hash-chain verification."""

from pathlib import Path

from mtg.pipeline import validate_pre
from mtg.receipts import (
    append_to_chain,
    build_receipt,
    read_chain,
    verify_chain,
)
from mtg.types import GuardSpec


def _spec() -> GuardSpec:
    return GuardSpec.from_dict({
        "slot_type": "free_text",
        "script": "ar",
        "mode": "advisory",
    })


def test_build_receipt_passes_on_valid_input():
    spec = _spec()
    guard = validate_pre("مرحبا", spec)
    receipt = build_receipt(tool="test_tool", guards={"intent": guard})
    assert receipt.outcome == "pass"
    assert receipt.tool == "test_tool"
    assert "intent" in receipt.guards


def test_build_receipt_fails_on_high_severity_violation():
    spec = GuardSpec.from_dict({
        "slot_type": "free_text",
        "script": "ar",
        "transliteration_allowed": False,
        "mode": "advisory",
    })
    # Arabizi in an ar slot: script + translit violations
    guard = validate_pre("abi a7jez", spec)
    receipt = build_receipt(tool="test_tool", guards={"intent": guard})
    # Build-receipt outcome aggregates violations regardless of mode
    assert receipt.outcome == "fail"


def test_chain_verification_empty():
    ok, err = verify_chain([])
    assert ok is True
    assert err is None


def test_chain_verification_roundtrip(tmp_path: Path):
    spec = _spec()
    guard = validate_pre("مرحبا", spec)

    chain_file = tmp_path / "chain.ndjson"

    prev_hash = None
    for i in range(3):
        receipt = build_receipt(
            tool="t",
            guards={"p": guard},
            call_id=f"call-{i}",
            ts=f"2026-04-18T00:00:{i:02d}+00:00",
            prev_hash=prev_hash,
        )
        prev_hash = append_to_chain(receipt, chain_file)

    receipts = read_chain(chain_file)
    assert len(receipts) == 3
    ok, err = verify_chain(receipts)
    assert ok, err


def test_chain_verification_detects_tamper(tmp_path: Path):
    spec = _spec()
    guard = validate_pre("مرحبا", spec)

    chain_file = tmp_path / "chain.ndjson"

    prev_hash = None
    for i in range(3):
        receipt = build_receipt(
            tool="t",
            guards={"p": guard},
            call_id=f"call-{i}",
            ts=f"2026-04-18T00:00:{i:02d}+00:00",
            prev_hash=prev_hash,
        )
        prev_hash = append_to_chain(receipt, chain_file)

    # Tamper: rewrite the middle line with a different tool name
    lines = chain_file.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"tool":"t"', '"tool":"t2"')
    chain_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    receipts = read_chain(chain_file)
    ok, err = verify_chain(receipts)
    assert ok is False
    assert err is not None
