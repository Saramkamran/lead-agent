"use client";
// v2
import { useCallback, useEffect, useRef, useState } from "react";
import { getLeads, getLead, updateLead, deleteLead, importLeads, triggerScoreJob, Lead, Message, Conversation } from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { ScoreBadge, StatusBadge } from "@/components/ui/badge";
import { Upload, X, ChevronRight, Trash2, Zap } from "lucide-react";

const STATUS_OPTIONS = ["", "imported", "scored", "contacted", "replied", "booked", "not_interested", "bounced"];

export default function LeadsPage() {
  const [leads, setLeads] = useState<Partial<Lead>[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [slideOpen, setSlideOpen] = useState(false);
  const [editing, setEditing] = useState<Partial<Lead>>({});

  const [scoring, setScoring] = useState(false);
  const [scoredCount, setScoredCount] = useState<number | null>(null);

  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; skipped: number; errors: string[] } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const PAGE_SIZE = 20;

  const fetchLeads = useCallback(async () => {
    setLoading(true);
    try {
      const params: Parameters<typeof getLeads>[0] = { page, page_size: PAGE_SIZE };
      if (statusFilter) params.status = statusFilter;
      const data = await getLeads(params);
      setLeads(data.items);
      setTotal(data.total);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  useEffect(() => { fetchLeads(); }, [fetchLeads]);

  const filteredLeads = search
    ? leads.filter((l) =>
        [l.email, l.first_name, l.last_name, l.company, l.title]
          .join(" ")
          .toLowerCase()
          .includes(search.toLowerCase())
      )
    : leads;

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
    });
    setSlideOpen(true);
  }

  async function saveEditing() {
    if (!selectedLead) return;
    try {
      const updated = await updateLead(selectedLead.id, editing);
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

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <AppShell>
      <div className="p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Leads</h1>
          <div className="flex items-center gap-2">
            {scoredCount !== null && (
              <span className="text-sm text-green-600 font-medium">Scoring complete — leads updated</span>
            )}
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
        <div className="flex gap-3 mb-4">
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
              <option key={s} value={s}>{s.replace("_", " ")}</option>
            ))}
          </Select>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 text-left">
                <th className="px-4 py-3 font-medium text-gray-600">Name</th>
                <th className="px-4 py-3 font-medium text-gray-600">Email</th>
                <th className="px-4 py-3 font-medium text-gray-600">Company</th>
                <th className="px-4 py-3 font-medium text-gray-600">Title</th>
                <th className="px-4 py-3 font-medium text-gray-600">Score</th>
                <th className="px-4 py-3 font-medium text-gray-600">Status</th>
                <th className="px-4 py-3 font-medium text-gray-600">Added</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">Loading…</td></tr>
              ) : filteredLeads.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No leads found.</td></tr>
              ) : (
                filteredLeads.map((lead) => (
                  <tr
                    key={lead.id}
                    className="border-b border-gray-50 hover:bg-indigo-50/40 cursor-pointer transition-colors"
                    onClick={() => openLead(lead.id!)}
                  >
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {[lead.first_name, lead.last_name].filter(Boolean).join(" ") || lead.email}
                    </td>
                    <td className="px-4 py-3 text-gray-600">{lead.email}</td>
                    <td className="px-4 py-3 text-gray-600">{lead.company ?? "—"}</td>
                    <td className="px-4 py-3 text-gray-600">{lead.title ?? "—"}</td>
                    <td className="px-4 py-3"><ScoreBadge score={lead.score} /></td>
                    <td className="px-4 py-3"><StatusBadge status={lead.status!} /></td>
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
              <button onClick={() => setSlideOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X size={20} />
              </button>
            </div>

            <div className="flex-1 p-6 space-y-6">
              {/* Score */}
              <div className="flex items-center gap-3">
                <ScoreBadge score={selectedLead.score} />
                <StatusBadge status={selectedLead.status} />
                {selectedLead.score_reason && (
                  <span className="text-xs text-gray-500 italic">{selectedLead.score_reason}</span>
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
                      <option key={s} value={s}>{s.replace("_", " ")}</option>
                    ))}
                  </Select>
                </div>
                <Button onClick={saveEditing} size="sm">Save changes</Button>
              </div>

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
                        <span>{msg.type?.replace("_", " ")}</span>
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
