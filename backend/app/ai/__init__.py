"""AltStreet AI agent layer.

Architecture (v9 minimal):
  Supervisor → classifies intent → builds tool plan
  ToolExecutor → calls allow-listed backend APIs → writes tool_call_log
  ExplanationAgent → calls Anthropic with pre-computed results → returns sourced answer

Hard boundary: AI does NOT calculate metrics or rank funds.
Every tool call is logged to tool_call_log.
"""
