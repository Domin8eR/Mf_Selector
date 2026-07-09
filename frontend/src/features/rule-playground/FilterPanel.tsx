import { useState } from "react"
import { ChevronDown, ChevronUp, Info } from "lucide-react"
import { cn } from "@/lib/utils"
import type { Category36Group } from "@/lib/api"

export interface FilterValues {
  // ── Eligibility ──────────────────────────────────────────────────────────
  category: string
  bucket_36: string | null
  bucket_group: string | null           // "ALL Equity" | "ALL Hybrid" | "ALL Passive"
  amc_codes: number[]
  amc_exclude_codes: number[]
  status: string
  aum_min_cr: string
  aum_max_cr: string
  aum_freshness_days: string
  min_history_years: string
  expense_ratio_max: string
  plan_type: "" | "direct" | "regular"
  option_type: "" | "growth" | "idcw"
  exclude_elss: boolean
  exclude_thematic: boolean
  // ── Data Quality ─────────────────────────────────────────────────────────
  exclude_merged: boolean
  require_benchmark_mapped: boolean
  holdings_freshness_max_months: string
  data_confidence_min: "" | "Low" | "Medium" | "High"
  min_return_history: "" | "1Y" | "3Y" | "5Y"
  // ── Structural Improvement ────────────────────────────────────────────────
  ir_percentile_min: string
  outperformance_ratio_min: string
  rank_movement_min: string
  // ── Risk ──────────────────────────────────────────────────────────────────
  tracking_error_min: string
  tracking_error_max: string
  beta_min: string
  beta_max: string
  sharpe_min: string
  sortino_min: string
  // ── Portfolio ─────────────────────────────────────────────────────────────
  holding_concentration_max: string      // top-5
  top10_concentration_max: string        // top-10
  holding_count_min: string
  holding_count_max: string
  sector_names: string[]                 // maps to sector_exposure with min 0.01%
}

export const EMPTY_FILTERS: FilterValues = {
  category: "",
  bucket_36: null,
  bucket_group: null,
  amc_codes: [],
  amc_exclude_codes: [],
  status: "Active",
  aum_min_cr: "",
  aum_max_cr: "",
  aum_freshness_days: "",
  min_history_years: "",
  expense_ratio_max: "",
  plan_type: "",
  option_type: "",
  exclude_elss: false,
  exclude_thematic: false,
  exclude_merged: true,
  require_benchmark_mapped: false,
  holdings_freshness_max_months: "",
  data_confidence_min: "",
  min_return_history: "",
  ir_percentile_min: "",
  outperformance_ratio_min: "",
  rank_movement_min: "",
  tracking_error_min: "",
  tracking_error_max: "",
  beta_min: "",
  beta_max: "",
  sharpe_min: "",
  sortino_min: "",
  holding_concentration_max: "",
  top10_concentration_max: "",
  holding_count_min: "",
  holding_count_max: "",
  sector_names: [],
}

interface Amc {
  amc_code: number
  name: string
}

interface FlatCategory {
  id: string
  name: string
}

interface Sector {
  name: string
  scheme_count: number
}

const BUCKET_GROUPS = ["ALL Equity", "ALL Hybrid", "ALL Passive"] as const

interface Props {
  values: FilterValues
  onChange: (v: FilterValues) => void
  /** Flat list (raw altstreet categories) — shown when categories36 is empty */
  categories: FlatCategory[]
  /** Grouped 36-bucket taxonomy — preferred when available */
  categories36?: Category36Group[]
  amcs: Amc[]
  sectors?: Sector[]
}

