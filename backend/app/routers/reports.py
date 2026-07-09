"""Reports Builder router — Section 9.9.

Endpoints:
  POST /reports/generate              — LLM exec summary + narratives + compliance check
  POST /compliance/check              — standalone compliance scan (reuses Research Chat guard)
  GET  /reports/recent                — last 20 reports
  GET  /reports/{id}                  — single report full detail
  POST /reports/{id}/export           — PDF + DOCX (gated on compliance pass)
  PATCH /reports/{id}/apply-compliance-fix — apply a suggested rewrite, recheck
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.reports.compliance import check_compliance
from app.reports.generator import generate_report_content
from app.reports.export import export_pdf, export_docx

reports_router = APIRouter(prefix="/reports", tags=["reports"])
compliance_router = APIRouter(prefix="/compliance", tags=["compliance"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ReportSections(BaseModel):
    exec_summary: bool = True
    top_funds: bool = True
    key_insights: bool = True
    methodology: bool = True


class GenerateReportRequest(BaseModel):
    category: str = "Equity — Large Cap"
    snapshot_date: str | None = None  # defaults to latest
    sections: ReportSections = Field(default_factory=ReportSections)
    title: str | None = None


class ComplianceCheckRequest(BaseModel):
    text: str


class ApplyFixRequest(BaseModel):
    phrase: str
    field: str  # "exec_summary" | "fund_narrative:{schemecode}" | "key_insight:{idx}"
    new_text: str


# ── Helper: fetch active rule version ─────────────────────────────────────────

def _active_rule(db: Session) -> dict[str, Any]:
    row = db.execute(text(
        "SELECT id, version_label FROM selfmade_rule_version "
        "WHERE is_active = true ORDER BY id DESC LIMIT 1"
    )).fetchone()
    if not row:
        return {"id": None, "label": "unknown"}
    return {"id": row[0], "label": row[1]}


def _rule_components(db: Session, rule_version_id: int) -> list[dict[str, Any]]:
    rows = db.execute(text(
        "SELECT component_name, metric_column, weight, direction, sort_order "
        "FROM selfmade_rule_component WHERE rule_version_id = :id ORDER BY sort_order"
    ), {"id": rule_version_id}).fetchall()
    return [
        {
            "component_name": r[0],
            "metric_column": r[1],
            "weight": float(r[2]),
            "direction": r[3],
            "sort_order": r[4],
        }
        for r in rows
    ]


def _top_funds(
    db: Session, category: str, snapshot_date: str, limit: int = 5
) -> list[dict[str, Any]]:
    rows = db.execute(text("""
        SELECT schemecode, fund_name, rank_in_category,
               composite_score_v2, information_ratio_3yr, sharpe_score, rank_delta_6m
        FROM selfmade_ranking_snapshot
        WHERE category = :cat AND snapshot_date = :dt
        ORDER BY rank_in_category
        LIMIT :lim
    """), {"cat": category, "dt": snapshot_date, "lim": limit}).fetchall()
    return [
        {
            "schemecode": r[0],
            "fund_name": r[1],
            "rank": r[2],
            "composite_score": float(r[3]) if r[3] is not None else 0.0,
            "information_ratio_3yr": float(r[4]) if r[4] is not None else 0.0,
            "sharpe_score": float(r[5]) if r[5] is not None else 0.0,
            "rank_delta_6m": r[6],
        }
        for r in rows
    ]


def _latest_snapshot_date(db: Session, category: str) -> str | None:
    row = db.execute(text(
        "SELECT MAX(snapshot_date) FROM selfmade_ranking_snapshot WHERE category = :cat"
    ), {"cat": category}).fetchone()
    if row and row[0]:
        return row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0])
    return None


def _row_to_report(r: Any, keys: list[str]) -> dict[str, Any]:
    d = dict(zip(keys, r))
    # Deserialize JSONB fields that come back as strings
    for field in ("sections", "fund_narratives", "key_insights", "compliance_result"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    if d.get("created_at") and hasattr(d["created_at"], "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    if d.get("updated_at") and hasattr(d["updated_at"], "isoformat"):
        d["updated_at"] = d["updated_at"].isoformat()
    if d.get("snapshot_date") and hasattr(d["snapshot_date"], "isoformat"):
        d["snapshot_date"] = d["snapshot_date"].isoformat()
    return d


_REPORT_COLS = """
    id, title, category, snapshot_date, rule_version_id,
    status, sections, exec_summary, fund_narratives, key_insights,
    compliance_result, export_pdf_path, export_docx_path, created_at, updated_at
