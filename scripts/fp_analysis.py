#!/usr/bin/env python3
"""False-positive analysis for the BiDi / homoglyph / invisible layers.

The security detector is only useful if it's quiet on clean content.
This script runs the detectors over known-clean corpora and reports how
often each violation code fires on something that is, by construction,
not an attack.

Clean corpora scanned:

- `datasets/persian_v1.jsonl` — 10 clean Persian items (we curated them;
  any hit is a false positive on MTG's own test surface).
- `arabic-agent-eval` dialect splits, if available as a sibling checkout
  or via $AAE env var. Real Arabic tool-call items, not attack fixtures.

Output: a Markdown report with per-code FP rate and example hits. Save
with `--out fp_report.md` or pipe to stdout.

Usage:

    python scripts/fp_analysis.py
    python scripts/fp_analysis.py --out docs/fp_report.md
    AAE=/path/to/arabic-agent-eval python scripts/fp_analysis.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from mtg.bidi import detect_bidi_threats  # noqa: E402


@dataclass
class FPReport:
    """Aggregate false-positive counts over one corpus."""

    corpus_name: str
    total_strings: int = 0
    bidi_hits: int = 0
    invisible_hits: int = 0
    homoglyph_hits: int = 0
    mixed_script_hits: int = 0
    context_aware: bool = True
    examples: dict[str, list[str]] = field(default_factory=lambda: {
        "bidi": [], "invisible": [], "homoglyph": [], "mixed_script": [],
    })

    def record(self, value: str) -> None:
        self.total_strings += 1
        f = detect_bidi_threats(value, context_aware_digits=self.context_aware)
        if not f.any():
            return
        if f.bidi_controls or f.tag_chars or f.bidi_marks:
            self.bidi_hits += 1
            if len(self.examples["bidi"]) < 5:
                self.examples["bidi"].append(value)
        if f.invisible_chars:
            self.invisible_hits += 1
            if len(self.examples["invisible"]) < 5:
                self.examples["invisible"].append(value)
        if f.homoglyphs:
            self.homoglyph_hits += 1
            if len(self.examples["homoglyph"]) < 5:
                self.examples["homoglyph"].append(value)
        if f.mixed_script_within_token:
            self.mixed_script_hits += 1
            if len(self.examples["mixed_script"]) < 5:
                self.examples["mixed_script"].append(value)

    def rate(self, kind: str) -> float:
        attr = {
            "bidi": "bidi_hits",
            "invisible": "invisible_hits",
            "homoglyph": "homoglyph_hits",
            "mixed_script": "mixed_script_hits",
        }[kind]
        hits = getattr(self, attr)
        return hits / max(1, self.total_strings)


def _iter_persian() -> Iterable[tuple[str, str]]:
    """Yield (corpus_label, value) from datasets/persian_v1.jsonl."""
    path = HERE / "datasets" / "persian_v1.jsonl"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            yield "persian", item["value"]


def _aae_path() -> Optional[Path]:
    """Find arabic-agent-eval checkout — $AAE, or sibling of this repo."""
    if "AAE" in os.environ:
        p = Path(os.environ["AAE"])
        return p if p.is_dir() else None
    sibling = HERE.parent / "arabic-agent-eval"
    return sibling if sibling.is_dir() else None


def _iter_aae_items() -> Iterable[tuple[str, str]]:
    """Yield (dialect, string) for every Arabic-valued argument across
    the arabic-agent-eval dialect splits."""
    aae = _aae_path()
    if aae is None:
        return
    # The dataset module builds items in memory — import and iterate.
    sys.path.insert(0, str(aae))
    try:
        from arabic_agent_eval.dataset import Dataset  # type: ignore
    except ImportError:
        return
    ds = Dataset()
    for item in ds:
        dialect = item.dialect or "msa"
        # Instruction
        yield f"aae_{dialect}_instruction", item.instruction
        # Every expected-call argument value
        for call in item.expected_calls:
            for arg_value in call.arguments.values():
                if isinstance(arg_value, str):
                    yield f"aae_{dialect}_arg", arg_value


def run_fp_analysis(context_aware: bool = True) -> list[FPReport]:
    """Run the detector over every clean corpus we can find.

    `context_aware=False` reproduces the pre-fix behavior so the
    published report can show a verifiable before/after delta.
    """
    buckets: dict[str, FPReport] = {}

    for label, value in list(_iter_persian()) + list(_iter_aae_items()):
        if label not in buckets:
            buckets[label] = FPReport(corpus_name=label, context_aware=context_aware)
        buckets[label].record(value)

    return sorted(buckets.values(), key=lambda r: r.corpus_name)


def render_markdown(reports: list[FPReport], title_suffix: str = "") -> str:
    if not reports:
        return "No clean corpora found. Set $AAE or check out arabic-agent-eval as a sibling.\n"

    lines = [
        f"# MTG security layer — false-positive analysis{title_suffix}",
        "",
        "Every string scanned here is from a known-clean corpus: the items are",
        "real multilingual tool-call content, not attack fixtures. Any hit is",
        "a false positive by construction.",
        "",
        "## FP rate per corpus",
        "",
        "| corpus | strings | BIDI_CONTROL_SMUGGLING | INVISIBLE_CONTENT | SCRIPT_HOMOGLYPH | mixed-script |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    totals = FPReport(corpus_name="TOTAL")
    for r in reports:
        totals.total_strings += r.total_strings
        totals.bidi_hits += r.bidi_hits
        totals.invisible_hits += r.invisible_hits
        totals.homoglyph_hits += r.homoglyph_hits
        totals.mixed_script_hits += r.mixed_script_hits
        lines.append(
            "| {n} | {t} | {b} ({br:.1%}) | {i} ({ir:.1%}) | {h} ({hr:.1%}) | {m} ({mr:.1%}) |".format(
                n=r.corpus_name, t=r.total_strings,
                b=r.bidi_hits, br=r.rate("bidi"),
                i=r.invisible_hits, ir=r.rate("invisible"),
                h=r.homoglyph_hits, hr=r.rate("homoglyph"),
                m=r.mixed_script_hits, mr=r.rate("mixed_script"),
            )
        )

    lines.append(
        "| **{n}** | **{t}** | **{b} ({br:.1%})** | **{i} ({ir:.1%})** | "
        "**{h} ({hr:.1%})** | **{m} ({mr:.1%})** |".format(
            n=totals.corpus_name, t=totals.total_strings,
            b=totals.bidi_hits, br=totals.rate("bidi"),
            i=totals.invisible_hits, ir=totals.rate("invisible"),
            h=totals.homoglyph_hits, hr=totals.rate("homoglyph"),
            m=totals.mixed_script_hits, mr=totals.rate("mixed_script"),
        )
    )

    # Example hits so reviewers can eyeball the signal.
    lines.extend(["", "## Example hits", ""])
    any_example = False
    for r in reports:
        for kind, examples in r.examples.items():
            if not examples:
                continue
            any_example = True
            lines.append(f"### `{r.corpus_name}` / {kind}")
            for ex in examples:
                # Escape for markdown codeblocks
                lines.append(f"- `{ex!r}`")
    if not any_example:
        lines.append("_No false-positive hits across any corpus._")

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description="FP analysis for MTG security layer")
    p.add_argument("--out", help="Write markdown report to this path instead of stdout")
    p.add_argument(
        "--legacy",
        action="store_true",
        help=(
            "Reproduce the pre-fix (non-context-aware) behavior. "
            "Shows the baseline FP rate that the context-aware fix solved — "
            "useful for publishing a before/after delta."
        ),
    )
    args = p.parse_args()

    reports = run_fp_analysis(context_aware=not args.legacy)
    suffix = " (pre-fix baseline)" if args.legacy else ""
    md = render_markdown(reports, title_suffix=suffix)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
