"use client";

import { useEffect, useState } from "react";
import {
  getOutreachAccounts,
  createOutreachAccount,
  updateOutreachAccount,
  deleteOutreachAccount,
  testOutreachAccountConnection,
  OutreachAccount,
  OutreachAccountCreate,
} from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Badge } from "@/components/ui/badge";
import { Plus, Pencil, Trash2, Zap, Eye, EyeOff, CheckCircle, XCircle } from "lucide-react";

const MAX_ACCOUNTS = 5;

const EMPTY_FORM: OutreachAccountCreate = {
  display_name: "",
  smtp_host: "smtp.hostinger.com",
  smtp_port: 587,
  smtp_user: "",
  smtp_pass: "",
  imap_host: "imap.hostinger.com",
  imap_port: 993,
  from_name: "",
  from_email: "",
  daily_limit: 40,
};

export default function OutreachAccountsPage() {
  const [accounts, setAccounts] = useState<OutreachAccount[]>([]);
  const [loading, setLoading] = useState(true);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<OutreachAccountCreate & { is_active?: boolean }>({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [showPass, setShowPass] = useState(false);

  const [testResult, setTestResult] = useState<{ smtp: string; imap: string; error?: string } | null>(null);
  const [testing, setTesting] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const data = await getOutreachAccounts();
      setAccounts(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function openAdd() {
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
    setTestResult(null);
    setSaveError(null);
    setSaveSuccess(false);
    setShowPass(false);
    setModalOpen(true);
  }

  function openEdit(account: OutreachAccount) {
    setEditingId(account.id);
    setForm({
      display_name: account.display_name,
      smtp_host: account.smtp_host,
      smtp_port: account.smtp_port,
      smtp_user: account.smtp_user,
      smtp_pass: "",
      imap_host: account.imap_host,
      imap_port: account.imap_port,
      from_name: account.from_name,
      from_email: account.from_email,
      daily_limit: account.daily_limit,
      is_active: account.is_active,
    });
    setTestResult(null);
    setSaveError(null);
    setSaveSuccess(false);
    setShowPass(false);
    setModalOpen(true);
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      if (editingId) {
        const update: Record<string, unknown> = {
          display_name: form.display_name,
          daily_limit: form.daily_limit,
          is_active: form.is_active,
          smtp_host: form.smtp_host,
          smtp_port: form.smtp_port,
          imap_host: form.imap_host,
          imap_port: form.imap_port,
        };
        if (form.smtp_pass) update.smtp_pass = form.smtp_pass;
        await updateOutreachAccount(editingId, update);
      } else {
        await createOutreachAccount(form);
      }
      setSaveSuccess(true);
      await load();
      setTimeout(() => {
        setModalOpen(false);
        setSaveSuccess(false);
      }, 1200);
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "error" in e
          ? String((e as { error: string }).error)
          : "Failed to save account. Check your details and try again.";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this email account? Leads assigned to it will become unassigned.")) return;
    await deleteOutreachAccount(id);
    await load();
  }

  async function handleTest() {
    if (!editingId) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testOutreachAccountConnection(editingId);
      setTestResult(result);
    } catch (e) {
      setTestResult({ smtp: "failed", imap: "failed", error: String(e) });
    } finally {
      setTesting(false);
    }
  }

  const atMax = accounts.length >= MAX_ACCOUNTS;

  return (
    <AppShell>
      <div className="p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Email Accounts</h1>
          <div title={atMax ? `Maximum ${MAX_ACCOUNTS} accounts allowed` : undefined}>
            <Button onClick={openAdd} disabled={atMax}>
              <Plus size={16} /> Add Account
            </Button>
          </div>
        </div>

        {loading ? (
          <p className="text-gray-400 text-sm">Loading…</p>
        ) : accounts.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 p-12 text-center text-gray-400">
            <p className="text-sm">No email accounts configured.</p>
            <p className="text-xs mt-1">Add up to {MAX_ACCOUNTS} Hostinger (or other SMTP/IMAP) accounts.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {accounts.map((account) => (
              <div key={account.id} className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
                {/* Card header */}
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-semibold text-gray-900">{account.display_name}</p>
                    <p className="text-sm text-gray-500">{account.from_email}</p>
                  </div>
                  <Badge variant={account.is_active ? "green" : "gray"}>
                    {account.is_active ? "Active" : "Inactive"}
                  </Badge>
                </div>

                {/* Daily progress */}
                <div>
                  <div className="flex justify-between text-xs text-gray-500 mb-1">
                    <span>Leads today</span>
                    <span>{account.leads_assigned} / {account.daily_limit}</span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-1.5">
                    <div
                      className="bg-indigo-500 h-1.5 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (account.leads_assigned / account.daily_limit) * 100)}%` }}
                    />
                  </div>
                </div>

                {/* SMTP host */}
                <p className="text-xs text-gray-400">{account.smtp_host}:{account.smtp_port}</p>

                {/* Actions */}
                <div className="flex gap-2 pt-1">
                  <Button variant="secondary" size="sm" onClick={() => openEdit(account)}>
                    <Pencil size={14} /> Edit
                  </Button>
                  <button
                    onClick={() => handleDelete(account.id)}
                    className="text-gray-300 hover:text-red-500 transition-colors ml-auto"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add / Edit Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingId ? "Edit Email Account" : "Add Email Account"}
        maxWidth="max-w-2xl"
      >
        <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
          {/* Display name */}
          <Input
            label="Display Name"
            placeholder="e.g. Primary Outreach"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
          />

          {/* From */}
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="From Name"
              placeholder="Your Name"
              value={form.from_name}
              onChange={(e) => setForm({ ...form, from_name: e.target.value })}
            />
            <Input
              label="From Email"
              placeholder="you@example.com"
              value={form.from_email}
              onChange={(e) => setForm({ ...form, from_email: e.target.value })}
            />
          </div>

          {/* SMTP */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <Input
                label="SMTP Host"
                placeholder="smtp.hostinger.com"
                value={form.smtp_host}
                onChange={(e) => setForm({ ...form, smtp_host: e.target.value })}
              />
            </div>
            <Input
              label="SMTP Port"
              type="number"
              value={String(form.smtp_port)}
              onChange={(e) => setForm({ ...form, smtp_port: Number(e.target.value) })}
            />
          </div>

          {/* SMTP credentials */}
          <Input
            label="SMTP Username"
            placeholder="you@example.com"
            value={form.smtp_user}
            onChange={(e) => setForm({ ...form, smtp_user: e.target.value })}
          />
          <div className="relative">
            <Input
              label={editingId ? "SMTP Password (leave blank to keep current)" : "SMTP Password"}
              type={showPass ? "text" : "password"}
              placeholder={editingId ? "••••••••" : "Enter password"}
              value={form.smtp_pass}
              onChange={(e) => setForm({ ...form, smtp_pass: e.target.value })}
            />
            <button
              type="button"
              onClick={() => setShowPass(!showPass)}
              className="absolute right-3 top-8 text-gray-400 hover:text-gray-600"
            >
              {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>

          {/* IMAP */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <Input
                label="IMAP Host"
                placeholder="imap.hostinger.com"
                value={form.imap_host}
                onChange={(e) => setForm({ ...form, imap_host: e.target.value })}
              />
            </div>
            <Input
              label="IMAP Port"
              type="number"
              value={String(form.imap_port)}
              onChange={(e) => setForm({ ...form, imap_port: Number(e.target.value) })}
            />
          </div>

          {/* Daily limit + Active */}
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Daily Lead Limit"
              type="number"
              value={String(form.daily_limit)}
              onChange={(e) => setForm({ ...form, daily_limit: Math.min(40, Number(e.target.value)) })}
            />
            {editingId && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-gray-600">Active</label>
                <button
                  type="button"
                  onClick={() => setForm({ ...form, is_active: !form.is_active })}
                  className={`mt-1 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    form.is_active
                      ? "bg-green-50 border-green-200 text-green-700"
                      : "bg-gray-50 border-gray-200 text-gray-500"
                  }`}
                >
                  {form.is_active ? "Active" : "Inactive"}
                </button>
              </div>
            )}
          </div>

          {/* Test connection (only for existing accounts) */}
          {editingId && (
            <div className="border-t border-gray-100 pt-3">
              <div className="flex items-center gap-3 flex-wrap">
                <Button variant="secondary" size="sm" onClick={handleTest} disabled={testing}>
                  <Zap size={14} /> {testing ? "Testing…" : "Test Connection"}
                </Button>
                {testResult && (
                  <div className="flex items-center gap-3 text-sm">
                    <span className={`flex items-center gap-1 ${testResult.smtp === "ok" ? "text-green-600" : "text-red-600"}`}>
                      {testResult.smtp === "ok" ? <CheckCircle size={14} /> : <XCircle size={14} />}
                      SMTP
                    </span>
                    <span className={`flex items-center gap-1 ${testResult.imap === "ok" ? "text-green-600" : "text-red-600"}`}>
                      {testResult.imap === "ok" ? <CheckCircle size={14} /> : <XCircle size={14} />}
                      IMAP
                    </span>
                    {testResult.error && (
                      <span className="text-red-500 text-xs">{testResult.error}</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {saveError && (
          <div className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            <XCircle size={16} className="mt-0.5 shrink-0" />
            {saveError}
          </div>
        )}
        {saveSuccess && (
          <div className="mt-3 flex items-center gap-2 rounded-lg bg-green-50 border border-green-200 px-3 py-2 text-sm text-green-700">
            <CheckCircle size={16} className="shrink-0" />
            Account {editingId ? "updated" : "added"} successfully.
          </div>
        )}

        <div className="flex gap-2 justify-end mt-4 pt-4 border-t border-gray-100">
          <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving || !form.display_name || !form.from_email}>
            {saving ? "Saving…" : editingId ? "Save Changes" : "Add Account"}
          </Button>
        </div>
      </Modal>
    </AppShell>
  );
}
