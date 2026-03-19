"use client";

import { useEffect, useState } from "react";
import { getAdminUsers, createAdminUser, toggleAdminUser, deleteAdminUser, runSmokeTest, AdminUser } from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Plus, Trash2, CheckCircle, XCircle, ShieldCheck } from "lucide-react";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [smokeResults, setSmokeResults] = useState<null | { passed: number; failed: number; results: Array<{ check: string; passed: boolean; error?: string; detail?: string }> }>(null);
  const [smokeTesting, setSmokeTesting] = useState(false);

  useEffect(() => { fetchUsers(); }, []);

  async function fetchUsers() {
    setLoading(true);
    try {
      setUsers(await getAdminUsers());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate() {
    if (!email.trim() || !password.trim()) { setFormError("Email and password are required"); return; }
    setSaving(true);
    setFormError("");
    try {
      await createAdminUser(email.trim(), password);
      setModalOpen(false);
      setEmail("");
      setPassword("");
      fetchUsers();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Failed to create user";
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle(user: AdminUser) {
    try {
      await toggleAdminUser(user.id, !user.is_active);
      fetchUsers();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Action failed";
      alert(msg);
    }
  }

  async function handleDelete(user: AdminUser) {
    if (!confirm(`Delete user ${user.email}?`)) return;
    try {
      await deleteAdminUser(user.id);
      fetchUsers();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Delete failed";
      alert(msg);
    }
  }

  async function handleSmokeTest() {
    setSmokeTesting(true);
    setSmokeResults(null);
    try {
      const res = await runSmokeTest();
      setSmokeResults(res);
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "error" in e ? String((e as { error: string }).error) : "Smoke test failed";
      alert(msg);
    } finally {
      setSmokeTesting(false);
    }
  }

  return (
    <AppShell>
      <div className="p-8 space-y-8">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">User Management</h1>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={handleSmokeTest} disabled={smokeTesting}>
              <ShieldCheck size={16} />
              {smokeTesting ? "Testing…" : "Run Smoke Test"}
            </Button>
            <Button onClick={() => { setModalOpen(true); setFormError(""); setEmail(""); setPassword(""); }}>
              <Plus size={16} /> Invite User
            </Button>
          </div>
        </div>

        {/* Users table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 text-left">
                <th className="px-4 py-3 font-medium text-gray-600">Email</th>
                <th className="px-4 py-3 font-medium text-gray-600">Role</th>
                <th className="px-4 py-3 font-medium text-gray-600">Status</th>
                <th className="px-4 py-3 font-medium text-gray-600">Joined</th>
                <th className="px-4 py-3 font-medium text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">Loading…</td></tr>
              ) : (
                users.map((u) => (
                  <tr key={u.id} className="border-b border-gray-50">
                    <td className="px-4 py-3 text-gray-900">{u.email}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${u.role === "admin" ? "bg-purple-100 text-purple-700" : "bg-gray-100 text-gray-600"}`}>
                        {u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${u.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      {u.role !== "admin" && (
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleToggle(u)}
                            title={u.is_active ? "Deactivate" : "Activate"}
                            className={`p-1.5 rounded-lg transition-colors ${u.is_active ? "text-red-400 hover:text-red-600 hover:bg-red-50" : "text-green-500 hover:text-green-700 hover:bg-green-50"}`}
                          >
                            {u.is_active ? <XCircle size={16} /> : <CheckCircle size={16} />}
                          </button>
                          <button
                            onClick={() => handleDelete(u)}
                            title="Delete user"
                            className="p-1.5 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Smoke test results */}
        {smokeResults && (
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center gap-3 mb-4">
              <h2 className="font-semibold text-gray-900">Smoke Test Results</h2>
              <span className={`text-sm font-medium ${smokeResults.failed === 0 ? "text-green-600" : "text-red-600"}`}>
                {smokeResults.passed} passed / {smokeResults.failed} failed
              </span>
            </div>
            <div className="space-y-2">
              {smokeResults.results.map((r) => (
                <div key={r.check} className="flex items-center gap-3 text-sm">
                  {r.passed
                    ? <CheckCircle size={16} className="text-green-500 shrink-0" />
                    : <XCircle size={16} className="text-red-500 shrink-0" />}
                  <span className="font-mono text-gray-700">{r.check}</span>
                  {r.detail && <span className="text-gray-500">— {r.detail}</span>}
                  {r.error && <span className="text-red-500 text-xs">— {r.error}</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="Invite User"
        maxWidth="max-w-sm"
      >
        <div className="space-y-3">
          <Input
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="user@example.com"
          />
          <Input
            label="Temporary password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
          {formError && <p className="text-sm text-red-600">{formError}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={saving}>
              {saving ? "Creating…" : "Create user"}
            </Button>
          </div>
        </div>
      </Modal>
    </AppShell>
  );
}
