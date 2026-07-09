"""
Template renderer — fills frozen template strings with variables.
Never calls OpenAI. Returns InsightCard or None.
"""

from app.insights.models import FollowUpAction, InsightCard
from app.insights.templates import TEMPLATE_REGISTRY, InsightTemplate


def render_insight_template(
    template_id: str,
    variables: dict,
    severity_override: str | None = None,
) -> InsightCard | None:
    tmpl = TEMPLATE_REGISTRY.get(template_id)
    if tmpl is None:
        return None

    # Check required variables
    missing = [v for v in tmpl.required_variables if v not in variables]
    if missing:
        if tmpl.fallback_template_id:
            return render_insight_template(tmpl.fallback_template_id, variables)
        return None

    try:
        headline = tmpl.headline_template.format_map(variables)
        body = tmpl.body_template.format_map(variables)
    except (KeyError, ValueError):
        if tmpl.fallback_template_id:
            return render_insight_template(tmpl.fallback_template_id, variables)
        return None

    severity = severity_override or tmpl.severity

    follow_ups = _build_follow_ups(tmpl, variables)

    return InsightCard(
        template_id=template_id,
        insight_code=tmpl.insight_code,
        severity=severity,
        priority=tmpl.priority,
        headline=headline,
        body_text=body,
        facts_json=variables,
        generated_by="deterministic_template",
        prompt_tokens=0,
        follow_up_actions=follow_ups,
    )


def _build_follow_ups(tmpl: InsightTemplate, variables: dict) -> list[FollowUpAction]:
    actions: list[FollowUpAction] = []

    if tmpl.page_type == "workspace":
        cat = variables.get("category", "")
        actions.append(FollowUpAction(
            action_id=f"view_rankings_{cat}",
            label=f"View {cat} Rankings",
            action_type="open_category_rankings_filtered",
        ))

    if tmpl.page_type in ("category_rankings", "fund_detail"):
        fund = variables.get("fund_name", "")
        sc = variables.get("schemecode")
        if fund:
            actions.append(FollowUpAction(
                action_id=f"chat_{tmpl.template_id}",
                label="Discuss in Research Chat",
                action_type="open_research_chat_with_context",
                llm_context_payload={
                    "source_insight_id": tmpl.template_id,
                    "facts_json": variables,
                },
            ))

    if tmpl.page_type == "fund_comparison":
        actions.append(FollowUpAction(
            action_id=f"chat_cmp_{tmpl.template_id}",
            label="Discuss in Research Chat",
            action_type="open_research_chat_with_context",
            llm_context_payload={
                "source_insight_id": tmpl.template_id,
                "facts_json": variables,
            },
        ))

    return actions
