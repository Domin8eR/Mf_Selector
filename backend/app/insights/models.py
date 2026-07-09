"""Pydantic models for the Insights Engine."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class FollowUpAction(BaseModel):
    action_id: str
    label: str
    action_type: str
    llm_context_payload: dict | None = None


class InsightCard(BaseModel):
    template_id: str
    insight_code: str
    severity: str = Field(description="positive | warning | neutral | negative")
    priority: int = 100
    headline: str
    body_text: str
    facts_json: dict = Field(default_factory=dict)
    generated_by: str = "deterministic_template"
    prompt_tokens: int = 0
    follow_up_actions: list[FollowUpAction] = Field(default_factory=list)


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
