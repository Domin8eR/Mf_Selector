"""Pydantic models for the Insights Engine."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class FollowUpPayload(BaseModel):
    """Canonical follow-up LLM context payload (2026-07-18 migration).

    Passed verbatim to Research Chat when a user clicks a follow-up action
    on an insight card — the LLM must not rediscover these facts, and per
    the LLM rule, must not contradict allowed_conclusion.
    """
    page: str
    insight_code: str
    entity_id: str = ""
    entity_name: str = ""
    evaluation_date: str = ""
    facts: dict = Field(default_factory=dict)
    allowed_conclusion: str = ""
    forbidden_conclusions: list[str] = Field(default_factory=list)
    source_tables: list[str] = Field(default_factory=list)
    rule_version_id: str = ""
    data_version_id: str = ""
    calculation_version_id: str = ""


class FollowUpAction(BaseModel):
    action_id: str
    label: str
    action_type: str
    llm_context_payload: FollowUpPayload | None = None


class InsightCard(BaseModel):
    template_id: str
    insight_code: str
    severity: str = Field(description="positive | warning | neutral | negative")
    priority: int = 100
    compact_text: str
    expanded_bullets: list[str] = Field(default_factory=list)
    chips: dict = Field(default_factory=dict)
    facts_json: dict = Field(default_factory=dict)
    generated_by: str = "deterministic_template"
    prompt_tokens: int = 0
    follow_up_actions: list[FollowUpAction] = Field(default_factory=list)
    # Deprecated aliases kept during the compact-card migration so any
    # not-yet-updated caller reading .headline/.body_text doesn't crash —
    # new code should use compact_text/expanded_bullets.
    @property
    def headline(self) -> str:
        return self.compact_text

    @property
    def body_text(self) -> str:
        return "\n".join(self.expanded_bullets)


class InsightResponse(BaseModel):
    cards: list[InsightCard]
    evaluation_date: date
    poc_mode: bool = True
    assumptions: list[str] = Field(default_factory=lambda: [
        "Static benchmark mapping used",
        "Static scheme name used",
        "Static category used",
    ])
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    rule_version: str = "unknown"


class ChatContextPayloadRequest(BaseModel):
    source_insight_id: str
    selected_entities: dict = Field(default_factory=dict)
    facts_json: dict = Field(default_factory=dict)
    evaluation_date: date


class ChatContextPayloadResponse(BaseModel):
    source_page: str
    source_insight_id: str
    selected_entities: dict
    evaluation_date: date
    facts_json: dict
    allowed_conclusion: str
    forbidden_phrases: list[str] = Field(default_factory=lambda: [
        "buy", "sell", "switch", "recommend",
        "best investment", "guaranteed", "personalized",
    ])


class PrecomputeRequest(BaseModel):
    evaluation_date: date


class PrecomputeResponse(BaseModel):
    summary: dict
    evaluation_date: date


class CompareRequest(BaseModel):
    schemecodes: list[int] = Field(max_length=4)
    evaluation_date: date


class RulePlaygroundRequest(BaseModel):
    weights: dict
    sandbox_results: list
    current_top10: list
