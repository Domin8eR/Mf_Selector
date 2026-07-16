from __future__ import annotations
import json
import anthropic
import openai as openai_module
from app.core.config import settings
from app.ai.supervisor import _is_recommendation_request
from app.ai.templates import CHAT_RECOMMENDATION_REFRAME_V1
from .tool_result import ToolResult
from . import scheme_tools, exposure_tools, holdings_tools, overlap_tools, company_tools

_LLM_ROW_LIMIT = 100

SYSTEM_PROMPT = """You are an MF Selector research assistant for a mutual fund advisory platform.
You MUST use the provided tools to answer queries. NEVER write SQL directly.
Always provide a clear narrative explanation followed by the data.
Respond in plain text only — no markdown bold (**), no # headers, no bullet asterisks (*). Use plain numbered lists and simple sentences.

DATABASE STRUCTURE:
- AUM is stored in crores (e.g. aum_min=1000 means 1000 crores).
- Category 'Market Cap Fund' has sub_categories: 'Large Cap Fund', 'Mid Cap Fund', 'Small Cap Fund', 'Flexi Cap Fund', 'Large & Mid Cap'
- For 'large cap schemes' queries → use category='Large Cap Fund'
- For 'mid cap schemes' queries → use category='Mid Cap Fund'
- For 'small cap schemes' queries → use category='Small Cap Fund'
- For 'equity schemes' queries → use category='equity' (matches all equity fund types via partial search)
- Status values: 'Active' (default), 'Merged', 'Liquidated', 'FvChange', 'Pending', 'Suspended'
- AMC names resolve automatically: 'HDFC'→HDFC MF, 'ICICI'→ICICI Prudential MF, 'Nippon'→Nippon India MF, 'SBI'→SBI MF, 'Kotak'→Kotak MF, 'Axis'→Axis MF, 'Aditya Birla' or 'ABSL'→Aditya Birla Sun Life MF

TOOL SELECTION HINTS:
- "how many schemes per AMC" → group_by_amc
- "top N schemes by AUM" → sort_schemes with sort_by='aum', sort_dir='desc', limit=N
- "schemes with AUM > X crores" → list_schemes with aum_min=X
- "schemes with AUM < X crores" → list_schemes with aum_max=X
- "schemes launched before YEAR" → list_schemes with launch_date_before='YEAR-01-01'
- "schemes launched after YEAR" → list_schemes with launch_date_after='YEAR-01-01'
- "list schemes by launch date" → sort_schemes with sort_by='launch_date', sort_dir='asc'
- "list schemes alphabetically" → sort_schemes with sort_by='scheme_name', sort_dir='asc'
- "active vs merged vs closed breakdown" → call count_schemes THREE times: once with status='Active', once with status='Merged', once with status='Liquidated', then summarise all three counts together
- "which schemes hold company X" or "exposure to X" → aggregate_company_exposure
- "how many schemes hold X" → count_schemes_holding_company
- "top 5 holdings of scheme X" → list_holdings with top_n=5
- "all holdings / list companies held by scheme X" → list_holdings with no top_n limit
- "holdings count of scheme X" → count_holdings
- "overlap between X and Y" → calculate_overlap
- "common companies between X and Y" → compare_schemes_holdings
- "count of common companies between X and Y" → calculate_overlap (the common_holdings_count metric)
- "large cap / mid cap / small cap split for scheme X" → get_market_cap_split (pass the fund name directly)
- "schemes where large-cap exposure < X%" → filter_by_cap_exposure with large_cap_max=X
- "mid-cap schemes with small-cap exposure > X%" → filter_by_cap_exposure with category='Mid Cap Fund', small_cap_min=X
- "large cap schemes with >X% small cap exposure" → filter_by_cap_exposure with category='Large Cap Fund', small_cap_min=X
"""

