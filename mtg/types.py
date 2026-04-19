"""Core value objects for MTG.

Frozen dataclasses so downstream consumers can cache and hash them safely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Literal


SlotType = Literal[
    "action_verb",
    "deverbal_noun",
    "inflected_request_form",
    "named_entity",
    "temporal",
    "numeric",
    "identifier",
    "free_text",
]

Script = Literal["ar", "latn", "he", "fa", "mixed", "any"]

Dialect = Literal["msa", "gulf", "egy", "lev", "maghrebi", "any"]

DialectEnforcement = Literal["strict", "preserve", "advisory"]

Canonicalization = Literal["none", "lemma", "root_pattern", "normalized"]

Mode = Literal["advisory", "reconciled", "enforced"]

Severity = Literal["high", "medium", "low", "info"]

Phase = Literal["pre", "post"]

FACTORABLE_SLOTS: frozenset[str] = frozenset(
    {"action_verb", "deverbal_noun", "inflected_request_form"}
)

NON_FACTORABLE_SLOTS: frozenset[str] = frozenset(
    {"named_entity", "temporal", "numeric", "identifier", "free_text"}
)


@dataclass(frozen=True)
class GuardSpec:
    """Parsed x-mtg block."""

    slot_type: str = "free_text"
    script: str = "any"
    dialect_expected: str = "any"
    dialect_enforcement: str = "advisory"
    transliteration_allowed: bool = True
    morphologically_productive: bool = False
    canonicalization: str = "none"
    canonical_form_required: bool = False
    mode: str = "advisory"
    post_call_contract: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any], validate: bool = True) -> "GuardSpec":
        """Parse an x-mtg block into a GuardSpec.

        `validate=True` (default) enforces spec/mtg.schema.json — unknown keys
        or bad enum values raise MTGSchemaError. Pass `validate=False` for the
        legacy lenient path (not recommended; preserved for adapter internals
        that may receive partial blocks).
        """
        if validate:
            from mtg.schema_validator import validate_x_mtg_strict
            validate_x_mtg_strict(data)
        contract = data.get("post_call_contract") or []
        return cls(
            slot_type=data.get("slot_type", "free_text"),
            script=data.get("script", "any"),
            dialect_expected=data.get("dialect_expected", "any"),
            dialect_enforcement=data.get("dialect_enforcement", "advisory"),
            transliteration_allowed=bool(data.get("transliteration_allowed", True)),
            morphologically_productive=bool(data.get("morphologically_productive", False)),
            canonicalization=data.get("canonicalization", "none"),
            canonical_form_required=bool(data.get("canonical_form_required", False)),
            mode=data.get("mode", "advisory"),
            post_call_contract=tuple(contract),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["post_call_contract"] = list(self.post_call_contract)
        return d

    @property
    def is_factorable(self) -> bool:
        return self.slot_type in FACTORABLE_SLOTS


@dataclass(frozen=True)
class Analysis:
    """Output of a morphological-ish analysis pass."""

    script_detected: str = "any"
    dialect_detected: str | None = None
    dialect_confidence: float = 0.0
    root: str | None = None
    pattern: str | None = None
    lemma: str | None = None
    morph_confidence: float = 0.0
    backend: str = "fallback"
    backend_available: bool = True
    ensemble_agreement: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Violation:
    """A single guard violation."""

    code: str
    severity: str  # 'high' | 'medium' | 'low' | 'info'
    phase: str     # 'pre' | 'post'
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "phase": self.phase,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class GuardResult:
    """Result of running the pipeline on one parameter."""

    surface: str
    analysis: Analysis
    violations: tuple[Violation, ...]
    mode: str
    # Reconciled-mode: proposed repairs. Empty tuple in advisory mode.
    # Each element is a mtg.repair.RepairSuggestion serialized to dict via
    # to_dict(); runtime usage keeps the frozen dataclass reference.
    repairs: tuple = field(default_factory=tuple)
    # Reconciled-mode: the single best repaired surface, or None. Callers
    # that want to replay validation on the repaired value use this.
    repaired_surface: str | None = None

    @property
    def outcome(self) -> str:
        """Aggregate outcome from violations. Advisory mode never fails."""
        if self.mode == "advisory":
            return "pass" if not self.violations else "pass"
        highest = _worst_severity(self.violations)
        if highest == "high":
            return "fail"
        if highest == "medium":
            return "partial"
        return "pass"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "surface": self.surface,
            "analysis": self.analysis.to_dict(),
            "pre_call_violations": [v.to_dict() for v in self.violations if v.phase == "pre"],
            "post_call_violations": [v.to_dict() for v in self.violations if v.phase == "post"],
            "mode": self.mode,
        }
        if self.repairs:
            out["repairs"] = [
                r.to_dict() if hasattr(r, "to_dict") else dict(r)
                for r in self.repairs
            ]
        if self.repaired_surface is not None:
            out["repaired_surface"] = self.repaired_surface
        return out


@dataclass(frozen=True)
class Receipt:
    """Hash-chained receipt for a full call."""

    call_id: str
    tool: str
    ts: str
    guards: dict                 # param_name -> GuardResult.to_dict()
    outcome: str                 # 'pass' | 'partial' | 'fail'
    hash_prev: str | None = None

    def canonical_json(self) -> str:
        """Stable JSON for hashing."""
        payload = {
            "call_id": self.call_id,
            "tool": self.tool,
            "ts": self.ts,
            "guards": self.guards,
            "outcome": self.outcome,
            "hash_prev": self.hash_prev,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool": self.tool,
            "ts": self.ts,
            "guards": self.guards,
            "outcome": self.outcome,
            "hash_prev": self.hash_prev,
        }


def _worst_severity(violations: tuple[Violation, ...]) -> str:
    order = {"high": 3, "medium": 2, "low": 1, "info": 0}
    if not violations:
        return "info"
    return max(violations, key=lambda v: order.get(v.severity, 0)).severity


SEVERITY_TO_OUTCOME: dict[str, str] = {
    "high": "fail",
    "medium": "partial",
    "low": "pass",
    "info": "pass",
}
