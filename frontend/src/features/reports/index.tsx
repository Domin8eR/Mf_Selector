/**
 * Reports Builder — Section 9.9
 * 3-step flow: Compose → Preview → Export
 * Language rule: never "recommendation/buy/sell" — use "ranked fund/research candidate"
 */
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  reportsApi,
  type Report,
  type FundNarrative,
  type KeyInsight,
  type ComplianceResult,
} from "../../lib/api"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"

// ── Constants ─────────────────────────────────────────────────────────────────

const CATEGORIES = [
  "Equity — Large Cap",
  "Equity — Mid Cap",
  "Equity — Small Cap",
] as const

const STEPS = ["Compose", "Preview", "Export"] as const

const CHART_COLORS = [
  "#2563EB",
  "#3B82F6",
  "#60A5FA",
  "#93C5FD",
  "#BFDBFE",
]

// ── Step indicator ─────────────────────────────────────────────────────────────

function StepBar({ step }: { step: number }) {
  return (
    <div className="flex items-center gap-2 mb-6">
      {STEPS.map((label, idx) => (
        <div key={label} className="flex items-center gap-2">
          <div
            className={[
              "w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold",
              idx < step
                ? "bg-blue-600 text-white"
                : idx === step
                ? "bg-blue-600 text-white ring-2 ring-blue-300"
                : "bg-slate-100 text-slate-400",
            ].join(" ")}
          >
            {idx < step ? "✓" : idx + 1}
          </div>
          <span
            className={`text-sm ${idx === step ? "font-semibold text-slate-800" : "text-slate-400"}`}
          >
            {label}
          </span>
          {idx < STEPS.length - 1 && (
            <div className={`h-px w-8 ${idx < step ? "bg-blue-600" : "bg-slate-200"}`} />
          )}
        </div>
      ))}
    </div>
  )
}

// ── Compliance banner ──────────────────────────────────────────────────────────

