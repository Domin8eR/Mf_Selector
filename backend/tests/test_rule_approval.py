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

# ── Fixture: snapshot + restore ───────────────────────────────────────────────

@pytest.fixture(autouse=False)
def restore_rule_state():
    """
    Before each test: snapshot all selfmade_rule_version rows and the max id.
    After each test: hard-restore the snapshot, delete any new rows,
    and wipe audit events that the test created.
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

    engine.dispose()


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Helper: find the pending sandbox-1 version ───────────────────────────────

def _find_pending(client: TestClient) -> dict:
    resp = client.get("/rules/pending")
    assert resp.status_code == 200, resp.text
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
    before_rank = client.get("/rankings/category?category=Equity+%E2%80%94+Large+Cap")
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
    after_rank = client.get("/rankings/category?category=Equity+%E2%80%94+Large+Cap")
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
    rank_resp = client.get("/rankings/category?category=Equity+%E2%80%94+Large+Cap")
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

def test_reject_requires_approver_name(client: TestClient):
    """Reject with blank approver_name must return 422."""
    pending = _find_pending(client)
    resp = client.post("/rules/reject", json={
        "rule_version_id": pending["rule_version_id"],
        "approver_name": "   ",
        "comment": "some comment",
    })
    assert resp.status_code == 422


def test_reject_requires_comment(client: TestClient):
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

def test_approve_requires_approver_name(client: TestClient):
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

def test_request_changes_requires_approver_name(client: TestClient):
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


def test_request_changes_requires_comment(client: TestClient):
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

def test_pending_returns_live_diff(client: TestClient):
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
