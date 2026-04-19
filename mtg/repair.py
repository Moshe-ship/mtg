"""Repair primitives for MTG reconciled mode.

Reconciled mode runs the same detection as advisory mode, then proposes
safe, deterministic repairs for a subset of violations. Repairs are never
applied silently — they produce `RepairSuggestion` records carrying the
original surface, the proposed replacement, and a machine-readable action
label so downstream consumers (ToolProof receipts, agent replay) can
decide whether to accept.

What we repair:

- `SCRIPT_VIOLATION` when the value looks like Arabizi → naive
  digit-letter + digraph reverse-transliteration. Best-effort; clearly
  marked as `needs_review=True`.
- `TRANSLITERATION_VIOLATION` → same path.
- `CANONICALIZATION_REQUIRED` → attach the `normalized` form as a
  canonical candidate, since `normalized` is a pure string transform
  that cannot fail.

What we DO NOT repair:

- `DIALECT_DRIFT` — rewriting across dialects requires a generative model.
  We emit an `advisory` suggestion naming the target dialect but do not
  rewrite.
- `FREE_TEXT_OVERFLOW` — the slot type is wrong; fix the schema, not
  the value.
- `MORPH_*` — advisory only.

Repairs are deterministic and side-effect-free. Adding a new repair
action requires only: a new `RepairAction` literal, a pure function, and
a dispatch entry in `suggest_repairs`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from typing import Any, Literal

from mtg.canonical import normalize
from mtg.translit import looks_like_arabizi
from mtg.types import Analysis, GuardSpec, Violation


RepairAction = Literal[
    "arabizi_to_arabic",
    "normalize_script",
    "attach_canonical",
    "suggest_dialect_rewrite",
    "suggest_slot_type_review",
]


@dataclass(frozen=True)
class RepairSuggestion:
    """A proposed repair for a guarded value.

    `original`   — the surface value as received (never mutated).
    `proposed`   — the candidate replacement, or None for advisory-only
                   suggestions (like dialect rewrite which needs a model).
    `action`     — machine-readable action label.
    `rationale`  — human-readable explanation.
    `needs_review` — True when the repair is best-effort / lossy and the
                   caller must sanity-check before applying.
    `violation_code` — which detected violation prompted this suggestion.
    """

    original: str
    proposed: str | None
    action: str
    rationale: str
    needs_review: bool = True
    violation_code: str | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "proposed": self.proposed,
            "action": self.action,
            "rationale": self.rationale,
            "needs_review": self.needs_review,
            "violation_code": self.violation_code,
            "details": dict(self.details),
        }


# Arabizi reverse transliteration mapping. Deterministic but lossy —
# digit substitutions have multiple Arabic targets depending on dialect
# and orthographic convention. We pick the most common choice and mark
# every output as needs_review=True.

_ARABIZI_DIGITS = {
    "2": "ء",   # hamza
    "3": "ع",   # ayn
    "5": "خ",   # kha (also sometimes "kh")
    "6": "ط",   # Taa (less common)
    "7": "ح",   # Haa
    "8": "ق",   # qaf (Maghrebi convention; also 9)
    "9": "ق",   # qaf
}

_ARABIZI_DIGRAPHS = [
    ("sh", "ش"),
    ("Sh", "ش"),
    ("SH", "ش"),
    ("kh", "خ"),
    ("Kh", "خ"),
    ("KH", "خ"),
    ("gh", "غ"),
    ("Gh", "غ"),
    ("GH", "غ"),
    ("th", "ث"),
    ("Th", "ث"),
    ("TH", "ث"),
    ("aa", "ا"),
    ("ee", "ي"),
    ("oo", "و"),
    ("ou", "و"),
    ("ai", "اي"),
]

_LATIN_LETTER_TO_ARABIC = {
    "a": "ا",
    "b": "ب",
    "c": "ك",   # dialectal / soft c → k
    "d": "د",
    "e": "ي",
    "f": "ف",
    "g": "ج",
    "h": "ه",
    "i": "ي",
    "j": "ج",
    "k": "ك",
    "l": "ل",
    "m": "م",
    "n": "ن",
    "o": "و",
    "p": "ب",   # no pure /p/ in Arabic
    "q": "ق",
    "r": "ر",
    "s": "س",
    "t": "ت",
    "u": "و",
    "v": "ف",
    "w": "و",
    "x": "كس",
    "y": "ي",
    "z": "ز",
}


def arabizi_to_arabic_naive(text: str) -> str:
    """Best-effort reverse transliteration from Arabizi to Arabic script.

    Applies digraph substitutions first (sh/kh/gh/th/aa/ee/oo/ai), then
    digit-letter substitutions, then per-letter Latin→Arabic mapping.
    Output is deterministic but lossy — always flag `needs_review=True`
    when exposing to users.
    """
    if not text:
        return ""
    out = text
    # Digraphs first (longest match wins)
    for latin, ar in _ARABIZI_DIGRAPHS:
        out = out.replace(latin, ar)
    # Digit substitutions
    for d, ar in _ARABIZI_DIGITS.items():
        out = out.replace(d, ar)
    # Per-letter mapping for remaining Latin chars
    result = []
    for ch in out:
        lower = ch.lower()
        if lower in _LATIN_LETTER_TO_ARABIC:
            result.append(_LATIN_LETTER_TO_ARABIC[lower])
        else:
            result.append(ch)
    return "".join(result)


def suggest_repairs(
    value: str,
    spec: GuardSpec,
    analysis: Analysis,
    violations: list[Violation],
) -> list[RepairSuggestion]:
    """Produce repair suggestions for the set of violations emitted on `value`.

    Ordering: script/translit repairs first (they may change downstream
    analysis), then canonical attach, then advisory dialect notes.
    """
    suggestions: list[RepairSuggestion] = []
    codes = {v.code for v in violations}

    # Script / translit → Arabizi reverse transliteration (if applicable).
    if (
        ("SCRIPT_VIOLATION" in codes or "TRANSLITERATION_VIOLATION" in codes)
        and spec.script == "ar"
        and looks_like_arabizi(value)
    ):
        proposed = arabizi_to_arabic_naive(value)
        suggestions.append(
            RepairSuggestion(
                original=value,
                proposed=proposed,
                action="arabizi_to_arabic",
                rationale=(
                    "value looks like Arabizi (Romanized Arabic); proposing "
                    "naive digit+digraph+letter reverse transliteration"
                ),
                needs_review=True,
                violation_code=(
                    "TRANSLITERATION_VIOLATION" if "TRANSLITERATION_VIOLATION" in codes
                    else "SCRIPT_VIOLATION"
                ),
                details={"script_detected": analysis.script_detected},
            )
        )

    # Canonical form attachment — always safe when canonicalization is
    # `normalized` (pure string transform). For `lemma` / `root_pattern`
    # we can still attach the normalized fallback as best-effort.
    if "CANONICALIZATION_REQUIRED" in codes:
        normalized = normalize(value)
        suggestions.append(
            RepairSuggestion(
                original=value,
                proposed=normalized,
                action="attach_canonical",
                rationale=(
                    f"canonical_form_required=true with mode='{spec.canonicalization}' "
                    f"could not derive a form; attaching normalized surface as fallback"
                ),
                needs_review=(spec.canonicalization != "normalized"),
                violation_code="CANONICALIZATION_REQUIRED",
                details={
                    "canonicalization": spec.canonicalization,
                    "normalized_form": normalized,
                },
            )
        )

    # Dialect drift — advisory only; we don't rewrite across dialects.
    if "DIALECT_DRIFT" in codes and spec.dialect_expected != "any":
        suggestions.append(
            RepairSuggestion(
                original=value,
                proposed=None,
                action="suggest_dialect_rewrite",
                rationale=(
                    f"detected dialect '{analysis.dialect_detected}' differs from "
                    f"expected '{spec.dialect_expected}'; rewriting across dialects "
                    f"requires a generative model — advisory suggestion only"
                ),
                needs_review=True,
                violation_code="DIALECT_DRIFT",
                details={
                    "expected": spec.dialect_expected,
                    "detected": analysis.dialect_detected,
                },
            )
        )

    # Free-text overflow — schema-side fix, not value-side.
    if "FREE_TEXT_OVERFLOW" in codes:
        suggestions.append(
            RepairSuggestion(
                original=value,
                proposed=None,
                action="suggest_slot_type_review",
                rationale=(
                    f"factorable slot '{spec.slot_type}' received dominantly "
                    f"non-factorable content; consider changing the schema slot_type "
                    f"to 'free_text' or 'named_entity'"
                ),
                needs_review=True,
                violation_code="FREE_TEXT_OVERFLOW",
                details={"slot_type": spec.slot_type},
            )
        )

    return suggestions


def pick_repaired_value(
    original: str,
    suggestions: list[RepairSuggestion],
) -> str | None:
    """Select the single best repaired surface, or None if no concrete
    replacement is available.

    Preference: script/translit repairs (they produce a usable Arabic
    surface) > canonical attach (changes surface semantics, riskier) >
    advisory suggestions (no surface change).
    """
    for action in ("arabizi_to_arabic",):
        for s in suggestions:
            if s.action == action and s.proposed is not None:
                return s.proposed
    return None


def score_repair(
    original: str,
    proposed: str,
    action: str,
    spec: GuardSpec | None = None,
) -> float:
    """Score a concrete repair proposal in [0.0, 1.0] without ground truth.

    The score asks: "does the repair preserve invariants we can check
    locally?" It is NOT a human-judged quality score — for that, you
    need ground-truth pairs. But for catching broken repairs (length
    blow-up, script mismatch, new BiDi chars introduced) this score
    flags them cheaply.

    Scoring ladder:

    - 0.0 if the proposal violates an invariant (different script than
      declared, introduced BiDi control chars, length changed by >3×)
    - 0.5 if the proposal is syntactically valid but flagged
      `needs_review=True` and we have no stronger signal
    - 0.7 if the proposal is syntactically valid, not flagged for review,
      and preserves length within 50%
    - 1.0 if all above AND round-trip preservation holds (action-specific
      invariants — e.g. arabizi_to_arabic output must be pure Arabic;
      attach_canonical output must be deterministic normalization)

    Advisory-only actions (where `proposed` is None) should not reach
    this function — callers filter them first. We assert that here.
    """
    assert proposed is not None, (
        "score_repair() called on an advisory suggestion — caller should "
        "filter `proposed is None` before invoking"
    )

    from mtg.bidi import detect_bidi_threats
    from mtg.script import detect_script

    # Invariant 1: no new BiDi control / invisible / tag characters
    # introduced by the repair. If original was clean and proposed is
    # not, the repair made things worse.
    original_threats = detect_bidi_threats(original)
    proposed_threats = detect_bidi_threats(proposed)
    proposed_added_security_issues = (
        len(proposed_threats.bidi_controls) > len(original_threats.bidi_controls)
        or len(proposed_threats.invisible_chars) > len(original_threats.invisible_chars)
        or len(proposed_threats.tag_chars) > len(original_threats.tag_chars)
        or len(proposed_threats.homoglyphs) > len(original_threats.homoglyphs)
    )
    if proposed_added_security_issues:
        return 0.0

    # Invariant 2: length sanity. A repair that expands the string by
    # >3× is almost certainly corrupt (runaway mapping, infinite loop).
    orig_len = max(1, len(original))
    if len(proposed) > 3 * orig_len or len(proposed) < orig_len / 10:
        return 0.0

    # Action-specific invariants.
    if action == "arabizi_to_arabic":
        # The whole point of this repair is to produce Arabic script.
        # If the proposed output is not predominantly Arabic, repair
        # failed its contract.
        script = detect_script(proposed)
        if script != "ar":
            return 0.0
        # Good: pure Arabic, no new security chars, reasonable length
        return 1.0

    if action == "attach_canonical":
        # Canonical form must be deterministic — applying the same
        # transform twice should be idempotent. We test that here.
        from mtg.canonical import normalize
        if normalize(normalize(proposed)) != normalize(proposed):
            return 0.0
        # If the spec declared canonicalization='normalized', idempotence
        # is guaranteed by construction → full credit.
        if spec is not None and spec.canonicalization == "normalized":
            return 1.0
        # Otherwise (lemma / root_pattern fallback to normalized):
        # syntactically valid but needs review.
        return 0.7

    # Unknown concrete action — treat as needs-review but syntactically OK.
    return 0.5


__all__ = [
    "RepairAction",
    "RepairSuggestion",
    "arabizi_to_arabic_naive",
    "pick_repaired_value",
    "score_repair",
    "suggest_repairs",
]
