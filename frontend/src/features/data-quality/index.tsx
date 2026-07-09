import { useQuery } from "@tanstack/react-query"
import {
  CheckCircle2, AlertCircle, XCircle, RefreshCw,
  Database, Clock, Loader2,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { dataQualityApi, type BenchmarkCoverageRow } from "@/lib/api"

function KpiCard({
  label, pct, sublabel,
}: { label: string; pct: number; sublabel?: string }) {
  const ok = pct >= 99
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
      <div className="flex items-center justify-center mb-2">
        {ok
          ? <CheckCircle2 className="h-6 w-6 text-green-500" />
          : <AlertCircle className="h-6 w-6 text-amber-500" />}
      </div>
      <div className={cn(
        "text-2xl font-bold mb-0.5",
        ok ? "text-green-600" : "text-amber-600",
      )}>
        {pct.toFixed(1)}%
      </div>
      <div className="text-xs text-gray-600 font-medium">{label}</div>
      {sublabel && <div className="text-[10px] text-gray-400 mt-0.5">{sublabel}</div>}
    </div>
  )
}

function SeverityDot({ s }: { s: string }) {
  const cls = s === "blocking" ? "bg-red-500" : s === "warning" ? "bg-amber-400" : "bg-blue-400"
  return <span className={cn("h-2 w-2 rounded-full flex-shrink-0", cls)} />
}

function SeverityBadge({ s }: { s: string }) {
  const cls =
    s === "blocking" ? "bg-red-50 text-red-700 border-red-200"
    : s === "warning" ? "bg-amber-50 text-amber-700 border-amber-200"
    : "bg-blue-50 text-blue-600 border-blue-200"
  return (
    <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full border uppercase", cls)}>
      {s}
    </span>
  )
}

