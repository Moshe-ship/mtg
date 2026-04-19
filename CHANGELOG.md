# Changelog

All notable changes to MTG (Morphological Type Guards).

## 0.1.0 — initial public release

### Added

- **Specification** (`spec/`): taxonomy, violations, resolution modes, receipt schema. `mtg.schema.json` defines the `x-mtg` extension block — slot_type, script, dialect_expected, morphologically_productive, canonicalization, canonical_form_required, mode, post_call_contract.
- **Pipeline** (`mtg.pipeline`): `validate_pre`, `validate_post`, `run`, `apply_canonicalization`. Orchestrates script detection, transliteration probe, dialect classification, morphology analysis (CAMeL Tools when available, surface-only fallback), and violation emission.
- **Backends**: `mtg.script` (pure-Python Unicode detection), `mtg.translit` (Arabizi heuristics), `mtg.dialect` (CAMeL DID if installed, keyword classifier fallback), `mtg.morph` (CAMeL Tools) + `mtg.morph_fallback` (surface-only).
- **Violation codes**: SCRIPT_VIOLATION, TRANSLITERATION_VIOLATION, DIALECT_DRIFT, MORPH_CANONICALIZATION_FAILURE, MORPH_AMBIGUITY, BACKEND_DISAGREEMENT, FREE_TEXT_OVERFLOW, CANONICALIZATION_REQUIRED, SURFACE_CORRUPTION_POST_CALL, DIALECT_FLATTEN, ROOT_DRIFT.
- **Framework adapters** (`mtg.adapters`): `openai`, `anthropic`, `hermes_fc`. Each wraps a tool definition with MTG guards and exposes `validate_call` / `validate_response`.
- **Receipts** (`mtg.receipts`): hash-chained NDJSON, `build_receipt`, `append_to_chain`, `verify_chain`, `read_chain`. ToolProof-compatible via `toolproof.mtg_bridge`.
- **Evaluation harness** (`mtg.eval`): public API for running MTG on arabic-agent-eval-style JSONL datasets. Exports `run_on_jsonl`, `ItemReport`, `AggregateReport`, four experimental `Condition` arms (A/B/C/D).
- **Schema accessors** (public, top-level): `mtg.get_schema()`, `mtg.load_schema()`, `mtg.validate_x_mtg()`, `mtg.validate_x_mtg_strict()`, `mtg.MTGSchemaError`.
- **CLI** (`mtg`): `check-schema`, `validate`, `receipt-verify`.
- **Cross-repo integration CI**: `scripts/cross_repo_smoke.sh` + `.github/workflows/cross-repo-smoke.yml`. Installs mtg + toolproof + hurmoz into a fresh venv and runs the full guard_tool → receipt_from_mtg_run path against the Hurmoz dialect-specialized send_message variants.
- **Datasets** (`datasets/mtg_slots_v1.jsonl`): 10 cross-dialect examples for regression and evaluation.

### Design notes

- **Advisory only.** `reconciled` and `enforced` modes are defined in the spec but raise `NotImplementedError` in v0.1.0 — data first, policy later.
- **Agent-framework-agnostic.** Three adapters; the primitive is not specific to any one framework.
- **Schema bundled.** `mtg/mtg.schema.json` ships as package data so `pip install` works end-to-end (schema accessors have an `importlib.resources` fallback for zipped wheels).

### Tests

81 tests covering pipeline, adapters, schema validation, receipts, scoring, and cross-dialect regression cases.
