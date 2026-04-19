#!/usr/bin/env bash
# Cross-repo integration smoke for the Arabic agent stack.
#
# Installs mtg (this repo), toolproof, and hurmoz tool-schemas into a fresh
# venv and exercises the full guard_tool -> receipt_from_mtg_run path.
# Used by .github/workflows/cross-repo-smoke.yml and safe to run locally.
#
# Usage:
#   scripts/cross_repo_smoke.sh                   # expects sibling checkouts
#   MTG=/path/to/mtg TOOLPROOF=/path/to/toolproof HURMOZ=/path/to/hurmoz \
#     scripts/cross_repo_smoke.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MTG_DIR="${MTG:-$(cd "$HERE/.." && pwd)}"
TOOLPROOF_DIR="${TOOLPROOF:-$MTG_DIR/../toolproof}"
HURMOZ_DIR="${HURMOZ:-$MTG_DIR/../hurmoz}"

echo ">> mtg:       $MTG_DIR"
echo ">> toolproof: $TOOLPROOF_DIR"
echo ">> hurmoz:    $HURMOZ_DIR"

for d in "$MTG_DIR" "$TOOLPROOF_DIR" "$HURMOZ_DIR"; do
  if [ ! -d "$d" ]; then
    echo "missing: $d" >&2
    exit 1
  fi
done

VENV="$(mktemp -d)/venv"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$MTG_DIR"
"$VENV/bin/pip" install --quiet "$TOOLPROOF_DIR"

echo ">> installed into $VENV"

HURMOZ_SCHEMAS="$HURMOZ_DIR/tool-schemas"

"$VENV/bin/python" - <<PY
"""End-to-end: guard_tool (Hurmoz schema) -> receipt (ToolProof) + integrity."""
import json
import sys
from pathlib import Path

import mtg
from mtg.adapters.openai import guard_tool
from toolproof.mtg_bridge import receipt_from_mtg_run

schemas = Path(r"""$HURMOZ_SCHEMAS""")

# 1) Public schema accessor works
schema = mtg.get_schema()
assert schema["type"] == "object", "schema accessor broken"

# 2) Each send_message_* variant produces the right dialect_expected
results = []
for variant in ["gulf", "egy", "lev", "msa"]:
    tool = json.loads((schemas / f"send_message_{variant}.json").read_text(encoding="utf-8"))
    wrapped = guard_tool(tool)
    report = wrapped.validate_call({
        "arguments": {
            "recipient": "أحمد",
            "platform": "whatsapp",
            "message": "أبي أحجز فندق في دبي",  # Gulf
        }
    })
    guards = report.to_dict()["per_param"]
    receipt = receipt_from_mtg_run(tool=f"send_message_{variant}", guards=guards,
                                    arguments={"message": "أبي أحجز فندق في دبي"})
    results.append((variant, receipt))
    # verify_integrity must be True after clean sign
    assert receipt.verify_integrity(), f"{variant}: verify_integrity failed at sign time"
    # Tamper detection
    original = receipt.outcome
    receipt.outcome = "fail" if original != "fail" else "pass"
    assert not receipt.verify_integrity(), f"{variant}: tamper detection failed"
    receipt.outcome = original  # restore
    assert receipt.verify_integrity(), f"{variant}: restore broke verify"

# 3) Only the matching variant should produce outcome=pass
by_variant = {v: r.outcome for v, r in results}
assert by_variant["gulf"] == "pass", by_variant
assert by_variant["egy"] == "partial", by_variant
assert by_variant["lev"] == "partial", by_variant
assert by_variant["msa"] == "partial", by_variant

# 4) dialect_expected is recorded correctly on each variant
for v, r in results:
    assert r.dialect_expected == v, f"{v}: dialect_expected mismatch {r.dialect_expected!r}"

print("CROSS-REPO SMOKE: OK")
print(f"  variants tested: {[v for v, _ in results]}")
print(f"  outcomes: {by_variant}")
PY

echo ">> smoke passed; running closed-loop router example from Hurmoz"

"$VENV/bin/python" "$HURMOZ_DIR/examples/dialect_router.py" > /tmp/router-output.txt
grep -q "signed receipts" /tmp/router-output.txt || {
  echo "router example did not produce the expected banner" >&2
  cat /tmp/router-output.txt
  exit 1
}

echo ">> router example OK"

"$VENV/bin/mtg" report "$HOME/.toolproof/dialect_router_chain.ndjson" --json /tmp/router-scorecard.json > /tmp/report-output.txt
grep -q "receipts:" /tmp/report-output.txt || {
  echo "mtg report did not produce expected output" >&2
  cat /tmp/report-output.txt
  exit 1
}

echo ">> report CLI OK"
echo ">> done"
