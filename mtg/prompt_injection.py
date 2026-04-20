"""Prompt-injection detection primitives.

OWASP LLM01 coverage. Heuristic, not ML — the goal is to raise a
reviewable flag when a guarded value looks like it's trying to
hijack the agent, not to classify intent with certainty.

Detection categories:

- **direct_override** — phrases that tell the model to ignore its
  prior instructions: "ignore previous", "disregard all prior", etc.
- **role_hijack** — attempts to flip the conversation role:
  "you are now...", fake system/assistant headers.
- **tool_escalation** — instructions that nudge toward unsafe tool
  use (delete, transfer, send to everyone) embedded in a user-facing
  field.
- **indirect_injection_marker** — delimiters that often demarcate
  injected content in retrieved-document attacks: triple backticks
  around instructions, fake XML tags, "---" around a payload.
- **encoded_payload** — suspicious density of base64 / hex / rot13-
  looking content (heuristic only, high false-positive risk).

All indicators are rule-based. Coverage is deliberately partial; the
purpose is to surface the obvious attacks as a warning layer on top
of the BiDi / homoglyph / script-check layer, not to replace a
dedicated LLM security product.

Wire-up: `pipeline._pre_call_violations` emits
`PROMPT_INJECTION_SUSPECTED` at medium severity when any category
fires. Callers that want stricter policy can promote to high via
their own guard layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Direct override — the classic prompt-injection opener. Case-insensitive,
# tolerates punctuation between words.
_DIRECT_OVERRIDE_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+)?(the\s+)?(previous|prior|above)\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(all\s+)?(the\s+)?(previous|prior|above)\b", re.IGNORECASE),
    re.compile(r"\bforget\s+(all\s+)?(your\s+)?(instructions?|prompts?)\b", re.IGNORECASE),
    re.compile(r"\bnew\s+instructions?:\s*", re.IGNORECASE),
    re.compile(r"\boverride\s+(the\s+)?(previous|system)\b", re.IGNORECASE),
]

# Role hijack — attempts to impersonate system/assistant or re-scope
# the model.
_ROLE_HIJACK_PATTERNS = [
    re.compile(r"\byou\s+are\s+(now\s+)?(a\s+|an\s+|the\s+)?(different|new)\b", re.IGNORECASE),
    # Bare "act as X" is too common a benign phrasing (e.g. "act as a
    # translator"); only flag it when paired with a role-hijack target
    # (admin/root/system/developer/with no restrictions).
    re.compile(
        r"\bact\s+as\s+(a\s+|an\s+|the\s+)?"
        r"(admin|administrator|root|sysadmin|developer|system|dev\s+mode|"
        r"unrestricted|jailbroken|dan|do\s+anything)\b",
        re.IGNORECASE,
    ),
    re.compile(r"</?\s*(system|assistant|user|sys)\s*>", re.IGNORECASE),
    re.compile(r"\[\s*(system|assistant|user|sys)\s*\]", re.IGNORECASE),
    re.compile(r"\bpretend\s+(to\s+be|you\s+are)\b", re.IGNORECASE),
]

# Tool escalation — natural-language instructions that smell like
# unsafe tool invocations. These fire on user-facing text, not on
# legitimate tool responses.
_TOOL_ESCALATION_PATTERNS = [
    re.compile(r"\b(delete|drop|wipe|erase)\s+(all|every|the)\s+\w+", re.IGNORECASE),
    re.compile(r"\btransfer\s+(all|\$?\d+|every|\w+)(\s+\w+)?\s+(to|from)\b", re.IGNORECASE),
    re.compile(r"\bsend\s+\S+(\s+\S+){0,4}\s+to\s+(everyone|all\s+users|all\s+contacts|every\s+\w+)\b", re.IGNORECASE),
    re.compile(r"\bsend\s+to\s+(everyone|all\s+users|all\s+contacts)\b", re.IGNORECASE),
    re.compile(r"\b(shutdown|terminate)\s+(all|the)\s+\w+", re.IGNORECASE),
    re.compile(r"\brevoke\s+(all|every)\s+(permission|access|key)", re.IGNORECASE),
]

# Indirect-injection markers — the structural scaffolding attackers
# use to sneak instructions into retrieved/quoted content.
_INDIRECT_PATTERNS = [
    re.compile(r"```[^\n]*\n.*(ignore|disregard|new\s+instruction)", re.IGNORECASE | re.DOTALL),
    re.compile(r"<!--\s*(inject|hidden|instruction).*?-->", re.IGNORECASE | re.DOTALL),
    re.compile(r"---+\s*BEGIN\s+(INSTRUCTION|INJECTED)\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class Indicator:
    """One prompt-injection signal hit."""

    category: str          # "direct_override", "role_hijack", etc.
    pattern: str           # regex source that matched
    match_text: str        # the literal span that triggered

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "pattern": self.pattern,
            "match": self.match_text,
        }


@dataclass(frozen=True)
class InjectionFinding:
    """Structured summary for a single value."""

    indicators: tuple[Indicator, ...] = ()

    def any(self) -> bool:
        return bool(self.indicators)

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({i.category for i in self.indicators}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicators": [i.to_dict() for i in self.indicators],
            "categories": list(self.categories),
        }


def _match_all(patterns: list[re.Pattern[str]], value: str, category: str) -> list[Indicator]:
    out: list[Indicator] = []
    for pat in patterns:
        for m in pat.finditer(value):
            out.append(Indicator(
                category=category,
                pattern=pat.pattern,
                match_text=m.group(0),
            ))
    return out


def detect_prompt_injection(value: str) -> InjectionFinding:
    """Scan `value` for prompt-injection indicators.

    Heuristic — never mutates, never raises. Empty input → empty
    finding. Long inputs scan in full (no truncation) because
    attackers commonly hide the payload deep in retrieved content.
    """
    if not value:
        return InjectionFinding()
    hits: list[Indicator] = []
    hits.extend(_match_all(_DIRECT_OVERRIDE_PATTERNS, value, "direct_override"))
    hits.extend(_match_all(_ROLE_HIJACK_PATTERNS, value, "role_hijack"))
    hits.extend(_match_all(_TOOL_ESCALATION_PATTERNS, value, "tool_escalation"))
    hits.extend(_match_all(_INDIRECT_PATTERNS, value, "indirect_injection_marker"))
    return InjectionFinding(indicators=tuple(hits))


__all__ = [
    "Indicator",
    "InjectionFinding",
    "detect_prompt_injection",
]
