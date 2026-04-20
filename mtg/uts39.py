"""UTS #39 Unicode Security Mechanisms — subset.

Slot-gated confusable detection and restriction-level classification.
The goal: catch identifier-spoofing attacks (Cyrillic 'а' in a
"paypal.com" domain, Arabic-Indic digits in a numeric code) WITHOUT
false-positiving natural Arabic/Persian prose, which is the reason
free_text / named_entity slots stay exempt by policy.

What this module is:
- A partial, pragmatic implementation of UTS #39 §4 (confusable
  skeleton) and §5.2 (restriction levels).
- A slot-type gate: by default, only `identifier` and `numeric` slots
  are subject to UTS #39 checks. Free-text slots are exempt.

What this module is NOT:
- A full Unicode confusables.txt mapping. The ~10k-entry UTS #39
  confusables table is not vendored; instead we carry a curated subset
  targeting the script-laundering attacks we've actually seen at the
  tool-argument layer (Cyrillic→Latin, Greek→Latin, Arabic-Indic→ASCII
  digits, fullwidth→ASCII).
- A script classifier that covers every Unicode script. Script ranges
  are limited to the scripts we see in our benchmark corpus
  (Latin / Arabic / Hebrew / Cyrillic / Greek / CJK / Devanagari /
  digits). Codepoints outside these ranges classify as "Other".
- A replacement for `mtg.bidi`. The BiDi module catches char-level
  security threats (CVE-2021-42574 BiDi controls, invisible padding,
  TAG chars); this module classifies restriction level and returns a
  confusable skeleton for identifier equality checks.

Wire-up: `pipeline._pre_call_violations` can gate on `applies_to(
spec.slot_type)` and emit `UTS39_RESTRICTION_VIOLATION` when
`Uts39Finding.is_suspicious()` on a guarded value. Gate stays tight by
default so natural multilingual text never triggers.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any


# Slot types subject to UTS #39 checks. Intentionally tight: identifiers
# and numeric slots are where script-mixing spoofs bite. Free-text and
# named-entity slots routinely carry natural multilingual content and
# must stay exempt.
_UTS39_APPLICABLE_SLOTS: frozenset[str] = frozenset({
    "identifier",
    "numeric",
})


# Script range table. Covers the scripts seen in our Arabic/Persian
# benchmark + common laundering sources (Cyrillic/Greek). Returns the
# canonical UTS #39 script name. Digit scripts are mapped back to their
# parent script (Arabic digits → "Arabic"), mirroring the UTS #39
# Script property.
_SCRIPT_RANGES: list[tuple[int, int, str]] = [
    # Basic Latin letters
    (0x0041, 0x005A, "Latin"),
    (0x0061, 0x007A, "Latin"),
    (0x00C0, 0x024F, "Latin"),
    (0x1E00, 0x1EFF, "Latin"),
    # Greek
    (0x0370, 0x03FF, "Greek"),
    (0x1F00, 0x1FFF, "Greek"),
    # Cyrillic
    (0x0400, 0x04FF, "Cyrillic"),
    (0x0500, 0x052F, "Cyrillic"),
    # Hebrew
    (0x0590, 0x05FF, "Hebrew"),
    # Arabic script (incl. Persian/Urdu extensions + presentation forms)
    (0x0600, 0x06FF, "Arabic"),
    (0x0750, 0x077F, "Arabic"),
    (0x08A0, 0x08FF, "Arabic"),
    (0xFB50, 0xFDFF, "Arabic"),
    (0xFE70, 0xFEFF, "Arabic"),
    # Devanagari
    (0x0900, 0x097F, "Devanagari"),
    # CJK Unified Ideographs (subset)
    (0x4E00, 0x9FFF, "Han"),
    # Hiragana / Katakana
    (0x3040, 0x309F, "Hiragana"),
    (0x30A0, 0x30FF, "Katakana"),
    # Hangul
    (0xAC00, 0xD7A3, "Hangul"),
    (0x1100, 0x11FF, "Hangul"),
    # Thai
    (0x0E00, 0x0E7F, "Thai"),
]

# UTS #39 treats the digit blocks as belonging to their script — e.g.
# Arabic-Indic digits are script "Arabic", Devanagari digits are script
# "Devanagari". The range table above already covers them.

# Codepoints that UTS #39 classifies as "Common" or "Inherited" — they
# don't count toward script-mixing. ASCII digits and punctuation live
# here.
def _is_common(ch: str) -> bool:
    cp = ord(ch)
    if cp < 0x0080:  # ASCII: digits + punctuation + basic latin space
        # But ASCII letters are Latin, not Common.
        if 0x0041 <= cp <= 0x005A or 0x0061 <= cp <= 0x007A:
            return False
        return True
    # Whitespace, punctuation, control, symbols (broad sweep)
    cat = unicodedata.category(ch)
    if cat[0] in ("P", "S", "Z", "C", "M"):
        return True
    # Common digit-like block (fullwidth digits, etc.) — defer to the
    # range table instead; leave False here.
    return False


def _script_of(ch: str) -> str:
    """Return the UTS #39-style script name for `ch`.

    "Common" / "Inherited" for punctuation, digits-are-their-script
    per UTS #39 §5.1 convention. Anything outside the known ranges
    classifies as "Other" — callers treat Other as an automatic
    restriction-level downgrade.
    """
    if _is_common(ch):
        return "Common"
    cp = ord(ch)
    for start, end, name in _SCRIPT_RANGES:
        if start <= cp <= end:
            return name
    return "Other"


# Curated confusable map. NOT the full UTS #39 confusables.txt (10k+
# entries). Covers the highest-value spoof pairs: Cyrillic letters that
# render identically to Latin, Greek letters that render as Latin,
# Arabic-Indic digits that render as ASCII digits, fullwidth ASCII.
# Each key maps to its "skeleton" prototype (the canonical
# same-appearance codepoint).
_CONFUSABLE_PROTOTYPES: dict[str, str] = {
    # Cyrillic → Latin
    "а": "a", "в": "B", "е": "e", "к": "k", "м": "M", "н": "H",
    "о": "o", "р": "p", "с": "c", "т": "T", "у": "y", "х": "x",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "і": "i", "І": "I", "ѕ": "s", "Ѕ": "S", "ј": "j", "Ј": "J",
    # Greek → Latin
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I",
    "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
    "Υ": "Y", "Χ": "X",
    "ο": "o", "ν": "v", "ι": "i", "κ": "k", "ρ": "p", "τ": "t",
    # Arabic-Indic digits → ASCII digits
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    # Extended Arabic-Indic (Persian) digits → ASCII digits
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    # Fullwidth ASCII → ASCII (common in phishing)
    **{chr(0xFF10 + i): str(i) for i in range(10)},
    **{chr(0xFF21 + i): chr(0x41 + i) for i in range(26)},
    **{chr(0xFF41 + i): chr(0x61 + i) for i in range(26)},
}


def skeleton(value: str) -> str:
    """UTS #39 §4 confusable skeleton (subset).

    Two strings have the same skeleton → they render as visually
    identical / highly similar even though their codepoints differ.
    Used to compare an input against a trusted-identifier list.

    This is NOT UTS #39's complete skeleton transformation (which
    requires the full confusables.txt data). It handles the curated
    map above plus NFKC normalization.
    """
    if not value:
        return ""
    # Apply the curated prototype map first, then NFKC-normalize the
    # result. NFKC collapses compatibility variants (fullwidth, ligature
    # forms) onto their canonical codepoints, which is a superset of
    # the UTS #39 prototype step for that particular family.
    swapped = "".join(_CONFUSABLE_PROTOTYPES.get(ch, ch) for ch in value)
    return unicodedata.normalize("NFKC", swapped)


def confusable_codepoints(value: str) -> tuple[str, ...]:
    """Return the subset of `value`'s codepoints that map to a
    confusable prototype — i.e. the suspicious characters."""
    return tuple(ch for ch in value if ch in _CONFUSABLE_PROTOTYPES)


def scripts_in(value: str) -> tuple[str, ...]:
    """Ordered-unique list of scripts present (excluding Common)."""
    seen: dict[str, None] = {}
    for ch in value:
        s = _script_of(ch)
        if s == "Common":
            continue
        if s not in seen:
            seen[s] = None
    return tuple(seen.keys())


# UTS #39 §5.2 restriction levels (paraphrased):
#
#   ascii_only              — Only ASCII letters (plus Common).
#   single_script           — Exactly one non-Common script.
#   highly_restrictive      — Latin + (Han+Hiragana+Katakana |
#                             Han+Bopomofo | Han+Hangul). I.e. the
#                             CJK-mixing pattern.
#   moderately_restrictive  — Latin + at most one non-Latin script.
#                             This is where most Latin/Cyrillic spoofs
#                             live — note it's still "allowed" by the
#                             level, so callers flag by rule, not level.
#   minimally_restrictive   — Any combination of scripts, but at least
#                             one non-Common script is present.
#   unrestricted            — No constraint. Default for free text.


def classify_restriction_level(value: str) -> str:
    """Return the UTS #39 restriction level name for `value`."""
    if not value:
        return "ascii_only"

    scripts = scripts_in(value)
    if not scripts:
        return "ascii_only"

    # "Other" script present = unknown script = unrestricted
    if "Other" in scripts:
        return "unrestricted"

    # ASCII-only: all chars are ASCII and only Latin appears
    if scripts == ("Latin",) and all(ord(c) < 0x80 for c in value):
        return "ascii_only"

    if len(scripts) == 1:
        return "single_script"

    # Highly restrictive: Latin + {Han+Hiragana, Han+Katakana,
    # Han+Hiragana+Katakana, Han+Hangul}
    script_set = set(scripts)
    highly_restrictive_combos = [
        {"Latin", "Han", "Hiragana"},
        {"Latin", "Han", "Katakana"},
        {"Latin", "Han", "Hiragana", "Katakana"},
        {"Latin", "Han", "Hangul"},
    ]
    for combo in highly_restrictive_combos:
        if script_set == combo:
            return "highly_restrictive"

    # Moderately restrictive: Latin + exactly one non-Latin
    if "Latin" in script_set and len(script_set) == 2:
        return "moderately_restrictive"

    # Otherwise: multiple non-Latin scripts, or Latin + >1 non-Latin
    return "minimally_restrictive"


