"""Tests for x-mtg schema validation against spec/mtg.schema.json."""

import pytest

from mtg.schema_validator import (
    MTGSchemaError,
    validate_x_mtg,
    validate_x_mtg_strict,
)
from mtg.types import GuardSpec


def test_valid_full_block_passes():
    block = {
        "slot_type": "inflected_request_form",
        "script": "ar",
        "dialect_expected": "gulf",
        "dialect_enforcement": "preserve",
        "transliteration_allowed": False,
        "morphologically_productive": True,
        "canonicalization": "root_pattern",
        "mode": "advisory",
        "post_call_contract": ["script_match", "dialect_preserve"],
    }
    assert validate_x_mtg(block) == []


def test_valid_minimal_block_passes():
    """All fields have defaults; empty block is valid."""
    assert validate_x_mtg({}) == []


def test_invalid_slot_type_rejected():
    errors = validate_x_mtg({"slot_type": "bogus"})
    assert any("slot_type" in e for e in errors)


def test_invalid_script_rejected():
    errors = validate_x_mtg({"script": "martian"})
    assert any("script" in e for e in errors)


def test_invalid_mode_rejected():
    errors = validate_x_mtg({"mode": "oops"})
    assert any("mode" in e for e in errors)


def test_unknown_key_rejected():
    """additionalProperties=false in the spec means typos are caught."""
    errors = validate_x_mtg({"transliteration_allwoed": False})  # typo
    assert any("transliteration_allwoed" in e or "Additional" in e for e in errors)


def test_wrong_type_rejected():
    errors = validate_x_mtg({"morphologically_productive": "yes"})  # should be bool
    assert any("morphologically_productive" in e for e in errors)


def test_validate_strict_raises_on_invalid():
    with pytest.raises(MTGSchemaError) as exc:
        validate_x_mtg_strict({"script": "elvish", "mode": "nope"})
    assert len(exc.value.errors) >= 2


def test_validate_strict_silent_on_valid():
    validate_x_mtg_strict({"slot_type": "free_text", "script": "ar"})  # no raise


def test_guard_spec_from_dict_rejects_invalid():
    with pytest.raises(MTGSchemaError):
        GuardSpec.from_dict({"script": "bogus"})


def test_guard_spec_from_dict_lenient_bypasses_validation():
    """Adapter internals may pass validate=False for partial blocks during
    migration; still not recommended for public API use."""
    spec = GuardSpec.from_dict({"script": "bogus"}, validate=False)
    # Bypass leaves the invalid value in the dataclass — caller accepted risk.
    assert spec.script == "bogus"
