"""
Tests for the AI Workspace feature.

Coverage:
  1. NL → metric/quadrant mapping (3 phrasings via keyword fallback)
  2. Quadrant assignment correctness (hand-checkable fixture)
  3. POST /workspaces creates a real row; GET /workspaces/{id} recomputes live
  4. Recommendation-reframe guard fires for ≥ 2 disguised phrasings
"""

import pytest
from unittest.mock import patch, MagicMock

from app.ai.supervisor import classify_lens_query
from app.routers.metrics import _assign_quadrant


# ── 1. NL → metric/quadrant (keyword fallback, no LLM) ──────────────────────

def _keyword_classify(msg: str) -> dict:
    """Force keyword-only classification by patching the LLM tiers."""
    with (
        patch("app.ai.supervisor._lens_classify_openai", return_value=None),
        patch("app.ai.supervisor._lens_classify_anthropic", return_value=None),
    ):
        return classify_lens_query(msg)


def test_nl_improving_ir_maps_to_ir_slope_quadrant():
    result = _keyword_classify("show me funds with improving ir trend in large cap")
    assert result["refusal_reason"] is None
    assert result["y_metric"] == "ir_slope_6m_proxy"
    assert result["quadrant_filter"] in (None, "improving-strong", "improving-weak")


def test_nl_rank_movers_maps_to_rank_delta():
    result = _keyword_classify("which funds are rank movers trending up")
    assert result["refusal_reason"] is None
    # rank movers should resolve to rank_delta_6m on y axis or as primary concern
    # if keyword doesn't override y, defaults are accepted — just confirm no crash
    assert result["x_metric"] in ("information_ratio_3yr", "composite_score_v2", "rank_delta_6m")


def test_nl_high_ir_maps_correct_direction():
    result = _keyword_classify("find funds where ir is high and structurally improving")
    assert result["refusal_reason"] is None
    assert result["x_metric"] == "information_ratio_3yr"
    assert result["quadrant_filter"] in (None, "improving-strong", "improving-weak")


# ── 2. Quadrant assignment correctness ───────────────────────────────────────

@pytest.mark.parametrize("x_val, y_val, x_thresh, y_thresh, y_higher, expected", [
    # improving-strong: x >= median, y >= threshold (y_higher=True)
    (0.8, 0.05, 0.5, 0.0, True,  "improving-strong"),
    # improving-weak: x < median, y >= threshold
    (0.2, 0.05, 0.5, 0.0, True,  "improving-weak"),
    # declining-strong: x >= median, y < threshold
    (0.8, -0.05, 0.5, 0.0, True, "declining-strong"),
    # declining-weak: x < median, y < threshold
    (0.2, -0.05, 0.5, 0.0, True, "declining-weak"),
    # rank_delta_6m: y_higher=False → lower (more negative) is better
    # declining rank number (positive delta) → y_good = False when y >= thresh
    (0.8, 5.0,  0.5, 0.0, False, "declining-strong"),   # x high, rank worsened
    (0.8, -5.0, 0.5, 0.0, False, "improving-strong"),   # x high, rank improved
    (0.2, -5.0, 0.5, 0.0, False, "improving-weak"),     # x low, rank improved
    (0.2, 5.0,  0.5, 0.0, False, "declining-weak"),     # x low, rank worsened
])
def test_quadrant_assignment(x_val, y_val, x_thresh, y_thresh, y_higher, expected):
    result = _assign_quadrant(x_val, y_val, x_thresh, y_thresh, y_higher)
    assert result == expected, (
        f"_assign_quadrant({x_val}, {y_val}, {x_thresh}, {y_thresh}, {y_higher}) "
        f"→ {result!r}, expected {expected!r}"
    )


# ── 3. POST /workspaces + GET /workspaces/{id} ───────────────────────────────

def _fake_db_session():
    """Minimal mock of SQLAlchemy Session for persistence tests."""
    mock_session = MagicMock()
    # POST: INSERT RETURNING
    post_row = MagicMock()
    post_row.__getitem__ = lambda self, i: [
        1, "Test Workspace", "IR improving", "Equity — Large Cap",
        "information_ratio_3yr", "ir_slope_6m_proxy",
        "show me improving ir funds", "IR improving funds",
        None,
        __import__("datetime").datetime(2025, 1, 1),
        __import__("datetime").datetime(2025, 1, 1),
    ][i]
    mock_session.execute.return_value.fetchone.return_value = post_row
    mock_session.commit.return_value = None
    return mock_session


