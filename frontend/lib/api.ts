const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (res.status === 401) {
    if (typeof window !== "undefined") {
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: "Request failed" }));
    throw error;
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export const login = (email: string, password: string) =>
  apiFetch<{ access_token: string; token_type: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const register = (email: string, password: string) =>
  apiFetch<{ id: string; email: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

// ── Leads ─────────────────────────────────────────────────────────────────────
export interface Lead {
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  company?: string;
  title?: string;
  website?: string;
  industry?: string;
  company_size?: string;
  source: string;
  status: string;
  score?: number;
  score_reason?: string;
  custom_offer?: string;
  created_at: string;
  messages: Message[];
  conversations: Conversation[];
}

export interface Message {
  id: string;
  lead_id: string;
  type?: string;
  subject?: string;
  body?: string;
  status: string;
  sent_at?: string;
  provider_message_id?: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  lead_id: string;
  status: string;
  sentiment?: string;
  thread: Array<{ role: string; content: string; timestamp: string }>;
  created_at: string;
  updated_at: string;
}

export interface ConversationWithLead extends Conversation {
  lead?: {
    id: string;
    email: string;
    first_name?: string;
    last_name?: string;
    company?: string;
  };
}

export interface PaginatedLeads {
  items: Partial<Lead>[];
  total: number;
  page: number;
  page_size: number;
}

export const getLeads = (params?: { page?: number; page_size?: number; status?: string; min_score?: number }) => {
  const qs = new URLSearchParams();
  if (params?.page) qs.set("page", String(params.page));
  if (params?.page_size) qs.set("page_size", String(params.page_size));
  if (params?.status) qs.set("status", params.status);
  if (params?.min_score !== undefined) qs.set("min_score", String(params.min_score));
  return apiFetch<PaginatedLeads>(`/leads?${qs}`);
};

export const getLead = (id: string) => apiFetch<Lead>(`/leads/${id}`);

export const updateLead = (id: string, data: Partial<Lead>) =>
  apiFetch<Lead>(`/leads/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const deleteLead = (id: string) =>
  apiFetch<void>(`/leads/${id}`, { method: "DELETE" });

export const importLeads = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  return fetch(`${API_URL}/leads/import`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  }).then((r) => r.json()) as Promise<{ imported: number; skipped: number; errors: string[] }>;
};

export const getLeadStats = () =>
  apiFetch<{ status_counts: Record<string, number> }>("/leads/stats");

// ── Campaigns ─────────────────────────────────────────────────────────────────
export interface Campaign {
  id: string;
  name: string;
  status: string;
  sender_name?: string;
  sender_email?: string;
  sender_company?: string;
  daily_limit: number;
  min_score: number;
  target_industry?: string;
  calendly_link?: string;
  created_at: string;
  lead_count: number;
}

export const getCampaigns = () => apiFetch<Campaign[]>("/campaigns");

export const getCampaign = (id: string) => apiFetch<Campaign>(`/campaigns/${id}`);

export const createCampaign = (data: Partial<Campaign>) =>
  apiFetch<Campaign>("/campaigns", { method: "POST", body: JSON.stringify(data) });

export const updateCampaign = (id: string, data: Partial<Campaign>) =>
  apiFetch<Campaign>(`/campaigns/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const startCampaign = (id: string) =>
  apiFetch<Campaign>(`/campaigns/${id}/start`, { method: "POST" });

export const pauseCampaign = (id: string) =>
  apiFetch<Campaign>(`/campaigns/${id}/pause`, { method: "POST" });

// ── Conversations ──────────────────────────────────────────────────────────────
export const getConversations = () =>
  apiFetch<ConversationWithLead[]>("/conversations");

export const getConversation = (id: string) =>
  apiFetch<ConversationWithLead>(`/conversations/${id}`);

export const updateConversation = (id: string, data: { status?: string; sentiment?: string }) =>
  apiFetch<ConversationWithLead>(`/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const replyToConversation = (id: string, body: string) =>
  apiFetch<ConversationWithLead>(`/conversations/${id}/reply`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });

// ── Jobs ───────────────────────────────────────────────────────────────────────
export const triggerScoreJob = () =>
  apiFetch<{ ok: boolean; job: string }>("/jobs/score", { method: "POST" });

export const triggerOutreachJob = () =>
  apiFetch<{ ok: boolean; job: string }>("/jobs/outreach", { method: "POST" });
