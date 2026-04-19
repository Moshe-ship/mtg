# MTG security layer — false-positive analysis

Every string scanned here is from a known-clean corpus: the items are
real multilingual tool-call content, not attack fixtures. Any hit is
a false positive by construction.

## FP rate per corpus

| corpus | strings | BIDI_CONTROL_SMUGGLING | INVISIBLE_CONTENT | SCRIPT_HOMOGLYPH | mixed-script |
|---|---:|---:|---:|---:|---:|
| aae_egyptian_arg | 7 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_egyptian_instruction | 3 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_gulf_arg | 18 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_gulf_instruction | 10 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_levantine_arg | 8 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_levantine_instruction | 4 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_maghrebi_arg | 4 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_maghrebi_instruction | 2 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_msa_arg | 80 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_msa_instruction | 32 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| persian | 10 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| **TOTAL** | **178** | **0 (0.0%)** | **0 (0.0%)** | **0 (0.0%)** | **0 (0.0%)** |

## Example hits

_No false-positive hits across any corpus._
