"""MTG evaluation harness — public API.

Run MTG guards against arabic-agent-eval items (or any JSONL in the same
shape) and aggregate per-dialect violation rates. Useful for:

- Measuring MTG violation prevalence on a held-out benchmark
- A/B/C/D experimental arms over the same dataset
- Building a Receipt chain offline from a dataset for inspection

Example:

    from pathlib import Path
    from mtg.eval import run_on_jsonl
    from mtg import GuardSpec

    guard_map = {
        "intent_phrase": GuardSpec.from_dict({
            "slot_type": "inflected_request_form",
            "script": "ar",
            "dialect_expected": "gulf",
            "morphologically_productive": True,
            "mode": "advisory",
        }),
    }
    report = run_on_jsonl(Path("datasets/mtg_slots_v1.jsonl"), guard_map)
    print(report.violation_counts)
    print(report.dialect_violation_rates)

See `spec/resolution.md` for the four experimental arms (A/B/C/D) and
`mtg.eval.conditions` for the `Condition` dataclass.
"""

from __future__ import annotations

from mtg.eval.conditions import (
    ALL_ARMS,
    ARM_A,
    ARM_B,
    ARM_C,
    ARM_D,
    Condition,
)
from mtg.eval.runner import (
    AggregateReport,
    ItemReport,
    run_on_jsonl,
)

__all__ = [
    "AggregateReport",
    "ALL_ARMS",
    "ARM_A",
    "ARM_B",
    "ARM_C",
    "ARM_D",
    "Condition",
    "ItemReport",
    "run_on_jsonl",
]
