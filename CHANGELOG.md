# Changelog

All notable changes to MTG (Morphological Type Guards).

## Unreleased — BiDi security layer + Persian pilot + reliability runtime

### Added (security layer)

- **`mtg.bidi`** — detection and repair primitives for agent-argument security:
  - `BIDI_CONTROL_SMUGGLING` · high — Unicode directional control chars (U+202A..U+202E, U+2066..U+2069) and invisible TAG chars (U+E0020..U+E007F). Covers the CVE-2021-42574 ("Trojan Source") attack class at the tool-argument level.
  - `INVISIBLE_CONTENT` · medium — zero-width chars (U+200B ZWSP, U+2060 WJ, U+FEFF BOM, U+00AD SHY, U+034F CGJ). ZWNJ/ZWJ deliberately excluded — they are legitimate in Persian, Urdu, Hindi, Thai, emoji.
  - `SCRIPT_HOMOGLYPH` · medium — Cyrillic/Greek/Arabic-Indic-digit lookalikes, and single-token cross-script mixing.
  - `detect_bidi_threats`, `strip_bidi`, `rewrite_homoglyphs` public primitives.
- Security checks run on every guarded value regardless of declared `script` — these are security issues, not linguistic preferences.

### Added (Persian pilot)

- `datasets/persian_v1.jsonl` — 10 Persian/Farsi items.
- `examples/book_flight_persian.json` — Persian tool schema (script=fa on all Persian slots).
- `matches_required_script("fa")` now accepts detected `ar` as a valid subset — Persian uses the Arabic script as a strict superset, so a Persian value without پ/چ/ژ/گ is legitimately indistinguishable at the script layer (by design; dialect/morphology is the right layer for finer-grained Persian/Arabic separation).

### Design notes

- The Persian pilot proves the MTG primitive travels beyond Arabic without language-specific code. Same pipeline, same adapter, same receipt shape — only the `script` and dataset change.

## Unreleased (earlier) — reliability runtime (reconciled mode + report CLI)

### Added

- **Reconciled mode** (`mode: "reconciled"` no longer raises). Runs the same detection as advisory, then emits `RepairSuggestion` records for the subset of violations that can be repaired deterministically: Arabizi → Arabic (naive reverse transliteration), canonical-form attach (always-safe normalized fallback when `canonical_form_required=true` and the backend is unavailable). Dialect drift is advisory-only (`proposed=None`) because rewriting across dialects requires a generative model; free-text overflow emits a schema-review suggestion, not a value fix. Repairs are never applied silently — each carries `needs_review` and `rationale`.
- **`mtg.repair`** module — `RepairSuggestion`, `arabizi_to_arabic_naive`, `suggest_repairs`, `pick_repaired_value`. All exported at top level as `mtg.RepairSuggestion`, `mtg.arabizi_to_arabic_naive`, etc.
- **`GuardResult.repairs`** and **`GuardResult.repaired_surface`** — populated in reconciled mode, serialized via `to_dict()`.
- **`mtg report` CLI** — aggregates an NDJSON receipt chain (mtg-native or ToolProof) into a scorecard. Supports `--html` (self-contained single-file HTML with bar charts and per-tool fail-rate table) and `--json`. Aggregates outcomes, violation histogram with severity, dialect-drift pairs (`expected→observed` counts), repair action counts, and per-tool hot spots sorted by fail-rate.
- **`mtg.report`** module — `Scorecard`, `ScorecardRow`, `aggregate`, `load_ndjson`, `render_html`. Accepts both flat-`mtg_violations` (ToolProof) and nested-`guards[param].pre_call_violations` (mtg-native) shapes.
- **Wheel/sdist CI check** — cross-repo-smoke.yml gains a `build-artifacts` job that `python -m build`s mtg + toolproof and installs from `dist/*.whl` and `dist/*.tar.gz` into fresh venvs before running the end-to-end smoke. Catches packaging bugs (missing package data, manifest drift) that editable installs mask.
- **Router example integration in CI** — `scripts/cross_repo_smoke.sh` now runs `hurmoz/examples/dialect_router.py` after the smoke tests and invokes `mtg report` on the resulting chain.

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
