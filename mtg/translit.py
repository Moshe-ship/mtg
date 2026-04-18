"""Arabizi / transliteration detection.

Arabizi (also called Franco-Arabic, Romanized Arabic) uses Latin letters
and digit-letter substitutions (2 for ء, 3 for ع, 7 for ح, 9 for ص) to
write Arabic. MTG flags this when a field declares ar script but is Latin.
"""

from __future__ import annotations

import re

from mtg.script import detect_script

# Digit-letter substitutions canonical to Arabizi.
_ARABIZI_DIGITS = re.compile(r"\b\w*[23579]\w*\b", re.UNICODE)

# Common Arabizi tokens that rarely appear in English but are very common
# in Romanized Arabic (dialect markers, greetings, and function words).
_ARABIZI_MARKERS = frozenset({
    "abi", "abgha", "aywa", "inshallah", "mashallah", "wallah", "yalla",
    "habibi", "habibti", "akhi", "ukhti", "sa7bi", "sa7bti",
    "bismillah", "alhamdulillah", "salam", "assalamu",
    "3aleykum", "a7la", "a7sant", "3arabi", "3adi",
    "3al", "3ala", "3andi", "ba3den", "ba3d",
    "mush", "mesh", "ma3ak", "wen", "wein", "fen",
    "bikun", "bikum", "bte7ki", "bhebak",
})

_ARABIZI_SUBSTITUTIONS = re.compile(
    r"[a-z][2357][a-z]|[a-z][a-z][2357]|[2357][a-z][a-z]",
    re.IGNORECASE,
)


def looks_like_arabizi(text: str) -> bool:
    """Heuristic — does this Latin-script text look like Arabizi?

    Returns False for pure English or mixed-language content that happens
    to contain a number. Returns True when digit-letter substitutions OR
    known Arabizi markers dominate.
    """
    if not text:
        return False

    if detect_script(text) != "latn":
        return False

    lowered = text.lower()
    words = re.findall(r"[a-z0-9']+", lowered)
    if not words:
        return False

    # Strong signal: known Arabizi function words.
    marker_hits = sum(1 for w in words if w in _ARABIZI_MARKERS)
    if marker_hits >= 1 and len(words) <= 12:
        return True

    # Weaker signal: digit-letter substitutions.
    sub_hits = len(_ARABIZI_SUBSTITUTIONS.findall(lowered))
    if sub_hits >= 1 and len(words) <= 20:
        return True

    # Combine signals — needed for longer text.
    if marker_hits + sub_hits >= 2:
        return True

    return False


def transliteration_violation_detected(
    text: str,
    declared_script: str,
    allowed: bool,
) -> bool:
    """True when the value violates `transliteration_allowed: false`."""
    if allowed:
        return False
    if declared_script not in ("ar", "fa"):
        return False
    return looks_like_arabizi(text)
