import React, { useEffect, useRef } from "react";
import { Loader2, Paperclip, Send, Square, X } from "lucide-react";
import { cx, fileSize } from "../../lib/format";

export type Attachment = { fileId: string; name: string; size?: number };

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  attachments,
  onUpload,
  onRemoveAttachment,
  uploading,
  disabled,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  attachments: Attachment[];
  onUpload: (file: File) => void;
  onRemoveAttachment: (fileId: string) => void;
  uploading?: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const canSend = Boolean(value.trim()) && !disabled && !streaming;
  const locked = Boolean(disabled);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    // 中文输入法组合中的回车不发送
    if (e.nativeEvent.isComposing) return;
    e.preventDefault();
    if (canSend) onSend();
  };

  return (
    <div className="border-t border-surface-200 bg-white/80 px-4 py-3 backdrop-blur">
      <div className="mx-auto max-w-[880px]">
        <div
          className={cx(
            "rounded-2xl border bg-white p-2 transition",
            locked ? "border-surface-200 opacity-70" : "border-surface-300 focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-500/10"
          )}
        >
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-1 pb-2">
              {attachments.map((a) => (
                <span
                  key={a.fileId}
                  className="inline-flex items-center gap-1 rounded-lg border border-surface-300 bg-surface-50 py-1 pl-2 pr-1 text-[11px] text-ink-600"
                >
                  <Paperclip size={11} className="text-ink-400" />
                  <span className="max-w-[180px] truncate">{a.name}</span>
                  {a.size !== undefined && <span className="text-ink-400">{fileSize(a.size)}</span>}
                  <button
                    type="button"
                    onClick={() => onRemoveAttachment(a.fileId)}
                    className="rounded p-0.5 text-ink-400 hover:bg-surface-200 hover:text-ink-700"
                    aria-label={`移除附件 ${a.name}`}
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}

          <textarea
            ref={taRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={locked}
            placeholder={placeholder || "说说你想让数字员工做什么，例如：帮我分析下上季度各区域工时效率情况"}
            className="max-h-[160px] w-full resize-none bg-transparent px-2 py-1.5 text-[13.5px] leading-6 text-ink-900 outline-none placeholder:text-ink-400 disabled:cursor-not-allowed"
          />

          <div className="flex items-center gap-1 px-1 pt-1">
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUpload(f);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={locked || uploading}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-[11.5px] text-ink-500 transition hover:bg-surface-100 hover:text-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {uploading ? <Loader2 size={13} className="animate-spin" /> : <Paperclip size={13} />}
              {uploading ? "上传中" : "附件"}
            </button>
            <span className="ml-1 hidden text-[10.5px] text-ink-300 sm:inline">Enter 发送 · Shift+Enter 换行</span>

            <div className="ml-auto">
              {streaming ? (
                <button
                  type="button"
                  onClick={onStop}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-surface-300 bg-white px-3 py-1.5 text-[12.5px] font-medium text-ink-700 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600"
                >
                  <Square size={12} /> 停止
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onSend}
                  disabled={!canSend}
                  className="btn-primary !px-3 !py-1.5 !text-[12.5px]"
                >
                  <Send size={13} /> 发送
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="mt-1.5 px-1 text-center text-[10.5px] leading-relaxed text-ink-400">
          数字员工将按你的数据权限调用工具，越权操作会被拦截并审计
        </div>
      </div>
    </div>
  );
}

export default Composer;
