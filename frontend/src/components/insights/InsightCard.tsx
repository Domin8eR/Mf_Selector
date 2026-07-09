import { useNavigate } from "react-router-dom"
import { MessageSquare, ChevronRight, BarChart2, ListFilter, GitCompare } from "lucide-react"
import { cn } from "@/lib/utils"
import type { InsightCardData, FollowUpAction } from "@/lib/api"

const SEVERITY_BORDER: Record<string, string> = {
  positive: "border-l-green-500",
  warning:  "border-l-amber-500",
  negative: "border-l-red-500",
  neutral:  "border-l-slate-400",
}

const ACTION_ICONS: Record<string, typeof MessageSquare> = {
  open_research_chat_with_context:   MessageSquare,
  open_category_rankings_filtered:   ListFilter,
  open_fund_detail:                  BarChart2,
  open_fund_comparison:              GitCompare,
  open_rule_playground:              ListFilter,
}

export default function InsightCard({ card }: { card: InsightCardData }) {
  const navigate = useNavigate()

  const handleAction = (action: FollowUpAction) => {
    switch (action.action_type) {
      case "open_category_rankings_filtered":
        navigate("/rankings")
        break
      case "open_fund_detail":
        navigate(`/funds/${action.llm_context_payload?.schemecode ?? ""}`)
        break
      case "open_fund_comparison":
        navigate("/compare")
        break
      case "open_research_chat_with_context":
        navigate("/research-chat")
        break
      case "open_rule_playground":
        navigate("/rule-playground")
        break
    }
  }

  return (
    <div
      className={cn(
        "bg-white rounded-lg border border-gray-200 border-l-4 px-4 py-3",
        SEVERITY_BORDER[card.severity] ?? SEVERITY_BORDER.neutral,
      )}
    >
      <div className="text-sm font-semibold text-gray-800 mb-1">{card.headline}</div>
      <div className="text-xs text-gray-500 leading-relaxed">{card.body_text}</div>

      {card.follow_up_actions.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {card.follow_up_actions.map(action => {
            const Icon = ACTION_ICONS[action.action_type] ?? ChevronRight
            return (
              <button
                key={action.action_id}
                onClick={() => handleAction(action)}
                className="inline-flex items-center gap-1 text-[11px] text-blue-600 hover:bg-blue-50 rounded px-2 py-1 transition-colors"
              >
                <Icon className="h-3 w-3" />
                {action.label}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
