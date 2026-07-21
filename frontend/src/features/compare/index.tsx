import { useState, useEffect } from "react"
import { useSearchParams, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  X, Plus, Loader2, Sparkles, Save, ChevronRight,
  AlertCircle, Info,
} from "lucide-react"
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ReTooltip,
  ResponsiveContainer, Legend, LineChart, Line,
} from "recharts"
import { cn } from "@/lib/utils"
import {
  rankingsV2Api, insightsApi, metricsApiV2,
  type CompareFundEntry, type MetricResult, type CommonHolding,
} from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"
import InsightPanel from "@/components/insights/InsightPanel"
import PocBadge from "@/components/insights/PocBadge"
import FundPicker from "@/components/funds/FundPicker"
// ── Constants ─────────────────────────────────────────────────────────────────

const COLORS = ["#2563EB", "#16A34A", "#D97706", "#7C3AED"]

// Real bucket_36 taxonomy values (see /rankings/categories) — these must
// match exactly what /rankings/category accepts. The pre-migration legacy
// "Equity — X" labels 400 against the current taxonomy now that the
// frontend-side LEGACY_SNAPSHOT_CATEGORY translation shim was removed.
const PICKER_CATEGORIES = [
  "Large Cap",
  "Mid Cap",
  "Small Cap",
] as const

const STATUS_CLS: Record<string, string> = {
  Strong:  "bg-emerald-50 text-emerald-700 border border-emerald-200",
  Good:    "bg-blue-50 text-blue-700 border border-blue-200",
  Neutral: "bg-amber-50 text-amber-700 border border-amber-200",
  Weak:    "bg-red-50 text-red-700 border border-red-200",
  "Insufficient Data": "bg-gray-50 text-gray-500 border border-gray-200",
}

const RADAR_AXES: Array<{ key: keyof import("@/lib/api").RadarAxes; label: string }> = [
  { key: "ir_3yr_normalized",              label: "3Y IR" },
  { key: "downside_protection",            label: "Downside Prot." },
  { key: "active_share_normalized",        label: "Active Share" },
  { key: "expense_efficiency",             label: "Expense Eff." },
  { key: "portfolio_stability_normalized", label: "Port. Stability" },
]

// ── Small utilities ───────────────────────────────────────────────────────────

function shortName(fund_name: string): string {
  return fund_name.replace(/\s+(Fund|Direct|Growth|Plan|Regular)\b/gi, "").trim().slice(0, 28)
}

function aumSuffix(aum_cr: number | null | undefined): string {
  return aum_cr != null ? ` (₹${aum_cr.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr)` : ""
}

function fmtPct(v: number | null, d = 2): string {
  return v == null ? "—" : v.toFixed(d) + "%"
}
function fmtNum(v: number | null, d = 2): string {
  return v == null ? "—" : v.toFixed(d)
}

function UnavailableBadge({ reason }: { reason?: string }) {
  return (
    <span
      title={reason ?? "Insufficient data for this metric"}
      className="inline-flex items-center gap-0.5 text-[10px] text-gray-400 bg-gray-50 border border-gray-200 rounded px-1.5 py-0.5 cursor-help"
    >
      <AlertCircle className="h-2.5 w-2.5" /> Unavailable
    </span>
  )
}

function MetricCell({ m, suffix = "" }: { m: MetricResult | null | undefined; suffix?: string }) {
  if (!m) return <span className="text-gray-300 text-xs">—</span>
  if (m.status === "insufficient_data" || m.value == null)
    return <UnavailableBadge reason={m.confidence} />
  return <span className="text-xs font-mono">{fmtNum(m.value)}{suffix}</span>
}

// ── Heatmap row (per fund, used in Layout B) ──────────────────────────────────

