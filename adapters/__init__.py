"""Framework adapters for MTG.

Adapters wrap a tool definition from a specific agent framework so that
tool-call arguments get validated through the MTG pipeline. Framework-agnostic
by design — one primitive, multiple adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

from mtg.pipeline import validate_pre, validate_post
from mtg.types import GuardResult, GuardSpec


@dataclass
class ValidationReport:
    """Aggregate report from validating a single tool call."""

    tool: str
    per_param: dict[str, GuardResult]

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
        return {
            "tool": self.tool,
            "per_param": {name: guard.to_dict() for name, guard in self.per_param.items()},
            "has_violations": self.has_violations,
        }


__all__ = ["ValidationReport", "validate_pre", "validate_post", "GuardSpec"]
