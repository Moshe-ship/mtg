# Violation taxonomy

All violations are phase-tagged (`pre` or `post`) and severity-tagged (`high`, `medium`, `low`, `info`). In `advisory` mode (the only mode v0.1.0 ships), violations are logged to the receipt but do not alter call flow.

## Pre-call violations

### `SCRIPT_VIOLATION` · high

The value's detected Unicode script does not match the declared `script`.

| Declared | Actual | Violation |
|---|---|---|
| `ar` | `"Hello world"` | SCRIPT_VIOLATION |
| `latn` | `"مرحبا"` | SCRIPT_VIOLATION |
| `ar` | `"Hello مرحبا"` | SCRIPT_VIOLATION (unless `mixed` declared) |
| `any` | anything | — |

### `TRANSLITERATION_VIOLATION` · high

The value is Romanized Arabic (Arabizi) but `transliteration_allowed: false` is declared. Heuristics detect digit-letter substitutions (3, 7, 9 standing in for Arabic letters) and dominant Arabic-language content written in Latin script.

Examples flagged: `abi a7jez`, `marhaba 3aleykum`, `el reyad`.

### `DIALECT_DRIFT` · medium

Detected dialect differs from `dialect_expected`, and `dialect_enforcement` is `strict` or `preserve`.

| Expected | Detected | Enforcement | Violation |
|---|---|---|---|
| `gulf` | `gulf` | any | — |
| `gulf` | `egy` | `preserve` | DIALECT_DRIFT |
| `gulf` | `egy` | `advisory` | logged as `info` only |
| `any` | anything | any | — |

Every receipt carries `dialect_confidence`. If confidence is below 0.75, dialect guards revert to advisory regardless of declared enforcement.

### `MORPH_CANONICALIZATION_FAILURE` · low

Morphological analysis could not produce a canonical form for a span that declared `morphologically_productive: true`. Common cause: backend unavailable, or a named-entity value in a factorable slot.

Falls back to surface-only canonicalization.

### `MORPH_AMBIGUITY` · low

Multiple analyses tied within 0.15 confidence of each other. Pipeline cannot pick a winner; emits ambiguity info and falls back to surface-only. Downstream consumers should treat the `analysis.root` field as non-authoritative when this flag is present.

### `BACKEND_DISAGREEMENT` · info

When an ensemble of morphological backends is active (CAMeL Tools + Farasa, for example), this annotation records disagreement rate. Not a failure — a transparency signal.

### `FREE_TEXT_OVERFLOW` · medium

A parameter declared a factorable `slot_type` but the actual value is dominantly non-factorable (named entities, numerics). See [taxonomy.md](taxonomy.md#free_text_overflow).

### `CANONICALIZATION_REQUIRED` · high

The schema author declared `canonical_form_required: true` with `canonicalization: lemma` or `canonicalization: root_pattern`, but the pipeline could not produce a canonical form — typically because the morphology backend is unavailable, or because `FREE_TEXT_OVERFLOW` downgraded the morphological analysis for this call.

`canonical_form_required` is a **derivability** requirement on the validator, not a wire-format requirement on the call payload — the caller still sends only the surface value; the pipeline is responsible for computing the canonical form.

## Post-call violations

Post-call guards compare the tool response against the input value to detect corruption or invariant breaks. Runs only for parameters with `post_call_contract` entries.

### `SURFACE_CORRUPTION_POST_CALL` · high

The response's echoed value differs from the input value by more than a small-edit tolerance, even after Arabic normalization.

Tolerance: edit distance ≤ `max(2, 0.05 * len(input))` on the normalized form.

### `DIALECT_FLATTEN` · medium

Input was dialect-marked; response echoes the parameter in MSA. Applies when `post_call_contract` includes `dialect_preserve`.

### `ROOT_DRIFT` · medium

Input and response share surface but the morphological root changed across the call. Indicates upstream semantic mutation. Requires `morphologically_productive: true` and `post_call_contract: ["root_preserve"]`.

## Severity → outcome mapping (for ToolProof bridge)

| Severity | ToolProof outcome |
|---|---|
| `high` | `fail` |
| `medium` | `partial` |
| `low`, `info` | `pass` (logged) |

The bridge lives in `toolproof.mtg_bridge.from_mtg_violation` — see ToolProof 0.5.
