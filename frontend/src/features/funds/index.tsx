import { useState } from "react"
import { useParams, useNavigate, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  ArrowLeft, GitCompare, FileText, ExternalLink,
  TrendingUp, BarChart3, ChevronDown, ChevronUp,
} from "lucide-react"
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from "recharts"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import {
  metricsApiV2, schemesApi, insightsApi,
  type GrowthPoint,
} from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"
import InsightPanel from "@/components/insights/InsightPanel"

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

// ── Metric card ───────────────────────────────────────────────────────────

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border bg-card p-4 flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xl font-semibold tabular-nums">{value}</span>
      {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
    </div>
  )
}

// ── HeatmapGrid ──────────────────────────────────────────────────────────

const ANNUAL_STRIPE = "repeating-linear-gradient(45deg, rgba(255,255,255,0.18) 0px, rgba(255,255,255,0.18) 1px, transparent 1px, transparent 5px)"

function HeatmapGrid({ cells }: { cells: Array<{ month_label: string; ir: number; color: string; is_real: boolean; resolution: string }> }) {
  const COLOR_MAP = { green: "#16a34a", yellow: "#d97706", red: "#dc2626" }

  const hasAnnualCells = cells.some(c => c.resolution === "annual_anchor")

  return (
    <div>
      <div className="flex flex-wrap gap-1">
        {cells.map((c, i) => (
          <div
            key={i}
            title={
              c.resolution === "annual_anchor"
                ? `${c.month_label}: IR ${c.ir.toFixed(3)} (annual segment value — not true monthly data)`
                : c.resolution === "synthetic"
                ? `${c.month_label}: IR ${c.ir.toFixed(3)} (model-estimated)`
                : `${c.month_label}: IR ${c.ir.toFixed(3)}`
            }
            className={cn(
              "w-8 h-8 rounded cursor-default",
              !c.is_real && "opacity-40 ring-1 ring-inset ring-white/60",
            )}
            style={{
              backgroundColor: COLOR_MAP[c.color as keyof typeof COLOR_MAP] ?? "#6b7280",
              backgroundImage: c.resolution === "annual_anchor" ? ANNUAL_STRIPE : undefined,
            }}
          />
        ))}
      </div>
      {hasAnnualCells && (
        <div className="flex items-center gap-1.5 mt-2">
          <div
            className="w-3.5 h-3.5 rounded-sm bg-emerald-500 flex-shrink-0"
            style={{ backgroundImage: ANNUAL_STRIPE }}
          />
          <span className="text-[10px] text-muted-foreground">
            Striped cells = one annual IR value repeated across ~10 months (no true monthly NAV data)
          </span>
        </div>
      )}
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

  const holdingsQ = useQuery({
    queryKey: queryKeys.funds.holdingsV2(fundId),
    queryFn: () => schemesApi.getHoldingsV2(fundId, 20),
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

  const summary = summaryQ.data
  const growth = growthQ.data
  const heatmap = heatmapQ.data
  const holdings = holdingsQ.data
  const docs = docsQ.data
  const insights = insightsQ.data

  // Sector aggregation from holdings
  const sectorMap: Record<string, number> = {}
  if (holdings?.holdings) {
    for (const h of holdings.holdings) {
      const s = h.sector ?? "Other"
      sectorMap[s] = (sectorMap[s] ?? 0) + h.weight_pct
    }
  }
  const sectorData = Object.entries(sectorMap)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({ name, value: Math.round(value * 10) / 10 }))

  // Growth chart series
  const chartData: Array<{ date: string; fund: number | null; bm: number | null }> = []
  if (growth) {
    const bmMap = new Map<string, number>(growth.benchmark_series.map((p: GrowthPoint) => [p.date, p.value]))
    for (const p of growth.fund_series) {
      chartData.push({ date: p.date.slice(0, 7), fund: p.value, bm: bmMap.get(p.date) ?? null })
    }
  }

  // Benchmark metric cards
  const metricCards = summary
    ? [
        { label: "3Y Return %", value: summary.fund_3yr_ret != null ? `${summary.fund_3yr_ret.toFixed(2)}%` : "—", sub: "Annualised CAGR" },
        { label: "1Y Return %", value: summary.fund_1yr_ret != null ? `${summary.fund_1yr_ret.toFixed(2)}%` : "—" },
        { label: "IR (3Y)", value: summary.information_ratio_3yr != null ? summary.information_ratio_3yr.toFixed(3) : "—", sub: "Information ratio" },
        { label: "Sharpe (3Y)", value: summary.sharpe_ratio_3yr != null ? summary.sharpe_ratio_3yr.toFixed(3) : "—" },
        { label: "Active Ret 3Y", value: summary.active_3yr_ret != null ? `${summary.active_3yr_ret.toFixed(2)}%` : "—", sub: "vs benchmark" },
        { label: "Track Error 3Y", value: summary.tracking_error_3yr != null ? `${summary.tracking_error_3yr.toFixed(2)}%` : "—", sub: "Lower is better" },
      ]
    : []

  // Display holdings (full or top 10)
  const displayedHoldings = showAllHoldings
    ? (holdings?.holdings ?? [])
    : (holdings?.holdings ?? []).slice(0, 10)

  if (!fundId) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-6">
        <TrendingUp className="h-12 w-12 text-muted-foreground/30" />
        <div>
          <p className="text-lg font-medium text-foreground">No fund selected</p>
          <p className="text-sm text-muted-foreground mt-1">
            Go to Rankings and click a fund to view its detail.
          </p>
        </div>
        <button
          onClick={() => navigate("/rankings")}
          className="text-sm font-medium text-blue-600 hover:underline"
        >
          Browse ranked funds →
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
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false}
                    tickFormatter={(v: number) => `₹${(v / 1000).toFixed(1)}k`} />
                  <Tooltip
                    formatter={(v: unknown) => [`₹${(v as number).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`, ""]}
                    labelFormatter={(l: string) => l}
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
                  {(holdings?.holdings?.length ?? 0) > 10 && (
                    <button
                      onClick={() => setShowAllHoldings(!showAllHoldings)}
                      className="mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    >
                      {showAllHoldings ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                      {showAllHoldings ? "Show less" : `Show all ${holdings?.holdings?.length} holdings`}
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
                    >
                      {sectorData.map((_, i) => (
                        <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />
                      ))}
                    </Pie>
                    <Legend
                      formatter={(value: string) => <span className="text-[10px]">{value}</span>}
                      layout="vertical"
                      align="right"
                      verticalAlign="middle"
                    />
                    <Tooltip formatter={(v: unknown) => [`${(v as number).toFixed(1)}%`, ""]} />
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
          {/* 6 metric cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {metricCards.map((m, i) => (
              <MetricCard key={i} label={m.label} value={m.value} sub={m.sub} />
            ))}
          </div>

          {/* Benchmark comparison table */}
          {summary && (
            <div className="rounded-xl border bg-card p-4">
              <span className="text-sm font-semibold mb-3 block">Performance Summary</span>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground">
                    <th className="text-left pb-2">Metric</th>
                    <th className="text-right pb-2">Value</th>
                    <th className="text-right pb-2">Category Rank</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: "1Y Return", val: summary.fund_1yr_ret != null ? `${summary.fund_1yr_ret.toFixed(2)}%` : "—", rank: null },
                    { label: "3Y Return (CAGR)", val: summary.fund_3yr_ret != null ? `${summary.fund_3yr_ret.toFixed(2)}%` : "—", rank: null },
                    { label: "5Y Return (CAGR)", val: summary.fund_5yr_ret != null ? `${summary.fund_5yr_ret.toFixed(2)}%` : "—", rank: null },
                    { label: "Active Return 3Y", val: summary.active_3yr_ret != null ? `${summary.active_3yr_ret.toFixed(2)}%` : "—", rank: null },
                    { label: "IR (3Y)", val: summary.information_ratio_3yr != null ? summary.information_ratio_3yr.toFixed(3) : "—", rank: null },
                    { label: "Sharpe (3Y)", val: summary.sharpe_ratio_3yr != null ? summary.sharpe_ratio_3yr.toFixed(3) : "—", rank: null },
                    { label: "Tracking Error 3Y", val: summary.tracking_error_3yr != null ? `${summary.tracking_error_3yr.toFixed(2)}%` : "—", rank: null },
                    { label: "Composite Score", val: summary.composite_score != null ? summary.composite_score.toFixed(1) : "—",
                      rank: summary.rank_in_category && summary.total_in_category ? `${summary.rank_in_category} / ${summary.total_in_category}` : null },
                  ].map((row, i) => (
                    <tr key={i} className="border-t border-border/40">
                      <td className="py-2 text-muted-foreground">{row.label}</td>
                      <td className="py-2 text-right tabular-nums font-medium">{row.val}</td>
                      <td className="py-2 text-right tabular-nums text-muted-foreground text-xs">{row.rank ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Monthly IR heatmap */}
          <div className="rounded-xl border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold">Monthly IR Consistency (36 months)</span>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-green-600 inline-block" /> ≥0.3</span>
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-amber-600 inline-block" /> 0–0.3</span>
                <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-600 inline-block" /> &lt;0</span>
              </div>
            </div>
            {heatmapQ.isLoading ? (
              <div className="h-24 animate-pulse bg-muted rounded" />
            ) : heatmap ? (
              <>
                <HeatmapGrid cells={heatmap.cells} />
                <p className="text-xs text-muted-foreground mt-2">{heatmap.data_note}</p>
              </>
            ) : null}
          </div>

          {/* AI Summary */}
          <div className="rounded-xl border bg-card">
            <InsightPanel
              cards={insights?.cards ?? []}
              isLoading={insightsQ.isLoading}
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