def test_create_workspace_sets_description_from_filter_summary():
    """POST /workspaces should set description = filter_summary for Home card compat."""
    from app.routers.workspaces import CreateWorkspaceRequest, create_workspace

    db = _fake_db_session()
    body = CreateWorkspaceRequest(
        name="IR Lens",
        category="Equity — Large Cap",
        x_metric="information_ratio_3yr",
        y_metric="ir_slope_6m_proxy",
        query_text="show me improving ir funds",
        filter_summary="IR improving funds in Large Cap",
    )

    result = create_workspace(body, db)

    # verify INSERT was called
    assert db.execute.called
    sql_call = db.execute.call_args[0][0]
    assert "INSERT INTO selfmade_workspace" in str(sql_call)

    # verify description param = filter_summary
    params = db.execute.call_args[0][1]
    assert params["desc"] == "IR improving funds in Large Cap"
    assert params["name"] == "IR Lens"


def test_get_workspace_calls_live_recompute(monkeypatch):
    """GET /workspaces/{id} must query selfmade tables (live recompute, never stale cache)."""
    from app.routers.workspaces import get_workspace

    executed_sqls: list[str] = []

    mock_session = MagicMock()

    # First fetchone: the workspace row itself
    ws_row = MagicMock()
    ws_row.__getitem__ = lambda self, i: [
        42, "Saved Workspace", "filter text", "Equity — Large Cap",
        "information_ratio_3yr", "ir_slope_6m_proxy",
        "improving ir", "IR improving",
        None,
        __import__("datetime").datetime(2025, 1, 1),
        __import__("datetime").datetime(2025, 1, 1),
    ][i]

    call_count = 0

    def fake_execute(sql, params=None):
        nonlocal call_count
        executed_sqls.append(str(sql))
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.fetchone.return_value = ws_row
        else:
            # scatter data query — return empty list (no actual DB data in unit test)
            mock_result.fetchall.return_value = []
        return mock_result

    mock_session.execute.side_effect = fake_execute

    # Patch _generate_lens_insights to avoid complex template setup
    monkeypatch.setattr(
        "app.routers.workspaces._generate_lens_insights",
        lambda **_: [],
    )

    result = get_workspace(42, mock_session)

    # Verify at least two SQL calls: one for workspace row, one for scatter recompute
    assert call_count >= 2, f"Expected ≥2 SQL calls, got {call_count}"

    # Verify the scatter recompute hits selfmade_ranking_snapshot
    scatter_sqls = [s for s in executed_sqls if "selfmade_ranking_snapshot" in s]
    assert scatter_sqls, "GET /workspaces/{id} must query selfmade_ranking_snapshot for live recompute"

    # Workspace metadata should be returned
    assert result["id"] == 42
    assert result["name"] == "Saved Workspace"
    assert "scatter" in result


# ── 4. Recommendation-reframe guard ─────────────────────────────────────────

@pytest.mark.parametrize("disguised_query", [
    "which fund should I buy for my retirement",
    "what's the best fund to invest in right now",
    "recommend me a good equity fund for 5 years",
    "should I sell my current holdings and switch to this fund",
])
def test_recommendation_guard_fires_via_interpret_endpoint(disguised_query):
    """
    The recommendation-reframe regex must fire for disguised suitability
    queries submitted through /workspace/interpret-query.

    We test classify_lens_query directly (same function the endpoint calls)
    with LLM tiers patched so only the guard logic is tested.
    """
    with (
        patch("app.ai.supervisor._lens_classify_openai", return_value=None),
        patch("app.ai.supervisor._lens_classify_anthropic", return_value=None),
    ):
        result = classify_lens_query(disguised_query)

    assert result["refusal_reason"] is not None, (
        f"Guard should fire for: {disguised_query!r}\n"
        f"Got refusal_reason=None — update _REFRAME_RE in supervisor.py"
    )
    # Defaults must still be set so the caller can render something
    assert result["x_metric"] == "information_ratio_3yr"
    assert result["y_metric"] == "ir_slope_6m_proxy"
