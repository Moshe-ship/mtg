# mtg — Morphological Type Guards

**A JSON Schema extension for multilingual tool-call arguments.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Status: v0.1.0 advisory](https://img.shields.io/badge/status-v0.1.0%20advisory-orange.svg)](#status)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)

> Tool-call parameters today are typed as `string`. Too weak for multilingual agents. MTG adds linguistic constraints on the span, validates pre-call and post-call, and emits structured violation receipts.

## Why

Run a Gulf Arabic instruction through a frontier model and watch half the tool arguments come back transliterated — `الرياض` becomes `Riyadh`, `أبي أحجز` collapses to MSA. There is no type today that says *"this parameter must stay in Arabic, in Gulf register, with preserved morphology."* MTG is that type.

MTG is **agent-framework-agnostic**. Hermes is one adapter among several (OpenAI, Anthropic, Hermes-Function-Calling). The primitive generalizes to any morphologically rich language — Hebrew, Amharic, Tigrinya, Turkish, Persian.

## Status

**v0.1.0 — advisory mode only.** Violations are logged; calls are never blocked. `reconciled` and `enforced` modes are defined in the spec but not enabled in the reference implementation. Data first, policy later.

## Install

```bash
# From source (not yet on PyPI)
git clone https://github.com/Moshe-ship/mtg.git
cd mtg
pip install -e .

# With optional CAMeL Tools morphology backend
pip install -e ".[morph]"
```

## Quickstart

```python
import json
from mtg.adapters.openai import guard_tool

tool = json.load(open("examples/book_service.json"))
wrapped = guard_tool(tool)

# Validate an inbound call
result = wrapped.validate_call({
    "name": "book_service",
    "arguments": {
        "intent_phrase": "أبي أحجز",      # Gulf Arabic
        "service_id": "svc-42",
    },
})
for violation in result.violations:
    print(violation.code, violation.severity, violation.message)
```

## Architecture

```
Tool definition (JSON Schema + x-mtg extension)
         │
         ▼
    Adapter  (openai / anthropic / hermes_fc)
         │
         ▼
    Pipeline  (pre-call + post-call)
         │
         ├─▶ Script backend      (Unicode range checks, pure-Python)
         ├─▶ Translit backend    (Arabizi heuristics)
         ├─▶ Dialect backend     (CAMeL DID if available; keyword fallback)
         ├─▶ Morph backend       (CAMeL Tools if available; fallback otherwise)
         └─▶ Canonical transforms (lemma / root+pattern / normalized)
         │
         ▼
    Receipt  (hash-chained, ToolProof-compatible)
```

## The `x-mtg` extension

Any JSON Schema `string` property can carry an `x-mtg` block:

```json
{
  "type": "string",
  "x-mtg": {
    "slot_type": "inflected_request_form",
    "script": "ar",
    "dialect_expected": "gulf",
    "dialect_enforcement": "preserve",
    "transliteration_allowed": false,
    "morphologically_productive": true,
    "canonicalization": "root_pattern",
    "mode": "advisory",
    "post_call_contract": ["script_match", "dialect_preserve"]
  }
}
```

Full spec: [spec/taxonomy.md](spec/taxonomy.md) · [spec/violations.md](spec/violations.md) · [spec/resolution.md](spec/resolution.md) · [spec/mtg.schema.json](spec/mtg.schema.json)

## Violation taxonomy

| Code | Phase | Severity |
|---|---|---|
| `SCRIPT_VIOLATION` | pre | high |
| `TRANSLITERATION_VIOLATION` | pre | high |
| `DIALECT_DRIFT` | pre | medium |
| `DIALECT_FLATTEN` | post | medium |
| `MORPH_CANONICALIZATION_FAILURE` | pre | low |
| `MORPH_AMBIGUITY` | pre | low |
| `BACKEND_DISAGREEMENT` | pre | info |
| `SURFACE_CORRUPTION_POST_CALL` | post | high |
| `ROOT_DRIFT` | post | medium |
| `FREE_TEXT_OVERFLOW` | pre | medium |
| `CANONICALIZATION_REQUIRED` | pre | high |

## CLI

```bash
# Validate a tool's x-mtg annotations
mtg check-schema examples/book_service.json

# Validate an inbound call against a tool
mtg validate examples/book_service.json examples/sample_call.json

# Verify a receipt chain
mtg receipt-verify ~/.mtg/chain.ndjson
```

## Limitations (v0.1.0)

- **Advisory only.** No enforcement. Don't use MTG as a security control — use it as a diagnostic.
- **CAMeL Tools is optional.** Without it, morphological analysis falls back to surface-only with `BACKEND_DISAGREEMENT` info annotations. Install `mtg-guards[morph]` for full analysis.
- **Dialect classifier is keyword-based** by default. Accuracy on short tool-call inputs is limited; receipts always include `dialect_confidence` so downstream consumers can filter low-confidence cases (`<0.75`).
- **Arabic-first.** Other languages are supported in the schema (`script: "he"`, `"fa"`, etc.) but the reference validator is tuned for Arabic. Other-language backends are welcome PRs.
- **Not fine-tuned.** MTG v0.1.0 is a prompt-time instrument. It does not modify models or training data.

## Related projects

- [arabic-agent-eval](https://github.com/Moshe-ship/arabic-agent-eval) — 51-item Arabic function-calling benchmark with dialect splits. The primary diagnostic substrate for MTG.
- [ToolProof](https://github.com/Moshe-ship/toolproof) — agent tool-call verification. MTG violations convert to ToolProof receipts via `toolproof.mtg_bridge.from_mtg_violation`.
- [artok](https://github.com/Moshe-ship/artok) — Arabic token cost calculator across 18 tokenizers. Provides the future-work basis for MTG compression claims.
- [NousResearch/Hermes-Function-Calling](https://github.com/NousResearch/Hermes-Function-Calling) — target adapter landing spot upstream.
- [NousResearch/atropos](https://github.com/NousResearch/atropos) — community environment for MTG-guarded RL rollouts.

## Citation

```bibtex
@software{mtg_2026,
  title = {Morphological Type Guards: A JSON Schema extension for multilingual tool-call arguments},
  author = {Abumazin, Mousa},
  year = {2026},
  url = {https://github.com/Moshe-ship/mtg}
}
```

## License

Apache-2.0. See [LICENSE](LICENSE).
