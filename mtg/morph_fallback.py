"""Surface-only morphology fallback when CAMeL Tools is unavailable.

Emits an Analysis with backend_available=False so downstream consumers
can filter or label receipts accordingly.
"""

from __future__ import annotations

from mtg.types import Analysis


class SurfaceOnlyMorphBackend:
    backend_name = "fallback"

    def analyze(self, text: str) -> list[Analysis]:
        """Return a single empty Analysis that signals unavailable backend.

        This keeps the pipeline consistent — callers still receive an Analysis
        instance with confidence 0.0 and backend_available=False.
        """
        if not text or not text.strip():
            return []
        return [
            Analysis(
                script_detected="any",
                root=None,
                pattern=None,
                lemma=None,
                morph_confidence=0.0,
                backend=self.backend_name,
                backend_available=False,
            )
        ]
