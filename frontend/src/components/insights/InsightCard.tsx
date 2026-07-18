import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { ChevronDown, ChevronUp, MessageSquare } from "lucide-react"
import { cn } from "@/lib/utils"
import type { InsightCardData, FollowUpPayload } from "@/lib/api"

const SEVERITY_BORDER: Record<string, string> = {
  positive: "border-l-green-500",
  warning:  "border-l-amber-500",
  negative: "border-l-red-500",
  neutral:  "border-l-slate-400",
}

// Renders **bold** markers as real bold — never literal asterisks.
function renderBold(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i} className="font-semibold text-gray-900">{part.slice(2, -2)}</strong>
    }
    return <span key={i}>{part}</span>
  })
}

function formatChipValue(v: unknown): string {
  if (v === null || v === undefined || v === "n/a") return "—"
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2)
  return String(v)
}

function formatChipKey(k: string): string {
  return k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
}

// CompactInsightCard — shared by every page (Home, Category Rankings, Fund
// Detail, Fund Comparison, Rule Playground). Collapsed: compact sentence +
// 2-3 metric chips. Expanded (click/tap): 2-5 bullets. Same bold rule in
// both. One follow-up action, wired to the canonical payload shape.
export default function InsightCard({ card }: { card: InsightCardData }) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState(false)

  const handleFollowUp = (payload: FollowUpPayload | null) => {
    if (!payload) {
      navigate("/chat")
      return
    }
    const params = new URLSearchParams({
      from: payload.page,
      schemecode: payload.entity_id || "",
      fund_name: payload.entity_name || "",
      facts_json: JSON.stringify(payload.facts ?? {}),
      // Canonical follow-up context (2026-07-18) — sent as `context` on the
      // /chat/query POST body by ChatPage, not as a separate query param;
      // encoded here too so a fresh chat session opened via URL still has it.
      context: JSON.stringify(payload),
    })
    navigate(`/chat?${params.toString()}`)
  }

  const followUp = card.follow_up_actions[0]
  const chipEntries = Object.entries(card.chips ?? {}).slice(0, 3)

  return (
    <div
      className={cn(
        "bg-white rounded-lg border border-gray-200 border-l-4 px-4 py-3",
        SEVERITY_BORDER[card.severity] ?? SEVERITY_BORDER.neutral,
      )}
    >
      <button
        className="w-full text-left"
        onClick={() => setExpanded(e => !e)}
        aria-expanded={expanded}
      >
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm text-gray-800 leading-snug flex-1">
            {renderBold(card.compact_text)}
          </p>
          {expanded
            ? <ChevronUp className="h-4 w-4 text-gray-400 flex-shrink-0 mt-0.5" />
            : <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0 mt-0.5" />}
        </div>

        {chipEntries.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {chipEntries.map(([k, v]) => (
              <span
                key={k}
                className="text-[10px] bg-gray-50 border border-gray-200 rounded-full px-2 py-0.5 text-gray-600"
              >
                <span className="text-gray-400">{formatChipKey(k)}:</span>{" "}
                <span className="font-medium text-gray-700">{formatChipValue(v)}</span>
              </span>
            ))}
          </div>
        )}
      </button>

      {expanded && (
        <ul className="mt-3 space-y-1 border-t border-gray-100 pt-2">
          {card.expanded_bullets.map((bullet, i) => (
            <li key={i} className="text-xs text-gray-600 leading-relaxed flex gap-1.5">
              <span className="text-gray-300 flex-shrink-0">•</span>
              <span>{renderBold(bullet)}</span>
            </li>
          ))}
        </ul>
      )}

      {followUp && (
        <div className="mt-2">
          <button
            onClick={(e) => { e.stopPropagation(); handleFollowUp(followUp.llm_context_payload) }}
            className="inline-flex items-center gap-1 text-[11px] text-blue-600 hover:bg-blue-50 rounded px-2 py-1 transition-colors"
          >
            <MessageSquare className="h-3 w-3" />
            {followUp.label}
          </button>
        </div>
      )}
    </div>
  )
}
