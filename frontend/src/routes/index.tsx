import { createBrowserRouter } from "react-router-dom"
import { Layout } from "@/components/Layout"

import HomePage from "@/features/home"
import RankingsPage from "@/features/rankings"
import FundDetailPage from "@/features/funds"
import ComparePage from "@/features/compare"
import ChatPage from "@/features/chat"
import RulePlaygroundPage from "@/features/rule-playground"
import RuleApprovalPage from "@/features/rule-approval"
import DataQualityPage from "@/features/data-quality"
import ResearchChatPage from "@/features/research-chat"
import WorkspacePage from "@/features/workspace"

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
      { path: "rule-approval", element: <RuleApprovalPage /> },
      { path: "data-quality", element: <DataQualityPage /> },
      { path: "research-chat", element: <ResearchChatPage /> },
      { path: "workspace", element: <WorkspacePage /> },
    ],
  },
])
