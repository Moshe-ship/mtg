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
    """Render a Scorecard as a screenshot-grade single-page HTML document.

    Designed for social-media sharing: headline pass-rate up top,
    three-column stat band, proper bar charts for each breakdown, and
    clickable column sorting on the per-tool table. No external assets —
    one file, copy-and-paste into a browser.
    """
    data = card.to_dict()
    by_outcome = data["by_outcome"]
    total = data["total_receipts"] or 1
    pass_n = by_outcome.get("pass", 0)
    partial_n = by_outcome.get("partial", 0)
    fail_n = by_outcome.get("fail", 0)
    pass_pct = 100 * pass_n / total

    def _bar_row(label: str, count: int, total: int, tone: str = "neutral") -> str:
        pct = 100 * count / max(total, 1)
        return (
            f'<tr><td class="label"><code>{label}</code></td>'
            f'<td class="num">{count}</td>'
            f'<td class="num mute">{pct:.1f}%</td>'
            f'<td class="barcell"><div class="bar bar-{tone}">'
            f'<div class="fill" style="width:{pct:.1f}%"></div></div></td></tr>'
        )

    def _rows(items: list[tuple[str, int]], tone: str = "neutral") -> str:
        return "\n".join(_bar_row(k, v, total, tone) for k, v in items)

    # Tool table sorted (fail desc already done in aggregate)
    tool_rows = "\n".join(
        f'<tr><td><code>{r["tool"]}</code></td>'
        f'<td class="num">{r["total"]}</td>'
        f'<td class="num pass-color">{r["pass"]}</td>'
        f'<td class="num partial-color">{r["partial"]}</td>'
        f'<td class="num fail-color">{r["fail"]}</td>'
        f'<td class="num strong">{r["fail_rate"]:.0%}</td></tr>'
        for r in data["per_tool"]
    )

    # Empty-section helper — don't render blank tables
    def _section(title: str, items: list, body: str, tone: str = "") -> str:
        if not items:
            return ""
        return f'<section class="{tone}"><h2>{title}</h2><table class="stat">{body}</table></section>'

    violation_section = _section(
        "violation codes",
        list(data["violation_codes"].items()),
        _rows(list(data["violation_codes"].items()), tone="warn"),
    )

    drift_section = _section(
        "dialect drift pairs",
        list(data["dialect_drift_pairs"].items()),
        _rows(list(data["dialect_drift_pairs"].items()), tone="warn"),
    )

    repair_section = _section(
        "repair actions proposed",
        list(data["repair_actions"].items()),
        _rows(list(data["repair_actions"].items()), tone="good"),
    )

    severity_section = _section(
        "severity distribution",
        list(data["violation_severity"].items()),
        _rows(list(data["violation_severity"].items()), tone="warn"),
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MTG scorecard — {data['total_receipts']} receipts</title>
<style>
  :root {{
    --bg: #fff; --fg: #111; --muted: #6b7280; --border: #e5e7eb;
    --pass: #10b981; --partial: #f59e0b; --fail: #ef4444;
    --good: #10b981; --warn: #f59e0b; --neutral: #6b7280;
    --card-bg: #f9fafb; --mono: ui-monospace,SFMono-Regular,Menlo,monospace;
    --sans: -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font: 14px/1.5 var(--sans); color: var(--fg); background: var(--bg);
    max-width: 1000px; margin: 0 auto; padding: 2.5rem 1.5rem 4rem;
  }}
  header {{ border-bottom: 1px solid var(--border); padding-bottom: 1.25rem; margin-bottom: 2rem; }}
  header h1 {{ font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin: 0 0 .5rem; }}
  .headline {{ display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }}
  .headline .pct {{ font: 600 48px/1 var(--sans); font-variant-numeric: tabular-nums; }}
  .headline .caption {{ color: var(--muted); font-size: 13px; }}
  .stats {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem;
    margin: 1.5rem 0 0;
  }}
  .stat-tile {{
    border: 1px solid var(--border); border-radius: 6px;
    padding: .85rem 1rem; background: var(--card-bg);
  }}
  .stat-tile .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }}
  .stat-tile .value {{ font: 600 22px/1.2 var(--sans); font-variant-numeric: tabular-nums; margin-top: .2rem; }}
  .stat-tile.pass .value {{ color: var(--pass); }}
  .stat-tile.partial .value {{ color: var(--partial); }}
  .stat-tile.fail .value {{ color: var(--fail); }}
  section {{ margin-top: 2.5rem; }}
  h2 {{
    font: 600 11px/1 var(--sans); text-transform: uppercase; letter-spacing: .08em;
    color: var(--muted); margin: 0 0 .75rem;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  table.stat td {{ padding: .45rem .4rem; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  table.stat td.label {{ width: 30%; }}
  table.stat td.label code {{ font: 12px/1 var(--mono); background: #f3f4f6; padding: 3px 6px; border-radius: 3px; color: #111; }}
  table.stat td.num {{ width: 9%; text-align: right; font-variant-numeric: tabular-nums; }}
  table.stat td.mute {{ color: var(--muted); font-size: 12px; }}
  table.stat td.barcell {{ width: 45%; padding-left: 1rem; }}
  .bar {{ height: 8px; background: #f3f4f6; border-radius: 2px; overflow: hidden; }}
  .bar .fill {{ height: 100%; background: var(--neutral); transition: width .2s; }}
  .bar-good .fill {{ background: var(--good); }}
  .bar-warn .fill {{ background: var(--warn); }}
  table.tools {{ width: 100%; margin-top: .5rem; }}
  table.tools th, table.tools td {{ padding: .5rem .4rem; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }}
  table.tools th {{ font: 600 11px/1 var(--sans); text-transform: uppercase; letter-spacing: .06em; color: var(--muted); background: var(--card-bg); cursor: pointer; user-select: none; }}
  table.tools th.num, table.tools td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.tools td.strong {{ font-weight: 600; }}
  .pass-color {{ color: var(--pass); }}
  .partial-color {{ color: var(--partial); }}
  .fail-color {{ color: var(--fail); }}
  footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); font-size: 11px; color: var(--muted); }}
  footer code {{ font: 11px/1 var(--mono); }}
</style>
</head><body>
<header>
  <h1>MTG scorecard</h1>
  <div class="headline">
    <span class="pct">{pass_pct:.1f}%</span>
    <span class="caption">pass rate · {pass_n} / {total} receipts</span>
  </div>
  <div class="stats">
    <div class="stat-tile pass"><div class="label">pass</div><div class="value">{pass_n}</div></div>
    <div class="stat-tile partial"><div class="label">partial</div><div class="value">{partial_n}</div></div>
    <div class="stat-tile fail"><div class="label">fail</div><div class="value">{fail_n}</div></div>
  </div>
</header>

{violation_section}
{severity_section}
{drift_section}
{repair_section}

<section>
  <h2>per-tool hot spots</h2>
  <table class="tools" id="tools">
    <thead><tr>
      <th onclick="sortT(0,'str')">tool</th>
      <th class="num" onclick="sortT(1,'num')">total</th>
      <th class="num" onclick="sortT(2,'num')">pass</th>
      <th class="num" onclick="sortT(3,'num')">partial</th>
      <th class="num" onclick="sortT(4,'num')">fail</th>
      <th class="num" onclick="sortT(5,'num')">fail %</th>
    </tr></thead>
    <tbody>{tool_rows}</tbody>
  </table>
</section>

<footer>
  Generated by <code>mtg.report</code>. Single-page, self-contained. No external assets, no tracking.
</footer>

<script>
function sortT(col, kind) {{
  var tbody = document.querySelector('#tools tbody');
  var rows = Array.from(tbody.rows);
  var dir = tbody.dataset.sortCol == col && tbody.dataset.sortDir == 'asc' ? 'desc' : 'asc';
  rows.sort(function(a,b){{
    var av = a.cells[col].textContent.trim();
    var bv = b.cells[col].textContent.trim();
    if (kind === 'num') {{
      av = parseFloat(av.replace('%','')) || 0;
      bv = parseFloat(bv.replace('%','')) || 0;
      return dir === 'asc' ? av - bv : bv - av;
    }}
    return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  rows.forEach(function(r){{ tbody.appendChild(r); }});
  tbody.dataset.sortCol = col; tbody.dataset.sortDir = dir;
}}
</script>
</body></html>
"""


__all__ = [
    "Scorecard",
    "ScorecardRow",
    "aggregate",
    "load_ndjson",
    "render_html",
]
