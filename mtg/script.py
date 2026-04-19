"""Unicode script detection for MTG guards.

Pure-Python. No external dependencies. Detects Arabic, Latin, Hebrew,
Persian-specific characters, and mixed-script content.
"""

from __future__ import annotations

from typing import Literal

ScriptLabel = Literal["ar", "latn", "he", "fa", "mixed", "empty", "other"]

# Arabic script blocks (covers MSA + dialectal Arabic)
_ARABIC_RANGES = [
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
]

# Hebrew block
_HEBREW_RANGES = [(0x0590, 0x05FF)]

# Persian-specific characters (on top of Arabic script)
_PERSIAN_SPECIFIC = frozenset({"\u067E", "\u0686", "\u0698", "\u06AF"})  # پ چ ژ گ

_LATIN_RANGES = [
    (0x0041, 0x005A),  # A-Z
    (0x0061, 0x007A),  # a-z
    (0x00C0, 0x024F),  # Latin Extended
]


def _in_ranges(cp: int, ranges: list[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start <= cp <= end:
            return True
    return False


def is_arabic_char(ch: str) -> bool:
    return _in_ranges(ord(ch), _ARABIC_RANGES)


def is_hebrew_char(ch: str) -> bool:
    return _in_ranges(ord(ch), _HEBREW_RANGES)


def is_latin_char(ch: str) -> bool:
    return _in_ranges(ord(ch), _LATIN_RANGES)


def detect_script(text: str) -> ScriptLabel:
    """Detect the dominant script of a string.

    Returns:
        "empty" if no alphabetic characters.
        "ar", "he", "latn" if one script dominates (>= 80% of alpha chars).
        "fa" if Arabic script + Persian-specific characters.
        "mixed" if more than one script has >= 20% share.
        "other" for CJK, Cyrillic, etc.
    """
    if not text:
        return "empty"

    ar = he = latn = other = 0
    persian = False
    for ch in text:
        if ch in _PERSIAN_SPECIFIC:
            persian = True
            ar += 1
        elif is_arabic_char(ch):
            ar += 1
        elif is_hebrew_char(ch):
            he += 1
        elif is_latin_char(ch):
            latn += 1
        elif ch.isalpha():
            other += 1

    total = ar + he + latn + other
    if total == 0:
        return "empty"

    if persian and ar >= total * 0.5:
        return "fa"

    shares = {
        "ar": ar / total,
        "he": he / total,
        "latn": latn / total,
    }
    dominant = max(shares, key=shares.get)  # type: ignore[arg-type]
    if shares[dominant] >= 0.8:
        return dominant  # type: ignore[return-value]

    # >=20% from two or more scripts → mixed
    non_trivial = sum(1 for v in shares.values() if v >= 0.2)
    if non_trivial >= 2:
        return "mixed"

    return "other"


def matches_required_script(text: str, required: str) -> bool:
    """Does `text` match `required` script declaration?

    Script semantics:
    - "any"   → everything passes
    - "mixed" → permissive, accepts ar, latn, or genuinely mixed content
                (but not hebrew/persian/other). Schema authors use "mixed"
                for named-entity-like fields that can be either script.
    - "ar", "latn", "he", "fa" → strict, requires detected script to match.
    - empty input → always passes (non-empty checks are caller's job).
    """
    if required == "any":
        return True
    detected = detect_script(text)
    if detected == "empty":
        return True
    if required == "mixed":
        return detected in ("ar", "latn", "mixed")
    return detected == required
