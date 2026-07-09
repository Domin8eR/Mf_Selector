import { useState, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  ArrowUp, ArrowDown, Minus, ChevronRight, ChevronUp, ChevronDown,
  Search, Info, BarChart2, CheckSquare, MessageSquare, X,
} from "lucide-react"
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from "recharts"
import { cn } from "@/lib/utils"
import {
  rankingsV2Api, insightsApi,
  type RankedFund, type ExplainComponent,
} from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"
import InsightPanel from "@/components/insights/InsightPanel"

// ── Category options ──────────────────────────────────────────────────────────
const CATEGORIES = [
  "Equity — Large Cap",
  "Equity — Mid Cap",
  "Equity — Small Cap",
] as const
type Category = (typeof CATEGORIES)[number]

// ── Status badge colours ──────────────────────────────────────────────────────
const STATUS_COLOURS: Record<string, string> = {
  Strong:  "bg-emerald-50 text-emerald-700 border border-emerald-200",
  Good:    "bg-blue-50   text-blue-700   border border-blue-200",
  Neutral: "bg-gray-50   text-gray-600   border border-gray-300",
  Weak:    "bg-red-50    text-red-700    border border-red-200",
}

// ── Bump-chart colour palette (top-10 lines) ──────────────────────────────────
const LINE_COLORS = [
  "#6366f1","#10b981","#f59e0b","#ef4444","#3b82f6",
  "#8b5cf6","#06b6d4","#f97316","#ec4899","#84cc16",
]

type SortKey = "rank" | "composite_score" | "ir_3yr" | "sharpe_3yr"
               | "active_ret_3yr" | "ir_slope_6m_proxy" | "tracking_error_3yr"

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "—"
  return v.toFixed(decimals)
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

