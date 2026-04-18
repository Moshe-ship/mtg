"""Experimental conditions for MTG evaluation.

Four arms are defined, matching spec/resolution.md + the research program:

- A: surface only (baseline — no analysis block)
- B: surface + dialect hint in system prompt (cheap scaffold)
- C: surface + full analysis block in prompt (advisory mode)
- D: surface + analysis + reconciled guards (NOT shipped in v0.1.0)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Condition:
    name: str
    description: str
    include_analysis_in_prompt: bool
    enable_reconciled_mode: bool


ARM_A = Condition(
    name="A",
    description="surface only, no MTG context in prompt",
    include_analysis_in_prompt=False,
    enable_reconciled_mode=False,
)
ARM_B = Condition(
    name="B",
    description="surface + dialect hint in system prompt",
    include_analysis_in_prompt=False,
    enable_reconciled_mode=False,
)
ARM_C = Condition(
    name="C",
    description="surface + full MTG analysis block in prompt (advisory)",
    include_analysis_in_prompt=True,
    enable_reconciled_mode=False,
)
ARM_D = Condition(
    name="D",
    description="surface + analysis + reconciled guards (v0.1.0 not shipped)",
    include_analysis_in_prompt=True,
    enable_reconciled_mode=True,
)


ALL_ARMS = (ARM_A, ARM_B, ARM_C, ARM_D)