"""
_REPORT_KEYS = [
    "id", "title", "category", "snapshot_date", "rule_version_id",
    "status", "sections", "exec_summary", "fund_narratives", "key_insights",
    "compliance_result", "export_pdf_path", "export_docx_path", "created_at", "updated_at",
]


# ── POST /reports/generate ────────────────────────────────────────────────────

@reports_router.post("/generate")
def generate_report(
    body: GenerateReportRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Generate a research report:
    1. Pull top-5 funds from ranking_snapshot for the given category/date.
    2. Get active rule version + components.
    3. Call LLM to write exec_summary, per-fund narratives, key insights.
    4. Immediately run compliance check on all generated text.
    5. Persist the report (status=draft or compliance_passed/failed) and return it.
    """
    rule = _active_rule(db)

    snapshot_date = body.snapshot_date or _latest_snapshot_date(db, body.category)
    if not snapshot_date:
        raise HTTPException(404, f"No ranking data found for category '{body.category}'.")

    funds = _top_funds(db, body.category, snapshot_date)
    if not funds:
        raise HTTPException(404, f"No funds found for '{body.category}' on {snapshot_date}.")

    components: list[dict[str, Any]] = []
    if rule["id"]:
        components = _rule_components(db, rule["id"])

    sections_dict = body.sections.model_dump()

    # LLM generation
    generated = generate_report_content(
        category=body.category,
        snapshot_date=snapshot_date,
        funds=funds,
        rule_components=components,
        sections=sections_dict,
    )

    exec_summary: str = generated.get("exec_summary", "")
    raw_narratives: list[dict] = generated.get("fund_narratives", [])
    key_insights: list[dict] = generated.get("key_insights", [])

    # Merge LLM narratives back into fund rows (keeps composite_score etc.)
    narrative_map = {str(n.get("schemecode", "")): n.get("narrative", "") for n in raw_narratives}
    fund_narratives = [
        {**f, "narrative": narrative_map.get(str(f["schemecode"]), "")}
        for f in funds
    ]

    # Compliance check — always runs, report saved regardless of result
    all_text = " ".join([
        exec_summary,
        " ".join(fn.get("narrative", "") for fn in fund_narratives),
        " ".join(f"{ki.get('heading', '')} {ki.get('body', '')}" for ki in key_insights),
    ])
    compliance_result = check_compliance(all_text)

    status = "compliance_passed" if compliance_result["pass"] else "compliance_failed"

    title = (
        body.title
        or f"{body.category} Research Report — {snapshot_date}"
    )

    row = db.execute(text("""
        INSERT INTO selfmade_report
            (title, category, snapshot_date, rule_version_id, status,
             sections, exec_summary, fund_narratives, key_insights, compliance_result)
        VALUES
            (:title, :category, :snapshot_date, :rule_version_id, :status,
             CAST(:sections AS jsonb), :exec_summary, CAST(:fund_narratives AS jsonb),
             CAST(:key_insights AS jsonb), CAST(:compliance_result AS jsonb))
        RETURNING id
    """), {
        "title": title,
        "category": body.category,
        "snapshot_date": snapshot_date,
        "rule_version_id": rule["id"],
        "status": status,
        "sections": json.dumps(sections_dict),
        "exec_summary": exec_summary,
        "fund_narratives": json.dumps(fund_narratives),
        "key_insights": json.dumps(key_insights),
        "compliance_result": json.dumps(compliance_result),
    }).fetchone()
    db.commit()

    report_id: int = row[0]

    full = db.execute(text(
        f"SELECT {_REPORT_COLS} FROM selfmade_report WHERE id = :id"
    ), {"id": report_id}).fetchone()
    result = _row_to_report(full, _REPORT_KEYS)
    result["rule_version_label"] = rule["label"]
    result["rule_components"] = components
    return result


# ── POST /compliance/check ────────────────────────────────────────────────────

@compliance_router.post("/check")
def compliance_check(body: ComplianceCheckRequest) -> dict:
    """
    Standalone compliance scan on arbitrary text.
    Reuses the exact same two-layer guard as Research Chat.
    """
    return check_compliance(body.text)


# ── GET /reports/recent ───────────────────────────────────────────────────────

@reports_router.get("/recent")
def recent_reports(db: Session = Depends(get_db)) -> dict:
    """Return the 20 most-recently created reports."""
    rows = db.execute(text(
        f"SELECT {_REPORT_COLS} FROM selfmade_report ORDER BY created_at DESC LIMIT 20"
    )).fetchall()
    return {
        "reports": [_row_to_report(r, _REPORT_KEYS) for r in rows],
        "total": len(rows),
    }


# ── GET /reports/{id} ─────────────────────────────────────────────────────────

