import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  Sparkles, ArrowRight, MessageSquare, Clock,
  BarChart2, AlertCircle, ChevronRight,
} from "lucide-react"
import { queryKeys } from "@/lib/query-keys"
import {
  healthApi, insightsApi, chatApi, rankingRunsApi,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import InsightCard from "@/components/insights/InsightCard"

// ── Language-rule compliant quick-action labels (no "recommend", "buy", "sell") ──
const QUICK_ACTIONS = [
  { label: "Show structurally improving large cap funds", to: "/rankings" },
  { label: "What changed this month?", to: "/rankings" },
  { label: "Compare SBI and HDFC schemes", to: "/compare" },
  { label: "Build a new rule", to: "/rule-lab" },
] as const


// ── Shared card shell ──────────────────────────────────────────────────────────
function CardShell({
  icon: Icon,
  title,
  linkLabel,
  linkTo,
  children,
  className,
}: {
  icon: React.ElementType
  title: string
  linkLabel?: string
  linkTo?: string
  children: React.ReactNode
  className?: string
}) {
  const navigate = useNavigate()
  return (
    <div className={cn("bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-3", className)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-blue-500 flex-shrink-0" />
          <span className="text-sm font-semibold text-gray-800">{title}</span>
        </div>
        {linkLabel && linkTo && (
          <button
            onClick={() => navigate(linkTo)}
            className="text-xs text-blue-600 hover:underline flex-shrink-0"
          >
            {linkLabel}
          </button>
        )}
      </div>
      {children}
    </div>
  )
}

function LoadingState({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 bg-gray-100 rounded-lg" />
      ))}
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-red-500 py-3">
      <AlertCircle className="h-4 w-4 flex-shrink-0" />
      {message}
    </div>
  )
}

function EmptyState({ message, cta, ctaTo }: { message: string; cta?: string; ctaTo?: string }) {
  const navigate = useNavigate()
  return (
    <div className="text-center py-4">
      <p className="text-xs text-gray-400">{message}</p>
      {cta && ctaTo && (
        <button
          onClick={() => navigate(ctaTo)}
          className="mt-2 text-xs text-blue-600 hover:underline"
        >
          {cta} →
        </button>
      )}
    </div>
  )
}

// ── Daily Briefing Card ────────────────────────────────────────────────────────
function DailyBriefingCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.home.dailyBriefing,
    queryFn: () => insightsApi.getWorkspaceBriefing(),
    staleTime: 5 * 60_000,
  })

  const cards = data?.cards ?? []

  return (
    <CardShell
      icon={Sparkles}
      title="Daily Briefing"
      linkLabel="View all"
      linkTo="/chat"
    >
      {isLoading ? (
        <LoadingState rows={3} />
      ) : isError ? (
        <ErrorState message="Could not load daily briefing." />
      ) : cards.length === 0 ? (
        <EmptyState
          message="No insights available for today."
          cta="Go to Research Chat"
          ctaTo="/chat"
        />
      ) : (
        <div className="space-y-2">
          {cards.slice(0, 4).map((card) => (
            <InsightCard key={`${card.template_id}-${card.compact_text}`} card={card} />
          ))}
        </div>
      )}
      {data && (
        <p className="text-[10px] text-gray-400">
          Evaluated: {data.evaluation_date}
        </p>
      )}
    </CardShell>
  )
}

