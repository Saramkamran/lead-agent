"use client";

import { useEffect, useState } from "react";
import { getCampaigns, createCampaign, updateCampaign, startCampaign, pauseCampaign, deleteCampaign, triggerOutreachJob, Campaign } from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { StatusBadge } from "@/components/ui/badge";
import { Plus, Play, Pause, Pencil, Send, Trash2, AlertCircle } from "lucide-react";

const EMPTY_FORM: Partial<Campaign> = {
  name: "",
  sender_name: "",
  sender_email: "",
  sender_company: "",
  calendly_link: "",
  daily_limit: 30,
  min_score: 50,
  send_hour: 9,
  send_minute: 0,
};

function isReadyToStart(c: Campaign) {
  return !!(c.sender_email?.trim() && c.calendly_link?.trim());
}

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingCampaign, setEditingCampaign] = useState<Campaign | null>(null);
  const [form, setForm] = useState<Partial<Campaign>>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [outreaching, setOutreaching] = useState(false);
  const [outreachResult, setOutreachResult] = useState<string | null>(null);
  const [startError, setStartError] = useState<{ id: string; msg: string } | null>(null);

  useEffect(() => { fetchCampaigns(); }, []);

  async function fetchCampaigns() {
    setLoading(true);
    try {
      setCampaigns(await getCampaigns());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  function openNew() {
    setEditingCampaign(null);
    setForm(EMPTY_FORM);
    setError("");
    setModalOpen(true);
  }

  function openEdit(campaign: Campaign) {
    if (campaign.status === "active") return;
    setEditingCampaign(campaign);
    setForm({
      name: campaign.name,
      sender_name: campaign.sender_name ?? "",
      sender_email: campaign.sender_email ?? "",
      sender_company: campaign.sender_company ?? "",
      calendly_link: campaign.calendly_link ?? "",
      daily_limit: campaign.daily_limit,
      min_score: campaign.min_score,
      send_hour: campaign.send_hour ?? 9,
      send_minute: campaign.send_minute ?? 0,
    });
    setError("");
    setModalOpen(true);
  }

  async function handleSave() {
    if (!form.name?.trim()) { setError("Campaign name is required"); return; }
    setSaving(true);
    setError("");
    try {
      if (editingCampaign) {
        await updateCampaign(editingCampaign.id, form);
      } else {
        await createCampaign(form);
      }
      setModalOpen(false);
      fetchCampaigns();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Failed to save";
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(campaign: Campaign) {
    if (!confirm(`Delete campaign "${campaign.name}"? This cannot be undone.`)) return;
    try {
      await deleteCampaign(campaign.id);
      fetchCampaigns();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Delete failed";
      alert(msg);
    }
  }

  async function handleSendOutreach() {
    setOutreaching(true);
    setOutreachResult(null);
    try {
      const result = await triggerOutreachJob();
      const msg = result.sent > 0
        ? `${result.sent} email${result.sent === 1 ? "" : "s"} sent`
        : "No emails sent — check that your campaign is active and you have scored leads above the minimum score";
      setOutreachResult(msg);
      setTimeout(() => setOutreachResult(null), 6000);
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Outreach failed";
      alert(msg);
    } finally {
      setOutreaching(false);
    }
  }

  async function toggleCampaign(campaign: Campaign) {
    setStartError(null);
    try {
      if (campaign.status === "active") {
        await pauseCampaign(campaign.id);
      } else {
        if (!isReadyToStart(campaign)) {
          setStartError({
            id: campaign.id,
            msg: "Edit this campaign to add sender email and calendar link before starting.",
          });
          return;
        }
        await startCampaign(campaign.id);
      }
      fetchCampaigns();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Action failed";
      setStartError({ id: campaign.id, msg });
    }
  }

  return (
    <AppShell>
      <div className="p-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Campaigns</h1>
          <div className="flex items-center gap-2">
            {outreachResult && (
              <span className={`text-sm font-medium ${outreachResult.startsWith("No emails") ? "text-amber-600" : "text-green-600"}`}>
                {outreachResult}
              </span>
            )}
            <Button variant="secondary" onClick={handleSendOutreach} disabled={outreaching}>
              <Send size={16} />
              {outreaching ? "Sending…" : "Send Outreach Now"}
            </Button>
            <Button onClick={openNew}>
              <Plus size={16} /> New Campaign
            </Button>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 text-left">
                <th className="px-4 py-3 font-medium text-gray-600">Name</th>
                <th className="px-4 py-3 font-medium text-gray-600">Status</th>
                <th className="px-4 py-3 font-medium text-gray-600">Sender</th>
                <th className="px-4 py-3 font-medium text-gray-600">Min Score</th>
                <th className="px-4 py-3 font-medium text-gray-600">Daily Limit</th>
                <th className="px-4 py-3 font-medium text-gray-600">Send Time</th>
                <th className="px-4 py-3 font-medium text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">Loading…</td></tr>
              ) : campaigns.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">No campaigns yet. Create one to start sending.</td></tr>
              ) : (
                campaigns.map((c) => (
                  <>
                    <tr key={c.id} className="border-b border-gray-50">
                      <td className="px-4 py-3 font-medium text-gray-900">{c.name}</td>
                      <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                      <td className="px-4 py-3">
                        {c.sender_email ? (
                          <span className="text-gray-600 text-xs">{c.sender_email}</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-xs text-amber-600">
                            <AlertCircle size={12} /> Setup required
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600">{c.min_score}</td>
                      <td className="px-4 py-3 text-gray-600">{c.daily_limit}/day</td>
                      <td className="px-4 py-3 text-gray-600">
                        {String(c.send_hour ?? 9).padStart(2, "0")}:{String(c.send_minute ?? 0).padStart(2, "0")} UTC
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => toggleCampaign(c)}
                            title={c.status === "active" ? "Pause" : isReadyToStart(c) ? "Start" : "Edit campaign to add required fields first"}
                            className={`p-1.5 rounded-lg transition-colors ${
                              c.status === "active"
                                ? "text-yellow-600 hover:bg-yellow-50"
                                : isReadyToStart(c)
                                ? "text-green-600 hover:bg-green-50"
                                : "text-gray-300 cursor-not-allowed"
                            }`}
                          >
                            {c.status === "active" ? <Pause size={16} /> : <Play size={16} />}
                          </button>
                          <button
                            onClick={() => openEdit(c)}
                            disabled={c.status === "active"}
                            title={c.status === "active" ? "Pause campaign to edit" : "Edit"}
                            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <Pencil size={16} />
                          </button>
                          <button
                            onClick={() => handleDelete(c)}
                            disabled={c.status === "active"}
                            title={c.status === "active" ? "Pause campaign to delete" : "Delete"}
                            className="p-1.5 rounded-lg text-red-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                    {startError?.id === c.id && (
                      <tr key={`${c.id}-err`} className="bg-amber-50">
                        <td colSpan={7} className="px-4 py-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs text-amber-700 flex items-center gap-1">
                              <AlertCircle size={12} /> {startError.msg}
                            </span>
                            <button
                              onClick={() => { openEdit(c); setStartError(null); }}
                              className="text-xs text-indigo-600 hover:underline font-medium"
                            >
                              Edit campaign →
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingCampaign ? "Edit Campaign" : "New Campaign"}
        maxWidth="max-w-md"
      >
        <div className="space-y-4">
          <Input
            label="Campaign name *"
            value={form.name ?? ""}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="e.g. March Outreach"
          />

          <div className="border-t border-gray-100 pt-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Sender Identity</p>
            <div className="space-y-2">
              <Input
                label="Sender name"
                value={form.sender_name ?? ""}
                onChange={(e) => setForm({ ...form, sender_name: e.target.value })}
                placeholder="e.g. Hassan"
              />
              <div className="grid grid-cols-2 gap-2">
                <Input
                  label="Sender email *"
                  type="email"
                  value={form.sender_email ?? ""}
                  onChange={(e) => setForm({ ...form, sender_email: e.target.value })}
                  placeholder="hassan@blackbird.com"
                />
                <Input
                  label="Sender company"
                  value={form.sender_company ?? ""}
                  onChange={(e) => setForm({ ...form, sender_company: e.target.value })}
                  placeholder="Blackbird"
                />
              </div>
              <Input
                label="Calendly / booking link *"
                value={form.calendly_link ?? ""}
                onChange={(e) => setForm({ ...form, calendly_link: e.target.value })}
                placeholder="https://cal.com/..."
              />
              <p className="text-xs text-amber-600">* Required to activate campaign</p>
            </div>
          </div>

          <div className="border-t border-gray-100 pt-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Sending Rules</p>
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="Min score"
                type="number"
                min={0}
                max={100}
                value={form.min_score ?? 50}
                onChange={(e) => setForm({ ...form, min_score: Number(e.target.value) })}
              />
              <Input
                label="Daily limit"
                type="number"
                min={1}
                max={500}
                value={form.daily_limit ?? 30}
                onChange={(e) => setForm({ ...form, daily_limit: Number(e.target.value) })}
              />
            </div>
            <div className="mt-2">
              <label className="block text-xs font-medium text-gray-600 mb-1">Send hour (UTC)</label>
              <select
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={form.send_hour ?? 9}
                onChange={(e) => setForm({ ...form, send_hour: Number(e.target.value) })}
              >
                {Array.from({ length: 24 }, (_, i) => (
                  <option key={i} value={i}>{String(i).padStart(2, "0")}:00</option>
                ))}
              </select>
              <p className="text-xs text-gray-400 mt-1">Outreach runs hourly — only sends when the clock matches this hour (UTC).</p>
            </div>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : editingCampaign ? "Save changes" : "Create campaign"}
            </Button>
          </div>
        </div>
      </Modal>
    </AppShell>
  );
}
