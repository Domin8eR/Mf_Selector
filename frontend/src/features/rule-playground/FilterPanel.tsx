// Fund-universe eligibility filter catalogue — defines WHICH funds a rule is
// scored against, separate from the rule's own metric weights (Edit Rules
// panel). Every enabled control here has REAL backing data as of the 2026-07
// filter-catalogue audit (see backend/app/schemas/rules.py's EligibilityFilters
// and app/services/rule_playground.py's build_eligibility_sql for the exact
// source table/column + real coverage per field). Controls with NO real
// backing data are shown disabled with an explanatory tooltip — never hidden,
// never silently accepted — per that audit's explicit requirement not to
// fabricate filter behavior.
import { useState } from "react"
import { ChevronDown, ChevronUp, Info, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import type { Category36Group, Amc, Sector, EligibilityFilters } from "@/lib/api"

export interface FilterValues {
  // ── Core eligibility ────────────────────────────────────────────────────
  bucket_36: string | null
  bucket_group: string | null           // "ALL Equity" | "ALL Hybrid" | "ALL Passive"
  amc_codes: number[]
  amc_exclude_codes: number[]
  status: string
  plan_type: "" | "direct" | "regular"
  option_type: "" | "growth" | "idcw"
  min_history_years: string
  require_benchmark_mapped: boolean
  data_confidence_min: "" | "Low" | "Medium" | "High"
  // ── Performance history ─────────────────────────────────────────────────
  min_return_history: "" | "1Y" | "3Y" | "5Y"
  // ── Size / liquidity ────────────────────────────────────────────────────
  aum_min_cr: string
  aum_max_cr: string
  expense_ratio_max: string
  // ── Portfolio composition ───────────────────────────────────────────────
  holding_concentration_max: string      // top-5
  top10_concentration_max: string        // top-10
  holding_count_min: string
  holding_count_max: string
  sector_names: string[]                 // maps to sector_exposure with min 0.01%
  company_include: string
  company_exclude: string
  // ── Risk ─────────────────────────────────────────────────────────────────
  tracking_error_min: string
  tracking_error_max: string
  beta_min: string
  beta_max: string
  sharpe_min: string
  sortino_min: string
  // ── Structural improvement ──────────────────────────────────────────────
  ir_slope_min: string
  outperformance_ratio_min: string
  rank_movement_min: string
  // ── Lifecycle / regulatory ──────────────────────────────────────────────
  exclude_merged: boolean
  // ── Operational / data quality ──────────────────────────────────────────
  holdings_freshness_max_months: string
  aum_freshness_days: string
  // ── Taxonomy ─────────────────────────────────────────────────────────────
  exclude_elss: boolean
  exclude_thematic: boolean
}

export const EMPTY_FILTERS: FilterValues = {
  bucket_36: null,
  bucket_group: null,
  amc_codes: [],
  amc_exclude_codes: [],
  status: "Active",
  plan_type: "",
  option_type: "",
  min_history_years: "",
  require_benchmark_mapped: false,
  data_confidence_min: "",
  min_return_history: "",
  aum_min_cr: "",
  aum_max_cr: "",
  expense_ratio_max: "",
  holding_concentration_max: "",
  top10_concentration_max: "",
  holding_count_min: "",
  holding_count_max: "",
  sector_names: [],
  company_include: "",
  company_exclude: "",
  tracking_error_min: "",
  tracking_error_max: "",
  beta_min: "",
  beta_max: "",
  sharpe_min: "",
  sortino_min: "",
  ir_slope_min: "",
  outperformance_ratio_min: "",
  rank_movement_min: "",
  exclude_merged: true,
  holdings_freshness_max_months: "",
  aum_freshness_days: "",
  exclude_elss: false,
  exclude_thematic: false,
}

/** Pure conversion to the wire payload — empty strings become undefined
 *  (filter disabled), never 0 or null-as-zero. Kept outside the component so
 *  it's unit-testable without rendering anything. */
export function toEligibilityFilters(v: FilterValues): EligibilityFilters {
  const num = (s: string): number | undefined => (s.trim() === "" ? undefined : Number(s))
  return {
    bucket_36s: v.bucket_36 ? [v.bucket_36] : undefined,
    bucket_group: v.bucket_group || undefined,
    amc_codes: v.amc_codes.length ? v.amc_codes : undefined,
    amc_exclude_codes: v.amc_exclude_codes.length ? v.amc_exclude_codes : undefined,
    status: v.status,
    plan_type: v.plan_type || undefined,
    option_type: v.option_type || undefined,
    min_history_years: num(v.min_history_years),
    require_benchmark_mapped: v.require_benchmark_mapped,
    data_confidence_min: v.data_confidence_min || undefined,
    min_return_history: v.min_return_history || undefined,
    aum_min_cr: num(v.aum_min_cr),
    aum_max_cr: num(v.aum_max_cr),
    expense_ratio_max: num(v.expense_ratio_max),
    holding_concentration_max: num(v.holding_concentration_max),
    top10_concentration_max: num(v.top10_concentration_max),
    holding_count_min: num(v.holding_count_min),
    holding_count_max: num(v.holding_count_max),
    sector_exposure: v.sector_names.length
      ? Object.fromEntries(v.sector_names.map(s => [s, 0.01]))
      : undefined,
    company_include: v.company_include.trim() || undefined,
    company_exclude: v.company_exclude.trim() || undefined,
    tracking_error_min: num(v.tracking_error_min),
    tracking_error_max: num(v.tracking_error_max),
    beta_min: num(v.beta_min),
    beta_max: num(v.beta_max),
    sharpe_min: num(v.sharpe_min),
    sortino_min: num(v.sortino_min),
    ir_slope_min: num(v.ir_slope_min),
    outperformance_ratio_min: num(v.outperformance_ratio_min),
    rank_movement_min: num(v.rank_movement_min),
    exclude_merged: v.exclude_merged,
    holdings_freshness_max_months: num(v.holdings_freshness_max_months),
    aum_freshness_days: num(v.aum_freshness_days),
    exclude_elss: v.exclude_elss,
    exclude_thematic: v.exclude_thematic,
  }
}

const BUCKET_GROUPS = ["ALL Equity", "ALL Hybrid", "ALL Passive"] as const

interface Props {
  values: FilterValues
  onChange: (v: FilterValues) => void
  categories36?: Category36Group[]
  amcs: Amc[]
  sectors?: Sector[]
  /** Live "N of M funds match" preview — owned by the parent (debounced
   *  query against POST /rules/sandbox/eligible-count) so this component
   *  stays presentational. */
  eligibleCount?: { eligible: number; total: number; loading: boolean } | null
}

function SectionHeader({
  title, open, onToggle, badge,
}: { title: string; open: boolean; onToggle: () => void; badge?: string }) {
  return (
    <button
      onClick={onToggle}
      className="flex items-center justify-between w-full py-2 text-sm font-semibold text-gray-700 border-b border-gray-100"
    >
      <span>{title}{badge && <span className="ml-1.5 text-[10px] font-normal text-blue-600">{badge}</span>}</span>
      {open ? <ChevronUp className="h-3.5 w-3.5 text-gray-400" /> : <ChevronDown className="h-3.5 w-3.5 text-gray-400" />}
    </button>
  )
}

function NumberInput({
  label, hint, value, onChange, placeholder, min, max, step = "any",
}: {
  label: string; hint?: string; value: string; onChange: (v: string) => void
  placeholder?: string; min?: number; max?: number; step?: string | number
}) {
  return (
    <div className="space-y-0.5">
      <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
        {label}
        {hint && <span title={hint} className="cursor-help"><Info className="h-3 w-3 text-gray-300" /></span>}
      </label>
      <input
        type="number" value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder ?? ""} min={min} max={max} step={step}
        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 placeholder-gray-300"
      />
    </div>
  )
}

