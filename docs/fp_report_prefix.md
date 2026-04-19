# MTG security layer — false-positive analysis (pre-fix baseline)

Every string scanned here is from a known-clean corpus: the items are
real multilingual tool-call content, not attack fixtures. Any hit is
a false positive by construction.

## FP rate per corpus

| corpus | strings | BIDI_CONTROL_SMUGGLING | INVISIBLE_CONTENT | SCRIPT_HOMOGLYPH | mixed-script |
|---|---:|---:|---:|---:|---:|
| aae_egyptian_arg | 7 | 0 (0.0%) | 0 (0.0%) | 1 (14.3%) | 0 (0.0%) |
| aae_egyptian_instruction | 3 | 0 (0.0%) | 0 (0.0%) | 1 (33.3%) | 0 (0.0%) |
| aae_gulf_arg | 18 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_gulf_instruction | 10 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_levantine_arg | 8 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_levantine_instruction | 4 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_maghrebi_arg | 4 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_maghrebi_instruction | 2 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| aae_msa_arg | 80 | 0 (0.0%) | 0 (0.0%) | 4 (5.0%) | 0 (0.0%) |
| aae_msa_instruction | 32 | 0 (0.0%) | 0 (0.0%) | 3 (9.4%) | 0 (0.0%) |
| persian | 10 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| **TOTAL** | **178** | **0 (0.0%)** | **0 (0.0%)** | **9 (5.1%)** | **0 (0.0%)** |

## Example hits

### `aae_egyptian_arg` / homoglyph
- `'تعالى بكره الساعة ٥'`
### `aae_egyptian_instruction` / homoglyph
- `'عايز أبعت رسالة لمحمد على الواتس أقوله تعالى بكره الساعة ٥'`
### `aae_msa_arg` / homoglyph
- `'١٥ رمضان'`
- `'٢٠ رمضان'`
- `'٢ الظهر'`
- `'٨ المساء'`
### `aae_msa_instruction` / homoglyph
- `'احجز فندق في مكة من يوم ١٥ رمضان إلى ٢٠ رمضان لشخصين'`
- `'رتّب لي اجتماع مع فريق التسويق يوم الأحد الساعة ٢ الظهر عنوانه مراجعة الحملة الإعلانية'`
- `'احجز طاولة لأربعة أشخاص في مطعم نصرت يوم الجمعة الساعة ٨ المساء'`
