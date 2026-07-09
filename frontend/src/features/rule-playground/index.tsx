import { useState, useEffect, useCallback, useMemo, useRef } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  RotateCcw, Send, Loader2, AlertCircle, Plus, X,
  TrendingUp, TrendingDown, Minus, CheckCircle2, XCircle,
  ChevronDown, ChevronUp,
} from "lucide-react"
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts"
import { cn } from "@/lib/utils"
import {
  rulesApi, schemesApi,
  type SandboxFundResult, type FormulaValidationResult, type CategoryItem,
} from "@/lib/api"
import { queryKeys } from "@/lib/query-keys"
import InsightPanel from "@/components/insights/InsightPanel"
import PocBadge from "@/components/insights/PocBadge"

// ── Constants ─────────────────────────────────────────────────────────────────

const COLORS = ["#2563EB", "#16A34A", "#7C3AED", "#D97706", "#EF4444", "#0891B2"]
const SESSION_KEY = "mfit_rule_playground_v2"

// ── Types ─────────────────────────────────────────────────────────────────────

interface EditorComponent {
  uid: string                // local unique id (not DB id)
  metric_column: string
  direction: "higher_better" | "lower_better"
  weight_pct: number          // 0–100
  formula_text: string
}

// Persisted sandbox state written to sessionStorage
interface PersistedState {
  category: string
  components: EditorComponent[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function uid() {
  return Math.random().toString(36).slice(2, 9)
}

function loadSession(): PersistedState | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    return raw ? (JSON.parse(raw) as PersistedState) : null
  } catch {
    return null
  }
}

function saveSession(state: PersistedState) {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(state))
  } catch {
    // storage might be full — ignore
  }
}

function simpleHash(s: string): string {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (Math.imul(31, h) + s.charCodeAt(i)) | 0
  }
  return h.toString(36)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KpiTile({
  label,
  value,
  color,
}: {
  label: string
  value: string | number
  color?: string
}) {
  return (
    <div className="bg-gray-50 rounded-xl p-3 text-center">
      <div className={cn("text-2xl font-bold", color ?? "text-gray-800")}>{value}</div>
      <div className="text-[11px] text-gray-500 mt-0.5">{label}</div>
    </div>
  )
}

function CheckRow({ pass, label }: { pass: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      {pass
        ? <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
        : <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
      }
      <span className={pass ? "text-gray-700" : "text-red-600"}>{label}</span>
    </div>
  )
}

function RankChangeCell({ change }: { change: number }) {
  if (change > 0)
    return (
      <span className="flex items-center justify-center gap-0.5 text-green-600 text-xs">
        <TrendingUp className="h-3 w-3" />
        {change}
      </span>
    )
  if (change < 0)
    return (
      <span className="flex items-center justify-center gap-0.5 text-red-500 text-xs">
        <TrendingDown className="h-3 w-3" />
        {Math.abs(change)}
      </span>
    )
  return <Minus className="h-3.5 w-3.5 text-gray-300 mx-auto" />
}

// ── Rationale dialog ──────────────────────────────────────────────────────────

