import { useState, useEffect } from "react"
import { useQuery, useMutation } from "@tanstack/react-query"
import {
  RotateCcw, Send, Loader2, AlertCircle,
  TrendingUp, TrendingDown, Minus,
  ChevronDown, ChevronUp, TriangleAlert,
} from "lucide-react"
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
} from "recharts"
import { cn } from "@/lib/utils"
import { rulesApi, schemesApi, insightsApi, type RuleComponentOut, type Sector } from "@/lib/api"
import InsightPanel from "@/components/insights/InsightPanel"
import PocBadge from "@/components/insights/PocBadge"
import { FilterPanel, EMPTY_FILTERS, type FilterValues } from "./FilterPanel"

const COLORS = ["#2563EB", "#16A34A", "#7C3AED", "#D97706", "#6B7280"]
const RULE_SET_ID = "CLIENT-DEFAULT-LC"

function WeightBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="h-1.5 rounded-full bg-gray-100 flex-1">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="text-xs font-semibold text-gray-700 w-10 text-right">{pct}%</span>
    </div>
  )
}

function RankChangeCell({ change }: { change: number }) {
  if (change > 0) return (
    <span className="flex items-center justify-center gap-0.5 text-green-600 text-xs">
      <TrendingUp className="h-3 w-3" />{change}
    </span>
  )
  if (change < 0) return (
    <span className="flex items-center justify-center gap-0.5 text-red-500 text-xs">
      <TrendingDown className="h-3 w-3" />{Math.abs(change)}
    </span>
  )
  return <Minus className="h-3.5 w-3.5 text-gray-300 mx-auto" />
}

function ScoreChangeCell({ change }: { change: number }) {
  if (change > 0) return <span className="text-green-600 text-xs font-mono">+{change.toFixed(1)}</span>
  if (change < 0) return <span className="text-red-500 text-xs font-mono">{change.toFixed(1)}</span>
  return <span className="text-gray-400 text-xs font-mono">0.0</span>
}

function RuleInsightsPanel({
  sandbox,
  sandboxRun,
}: {
  sandbox: SandboxComponent[]
  sandboxRun: { results: { scheme_plan_id: string; fund_name: string; default_rank: number; sandbox_rank: number; rank_change: number; default_score: number; sandbox_score: number; score_change: number }[]; promoted_count: number; dropped_count: number } | null
}) {
  const weights: Record<string, number> = {}
  for (const c of sandbox) {
    weights[c.metric_id] = c.weight
  }

  const sandboxResults = sandboxRun?.results.map(r => ({
    schemecode: r.scheme_plan_id,
    fund_name: r.fund_name,
    composite_score: r.sandbox_score,
    score: r.sandbox_score,
    category: "",
  })) ?? []

  const currentTop10 = sandboxRun?.results
    .sort((a, b) => a.default_rank - b.default_rank)
    .slice(0, 10)
    .map(r => ({
      schemecode: r.scheme_plan_id,
      fund_name: r.fund_name,
      score: r.default_score,
    })) ?? []

  const { data, isLoading } = useQuery({
    queryKey: ["insights", "rule-playground", JSON.stringify(weights)],
    queryFn: () => insightsApi.rulePlayground(weights, sandboxResults, currentTop10),
    staleTime: 0,
    enabled: sandbox.length > 0,
  })

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-gray-700">Rule Validation Insights</span>
        <PocBadge />
      </div>
      <InsightPanel cards={data?.cards ?? []} isLoading={isLoading} />
    </div>
  )
}

interface SandboxComponent {
  id: string
  metric_id: string
  metric_name: string
  weight: number
  direction: string
  normalization: string
  window_years: number | null
  display_order: number
}

