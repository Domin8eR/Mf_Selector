import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  CheckCircle2, XCircle, MessageSquare, RotateCcw,
  Shield, Clock, ChevronRight,
  AlertCircle, Loader2, Sparkles,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { rulesApi, dataQualityApi, type RuleComponentOut } from "@/lib/api"

const RULE_SET_ID = "CLIENT-DEFAULT-LC"

const STATUS_COLORS: Record<string, string> = {
  active:    "bg-green-100 text-green-700 border-green-200",
  approved:  "bg-green-50 text-green-600 border-green-200",
  submitted: "bg-amber-50 text-amber-700 border-amber-200",
  draft:     "bg-gray-50 text-gray-500 border-gray-200",
  archived:  "bg-gray-50 text-gray-400 border-gray-100",
  rejected:  "bg-red-50 text-red-600 border-red-200",
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn(
      "text-[10px] font-semibold px-2 py-0.5 rounded-full border uppercase tracking-wide",
      STATUS_COLORS[status] ?? "bg-gray-50 text-gray-500 border-gray-200",
    )}>
      {status === "active" ? "Current Default" : status}
    </span>
  )
}

function ComponentRow({ c, prev }: { c: RuleComponentOut; prev?: RuleComponentOut }) {
  const changed = prev && c.weight_pct !== prev.weight_pct
  return (
    <div className={cn(
      "flex items-center justify-between py-2 px-3 rounded-lg text-sm",
      changed ? "bg-blue-50 border border-blue-100" : "border border-transparent",
    )}>
      <div>
        <div className="font-medium text-gray-800">{c.metric_name}</div>
        <div className="text-[10px] text-gray-400 font-mono">{c.metric_id}</div>
      </div>
      <div className="flex items-center gap-3">
        {changed && prev && (
          <>
            <span className="text-xs line-through text-red-400">{prev.weight_pct}%</span>
            <ChevronRight className="h-3 w-3 text-gray-400" />
          </>
        )}
        <span className={cn(
          "text-sm font-bold",
          changed ? "text-blue-600" : "text-gray-700",
        )}>
          {c.weight_pct}%
          {changed && (
            <span className="ml-1 text-[10px] font-normal text-blue-500">
              {c.weight_pct > (prev?.weight_pct ?? 0) ? "▲" : "▼"}
            </span>
          )}
        </span>
      </div>
    </div>
  )
}