# Tool definitions in Anthropic format (converted to OpenAI format on demand)
TOOLS: list[dict] = [
    {
        "name": "list_schemes",
        "description": "List mutual fund schemes. filters JSON keys: amc, category, sub_category, status, aum_min, aum_max, launch_date_before, launch_date_after (ISO dates). Default status=Active. category searches both category and sub_category.",
        "input_schema": {"type": "object", "properties": {"filters": {"type": "string", "description": "JSON object"}}, "required": []},
    },
    {
        "name": "count_schemes",
        "description": "Count schemes matching filters. Same filter keys as list_schemes.",
        "input_schema": {"type": "object", "properties": {"filters": {"type": "string"}}, "required": []},
    },
    {
        "name": "group_by_amc",
        "description": "Group scheme counts by AMC. Use for 'how many schemes per AMC'.",
        "input_schema": {"type": "object", "properties": {"filters": {"type": "string"}}, "required": []},
    },
    {
        "name": "sort_schemes",
        "description": "Sort schemes by a field. sort_by: aum/launch_date/scheme_name. sort_dir: asc/desc. limit: optional max results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filters": {"type": "string"},
                "sort_by": {"type": "string", "enum": ["aum", "launch_date", "scheme_name"]},
                "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
                "limit": {"type": "integer"},
            },
            "required": ["sort_by", "sort_dir"],
        },
    },
    {
        "name": "get_market_cap_split",
        "description": "Get large/mid/small cap allocation percentages for a scheme. scheme_identifier: scheme_id, amfi_code, or isin.",
        "input_schema": {"type": "object", "properties": {"scheme_identifier": {"type": "string"}}, "required": ["scheme_identifier"]},
    },
    {
        "name": "filter_by_cap_exposure",
        "description": "Filter schemes by market-cap exposure thresholds. Pass -1 to skip any threshold. category: optional SEBI category filter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "large_cap_min": {"type": "number"}, "large_cap_max": {"type": "number"},
                "mid_cap_min":   {"type": "number"}, "mid_cap_max":   {"type": "number"},
                "small_cap_min": {"type": "number"}, "small_cap_max": {"type": "number"},
            },
            "required": [],
        },
    },
    {
        "name": "count_breaches",
        "description": "Find large-cap funds where large_cap_pct >= 65% but small_cap_pct exceeds a threshold.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_type": {"type": "string"},
                "small_cap_max": {"type": "number"},
            },
            "required": [],
        },
    },
    {
        "name": "count_holdings",
        "description": "Count the number of holdings in a scheme.",
        "input_schema": {"type": "object", "properties": {"scheme_identifier": {"type": "string"}}, "required": ["scheme_identifier"]},
    },
    {
        "name": "list_holdings",
        "description": "List holdings of a scheme. top_n=0 means all. sort_by: weight (default) or market_value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scheme_identifier": {"type": "string"},
                "top_n": {"type": "integer"},
                "sort_by": {"type": "string"},
            },
            "required": ["scheme_identifier"],
        },
    },
    {
        "name": "concentration_metrics",
        "description": "Get concentration metrics for a scheme: top-1%, top-5% weight, Herfindahl index.",
        "input_schema": {"type": "object", "properties": {"scheme_identifier": {"type": "string"}}, "required": ["scheme_identifier"]},
    },
    {
        "name": "list_holdings_by_market_cap",
        "description": "List holdings of a scheme filtered by market-cap category. cap_type must be exactly: 'Large Cap', 'Mid Cap', or 'Small Cap'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scheme_identifier": {"type": "string"},
                "cap_type": {"type": "string", "enum": ["Large Cap", "Mid Cap", "Small Cap"]},
            },
            "required": ["scheme_identifier", "cap_type"],
        },
    },
    {
        "name": "compare_schemes_holdings",
        "description": "List companies held in common between two schemes, with their weight in each scheme.",
        "input_schema": {
            "type": "object",
            "properties": {"scheme_a": {"type": "string"}, "scheme_b": {"type": "string"}},
            "required": ["scheme_a", "scheme_b"],
        },
    },
    {
        "name": "calculate_overlap",
        "description": "Calculate overlap between two schemes: common holding count, overlap % by count, overlap % by weight.",
        "input_schema": {
            "type": "object",
            "properties": {"scheme_a": {"type": "string"}, "scheme_b": {"type": "string"}},
            "required": ["scheme_a", "scheme_b"],
        },
    },
    {
        "name": "count_schemes_holding_company",
        "description": "Count how many schemes hold a given company.",
        "input_schema": {"type": "object", "properties": {"company_name": {"type": "string"}}, "required": ["company_name"]},
    },
    {
        "name": "aggregate_company_exposure",
        "description": "Get all schemes holding a company with their weight and market_value_crores. min_market_value_crores: optional filter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string"},
                "min_market_value_crores": {"type": "number"},
            },
            "required": ["company_name"],
        },
    },
]


def _to_openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOLS
    ]


def _serialize(result: ToolResult) -> str:
    d = result.to_dict()
    total = len(d.get("table", []))
    if total > _LLM_ROW_LIMIT:
        d["table"] = d["table"][:_LLM_ROW_LIMIT]
        d["narrative_summary"] += f" (Showing first {_LLM_ROW_LIMIT} of {total} rows.)"
    return json.dumps(d, default=str)


