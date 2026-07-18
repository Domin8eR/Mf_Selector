"""
Template renderer — fills frozen compact-card templates with variables.
Never calls an LLM. Returns InsightCard or None.

Compact-card format (2026-07-18): picks one of the template's 4 compact-
sentence variants deterministically (variant_index — hash of entity_id +
evaluation_date), renders the expanded bullets, and builds the canonical
follow-up LLM context payload from the template's own allowed_conclusion_
template / forbidden_conclusions / source_tables.
"""

from app.core.config import settings
from app.insights.models import FollowUpAction, FollowUpPayload, InsightCard
from app.insights.templates import TEMPLATE_REGISTRY, InsightTemplate, variant_index


def _active_rule_version_id(variables: dict) -> str:
    return str(variables.get("rule_version_id") or settings.rule_version or "")


def render_insight_template(
    template_id: str,
    variables: dict,
    severity_override: str | None = None,
) -> InsightCard | None:
    tmpl = TEMPLATE_REGISTRY.get(template_id)
    if tmpl is None:
        return None

    # New-style (compact_variants) templates are the only ones this renderer
    # fills — old-style (headline_template/body_template) definitions that
    # haven't been migrated yet are simply not renderable via this path.
    if not tmpl.compact_variants:
        return None

    idx = variant_index(variables, n=len(tmpl.compact_variants))
    try:
        compact_text = tmpl.compact_variants[idx].format_map(variables)
        bullets = [b.format_map(variables) for b in tmpl.expanded_bullets]
    except (KeyError, ValueError):
        if tmpl.fallback_template_id:
            return render_insight_template(tmpl.fallback_template_id, variables)
        return None

    severity = severity_override or tmpl.severity
    chips = {k: variables[k] for k in tmpl.chip_keys if k in variables}
    follow_ups = _build_follow_ups(tmpl, variables)

    return InsightCard(
        template_id=template_id,
        insight_code=tmpl.insight_code,
        severity=severity,
        priority=tmpl.priority,
        compact_text=compact_text,
        expanded_bullets=bullets,
        chips=chips,
        facts_json=variables,
        generated_by="deterministic_template",
        prompt_tokens=0,
        follow_up_actions=follow_ups,
    )


def build_followup_payload(tmpl: InsightTemplate, variables: dict) -> FollowUpPayload:
    """Canonical follow-up LLM context payload (see models.FollowUpPayload)."""
    entity_id = str(
        variables.get("entity_id")
        or variables.get("schemecode")
        or variables.get("scheme_id")
        or ""
    )
    entity_name = str(
        variables.get("entity_name")
        or variables.get("fund_name")
        or variables.get("leader_fund")
        or variables.get("category")
        or ""
    )
    try:
        allowed = tmpl.allowed_conclusion_template.format_map(variables)
    except (KeyError, ValueError):
        allowed = tmpl.allowed_conclusion_template

    return FollowUpPayload(
        page=tmpl.page_type,
        insight_code=tmpl.template_id,
        entity_id=entity_id,
        entity_name=entity_name,
        evaluation_date=str(variables.get("evaluation_date", "")),
        facts=variables,
        allowed_conclusion=allowed,
        forbidden_conclusions=tmpl.forbidden_conclusions,
        source_tables=tmpl.source_tables,
        rule_version_id=_active_rule_version_id(variables),
        data_version_id=str(settings.data_version),
        calculation_version_id=str(settings.calculation_version),
    )


def _build_follow_ups(tmpl: InsightTemplate, variables: dict) -> list[FollowUpAction]:
    if not tmpl.follow_up_label:
        return []
    payload = build_followup_payload(tmpl, variables)
    return [FollowUpAction(
        action_id=f"followup_{tmpl.template_id}",
        label=tmpl.follow_up_label,
        action_type="open_research_chat_with_context",
        llm_context_payload=payload,
    )]
