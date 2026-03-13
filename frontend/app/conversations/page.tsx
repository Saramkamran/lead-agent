"use client";

import { useEffect, useState } from "react";
import {
  getConversations,
  updateConversation,
  replyToConversation,
  ConversationWithLead,
} from "@/lib/api";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { SentimentBadge, StatusBadge } from "@/components/ui/badge";
import { UserCheck, Send } from "lucide-react";

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<ConversationWithLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<ConversationWithLead | null>(null);
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    getConversations()
      .then(setConversations)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  async function handleTakeOver(conv: ConversationWithLead) {
    try {
      const updated = await updateConversation(conv.id, { status: "manual" });
      setConversations((cs) => cs.map((c) => (c.id === updated.id ? updated : c)));
      if (selected?.id === updated.id) setSelected(updated);
    } catch (e) {
      console.error(e);
    }
  }

  async function handleSendReply() {
    if (!selected || !replyText.trim()) return;
    setSending(true);
    try {
      const updated = await replyToConversation(selected.id, replyText.trim());
      setConversations((cs) => cs.map((c) => (c.id === updated.id ? updated : c)));
      setSelected(updated);
      setReplyText("");
    } catch (e) {
      console.error(e);
    } finally {
      setSending(false);
    }
  }

  function lastMessage(conv: ConversationWithLead) {
    if (!conv.thread?.length) return "";
    const last = conv.thread[conv.thread.length - 1];
    return last.content.slice(0, 80) + (last.content.length > 80 ? "…" : "");
  }

  function leadName(conv: ConversationWithLead) {
    if (!conv.lead) return conv.lead_id;
    const { first_name, last_name, email } = conv.lead;
    return [first_name, last_name].filter(Boolean).join(" ") || email;
  }

  return (
    <AppShell>
      <div className="flex h-[calc(100vh-0px)]">
        {/* Conversation list */}
        <div className="w-80 flex-shrink-0 border-r border-gray-200 bg-white overflow-y-auto">
          <div className="px-4 py-4 border-b border-gray-100">
            <h1 className="text-lg font-bold text-gray-900">Conversations</h1>
          </div>
          {loading ? (
            <div className="px-4 py-8 text-sm text-gray-400 text-center">Loading…</div>
          ) : conversations.length === 0 ? (
            <div className="px-4 py-8 text-sm text-gray-400 text-center">No conversations yet.</div>
          ) : (
            conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => { setSelected(conv); setReplyText(""); }}
                className={`w-full text-left px-4 py-3 border-b border-gray-50 hover:bg-gray-50 transition-colors ${
                  selected?.id === conv.id ? "bg-indigo-50 border-l-2 border-l-indigo-500" : ""
                }`}
              >
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-sm font-medium text-gray-900 truncate">{leadName(conv)}</span>
                  <SentimentBadge sentiment={conv.sentiment} />
                </div>
                {conv.lead?.company && (
                  <p className="text-xs text-gray-500 mb-1">{conv.lead.company}</p>
                )}
                <p className="text-xs text-gray-400 truncate">{lastMessage(conv)}</p>
                <div className="flex items-center gap-2 mt-1">
                  <StatusBadge status={conv.status} />
                  <span className="text-xs text-gray-300">
                    {new Date(conv.updated_at).toLocaleDateString()}
                  </span>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Thread view */}
        <div className="flex-1 flex flex-col bg-gray-50">
          {!selected ? (
            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
              Select a conversation
            </div>
          ) : (
            <>
              {/* Thread header */}
              <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
                <div>
                  <h2 className="font-semibold text-gray-900">{leadName(selected)}</h2>
                  {selected.lead?.company && (
                    <p className="text-sm text-gray-500">{selected.lead.company}</p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <SentimentBadge sentiment={selected.sentiment} />
                  <StatusBadge status={selected.status} />
                  {selected.status === "active" && (
                    <Button variant="secondary" size="sm" onClick={() => handleTakeOver(selected)}>
                      <UserCheck size={14} /> Take over
                    </Button>
                  )}
                </div>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
                {selected.thread.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center">No messages yet.</p>
                ) : (
                  selected.thread.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === "agent" ? "justify-end" : "justify-start"}`}>
                      <div
                        className={`max-w-[70%] rounded-2xl px-4 py-2.5 text-sm ${
                          msg.role === "agent"
                            ? "bg-indigo-600 text-white rounded-br-sm"
                            : "bg-white text-gray-900 border border-gray-200 rounded-bl-sm"
                        }`}
                      >
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                        <p className={`text-xs mt-1 ${msg.role === "agent" ? "text-indigo-200" : "text-gray-400"}`}>
                          {new Date(msg.timestamp).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Manual reply input — only shown when status=manual */}
              {selected.status === "manual" && (
                <div className="bg-white border-t border-gray-200 px-6 py-4">
                  <div className="flex gap-2">
                    <textarea
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      placeholder="Type your reply…"
                      rows={3}
                      className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handleSendReply();
                      }}
                    />
                    <Button onClick={handleSendReply} disabled={!replyText.trim() || sending} className="self-end">
                      <Send size={16} /> {sending ? "Sending…" : "Send"}
                    </Button>
                  </div>
                  <p className="text-xs text-gray-400 mt-1">Ctrl+Enter to send</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
