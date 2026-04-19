"""Validate x-mtg blocks against the bundled mtg.schema.json.

Wraps jsonschema with friendly error messages. Used by GuardSpec.from_dict
(strict) and the `mtg check-schema` CLI (strict-with-exit-code).

The schema is shipped as package data at `mtg/mtg.schema.json`, so it is
available after `pip install` just as it is in a source checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError


_SPEC_PATH = Path(__file__).resolve().parent / "mtg.schema.json"
_VALIDATOR: Draft202012Validator | None = None


class MTGSchemaError(ValueError):
    """Raised when an x-mtg block fails schema validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _get_validator() -> Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        # Primary: load the package-shipped schema (works after pip install).
        if _SPEC_PATH.exists():
            with _SPEC_PATH.open(encoding="utf-8") as f:
                schema = json.load(f)
        else:
            # importlib.resources fallback for installed packages where the
            # filesystem path may differ (e.g. zipped wheels).
            from importlib.resources import files
            schema_text = files("mtg").joinpath("mtg.schema.json").read_text(
                encoding="utf-8"
            )
            schema = json.loads(schema_text)
        _VALIDATOR = Draft202012Validator(schema)
    return _VALIDATOR


def validate_x_mtg(block: dict[str, Any]) -> list[str]:
    """Validate an x-mtg block. Returns a list of human-readable error strings.

    Empty list == valid. Unknown keys, bad enum values, and wrong types all
    produce errors. Does not mutate the input.
    """
    validator = _get_validator()
    errors: list[ValidationError] = sorted(
        validator.iter_errors(block), key=lambda e: tuple(e.absolute_path)
    )
    out: list[str] = []
    for err in errors:
        path = ".".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{path}: {err.message}")
    return out


def validate_x_mtg_strict(block: dict[str, Any]) -> None:
    """Raise MTGSchemaError if the block is invalid. Silent on success."""
    errors = validate_x_mtg(block)
    if errors:
        raise MTGSchemaError(errors)
