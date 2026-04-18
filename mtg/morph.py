"""Morphological analysis backend wrapper.

Uses CAMeL Tools when available; emits fallback Analysis otherwise.
"""

from __future__ import annotations

import logging
from typing import Protocol

from mtg.types import Analysis

log = logging.getLogger(__name__)


class MorphBackend(Protocol):
    backend_name: str

    def analyze(self, text: str) -> list[Analysis]:
        """Return candidate analyses. Empty list means nothing produced."""
        ...


class CamelMorphBackend:
    """CAMeL Tools Calima-Star morphological analyzer."""

    backend_name = "camel-tools"

    def __init__(self) -> None:
        try:
            from camel_tools.morphology.database import MorphologyDB  # type: ignore
            from camel_tools.morphology.analyzer import Analyzer  # type: ignore
            self._db = MorphologyDB.builtin_db()
            self._analyzer = Analyzer(self._db)
        except Exception as exc:  # pragma: no cover
            log.debug("CAMeL morphology unavailable: %s", exc)
            raise

    def analyze(self, text: str) -> list[Analysis]:  # pragma: no cover
        tokens = text.split()
        if not tokens:
            return []
        out: list[Analysis] = []
        for tok in tokens:
            candidates = self._analyzer.analyze(tok)
            if not candidates:
                continue
            top = candidates[0]
            out.append(
                Analysis(
                    script_detected="ar",
                    root=top.get("root"),
                    pattern=top.get("pattern"),
                    lemma=top.get("lex"),
                    morph_confidence=float(top.get("pos_logprob", 0.5)),
                    backend=self.backend_name,
                    backend_available=True,
                )
            )
        return out


def get_morph_backend() -> MorphBackend:
    """Return the best available morph backend."""
    try:
        return CamelMorphBackend()  # pragma: no cover
    except Exception:
        from mtg.morph_fallback import SurfaceOnlyMorphBackend

        return SurfaceOnlyMorphBackend()
