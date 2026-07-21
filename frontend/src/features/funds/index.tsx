import { useState } from "react"
import { useParams, useNavigate, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  ArrowLeft, GitCompare, FileText, ExternalLink,
  TrendingUp, BarChart3, ChevronDown, ChevronUp, Search,
} from "lucide-react"
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend, ReferenceLine,
} from "recharts"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import {
  metricsApiV2, schemesApi, insightsApi, rankingsV2Api,
  type GrowthPoint, type ExplainComponent,
} from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"
import InsightPanel from "@/components/insights/InsightPanel"
import {
  formatAxisDate, formatTooltipDate, computeBoundaryDates,
  computeSectorData, computeAnnualSegments, filterHoldingsByName,
} from "./utils"
import FundPicker from "@/components/funds/FundPicker"

// ── Palette ───────────────────────────────────────────────────────────────

const TIER_COLOR: Record<string, string> = {
  Strong: "bg-emerald-100 text-emerald-800",
  Good:   "bg-blue-100 text-blue-800",
  Neutral:"bg-amber-100 text-amber-800",
  Weak:   "bg-red-100 text-red-800",
}

const SECTOR_COLORS = [
  "#2563eb","#7c3aed","#059669","#d97706","#dc2626",
  "#0891b2","#65a30d","#9333ea","#f59e0b","#6b7280",
]

const PERIODS = ["1M","6M","1Y","3Y","5Y","Max"] as const
type Period = typeof PERIODS[number]

// ── Chip ─────────────────────────────────────────────────────────────────

function Chip({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex flex-col min-w-0">
      <span className="text-xs text-muted-foreground truncate">{label}</span>
      <span className="text-sm font-medium truncate">{value ?? "—"}</span>
    </div>
  )
}

// ── Expandable metric cell ─────────────────────────────────────────────────
// Mirrors CompactInsightCard's collapsed/expanded interaction (click header,
// chevron flip, detail revealed below) rather than inventing a second
// expand/collapse pattern — see components/insights/InsightCard.tsx.

function ExpandableMetricCell({
  label, value, definition, detail,
}: {
  label: string
  value: string
  definition: string
  detail?: string | null
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2">
      <button
        className="w-full text-left"
        onClick={() => setExpanded(e => !e)}
        aria-expanded={expanded}
      >
        <div className="flex items-start justify-between gap-1">
          <div className="min-w-0">
            <span className="text-[11px] text-muted-foreground block truncate">{label}</span>
            <span className="text-base font-semibold tabular-nums">{value}</span>
          </div>
          {expanded
            ? <ChevronUp className="h-3.5 w-3.5 text-gray-400 flex-shrink-0 mt-0.5" />
            : <ChevronDown className="h-3.5 w-3.5 text-gray-400 flex-shrink-0 mt-0.5" />}
        </div>
      </button>
      {expanded && (
        <div className="mt-2 pt-2 border-t border-gray-100 space-y-1">
          <p className="text-[11px] text-muted-foreground leading-snug">{definition}</p>
          {detail && <p className="text-[11px] text-gray-700 leading-snug">{detail}</p>}
        </div>
      )}
    </div>
  )
}

// ── Consistency heatmap (real years, honest about resolution) ────────────
// Redesign: distinct annual segments (from real NAV-anchor data) shown as
// wide bars labeled by their real year, plus real recent-monthly cells (if
// any) shown as a separate, clearly finer-grained strip. Synthetic
// (model-estimated, not real) cells are never rendered as if they were
// monthly data — see data note below instead.

interface HeatmapCellLite {
  year: number
  month: number
  month_label: string
  ir: number
  color: string
  is_real: boolean
  resolution: string
}

function colorFor(ir: number): string {
  return ir >= 0.3 ? "#16a34a" : ir >= 0 ? "#d97706" : "#dc2626"
}

