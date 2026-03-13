"use client";

import { useEffect, useState } from "react";
import { getCampaigns, createCampaign, updateCampaign, startCampaign, pauseCampaign, Campaign } from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { StatusBadge } from "@/components/ui/badge";
import { Plus, Play, Pause, Pencil } from "lucide-react";

const EMPTY_FORM: Partial<Campaign> = {
  name: "",
  sender_name: "",
  sender_email: "",
  sender_company: "",
  calendly_link: "",
  target_industry: "",
  daily_limit: 30,
  min_score: 50,
};

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingCampaign, setEditingCampaign] = useState<Campaign | null>(null);
  const [form, setForm] = useState<Partial<Campaign>>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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
      sender_name: campaign.sender_name,
      sender_email: campaign.sender_email,
      sender_company: campaign.sender_company,
      calendly_link: campaign.calendly_link,
      target_industry: campaign.target_industry,
      daily_limit: campaign.daily_limit,
      min_score: campaign.min_score,
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

  async function toggleCampaign(campaign: Campaign) {
    try {
      if (campaign.status === "active") {
        await pauseCampaign(campaign.id);
      } else {
        await startCampaign(campaign.id);
      }
      fetchCampaigns();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Action failed";
      alert(msg);
    }
  }

  return (
    <AppShell>
      <div className="p-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Campaigns</h1>
          <Button onClick={openNew}>
            <Plus size={16} /> New Campaign
          </Button>
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
                <th className="px-4 py-3 font-medium text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">Loading…</td></tr>
              ) : campaigns.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No campaigns yet. Create one to get started.</td></tr>
              ) : (
                campaigns.map((c) => (
                  <tr key={c.id} className="border-b border-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">{c.name}</td>
                    <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                    <td className="px-4 py-3 text-gray-600">{c.sender_name ?? "—"}</td>
                    <td className="px-4 py-3 text-gray-600">{c.min_score}</td>
                    <td className="px-4 py-3 text-gray-600">{c.daily_limit}/day</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => toggleCampaign(c)}
                          title={c.status === "active" ? "Pause" : "Start"}
                          className={`p-1.5 rounded-lg transition-colors ${
                            c.status === "active"
                              ? "text-yellow-600 hover:bg-yellow-50"
                              : "text-green-600 hover:bg-green-50"
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
                      </div>
                    </td>
                  </tr>
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
        maxWidth="max-w-xl"
      >
        <div className="space-y-3">
          <Input label="Campaign name *" value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Q1 SaaS Outreach" />

          <div className="grid grid-cols-2 gap-3">
            <Input label="Sender name" value={form.sender_name ?? ""} onChange={(e) => setForm({ ...form, sender_name: e.target.value })} placeholder="Jane Smith" />
            <Input label="Sender email" type="email" value={form.sender_email ?? ""} onChange={(e) => setForm({ ...form, sender_email: e.target.value })} placeholder="jane@company.com" />
            <Input label="Sender company" value={form.sender_company ?? ""} onChange={(e) => setForm({ ...form, sender_company: e.target.value })} placeholder="Acme Corp" />
            <Input label="Target industry" value={form.target_industry ?? ""} onChange={(e) => setForm({ ...form, target_industry: e.target.value })} placeholder="SaaS" />
            <Input label="Min score" type="number" min={0} max={100} value={form.min_score ?? 50} onChange={(e) => setForm({ ...form, min_score: Number(e.target.value) })} />
            <Input label="Daily limit" type="number" min={1} max={500} value={form.daily_limit ?? 30} onChange={(e) => setForm({ ...form, daily_limit: Number(e.target.value) })} />
          </div>

          <Input label="Calendly link" value={form.calendly_link ?? ""} onChange={(e) => setForm({ ...form, calendly_link: e.target.value })} placeholder="https://calendly.com/you/30min" />

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
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
