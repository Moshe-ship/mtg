"""Anthropic tool_use adapter.

Anthropic's tool format uses `input_schema` (vs OpenAI's `parameters`).
Otherwise the flow is identical — extract x-mtg blocks, validate calls.
"""

from __future__ import annotations

from mtg.adapters.openai import GuardedTool, _call_args, _extract_guards


def guard_tool(tool_def: dict) -> GuardedTool:
    """Wrap an Anthropic-style tool definition with MTG guards.

    Anthropic tool shape:
        {
          "name": "...",
          "description": "...",
          "input_schema": {"type": "object", "properties": {...}}
        }
    """
    name = tool_def.get("name", "unknown")
    params = tool_def.get("input_schema", tool_def)
    guards = _extract_guards(params)
    return GuardedTool(tool=tool_def, name=name, guards=guards)


__all__ = ["guard_tool", "GuardedTool"]
