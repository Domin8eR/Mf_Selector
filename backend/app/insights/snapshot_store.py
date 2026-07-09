"""
Precomputed snapshot management for insight cards.
Stores rendered cards in selfmade_insight_snapshot for fast retrieval.
"""

import json
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.insights.models import InsightCard

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS selfmade_insight_snapshot (
    id BIGSERIAL PRIMARY KEY,
    page_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    category_id TEXT,
    comparison_key TEXT,
    evaluation_date DATE NOT NULL,
    insight_code TEXT NOT NULL,
    template_id TEXT NOT NULL,
    insight_priority INT DEFAULT 100,
    severity TEXT NOT NULL,
    headline TEXT NOT NULL,
    body_text TEXT NOT NULL,
    facts_json JSONB NOT NULL,
    source_tables TEXT[],
    assumptions TEXT[],
    generated_by TEXT NOT NULL DEFAULT 'deterministic_template',
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP,
    UNIQUE(page_type, entity_id, insight_code, evaluation_date)
);
"""


def ensure_table(db: Session) -> None:
    db.execute(text(CREATE_TABLE_SQL))
    db.commit()


def store_insights(
    db: Session,
    page_type: str,
    entity_id: str | None,
    category_id: str | None,
    evaluation_date: date,
    cards: list[InsightCard],
    comparison_key: str | None = None,
    expires_hours: int = 24,
) -> int:
    """Store rendered cards. Returns count of rows upserted."""
    expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
    count = 0

    for card in cards:
        db.execute(text("""
            INSERT INTO selfmade_insight_snapshot
                (page_type, entity_type, entity_id, category_id, comparison_key,
                 evaluation_date, insight_code, template_id, insight_priority,
                 severity, headline, body_text, facts_json,
                 source_tables, assumptions, generated_by,
                 prompt_tokens, completion_tokens, expires_at)
            VALUES
                (:page_type, :entity_type, :entity_id, :category_id, :comparison_key,
                 :evaluation_date, :insight_code, :template_id, :priority,
                 :severity, :headline, :body_text, CAST(:facts_json AS jsonb),
                 :source_tables, :assumptions, :generated_by,
                 :prompt_tokens, 0, :expires_at)
            ON CONFLICT (page_type, entity_id, insight_code, evaluation_date)
            DO UPDATE SET
                template_id = EXCLUDED.template_id,
                insight_priority = EXCLUDED.insight_priority,
                severity = EXCLUDED.severity,
                headline = EXCLUDED.headline,
                body_text = EXCLUDED.body_text,
                facts_json = EXCLUDED.facts_json,
                generated_by = EXCLUDED.generated_by,
                prompt_tokens = EXCLUDED.prompt_tokens,
                expires_at = EXCLUDED.expires_at,
                created_at = NOW()
        """), {
            "page_type": page_type,
            "entity_type": "fund" if page_type == "fund_detail" else page_type,
            "entity_id": entity_id or "",
            "category_id": category_id,
            "comparison_key": comparison_key,
            "evaluation_date": evaluation_date,
            "insight_code": card.insight_code,
            "template_id": card.template_id,
            "priority": card.priority,
            "severity": card.severity,
            "headline": card.headline,
            "body_text": card.body_text,
            "facts_json": json.dumps(card.facts_json, default=str),
            "source_tables": ["selfmade_scheme_ranking", "selfmade_scheme_metrics"],
            "assumptions": [
                "Static benchmark mapping used",
                "Static scheme name used",
                "Static category used",
            ],
            "generated_by": card.generated_by,
            "prompt_tokens": card.prompt_tokens,
            "expires_at": expires_at,
        })
        count += 1

    db.commit()
    return count


def get_cached_insights(
    db: Session,
    page_type: str,
    entity_id: str,
    evaluation_date: date,
) -> list[dict] | None:
    """Return cached cards if exists and not expired. None = cache miss."""
    rows = db.execute(text("""
        SELECT template_id, insight_code, severity, insight_priority,
               headline, body_text, facts_json, generated_by, prompt_tokens
        FROM selfmade_insight_snapshot
        WHERE page_type = :page_type
          AND entity_id = :entity_id
          AND evaluation_date = :eval_date
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY insight_priority ASC
    """), {
        "page_type": page_type,
        "entity_id": entity_id,
        "eval_date": evaluation_date,
    }).fetchall()

    if not rows:
        return None

    cards = []
    for r in rows:
        facts = r[6] if isinstance(r[6], dict) else json.loads(r[6]) if r[6] else {}
        cards.append({
            "template_id": r[0],
            "insight_code": r[1],
            "severity": r[2],
            "priority": r[3],
            "headline": r[4],
            "body_text": r[5],
            "facts_json": facts,
            "generated_by": r[7],
            "prompt_tokens": r[8] or 0,
            "follow_up_actions": [],
        })

    return cards


def invalidate_cache(db: Session, page_type: str, entity_id: str) -> None:
    db.execute(text("""
        DELETE FROM selfmade_insight_snapshot
        WHERE page_type = :page_type AND entity_id = :entity_id
    """), {"page_type": page_type, "entity_id": entity_id})
    db.commit()
