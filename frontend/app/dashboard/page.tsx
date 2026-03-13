"use client";

import { useEffect, useState } from "react";
import { getLeadStats } from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";

const PIPELINE_STAGES = ["imported", "scored", "contacted", "replied", "booked"];
const STAGE_LABELS: Record<string, string> = {
  imported: "Imported",
  scored: "Scored",
  contacted: "Contacted",
  replied: "Replied",
  booked: "Booked",
};
const STAGE_COLORS: Record<string, string> = {
  imported: "bg-gray-400",
  scored: "bg-blue-500",
  contacted: "bg-yellow-500",
  replied: "bg-purple-500",
  booked: "bg-green-500",
};

export default function DashboardPage() {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getLeadStats()
      .then((data) => setCounts(data.status_counts))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const contacted = counts.contacted ?? 0;
  const replied = counts.replied ?? 0;
  const booked = counts.booked ?? 0;

  const stats = [
    { label: "Total Leads", value: total, color: "text-gray-900" },
    { label: "Contacted", value: contacted, color: "text-yellow-600" },
    { label: "Replied", value: replied, color: "text-purple-600" },
    { label: "Meetings Booked", value: booked, color: "text-green-600" },
  ];

  return (
    <AppShell>
      <div className="p-8 max-w-5xl">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Dashboard</h1>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {stats.map(({ label, value, color }) => (
            <div key={label} className="bg-white rounded-xl border border-gray-200 p-5">
              <p className="text-sm text-gray-500">{label}</p>
              <p className={`text-3xl font-bold mt-1 ${color}`}>
                {loading ? "—" : value}
              </p>
            </div>
          ))}
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">Lead Pipeline</h2>
          <div className="space-y-3">
            {PIPELINE_STAGES.map((stage) => {
              const count = counts[stage] ?? 0;
              const pct = total > 0 ? Math.round((count / total) * 100) : 0;
              return (
                <div key={stage} className="flex items-center gap-4">
                  <span className="w-24 text-sm text-gray-600 text-right">{STAGE_LABELS[stage]}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-5 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${STAGE_COLORS[stage]}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="w-16 text-sm text-gray-700 font-medium">
                    {loading ? "—" : `${count} (${pct}%)`}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
