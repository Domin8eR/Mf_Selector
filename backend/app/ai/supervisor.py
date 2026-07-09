"""Intent classification and response generation.

Flow:
  1. recommendation_request keyword guard (deterministic, fires first)
  2. LLM classification (GPT-4o if OPENAI_API_KEY; Claude Haiku if ANTHROPIC; else keyword)
  3. Tool execution (caller's responsibility)
  4. generate_response — structured JSON from LLM or template fallback

Language rule (enforced in system prompts AND in output scrubbing):
  NEVER: "recommendation", "buy", "sell", "best fund", "top pick"
  USE:   "ranked fund", "structural improvement", "research candidate", "composite score"
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import settings

# ── Intent catalogue ──────────────────────────────────────────────────────────

INTENTS = {
    "recommendation_request": {
        "keywords": [],  # detected by _REFRAME_RE only
        "tools": [],
        "description": "User asking for buy/sell/switch/suitability guidance",
    },
    "lens_query": {
        "keywords": [
            "structurally improving", "ir slope", "quadrant", "lens",
            "improving ir", "declining ir", "filter funds", "find funds with",
            "which funds have", "show me funds", "funds where", "high ir",
            "improving trend", "rank movers", "movers", "trending up", "trending down",
        ],
        "tools": [],
        "description": "NL filter → scatter lens spec (x_metric, y_metric, quadrant)",
    },
    "ranking_explain": {
        "keywords": ["rank", "ranked", "ranking", "top fund", "top performing",
                     "structurally improving", "composite score", "highest score",
                     "category ranking", "best performing", "who is ranked"],
        "tools": ["get_category_rankings"],
        "description": "Show or explain fund rankings in a category",
    },
    "fund_metrics": {
        "keywords": ["information ratio", "ir", "sharpe", "alpha", "sortino",
                     "tracking error", "metrics", "metric", "performance of",
                     "how is", "outperformed", "returns of", "ir slope",
                     "rolling ir", "rolling trend", "3 year", "5 year", "consistency",
                     "growth of 10k", "10,000", "10k", "rank history", "rank trend",
                     "rank over time", "rank movement"],
        "tools": ["get_fund_metrics"],
        "description": "Metrics, rank history, or growth-of-10k for a specific fund",
    },
    "compare": {
        "keywords": ["compare", "vs", "versus", "side by side", "difference between",
                     "which is better", "both funds"],
        "tools": ["compare_funds"],
        "description": "Side-by-side fund comparison",
    },
    "document_search": {
        "keywords": ["factsheet", "document", "mandate", "strategy", "stated",
                     "prospectus", "sid", "scheme information", "fund strategy",
                     "investment objective", "risk disclosure", "portfolio approach"],
        "tools": ["search_documents"],
        "description": "Search fund factsheets and scheme documents",
    },
    "rule_help": {
        "keywords": ["rule", "weight", "formula", "scoring", "methodology",
                     "how is the score", "what drives", "rule set", "component",
                     "what factors", "how are funds ranked"],
        "tools": ["get_current_rules"],
        "description": "Explain the scoring rules and methodology",
    },
    "report": {
        "keywords": ["report", "export", "download", "generate report", "pdf"],
        "tools": [],
        "description": "Generate or download a report",
    },
    "navigation": {
        "keywords": ["go to", "show me the", "take me to", "open", "navigate",
                     "where is", "page", "screen"],
        "tools": [],
        "description": "Navigate to a specific screen",
    },
}

# ── Recommendation guard ──────────────────────────────────────────────────────
# Catches buy/sell/switch/suitability phrasings before any tool is called.

_REFRAME_RE = re.compile(
    r"\b("
    # Direct action requests
    r"should i (buy|sell|invest|switch|put money|allocate|hold|redeem|exit|add|move)"
    r"|worth (buying|selling|investing|adding|it)"
    r"|time to (buy|sell|invest|exit|switch|redeem)"
    r"|is it a good time"
    r"|to (buy|sell) (now|today|right now|this fund|into)"
    # "best fund to buy" style
    r"|best fund to (buy|invest|pick|choose|select)"
    r"|best .{0,30} to (buy|invest in|choose)"
    # Advice/recommendation framing
    r"|recommend(ation)?"
    r"|should i (invest|switch|add|put|move)"
    r"|tell me which (one|fund)"
    r"|which (one|fund) (should|would you|do you|would) (i|you) (pick|choose|buy|invest|go for)"
    r"|which (one|fund) is better for (me|my)"
    r"|which (one|fund) would you (pick|choose|go for|recommend)"
    r"|just (pick|tell me|give me)"
    r"|what should i (do|buy|pick|choose|invest)"
    r"|where should i (invest|put|allocate)"
    r"|what would you (pick|choose|buy|invest)"
    # Suitability framing
    r"|suitable for (me|my)"
    r"|right for (me|my)"
    r"|good (investment|option|choice|pick) for (me|my)"
    r"|best fund for (me|my)"
    r"|best for my (goals|portfolio|risk|situation)"
    r"|(my|my own) (portfolio|goals|risk appetite|risk profile|situation)"
    r"|(suitability|suitable|appropriate) for"
    # Indirect "good investment" framing
    r"|is .{0,40} (a good|worth) (investment|bet|choice)"
    r"|good .{0,20} to invest"
    # Disguised-as-analysis (sound like research but imply personal selection)
    r"|if (i|you) had to (choose|pick|select|go with)"
    r"|(edges?|comes?) out (ahead|on top|better) for (me|my|someone in my)"
    r"|for someone in my (position|situation|place|shoes)"
    r"|(stronger|better|superior|winning) choice"
    r"|which .{0,30} (rational|prudent|sensible) (investor|person|analyst) (would|should)"
    r"|lean toward(s)? (one|this|that|which)"
    r"|what .{0,20} (data|numbers|metrics|analysis) (tell|suggest|indicate|say|show) .{0,20} (to do|should do|person|investor)"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def _is_recommendation_request(message: str) -> bool:
    return bool(_REFRAME_RE.search(message))


# ── LLM classify prompt ───────────────────────────────────────────────────────

_CLASSIFY_SYSTEM = """You are an intent classifier for a mutual fund research workspace.
Classify the user query into exactly one intent from this list:
  ranking_explain   — user wants ranked funds or to understand rankings
  fund_metrics      — user wants specific metric values for a named fund
  compare           — user wants to compare 2+ funds side by side
  document_search   — user wants to search factsheets or fund documents
  rule_help         — user wants to understand scoring rules/methodology
  report            — user wants to generate or download a report
  navigation        — user wants to navigate to a screen or page
  recommendation_request — user is asking for investment advice, buy/sell/switch, or suitability

