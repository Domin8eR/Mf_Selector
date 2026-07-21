import { useState, useMemo, useEffect, useRef } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useQuery, useMutation } from "@tanstack/react-query"
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
} from "recharts"
import {
  BrainCircuit,
  Share2,
  Plus,
  ChevronDown,
  ArrowRight,
  Save,
  ExternalLink,
  Loader2,
  AlertTriangle,
  Tag,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import InsightCard from "@/components/insights/InsightCard"
import {
  workspaceApi,
  lensApi,
  type LensSpec,
  type ScatterPoint,
  type LensScatterResponse,
  type InsightCardData,
} from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"
import { cn } from "@/lib/utils"

// ── Constants ─────────────────────────────────────────────────────────────────

const QUADRANT_LABELS: Record<string, string> = {
  "improving-strong": "Improving & Strong",
  "improving-weak": "Improving & Weak",
  "declining-strong": "Declining & Strong",
  "declining-weak": "Declining & Weak",
}

const QUADRANT_DOT_FILL: Record<string, string> = {
  "improving-strong": "#16a34a",
  "improving-weak": "#2563eb",
  "declining-strong": "#d97706",
  "declining-weak": "#dc2626",
}

const QUADRANT_AREA_FILL: Record<string, string> = {
  "improving-strong": "#dcfce7",
  "improving-weak": "#dbeafe",
  "declining-strong": "#fef3c7",
  "declining-weak": "#fee2e2",
}

// Real bucket_36 taxonomy values (see /rankings/categories). The pre-migration
// "Equity — X" labels don't 400 here — worse, selfmade_ranking_snapshot still
// has orphaned historical rows under those exact legacy labels (last written
// 2026-07-09, the day before the taxonomy migration), so lens-scatter was
// silently serving ~11-day-stale data instead of erroring. The "Debt — X"
// duration categories are left as-is: there is no real bucket_36 equivalent
// and no ranking data (old or new label) has ever existed for them.
const CATEGORIES = [
  "Large Cap",
  "Mid Cap",
  "Small Cap",
  "Multi Cap",
  "ELSS",
  "Debt — Short Duration",
  "Debt — Medium Duration",
  "Debt — Long Duration",
]

const QUADRANT_OPTIONS: { value: string | null; label: string }[] = [
  { value: null, label: "All quadrants" },
  { value: "improving-strong", label: "Improving & Strong" },
  { value: "improving-weak", label: "Improving & Weak" },
  { value: "declining-strong", label: "Declining & Strong" },
  { value: "declining-weak", label: "Declining & Weak" },
]

// ── Types ─────────────────────────────────────────────────────────────────────

type SortKey = "fund_name" | "x_value" | "y_value" | "ir_3yr" | "rank_in_category" | "rank_delta_6m"

// ── Sub-components ────────────────────────────────────────────────────────────

function SortIcon({ col, current, dir }: { col: SortKey; current: SortKey; dir: "asc" | "desc" }) {
  if (col !== current) return <ArrowUpDown className="h-3 w-3 opacity-30" />
  return dir === "asc"
    ? <ArrowUp className="h-3 w-3 text-blue-600" />
    : <ArrowDown className="h-3 w-3 text-blue-600" />
}

function CustomTooltip({ active, payload }: {
  active?: boolean
  payload?: Array<{ payload: ScatterPoint }>
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs max-w-[230px] z-50">
      <p className="font-semibold text-gray-900 mb-1 leading-tight">{p.fund_name}</p>
      <p className="text-gray-500 mb-2">
        <span
          className="inline-block h-2 w-2 rounded-full mr-1 align-middle"
          style={{ backgroundColor: QUADRANT_DOT_FILL[p.quadrant] ?? "#6b7280" }}
        />
        {QUADRANT_LABELS[p.quadrant] ?? p.quadrant}
      </p>
      <div className="space-y-0.5">
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">3Y IR</span>
          <span className="font-mono">{p.ir_3yr?.toFixed(3) ?? "—"}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">IR Slope</span>
          <span className="font-mono">{p.y_value?.toFixed(4) ?? "—"}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">Rank</span>
          <span>#{p.rank_in_category ?? "—"}</span>
        </div>
        {p.rank_delta_6m !== null && (
          <div className="flex justify-between gap-4">
            <span className="text-gray-400">Rank Δ 6m</span>
            <span className={cn(
              "font-medium",
              p.rank_delta_6m < 0 ? "text-green-600" : p.rank_delta_6m > 0 ? "text-red-600" : "text-gray-500"
            )}>
              {p.rank_delta_6m > 0 ? `+${p.rank_delta_6m}` : p.rank_delta_6m}
            </span>
          </div>
        )}
      </div>
      {p.note && <p className="mt-2 text-gray-400 italic leading-tight">{p.note}</p>}
      <p className="mt-1.5 text-blue-500 text-[10px]">Click to open fund detail →</p>
    </div>
  )
}

// ── Client-side insight generation (deterministic, no LLM) ──────────────────
// Mirrors the backend's LENS_*_V1 templates (app/insights/templates.py) and
// app.routers.metrics._lens_threshold_phrase — rendered through the shared
// CompactInsightCard (components/insights/InsightCard.tsx) like every other
// page, for a fresh (unsaved) query that hasn't round-tripped through
// GET /workspaces/{id} yet.

function lensThresholdPhrase(label: string, threshold: number): string {
  if (threshold === 0) return "a flat (zero-change) line"
  return `the category median (${label} = ${threshold.toFixed(3)})`
}

function buildClientInsights(
  scatter: LensScatterResponse,
  activeCategory: string,
  activeQuadrant: string | null,
): InsightCardData[] {
  const fundCount = scatter.total_funds

  const explainer: InsightCardData = {
    template_id: "LENS_QUADRANT_EXPLAINER_V1",
    insight_code: "lens_quadrant_explainer",
    severity: "neutral",
    priority: 1,
    compact_text: `**Axis guide:** ${scatter.x_label} (right) vs ${scatter.y_label} (up) — ${fundCount} funds in ${activeCategory}.`,
    expanded_bullets: [
      `Each dot = one **${activeCategory}** fund (${fundCount} total).`,
      `Further right = ${scatter.x_direction_phrase} (**${scatter.x_label}**).`,
      scatter.y_axis_meaning,
      `**Dashed lines** split funds into 4 groups using ${lensThresholdPhrase(scatter.x_label, scatter.x_threshold)} and ${lensThresholdPhrase(scatter.y_label, scatter.y_threshold)}.`,
    ],
    chips: { fund_count: fundCount, category: activeCategory, x_label: scatter.x_label, y_label: scatter.y_label },
    facts_json: {},
    generated_by: "deterministic-template",
    prompt_tokens: 0,
    follow_up_actions: [],
  }

  const targetQ = activeQuadrant ?? "improving-strong"
  const qLabel = QUADRANT_LABELS[targetQ] ?? targetQ
  const count = scatter.quadrant_counts[targetQ] ?? scatter.points.filter(p => p.quadrant === targetQ).length
  const filterSummary =
    `${scatter.x_label} ${targetQ.includes("strong") ? "≥" : "<"} median ` +
    `AND ${scatter.y_label} ${targetQ.includes("improving") ? "≥" : "<"} ${scatter.y_threshold}`

  let candidateCard: InsightCardData
  if (count > 0) {
    const topFunds = scatter.points
      .filter(p => p.quadrant === targetQ)
      .sort((a, b) => b.x_value - a.x_value)
      .slice(0, 5)
      .map(p => `${p.fund_name} (${p.x_value.toFixed(3)})`)
      .join("; ")
    candidateCard = {
      template_id: "LENS_CANDIDATES_FOUND_V1",
      insight_code: "lens_candidates_found",
      severity: "positive",
      priority: 5,
      compact_text: `**${count} research candidate(s)** found in the ${qLabel} quadrant of ${activeCategory}.`,
      expanded_bullets: [
        `**Filter:** ${filterSummary}`,
        `**Category:** ${activeCategory}`,
        `**Top by ${scatter.x_label}:** ${topFunds}`,
      ],
      chips: { count, category: activeCategory, quadrant_label: qLabel },
      facts_json: {},
      generated_by: "deterministic-template",
      prompt_tokens: 0,
      follow_up_actions: [],
    }
  } else {
    candidateCard = {
      template_id: "LENS_CANDIDATES_NONE_V1",
      insight_code: "lens_candidates_none",
      severity: "neutral",
      priority: 10,
      compact_text: `**No funds** match ${qLabel} in ${activeCategory}.`,
      expanded_bullets: [
        `**Filter:** ${filterSummary}`,
        `**Category:** ${activeCategory}`,
        `**Try:** loosen the filter or switch quadrants.`,
      ],
      chips: { category: activeCategory, quadrant_label: qLabel },
      facts_json: {},
      generated_by: "deterministic-template",
      prompt_tokens: 0,
      follow_up_actions: [],
    }
  }

  return [explainer, candidateCard]
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WorkspacePage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const wsId = searchParams.get("ws") ? parseInt(searchParams.get("ws")!, 10) : null

  // Header
  const [workspaceName, setWorkspaceName] = useState("Untitled workspace")
  const [isEditingName, setIsEditingName] = useState(false)
  const nameInputRef = useRef<HTMLInputElement>(null)

  // Query + filter
  const [queryInput, setQueryInput] = useState("")
  const [lensSpec, setLensSpec] = useState<LensSpec | null>(null)
  const [category, setCategory] = useState("Large Cap")
  const [quadrantFilter, setQuadrantFilter] = useState<string | null>(null)
  const [showCategoryDropdown, setShowCategoryDropdown] = useState(false)
  const [showQuadrantDropdown, setShowQuadrantDropdown] = useState(false)

  // UI state
  const [isSaved, setIsSaved] = useState(false)
  const [selectedPoint, setSelectedPoint] = useState<number | null>(null)

  // Table sort
  const [sortCol, setSortCol] = useState<SortKey>("x_value")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  // ── Derived active values ─────────────────────────────────────────────────

  const activeX = lensSpec?.x_metric ?? "information_ratio_3yr"
  const activeY = lensSpec?.y_metric ?? "ir_slope_6m_proxy"
  const activeCategory = lensSpec?.category ?? category
  const activeQuadrant = lensSpec?.quadrant_filter ?? quadrantFilter

  // ── Existing workspace load ───────────────────────────────────────────────

  const existingWsQuery = useQuery({
    queryKey: queryKeys.workspace.get(wsId!),
    queryFn: () => workspaceApi.get(wsId!),
    enabled: wsId !== null,
  })

  useEffect(() => {
    if (existingWsQuery.data && wsId !== null) {
      const ws = existingWsQuery.data
      setWorkspaceName(ws.name)
      setCategory(ws.category ?? "Large Cap")
      setIsSaved(true)
      if (ws.query_text) setQueryInput(ws.query_text)
      if (ws.scatter?.x_metric) {
        setLensSpec({
          x_metric: ws.x_metric,
          y_metric: ws.y_metric,
          x_label: ws.scatter.x_label,
          y_label: ws.scatter.y_label,
          category: ws.category,
          quadrant_filter: ws.scatter.quadrant_filter,
          filter_summary_text: ws.filter_summary ?? "",
          refusal_reason: null,
          classifier: "saved",
        })
      }
    }
  }, [existingWsQuery.data, wsId])

  // ── NL interpretation mutation ────────────────────────────────────────────

  const interpretMutation = useMutation({
    mutationFn: (msg: string) => workspaceApi.interpretQuery(msg, category),
    onSuccess: (spec) => {
      setLensSpec(spec)
      if (spec.category && !spec.refusal_reason) setCategory(spec.category)
    },
  })

  // ── Scatter data (used when not loading from saved workspace) ─────────────

  const scatterQuery = useQuery({
    queryKey: queryKeys.workspace.scatter(activeCategory, activeX, activeY, activeQuadrant ?? ""),
    queryFn: () =>
      lensApi.getScatter({
        category: activeCategory,
        x_metric: activeX,
        y_metric: activeY,
        quadrant_filter: activeQuadrant ?? undefined,
      }),
    enabled: wsId === null,
  })

  const scatter: LensScatterResponse | undefined =
    wsId ? existingWsQuery.data?.scatter : scatterQuery.data

  // Client-side deterministic insights for fresh (unsaved) queries
  const savedInsights: InsightCardData[] = wsId ? (existingWsQuery.data?.insights ?? []) : []
  const clientInsights = useMemo(
    () => (scatter && !wsId ? buildClientInsights(scatter, activeCategory, activeQuadrant) : []),
    [scatter, wsId, activeCategory, activeQuadrant],
  )
  const displayInsights = wsId ? savedInsights : clientInsights

  // ── Chart domain ──────────────────────────────────────────────────────────

  const { xMin, xMax, yMin, yMax } = useMemo(() => {
    if (!scatter?.points.length) return { xMin: -1, xMax: 1, yMin: -1, yMax: 1 }
    const xs = scatter.points.map(p => p.x_value)
    const ys = scatter.points.map(p => p.y_value)
    const xRange = Math.max(...xs) - Math.min(...xs) || 1
    const yRange = Math.max(...ys) - Math.min(...ys) || 1
    return {
      xMin: Math.min(...xs) - xRange * 0.12,
      xMax: Math.max(...xs) + xRange * 0.12,
      yMin: Math.min(...ys) - yRange * 0.15,
      yMax: Math.max(...ys) + yRange * 0.15,
    }
  }, [scatter])

  const xThresh = scatter?.x_threshold ?? 0
  const yThresh = scatter?.y_threshold ?? 0

  // ── Table rows ────────────────────────────────────────────────────────────

  const sortedPoints = useMemo(() => {
    if (!scatter) return []
    return [...scatter.points].sort((a, b) => {
      const av = a[sortCol]
      const bv = b[sortCol]
      if (av === null || av === undefined) return 1
      if (bv === null || bv === undefined) return -1
      const cmp =
        typeof av === "string"
          ? av.localeCompare(bv as string)
          : (av as number) < (bv as number)
            ? -1
            : (av as number) > (bv as number)
              ? 1
              : 0
      return sortDir === "asc" ? cmp : -cmp
    })
  }, [scatter, sortCol, sortDir])

  const toggleSort = (col: SortKey) => {
    if (sortCol === col) setSortDir(d => (d === "asc" ? "desc" : "asc"))
    else {
      setSortCol(col)
      setSortDir("desc")
    }
  }

  // ── Save mutation ─────────────────────────────────────────────────────────

  const saveMutation = useMutation({
    mutationFn: () =>
      workspaceApi.create({
        name: workspaceName,
        category: activeCategory,
        x_metric: activeX,
        y_metric: activeY,
        query_text: queryInput || undefined,
        filter_summary: lensSpec?.filter_summary_text || undefined,
      }),
    onSuccess: (ws) => {
      setIsSaved(true)
      setSearchParams({ ws: String(ws.id) })
    },
  })

  const isLoading = wsId
    ? existingWsQuery.isLoading
    : scatterQuery.isLoading && !scatter

  const refusalReason = lensSpec?.refusal_reason

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = () => {
      setShowCategoryDropdown(false)
      setShowQuadrantDropdown(false)
    }
    document.addEventListener("click", handler)
    return () => document.removeEventListener("click", handler)
  }, [])

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* ── Header ── */}
      <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-4 flex-shrink-0">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <BrainCircuit className="h-5 w-5 text-purple-500 flex-shrink-0" />
          {isEditingName ? (
            <input
              ref={nameInputRef}
              className="text-base font-semibold text-gray-900 border-b border-blue-400 outline-none bg-transparent min-w-0 max-w-xs"
              value={workspaceName}
              onChange={e => setWorkspaceName(e.target.value)}
              onBlur={() => setIsEditingName(false)}
              onKeyDown={e => e.key === "Enter" && setIsEditingName(false)}
              autoFocus
            />
          ) : (
            <button
              className="text-base font-semibold text-gray-900 hover:text-blue-600 truncate text-left"
              onClick={() => setIsEditingName(true)}
            >
              {workspaceName}
            </button>
          )}
          {!isSaved && (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full flex-shrink-0">
              Temporary analysis workspace
            </span>
          )}
          {isSaved && (
            <span className="text-xs text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded-full flex-shrink-0">
              Saved
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <Button variant="ghost" size="sm" disabled className="text-gray-400 cursor-not-allowed">
            <Share2 className="h-3.5 w-3.5 mr-1.5" />
            Share
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setSearchParams({})
              setWorkspaceName("Untitled workspace")
              setQueryInput("")
              setLensSpec(null)
              setIsSaved(false)
              setCategory("Large Cap")
              setQuadrantFilter(null)
              setSelectedPoint(null)
            }}
          >
            <Plus className="h-3.5 w-3.5 mr-1.5" />
            New Workspace
          </Button>
        </div>
      </div>

      {/* ── Query bar ── */}
      <div className="bg-white border-b border-gray-100 px-6 py-3 flex-shrink-0">
        <div className="flex items-start gap-3">
          {/* Query input */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 focus-within:border-blue-400 focus-within:ring-1 focus-within:ring-blue-100 transition-shadow">
              <BrainCircuit className="h-4 w-4 text-purple-400 flex-shrink-0" />
              <input
                className="flex-1 text-sm bg-transparent outline-none text-gray-800 placeholder:text-gray-400 min-w-0"
                placeholder="Describe what you're looking for — e.g. 'large cap funds with improving IR and strong composite score'"
                value={queryInput}
                onChange={e => setQueryInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter" && queryInput.trim()) {
                    interpretMutation.mutate(queryInput.trim())
                  }
                }}
              />
              <Button
                size="sm"
                onClick={() => interpretMutation.mutate(queryInput.trim())}
                disabled={!queryInput.trim() || interpretMutation.isPending}
                className="flex-shrink-0"
              >
                {interpretMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ArrowRight className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>

            {/* Interpreted query echo */}
            {lensSpec && !refusalReason && (
              <p className="text-xs text-gray-500 mt-1.5 pl-1">
                Interpreted: {lensSpec.filter_summary_text}
                <span className="text-gray-400 ml-1.5">via {lensSpec.classifier}</span>
              </p>
            )}

            {/* Refusal / reframe message */}
            {refusalReason && (
              <div className="flex items-start gap-2 mt-2 p-2.5 bg-amber-50 border border-amber-200 rounded-lg">
                <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-amber-800 leading-relaxed">{refusalReason}</p>
              </div>
            )}
          </div>

          {/* Filter chips */}
          <div
            className="flex items-center gap-2 flex-shrink-0 pt-1"
            onClick={e => e.stopPropagation()}
          >
            {/* Category chip */}
            <div className="relative">
              <button
                onClick={() => {
                  setShowCategoryDropdown(v => !v)
                  setShowQuadrantDropdown(false)
                }}
                className="flex items-center gap-1.5 text-xs bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-3 py-1.5 hover:bg-blue-100 transition-colors"
              >
                <Tag className="h-3 w-3" />
                {activeCategory.length > 20 ? activeCategory.slice(0, 20) + "…" : activeCategory}
                <ChevronDown className="h-3 w-3" />
              </button>
              {showCategoryDropdown && (
                <div className="absolute top-full mt-1 right-0 z-30 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[210px]">
                  {CATEGORIES.map(c => (
                    <button
                      key={c}
                      className={cn(
                        "w-full text-left text-xs px-3 py-2 hover:bg-gray-50 transition-colors",
                        c === activeCategory && "font-semibold text-blue-700 bg-blue-50",
                      )}
                      onClick={() => {
                        setCategory(c)
                        setShowCategoryDropdown(false)
                        if (lensSpec) setLensSpec({ ...lensSpec, category: c })
                      }}
                    >
                      {c}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Quadrant chip */}
            <div className="relative">
              <button
                onClick={() => {
                  setShowQuadrantDropdown(v => !v)
                  setShowCategoryDropdown(false)
                }}
                className="flex items-center gap-1.5 text-xs bg-gray-100 text-gray-700 border border-gray-200 rounded-full px-3 py-1.5 hover:bg-gray-200 transition-colors"
              >
                {activeQuadrant ? QUADRANT_LABELS[activeQuadrant] : "All quadrants"}
                <ChevronDown className="h-3 w-3" />
              </button>
              {showQuadrantDropdown && (
                <div className="absolute top-full mt-1 right-0 z-30 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[190px]">
                  {QUADRANT_OPTIONS.map(opt => (
                    <button
                      key={opt.value ?? "all"}
                      className={cn(
                        "w-full text-left text-xs px-3 py-2 hover:bg-gray-50 transition-colors",
                        opt.value === activeQuadrant && "font-semibold text-blue-700 bg-blue-50",
                      )}
                      onClick={() => {
                        setQuadrantFilter(opt.value)
                        setShowQuadrantDropdown(false)
                        if (lensSpec) setLensSpec({ ...lensSpec, quadrant_filter: opt.value })
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        {isLoading && (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-gray-300" />
          </div>
        )}

        {!isLoading && !scatter && (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <BrainCircuit className="h-12 w-12 text-gray-200 mb-3" />
            <p className="text-sm font-medium text-gray-500">Describe what you're looking for</p>
            <p className="text-xs text-gray-400 mt-1 max-w-[400px] leading-relaxed">
              Type a natural-language query above — e.g. "large cap funds with improving IR and strong composite score" — and press Enter.
            </p>
          </div>
        )}

        {!isLoading && scatter && (
          <div className="flex-1 flex overflow-hidden">
            {/* ── Left: chart + table ── */}
            <div className="flex-1 min-w-0 overflow-y-auto p-6 space-y-5">
              {/* Scatter chart */}
              <Card>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm font-semibold text-gray-800">
                      {scatter.x_label}
                      <span className="text-gray-400 font-normal"> (x) </span>
                      vs {scatter.y_label}
                      <span className="text-gray-400 font-normal"> (y)</span>
                      <span className="text-gray-400 font-normal ml-2">— {activeCategory}</span>
                    </CardTitle>
                    <span className="text-xs text-gray-400">{scatter.total_funds} funds</span>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <ResponsiveContainer width="100%" height={360}>
                    <ScatterChart margin={{ top: 20, right: 30, bottom: 44, left: 55 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />

                      {/* Quadrant background areas */}
                      <ReferenceArea
                        x1={xMin} x2={xThresh} y1={yThresh} y2={yMax}
                        fill={QUADRANT_AREA_FILL["improving-weak"]}
                        fillOpacity={0.45}
                      />
                      <ReferenceArea
                        x1={xThresh} x2={xMax} y1={yThresh} y2={yMax}
                        fill={QUADRANT_AREA_FILL["improving-strong"]}
                        fillOpacity={0.45}
                      />
                      <ReferenceArea
                        x1={xMin} x2={xThresh} y1={yMin} y2={yThresh}
                        fill={QUADRANT_AREA_FILL["declining-weak"]}
                        fillOpacity={0.45}
                      />
                      <ReferenceArea
                        x1={xThresh} x2={xMax} y1={yMin} y2={yThresh}
                        fill={QUADRANT_AREA_FILL["declining-strong"]}
                        fillOpacity={0.45}
                      />

                      {/* Threshold lines */}
                      <ReferenceLine
                        x={xThresh}
                        stroke="#9ca3af"
                        strokeDasharray="5 3"
                        label={{ value: "median", position: "insideTopRight", fontSize: 9, fill: "#9ca3af" }}
                      />
                      <ReferenceLine
                        y={yThresh}
                        stroke="#9ca3af"
                        strokeDasharray="5 3"
                        label={{ value: `${yThresh.toFixed(3)}`, position: "insideTopLeft", fontSize: 9, fill: "#9ca3af" }}
                      />

                      <XAxis
                        dataKey="x_value"
                        type="number"
                        name={scatter.x_label}
                        domain={[xMin, xMax]}
                        tickCount={6}
                        tickFormatter={(v: number) => v.toFixed(2)}
                        tick={{ fontSize: 10, fill: "#6b7280" }}
                        label={{
                          value: scatter.x_label,
                          position: "insideBottom",
                          offset: -30,
                          fontSize: 11,
                          fill: "#374151",
                        }}
                      />
                      <YAxis
                        dataKey="y_value"
                        type="number"
                        name={scatter.y_label}
                        domain={[yMin, yMax]}
                        tickCount={6}
                        tickFormatter={(v: number) => v.toFixed(3)}
                        tick={{ fontSize: 10, fill: "#6b7280" }}
                        width={62}
                        label={{
                          value: scatter.y_label,
                          angle: -90,
                          position: "insideLeft",
                          offset: 10,
                          fontSize: 11,
                          fill: "#374151",
                        }}
                      />

                      <Tooltip content={<CustomTooltip />} />

                      <Scatter
                        data={scatter.points}
                        shape={(props: unknown) => {
                          const { cx, cy, payload } = props as {
                            cx: number
                            cy: number
                            payload: ScatterPoint
                          }
                          const isSelected = payload.schemecode === selectedPoint
                          return (
                            <circle
                              cx={cx}
                              cy={cy}
                              r={isSelected ? 8 : 5}
                              fill={QUADRANT_DOT_FILL[payload.quadrant] ?? "#6b7280"}
                              stroke={isSelected ? "#1d4ed8" : "#fff"}
                              strokeWidth={isSelected ? 2.5 : 1}
                              style={{ cursor: "pointer" }}
                              onClick={() => {
                                setSelectedPoint(payload.schemecode)
                                navigate(`/funds/${payload.schemecode}`)
                              }}
                            />
                          )
                        }}
                      />
                    </ScatterChart>
                  </ResponsiveContainer>

                  {/* Quadrant legend */}
                  <div className="flex flex-wrap items-center justify-center gap-4 mt-1">
                    {Object.entries(QUADRANT_LABELS).map(([key, label]) => (
                      <button
                        key={key}
                        onClick={() => setQuadrantFilter(activeQuadrant === key ? null : key)}
                        className={cn(
                          "flex items-center gap-1.5 text-xs transition-opacity",
                          activeQuadrant && activeQuadrant !== key ? "opacity-40" : "opacity-100",
                        )}
                      >
                        <span
                          className="h-2.5 w-2.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: QUADRANT_DOT_FILL[key] }}
                        />
                        <span className="text-gray-600">{label}</span>
                        <span className="text-gray-400 tabular-nums">
                          ({scatter.quadrant_counts[key] ?? 0})
                        </span>
                      </button>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {/* ── Results table ── */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-semibold text-gray-800">
                    Inspect filtered results
                    <span className="text-gray-400 font-normal text-xs ml-2">
                      {sortedPoints.length} fund{sortedPoints.length !== 1 ? "s" : ""}
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-0 pb-1">
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-gray-100 bg-gray-50">
                          {(
                            [
                              { col: "fund_name" as SortKey, label: "Fund" },
                              { col: "x_value" as SortKey, label: scatter.x_label },
                              { col: "y_value" as SortKey, label: scatter.y_label },
                              { col: "ir_3yr" as SortKey, label: "3Y IR" },
                              { col: "rank_in_category" as SortKey, label: "Rank" },
                              { col: "rank_delta_6m" as SortKey, label: "Rank Δ 6m" },
                            ] as const
                          ).map(({ col, label }) => (
                            <th
                              key={col}
                              onClick={() => toggleSort(col)}
                              className="px-3 py-2 text-left font-medium text-gray-500 cursor-pointer hover:text-gray-800 whitespace-nowrap select-none"
                            >
                              <span className="inline-flex items-center gap-1">
                                {label}
                                <SortIcon col={col} current={sortCol} dir={sortDir} />
                              </span>
                            </th>
                          ))}
                          <th className="px-3 py-2 text-left font-medium text-gray-500 whitespace-nowrap">
                            Notes
                          </th>
                          <th className="w-8" />
                        </tr>
                      </thead>
                      <tbody>
                        {sortedPoints.map(p => (
                          <tr
                            key={p.schemecode}
                            className={cn(
                              "border-b border-gray-50 hover:bg-gray-50 transition-colors cursor-pointer",
                              selectedPoint === p.schemecode && "bg-blue-50 hover:bg-blue-50",
                            )}
                            onClick={() => setSelectedPoint(p.schemecode)}
                          >
                            <td className="px-3 py-2">
                              <div className="flex items-center gap-1.5">
                                <span
                                  className="h-2 w-2 rounded-full flex-shrink-0"
                                  style={{ backgroundColor: QUADRANT_DOT_FILL[p.quadrant] ?? "#6b7280" }}
                                />
                                <span
                                  className="font-medium text-gray-900 truncate max-w-[180px]"
                                  title={p.fund_name}
                                >
                                  {p.fund_name}
                                </span>
                              </div>
                            </td>
                            <td className="px-3 py-2 font-mono text-gray-700">
                              {p.x_value.toFixed(3)}
                            </td>
                            <td className="px-3 py-2 font-mono text-gray-700">
                              {p.y_value.toFixed(4)}
                            </td>
                            <td className="px-3 py-2 font-mono text-gray-700">
                              {p.ir_3yr?.toFixed(3) ?? "—"}
                            </td>
                            <td className="px-3 py-2 text-gray-700">
                              #{p.rank_in_category ?? "—"}
                            </td>
                            <td className="px-3 py-2">
                              {p.rank_delta_6m !== null ? (
                                <span
                                  className={cn(
                                    "font-medium",
                                    p.rank_delta_6m < 0
                                      ? "text-green-600"
                                      : p.rank_delta_6m > 0
                                        ? "text-red-600"
                                        : "text-gray-500",
                                  )}
                                >
                                  {p.rank_delta_6m > 0 ? `+${p.rank_delta_6m}` : p.rank_delta_6m}
                                </span>
                              ) : (
                                "—"
                              )}
                            </td>
                            <td
                              className="px-3 py-2 text-gray-500 italic max-w-[160px] truncate"
                              title={p.note ?? undefined}
                            >
                              {p.note ?? "—"}
                            </td>
                            <td className="px-3 py-2">
                              <button
                                title="Open fund detail"
                                onClick={e => {
                                  e.stopPropagation()
                                  navigate(`/funds/${p.schemecode}`)
                                }}
                                className="text-gray-400 hover:text-blue-600 transition-colors"
                              >
                                <ExternalLink className="h-3.5 w-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                        {sortedPoints.length === 0 && (
                          <tr>
                            <td colSpan={8} className="px-3 py-10 text-center text-gray-400">
                              No funds match the current filter.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* ── Right rail: AI Insight ── */}
            <div className="w-[272px] flex-shrink-0 border-l border-gray-200 bg-gray-50/80 flex flex-col overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-200 flex items-center gap-2">
                <BrainCircuit className="h-4 w-4 text-purple-500" />
                <span className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
                  AI Insights
                </span>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {displayInsights.length === 0 && (
                  <p className="text-xs text-gray-400 leading-relaxed">
                    Interpret a query or load a saved workspace to see structural insights.
                  </p>
                )}
                {displayInsights.map((card, i) => (
                  <InsightCard key={i} card={card} />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Bottom action bar ── */}
      {scatter && (
        <div className="bg-white border-t border-gray-200 px-6 py-3 flex items-center gap-3 flex-shrink-0">
          <Button
            variant="outline"
            size="sm"
            disabled={!selectedPoint}
            onClick={() => selectedPoint && navigate(`/funds/${selectedPoint}`)}
          >
            <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
            Open Fund Detail
          </Button>
          <Button
            size="sm"
            onClick={() => saveMutation.mutate()}
            disabled={isSaved || saveMutation.isPending}
          >
            {saveMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5 mr-1.5" />
            )}
            {isSaved ? "Workspace saved" : "Save Workspace"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled
            className="text-gray-300 cursor-not-allowed"
          >
            Create Report
          </Button>
          <span className="ml-auto text-xs text-gray-400">
            {scatter.total_funds} ranked funds · {scatter.as_of_date}
          </span>
        </div>
      )}
    </div>
  )
}
