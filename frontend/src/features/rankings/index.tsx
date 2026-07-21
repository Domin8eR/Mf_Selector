import { useState, useMemo, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  ArrowUp, ArrowDown, Minus, ChevronRight, ChevronUp, ChevronDown,
  Search, Info, BarChart2, CheckSquare, MessageSquare, X, Maximize2,
} from "lucide-react"
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from "recharts"
import { cn } from "@/lib/utils"
import {
  rankingsV2Api, insightsApi, metricsApiV2, schemesApi,
  type RankedFund, type ExplainComponent, type GrowthPoint,
  type RankHistorySeries,
} from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"
import InsightPanel from "@/components/insights/InsightPanel"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { formatAxisDate, formatTooltipDate } from "@/features/funds/utils"
import {
  historySpanDays, historySpanLabel, lineColor, shortFundName, toScoreChartRows,
  LINE_COLORS,
} from "./utils"

// ── Category options ──────────────────────────────────────────────────────────
// The full category_taxonomy_current.bucket_36 / bucket_group taxonomy is
// fetched live from /rankings/categories (real ranked-fund counts per
// category) — no hardcoded list here. Every endpoint (main list, explain,
// history, what-changed, category insights) now takes the same real
// bucket_36 value directly — no legacy-string translation. Trend panels
// (bump chart / what-changed) only show data once a category has been
// recomputed more than once (each rule approval or pipeline run adds one
// real data point); they degrade to "no data yet" honestly otherwise.
type Category = string

// ── Status badge colours ──────────────────────────────────────────────────────
const STATUS_COLOURS: Record<string, string> = {
  Strong:  "bg-emerald-50 text-emerald-700 border border-emerald-200",
  Good:    "bg-blue-50   text-blue-700   border border-blue-200",
  Neutral: "bg-gray-50   text-gray-600   border border-gray-300",
  Weak:    "bg-red-50    text-red-700    border border-red-200",
}

type SortKey = "rank" | "composite_score" | "ir_3yr" | "sharpe_3yr"
               | "active_ret_3yr" | "ir_slope_6m_proxy" | "tracking_error_3yr" | "aum_cr"
               | "score_change"

type DrawerTab = "overview" | "explain-rank"

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "—"
  return v.toFixed(decimals)
}

// Score change: HIGHER is better (unlike rank delta, where lower is better) —
// positive = improvement (green), negative = decline (red). null means the
// fund has only one real snapshot under the current formula (insufficient
// history), not a zero change — never render it as "0".
function fmtScoreChange(v: number | null | undefined): React.ReactNode {
  if (v == null) return <span className="text-gray-400 text-[11px]">Insufficient history</span>
  if (v > 0) return <span className="text-emerald-600 text-xs font-semibold">+{v.toFixed(1)}</span>
  if (v < 0) return <span className="text-red-500 text-xs font-semibold">{v.toFixed(1)}</span>
  return <span className="text-gray-400 text-xs">0.0</span>
}

function fmtDelta(v: number | null | undefined): React.ReactNode {
  if (v == null) return <Minus className="h-3 w-3 text-gray-300 mx-auto" />
  if (v < 0) return (
    <span className="flex items-center gap-0.5 text-emerald-600 text-xs font-semibold justify-center">
      <ArrowUp className="h-3 w-3" />{Math.abs(v)}
    </span>
  )
  if (v > 0) return (
    <span className="flex items-center gap-0.5 text-red-500 text-xs font-semibold justify-center">
      <ArrowDown className="h-3 w-3" />{v}
    </span>
  )
  return <span className="text-gray-400 text-xs">0</span>
}

function SortIcon({ col, active, dir }: { col: string; active: string; dir: "asc" | "desc" }) {
  if (col !== active) return <ChevronDown className="h-3 w-3 text-gray-300" />
  return dir === "asc"
    ? <ChevronUp className="h-3 w-3 text-indigo-500" />
    : <ChevronDown className="h-3 w-3 text-indigo-500" />
}