export default function RulePlaygroundPage() {
  const { data: ruleData, isLoading } = useQuery({
    queryKey: ["rules", "current", RULE_SET_ID],
    queryFn: () => rulesApi.getCurrent(RULE_SET_ID),
    staleTime: 10 * 60 * 1000,
  })

  const [sandbox, setSandbox] = useState<SandboxComponent[]>([])
  const [filters, setFilters] = useState<FilterValues>(EMPTY_FILTERS)
  const [sandboxRun, setSandboxRun] = useState<null | {
    results: {
      scheme_plan_id: string; fund_name: string
      default_rank: number; sandbox_rank: number; rank_change: number
      default_score: number; sandbox_score: number; score_change: number
    }[]
    promoted_count: number
    dropped_count: number
    warnings: string[]
  }>(null)

  const { data: amcData } = useQuery({
    queryKey: ["rules", "amcs"],
    queryFn: () => rulesApi.listAmcs(),
    staleTime: Infinity,
  })
  const { data: categoryData } = useQuery({
    queryKey: ["schemes", "categories"],
    queryFn: () => schemesApi.listCategories(),
    staleTime: Infinity,
  })
  const { data: categories36Data } = useQuery({
    queryKey: ["schemes", "categories-36"],
    queryFn: () => schemesApi.listCategories36(),
    staleTime: Infinity,
  })
  const { data: sectorsData } = useQuery({
    queryKey: ["rules", "sectors"],
    queryFn: () => rulesApi.listSectors(),
    staleTime: Infinity,
  })

  // Expanded table toggle
  const [showFullRanking, setShowFullRanking] = useState(false)

  useEffect(() => {
    if (ruleData && sandbox.length === 0) {
      setSandbox(ruleData.components.map((c: RuleComponentOut) => ({ ...c, weight: c.weight_pct })))
    }
  }, [ruleData])

  const totalWeight = sandbox.reduce((s, c) => s + c.weight, 0)
  const weightOk    = Math.abs(totalWeight - 100) < 1

  const donutData = sandbox.map((c, i) => ({
    name: c.metric_name,
    value: c.weight,
    color: COLORS[i % COLORS.length],
  }))

  const runMutation = useMutation({
    mutationFn: () => {
      // Build sector_exposure dict: each selected sector requires ≥0.01% exposure
      const sectorExp = filters.sector_names.length
        ? Object.fromEntries(filters.sector_names.map(s => [s, 0.01]))
        : null

      return rulesApi.sandboxRun({
        components: sandbox.map(c => ({ metric_id: c.metric_id, weight: c.weight })),
        // Eligibility
        category_id: filters.category || undefined,
        bucket_36: filters.bucket_36 || null,
        bucket_group: filters.bucket_group || null,
        amc_codes: filters.amc_codes.length ? filters.amc_codes : null,
        amc_exclude_codes: filters.amc_exclude_codes.length ? filters.amc_exclude_codes : null,
        status: filters.status,
        aum_min_cr: filters.aum_min_cr ? parseFloat(filters.aum_min_cr) : null,
        aum_max_cr: filters.aum_max_cr ? parseFloat(filters.aum_max_cr) : null,
        aum_freshness_days: filters.aum_freshness_days ? parseInt(filters.aum_freshness_days) : null,
        min_history_years: filters.min_history_years ? parseFloat(filters.min_history_years) : null,
        expense_ratio_max: filters.expense_ratio_max ? parseFloat(filters.expense_ratio_max) : null,
        plan_type: filters.plan_type || null,
        option_type: filters.option_type || null,
        exclude_elss: filters.exclude_elss,
        exclude_thematic: filters.exclude_thematic,
        // Data Quality
        exclude_merged: filters.exclude_merged,
        require_benchmark_mapped: filters.require_benchmark_mapped,
        holdings_freshness_max_months: filters.holdings_freshness_max_months
          ? parseInt(filters.holdings_freshness_max_months)
          : null,
        data_confidence_min: filters.data_confidence_min || null,
        min_return_history: filters.min_return_history || null,
        // Structural Improvement
        ir_percentile_min: filters.ir_percentile_min ? parseFloat(filters.ir_percentile_min) : null,
        outperformance_ratio_min: filters.outperformance_ratio_min
          ? parseFloat(filters.outperformance_ratio_min)
          : null,
        // Risk
        tracking_error_min: filters.tracking_error_min ? parseFloat(filters.tracking_error_min) : null,
        tracking_error_max: filters.tracking_error_max ? parseFloat(filters.tracking_error_max) : null,
        beta_min: filters.beta_min ? parseFloat(filters.beta_min) : null,
        beta_max: filters.beta_max ? parseFloat(filters.beta_max) : null,
        sharpe_min: filters.sharpe_min ? parseFloat(filters.sharpe_min) : null,
        sortino_min: filters.sortino_min ? parseFloat(filters.sortino_min) : null,
        // Portfolio
        holding_concentration_max: filters.holding_concentration_max
          ? parseFloat(filters.holding_concentration_max)
          : null,
        top10_concentration_max: filters.top10_concentration_max
          ? parseFloat(filters.top10_concentration_max)
          : null,
        holding_count_min: filters.holding_count_min ? parseInt(filters.holding_count_min) : null,
        holding_count_max: filters.holding_count_max ? parseInt(filters.holding_count_max) : null,
        sector_exposure: sectorExp,
      })
    },
    onSuccess: data => { setSandboxRun(data); setShowFullRanking(false) },
  })

  const resetToDefault = () => {
    if (ruleData) setSandbox(ruleData.components.map((c: RuleComponentOut) => ({ ...c, weight: c.weight_pct })))
    setFilters(EMPTY_FILTERS)
    setSandboxRun(null)
    setShowFullRanking(false)
  }

  const updateWeight = (id: string, val: number) =>
    setSandbox(prev => prev.map(c => c.id === id ? { ...c, weight: val } : c))

  const displayedRows = sandboxRun
    ? showFullRanking
      ? sandboxRun.results
      : sandboxRun.results.slice(0, 8)
    : []

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Rule Playground</h1>
          <p className="text-sm text-gray-500 mt-0.5">Test rule changes in a sandbox before applying them.</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={resetToDefault}
            className="flex items-center gap-1.5 text-sm border border-gray-200 rounded-xl px-4 py-2 hover:bg-gray-50 transition-colors"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset to default
          </button>
          <button className="flex items-center gap-1.5 text-sm bg-blue-600 text-white rounded-xl px-4 py-2 hover:bg-blue-700 transition-colors">
            <Send className="h-3.5 w-3.5" /> Submit for review
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16 text-gray-400 gap-2">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading rule set…</span>
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-4">

          {/* Col 0 — Filters */}
          <FilterPanel
            values={filters}
            onChange={setFilters}
            categories={categoryData?.categories ?? []}
            categories36={categories36Data ?? []}
            amcs={amcData ?? []}
            sectors={(sectorsData ?? []) as Sector[]}
          />

          {/* Col 1 — Current default rules */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="h-5 w-5 rounded-full bg-gray-200 flex items-center justify-center text-[10px] font-bold text-gray-600">D</span>
              <span className="text-sm font-semibold text-gray-700">Current Default Rules</span>
            </div>
            <p className="text-[11px] text-gray-400 mb-3">These are the rules used in current rankings.</p>
            <div className="space-y-3">
              {(ruleData?.components ?? []).map((c: RuleComponentOut, i: number) => (
                <div key={c.id} className="space-y-1">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-medium text-gray-800">{c.metric_name}</div>
                      <div className="text-[10px] text-gray-400 font-mono">{c.metric_id}</div>
                    </div>
                    <span className="text-xs font-bold text-gray-500">{c.weight_pct}%</span>
                  </div>
                  <WeightBar pct={c.weight_pct} color={COLORS[i % COLORS.length]} />
                </div>
              ))}
            </div>
            {ruleData && (
              <div className="mt-3 pt-3 border-t border-gray-100 text-[11px] text-gray-400">
                v{ruleData.version_number} · Total 100%
              </div>
            )}
          </div>

          {/* Col 2 — Impact preview */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="h-5 w-5 rounded-full bg-green-500 flex items-center justify-center text-[10px] font-bold text-white">2</span>
              <span className="text-sm font-semibold text-gray-700">Preview Impact</span>
            </div>

            {/* Weight donut */}
            <div className="mb-3">
              <p className="text-[11px] text-gray-400 mb-2">Weight Allocation</p>
              <ResponsiveContainer width="100%" height={140}>
                <PieChart>
                  <Pie data={donutData} cx="50%" cy="50%" innerRadius={40} outerRadius={58} dataKey="value">
                    {donutData.map((d) => <Cell key={d.name} fill={d.color} />)}
                  </Pie>
                  <Tooltip formatter={(v: number) => [`${v}%`, ""]} contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1">
                {donutData.map(d => (
                  <div key={d.name} className="flex items-center justify-between text-[11px]">
                    <span className="flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full" style={{ background: d.color }} />
                      <span className="text-gray-600 truncate max-w-[120px]">{d.name}</span>
                    </span>
                    <span className="font-semibold text-gray-700">{d.value}%</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Weight validation */}
            <div className={cn(
              "rounded-lg px-3 py-2 text-xs font-medium flex items-center gap-2 mb-3",
              weightOk ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600",
            )}>
              {weightOk
                ? <><span className="text-green-500">✓</span> Total weight = 100%</>
                : <><AlertCircle className="h-3.5 w-3.5" /> Total = {totalWeight}% (must equal 100%)</>}
            </div>

            {/* Run button */}
            {!sandboxRun && (
              <button
                disabled={!weightOk || runMutation.isPending}
                onClick={() => runMutation.mutate()}
                className={cn(
                  "w-full text-sm rounded-xl px-4 py-2.5 font-medium transition-colors",
                  weightOk
                    ? "bg-blue-600 text-white hover:bg-blue-700"
                    : "bg-gray-100 text-gray-400 cursor-not-allowed",
                )}
              >
                {runMutation.isPending ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Running…
                  </span>
                ) : "Preview impact"}
              </button>
            )}

            {sandboxRun && (
              <button
                onClick={() => { setSandboxRun(null); setShowFullRanking(false) }}
                className="w-full text-xs text-gray-500 border border-gray-200 rounded-xl px-4 py-1.5 hover:bg-gray-50 transition-colors"
              >
                Clear results
              </button>
            )}
          </div>

          {/* Col 3 — Sandbox rules (editable) */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="h-5 w-5 rounded-full bg-blue-600 flex items-center justify-center text-[10px] font-bold text-white">1</span>
              <span className="text-sm font-semibold text-gray-700">Edit Rules Here</span>
            </div>
            <div className="space-y-4">
              {sandbox.map((c) => {
                const defaultComp = ruleData?.components.find((d: RuleComponentOut) => d.id === c.id)
                const changed = defaultComp && c.weight !== defaultComp.weight_pct
                return (
                  <div key={c.id} className={cn("rounded-xl p-3 border transition-colors", changed ? "border-blue-300 bg-blue-50/40" : "border-gray-100")}>
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <div className="text-xs font-semibold text-gray-800">
                          {c.metric_name}
                          {changed && <span className="ml-1.5 text-[10px] text-blue-600">modified</span>}
                        </div>
                        <div className="text-[10px] text-gray-400 font-mono">{c.metric_id}</div>
                      </div>
                      <span className="text-sm font-bold text-blue-600">{c.weight}%</span>
                    </div>
                    <input
                      type="range" min={5} max={60} step={5}
                      value={c.weight}
                      onChange={e => updateWeight(c.id, Number(e.target.value))}
                      className="w-full accent-blue-600 h-1.5"
                    />
                    <div className="flex justify-between text-[9px] text-gray-300 mt-0.5">
                      <span>5%</span><span>60%</span>
                    </div>
                  </div>
                )
              })}
            </div>
            <div className={cn("mt-3 pt-3 border-t text-xs font-semibold", weightOk ? "text-green-600" : "text-red-500")}>
              Total weight: {totalWeight}%
            </div>
          </div>
        </div>
      )}

      {/* Sandbox results table */}
      {sandboxRun && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-gray-800">Sandbox Ranking Results</span>
              <span className="text-[11px] bg-green-50 text-green-700 px-2 py-0.5 rounded-full border border-green-200">
                {sandboxRun.promoted_count} promoted
              </span>
              <span className="text-[11px] bg-red-50 text-red-600 px-2 py-0.5 rounded-full border border-red-200">
                {sandboxRun.dropped_count} dropped
              </span>
              <span className="text-[11px] text-gray-400">{sandboxRun.results.length} funds</span>
            </div>
            <button
              onClick={() => setShowFullRanking(p => !p)}
              className="flex items-center gap-1.5 text-xs text-blue-600 border border-blue-200 rounded-lg px-2.5 py-1 hover:bg-blue-50 transition-colors"
            >
              {showFullRanking ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {showFullRanking ? "Show compact" : "View full ranking"}
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="text-left px-4 py-2.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Fund</th>
                  <th className="text-center px-3 py-2.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Default Rank</th>
                  <th className="text-center px-3 py-2.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Sandbox Rank</th>
                  <th className="text-center px-3 py-2.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Rank Δ</th>
                  {showFullRanking && (
                    <>
                      <th className="text-center px-3 py-2.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Default Score</th>
                      <th className="text-center px-3 py-2.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Sandbox Score</th>
                      <th className="text-center px-3 py-2.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Score Δ</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {displayedRows.map(r => (
                  <tr
                    key={r.scheme_plan_id}
                    className={cn(
                      "hover:bg-gray-50 transition-colors",
                      r.rank_change > 0 ? "bg-green-50/30" : r.rank_change < 0 ? "bg-red-50/20" : "",
                    )}
                  >
                    <td className="px-4 py-2.5 font-medium text-gray-800 max-w-[200px] truncate">{r.fund_name}</td>
                    <td className="px-3 py-2.5 text-center text-gray-500">{r.default_rank}</td>
                    <td className="px-3 py-2.5 text-center font-semibold text-gray-800">{r.sandbox_rank}</td>
                    <td className="px-3 py-2.5 text-center"><RankChangeCell change={r.rank_change} /></td>
                    {showFullRanking && (
                      <>
                        <td className="px-3 py-2.5 text-center font-mono text-gray-500">{r.default_score.toFixed(1)}</td>
                        <td className="px-3 py-2.5 text-center font-mono font-semibold text-gray-700">{r.sandbox_score.toFixed(1)}</td>
                        <td className="px-3 py-2.5 text-center"><ScoreChangeCell change={r.score_change} /></td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!showFullRanking && sandboxRun.results.length > 8 && (
            <div className="px-4 py-2 border-t border-gray-100 text-center">
              <button
                onClick={() => setShowFullRanking(true)}
                className="text-xs text-blue-600 hover:underline"
              >
                Show all {sandboxRun.results.length} funds
              </button>
            </div>
          )}
        </div>
      )}

      {/* Filter warnings from backend (stubs / data gaps) */}
      {sandboxRun && sandboxRun.warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2 mb-1.5 text-xs font-semibold text-amber-800">
            <TriangleAlert className="h-3.5 w-3.5" />
            {sandboxRun.warnings.length} filter{sandboxRun.warnings.length > 1 ? "s" : ""} skipped (data not yet available)
          </div>
          <ul className="space-y-0.5">
            {sandboxRun.warnings.map((w, i) => (
              <li key={i} className="text-[11px] text-amber-700">· {w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Rule Validation Insights */}
      <RuleInsightsPanel sandbox={sandbox} sandboxRun={sandboxRun} />

      <div className="text-xs text-gray-400 text-right">
        Sandbox only — rules require explicit approval before going live.
      </div>
    </div>
  )
}
