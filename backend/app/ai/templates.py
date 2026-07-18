"""CHAT_*_V1 response templates.

Templates are returned when:
  - LLM is not configured (no API key)
  - A compliance guard fires (recommendation_request)
  - A tool returns no data
  - Document evidence is unavailable

Language rule: NEVER say "recommendation", "buy", "sell", "best fund", "top pick".
"""

from __future__ import annotations


CHAT_RECOMMENDATION_REFRAME_V1: dict = {
    "answer": (
        "MFit is a fund research workspace — it surfaces pre-computed metrics, "
        "ranking scores, and structural patterns derived from historical data. "
        "It does not provide investment advice, buy/sell/switch guidance, or "
        "individual suitability assessments.\n\n"
        "**What I can show you:**\n"
        "• Ranked funds in a category by composite score (IR, Sharpe, outperformance)\n"
        "• Metric breakdown explaining why a fund ranks where it does\n"
        "• Side-by-side comparison of two funds on quantitative metrics\n"
        "• Factsheet excerpts describing a fund's stated investment mandate\n\n"
        "Try: *\"Show ranked funds in Equity — Large Cap\"* "
        "or *\"Compare HDFC Top 100 and Mirae Asset Large Cap metrics\"*"
    ),
    "result_component_type": "text",
    "table_columns": None,
    "table_rows": None,
    "chart_type": None,
    "chart_data": None,
    "source_tables": [],
    "data_confidence": {"level": "high", "coverage": 1.0, "recency": "N/A"},
    "suggested_next_actions": [
        "Show ranked funds in Equity — Large Cap",
        "Explain the ranking methodology",
        "Compare two funds by quantitative metrics",
        "Search fund factsheets",
    ],
}

CHAT_NO_TOOL_RESULT_V1: dict = {
    "answer": (
        "The data for this query could not be retrieved. This usually means "
        "the fund isn't in the current ranking snapshot, the fund code wasn't "
        "recognised, or no data has been loaded for this category yet. "
        "Try specifying the fund name more precisely, or browse the Rankings page."
    ),
    "result_component_type": "text",
    "table_columns": None,
    "table_rows": None,
    "chart_type": None,
    "chart_data": None,
    "source_tables": [],
    "data_confidence": {"level": "low", "coverage": 0.0, "recency": "N/A"},
    "suggested_next_actions": [
        "Show ranked funds in Equity — Large Cap",
        "Browse all funds in Equity — Mid Cap",
    ],
}

CHAT_NO_DOCUMENT_EVIDENCE_V1: dict = {
    # Compact-card format (2026-07-18 migration, Section 6): one compact
    # sentence + bullets, not a paragraph block.
    "answer": (
        "**No document evidence:** answer is limited to metrics and holdings data.\n\n"
        "• **Available:** metrics, rankings and holdings.\n"
        "• **Not available:** document evidence.\n"
        "• **Restriction:** do not infer manager intent or strategy cause without sources."
    ),
    "result_component_type": "text",
    "table_columns": None,
    "table_rows": None,
    "chart_type": None,
    "chart_data": None,
    "source_tables": ["selfmade_document_chunk"],
    "data_confidence": {"level": "low", "coverage": 0.0, "recency": "N/A"},
    "suggested_next_actions": [
        "Show this fund's quantitative metrics",
        "Show top-ranked funds with available factsheets",
    ],
}

CHAT_FOLLOWUP_FROM_INSIGHT_V1: dict = {
    # Fires when the user clicks a follow-up action on an insight card —
    # confirms the deterministic context was loaded, in compact-card format.
    "answer": (
        "**Context loaded:** answering from the selected insight and source metrics.\n\n"
        "• **Insight code:** {insight_code}\n"
        "• **Entity:** {entity_name}\n"
        "• **Evaluation date:** {evaluation_date}\n"
        "• **Allowed conclusion:** {allowed_conclusion}"
    ),
    "result_component_type": "text",
    "table_columns": None,
    "table_rows": None,
    "chart_type": None,
    "chart_data": None,
    "source_tables": [],
    "data_confidence": {"level": "high", "coverage": 1.0, "recency": "N/A"},
    "suggested_next_actions": [],
}

CHAT_DIRECT_ANSWER_WITH_TABLE_V1: dict = {
    "answer": "",
    "result_component_type": "table",
    "table_columns": [],
    "table_rows": [],
    "chart_type": None,
    "chart_data": None,
    "source_tables": [],
    "data_confidence": {"level": "medium", "coverage": 0.5, "recency": "N/A"},
    "suggested_next_actions": [],
}

CHAT_DIRECT_ANSWER_WITH_CHART_V1: dict = {
    "answer": "",
    "result_component_type": "chart",
    "table_columns": None,
    "table_rows": None,
    "chart_type": "bar",
    "chart_data": [],
    "source_tables": [],
    "data_confidence": {"level": "medium", "coverage": 0.5, "recency": "N/A"},
    "suggested_next_actions": [],
}