function ComplianceBanner({
  result,
}: {
  result: ComplianceResult
}) {
  if (result.pass) {
    return (
      <div className="rounded-lg bg-green-50 border border-green-200 px-4 py-3 flex items-center gap-2 text-sm text-green-800">
        <span className="text-green-600 font-bold">✓</span>
        Compliance check passed — no forbidden phrases detected.
      </div>
    )
  }

  return (
    <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-red-800">
        <span>⚠</span>
        Compliance check failed — {result.flagged_phrases.length} issue
        {result.flagged_phrases.length !== 1 ? "s" : ""} detected. Export is blocked until
        resolved.
      </div>
      <div className="text-xs text-red-700 space-y-1">
        {result.flagged_phrases.map((phrase, i) => (
          <div key={i} className="flex items-baseline gap-2">
            <span className="font-mono bg-red-100 px-1 rounded">{phrase}</span>
            <span className="text-red-500">—</span>
            <span className="text-red-600">
              {result.suggested_rewrites.find((r) => r.phrase === phrase)?.rewrite ??
                "replace with compliant phrasing"}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Make-client-safe card ─────────────────────────────────────────────────────

function ClientSafeCard({
  compliance,
  reportId,
  onFixed,
}: {
  compliance: ComplianceResult
  reportId: number
  onFixed: (updated: Report) => void
}) {
  const qc = useQueryClient()
  const fixMutation = useMutation({
    mutationFn: ({
      phrase,
      field,
      rewrite,
    }: {
      phrase: string
      field: string
      rewrite: string
    }) => reportsApi.applyFix(reportId, phrase, field, rewrite),
    onSuccess: (updated) => {
      onFixed(updated)
      qc.invalidateQueries({ queryKey: ["reports", "recent"] })
    },
  })

  if (compliance.pass || compliance.suggested_rewrites.length === 0) return null

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-4 space-y-3">
      <h3 className="text-sm font-semibold text-amber-900">Make this client-safe</h3>
      <p className="text-xs text-amber-700">
        Apply the suggested rewrite for each flagged phrase. Each fix reruns the full
        compliance check.
      </p>
      {compliance.suggested_rewrites.map((rw, i) => (
        <div
          key={i}
          className="flex items-start justify-between gap-4 rounded bg-white border border-amber-100 px-3 py-2"
        >
          <div className="text-xs space-y-0.5">
            <div>
              <span className="text-red-600 font-mono line-through">{rw.phrase}</span>
              <span className="mx-2 text-slate-400">→</span>
              <span className="text-green-700 font-medium">{rw.rewrite}</span>
            </div>
          </div>
          <button
            onClick={() =>
              fixMutation.mutate({ phrase: rw.phrase, field: "exec_summary", rewrite: rw.rewrite })
            }
            disabled={fixMutation.isPending}
            className="shrink-0 text-xs bg-amber-600 hover:bg-amber-700 text-white px-2 py-1 rounded disabled:opacity-50"
          >
            {fixMutation.isPending ? "Applying…" : "Apply"}
          </button>
        </div>
      ))}
    </div>
  )
}

// ── Fund table ────────────────────────────────────────────────────────────────

function FundTable({ funds }: { funds: FundNarrative[] }) {
  return (
    <div className="overflow-auto rounded-lg border border-slate-200">
      <table className="w-full text-xs">
        <thead className="bg-blue-700 text-white">
          <tr>
            {["Rank", "Fund Name", "Score", "IR 3Y", "Sharpe", "6M Δ", "Why it stands out"].map(
              (h) => (
                <th key={h} className="px-3 py-2 text-left font-semibold whitespace-nowrap">
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {funds.map((fn, i) => (
            <tr
              key={fn.schemecode}
              className={i % 2 === 0 ? "bg-white" : "bg-slate-50"}
            >
              <td className="px-3 py-2 font-bold text-blue-700">#{fn.rank}</td>
              <td className="px-3 py-2 max-w-[200px]">
                <span className="line-clamp-2">{fn.fund_name}</span>
              </td>
              <td className="px-3 py-2 tabular-nums font-mono">
                {fn.composite_score.toFixed(2)}
              </td>
              <td className="px-3 py-2 tabular-nums font-mono">
                {fn.information_ratio_3yr.toFixed(4)}
              </td>
              <td className="px-3 py-2 tabular-nums font-mono">
                {fn.sharpe_score.toFixed(4)}
              </td>
              <td className="px-3 py-2 tabular-nums">
                {fn.rank_delta_6m !== null ? (
                  <span
                    className={
                      fn.rank_delta_6m > 0
                        ? "text-green-600"
                        : fn.rank_delta_6m < 0
                        ? "text-red-600"
                        : "text-slate-400"
                    }
                  >
                    {fn.rank_delta_6m > 0 ? "+" : ""}
                    {fn.rank_delta_6m}
                  </span>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
              <td className="px-3 py-2 text-slate-600 max-w-[240px]">
                <span className="line-clamp-2">{fn.narrative || "—"}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Score bar chart ────────────────────────────────────────────────────────────

function ScoreChart({ funds }: { funds: FundNarrative[] }) {
  const data = funds.map((fn) => ({
    name: `#${fn.rank} ${fn.fund_name.split(" ").slice(0, 2).join(" ")}`,
    score: fn.composite_score,
  }))

  return (
    <div className="h-40">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <XAxis dataKey="name" tick={{ fontSize: 10 }} />
          <YAxis
            domain={[
              Math.floor((Math.min(...data.map((d) => d.score)) - 2) / 5) * 5,
              Math.ceil((Math.max(...data.map((d) => d.score)) + 2) / 5) * 5,
            ]}
            tick={{ fontSize: 10 }}
          />
          <Tooltip
            formatter={(v: number) => [v.toFixed(2), "Composite Score"]}
          />
          <Bar dataKey="score" radius={[3, 3, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Key insights cards ─────────────────────────────────────────────────────────

function KeyInsightsCards({ insights }: { insights: KeyInsight[] }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      {insights.map((ki, i) => (
        <div key={i} className="rounded-lg bg-slate-50 border border-slate-200 px-4 py-3">
          <div className="text-xs font-semibold text-slate-700 mb-1">{ki.heading}</div>
          <div className="text-xs text-slate-600">{ki.body}</div>
        </div>
      ))}
    </div>
  )
}

// ── Recent reports strip ──────────────────────────────────────────────────────

function RecentStrip({ onSelect }: { onSelect: (r: Report) => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["reports", "recent"],
    queryFn: reportsApi.getRecent,
    staleTime: 30_000,
  })

  if (isLoading) return null
  if (!data?.reports.length) return null

  const statusColors: Record<string, string> = {
    draft: "bg-slate-100 text-slate-600",
    compliance_passed: "bg-green-100 text-green-700",
    compliance_failed: "bg-red-100 text-red-700",
    exported: "bg-blue-100 text-blue-700",
  }

  return (
    <div className="mt-8 border-t border-slate-200 pt-4">
      <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
        Recent reports
      </h3>
      <div className="flex gap-3 overflow-x-auto pb-1">
        {data.reports.slice(0, 8).map((r) => (
          <button
            key={r.id}
            onClick={() => onSelect(r)}
            className="shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-left hover:border-blue-400 hover:shadow-sm transition-all w-52"
          >
            <div className="text-xs font-medium text-slate-800 line-clamp-1">{r.title}</div>
            <div className="text-xs text-slate-500 mt-0.5">{r.snapshot_date}</div>
            <div className="mt-1.5">
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${statusColors[r.status] ?? "bg-slate-100 text-slate-500"}`}
              >
                {r.status.replace("_", " ")}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Step 1: Compose ────────────────────────────────────────────────────────────

function ComposeStep({
  onGenerate,
}: {
  onGenerate: (report: Report) => void
}) {
  const [category, setCategory] = useState<string>(CATEGORIES[0])
  const [sections, setSections] = useState({
    exec_summary: true,
    top_funds: true,
    key_insights: true,
    methodology: false,
  })
  const [title, setTitle] = useState("")

  const generateMutation = useMutation({
    mutationFn: () =>
      reportsApi.generate({
        category,
        title: title.trim() || undefined,
        sections,
      }),
    onSuccess: onGenerate,
  })

  const toggleSection = (key: keyof typeof sections) =>
    setSections((s) => ({ ...s, [key]: !s[key] }))

  return (
    <div className="max-w-xl space-y-5">
      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">
          Report title (optional)
        </label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Q3 Large Cap Research Review"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-1">
          Category
        </label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-700 mb-2">
          Sections
        </label>
        <div className="space-y-2">
          {(
            [
              ["exec_summary", "Executive Summary"],
              ["top_funds", "Top Ranked Funds Table"],
              ["key_insights", "Key Insights"],
              ["methodology", "Methodology (disabled in MVP)", true],
            ] as [keyof typeof sections, string, boolean?][]
          ).map(([key, label, disabled]) => (
            <label
              key={key}
              className={`flex items-center gap-2 text-sm ${disabled ? "text-slate-400 cursor-not-allowed" : "cursor-pointer"}`}
            >
              <input
                type="checkbox"
                checked={disabled ? false : sections[key]}
                disabled={!!disabled}
                onChange={() => !disabled && toggleSection(key)}
                className="rounded"
              />
              {label}
              {disabled && (
                <span className="text-xs bg-slate-100 text-slate-400 px-1.5 py-0.5 rounded">
                  coming soon
                </span>
              )}
            </label>
          ))}
        </div>
      </div>

      {generateMutation.isError && (
        <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
          {String(generateMutation.error)}
        </div>
      )}

      <button
        onClick={() => generateMutation.mutate()}
        disabled={generateMutation.isPending}
        className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2.5 rounded-md disabled:opacity-60 flex items-center justify-center gap-2"
      >
        {generateMutation.isPending ? (
          <>
            <span className="animate-spin">⟳</span> Generating report…
          </>
        ) : (
          "Generate Report"
        )}
      </button>

      <p className="text-xs text-slate-500">
        Pulls top-5 ranked research candidates for the selected category from the latest
        snapshot. An AI narrative is drafted and immediately checked for compliance
        before you see it.
      </p>
    </div>
  )
}

// ── Step 2: Preview ────────────────────────────────────────────────────────────

function PreviewStep({
  report,
  onChange,
  onNext,
  onBack,
}: {
  report: Report
  onChange: (r: Report) => void
  onNext: () => void
  onBack: () => void
}) {
  const compliance = report.compliance_result

  return (
    <div className="space-y-5">
      {/* Compliance banner */}
      {compliance && (
        <ComplianceBanner result={compliance} />
      )}

      {/* Make client-safe card */}
      {compliance && !compliance.pass && (
        <ClientSafeCard
          compliance={compliance}
          reportId={report.id}
          onFixed={onChange}
        />
      )}

      {/* Report content */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        {/* Header */}
        <div className="bg-blue-700 text-white px-6 py-4">
          <h2 className="text-base font-bold">{report.title}</h2>
          <div className="text-blue-200 text-xs mt-0.5">
            {report.category} · Snapshot {report.snapshot_date}
            {report.rule_version_label ? ` · Rule ${report.rule_version_label}` : ""}
          </div>
        </div>

        <div className="px-6 py-5 space-y-6">
          {/* Chart */}
          {report.fund_narratives.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3">
                Composite Scores — Top Ranked Funds
              </h3>
              <ScoreChart funds={report.fund_narratives} />
            </div>
          )}

          {/* Fund table */}
          {report.fund_narratives.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3">
                Top Ranked Research Candidates
              </h3>
              <FundTable funds={report.fund_narratives} />
            </div>
          )}

          {/* Exec summary */}
          {report.exec_summary && (
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-2">
                Executive Summary
              </h3>
              {report.exec_summary.split("\n\n").map((para, i) => (
                <p key={i} className="text-sm text-slate-700 mb-2 leading-relaxed">
                  {para}
                </p>
              ))}
            </div>
          )}

          {/* Key insights */}
          {report.key_insights.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-2">Key Insights</h3>
              <KeyInsightsCards insights={report.key_insights} />
            </div>
          )}

          {/* Disclaimer */}
          <div className="rounded-md bg-slate-50 border border-slate-200 px-4 py-3 text-xs text-slate-500">
            This report presents metric-derived rankings and structural analysis only.
            It does not constitute investment advice or a suitability assessment.
          </div>
        </div>
      </div>

      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="border border-slate-300 text-slate-700 text-sm px-4 py-2 rounded-md hover:bg-slate-50"
        >
          ← Back
        </button>
        <button
          onClick={onNext}
          disabled={!compliance?.pass}
          title={!compliance?.pass ? "Resolve compliance issues to continue" : undefined}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-md disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Proceed to Export →
        </button>
      </div>
    </div>
  )
}

// ── Step 3: Export ─────────────────────────────────────────────────────────────

function ExportStep({
  report,
  onBack,
}: {
  report: Report
  onBack: () => void
}) {
  const [exported, setExported] = useState<{
    pdfPath: string
    docxPath: string
  } | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const qc = useQueryClient()

  const exportMutation = useMutation({
    mutationFn: () => reportsApi.export(report.id),
    onSuccess: (res) => {
      setExported({ pdfPath: res.pdf_path, docxPath: res.docx_path })
      qc.invalidateQueries({ queryKey: ["reports", "recent"] })
    },
  })

  const compliancePassed = report.compliance_result?.pass === true

  return (
    <div className="space-y-5 max-w-lg">
      {!compliancePassed && (
        <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          Export is blocked — compliance check has not passed. Go back and resolve the
          flagged phrases.
        </div>
      )}

      <div className="rounded-lg border border-slate-200 p-5 space-y-4 bg-white">
        <h3 className="text-sm font-semibold text-slate-800">Export Report</h3>

        {/* PDF + DOCX */}
        <div className="flex gap-3">
          {exported ? (
            <>
              <a
                href={`data:application/octet-stream;base64,`}
                download={`report_${report.id}.pdf`}
                title={exported.pdfPath}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-md"
              >
                ↓ PDF
              </a>
              <a
                href={`data:application/octet-stream;base64,`}
                download={`report_${report.id}.docx`}
                title={exported.docxPath}
                className="flex items-center gap-2 border border-blue-600 text-blue-700 hover:bg-blue-50 text-sm px-4 py-2 rounded-md"
              >
                ↓ DOCX
              </a>
            </>
          ) : (
            <button
              onClick={() => exportMutation.mutate()}
              disabled={!compliancePassed || exportMutation.isPending}
              title={
                !compliancePassed
                  ? "Compliance must pass before exporting"
                  : "Generate PDF and DOCX files"
              }
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-md disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {exportMutation.isPending ? "Generating files…" : "Generate PDF + DOCX"}
            </button>
          )}
        </div>

        {exported && (
          <div className="text-xs text-slate-500 space-y-0.5">
            <div>PDF: <span className="font-mono">{exported.pdfPath}</span></div>
            <div>DOCX: <span className="font-mono">{exported.docxPath}</span></div>
          </div>
        )}

        {exportMutation.isError && (
          <div className="text-xs text-red-600">
            {String(exportMutation.error)}
          </div>
        )}

        {/* Presentation mode */}
        <div className="border-t border-slate-100 pt-3">
          <button
            onClick={() => setFullscreen(true)}
            className="text-sm text-slate-600 hover:text-blue-700 flex items-center gap-1.5"
          >
            <span>⛶</span> Presentation Mode (fullscreen preview)
          </button>
        </div>

        {/* Share via email (no-op) */}
        <div>
          <button
            disabled
            title="Share via email — coming soon"
            className="text-sm text-slate-400 flex items-center gap-1.5 cursor-not-allowed"
          >
            <span>✉</span> Share via Email
            <span className="text-xs bg-slate-100 px-1 rounded">coming soon</span>
          </button>
        </div>
      </div>

      <button
        onClick={onBack}
        className="border border-slate-300 text-slate-700 text-sm px-4 py-2 rounded-md hover:bg-slate-50"
      >
        ← Back to Preview
      </button>

      {/* Fullscreen presentation overlay */}
      {fullscreen && (
        <div className="fixed inset-0 z-50 bg-white overflow-auto p-8">
          <button
            onClick={() => setFullscreen(false)}
            className="fixed top-4 right-4 bg-slate-800 text-white text-xs px-3 py-1.5 rounded-md hover:bg-slate-700"
          >
            ✕ Exit Presentation
          </button>
          <div className="max-w-4xl mx-auto">
            <div className="bg-blue-700 text-white px-8 py-6 rounded-t-xl">
              <h1 className="text-2xl font-bold">{report.title}</h1>
              <p className="text-blue-200 mt-1 text-sm">
                {report.category} · {report.snapshot_date}
              </p>
            </div>
            <div className="border border-t-0 border-slate-200 rounded-b-xl px-8 py-6 space-y-8">
              {report.fund_narratives.length > 0 && (
                <div>
                  <h2 className="text-lg font-semibold mb-4">
                    Composite Scores — Top Ranked Funds
                  </h2>
                  <div className="h-56">
                    <ScoreChart funds={report.fund_narratives} />
                  </div>
                </div>
              )}
              {report.fund_narratives.length > 0 && (
                <div>
                  <h2 className="text-lg font-semibold mb-3">
                    Top Ranked Research Candidates
                  </h2>
                  <FundTable funds={report.fund_narratives} />
                </div>
              )}
              {report.exec_summary && (
                <div>
                  <h2 className="text-lg font-semibold mb-3">Executive Summary</h2>
                  {report.exec_summary.split("\n\n").map((p, i) => (
                    <p key={i} className="text-sm text-slate-700 mb-3 leading-relaxed">
                      {p}
                    </p>
                  ))}
                </div>
              )}
              {report.key_insights.length > 0 && (
                <div>
                  <h2 className="text-lg font-semibold mb-3">Key Insights</h2>
                  <KeyInsightsCards insights={report.key_insights} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const [step, setStep] = useState<0 | 1 | 2>(0)
  const [report, setReport] = useState<Report | null>(null)

  const handleGenerated = (r: Report) => {
    setReport(r)
    setStep(1)
  }

  const handleRecentSelect = (r: Report) => {
    setReport(r)
    setStep(1)
  }

  return (
    <div className="space-y-2">
      <div>
        <h1 className="text-lg font-semibold">Reports Builder</h1>
        <p className="text-sm text-slate-500">
          Generate compliance-checked research reports from live ranking data. Language
          rule: ranked funds and structural improvements only — never
          recommendations or buy/sell guidance.
        </p>
      </div>

      <div className="mt-4">
        <StepBar step={step} />

        {step === 0 && <ComposeStep onGenerate={handleGenerated} />}

        {step === 1 && report && (
          <PreviewStep
            report={report}
            onChange={setReport}
            onNext={() => setStep(2)}
            onBack={() => setStep(0)}
          />
        )}

        {step === 2 && report && (
          <ExportStep report={report} onBack={() => setStep(1)} />
        )}
      </div>

      <RecentStrip onSelect={handleRecentSelect} />
    </div>
  )
}
