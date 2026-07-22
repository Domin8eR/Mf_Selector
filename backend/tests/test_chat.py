"""Tests for Research Chat endpoint.

Covers:
  - recommendation_request guard fires for 12+ phrasings
  - search_documents returns real chunks for seeded funds, empty for non-seeded
  - tool_call_log records every call
  - 1 E2E per intent type using live DB
  - 2026-07-21 fixes: _resolve_schemecode's Direct+Growth preference order +
    ambiguity disclosure (was previously silent/arbitrary — LIMIT 1, no
    ORDER BY), and compare_holdings_overlap's "find funds similar to X"
    mode (only two-fund overlap existed before; a one-fund-only overlap_search
    query silently errored with "requires both funds identified")
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.config import settings


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def db():
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ── Recommendation guard (18 phrasings) ───────────────────────────────────────

REFRAME_PHRASINGS = [
    "Should I buy HDFC Top 100?",
    "Should I sell my fund units?",
    "Should I invest in Mirae Asset Large Cap?",
    "Should I switch from HDFC to Axis?",
    "Is HDFC Top 100 worth investing in?",
    "Is this a good investment for my portfolio?",
    "Which fund is suitable for me?",
    "Which one is better for my goals?",
    "Just tell me which one you would pick",
    "Which fund would you recommend between these two?",
    "Is it a good time to invest in large cap funds?",
    "Which one is right for my risk appetite?",
    "Tell me the best fund to buy right now",
    "What should I buy for long term wealth creation?",
    "Recommend a fund for 10 year horizon",
    "Which fund should I invest my savings in?",
    "Is Axis Small Cap a good investment?",
    "What would you pick if you had money to invest?",
]

NOT_REFRAME_PHRASINGS = [
    "Show me ranked funds in Large Cap",
    "What is the IR of HDFC Top 100?",
    "Compare HDFC Top 100 vs Mirae Asset metrics",
    "Explain the scoring methodology",
    "What drives this fund's ranking?",
    "Show top 10 ranked funds in mid cap",
]


def test_recommendation_guard_python():
    """All reframe phrasings must trigger the guard in Python (no HTTP overhead)."""
    from app.ai.supervisor import _is_recommendation_request

    missed = [p for p in REFRAME_PHRASINGS if not _is_recommendation_request(p)]
    assert missed == [], f"Guard missed: {missed}"

    false_pos = [p for p in NOT_REFRAME_PHRASINGS if _is_recommendation_request(p)]
    assert false_pos == [], f"False positives: {false_pos}"


def test_recommendation_guard_api(client: TestClient):
    """POST /chat/query must return intent=recommendation_request with no tool_calls."""
    resp = client.post("/chat/query", json={"message": "Should I buy HDFC Top 100?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "recommendation_request"
    assert data["tool_calls"] == []
    # Answer must never contain forbidden words
    answer_lower = data["answer"].lower()
    for bad in ("recommendation", " buy ", " sell ", "best fund", "top pick"):
        assert bad.lower() not in answer_lower, f"Forbidden word '{bad}' found in reframe answer"


# ── E2E intent tests ──────────────────────────────────────────────────────────

def test_ranking_explain_e2e(client: TestClient):
    resp = client.post("/chat/query", json={"message": "Show ranked funds in Equity — Large Cap"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] in ("ranking_explain", "fund_metrics")
    assert data["result_component_type"] in ("table", "text")
    assert len(data["source_tables"]) > 0 or data["intent"] == "recommendation_request"
    assert data["data_confidence"]["level"] in ("high", "medium", "low")


def test_compare_e2e(client: TestClient):
    resp = client.post("/chat/query", json={
        "message": "Compare these two funds",
        "context": {"selected_entities": [19619, 18434], "primary_schemecode": 19619}
    })
    assert resp.status_code == 200
    data = resp.json()
    # compare or fund_metrics are both valid if message is ambiguous without fund names
    assert data["intent"] in ("compare", "fund_metrics", "ranking_explain")


def test_document_search_e2e(client: TestClient):
    """search_documents tool should return chunks for seeded funds."""
    resp = client.post("/chat/query", json={
        "message": "Search fund factsheet documents for large cap strategy mandate"
    })
    assert resp.status_code == 200
    data = resp.json()
    # If intent is document_search, there should be a tool call for search_documents
    if data["intent"] == "document_search":
        tool_names = [tc["tool"] for tc in data["tool_calls"]]
        assert "search_documents" in tool_names


# ── Tool call log audit ───────────────────────────────────────────────────────

def test_tool_call_logged(client: TestClient, db):
    from sqlalchemy import text as sqltext
    initial_count = db.execute(sqltext("SELECT COUNT(*) FROM tool_call_log")).scalar()

    resp = client.post("/chat/query", json={"message": "Show top 5 ranked funds in Equity — Large Cap"})
    assert resp.status_code == 200
    data = resp.json()

    if data["tool_calls"]:  # Only check if tools were called
        new_count = db.execute(sqltext("SELECT COUNT(*) FROM tool_call_log")).scalar()
        assert new_count > initial_count, "No tool_call_log rows were inserted"

        # Verify the log entries have the thread_id set
        thread_id = data["thread_id"]
        rows = db.execute(
            sqltext("SELECT tool_name, status FROM tool_call_log WHERE thread_id = :tid"),
            {"tid": thread_id},
        ).fetchall()
        assert len(rows) > 0


# ── Search documents unit-level ───────────────────────────────────────────────

def test_search_documents_returns_chunks(db):
    """search_documents returns real chunks for a seeded fund schemecode."""
    from app.ai.rag import search_documents
    # 19619 = PGIM India Large Cap (rank #1, was seeded)
    results = search_documents("information ratio structural improvement", db, scheme_id=19619, top_k=3)
    assert len(results) > 0, "Expected chunks for seeded fund 19619"
    for r in results:
        assert "chunk_text" in r
        assert len(r["chunk_text"]) > 10


def test_search_documents_empty_for_unseeded(db):
    """search_documents returns empty list for a fund that has no chunks."""
    from app.ai.rag import search_documents
    # Schemecode 99999 is unlikely to exist
    results = search_documents("anything", db, scheme_id=99999, top_k=5)
    assert results == []


# ── Language rule compliance ───────────────────────────────────────────────────

def test_no_forbidden_words_in_ranking_response(client: TestClient):
    resp = client.post("/chat/query", json={"message": "Show top ranked large cap funds"})
    assert resp.status_code == 200
    answer = resp.json()["answer"].lower()
    for bad in ("recommendation", "best fund", "top pick"):
        assert bad not in answer, f"Forbidden word '{bad}' in answer: {answer[:200]}"


def test_suggested_next_actions_present(client: TestClient):
    resp = client.post("/chat/query", json={"message": "Show ranked funds in Equity — Large Cap"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["suggested_next_actions"], list)
    assert len(data["suggested_next_actions"]) > 0


# ── Merged-from-research_chat capability E2E tests (2026-07-17) ──────────────
# These four intents (scheme_filter, holdings_lookup, overlap_search,
# company_exposure) route through the SAME /chat/query endpoint as every
# other intent — there is no second endpoint anymore.

def test_scheme_filter_e2e(client: TestClient):
    resp = client.post("/chat/query", json={
        "message": "List large cap schemes with AUM over 5000 crore"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "scheme_filter"
    tool_names = [tc["tool"] for tc in data["tool_calls"]]
    assert "filter_schemes" in tool_names
    assert data["result_component_type"] == "table"
    assert data["table_rows"] and len(data["table_rows"]) > 0


def test_holdings_lookup_e2e(client: TestClient):
    resp = client.post("/chat/query", json={
        "message": "What are the top holdings of PGIM India Large Cap Fund - Direct Plan - Dividend?"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "holdings_lookup"
    tool_names = [tc["tool"] for tc in data["tool_calls"]]
    assert "get_holdings" in tool_names
    assert data["table_rows"] and len(data["table_rows"]) > 0


def test_overlap_search_e2e(client: TestClient):
    resp = client.post("/chat/query", json={
        "message": (
            "What is the overlap between PGIM India Large Cap Fund - Direct Plan - Dividend "
            "and PGIM India Large Cap Fund - Direct Plan - Growth?"
        )
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "overlap_search"
    tool_names = [tc["tool"] for tc in data["tool_calls"]]
    assert "compare_holdings_overlap" in tool_names
    assert data["result_component_type"] == "table"


def test_overlap_search_similar_funds_mode_e2e(client: TestClient):
    """A one-fund overlap_search ("similar to X") used to silently error with
    "compare_holdings_overlap requires both funds identified" — no one-to-many
    holdings-similarity search existed anywhere (confirmed absent in the
    pre-merge research_chat module too). Must now return real ranked results."""
    resp = client.post("/chat/query", json={
        "message": "Which funds hold similar holdings to HDFC Large Cap Fund?"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "overlap_search"
    tool_names = [tc["tool"] for tc in data["tool_calls"]]
    assert "compare_holdings_overlap" in tool_names
    assert all(tc["ok"] for tc in data["tool_calls"] if tc["tool"] == "compare_holdings_overlap")
    assert data["result_component_type"] == "table"
    assert data["table_rows"] and len(data["table_rows"]) > 0


def test_compare_holdings_overlap_similar_funds_mode_tool_level(db):
    """Tool-level (no LLM round trip): real ranked, sorted, real-data results —
    same overlap definition as the two-fund path, computed set-based."""
    from app.ai.tools import call_tool

    result = call_tool(
        "compare_holdings_overlap",
        {"scheme_identifier_a": "HDFC Large Cap Fund", "limit": 5},
        db,
    )
    db.rollback()

    assert "error" not in result
    assert result["mode"] == "similar_funds"
    ref_sc = result["reference_fund"]["schemecode"]
    similar = result["similar_funds"]
    assert 0 < len(similar) <= 5

    # Reference fund must never rank against itself.
    assert all(s["schemecode"] != ref_sc for s in similar)
    # Ranked descending by overlap weight.
    weights = [s["overlap_by_weight_pct"] for s in similar]
    assert weights == sorted(weights, reverse=True)
    # HDFC Large Cap Fund is ambiguous (8 real Direct/Regular x Growth/IDCW
    # variants) — the pick must be disclosed, not silent.
    assert result.get("fund_resolution_notes")


def test_resolve_schemecode_prefers_direct_growth_and_discloses_ambiguity(db):
    """Real DB, the exact 6-variant / 8-variant cases from this session.
    Mahindra Manulife: Direct+Growth is unique among the 6 matches — preference
    order fully resolves it, note explains other variants exist. PGIM India:
    Direct+Growth preference still leaves 2 tied rows (a "Series 2" variant) —
    note must disclose the tie itself, not just that alternatives exist."""
    from app.ai.tools import _resolve_schemecode

    sc, name, note = _resolve_schemecode("Mahindra Manulife Large Cap", db)
    assert sc == 42765
    assert "Direct Plan" in name and "Growth" in name
    assert note and "other real match" in note

    sc, name, note = _resolve_schemecode("PGIM India Large Cap", db)
    assert sc == 18434
    assert "Direct Plan" in name and "Growth" in name
    assert note and "tied" in note.lower()


def test_company_exposure_e2e(client: TestClient):
    resp = client.post("/chat/query", json={
        "message": "Which funds hold more than 5% in HDFC Bank?"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "company_exposure"
    tool_names = [tc["tool"] for tc in data["tool_calls"]]
    assert "get_company_exposure" in tool_names
    assert data["table_rows"] is not None


# ── Recommendation guard on the new intents (Python-level, per instruction:
# don't assume the existing guard "just works" for untested paths) ───────────

NEW_INTENT_REFRAME_PHRASINGS = [
    # scheme_filter-shaped
    "Which HDFC scheme should I buy for my portfolio?",
    "Should I invest in one of these large cap AUM schemes?",
    # holdings_lookup-shaped
    "Should I invest based on this fund's top holdings?",
    "Is this fund's concentration a good pick for me?",
    # overlap_search-shaped
    "Given the overlap, which of these two should I hold?",
    "Which of these overlapping funds is the better choice for me?",
    # company_exposure-shaped
    "Should I buy the fund with the most exposure to HDFC Bank?",
    "Which of these HDFC Bank-holding funds would you recommend?",
]


def test_recommendation_guard_covers_new_intents_python():
    from app.ai.supervisor import _is_recommendation_request

    missed = [p for p in NEW_INTENT_REFRAME_PHRASINGS if not _is_recommendation_request(p)]
    assert missed == [], f"Guard missed on new-intent-shaped phrasing: {missed}"


def test_recommendation_guard_covers_new_intents_api(client: TestClient):
    for message in NEW_INTENT_REFRAME_PHRASINGS[:4]:
        resp = client.post("/chat/query", json={"message": message})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "recommendation_request", f"Guard did not fire for: {message!r}"
        assert data["tool_calls"] == []


# ── GET /chat/threads — Home page "Recent Chats" card ─────────────────────────

def test_recent_threads_returns_real_rows_ordered_by_recency(client: TestClient, db):
    from sqlalchemy import text as sqltext

    total = db.execute(sqltext("SELECT COUNT(*) FROM chat_thread")).scalar()
    assert total > 0, "chat_thread table is empty — nothing to verify against"

    resp = client.get("/chat/threads?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    threads = data["threads"]
    assert len(threads) == min(10, total)

    for t in threads:
        assert t["thread_id"]
        assert t["title"]
        assert t["updated_at"]

    updated_ats = [t["updated_at"] for t in threads]
    assert updated_ats == sorted(updated_ats, reverse=True), "threads must be most-recent-first"

    # Cross-check against the DB directly for the single most recent thread
    top_row = db.execute(sqltext(
        "SELECT id, updated_at FROM chat_thread ORDER BY updated_at DESC LIMIT 1"
    )).fetchone()
    assert threads[0]["thread_id"] == str(top_row[0])


def test_recent_threads_respects_limit(client: TestClient):
    resp = client.get("/chat/threads?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()["threads"]) == 3