function RationaleDialog({
  open,
  onClose,
  onSubmit,
  isSubmitting,
}: {
  open: boolean
  onClose: () => void
  onSubmit: (rationale: string) => void
  isSubmitting: boolean
}) {
  const [text, setText] = useState("")
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-1">Submit for Review</h2>
        <p className="text-xs text-gray-500 mb-4">
          Describe why this rule change is a structural improvement. The proposed rule set
          will remain in <em>pending_review</em> status until a separate approval action promotes it.
        </p>
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          rows={4}
          placeholder="Rationale for this rule change…"
          className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onClose}
            className="text-sm text-gray-500 px-4 py-2 border border-gray-200 rounded-xl hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            disabled={text.trim().length < 10 || isSubmitting}
            onClick={() => onSubmit(text.trim())}
            className={cn(
              "text-sm px-4 py-2 rounded-xl font-medium",
              text.trim().length >= 10 && !isSubmitting
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "bg-gray-100 text-gray-400 cursor-not-allowed",
            )}
          >
            {isSubmitting ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Submitting…
              </span>
            ) : "Submit"}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function RulePlaygroundPage() {
  const queryClient = useQueryClient()
  const initialSession = useRef(loadSession())

  // ── Server data ─────────────────────────────────────────────────────────────
  const { data: defaultData, isLoading: defaultLoading } = useQuery({
    queryKey: queryKeys.rules.v2Default,
    queryFn: () => rulesApi.getDefault(),
    staleTime: 10 * 60 * 1000,
  })

  const { data: categoryData } = useQuery({
    queryKey: ["schemes", "categories"],
    queryFn: () => schemesApi.listCategories(),
    staleTime: Infinity,
  })

  const METRIC_VOCAB = defaultData?.metric_vocab ?? {}

  // ── Editor state ─────────────────────────────────────────────────────────────
  const [category, setCategory] = useState<string>(
    initialSession.current?.category ?? "Large Cap"
  )
  const [components, setComponents] = useState<EditorComponent[]>(
    initialSession.current?.components ?? []
  )
  const [formulaValidations, setFormulaValidations] = useState<
    Record<string, FormulaValidationResult>
  >({})

  // ── Sandbox run state ────────────────────────────────────────────────────────
  const [sandboxRun, setSandboxRun] = useState<{
    fund_count: number
    promoted_count: number
    dropped_count: number
    no_change_count: number
    top10_turnover_pct: number
    entering_top10: string[]
    leaving_top10: string[]
    results: SandboxFundResult[]
    warnings: string[]
  } | null>(null)

  // ── UI state ─────────────────────────────────────────────────────────────────
  const [showRationaleDialog, setShowRationaleDialog] = useState(false)
  const [submitResult, setSubmitResult] = useState<{
    version_label: string
    status: string
    message: string
  } | null>(null)
  const [showAllResults, setShowAllResults] = useState(false)

  // ── Initialise from default data when it arrives ──────────────────────────
  useEffect(() => {
    if (defaultData && components.length === 0) {
      setComponents(
        defaultData.components.map(c => ({
          uid: uid(),
          metric_column: c.metric_column,
          direction: c.direction,
          weight_pct: c.weight_pct,
          formula_text: "",
        }))
      )
    }
  }, [defaultData])

  // ── Persist to sessionStorage on change ──────────────────────────────────────
  useEffect(() => {
    saveSession({ category, components })
  }, [category, components])

  // ── Derived values ────────────────────────────────────────────────────────────
  const totalPct = useMemo(
    () => components.reduce((s, c) => s + c.weight_pct, 0),
    [components]
  )
  const weightOk = Math.abs(totalPct - 100) <= 0.5
  const hasNegative = components.some(c => c.weight_pct < 0)
  const allFormulasValid = Object.values(formulaValidations).every(v => v.valid)
  const hasFormulas = components.some(c => c.formula_text.trim().length > 0)

  const SHORT_WINDOW = new Set(["ir_slope_6m_proxy", "active_1yr_ret", "fund_1yr_ret", "rank_delta_6m"])
  const shortWindowPct = components
    .filter(c => SHORT_WINDOW.has(c.metric_column))
    .reduce((s, c) => s + c.weight_pct, 0)
  const recencyOk = shortWindowPct <= 50

  // rationale_present used only inside the insights payload; declared inline there

  const readyForApproval =
    weightOk &&
    !hasNegative &&
    (!hasFormulas || allFormulasValid) &&
    recencyOk &&
    sandboxRun !== null

  // ── Insight payload hash (to avoid refetch on irrelevant changes) ─────────
  const insightHash = useMemo(() => {
    const key = JSON.stringify({
      category,
      comps: components.map(c => ({
        m: c.metric_column,
        w: c.weight_pct,
        f: c.formula_text,
      })),
      run: sandboxRun
        ? {
            p: sandboxRun.promoted_count,
            d: sandboxRun.dropped_count,
            t: sandboxRun.top10_turnover_pct,
          }
        : null,
    })
    return simpleHash(key)
  }, [category, components, sandboxRun])

  // ── Insight query ─────────────────────────────────────────────────────────
  const { data: insightData, isLoading: insightLoading } = useQuery({
    queryKey: queryKeys.rules.v2Insights(category, insightHash),
    queryFn: () =>
      rulesApi.getRulePlaygroundInsights({
        components: components.map(c => ({
          metric_column: c.metric_column,
          weight_pct: c.weight_pct,
          formula_text: c.formula_text || undefined,
        })),
        formula_validations: Object.entries(formulaValidations).map(([cn, fv]) => ({
          component_name: cn,
          valid: fv.valid,
          error_type: fv.error_type,
          error_message: fv.error_message,
          parsed_variables: fv.parsed_variables,
          sample_result: fv.sample_preview?.[0]?.result ?? null,
        })),
        sandbox_run: sandboxRun
          ? {
              fund_count: sandboxRun.fund_count,
              promoted: sandboxRun.promoted_count,
              dropped: sandboxRun.dropped_count,
              no_change: sandboxRun.no_change_count,
              top10_turnover_pct: sandboxRun.top10_turnover_pct,
              entering_top10: sandboxRun.entering_top10,
              leaving_top10: sandboxRun.leaving_top10,
            }
          : null,
        rationale_present: false,
        category,
      }),
    staleTime: 0,
    enabled: components.length > 0,
  })

  // ── Formula validation mutation ────────────────────────────────────────────
  const validateFormulaMutation = useMutation({
    mutationFn: ({
      compUid: _compUid,
      formula_text,
      available_variables,
    }: {
      compUid: string
      formula_text: string
      available_variables: string[]
    }) => rulesApi.validateFormula(formula_text, available_variables),
    onSuccess: (result, { compUid }) => {
      setFormulaValidations(prev => ({ ...prev, [compUid]: result }))
    },
  })

  // ── Sandbox run mutation ───────────────────────────────────────────────────
  const sandboxMutation = useMutation({
    mutationFn: () =>
      rulesApi.sandboxRunV2({
        category,
        rule_components: components.map(c => ({
          metric_column: c.metric_column,
          direction: c.direction,
          weight: c.weight_pct / 100,
          formula_text: c.formula_text || undefined,
        })),
      }),
    onSuccess: data => {
      setSandboxRun({
        fund_count: data.fund_count,
        promoted_count: data.promoted_count,
        dropped_count: data.dropped_count,
        no_change_count: data.no_change_count,
        top10_turnover_pct: data.top10_turnover_pct,
        entering_top10: data.entering_top10,
        leaving_top10: data.leaving_top10,
        results: data.results,
        warnings: data.warnings,
      })
      setShowAllResults(false)
      queryClient.invalidateQueries({ queryKey: ["rules", "v2", "insights"] })
    },
  })

  // ── Submit for approval mutation ───────────────────────────────────────────
  const submitMutation = useMutation({
    mutationFn: (rationale: string) =>
      rulesApi.submitForApproval({
        rule_components: components.map(c => ({
          metric_column: c.metric_column,
          direction: c.direction,
          weight: c.weight_pct / 100,
          formula_text: c.formula_text || undefined,
        })),
        rationale,
        sandbox_run_summary: sandboxRun
          ? {
              fund_count: sandboxRun.fund_count,
              promoted_count: sandboxRun.promoted_count,
              dropped_count: sandboxRun.dropped_count,
              no_change_count: sandboxRun.no_change_count,
              top10_turnover_pct: sandboxRun.top10_turnover_pct,
            }
          : undefined,
        category,
      }),
    onSuccess: data => {
      setSubmitResult(data)
      setShowRationaleDialog(false)
    },
  })

  // ── Component editor actions ───────────────────────────────────────────────
  const addComponent = useCallback(() => {
    const firstAvailable = Object.keys(METRIC_VOCAB)[0] ?? "information_ratio_3yr"
    const vocab = METRIC_VOCAB[firstAvailable]
    setComponents(prev => [
      ...prev,
      {
        uid: uid(),
        metric_column: firstAvailable,
        direction: vocab?.direction ?? "higher_better",
        weight_pct: 0,
        formula_text: "",
      },
    ])
  }, [METRIC_VOCAB])

  const removeComponent = useCallback((removeUid: string) => {
    setComponents(prev => prev.filter(c => c.uid !== removeUid))
    setFormulaValidations(prev => {
      const next = { ...prev }
      delete next[removeUid]
      return next
    })
    setSandboxRun(null)
  }, [])

  const updateMetric = useCallback(
    (compUid: string, metricCol: string) => {
      const vocab = METRIC_VOCAB[metricCol]
      setComponents(prev =>
        prev.map(c =>
          c.uid === compUid
            ? {
                ...c,
                metric_column: metricCol,
                direction: vocab?.direction ?? "higher_better",
                formula_text: "",
              }
            : c
        )
      )
      setSandboxRun(null)
    },
    [METRIC_VOCAB]
  )

  const updateWeight = useCallback((compUid: string, val: number) => {
    setComponents(prev => prev.map(c => (c.uid === compUid ? { ...c, weight_pct: val } : c)))
    setSandboxRun(null)
  }, [])

  const updateFormula = useCallback((compUid: string, text: string) => {
    setComponents(prev =>
      prev.map(c => (c.uid === compUid ? { ...c, formula_text: text } : c))
    )
    setSandboxRun(null)
  }, [])

  const resetToDefault = useCallback(() => {
    if (defaultData) {
      setComponents(
        defaultData.components.map(c => ({
          uid: uid(),
          metric_column: c.metric_column,
          direction: c.direction,
          weight_pct: c.weight_pct,
          formula_text: "",
        }))
      )
    }
    setFormulaValidations({})
    setSandboxRun(null)
    setSubmitResult(null)
    setShowAllResults(false)
    sessionStorage.removeItem(SESSION_KEY)
  }, [defaultData])

  // ── Donut data ────────────────────────────────────────────────────────────
  const donutData = components.map((c, i) => ({
    name: METRIC_VOCAB[c.metric_column]?.label ?? c.metric_column,
    value: c.weight_pct,
    color: COLORS[i % COLORS.length],
  }))

  // ── Categories for top bar ────────────────────────────────────────────────
  const categories: CategoryItem[] = categoryData?.categories ?? []

  // ── Sorted results split into default vs sandbox ──────────────────────────
  const defaultSorted = sandboxRun
    ? [...sandboxRun.results].sort((a, b) => a.default_rank - b.default_rank)
    : []
  const displayRows = showAllResults
    ? defaultSorted
    : defaultSorted.slice(0, 10)

  if (defaultLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400 gap-2">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">Loading default rules…</span>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5 min-h-screen">

      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Rule Playground</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Propose structural changes to the ranking rule set. Changes are sandboxed and
            require explicit approval before going live.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Category selector */}
          <select
            value={category}
            onChange={e => {
              setCategory(e.target.value)
              setSandboxRun(null)
            }}
            className="text-sm border border-gray-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {categories.map(cat => (
              <option key={cat.id} value={cat.id}>{cat.name}</option>
            ))}
          </select>

          <button
            onClick={resetToDefault}
            className="flex items-center gap-1.5 text-sm border border-gray-200 rounded-xl px-4 py-2 hover:bg-gray-50 transition-colors"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset to Default
          </button>

          <button
            disabled={!readyForApproval || submitMutation.isPending}
            onClick={() => setShowRationaleDialog(true)}
            title={
              !readyForApproval
                ? "Complete all validation checks and run sandbox before submitting"
                : "Submit proposed rule set for review"
            }
            className={cn(
              "flex items-center gap-1.5 text-sm rounded-xl px-4 py-2 font-medium transition-colors",
              readyForApproval && !submitMutation.isPending
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "bg-gray-100 text-gray-400 cursor-not-allowed",
            )}
          >
            <Send className="h-3.5 w-3.5" />
            Submit for Review
          </button>
        </div>
      </div>

      {/* ── Submit success banner ───────────────────────────────────────────── */}
      {submitResult && (
        <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 flex items-start gap-3">
          <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-green-800">
              Rule set submitted — {submitResult.version_label}
            </p>
            <p className="text-xs text-green-700 mt-0.5">
              Status: <code className="font-mono">{submitResult.status}</code>. This version
              is in pending review and will NOT affect live rankings until explicitly approved.
            </p>
          </div>
        </div>
      )}

      {/* ── 3-column layout ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-4 items-start">

        {/* ═══ Column 1 — Edit Rules ════════════════════════════════════════ */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-800">Edit Rules</span>
            <span
              className={cn(
                "text-xs font-semibold px-2 py-0.5 rounded-full",
                weightOk ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600",
              )}
            >
              {totalPct.toFixed(0)}% / 100%
            </span>
          </div>

          <div className="space-y-3">
            {components.map((comp, idx) => {
              const vocab = METRIC_VOCAB[comp.metric_column]
              const fv = formulaValidations[comp.uid]
              const formulaActive = comp.formula_text.trim().length > 0
              const defaultComp = defaultData?.components.find(
                d => d.metric_column === comp.metric_column
              )
              const changed =
                defaultComp && comp.weight_pct !== defaultComp.weight_pct

              return (
                <div
                  key={comp.uid}
                  className={cn(
                    "rounded-xl border p-3 space-y-2 transition-colors",
                    changed ? "border-blue-200 bg-blue-50/30" : "border-gray-100",
                  )}
                >
                  {/* Header row */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <select
                        value={comp.metric_column}
                        onChange={e => updateMetric(comp.uid, e.target.value)}
                        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                      >
                        {Object.entries(METRIC_VOCAB).map(([col, v]) => (
                          <option key={col} value={col}>
                            {v.label} ({col})
                          </option>
                        ))}
                      </select>
                    </div>
                    <span
                      className={cn(
                        "text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0",
                        comp.direction === "higher_better"
                          ? "bg-green-50 text-green-700"
                          : "bg-amber-50 text-amber-700",
                      )}
                    >
                      {comp.direction === "higher_better" ? "↑ higher" : "↓ lower"}
                    </span>
                    <button
                      onClick={() => removeComponent(comp.uid)}
                      className="shrink-0 text-gray-300 hover:text-red-500 transition-colors"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  {/* Weight slider */}
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min={0}
                      max={100}
                      step={5}
                      value={comp.weight_pct}
                      onChange={e => updateWeight(comp.uid, Number(e.target.value))}
                      className="flex-1 accent-blue-600 h-1.5"
                    />
                    <div
                      className="flex items-center gap-1 shrink-0"
                      style={{ color: COLORS[idx % COLORS.length] }}
                    >
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={5}
                        value={comp.weight_pct}
                        onChange={e => {
                          const v = Math.min(100, Math.max(0, Number(e.target.value)))
                          updateWeight(comp.uid, v)
                        }}
                        className="w-12 text-xs font-bold border border-gray-200 rounded-lg px-1.5 py-1 text-center focus:outline-none"
                      />
                      <span className="text-xs font-bold">%</span>
                    </div>
                  </div>

                  {/* Optional formula field */}
                  <details className="group" open={formulaActive}>
                    <summary className="text-[10px] text-gray-400 cursor-pointer select-none hover:text-gray-600 list-none flex items-center gap-1">
                      <Plus className="h-3 w-3" />
                      <span>Custom formula</span>
                      {formulaActive && fv && (
                        fv.valid
                          ? <CheckCircle2 className="h-3 w-3 text-green-500 ml-1" />
                          : <XCircle className="h-3 w-3 text-red-500 ml-1" />
                      )}
                    </summary>
                    <div className="mt-1.5 space-y-1">
                      <textarea
                        rows={2}
                        value={comp.formula_text}
                        onChange={e => updateFormula(comp.uid, e.target.value)}
                        placeholder="e.g. information_ratio_3yr * 0.6 + sharpe_ratio_3yr * 0.4"
                        className="w-full text-[11px] font-mono border border-gray-200 rounded-lg px-2 py-1.5 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      {comp.formula_text.trim() && (
                        <button
                          onClick={() =>
                            validateFormulaMutation.mutate({
                              compUid: comp.uid,
                              formula_text: comp.formula_text,
                              available_variables: Object.keys(METRIC_VOCAB),
                            })
                          }
                          className="text-[10px] text-blue-600 hover:underline"
                        >
                          {validateFormulaMutation.isPending ? "Validating…" : "Validate"}
                        </button>
                      )}
                      {fv && !fv.valid && fv.error_message && (
                        <p className="text-[10px] text-red-600 bg-red-50 px-2 py-1 rounded">
                          {fv.error_message}
                        </p>
                      )}
                      {fv?.valid && fv.sample_preview && fv.sample_preview[0] && (
                        <p className="text-[10px] text-green-700 bg-green-50 px-2 py-1 rounded font-mono">
                          Preview: {fv.sample_preview[0].result?.toFixed(4)}
                        </p>
                      )}
                    </div>
                  </details>

                  {/* Short-window badge */}
                  {vocab?.short_window && (
                    <p className="text-[9px] text-amber-600 bg-amber-50 px-2 py-0.5 rounded">
                      Short window ({vocab.window_months}m) — counts toward recency-bias check
                    </p>
                  )}
                </div>
              )
            })}
          </div>

          <button
            onClick={addComponent}
            className="w-full flex items-center justify-center gap-1.5 text-xs text-blue-600 border border-dashed border-blue-300 rounded-xl py-2 hover:bg-blue-50 transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Rule Component
          </button>
        </div>

        {/* ═══ Column 2 — See Weights + Validate ════════════════════════════ */}
        <div className="space-y-4">

          {/* Weight donut */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-sm font-semibold text-gray-800 mb-3">Weight Allocation</p>
            <ResponsiveContainer width="100%" height={160}>
              <PieChart>
                <Pie
                  data={donutData}
                  cx="50%"
                  cy="50%"
                  innerRadius={42}
                  outerRadius={62}
                  dataKey="value"
                  strokeWidth={0}
                >
                  {donutData.map(d => (
                    <Cell key={d.name} fill={d.color} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(v: number) => [`${v}%`, ""]}
                  contentStyle={{ fontSize: 11, borderRadius: 8 }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="space-y-1.5 mt-2">
              {donutData.map(d => (
                <div key={d.name} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1.5 min-w-0">
                    <span
                      className="h-2.5 w-2.5 rounded-full shrink-0"
                      style={{ background: d.color }}
                    />
                    <span className="text-gray-600 truncate max-w-[150px]">{d.name}</span>
                  </span>
                  <span className="font-semibold text-gray-700 ml-2">{d.value}%</span>
                </div>
              ))}
            </div>
          </div>

          {/* Validation checklist */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-2">
            <p className="text-sm font-semibold text-gray-800 mb-1">Validation</p>
            <CheckRow pass={weightOk} label={`Weights sum to 100% (current: ${totalPct.toFixed(0)}%)`} />
            <CheckRow pass={!hasNegative} label="No negative weights" />
            <CheckRow pass={!hasFormulas || allFormulasValid} label="All custom formulas valid" />
            <CheckRow pass={recencyOk} label={`Recency bias OK (short-window: ${shortWindowPct.toFixed(0)}% ≤ 50%)`} />
            <CheckRow pass={sandboxRun !== null} label="Sandbox run completed" />
            <CheckRow pass={submitResult !== null} label="Rationale provided and submitted" />

            <div className="pt-2">
              <button
                disabled={!weightOk || sandboxMutation.isPending}
                onClick={() => sandboxMutation.mutate()}
                className={cn(
                  "w-full text-sm rounded-xl px-4 py-2.5 font-medium transition-colors flex items-center justify-center gap-2",
                  weightOk && !sandboxMutation.isPending
                    ? "bg-blue-600 text-white hover:bg-blue-700"
                    : "bg-gray-100 text-gray-400 cursor-not-allowed",
                )}
              >
                {sandboxMutation.isPending ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Running…
                  </>
                ) : "Run Sandbox"}
              </button>
              {sandboxMutation.isError && (
                <p className="text-[11px] text-red-600 mt-2 flex items-start gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                  {sandboxMutation.error instanceof Error
                    ? sandboxMutation.error.message
                    : "Sandbox run failed. Check weights sum to 100%."}
                </p>
              )}
              {sandboxRun && (
                <button
                  onClick={() => { setSandboxRun(null); setShowAllResults(false) }}
                  className="w-full mt-2 text-xs text-gray-400 border border-gray-200 rounded-xl py-1.5 hover:bg-gray-50 transition-colors"
                >
                  Clear results
                </button>
              )}
            </div>
          </div>

          {/* Default rule summary */}
          {defaultData && (
            <div className="bg-gray-50 rounded-xl border border-gray-200 p-4">
              <p className="text-xs font-semibold text-gray-600 mb-2">
                Active Default — {defaultData.version_label}
              </p>
              <div className="space-y-1.5">
                {defaultData.components.map(c => (
                  <div key={c.id} className="flex justify-between text-xs">
                    <span className="text-gray-600 truncate max-w-[160px]">
                      {c.label_display}
                    </span>
                    <span className="font-semibold text-gray-700 ml-2">{c.weight_pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ═══ Column 3 — Compare Results ═══════════════════════════════════ */}
        <div className="space-y-4">

          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3">
            <KpiTile
              label="Promoted"
              value={sandboxRun?.promoted_count ?? "—"}
              color={sandboxRun ? "text-green-600" : undefined}
            />
            <KpiTile
              label="Dropped"
              value={sandboxRun?.dropped_count ?? "—"}
              color={sandboxRun ? "text-red-500" : undefined}
            />
            <KpiTile
              label="No Change"
              value={sandboxRun?.no_change_count ?? "—"}
              color="text-gray-600"
            />
            <KpiTile
              label="Top-10 Turnover"
              value={sandboxRun ? `${sandboxRun.top10_turnover_pct.toFixed(0)}%` : "—"}
              color={
                sandboxRun
                  ? sandboxRun.top10_turnover_pct > 40
                    ? "text-amber-600"
                    : "text-gray-700"
                  : undefined
              }
            />
          </div>

          {/* Side-by-side ranked table */}
          {sandboxRun ? (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100">
                <span className="text-xs font-semibold text-gray-700">
                  Rank Comparison · {category}
                </span>
                <span className="text-[11px] text-gray-400">
                  {sandboxRun.fund_count} research candidates
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      <th className="text-left px-3 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                        Fund
                      </th>
                      <th className="text-center px-2 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                        Default
                      </th>
                      <th className="text-center px-2 py-2 text-[11px] font-semibold text-blue-600 uppercase tracking-wide">
                        Sandbox
                      </th>
                      <th className="text-center px-2 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                        Δ
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {displayRows.map(r => (
                      <tr
                        key={r.schemecode}
                        className={cn(
                          "hover:bg-gray-50 transition-colors",
                          r.rank_change > 0
                            ? "bg-green-50/30"
                            : r.rank_change < 0
                            ? "bg-red-50/20"
                            : "",
                        )}
                      >
                        <td className="px-3 py-2 font-medium text-gray-800 max-w-[180px] truncate">
                          {r.fund_name}
                        </td>
                        <td className="px-2 py-2 text-center text-gray-400">{r.default_rank}</td>
                        <td className="px-2 py-2 text-center font-semibold text-gray-800">
                          {r.sandbox_rank}
                        </td>
                        <td className="px-2 py-2 text-center">
                          <RankChangeCell change={r.rank_change} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {defaultSorted.length > 10 && (
                <div className="px-4 py-2 border-t border-gray-100 text-center">
                  <button
                    onClick={() => setShowAllResults(p => !p)}
                    className="flex items-center justify-center gap-1.5 text-xs text-blue-600 hover:underline mx-auto"
                  >
                    {showAllResults ? (
                      <>
                        <ChevronUp className="h-3 w-3" /> Show top 10 only
                      </>
                    ) : (
                      <>
                        <ChevronDown className="h-3 w-3" /> Show all {defaultSorted.length} funds
                      </>
                    )}
                  </button>
                </div>
              )}

              {/* Entering / leaving top 10 */}
              {(sandboxRun.entering_top10.length > 0 ||
                sandboxRun.leaving_top10.length > 0) && (
                <div className="px-4 py-3 border-t border-gray-100 grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-[10px] font-semibold text-green-700 mb-1">
                      Entering top 10
                    </p>
                    {sandboxRun.entering_top10.map(f => (
                      <p key={f} className="text-[10px] text-green-700 truncate">
                        + {f}
                      </p>
                    ))}
                    {sandboxRun.entering_top10.length === 0 && (
                      <p className="text-[10px] text-gray-400">None</p>
                    )}
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold text-red-600 mb-1">
                      Leaving top 10
                    </p>
                    {sandboxRun.leaving_top10.map(f => (
                      <p key={f} className="text-[10px] text-red-600 truncate">
                        − {f}
                      </p>
                    ))}
                    {sandboxRun.leaving_top10.length === 0 && (
                      <p className="text-[10px] text-gray-400">None</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-gray-50 rounded-xl border border-dashed border-gray-200 p-8 text-center">
              <p className="text-sm text-gray-400">
                Run the sandbox to compare default vs. proposed rankings.
              </p>
            </div>
          )}

          {/* Sandbox warnings */}
          {sandboxRun && sandboxRun.warnings.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
              <p className="text-[11px] font-semibold text-amber-800 mb-1">
                Sandbox warnings
              </p>
              <ul className="space-y-0.5">
                {sandboxRun.warnings.map((w, i) => (
                  <li key={i} className="text-[11px] text-amber-700">
                    · {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* ── AI Guidance strip ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold text-gray-700">Rule Validation Guidance</span>
          <PocBadge />
        </div>
        <InsightPanel
          cards={insightData?.cards ?? []}
          isLoading={insightLoading && components.length > 0}
        />
        {components.length === 0 && (
          <p className="text-xs text-gray-400 text-center py-2">
            Add at least one rule component to see validation guidance.
          </p>
        )}
      </div>

      <div className="text-xs text-gray-400 text-right">
        Sandbox only — proposed rules require explicit approval before going live.
        Approval status is visible in the Admin panel.
      </div>

      {/* ── Rationale dialog ──────────────────────────────────────────────────── */}
      <RationaleDialog
        open={showRationaleDialog}
        onClose={() => setShowRationaleDialog(false)}
        onSubmit={rationale => submitMutation.mutate(rationale)}
        isSubmitting={submitMutation.isPending}
      />
    </div>
  )
}