// ── Fund Preview Drawer (Overview + Explain Rank tabs) ────────────────────────
function FundPreviewDrawer({
  schemecode,
  fundName,
  category,
  defaultTab = "overview",
  onClose,
}: {
  schemecode: number
  fundName: string
  category: string
  defaultTab?: DrawerTab
  onClose: () => void
}) {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<DrawerTab>(defaultTab)
  const fundId = String(schemecode)

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [onClose])

  // Explain Rank query
  const explainQ = useQuery({
    queryKey: queryKeys.rankings.explain(schemecode, category),
    queryFn: () => rankingsV2Api.explain(schemecode, category),
  })

  // Overview queries — same keys as Fund Detail so cache is shared
  const summaryQ = useQuery({
    queryKey: queryKeys.funds.summaryV2(fundId),
    queryFn: () => metricsApiV2.getSummaryV2(fundId),
  })
  const growthQ = useQuery({
    queryKey: queryKeys.funds.growthOf10k(fundId, "3Y"),
    queryFn: () => metricsApiV2.getGrowthOf10k(fundId, "3Y"),
  })
  const holdingsQ = useQuery({
    queryKey: queryKeys.funds.holdingsV2(fundId),
    queryFn: () => schemesApi.getHoldingsV2(fundId, 20),
  })
  const insightsQ = useQuery({
    queryKey: queryKeys.funds.insights(fundId),
    queryFn: () => insightsApi.getFundInsights(schemecode),
  })

  const summary = summaryQ.data
  const growth = growthQ.data
  const holdings = holdingsQ.data
  const insights = insightsQ.data
  const explainData = explainQ.data

  const growthChartData = growth ? (() => {
    const bmMap = new Map<string, number>(
      growth.benchmark_series.map((p: GrowthPoint) => [p.date, p.value])
    )
    return growth.fund_series.map((p: GrowthPoint) => ({
      date: p.date.slice(0, 7),
      fund: p.value,
      bm: bmMap.get(p.date) ?? null,
    }))
  })() : []

  const miniCards = summary ? [
    { label: "IR (3Y)",        value: summary.information_ratio_3yr != null ? summary.information_ratio_3yr.toFixed(3) : "—" },
    { label: "IR Slope",       value: summary.ir_slope_6m_proxy != null ? summary.ir_slope_6m_proxy.toFixed(4) : "—" },
    { label: "Active Ret (3Y)",value: summary.active_3yr_ret != null ? `${summary.active_3yr_ret.toFixed(2)}%` : "—" },
    { label: "Sharpe (3Y)",    value: summary.sharpe_ratio_3yr != null ? summary.sharpe_ratio_3yr.toFixed(3) : "—" },
  ] : []

  const top5Holdings = (holdings?.holdings ?? []).slice(0, 5)
  const top2Insights = (insights?.cards ?? []).slice(0, 2)

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative z-10 w-full max-w-lg bg-white shadow-2xl flex flex-col">

        {/* ── Header ─────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h2 className="text-sm font-semibold text-gray-900 leading-tight truncate pr-2">{fundName}</h2>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 shrink-0">
            <X className="h-4 w-4 text-gray-500" />
          </button>
        </div>

        {/* ── Tab bar ────────────────────────────────────────────── */}
        <div className="flex border-b shrink-0 bg-gray-50">
          {(["overview", "explain-rank"] as DrawerTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-5 py-2.5 text-xs font-medium border-b-2 transition-colors",
                activeTab === tab
                  ? "border-indigo-500 text-indigo-700 bg-white"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              )}
            >
              {tab === "overview" ? "Overview" : "Explain Rank"}
            </button>
          ))}
        </div>

        {/* ── Tab content ────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto">

          {/* ═══ OVERVIEW ═══════════════════════════════════════════ */}
          {activeTab === "overview" && (
            <div className="px-5 py-4 space-y-5">

              {/* Fund header */}
              {summaryQ.isLoading ? (
                <div className="space-y-2">
                  <div className="h-3.5 w-48 animate-pulse bg-gray-100 rounded" />
                  <div className="h-3 w-32 animate-pulse bg-gray-100 rounded" />
                </div>
              ) : summaryQ.isError ? (
                <p className="text-xs text-red-500">Unable to load fund summary.</p>
              ) : summary ? (
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-700 truncate">{summary.amc_name}</p>
                    <p className="text-[11px] text-gray-500 mt-0.5 truncate">{summary.category}</p>
                    {summary.benchmark && (
                      <p className="text-[10px] text-gray-400 mt-0.5 truncate">vs {summary.benchmark}</p>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    {summary.rank_in_category != null && summary.total_in_category != null && (
                      <span className="text-xs font-semibold text-indigo-700">
                        Rank {summary.rank_in_category}/{summary.total_in_category}
                      </span>
                    )}
                    {summary.composite_score != null && (
                      <span className="text-[10px] text-gray-500">
                        Score {summary.composite_score.toFixed(1)}
                      </span>
                    )}
                    {summary.tier && (
                      <span className={cn(
                        "text-[10px] px-1.5 py-0.5 rounded-full font-medium",
                        STATUS_COLOURS[summary.tier] ?? "bg-gray-50 text-gray-600 border border-gray-200"
                      )}>
                        {summary.tier}
                      </span>
                    )}
                  </div>
                </div>
              ) : null}

              {/* 4 metric mini-cards */}
              {summaryQ.isLoading ? (
                <div className="grid grid-cols-2 gap-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="h-14 animate-pulse bg-gray-100 rounded-lg" />
                  ))}
                </div>
              ) : miniCards.length > 0 ? (
                <div className="grid grid-cols-2 gap-2">
                  {miniCards.map((c) => (
                    <div key={c.label} className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5">
                      <p className="text-[10px] text-gray-500 uppercase tracking-wide leading-tight">{c.label}</p>
                      <p className="text-sm font-semibold text-gray-800 font-mono mt-1">{c.value}</p>
                    </div>
                  ))}
                </div>
              ) : null}

              {/* Growth of ₹10,000 (3Y) chart — compact */}
              <div>
                <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
                  Growth of ₹10,000 (3Y)
                </p>
                {growthQ.isLoading ? (
                  <div className="h-36 animate-pulse bg-gray-100 rounded-lg" />
                ) : growthQ.isError ? (
                  <p className="text-xs text-red-500 py-2">Unable to load chart data.</p>
                ) : growthChartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={148}>
                    <LineChart data={growthChartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis
                        dataKey="date"
                        tick={{ fontSize: 8, fill: "#9ca3af" }}
                        tickLine={false}
                        interval="preserveStartEnd"
                      />
                      <YAxis
                        tick={{ fontSize: 8, fill: "#9ca3af" }}
                        tickLine={false}
                        axisLine={false}
                        width={40}
                        tickFormatter={(v: number) => `₹${(v / 1000).toFixed(1)}k`}
                      />
                      <Tooltip
                        formatter={(v: unknown) => [
                          `₹${(v as number).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`,
                          "",
                        ]}
                        contentStyle={{ fontSize: 9 }}
                      />
                      <Line dataKey="fund" name="Fund" stroke="#2563eb" dot={false} strokeWidth={2} />
                      <Line
                        dataKey="bm"
                        name={growth?.benchmark_name ?? "Benchmark"}
                        stroke="#9333ea"
                        dot={false}
                        strokeWidth={1.5}
                        strokeDasharray="4 2"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="text-xs text-gray-400 py-2">No chart data available.</p>
                )}
              </div>

              {/* Top 5 holdings */}
              <div>
                <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
                  Top Holdings
                  {holdings?.as_of_date && (
                    <span className="ml-1.5 text-[10px] text-gray-400 normal-case font-normal">
                      as of {holdings.as_of_date}
                    </span>
                  )}
                </p>
                {holdingsQ.isLoading ? (
                  <div className="space-y-1.5">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <div key={i} className="h-5 animate-pulse bg-gray-100 rounded" />
                    ))}
                  </div>
                ) : holdingsQ.isError ? (
                  <p className="text-xs text-red-500">Unable to load holdings.</p>
                ) : top5Holdings.length === 0 ? (
                  <p className="text-xs text-gray-400">No holdings data available.</p>
                ) : (
                  <div className="space-y-1.5">
                    {top5Holdings.map((h, i) => (
                      <div key={i} className="flex items-start justify-between text-xs gap-2">
                        <div className="min-w-0">
                          <span className="text-gray-800 font-medium block truncate">{h.company_name}</span>
                          {h.sector && (
                            <span className="text-[10px] text-gray-400">{h.sector}</span>
                          )}
                        </div>
                        <span className="font-mono text-gray-600 shrink-0">{h.weight_pct.toFixed(2)}%</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Up to 2 FUND_* insight cards */}
              {(insightsQ.isLoading || top2Insights.length > 0) && (
                <div>
                  <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">
                    <BarChart2 className="inline h-3.5 w-3.5 mr-1 text-gray-500" />
                    Insights
                  </p>
                  <InsightPanel cards={top2Insights} isLoading={insightsQ.isLoading} />
                </div>
              )}

              {/* View full details */}
              <button
                onClick={() => navigate(`/funds/${schemecode}`)}
                className="w-full flex items-center justify-center gap-1.5 px-4 py-2.5 text-sm font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg border border-indigo-200 transition"
              >
                View full details <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}

          {/* ═══ EXPLAIN RANK (unchanged from original ExplainDrawer) ══════ */}
          {activeTab === "explain-rank" && (
            <div className="px-5 py-4 space-y-5">
              {explainQ.isLoading ? (
                <div className="flex items-center justify-center py-12 text-gray-400 text-sm">
                  Loading breakdown…
                </div>
              ) : !explainData ? (
                <div className="flex items-center justify-center py-12 text-gray-400 text-sm">
                  No data available.
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap gap-2">
                    <span className="px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 text-xs font-medium border border-indigo-200">
                      Rank {explainData.rank} / {explainData.total_in_category}
                    </span>
                    <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium", STATUS_COLOURS[explainData.status_label] ?? "bg-gray-50 text-gray-600 border border-gray-200")}>
                      {explainData.status_label}
                    </span>
                    <span className="px-2 py-0.5 rounded-full bg-gray-50 text-gray-700 text-xs border border-gray-200">
                      Score {explainData.composite_score.toFixed(1)} / 100
                    </span>
                    <span className="px-2 py-0.5 rounded-full bg-gray-50 text-gray-600 text-xs border border-gray-200">
                      Confidence: {explainData.confidence}
                    </span>
                  </div>

                  <div>
                    <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-3">
                      Score Breakdown
                    </p>
                    <div className="space-y-3">
                      {explainData.components.map((c: ExplainComponent) => (
                        <div key={c.component_id}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs text-gray-600">{c.label_display}</span>
                            <span className="text-xs font-mono text-gray-800">
                              +{c.contribution.toFixed(2)} pts
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-indigo-500 rounded-full"
                                style={{ width: `${Math.min(c.percentile_score, 100)}%` }}
                              />
                            </div>
                            <span className="text-xs text-gray-500 w-14 text-right">
                              {c.percentile_score.toFixed(0)}th pct
                            </span>
                          </div>
                          <div className="flex items-center justify-between mt-0.5">
                            <span className="text-[10px] text-gray-400">
                              Raw: {c.raw_value != null ? c.raw_value.toFixed(4) : "—"}
                              &nbsp;·&nbsp;weight {(c.weight * 100).toFixed(0)}%
                              &nbsp;·&nbsp;{c.direction === "higher_better" ? "↑ higher = better" : "↓ lower = better"}
                            </span>
                          </div>
                          {c.data_note && (
                            <p className="text-[10px] text-amber-600 mt-0.5 flex items-start gap-0.5">
                              <Info className="h-3 w-3 mt-0.5 shrink-0" />
                              {c.data_note}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="bg-gray-50 rounded-lg p-3 text-[11px] text-gray-500 space-y-0.5 border border-gray-100">
                    <p><span className="font-medium text-gray-700">Rule version:</span> {explainData.rule_version}</p>
                    <p><span className="font-medium text-gray-700">Evaluated on:</span> {explainData.evaluation_date}</p>
                    <p><span className="font-medium text-gray-700">Data version:</span> {explainData.data_version} · calc {explainData.calculation_version}</p>
                    <p className="text-[10px] text-gray-400 mt-1">
                      Scores are pre-computed percentile ranks within category — no AI was used in metric calculation.
                    </p>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Fullscreen chart overlay ───────────────────────────────────────────────────
// Plain CSS/Tailwind entrance animation via the tailwindcss-animate plugin
// already used by this app's Dialog/Sheet primitives (fade + zoom + slight
// slide-up) — no new animation library. Escape key or the close button exits.
function ChartFullscreenOverlay({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-6 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="relative bg-white rounded-2xl shadow-2xl w-full max-w-5xl max-h-[85vh] overflow-auto p-6 animate-in zoom-in-95 slide-in-from-bottom-4 duration-300"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-gray-100"
            aria-label="Close fullscreen"
          >
            <X className="h-4 w-4 text-gray-500" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

function MaximizeButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
      title="Maximize"
      aria-label="Maximize chart"
    >
      <Maximize2 className="h-3 w-3" />
    </button>
  )
}

// ── Bump Chart (Rank History) ─────────────────────────────────────────────────
function BumpChart({ category, height = 240, onMaximize }: {
  category: string
  height?: number
  onMaximize?: () => void
}) {
  const TOP_N = 10
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.rankings.history(category, TOP_N, "latest"),
    queryFn: () => rankingsV2Api.getHistory(category, TOP_N, "latest"),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-xs">
        Loading rank history…
      </div>
    )
  }
  if (!data || !data.series.length) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-xs">
        No history data yet.
      </div>
    )
  }

  const chartData = data.dates.map((dt) => {
    const point: Record<string, string | number | null> = { date: dt.slice(0, 10) }
    data.series.forEach((s) => {
      const dp = s.data.find((d) => d.date === dt)
      point[s.fund_name] = dp?.rank ?? null
    })
    return point
  })

  const isShortSpan = historySpanDays(data.dates) < 365

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
          Rank History — Top {TOP_N} ({historySpanLabel(data.dates)})
        </p>
        {onMaximize && <MaximizeButton onClick={onMaximize} />}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: "#9ca3af" }}
            tickFormatter={(v: string) => formatAxisDate(v, isShortSpan)}
          />
          <YAxis
            reversed
            tick={{ fontSize: 9, fill: "#9ca3af" }}
            tickCount={6}
            domain={["dataMin - 1", "dataMax + 1"]}
          />
          <Tooltip
            formatter={(v: unknown, name: string) => [`Rank ${v ?? "—"}`, shortFundName(name)]}
            labelFormatter={(l: string) => `Date: ${formatTooltipDate(l)}`}
            contentStyle={{ fontSize: 10 }}
          />
          {data.series.map((s, i) => (
            <Line
              key={s.schemecode}
              type="monotone"
              dataKey={s.fund_name}
              stroke={LINE_COLORS[i % LINE_COLORS.length]}
              strokeWidth={s.latest_rank === 1 ? 2.5 : 1.5}
              dot={false}
              activeDot={{ r: 3 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <div className="mt-2 space-y-0.5">
        {data.series.map((s, i) => (
          <div key={s.schemecode} className="flex items-center gap-1.5 text-[10px] text-gray-600">
            <span
              className="inline-block w-3 h-0.5 rounded"
              style={{ background: LINE_COLORS[i % LINE_COLORS.length] }}
            />
            <span className="truncate" title={s.fund_name}>{shortFundName(s.fund_name)}</span>
            <span className="ml-auto text-gray-400 shrink-0">#{s.latest_rank}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Score History chart ────────────────────────────────────────────────────────
// Union of top-10 across every real snapshot date (not just the latest) —
// naturally >10 lines if top-10 membership shifted month to month. A fund
// missing a score on some date gets a REAL gap (no connectNulls) rather
// than a fabricated bridge, since Recharts only draws between consecutive
// non-null points when connectNulls is absent/false.
function ScoreHistoryChart({ category, height = 240, onMaximize }: {
  category: string
  height?: number
  onMaximize?: () => void
}) {
  const TOP_N = 10
  const [hovered, setHovered] = useState<number | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.rankings.history(category, TOP_N, "union"),
    queryFn: () => rankingsV2Api.getHistory(category, TOP_N, "union"),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-xs">
        Loading score history…
      </div>
    )
  }

  if (!data || data.dates.length < 2) {
    const msg = !data || data.dates.length === 0
      ? "No history data yet for this category."
      : "Not enough history yet to show a trend — only 1 real snapshot exists for this category so far."
    return (
      <div className="flex flex-col items-center justify-center h-48 text-center px-4 gap-1">
        <Info className="h-4 w-4 text-gray-300" />
        <p className="text-xs text-gray-400 max-w-[220px]">{msg}</p>
      </div>
    )
  }

  const series: RankHistorySeries[] = data.series
  const chartData = toScoreChartRows(data.dates, series)

  const isShortSpan = historySpanDays(data.dates) < 365
  const isLargeLegend = series.length > 15

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
          Score History — Top {TOP_N} union ({historySpanLabel(data.dates)})
        </p>
        {onMaximize && <MaximizeButton onClick={onMaximize} />}
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: "#9ca3af" }}
            tickFormatter={(v: string) => formatAxisDate(v, isShortSpan)}
          />
          <YAxis
            tick={{ fontSize: 9, fill: "#9ca3af" }}
            tickCount={6}
            domain={["dataMin - 2", "dataMax + 2"]}
          />
          <Tooltip
            formatter={(v: unknown, name: string) => [v == null ? "No data" : (v as number).toFixed(1), shortFundName(name)]}
            labelFormatter={(l: string) => `Date: ${formatTooltipDate(l)}`}
            contentStyle={{ fontSize: 10 }}
          />
          {series.map((s, i) => (
            <Line
              key={s.schemecode}
              type="monotone"
              dataKey={s.fund_name}
              stroke={lineColor(i)}
              strokeWidth={hovered === s.schemecode ? 3 : s.latest_rank === 1 ? 2.5 : 1.5}
              strokeOpacity={hovered == null || hovered === s.schemecode ? 1 : 0.15}
              dot={false}
              activeDot={{ r: 3 }}
              // No connectNulls: a fund missing a score on some real date
              // (wasn't top-10 that month, or is new since) shows a real
              // visual gap rather than an implied/interpolated value.
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <div
        className={cn(
          "mt-2 space-y-0.5",
          isLargeLegend && "max-h-32 overflow-y-auto pr-1"
        )}
      >
        {series.map((s, i) => (
          <div
            key={s.schemecode}
            className="flex items-center gap-1.5 text-[10px] text-gray-600 cursor-default rounded px-0.5 hover:bg-gray-50"
            onMouseEnter={() => setHovered(s.schemecode)}
            onMouseLeave={() => setHovered(null)}
          >
            <span
              className="inline-block w-3 h-0.5 rounded shrink-0"
              style={{ background: lineColor(i) }}
            />
            <span className="truncate" title={s.fund_name}>{shortFundName(s.fund_name)}</span>
            <span className="ml-auto text-gray-400 shrink-0">
              {s.latest_rank != null ? `#${s.latest_rank}` : "dropped out"}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Rank/Score History panel — tabs + shared fullscreen ───────────────────────
function RankingHistoryPanel({ category }: { category: string }) {
  const [tab, setTab] = useState<"rank" | "score">("rank")
  const [fullscreen, setFullscreen] = useState(false)

  return (
    <div>
      <Tabs value={tab} onValueChange={(v) => setTab(v as "rank" | "score")}>
        <TabsList className="h-8 mb-1">
          <TabsTrigger value="rank" className="text-xs px-2.5 py-1">Rank History</TabsTrigger>
          <TabsTrigger value="score" className="text-xs px-2.5 py-1">Score History</TabsTrigger>
        </TabsList>
        <TabsContent value="rank">
          <BumpChart category={category} onMaximize={() => setFullscreen(true)} />
        </TabsContent>
        <TabsContent value="score">
          <ScoreHistoryChart category={category} onMaximize={() => setFullscreen(true)} />
        </TabsContent>
      </Tabs>

      {fullscreen && (
        <ChartFullscreenOverlay
          title={tab === "rank" ? "Rank History" : "Score History"}
          onClose={() => setFullscreen(false)}
        >
          {tab === "rank"
            ? <BumpChart category={category} height={480} />
            : <ScoreHistoryChart category={category} height={480} />}
        </ChartFullscreenOverlay>
      )}
    </div>
  )
}

// ── Change Summary Strip ──────────────────────────────────────────────────────
function ChangeSummaryStrip({ category }: { category: string }) {
  const { data } = useQuery({
    queryKey: queryKeys.rankings.whatChanged(category),
    queryFn: () => rankingsV2Api.getWhatChanged(category),
  })

  if (!data?.has_data) return null

  const directionClass = (d: string) =>
    d === "positive" ? "text-emerald-600"
    : d === "negative" ? "text-red-500"
    : "text-gray-700"

  return (
    <div className="grid grid-cols-3 gap-3 mb-4">
      {data.tiles.map((tile) => (
        <div key={tile.key} className="bg-white rounded-xl border border-gray-200 px-4 py-3">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide mb-1 leading-tight">{tile.label}</p>
          <p className={cn("text-2xl font-bold", directionClass(tile.direction))}>
            {typeof tile.value === "number" && tile.unit === "pts"
              ? (tile.value >= 0 ? "+" : "") + tile.value.toFixed(2)
              : tile.value}
            <span className="text-xs font-normal text-gray-400 ml-1">{tile.unit}</span>
          </p>
          <p className="text-[10px] text-gray-400 mt-0.5 leading-tight">{tile.description}</p>
        </div>
      ))}
    </div>
  )
}

// ── Fund table row ────────────────────────────────────────────────────────────
function FundRow({
  fund,
  isSelected,
  onToggleSelect,
  onRowClick,
  onExplain,
}: {
  fund: RankedFund
  isSelected: boolean
  onToggleSelect: () => void
  onRowClick: () => void
  onExplain: () => void
}) {
  const rank = fund.rank
  const rankBg =
    rank === 1 ? "bg-yellow-50 text-yellow-700 border-yellow-200 font-bold"
    : rank <= 3 ? "bg-emerald-50 text-emerald-700 border-emerald-200 font-semibold"
    : "bg-gray-50 text-gray-500 border-gray-200"

  const slopeColor = (v: number | null) =>
    v == null ? "text-gray-400"
    : v > 0.005 ? "text-emerald-600"
    : v < -0.005 ? "text-red-500"
    : "text-gray-500"

  return (
    <tr
      className={cn(
        "border-b border-gray-50 hover:bg-gray-50/60 transition-colors cursor-pointer",
        isSelected && "bg-indigo-50/30"
      )}
      onClick={onRowClick}
    >
      {/* Checkbox — stop propagation so it doesn't also open the drawer */}
      <td className="px-3 py-2 text-center" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggleSelect}
          className="h-3.5 w-3.5 rounded border-gray-300 text-indigo-600 focus:ring-indigo-400"
        />
      </td>
      <td className="px-3 py-2 text-center">
        <span className={cn("inline-flex items-center justify-center h-6 w-6 rounded-full border text-[11px]", rankBg)}>
          {rank}
        </span>
      </td>
      <td className="px-3 py-2 max-w-[200px]">
        <div className="flex items-start gap-1.5">
          {fund.plan_label && (
            <span
              className={cn(
                "shrink-0 mt-0.5 text-[9px] font-semibold px-1 py-0.5 rounded whitespace-nowrap",
                fund.plan_label === "Direct"
                  ? "bg-indigo-50 text-indigo-600 border border-indigo-200"
                  : "bg-amber-50 text-amber-700 border border-amber-200"
              )}
              title={`${fund.plan_label} Plan — a different investable product (own NAV/expense ratio) from other plans of the same scheme`}
            >
              {fund.plan_label}
            </span>
          )}
          <span
            className="text-xs font-medium text-gray-900 line-clamp-2"
            title={fund.fund_name}
          >
            {fund.fund_name}
          </span>
        </div>
      </td>
      <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{fund.amc_name}</td>
      <td className="px-3 py-2 text-xs font-mono text-gray-700 text-right whitespace-nowrap">
        {fund.aum_cr != null ? `₹${fund.aum_cr.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : <span className="text-gray-400">—</span>}
      </td>
      <td className="px-3 py-2 text-xs font-mono text-gray-700 text-right">{fmtNum(fund.ir_3yr, 3)}</td>
      <td className="px-3 py-2 text-xs font-mono text-gray-700 text-right">{fmtNum(fund.sharpe_3yr, 3)}</td>
      <td className="px-3 py-2 text-xs font-mono text-right">
        {fund.active_ret_3yr != null
          ? <span className={fund.active_ret_3yr >= 0 ? "text-emerald-600" : "text-red-500"}>
              {fund.active_ret_3yr >= 0 ? "+" : ""}{fmtNum(fund.active_ret_3yr, 2)}%
            </span>
          : <span className="text-gray-400">—</span>}
      </td>
      <td className="px-3 py-2 text-xs font-mono text-gray-700 text-right">{fmtNum(fund.tracking_error_3yr, 3)}</td>
      <td className="px-3 py-2 text-xs font-mono text-right">
        <span className={slopeColor(fund.ir_slope_6m_proxy)}>
          {fund.ir_slope_6m_proxy != null
            ? (fund.ir_slope_6m_proxy >= 0 ? "+" : "") + fund.ir_slope_6m_proxy.toFixed(4)
            : "—"}
        </span>
      </td>
      <td className="px-3 py-2">
        <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap", STATUS_COLOURS[fund.status_label] ?? "bg-gray-50 text-gray-600 border border-gray-200")}>
          {fund.status_label}
        </span>
      </td>
      <td className="px-3 py-2 text-xs font-mono text-gray-800 text-right font-semibold">
        {fmtNum(fund.composite_score, 1)}
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {fmtScoreChange(fund.score_change)}
      </td>
      <td className="px-3 py-2 text-center">
        {fmtDelta(fund.rank_delta_6m != null ? -fund.rank_delta_6m : null)}
      </td>
      {/* ChevronRight — icon-only button, stops propagation, opens Explain Rank tab */}
      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={onExplain}
          className="p-1 rounded hover:bg-indigo-50 group transition"
          title="Explain rank"
        >
          <ChevronRight className="h-3.5 w-3.5 text-gray-300 group-hover:text-indigo-500" />
        </button>
      </td>
    </tr>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function CategoryRankingsPage() {
  const navigate = useNavigate()

  const [category, setCategory] = useState<Category>("Large Cap")
  const { data: categoryOptionsData } = useQuery({
    queryKey: queryKeys.rankings.categoryOptions,
    queryFn: () => rankingsV2Api.getCategories(),
    staleTime: 5 * 60_000,
  })
  const categoryOptions = categoryOptionsData?.categories ?? []
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [aumMin, setAumMin] = useState("")
  const [aumMax, setAumMax] = useState("")
  const [appliedAumMin, setAppliedAumMin] = useState<number | null>(null)
  const [appliedAumMax, setAppliedAumMax] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 50

  const [sortKey, setSortKey] = useState<SortKey>("rank")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [previewFund, setPreviewFund] = useState<{
    schemecode: number
    name: string
    defaultTab: DrawerTab
  } | null>(null)

  const { data: rankData, isLoading: rankLoading } = useQuery({
    queryKey: queryKeys.rankings.v2Category(category, undefined, debouncedSearch, page, appliedAumMin, appliedAumMax),
    queryFn: () => rankingsV2Api.getCategory({
      category,
      search: debouncedSearch || undefined,
      aumMinCr: appliedAumMin,
      aumMaxCr: appliedAumMax,
      page,
      pageSize: PAGE_SIZE,
    }),
  })

  const { data: insightData } = useQuery({
    queryKey: queryKeys.rankings.insights(category),
    queryFn: () => insightsApi.getCategoryRankings(category),
  })

  const sortedFunds = useMemo(() => {
    if (!rankData?.results) return []
    const arr = [...rankData.results]
    arr.sort((a, b) => {
      const va = (a[sortKey] ?? (sortDir === "asc" ? Infinity : -Infinity)) as number
      const vb = (b[sortKey] ?? (sortDir === "asc" ? Infinity : -Infinity)) as number
      return sortDir === "asc" ? va - vb : vb - va
    })
    return arr
  }, [rankData?.results, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir(key === "rank" ? "asc" : "desc")
    }
  }

  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      setDebouncedSearch(search)
      setPage(1)
    }
  }

  function applyAumFilter() {
    setAppliedAumMin(aumMin.trim() ? Number(aumMin) : null)
    setAppliedAumMax(aumMax.trim() ? Number(aumMax) : null)
    setPage(1)
  }

  function handleAumKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") applyAumFilter()
  }

  function toggleSelect(sc: number) {
    setSelected((prev) => {
      const n = new Set(prev)
      n.has(sc) ? n.delete(sc) : n.add(sc)
      return n
    })
  }

  function handleCompare() {
    if (selected.size < 2) return
    navigate(`/compare?funds=${Array.from(selected).join(",")}`)
  }

  const totalPages = Math.ceil((rankData?.total ?? 0) / PAGE_SIZE)

  const thClass =
    "text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wide py-2 px-3 " +
    "cursor-pointer select-none whitespace-nowrap hover:text-gray-700"

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* Filter bar */}
      <div className="bg-white border-b border-gray-100 px-6 py-3 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 font-medium">Category</label>
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value as Category)
              setPage(1)
              setSelected(new Set())
              setSearch("")
              setDebouncedSearch("")
            }}
            className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-300"
          >
            {categoryOptions.length === 0 ? (
              <option value={category}>{category}</option>
            ) : (
              (["Overview", "ALL Equity", "ALL Hybrid", "ALL Passive"] as const).map((group) => {
                const opts = group === "Overview"
                  ? categoryOptions.filter((c) => c.is_aggregate)
                  : categoryOptions.filter((c) => c.bucket_group === group)
                if (opts.length === 0) return null
                return (
                  <optgroup key={group} label={group === "Overview" ? "Overview" : group.replace("ALL ", "")}>
                    {opts.map((c) => (
                      <option
                        key={c.key}
                        value={c.key}
                        style={c.ranked_count === 0 ? { color: "#9ca3af" } : undefined}
                      >
                        {c.key} ({c.ranked_count})
                      </option>
                    ))}
                  </optgroup>
                )
              })
            )}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 font-medium">Rule Set</label>
          <span className="text-sm text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 bg-gray-50">
            Client Default v1.0
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <label className="text-xs text-gray-500 font-medium">AUM (Cr)</label>
          <input
            type="number"
            placeholder="Min"
            value={aumMin}
            onChange={(e) => setAumMin(e.target.value)}
            onKeyDown={handleAumKeyDown}
            onBlur={applyAumFilter}
            className="w-20 px-2 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300"
          />
          <span className="text-gray-300">–</span>
          <input
            type="number"
            placeholder="Max"
            value={aumMax}
            onChange={(e) => setAumMax(e.target.value)}
            onKeyDown={handleAumKeyDown}
            onBlur={applyAumFilter}
            className="w-20 px-2 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300"
          />
        </div>

        <div className="relative ml-auto">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
          <input
            type="text"
            placeholder="Search fund… (Enter)"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            className="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg w-60 focus:outline-none focus:ring-2 focus:ring-indigo-300"
          />
        </div>

        <button
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50 transition"
          onClick={() => {
            const params = new URLSearchParams({
              from: "rankings",
              category,
              facts_json: JSON.stringify({ category, rule_set: "Client Default v1.0" }),
              required_tools: JSON.stringify(["get_category_rankings", "get_rankings_explain"]),
              forbidden_phrases: JSON.stringify(["recommend", "buy", "sell", "should I invest", "best fund"]),
            })
            navigate(`/chat?${params.toString()}`)
          }}
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Ask this table
        </button>

        <button
          disabled={selected.size < 2}
          onClick={handleCompare}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition border",
            selected.size >= 2
              ? "bg-indigo-600 text-white border-indigo-600 hover:bg-indigo-700"
              : "bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed",
          )}
        >
          <CheckSquare className="h-3.5 w-3.5" />
          {selected.size >= 2 ? `Compare (${selected.size})` : "Compare Selected"}
        </button>
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left: table + KPIs */}
        <div className="flex-1 flex flex-col overflow-hidden px-6 py-4">
          <ChangeSummaryStrip category={category} />

          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-gray-500">
              {rankLoading
                ? "Loading…"
                : `${rankData?.total ?? 0} ranked funds · ${rankData?.evaluation_date ?? ""}`}
            </p>
            {rankData && (
              <p className="text-[10px] text-gray-400">
                Rule {rankData.rule_version} · data v{rankData.data_version}
              </p>
            )}
          </div>

          <div className="flex-1 overflow-auto rounded-xl border border-gray-200 bg-white">
            <table className="w-full text-sm border-collapse min-w-[900px]">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr>
                  <th className="w-8 px-3 py-2" />
                  <th className={thClass} onClick={() => toggleSort("rank")}>
                    <span className="flex items-center gap-1">Rank <SortIcon col="rank" active={sortKey} dir={sortDir} /></span>
                  </th>
                  <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wide py-2 px-3">Scheme</th>
                  <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wide py-2 px-3">AMC</th>
                  <th className={thClass} onClick={() => toggleSort("aum_cr")}>
                    <span className="flex items-center gap-1">AUM (Cr) <SortIcon col="aum_cr" active={sortKey} dir={sortDir} /></span>
                  </th>
                  <th className={thClass} onClick={() => toggleSort("ir_3yr")}>
                    <span className="flex items-center gap-1">IR₃ <SortIcon col="ir_3yr" active={sortKey} dir={sortDir} /></span>
                  </th>
                  <th className={thClass} onClick={() => toggleSort("sharpe_3yr")}>
                    <span className="flex items-center gap-1">Sharpe₃ <SortIcon col="sharpe_3yr" active={sortKey} dir={sortDir} /></span>
                  </th>
                  <th className={thClass} onClick={() => toggleSort("active_ret_3yr")}>
                    <span className="flex items-center gap-1">Active Ret₃ <SortIcon col="active_ret_3yr" active={sortKey} dir={sortDir} /></span>
                  </th>
                  <th className={thClass} onClick={() => toggleSort("tracking_error_3yr")}>
                    <span className="flex items-center gap-1">TE₃↓ <SortIcon col="tracking_error_3yr" active={sortKey} dir={sortDir} /></span>
                  </th>
                  <th className={thClass} onClick={() => toggleSort("ir_slope_6m_proxy")}>
                    <span className="flex items-center gap-1">IR Slope <SortIcon col="ir_slope_6m_proxy" active={sortKey} dir={sortDir} /></span>
                  </th>
                  <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wide py-2 px-3">Status</th>
                  <th className={thClass} onClick={() => toggleSort("composite_score")}>
                    <span className="flex items-center gap-1">Score <SortIcon col="composite_score" active={sortKey} dir={sortDir} /></span>
                  </th>
                  <th className={thClass} onClick={() => toggleSort("score_change")}>
                    <span className="flex items-center gap-1">
                      Δ Score ({rankData?.score_change_window_label ?? "…"})
                      <SortIcon col="score_change" active={sortKey} dir={sortDir} />
                    </span>
                  </th>
                  <th className="text-center text-[10px] font-semibold text-gray-500 uppercase tracking-wide py-2 px-3">6m Δ</th>
                  <th className="w-8 px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {rankLoading ? (
                  <tr>
                    <td colSpan={14} className="text-center py-12 text-gray-400 text-sm">
                      Loading ranked funds…
                    </td>
                  </tr>
                ) : sortedFunds.length === 0 ? (
                  <tr>
                    <td colSpan={14} className="text-center py-12 text-gray-400 text-sm">
                      {debouncedSearch || appliedAumMin != null || appliedAumMax != null
                        ? "No funds match the current filters in this category."
                        : "No ranked funds currently available in this category."}
                    </td>
                  </tr>
                ) : (
                  sortedFunds.map((fund) => (
                    <FundRow
                      key={fund.schemecode}
                      fund={fund}
                      isSelected={selected.has(fund.schemecode)}
                      onToggleSelect={() => toggleSelect(fund.schemecode)}
                      onRowClick={() => setPreviewFund({ schemecode: fund.schemecode, name: fund.fund_name, defaultTab: "overview" })}
                      onExplain={() => setPreviewFund({ schemecode: fund.schemecode, name: fund.fund_name, defaultTab: "explain-rank" })}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-3">
              <p className="text-xs text-gray-500">
                Page {page} of {totalPages} · {rankData?.total} funds
              </p>
              <div className="flex gap-2">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="px-3 py-1 text-xs border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
                >
                  Previous
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  className="px-3 py-1 text-xs border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Right rail */}
        <div className="w-80 shrink-0 border-l border-gray-100 bg-white overflow-y-auto px-4 py-4 space-y-6">
          <RankingHistoryPanel category={category} />

          {insightData && insightData.cards.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-3">
                <BarChart2 className="inline h-3.5 w-3.5 mr-1 text-gray-500" />
                Signals
              </p>
              <InsightPanel cards={insightData.cards} isLoading={false} />
            </div>
          )}
        </div>
      </div>

      {previewFund && (
        <FundPreviewDrawer
          schemecode={previewFund.schemecode}
          fundName={previewFund.name}
          category={category}
          defaultTab={previewFund.defaultTab}
          onClose={() => setPreviewFund(null)}
        />
      )}
    </div>
  )
}