function SectionHeader({
  title, open, onToggle,
}: { title: string; open: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className="flex items-center justify-between w-full py-2 text-sm font-semibold text-gray-700 border-b border-gray-100"
    >
      <span>{title}</span>
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

export function FilterPanel({
  values, onChange, categories, categories36, amcs, sectors = [],
}: Props) {
  const [openSections, setOpenSections] = useState({
    eligibility: true,
    dataQuality: false,
    advanced: false,
  })
  const [amcMode, setAmcMode] = useState<"include" | "exclude">("include")

  const toggle = (section: keyof typeof openSections) =>
    setOpenSections(prev => ({ ...prev, [section]: !prev[section] }))

  const set = <K extends keyof FilterValues>(k: K, v: FilterValues[K]) =>
    onChange({ ...values, [k]: v })

  const amcCount = values.amc_codes.length + values.amc_exclude_codes.length

  // Build sector_exposure dict from selected sector_names (any exposure ≥ 0.01%)
  const sectorExposureMap = Object.fromEntries(
    values.sector_names.map(s => [s, 0.01])
  )
  void sectorExposureMap // used by parent via FilterValues → index.tsx mapping

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3 text-xs">
      <div className="text-sm font-semibold text-gray-800">Filters</div>

      {/* ── ELIGIBILITY ──────────────────────────────────────────────────── */}
      <div>
        <SectionHeader
          title={`Eligibility${amcCount ? ` · ${amcCount} AMC` : ""}`}
          open={openSections.eligibility}
          onToggle={() => toggle("eligibility")}
        />
        {openSections.eligibility && (
          <div className="pt-3 space-y-3">

            {/* Group picker (ALL Equity / ALL Hybrid / ALL Passive) */}
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

            {/* Category — 36-bucket grouped picker (bucket_group overrides this) */}
            <div className="space-y-0.5">
              <label className="text-[11px] font-medium text-gray-600">
                Category
                {categories36 && categories36.length > 0 && (
                  <span className="ml-1 text-[10px] text-blue-500">36-bucket</span>
                )}
              </label>
              <select
                value={values.bucket_36 ?? values.category}
                onChange={e => {
                  if (categories36 && categories36.length > 0) {
                    set("bucket_36", e.target.value || null)
                  } else {
                    set("category", e.target.value)
                  }
                }}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white"
              >
                <option value="">All categories</option>
                {categories36 && categories36.length > 0
                  ? categories36.map(g => (
                      <optgroup key={g.group} label={g.group}>
                        {g.buckets.map(b => (
                          <option key={b.id} value={b.id}>{b.name} ({b.count})</option>
                        ))}
                      </optgroup>
                    ))
                  : categories.map(c => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))
                }
              </select>
            </div>

            {/* AMC multi-select with include / exclude toggle */}
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

            {/* Status */}
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
                <option value="Closed">Closed</option>
                <option value="Pending">Pending</option>
                <option value="Suspended">Suspended</option>
                <option value="Liquidated">Liquidated</option>
              </select>
            </div>

            {/* AUM range */}
            <RangeInputs
              label="AUM (₹ Cr)"
              minValue={values.aum_min_cr}
              maxValue={values.aum_max_cr}
              onMinChange={v => set("aum_min_cr", v)}
              onMaxChange={v => set("aum_max_cr", v)}
              min={0}
            />

            {/* Min history & expense ratio */}
            <div className="grid grid-cols-2 gap-2">
              <NumberInput
                label="Min history (yrs)"
                hint="Minimum fund age since inception date"
                value={values.min_history_years}
                onChange={v => set("min_history_years", v)}
                placeholder="e.g. 3" min={0} max={30}
              />
              <NumberInput
                label="Max expense ratio %"
                hint="Latest expense ratio from expenceratio table"
                value={values.expense_ratio_max}
                onChange={v => set("expense_ratio_max", v)}
                placeholder="e.g. 1.5" min={0} max={5} step={0.1}
              />
            </div>

            {/* Plan / Option type */}
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-0.5">
                <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                  Plan type
                  <span title="Inferred from afd.optiontype codes (DP/DR ≈ Direct). Verify against DB." className="cursor-help">
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
                <label className="text-[11px] font-medium text-gray-600">Option type</label>
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

            {/* Taxonomy exclusion toggles */}
            <div className="space-y-2 pt-1 border-t border-gray-50">
              <Toggle
                label="Exclude ELSS funds"
                hint="Removes 'Equity Linked Savings Scheme' funds (3-yr tax lock-in)"
                checked={values.exclude_elss}
                onChange={v => set("exclude_elss", v)}
              />
              <Toggle
                label="Exclude Thematic / Sectoral"
                hint="Removes Thematic Fund + Sector Funds categories from universe"
                checked={values.exclude_thematic}
                onChange={v => set("exclude_thematic", v)}
              />
            </div>
          </div>
        )}
      </div>

      {/* ── DATA QUALITY / REGULATORY ────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Data Quality / Regulatory"
          open={openSections.dataQuality}
          onToggle={() => toggle("dataQuality")}
        />
        {openSections.dataQuality && (
          <div className="pt-3 space-y-3">
            <Toggle
              label="Exclude merged funds"
              hint="Excludes schemes with status='Merged' in accord_fintech_scheme_details"
              checked={values.exclude_merged}
              onChange={v => set("exclude_merged", v)}
            />
            <Toggle
              label="Require exact benchmark"
              hint="Only include funds with a non-fallback benchmark in selfmade_scheme_category_benchmark"
              checked={values.require_benchmark_mapped}
              onChange={v => set("require_benchmark_mapped", v)}
            />
            <NumberInput
              label="Max holdings age (months)"
              hint="Maximum months since latest portfolio disclosure in accord_fintech_mf_portfolio"
              value={values.holdings_freshness_max_months}
              onChange={v => set("holdings_freshness_max_months", v)}
              placeholder="e.g. 6" min={0} max={36}
            />
            <NumberInput
              label="Max AUM data age (days)"
              hint="Maximum days since latest scheme_aum snapshot"
              value={values.aum_freshness_days}
              onChange={v => set("aum_freshness_days", v)}
              placeholder="e.g. 90" min={0}
            />

            {/* Data confidence min — backend fully wired */}
            <div className="space-y-0.5">
              <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                Min data confidence
                <span title="Composite: 40% benchmark quality + 30% history + 30% holdings freshness" className="cursor-help">
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

            {/* Min return history */}
            <div className="space-y-0.5">
              <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                Min return history
                <span title="Require non-null CAGR return for at least this window in mf_cagr_return" className="cursor-help">
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

            {/* NAV coverage — BLOCKED, shown with explanation */}
            <div className="space-y-0.5 opacity-50">
              <label className="text-[11px] font-medium text-gray-500 flex items-center gap-1">
                NAV coverage min %
                <span title="Blocked — navhist only has 9 days of data and trading_calendar table is missing. Import full NAV history first." className="cursor-help">
                  <Info className="h-3 w-3 text-gray-400" />
                </span>
              </label>
              <div className="w-full text-xs border border-dashed border-gray-200 rounded-lg px-2 py-1.5 text-gray-400 bg-gray-50">
                Blocked (import full NAV history first)
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── ADVANCED ─────────────────────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Advanced"
          open={openSections.advanced}
          onToggle={() => toggle("advanced")}
        />
        {openSections.advanced && (
          <div className="pt-3 space-y-4">

            {/* Structural Improvement */}
            <div>
              <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-2">
                Structural Improvement
              </div>
              <div className="space-y-2">
                <NumberInput
                  label="Min IR percentile (0–100)"
                  hint="Percentile proxy for IR quality via selfmade_scheme_ranking.pct_ir_3yr. Not the raw IR-slope value — direct slope column not yet computed."
                  value={values.ir_percentile_min}
                  onChange={v => set("ir_percentile_min", v)}
                  placeholder="e.g. 50" min={0} max={100}
                />
                <NumberInput
                  label="Min outperformance ratio (0–1)"
                  hint="Fraction of 1yr/3yr/5yr periods where fund outperformed benchmark. 0.5 = at least 2/3."
                  value={values.outperformance_ratio_min}
                  onChange={v => set("outperformance_ratio_min", v)}
                  placeholder="e.g. 0.5" min={0} max={1} step={0.01}
                />
                <div className="space-y-0.5 opacity-50">
                  <label className="text-[11px] font-medium text-gray-500 flex items-center gap-1">
                    Min improvement metric
                    <span title="Requires a pre-computed IR-trend column populated by a Celery job. Not yet available." className="cursor-help"><Info className="h-3 w-3 text-gray-400" /></span>
                  </label>
                  <div className="w-full text-xs border border-dashed border-gray-200 rounded-lg px-2 py-1.5 text-gray-400 bg-gray-50">Stub — Celery job needed</div>
                </div>
                <div className="space-y-0.5 opacity-50">
                  <label className="text-[11px] font-medium text-gray-500 flex items-center gap-1">
                    Min rank movement
                    <span title="selfmade_scheme_ranking.rank_delta is not yet populated — only one ranking run exists." className="cursor-help"><Info className="h-3 w-3 text-gray-400" /></span>
                  </label>
                  <div className="w-full text-xs border border-dashed border-gray-200 rounded-lg px-2 py-1.5 text-gray-400 bg-gray-50">Stub — run ranking job again first</div>
                </div>
              </div>
            </div>

            {/* Risk */}
            <div>
              <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-2">
                Risk
              </div>
              <div className="space-y-2">
                <RangeInputs
                  label="Tracking error 3yr (%)"
                  hint="From selfmade_scheme_metrics.tracking_error_3yr"
                  minValue={values.tracking_error_min}
                  maxValue={values.tracking_error_max}
                  onMinChange={v => set("tracking_error_min", v)}
                  onMaxChange={v => set("tracking_error_max", v)}
                  min={0} minPlaceholder="Min" maxPlaceholder="Max e.g. 8"
                />
                <RangeInputs
                  label="Beta range"
                  hint="From mf_ratios_defaultbm.beta — populated for all schemes"
                  minValue={values.beta_min}
                  maxValue={values.beta_max}
                  onMinChange={v => set("beta_min", v)}
                  onMaxChange={v => set("beta_max", v)}
                  step={0.01} minPlaceholder="Min e.g. 0.7" maxPlaceholder="Max e.g. 1.3"
                />
                <div className="grid grid-cols-2 gap-2">
                  <NumberInput
                    label="Sharpe ratio min"
                    hint="mf_ratios_defaultbm.sharpe — also the current ranking sort basis"
                    value={values.sharpe_min}
                    onChange={v => set("sharpe_min", v)}
                    placeholder="e.g. 0.5" step={0.01}
                  />
                  <NumberInput
                    label="Sortino ratio min"
                    hint="mf_ratios_defaultbm.sortino"
                    value={values.sortino_min}
                    onChange={v => set("sortino_min", v)}
                    placeholder="e.g. 0.3" step={0.01}
                  />
                </div>
                <div className="space-y-0.5 opacity-50">
                  <label className="text-[11px] font-medium text-gray-500 flex items-center gap-1">
                    Max downside capture %
                    <span title="Requires daily price series vs benchmark. navhist only has 9 days. Blocked." className="cursor-help"><Info className="h-3 w-3 text-gray-400" /></span>
                  </label>
                  <div className="w-full text-xs border border-dashed border-gray-200 rounded-lg px-2 py-1.5 text-gray-400 bg-gray-50">Blocked (import full NAV history first)</div>
                </div>
              </div>
            </div>

            {/* Portfolio */}
            <div>
              <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wide mb-2">
                Portfolio
              </div>
              <div className="space-y-2">
                <NumberInput
                  label="Max top-5 concentration %"
                  hint="Maximum % held in the top 5 holdings (accord_fintech_mf_portfolio, latest disclosure)"
                  value={values.holding_concentration_max}
                  onChange={v => set("holding_concentration_max", v)}
                  placeholder="e.g. 40" min={0} max={100}
                />
                <NumberInput
                  label="Max top-10 concentration %"
                  hint="Maximum % held in the top 10 holdings. Note: must be ≥ top-5 value."
                  value={values.top10_concentration_max}
                  onChange={v => set("top10_concentration_max", v)}
                  placeholder="e.g. 60" min={0} max={100}
                />
                <RangeInputs
                  label="Number of holdings"
                  hint="Count of holdings in latest portfolio disclosure"
                  minValue={values.holding_count_min}
                  maxValue={values.holding_count_max}
                  onMinChange={v => set("holding_count_min", v)}
                  onMaxChange={v => set("holding_count_max", v)}
                  min={0} minPlaceholder="Min" maxPlaceholder="Max"
                />

                {/* Sector multi-select — backend fully wired */}
                {sectors.length > 0 && (
                  <div className="space-y-0.5">
                    <label className="text-[11px] font-medium text-gray-600 flex items-center gap-1">
                      Sector exposure (include)
                      <span title="Fund must have any exposure to ALL selected sectors. AND logic — select one sector for OR-style inclusion." className="cursor-help">
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
                      <button
                        onClick={() => set("sector_names", [])}
                        className="text-[10px] text-blue-500 hover:underline"
                      >
                        Clear sectors
                      </button>
                    )}
                  </div>
                )}

                <div className="space-y-0.5 opacity-50">
                  <label className="text-[11px] font-medium text-gray-500 flex items-center gap-1">
                    Cap-size exposure (large/mid/small/cash %)
                    <span title="Tier 3 — requires scheme_assetalloc service. Coming soon." className="cursor-help"><Info className="h-3 w-3 text-gray-400" /></span>
                  </label>
                  <div className="w-full text-xs border border-dashed border-gray-200 rounded-lg px-2 py-1.5 text-gray-400 bg-gray-50">Tier 3 — scheme_assetalloc needed</div>
                </div>
              </div>
            </div>

          </div>
        )}
      </div>
    </div>
  )
}
