"""MTG validation pipeline.

Orchestrates script detection, transliteration probe, dialect classification,
morphological analysis, canonicalization, and violation emission.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from mtg.canonical import canonicalize, normalize
from mtg.dialect import get_dialect_backend, KeywordDialectClassifier
from mtg.morph import get_morph_backend
from mtg.morph_fallback import SurfaceOnlyMorphBackend
from mtg.script import detect_script, matches_required_script
from mtg.translit import transliteration_violation_detected
from mtg.types import (
    Analysis,
    GuardResult,
    GuardSpec,
    Violation,
)


_DIALECT_CONFIDENCE_FLOOR = 0.75

# Ambiguity threshold: if two morph analyses are within this confidence,
# consider it ambiguous and skip canonicalization.
_MORPH_AMBIGUITY_DELTA = 0.15


def _validate_mode(spec: GuardSpec) -> None:
    if spec.mode == "reconciled":
        raise NotImplementedError(
            "reconciled mode is defined in spec/resolution.md but not shipped in v0.1.0"
        )
    if spec.mode == "enforced":
        raise NotImplementedError(
            "enforced mode is defined in spec/resolution.md but not shipped in v0.1.0"
        )


def _pre_call_violations(
    value: str,
    spec: GuardSpec,
    analysis: Analysis,
) -> list[Violation]:
    violations: list[Violation] = []

    # Script
    if spec.script != "any" and not matches_required_script(value, spec.script):
        detected = detect_script(value)
        violations.append(
            Violation(
                code="SCRIPT_VIOLATION",
                severity="high",
                phase="pre",
                message=f"expected script '{spec.script}', detected '{detected}'",
                details={"expected": spec.script, "detected": detected},
            )
        )

    # Transliteration
    if transliteration_violation_detected(value, spec.script, spec.transliteration_allowed):
        violations.append(
            Violation(
                code="TRANSLITERATION_VIOLATION",
                severity="high",
                phase="pre",
                message="value appears to be Arabizi / Romanized Arabic but transliteration_allowed=false",
                details={"script": spec.script},
            )
        )

    # Dialect drift (only when script is ar and a specific dialect expected)
    if spec.script == "ar" and spec.dialect_expected != "any":
        detected_dialect = analysis.dialect_detected or "unknown"
        confidence = analysis.dialect_confidence
        if detected_dialect != spec.dialect_expected and confidence >= _DIALECT_CONFIDENCE_FLOOR:
            severity = "medium" if spec.dialect_enforcement != "advisory" else "info"
            violations.append(
                Violation(
                    code="DIALECT_DRIFT",
                    severity=severity,
                    phase="pre",
                    message=f"expected dialect '{spec.dialect_expected}', detected '{detected_dialect}' (conf {confidence:.2f})",
                    details={
                        "expected": spec.dialect_expected,
                        "detected": detected_dialect,
                        "confidence": confidence,
                        "enforcement": spec.dialect_enforcement,
                    },
                )
            )

    # Morph ambiguity and canonicalization failure are tracked in the Analysis
    return violations


def _post_call_violations(
    value_before: str,
    value_after: str,
    spec: GuardSpec,
    analysis_before: Analysis,
    analysis_after: Analysis | None,
) -> list[Violation]:
    violations: list[Violation] = []

    if "script_match" in spec.post_call_contract and spec.script != "any":
        if not matches_required_script(value_after, spec.script):
            detected = detect_script(value_after)
            violations.append(
                Violation(
                    code="SURFACE_CORRUPTION_POST_CALL",
                    severity="high",
                    phase="post",
                    message=f"response script mismatch: expected '{spec.script}', got '{detected}'",
                    details={"expected": spec.script, "detected": detected},
                )
            )

    if "no_surface_corruption" in spec.post_call_contract or spec.script == "ar":
        norm_before = normalize(value_before)
        norm_after = normalize(value_after)
        if norm_before != norm_after:
            similarity = SequenceMatcher(None, norm_before, norm_after).ratio()
            tolerance = max(2, int(0.05 * len(norm_before)))
            edit_approx = int(len(norm_before) * (1 - similarity))
            if edit_approx > tolerance:
                violations.append(
                    Violation(
                        code="SURFACE_CORRUPTION_POST_CALL",
                        severity="high",
                        phase="post",
                        message="response parameter diverged from input beyond tolerance",
                        details={
                            "similarity": round(similarity, 3),
                            "tolerance_edits": tolerance,
                        },
                    )
                )

    if (
        "dialect_preserve" in spec.post_call_contract
        and spec.script == "ar"
        and spec.dialect_expected != "any"
        and analysis_after is not None
    ):
        detected_after = analysis_after.dialect_detected or "unknown"
        if detected_after != spec.dialect_expected and analysis_after.dialect_confidence >= _DIALECT_CONFIDENCE_FLOOR:
            violations.append(
                Violation(
                    code="DIALECT_FLATTEN",
                    severity="medium",
                    phase="post",
                    message=f"response dialect '{detected_after}' differs from expected '{spec.dialect_expected}'",
                    details={
                        "expected": spec.dialect_expected,
                        "detected": detected_after,
                    },
                )
            )

    if (
        "root_preserve" in spec.post_call_contract
        and spec.morphologically_productive
        and analysis_after is not None
        and analysis_before.root
        and analysis_after.root
        and analysis_before.root != analysis_after.root
    ):
        violations.append(
            Violation(
                code="ROOT_DRIFT",
                severity="medium",
                phase="post",
                message=f"root changed across call: {analysis_before.root} → {analysis_after.root}",
                details={
                    "before": analysis_before.root,
                    "after": analysis_after.root,
                },
            )
        )

    return violations


def _analyze(value: str, spec: GuardSpec) -> Analysis:
    """Run the analysis stack on a single value."""
    script = detect_script(value)

    # Dialect (only makes sense for Arabic)
    dialect, dialect_confidence = "unknown", 0.0
    if spec.script == "ar" or script == "ar":
        backend = get_dialect_backend()
        dialect, dialect_confidence = backend.classify(value)
        if isinstance(backend, KeywordDialectClassifier) and dialect_confidence < _DIALECT_CONFIDENCE_FLOOR:
            # Low-confidence fallback dialect — flagged downstream but still recorded.
            pass

    # Morph (only for factorable + productive slots in Arabic)
    morph_backend = get_morph_backend()
    analyses: list[Analysis] = []
    if spec.morphologically_productive and spec.is_factorable and spec.script == "ar":
        analyses = morph_backend.analyze(value)

    if analyses:
        top = analyses[0]
        second_conf = analyses[1].morph_confidence if len(analyses) > 1 else 0.0
        ambiguous = (top.morph_confidence - second_conf) < _MORPH_AMBIGUITY_DELTA and len(analyses) > 1
        return Analysis(
            script_detected=script,
            dialect_detected=dialect,
            dialect_confidence=dialect_confidence,
            root=None if ambiguous else top.root,
            pattern=None if ambiguous else top.pattern,
            lemma=top.lemma,
            morph_confidence=top.morph_confidence,
            backend=top.backend,
            backend_available=top.backend_available,
        )

    # No productive analysis — either not requested or backend unavailable
    return Analysis(
        script_detected=script,
        dialect_detected=dialect,
        dialect_confidence=dialect_confidence,
        root=None,
        pattern=None,
        lemma=None,
        morph_confidence=0.0,
        backend=(morph_backend.backend_name if morph_backend else "none"),
        backend_available=not isinstance(morph_backend, SurfaceOnlyMorphBackend),
    )


def validate_pre(value: str, spec: GuardSpec) -> GuardResult:
    """Run pre-call validation. Never mutates inputs."""
    _validate_mode(spec)
    if value is None:  # defensive
        value = ""

    analysis = _analyze(value, spec)
    violations = _pre_call_violations(value, spec, analysis)

    # Morph canonicalization failure + ambiguity annotations
    if spec.morphologically_productive and spec.script == "ar":
        if not analysis.backend_available:
            violations.append(
                Violation(
                    code="MORPH_CANONICALIZATION_FAILURE",
                    severity="low",
                    phase="pre",
                    message="morphology backend unavailable; falling back to surface-only",
                    details={"backend": analysis.backend},
                )
            )
        elif analysis.root is None and analysis.backend != "fallback":
            violations.append(
                Violation(
                    code="MORPH_AMBIGUITY",
                    severity="low",
                    phase="pre",
                    message="multiple analyses within ambiguity threshold; skipped canonicalization",
                    details={"threshold": _MORPH_AMBIGUITY_DELTA},
                )
            )

    return GuardResult(
        surface=value,
        analysis=analysis,
        violations=tuple(violations),
        mode=spec.mode,
    )


def validate_post(
    pre_result: GuardResult,
    response_value: str,
    spec: GuardSpec,
) -> GuardResult:
    """Run post-call validation. Combines pre violations with post violations."""
    _validate_mode(spec)
    if response_value is None:
        response_value = ""

    analysis_after = _analyze(response_value, spec)
    post = _post_call_violations(
        pre_result.surface,
        response_value,
        spec,
        pre_result.analysis,
        analysis_after,
    )
    combined = tuple(pre_result.violations) + tuple(post)
    return GuardResult(
        surface=pre_result.surface,
        analysis=pre_result.analysis,
        violations=combined,
        mode=spec.mode,
    )


def run(value: str, spec: GuardSpec) -> GuardResult:
    """Convenience wrapper — runs pre-call validation only."""
    return validate_pre(value, spec)


def apply_canonicalization(guard_result: GuardResult, spec: GuardSpec) -> tuple[str, bool]:
    """Produce the canonical form for a guard result (surface + analyses)."""
    analyses = [guard_result.analysis] if guard_result.analysis else []
    return canonicalize(guard_result.surface, spec.canonicalization, analyses)