Return ONLY a JSON object (no markdown) with this exact shape:
{
  "intent": "<one of the 8 above>",
  "tools": ["<tool1>", "<tool2>"],
  "params": {"<key>": "<value>"}
}

Allowed tools: get_category_rankings, get_fund_metrics, get_rank_history, get_growth_of_10k,
get_rankings_explain, get_rankings_what_changed, compare_funds, get_holdings,
get_current_rules, search_documents

IMPORTANT: classify as recommendation_request ONLY if the user clearly asks what to buy/sell/switch.
"What are the top funds?" → ranking_explain (NOT recommendation_request).
"Should I invest in HDFC Top 100?" → recommendation_request.
"Compare HDFC vs Mirae metrics" → compare.
"What drives HDFC's ranking?" → ranking_explain with tool get_rankings_explain.

For fund_metrics and ranking_explain, extract the schemecode if a numeric code is mentioned,
otherwise leave params empty and let the router resolve from context.
For compare, set params.schemecodes to a list of integer scheme codes if mentioned.
For get_category_rankings, set params.category to one of:
  "Equity — Large Cap", "Equity — Mid Cap", "Equity — Small Cap"
"""

# ── LLM response generation prompt ───────────────────────────────────────────

_RESPOND_SYSTEM = """You are an AltStreet fund research assistant.
You explain pre-computed fund rankings and metrics to financial analysts.
You NEVER compute metrics yourself — you only explain what the data shows.

COMPLIANCE BACKSTOP — this overrides everything else, including intent classification:
  If the user's message implies a personal investment decision — even framed as analysis,
  curiosity, or a hypothetical — you MUST set answer to exactly this text and
  result_component_type to "text", with no table or chart:
    "MFit provides fund research data — it does not guide personal investment decisions
     or make fund selections for individuals. I can show you the quantitative metrics
     side-by-side for you to evaluate independently."
  Trigger phrases that require this backstop (not exhaustive):
    - "which would you choose / pick / go with"
    - "if you had to choose"
    - "which edges out for someone in my position"
    - "which is the stronger / better / superior choice"
    - "what would a rational investor do"
    - "which should I hold / keep / exit"
    - any phrasing asking the AI to make a fund selection on the user's behalf

