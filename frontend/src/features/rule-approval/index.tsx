import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  CheckCircle2, XCircle, MessageSquare, RotateCcw,
  Clock, AlertCircle, Loader2, ChevronRight, Shield,
  ArrowUpRight, ArrowDownRight, Minus,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  rulesApi,
  type PendingRuleVersion,
  type RuleVersionSummary,
  type RuleVersionDetail,
  type AuditHistoryEvent,
  type DiffRow,
} from "@/lib/api"

// ── Status helpers ────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  active:             "bg-green-100 text-green-800 border-green-200",
  pending_review:     "bg-amber-50  text-amber-700  border-amber-200",
  superseded:         "bg-gray-100  text-gray-500   border-gray-200",
  rejected:           "bg-red-50    text-red-600    border-red-200",
  changes_requested:  "bg-blue-50   text-blue-700   border-blue-200",
}

const STATUS_LABEL: Record<string, string> = {
  active:             "Current Default",
  pending_review:     "Pending Review",
  superseded:         "Superseded",
  rejected:           "Rejected",
  changes_requested:  "Changes Requested",
}

const ACTION_ICONS: Record<string, string> = {
  approved:           "✅",
  rejected:           "❌",
  changes_requested:  "🔄",
  reverted:           "↩️",
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn(
      "text-[10px] font-semibold px-2 py-0.5 rounded-full border uppercase tracking-wide",
      STATUS_STYLES[status] ?? "bg-gray-50 text-gray-500 border-gray-200",
    )}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

// ── Live diff table ───────────────────────────────────────────────────────────

