---
language:
- ar
license: cc-by-4.0
task_categories:
- text-classification
tags:
- function-calling
- tool-use
- arabic
- dialects
- morphology
- type-system
size_categories:
- n<1K
pretty_name: MTG Slots v1
---

# MTG Slots v1 — annotated examples

Ten hand-annotated Arabic tool-call spans plus five English controls, demonstrating the `x-mtg` schema in action. Drawn from [arabic-agent-eval](https://github.com/Moshe-ship/arabic-agent-eval) with explicit morphological and dialect annotations added.

## Purpose

Reference examples for:

- Schema conformance testing of the `x-mtg` extension
- Fixtures for MTG's own unit and integration tests
- A starting point for papers, demos, and downstream consumers

Not a benchmark of model behavior — for that, see [arabic-agent-eval](https://github.com/Moshe-ship/arabic-agent-eval).

## Structure

Each JSONL row:

| Field | Description |
|---|---|
| `id` | Stable identifier (`mtg_<dialect>_<n>` or `ctl_en_<n>`) |
| `surface` | Arabic (or English control) text span |
| `slot_type` | MTG slot type |
| `dialect` | Ground-truth dialect label (`null` for English controls) |
| `x_mtg` | Full `x-mtg` block matching [spec/mtg.schema.json](../spec/mtg.schema.json) |
| `notes` | Human annotation about why this item is interesting |

## Coverage

| Dialect | Items |
|---|---:|
| MSA | 2 |
| Gulf | 2 |
| Egyptian | 2 |
| Levantine | 2 |
| Maghrebi | 2 |
| English control (pass) | 3 |
| English control (fail) | 2 |

## License

CC-BY-4.0. Attribute as: *MTG Slots v1, Mousa Abumazin, https://github.com/Moshe-ship/mtg*