// ── Explain Rank Drawer ───────────────────────────────────────────────────────
function ExplainDrawer({
  schemecode,
  fundName,
  category,
  onClose,
}: {
  schemecode: number
  fundName: string
  category: string
  onClose: () => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.rankings.explain(schemecode, category),
    queryFn: () => rankingsV2Api.explain(schemecode, category),
  })

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative z-10 w-full max-w-md bg-white shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <div>
            <p className="text-xs text-gray-500 mb-0.5">Rank Explanation</p>
            <h2 className="text-sm font-semibold text-gray-900 leading-tight">{fundName}</h2>
          </div>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100">
            <X className="h-4 w-4 text-gray-500" />
          </button>
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
            Loading breakdown…
          </div>
        ) : !data ? (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
            No data available.
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
            <div className="flex flex-wrap gap-2">
              <span className="px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 text-xs font-medium border border-indigo-200">
                Rank {data.rank} / {data.total_in_category}
              </span>
              <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium", STATUS_COLOURS[data.status_label] ?? "bg-gray-50 text-gray-600 border border-gray-200")}>
                {data.status_label}
              </span>
              <span className="px-2 py-0.5 rounded-full bg-gray-50 text-gray-700 text-xs border border-gray-200">
                Score {data.composite_score.toFixed(1)} / 100
              </span>
              <span className="px-2 py-0.5 rounded-full bg-gray-50 text-gray-600 text-xs border border-gray-200">
                Confidence: {data.confidence}
              </span>
            </div>

            <div>
              <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-3">
                Score Breakdown
              </p>
              <div className="space-y-3">
                {data.components.map((c: ExplainComponent) => (
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
              <p><span className="font-medium text-gray-700">Rule version:</span> {data.rule_version}</p>
              <p><span className="font-medium text-gray-700">Evaluated on:</span> {data.evaluation_date}</p>
              <p><span className="font-medium text-gray-700">Data version:</span> {data.data_version} · calc {data.calculation_version}</p>
              <p className="text-[10px] text-gray-400 mt-1">
                Scores are pre-computed percentile ranks within category — no AI was used in metric calculation.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Bump Chart ────────────────────────────────────────────────────────────────
function BumpChart({ category }: { category: string }) {
  const TOP_N = 10
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.rankings.history(category, TOP_N),
    queryFn: () => rankingsV2Api.getHistory(category, TOP_N),
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

  const shortName = (name: string) => name.split(" ").slice(0, 3).join(" ")

  return (
    <div>
      <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-3">
        Rank History — Top {TOP_N} (6 months)
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: "#9ca3af" }}
            tickFormatter={(v: string) => {
              const d = new Date(v)
              return d.toLocaleString("default", { month: "short" })
            }}
          />
          <YAxis
            reversed
            tick={{ fontSize: 9, fill: "#9ca3af" }}
            tickCount={6}
            domain={["dataMin - 1", "dataMax + 1"]}
          />
          <Tooltip
            formatter={(v: unknown, name: string) => [`Rank ${v ?? "—"}`, shortName(name)]}
            labelFormatter={(l: string) => `Date: ${l}`}
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
            <span className="truncate" title={s.fund_name}>{shortName(s.fund_name)}</span>
            <span className="ml-auto text-gray-400 shrink-0">#{s.latest_rank}</span>
          </div>
        ))}
      </div>
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
  onExplain,
}: {
  fund: RankedFund
  isSelected: boolean
  onToggleSelect: () => void
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
    <tr className={cn("border-b border-gray-50 hover:bg-gray-50/60 transition-colors", isSelected && "bg-indigo-50/30")}>
      <td className="px-3 py-2 text-center">
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
        <span
          className="text-xs font-medium text-gray-900 hover:text-indigo-700 cursor-pointer line-clamp-2"
          title={fund.fund_name}
        >
          {fund.fund_name}
        </span>
      </td>
      <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{fund.amc_name}</td>
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
      <td className="px-3 py-2 text-center">
        {fmtDelta(fund.rank_delta_6m != null ? -fund.rank_delta_6m : null)}
      </td>
      <td className="px-3 py-2">
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

  const [category, setCategory] = useState<Category>("Equity — Large Cap")
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 50

  const [sortKey, setSortKey] = useState<SortKey>("rank")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [explainFund, setExplainFund] = useState<{ schemecode: number; name: string } | null>(null)

  const { data: rankData, isLoading: rankLoading } = useQuery({
    queryKey: queryKeys.rankings.v2Category(category, undefined, debouncedSearch, page),
    queryFn: () => rankingsV2Api.getCategory({
      category,
      search: debouncedSearch || undefined,
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
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 font-medium">Rule Set</label>
          <span className="text-sm text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 bg-gray-50">
            Client Default v1.0
          </span>
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
          onClick={() => navigate("/research-chat")}
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
                  <th className="text-center text-[10px] font-semibold text-gray-500 uppercase tracking-wide py-2 px-3">6m Δ</th>
                  <th className="w-8 px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {rankLoading ? (
                  <tr>
                    <td colSpan={13} className="text-center py-12 text-gray-400 text-sm">
                      Loading ranked funds…
                    </td>
                  </tr>
                ) : sortedFunds.length === 0 ? (
                  <tr>
                    <td colSpan={13} className="text-center py-12 text-gray-400 text-sm">
                      No ranked funds found.
                    </td>
                  </tr>
                ) : (
                  sortedFunds.map((fund) => (
                    <FundRow
                      key={fund.schemecode}
                      fund={fund}
                      isSelected={selected.has(fund.schemecode)}
                      onToggleSelect={() => toggleSelect(fund.schemecode)}
                      onExplain={() => setExplainFund({ schemecode: fund.schemecode, name: fund.fund_name })}
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
          <BumpChart category={category} />

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

      {explainFund && (
        <ExplainDrawer
          schemecode={explainFund.schemecode}
          fundName={explainFund.name}
          category={category}
          onClose={() => setExplainFund(null)}
        />
      )}
    </div>
  )
}
