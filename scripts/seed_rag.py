"""
Seed synthetic document chunks and OpenAI embeddings for the top-30 ranked
funds per category (90 funds × ~3 chunks = ~270 chunks).

Run once:
  cd backend && python ../scripts/seed_rag.py

Requires OPENAI_API_KEY in backend/.env.
Uses selfmade_document (already seeded with 1419 rows) as the FK parent.
"""

from __future__ import annotations

import os
import sys
import time

# Allow running from project root or scripts/ folder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.db import SessionLocal
from app.core.config import settings

CATEGORIES = ["Equity — Large Cap", "Equity — Mid Cap", "Equity — Small Cap"]
FUNDS_PER_CATEGORY = 30
CHUNK_SIZE_APPROX = 400  # characters per chunk


def _top_funds(db, category: str, n: int) -> list[dict]:
    from sqlalchemy import text
    rows = db.execute(
        text(
            "SELECT schemecode, fund_name, rank_in_category, composite_score_v2, "
            "       information_ratio_3yr, snapshot_date "
            "FROM selfmade_ranking_snapshot "
            "WHERE category = :cat "
            "  AND snapshot_date = (SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot "
            "                       WHERE category = :cat) "
            "ORDER BY rank_in_category LIMIT :n"
        ),
        {"cat": category, "n": n},
    ).fetchall()
    return [
        {
            "schemecode": r[0],
            "fund_name": r[1],
            "rank": r[2],
            "score": float(r[3]) if r[3] else None,
            "ir_3yr": float(r[4]) if r[4] else None,
            "snapshot_date": str(r[5]),
        }
        for r in rows
    ]


