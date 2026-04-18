"""OpenAI function-calling adapter.

Wraps an OpenAI-style tool definition. Exposes:

    guard_tool(tool_def) -> GuardedTool
    guarded.validate_call(call) -> ValidationReport
    guarded.validate_response(call, response) -> ValidationReport
"""

from __future__ import annotations

from dataclasses import dataclass, field

from adapters import ValidationReport
from mtg.pipeline import validate_pre, validate_post
from mtg.types import GuardResult, GuardSpec


def _tool_parameters(tool_def: dict) -> tuple[str, dict]:
    """Return (tool_name, parameters_schema) from an OpenAI tool definition.

    Supports both the nested `{type: "function", function: {...}}` shape and
    the bare `{name, parameters}` shape.
    """
    if "function" in tool_def and isinstance(tool_def["function"], dict):
        name = tool_def["function"].get("name", "unknown")
        params = tool_def["function"].get("parameters", {})
        return name, params
    name = tool_def.get("name", "unknown")
    params = tool_def.get("parameters", tool_def)
    return name, params


def _extract_guards(parameters: dict) -> dict[str, GuardSpec]:
    out: dict[str, GuardSpec] = {}
    props = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    for name, prop in props.items():
        if isinstance(prop, dict) and "x-mtg" in prop:
            out[name] = GuardSpec.from_dict(prop["x-mtg"])
    return out


@dataclass
class GuardedTool:
    """A tool definition wrapped with MTG guards."""

    tool: dict
    name: str
    guards: dict[str, GuardSpec] = field(default_factory=dict)

    def validate_call(self, call: dict) -> ValidationReport:
        """Run pre-call validation on an OpenAI call dict.

        `call` is expected to have either `arguments` (dict) or `input` (dict),
        or to be the arguments dict itself.
        """
        args = _call_args(call)
        per_param: dict[str, GuardResult] = {}
        for param_name, spec in self.guards.items():
            value = args.get(param_name, "")
            per_param[param_name] = validate_pre(str(value), spec)
        return ValidationReport(tool=self.name, per_param=per_param)

    def validate_response(self, call: dict, response: dict) -> ValidationReport:
        """Run both pre-call and post-call guards. `response` is the tool output.

        The response must be a dict; MTG reads the same parameter names from it
        as it did from the call (echo-back pattern for mutation detection).
        """
        call_args = _call_args(call)
        resp_args = _call_args(response)
        per_param: dict[str, GuardResult] = {}
        for param_name, spec in self.guards.items():
            pre = validate_pre(str(call_args.get(param_name, "")), spec)
            post = validate_post(pre, str(resp_args.get(param_name, "")), spec)
            per_param[param_name] = post
        return ValidationReport(tool=self.name, per_param=per_param)


def _call_args(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("arguments", "input", "args"):
        if isinstance(payload.get(key), dict):
            return payload[key]
    return payload


def guard_tool(tool_def: dict) -> GuardedTool:
    """Wrap an OpenAI-style tool definition with MTG guards."""
    name, params = _tool_parameters(tool_def)
    guards = _extract_guards(params)
    return GuardedTool(tool=tool_def, name=name, guards=guards)