@dataclass(frozen=True)
class Uts39Finding:
    """UTS #39 analysis of one value."""

    restriction_level: str
    scripts: tuple[str, ...]
    confusable_codepoints: tuple[str, ...]
    skeleton: str

    def is_suspicious(self) -> bool:
        """Does this finding warrant raising a violation?

        Heuristic: any confusable codepoint, OR a restriction level
        worse than `single_script` (i.e. moderately/minimally
        restrictive, or unrestricted). `ascii_only`, `single_script`,
        and `highly_restrictive` are treated as benign.
        """
        if self.confusable_codepoints:
            return True
        return self.restriction_level in {
            "moderately_restrictive",
            "minimally_restrictive",
            "unrestricted",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "restriction_level": self.restriction_level,
            "scripts": list(self.scripts),
            "confusable_codepoints": [
                {"char": c, "codepoint": hex(ord(c)), "prototype": _CONFUSABLE_PROTOTYPES[c]}
                for c in self.confusable_codepoints
            ],
            "skeleton": self.skeleton,
        }


def analyze(value: str) -> Uts39Finding:
    """Run the full UTS #39 analysis on `value`."""
    return Uts39Finding(
        restriction_level=classify_restriction_level(value),
        scripts=scripts_in(value),
        confusable_codepoints=confusable_codepoints(value),
        skeleton=skeleton(value),
    )


def applies_to(slot_type: str) -> bool:
    """Policy gate: UTS #39 checks apply only to identifier-like
    slots. Free-text / named-entity / factorable-Arabic slots are
    exempt by design — natural multilingual text can't be held to an
    identifier restriction level without unacceptable false positives.
    """
    return slot_type in _UTS39_APPLICABLE_SLOTS


__all__ = [
    "Uts39Finding",
    "analyze",
    "applies_to",
    "classify_restriction_level",
    "confusable_codepoints",
    "scripts_in",
    "skeleton",
]
