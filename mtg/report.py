"""Aggregate MTG receipt chains into a scorecard (JSON / HTML).

Reads an NDJSON chain (from mtg.receipts or toolproof.ReceiptStore) and
produces a single artifact summarizing:

- pass / partial / fail totals
- violation-code histogram with severity breakdown
- dialect-drift pairs (expected → observed counts)
- repair action histogram (how often each action was proposed)
- per-tool outcome breakdown (hot-spot view)

Pure-Python. No templating library, no HTTP, no filesystem writes beyond
the out-paths the caller specifies. Safe to call offline over any chain.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_VIOLATION_SEVERITY: dict[str, str] = {
    "SCRIPT_VIOLATION": "high",
    "TRANSLITERATION_VIOLATION": "high",
    "SURFACE_CORRUPTION_POST_CALL": "high",
    "CANONICALIZATION_REQUIRED": "high",
    "DIALECT_DRIFT": "medium",
    "DIALECT_FLATTEN": "medium",
    "ROOT_DRIFT": "medium",
    "FREE_TEXT_OVERFLOW": "medium",
    "MORPH_CANONICALIZATION_FAILURE": "low",
    "MORPH_AMBIGUITY": "low",
    "BACKEND_DISAGREEMENT": "info",
}


@dataclass
class ScorecardRow:
    """Per-tool outcome breakdown."""

    tool: str
    total: int = 0
    pass_: int = 0
    partial: int = 0
    fail: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "total": self.total,
            "pass": self.pass_,
            "partial": self.partial,
            "fail": self.fail,
            "fail_rate": round(self.fail / self.total, 4) if self.total else 0.0,
        }


@dataclass
class Scorecard:
    total_receipts: int = 0
    by_outcome: Counter = field(default_factory=Counter)
    violation_codes: Counter = field(default_factory=Counter)
    violation_severity: Counter = field(default_factory=Counter)
    dialect_drift_pairs: Counter = field(default_factory=Counter)
    repair_actions: Counter = field(default_factory=Counter)
    per_tool: dict[str, ScorecardRow] = field(default_factory=dict)

    def _record(self, receipt: dict[str, Any]) -> None:
        self.total_receipts += 1

        outcome = receipt.get("outcome") or "pass"
        self.by_outcome[outcome] += 1

        tool = receipt.get("tool_name") or receipt.get("tool") or "<unknown>"
        row = self.per_tool.setdefault(tool, ScorecardRow(tool=tool))
        row.total += 1
        if outcome == "pass":
            row.pass_ += 1
        elif outcome == "partial":
            row.partial += 1
        elif outcome == "fail":
            row.fail += 1

        # Violations — two accepted shapes:
        # - toolproof.Receipt: `mtg_violations` flat list
        # - mtg.Receipt: `guards[param].{pre_call_violations, post_call_violations}`
        violations: list[dict] = []
        if isinstance(receipt.get("mtg_violations"), list):
            violations.extend(receipt["mtg_violations"])
        guards = receipt.get("guards") or {}
        if isinstance(guards, dict):
            for guard in guards.values():
                if not isinstance(guard, dict):
                    continue
                for key in ("pre_call_violations", "post_call_violations"):
                    for v in guard.get(key, []) or []:
                        violations.append(v)
        for v in violations:
            code = v.get("code", "UNKNOWN")
            self.violation_codes[code] += 1
            sev = v.get("severity") or _VIOLATION_SEVERITY.get(code, "info")
            self.violation_severity[sev] += 1

        # Dialect drift pairs
        expected = receipt.get("dialect_expected")
        observed = receipt.get("dialect_observed")
        if expected and observed and expected != observed:
            self.dialect_drift_pairs[f"{expected}→{observed}"] += 1

        # Repair actions
        for repair in receipt.get("mtg_repairs") or []:
            action = repair.get("action", "<unknown>")
            self.repair_actions[action] += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_receipts": self.total_receipts,
            "by_outcome": dict(self.by_outcome),
            "violation_codes": dict(self.violation_codes.most_common()),
            "violation_severity": dict(self.violation_severity.most_common()),
            "dialect_drift_pairs": dict(self.dialect_drift_pairs.most_common()),
            "repair_actions": dict(self.repair_actions.most_common()),
            "per_tool": [row.to_dict() for row in sorted(
                self.per_tool.values(), key=lambda r: (-r.fail, -r.total)
            )],
        }


def aggregate(receipts: Iterable[dict[str, Any]]) -> Scorecard:
    """Aggregate an iterable of receipt dicts into a Scorecard."""
    card = Scorecard()
    for r in receipts:
        card._record(r)
    return card


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    """Load an NDJSON chain into a list of dicts."""
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def render_html(card: Scorecard) -> str:
    """Render a Scorecard as a self-contained HTML document."""
    data = card.to_dict()
    by_outcome = data["by_outcome"]
    total = data["total_receipts"] or 1

    def _bar(n: int, total: int) -> str:
        pct = 100 * n / max(total, 1)
        return f'<div class="bar"><div class="fill" style="width:{pct:.1f}%"></div><span>{n}</span></div>'

    def _rows(items: list[tuple[str, int]]) -> str:
        return "\n".join(
            f"<tr><td><code>{k}</code></td><td class='num'>{v}</td><td>{_bar(v, total)}</td></tr>"
            for k, v in items
        )

    tool_rows = "\n".join(
        f"<tr><td><code>{r['tool']}</code></td>"
        f"<td class='num'>{r['total']}</td>"
        f"<td class='num pass'>{r['pass']}</td>"
        f"<td class='num partial'>{r['partial']}</td>"
        f"<td class='num fail'>{r['fail']}</td>"
        f"<td class='num'>{r['fail_rate']:.0%}</td></tr>"
        for r in data["per_tool"]
    )

    return (
        "<!doctype html>\n"
        '<html><head><meta charset="utf-8"><title>MTG scorecard</title>\n'
        "<style>\n"
        "body{font:13px -apple-system,sans-serif;color:#111;max-width:960px;margin:2em auto;padding:0 1em}\n"
        "h1{font-size:20px;border-bottom:1px solid #ddd;padding-bottom:.3em}\n"
        "h2{font-size:15px;margin-top:2em;color:#555}\n"
        "table{border-collapse:collapse;width:100%;margin:.5em 0}\n"
        "th,td{padding:.3em .6em;text-align:left;border-bottom:1px solid #eee}\n"
        "th{background:#f6f6f6;font-weight:600}\n"
        ".num{text-align:right;font-variant-numeric:tabular-nums}\n"
        ".pass{color:#2a7}.partial{color:#c80}.fail{color:#c33}\n"
        ".bar{background:#eee;height:14px;border-radius:2px;position:relative;overflow:hidden}\n"
        ".bar .fill{background:#999;height:100%}\n"
        ".bar span{position:absolute;top:0;left:4px;font-size:11px;line-height:14px;color:#fff;mix-blend-mode:difference}\n"
        ".card{background:#fafafa;border:1px solid #eee;padding:.7em 1em;border-radius:4px;margin:.5em 0}\n"
        "code{background:#f2f2f2;padding:1px 4px;border-radius:2px}\n"
        "</style></head><body>\n"
        f"<h1>MTG scorecard — {data['total_receipts']} receipts</h1>\n"
        "<div class='card'>"
        f"<strong>Outcomes:</strong> "
        f"<span class='pass'>{by_outcome.get('pass', 0)} pass</span> · "
        f"<span class='partial'>{by_outcome.get('partial', 0)} partial</span> · "
        f"<span class='fail'>{by_outcome.get('fail', 0)} fail</span>"
        "</div>\n"
        "<h2>Violation codes</h2>\n"
        "<table><thead><tr><th>Code</th><th class='num'>Count</th><th>Share</th></tr></thead>"
        f"<tbody>{_rows(list(data['violation_codes'].items()))}</tbody></table>\n"
        "<h2>Dialect drift</h2>\n"
        "<table><thead><tr><th>expected → observed</th><th class='num'>Count</th><th>Share</th></tr></thead>"
        f"<tbody>{_rows(list(data['dialect_drift_pairs'].items()))}</tbody></table>\n"
        "<h2>Repair actions</h2>\n"
        "<table><thead><tr><th>Action</th><th class='num'>Count</th><th>Share</th></tr></thead>"
        f"<tbody>{_rows(list(data['repair_actions'].items()))}</tbody></table>\n"
        "<h2>Per-tool hot spots</h2>\n"
        "<table><thead><tr><th>Tool</th><th class='num'>Total</th>"
        "<th class='num pass'>Pass</th><th class='num partial'>Partial</th>"
        "<th class='num fail'>Fail</th><th class='num'>Fail%</th></tr></thead>"
        f"<tbody>{tool_rows}</tbody></table>\n"
        "</body></html>\n"
    )


__all__ = [
    "Scorecard",
    "ScorecardRow",
    "aggregate",
    "load_ndjson",
    "render_html",
]
