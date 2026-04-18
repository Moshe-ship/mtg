"""Receipt emission + hash-chain verification for MTG.

Receipts are appended to ~/.mtg/chain.ndjson (one JSON per line). Each receipt
carries hash_prev = SHA-256 of the previous receipt's canonical JSON, forming a
tamper-evident chain without requiring signatures. Optional signing path is
handled by the ToolProof bridge (toolproof.mtg_bridge).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from mtg.types import GuardResult, Receipt, _worst_severity


CHAIN_DEFAULT_DIR = Path(os.path.expanduser("~/.mtg"))
CHAIN_DEFAULT_PATH = CHAIN_DEFAULT_DIR / "chain.ndjson"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_outcome(guards: dict[str, GuardResult]) -> str:
    """Aggregate outcome across all per-parameter guard results."""
    all_violations: list = []
    for guard in guards.values():
        all_violations.extend(guard.violations)
    if not all_violations:
        return "pass"
    worst = _worst_severity(tuple(all_violations))
    if worst == "high":
        return "fail"
    if worst == "medium":
        return "partial"
    return "pass"


def build_receipt(
    tool: str,
    guards: dict[str, GuardResult],
    call_id: str | None = None,
    ts: str | None = None,
    prev_hash: str | None = None,
) -> Receipt:
    """Build a Receipt from per-parameter guard results."""
    serialized = {name: guard.to_dict() for name, guard in guards.items()}
    return Receipt(
        call_id=call_id or str(uuid.uuid4()),
        tool=tool,
        ts=ts or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        guards=serialized,
        outcome=_build_outcome(guards),
        hash_prev=prev_hash,
    )


def append_to_chain(receipt: Receipt, path: Path | None = None) -> str:
    """Append receipt to the NDJSON chain and return its own hash."""
    target = path or CHAIN_DEFAULT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(receipt.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with target.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return _sha256(receipt.canonical_json())


def read_chain(path: Path | None = None) -> list[Receipt]:
    target = path or CHAIN_DEFAULT_PATH
    if not target.exists():
        return []
    out: list[Receipt] = []
    with target.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            out.append(
                Receipt(
                    call_id=data["call_id"],
                    tool=data["tool"],
                    ts=data["ts"],
                    guards=data["guards"],
                    outcome=data["outcome"],
                    hash_prev=data.get("hash_prev"),
                )
            )
    return out


def verify_chain(receipts: Iterable[Receipt]) -> tuple[bool, str | None]:
    """Verify hash_prev links in a chain of receipts.

    Returns (is_valid, error_message_or_None).
    """
    prev_hash: str | None = None
    for i, receipt in enumerate(receipts):
        if receipt.hash_prev != prev_hash:
            return False, (
                f"chain broken at index {i}: expected hash_prev={prev_hash!r}, "
                f"got {receipt.hash_prev!r}"
            )
        prev_hash = _sha256(receipt.canonical_json())
    return True, None