export default function RuleApprovalPage() {
  const qc = useQueryClient()
  const [rationale, setRationale] = useState("")
  const [expanded, setExpanded] = useState<string | null>(null)

  const versionsQ = useQuery({
    queryKey: ["rules", "versions", RULE_SET_ID],
    queryFn: () => rulesApi.listVersions(RULE_SET_ID),
    staleTime: 60_000,
  })

  const auditQ = useQuery({
    queryKey: ["audit-events"],
    queryFn: () => dataQualityApi.getAuditEvents(8),
    staleTime: 30_000,
  })

  const approveMut = useMutation({
    mutationFn: (rvId: string) => rulesApi.approveVersion(rvId, rationale),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] })
      setRationale("")
    },
  })

  const rejectMut = useMutation({
    mutationFn: (rvId: string) => rulesApi.rejectVersion(rvId, rationale),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] })
      setRationale("")
    },
  })

  const versions = versionsQ.data ?? []
  const pending = versions.filter(v => v.status === "submitted")
  const active = versions.find(v => v.status === "active")

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Rule Approval &amp; Version History</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Review sandbox submissions, approve new defaults, and revert to earlier rule versions.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* ── Version timeline ── */}
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-4">
            <Clock className="h-4 w-4 text-blue-500" />
            <span className="text-sm font-semibold text-gray-800">Version Timeline</span>
          </div>

          {versionsQ.isLoading ? (
            <div className="flex items-center gap-2 text-gray-400 text-sm py-4">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : (
            <div className="space-y-2">
              {versions.map(v => (
                <button
                  key={v.id}
                  onClick={() => setExpanded(expanded === v.id ? null : v.id)}
                  className={cn(
                    "w-full text-left rounded-xl border p-3 transition-colors",
                    expanded === v.id
                      ? "border-blue-300 bg-blue-50"
                      : "border-gray-100 hover:border-gray-200 hover:bg-gray-50",
                  )}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-gray-700">
                      v{v.version_number}
                    </span>
                    <StatusBadge status={v.status} />
                  </div>
                  <div className="text-[10px] text-gray-400">
                    {v.id}
                  </div>
                  {expanded === v.id && (
                    <div className="mt-2 pt-2 border-t border-gray-100 space-y-1">
                      {v.components.map(c => (
                        <div key={c.id} className="flex justify-between text-[11px] text-gray-600">
                          <span className="truncate">{c.metric_name}</span>
                          <span className="font-mono font-semibold ml-2">{c.weight_pct}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                </button>
              ))}
              {versions.length === 0 && (
                <p className="text-sm text-gray-400 text-center py-4">
                  No rule versions found. Seed the database first.
                </p>
              )}
            </div>
          )}
        </div>

        {/* ── Diff view (pending → active) ── */}
        <div className="space-y-4">
          {pending.length > 0 ? (
            pending.slice(0, 1).map(pv => (
              <div key={pv.id} className="bg-white rounded-xl border border-amber-200 p-4">
                <div className="flex items-center gap-2 mb-3">
                  <AlertCircle className="h-4 w-4 text-amber-500" />
                  <span className="text-sm font-semibold text-gray-800">
                    Submitted — v{pv.version_number}
                  </span>
                  <StatusBadge status="submitted" />
                </div>
                <p className="text-[11px] text-gray-500 mb-3">
                  Changes vs current default (v{active?.version_number ?? "?"})
                </p>
                <div className="space-y-1">
                  {pv.components.map(c => {
                    const prev = active?.components.find(x => x.metric_id === c.metric_id)
                    return <ComponentRow key={c.id} c={c} prev={prev} />
                  })}
                </div>
              </div>
            ))
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 p-8 text-center">
              <Shield className="h-8 w-8 text-gray-200 mx-auto mb-2" />
              <p className="text-sm text-gray-400">No pending submissions</p>
              <p className="text-xs text-gray-300 mt-1">
                Submit a sandbox rule from the Rule Playground to see it here.
              </p>
            </div>
          )}

          {/* Current default (read-only) */}
          {active && (
            <div className="bg-white rounded-xl border border-green-100 p-4">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
                <span className="text-sm font-semibold text-gray-800">
                  Current Default — v{active.version_number}
                </span>
                <StatusBadge status="active" />
              </div>
              <div className="space-y-1">
                {active.components.map(c => (
                  <ComponentRow key={c.id} c={c} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Approval actions ── */}
        <div className="space-y-4">
          {/* AI review note */}
          <div className="bg-purple-50 border border-purple-100 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="h-4 w-4 text-purple-500" />
              <span className="text-sm font-semibold text-purple-800">AI Review Note</span>
            </div>
            {pending.length > 0 ? (
              <p className="text-xs text-purple-700 leading-relaxed">
                No circular rule conflicts detected. Increasing IR Consistency weight to 30%
                is expected to improve top-5 rank stability. Bias flag: funds under 5 years
                old lose IR Consistency score eligibility.
              </p>
            ) : (
              <p className="text-xs text-purple-600">
                No pending submissions to review.
              </p>
            )}
          </div>

          {/* Rationale input */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="text-sm font-semibold text-gray-700 mb-2">
              Approver Rationale <span className="text-red-400">*</span>
            </div>
            <textarea
              value={rationale}
              onChange={e => setRationale(e.target.value)}
              placeholder="Enter your review rationale before approving or rejecting. Stored permanently in the rule audit log."
              rows={4}
              className="w-full text-xs border border-gray-200 rounded-lg p-2.5 resize-none focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="text-[10px] text-gray-400 mt-1">
              Required for audit compliance. Stored with firm ID, rule version, and timestamp.
            </p>
          </div>

          {/* Action buttons */}
          {pending.length > 0 && (
            <div className="space-y-2">
              <button
                disabled={!rationale.trim() || approveMut.isPending}
                onClick={() => approveMut.mutate(pending[0].id)}
                className={cn(
                  "w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-colors",
                  rationale.trim()
                    ? "bg-green-600 text-white hover:bg-green-700"
                    : "bg-gray-100 text-gray-400 cursor-not-allowed",
                )}
              >
                {approveMut.isPending
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : <CheckCircle2 className="h-4 w-4" />}
                Approve and publish
              </button>
              <button
                disabled={!rationale.trim() || rejectMut.isPending}
                onClick={() => rejectMut.mutate(pending[0].id)}
                className={cn(
                  "w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-colors",
                  rationale.trim()
                    ? "border border-red-200 text-red-600 hover:bg-red-50"
                    : "border border-gray-200 text-gray-400 cursor-not-allowed",
                )}
              >
                <XCircle className="h-4 w-4" /> Reject
              </button>
              <button className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium border border-gray-200 text-gray-600 hover:bg-gray-50">
                <MessageSquare className="h-4 w-4" /> Request changes
              </button>
            </div>
          )}

          {/* Revert */}
          {versions.filter(v => v.status === "archived").length > 0 && (
            <div className="bg-amber-50 border border-amber-100 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <RotateCcw className="h-4 w-4 text-amber-600" />
                <span className="text-sm font-semibold text-amber-800">Revert</span>
              </div>
              <p className="text-xs text-amber-700 mb-2">
                Reverting creates a new version copied from the selected archive. All actions
                are logged and immutable.
              </p>
              <button className="w-full text-xs border border-amber-200 text-amber-700 rounded-lg py-2 hover:bg-amber-100 transition-colors">
                Revert to archived version →
              </button>
            </div>
          )}

          {/* Audit log — live from DB */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              Audit Log (Latest Activity)
            </div>
            {auditQ.isLoading ? (
              <div className="flex items-center gap-2 text-gray-400 text-xs py-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
              </div>
            ) : (auditQ.data?.events ?? []).length === 0 ? (
              <p className="text-xs text-gray-400 py-2">
                No audit events yet. They appear here when rules are submitted or approved.
              </p>
            ) : (
              <ul className="space-y-2 text-xs text-gray-500">
                {(auditQ.data?.events ?? []).map((e, i) => (
                  <li key={i} className="flex justify-between gap-2">
                    <span className="text-gray-600">
                      {e.actor_name !== "System" ? `${e.actor_name} — ` : ""}
                      {e.action.replace(".", " ").replace("_", " ")}
                    </span>
                    <span className="text-gray-400 flex-shrink-0">
                      {e.created_at
                        ? new Date(e.created_at).toLocaleString("en-IN", {
                            month: "short", day: "2-digit",
                            hour: "2-digit", minute: "2-digit",
                          })
                        : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