def _dispatch(tool_name: str, tool_input: dict) -> str:
    def f(filters_key: str = "filters") -> dict:
        raw = tool_input.get(filters_key, "{}")
        return json.loads(raw) if raw else {}

    match tool_name:
        case "list_schemes":            return _serialize(scheme_tools.list_schemes(f()))
        case "count_schemes":           return _serialize(scheme_tools.count_schemes(f()))
        case "group_by_amc":            return _serialize(scheme_tools.group_by_amc(f()))
        case "sort_schemes":
            return _serialize(scheme_tools.sort_schemes(
                f(), tool_input.get("sort_by", "aum"),
                tool_input.get("sort_dir", "desc"),
                tool_input.get("limit") or None,
            ))
        case "get_market_cap_split":
            return _serialize(exposure_tools.get_market_cap_split(tool_input["scheme_identifier"]))
        case "filter_by_cap_exposure":
            kwargs = {k: v for k, v in tool_input.items() if v is not None}
            return _serialize(exposure_tools.filter_by_cap_exposure(**kwargs))
        case "count_breaches":
            return _serialize(exposure_tools.count_breaches(
                tool_input.get("rule_type", "large_cap_small_cap_breach"),
                tool_input.get("small_cap_max", 10.0),
            ))
        case "count_holdings":
            return _serialize(holdings_tools.count_holdings(tool_input["scheme_identifier"]))
        case "list_holdings":
            return _serialize(holdings_tools.list_holdings(
                tool_input["scheme_identifier"],
                tool_input.get("top_n") or None,
                tool_input.get("sort_by", "weight"),
            ))
        case "concentration_metrics":
            return _serialize(holdings_tools.concentration_metrics(tool_input["scheme_identifier"]))
        case "list_holdings_by_market_cap":
            return _serialize(holdings_tools.list_holdings_by_market_cap(
                tool_input["scheme_identifier"], tool_input.get("cap_type", "Large Cap"),
            ))
        case "compare_schemes_holdings":
            return _serialize(holdings_tools.compare_schemes_holdings(
                tool_input["scheme_a"], tool_input["scheme_b"],
            ))
        case "calculate_overlap":
            return _serialize(overlap_tools.calculate_overlap(
                tool_input["scheme_a"], tool_input["scheme_b"],
            ))
        case "count_schemes_holding_company":
            return _serialize(company_tools.count_schemes_holding_company(tool_input["company_name"]))
        case "aggregate_company_exposure":
            return _serialize(company_tools.aggregate_company_exposure(
                tool_input["company_name"],
                tool_input.get("min_market_value_crores", 0),
            ))
        case _:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})


def _extract_result(last_tool_result: dict | None) -> dict | None:
    if last_tool_result and last_tool_result.get("table"):
        return {
            "columns": last_tool_result.get("columns", []),
            "rows": last_tool_result["table"],
        }
    return None


async def _run_anthropic(message: str) -> dict:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = settings.llm_model or "claude-sonnet-4-6"
    messages: list[dict] = [{"role": "user", "content": message}]
    tool_traces: list[dict] = []
    last_tool_result: dict | None = None
    reply = "I couldn't process that query."

    for _ in range(10):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            reply = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result_str = _dispatch(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })
                    try:
                        parsed = json.loads(result_str)
                        last_tool_result = parsed
                        tool_traces.append({"tool": block.name, "row_count": len(parsed.get("table", []))})
                    except Exception:
                        pass
            messages.append({"role": "user", "content": tool_results})

    return {"reply": reply, "table": _extract_result(last_tool_result), "tool_trace": tool_traces}


async def _run_openai(message: str) -> dict:
    client = openai_module.OpenAI(api_key=settings.openai_api_key)
    model = settings.llm_model or "gpt-4o"
    openai_tools = _to_openai_tools()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    tool_traces: list[dict] = []
    last_tool_result: dict | None = None
    reply = "I couldn't process that query."

    for _ in range(10):
        response = client.chat.completions.create(
            model=model,
            max_tokens=4096,
            tools=openai_tools,
            messages=messages,
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop":
            reply = choice.message.content or reply
            break

        if choice.finish_reason == "tool_calls":
            msg = choice.message
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                tool_input = json.loads(tc.function.arguments)
                result_str = _dispatch(tc.function.name, tool_input)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })
                try:
                    parsed = json.loads(result_str)
                    last_tool_result = parsed
                    tool_traces.append({"tool": tc.function.name, "row_count": len(parsed.get("table", []))})
                except Exception:
                    pass

    return {"reply": reply, "table": _extract_result(last_tool_result), "tool_trace": tool_traces}


async def run_research_chat(message: str) -> dict:
    # Recommendation-reframe guard — same deterministic check app.ai.supervisor
    # runs before the workspace chat calls an LLM. This endpoint (/api/research-chat)
    # had no equivalent: the raw message went straight to the LLM with only a
    # tool-usage system prompt, no compliance backstop. Reused here rather than
    # reimplemented, per CLAUDE.md's language rule applying "everywhere" AI output
    # is produced.
    if _is_recommendation_request(message):
        return {
            "reply": CHAT_RECOMMENDATION_REFRAME_V1["answer"],
            "table": None,
            "tool_trace": [],
        }

    if settings.llm_provider.lower() == "openai":
        return await _run_openai(message)
    return await _run_anthropic(message)