function RangeInputs({
  label, hint, minValue, maxValue, onMinChange, onMaxChange,
  minPlaceholder = "Min", maxPlaceholder = "Max", min, max, step = "any",
}: {
  label: string; hint?: string; minValue: string; maxValue: string
  onMinChange: (v: string) => void; onMaxChange: (v: string) => void
  minPlaceholder?: string; maxPlaceholder?: string
  min?: number; max?: number; step?: string | number
}) {
  return (
    <div className="space-y-0.5">
      <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
        {label}
        {hint && <span title={hint} className="cursor-help"><Info className="h-3 w-3 text-gray-300" /></span>}
      </label>
      <div className="flex items-center gap-1.5">
        <input
          type="number" value={minValue} onChange={e => onMinChange(e.target.value)}
          placeholder={minPlaceholder} min={min} max={max} step={step}
          className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <span className="text-gray-400 text-[10px]">–</span>
        <input
          type="number" value={maxValue} onChange={e => onMaxChange(e.target.value)}
          placeholder={maxPlaceholder} min={min} max={max} step={step}
          className="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>
    </div>
  )
}

function TextInput({
  label, hint, value, onChange, placeholder,
}: { label: string; hint?: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="space-y-0.5">
      <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
        {label}
        {hint && <span title={hint} className="cursor-help"><Info className="h-3 w-3 text-gray-300" /></span>}
      </label>
      <input
        type="text" value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder ?? ""}
        className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 placeholder-gray-300"
      />
    </div>
  )
}