@reports_router.get("/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    """Return a single report with full detail."""
    row = db.execute(text(
        f"SELECT {_REPORT_COLS} FROM selfmade_report WHERE id = :id"
    ), {"id": report_id}).fetchone()
    if not row:
        raise HTTPException(404, f"Report {report_id} not found.")
    result = _row_to_report(row, _REPORT_KEYS)

    # Attach rule version label if available
    if result.get("rule_version_id"):
        rv = db.execute(text(
            "SELECT version_label FROM selfmade_rule_version WHERE id = :id"
        ), {"id": result["rule_version_id"]}).fetchone()
        result["rule_version_label"] = rv[0] if rv else "unknown"
    else:
        result["rule_version_label"] = "unknown"

    return result


# ── POST /reports/{id}/export ─────────────────────────────────────────────────

@reports_router.post("/{report_id}/export")
def export_report(
    report_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """
    Generate and persist PDF + DOCX exports.
    GATED: compliance_result.pass must be True.
    Returns {pdf_path, docx_path} on success.
    """
    row = db.execute(text(
        f"SELECT {_REPORT_COLS} FROM selfmade_report WHERE id = :id"
    ), {"id": report_id}).fetchone()
    if not row:
        raise HTTPException(404, f"Report {report_id} not found.")

    report = _row_to_report(row, _REPORT_KEYS)

    compliance: dict = report.get("compliance_result") or {}
    if not compliance.get("pass", False):
        raise HTTPException(
            400,
            {
                "detail": "Export is blocked: compliance check has not passed.",
                "flagged_phrases": compliance.get("flagged_phrases", []),
                "suggested_rewrites": compliance.get("suggested_rewrites", []),
            },
        )

    # Attach rule label for cover page
    if report.get("rule_version_id"):
        rv = db.execute(text(
            "SELECT version_label FROM selfmade_rule_version WHERE id = :id"
        ), {"id": report["rule_version_id"]}).fetchone()
        report["rule_version_label"] = rv[0] if rv else "unknown"
    else:
        report["rule_version_label"] = "unknown"

    pdf_path = export_pdf(report)
    docx_path = export_docx(report)

    db.execute(text("""
        UPDATE selfmade_report
        SET status = 'exported',
            export_pdf_path = :pdf,
            export_docx_path = :docx,
            updated_at = NOW()
        WHERE id = :id
    """), {"pdf": pdf_path, "docx": docx_path, "id": report_id})
    db.commit()

    return {
        "report_id": report_id,
        "pdf_path": pdf_path,
        "docx_path": docx_path,
        "status": "exported",
    }


# ── PATCH /reports/{id}/apply-compliance-fix ──────────────────────────────────

@reports_router.patch("/{report_id}/apply-compliance-fix")
def apply_compliance_fix(
    report_id: int,
    body: ApplyFixRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Apply a suggested compliance rewrite to a specific field, then recheck compliance.

    `field` values:
      "exec_summary"              — replace phrase in exec_summary
      "fund_narrative:{schemecode}" — replace phrase in that fund's narrative
      "key_insight:{idx}"         — replace phrase in key_insights[idx].body
    """
    row = db.execute(text(
        f"SELECT {_REPORT_COLS} FROM selfmade_report WHERE id = :id"
    ), {"id": report_id}).fetchone()
    if not row:
        raise HTTPException(404, f"Report {report_id} not found.")

    report = _row_to_report(row, _REPORT_KEYS)

    field = body.field
    phrase = body.phrase
    new_text = body.new_text

    if field == "exec_summary":
        old = report.get("exec_summary", "") or ""
        report["exec_summary"] = old.replace(phrase, new_text, 1)
    elif field.startswith("fund_narrative:"):
        schemecode = field.split(":", 1)[1]
        narratives: list[dict] = report.get("fund_narratives", [])
        for fn in narratives:
            if str(fn.get("schemecode", "")) == schemecode:
                fn["narrative"] = (fn.get("narrative", "") or "").replace(phrase, new_text, 1)
        report["fund_narratives"] = narratives
    elif field.startswith("key_insight:"):
        idx = int(field.split(":", 1)[1])
        insights: list[dict] = report.get("key_insights", [])
        if 0 <= idx < len(insights):
            insights[idx]["body"] = (insights[idx].get("body", "") or "").replace(phrase, new_text, 1)
        report["key_insights"] = insights
    else:
        raise HTTPException(400, f"Unknown field '{field}'.")

    # Rerun compliance on full text
    all_text = " ".join([
        report.get("exec_summary", "") or "",
        " ".join(fn.get("narrative", "") or "" for fn in report.get("fund_narratives", [])),
        " ".join(
            f"{ki.get('heading', '')} {ki.get('body', '')}"
            for ki in report.get("key_insights", [])
        ),
    ])
    new_compliance = check_compliance(all_text)
    new_status = "compliance_passed" if new_compliance["pass"] else "compliance_failed"

    db.execute(text("""
        UPDATE selfmade_report
        SET exec_summary      = :exec_summary,
            fund_narratives   = CAST(:fund_narratives AS jsonb),
            key_insights      = CAST(:key_insights AS jsonb),
            compliance_result = CAST(:compliance_result AS jsonb),
            status            = :status,
            updated_at        = NOW()
        WHERE id = :id
    """), {
        "exec_summary": report.get("exec_summary"),
        "fund_narratives": json.dumps(report.get("fund_narratives", [])),
        "key_insights": json.dumps(report.get("key_insights", [])),
        "compliance_result": json.dumps(new_compliance),
        "status": new_status,
        "id": report_id,
    })
    db.commit()

    updated_row = db.execute(text(
        f"SELECT {_REPORT_COLS} FROM selfmade_report WHERE id = :id"
    ), {"id": report_id}).fetchone()
    result = _row_to_report(updated_row, _REPORT_KEYS)
    result["compliance_result"] = new_compliance
    return result
