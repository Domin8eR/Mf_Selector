// Approval drawer — folds the decommissioned standalone Rule Approval page
// into Rule Playground as an in-place side panel (same fixed-inset drawer
// pattern as Category Rankings' FundPreviewDrawer). Reuses the presentational
// pieces exported from features/rule-approval/index.tsx rather than
// duplicating them — that file's own page/route is unreferenced, but its
// StatusBadge/DiffTable/ActionForm/VersionDetailPanel/AuditLogStrip remain
// the single source of truth for this UI.
//
// Scope note: the "Pending Review" tab intentionally shows ALL pending
// submissions across every category — /rules/pending has never taken a
// category filter (it's rule-version-level, not category-scoped) — so an
// approver reviewing a colleague's submission from another category always
// sees it here, independent of whatever category happens to be selected in
// the Rule Playground editor behind this drawer.

import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { X, Clock, Shield, CheckCircle2, Loader2, AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { rulesApi, type PendingRuleVersion, type RuleVersionSummary } from "@/lib/api"
import {
  StatusBadge, DiffTable, ActionForm, VersionDetailPanel, AuditLogStrip,
} from "@/features/rule-approval"

export type ApprovalTab = "pending" | "versions" | "audit"

const TAB_LABEL: Record<ApprovalTab, string> = {
  pending: "Pending Review",
  versions: "Version Timeline",
  audit: "Audit Log",
}

// ── Pending Review tab ────────────────────────────────────────────────────────

function PendingReviewTab({
  pending,
  isLoading,
  focusRuleVersionId,
}: {
  pending: PendingRuleVersion[]
  isLoading: boolean
  focusRuleVersionId?: number | null
}) {
  const [selectedId, setSelectedId] = useState<number | null>(focusRuleVersionId ?? null)

  // If the drawer was opened focused on a specific just-submitted version,
  // select it once the real list arrives (covers the case where it opens
  // before the list query has resolved).
  useEffect(() => {
    if (focusRuleVersionId != null) setSelectedId(focusRuleVersionId)
  }, [focusRuleVersionId])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-10 text-gray-400 text-sm gap-2">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading pending submissions…
      </div>
    )
  }

  if (pending.length === 0) {
    return (
      <div className="py-10 text-center">
        <Shield className="h-8 w-8 text-gray-200 mx-auto mb-2" />
        <p className="text-sm font-medium text-gray-500">No pending submissions</p>
        <p className="text-xs text-gray-400 mt-1">
          Submit a sandbox rule from Rule Playground to see it here.
        </p>
      </div>
    )
  }

  const current = pending.find(p => p.rule_version_id === selectedId) ?? pending[0]

  return (
    <div className="space-y-3">
      {/* List of ALL pending submissions across every category */}
      {pending.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {pending.map(p => (
            <button
              key={p.rule_version_id}
              onClick={() => setSelectedId(p.rule_version_id)}
              className={cn(
                "text-xs px-2.5 py-1 rounded-lg border transition-colors",
                (current?.rule_version_id === p.rule_version_id)
                  ? "border-amber-300 bg-amber-50 text-amber-800 font-semibold"
                  : "border-gray-200 text-gray-600 hover:border-gray-300",
              )}
            >
              {p.version_label}
            </button>
          ))}
        </div>
      )}

      {current && (
        <div className="bg-white rounded-xl border border-amber-200 p-4 space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <div className="font-semibold text-gray-800 text-sm">{current.version_label}</div>
              <div className="text-[11px] text-gray-400 mt-0.5">
                Submitted {current.submitted_at
                  ? new Date(current.submitted_at).toLocaleString("en-IN", {
                      day: "2-digit", month: "short", year: "numeric",
                    })
                  : ""}
                {current.submitted_by ? ` by ${current.submitted_by}` : ""}
              </div>
              {current.active_version_label && (
                <div className="text-[10px] text-gray-400 mt-0.5">
                  Diff vs <span className="font-semibold">{current.active_version_label}</span>
                </div>
              )}
            </div>
            <StatusBadge status={current.status} />
          </div>

          <div>
            <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Component Diff (live vs current default)
            </div>
            <DiffTable diff={current.diff} />
          </div>

          {current.rationale && (
            <div>
              <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">
                Submitted Rationale
              </div>
              <p className="text-xs text-gray-600 bg-gray-50 rounded-lg p-2 italic">
                "{current.rationale}"
              </p>
            </div>
          )}

          <div className="border-t border-gray-100 pt-3">
            <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Governance Action
            </div>
            <ActionForm
              pending={current}
              onDone={() => setSelectedId(null)}
            />
          </div>
        </div>
      )}
    </div>
  )
}

