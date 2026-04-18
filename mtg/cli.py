"""MTG CLI — validate tools, validate calls, verify receipt chains."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mtg.pipeline import validate_pre
from mtg.receipts import read_chain, verify_chain
from mtg.types import GuardSpec


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _extract_guards(tool_def: dict) -> dict[str, GuardSpec]:
    """Pull every x-mtg block out of an OpenAI-style tool definition."""
    out: dict[str, GuardSpec] = {}
    if "function" in tool_def:
        params = tool_def["function"].get("parameters", {})
    elif "parameters" in tool_def:
        params = tool_def["parameters"]
    elif "input_schema" in tool_def:
        params = tool_def["input_schema"]
    else:
        params = tool_def
    props = params.get("properties", {})
    for name, prop in props.items():
        if "x-mtg" in prop:
            out[name] = GuardSpec.from_dict(prop["x-mtg"])
    return out


def cmd_check_schema(args: argparse.Namespace) -> int:
    tool = _load_json(args.tool)
    guards = _extract_guards(tool)
    if not guards:
        print("No x-mtg annotations found.")
        return 0
    for name, spec in guards.items():
        print(f"  {name}: slot={spec.slot_type} script={spec.script} dialect={spec.dialect_expected} mode={spec.mode}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    tool = _load_json(args.tool)
    call = _load_json(args.call)
    guards = _extract_guards(tool)
    arguments = call.get("arguments") or call.get("input") or {}
    out: dict[str, dict] = {}
    any_violation = False
    for name, spec in guards.items():
        value = arguments.get(name, "")
        result = validate_pre(str(value), spec)
        out[name] = result.to_dict()
        if result.violations:
            any_violation = True
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if any_violation else 0


def cmd_receipt_verify(args: argparse.Namespace) -> int:
    receipts = read_chain(Path(args.path))
    if not receipts:
        print("Chain is empty.")
        return 0
    ok, err = verify_chain(receipts)
    if ok:
        print(f"Chain valid ({len(receipts)} receipts).")
        return 0
    print(f"Chain INVALID: {err}", file=sys.stderr)
    return 1


def main() -> int:
    p = argparse.ArgumentParser(prog="mtg", description="MTG — Morphological Type Guards")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("check-schema", help="Validate x-mtg annotations in a tool definition")
    sp.add_argument("tool", help="Path to tool-definition JSON")
    sp.set_defaults(fn=cmd_check_schema)

    sp = sub.add_parser("validate", help="Run MTG guards on a tool call")
    sp.add_argument("tool", help="Path to tool-definition JSON")
    sp.add_argument("call", help="Path to call JSON (with 'arguments' or 'input')")
    sp.set_defaults(fn=cmd_validate)

    sp = sub.add_parser("receipt-verify", help="Verify a receipt hash chain NDJSON")
    sp.add_argument("path", help="Path to chain.ndjson")
    sp.set_defaults(fn=cmd_receipt_verify)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
