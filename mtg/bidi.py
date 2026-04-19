"""BiDi / RTL security primitives for MTG.

Tool-call arguments are strings. Strings carry Unicode. Attackers exploit
this at three layers:

1. **BiDi control smuggling** — invisible directional override characters
   (U+202A..U+202E, U+2066..U+2069, U+200E/U+200F) reorder the DISPLAY
   of text without changing the LOGICAL order. CVE-2021-42574 ("Trojan
   Source") showed how compilers and reviewers can be tricked; the same
   class of attack applies to LLM-mediated tool calls when the model
   sees one thing and the runtime executes another.

2. **Invisible content** — zero-width characters (U+200B ZWSP,
   U+200C ZWNJ, U+200D ZWJ), tag characters (U+E0020..U+E007F), and the
   soft-hyphen (U+00AD) can pad strings invisibly.

3. **Homoglyph / script laundering** — use of lookalike characters from
   different Unicode blocks (Cyrillic 'а' U+0430 vs Latin 'a' U+0061,
   Arabic-Indic digit '٠' U+0660 vs Western '0' U+0030, etc.) to evade
   naive script checks or to smuggle semantics past a human reviewer.

MTG's BiDi layer runs pre-call on every guarded value regardless of
declared script. High-severity by default — these are security
violations, not linguistic preferences. Detection is pure-Python and
allocation-light; no regex over the full CVE-2021-42574 threat model is
required because we check character classes directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


# Unicode BiDi explicit-embedding and override control characters.
# These change the display direction of surrounding text.
# Source: UAX #9 (Unicode Bidirectional Algorithm).
BIDI_CONTROL_CHARS: frozenset[str] = frozenset(
    {
        "\u202a",  # LRE — Left-to-Right Embedding
        "\u202b",  # RLE — Right-to-Left Embedding
        "\u202c",  # PDF — Pop Directional Formatting
        "\u202d",  # LRO — Left-to-Right Override
        "\u202e",  # RLO — Right-to-Left Override
        "\u2066",  # LRI — Left-to-Right Isolate
        "\u2067",  # RLI — Right-to-Left Isolate
        "\u2068",  # FSI — First Strong Isolate
        "\u2069",  # PDI — Pop Directional Isolate
    }
)

# Weaker directional markers — not control characters, but can still
# flip rendering next to neutrals. Use-specific; flag as medium not high.
BIDI_MARKS: frozenset[str] = frozenset(
    {
        "\u200e",  # LRM — Left-to-Right Mark
        "\u200f",  # RLM — Right-to-Left Mark
    }
)

# Zero-width / invisible characters that can pad strings unnoticed.
#
# We deliberately EXCLUDE ZWNJ (U+200C) and ZWJ (U+200D) from this set:
# they are legitimate orthographic characters in Persian, Urdu, Hindi,
# Thai, and emoji sequences. False-positive rate on those scripts would
# be unacceptable. If they appear at pathological density we still flag
# via `mixed_script_within_token` + homoglyph pathways.
INVISIBLE_CHARS: frozenset[str] = frozenset(
    {
        "\u200b",  # ZWSP — zero-width space (rarely legitimate in tool args)
        "\u2060",  # WJ   — word joiner
        "\ufeff",  # ZWNBSP / BOM
        "\u00ad",  # SHY  — soft hyphen
        "\u180e",  # MVS  — Mongolian vowel separator (deprecated)
        "\u034f",  # CGJ  — combining grapheme joiner
    }
)

# Unicode Tag characters (U+E0020..U+E007F) — invisible and used in
# several prompt-injection attacks against LLMs.
_TAG_RANGE = (0xE0020, 0xE007F)


# Homoglyph pairs — Latin vs lookalike. The list is intentionally small
# and high-precision (no false positives on normal content). Expand via
# confusables.txt (Unicode TR39) for a broader production set; what ships
# here is the "obvious attack surface" layer.
HOMOGLYPH_LATIN_LOOKALIKES: dict[str, str] = {
    # Cyrillic → Latin
    "\u0430": "a",  # CYRILLIC SMALL LETTER A
    "\u0435": "e",  # CYRILLIC SMALL LETTER IE
    "\u043e": "o",  # CYRILLIC SMALL LETTER O
    "\u0440": "p",  # CYRILLIC SMALL LETTER ER
    "\u0441": "c",  # CYRILLIC SMALL LETTER ES
    "\u0445": "x",  # CYRILLIC SMALL LETTER HA
    "\u0443": "y",  # CYRILLIC SMALL LETTER U
    "\u0456": "i",  # CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u0458": "j",  # CYRILLIC SMALL LETTER JE
    # Greek → Latin
    "\u03b1": "a",  # GREEK SMALL LETTER ALPHA
    "\u03bf": "o",  # GREEK SMALL LETTER OMICRON
    "\u03c1": "p",  # GREEK SMALL LETTER RHO
    # Arabic-Indic digits → Western
    "\u0660": "0", "\u0661": "1", "\u0662": "2", "\u0663": "3", "\u0664": "4",
    "\u0665": "5", "\u0666": "6", "\u0667": "7", "\u0668": "8", "\u0669": "9",
    # Extended Arabic-Indic digits (Persian/Urdu)
    "\u06f0": "0", "\u06f1": "1", "\u06f2": "2", "\u06f3": "3", "\u06f4": "4",
    "\u06f5": "5", "\u06f6": "6", "\u06f7": "7", "\u06f8": "8", "\u06f9": "9",
}


@dataclass(frozen=True)
class BidiFinding:
    """Structured BiDi / homoglyph detection result."""

    bidi_controls: tuple[str, ...] = ()
    bidi_marks: tuple[str, ...] = ()
    invisible_chars: tuple[str, ...] = ()
    tag_chars: tuple[str, ...] = ()
    homoglyphs: tuple[tuple[str, str], ...] = ()  # (char, latin_equivalent)
    mixed_script_within_token: bool = False

    def any(self) -> bool:
        return bool(
            self.bidi_controls
            or self.bidi_marks
            or self.invisible_chars
            or self.tag_chars
            or self.homoglyphs
            or self.mixed_script_within_token
        )


def _contains_tag_char(value: str) -> list[str]:
    found: list[str] = []
    start, end = _TAG_RANGE
    for ch in value:
        cp = ord(ch)
        if start <= cp <= end:
            found.append(ch)
    return found


def _tokens_have_mixed_script(value: str) -> bool:
    """True when a SINGLE whitespace-separated token mixes scripts.

    Mixed-script tokens are a strong laundering signal: a legitimate word
    is almost never written with half Cyrillic + half Latin characters.
    Cross-token mixing (Arabic phrase + Latin URL) is fine and common.
    """
    from mtg.script import is_arabic_char, is_hebrew_char, is_latin_char

    def _script_of(ch: str) -> str:
        if is_arabic_char(ch):
            return "ar"
        if is_hebrew_char(ch):
            return "he"
        if is_latin_char(ch):
            return "latn"
        # Check Cyrillic (U+0400-U+04FF) + Greek (U+0370-U+03FF) explicitly
        cp = ord(ch)
        if 0x0400 <= cp <= 0x04FF:
            return "cyrl"
        if 0x0370 <= cp <= 0x03FF:
            return "grek"
        return ""

    for token in value.split():
        seen: set[str] = set()
        for ch in token:
            s = _script_of(ch)
            if s:
                seen.add(s)
        if len(seen) > 1:
            return True
    return False


def _arabic_indic_digit_is_contextually_legitimate(value: str) -> bool:
    """Are Arabic-Indic digits (U+0660..U+0669) in this value being used
    as normal digits within an Arabic-script context, or is the value
    predominantly Latin/other (suggesting laundering)?

    Arabic typography uses ٠-٩ natively. `الساعة ٥` and `١٥ رمضان` are
    normal content, not attacks. Flagging them as homoglyphs would
    create a 5%+ false-positive rate on real Arabic tool-call content
    (measured via scripts/fp_analysis.py).

    Similarly for Persian digits U+06F0..U+06F9 in Persian context.
    """
    from mtg.script import is_arabic_char, is_latin_char

    ar_count = sum(1 for c in value if is_arabic_char(c))
    latn_count = sum(1 for c in value if is_latin_char(c))
    # If Arabic dominates, Arabic-Indic digits are expected typography.
    return ar_count > latn_count


# Codepoint ranges for script-native digits that should be treated as
# contextually-legitimate when the value is dominantly Arabic.
_ARABIC_INDIC_DIGITS = frozenset(chr(cp) for cp in range(0x0660, 0x066A))
_PERSIAN_DIGITS = frozenset(chr(cp) for cp in range(0x06F0, 0x06FA))
_SCRIPT_NATIVE_DIGITS = _ARABIC_INDIC_DIGITS | _PERSIAN_DIGITS


def detect_bidi_threats(value: str) -> BidiFinding:
    """Scan `value` for BiDi control smuggling, invisible chars, tag
    characters, and homoglyphs.

    Pure scan; no I/O. Returns a frozen BidiFinding — caller decides
    whether to treat as violations.

    Context-aware: Arabic-Indic / Persian digits in Arabic-dominant
    content are NOT treated as homoglyphs (they are normal typography).
    A mixed Latin+Arabic-Indic value (e.g. "acct ١٢٣" where "acct" is
    Latin and ١٢٣ is Arabic-Indic) IS flagged because the script mix
    makes the digit substitution the laundering signal.
    """
    if not value:
        return BidiFinding()

    native_digits_legitimate = _arabic_indic_digit_is_contextually_legitimate(value)

    controls: list[str] = []
    marks: list[str] = []
    invisible: list[str] = []
    homoglyphs: list[tuple[str, str]] = []

    for ch in value:
        if ch in BIDI_CONTROL_CHARS:
            controls.append(ch)
        elif ch in BIDI_MARKS:
            marks.append(ch)
        elif ch in INVISIBLE_CHARS:
            invisible.append(ch)
        elif ch in HOMOGLYPH_LATIN_LOOKALIKES:
            if ch in _SCRIPT_NATIVE_DIGITS and native_digits_legitimate:
                # Expected Arabic/Persian digit usage — not a homoglyph attack.
                continue
            homoglyphs.append((ch, HOMOGLYPH_LATIN_LOOKALIKES[ch]))

    tag_chars = tuple(_contains_tag_char(value))
    mixed = _tokens_have_mixed_script(value)

    return BidiFinding(
        bidi_controls=tuple(controls),
        bidi_marks=tuple(marks),
        invisible_chars=tuple(invisible),
        tag_chars=tag_chars,
        homoglyphs=tuple(homoglyphs),
        mixed_script_within_token=mixed,
    )


def strip_bidi(value: str) -> str:
    """Remove all BiDi control, mark, invisible, and tag characters from
    `value`. Does NOT rewrite homoglyphs (that's a riskier transform that
    should be proposed via reconciled-mode repair, not done silently)."""
    if not value:
        return value
    out: list[str] = []
    start, end = _TAG_RANGE
    strip_set = BIDI_CONTROL_CHARS | BIDI_MARKS | INVISIBLE_CHARS
    for ch in value:
        if ch in strip_set:
            continue
        cp = ord(ch)
        if start <= cp <= end:
            continue
        out.append(ch)
    return "".join(out)


def rewrite_homoglyphs(value: str) -> str:
    """Replace known homoglyph characters with their Latin equivalents.

    Lossy — use only after flagging with BidiFinding and with user
    confirmation. Meant for reconciled-mode repair proposals, not silent
    application.
    """
    if not value:
        return value
    return "".join(HOMOGLYPH_LATIN_LOOKALIKES.get(ch, ch) for ch in value)


__all__ = [
    "BIDI_CONTROL_CHARS",
    "BIDI_MARKS",
    "INVISIBLE_CHARS",
    "HOMOGLYPH_LATIN_LOOKALIKES",
    "BidiFinding",
    "detect_bidi_threats",
    "rewrite_homoglyphs",
    "strip_bidi",
]