export default function DataQualityPage() {
  const summaryQ = useQuery({
    queryKey: ["data-quality", "summary"],
    queryFn: dataQualityApi.getSummary,
    refetchInterval: 60_000,
  })

  const exceptionsQ = useQuery({
    queryKey: ["data-quality", "exceptions"],
    queryFn: () => dataQualityApi.getExceptions(),
    refetchInterval: 60_000,
  })

  const coverageQ = useQuery({
    queryKey: ["data-quality", "benchmark-coverage"],
    queryFn: dataQualityApi.getBenchmarkCoverage,
    staleTime: 5 * 60_000,
  })

  const ingestionQ = useQuery({
    queryKey: ["data-quality", "ingestion"],
    queryFn: dataQualityApi.getIngestionStatus,
  })

  const summary = summaryQ.data
  const exceptions = exceptionsQ.data?.items ?? []
  const ingestion = ingestionQ.data?.runs ?? []

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Data Quality &amp; Operations</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Monitor daily ingestion, fix mappings, review exceptions and trigger recalculation.
          </p>
        </div>
        <button className="flex items-center gap-1.5 text-sm border border-gray-200 rounded-xl px-3 py-2 hover:bg-gray-50">
          <RefreshCw className="h-3.5 w-3.5" /> Rerun all rankings
        </button>
      </div>

      {/* KPI cards */}
      {summaryQ.isLoading ? (
        <div className="flex items-center gap-2 text-gray-400 py-4">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-sm">Loading data quality status…</span>
        </div>
      ) : summary ? (
        <div className="grid grid-cols-4 gap-4">
          {Object.entries(summary.domains).map(([key, d]) => (
            <KpiCard
              key={key}
              label={(d as { label: string; pct: number }).label}
              pct={(d as { pct: number }).pct}
              sublabel="On time"
            />
          ))}
        </div>
      ) : null}

      {summary && (
        <p className="text-xs text-gray-400 -mt-2">
          All critical datasets are within acceptable quality thresholds.
          NAV coverage: {summary.nav_coverage_pct.toFixed(1)}%
        </p>
      )}

      <div className="grid grid-cols-2 gap-4">
        {/* Exceptions table */}
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-red-500" />
              <span className="text-sm font-semibold text-gray-800">Data Exceptions</span>
              {summary && summary.blocking_open > 0 && (
                <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold">
                  {summary.blocking_open} blocking
                </span>
              )}
            </div>
            <button className="text-xs text-blue-600 hover:underline">View all</button>
          </div>

          {exceptionsQ.isLoading ? (
            <div className="flex items-center gap-2 text-gray-400 py-4">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm">Loading exceptions…</span>
            </div>
          ) : exceptions.length === 0 ? (
            <div className="text-center py-8">
              <CheckCircle2 className="h-8 w-8 text-green-400 mx-auto mb-2" />
              <p className="text-sm text-gray-500">No open exceptions</p>
              <p className="text-xs text-gray-400 mt-1">All datasets validated successfully.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {exceptions.slice(0, 6).map(e => (
                <div
                  key={e.id}
                  className="flex items-start gap-3 py-2.5 px-3 rounded-lg border border-gray-100 hover:border-gray-200"
                >
                  <SeverityDot s={e.severity} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-gray-800 truncate">
                        {e.scheme_plan_id ?? e.benchmark_id ?? e.domain}
                      </span>
                      <SeverityBadge s={e.severity} />
                    </div>
                    <p className="text-[11px] text-gray-500 mt-0.5 line-clamp-1">{e.message}</p>
                  </div>
                  <button className="text-[11px] text-blue-600 hover:underline flex-shrink-0">
                    Fix →
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right column */}
        <div className="space-y-4">
          {/* Benchmark coverage */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Database className="h-4 w-4 text-blue-500" />
              <span className="text-sm font-semibold text-gray-800">Benchmark Mapping</span>
            </div>
            <div className="space-y-2">
              {coverageQ.isLoading && (
                <div className="flex items-center gap-2 text-gray-400 text-xs py-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
                </div>
              )}
              {(coverageQ.data?.coverage ?? []).length === 0 && !coverageQ.isLoading && (
                <p className="text-xs text-gray-400 py-2">No scheme plans found in DB.</p>
              )}
              {(coverageQ.data?.coverage ?? []).map((r: BenchmarkCoverageRow) => (
                <div key={r.category} className="flex items-center gap-3 text-xs">
                  <span className="w-24 text-gray-600 flex-shrink-0">{r.category}</span>
                  <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        r.pct === 100 ? "bg-green-400" : r.pct >= 90 ? "bg-amber-400" : "bg-red-400",
                      )}
                      style={{ width: `${r.pct}%` }}
                    />
                  </div>
                  <span className={cn(
                    "w-8 text-right font-mono font-semibold",
                    r.pct === 100 ? "text-green-600" : r.pct >= 90 ? "text-amber-600" : "text-red-500",
                  )}>
                    {r.pct}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Ingestion job log */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="h-4 w-4 text-purple-500" />
              <span className="text-sm font-semibold text-gray-800">Ingestion Jobs</span>
            </div>
            {ingestion.length === 0 ? (
              <div className="text-xs text-gray-400 py-2 text-center">
                No ingestion runs yet. Jobs run daily at 09:30 IST.
              </div>
            ) : (
              <div className="space-y-1.5">
                {ingestion.map((r, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      {r.status === "completed"
                        ? <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                        : r.status === "failed"
                          ? <XCircle className="h-3.5 w-3.5 text-red-500" />
                          : <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />}
                      <span className="text-gray-700">{r.source}</span>
                    </div>
                    <span className="text-gray-400">
                      {r.completed_at
                        ? new Date(r.completed_at).toLocaleTimeString("en-IN", {
                            hour: "2-digit", minute: "2-digit",
                          })
                        : "Running…"}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Admin actions */}
            <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-gray-100">
              {[
                "Rerun all rankings",
                "Export fund universe",
                "Category migration",
                "Audit log export",
              ].map(label => (
                <button
                  key={label}
                  className="text-xs border border-gray-200 rounded-lg py-1.5 px-2 text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
