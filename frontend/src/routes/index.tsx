import { createBrowserRouter } from "react-router-dom"
import { Layout } from "@/components/Layout"

import HomePage from "@/features/home"
import RankingsPage from "@/features/rankings"
import FundDetailPage from "@/features/funds"
import ComparePage from "@/features/compare"
import ChatPage from "@/features/chat"
import RulePlaygroundPage from "@/features/rule-playground"
import WorkspacePage from "@/features/workspace"
// features/research-chat and its backend (app/research_chat) are decommissioned
// as of the 2026-07-17 merge — capability folded into /chat (see app/ai/tools.py
// docstring). Left in place, unreferenced, for reversibility — not deleted.
// features/data-quality is decommissioned as a nav destination as of this
// session — it's already gone from Home's card grid; this removes the
// standalone route too. The page component and its backend router
// (app/routers/data_quality.py, still included in main.py and reachable by
// direct API call) are both left in place, unreferenced from the UI, for
// reversibility — not deleted.
// features/rule-approval is decommissioned as a standalone route as of this
// session — folded into Rule Playground's ApprovalDrawer (a side panel, not
// a page). Its component (RuleApprovalPage) and every /rules/pending,
// /rules/all-versions(/{id}), /rules/approve|reject|request-changes,
// /rules/all-versions/{id}/revert, /audit/rule-history backend endpoint are
// completely unchanged — this is a frontend-only consolidation. The page
// component's presentational pieces (StatusBadge, DiffTable, ActionForm,
// VersionDetailPanel, AuditLogStrip) are now imported directly by
// ApprovalDrawer rather than duplicated; RuleApprovalPage itself is left in
// place, unreferenced from routing, for reversibility — not deleted.

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "rankings", element: <RankingsPage /> },
      { path: "funds", element: <FundDetailPage /> },
      { path: "funds/:fundId", element: <FundDetailPage /> },
      { path: "compare", element: <ComparePage /> },
      { path: "chat", element: <ChatPage /> },
      { path: "rule-playground", element: <RulePlaygroundPage /> },
      { path: "workspace", element: <WorkspacePage /> },
    ],
  },
])
