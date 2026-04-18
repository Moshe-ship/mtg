"""Run MTG guards against arabic-agent-eval items (or any compatible JSONL).

Consumes items of the shape emitted by arabic-agent-eval.exporter. For each
item, builds guard specs from a provided mapping of parameter-name → GuardSpec
and runs validate_pre on every expected call argument. Emits an MTG report
with per-item and aggregate violation statistics.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from mtg.pipeline import validate_pre
from mtg.types import GuardResult, GuardSpec


@dataclass
class ItemReport:
    item_id: str
    dialect: str
    per_param: dict[str, GuardResult] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "dialect": self.dialect,
            "per_param": {n: g.to_dict() for n, g in self.per_param.items()},
        }


@dataclass
class AggregateReport:
    per_item: list[ItemReport]
    violation_counts: Counter
    dialect_violation_rates: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "items": [r.to_dict() for r in self.per_item],
            "violation_counts": dict(self.violation_counts),
            "dialect_violation_rates": dict(self.dialect_violation_rates),
        }


def _iter_items(jsonl_path: Path) -> Iterable[dict]:
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def run_on_jsonl(
    jsonl_path: Path,
    guard_map: dict[str, GuardSpec],
) -> AggregateReport:
    """Run MTG guards against a JSONL of arabic-agent-eval items.

    `guard_map` maps parameter names to GuardSpecs. Parameters that do not
    have a GuardSpec are not validated.
    """
    per_item: list[ItemReport] = []
    violation_counts: Counter = Counter()
    dialect_totals: Counter = Counter()
    dialect_with_violations: Counter = Counter()

    for item in _iter_items(jsonl_path):
        dialect = item.get("dialect", "unknown")
        dialect_totals[dialect] += 1
        report = ItemReport(item_id=item["id"], dialect=dialect)
        had_violation = False
        for call in item.get("expected_calls", []):
            args = call.get("arguments", {})
            for param_name, spec in guard_map.items():
                if param_name not in args:
                    continue
                value = str(args[param_name])
                result = validate_pre(value, spec)
                report.per_param[f"{call.get('function')}::{param_name}"] = result
                for v in result.violations:
                    violation_counts[v.code] += 1
                    had_violation = True
        if had_violation:
            dialect_with_violations[dialect] += 1
        per_item.append(report)

    rates: dict[str, float] = {}
    for dialect, total in dialect_totals.items():
        if total == 0:
            continue
        rates[dialect] = dialect_with_violations[dialect] / total

    return AggregateReport(
        per_item=per_item,
        violation_counts=violation_counts,
        dialect_violation_rates=rates,
    )
