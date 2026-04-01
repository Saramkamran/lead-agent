"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getLeads,
  getLead,
  getLeadScan,
  triggerLeadScan,
  processLead,
  deleteLeadMessages,
  updateLead,
  deleteLead,
  importLeads,
  triggerProcessJob,
  triggerScoreJob,
  bulkDeleteLeads,
  bulkScoreLeads,
  bulkProcessLeads,
  getOutreachAccounts,
  autoAssignAccounts,
  Lead,
  Message,
  Conversation,
  OutreachAccount,
  WebsiteScan,
} from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Badge, ScoreBadge, StatusBadge } from "@/components/ui/badge";
import { Upload, X, Trash2, Zap, UserPlus, RefreshCw, Play, ChevronDown } from "lucide-react";

const STATUS_OPTIONS = [
  "", "imported", "scored", "contacted", "follow_up_1", "follow_up_2", "follow_up_3",
  "replied", "booked", "not_interested", "disqualified",
];

function ScanBadge({ status, reusedFrom }: { status?: string; reusedFrom?: string }) {
  if (!status || status === "pending") return <Badge variant="gray">Pending</Badge>;
  if (status === "scanning") return <Badge variant="gray">Scanning…</Badge>;
  if (status === "success" && reusedFrom) return <Badge variant="blue">Already Scanned</Badge>;
  if (status === "success") return <Badge variant="green">Scanned</Badge>;
  if (status === "failed") return <Badge variant="gray">Scan failed</Badge>;
  return null;
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Partial<Lead>[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [scoreOp, setScoreOp] = useState<"" | "gt" | "lt">("");
  const [scoreVal, setScoreVal] = useState("");
  const [loading, setLoading] = useState(true);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkResult, setBulkResult] = useState<string | null>(null);

  const [accounts, setAccounts] = useState<OutreachAccount[]>([]);

  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [slideOpen, setSlideOpen] = useState(false);
  const [editing, setEditing] = useState<Partial<Lead>>({});
  const [scan, setScan] = useState<WebsiteScan | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const [scoring, setScoring] = useState(false);
  const [scoredCount, setScoredCount] = useState<number | null>(null);
  const [processingAll, setProcessingAll] = useState(false);
  const [processedCount, setProcessedCount] = useState<number | null>(null);

  const [autoAssigning, setAutoAssigning] = useState(false);
  const [autoAssignResult, setAutoAssignResult] = useState<string | null>(null);

  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; skipped: number; errors: string[] } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const PAGE_SIZE = 20;

  const fetchLeads = useCallback(async () => {
    setLoading(true);
    setSelectedIds(new Set());
    try {
      const params: Parameters<typeof getLeads>[0] = { page, page_size: PAGE_SIZE };
      if (statusFilter) params.status = statusFilter;
      const numVal = parseInt(scoreVal);
      if (scoreOp === "gt" && !isNaN(numVal)) params.min_score = numVal;
      if (scoreOp === "lt" && !isNaN(numVal)) params.max_score = numVal;
      const data = await getLeads(params);
      setLeads(data.items);
      setTotal(data.total);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, scoreOp, scoreVal]);

  useEffect(() => { fetchLeads(); }, [fetchLeads]);

  useEffect(() => {
    getOutreachAccounts().then(setAccounts).catch(console.error);
  }, []);

  const filteredLeads = search
    ? leads.filter((l) =>
        [l.email, l.first_name, l.last_name, l.company, l.title]
          .join(" ")
          .toLowerCase()
          .includes(search.toLowerCase())
      )
    : leads;

  function accountLabel(id?: string) {
    if (!id) return "—";
    const acc = accounts.find((a) => a.id === id);
    return acc ? acc.from_email : "—";
  }

  async function openLead(id: string) {
    const lead = await getLead(id);
    setSelectedLead(lead);
    setEditing({
      first_name: lead.first_name,
      last_name: lead.last_name,
      company: lead.company,
      title: lead.title,
      website: lead.website,
      industry: lead.industry,
      company_size: lead.company_size,
      status: lead.status,
      outreach_account_id: lead.outreach_account_id ?? "",
    });
    setScan(null);
    setSlideOpen(true);
    // Load scan data in background
    getLeadScan(id).then(setScan).catch(() => setScan(null));
  }

  async function saveEditing() {
    if (!selectedLead) return;
    try {
      const payload = { ...editing };
      if (payload.outreach_account_id === "") payload.outreach_account_id = undefined;
      const updated = await updateLead(selectedLead.id, payload);
      setSelectedLead(updated);
      fetchLeads();
    } catch (e) {
      console.error(e);
    }
  }

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("Delete this lead?")) return;
    await deleteLead(id);
    fetchLeads();
  }

  async function handleImport() {
    if (!importFile) return;
    setImportLoading(true);
    setImportResult(null);
    try {
      const result = await importLeads(importFile);
      setImportResult(result);
      if (result.imported > 0) fetchLeads();
    } catch (e) {
      console.error(e);
    } finally {
      setImportLoading(false);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file?.name.endsWith(".csv")) setImportFile(file);
  }

  async function handleProcessNow() {
    setProcessingAll(true);
    setProcessedCount(null);
    try {
      const res = await triggerProcessJob();
      setProcessedCount(res.processed);
      fetchLeads();
      setTimeout(() => setProcessedCount(null), 4000);
    } catch (e) {
      console.error(e);
    } finally {
      setProcessingAll(false);
    }
  }

  async function handleScoreNow() {
    setScoring(true);
    setScoredCount(null);
    try {
      await triggerScoreJob();
      setScoredCount(1);
      fetchLeads();
      setTimeout(() => setScoredCount(null), 4000);
    } catch (e) {
      console.error(e);
    } finally {
      setScoring(false);
    }
  }

  async function handleAutoAssign() {
    setAutoAssigning(true);
    setAutoAssignResult(null);
    try {
      const result = await autoAssignAccounts();
      setAutoAssignResult(
        result.assigned > 0
          ? `${result.assigned} lead${result.assigned === 1 ? "" : "s"} assigned`
          : "No leads assigned — check that active accounts have remaining capacity"
      );
      fetchLeads();
      setTimeout(() => setAutoAssignResult(null), 5000);
    } catch (e) {
      console.error(e);
    } finally {
      setAutoAssigning(false);
    }
  }

  function toggleSelectAll() {
    if (selectedIds.size === filteredLeads.length && filteredLeads.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredLeads.map((l) => l.id!).filter(Boolean)));
    }
  }

  function toggleSelectOne(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleBulkDelete() {
    if (!confirm(`Delete ${selectedIds.size} lead(s)? This cannot be undone.`)) return;
    setBulkLoading(true);
    try {
      const res = await bulkDeleteLeads(Array.from(selectedIds));
      setBulkResult(`${res.deleted} lead(s) deleted`);
      setSelectedIds(new Set());
      fetchLeads();
      setTimeout(() => setBulkResult(null), 4000);
    } catch (e) { console.error(e); }
    finally { setBulkLoading(false); }
  }

  async function handleBulkScore() {
    setBulkLoading(true);
    try {
      const res = await bulkScoreLeads(Array.from(selectedIds));
      setBulkResult(`${res.scored} lead(s) scored`);
      setSelectedIds(new Set());
      fetchLeads();
      setTimeout(() => setBulkResult(null), 4000);
    } catch (e) { console.error(e); }
    finally { setBulkLoading(false); }
  }

  async function handleBulkProcess() {
    setBulkLoading(true);
    try {
      const res = await bulkProcessLeads(Array.from(selectedIds));
      setBulkResult(`${res.processed} lead(s) processed`);
      setSelectedIds(new Set());
      fetchLeads();
      setTimeout(() => setBulkResult(null), 4000);
    } catch (e) { console.error(e); }
    finally { setBulkLoading(false); }
  }

  async function handleRescan() {
    if (!selectedLead) return;
    setScanLoading(true);
    try {
      await triggerLeadScan(selectedLead.id);
      setScan(null);
    } catch (e) {
      console.error(e);
    } finally {
      setScanLoading(false);
    }
  }

  async function handleProcessLead() {
    if (!selectedLead) return;
    setProcessing(true);
    try {
      const updated = await processLead(selectedLead.id);
      setSelectedLead(updated);
      setEditing({
        first_name: updated.first_name,
        last_name: updated.last_name,
        company: updated.company,
        title: updated.title,
        website: updated.website,
        industry: updated.industry,
        company_size: updated.company_size,
        status: updated.status,
        outreach_account_id: updated.outreach_account_id ?? "",
      });
      // Reload scan data
      getLeadScan(updated.id).then(setScan).catch(() => setScan(null));
      fetchLeads();
    } catch (e) {
      console.error(e);
    } finally {
      setProcessing(false);
    }
  }

  async function handleRegenerateEmails() {
    if (!selectedLead) return;
    if (!confirm("Delete cached emails and regenerate fresh ones? This cannot be undone.")) return;
    setRegenerating(true);
    try {
      await deleteLeadMessages(selectedLead.id);
      const updated = await processLead(selectedLead.id);
      setSelectedLead(updated);
      setEditing({
        first_name: updated.first_name,
        last_name: updated.last_name,
        company: updated.company,
        title: updated.title,
        website: updated.website,
        industry: updated.industry,
        company_size: updated.company_size,
        status: updated.status,
        outreach_account_id: updated.outreach_account_id ?? "",
      });
      getLeadScan(updated.id).then(setScan).catch(() => setScan(null));
      fetchLeads();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Regeneration failed";
      alert(msg);
    } finally {
      setRegenerating(false);
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <AppShell>
      <div className="p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Leads</h1>
          <div className="flex items-center gap-2 flex-wrap justify-end">
            {processedCount !== null && (
              <span className="text-sm text-green-600 font-medium">Processing complete — {processedCount} lead(s) updated</span>
            )}
            {scoredCount !== null && (
              <span className="text-sm text-green-600 font-medium">Scoring complete — leads updated</span>
            )}
            {autoAssignResult && (
              <span className={`text-sm font-medium ${autoAssignResult.startsWith("No") ? "text-amber-600" : "text-green-600"}`}>
                {autoAssignResult}
              </span>
            )}
            <Button variant="secondary" onClick={handleAutoAssign} disabled={autoAssigning}>
              <UserPlus size={16} />
              {autoAssigning ? "Assigning…" : "Auto-Assign Accounts"}
            </Button>
            <Button variant="secondary" onClick={handleProcessNow} disabled={processingAll}>
              <Play size={16} />
              {processingAll ? "Processing…" : "Process Now"}
            </Button>
            <Button variant="secondary" onClick={handleScoreNow} disabled={scoring}>
              <Zap size={16} />
              {scoring ? "Scoring…" : "Score Now"}
            </Button>
            <Button onClick={() => { setImportOpen(true); setImportResult(null); setImportFile(null); }}>
              <Upload size={16} /> Import CSV
            </Button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-3 mb-4 flex-wrap items-center">
          <Input
            placeholder="Search name, company, email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="max-w-xs"
          />
          <Select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="max-w-[180px]"
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.filter(Boolean).map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
            ))}
          </Select>
          <Select
            value={scoreOp}
            onChange={(e) => { setScoreOp(e.target.value as "" | "gt" | "lt"); setPage(1); }}
            className="w-[130px]"
          >
            <option value="">Score filter</option>
            <option value="gt">Score &gt;</option>
            <option value="lt">Score &lt;</option>
          </Select>
          {scoreOp && (
            <Input
              type="number"
              placeholder="Value"
              value={scoreVal}
              onChange={(e) => { setScoreVal(e.target.value); setPage(1); }}
              className="w-24"
            />
          )}
          {scoreOp && (
            <button
              onClick={() => { setScoreOp(""); setScoreVal(""); setPage(1); }}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Clear
            </button>
          )}
        </div>

        {/* Bulk actions toolbar */}
        {selectedIds.size > 0 && (
          <div className="flex items-center gap-3 mb-3 px-4 py-2 bg-indigo-50 border border-indigo-200 rounded-lg">
            <span className="text-sm font-medium text-indigo-700">{selectedIds.size} selected</span>
            {bulkResult && <span className="text-sm text-green-600 font-medium">{bulkResult}</span>}
            <div className="flex gap-2 ml-auto">
              <Button variant="secondary" size="sm" onClick={handleBulkScore} disabled={bulkLoading}>
                <Zap size={14} /> Score
              </Button>
              <Button variant="secondary" size="sm" onClick={handleBulkProcess} disabled={bulkLoading}>
                <Play size={14} /> Process
              </Button>
              <Button variant="secondary" size="sm" onClick={handleBulkDelete} disabled={bulkLoading}
                className="text-red-600 hover:text-red-700">
                <Trash2 size={14} /> Delete
              </Button>
            </div>
          </div>
        )}

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 text-left">
                <th className="px-4 py-3 w-10">
                  <input
                    type="checkbox"
                    className="rounded border-gray-300 cursor-pointer"
                    checked={filteredLeads.length > 0 && selectedIds.size === filteredLeads.length}
                    ref={(el) => { if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < filteredLeads.length; }}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className="px-4 py-3 font-medium text-gray-600">Name</th>
                <th className="px-4 py-3 font-medium text-gray-600">Email</th>
                <th className="px-4 py-3 font-medium text-gray-600">Company</th>
                <th className="px-4 py-3 font-medium text-gray-600">Score</th>
                <th className="px-4 py-3 font-medium text-gray-600">Status</th>
                <th className="px-4 py-3 font-medium text-gray-600">Scan</th>
                <th className="px-4 py-3 font-medium text-gray-600">Account</th>
                <th className="px-4 py-3 font-medium text-gray-600">Added</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={10} className="px-4 py-8 text-center text-gray-400">Loading…</td></tr>
              ) : filteredLeads.length === 0 ? (
                <tr><td colSpan={10} className="px-4 py-8 text-center text-gray-400">No leads found.</td></tr>
              ) : (
                filteredLeads.map((lead) => (
                  <tr
                    key={lead.id}
                    className={`border-b border-gray-50 hover:bg-indigo-50/40 cursor-pointer transition-colors ${selectedIds.has(lead.id!) ? "bg-indigo-50" : ""}`}
                    onClick={() => openLead(lead.id!)}
                  >
                    <td className="px-4 py-3" onClick={(e) => toggleSelectOne(lead.id!, e)}>
                      <input
                        type="checkbox"
                        className="rounded border-gray-300 cursor-pointer"
                        checked={selectedIds.has(lead.id!)}
                        onChange={() => {}}
                      />
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {[lead.first_name, lead.last_name].filter(Boolean).join(" ") || lead.email}
                    </td>
                    <td className="px-4 py-3 text-gray-600">{lead.email}</td>
                    <td className="px-4 py-3 text-gray-600">{lead.company ?? "—"}</td>
                    <td className="px-4 py-3"><ScoreBadge score={lead.score} /></td>
                    <td className="px-4 py-3"><StatusBadge status={lead.status!} /></td>
                    <td className="px-4 py-3"><ScanBadge status={lead.scan_status} /></td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{accountLabel(lead.outreach_account_id)}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {lead.created_at ? new Date(lead.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={(e) => handleDelete(lead.id!, e)}
                        className="text-gray-300 hover:text-red-500 transition-colors"
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
              <span className="text-sm text-gray-500">
                {total} leads — page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="secondary" size="sm" disabled={page === totalPages} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Slide-over panel */}
      {slideOpen && selectedLead && (
        <div className="fixed inset-0 z-30 flex">
          <div className="flex-1 bg-black/30" onClick={() => setSlideOpen(false)} />
          <div className="w-[480px] bg-white shadow-2xl overflow-y-auto flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <h2 className="font-semibold text-gray-900 text-lg">
                {[selectedLead.first_name, selectedLead.last_name].filter(Boolean).join(" ") || selectedLead.email}
              </h2>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handleRegenerateEmails}
                  disabled={regenerating || processing}
                  title="Delete cached emails and regenerate with latest scan"
                >
                  <RefreshCw size={14} className={regenerating ? "animate-spin" : ""} />
                  {regenerating ? "Regenerating…" : "Regenerate Emails"}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handleProcessLead}
                  disabled={processing || regenerating}
                >
                  <Play size={14} className={processing ? "animate-pulse" : ""} />
                  {processing ? "Processing…" : "Process Lead"}
                </Button>
                <button onClick={() => setSlideOpen(false)} className="text-gray-400 hover:text-gray-600">
                  <X size={20} />
                </button>
              </div>
            </div>

            <div className="flex-1 p-6 space-y-6">
              {/* Score + Status */}
              <div className="flex items-center gap-3 flex-wrap">
                <ScoreBadge score={selectedLead.score} />
                <StatusBadge status={selectedLead.status} />
                <ScanBadge status={selectedLead.scan_status} reusedFrom={scan?.reused_from} />
                {selectedLead.reply_category && (
                  <span className="text-xs bg-purple-50 text-purple-700 border border-purple-200 rounded-full px-2 py-0.5">
                    {selectedLead.reply_category.replace(/_/g, " ")}
                  </span>
                )}
                {selectedLead.score_reason && (
                  <span className="text-xs text-gray-500 italic">{selectedLead.score_reason}</span>
                )}
              </div>

              {/* Website Analysis */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-gray-700">Website Analysis</h3>
                  <button
                    onClick={handleRescan}
                    disabled={scanLoading}
                    className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
                  >
                    <RefreshCw size={12} className={scanLoading ? "animate-spin" : ""} />
                    {scanLoading ? "Queuing…" : "Re-scan"}
                  </button>
                </div>
                {scan ? (
                  <div className="bg-gray-50 rounded-lg p-3 space-y-2 text-sm">
                    {scan.reused_from && (
                      <p className="text-xs text-blue-600 bg-blue-50 border border-blue-200 rounded px-2 py-1">
                        Website already scanned — scan data reused from another lead with the same website.
                      </p>
                    )}
                    {scan.hook_text && (
                      <p className="text-gray-700 italic border-l-2 border-indigo-400 pl-3">
                        &ldquo;{scan.hook_text}&rdquo;
                      </p>
                    )}
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
                      {scan.business_type && <span className="col-span-2 text-gray-700 font-medium">{scan.business_type}</span>}
                      <span>Booking system: <b className={scan.has_booking_system ? "text-green-600" : "text-red-500"}>{scan.has_booking_system ? "Yes" : "No"}</b></span>
                      <span>Pricing page: <b className={scan.has_pricing_page ? "text-green-600" : "text-red-500"}>{scan.has_pricing_page ? "Yes" : "No"}</b></span>
                      <span>Contact form: <b className={scan.has_contact_form ? "text-green-600" : "text-red-500"}>{scan.has_contact_form ? "Yes" : "No"}</b></span>
                      <span>CTA strength: <b>{scan.cta_strength ?? "—"}</b></span>
                      {scan.booking_method && <span>Booking method: <b>{scan.booking_method}</b></span>}
                    </div>
                  </div>
                ) : selectedLead.scan_status === "pending" || selectedLead.scan_status === "scanning" ? (
                  <p className="text-xs text-gray-400">Scan in progress — check back shortly.</p>
                ) : selectedLead.scan_status === "failed" ? (
                  <p className="text-xs text-amber-600">Scan failed — generic email template will be used.</p>
                ) : (
                  <p className="text-xs text-gray-400">No scan data yet.</p>
                )}
              </div>

              {/* Custom offer */}
              {selectedLead.custom_offer && (
                <div className="bg-indigo-50 rounded-lg px-4 py-3 text-sm text-indigo-800">
                  {selectedLead.custom_offer}
                </div>
              )}

              {/* Editable fields */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-gray-700">Lead Details</h3>
                <div className="grid grid-cols-2 gap-3">
                  <Input label="First name" value={editing.first_name ?? ""} onChange={(e) => setEditing({ ...editing, first_name: e.target.value })} />
                  <Input label="Last name" value={editing.last_name ?? ""} onChange={(e) => setEditing({ ...editing, last_name: e.target.value })} />
                  <Input label="Company" value={editing.company ?? ""} onChange={(e) => setEditing({ ...editing, company: e.target.value })} />
                  <Input label="Title" value={editing.title ?? ""} onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
                  <Input label="Website" value={editing.website ?? ""} onChange={(e) => setEditing({ ...editing, website: e.target.value })} />
                  <Input label="Industry" value={editing.industry ?? ""} onChange={(e) => setEditing({ ...editing, industry: e.target.value })} />
                  <Input label="Company size" value={editing.company_size ?? ""} onChange={(e) => setEditing({ ...editing, company_size: e.target.value })} />
                  <Select label="Status" value={editing.status ?? ""} onChange={(e) => setEditing({ ...editing, status: e.target.value })}>
                    {STATUS_OPTIONS.filter(Boolean).map((s) => (
                      <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
                    ))}
                  </Select>
                </div>

                {/* Outreach Account dropdown */}
                <Select
                  label="Outreach Account"
                  value={editing.outreach_account_id ?? ""}
                  onChange={(e) => setEditing({ ...editing, outreach_account_id: e.target.value })}
                >
                  <option value="">Unassigned</option>
                  {accounts.map((acc) => (
                    <option key={acc.id} value={acc.id}>
                      {acc.display_name} ({acc.from_email})
                    </option>
                  ))}
                </Select>

                <Button onClick={saveEditing} size="sm">Save changes</Button>
              </div>

              {/* Followup timing */}
              {(selectedLead.last_contacted_at || selectedLead.next_followup_at) && (
                <div className="text-xs text-gray-500 space-y-1">
                  {selectedLead.last_contacted_at && (
                    <p>Last contacted: {new Date(selectedLead.last_contacted_at).toLocaleDateString()}</p>
                  )}
                  {selectedLead.next_followup_at && (
                    <p>Next follow-up: {new Date(selectedLead.next_followup_at).toLocaleDateString()}</p>
                  )}
                </div>
              )}

              {/* Messages */}
              {selectedLead.messages && selectedLead.messages.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold text-gray-700">Emails</h3>
                  {selectedLead.messages.map((msg: Message) => (
                    <div key={msg.id} className="border border-gray-100 rounded-lg p-3 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-gray-800">{msg.subject ?? "(no subject)"}</span>
                        <StatusBadge status={msg.status} />
                      </div>
                      <div className="flex gap-3 mt-1 text-xs text-gray-400">
                        <span>{msg.type?.replace(/_/g, " ")}</span>
                        {msg.sent_at && <span>{new Date(msg.sent_at).toLocaleDateString()}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Conversation thread */}
              {selectedLead.conversations && selectedLead.conversations.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold text-gray-700">Conversation</h3>
                  <div className="space-y-2 max-h-60 overflow-y-auto">
                    {(selectedLead.conversations[0].thread as Array<{ role: string; content: string; timestamp: string }>).map(
                      (msg, i) => (
                        <div key={i} className={`flex ${msg.role === "agent" ? "justify-end" : "justify-start"}`}>
                          <div
                            className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${
                              msg.role === "agent"
                                ? "bg-indigo-600 text-white"
                                : "bg-gray-100 text-gray-900"
                            }`}
                          >
                            {msg.content}
                          </div>
                        </div>
                      )
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Import CSV Modal */}
      <Modal open={importOpen} onClose={() => setImportOpen(false)} title="Import Leads (CSV)">
        <div className="space-y-4">
          <div
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
              dragOver ? "border-indigo-400 bg-indigo-50" : "border-gray-200 hover:border-gray-300"
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
          >
            <Upload size={32} className="mx-auto text-gray-300 mb-2" />
            {importFile ? (
              <p className="text-sm text-indigo-700 font-medium">{importFile.name}</p>
            ) : (
              <>
                <p className="text-sm text-gray-600">Drop a CSV file here or click to browse</p>
                <p className="text-xs text-gray-400 mt-1">Columns: email, first_name, last_name, company, title, website, industry, company_size</p>
              </>
            )}
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && setImportFile(e.target.files[0])}
            />
          </div>

          {importResult && (
            <div className="rounded-lg bg-green-50 border border-green-200 p-3 text-sm text-green-800">
              Imported <strong>{importResult.imported}</strong> leads.{" "}
              {importResult.skipped > 0 && <span>Skipped {importResult.skipped} duplicates. </span>}
              {importResult.errors.length > 0 && (
                <span className="text-red-600">{importResult.errors.length} errors.</span>
              )}
            </div>
          )}

          <div className="flex gap-2 justify-end">
            <Button variant="secondary" onClick={() => setImportOpen(false)}>Cancel</Button>
            <Button onClick={handleImport} disabled={!importFile || importLoading}>
              {importLoading ? "Importing…" : "Import"}
            </Button>
          </div>
        </div>
      </Modal>
    </AppShell>
  );
}