def _get_metrics(db, schemecode: int) -> dict:
    from sqlalchemy import text
    m = db.execute(
        text(
            "SELECT information_ratio_3yr, sharpe_ratio_3yr, jensens_alpha_3yr, "
            "       sortino_ratio_3yr, tracking_error_3yr, ir_slope_6m_proxy, "
            "       outperformed_1yr, outperformed_3yr, outperformed_5yr, "
            "       benchmark_index, as_of_date "
            "FROM selfmade_scheme_metrics WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()
    ret = db.execute(
        text(
            "SELECT fund_1yr_ret, fund_3yr_ret, fund_5yr_ret, "
            "       active_1yr_ret, active_3yr_ret "
            "FROM selfmade_scheme_returns WHERE schemecode = :sc"
        ),
        {"sc": schemecode},
    ).fetchone()
    return {
        "ir_3yr": float(m[0]) if m and m[0] else None,
        "sharpe": float(m[1]) if m and m[1] else None,
        "alpha": float(m[2]) if m and m[2] else None,
        "sortino": float(m[3]) if m and m[3] else None,
        "tracking_error": float(m[4]) if m and m[4] else None,
        "ir_slope": float(m[5]) if m and m[5] else None,
        "outperformed_3yr": bool(m[7]) if m and m[7] is not None else None,
        "benchmark": m[9] if m else "Nifty 50",
        "as_of_date": str(m[10]) if m and m[10] else "N/A",
        "fund_1yr": float(ret[0]) if ret and ret[0] else None,
        "fund_3yr": float(ret[1]) if ret and ret[1] else None,
        "fund_5yr": float(ret[2]) if ret and ret[2] else None,
        "active_3yr": float(ret[4]) if ret and ret[4] else None,
    }


def _synthetic_chunks(fund: dict, metrics: dict, category: str) -> list[str]:
    name = fund["fund_name"]
    rank = fund["rank"]
    score = f"{fund['score']:.2f}" if fund["score"] else "N/A"
    bm = metrics.get("benchmark") or "benchmark index"
    date = metrics.get("as_of_date", "N/A")

    ir = f"{metrics['ir_3yr']:.3f}" if metrics.get("ir_3yr") is not None else "N/A"
    sharpe = f"{metrics['sharpe']:.3f}" if metrics.get("sharpe") is not None else "N/A"
    alpha = f"{metrics['alpha']:.3f}" if metrics.get("alpha") is not None else "N/A"
    slope = f"{metrics['ir_slope']:.4f}" if metrics.get("ir_slope") is not None else "N/A"
    ret3y = f"{metrics['fund_3yr']:.2f}%" if metrics.get("fund_3yr") is not None else "N/A"
    ret5y = f"{metrics['fund_5yr']:.2f}%" if metrics.get("fund_5yr") is not None else "N/A"
    active3y = f"{metrics['active_3yr']:.2f}%" if metrics.get("active_3yr") is not None else "N/A"
    op3 = ("outperformed" if metrics.get("outperformed_3yr") else "underperformed") if metrics.get("outperformed_3yr") is not None else "data unavailable"

    chunk1 = (
        f"Fund: {name}. Category: {category}. "
        f"This fund is ranked #{rank} in its category with a composite score of {score} "
        f"(as of {fund['snapshot_date']}). "
        f"The fund tracks {bm} as its benchmark and aims to generate risk-adjusted excess returns "
        f"through active portfolio management in the {category.lower()} segment. "
        f"As of {date}, the fund has {op3} its benchmark index on a 3-year rolling basis. "
        f"3-year fund return: {ret3y}. 5-year fund return: {ret5y}. "
        f"Active return (3Y vs benchmark): {active3y}. "
    )

    chunk2 = (
        f"Quantitative metrics for {name} (as of {date}): "
        f"Information Ratio (3Y): {ir} — a measure of risk-adjusted active return per unit of tracking risk. "
        f"Sharpe Ratio (3Y): {sharpe} — total risk-adjusted return relative to the risk-free rate. "
        f"Jensen's Alpha (3Y): {alpha} — excess return beyond what CAPM predicts given beta risk. "
        f"Sortino Ratio (3Y): {metrics.get('sortino', 'N/A')} — downside-risk-adjusted return. "
        f"Tracking Error (3Y): {metrics.get('tracking_error', 'N/A')}% — annualised standard deviation of active returns. "
        f"IR Slope (6M proxy): {slope} — direction of change in rolling information ratio; positive indicates structural improvement. "
        f"All values sourced from AltStreet internal validated tables (selfmade_scheme_metrics)."
    )

    chunk3 = (
        f"Investment mandate and strategy note for {name} ({category}): "
        f"The fund operates within the {category} universe as defined by SEBI categorisation. "
        f"Portfolio construction emphasises bottom-up stock selection with benchmark-relative "
        f"risk management. The fund is expected to maintain sufficient diversification to limit "
        f"unsystematic risk while seeking alpha generation through active weight deviations. "
        f"Risk disclosures: equity funds are subject to market risk, liquidity risk, and "
        f"concentration risk. Past performance is not indicative of future results. "
        f"This note is derived from publicly available scheme information and AltStreet "
        f"quantitative research. It is a research summary, not an investment recommendation. "
        f"Source: AltStreet selfmade_document (synthetic_seed_content)."
    )

    return [chunk1, chunk2, chunk3]


def _ensure_document(db, schemecode: int, date_str: str) -> int:
    """Return the selfmade_document.id for this fund, creating one if needed."""
    from sqlalchemy import text
    existing = db.execute(
        text(
            "SELECT id FROM selfmade_document "
            "WHERE scheme_id = :sc AND doc_type = 'factsheet' AND as_of_date = :d"
        ),
        {"sc": schemecode, "d": date_str},
    ).fetchone()
    if existing:
        return existing[0]
    # Insert a synthetic doc row
    row = db.execute(
        text(
            "INSERT INTO selfmade_document (scheme_id, doc_type, as_of_date, file_url, extraction_status) "
            "VALUES (:sc, 'factsheet', :d, 'synthetic://seed', 'extracted') "
            "ON CONFLICT (scheme_id, doc_type, as_of_date) DO UPDATE SET extraction_status='extracted' "
            "RETURNING id"
        ),
        {"sc": schemecode, "d": date_str},
    ).fetchone()
    db.flush()
    return row[0]


def _embed(texts: list[str], client) -> list[list[float]]:
    resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [d.embedding for d in resp.data]


def main() -> None:
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set in backend/.env — aborting.")
        sys.exit(1)

    import openai
    client = openai.OpenAI(api_key=settings.openai_api_key)

    db = SessionLocal()
    total_chunks = 0
    total_embeddings = 0

    try:
        for category in CATEGORIES:
            funds = _top_funds(db, category, FUNDS_PER_CATEGORY)
            print(f"\n{category}: {len(funds)} funds to seed")

            for fund in funds:
                sc = fund["schemecode"]
                metrics = _get_metrics(db, sc)
                snap_date = fund["snapshot_date"]

                doc_id = _ensure_document(db, sc, snap_date)
                chunks = _synthetic_chunks(fund, metrics, category)

                chunk_ids: list[int] = []
                for idx, text_content in enumerate(chunks):
                    from sqlalchemy import text as sqltext
                    # Upsert chunk (skip if already exists)
                    existing = db.execute(
                        sqltext(
                            "SELECT id FROM selfmade_document_chunk "
                            "WHERE document_id = :did AND chunk_index = :idx"
                        ),
                        {"did": doc_id, "idx": idx},
                    ).fetchone()

                    if existing:
                        chunk_ids.append(existing[0])
                    else:
                        row = db.execute(
                            sqltext(
                                "INSERT INTO selfmade_document_chunk "
                                "(document_id, chunk_index, chunk_text, char_start, char_end, extraction_status) "
                                "VALUES (:did, :idx, :txt, 0, :cend, 'synthetic_seed_content') "
                                "RETURNING id"
                            ),
                            {
                                "did": doc_id,
                                "idx": idx,
                                "txt": text_content,
                                "cend": len(text_content),
                            },
                        ).fetchone()
                        db.flush()
                        chunk_ids.append(row[0])
                        total_chunks += 1

                # Embed chunks that don't already have embeddings
                chunks_to_embed = []
                chunk_ids_to_embed = []
                for cid, chunk_text in zip(chunk_ids, chunks):
                    exists = db.execute(
                        sqltext(
                            "SELECT 1 FROM selfmade_document_embedding WHERE chunk_id = :cid"
                        ),
                        {"cid": cid},
                    ).fetchone()
                    if not exists:
                        chunks_to_embed.append(chunk_text)
                        chunk_ids_to_embed.append(cid)

                if chunks_to_embed:
                    try:
                        vectors = _embed(chunks_to_embed, client)
                        import json
                        for cid, vec in zip(chunk_ids_to_embed, vectors):
                            db.execute(
                                sqltext(
                                    "INSERT INTO selfmade_document_embedding "
                                    "(chunk_id, embedding, model_name) "
                                    "VALUES (:cid, CAST(:emb AS jsonb), 'text-embedding-3-small')"
                                ),
                                {"cid": cid, "emb": json.dumps(vec)},
                            )
                            total_embeddings += 1
                        db.flush()
                        time.sleep(0.05)  # rate-limit courtesy pause
                    except Exception as e:
                        db.rollback()  # clear aborted txn before continuing
                        print(f"  WARNING: embedding failed for sc={sc}: {e}")

                print(f"  #{fund['rank']:3d} {fund['fund_name'][:55]:<55} chunks={len(chunks)} embeds={len(chunks_to_embed)}")

        db.commit()
        print(f"\nDone. Inserted {total_chunks} new chunks, {total_embeddings} new embeddings.")

    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
