"""MTG validation pipeline.

Orchestrates script detection, transliteration probe, dialect classification,
morphological analysis, canonicalization, and violation emission.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from mtg.bidi import detect_bidi_threats
from mtg.canonical import canonicalize, normalize
from mtg.dialect import get_dialect_backend, KeywordDialectClassifier
from mtg.morph import get_morph_backend
from mtg.morph_fallback import SurfaceOnlyMorphBackend
from mtg.script import detect_script, is_arabic_char, matches_required_script
from mtg.translit import transliteration_violation_detected
from mtg.types import (
    Analysis,
    FACTORABLE_SLOTS,
    GuardResult,
    GuardSpec,
    Violation,
)


_DIALECT_CONFIDENCE_FLOOR = 0.75

# Ambiguity threshold: if two morph analyses are within this confidence,
# consider it ambiguous and skip canonicalization.
_MORPH_AMBIGUITY_DELTA = 0.15

# Fraction of tokens that must look non-factorable before FREE_TEXT_OVERFLOW
# fires on a factorable slot. Spec says ">70% named-entity tokens, all-numeric".
_FREE_TEXT_OVERFLOW_RATIO = 0.7


def _token_looks_non_factorable(token: str) -> bool:
    """Heuristic: does this whitespace token look like free-text filler
    for a factorable slot (identifier, numeric, latin-only)?

    Returns True for tokens that are:
    - pure numeric (with optional sign / decimal / thousand separators)
    - latin-dominant alphanumerics (ascii-only, id-like)
    - pure punctuation / symbols
    Returns False for tokens carrying any Arabic letter.
    """
    if not token:
        return False

    if any(is_arabic_char(ch) for ch in token):
        return False

    stripped = token.strip(".,;:!?()[]{}\"'،؛")
    if not stripped:
        return True

    if stripped.replace(".", "").replace(",", "").replace("-", "").replace("_", "").isdigit():
        return True

    ascii_alnum = sum(1 for c in stripped if c.isascii() and (c.isalnum() or c in "-_"))
    if ascii_alnum / max(1, len(stripped)) >= 0.7:
        return True

    return False


def _free_text_overflow_detected(value: str) -> tuple[bool, float]:
    """Is `value` dominantly non-factorable content?

    Returns (overflow_detected, non_factorable_fraction).
    """
    tokens = value.split()
    if not tokens:
        return False, 0.0
    nf = sum(1 for t in tokens if _token_looks_non_factorable(t))
    ratio = nf / len(tokens)
    return ratio > _FREE_TEXT_OVERFLOW_RATIO, ratio


def _validate_mode(spec: GuardSpec) -> None:
    """Check that `spec.mode` is implemented in the current runtime.

    - `advisory`   — always supported.
    - `reconciled` — supported since v0.2.0: runs detection, then emits
                     RepairSuggestion records via mtg.repair; proposals
                     are never applied silently.
    - `enforced`   — NOT shipped; policy decisions happen at the caller.
    """
    if spec.mode == "enforced":
        raise NotImplementedError(
            "enforced mode is defined in spec/resolution.md but not shipped; "
            "use 'reconciled' and let the caller decide whether to block on "
            "high-severity outcomes"
        )


def _bidi_violations(value: str) -> list[Violation]:
    """Security pre-flight: BiDi control smuggling, invisible padding,
    tag characters, homoglyphs, mixed-script tokens. Runs on every
    guarded value regardless of declared `script`. These are security
    issues, not linguistic preferences — high severity by default.

    Detects the CVE-2021-42574 ("Trojan Source") attack family at the
    tool-argument level.
    """
    violations: list[Violation] = []
    finding = detect_bidi_threats(value)
    if not finding.any():
        return violations

    if finding.bidi_controls:
        violations.append(
            Violation(
                code="BIDI_CONTROL_SMUGGLING",
                severity="high",
                phase="pre",
                message=(
                    f"value contains {len(finding.bidi_controls)} Unicode BiDi "
                    f"control character(s) (U+202A..U+202E, U+2066..U+2069) — "
                    f"these reorder DISPLAY without changing LOGICAL content "
                    f"and are the CVE-2021-42574 attack class"
                ),
                details={
                    "codepoints": [hex(ord(c)) for c in finding.bidi_controls],
                    "count": len(finding.bidi_controls),
                },
            )
        )

    if finding.tag_chars:
        violations.append(
            Violation(
                code="BIDI_CONTROL_SMUGGLING",
                severity="high",
                phase="pre",
                message=(
                    f"value contains {len(finding.tag_chars)} Unicode TAG "
                    f"character(s) (U+E0020..U+E007F) — invisible code points "
                    f"used in LLM prompt-injection attacks"
                ),
                details={
                    "codepoints": [hex(ord(c)) for c in finding.tag_chars],
                    "count": len(finding.tag_chars),
                },
            )
        )

    if finding.invisible_chars:
        violations.append(
            Violation(
                code="INVISIBLE_CONTENT",
                severity="medium",
                phase="pre",
                message=(
                    f"value contains {len(finding.invisible_chars)} zero-width / "
                    f"invisible character(s) — padding and laundering signal"
                ),
                details={
                    "codepoints": [hex(ord(c)) for c in finding.invisible_chars],
                    "count": len(finding.invisible_chars),
                },
            )
        )

    if finding.homoglyphs:
        violations.append(
            Violation(
                code="SCRIPT_HOMOGLYPH",
                severity="medium",
                phase="pre",
                message=(
                    f"value contains {len(finding.homoglyphs)} homoglyph "
                    f"character(s) from lookalike scripts (Cyrillic/Greek/Arabic-Indic "
                    f"digits) — script laundering signal"
                ),
                details={
                    "pairs": [
                        {"glyph": g, "codepoint": hex(ord(g)), "latin_lookalike": lat}
                        for g, lat in finding.homoglyphs
                    ],
                    "count": len(finding.homoglyphs),
                },
            )
        )

    if finding.mixed_script_within_token:
        violations.append(
            Violation(
                code="SCRIPT_HOMOGLYPH",
                severity="medium",
                phase="pre",
                message=(
                    "value contains a token that mixes scripts (e.g. Cyrillic + "
                    "Latin within one word) — strong laundering signal"
                ),
                details={"reason": "mixed_script_within_token"},
            )
        )

    # BIDI_MARKS alone (LRM/RLM) are sometimes legitimate in Arabic text
    # adjacent to Latin punctuation; flag only when combined with other
    # signals to keep false-positive rate low.
    if finding.bidi_marks and (
        finding.bidi_controls or finding.invisible_chars or finding.homoglyphs
    ):
        violations.append(
            Violation(
                code="BIDI_CONTROL_SMUGGLING",
                severity="medium",
                phase="pre",
                message=(
                    f"value contains {len(finding.bidi_marks)} BiDi mark(s) "
                    f"(U+200E/U+200F) alongside other suspicious characters"
                ),
                details={
                    "codepoints": [hex(ord(c)) for c in finding.bidi_marks],
                    "count": len(finding.bidi_marks),
                },
            )
        )

    return violations


def _pre_call_violations(
    value: str,
    spec: GuardSpec,
    analysis: Analysis,
) -> list[Violation]:
    violations: list[Violation] = []

    # BiDi / RTL security pre-flight — always runs, regardless of declared
    # script. Security issues take priority over linguistic constraints.
    violations.extend(_bidi_violations(value))

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
    violations: list[Violation] = []

    # FREE_TEXT_OVERFLOW — detect BEFORE the morph annotations so the
    # downgraded analysis flows through to canonical_form_required and the
    # returned GuardResult. Taxonomy contract: overflow "downgrades
    # morphological analysis for that call", so we strip root/pattern/lemma
    # and zero morph_confidence. Dialect detection is preserved because
    # overflow is about morphology, not dialect.
    downgraded = False
    overflow_ratio = 0.0
    if spec.is_factorable and value and spec.script in ("ar", "mixed", "any"):
        overflow, overflow_ratio = _free_text_overflow_detected(value)
        if overflow:
            downgraded = True
            violations.append(
                Violation(
                    code="FREE_TEXT_OVERFLOW",
                    severity="medium",
                    phase="pre",
                    message=(
                        f"factorable slot '{spec.slot_type}' received value with "
                        f"{overflow_ratio:.0%} non-factorable tokens; morphology downgraded"
                    ),
                    details={
                        "slot_type": spec.slot_type,
                        "non_factorable_ratio": round(overflow_ratio, 3),
                        "threshold": _FREE_TEXT_OVERFLOW_RATIO,
                        "downgraded": True,
                    },
                )
            )
            # Strip morphology — root/pattern/lemma are meaningless here.
            analysis = Analysis(
                script_detected=analysis.script_detected,
                dialect_detected=analysis.dialect_detected,
                dialect_confidence=analysis.dialect_confidence,
                root=None,
                pattern=None,
                lemma=None,
                morph_confidence=0.0,
                backend=analysis.backend,
                backend_available=analysis.backend_available,
                ensemble_agreement=analysis.ensemble_agreement,
            )

    violations.extend(_pre_call_violations(value, spec, analysis))

    # Morph canonicalization failure + ambiguity annotations — suppressed
    # when overflow downgraded morphology, since those codes describe a
    # productive-slot failure, not a free-text-overflow downgrade.
    if spec.morphologically_productive and spec.script == "ar" and not downgraded:
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

    # canonical_form_required — the schema author declared that a canonical
    # form MUST be derivable at validation time. We call canonicalize() on
    # the (possibly downgraded) analysis and emit a high-severity violation
    # when the requested form cannot be produced. This is a derivability
    # requirement, not a wire-format requirement: the call payload is NOT
    # expected to carry the canonical form; the pipeline is expected to
    # compute it. See spec/mtg.schema.json.
    if spec.canonical_form_required and spec.canonicalization not in ("none",):
        canonical, succeeded = canonicalize(value, spec.canonicalization, [analysis])
        if not succeeded:
            violations.append(
                Violation(
                    code="CANONICALIZATION_REQUIRED",
                    severity="high",
                    phase="pre",
                    message=(
                        f"canonical_form_required=true but '{spec.canonicalization}' "
                        f"canonicalization could not be produced (backend={analysis.backend})"
                    ),
                    details={
                        "canonicalization": spec.canonicalization,
                        "backend": analysis.backend,
                        "fallback_surface": canonical,
                        "downgraded_by_overflow": downgraded,
                    },
                )
            )

    # Reconciled mode — emit repair suggestions for the subset of
    # violations that can be meaningfully repaired. Advisory mode never
    # calls repair. See mtg/repair.py for the repair policy.
    repairs: tuple = ()
    repaired_surface: str | None = None
    if spec.mode == "reconciled" and violations:
        from mtg.repair import pick_repaired_value, suggest_repairs

        repair_list = suggest_repairs(value, spec, analysis, violations)
        repairs = tuple(repair_list)
        repaired_surface = pick_repaired_value(value, repair_list)

    return GuardResult(
        surface=value,
        analysis=analysis,
        violations=tuple(violations),
        mode=spec.mode,
        repairs=repairs,
        repaired_surface=repaired_surface,
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
