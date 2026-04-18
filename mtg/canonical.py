"""Canonicalization transforms for Arabic text.

Four canonicalization modes (per spec/taxonomy.md):

- `none`            — return surface
- `lemma`           — strip diacritics + unify alef/ya/ta-marbuta + use lemma if available
- `root_pattern`    — format as "<root>/<pattern>" when available; fall back to normalized
- `normalized`      — alef/ya/ta-marbuta unification + tatweel strip
"""

from __future__ import annotations

from mtg.types import Analysis

_TATWEEL = "\u0640"
_ALEF_VARIANTS = str.maketrans({"\u0622": "\u0627", "\u0623": "\u0627", "\u0625": "\u0627"})
_YA_VARIANT = str.maketrans({"\u0649": "\u064A"})
_TA_MARBUTA = str.maketrans({"\u0629": "\u0647"})
# Arabic diacritics (Harakat) — U+064B..U+065F plus superscript alef U+0670
_HARAKAT = frozenset(chr(cp) for cp in range(0x064B, 0x0660)) | frozenset({"\u0670"})


def strip_diacritics(text: str) -> str:
    """Remove tashkeel (harakat) and tatweel."""
    return "".join(ch for ch in text if ch not in _HARAKAT and ch != _TATWEEL)


def normalize(text: str) -> str:
    """Apply the standard MTG normalization chain."""
    out = strip_diacritics(text)
    out = out.translate(_ALEF_VARIANTS)
    out = out.translate(_YA_VARIANT)
    out = out.translate(_TA_MARBUTA)
    return out.strip()


def canonicalize(
    surface: str,
    mode: str,
    analyses: list[Analysis],
) -> tuple[str, bool]:
    """Return (canonical_form, succeeded).

    `succeeded` is False when the requested canonicalization could not be
    computed (e.g. root_pattern requested but no backend analysis).
    """
    if mode == "none":
        return surface, True

    if mode == "normalized":
        return normalize(surface), True

    if mode == "lemma":
        for analysis in analyses:
            if analysis.lemma:
                return analysis.lemma, True
        return normalize(surface), False

    if mode == "root_pattern":
        for analysis in analyses:
            if analysis.root and analysis.pattern:
                return f"{analysis.root}/{analysis.pattern}", True
        return normalize(surface), False

    # Unknown mode — treat as none
    return surface, True
