"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  useCopilotKit,
  useThreads,
} from "@copilotkit/react-core/v2";
import { Archive, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { shortId } from "@/lib/format";

type ThreadEndpoints = { list?: boolean; mutations?: boolean };

export function ConversationHistory({
  activeThreadId,
  onNavigate,
}: {
  activeThreadId: string;
  onNavigate?: (id: string) => void;
}) {
  const router = useRouter();
  const { copilotkit } = useCopilotKit();
  const threadEndpoints = (copilotkit as unknown as { threadEndpoints?: ThreadEndpoints })
    .threadEndpoints;
  const canList = threadEndpoints?.list === true;
  const canMutate = threadEndpoints?.mutations === true;

  const [includeArchived, setIncludeArchived] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");

  const {
    threads,
    isLoading,
    listError,
    isMutating,
    renameThread,
    archiveThread,
    unarchiveThread,
    deleteThread,
    fetchMoreThreads,
    hasMoreThreads,
    isFetchingMoreThreads,
    refetchThreads,
  } = useThreads({
    agentId: "marketmesh_orchestrator",
    enabled: canList,
    includeArchived,
    limit: 20,
  });

  if (!canList) return null;

  const navigate = (id: string) => {
    if (onNavigate) onNavigate(id);
    else router.push(`/runs/${id}`);
  };

  const commitRename = async (id: string) => {
    const name = draftName.trim();
    if (name) await renameThread(id, name);
    setEditingId(null);
  };

  return (
    <nav className="mm-conversation-history" aria-label="Conversation history">
      <header className="mm-conversation-history-head">
        <span className="mm-kicker">Conversations</span>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => navigate(crypto.randomUUID())}
          aria-label="New conversation"
        >
          <Plus size={13} aria-hidden="true" />
        </Button>
      </header>

      {isLoading ? <p className="mm-muted">Loading…</p> : null}
      {listError ? (
        <div className="mm-alert" role="alert">
          <span>{listError.message}</span>
          <Button size="sm" variant="ghost" onClick={() => refetchThreads()}>
            Retry
          </Button>
        </div>
      ) : null}

      {threads.length === 0 && !isLoading && !listError ? (
        <p className="mm-muted">No conversations yet. Start a run.</p>
      ) : null}

      <ul className="mm-conversation-list">
        {threads.map((t) => {
          const active = t.id === activeThreadId;
          return (
            <li key={t.id} className={active ? "is-active" : undefined}>
              {editingId === t.id ? (
                <input
                  className="mm-conversation-rename"
                  value={draftName}
                  autoFocus
                  onChange={(e) => setDraftName(e.target.value)}
                  onBlur={() => void commitRename(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void commitRename(t.id);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                  aria-label="Rename conversation"
                />
              ) : (
                <button
                  type="button"
                  className="mm-conversation-row"
                  aria-current={active ? "page" : undefined}
                  onClick={() => navigate(t.id)}
                >
                  <span className="mm-conversation-name">
                    {t.name ?? shortId(t.id, 8)}
                  </span>
                  <span className="mm-conversation-time">
                    {t.lastRunAt ?? t.updatedAt}
                  </span>
                </button>
              )}
              {canMutate ? (
                <div className="mm-conversation-actions">
                  <button
                    type="button"
                    aria-label="Rename"
                    onClick={() => {
                      setEditingId(t.id);
                      setDraftName(t.name ?? "");
                    }}
                  >
                    <Pencil size={12} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={t.archived ? "Unarchive" : "Archive"}
                    onClick={() =>
                      t.archived ? unarchiveThread(t.id) : archiveThread(t.id)
                    }
                  >
                    <Archive size={12} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label="Delete"
                    onClick={() => {
                      if (window.confirm("Delete this conversation?")) {
                        void deleteThread(t.id).then(() => {
                          if (t.id === activeThreadId) router.push("/runs");
                        });
                      }
                    }}
                  >
                    <Trash2 size={12} aria-hidden="true" />
                  </button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      {hasMoreThreads ? (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => fetchMoreThreads()}
          disabled={isFetchingMoreThreads}
        >
          {isFetchingMoreThreads ? "Loading…" : "Load more"}
        </Button>
      ) : null}

      <label className="mm-conversation-archived-toggle">
        <input
          type="checkbox"
          checked={includeArchived}
          onChange={(e) => setIncludeArchived(e.target.checked)}
        />
        Show archived
      </label>
    </nav>
  );
}
