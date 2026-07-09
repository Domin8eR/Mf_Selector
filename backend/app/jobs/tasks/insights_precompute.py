"""
Daily precompute task for insight snapshots.

Scheduled after market close (default 18:30 IST).
Refreshes ranking data then precomputes insights for all pages.
"""

from datetime import date

from app.core.db import SessionLocal
from app.insights.renderer import render_insight_template
from app.insights.rules import InsightRuleEngine
from app.insights.snapshot_store import ensure_table, store_insights
from app.jobs.celery_app import celery_app


def _render_triggered(triggered: list[dict]):
    from app.insights.models import InsightCard
    cards = []
    for t in triggered:
        card = render_insight_template(
            t["template_id"], t["variables"],
            severity_override=t.get("severity_override"),
        )
        if card:
            cards.append(card)
    cards.sort(key=lambda c: c.priority)
    return cards


@celery_app.task(name="tasks.precompute_daily_insights", bind=True)
def precompute_daily_insights(self, evaluation_date_iso: str | None = None):
    eval_date = (
        date.fromisoformat(evaluation_date_iso)
        if evaluation_date_iso
        else date.today()
    )

    db = SessionLocal()
    try:
        ensure_table(db)
        engine = InsightRuleEngine(db)
        summary: dict[str, int] = {}

        # 1. Workspace daily briefing
        ws_count = 0
        for cat in ["Equity — Large Cap", "Equity — Mid Cap", "Equity — Small Cap"]:
            triggered = engine.evaluate_workspace_daily_briefing(cat, eval_date)
            cards = _render_triggered(triggered)
            if cards:
                ws_count += store_insights(db, "workspace", cat, cat, eval_date, cards)
        summary["workspace"] = ws_count

        # 2. Category ranking insights
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

        # 3. Fund detail insights
        schemes = db.execute(text(
            "SELECT schemecode FROM selfmade_scheme_ranking ORDER BY schemecode"
        )).fetchall()

        fund_count = 0
        for i, (sc,) in enumerate(schemes):
            triggered = engine.evaluate_fund_detail_insights(sc, eval_date)
            cards = _render_triggered(triggered)
            if cards:
                fund_count += store_insights(
                    db, "fund_detail", str(sc), None, eval_date, cards,
                )
            if (i + 1) % 500 == 0:
                print(f"  Fund insights: {i + 1}/{len(schemes)} ...")

        summary["fund_detail"] = fund_count

        # 4. Log summary
        try:
            db.execute(text("""
                INSERT INTO etl_run_log (table_name, rows_inserted, run_date)
                VALUES ('selfmade_insight_snapshot', :rows, :run_date)
            """), {
                "rows": sum(summary.values()),
                "run_date": eval_date,
            })
            db.commit()
        except Exception:
            db.rollback()

        return summary
    finally:
        db.close()
