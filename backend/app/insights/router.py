"""
Insights Engine API router.

All endpoints return deterministic template-based insights.
No LLM calls for page insight cards (ENABLE_LLM_PAGE_INSIGHT_POLISH = False).
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.insights.models import (
    ChatContextPayloadRequest,
    ChatContextPayloadResponse,
    CompareRequest,
    InsightCard,
    InsightResponse,
    PrecomputeRequest,
    PrecomputeResponse,
    RulePlaygroundRequest,
)
from app.insights.renderer import render_insight_template
from app.insights.rules import InsightRuleEngine
from app.insights.snapshot_store import (
    ensure_table,
    get_cached_insights,
    store_insights,
)

router = APIRouter(prefix="/insights", tags=["insights"])


def _active_rule_version(db: Session) -> str:
    """Return version_label of the currently active selfmade_rule_version."""
    try:
        row = db.execute(text(
            "SELECT version_label FROM selfmade_rule_version WHERE is_active = true ORDER BY id DESC LIMIT 1"
        )).fetchone()
        return row[0] if row else "unknown"
    except Exception:
        return "unknown"


POC_ASSUMPTIONS = [
    "Static benchmark mapping used",
    "Static scheme name used",
    "Static category used",
]


def _render_triggered(triggered: list[dict]) -> list[InsightCard]:
    cards = []
    for t in triggered:
        card = render_insight_template(
            t["template_id"],
            t["variables"],
            severity_override=t.get("severity_override"),
        )
        if card:
            cards.append(card)
    cards.sort(key=lambda c: c.priority)
    return cards


@router.get("/workspace/daily-briefing", response_model=InsightResponse)
def workspace_daily_briefing(
    evaluation_date: date = Query(default=None),
    db: Session = Depends(get_db),
):
    eval_date = evaluation_date or date.today()
    ensure_table(db)

    categories = ["Equity — Large Cap", "Equity — Mid Cap", "Equity — Small Cap"]
    all_cards: list[InsightCard] = []
    total_improvers = 0

    for cat in categories:
        cached = get_cached_insights(db, "workspace", cat, eval_date)
        if cached:
            cat_cards = [InsightCard(**c) for c in cached]
            all_cards.extend(cat_cards)
            total_improvers += sum(
                1 for c in cat_cards
                if c.template_id == "AIW_RANK_IMPROVERS_COUNT_POSITIVE_V1"
                and c.facts_json.get("count", 0) > 0
            )
            continue

        engine = InsightRuleEngine(db)
        triggered = engine.generate_workspace_daily_briefing_insights(cat, eval_date)
        cards = _render_triggered(triggered)
        if cards:
            store_insights(db, "workspace", cat, cat, eval_date, cards)
        all_cards.extend(cards)
        # Count improvers from this category
        for t in triggered:
            if t["template_id"] == "AIW_RANK_IMPROVERS_COUNT_POSITIVE_V1":
                total_improvers += t["variables"].get("count", 0)

    # ── Append cross-category daily summary (AIW_DAILY_BRIEFING_SUMMARY_V1) ──
    if total_improvers > 0:
        summary_detail = (
            f"Most active category had {total_improvers} qualifying fund(s)"
        )
    else:
        summary_detail = (
            "No funds crossed the structural improvement threshold today"
        )

    summary_triggered = [{
        "template_id": "AIW_DAILY_BRIEFING_SUMMARY_V1",
        "variables": {
            "evaluation_date": str(eval_date),
            "category_count": len(categories),
            "total_improvers": total_improvers,
            "summary_detail": summary_detail,
        },
    }]
    summary_cards = _render_triggered(summary_triggered)
    all_cards.extend(summary_cards)

    return InsightResponse(
        cards=all_cards,
        evaluation_date=eval_date,
        poc_mode=True,
        assumptions=POC_ASSUMPTIONS,
        generated_at=datetime.utcnow(),
        rule_version=_active_rule_version(db),
    )


@router.get("/category-rankings", response_model=InsightResponse)
def category_ranking_insights(
    category: str = Query(...),
    evaluation_date: date = Query(default=None),
    db: Session = Depends(get_db),
):
    eval_date = evaluation_date or date.today()
    ensure_table(db)

    cached = get_cached_insights(db, "category_rankings", category, eval_date)
    if cached:
        return InsightResponse(
            cards=[InsightCard(**c) for c in cached],
            evaluation_date=eval_date,
            poc_mode=True,
            assumptions=POC_ASSUMPTIONS,
            generated_at=datetime.utcnow(),
        )

    engine = InsightRuleEngine(db)
    triggered = engine.evaluate_category_ranking_insights(category, eval_date)
    cards = _render_triggered(triggered)

    if cards:
        store_insights(db, "category_rankings", category, category, eval_date, cards)

    return InsightResponse(
        cards=cards[:5],
        evaluation_date=eval_date,
        poc_mode=True,
        assumptions=POC_ASSUMPTIONS,
        generated_at=datetime.utcnow(),
    )


@router.get("/fund/{schemecode}", response_model=InsightResponse)
def fund_detail_insights(
    schemecode: int,
    evaluation_date: date = Query(default=None),
    db: Session = Depends(get_db),
):
    eval_date = evaluation_date or date.today()
    ensure_table(db)

    entity_id = str(schemecode)
    cached = get_cached_insights(db, "fund_detail", entity_id, eval_date)
    if cached:
        return InsightResponse(
            cards=[InsightCard(**c) for c in cached],
            evaluation_date=eval_date,
            poc_mode=True,
            assumptions=POC_ASSUMPTIONS,
            generated_at=datetime.utcnow(),
        )

    engine = InsightRuleEngine(db)
    triggered = engine.evaluate_fund_detail_insights(schemecode, eval_date)
    cards = _render_triggered(triggered)

    if cards:
        store_insights(db, "fund_detail", entity_id, None, eval_date, cards)

    return InsightResponse(
        cards=cards,
        evaluation_date=eval_date,
        poc_mode=True,
        assumptions=POC_ASSUMPTIONS,
        generated_at=datetime.utcnow(),
    )


@router.post("/compare-funds", response_model=InsightResponse)
def compare_funds_insights(
    body: CompareRequest,
    db: Session = Depends(get_db),
):
    eval_date = body.evaluation_date or date.today()
    ensure_table(db)

    sorted_codes = sorted(body.schemecodes)
    comparison_key = "_".join(str(s) for s in sorted_codes)

    cached = get_cached_insights(db, "fund_comparison", comparison_key, eval_date)
    if cached:
        return InsightResponse(
            cards=[InsightCard(**c) for c in cached],
            evaluation_date=eval_date,
            poc_mode=True,
            assumptions=POC_ASSUMPTIONS,
            generated_at=datetime.utcnow(),
        )

    engine = InsightRuleEngine(db)
    triggered = engine.evaluate_fund_comparison_insights(body.schemecodes, eval_date)
    cards = _render_triggered(triggered)

    if cards:
        store_insights(
            db, "fund_comparison", comparison_key, None, eval_date, cards,
            comparison_key=comparison_key,
        )

    return InsightResponse(
        cards=cards,
        evaluation_date=eval_date,
        poc_mode=True,
        assumptions=POC_ASSUMPTIONS,
        generated_at=datetime.utcnow(),
    )


@router.post("/rule-playground", response_model=InsightResponse)
def rule_playground_insights(
    body: RulePlaygroundRequest,
    db: Session = Depends(get_db),
):
    engine = InsightRuleEngine(db)
    triggered = engine.evaluate_rule_playground_insights(
        body.weights, body.sandbox_results, body.current_top10,
    )
    cards = _render_triggered(triggered)

    return InsightResponse(
        cards=cards,
        evaluation_date=date.today(),
        poc_mode=True,
        assumptions=POC_ASSUMPTIONS,
        generated_at=datetime.utcnow(),
    )


@router.post("/precompute-daily", response_model=PrecomputeResponse)
def precompute_daily(
    body: PrecomputeRequest,
    db: Session = Depends(get_db),
):
    eval_date = body.evaluation_date
    ensure_table(db)
    engine = InsightRuleEngine(db)
    summary: dict[str, int] = {}

    # Workspace briefing
    ws_count = 0
    for cat in ["Equity — Large Cap", "Equity — Mid Cap", "Equity — Small Cap"]:
        triggered = engine.evaluate_workspace_daily_briefing(cat, eval_date)
        cards = _render_triggered(triggered)
        if cards:
            ws_count += store_insights(db, "workspace", cat, cat, eval_date, cards)
    summary["workspace"] = ws_count

    # Category rankings
    from sqlalchemy import text
    cats = db.execute(text(
        "SELECT DISTINCT category FROM selfmade_scheme_category_benchmark ORDER BY category"
    )).fetchall()

    cat_count = 0
    for (cat_name,) in cats:
        triggered = engine.evaluate_category_ranking_insights(cat_name, eval_date)
        cards = _render_triggered(triggered)
        if cards:
            cat_count += store_insights(
                db, "category_rankings", cat_name, cat_name, eval_date, cards,
            )
    summary["category_rankings"] = cat_count

    # Fund detail
    schemes = db.execute(text(
        "SELECT schemecode FROM selfmade_scheme_ranking ORDER BY schemecode"
    )).fetchall()

    fund_count = 0
    for (sc,) in schemes:
        triggered = engine.evaluate_fund_detail_insights(sc, eval_date)
        cards = _render_triggered(triggered)
        if cards:
            fund_count += store_insights(
                db, "fund_detail", str(sc), None, eval_date, cards,
            )
    summary["fund_detail"] = fund_count

    return PrecomputeResponse(
        summary=summary,
        evaluation_date=eval_date,
    )


@router.post("/chat/context-payload", response_model=ChatContextPayloadResponse)
def chat_context_payload(
    body: ChatContextPayloadRequest,
):
    source_page = "unknown"
    if body.source_insight_id.startswith("AIW_"):
        source_page = "workspace"
    elif body.source_insight_id.startswith("CAT_"):
        source_page = "category_rankings"
    elif body.source_insight_id.startswith("FUND_"):
        source_page = "fund_detail"
    elif body.source_insight_id.startswith("CMP_"):
        source_page = "fund_comparison"
    elif body.source_insight_id.startswith("RULE_"):
        source_page = "rule_playground"

    allowed = ""
    facts = body.facts_json
    if "fund_name" in facts:
        allowed = (
            f"The user is exploring data about {facts['fund_name']}. "
            "Provide factual analysis based on the pre-computed metrics. "
            "Do not provide investment advice."
        )
    elif "category" in facts:
        allowed = (
            f"The user is exploring the {facts['category']} category. "
            "Provide factual analysis based on the pre-computed rankings. "
            "Do not provide investment advice."
        )
    else:
        allowed = (
            "Provide factual analysis based on the pre-computed metrics. "
            "Do not provide investment advice."
        )

    return ChatContextPayloadResponse(
        source_page=source_page,
        source_insight_id=body.source_insight_id,
        selected_entities=body.selected_entities,
        evaluation_date=body.evaluation_date,
        facts_json=body.facts_json,
        allowed_conclusion=allowed,
        forbidden_phrases=[
            "buy", "sell", "switch", "recommend",
            "best investment", "guaranteed", "personalized",
        ],
    )


# ── GET /insights/rule-playground ────────────────────────────────────────────

from app.services.rule_playground_insights import (
    SandboxState as RuleSandboxState,
    SandboxComponent as RuleSandboxComponent,
    FormulaValidationStatus as RuleFormulaStatus,
    SandboxRunSummary as RuleSandboxRunSummary,
    generate_rule_playground_insights,
)
from pydantic import BaseModel as _BaseModel

class _FormulaStatusIn(_BaseModel):
    component_name: str
    valid: bool
    error_type: str | None = None
    error_message: str | None = None
    parsed_variables: list[str] = []
    sample_result: float | None = None

class _SandboxRunIn(_BaseModel):
    fund_count: int
    promoted: int
    dropped: int
    no_change: int
    top10_turnover_pct: float
    entering_top10: list[str] = []
    leaving_top10: list[str] = []
    beneficiary_name: str = ""
    beneficiary_default_rank: int = 0
    beneficiary_sandbox_rank: int = 0
    beneficiary_places: int = 0
    loser_name: str = ""
    loser_default_rank: int = 0
    loser_sandbox_rank: int = 0
    loser_places: int = 0
    category_shifts: dict[str, float] | None = None

class _RuleInsightsRequest(_BaseModel):
    components: list[dict]          # [{metric_column, weight_pct, formula_text?}]
    formula_validations: list[_FormulaStatusIn] = []
    sandbox_run: _SandboxRunIn | None = None
    rationale_present: bool = False
    category: str = "Equity — Large Cap"


@router.post("/rule-playground")
def rule_playground_insights(body: _RuleInsightsRequest) -> dict:
    """
    Generate deterministic RULE_*_V1 insight cards for the current sandbox editor state.
    No LLM calls — all 20 templates are evaluated from the submitted state.
    """
    sandbox_comps = [
        RuleSandboxComponent(
            metric_column=c.get("metric_column", ""),
            weight_pct=float(c.get("weight_pct", c.get("weight", 0))),
            formula_text=c.get("formula_text"),
        )
        for c in body.components
    ]

    formula_vals = [
        RuleFormulaStatus(
            component_name=fv.component_name,
            valid=fv.valid,
            error_type=fv.error_type,
            error_message=fv.error_message,
            parsed_variables=fv.parsed_variables,
            sample_result=fv.sample_result,
        )
        for fv in body.formula_validations
    ]

    run_summary: RuleSandboxRunSummary | None = None
    if body.sandbox_run:
        sr = body.sandbox_run
        # Derive beneficiary/loser from entering/leaving lists (lightweight heuristic)
        entering = sr.entering_top10 or []
        leaving  = sr.leaving_top10 or []
        run_summary = RuleSandboxRunSummary(
            fund_count=sr.fund_count,
            promoted=sr.promoted,
            dropped=sr.dropped,
            no_change=sr.no_change,
            top10_turnover_pct=sr.top10_turnover_pct,
            entering_funds=entering,
            leaving_funds=leaving,
            beneficiary_name=sr.beneficiary_name or (entering[0] if entering else ""),
            beneficiary_default_rank=sr.beneficiary_default_rank,
            beneficiary_sandbox_rank=sr.beneficiary_sandbox_rank,
            beneficiary_places=sr.beneficiary_places,
            loser_name=sr.loser_name or (leaving[0] if leaving else ""),
            loser_default_rank=sr.loser_default_rank,
            loser_sandbox_rank=sr.loser_sandbox_rank,
            loser_places=sr.loser_places,
            category_shifts=sr.category_shifts,
        )

    state = RuleSandboxState(
        components=sandbox_comps,
        formula_validations=formula_vals,
        sandbox_run=run_summary,
        rationale_present=body.rationale_present,
        category=body.category,
    )
    cards = generate_rule_playground_insights(state)
    return {"cards": cards, "total": len(cards)}