function FundHeatmapRow({ sc, label, color }: { sc: number; label: string; color: string }) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.compare.heatmap(sc),
    queryFn: () => metricsApiV2.getConsistencyHeatmap(String(sc)),
    staleTime: 10 * 60_000,
  })

  const mLabels = ["J","F","M","A","M","J","J","A","S","O","N","D"]
  const ANNUAL_STRIPE = "repeating-linear-gradient(45deg, rgba(255,255,255,0.2) 0px, rgba(255,255,255,0.2) 1px, transparent 1px, transparent 5px)"

  const cellCls = (color: string, isReal: boolean) => {
    const base = {
      green:  "bg-emerald-500",
      yellow: "bg-amber-400",
      red:    "bg-red-400",
    }[color] ?? "bg-gray-200"
    return cn(base, !isReal && "opacity-40 ring-1 ring-inset ring-white/60")
  }

  const cells = data?.cells ?? []
  const years = [...new Set(cells.map(c => c.year))].sort()

  return (
    <div className="flex items-start gap-3 py-2">
      <div className="flex items-center gap-1.5 w-40 flex-shrink-0 pt-0.5">
        <span className="h-2 w-2 rounded-full flex-shrink-0" style={{ background: color }} />
        <span className="text-[11px] font-medium text-gray-700 truncate">{shortName(label)}</span>
      </div>
      {isLoading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-300 mt-1" />
      ) : cells.length === 0 ? (
        <span className="text-[10px] text-gray-400">No data</span>
      ) : (
        <div className="space-y-0.5">
          {years.map(yr => (
            <div key={yr} className="flex items-center gap-0.5">
              <span className="text-[9px] text-gray-400 w-7 flex-shrink-0">{yr}</span>
              {mLabels.map((_, mo) => {
                const cell = cells.find(c => c.year === yr && c.month === mo + 1)
                const isAnnual = cell?.resolution === "annual_anchor"
                return (
                  <div
                    key={mo}
                    title={
                      cell
                        ? `${mLabels[mo]} ${yr}: IR ${fmtNum(cell.ir)}`
                          + (isAnnual ? " (annual segment value — not true monthly data)" : "")
                          + (!cell.is_real ? " (model-estimated)" : "")
                        : "No data"
                    }
                    className={cn(
                      "h-4 w-4 rounded-sm flex-shrink-0 cursor-default",
                      cell ? cellCls(cell.color, cell.is_real) : "bg-gray-100",
                    )}
                    style={isAnnual ? { backgroundImage: ANNUAL_STRIPE } : undefined}
                  />
                )
              })}
            </div>
          ))}
          <div className="flex items-center gap-0.5">
            <span className="w-7" />
            {mLabels.map((m, i) => (
              <div key={i} className="h-3 w-4 flex items-center justify-center text-[7px] text-gray-300">{m}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Fund selector chips row ───────────────────────────────────────────────────

function FundSelector({
  selectedCodes,
  fundNames,
  fundAum,
  onAdd,
  onRemove,
}: {
  selectedCodes: number[]
  fundNames: Record<number, string>
  fundAum: Record<number, number | null>
  onAdd: (sc: number, name: string) => void
  onRemove: (sc: number) => void
}) {
  const [pickerOpen, setPickerOpen] = useState(false)

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3 flex items-center gap-1.5">
        <span className="h-5 w-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-bold">1</span>
        Select funds to compare
        <span className="text-gray-400 normal-case font-normal">(2–4 funds)</span>
      </div>
      <div className="flex items-center flex-wrap gap-2 relative">
        {selectedCodes.map((sc, i) => (
          <div
            key={sc}
            className="flex items-center gap-1.5 border rounded-xl px-3 py-2 bg-white"
            style={{ borderColor: COLORS[i % COLORS.length] + "80" }}
          >
            <span className="h-2.5 w-2.5 rounded-full flex-shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
            <span className="text-xs font-medium text-gray-700 max-w-[150px] truncate">
              {fundNames[sc] ? shortName(fundNames[sc]) : `Fund ${sc}`}
            </span>
            <span className="text-xs text-gray-400 whitespace-nowrap flex-shrink-0">
              {aumSuffix(fundAum[sc])}
            </span>
            <button
              onClick={() => onRemove(sc)}
              className="ml-0.5 text-gray-300 hover:text-red-400 flex-shrink-0"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ))}
        {selectedCodes.length < 4 && (
          <div className="relative">
            <button
              onClick={() => setPickerOpen(prev => !prev)}
              className="flex items-center gap-1.5 text-sm border border-dashed border-gray-300 rounded-xl px-3 py-2 text-gray-500 hover:border-blue-400 hover:text-blue-600 transition-colors"
            >
              <Plus className="h-3.5 w-3.5" /> Add fund
            </button>
            {pickerOpen && (
              <FundPicker
                categories={PICKER_CATEGORIES}
                defaultCategory={PICKER_CATEGORIES[0]}
                excludeCodes={selectedCodes}
                onSelect={onAdd}
                onClose={() => setPickerOpen(false)}
                className="absolute top-full left-0 mt-2 z-30 bg-white border border-gray-200 rounded-xl shadow-xl w-[380px] p-3"
              />
            )}
          </div>
        )}
        {selectedCodes.length === 0 && (
          <p className="text-xs text-gray-400">Select 2–4 ranked funds to begin comparison.</p>
        )}
      </div>
    </div>
  )
}

// ── Layout A — 2-fund side-by-side ───────────────────────────────────────────

function AdvantageArrow({
  metric,
  sc,
  advantages,
  color,
}: {
  metric: string
  sc: number
  advantages: Record<string, number | null>
  color: string
}) {
  if (advantages[metric] !== sc) return null
  return <ChevronRight className="h-3.5 w-3.5 flex-shrink-0" style={{ color }} />
}

const METRICS_TABLE_ROWS: Array<{
  label: string
  key: string
  getter: (f: CompareFundEntry) => string
  advKey: string
}> = [
  {
    label: "Rule Score",
    key: "composite_score",
    getter: f => fmtNum(f.composite_score),
    advKey: "composite_score",
  },
  {
    label: "3Y Info. Ratio",
    key: "ir_3yr",
    getter: f => fmtNum(f.metrics.ir_3yr),
    advKey: "ir_3yr",
  },
  {
    label: "IR Trend (slope)",
    key: "ir_slope_6m_proxy",
    getter: f => fmtNum(f.metrics.ir_slope_6m_proxy, 4),
    advKey: "ir_slope_6m_proxy",
  },
  {
    label: "3Y Active Return",
    key: "active_ret_3yr",
    getter: f => fmtPct(f.metrics.active_ret_3yr),
    advKey: "active_ret_3yr",
  },
  {
    label: "1Y Return",
    key: "ret_1yr",
    getter: f => fmtPct(f.metrics.ret_1yr),
    advKey: "ret_1yr",
  },
  {
    label: "3Y Return",
    key: "ret_3yr",
    getter: f => fmtPct(f.metrics.ret_3yr),
    advKey: "ret_3yr",
  },
  {
    label: "Active Share",
    key: "active_share",
    getter: f =>
      f.active_share.value != null ? fmtPct(f.active_share.value) : "Unavailable",
    advKey: "active_share",
  },
  {
    label: "Expense Ratio",
    key: "expense_ratio_pct",
    getter: f =>
      f.expense_ratio_pct.value != null ? fmtPct(f.expense_ratio_pct.value) : "Unavailable",
    advKey: "expense_ratio_pct",
  },
  {
    label: "Portfolio Stability",
    key: "portfolio_stability",
    getter: f =>
      f.portfolio_stability.value != null ? fmtPct(f.portfolio_stability.value) : "Unavailable",
    advKey: "portfolio_stability",
  },
]

function LayoutA({
  funds,
  advantages,
  radarData,
  rankHistory,
  holdingsOverlap,
  insightCodes,
}: {
  funds: CompareFundEntry[]
  advantages: Record<string, number | null>
  radarData: Record<string, import("@/lib/api").RadarAxes> | null
  rankHistory: Record<string, Array<{ date: string; rank: number }>> | null
  holdingsOverlap: import("@/lib/api").HoldingsOverlapData
  insightCodes: number[]
}) {
  const [fa, fb] = funds

  // Radar chart data
  const radarRows = RADAR_AXES.map(ax => {
    const aVal = radarData?.[String(fa.schemecode)]?.[ax.key]
    const bVal = radarData?.[String(fb.schemecode)]?.[ax.key]
    return {
      axis: ax.label,
      [String(fa.schemecode)]: aVal ?? 50,
      [String(fb.schemecode)]: bVal ?? 50,
    }
  })

  // Rank history line chart data
  const allDates = [
    ...new Set([
      ...(rankHistory?.[String(fa.schemecode)] ?? []).map(p => p.date),
      ...(rankHistory?.[String(fb.schemecode)] ?? []).map(p => p.date),
    ]),
  ].sort()

  const rankRows = allDates.map(date => ({
    date: new Date(date).toLocaleDateString("en-IN", { month: "short", year: "2-digit" }),
    [String(fa.schemecode)]: rankHistory?.[String(fa.schemecode)]?.find(p => p.date === date)?.rank ?? null,
    [String(fb.schemecode)]: rankHistory?.[String(fb.schemecode)]?.find(p => p.date === date)?.rank ?? null,
  }))

  // Sector bar chart data
  const sectorRows = (holdingsOverlap.sector_table ?? []).slice(0, 8).map(row => ({
    sector: row.sector.slice(0, 14),
    [shortName(fa.fund_name)]: row.weights[String(fa.schemecode)] ?? 0,
    [shortName(fb.fund_name)]: row.weights[String(fb.schemecode)] ?? 0,
  }))

  return (
    <div className="space-y-4">
      {/* Metrics table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 pt-4 pb-2">
          <h2 className="text-sm font-semibold text-gray-800">Metrics Comparison</h2>
        </div>
        {[fa, fb].filter(f => f.coverage_note).map(f => (
          <div key={f.schemecode} className="mx-4 mb-2 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5 leading-snug">
            <span className="font-medium">{shortName(f.fund_name)}:</span> {f.coverage_note}
          </div>
        ))}
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left py-2 px-4 font-semibold text-gray-500 w-40">Metric</th>
                <th className="text-right py-2 px-3 font-semibold" style={{ color: COLORS[0] }}>
                  {shortName(fa.fund_name)}{aumSuffix(fa.aum_cr)}
                </th>
                <th className="text-right py-2 px-3 font-semibold" style={{ color: COLORS[1] }}>
                  {shortName(fb.fund_name)}{aumSuffix(fb.aum_cr)}
                </th>
                <th className="text-center py-2 px-3 font-semibold text-gray-500 w-20">Advantage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {METRICS_TABLE_ROWS.map(row => {
                const aVal = row.getter(fa)
                const bVal = row.getter(fb)
                return (
                  <tr key={row.key} className="hover:bg-gray-50">
                    <td className="py-2.5 px-4 text-gray-600">{row.label}</td>
                    <td className={cn("py-2.5 px-3 text-right font-mono", aVal === "Unavailable" && "text-gray-300")}>
                      {aVal === "Unavailable" ? <UnavailableBadge /> : aVal}
                    </td>
                    <td className={cn("py-2.5 px-3 text-right font-mono", bVal === "Unavailable" && "text-gray-300")}>
                      {bVal === "Unavailable" ? <UnavailableBadge /> : bVal}
                    </td>
                    <td className="py-2.5 px-3">
                      <div className="flex items-center justify-center gap-1">
                        {advantages[row.advKey] === fa.schemecode && (
                          <AdvantageArrow metric={row.advKey} sc={fa.schemecode} advantages={advantages} color={COLORS[0]} />
                        )}
                        {advantages[row.advKey] === fb.schemecode && (
                          <AdvantageArrow metric={row.advKey} sc={fb.schemecode} advantages={advantages} color={COLORS[1]} />
                        )}
                        {advantages[row.advKey] == null && <span className="text-gray-200">—</span>}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Radar + Rank history */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">Factor Profile</h2>
          {radarData ? (
            <ResponsiveContainer width="100%" height={220}>
              <RadarChart data={radarRows}>
                <PolarGrid stroke="#f0f0f0" />
                <PolarAngleAxis dataKey="axis" tick={{ fontSize: 10, fill: "#6b7280" }} />
                <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                <Radar
                  name={shortName(fa.fund_name)}
                  dataKey={String(fa.schemecode)}
                  stroke={COLORS[0]}
                  fill={COLORS[0]}
                  fillOpacity={0.15}
                />
                <Radar
                  name={shortName(fb.fund_name)}
                  dataKey={String(fb.schemecode)}
                  stroke={COLORS[1]}
                  fill={COLORS[1]}
                  fillOpacity={0.15}
                />
                <Legend formatter={v => <span className="text-[11px]">{v}</span>} />
              </RadarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-xs text-gray-400 text-center py-8">Radar data unavailable</p>
          )}
          <p className="text-[10px] text-gray-400 mt-1 flex items-center gap-1">
            <Info className="h-2.5 w-2.5" /> Axes are percentile-ranked within this comparison only
          </p>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">Historical Rank Trend</h2>
          {rankRows.length >= 2 ? (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={rankRows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                <YAxis reversed tick={{ fontSize: 10 }} label={{ value: "Rank", angle: -90, position: "insideLeft", fontSize: 10, fill: "#9ca3af" }} />
                <ReTooltip contentStyle={{ fontSize: 11 }} formatter={(v: unknown) => [`#${v}`, "Rank"]} />
                <Legend formatter={v => <span className="text-[11px]">{v}</span>} />
                <Line
                  dataKey={String(fa.schemecode)}
                  name={shortName(fa.fund_name)}
                  stroke={COLORS[0]}
                  dot={false}
                  strokeWidth={2}
                  connectNulls
                />
                <Line
                  dataKey={String(fb.schemecode)}
                  name={shortName(fb.fund_name)}
                  stroke={COLORS[1]}
                  dot={false}
                  strokeWidth={2}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-xs text-gray-400 text-center py-8">Rank history unavailable</p>
          )}
        </div>
      </div>

      {/* Holdings Overlap + Sector Overlap */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-800 mb-1">Holdings Overlap</h2>
          <div className="flex gap-4 mb-3">
            <div>
              <div className="text-[10px] text-gray-400">Weighted Overlap</div>
              <div className="text-base font-semibold text-gray-800">
                {fmtPct(holdingsOverlap.weighted_overlap)}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-gray-400">Jaccard</div>
              <div className="text-base font-semibold text-gray-800">
                {fmtPct(holdingsOverlap.jaccard)}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-gray-400">Common Holdings</div>
              <div className="text-base font-semibold text-gray-800">
                {holdingsOverlap.common_count}
              </div>
            </div>
          </div>
          {holdingsOverlap.common_holdings.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left pb-1.5 text-[10px] font-semibold text-gray-400 pr-3">Security</th>
                    <th className="text-right pb-1.5 text-[10px] font-semibold px-2" style={{ color: COLORS[0] }}>
                      {shortName(fa.fund_name)}
                    </th>
                    <th className="text-right pb-1.5 text-[10px] font-semibold px-2" style={{ color: COLORS[1] }}>
                      {shortName(fb.fund_name)}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {holdingsOverlap.common_holdings.map((h: CommonHolding) => (
                    <tr key={h.security_name} className="hover:bg-gray-50">
                      <td className="py-1.5 pr-3 text-gray-700">{h.security_name}</td>
                      <td className="py-1.5 px-2 text-right font-mono">{fmtPct(h.weight_a)}</td>
                      <td className="py-1.5 px-2 text-right font-mono">{fmtPct(h.weight_b)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-gray-400">No common holdings found.</p>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-800 mb-1">Sector Exposure</h2>
          {holdingsOverlap.sector_overlap != null && (
            <div className="text-[10px] text-gray-400 mb-3">
              Sector overlap: <span className="font-semibold text-gray-700">{fmtPct(holdingsOverlap.sector_overlap)}</span>
            </div>
          )}
          {sectorRows.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={sectorRows} layout="vertical" margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 9 }} unit="%" />
                <YAxis type="category" dataKey="sector" tick={{ fontSize: 9 }} width={80} />
                <ReTooltip contentStyle={{ fontSize: 11 }} formatter={(v: unknown) => [`${(v as number).toFixed(1)}%`]} />
                <Bar dataKey={shortName(fa.fund_name)} fill={COLORS[0]} radius={[0,2,2,0]} />
                <Bar dataKey={shortName(fb.fund_name)} fill={COLORS[1]} radius={[0,2,2,0]} />
                <Legend formatter={v => <span className="text-[10px]">{v}</span>} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-xs text-gray-400 py-8 text-center">No sector data</p>
          )}
        </div>
      </div>

      {/* AI Insights */}
      <AIInsightsCard codes={insightCodes} />
    </div>
  )
}

// ── Layout B — 3-4 fund grid ──────────────────────────────────────────────────

const BAR_METRICS: Array<{ key: keyof CompareFundEntry["metrics"]; label: string; pct: boolean }> = [
  { key: "ir_3yr",        label: "3Y IR",         pct: false },
  { key: "active_ret_3yr", label: "3Y Active Ret", pct: true  },
  { key: "ret_1yr",       label: "1Y Return",     pct: true  },
  { key: "ret_3yr",       label: "3Y Return",     pct: true  },
]

function LayoutB({
  funds,
  advantages,
  holdingsOverlap,
  insightCodes,
}: {
  funds: CompareFundEntry[]
  advantages: Record<string, number | null>
  holdingsOverlap: import("@/lib/api").HoldingsOverlapData
  insightCodes: number[]
}) {
  // Build grouped bar chart data
  const barRows = BAR_METRICS.map(m => {
    const row: Record<string, unknown> = { metric: m.label }
    funds.forEach((f, i) => {
      const v = f.metrics[m.key]
      row[`f${i}`] = v
    })
    return row
  })

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${funds.length}, minmax(0, 1fr))` }}>
        {funds.map((f, i) => (
          <div
            key={f.schemecode}
            className="bg-white rounded-xl border-2 p-4"
            style={{ borderColor: COLORS[i % COLORS.length] + "60" }}
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full flex-shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="text-xs font-semibold text-gray-800 leading-tight">{f.fund_name}{aumSuffix(f.aum_cr)}</span>
              </div>
              <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium flex-shrink-0", STATUS_CLS[f.status_label])}>
                {f.status_label}
              </span>
            </div>
            <div className="text-[10px] text-gray-400 mb-2">{f.amc_name}{f.category ? ` · ${f.category}` : ""}</div>
            {f.coverage_note && (
              <p className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1 mb-2 leading-snug">
                {f.coverage_note}
              </p>
            )}
            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <div>
                <div className="text-[10px] text-gray-400">Rank</div>
                <div className="font-semibold text-gray-800">
                  {f.rank != null ? <>#{f.rank} <span className="text-[10px] text-gray-400">/ {f.total_in_category}</span></> : "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400">Score</div>
                <div className="font-semibold text-gray-800">{fmtNum(f.composite_score)}</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400">3Y IR</div>
                <div className="font-mono text-gray-800">{fmtNum(f.metrics.ir_3yr)}</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400">1Y Return</div>
                <div className="font-mono text-gray-800">{fmtPct(f.metrics.ret_1yr)}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Consistency heatmap — one row per fund */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-sm font-semibold text-gray-800">Consistency Heatmap</h2>
          <div className="flex items-center gap-1 text-[10px] text-gray-400">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500" /> Real
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500 opacity-40 ml-2 ring-1 ring-inset ring-white/60" /> Estimated
          </div>
        </div>
        <div className="divide-y divide-gray-50">
          {funds.map((f, i) => (
            <FundHeatmapRow
              key={f.schemecode}
              sc={f.schemecode}
              label={f.fund_name}
              color={COLORS[i % COLORS.length]}
            />
          ))}
        </div>
      </div>

      {/* Grouped bar chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <h2 className="text-sm font-semibold text-gray-800 mb-3">Metric Comparison</h2>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={barRows} margin={{ left: 0, right: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="metric" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <ReTooltip contentStyle={{ fontSize: 11 }} />
            <Legend formatter={v => <span className="text-[10px]">{v}</span>} />
            {funds.map((f, i) => (
              <Bar
                key={f.schemecode}
                dataKey={`f${i}`}
                name={shortName(f.fund_name)}
                fill={COLORS[i % COLORS.length]}
                radius={[2, 2, 0, 0]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Detailed metrics table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 pt-4 pb-2">
          <h2 className="text-sm font-semibold text-gray-800">Detailed Metrics</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left py-2 px-4 font-semibold text-gray-500 w-36">Metric</th>
                {funds.map((f, i) => (
                  <th key={f.schemecode} className="text-right py-2 px-3 font-semibold" style={{ color: COLORS[i] }}>
                    {shortName(f.fund_name)}{aumSuffix(f.aum_cr)}
                  </th>
                ))}
                <th className="text-center py-2 px-3 font-semibold text-gray-500 w-20">Best</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {METRICS_TABLE_ROWS.map(row => (
                <tr key={row.key} className="hover:bg-gray-50">
                  <td className="py-2.5 px-4 text-gray-600">{row.label}</td>
                  {funds.map(f => {
                    const v = row.getter(f)
                    return (
                      <td key={f.schemecode} className={cn("py-2.5 px-3 text-right font-mono", v === "Unavailable" && "text-gray-300")}>
                        {v === "Unavailable" ? <UnavailableBadge /> : v}
                      </td>
                    )
                  })}
                  <td className="py-2.5 px-3 text-center">
                    {advantages[row.advKey] != null ? (
                      <span
                        className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                        style={{
                          color: COLORS[funds.findIndex(f => f.schemecode === advantages[row.advKey]) % COLORS.length],
                          background: COLORS[funds.findIndex(f => f.schemecode === advantages[row.advKey]) % COLORS.length] + "18",
                        }}
                      >
                        {shortName(funds.find(f => f.schemecode === advantages[row.advKey])?.fund_name ?? "")}
                      </span>
                    ) : (
                      <span className="text-gray-200">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {/* Per-fund unavailable metric rows */}
              <tr className="hover:bg-gray-50">
                <td className="py-2.5 px-4 text-gray-600">Active Share</td>
                {funds.map(f => (
                  <td key={f.schemecode} className="py-2.5 px-3 text-right">
                    <MetricCell m={f.active_share} suffix="%" />
                  </td>
                ))}
                <td className="py-2.5 px-3 text-center">
                  {advantages["active_share"] != null ? (
                    <span
                      className="text-[10px] font-semibold"
                      style={{ color: COLORS[funds.findIndex(f => f.schemecode === advantages["active_share"]) % COLORS.length] }}
                    >
                      ★
                    </span>
                  ) : <span className="text-gray-200">—</span>}
                </td>
              </tr>
              <tr className="hover:bg-gray-50">
                <td className="py-2.5 px-4 text-gray-600">Expense Ratio</td>
                {funds.map(f => (
                  <td key={f.schemecode} className="py-2.5 px-3 text-right">
                    <MetricCell m={f.expense_ratio_pct} suffix="%" />
                  </td>
                ))}
                <td className="py-2.5 px-3 text-center">
                  {advantages["expense_ratio_pct"] != null ? (
                    <span
                      className="text-[10px] font-semibold"
                      style={{ color: COLORS[funds.findIndex(f => f.schemecode === advantages["expense_ratio_pct"]) % COLORS.length] }}
                    >
                      ★
                    </span>
                  ) : <span className="text-gray-200">—</span>}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Holdings overlap summary for B */}
      {holdingsOverlap.pairs.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">Pairwise Holdings Overlap</h2>
          <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))" }}>
            {holdingsOverlap.pairs.map(pair => {
              const nameA = funds.find(f => f.schemecode === pair.fund_a)?.fund_name ?? String(pair.fund_a)
              const nameB = funds.find(f => f.schemecode === pair.fund_b)?.fund_name ?? String(pair.fund_b)
              return (
                <div key={`${pair.fund_a}-${pair.fund_b}`} className="text-xs bg-gray-50 rounded-lg p-3">
                  <div className="text-[10px] text-gray-500 mb-1 truncate">
                    {shortName(nameA)} vs {shortName(nameB)}
                  </div>
                  <div className="font-semibold text-gray-800">
                    {fmtPct(pair.weighted_overlap)} weighted overlap
                  </div>
                  <div className="text-[10px] text-gray-400">{pair.common_count} common holdings</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* AI Insights */}
      <AIInsightsCard codes={insightCodes} />
    </div>
  )
}

// ── AI Insights card (shared) ─────────────────────────────────────────────────

function AIInsightsCard({ codes }: { codes: number[] }) {
  const today = new Date().toISOString().slice(0, 10)
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.compare.insights(codes),
    queryFn: () => insightsApi.compareFunds(codes, today),
    enabled: codes.length >= 2,
    staleTime: 5 * 60_000,
  })

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-purple-500" />
          <span className="text-sm font-semibold text-gray-700">Comparison Insights</span>
        </div>
        <PocBadge />
      </div>
      <InsightPanel cards={data?.cards ?? []} isLoading={isLoading} />
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ComparePage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const initCodes = (searchParams.get("funds") ?? "")
    .split(",")
    .map(Number)
    .filter(n => n > 0)
    .slice(0, 4)

  const [selectedCodes, setSelectedCodes] = useState<number[]>(initCodes)
  const [fundNames, setFundNames]         = useState<Record<number, string>>({})

  const add = (sc: number, name: string) => {
    if (!selectedCodes.includes(sc) && selectedCodes.length < 4) {
      setSelectedCodes(prev => [...prev, sc])
      setFundNames(prev => ({ ...prev, [sc]: name }))
    }
  }
  const remove = (sc: number) => setSelectedCodes(prev => prev.filter(x => x !== sc))

  const canCompare = selectedCodes.length >= 2

  // Main compare query
  const compareQ = useQuery({
    queryKey: queryKeys.compare.funds(selectedCodes),
    queryFn: () => rankingsV2Api.compareFunds(selectedCodes),
    enabled: canCompare,
    staleTime: 5 * 60_000,
  })

  // Populate fundNames from compare response (authoritative names)
  useEffect(() => {
    if (!compareQ.data) return
    const patch: Record<number, string> = {}
    for (const f of compareQ.data.funds) {
      if (!fundNames[f.schemecode]) patch[f.schemecode] = f.fund_name
    }
    if (Object.keys(patch).length) setFundNames(prev => ({ ...prev, ...patch }))
  }, [compareQ.data])

  // Comparison history/save persistence (POST /compare/sessions) is not yet
  // built — the comparison_session table doesn't exist (no migration was
  // ever written). No auto-save trigger and no "Save comparison" mutation
  // are wired up here; the button below is honestly disabled instead of
  // erroring on click. See the disabled "Save comparison" button.

  const cData = compareQ.data

  return (
    <div className="p-6 space-y-5 max-w-screen-xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Fund Comparison</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Side-by-side structural analysis of ranked funds.
          </p>
        </div>
        {canCompare && (
          <button
            disabled
            title="Comparison history isn't available yet — coming soon"
            className="flex items-center gap-1.5 text-sm bg-gray-100 text-gray-400 px-4 py-2 rounded-xl cursor-not-allowed"
          >
            <Save className="h-3.5 w-3.5" />
            Save comparison
            <span className="text-xs bg-gray-200 px-1 rounded">coming soon</span>
          </button>
        )}
      </div>

      {/* Fund selector */}
      <FundSelector
        selectedCodes={selectedCodes}
        fundNames={fundNames}
        fundAum={Object.fromEntries((cData?.funds ?? []).map(f => [f.schemecode, f.aum_cr]))}
        onAdd={add}
        onRemove={remove}
      />

      {/* Empty / loading / error states */}
      {!canCompare && (
        <div className="bg-gray-50 rounded-xl border border-dashed border-gray-200 py-16 text-center">
          <p className="text-sm text-gray-400">Select 2 or more ranked funds above to begin comparison.</p>
        </div>
      )}

      {canCompare && compareQ.isLoading && (
        <div className="flex items-center justify-center py-16 gap-2 text-gray-400">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading comparison data…</span>
        </div>
      )}

      {canCompare && compareQ.isError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          Failed to load comparison data. Please try again.
        </div>
      )}

      {/* Layout A or B */}
      {cData && cData.layout === "A" && (
        <LayoutA
          funds={cData.funds}
          advantages={cData.advantages}
          radarData={cData.radar_data}
          rankHistory={cData.rank_history}
          holdingsOverlap={cData.holdings_overlap}
          insightCodes={selectedCodes}
        />
      )}

      {cData && cData.layout === "B" && (
        <LayoutB
          funds={cData.funds}
          advantages={cData.advantages}
          holdingsOverlap={cData.holdings_overlap}
          insightCodes={selectedCodes}
        />
      )}

      {/* Action row */}
      {cData && (
        <div className="flex items-center gap-3 py-2 border-t border-gray-100">
          <button
            onClick={() => {
              const params = new URLSearchParams({
                from: "compare",
                schemecodes: JSON.stringify(selectedCodes),
                // facts_json: all fund metrics and overlap visible on this page
                facts_json: JSON.stringify({
                  funds: cData.funds.map(f => ({
                    schemecode: f.schemecode,
                    fund_name: f.fund_name,
                    category: f.category,
                    rank: f.rank,
                    total_in_category: f.total_in_category,
                    composite_score: f.composite_score,
                    status_label: f.status_label,
                    ir_3yr: f.metrics.ir_3yr,
                    sharpe_3yr: f.metrics.sharpe_3yr,
                    active_ret_3yr: f.metrics.active_ret_3yr,
                    ret_1yr: f.metrics.ret_1yr,
                    ret_3yr: f.metrics.ret_3yr,
                  })),
                  advantages: cData.advantages,
                  holdings_overlap: {
                    weighted_overlap: cData.holdings_overlap.weighted_overlap,
                    jaccard: cData.holdings_overlap.jaccard,
                    common_count: cData.holdings_overlap.common_count,
                  },
                  evaluation_date: cData.evaluation_date,
                }),
                // hint which tools the chat should call first for this context
                required_tools: JSON.stringify([
                  "compare_funds",
                  "get_fund_metrics",
                  "get_holdings",
                  "get_benchmark_comparison",
                ]),
                // language compliance: never ask AI to recommend or rank FOR the user
                forbidden_phrases: JSON.stringify([
                  "recommend", "buy", "sell", "should I invest", "best fund",
                ]),
                // one entity entry per fund in the comparison
                selected_entities: JSON.stringify(
                  cData.funds.map(f => ({
                    schemecode: f.schemecode,
                    fund_name: f.fund_name,
                    category: f.category,
                  }))
                ),
              })
              navigate(`/chat?${params.toString()}`)
            }}
            className="flex items-center gap-1.5 text-xs bg-purple-600 text-white px-3 py-1.5 rounded-lg hover:bg-purple-700 transition-colors"
          >
            <Sparkles className="h-3 w-3" /> Ask about this comparison
          </button>
          <button disabled className="text-xs text-gray-300 cursor-not-allowed">
            Add to report (coming soon)
          </button>
          <button disabled className="text-xs text-gray-300 cursor-not-allowed">
            Export PDF (coming soon)
          </button>
        </div>
      )}
    </div>
  )
}
