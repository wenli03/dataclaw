import React from "react";
import { AlertCircle } from "lucide-react";
import type { ChatMessage, Employee } from "../../lib/types";
import { cx, formatDateTime, timeAgo } from "../../lib/format";
import { Avatar } from "../ui";
import { Markdown } from "../ui/Markdown";
import { StepTimeline } from "./StepTimeline";
import { ArtifactView } from "./ArtifactView";

/** 页面层在 ChatMessage 上附加的瞬时状态（错误提示），不改 lib/types 契约。 */
export type UiMessage = ChatMessage & { error?: string };

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-1 align-middle">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-400"
          style={{ animationDelay: `${i * 160}ms` }}
        />
      ))}
    </span>
  );
}

function duration(ms?: number): string {
  if (!ms) return "";
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function MessageBubble({
  message,
  employee,
}: {
  message: UiMessage;
  employee?: Employee | null;
}) {
  const isUser = message.role === "user";
  const name = employee?.name || "数字员工";
  const avatarSeed = employee?.avatar || employee?.id || name;
  const hasArtifacts = Boolean(message.artifacts && message.artifacts.length);

  if (isUser) {
    return (
      <div className="group flex justify-end gap-2.5" data-message-id={message.id}>
        <div className="flex max-w-[78%] flex-col items-end">
          <div className="whitespace-pre-wrap break-words rounded-2xl rounded-tr-md bg-brand-600 px-3.5 py-2.5 text-[13.5px] leading-relaxed text-white shadow-sm">
            {message.content}
          </div>
          <div className="mt-1 flex items-center gap-2 text-[10.5px] text-ink-400 opacity-0 transition group-hover:opacity-100">
            <span>{formatDateTime(message.createdAt)}</span>
          </div>
        </div>
        <Avatar name="我" seed="me-self" size={30} className="mt-0.5" />
      </div>
    );
  }

  return (
    <div className="flex gap-2.5" data-message-id={message.id}>
      <Avatar name={name} seed={avatarSeed} size={30} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex items-center gap-2">
          <span className="text-[12px] font-medium text-ink-800">{name}</span>
          {message.streaming && <span className="chip border border-brand-100 bg-brand-50 text-brand-700">正在生成</span>}
          <span className="text-[10.5px] text-ink-400">
            {message.streaming ? "回答中…" : message.createdAt ? timeAgo(message.createdAt) : ""}
          </span>
          {!message.streaming && message.latencyMs ? (
            <span className="text-[10.5px] text-ink-300">· {duration(message.latencyMs)}</span>
          ) : null}
        </div>

        {message.steps && message.steps.length > 0 && <StepTimeline steps={message.steps} />}

        {message.content ? (
          <div className={cx("min-w-0", message.streaming && "stream-cursor")}>
            <Markdown text={message.content} />
          </div>
        ) : message.streaming ? (
          <div className="flex items-center gap-2 rounded-xl border border-surface-200 bg-white px-3 py-2 text-[12px] text-ink-500">
            <TypingDots />
            <span>正在理解你的问题…</span>
          </div>
        ) : null}

        {hasArtifacts && (
          <div className="mt-3 space-y-3">
            {message.artifacts?.map((a) => (
              <div key={a.id || a.title} data-artifact-id={a.id} data-artifact-kind={a.kind} className="scroll-mt-4">
                <ArtifactView artifact={a} />
              </div>
            ))}
          </div>
        )}

        {message.error && (
          <div className="mt-2 flex items-start gap-1.5 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-[11.5px] text-rose-700">
            <AlertCircle size={13} className="mt-0.5 shrink-0" />
            <span>{message.error}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default MessageBubble;
