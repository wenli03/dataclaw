import React, { useMemo, useState } from "react";
import { MessageSquare, Pencil, Pin, PinOff, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import type { SessionItem } from "../../lib/types";
import { cx, timeAgo } from "../../lib/format";
import { Avatar, Empty, Skeleton } from "../ui";

export function SessionList({
  sessions,
  activeId,
  loading,
  error,
  creating,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  onTogglePin,
  onRetry,
  onClose,
}: {
  sessions: SessionItem[];
  activeId?: string;
  loading: boolean;
  error: string;
  creating?: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onTogglePin: (id: string, pinned: boolean) => void;
  onRetry: () => void;
  onClose?: () => void;
}) {
  const [keyword, setKeyword] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const list = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return [...sessions]
      .filter((s) => !kw || (s.title || "").toLowerCase().includes(kw) || (s.employeeName || "").toLowerCase().includes(kw))
      .sort((a, b) => {
        if (Boolean(a.pinned) !== Boolean(b.pinned)) return a.pinned ? -1 : 1;
        return new Date(b.lastMessageAt || 0).getTime() - new Date(a.lastMessageAt || 0).getTime();
      });
  }, [sessions, keyword]);

  const commitRename = (id: string) => {
    const title = draft.trim();
    if (title) onRename(id, title);
    setEditingId(null);
  };

  return (
    <aside className="flex h-full w-[264px] shrink-0 flex-col border-r border-surface-200 bg-white">
      <div className="flex items-center gap-2 px-3 pb-2 pt-3">
        <div className="text-[13px] font-semibold text-ink-900">会话</div>
        <span className="text-[11px] text-ink-400">{sessions.length}</span>
        {onClose && (
          <button onClick={onClose} className="ml-auto rounded-lg p-1 text-ink-400 hover:bg-surface-100 hover:text-ink-700 lg:hidden">
            <X size={15} />
          </button>
        )}
      </div>

      <div className="space-y-1.5 px-3 pb-2">
        <button
          onClick={onCreate}
          disabled={creating}
          className="btn-outline w-full !justify-start !py-1.5 !text-[12.5px]"
        >
          {creating ? <RefreshCw size={13} className="animate-spin" /> : <Plus size={13} />}
          新建会话
        </button>
        <div className="relative">
          <Search size={12} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索会话"
            className="input !py-1.5 !pl-7 !text-[12px]"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {loading ? (
          <div className="space-y-2 px-1 py-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-2 rounded-xl p-2">
                <Skeleton className="h-7 w-7 shrink-0 rounded-full" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-2.5 w-3/4" />
                  <Skeleton className="h-2 w-1/2" />
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          <Empty
            title="会话加载失败"
            desc={error}
            icon={<MessageSquare size={18} />}
            action={
              <button onClick={onRetry} className="btn-outline !py-1.5 !text-[12px]">
                <RefreshCw size={12} /> 重试
              </button>
            }
          />
        ) : list.length === 0 ? (
          <Empty
            title={keyword ? "没有匹配的会话" : "还没有会话"}
            desc={keyword ? "换个关键词试试" : "新建会话，让数字员工开始干活"}
            icon={<MessageSquare size={18} />}
          />
        ) : (
          <div className="space-y-0.5">
            {list.map((s) => {
              const active = s.id === activeId;
              return (
                <div
                  key={s.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect(s.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(s.id);
                    }
                  }}
                  className={cx(
                    "group relative flex cursor-pointer items-start gap-2 rounded-xl border px-2 py-2 transition",
                    active
                      ? "border-brand-100 bg-brand-50"
                      : "border-transparent hover:border-surface-200 hover:bg-surface-50"
                  )}
                >
                  <Avatar name={s.employeeName || s.title} seed={s.employeeAvatar || s.employeeId} size={26} className="mt-0.5" />
                  <div className="min-w-0 flex-1">
                    {editingId === s.id ? (
                      <input
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                        onBlur={() => commitRename(s.id)}
                        onKeyDown={(e) => {
                          e.stopPropagation();
                          if (e.key === "Enter") commitRename(s.id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        className="w-full rounded border border-brand-300 bg-white px-1 py-0.5 text-[12px] outline-none"
                      />
                    ) : (
                      <div className={cx("truncate text-[12.5px] leading-5", active ? "font-medium text-brand-800" : "text-ink-800")}>
                        {s.pinned && <Pin size={10} className="mr-1 inline-block align-[-1px] text-brand-500" />}
                        {s.title || "未命名会话"}
                      </div>
                    )}
                    <div className="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-ink-400">
                      <span>{timeAgo(s.lastMessageAt)}</span>
                      <span>·</span>
                      <span>{s.messageCount ?? 0} 条</span>
                    </div>
                  </div>

                  <div className="absolute right-1.5 top-1.5 flex items-center gap-0.5 rounded-lg bg-white/90 p-0.5 opacity-0 shadow-sm transition group-hover:opacity-100">
                    <button
                      title={s.pinned ? "取消置顶" : "置顶"}
                      onClick={(e) => {
                        e.stopPropagation();
                        onTogglePin(s.id, !s.pinned);
                      }}
                      className="rounded p-1 text-ink-400 hover:bg-surface-100 hover:text-brand-600"
                    >
                      {s.pinned ? <PinOff size={11} /> : <Pin size={11} />}
                    </button>
                    <button
                      title="重命名"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(s.id);
                        setDraft(s.title || "");
                      }}
                      className="rounded p-1 text-ink-400 hover:bg-surface-100 hover:text-ink-800"
                    >
                      <Pencil size={11} />
                    </button>
                    <button
                      title="删除"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(s.id);
                      }}
                      className="rounded p-1 text-ink-400 hover:bg-rose-50 hover:text-rose-600"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}

export default SessionList;