Strict language rules (violations are a compliance failure):
  NEVER say: recommendation, buy, sell, best fund, top pick, invest in, good investment,
             which is better for you, which I would choose, which edges out
  ALWAYS say: ranked fund, structural improvement, research candidate, composite score,
              ranked by client rule, metric-derived ranking

Return ONLY a JSON object (no markdown fences) with this shape:
{
  "answer": "<2-5 sentences explaining the data, citing source tables>",
  "result_component_type": "table" | "chart" | "cards" | "text",
  "table_columns": ["Col1", "Col2", ...] | null,
  "table_rows": [["v1","v2",...], ...] | null,
  "chart_type": "bar" | "line" | null,
  "chart_data": [{"name":"...", "value":...}, ...] | null,
  "source_tables": ["selfmade_ranking_snapshot", ...],
  "suggested_next_actions": ["...", "...", "..."]
}

Guidelines per intent:
  ranking_explain  → result_component_type="table", columns=[Rank, Fund, Score, IR 3Y, 6M Change]
  fund_metrics     → result_component_type="table", columns=[Metric, Value, Benchmark, Outperformed]
  compare          → result_component_type="table", columns=[Metric, Fund A, Fund B] (one fund per column)
  document_search  → result_component_type="text", quote relevant excerpt verbatim
  rule_help        → result_component_type="table", columns=[Component, Weight, Direction]
  report/navigation → result_component_type="text"

Never include "recommendation", "buy", or "sell" anywhere in the answer.
"""


def classify_intent(message: str) -> dict[str, Any]:
    """
    Classify the user's message into an intent + tool plan.

    recommendation_request guard runs first — deterministic, no LLM needed.
    """
    if _is_recommendation_request(message):
        return {
            "intent": "recommendation_request",
            "tools": [],
            "params": {},
            "classifier": "guard",
        }

    if settings.openai_api_key:
        return _classify_openai(message)
    if settings.anthropic_api_key:
        return _classify_anthropic(message)
    return _classify_keywords(message)


def _classify_openai(message: str) -> dict[str, Any]:
    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.llm_model or "gpt-4o",
            max_tokens=200,
            temperature=0,
            messages=[
                {"role": "system", "content": _CLASSIFY_SYSTEM},
                {"role": "user", "content": message},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(_strip_json(raw))
        intent = parsed.get("intent", "ranking_explain")
        if intent not in INTENTS:
            intent = "ranking_explain"
        # LLM may also classify as recommendation_request — honour it
        tools = parsed.get("tools", INTENTS[intent]["tools"])
        return {
            "intent": intent,
            "tools": [t for t in tools if t in _all_tools()],
            "params": parsed.get("params", {}),
            "classifier": "llm_openai",
        }
    except Exception:
        return _classify_keywords(message)


def _classify_anthropic(message: str) -> dict[str, Any]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": message}],
        )
        raw = resp.content[0].text.strip()
        parsed = json.loads(_strip_json(raw))
        intent = parsed.get("intent", "ranking_explain")
        if intent not in INTENTS:
            intent = "ranking_explain"
        tools = parsed.get("tools", INTENTS[intent]["tools"])
        return {
            "intent": intent,
            "tools": [t for t in tools if t in _all_tools()],
            "params": parsed.get("params", {}),
            "classifier": "llm_anthropic",
        }
    except Exception:
        return _classify_keywords(message)


def _classify_keywords(message: str) -> dict[str, Any]:
    msg_lower = message.lower()
    best_intent = "ranking_explain"
    best_score = 0

    for intent_name, cfg in INTENTS.items():
        score = sum(1 for kw in cfg["keywords"] if kw in msg_lower)
        if score > best_score:
            best_score = score
            best_intent = intent_name

    cfg = INTENTS[best_intent]
    return {
        "intent": best_intent,
        "tools": list(cfg["tools"]),
        "params": _extract_keyword_params(message, best_intent),
        "classifier": "keyword",
    }


def _extract_keyword_params(message: str, intent: str) -> dict:
    msg_lower = message.lower()
    params: dict = {}
    if "mid cap" in msg_lower or "midcap" in msg_lower:
        params["category"] = "Equity — Mid Cap"
    elif "small cap" in msg_lower or "smallcap" in msg_lower:
        params["category"] = "Equity — Small Cap"
    else:
        params["category"] = "Equity — Large Cap"
    return params


def _all_tools() -> set[str]:
    from app.ai.tools import ALLOWED_TOOLS
    return ALLOWED_TOOLS


def _strip_json(text: str) -> str:
    """Remove markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


