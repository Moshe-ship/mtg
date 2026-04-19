"""Framework adapters for MTG.

Adapters wrap a tool definition from a specific agent framework so that
tool-call arguments get validated through the MTG pipeline. Framework-agnostic
by design — one primitive, multiple adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg.pipeline import validate_pre, validate_post
from mtg.types import GuardResult, GuardSpec


@dataclass
class ValidationReport:
    """Aggregate report from validating a single tool call.

    `per_param` maps parameter name → GuardResult (what we detected).
    `specs`    maps parameter name → GuardSpec (what was declared).
    Downstream consumers (e.g. toolproof.mtg_bridge.receipt_from_mtg_run)
    rely on `specs` to set dialect_expected and to filter dialect_observed
    to the param whose slot actually carried an Arabic declaration.
    """

    tool: str
    per_param: dict[str, GuardResult]
    specs: dict[str, GuardSpec] = field(default_factory=dict)

    @property
    def violations(self) -> list:
        out = []
        for guard in self.per_param.values():
            out.extend(guard.violations)
        return out

    @property
    def has_violations(self) -> bool:
        return any(guard.violations for guard in self.per_param.values())

    def to_dict(self) -> dict:
        guards_with_specs: dict[str, dict] = {}
        for name, guard in self.per_param.items():
            entry = guard.to_dict()
            if name in self.specs:
                entry["spec"] = self.specs[name].to_dict()
            guards_with_specs[name] = entry
        return {
            "tool": self.tool,
            "per_param": guards_with_specs,
            "has_violations": self.has_violations,
        }


__all__ = ["ValidationReport", "validate_pre", "validate_post", "GuardSpec"]
