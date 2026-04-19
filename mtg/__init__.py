"""MTG — Morphological Type Guards for multilingual tool-call arguments.

Public API:

    # Core pipeline
    from mtg import (
        GuardSpec, Analysis, Violation, GuardResult, Receipt,
        validate_pre, validate_post, run,
        build_receipt, append_to_chain, verify_chain,
    )

    # Framework adapters
    from mtg.adapters.openai import guard_tool              # OpenAI
    from mtg.adapters.anthropic import guard_tool           # Anthropic
    from mtg.adapters.hermes_fc import guard_tool           # Hermes-FC

    # Evaluation harness (public — for running MTG against
    # arabic-agent-eval style JSONL datasets)
    from mtg.eval import (
        Condition, ALL_ARMS, ARM_A, ARM_B, ARM_C, ARM_D,
        ItemReport, AggregateReport, run_on_jsonl,
    )

See README.md and spec/ for details.
"""

from __future__ import annotations

__version__ = "0.1.0"

from mtg.types import (
    Analysis,
    GuardResult,
    GuardSpec,
    Receipt,
    Violation,
    FACTORABLE_SLOTS,
    NON_FACTORABLE_SLOTS,
    SEVERITY_TO_OUTCOME,
)
from mtg.pipeline import (
    apply_canonicalization,
    run,
    validate_post,
    validate_pre,
)
from mtg.receipts import (
    CHAIN_DEFAULT_PATH,
    append_to_chain,
    build_receipt,
    read_chain,
    verify_chain,
)
from mtg.schema_validator import (
    MTGSchemaError,
    load_schema,
    validate_x_mtg,
    validate_x_mtg_strict,
)
from mtg.repair import (
    RepairSuggestion,
    arabizi_to_arabic_naive,
    pick_repaired_value,
    score_repair,
    suggest_repairs,
)


def get_schema() -> dict:
    """Return the bundled x-mtg JSON Schema as a dict.

    Convenience alias for `mtg.schema_validator.load_schema`. Stable public
    API — downstream consumers can call this instead of touching internal
    file paths or the `spec/` directory.
    """
    return load_schema()


__all__ = [
    "__version__",
    "Analysis",
    "GuardResult",
    "GuardSpec",
    "Receipt",
    "Violation",
    "FACTORABLE_SLOTS",
    "NON_FACTORABLE_SLOTS",
    "SEVERITY_TO_OUTCOME",
    "apply_canonicalization",
    "run",
    "validate_post",
    "validate_pre",
    "CHAIN_DEFAULT_PATH",
    "append_to_chain",
    "build_receipt",
    "read_chain",
    "verify_chain",
    # Schema accessors (public)
    "MTGSchemaError",
    "get_schema",
    "load_schema",
    "validate_x_mtg",
    "validate_x_mtg_strict",
    # Reconciled-mode repair primitives (public)
    "RepairSuggestion",
    "arabizi_to_arabic_naive",
    "pick_repaired_value",
    "score_repair",
    "suggest_repairs",
]
