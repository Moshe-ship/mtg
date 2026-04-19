# MTG security layer — false-positive analysis

The BiDi / homoglyph / invisible-char detectors are only useful if
they stay quiet on clean content. This document presents a
reproducible before/after delta.

## Methodology

Run the detector over 178 strings of known-clean multilingual content:

- 10 Persian items from `datasets/persian_v1.jsonl`
- Every Arabic-valued argument and instruction across the five
  dialect splits in `arabic-agent-eval`

Every hit is a false positive by construction — the corpora are real
tool-call content, not attack fixtures.

The analysis is reproducible with two flags:

```bash
# Current (context-aware): post-fix state
python scripts/fp_analysis.py --out docs/fp_report.md

# Legacy: reproduces pre-fix behavior for before/after comparison
python scripts/fp_analysis.py --legacy --out docs/fp_report_prefix.md
```

## Result

| Version | BIDI | INVISIBLE | SCRIPT_HOMOGLYPH | mixed-script |
|---|---:|---:|---:|---:|
| Pre-fix (legacy) | 0.0% (0 / 178) | 0.0% (0 / 178) | **5.1% (9 / 178)** | 0.0% (0 / 178) |
| Post-fix (current) | 0.0% (0 / 178) | 0.0% (0 / 178) | **0.0% (0 / 178)** | 0.0% (0 / 178) |
| Delta | — | — | −5.1 pp | — |

Full per-corpus breakdown:

- [docs/fp_report.md](fp_report.md) — current state
- [docs/fp_report_prefix.md](fp_report_prefix.md) — pre-fix baseline

## What the fix did

The pre-fix detector flagged Arabic-Indic digits (U+0660..U+0669) and
Persian digits (U+06F0..U+06F9) as homoglyphs in every context. In
Arabic-dominant text those digits are **native typography** — the
normal way to write numbers in an Arabic string. `الساعة ٥` and
`١٥ رمضان` both flagged, even though they are standard Arabic content.

The fix is context-aware: native digits are only flagged when the
surrounding content is predominantly Latin (the laundering signal).
See `mtg/bidi.py:_arabic_indic_digit_is_contextually_legitimate`.

## Attack coverage preserved

Real attack cases still fire:

- BiDi control characters (U+202A..U+202E, U+2066..U+2069) → always
  flagged regardless of surrounding script.
- Arabic-Indic digits in a Latin-declared slot (e.g. a postal_code
  field declared `script: "latn"` receiving `١٢٣٤٥`) → caught via
  `SCRIPT_VIOLATION` because the detected script does not match the
  declared script.
- Homoglyph characters from Cyrillic, Greek, or other scripts → always
  flagged when they appear in a Latin-dominant context.

Tested end-to-end in `hurmoz/demos/demo_saudi_business.py`.
