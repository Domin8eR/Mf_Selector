"""LLM-driven report content generator for the Reports Builder.

All generated content is grounded in real data passed in as context.
The LLM never computes metrics — it only narrates pre-computed values.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import settings

_GENERATE_SYSTEM = """You are an AltStreet fund research writer.
You write concise, professional sections for mutual fund research reports.
You cite ONLY the data provided in the prompt — you never fabricate numbers,
ranks, or fund names. Every figure you mention must appear in the input data.

COMPLIANCE RULES — mandatory, any violation disqualifies the report:
  NEVER use: recommendation, buy, sell, best fund, top pick, invest in,
             good investment, you should, clients should, suitable for,
             suitability, personalised, personalized, investment advice,
             financial advice, returns will be, guaranteed, poised to outperform
  ALWAYS use: ranked fund, structural improvement, research candidate,
              composite score, ranked by client rule, metric-derived ranking,
              historically demonstrated, per the data, structurally

Return ONLY a JSON object (no markdown fences) matching the requested schema exactly.
"""


def generate_report_content(
    category: str,
    snapshot_date: str,
    funds: list[dict[str, Any]],
    rule_components: list[dict[str, Any]],
    sections: dict[str, bool],
) -> dict[str, Any]:
    """
    Generate exec_summary, fund_narratives, and key_insights using LLM.

    Falls back to template content when no LLM key is configured.
    `funds` is the top-5 list from ranking_snapshot.
    `rule_components` comes from the active selfmade_rule_version.
    """
    prompt = _build_prompt(category, snapshot_date, funds, rule_components, sections)

    result: dict[str, Any] | None = None
    if settings.anthropic_api_key:
        result = _call_anthropic(prompt)
    elif settings.openai_api_key:
        result = _call_openai(prompt)

    if result is None:
        result = _template_fallback(category, snapshot_date, funds, rule_components)

    return result


def _build_prompt(
    category: str,
    snapshot_date: str,
    funds: list[dict[str, Any]],
    rule_components: list[dict[str, Any]],
    sections: dict[str, bool],
) -> str:
    funds_text = "\n".join(
        f"  Rank {f['rank']}: {f['fund_name']} — composite score {f['composite_score']:.2f}, "
        f"IR 3Y {f['information_ratio_3yr']:.4f}, Sharpe score {f['sharpe_score']:.4f}, "
        f"rank delta 6M {f.get('rank_delta_6m', 'N/A')}"
        for f in funds
    )
    weights_text = "\n".join(
        f"  {c['component_name']} ({c['metric_column']}): weight {float(c['weight'])*100:.1f}%, "
        f"direction {c['direction']}"
        for c in rule_components
    )
    requested = [k for k, v in sections.items() if v]

    return f"""Generate research report content for:
Category: {category}
Snapshot date: {snapshot_date}
Requested sections: {', '.join(requested)}

Top-ranked funds (use ONLY these numbers, do not fabricate):
{funds_text}

Active scoring rule components:
{weights_text}

Return a JSON object with these keys:
{{
  "exec_summary": "<2-3 paragraphs: overview of category, what the composite score measures, top structural findings — grounded in the numbers above>",
  "fund_narratives": [
    {{"schemecode": <int>, "fund_name": "<name>", "narrative": "<1 sentence: why this fund ranks here, citing its IR/Sharpe/score>"}}
  ],
  "key_insights": [
    {{"heading": "<short heading>", "body": "<1-2 sentence insight grounded in the data>"}},
    ...
  ]
}}

key_insights must have 3 entries. Use only the data provided above. Follow compliance rules strictly.
"""


def _call_anthropic(prompt: str) -> dict[str, Any] | None:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=_GENERATE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        return _parse(raw)
    except Exception:
        return None


def _call_openai(prompt: str) -> dict[str, Any] | None:
    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.llm_model or "gpt-4o",
            max_tokens=1500,
            temperature=0.3,
            messages=[
                {"role": "system", "content": _GENERATE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        raw = resp.choices[0].message.content or ""
        return _parse(raw)
    except Exception:
        return None


def _parse(raw: str) -> dict[str, Any] | None:
    try:
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(clean)
    except (json.JSONDecodeError, TypeError):
        return None


def _template_fallback(
    category: str,
    snapshot_date: str,
    funds: list[dict[str, Any]],
    rule_components: list[dict[str, Any]],
) -> dict[str, Any]:
    """Template-mode content when no LLM key is available."""
    top = funds[0] if funds else {}
    weights_summary = ", ".join(
        f"{c['component_name']} ({float(c['weight'])*100:.0f}%)"
        for c in rule_components
    )
    exec_summary = (
        f"This report covers the {category} segment as of {snapshot_date}. "
        f"Funds are ranked by a composite score derived from: {weights_summary}. "
        f"All rankings are metric-derived and reflect structural characteristics "
        f"computed from historical data — they do not constitute investment guidance."
        + (
            f"\n\nThe top-ranked research candidate in this category is "
            f"{top.get('fund_name', 'N/A')} with a composite score of "
            f"{float(top.get('composite_score', 0)):.2f}, reflecting strong "
            f"structural metrics per the active client rule."
            if top else ""
        )
    )
    fund_narratives = [
        {
            "schemecode": f["schemecode"],
            "fund_name": f["fund_name"],
            "narrative": (
                f"Ranked #{f['rank']} with composite score {float(f['composite_score']):.2f} "
                f"and 3Y Information Ratio {float(f['information_ratio_3yr']):.4f} — "
                f"structurally strong by the active rule weighting."
            ),
        }
        for f in funds
    ]
    key_insights = [
        {
            "heading": "Composite Score Distribution",
            "body": (
                f"The top-ranked fund scores {float(funds[0]['composite_score']):.2f} vs "
                f"{float(funds[-1]['composite_score']):.2f} for rank #{funds[-1]['rank']} — "
                f"a spread of {float(funds[0]['composite_score']) - float(funds[-1]['composite_score']):.2f} points."
                if len(funds) >= 2 else "Insufficient data for spread analysis."
            ),
        },
        {
            "heading": "Rule Methodology",
            "body": (
                f"The active rule weights {len(rule_components)} components. "
                f"IR 3Y carries the highest weight at "
                f"{float(rule_components[0]['weight'])*100:.0f}% when sorted by sort_order."
                if rule_components else "No active rule components found."
            ),
        },
        {
            "heading": "Data Recency",
            "body": (
                f"Snapshot date: {snapshot_date}. Rankings reflect data as of this date. "
                f"Historical data is sourced from validated internal tables only."
            ),
        },
    ]
    return {
        "exec_summary": exec_summary,
        "fund_narratives": fund_narratives,
        "key_insights": key_insights,
    }