// ── Version Timeline tab ───────────────────────────────────────────────────────

function VersionTimelineTab({
  versions,
  isLoading,
}: {
  versions: RuleVersionSummary[]
  isLoading: boolean
}) {
  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null)
  const activeVersion = versions.find(v => v.is_current_default)
  const selectedVersion = selectedVersionId ? versions.find(v => v.id === selectedVersionId) : null

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        {isLoading ? (
          <div className="flex items-center gap-2 text-gray-400 text-sm py-4">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
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
                    <StatusBadge status={v.status} />
                  </td>
                  <td className="py-2 pr-2 text-gray-400">
                    {v.published_on
                      ? new Date(v.published_on).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
                      : "—"}
                    {v.published_by && <div className="text-[10px]">{v.published_by}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selectedVersion && (
        <VersionDetailPanel version={selectedVersion} isActive={selectedVersion.is_current_default} />
      )}

      {!selectedVersion && activeVersion && (
        <div className="bg-green-50 border border-green-100 rounded-xl p-3">
          <div className="flex items-center gap-2 text-xs text-green-700">
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span className="font-semibold">Current default:</span>
            <span>{activeVersion.version_label}</span>
            {activeVersion.published_by && (
              <span className="text-green-600">— approved by {activeVersion.published_by}</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main drawer ────────────────────────────────────────────────────────────────

export default function ApprovalDrawer({
  initialTab = "pending",
  focusRuleVersionId,
  onClose,
}: {
  initialTab?: ApprovalTab
  focusRuleVersionId?: number | null
  onClose: () => void
}) {
  const [activeTab, setActiveTab] = useState<ApprovalTab>(initialTab)

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [onClose])

  // Same query keys the old standalone Rule Approval page used — the
  // persistent Approvals button badge in Rule Playground shares this exact
  // key, so both read/invalidate the same cache entry.
  const pendingQ = useQuery({ queryKey: ["rules", "pending"], queryFn: rulesApi.getPending, staleTime: 30_000 })
  const versionsQ = useQuery({ queryKey: ["rules", "allVersions"], queryFn: rulesApi.getAllVersions, staleTime: 30_000 })
  const auditQ = useQuery({ queryKey: ["audit", "history"], queryFn: () => rulesApi.getAuditHistory(20), staleTime: 30_000 })

  const pending = pendingQ.data ?? []
  const versions = versionsQ.data ?? []
  const auditEvents = auditQ.data?.events ?? []

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative z-10 w-full max-w-lg bg-white shadow-2xl flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-gray-900 leading-tight flex items-center gap-1.5">
              <Shield className="h-4 w-4 text-gray-400" /> Rule Approval
            </h2>
            <p className="text-[11px] text-gray-400 mt-0.5">
              All rule versions are immutable — old and new defaults are always kept for audit.
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 shrink-0" aria-label="Close">
            <X className="h-4 w-4 text-gray-500" />
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex border-b shrink-0 bg-gray-50">
          {(["pending", "versions", "audit"] as ApprovalTab[]).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-4 py-2.5 text-xs font-medium border-b-2 transition-colors flex items-center gap-1.5",
                activeTab === tab
                  ? "border-indigo-500 text-indigo-700 bg-white"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              )}
            >
              {tab === "pending" && <AlertCircle className="h-3.5 w-3.5" />}
              {tab === "versions" && <Clock className="h-3.5 w-3.5" />}
              {tab === "audit" && <Shield className="h-3.5 w-3.5" />}
              {TAB_LABEL[tab]}
              {tab === "pending" && pending.length > 0 && (
                <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full font-semibold">
                  {pending.length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {activeTab === "pending" && (
            <PendingReviewTab
              pending={pending}
              isLoading={pendingQ.isLoading}
              focusRuleVersionId={focusRuleVersionId}
            />
          )}
          {activeTab === "versions" && (
            <VersionTimelineTab versions={versions} isLoading={versionsQ.isLoading} />
          )}
          {activeTab === "audit" && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center gap-2 mb-3">
                <Shield className="h-4 w-4 text-gray-400" />
                <span className="text-sm font-semibold text-gray-700">Audit Log</span>
                <span className="text-xs text-gray-400">(most recent actions first)</span>
              </div>
              {auditQ.isLoading ? (
                <div className="flex items-center gap-2 text-gray-400 text-xs py-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
                </div>
              ) : (
                <AuditLogStrip events={auditEvents} />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
