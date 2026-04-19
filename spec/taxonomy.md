# Slot taxonomy

MTG applies guards only to parameters that declare a `slot_type`. Slot types separate **factorable** spans (where morphological analysis is meaningful) from **non-factorable** spans (where it is noise). This is the primary defense against the "morphology on arbitrary strings" objection.

## Factorable slots

Morphological analysis runs. `morphologically_productive: true` and `canonicalization: root_pattern` are meaningful.

### `action_verb`

The primary imperative or intent verb in a tool-call argument.

Examples: `احجز` (reserve), `ارسل` (send), `ابحث` (search), `اطلب` (order), `حوّل` (transfer).

### `deverbal_noun`

A nominalized action — the noun form of a verb.

Examples: `حجز` (booking), `طلب` (order/request), `إلغاء` (cancellation), `تحويل` (transfer).

### `inflected_request_form`

A morphologically marked request form that binds a dialect register. Gulf `أبي أحجز`, Egyptian `عايز أحجز`, Levantine `بدي احجز`, Maghrebi `بغيت نحجز` all surface the root `ح-ج-ز` with different inflectional patterns.

This slot is the primary place MTG's dialect tracking adds value.

## Non-factorable slots

Morphological analysis is suppressed. Only `script`, `transliteration_allowed`, and `post_call_contract` guards apply.

### `named_entity`

Proper nouns — people, cities, brands, companies. Do not decompose.

Examples: `الرياض` (Riyadh), `البيك` (Al Baik), `أرامكو` (Aramco).

### `temporal`

Time expressions — dates, durations, calendar references. Treat atomically.

Examples: `بكرا` (tomorrow), `الساعة ٥` (at 5), `١٥ رمضان`.

### `numeric`

Numeric literals, quantities, currency amounts. No morphology.

Examples: `1000`, `خمسمئة ريال`, `2%`.

### `identifier`

Opaque strings — IDs, tokens, codes. Never morphology. May still be script-checked if declared `script: latn`.

Examples: `ABC123`, `P987654`, `svc-42`.

### `free_text`

The default for unspecified slots. No morphology, no dialect tracking. Script and transliteration checks still apply if declared.

## Slot-type defaults

Any `string` property without `x-mtg` is treated as `free_text` with `script: any` — effectively opt-out of all guards. Backward compatible.

## `FREE_TEXT_OVERFLOW`

If a parameter declares a factorable `slot_type` but runtime inspection shows the value is dominantly non-factorable (e.g. >70% named-entity tokens, all-numeric), the pipeline emits `FREE_TEXT_OVERFLOW` and downgrades morphological analysis for that call.

Concretely, the downgrade means the returned `Analysis` has `root=None`, `pattern=None`, `lemma=None`, and `morph_confidence=0.0`. The `MORPH_CANONICALIZATION_FAILURE` and `MORPH_AMBIGUITY` annotations are suppressed for overflow-downgraded calls because they would be redundant — morphology was never meaningful here. Dialect detection on the (Arabic) surface is preserved, since dialect classification works on tokens that are not morphologically productive.

The signal also means the schema author put factorable expectations on a slot that actual users fill with free text — worth reviewing the guard annotations for that parameter.
