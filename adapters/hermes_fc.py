"""Hermes-Function-Calling adapter.

Nous's Hermes-Function-Calling uses OpenAI-compatible tool definitions under
the hood. This module is a thin labeled alias over the OpenAI adapter so that
upstream integrations can discover "hermes_fc" explicitly.
"""

from __future__ import annotations

from adapters.openai import GuardedTool, guard_tool as _openai_guard_tool


def guard_tool(tool_def: dict) -> GuardedTool:
    """Wrap a Hermes-FC tool definition with MTG guards."""
    return _openai_guard_tool(tool_def)


__all__ = ["guard_tool", "GuardedTool"]
