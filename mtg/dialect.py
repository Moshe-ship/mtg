"""Dialect classifier.

Tries CAMeL Tools `dialectid` if installed. Falls back to a keyword-based
heuristic. The fallback is NOT accurate on long-form text — receipts always
carry `dialect_confidence` so downstream consumers can filter low-confidence.
"""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class DialectBackend(Protocol):
    def classify(self, text: str) -> tuple[str, float]:
        """Return (dialect, confidence). Dialect is one of msa|gulf|egy|lev|maghrebi|unknown."""
        ...


class KeywordDialectClassifier:
    """Fallback dialect classifier using dialect-marker word lists.

    Accuracy is limited (~60-70% on short tool-call inputs) but is deterministic
    and fast. The marker lists are minimal-viable; extension via PR is welcome.
    """

    _MARKERS: dict[str, frozenset[str]] = {
        "gulf": frozenset({
            "ابي", "ابغى", "ابغا", "وش", "شلون", "الحين", "هالكثر",
            "يبي", "يبغى", "بكرا", "اليوم", "توني", "طاري",
        }),
        "egy": frozenset({
            "عايز", "عاوز", "عايزة", "إزاي", "ازاي", "إيه", "ايه",
            "بتاع", "بتاعي", "دلوقتي", "دول", "دي", "كده",
            "الواد", "مش", "بكره", "دي",
        }),
        "lev": frozenset({
            "بدي", "بدو", "بدها", "هلأ", "هلا", "قديش", "شو",
            "هون", "هنيك", "كتير", "منيح", "هيك", "زلمة",
            "بحكي", "لسه", "هلق", "بحب",
        }),
        "maghrebi": frozenset({
            "بغيت", "بغات", "كيفاش", "واش", "شحال", "حنا", "فاش",
            "مزيان", "بزاف", "دابا", "دير", "راه", "زعما",
            "كاين", "خوك", "نتوما", "لاباس",
        }),
    }

    backend_name = "keyword-fallback"

    def classify(self, text: str) -> tuple[str, float]:
        if not text or not text.strip():
            return "unknown", 0.0

        from mtg.canonical import normalize

        tokens = [t.strip() for t in text.split() if t.strip()]
        if not tokens:
            return "unknown", 0.0

        hits: dict[str, int] = {d: 0 for d in self._MARKERS}
        for token in tokens:
            normalized = normalize(token.strip("،.؟!?.,").strip())
            for dialect, markers in self._MARKERS.items():
                normalized_markers = {normalize(m) for m in markers}
                if normalized in normalized_markers:
                    hits[dialect] += 1

        total_hits = sum(hits.values())
        if total_hits == 0:
            # No dialect markers: default to MSA with low confidence
            return "msa", 0.45

        best = max(hits, key=lambda d: hits[d])
        dominance = hits[best] / total_hits
        density = total_hits / len(tokens)
        # Confidence combines within-dialect dominance and marker density
        confidence = min(0.95, 0.55 + 0.35 * dominance + 0.25 * density)
        return best, round(confidence, 3)


class CamelDialectClassifier:
    """CAMeL Tools dialect identification backend.

    Optional — instantiation returns None if camel_tools is not importable.
    """

    backend_name = "camel-tools-did"

    def __init__(self) -> None:
        try:
            from camel_tools.dialectid import DialectIdentifier  # type: ignore

            self._did = DialectIdentifier.pretrained()
        except Exception as exc:  # pragma: no cover
            log.debug("CAMeL DID unavailable: %s", exc)
            raise

    def classify(self, text: str) -> tuple[str, float]:  # pragma: no cover
        result = self._did.predict([text])
        if not result:
            return "unknown", 0.0
        top = result[0]
        raw_label = getattr(top, "top", "MSA").lower()
        mapping = {
            "msa": "msa",
            "glf": "gulf", "sau": "gulf", "ksa": "gulf", "uae": "gulf", "kwt": "gulf",
            "egy": "egy", "cai": "egy",
            "lev": "lev", "syr": "lev", "jor": "lev", "pal": "lev", "leb": "lev",
            "mag": "maghrebi", "mar": "maghrebi", "dza": "maghrebi", "tun": "maghrebi",
        }
        dialect = mapping.get(raw_label, "unknown")
        score = float(getattr(top, "score", 0.5))
        return dialect, score


def get_dialect_backend() -> DialectBackend:
    """Return best available backend.

    Prefers CAMeL Tools; falls back to keyword classifier.
    """
    try:
        return CamelDialectClassifier()  # pragma: no cover
    except Exception:
        return KeywordDialectClassifier()