function AnnualIRBars({ cells }: { cells: HeatmapCellLite[] }) {
  // Segment/mode-year-labeling logic lives in utils.ts (computeAnnualSegments)
  // so it can be unit tested against the exact truncated-segment scenario
  // that previously mislabeled a mostly-2025 segment as "2026".
  const segments = computeAnnualSegments(cells)

  if (segments.length === 0) return null

  const maxAbs = Math.max(0.4, ...segments.map(s => Math.abs(s.ir)))

  return (
    <div>
      <p className="text-[11px] font-medium text-gray-500 mb-2">
        Annual IR — {segments.length} real year{segments.length !== 1 ? "s" : ""} of NAV-anchor data
      </p>
      <div className="flex items-end gap-3 h-24">
        {segments.map((s, i) => {
          const heightPct = Math.max(8, (Math.abs(s.ir) / maxAbs) * 100)
          return (
            <div key={i} className="flex flex-col items-center gap-1 flex-1 h-full justify-end">
              <span className="text-[10px] font-medium tabular-nums text-gray-700">{s.ir.toFixed(2)}</span>
              <div
                className="w-full rounded-t"
                style={{ height: `${heightPct}%`, backgroundColor: colorFor(s.ir), minHeight: 6 }}
                title={`${s.label}: annual IR ${s.ir.toFixed(3)} (real NAV-anchor segment, ~${s.months} months)`}
              />
              <span className="text-[10px] text-muted-foreground">{s.label}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MonthlyIRStrip({ cells }: { cells: HeatmapCellLite[] }) {
  const monthly = [...cells]
    .filter(c => c.resolution === "snapshot")
    .sort((a, b) => a.year - b.year || a.month - b.month)

  if (monthly.length === 0) return null

  return (
    <div className="mt-4">
      <p className="text-[11px] font-medium text-gray-500 mb-2">
        Recent months — {monthly.length} real monthly reading{monthly.length !== 1 ? "s" : ""} (higher resolution than the annual bars)
      </p>
      <div className="flex gap-1.5">
        {monthly.map((c, i) => (
          <div key={i} className="flex flex-col items-center gap-1">
            <div
              className="w-9 h-9 rounded"
              style={{ backgroundColor: colorFor(c.ir) }}
              title={`${c.month_label}: IR ${c.ir.toFixed(3)} (real monthly value)`}
            />
            <span className="text-[9px] text-muted-foreground">{c.month_label.split(" ")[0]}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ConsistencyHeatmap({ cells, realMonths }: { cells: HeatmapCellLite[]; realMonths: number }) {
  const hasAnnual = cells.some(c => c.resolution === "annual_anchor")
  const hasMonthly = cells.some(c => c.resolution === "snapshot")

  if (!hasAnnual && !hasMonthly) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        No real IR history available for this fund yet — nothing honest to show here.
      </p>
    )
  }

  return (
    <div>
      <AnnualIRBars cells={cells} />
      <MonthlyIRStrip cells={cells} />
      <p className="text-[10px] text-muted-foreground mt-3">
        {realMonths} of {cells.length} months are grounded in real data (NAV-anchor annual segments + rolling
        snapshot IR). Months not covered by either are omitted here rather than shown as fabricated monthly detail.
      </p>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function FundDetailPage() {
  const { fundId = "" } = useParams<{ fundId: string }>()
  const navigate = useNavigate()
  useSearchParams()
  const [period, setPeriod] = useState<Period>("3Y")
  const [showAllHoldings, setShowAllHoldings] = useState(false)
  const [holdingsSearch, setHoldingsSearch] = useState("")

  const summaryQ = useQuery({
    queryKey: queryKeys.funds.summaryV2(fundId),
    queryFn: () => metricsApiV2.getSummaryV2(fundId),
    enabled: !!fundId,
  })

  const growthQ = useQuery({
    queryKey: queryKeys.funds.growthOf10k(fundId, period),
    queryFn: () => metricsApiV2.getGrowthOf10k(fundId, period),
    enabled: !!fundId,
  })

  const heatmapQ = useQuery({
    queryKey: queryKeys.funds.heatmap(fundId),
    queryFn: () => metricsApiV2.getConsistencyHeatmap(fundId),
    enabled: !!fundId,
  })

  // limit=50 fetches the fund's FULL holdings list in one call (real funds
  // top out around 35 holdings; the backend's existing cap is le=50) so
  // search can reach beyond the top-10 default view without a second
  // request or a server-side search endpoint.
  const holdingsQ = useQuery({
    queryKey: queryKeys.funds.holdingsV2(fundId),
    queryFn: () => schemesApi.getHoldingsV2(fundId, 50),
    enabled: !!fundId,
  })

  const docsQ = useQuery({
    queryKey: queryKeys.funds.documents(fundId),
    queryFn: () => schemesApi.getDocuments(fundId),
    enabled: !!fundId,
  })

  const insightsQ = useQuery({
    queryKey: queryKeys.funds.insights(fundId),
    queryFn: () => insightsApi.getFundInsights(parseInt(fundId, 10)),
    enabled: !!fundId,
  })

  // Real per-metric category percentile — reuses the existing /rankings/explain
  // endpoint (already built for Category Rankings) rather than a new one.
  const explainQ = useQuery({
    queryKey: queryKeys.rankings.explain(parseInt(fundId || "0", 10), summaryQ.data?.category ?? ""),
    queryFn: () => rankingsV2Api.explain(parseInt(fundId, 10), summaryQ.data!.category),
    enabled: !!fundId && !!summaryQ.data?.category,
  })

  const summary = summaryQ.data
  const growth = growthQ.data
  const heatmap = heatmapQ.data
  const holdings = holdingsQ.data
  const docs = docsQ.data
  const insights = insightsQ.data
  const explain = explainQ.data

  // Real per-metric percentile/context, keyed by a recognisable substring of
  // label_display — only present for whatever components the ACTIVE rule
  // version actually scores (today: IR, Sharpe, Active Return, Tracking
  // Error). Never fabricated for metrics the rule engine doesn't cover.
  function findComponent(...needles: string[]): ExplainComponent | undefined {
    return explain?.components.find(c =>
      needles.some(n => c.label_display.toLowerCase().includes(n)),
    )
  }
  const irComponent = findComponent("information ratio", "ir₃")
  const sharpeComponent = findComponent("sharpe")
  const activeRetComponent = findComponent("active ret")
  const teComponent = findComponent("tracking error")

  function percentileDetail(component: ExplainComponent | undefined): string | null {
    if (!component) return null
    return `Ranks in the ${Math.round(component.percentile_score)}th percentile of its category for this metric.`
  }

  // Sector aggregation from holdings (pure logic in utils.ts, unit tested)
  const sectorData = computeSectorData(holdings?.holdings ?? [])

  // Growth chart series — full ISO dates kept (not truncated) so the X-axis
  // can format adaptively by period and gridlines can mark real boundaries.
  const chartData: Array<{ date: string; fund: number | null; bm: number | null }> = []
  if (growth) {
    const bmMap = new Map<string, number>(growth.benchmark_series.map((p: GrowthPoint) => [p.date, p.value]))
    for (const p of growth.fund_series) {
      chartData.push({ date: p.date, fund: p.value, bm: bmMap.get(p.date) ?? null })
    }
  }
  const isShortPeriod = period === "1M" || period === "6M"

  // Date-axis formatting and gridline-boundary logic live in utils.ts (pure,
  // unit tested) — day-level ticks for 1M/6M, month-level for 1Y/3Y/5Y/Max.
  const axisDateFormatter = (dateStr: string) => formatAxisDate(dateStr, isShortPeriod)
  const boundaryDates = computeBoundaryDates(chartData.map(p => p.date), isShortPeriod)

  // ── Grouped metric cells (Step 1) ─────────────────────────────────────────
  // Returns: 1Y / 3Y / 5Y CAGR + Active Return vs benchmark.
  // Risk-Adjusted: IR / Sharpe / Tracking Error (the metrics the rule engine
  // actually scores). Sortino/Alpha/Beta are not shown — not present
  // anywhere in this fund's data pipeline; not fabricating them.
  // Category Standing: composite score, rank, expense ratio (real data,
  // previously fetched but never displayed anywhere on this page).
  const returnCells = summary
    ? [
        { label: "1Y Return", value: summary.fund_1yr_ret != null ? `${summary.fund_1yr_ret.toFixed(2)}%` : "—",
          definition: "Trailing 1-year return." },
        { label: "3Y Return (CAGR)", value: summary.fund_3yr_ret != null ? `${summary.fund_3yr_ret.toFixed(2)}%` : "—",
          definition: "Annualised compound growth rate over the trailing 3 years." },
        { label: "5Y Return (CAGR)", value: summary.fund_5yr_ret != null ? `${summary.fund_5yr_ret.toFixed(2)}%` : "—",
          definition: "Annualised compound growth rate over the trailing 5 years." },
        { label: "Active Return 3Y", value: summary.active_3yr_ret != null ? `${summary.active_3yr_ret.toFixed(2)}%` : "—",
          definition: "Fund return minus benchmark return over 3 years (excess return).",
          detail: percentileDetail(activeRetComponent) },
      ]
    : []
  const riskCells = summary
    ? [
        { label: "IR (3Y)", value: summary.information_ratio_3yr != null ? summary.information_ratio_3yr.toFixed(3) : "—",
          definition: "Information Ratio — active return per unit of tracking error. Higher means more consistent outperformance.",
          detail: percentileDetail(irComponent) ?? (summary.ir_slope_6m_proxy != null
            ? `6-month trend: ${summary.ir_slope_6m_proxy >= 0 ? "improving" : "declining"} (${summary.ir_slope_6m_proxy.toFixed(4)}/mo).`
            : null) },
        { label: "Sharpe (3Y)", value: summary.sharpe_ratio_3yr != null ? summary.sharpe_ratio_3yr.toFixed(3) : "—",
          definition: "Sharpe Ratio — return per unit of total volatility.",
          detail: percentileDetail(sharpeComponent) },
        { label: "Tracking Error 3Y", value: summary.tracking_error_3yr != null ? `${summary.tracking_error_3yr.toFixed(2)}%` : "—",
          definition: "Standard deviation of active return vs benchmark. Lower means the fund hugs its benchmark more closely.",
          detail: percentileDetail(teComponent) },
      ]
    : []
  const standingCells = summary
    ? [
        { label: "Composite Score", value: summary.composite_score != null ? summary.composite_score.toFixed(1) : "—",
          definition: "Weighted percentile score from the currently active rule version, out of 100." },
        { label: "Category Rank", value: summary.rank_in_category && summary.total_in_category
            ? `${summary.rank_in_category} / ${summary.total_in_category}` : "—",
          definition: "This fund's rank among all ranked funds in its real category." },
        { label: "Expense Ratio", value: summary.expense_ratio_pct != null ? `${summary.expense_ratio_pct.toFixed(2)}%` : "—",
          definition: "Annual fee charged by the AMC, as a % of assets." },
      ]
    : []

  // Display holdings — searching the FULL portfolio always wins over the
  // top-10/show-all toggle; clearing the search returns to that toggle's
  // state (top 10 by default).
  const allHoldings = holdings?.holdings ?? []
  const isSearchingHoldings = holdingsSearch.trim().length > 0
  const holdingsSearchResults = filterHoldingsByName(allHoldings, holdingsSearch)
  const displayedHoldings = isSearchingHoldings
    ? holdingsSearchResults
    : showAllHoldings
    ? allHoldings
    : allHoldings.slice(0, 10)

  if (!fundId) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-6">
        <TrendingUp className="h-12 w-12 text-muted-foreground/30" />
        <div>
          <p className="text-lg font-medium text-foreground">No fund selected</p>
          <p className="text-sm text-muted-foreground mt-1">
            Jump straight to a fund below, or browse the complete ranked list.
          </p>
        </div>
        <FundPicker
          onSelect={sc => navigate(`/funds/${sc}`)}
          className="bg-white border border-gray-200 rounded-xl shadow-sm w-full max-w-[420px] p-3 text-left"
        />
        <button
          onClick={() => navigate("/rankings")}
          className="text-sm font-medium text-blue-600 hover:underline"
        >
          Browse full rankings →
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col min-h-screen">
      {/* ── Header ── */}
      <div className="sticky top-0 z-20 bg-background border-b">
        <div className="px-6 py-3 flex items-start gap-4">
          <button
            onClick={() => navigate(-1)}
            className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> Back
          </button>

          <div className="flex-1 min-w-0">
            {summaryQ.isLoading ? (
              <div className="h-6 w-64 animate-pulse bg-muted rounded" />
            ) : (
              <h1 className="text-lg font-semibold truncate leading-tight">
                {summary?.fund_name ?? `Fund ${fundId}`}
              </h1>
            )}
            {summary && (
              <div className="mt-2 flex flex-wrap gap-4">
                <Chip label="Category" value={summary.category} />
                <Chip label="Benchmark" value={summary.benchmark} />
                <Chip label="AUM (Cr)" value={summary.aum_cr != null ? `₹${summary.aum_cr.toLocaleString()}` : null} />
                <Chip label="Inception" value={summary.launch_date} />
                {summary.tier && (
                  <div className="flex flex-col min-w-0">
                    <span className="text-xs text-muted-foreground">Tier</span>
                    <span className={cn("text-xs font-medium px-2 py-0.5 rounded-full w-fit mt-0.5", TIER_COLOR[summary.tier] ?? "bg-muted text-muted-foreground")}>
                      {summary.tier}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>

          <button
            onClick={() => navigate(`/compare?funds=${fundId}`)}
            className="flex items-center gap-1.5 text-sm border rounded-lg px-3 py-1.5 hover:bg-muted whitespace-nowrap"
          >
            <GitCompare className="h-4 w-4" /> Open in Compare
          </button>
        </div>
      </div>

      {/* ── Tabs ── */}
      <Tabs defaultValue="overview" className="flex-1 px-6 pt-4">
        <TabsList>
          <TabsTrigger value="overview" className="flex items-center gap-1.5">
            <TrendingUp className="h-3.5 w-3.5" /> Overview
          </TabsTrigger>
          <TabsTrigger value="analytics" className="flex items-center gap-1.5">
            <BarChart3 className="h-3.5 w-3.5" /> Analytics
          </TabsTrigger>
        </TabsList>

        {/* ═══ OVERVIEW TAB ═══════════════════════════════════════════════ */}
        <TabsContent value="overview" className="mt-4 space-y-6 pb-24">
          {/* Growth of 10k chart */}
          <div className="rounded-xl border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold">Growth of ₹10,000</span>
              <div className="flex gap-1">
                {PERIODS.map((p) => (
                  <button
                    key={p}
                    onClick={() => setPeriod(p)}
                    className={cn(
                      "px-2 py-0.5 rounded text-xs font-medium",
                      period === p ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
            {growthQ.isLoading ? (
              <div className="h-48 animate-pulse bg-muted rounded" />
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  {boundaryDates.map((d) => (
                    <ReferenceLine key={d} x={d} stroke="#d1d5db" strokeDasharray="2 2" />
                  ))}
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    interval="preserveStartEnd"
                    tickFormatter={axisDateFormatter}
                  />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false}
                    tickFormatter={(v: number) => `₹${(v / 1000).toFixed(1)}k`} />
                  <Tooltip
                    formatter={(v: unknown, name: string) => [`₹${(v as number).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`, name]}
                    labelFormatter={formatTooltipDate}
                  />
                  <Legend
                    verticalAlign="top"
                    height={28}
                    formatter={(value: string) => <span className="text-xs text-gray-600">{value}</span>}
                  />
                  <Line dataKey="fund" name="Fund" stroke="#2563eb" dot={false} strokeWidth={2} />
                  <Line dataKey="bm" name={growth?.benchmark_name ?? "Benchmark"} stroke="#9333ea" dot={false} strokeWidth={1.5} strokeDasharray="4 2" />
                </LineChart>
              </ResponsiveContainer>
            )}
            {growth?.data_note && (
              <p className="text-xs text-muted-foreground mt-2">{growth.data_note}</p>
            )}
          </div>

          {/* AI Insight card */}
          <div className="rounded-xl border bg-card">
            <InsightPanel
              cards={insights?.cards ?? []}
              isLoading={insightsQ.isLoading}
              layout="grid"
            />
          </div>

          {/* Holdings + Sector side-by-side */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Top holdings */}
            <div className="rounded-xl border bg-card p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-semibold">
                  Top Holdings
                  {holdings?.as_of_date && (
                    <span className="ml-2 text-xs text-muted-foreground">as of {holdings.as_of_date}</span>
                  )}
                </span>
              </div>
              {holdingsQ.isLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="h-6 animate-pulse bg-muted rounded" />
                  ))}
                </div>
              ) : (
                <>
                  {allHoldings.length > 10 && (
                    <div className="relative mb-2">
                      <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                      <input
                        value={holdingsSearch}
                        onChange={e => setHoldingsSearch(e.target.value)}
                        placeholder={`Search all ${allHoldings.length} holdings by company name…`}
                        className="w-full text-xs border border-gray-200 rounded-lg pl-6 pr-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    </div>
                  )}
                  {isSearchingHoldings && holdingsSearchResults.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-3">No holdings match "{holdingsSearch}".</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-muted-foreground">
                          <th className="text-left pb-1">Company</th>
                          <th className="text-right pb-1">Weight</th>
                        </tr>
                      </thead>
                      <tbody>
                        {displayedHoldings.map((h, i) => (
                          <tr key={i} className="border-t border-border/40">
                            <td className="py-1 pr-2">
                              <div className="font-medium truncate max-w-[160px]">{h.company_name}</div>
                              {h.sector && <div className="text-muted-foreground text-[10px]">{h.sector}</div>}
                            </td>
                            <td className="py-1 text-right tabular-nums">{h.weight_pct.toFixed(2)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {!isSearchingHoldings && allHoldings.length > 10 && (
                    <button
                      onClick={() => setShowAllHoldings(!showAllHoldings)}
                      className="mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      {showAllHoldings ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                      {showAllHoldings ? "Show less" : `Show all ${allHoldings.length} holdings`}
                    </button>
                  )}
                  {holdings?.total_weight_pct != null && (
                    <p className="text-xs text-muted-foreground mt-2">
                      Total accounted: {holdings.total_weight_pct.toFixed(1)}%
                    </p>
                  )}
                </>
              )}
            </div>

            {/* Sector donut */}
            <div className="rounded-xl border bg-card p-4">
              <span className="text-sm font-semibold">Sector Exposure</span>
              {holdingsQ.isLoading ? (
                <div className="h-48 animate-pulse bg-muted rounded mt-3" />
              ) : sectorData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={sectorData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={85}
                      label={({ cx, cy, midAngle, outerRadius, percent }) => {
                        if (percent < 0.04) return null // skip labels on slivers to avoid clutter
                        const RADIAN = Math.PI / 180
                        const radius = outerRadius + 14
                        const x = cx + radius * Math.cos(-midAngle * RADIAN)
                        const y = cy + radius * Math.sin(-midAngle * RADIAN)
                        return (
                          <text x={x} y={y} fill="#374151" fontSize={10} fontWeight={600}
                            textAnchor={x > cx ? "start" : "end"} dominantBaseline="central">
                            {`${Math.round(percent * 100)}%`}
                          </text>
                        )
                      }}
                      labelLine={{ stroke: "#d1d5db", strokeWidth: 1 }}
                    >
                      {sectorData.map((_, i) => (
                        <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />
                      ))}
                    </Pie>
                    <Legend
                      formatter={(value: string, entry) => {
                        const pct = (entry?.payload as unknown as { pct: number } | undefined)?.pct
                        return <span className="text-[10px]">{value}{pct != null ? ` — ${pct.toFixed(1)}%` : ""}</span>
                      }}
                      layout="vertical"
                      align="right"
                      verticalAlign="middle"
                    />
                    <Tooltip
                      formatter={(_v: unknown, name: string, entry) => {
                        const payload = entry?.payload as { value: number; pct: number } | undefined
                        const pct = payload?.pct ?? 0
                        const weight = payload?.value
                        return [
                          weight != null ? `${pct.toFixed(1)}% (wt ${weight.toFixed(1)}%)` : `${pct.toFixed(1)}%`,
                          name,
                        ]
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-muted-foreground mt-4">No sector data available</p>
              )}
            </div>
          </div>

          {/* Documents */}
          {docs && docs.documents.length > 0 && (
            <div className="rounded-xl border bg-card p-4">
              <span className="text-sm font-semibold mb-3 block">Research Documents</span>
              <div className="space-y-2">
                {docs.documents.map((d, i) => (
                  <div key={i} className="flex items-center justify-between py-1.5 border-t border-border/40 first:border-0">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <div className="text-sm font-medium">{d.label}</div>
                        <div className="text-xs text-muted-foreground">as of {d.as_of_date}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={cn("text-xs px-2 py-0.5 rounded-full",
                        d.extraction_status === "extracted" ? "bg-green-100 text-green-700" : "bg-muted text-muted-foreground"
                      )}>
                        {d.extraction_status}
                      </span>
                      <a href={d.file_url} target="_blank" rel="noreferrer"
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Research CTA */}
          <div className="rounded-xl border bg-card/50 p-4 flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Deep research on {summary?.fund_name ?? "this fund"}</p>
              <p className="text-xs text-muted-foreground mt-0.5">Ask sourced questions — AI cites pre-computed data only</p>
            </div>
            <button
              onClick={() => {
                if (!summary) return
                const params = new URLSearchParams({
                  from: "fund_detail",
                  schemecode: fundId,
                  fund_name: encodeURIComponent(summary.fund_name),
                  category: encodeURIComponent(summary.category),
                  // facts_json: key metrics visible on this page right now
                  facts_json: JSON.stringify({
                    fund_name: summary.fund_name,
                    category: summary.category,
                    rank: summary.rank_in_category,
                    total_in_category: summary.total_in_category,
                    composite_score: summary.composite_score,
                    ir_3yr: summary.information_ratio_3yr,
                    sharpe_3yr: summary.sharpe_ratio_3yr,
                    ir_slope: summary.ir_slope_6m_proxy,
                    fund_3yr_ret: summary.fund_3yr_ret,
                    active_3yr_ret: summary.active_3yr_ret,
                    benchmark: summary.benchmark,
                    as_of_date: summary.as_of_date,
                  }),
                  // hint which tools the chat should use first
                  required_tools: JSON.stringify(["get_fund_metrics", "get_rankings_explain"]),
                  // language compliance: never ask AI to recommend or rank FOR the user
                  forbidden_phrases: JSON.stringify(["recommend", "buy", "sell", "should I invest", "best fund"]),
                })
                navigate(`/chat?${params.toString()}`)
              }}
              className="flex items-center gap-1.5 text-sm bg-primary text-primary-foreground rounded-lg px-3 py-1.5 hover:bg-primary/90"
            >
              Research Chat
            </button>
          </div>
        </TabsContent>

        {/* ═══ ANALYTICS TAB ══════════════════════════════════════════════ */}
        <TabsContent value="analytics" className="mt-4 space-y-6 pb-24">
          {/* Grouped metric cards — Returns / Risk-Adjusted / Category Standing,
              replacing the old 6-card grid + separate Performance Summary
              table (same fields, no longer duplicated across two layouts). */}
          {summary && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="rounded-xl border bg-card p-4">
                <span className="text-sm font-semibold mb-3 block">Returns</span>
                <div className="grid grid-cols-2 gap-2">
                  {returnCells.map((c, i) => <ExpandableMetricCell key={i} {...c} />)}
                </div>
              </div>
              <div className="rounded-xl border bg-card p-4">
                <span className="text-sm font-semibold mb-3 block">Risk-Adjusted</span>
                <div className="grid grid-cols-1 gap-2">
                  {riskCells.map((c, i) => <ExpandableMetricCell key={i} {...c} />)}
                </div>
              </div>
              <div className="rounded-xl border bg-card p-4">
                <span className="text-sm font-semibold mb-3 block">Category Standing</span>
                <div className="grid grid-cols-1 gap-2">
                  {standingCells.map((c, i) => <ExpandableMetricCell key={i} {...c} />)}
                </div>
              </div>
            </div>
          )}

          {/* Consistency heatmap — real annual segments + real recent months */}
          <div className="rounded-xl border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold">IR Consistency</span>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-600 inline-block" /> ≥0.3</span>
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-amber-600 inline-block" /> 0–0.3</span>
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-600 inline-block" /> &lt;0</span>
              </div>
            </div>
            {heatmapQ.isLoading ? (
              <div className="h-24 animate-pulse bg-muted rounded" />
            ) : heatmap ? (
              <ConsistencyHeatmap cells={heatmap.cells} realMonths={heatmap.real_months} />
            ) : null}
          </div>

          {/* AI Summary */}
          <div className="rounded-xl border bg-card">
            <InsightPanel
              cards={insights?.cards ?? []}
              isLoading={insightsQ.isLoading}
              layout="grid"
            />
          </div>
        </TabsContent>
      </Tabs>

      {/* ── Bottom action bar ── */}
      <div className="fixed bottom-0 left-0 right-0 z-20 bg-background border-t px-6 py-3 flex items-center gap-3">
        <button
          onClick={() => navigate(`/compare?funds=${fundId}`)}
          className="flex items-center gap-1.5 text-sm border rounded-lg px-3 py-1.5 hover:bg-muted"
        >
          <GitCompare className="h-4 w-4" /> Compare
        </button>
        <button
          className="flex items-center gap-1.5 text-sm border rounded-lg px-3 py-1.5 hover:bg-muted"
          onClick={() => alert("Save to workspace — coming in M6")}
        >
          Save to workspace
        </button>
        <button
          className="flex items-center gap-1.5 text-sm border rounded-lg px-3 py-1.5 hover:bg-muted"
          onClick={() => alert("Add to report — coming in M7")}
        >
          Add to report
        </button>
        {summary && (
          <span className="ml-auto text-xs text-muted-foreground">
            {summary.fund_name}
          </span>
        )}
      </div>
    </div>
  )
}