function Toggle({
  label, hint, checked, onChange,
}: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-2 cursor-pointer">
      <span className="text-xs text-gray-700 flex items-center gap-1">
        {label}
        {hint && <span title={hint} className="cursor-help"><Info className="h-3 w-3 text-gray-300" /></span>}
      </span>
      <button
        role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors duration-200",
          checked ? "bg-blue-600" : "bg-gray-200",
        )}
      >
        <span className={cn(
          "inline-block h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 mt-0.5",
          checked ? "translate-x-4" : "translate-x-0.5",
        )} />
      </button>
    </label>
  )
}

/** A control with NO real backing data — shown disabled, never hidden, never
 *  silently accepted. `reason` explains exactly what's missing. */
function DisabledField({ label, reason }: { label: string; reason: string }) {
  return (
    <div className="space-y-0.5 opacity-50">
      <label className="text-[11px] font-medium text-gray-500 flex items-center gap-1">
        {label}
        <span title={reason} className="cursor-help"><Info className="h-3 w-3 text-gray-400" /></span>
      </label>
      <div className="w-full text-xs border border-dashed border-gray-200 rounded-lg px-2 py-1.5 text-gray-400 bg-gray-50">
        Not yet available
      </div>
    </div>
  )
}

export function FilterPanel({
  values, onChange, categories36, amcs, sectors = [], eligibleCount,
}: Props) {
  const [openSections, setOpenSections] = useState({
    core: true,
    performance: false,
    size: false,
    portfolio: false,
    risk: false,
    structural: false,
    lifecycle: false,
    operational: false,
    taxonomy: false,
    governance: false,
  })
  const [amcMode, setAmcMode] = useState<"include" | "exclude">("include")

  const toggle = (section: keyof typeof openSections) =>
    setOpenSections(prev => ({ ...prev, [section]: !prev[section] }))

  const set = <K extends keyof FilterValues>(k: K, v: FilterValues[K]) =>
    onChange({ ...values, [k]: v })

  const amcCount = values.amc_codes.length + values.amc_exclude_codes.length

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-800">Filters</div>
      </div>

      {/* Live eligible-count preview — updates as filters are adjusted,
          before Run Sandbox is clicked. */}
      {eligibleCount && (
        <div className={cn(
          "rounded-lg px-3 py-2 text-[11px] font-medium flex items-center gap-2",
          eligibleCount.eligible === 0
            ? "bg-red-50 text-red-700 border border-red-100"
            : "bg-blue-50 text-blue-700 border border-blue-100",
        )}>
          {eligibleCount.loading
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : <span className="font-mono font-semibold">{eligibleCount.eligible}</span>}
          {!eligibleCount.loading && (
            <span>of {eligibleCount.total} funds match current filters</span>
          )}
        </div>
      )}

      {/* ── CORE ELIGIBILITY ──────────────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Core Eligibility"
          badge={amcCount ? `${amcCount} AMC` : undefined}
          open={openSections.core}
          onToggle={() => toggle("core")}
        />
        {openSections.core && (
          <div className="pt-3 space-y-3">
            <div className="space-y-0.5">
              <label className="text-[11px] font-medium text-gray-600">Asset class</label>
              <select
                value={values.bucket_group ?? ""}
                onChange={e => set("bucket_group", e.target.value || null)}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              >
                <option value="">All</option>
                {BUCKET_GROUPS.map(g => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </div>

            {categories36 && categories36.length > 0 && (
              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-gray-600">Category (36-bucket)</label>
                <select
                  value={values.bucket_36 ?? ""}
                  onChange={e => set("bucket_36", e.target.value || null)}
                  className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
                >
                  <option value="">All categories</option>
                  {categories36.map(g => (
                    <optgroup key={g.group} label={g.group}>
                      {g.buckets.map(b => (
                        <option key={b.id} value={b.id}>{b.name} ({b.count})</option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
            )}

            <div className="space-y-0.5">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-medium text-gray-600">
                  AMC{amcCount > 0 && <span className="ml-1 text-blue-600">{amcCount} selected</span>}
                </label>
                <div className="flex rounded-md overflow-hidden border border-gray-200">
                  {(["include", "exclude"] as const).map(m => (
                    <button
                      key={m}
                      onClick={() => setAmcMode(m)}
                      className={cn(
                        "px-2 py-0.5 text-[10px] capitalize",
                        amcMode === m ? "bg-blue-600 text-white" : "text-gray-500 hover:bg-gray-50",
                      )}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>
              <div className="border border-gray-200 rounded-lg overflow-y-auto max-h-28">
                {amcs.map(a => {
                  const incl = values.amc_codes.includes(a.amc_code)
                  const excl = values.amc_exclude_codes.includes(a.amc_code)
                  const checked = amcMode === "include" ? incl : excl
                  return (
                    <label
                      key={a.amc_code}
                      className={cn(
                        "flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-gray-50 text-[11px]",
                        incl && "bg-blue-50 text-blue-700",
                        excl && "bg-red-50 text-red-700",
                        !incl && !excl && "text-gray-700",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={e => {
                          if (amcMode === "include") {
                            set("amc_codes", e.target.checked
                              ? [...values.amc_codes, a.amc_code]
                              : values.amc_codes.filter(c => c !== a.amc_code))
                          } else {
                            set("amc_exclude_codes", e.target.checked
                              ? [...values.amc_exclude_codes, a.amc_code]
                              : values.amc_exclude_codes.filter(c => c !== a.amc_code))
                          }
                        }}
                        className="accent-blue-600"
                      />
                      {a.name}
                      {excl && <span className="ml-auto text-[9px] text-red-400">excluded</span>}
                    </label>
                  )
                })}
              </div>
              {amcCount > 0 && (
                <button
                  onClick={() => { set("amc_codes", []); set("amc_exclude_codes", []) }}
                  className="text-[10px] text-blue-500 hover:underline"
                >
                  Clear AMC selection
                </button>
              )}
            </div>

            <div className="space-y-0.5">
              <label className="text-[11px] font-medium text-gray-600">Status</label>
              <select
                value={values.status}
                onChange={e => set("status", e.target.value)}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              >
                <option value="All">All statuses</option>
                <option value="Active">Active</option>
                <option value="Merged">Merged</option>
                <option value="Pending">Pending</option>
                <option value="Suspended">Suspended</option>
                <option value="Liquidated">Liquidated</option>
              </select>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                  Plan type
                  <span title="accord_fintech_scheme_details.plan (5=Direct, 6=Regular) — verified clean within equity categories" className="cursor-help">
                    <Info className="h-3 w-3 text-gray-300" />
                  </span>
                </label>
                <select
                  value={values.plan_type}
                  onChange={e => set("plan_type", e.target.value as FilterValues["plan_type"])}
                  className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
                >
                  <option value="">Any</option>
                  <option value="direct">Direct</option>
                  <option value="regular">Regular</option>
                </select>
              </div>
              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                  Option type
                  <span title="Best-effort text match on defaultplan — no coded lookup table exists for this field" className="cursor-help">
                    <Info className="h-3 w-3 text-gray-300" />
                  </span>
                </label>
                <select
                  value={values.option_type}
                  onChange={e => set("option_type", e.target.value as FilterValues["option_type"])}
                  className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
                >
                  <option value="">Any</option>
                  <option value="growth">Growth</option>
                  <option value="idcw">IDCW</option>
                </select>
              </div>
            </div>

            <NumberInput
              label="Min history (yrs)"
              hint="altstreet_scheme_master.launch_date age"
              value={values.min_history_years}
              onChange={v => set("min_history_years", v)}
              placeholder="e.g. 3" min={0} max={30}
            />

            <Toggle
              label="Require real benchmark mapping"
              hint="selfmade_scheme_category_benchmark, excludes is_fallback_benchmark — 2862/3758 real mapped vendor-wide"
              checked={values.require_benchmark_mapped}
              onChange={v => set("require_benchmark_mapped", v)}
            />

            <div className="space-y-0.5">
              <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                Min data confidence
                <span title="Composite: 40% real-benchmark-mapped + 30% fund age + 30% holdings freshness — all 3 inputs real" className="cursor-help">
                  <Info className="h-3 w-3 text-gray-300" />
                </span>
              </label>
              <select
                value={values.data_confidence_min}
                onChange={e => set("data_confidence_min", e.target.value as FilterValues["data_confidence_min"])}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              >
                <option value="">Any confidence</option>
                <option value="Low">Low or better (score ≥ 0)</option>
                <option value="Medium">Medium or better (score ≥ 40)</option>
                <option value="High">High only (score ≥ 70)</option>
              </select>
            </div>
          </div>
        )}
      </div>

      {/* ── PERFORMANCE HISTORY ───────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Performance History" open={openSections.performance} onToggle={() => toggle("performance")} />
        {openSections.performance && (
          <div className="pt-3 space-y-3">
            <div className="space-y-0.5">
              <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                Min return history
                <span title="Require non-null selfmade_scheme_returns for at least this window" className="cursor-help">
                  <Info className="h-3 w-3 text-gray-300" />
                </span>
              </label>
              <select
                value={values.min_return_history}
                onChange={e => set("min_return_history", e.target.value as FilterValues["min_return_history"])}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              >
                <option value="">Any</option>
                <option value="1Y">Has 1-year return</option>
                <option value="3Y">Has 3-year return</option>
                <option value="5Y">Has 5-year return</option>
              </select>
            </div>
            <DisabledField
              label="Min rolling-metric observation count"
              reason="No column tracks a distinct observation count — non-null metric checks above are the closest real proxy"
            />
            <DisabledField
              label="NAV coverage min %"
              reason="Blocked — navhist only has 9 days of data (Sept 2022) and no trading_calendar table exists. Import full NAV history first."
            />
          </div>
        )}
      </div>

      {/* ── SIZE / LIQUIDITY ──────────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Size / Liquidity" open={openSections.size} onToggle={() => toggle("size")} />
        {openSections.size && (
          <div className="pt-3 space-y-3">
            <RangeInputs
              label="AUM (₹ Cr)"
              hint="Latest accord_fintech_mf_portfolio.aum"
              minValue={values.aum_min_cr}
              maxValue={values.aum_max_cr}
              onMinChange={v => set("aum_min_cr", v)}
              onMaxChange={v => set("aum_max_cr", v)}
              min={0}
            />
            <NumberInput
              label="Max expense ratio %"
              hint="selfmade_expense_ratio — full real coverage (NOT the sparse legacy expenceratio vendor table)"
              value={values.expense_ratio_max}
              onChange={v => set("expense_ratio_max", v)}
              placeholder="e.g. 1.5" min={0} max={5} step={0.1}
            />
          </div>
        )}
      </div>

      {/* ── PORTFOLIO COMPOSITION ─────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Portfolio Composition" open={openSections.portfolio} onToggle={() => toggle("portfolio")} />
        {openSections.portfolio && (
          <div className="pt-3 space-y-3">
            <DisabledField
              label="Large/mid/small-cap exposure range"
              reason="No real per-holding market-cap classification exists — accord_fintech_mf_portfolio has sector only, and scheme_assetalloc's 'investment' field is a SEBI mandate category (Debt/Equity/REITs), not a cap-size breakdown"
            />
            <NumberInput
              label="Max top-5 concentration %"
              hint="Real accord_fintech_mf_portfolio holdings, latest disclosure"
              value={values.holding_concentration_max}
              onChange={v => set("holding_concentration_max", v)}
              placeholder="e.g. 40" min={0} max={100}
            />
            <NumberInput
              label="Max top-10 concentration %"
              hint="Same real source as top-5"
              value={values.top10_concentration_max}
              onChange={v => set("top10_concentration_max", v)}
              placeholder="e.g. 60" min={0} max={100}
            />
            <RangeInputs
              label="Number of holdings"
              hint="Count of holdings in latest real portfolio disclosure"
              minValue={values.holding_count_min}
              maxValue={values.holding_count_max}
              onMinChange={v => set("holding_count_min", v)}
              onMaxChange={v => set("holding_count_max", v)}
              min={0} minPlaceholder="Min" maxPlaceholder="Max"
            />
            {sectors.length > 0 && (
              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                  Sector exposure (include)
                  <span title="Fund must have exposure to ALL selected sectors — real sect_name column" className="cursor-help">
                    <Info className="h-3 w-3 text-gray-300" />
                  </span>
                  {values.sector_names.length > 0 && (
                    <span className="ml-1 text-blue-600">{values.sector_names.length} selected</span>
                  )}
                </label>
                <div className="border border-gray-200 rounded-lg overflow-y-auto max-h-28">
                  {sectors.map(s => (
                    <label
                      key={s.name}
                      className={cn(
                        "flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-gray-50 text-[11px]",
                        values.sector_names.includes(s.name) ? "bg-blue-50 text-blue-700" : "text-gray-700",
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={values.sector_names.includes(s.name)}
                        onChange={e =>
                          set("sector_names", e.target.checked
                            ? [...values.sector_names, s.name]
                            : values.sector_names.filter(n => n !== s.name))
                        }
                        className="accent-blue-600"
                      />
                      <span className="flex-1 truncate">{s.name}</span>
                      <span className="text-[9px] text-gray-300">{s.scheme_count}</span>
                    </label>
                  ))}
                </div>
                {values.sector_names.length > 0 && (
                  <button onClick={() => set("sector_names", [])} className="text-[10px] text-blue-500 hover:underline">
                    Clear sectors
                  </button>
                )}
              </div>
            )}
            <TextInput
              label="Must hold company (include)"
              hint="Real accord_fintech_mf_portfolio.compname substring match, latest disclosure"
              value={values.company_include}
              onChange={v => set("company_include", v)}
              placeholder="e.g. HDFC Bank"
            />
            <TextInput
              label="Must not hold company (exclude)"
              hint="Same real source"
              value={values.company_exclude}
              onChange={v => set("company_exclude", v)}
              placeholder="e.g. Adani"
            />
          </div>
        )}
      </div>

      {/* ── RISK ───────────────────────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Risk" open={openSections.risk} onToggle={() => toggle("risk")} />
        {openSections.risk && (
          <div className="pt-3 space-y-3">
            <DisabledField label="Max drawdown" reason="No column exists anywhere in the schema for max drawdown" />
            <DisabledField label="Volatility (annualised SD)" reason="mf_ratios_defaultbm.sd_annualised has zero populated rows" />
            <RangeInputs
              label="Tracking error 3yr (%)"
              hint="selfmade_scheme_metrics.tracking_error_3yr — full real coverage"
              minValue={values.tracking_error_min}
              maxValue={values.tracking_error_max}
              onMinChange={v => set("tracking_error_min", v)}
              onMaxChange={v => set("tracking_error_max", v)}
              min={0} minPlaceholder="Min" maxPlaceholder="Max e.g. 8"
            />
            <RangeInputs
              label="Beta range"
              hint="mf_ratios_defaultbm.beta — PARTIAL, ~17/473 populated in the ranked universe"
              minValue={values.beta_min}
              maxValue={values.beta_max}
              onMinChange={v => set("beta_min", v)}
              onMaxChange={v => set("beta_max", v)}
              step={0.01} minPlaceholder="Min e.g. 0.7" maxPlaceholder="Max e.g. 1.3"
            />
            <div className="grid grid-cols-2 gap-2">
              <NumberInput
                label="Sharpe ratio min"
                hint="selfmade_scheme_metrics.sharpe_ratio_3yr — full real coverage"
                value={values.sharpe_min}
                onChange={v => set("sharpe_min", v)}
                placeholder="e.g. 0.5" step={0.01}
              />
              <NumberInput
                label="Sortino ratio min"
                hint="selfmade_scheme_metrics.sortino_ratio_3yr — PARTIAL, ~18/473 populated (real, still sparse after the earlier fix)"
                value={values.sortino_min}
                onChange={v => set("sortino_min", v)}
                placeholder="e.g. 0.3" step={0.01}
              />
            </div>
            <DisabledField
              label="Max downside capture %"
              reason="Requires a daily price series vs benchmark — navhist only has 9 days of data"
            />
          </div>
        )}
      </div>

      {/* ── STRUCTURAL IMPROVEMENT ─────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Structural Improvement" open={openSections.structural} onToggle={() => toggle("structural")} />
        {openSections.structural && (
          <div className="pt-3 space-y-3">
            <NumberInput
              label="IR slope (6mo) min"
              hint="selfmade_scheme_metrics.ir_slope_6m_proxy — full real coverage"
              value={values.ir_slope_min}
              onChange={v => set("ir_slope_min", v)}
              placeholder="e.g. 0" step={0.01}
            />
            <NumberInput
              label="Min outperformance ratio (0–1)"
              hint="Fraction of outperformed_1yr/3yr/5yr flags — real, full/near-full coverage"
              value={values.outperformance_ratio_min}
              onChange={v => set("outperformance_ratio_min", v)}
              placeholder="e.g. 0.5" min={0} max={1} step={0.01}
            />
            <NumberInput
              label="Min rank movement (6mo)"
              hint="selfmade_ranking_snapshot.rank_delta_6m — real column, fully populated. Currently 0 for every fund under every category's CURRENT taxonomy naming (no 6-month lookback exists yet post-rename) — a threshold above 0 will honestly show zero matches until more time passes."
              value={values.rank_movement_min}
              onChange={v => set("rank_movement_min", v)}
              placeholder="e.g. 3"
            />
            <DisabledField
              label="Min improvement metric"
              reason="No separate pre-computed IR-trend column exists beyond IR slope above — use IR slope (6mo) min as the real proxy"
            />
            <DisabledField
              label="Min consistency score"
              reason="No stored consistency-score column exists — Fund Detail's IR Consistency view is computed on-the-fly per fund, not as a single filterable number"
            />
          </div>
        )}
      </div>

      {/* ── LIFECYCLE / REGULATORY ────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Lifecycle / Regulatory" open={openSections.lifecycle} onToggle={() => toggle("lifecycle")} />
        {openSections.lifecycle && (
          <div className="pt-3 space-y-3">
            <Toggle
              label="Exclude merged funds"
              hint="altstreet_scheme_master.status != 'Merged' — real, rich status distribution"
              checked={values.exclude_merged}
              onChange={v => set("exclude_merged", v)}
            />
            <DisabledField
              label="Exclude recently category-changed schemes"
              reason="category_taxonomy_current versioning infrastructure exists, but every scheme is still at version 1 — zero real category-change events have ever been recorded to filter against"
            />
            <DisabledField
              label="Exclude recently benchmark-changed schemes"
              reason="selfmade_scheme_category_benchmark versioning infrastructure exists, but every mapping is still at version 1 — zero real benchmark-change events recorded"
            />
          </div>
        )}
      </div>

      {/* ── OPERATIONAL / DATA QUALITY ────────────────────────────────────── */}
      <div>
        <SectionHeader title="Operational / Data Quality" open={openSections.operational} onToggle={() => toggle("operational")} />
        {openSections.operational && (
          <div className="pt-3 space-y-3">
            <NumberInput
              label="Max holdings age (months)"
              hint="Real accord_fintech_mf_portfolio.invdate freshness"
              value={values.holdings_freshness_max_months}
              onChange={v => set("holdings_freshness_max_months", v)}
              placeholder="e.g. 6" min={0} max={36}
            />
            <NumberInput
              label="Max AUM data age (days)"
              hint="Real accord_fintech_mf_portfolio.invdate freshness for the latest AUM figure"
              value={values.aum_freshness_days}
              onChange={v => set("aum_freshness_days", v)}
              placeholder="e.g. 90" min={0}
            />
            <DisabledField
              label="Document availability"
              reason="selfmade_document rows exist for all 473 core funds, but the underlying file_url values are seeded placeholders (storage.altstreet.local), not real documents — not a trustworthy filter signal yet"
            />
          </div>
        )}
      </div>

      {/* ── TAXONOMY ───────────────────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Taxonomy" open={openSections.taxonomy} onToggle={() => toggle("taxonomy")} />
        {openSections.taxonomy && (
          <div className="pt-3 space-y-3">
            <Toggle
              label="Exclude ELSS funds"
              hint="Derived from sm.category = 'Equity Linked Savings Scheme' (3-yr tax lock-in)"
              checked={values.exclude_elss}
              onChange={v => set("exclude_elss", v)}
            />
            <Toggle
              label="Exclude Thematic / Sectoral"
              hint="Derived from sm.category — removes Thematic Fund + Sector Funds"
              checked={values.exclude_thematic}
              onChange={v => set("exclude_thematic", v)}
            />
            <p className="text-[10px] text-gray-400 pt-1">
              Asset class (equity/hybrid/passive), Index Funds, and ETFs are already
              filterable above via Asset Class and Category — real category_taxonomy_current fields.
            </p>
            <DisabledField
              label="Open / close-ended"
              reason="No real column distinguishes open-ended vs close-ended schemes in the data available today"
            />
          </div>
        )}
      </div>

      {/* ── CLIENT-SPECIFIC / GOVERNANCE ──────────────────────────────────── */}
      <div>
        <SectionHeader title="Client-Specific / Governance" open={openSections.governance} onToggle={() => toggle("governance")} />
        {openSections.governance && (
          <div className="pt-3 space-y-3">
            <DisabledField label="Client-approved AMC list" reason="No client-configuration system exists in this product yet" />
            <DisabledField label="Client-restricted funds" reason="No client-configuration system exists in this product yet" />
            <DisabledField label="Watchlist-only" reason="No watchlist table exists in this product yet" />
            <DisabledField label="Compliance-flagged exclusion" reason="No compliance-flag table exists in this product yet" />
            <DisabledField label="Approved universe version" reason="No client-approved-universe versioning exists in this product yet" />
          </div>
        )}
      </div>
    </div>
  )
}
