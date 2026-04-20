"""Trace-grade observability for MTG-guarded agent runs.

Workflow-level debugging primitive: a `Trace` is an ordered sequence
of `Turn` records, each capturing what the agent did and what the
pipeline said about it. Lets you grade failure modes at the workflow
level ("did the agent recover after the tool error?", "did it abstain
when it should have?") instead of per-call.

Deliberately smaller scope than OpenAI's full trace-grading surface:
- no model-graded rubrics; we ship a deterministic rule-based grader
- no span hierarchy; flat per-turn records are the shape
- no external backend; everything is local NDJSON

Interop target: easy to bridge to OpenTelemetry GenAI semantics later
(agent span, execute-tool span, eval-result event) once those
conventions stabilize. Until then, the Trace shape below is a stable
internal schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional


@dataclass
class Turn:
    """One turn in an agent trace.

    A turn typically corresponds to:
    - one user instruction
    - zero or more tool calls the agent issued in response
    - their tool results
    - any MTG violations + repairs that fired during the turn
    - a final per-turn outcome

    Latency/token fields are opt-in — callers that don't track them
    leave them at zero.
    """

    turn_id: int
    instruction: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    violations: list[dict[str, Any]] = field(default_factory=list)
    repairs: list[dict[str, Any]] = field(default_factory=list)
    # Per-turn outcome: "pass" | "partial" | "fail" | "abstain" | "error"
    # - "abstain" when the agent declined to call a tool (empty tool_calls
    #   plus an explicit refusal in the assistant response)
    # - "error" when a tool call raised / timed out
    outcome: str = "pass"
    # Model-side telemetry (opt-in)
    latency_ms: Optional[float] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    # Free-form per-turn notes the grader or agent wants to surface
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Turn:
        return cls(
            turn_id=int(data.get("turn_id", 0)),
            instruction=data.get("instruction", "") or "",
            tool_calls=list(data.get("tool_calls") or []),
            tool_results=list(data.get("tool_results") or []),
            violations=list(data.get("violations") or []),
            repairs=list(data.get("repairs") or []),
            outcome=data.get("outcome", "pass") or "pass",
            latency_ms=data.get("latency_ms"),
            tokens_in=data.get("tokens_in"),
            tokens_out=data.get("tokens_out"),
            notes=data.get("notes", "") or "",
        )


@dataclass
class Trace:
    """Ordered sequence of turns for one agent run.

    `trace_id` identifies the run uniquely; `metadata` carries scope
    (provider, model, dataset_version, task) so downstream consumers
    can filter.
    """

    trace_id: str
    turns: list[Turn] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    ended_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "metadata": dict(self.metadata),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "turns": [t.to_dict() for t in self.turns],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Trace:
        return cls(
            trace_id=str(data.get("trace_id", "")),
            turns=[Turn.from_dict(t) for t in (data.get("turns") or [])],
            metadata=dict(data.get("metadata") or {}),
            started_at=data.get("started_at", "") or "",
            ended_at=data.get("ended_at", "") or "",
        )

    @property
    def n_turns(self) -> int:
        return len(self.turns)

    @property
    def outcome(self) -> str:
        """Worst turn outcome across the trace. Mirrors the severity
        aggregation in GuardResult: error > fail > partial > abstain >
        pass. Rationale: one bad turn in a 10-turn trace is still a
        failed trace."""
        order = {"error": 5, "fail": 4, "partial": 3, "abstain": 2, "pass": 1}
        worst = "pass"
        worst_rank = 1
        for t in self.turns:
            rank = order.get(t.outcome, 0)
            if rank > worst_rank:
                worst_rank = rank
                worst = t.outcome
        return worst


@dataclass
class Rubric:
    """Rule-based grading spec. Deliberately simple — this is the
    deterministic counterpart of model-graded rubrics.

    Every check is an invariant that must hold across the whole trace.
    Callers mix these into the rubric they want; `grade_trace` runs
    each check and reports pass/fail per check."""

    # Maximum number of turns allowed. None = no cap.
    max_turns: Optional[int] = None
    # Maximum number of "fail" or "error" turns allowed. Default 0 —
    # any hard-fail turn fails the trace.
    max_hard_fail_turns: int = 0
    # If True, the trace must end with a non-error turn.
    require_final_success: bool = True
    # Violation codes that, if they appear in any turn, fail the trace.
    forbidden_violation_codes: tuple[str, ...] = (
        "BIDI_CONTROL_SMUGGLING",
        "PROMPT_INJECTION_SUSPECTED",
        "SURFACE_CORRUPTION_POST_CALL",
    )
    # Tool names that must NOT appear anywhere in the trace's tool_calls.
    # Useful for verifying abstention ("agent must not call delete_account").
    forbidden_tools: tuple[str, ...] = ()
    # Tool names that MUST appear at least once in the trace.
    required_tools: tuple[str, ...] = ()


@dataclass
class TraceGrading:
    """Result of applying a rubric to a trace."""

    trace_id: str
    outcome: str  # "pass" | "fail"
    failed_checks: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def grade_trace(trace: Trace, rubric: Optional[Rubric] = None) -> TraceGrading:
    """Apply `rubric` to `trace` and return pass/fail + per-check status.

    Deterministic. No I/O. `rubric=None` uses the default Rubric
    (reasonable defaults for a well-behaved run)."""
    rubric = rubric or Rubric()
    failed: list[str] = []
    details: dict[str, Any] = {}

    if rubric.max_turns is not None and trace.n_turns > rubric.max_turns:
        failed.append(
            f"too_many_turns (got {trace.n_turns}, max {rubric.max_turns})"
        )

    hard_fail_turns = [
        t for t in trace.turns if t.outcome in ("fail", "error")
    ]
    if len(hard_fail_turns) > rubric.max_hard_fail_turns:
        failed.append(
            f"too_many_hard_fail_turns (got {len(hard_fail_turns)}, "
            f"max {rubric.max_hard_fail_turns})"
        )
        details["hard_fail_turn_ids"] = [t.turn_id for t in hard_fail_turns]

    if rubric.require_final_success and trace.turns:
        final = trace.turns[-1]
        if final.outcome in ("fail", "error"):
            failed.append(f"final_turn_failed (outcome={final.outcome!r})")

    observed_codes: set[str] = set()
    for t in trace.turns:
        for v in t.violations:
            code = v.get("code") if isinstance(v, dict) else None
            if code:
                observed_codes.add(code)
    forbidden_present = set(rubric.forbidden_violation_codes) & observed_codes
    if forbidden_present:
        failed.append(
            f"forbidden_violations_present ({sorted(forbidden_present)})"
        )

    called_tools: set[str] = set()
    for t in trace.turns:
        for call in t.tool_calls:
            name = call.get("function") or call.get("name") if isinstance(call, dict) else None
            if name:
                called_tools.add(name)

    forbidden_called = set(rubric.forbidden_tools) & called_tools
    if forbidden_called:
        failed.append(
            f"forbidden_tools_called ({sorted(forbidden_called)})"
        )

    missing_required = set(rubric.required_tools) - called_tools
    if missing_required:
        failed.append(
            f"required_tools_missing ({sorted(missing_required)})"
        )

    return TraceGrading(
        trace_id=trace.trace_id,
        outcome="pass" if not failed else "fail",
        failed_checks=failed,
        details=details,
    )


def load_ndjson(path: Path) -> list[Trace]:
    """Load a trace chain from NDJSON (one Trace dict per line)."""
    out: list[Trace] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(Trace.from_dict(json.loads(line)))
    return out


def render_markdown(trace: Trace, grading: Optional[TraceGrading] = None) -> str:
    """Render one trace as human-readable Markdown. Useful for PR
    comments, review threads, or dropping into a bug report."""
    parts: list[str] = [f"# Trace `{trace.trace_id}`", ""]
    if trace.metadata:
        parts.append("**Metadata:**")
        for k, v in sorted(trace.metadata.items()):
            parts.append(f"- `{k}`: `{v}`")
        parts.append("")

    if grading is not None:
        status = "✅ pass" if grading.outcome == "pass" else "❌ fail"
        parts.extend([
            f"**Grading:** {status}",
            "",
        ])
        if grading.failed_checks:
            parts.append("**Failed checks:**")
            for check in grading.failed_checks:
                parts.append(f"- {check}")
            parts.append("")

    parts.extend([
        f"**Turns:** {trace.n_turns} · **Outcome:** `{trace.outcome}`",
        "",
    ])

    for t in trace.turns:
        parts.extend([
            f"## Turn {t.turn_id} — `{t.outcome}`",
            "",
        ])
        if t.instruction:
            parts.append(f"**Instruction:** {t.instruction}")
            parts.append("")
        if t.tool_calls:
            parts.append("**Tool calls:**")
            for call in t.tool_calls:
                name = call.get("function") or call.get("name") or "?"
                args = call.get("arguments") or {}
                parts.append(f"- `{name}` — args: `{json.dumps(args, ensure_ascii=False)}`")
            parts.append("")
        if t.violations:
            parts.append("**Violations:**")
            for v in t.violations:
                code = v.get("code") if isinstance(v, dict) else "?"
                sev = v.get("severity") if isinstance(v, dict) else "?"
                msg = v.get("message") if isinstance(v, dict) else ""
                parts.append(f"- `{code}` ({sev}): {msg}")
            parts.append("")
        if t.repairs:
            parts.append("**Repairs proposed:**")
            for r in t.repairs:
                action = r.get("action") if isinstance(r, dict) else "?"
                parts.append(f"- `{action}`")
            parts.append("")
        if t.notes:
            parts.append(f"**Notes:** {t.notes}")
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"


__all__ = [
    "Rubric",
    "Trace",
    "TraceGrading",
    "Turn",
    "grade_trace",
    "load_ndjson",
    "render_markdown",
]