# ── Response generation ───────────────────────────────────────────────────────


def generate_response(
    message: str,
    intent: str,
    tool_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Generate a structured response dict from tool results.

    Returns a dict with: answer, result_component_type, table_columns,
    table_rows, chart_type, chart_data, source_tables, data_confidence,
    suggested_next_actions, llm_available.
    """
    from app.ai.templates import (
        CHAT_NO_TOOL_RESULT_V1,
        CHAT_RECOMMENDATION_REFRAME_V1,
    )

    llm_available = bool(settings.openai_api_key or settings.anthropic_api_key)

    if intent == "recommendation_request":
        return {**CHAT_RECOMMENDATION_REFRAME_V1, "llm_available": llm_available}

    # If all tools errored or returned empty
    all_empty = all("error" in r or not r for r in tool_results)
    if not tool_results or all_empty:
        return {**CHAT_NO_TOOL_RESULT_V1, "llm_available": llm_available}

    # Compute data_confidence from tool results
    coverage = sum(1 for r in tool_results if "error" not in r) / max(len(tool_results), 1)
    as_of_dates = _extract_dates(tool_results)
    recency = max(as_of_dates) if as_of_dates else "N/A"
    conf_level = "high" if coverage >= 0.8 else ("medium" if coverage >= 0.5 else "low")
    data_confidence = {"level": conf_level, "coverage": round(coverage, 2), "recency": recency}

    source_tables = _extract_source_tables(tool_results)

    if llm_available:
        structured = _respond_llm(message, intent, tool_results)
        if structured:
            structured["data_confidence"] = data_confidence
            structured["source_tables"] = source_tables or structured.get("source_tables", [])
            structured["llm_available"] = True
            return structured

    # Template fallback
    result = _respond_template(intent, tool_results)
    result["data_confidence"] = data_confidence
    result["source_tables"] = source_tables
    result["llm_available"] = llm_available
    return result


def _respond_llm(
    message: str,
    intent: str,
    tool_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    context = "\n\n".join(
        f"Tool result {i + 1}:\n{json.dumps(r, default=str)[:1200]}"
        for i, r in enumerate(tool_results)
    )
    user_content = (
        f"User query: {message}\nIntent: {intent}\n\nData from backend tools:\n{context}"
    )

    if settings.openai_api_key:
        return _respond_openai(user_content)
    if settings.anthropic_api_key:
        return _respond_anthropic(user_content)
    return None


def _respond_openai(user_content: str) -> dict | None:
    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.llm_model or "gpt-4o",
            max_tokens=800,
            temperature=0.2,
            messages=[
                {"role": "system", "content": _RESPOND_SYSTEM},
                {"role": "user", "content": user_content},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        return _parse_response(raw)
    except Exception:
        return None


def _respond_anthropic(user_content: str) -> dict | None:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=_RESPOND_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = resp.content[0].text.strip()
        return _parse_response(raw)
    except Exception:
        return None


def _parse_response(raw: str) -> dict | None:
    try:
        parsed = json.loads(_strip_json(raw))
        # Compliance scrub on answer
        answer = parsed.get("answer", "")
        for bad in ("recommendation", " buy ", " sell ", "best fund", "top pick"):
            answer = re.sub(re.escape(bad), lambda m: f"[{m.group().strip()}]", answer, flags=re.IGNORECASE)
        parsed["answer"] = answer
        return parsed
    except (json.JSONDecodeError, TypeError):
        return None


def _respond_template(
    intent: str,
    tool_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keyword-mode fallback — builds table/text from tool results directly."""
    from app.ai.templates import CHAT_DIRECT_ANSWER_WITH_TABLE_V1
    import copy

    result = tool_results[0] if tool_results else {}

    if intent == "ranking_explain" and "funds" in result:
        funds = result["funds"]
        cat = result.get("category", "")
        tpl = copy.deepcopy(CHAT_DIRECT_ANSWER_WITH_TABLE_V1)
        tpl["answer"] = (
            f"Here are the top ranked funds in {cat} by composite score "
            f"(source: selfmade_ranking_snapshot, date: {result.get('snapshot_date', 'N/A')}). "
            "Rankings reflect the active client rule set — not investment guidance."
        )
        tpl["table_columns"] = ["Rank", "Fund", "Score", "IR 3Y", "6M Change"]
        tpl["table_rows"] = [
            [
                f['rank'],
                f['fund_name'],
                round(f['composite_score_v2'] or f['composite_score'] or 0, 2),
                round(f['ir_3yr'] or 0, 3) if f['ir_3yr'] else "—",
                f"{'+' if (f['rank_delta_6m'] or 0) > 0 else ''}{f['rank_delta_6m']}"
                if f['rank_delta_6m'] is not None else "—",
            ]
            for f in funds
        ]
        tpl["suggested_next_actions"] = [
            f"Explain why rank 1 fund in {cat} is ranked first",
            "Compare top 2 funds side by side",
            "Show the scoring rule components",
        ]
        return tpl

    if intent == "fund_metrics" and "metrics" in result:
        m = result["metrics"]
        ret = result.get("returns", {})
        import copy
        tpl = copy.deepcopy(CHAT_DIRECT_ANSWER_WITH_TABLE_V1)
        tpl["answer"] = (
            f"Metrics for **{result.get('fund_name', '')}** "
            f"(source: selfmade_scheme_metrics, as_of: {m.get('as_of_date', 'N/A')}). "
            "All values are pre-computed from validated NAV data."
        )
        tpl["table_columns"] = ["Metric", "Value"]
        rows = []
        if m.get("information_ratio_3yr") is not None:
            rows.append(["Information Ratio (3Y)", f"{m['information_ratio_3yr']:.3f}"])
        if m.get("sharpe_ratio_3yr") is not None:
            rows.append(["Sharpe Ratio (3Y)", f"{m['sharpe_ratio_3yr']:.3f}"])
        if m.get("jensens_alpha_3yr") is not None:
            rows.append(["Jensen's Alpha (3Y)", f"{m['jensens_alpha_3yr']:.3f}"])
        if m.get("sortino_ratio_3yr") is not None:
            rows.append(["Sortino Ratio (3Y)", f"{m['sortino_ratio_3yr']:.3f}"])
        if m.get("tracking_error_3yr") is not None:
            rows.append(["Tracking Error (3Y)", f"{m['tracking_error_3yr']:.3f}%"])
        if m.get("ir_slope_6m_proxy") is not None:
            rows.append(["IR Slope (6M proxy)", f"{m['ir_slope_6m_proxy']:.4f}"])
        if ret.get("fund_3yr") is not None:
            rows.append(["3Y Fund Return", f"{ret['fund_3yr']:.2f}%"])
        if ret.get("fund_5yr") is not None:
            rows.append(["5Y Fund Return", f"{ret['fund_5yr']:.2f}%"])
        tpl["table_rows"] = rows
        tpl["suggested_next_actions"] = [
            f"Explain why this fund is ranked in its category",
            f"Compare this fund with another in the same category",
            "Show this fund's top holdings",
        ]
        return tpl

    if intent == "compare" and "funds" in result:
        import copy
        funds = result["funds"]
        tpl = copy.deepcopy(CHAT_DIRECT_ANSWER_WITH_TABLE_V1)
        tpl["answer"] = (
            "Side-by-side metric comparison (source: selfmade_scheme_metrics). "
            "All values are pre-computed — not generated by AI."
        )
        tpl["table_columns"] = ["Metric"] + [f['fund_name'] for f in funds]
        metrics_keys = [
            ("ir_3yr", "IR (3Y)"),
            ("sharpe_3yr", "Sharpe (3Y)"),
            ("alpha_3yr", "Alpha (3Y)"),
            ("fund_3yr", "3Y Return"),
            ("fund_5yr", "5Y Return"),
            ("active_3yr", "Active Return 3Y"),
        ]
        rows = []
        for key, label in metrics_keys:
            vals = [f.get(key) for f in funds]
            if any(v is not None for v in vals):
                rows.append([label] + [
                    f"{v:.3f}" if isinstance(v, float) else "—" for v in vals
                ])
        tpl["table_rows"] = rows
        tpl["suggested_next_actions"] = [
            "Show holdings of fund 1",
            "Show holdings of fund 2",
            "Explain ranking for one of these funds",
        ]
        return tpl

    if intent == "rule_help" and "components" in result:
        import copy
        tpl = copy.deepcopy(CHAT_DIRECT_ANSWER_WITH_TABLE_V1)
        tpl["answer"] = (
            f"Active rule set: **{result.get('rule_set', 'Default')}** "
            f"(version: {result.get('version_label', 'v1')}). "
            "Each component contributes a weighted score to the fund's composite ranking."
        )
        tpl["table_columns"] = ["Component", "Weight %", "Direction"]
        tpl["table_rows"] = [
            [c["label"], f"{c['weight_pct']}%", c["direction"].replace("_", " ")]
            for c in result["components"]
        ]
        tpl["suggested_next_actions"] = [
            "Show ranked funds in Equity — Large Cap",
            "Explain why a specific fund ranks where it does",
        ]
        return tpl

    if intent == "document_search" and "chunks" in result:
        chunks = result["chunks"]
        if not chunks:
            from app.ai.templates import CHAT_NO_DOCUMENT_EVIDENCE_V1
            return copy.deepcopy(CHAT_NO_DOCUMENT_EVIDENCE_V1)
        excerpt = chunks[0]["chunk_text"][:500]
        return {
            "answer": (
                f"Found {len(chunks)} relevant document section(s). "
                f"Most relevant excerpt (similarity: {chunks[0].get('similarity', 'N/A')}):\n\n"
                f"> {excerpt}"
            ),
            "result_component_type": "text",
            "table_columns": None,
            "table_rows": None,
            "chart_type": None,
            "chart_data": None,
            "suggested_next_actions": [
                "Show quantitative metrics for this fund",
                "Compare with another fund",
            ],
        }

    return {
        "answer": "Query processed. Data retrieved from backend tools — see structured results.",
        "result_component_type": "text",
        "table_columns": None,
        "table_rows": None,
        "chart_type": None,
        "chart_data": None,
        "suggested_next_actions": [],
    }


# ── Lens query interpreter ────────────────────────────────────────────────────
# Section 8.3: reuses the existing three-tier (OpenAI / Anthropic / keyword) chain.
# No fourth NL parsing stack.

_LENS_METRIC_VOCAB = {
    "information_ratio_3yr":  {"label": "3Y IR",              "description": "3-year information ratio (active return ÷ tracking error)", "threshold_type": "median", "higher_better": True},
    "composite_score_v2":     {"label": "Rule Score",         "description": "composite ranking score (weighted IR + Sharpe + active return − TE)",    "threshold_type": "median", "higher_better": True},
    "sharpe_score":           {"label": "Sharpe Score",       "description": "Sharpe ratio score from the ranking model",                               "threshold_type": "median", "higher_better": True},
    "rank_delta_6m":          {"label": "Rank Change (6M)",   "description": "6-month rank movement (negative = rank improved)",                         "threshold_type": "zero",   "higher_better": False},
    "ir_slope_6m_proxy":      {"label": "IR Slope (6m proxy)","description": "6-month linear regression slope of rolling IR (positive = improving trend)","threshold_type": "zero",   "higher_better": True},
    "active_3yr_ret":         {"label": "3Y Active Return %", "description": "3-year excess return vs benchmark, annualised (%)",                        "threshold_type": "zero",   "higher_better": True},
    "fund_3yr_ret":           {"label": "3Y Fund Return %",   "description": "3-year fund CAGR return (%)",                                              "threshold_type": "median", "higher_better": True},
    "fund_5yr_ret":           {"label": "5Y Fund Return %",   "description": "5-year fund CAGR return (%)",                                              "threshold_type": "median", "higher_better": True},
}

_DEFAULT_X = "information_ratio_3yr"
_DEFAULT_Y = "ir_slope_6m_proxy"

_LENS_CLASSIFY_SYSTEM = f"""You are a lens query interpreter for a mutual fund research workspace.
Convert the user's natural language query into a structured scatter-plot lens specification.

ALLOWED x_metric / y_metric values (use ONLY these exact keys):
  information_ratio_3yr  — "3Y IR" — 3-year information ratio
  composite_score_v2     — "Rule Score" — composite ranking score
  sharpe_score           — "Sharpe Score" — Sharpe ratio score
  rank_delta_6m          — "Rank Change (6M)" — 6-month rank movement (lower = rank improved)
  ir_slope_6m_proxy      — "IR Slope (6m proxy)" — 6-month slope of rolling IR
  active_3yr_ret         — "3Y Active Return %" — 3-year excess return vs benchmark
  fund_3yr_ret           — "3Y Fund Return %" — 3-year fund CAGR
  fund_5yr_ret           — "5Y Fund Return %" — 5-year fund CAGR

If the user asks for a metric NOT in the list above, use the default axes
(x=information_ratio_3yr, y=ir_slope_6m_proxy) and explain in filter_summary_text.

ALLOWED categories: "Equity — Large Cap", "Equity — Mid Cap", "Equity — Small Cap"
Default category: "Equity — Large Cap"

ALLOWED quadrant_filter values (or null for all quadrants):
  "improving-strong"  — x >= median AND y >= y_threshold (high level + improving trend)
  "improving-weak"    — x <  median AND y >= y_threshold (low level  + improving trend)
  "declining-strong"  — x >= median AND y <  y_threshold (high level + declining trend)
  "declining-weak"    — x <  median AND y <  y_threshold (low level  + declining trend)

Return ONLY a JSON object (no markdown):
{{
  "x_metric": "<metric key>",
  "y_metric": "<metric key>",
  "category": "<category>",
  "quadrant_filter": "<quadrant name or null>",
  "filter_summary_text": "<1-2 plain-language sentences describing the filter>"
}}

Guideline: x_metric = level/quality dimension; y_metric = trend/change dimension.
If uncertain, default x=information_ratio_3yr, y=ir_slope_6m_proxy and note it.
NEVER produce metric keys not in the allowed list above.
"""

_LENS_KEYWORD_RULES: list[tuple[str, str, str]] = [
    # (keyword_fragment, field, value)
    ("mid cap",        "category",   "Equity — Mid Cap"),
    ("midcap",         "category",   "Equity — Mid Cap"),
    ("small cap",      "category",   "Equity — Small Cap"),
    ("smallcap",       "category",   "Equity — Small Cap"),
    ("sharpe",         "x_metric",   "sharpe_score"),
    ("active return",  "x_metric",   "active_3yr_ret"),
    ("active ret",     "x_metric",   "active_3yr_ret"),
    ("rank change",    "y_metric",   "rank_delta_6m"),
    ("rank mover",     "y_metric",   "rank_delta_6m"),
    ("mover",          "y_metric",   "rank_delta_6m"),
    ("5 year",         "x_metric",   "fund_5yr_ret"),
    ("5yr",            "x_metric",   "fund_5yr_ret"),
    ("3 year return",  "x_metric",   "fund_3yr_ret"),
    ("3yr return",     "x_metric",   "fund_3yr_ret"),
    ("declining",      "quadrant_filter", "declining-strong"),
    ("weakening",      "quadrant_filter", "declining-strong"),
    ("trending down",  "quadrant_filter", "declining-strong"),
    ("improving",      "quadrant_filter", "improving-strong"),
    ("trending up",    "quadrant_filter", "improving-strong"),
    ("structurally",   "quadrant_filter", "improving-strong"),
]


def classify_lens_query(message: str) -> dict[str, Any]:
    """
    Parse a natural-language lens query into a structured spec.

    Always runs the recommendation guard first — a workspace query like
    "which fund should my client put money in" must refuse via the same
    path as chat, not slip through as a lens query.

    Three-tier fallback chain (same as classify_intent — Section 8.3):
      1. OpenAI function-calling if OPENAI_API_KEY
      2. Anthropic Claude Haiku if ANTHROPIC_API_KEY
      3. Keyword matching
    """
    if _is_recommendation_request(message):
        return {
            "refusal_reason": (
                "MFit provides fund research data — it does not guide personal "
                "investment decisions or make fund selections for individuals."
            ),
            "x_metric": _DEFAULT_X,
            "y_metric": _DEFAULT_Y,
            "x_label": _LENS_METRIC_VOCAB[_DEFAULT_X]["label"],
            "y_label": _LENS_METRIC_VOCAB[_DEFAULT_Y]["label"],
            "category": "Equity — Large Cap",
            "quadrant_filter": None,
            "filter_summary_text": "",
            "classifier": "guard",
        }

    raw: dict[str, Any] = {}
    if settings.openai_api_key:
        raw = _lens_classify_openai(message)
    elif settings.anthropic_api_key:
        raw = _lens_classify_anthropic(message)
    if not raw:
        raw = _lens_classify_keywords(message)

    x_metric = raw.get("x_metric", _DEFAULT_X)
    y_metric = raw.get("y_metric", _DEFAULT_Y)
    if x_metric not in _LENS_METRIC_VOCAB:
        x_metric = _DEFAULT_X
    if y_metric not in _LENS_METRIC_VOCAB:
        y_metric = _DEFAULT_Y

    return {
        "refusal_reason": None,
        "x_metric": x_metric,
        "y_metric": y_metric,
        "x_label": _LENS_METRIC_VOCAB[x_metric]["label"],
        "y_label": _LENS_METRIC_VOCAB[y_metric]["label"],
        "category": raw.get("category", "Equity — Large Cap"),
        "quadrant_filter": raw.get("quadrant_filter"),
        "filter_summary_text": raw.get("filter_summary_text", ""),
        "classifier": raw.get("classifier", "keyword"),
    }


def _lens_classify_openai(message: str) -> dict:
    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.llm_model or "gpt-4o",
            max_tokens=300,
            temperature=0,
            messages=[
                {"role": "system", "content": _LENS_CLASSIFY_SYSTEM},
                {"role": "user", "content": message},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        return {**json.loads(_strip_json(raw)), "classifier": "llm_openai"}
    except Exception:
        return {}


def _lens_classify_anthropic(message: str) -> dict:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_LENS_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": message}],
        )
        raw = resp.content[0].text.strip()
        return {**json.loads(_strip_json(raw)), "classifier": "llm_anthropic"}
    except Exception:
        return {}


def _lens_classify_keywords(message: str) -> dict:
    msg = message.lower()
    result: dict[str, Any] = {
        "x_metric": _DEFAULT_X,
        "y_metric": _DEFAULT_Y,
        "category": "Equity — Large Cap",
        "quadrant_filter": "improving-strong",
        "filter_summary_text": "Default filter: 3Y IR vs IR Slope, improving-strong quadrant.",
        "classifier": "keyword",
    }
    for fragment, field, value in _LENS_KEYWORD_RULES:
        if fragment in msg:
            result[field] = value
    if "mid cap" not in msg and "small cap" not in msg:
        result["category"] = "Equity — Large Cap"
    if "quadrant_filter" not in result or not result["quadrant_filter"]:
        result["quadrant_filter"] = "improving-strong"
    x_lbl = _LENS_METRIC_VOCAB[result["x_metric"]]["label"]
    y_lbl = _LENS_METRIC_VOCAB[result["y_metric"]]["label"]
    q = result["quadrant_filter"]
    result["filter_summary_text"] = (
        f"{result['category']}: {x_lbl} × {y_lbl}, {q} quadrant."
    )
    return result


def _extract_dates(tool_results: list[dict]) -> list[str]:
    dates = []
    for r in tool_results:
        for key in ("snapshot_date", "as_of_date"):
            val = r.get(key)
            if isinstance(val, str) and val not in ("N/A", "None", ""):
                dates.append(val)
        if "metrics" in r:
            d = r["metrics"].get("as_of_date")
            if d:
                dates.append(d)
        if "returns" in r:
            d = r["returns"].get("as_of_date")
            if d:
                dates.append(d)
        if "funds" in r:
            for f in r["funds"]:
                d = f.get("as_of_date") or f.get("snapshot_date")
                if d:
                    dates.append(str(d))
    return [d for d in dates if d and d != "None"]


def _extract_source_tables(tool_results: list[dict]) -> list[str]:
    tables: list[str] = []
    for r in tool_results:
        t = r.get("source_table")
        if t:
            tables.append(t)
        ts = r.get("source_tables")
        if isinstance(ts, list):
            tables.extend(ts)
    return list(dict.fromkeys(tables))  # deduplicated, order-preserving
