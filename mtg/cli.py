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
    """Validate every x-mtg block in a tool definition against spec/mtg.schema.json.

    Exits 0 if all blocks pass, 2 if any fail. Prints per-field violations to
    stderr on failure.
    """
    from mtg.schema_validator import validate_x_mtg

    tool = _load_json(args.tool)
    # Pull raw blocks (pre-parse) so validation reports point at the source keys.
    if "function" in tool:
        props = tool["function"].get("parameters", {}).get("properties", {})
    elif "parameters" in tool:
        props = tool["parameters"].get("properties", {})
    elif "input_schema" in tool:
        props = tool["input_schema"].get("properties", {})
    else:
        props = (tool.get("properties") or {})

    found = 0
    failures: dict[str, list[str]] = {}
    for name, prop in props.items():
        if not isinstance(prop, dict) or "x-mtg" not in prop:
            continue
        found += 1
        errors = validate_x_mtg(prop["x-mtg"])
        if errors:
            failures[name] = errors

    if found == 0:
        print("No x-mtg annotations found.")
        return 0

    if failures:
        print(f"Schema validation FAILED — {len(failures)}/{found} guards invalid:", file=sys.stderr)
        for name, errors in failures.items():
            for err in errors:
                print(f"  {name}: {err}", file=sys.stderr)
        return 2

    # Success — print the parsed summary
    guards = _extract_guards(tool)
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


def cmd_trace_grade(args: argparse.Namespace) -> int:
    """Grade a chain of traces against a rubric.

    Reads NDJSON (one Trace dict per line) and applies the default
    rubric (no hard-fail turns, no forbidden violations, final turn
    must succeed). Exits non-zero if any trace fails. Writes per-trace
    Markdown + JSON summaries if asked."""
    from mtg.trace import (
        Rubric,
        grade_trace,
        load_ndjson,
        render_markdown as render_trace_md,
    )

    path = Path(args.path)
    if not path.exists():
        print(f"chain not found: {path}", file=sys.stderr)
        return 2

    traces = load_ndjson(path)
    if not traces:
        print("Chain is empty.")
        return 0

    forbidden_tools = tuple(args.forbid_tool or ())
    required_tools = tuple(args.require_tool or ())
    rubric = Rubric(
        max_turns=args.max_turns,
        max_hard_fail_turns=args.max_hard_fail,
        forbidden_tools=forbidden_tools,
        required_tools=required_tools,
    )

    gradings = [grade_trace(t, rubric) for t in traces]
    passed = sum(1 for g in gradings if g.outcome == "pass")
    failed = len(gradings) - passed

    print(f"traces: {len(gradings)}  pass: {passed}  fail: {failed}")
    for trace, grading in zip(traces, gradings):
        flag = "✅" if grading.outcome == "pass" else "❌"
        print(f"  {flag} {trace.trace_id} ({trace.n_turns} turns) "
              f"outcome={trace.outcome}")
        for check in grading.failed_checks:
            print(f"    - {check}")

    if args.json:
        payload = [
            {"trace": t.to_dict(), "grading": g.to_dict()}
            for t, g in zip(traces, gradings)
        ]
        Path(args.json).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote json → {args.json}")
    if args.markdown:
        md_parts: list[str] = []
        for t, g in zip(traces, gradings):
            md_parts.append(render_trace_md(t, g))
        Path(args.markdown).write_text("\n---\n\n".join(md_parts), encoding="utf-8")
        print(f"wrote markdown → {args.markdown}")

    return 0 if failed == 0 else 1


def cmd_report(args: argparse.Namespace) -> int:
    """Aggregate a receipt chain into a JSON and/or HTML scorecard.

    Accepts both mtg-native receipt chains (mtg/receipts.py) and ToolProof
    JSONL receipt logs (both have compatible JSON shapes for the keys the
    aggregator reads).
    """
    from mtg.report import aggregate, load_ndjson, render_html

    path = Path(args.path)
    if not path.exists():
        print(f"chain not found: {path}", file=sys.stderr)
        return 2

    receipts = load_ndjson(path)
    card = aggregate(receipts)
    data = card.to_dict()

    wrote: list[str] = []
    if args.json:
        Path(args.json).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        wrote.append(f"json → {args.json}")
    if args.html:
        Path(args.html).write_text(render_html(card), encoding="utf-8")
        wrote.append(f"html → {args.html}")

    # Human summary on stdout
    print(f"receipts: {data['total_receipts']}")
    print(f"outcomes: {data['by_outcome']}")
    if data["violation_codes"]:
        print("top violations:")
        for code, n in list(data["violation_codes"].items())[:5]:
            print(f"  {code}: {n}")
    if data["dialect_drift_pairs"]:
        print("dialect drift:")
        for pair, n in list(data["dialect_drift_pairs"].items())[:5]:
            print(f"  {pair}: {n}")
    if data["repair_actions"]:
        print("repairs proposed:")
        for action, n in list(data["repair_actions"].items())[:5]:
            print(f"  {action}: {n}")
    if wrote:
        print("wrote: " + ", ".join(wrote))
    if not args.json and not args.html:
        # If no output files requested, dump the JSON to stdout too.
        print()
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


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

    sp = sub.add_parser(
        "report",
        help="Aggregate a receipt chain into a scorecard (JSON + HTML)",
    )
    sp.add_argument("path", help="Path to chain.ndjson (mtg-native or ToolProof)")
    sp.add_argument("--json", metavar="PATH", help="Write scorecard JSON to PATH")
    sp.add_argument("--html", metavar="PATH", help="Write scorecard HTML to PATH")
    sp.set_defaults(fn=cmd_report)

    sp = sub.add_parser(
        "trace-grade",
        help="Grade a chain of agent traces against a rubric (NDJSON in)",
    )
    sp.add_argument("path", help="Path to trace chain NDJSON")
    sp.add_argument("--json", metavar="PATH", help="Write per-trace grading JSON")
    sp.add_argument("--markdown", metavar="PATH",
                     help="Write per-trace Markdown summary")
    sp.add_argument("--max-turns", type=int, default=None,
                     help="Maximum turns allowed per trace")
    sp.add_argument("--max-hard-fail", type=int, default=0,
                     help="Maximum fail/error turns allowed (default 0)")
    sp.add_argument("--forbid-tool", action="append", default=[],
                     metavar="TOOL",
                     help="Tool name that must NOT appear in any turn "
                          "(repeatable; useful for abstention rubrics)")
    sp.add_argument("--require-tool", action="append", default=[],
                     metavar="TOOL",
                     help="Tool name that MUST appear at least once "
                          "(repeatable)")
    sp.set_defaults(fn=cmd_trace_grade)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