// ── Recent Chats Card ───────────────────────────────────────────────────────────
function RecentChatsCard() {
  const navigate = useNavigate()
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.home.recentChats,
    queryFn: () => chatApi.getRecentThreads(5),
    staleTime: 60_000,
  })
  const threads = data?.threads ?? []

  return (
    <CardShell icon={MessageSquare} title="Recent Chats">
      {isLoading ? (
        <LoadingState rows={3} />
      ) : isError ? (
        <ErrorState message="Could not load recent chats." />
      ) : threads.length === 0 ? (
        <EmptyState
          message="No chats yet."
          cta="Open Research Chat to start one"
          ctaTo="/chat"
        />
      ) : (
        <ul className="space-y-1">
          {threads.map((t) => (
            <li key={t.thread_id}>
              <button
                onClick={() => navigate(`/chat?thread=${t.thread_id}`)}
                className="w-full flex items-center gap-2 rounded-lg px-3 py-2 hover:bg-gray-50 text-xs text-left"
              >
                <Clock className="h-3 w-3 text-blue-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-gray-700 font-medium truncate">{t.title}</div>
                  <div className="text-gray-400 text-[10px]">
                    {new Date(t.updated_at).toLocaleDateString("en-IN", {
                      day: "2-digit", month: "short", year: "numeric",
                    })}
                  </div>
                </div>
                <ChevronRight className="h-3 w-3 text-gray-300 flex-shrink-0" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </CardShell>
  )
}

// ── Recent Ranking Runs Table ──────────────────────────────────────────────────
function RecentRankingRunsCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.home.rankingRuns,
    queryFn: () => rankingRunsApi.recent(6),
    staleTime: 5 * 60_000,
  })
  const runs = data?.runs ?? []

  return (
    <CardShell icon={BarChart2} title="Recent Fund Rankings" linkLabel="Rankings" linkTo="/rankings">
      {isLoading ? (
        <LoadingState rows={4} />
      ) : isError ? (
        <ErrorState message="Could not load ranking runs." />
      ) : runs.length === 0 ? (
        <EmptyState
          message="No ranking runs recorded yet."
          cta="View Rankings"
          ctaTo="/rankings"
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] text-gray-400 uppercase tracking-wide border-b border-gray-100">
                <th className="text-left pb-2 font-medium">Category</th>
                <th className="text-right pb-2 font-medium pr-3">Date</th>
                <th className="text-right pb-2 font-medium pr-3">Funds</th>
                <th className="text-right pb-2 font-medium">Avg Score</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {runs.map((run, i) => (
                <tr key={`${run.run_date}-${run.category}-${i}`} className="hover:bg-gray-50">
                  <td className="py-1.5 pr-3">
                    <span className="text-gray-700 font-medium truncate block max-w-[160px]">
                      {run.category}
                    </span>
                    <span className="text-[10px] text-gray-400">{run.sort_basis}</span>
                  </td>
                  <td className="py-1.5 pr-3 text-right text-gray-500 whitespace-nowrap">
                    {new Date(run.run_date).toLocaleDateString("en-IN", {
                      day: "2-digit", month: "short",
                    })}
                  </td>
                  <td className="py-1.5 pr-3 text-right font-semibold text-gray-700">
                    {run.fund_count}
                  </td>
                  <td className="py-1.5 text-right text-blue-600 font-semibold">
                    {run.avg_score != null ? run.avg_score.toFixed(4) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data?.data_version && (
        <p className="text-[10px] text-gray-400">Data v{data.data_version}</p>
      )}
    </CardShell>
  )
}

// ── Footer Status Pill ─────────────────────────────────────────────────────────
function FooterStatus() {
  const { data: health } = useQuery({
    queryKey: queryKeys.health,
    queryFn: healthApi.getHealth,
    refetchInterval: 30_000,
  })
  const { data: version } = useQuery({
    queryKey: queryKeys.version,
    queryFn: healthApi.getVersion,
  })

  const online = health?.status === "ok"

  return (
    <div className="flex items-center gap-3 text-xs text-gray-400">
      <span
        className={cn(
          "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-medium",
          online
            ? "bg-green-50 border-green-200 text-green-700"
            : "bg-red-50 border-red-200 text-red-600",
        )}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", online ? "bg-green-500" : "bg-red-400")} />
        MFit AI Engine — {online ? "All systems operational" : "API offline"}
      </span>
      {version && (
        <>
          <span>·</span>
          <span>Data v{version.data_version}</span>
          <span>·</span>
          <span>Rules v{version.rule_version}</span>
          <span>·</span>
          <span>As of {version.as_of_date}</span>
        </>
      )}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function HomePage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState("")

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">

      {/* ── Hero command bar ── */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <div className="text-center mb-5">
          <div className="flex items-center justify-center gap-2 mb-1">
            <Sparkles className="h-5 w-5 text-blue-500" />
            <h1 className="text-xl font-semibold text-gray-900">MFit Research Workspace</h1>
          </div>
          <p className="text-sm text-gray-500">
            Ask about funds, rankings, holdings, rules, or data
          </p>
        </div>

        {/* Command bar */}
        <div className="flex items-center gap-2 border border-blue-300 rounded-xl px-4 py-3 bg-blue-50/40 max-w-2xl mx-auto mb-4 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-300">
          <Sparkles className="h-4 w-4 text-blue-500 flex-shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask MFit anything about funds, rankings, rules, or data…"
            className="flex-1 bg-transparent outline-none text-sm text-gray-700 placeholder:text-gray-400"
            onKeyDown={(e) => {
              if (e.key === "Enter" && query.trim()) {
                navigate(`/chat?from=home&q=${encodeURIComponent(query.trim())}`)
              }
            }}
          />
          <button
            onClick={() => query.trim() && navigate(`/chat?from=home&q=${encodeURIComponent(query.trim())}`)}
            className="h-7 w-7 bg-blue-600 rounded-lg flex items-center justify-center text-white hover:bg-blue-700 flex-shrink-0"
            aria-label="Submit query"
          >
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Quick-action chips */}
        <div className="flex flex-wrap gap-2 justify-center mb-5">
          {QUICK_ACTIONS.map((a) => (
            <button
              key={a.label}
              onClick={() => navigate(a.to)}
              className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded-full px-3 py-1.5 hover:bg-blue-100 transition-colors"
            >
              {a.label}
            </button>
          ))}
        </div>

        {/* 3-step guided pills */}
        <div className="flex items-center justify-center gap-4 text-xs text-gray-400">
          {(["Ask MFit", "Review insights", "Open a workspace"] as const).map((step, i) => (
            <div key={step} className="flex items-center gap-4">
              <div className="flex flex-col items-center gap-1">
                <div
                  className={cn(
                    "h-6 w-6 rounded-full flex items-center justify-center text-[11px] font-bold",
                    i === 0 ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-400",
                  )}
                >
                  {i + 1}
                </div>
                <span>{step}</span>
              </div>
              {i < 2 && <ArrowRight className="h-3 w-3 text-gray-300 -mt-4" />}
            </div>
          ))}
        </div>
      </div>

      {/* ── Card grid — Daily Briefing + Recent Fund Rankings + Recent Chats ── */}
      <div className="grid grid-cols-3 gap-4">
        <DailyBriefingCard />
        <RecentRankingRunsCard />
        <RecentChatsCard />
      </div>

      {/* ── Footer status pill ── */}
      <FooterStatus />
    </div>
  )
}
