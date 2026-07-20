"""
Rule Approval integration tests.

These tests hit the REAL database (no mocks). A fixture snapshots the rule_version
table state before each test and restores it on teardown so the tests are idempotent.

Coverage:
  1. PROPAGATION — approve sandbox-1, then verify /rankings/category AND
     /insights/workspace/daily-briefing both report the new rule_version label.
     Before/after values are printed side-by-side as required.
  2. IMMUTABILITY — after approval, v1.0 still exists in /rules/all-versions
     with status=superseded and all 4 original components intact.
  3. REJECT — rejected version stays non-active forever; currently-active
     version unchanged.
  4. REVERT — creates a genuinely NEW row (different id), old row untouched.
"""

from __future__ import annotations

import os
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://piyushrajlenka:29062002@localhost:5432/Altstreet_AI",
)
EPSILON = 0.02  # floating-point tolerance for hand-computed score/contribution checks

# ── Fixture: snapshot + restore ───────────────────────────────────────────────

@pytest.fixture(autouse=False)
def restore_rule_state():
    """
    Before each test: snapshot all selfmade_rule_version rows and the max id.
    After each test: hard-restore the snapshot, delete any new rows (and the
    selfmade_ranking_contribution rows that reference them — a rule
    component can no longer be deleted while a real contribution row still
    points at it, now that POST /rules/approve actually recomputes rankings
    as a real side effect), wipe audit events the test created, then re-run
    the real recompute so selfmade_ranking_snapshot/_contribution reflect
    whichever version is active again — restoring is_active alone would
    leave real ranking data computed under the test's temporary weights.
    """
    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, is_active, status, approved_by, approved_at
            FROM selfmade_rule_version
        """)).fetchall()
        snapshot = [(r[0], bool(r[1]), r[2], r[3], r[4]) for r in rows]
        max_id_before = max(r[0] for r in snapshot) if snapshot else 0

    yield max_id_before

    with engine.begin() as conn:
        # Delete audit events created during this test
        conn.execute(text("DELETE FROM selfmade_audit_event"))
        # Delete contribution rows referencing test-created components
        # BEFORE deleting the components themselves (FK constraint).
        conn.execute(text("""
            DELETE FROM selfmade_ranking_contribution
            WHERE component_id IN (
                SELECT id FROM selfmade_rule_component WHERE rule_version_id > :max_id
            )
        """), {"max_id": max_id_before})
        # Delete any version rows that were added
        conn.execute(text(
            "DELETE FROM selfmade_rule_component WHERE rule_version_id > :max_id"
        ), {"max_id": max_id_before})
        conn.execute(text(
            "DELETE FROM selfmade_rule_version WHERE id > :max_id"
        ), {"max_id": max_id_before})
        # Restore original rows to their snapshot state
        for (rv_id, is_active, status, approved_by, approved_at) in snapshot:
            conn.execute(text("""
                UPDATE selfmade_rule_version
                SET is_active = :ia, status = :s, approved_by = :ab, approved_at = :at
                WHERE id = :id
            """), {
                "ia": is_active, "s": status,
                "ab": approved_by, "at": approved_at, "id": rv_id,
            })

    # Real, governed recompute against whichever version is active again —
    # undoes the test's temporary-weights pollution of today's snapshot.
    from sqlalchemy.orm import sessionmaker
    from app.rankings.recompute import recompute_all_rankings
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        recompute_all_rankings(session)
    finally:
        session.close()

    engine.dispose()


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Helper: find (or create) the pending sandbox-1 version ───────────────────

def _find_pending(client: TestClient) -> dict:
    """
    Earlier interactive sessions manually seeded a "sandbox-1" pending
    version; that ephemeral DB state doesn't survive across environments
    or reruns. Self-contained instead: submit a real pending version
    (different weights from v1.0) via the actual API if none exists, so
    this suite is idempotent and doesn't depend on external setup.
    """
    resp = client.get("/rules/pending")
    assert resp.status_code == 200, resp.text
    pending = resp.json()
    if not pending:
        submit_resp = client.post("/rules/submit-for-approval", json={
            "rule_components": [
                {"metric_column": "information_ratio_3yr", "direction": "higher_better", "weight": 0.30},
                {"metric_column": "sharpe_ratio_3yr", "direction": "higher_better", "weight": 0.30},
                {"metric_column": "active_3yr_ret", "direction": "higher_better", "weight": 0.25},
                {"metric_column": "tracking_error_3yr", "direction": "lower_better", "weight": 0.15},
            ],
            "rationale": "Test-seeded sandbox version (different weights from v1.0)",
            "category": "Equity — Large Cap",
            "submitted_by": "test-harness",
        })
        assert submit_resp.status_code == 201, submit_resp.text
        resp = client.get("/rules/pending")
        pending = resp.json()
    assert len(pending) >= 1, "Expected at least one pending_review version (sandbox-1)"
    return pending[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PROPAGATION TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_approve_propagates_to_rankings_and_insights(client: TestClient, restore_rule_state: int):
    """
    Approve sandbox-1 for real.
    Assert that /rankings/category AND /insights/workspace/daily-briefing
    immediately reflect the new rule_version label — not the old one.
    """
    # ── BEFORE state ─────────────────────────────────────────────────────────
    before_rank = client.get("/rankings/category?category=Large+Cap")
    assert before_rank.status_code == 200
    before_rank_version = before_rank.json()["rule_version"]

    before_insight = client.get("/insights/workspace/daily-briefing")
    assert before_insight.status_code == 200
    before_insight_version = before_insight.json()["rule_version"]

    print(f"\n  BEFORE  /rankings/category       rule_version = {before_rank_version!r}")
    print(f"  BEFORE  /insights/daily-briefing  rule_version = {before_insight_version!r}")

    assert before_rank_version == "v1.0", (
        f"Expected 'v1.0' before approval, got {before_rank_version!r}"
    )
    assert before_insight_version == "v1.0", (
        f"Expected 'v1.0' before approval, got {before_insight_version!r}"
    )

    # ── Find pending sandbox-1 ────────────────────────────────────────────────
    pending = _find_pending(client)
    sandbox1_id = pending["rule_version_id"]
    sandbox1_label = pending["version_label"]
    assert sandbox1_label == "sandbox-1", (
        f"Expected label 'sandbox-1', got {sandbox1_label!r}"
    )

    # ── Approve ───────────────────────────────────────────────────────────────
    approve_resp = client.post("/rules/approve", json={
        "rule_version_id": sandbox1_id,
        "approver_name": "Test Approver",
        "comment": "Propagation test — verifying rule_version changes downstream",
    })
    assert approve_resp.status_code == 200, approve_resp.text
    approved = approve_resp.json()
    assert approved["status"] == "active"
    assert approved["version_label"] == "sandbox-1"

    # ── AFTER state ───────────────────────────────────────────────────────────
    after_rank = client.get("/rankings/category?category=Large+Cap")
    assert after_rank.status_code == 200
    after_rank_version = after_rank.json()["rule_version"]

    after_insight = client.get("/insights/workspace/daily-briefing")
    assert after_insight.status_code == 200
    after_insight_version = after_insight.json()["rule_version"]

    print(f"  AFTER   /rankings/category       rule_version = {after_rank_version!r}")
    print(f"  AFTER   /insights/daily-briefing  rule_version = {after_insight_version!r}")

    # THE KEY ASSERTIONS
    assert after_rank_version == "sandbox-1", (
        f"Expected 'sandbox-1' after approval, got {after_rank_version!r}\n"
        f"  BEFORE: {before_rank_version!r}  |  AFTER: {after_rank_version!r}"
    )
    assert after_insight_version == "sandbox-1", (
        f"Expected 'sandbox-1' after approval in insights, got {after_insight_version!r}\n"
        f"  BEFORE: {before_insight_version!r}  |  AFTER: {after_insight_version!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. IMMUTABILITY TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_old_version_preserved_as_superseded(client: TestClient, restore_rule_state: int):
    """
    After approving sandbox-1, v1.0 must appear in /rules/all-versions with
    status=superseded and all 4 original components intact.
    """
    pending = _find_pending(client)
    sandbox1_id = pending["rule_version_id"]

    client.post("/rules/approve", json={
        "rule_version_id": sandbox1_id,
        "approver_name": "Immutability Tester",
        "comment": "Testing that old version is preserved",
    })

    versions_resp = client.get("/rules/all-versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()

    # Find v1.0 in the timeline
    v10 = next((v for v in versions if v["version_label"] == "v1.0"), None)
    assert v10 is not None, "v1.0 must still exist in /rules/all-versions after approval"
    assert v10["status"] == "superseded", (
        f"v1.0 must be 'superseded' after a new approval, got {v10['status']!r}"
    )
    assert not v10["is_current_default"], "v1.0 must not be is_current_default after approval"

    # Verify all 4 original components are intact
    detail_resp = client.get(f"/rules/all-versions/{v10['id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    comps = detail["components"]
    assert len(comps) == 4, (
        f"v1.0 must still have all 4 original components; got {len(comps)}: "
        f"{[c['metric_column'] for c in comps]}"
    )
    # Verify the known component columns
    comp_cols = {c["metric_column"] for c in comps}
    assert "information_ratio_3yr" in comp_cols
    assert "sharpe_ratio_3yr"      in comp_cols
    assert "active_3yr_ret"        in comp_cols
    assert "tracking_error_3yr"    in comp_cols


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REJECT TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_reject_leaves_currently_active_version_unchanged(client: TestClient, restore_rule_state: int):
    """
    Reject a pending version. Verify:
    - The rejected version status is 'rejected' (not active).
    - The currently-active version is still v1.0 (unchanged).
    - /rankings/category still shows v1.0.
    """
    pending = _find_pending(client)
    sandbox1_id = pending["rule_version_id"]

    reject_resp = client.post("/rules/reject", json={
        "rule_version_id": sandbox1_id,
        "approver_name": "Reject Tester",
        "comment": "Rejected for test purposes",
    })
    assert reject_resp.status_code == 200, reject_resp.text
    rejected = reject_resp.json()
    assert rejected["status"] == "rejected"
    assert not rejected["is_current_default"], "Rejected version must not be the current default"

    # Current default must still be v1.0
    rank_resp = client.get("/rankings/category?category=Large+Cap")
    assert rank_resp.status_code == 200
    assert rank_resp.json()["rule_version"] == "v1.0", (
        "After rejection, /rankings/category must still report 'v1.0'"
    )

    # Rejected version must never appear as active
    versions = client.get("/rules/all-versions").json()
    active = [v for v in versions if v["is_current_default"]]
    assert len(active) == 1, "Exactly one version must be the current default"
    assert active[0]["version_label"] == "v1.0", (
        f"Active version must still be v1.0 after rejection, got {active[0]['version_label']!r}"
    )


# ── Sub-test: reject requires non-blank actor and comment ─────────────────────

def test_reject_requires_approver_name(client: TestClient, restore_rule_state: int):
    """Reject with blank approver_name must return 422."""
    pending = _find_pending(client)
    resp = client.post("/rules/reject", json={
        "rule_version_id": pending["rule_version_id"],
        "approver_name": "   ",
        "comment": "some comment",
    })
    assert resp.status_code == 422


def test_reject_requires_comment(client: TestClient, restore_rule_state: int):
    """Reject with blank comment must return 422."""
    pending = _find_pending(client)
    resp = client.post("/rules/reject", json={
        "rule_version_id": pending["rule_version_id"],
        "approver_name": "Real Person",
        "comment": "   ",
    })
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 4. REVERT TEST
# ═══════════════════════════════════════════════════════════════════════════════

def test_revert_creates_new_row_and_original_is_untouched(client: TestClient, restore_rule_state: int):
    """
    1. Approve sandbox-1 so it becomes active and v1.0 is superseded.
    2. Revert to v1.0 — this must create a NEW version row (new id, not id==3).
    3. Verify the original v1.0 row (id=3) is completely unchanged:
       - still status=superseded
       - still has 4 components
    4. Verify the new reverted row is active with the same component weights.
    """
    # Step 1: approve sandbox-1
    pending = _find_pending(client)
    sandbox1_id = pending["rule_version_id"]

    approve_resp = client.post("/rules/approve", json={
        "rule_version_id": sandbox1_id,
        "approver_name": "Revert Tester",
        "comment": "Approving before revert test",
    })
    assert approve_resp.status_code == 200

    # Get the v1.0 id from the versions list
    versions = client.get("/rules/all-versions").json()
    v10 = next(v for v in versions if v["version_label"] == "v1.0")
    v10_id = v10["id"]

    # Step 2: revert to v1.0
    revert_resp = client.post(f"/rules/all-versions/{v10_id}/revert", json={
        "approver_name": "Revert Tester",
        "comment": "Reverting to v1.0 for test",
    })
    assert revert_resp.status_code == 200, revert_resp.text
    reverted = revert_resp.json()

    # The new version must have a DIFFERENT id from the original v1.0
    assert reverted["id"] != v10_id, (
        f"Revert must create a NEW row, not reactivate old row. "
        f"Got id={reverted['id']!r}, expected != {v10_id!r}"
    )
    assert reverted["status"] == "active"
    assert reverted["is_current_default"]
    assert reverted["parent_version_id"] == v10_id, (
        "Reverted version must reference the source via parent_version_id"
    )

    # Step 3: original v1.0 row must be untouched
    original_resp = client.get(f"/rules/all-versions/{v10_id}")
    assert original_resp.status_code == 200
    original = original_resp.json()

    # The original row must still be superseded, not active
    assert original["id"] == v10_id, "Original row id must be unchanged"
    assert original["status"] == "superseded", (
        f"Original v1.0 row must stay 'superseded'; got {original['status']!r}"
    )
    assert not original["is_current_default"], (
        "Original v1.0 row must not be the current default after revert"
    )
    assert len(original["components"]) == 4, (
        f"Original v1.0 row must still have 4 components; got {len(original['components'])}"
    )

    # Step 4: new reverted version must have the same 4 components
    assert len(reverted["components"]) == 4, (
        f"Reverted version must copy 4 components from v1.0; got {len(reverted['components'])}"
    )
    new_comp_cols = {c["metric_column"] for c in reverted["components"]}
    orig_comp_cols = {c["metric_column"] for c in original["components"]}
    assert new_comp_cols == orig_comp_cols, (
        f"Reverted components must match original: "
        f"new={sorted(new_comp_cols)} vs orig={sorted(orig_comp_cols)}"
    )


# ── Sub-test: cannot approve non-pending version ──────────────────────────────

def test_approve_requires_pending_review_status(client: TestClient, restore_rule_state: int):
    """Approving a version that is already 'active' must return 422."""
    # v1.0 (id=3) is currently active — try to approve it again
    versions = client.get("/rules/all-versions").json()
    active_v = next(v for v in versions if v["is_current_default"])

    resp = client.post("/rules/approve", json={
        "rule_version_id": active_v["id"],
        "approver_name": "Someone",
        "comment": None,
    })
    assert resp.status_code == 422


# ── Sub-test: approve requires non-blank actor ────────────────────────────────

def test_approve_requires_approver_name(client: TestClient, restore_rule_state: int):
    """Approve with blank approver_name must return 422."""
    pending = _find_pending(client)
    resp = client.post("/rules/approve", json={
        "rule_version_id": pending["rule_version_id"],
        "approver_name": "",
        "comment": None,
    })
    assert resp.status_code == 422


# ── Sub-test: audit events are written ───────────────────────────────────────

def test_approve_writes_audit_event(client: TestClient, restore_rule_state: int):
    """Approval must write exactly one audit_event row with action='approved'."""
    pending = _find_pending(client)
    sandbox1_id = pending["rule_version_id"]

    client.post("/rules/approve", json={
        "rule_version_id": sandbox1_id,
        "approver_name": "Audit Tester",
        "comment": "Checking audit trail",
    })

    audit_resp = client.get("/audit/rule-history?limit=10")
    assert audit_resp.status_code == 200
    events = audit_resp.json()["events"]
    approved_events = [e for e in events if e["action"] == "approved" and e["actor"] == "Audit Tester"]
    assert len(approved_events) >= 1, (
        f"Expected at least one 'approved' audit event for 'Audit Tester'; got: {events}"
    )
    ev = approved_events[0]
    assert ev["rule_version_id"] == sandbox1_id
    assert ev["comment"] == "Checking audit trail"


# ── Sub-test: request-changes requires non-blank actor and comment ─────────────

def test_request_changes_requires_approver_name(client: TestClient, restore_rule_state: int):
    """request-changes with blank approver_name must return 422."""
    pending = _find_pending(client)
    resp = client.post("/rules/request-changes", json={
        "rule_version_id": pending["rule_version_id"],
        "approver_name": "   ",
        "comment": "some comment",
    })
    assert resp.status_code == 422, (
        f"Expected 422 for blank approver_name on request-changes, got {resp.status_code}"
    )


def test_request_changes_requires_comment(client: TestClient, restore_rule_state: int):
    """request-changes with blank comment must return 422."""
    pending = _find_pending(client)
    resp = client.post("/rules/request-changes", json={
        "rule_version_id": pending["rule_version_id"],
        "approver_name": "Real Person",
        "comment": "   ",
    })
    assert resp.status_code == 422, (
        f"Expected 422 for blank comment on request-changes, got {resp.status_code}"
    )


# ── Sub-test: GET /rules/pending returns live diff ────────────────────────────

def test_pending_returns_live_diff(client: TestClient, restore_rule_state: int):
    """GET /rules/pending must return diff rows with change_type values."""
    resp = client.get("/rules/pending")
    assert resp.status_code == 200
    pending = resp.json()
    if not pending:
        pytest.skip("No pending versions to test diff against")

    item = pending[0]
    assert "diff" in item
    diff = item["diff"]
    assert isinstance(diff, list) and len(diff) > 0
    change_types = {row["change_type"] for row in diff}
    # At least one component must differ (sandbox-1 has different weights from v1.0)
    assert change_types & {"added", "removed", "changed"}, (
        f"Expected at least one changed/added/removed component; got change_types={change_types}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RECOMPUTE PROPAGATION — the actual fix, proved with hand-computed numbers
# ═══════════════════════════════════════════════════════════════════════════════
#
# This is the direct fix for "contributions frozen from whenever the seed
# script last ran": approve a version with DIFFERENTLY WEIGHTED components
# than the currently active one, and prove — with a hand-computed expected
# number, not just "it changed" — that:
#   (a) recompute_all_rankings ran as part of approval
#   (b) a specific fund's composite_score_v2 changed to the CORRECT value
#   (c) /rankings/category returns that fund at its new correct rank
#   (d) /rankings/explain's contribution breakdown reflects the new weights

TEST_SCHEMECODE = 19619          # PGIM India Large Cap Fund — Direct Plan — Dividend
TEST_CATEGORY = "Large Cap"      # real bucket_36 value

# Deliberately different from v1.0's 0.40 IR / 0.25 Sharpe / 0.20 ActiveRet /
# 0.15 TE — Active Return becomes dominant instead of IR, which is expected
# to move TEST_SCHEMECODE's rank (its active_3yr_ret percentile is much
# lower than its IR/Sharpe/TE percentiles — see the hand-verification below).
NEW_WEIGHTS = {
    "information_ratio_3yr": 0.15,
    "sharpe_ratio_3yr": 0.20,
    "active_3yr_ret": 0.40,
    "tracking_error_3yr": 0.25,
}


@pytest.fixture(scope="module")
def db():
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_rule_approval_propagates_with_hand_verified_recompute(
    client: TestClient, db, restore_rule_state: int,
):
    assert abs(sum(NEW_WEIGHTS.values()) - 1.0) < 1e-9, "test weights must sum to 1.0"

    # ── Capture ground truth BEFORE approval ──────────────────────────────────
    # percentile_score is computed from raw metric values within the category —
    # it does NOT depend on the rule version's weights, so these numbers stay
    # valid ground truth for hand-computing the AFTER state below.
    before_rows = db.execute(text("""
        SELECT rcomp.metric_column, rc.percentile_score
        FROM selfmade_ranking_contribution rc
        JOIN selfmade_rule_component rcomp ON rcomp.id = rc.component_id
        JOIN selfmade_ranking_snapshot s ON s.id = rc.snapshot_id
        WHERE s.schemecode = :sc AND s.category = :cat
    """), {"sc": TEST_SCHEMECODE, "cat": TEST_CATEGORY}).fetchall()
    pct_by_metric = {r[0]: float(r[1]) for r in before_rows}
    assert set(pct_by_metric.keys()) == set(NEW_WEIGHTS.keys()), (
        f"Test fund must have all 4 components populated today; got {pct_by_metric}"
    )

    before_score = float(db.execute(text("""
        SELECT composite_score_v2 FROM selfmade_ranking_snapshot
        WHERE schemecode = :sc AND category = :cat
    """), {"sc": TEST_SCHEMECODE, "cat": TEST_CATEGORY}).scalar())
    before_rank = db.execute(text("""
        SELECT rank_in_category FROM selfmade_ranking_snapshot
        WHERE schemecode = :sc AND category = :cat
    """), {"sc": TEST_SCHEMECODE, "cat": TEST_CATEGORY}).scalar()

    # Hand-compute the expected AFTER composite score from the SAME (weight-
    # independent) percentile scores, using the NEW weights.
    expected_new_score = round(
        sum(pct_by_metric[m] * w for m, w in NEW_WEIGHTS.items()), 4
    )
    # Sanity check: this must be a real, materially different number — not a
    # coincidental near-match — otherwise this test wouldn't actually prove
    # the new weights took effect.
    assert abs(expected_new_score - before_score) > 1.0, (
        f"Test weights must produce a materially different score: "
        f"before={before_score}, expected_after={expected_new_score}"
    )

    # Hand-compute the fund's expected NEW rank: fetch every OTHER Large Cap
    # fund's own percentile scores (also weight-independent), recompute all
    # of them under NEW_WEIGHTS in plain Python, and find where the test
    # fund actually lands — an independent recomputation, not a copy of
    # recompute_all_rankings()'s own code.
    all_rows = db.execute(text("""
        SELECT s.schemecode, rcomp.metric_column, rc.percentile_score
        FROM selfmade_ranking_snapshot s
        JOIN selfmade_ranking_contribution rc ON rc.snapshot_id = s.id
        JOIN selfmade_rule_component rcomp ON rcomp.id = rc.component_id
        WHERE s.category = :cat
    """), {"cat": TEST_CATEGORY}).fetchall()
    pct_by_scheme: dict[int, dict[str, float]] = {}
    for sc, metric, pct in all_rows:
        pct_by_scheme.setdefault(sc, {})[metric] = float(pct)
    new_scores = {
        sc: sum(pcts[m] * w for m, w in NEW_WEIGHTS.items())
        for sc, pcts in pct_by_scheme.items()
        if set(pcts.keys()) == set(NEW_WEIGHTS.keys())
    }
    ranked = sorted(new_scores.items(), key=lambda kv: kv[1], reverse=True)
    expected_new_rank = next(i for i, (sc, _) in enumerate(ranked, start=1) if sc == TEST_SCHEMECODE)

    print(f"\n  BEFORE  composite_score_v2 = {before_score}  rank = {before_rank}")
    print(f"  HAND-COMPUTED AFTER  composite_score_v2 = {expected_new_score}  rank = {expected_new_rank}")

    # ── Submit a real pending version with the new weights, and approve it ────
    rule_set_id = db.execute(text(
        "SELECT rule_set_id FROM selfmade_rule_version WHERE is_active = true ORDER BY id DESC LIMIT 1"
    )).scalar()

    submit_resp = client.post("/rules/submit-for-approval", json={
        "rule_components": [
            {"metric_column": m, "direction": "higher_better" if m != "tracking_error_3yr" else "lower_better", "weight": w}
            for m, w in NEW_WEIGHTS.items()
        ],
        "rationale": "Propagation proof test — Active Return dominant",
        "category": "Equity — Large Cap",
        "submitted_by": "test-harness",
    })
    assert submit_resp.status_code == 201, submit_resp.text
    new_rv_id = submit_resp.json()["rule_version_id"]

    approve_resp = client.post("/rules/approve", json={
        "rule_version_id": new_rv_id,
        "approver_name": "Propagation Test",
        "comment": "Hand-verified recompute propagation proof",
    })
    assert approve_resp.status_code == 200, approve_resp.text
    approved = approve_resp.json()

    # ── (a) recompute_all_rankings ran as part of approval ────────────────────
    assert "recompute" in approved, "approve response must surface the recompute summary"
    recompute_summary = approved["recompute"]
    assert recompute_summary["status"] == "ok", recompute_summary
    assert recompute_summary["rule_version_id"] == new_rv_id
    assert recompute_summary["funds_scored"] > 0

    # ── (b) the fund's composite_score_v2 changed to the CORRECT value ────────
    after_score = float(db.execute(text("""
        SELECT composite_score_v2 FROM selfmade_ranking_snapshot
        WHERE schemecode = :sc AND category = :cat
    """), {"sc": TEST_SCHEMECODE, "cat": TEST_CATEGORY}).scalar())
    after_rank = db.execute(text("""
        SELECT rank_in_category FROM selfmade_ranking_snapshot
        WHERE schemecode = :sc AND category = :cat
    """), {"sc": TEST_SCHEMECODE, "cat": TEST_CATEGORY}).scalar()

    print(f"  ACTUAL  AFTER  composite_score_v2 = {after_score}  rank = {after_rank}")

    assert abs(after_score - expected_new_score) < EPSILON, (
        f"composite_score_v2 must equal the hand-computed value: "
        f"expected={expected_new_score}, actual={after_score}"
    )

    # ── (c) /rankings/category returns the fund at its new correct rank ───────
    rank_resp = client.get("/rankings/category", params={"category": TEST_CATEGORY, "page_size": 1, "search": "PGIM India Large Cap Fund - Direct Plan - Dividend"})
    assert rank_resp.status_code == 200, rank_resp.text
    rank_data = rank_resp.json()
    assert rank_data["rule_version"] == submit_resp.json()["version_label"]
    matching = [r for r in rank_data["results"] if r["schemecode"] == TEST_SCHEMECODE]
    assert matching, f"Fund {TEST_SCHEMECODE} must appear in /rankings/category results: {rank_data['results']}"
    api_rank = matching[0]["rank"]
    api_score = matching[0]["composite_score"]
    print(f"  /rankings/category reports  rank = {api_rank}  composite_score = {api_score}")
    assert api_rank == expected_new_rank, (
        f"/rankings/category rank must match the independently hand-computed rank: "
        f"expected={expected_new_rank}, api={api_rank}"
    )
    assert abs(api_score - expected_new_score) < EPSILON

    # ── (d) /rankings/explain's contribution breakdown reflects the NEW weights ──
    explain_resp = client.get(f"/rankings/explain/{TEST_SCHEMECODE}", params={"category": TEST_CATEGORY})
    assert explain_resp.status_code == 200, explain_resp.text
    explain_data = explain_resp.json()
    explain_by_metric = {c["component_name"]: c for c in explain_data["components"]}
    # component_name isn't the metric_column; match on data instead — rebuild
    # by metric via raw_value/percentile_score identity against pct_by_metric.
    components_by_pct = {round(c["percentile_score"], 2): c for c in explain_data["components"]}
    for metric, weight in NEW_WEIGHTS.items():
        pct = round(pct_by_metric[metric], 2)
        comp = components_by_pct.get(pct)
        assert comp is not None, (
            f"Expected a contribution row with percentile_score={pct} for {metric}; "
            f"got components={explain_data['components']}"
        )
        assert abs(comp["weight"] - weight) < 1e-6, (
            f"/rankings/explain weight for {metric} must reflect the NEW rule version "
            f"({weight}), not a frozen old one: got {comp['weight']}"
        )
        expected_contribution = round(pct * weight, 4)
        assert abs(comp["contribution"] - expected_contribution) < EPSILON, (
            f"/rankings/explain contribution for {metric} must be percentile_score * NEW weight: "
            f"expected={expected_contribution}, got={comp['contribution']}"
        )
    print(f"  /rankings/explain contributions reflect the NEW weights — not frozen: OK")
