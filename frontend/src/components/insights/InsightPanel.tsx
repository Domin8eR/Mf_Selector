import { Loader2 } from "lucide-react"
import type { InsightCardData } from "@/lib/api"
import InsightCard from "./InsightCard"

interface InsightPanelProps {
  cards: InsightCardData[]
  isLoading: boolean
  title?: string
  /** Card list layout. Defaults to the single-column stack used everywhere
   *  except Fund Detail — "grid" is opt-in per caller and never changes this
   *  default, so other pages using InsightPanel are unaffected. */
  layout?: "list" | "grid"
}

export default function InsightPanel({ cards, isLoading, title, layout = "list" }: InsightPanelProps) {
  const sorted = [...cards].sort((a, b) => a.priority - b.priority)
  const listClassName = layout === "grid" ? "grid grid-cols-1 md:grid-cols-2 gap-4" : "space-y-2"

  return (
    <div className="space-y-2">
      {title && (
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{title}</div>
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-gray-400 text-xs py-4">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading insights…
        </div>
      ) : sorted.length === 0 ? (
        <div className="text-xs text-gray-400 py-3 text-center bg-gray-50 rounded-lg border border-dashed border-gray-200">
          No insights available for current selection.
        </div>
      ) : (
        <div className={listClassName}>
          {sorted.map(card => <InsightCard key={card.template_id} card={card} />)}
        </div>
      )}
    </div>
  )
}