function DiffTable({ diff }: { diff: DiffRow[] }) {
  const visible = diff.filter(r => r.change_type !== "unchanged")
  const unchanged = diff.filter(r => r.change_type === "unchanged")

  const renderWeight = (w: number | null) =>
    w !== null ? `${(w * 100).toFixed(1)}%` : "—"

  const renderDelta = (row: DiffRow) => {
    if (row.change_type === "added")   return <span className="text-green-600 text-xs font-semibold">+ Added</span>
    if (row.change_type === "removed") return <span className="text-red-500   text-xs font-semibold">− Removed</span>
    if (row.delta == null) return null
    const pct = (row.delta * 100).toFixed(1)
    if (row.delta > 0) return <span className="flex items-center gap-0.5 text-green-600 text-xs font-semibold"><ArrowUpRight className="h-3 w-3"/>+{pct}%</span>
    if (row.delta < 0) return <span className="flex items-center gap-0.5 text-red-500   text-xs font-semibold"><ArrowDownRight className="h-3 w-3"/>{pct}%</span>
    return <span className="flex items-center gap-0.5 text-gray-400 text-xs"><Minus className="h-3 w-3"/>0%</span>
  }

  return (
    <div className="text-xs">
      <table className="w-full border-separate border-spacing-0">
        <thead>
          <tr className="text-[10px] text-gray-400 uppercase">
            <th className="text-left pb-1.5 font-medium">Metric</th>
            <th className="text-right pb-1.5 font-medium">Current</th>
            <th className="text-right pb-1.5 font-medium">Proposed</th>
            <th className="text-right pb-1.5 font-medium">Change</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {visible.map(row => (
            <tr
              key={row.metric_column}
              className={cn(
                "py-1",
                row.change_type === "added"   && "bg-green-50",
                row.change_type === "removed" && "bg-red-50",
                row.change_type === "changed" && "bg-blue-50",
              )}
            >
              <td className="py-1.5 pr-2 font-medium text-gray-700">{row.component_name}</td>
              <td className="py-1.5 text-right text-gray-500">{renderWeight(row.current_weight)}</td>
              <td className="py-1.5 text-right font-semibold text-gray-800">{renderWeight(row.proposed_weight)}</td>
              <td className="py-1.5 text-right">{renderDelta(row)}</td>
            </tr>
          ))}
          {unchanged.map(row => (
            <tr key={row.metric_column} className="opacity-40">
              <td className="py-1.5 pr-2 text-gray-600">{row.component_name}</td>
              <td className="py-1.5 text-right text-gray-500">{renderWeight(row.current_weight)}</td>
              <td className="py-1.5 text-right text-gray-500">{renderWeight(row.proposed_weight)}</td>
              <td className="py-1.5 text-right"><Minus className="h-3 w-3 text-gray-300 ml-auto"/></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Approver form ─────────────────────────────────────────────────────────────

interface ActionFormProps {
  pending: PendingRuleVersion
  onDone: () => void
}

function ActionForm({ pending, onDone }: ActionFormProps) {
  const qc = useQueryClient()
  const [approverName, setApproverName] = useState("")
  const [comment, setComment] = useState("")

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["rules", "pending"] })
    qc.invalidateQueries({ queryKey: ["rules", "allVersions"] })
    qc.invalidateQueries({ queryKey: ["audit", "history"] })
    onDone()
  }

  const approveMut = useMutation({
    mutationFn: () => rulesApi.approve(pending.rule_version_id, approverName, comment || undefined),
    onSuccess: invalidate,
  })
  const rejectMut = useMutation({
    mutationFn: () => rulesApi.reject(pending.rule_version_id, approverName, comment),
    onSuccess: invalidate,
  })
  const changeMut = useMutation({
    mutationFn: () => rulesApi.requestChanges(pending.rule_version_id, approverName, comment),
    onSuccess: invalidate,
  })

  const busy = approveMut.isPending || rejectMut.isPending || changeMut.isPending
  const nameOk = approverName.trim().length > 0
  const commentOk = comment.trim().length > 0
  const error = approveMut.error || rejectMut.error || changeMut.error

  return (
    <div className="space-y-3">
      <div>
        <label className="text-[11px] font-semibold text-gray-600 block mb-1">
          Approver Name <span className="text-red-400">*</span>
        </label>
        <input
          value={approverName}
          onChange={e => setApproverName(e.target.value)}
          placeholder="Your name — stored permanently in audit log"
          className="w-full text-xs border border-gray-200 rounded-lg px-2.5 py-2 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>
      <div>
        <label className="text-[11px] font-semibold text-gray-600 block mb-1">
          Comment <span className="text-gray-400">(required for reject / request-changes)</span>
        </label>
        <textarea
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="Governance rationale or review note…"
          rows={3}
          className="w-full text-xs border border-gray-200 rounded-lg px-2.5 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>

      {error && (
        <p className="text-xs text-red-500 border border-red-100 rounded-lg px-2 py-1 bg-red-50">
          {String((error as {body?: {detail?: string}}).body?.detail ?? "Action failed")}
        </p>
      )}

      <div className="flex flex-col gap-2">
        <button
          disabled={!nameOk || busy}
          onClick={() => approveMut.mutate()}
          className={cn(
            "w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-colors",
            nameOk ? "bg-green-600 text-white hover:bg-green-700" : "bg-gray-100 text-gray-400 cursor-not-allowed",
          )}
        >
          {approveMut.isPending ? <Loader2 className="h-4 w-4 animate-spin"/> : <CheckCircle2 className="h-4 w-4"/>}
          Approve as New Default
        </button>
        <button
          disabled={!nameOk || !commentOk || busy}
          onClick={() => changeMut.mutate()}
          className={cn(
            "w-full flex items-center justify-center gap-2 py-2 rounded-xl text-sm font-medium transition-colors border",
            nameOk && commentOk ? "border-blue-200 text-blue-700 hover:bg-blue-50" : "border-gray-200 text-gray-400 cursor-not-allowed",
          )}
        >
          {changeMut.isPending ? <Loader2 className="h-4 w-4 animate-spin"/> : <MessageSquare className="h-4 w-4"/>}
          Request Changes
        </button>
        <button
          disabled={!nameOk || !commentOk || busy}
          onClick={() => rejectMut.mutate()}
          className={cn(
            "w-full flex items-center justify-center gap-2 py-2 rounded-xl text-sm font-medium transition-colors border",
            nameOk && commentOk ? "border-red-200 text-red-600 hover:bg-red-50" : "border-gray-200 text-gray-400 cursor-not-allowed",
          )}
        >
          {rejectMut.isPending ? <Loader2 className="h-4 w-4 animate-spin"/> : <XCircle className="h-4 w-4"/>}
          Reject
        </button>
      </div>
    </div>
  )
}

// ── Version detail panel ──────────────────────────────────────────────────────

interface VersionDetailPanelProps {
  version: RuleVersionSummary
  isActive: boolean
}

function VersionDetailPanel({ version, isActive }: VersionDetailPanelProps) {
  const qc = useQueryClient()
  const [approverName, setApproverName] = useState("")
  const [comment, setComment] = useState("")
  const [reverting, setReverting] = useState(false)

  const detailQ = useQuery({
    queryKey: ["rules", "version", version.id],
    queryFn: () => rulesApi.getVersionDetail(version.id),
  })

  const revertMut = useMutation({
    mutationFn: () => rulesApi.revert(version.id, approverName, comment || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules", "allVersions"] })
      qc.invalidateQueries({ queryKey: ["audit", "history"] })
      qc.invalidateQueries({ queryKey: ["rules", "version", version.id] })
      setReverting(false)
      setApproverName("")
      setComment("")
    },
  })

  const detail: RuleVersionDetail | undefined = detailQ.data

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="font-semibold text-gray-800 text-sm">{version.version_label}</div>
          <div className="text-[10px] text-gray-400 mt-0.5">
            {version.submitted_at ? new Date(version.submitted_at).toLocaleString("en-IN", {
              day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
            }) : ""}
            {version.submitted_by ? ` — ${version.submitted_by}` : ""}
          </div>
        </div>
        <StatusBadge status={version.status} />
      </div>

      {version.rationale && (
        <div className="text-[11px] text-gray-600 bg-gray-50 rounded-lg p-2 italic">
          "{version.rationale}"
        </div>
      )}

      {detailQ.isLoading && (
        <div className="flex items-center gap-2 text-gray-400 text-xs py-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin"/> Loading components…
        </div>
      )}

      {detail && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Components</div>
          {detail.components.map(c => (
            <div key={c.metric_column} className="flex justify-between items-center text-xs py-0.5">
              <span className="text-gray-700">{c.component_name}</span>
              <div className="flex items-center gap-3 text-gray-500">
                <span className="text-[10px]">{c.direction === "lower_better" ? "↓ lower" : "↑ higher"}</span>
                <span className="font-semibold text-gray-800 font-mono">{c.weight_pct.toFixed(1)}%</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {!isActive && (
        <div className="pt-2 border-t border-gray-100">
          {!reverting ? (
            <button
              onClick={() => setReverting(true)}
              className="w-full flex items-center justify-center gap-2 py-2 rounded-xl text-xs font-medium border border-amber-200 text-amber-700 hover:bg-amber-50 transition-colors"
            >
              <RotateCcw className="h-3.5 w-3.5"/> Revert to this version
            </button>
          ) : (
            <div className="space-y-2">
              <div className="text-[10px] font-semibold text-amber-700 uppercase">Confirm Revert</div>
              <input
                value={approverName}
                onChange={e => setApproverName(e.target.value)}
                placeholder="Approver name *"
                className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-amber-400"
              />
              <textarea
                value={comment}
                onChange={e => setComment(e.target.value)}
                placeholder="Reason for revert (optional)"
                rows={2}
                className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 resize-none focus:outline-none focus:ring-1 focus:ring-amber-400"
              />
              {revertMut.error && (
                <p className="text-[10px] text-red-500">
                  {String((revertMut.error as {body?: {detail?: string}}).body?.detail ?? "Revert failed")}
                </p>
              )}
              <div className="flex gap-2">
                <button
                  disabled={!approverName.trim() || revertMut.isPending}
                  onClick={() => revertMut.mutate()}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-xs font-semibold transition-colors",
                    approverName.trim() ? "bg-amber-600 text-white hover:bg-amber-700" : "bg-gray-100 text-gray-400 cursor-not-allowed",
                  )}
                >
                  {revertMut.isPending ? <Loader2 className="h-3 w-3 animate-spin"/> : <RotateCcw className="h-3 w-3"/>}
                  Confirm
                </button>
                <button
                  onClick={() => { setReverting(false); setApproverName(""); setComment("") }}
                  className="flex-1 py-1.5 rounded-lg text-xs border border-gray-200 text-gray-600 hover:bg-gray-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Audit log strip ───────────────────────────────────────────────────────────

function AuditLogStrip({ events }: { events: AuditHistoryEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="text-xs text-gray-400 py-3 text-center">
        No governance actions recorded yet.
      </p>
    )
  }
  return (
    <ul className="space-y-2 text-xs">
      {events.map(e => (
        <li key={e.id} className="flex items-start gap-2">
          <span className="text-base leading-none mt-0.5">{ACTION_ICONS[e.action] ?? "📋"}</span>
          <div className="flex-1 min-w-0">
            <span className="font-medium text-gray-700">{e.actor}</span>
            <span className="text-gray-500"> {e.action.replace(/_/g, " ")}</span>
            {e.version_label && (
              <span className="text-gray-400"> — {e.version_label}</span>
            )}
            {e.comment && (
              <div className="text-[10px] text-gray-400 truncate">{e.comment}</div>
            )}
          </div>
          <span className="text-[10px] text-gray-400 flex-shrink-0">
            {e.created_at ? new Date(e.created_at).toLocaleString("en-IN", {
              day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
            }) : ""}
          </span>
        </li>
      ))}
    </ul>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function RuleApprovalPage() {
  const [selectedPendingIdx, setSelectedPendingIdx] = useState(0)
  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null)

  const pendingQ   = useQuery({ queryKey: ["rules", "pending"],     queryFn: rulesApi.getPending,      staleTime: 30_000 })
  const versionsQ  = useQuery({ queryKey: ["rules", "allVersions"], queryFn: rulesApi.getAllVersions,  staleTime: 30_000 })
  const auditQ     = useQuery({ queryKey: ["audit", "history"],     queryFn: () => rulesApi.getAuditHistory(20), staleTime: 30_000 })

  const pending  = pendingQ.data  ?? []
  const versions = versionsQ.data ?? []
  const auditEvents: AuditHistoryEvent[] = auditQ.data?.events ?? []

  const currentPending = pending[selectedPendingIdx] ?? null
  const activeVersion  = versions.find(v => v.is_current_default)
  const selectedVersion = selectedVersionId ? versions.find(v => v.id === selectedVersionId) : null

  return (
    <div className="p-6 space-y-5 max-w-screen-xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Rule Approval &amp; Version History</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Review pending submissions, approve new default rules, and revert to earlier versions.
        </p>
        <p className="text-xs text-gray-400 mt-1 border-l-2 border-gray-200 pl-2">
          All rule versions are immutable. Old and new defaults are always stored for audit and
          transparency.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-5">
        {/* ── LEFT: Submitted Sandbox Rule card ── */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-amber-500"/>
            <span className="text-sm font-semibold text-gray-800">Submitted Sandbox Rule</span>
            {pending.length > 0 && (
              <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full font-semibold">
                {pending.length}
              </span>
            )}
          </div>

          {/* Selector when multiple pending */}
          {pending.length > 1 && (
            <div className="flex gap-2 flex-wrap">
              {pending.map((p, i) => (
                <button
                  key={p.rule_version_id}
                  onClick={() => setSelectedPendingIdx(i)}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-lg border transition-colors",
                    i === selectedPendingIdx
                      ? "border-amber-300 bg-amber-50 text-amber-800 font-semibold"
                      : "border-gray-200 text-gray-600 hover:border-gray-300",
                  )}
                >
                  {p.version_label}
                </button>
              ))}
            </div>
          )}

          {pendingQ.isLoading ? (
            <div className="bg-white rounded-xl border border-gray-200 p-8 flex items-center justify-center gap-2 text-gray-400 text-sm">
              <Loader2 className="h-4 w-4 animate-spin"/> Loading…
            </div>
          ) : currentPending ? (
            <div className="bg-white rounded-xl border border-amber-200 p-4 space-y-4">
              {/* Meta */}
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold text-gray-800 text-sm">{currentPending.version_label}</div>
                  <div className="text-[11px] text-gray-400 mt-0.5">
                    Submitted {currentPending.submitted_at
                      ? new Date(currentPending.submitted_at).toLocaleString("en-IN", {
                          day: "2-digit", month: "short", year: "numeric",
                        })
                      : ""}
                    {currentPending.submitted_by ? ` by ${currentPending.submitted_by}` : ""}
                  </div>
                  {currentPending.active_version_label && (
                    <div className="text-[10px] text-gray-400 mt-0.5">
                      Diff vs <span className="font-semibold">{currentPending.active_version_label}</span>
                    </div>
                  )}
                </div>
                <StatusBadge status={currentPending.status} />
              </div>

              {/* Live diff table */}
              <div>
                <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Component Diff (live vs current default)
                </div>
                <DiffTable diff={currentPending.diff} />
              </div>

              {/* Rationale */}
              {currentPending.rationale && (
                <div>
                  <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">
                    Submitted Rationale
                  </div>
                  <p className="text-xs text-gray-600 bg-gray-50 rounded-lg p-2 italic">
                    "{currentPending.rationale}"
                  </p>
                </div>
              )}

              {/* Divider */}
              <div className="border-t border-gray-100 pt-3">
                <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Governance Action
                </div>
                <ActionForm
                  pending={currentPending}
                  onDone={() => setSelectedPendingIdx(0)}
                />
              </div>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 p-10 text-center">
              <Shield className="h-10 w-10 text-gray-200 mx-auto mb-3"/>
              <p className="text-sm font-medium text-gray-500">No pending submissions</p>
              <p className="text-xs text-gray-400 mt-1">
                Submit a sandbox rule from the Rule Playground to see it here.
              </p>
            </div>
          )}
        </div>

        {/* ── RIGHT: Version Timeline + Detail ── */}
        <div className="space-y-4">
          {/* Timeline table */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="h-4 w-4 text-blue-500"/>
              <span className="text-sm font-semibold text-gray-800">Version Timeline</span>
            </div>

            {versionsQ.isLoading ? (
              <div className="flex items-center gap-2 text-gray-400 text-sm py-4">
                <Loader2 className="h-4 w-4 animate-spin"/> Loading…
              </div>
            ) : versions.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-4">No versions found.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[10px] text-gray-400 uppercase border-b border-gray-100">
                    <th className="text-left pb-2 font-medium">Version</th>
                    <th className="text-left pb-2 font-medium">Status</th>
                    <th className="text-left pb-2 font-medium">Published</th>
                    <th className="text-right pb-2 font-medium"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {versions.map(v => (
                    <tr
                      key={v.id}
                      className={cn(
                        "cursor-pointer hover:bg-gray-50 transition-colors",
                        selectedVersionId === v.id && "bg-blue-50",
                      )}
                      onClick={() => setSelectedVersionId(selectedVersionId === v.id ? null : v.id)}
                    >
                      <td className="py-2 pr-2">
                        <span className="font-semibold text-gray-800">{v.version_label}</span>
                      </td>
                      <td className="py-2 pr-2">
                        <StatusBadge status={v.status}/>
                      </td>
                      <td className="py-2 pr-2 text-gray-400">
                        {v.published_on
                          ? new Date(v.published_on).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
                          : "—"}
                        {v.published_by && <div className="text-[10px]">{v.published_by}</div>}
                      </td>
                      <td className="py-2 text-right">
                        <ChevronRight className={cn(
                          "h-3.5 w-3.5 text-gray-400 inline transition-transform",
                          selectedVersionId === v.id && "rotate-90",
                        )}/>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Selected version detail */}
          {selectedVersion && (
            <VersionDetailPanel
              version={selectedVersion}
              isActive={selectedVersion.is_current_default}
            />
          )}

          {/* Fallback: show current default if nothing selected */}
          {!selectedVersion && activeVersion && (
            <div className="bg-green-50 border border-green-100 rounded-xl p-3">
              <div className="flex items-center gap-2 text-xs text-green-700">
                <CheckCircle2 className="h-3.5 w-3.5"/>
                <span className="font-semibold">Current default:</span>
                <span>{activeVersion.version_label}</span>
                {activeVersion.published_by && (
                  <span className="text-green-600">— approved by {activeVersion.published_by}</span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Bottom: Audit Log strip ── */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Shield className="h-4 w-4 text-gray-400"/>
          <span className="text-sm font-semibold text-gray-700">Audit Log</span>
          <span className="text-xs text-gray-400">(most recent actions first)</span>
        </div>
        {auditQ.isLoading ? (
          <div className="flex items-center gap-2 text-gray-400 text-xs py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin"/> Loading…
          </div>
        ) : (
          <AuditLogStrip events={auditEvents}/>
        )}
      </div>
    </div>
  )
}
