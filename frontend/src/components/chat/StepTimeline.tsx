import React, { useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  FileCheck2,
  FileSearch,
  FileText,
  Globe,
  Loader2,
  Presentation,
  ShieldAlert,
  Table,
  Wrench,
  X,
} from "lucide-react";
import type { StepItem } from "../../lib/types";
import { cx } from "../../lib/format";

type ToolMeta = { icon: LucideIcon; label: string };

/** 工具名 → 图标/中文名（chatbi.ask → chatbi） */
const TOOL_MAP: Record<string, ToolMeta> = {
  chatbi: { icon: Database, label: "数据查询" },
  dashboard: { icon: BarChart3, label: "可视化大屏" },
  report: { icon: FileText, label: "深度报告" },
  contract: { icon: FileCheck2, label: "合同审查" },
  knowledge: { icon: BookOpen, label: "知识检索" },
  web: { icon: Globe, label: "联网检索" },
  doc: { icon: FileSearch, label: "文档解析" },
  excel: { icon: Table, label: "表格处理" },
  pptx: { icon: Presentation, label: "演示文稿" },
};

const DEFAULT_META: ToolMeta = { icon: Wrench, label: "工具调用" };

function toolMeta(tool?: string): ToolMeta {
  if (!tool) return DEFAULT_META;
  const key = tool.split(".")[0].split("_")[0].toLowerCase();
  return TOOL_MAP[key] || DEFAULT_META;
}

function fmtDuration(ms?: number): string {
  if (ms === undefined || ms === null || Number.isNaN(ms)) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
}

/* ---------------- 状态点 ---------------- */
function StatusIcon({ status }: { status: StepItem["status"] }) {
  if (status === "running") return <Loader2 size={11} className="animate-spin text-brand-600" />;
  if (status === "error") return <X size={11} className="text-rose-600" />;
  if (status === "pending") return <Clock size={11} className="text-ink-400" />;
  return <Check size={11} className="text-emerald-600" />;
}

function dotClass(status: StepItem["status"]): string {
  if (status === "running") return "border-brand-300 bg-brand-50 text-brand-600 animate-pulse-soft";
  if (status === "error") return "border-rose-200 bg-rose-50 text-rose-600";
  if (status === "pending") return "border-surface-300 bg-surface-100 text-ink-400";
  return "border-emerald-200 bg-emerald-50 text-emerald-600";
}

/* ---------------- JSON 折叠块 ---------------- */
export function JsonBlock({ value, maxHeight = "max-h-44" }: { value: unknown; maxHeight?: string }) {
  const text = useMemo(() => {
    try {
      return JSON.stringify(value, null, 2) ?? "";
    } catch {
      return String(value);
    }
  }, [value]);
  if (!text || text === "null" || text === "{}") return null;
  return (
    <pre
      className={cx(
        "mt-1.5 overflow-auto rounded-lg border border-surface-200 bg-surface-50 p-2.5 font-mono text-[11px] leading-5 text-ink-700",
        maxHeight
      )}
    >
      {text}
    </pre>
  );
}

/* ---------------- 输出摘要 ---------------- */
function OutputSummary({ output }: { output: unknown }) {
  const info = useMemo(() => {
    if (!output || typeof output !== "object") return null;
    const o = output as Record<string, unknown>;
    const rawRows = o.rows;
    const rows =
      typeof rawRows === "number"
        ? rawRows
        : Array.isArray(rawRows)
        ? rawRows.length
        : typeof o.rowCount === "number"
        ? (o.rowCount as number)
        : undefined;
    const sql = typeof o.sql === "string" ? o.sql : typeof o.rewrittenSql === "string" ? (o.rewrittenSql as string) : undefined;
    const rewrittenSql = typeof o.rewrittenSql === "string" ? (o.rewrittenSql as string) : undefined;
    const rules = Array.isArray(o.appliedRules) ? o.appliedRules.length : undefined;
    const masks = Array.isArray(o.maskedColumns) ? (o.maskedColumns as unknown[]).map((x) => String(x)) : [];
    const summary = typeof o.summary === "string" ? (o.summary as string) : undefined;
    const denied = typeof o.deniedReason === "string" ? o.deniedReason : undefined;
    return { rows, sql, rewrittenSql, rules, masks, summary, denied };
  }, [output]);

  if (!info) {
    return <JsonBlock value={output} />;
  }

  return (
    <div className="mt-1.5 space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {info.summary && <span className="chip border border-surface-300 bg-surface-50 text-ink-600">{info.summary}</span>}
        {info.rows !== undefined && <span className="chip border border-surface-300 bg-surface-50 text-ink-600">{info.rows} 行</span>}
        {info.rules !== undefined && (
          <span className="chip border border-brand-100 bg-brand-50 text-brand-700">已应用 {info.rules} 条权限规则</span>
        )}
        {info.masks.length > 0 && (
          <span className="chip border border-amber-100 bg-amber-50 text-amber-700">已脱敏：{info.masks.join("、")}</span>
        )}
      </div>

      {info.denied && (
        <div className="flex items-start gap-1.5 rounded-lg border border-rose-100 bg-rose-50 px-2.5 py-2 text-[11.5px] text-rose-700">
          <ShieldAlert size={13} className="mt-0.5 shrink-0" />
          <span>越权拦截：{info.denied}</span>
        </div>
      )}

      {info.sql && (
        <div>
          <div className="text-[10.5px] font-medium text-ink-400">SQL</div>
          <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-ink-900 p-2.5 font-mono text-[11px] leading-5 text-slate-100">
            {info.sql}
          </pre>
        </div>
      )}

      {info.rewrittenSql && info.rewrittenSql !== info.sql && (
        <div>
          <div className="text-[10.5px] font-medium text-ink-400">改写后 SQL（权限网关）</div>
          <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-ink-900 p-2.5 font-mono text-[11px] leading-5 text-slate-100">
            {info.rewrittenSql}
          </pre>
        </div>
      )}

      <details className="group">
        <summary className="cursor-pointer select-none text-[11px] text-ink-400 hover:text-ink-600">
          查看原始输出
        </summary>
        <JsonBlock value={output} />
      </details>
    </div>
  );
}

/* ---------------- 单步 ---------------- */
function StepRow({ step, last }: { step: StepItem; last: boolean }) {
  const [open, setOpen] = useState(false);
  const meta = toolMeta(step.tool);
  const Icon = meta.icon;
  const isRunning = step.status === "running";
  const toggle = () => setOpen((v) => !v);
  const hasDetail =
    (step.input !== undefined && step.input !== null) ||
    (step.output !== undefined && step.output !== null) ||
    Boolean(step.summary);

  return (
    <div className="relative pl-7">
      {!last && <span className="absolute left-[9px] top-6 bottom-0 w-px bg-surface-300" />}
      <span
        className={cx(
          "absolute left-0 top-1.5 grid h-[19px] w-[19px] place-items-center rounded-full border bg-white",
          dotClass(step.status)
        )}
      >
        <StatusIcon status={step.status} />
      </span>

      <div className="pb-3">
        <button
          type="button"
          onClick={toggle}
          disabled={!hasDetail}
          className={cx(
            "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition",
            hasDetail && "hover:bg-surface-100",
            !hasDetail && "cursor-default"
          )}
        >
          <span className={cx("grid h-6 w-6 shrink-0 place-items-center rounded-md", isRunning ? "bg-brand-50 text-brand-600" : "bg-surface-100 text-ink-500")}>
            {isRunning ? <Loader2 size={12} className="animate-spin" /> : <Icon size={12} />}
          </span>
          <span className="min-w-0 flex-1">
            <span className={cx("block truncate text-[12.5px] font-medium", isRunning ? "text-brand-700" : "text-ink-800")}>
              {step.title || meta.label}
            </span>
            <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] text-ink-400">
              <span>{step.tool || meta.label}</span>
              {step.summary && <span className="truncate">{step.summary}</span>}
            </span>
          </span>
          {step.durationMs !== undefined && <span className="shrink-0 text-[10.5px] tabular-nums text-ink-400">{fmtDuration(step.durationMs)}</span>}
          {step.status === "error" && <AlertTriangle size={12} className="shrink-0 text-rose-500" />}
          {hasDetail && (
            <span className="shrink-0 text-ink-300">
              {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            </span>
          )}
        </button>

        {open && hasDetail && (
          <div className="ml-2 mt-1 animate-fade-in rounded-xl border border-surface-200 bg-white px-3 py-2">
            {step.input !== undefined && step.input !== null && (
              <div>
                <div className="text-[10.5px] font-medium text-ink-400">输入</div>
                {typeof step.input === "string" ? (
                  <pre className="mt-1 overflow-auto rounded-lg bg-surface-50 p-2 font-mono text-[11px] text-ink-700">{step.input}</pre>
                ) : (
                  <JsonBlock value={step.input} />
                )}
              </div>
            )}
            {step.output !== undefined && step.output !== null && (
              <div className={cx(step.input !== undefined && step.input !== null && "mt-2 border-t border-dashed border-surface-200 pt-2")}>
                <div className="text-[10.5px] font-medium text-ink-400">输出</div>
                {typeof step.output === "string" ? (
                  <pre className="mt-1 overflow-auto rounded-lg bg-surface-50 p-2 font-mono text-[11px] text-ink-700">{step.output}</pre>
                ) : (
                  <OutputSummary output={step.output} />
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** 工具调用时间线：竖线 + 圆点，点击展开输入/输出。 */
export function StepTimeline({ steps }: { steps?: StepItem[] }) {
  if (!steps || steps.length === 0) return null;
  return (
    <div className="mb-2.5 rounded-2xl border border-surface-200 bg-surface-50/60 px-3 py-2.5">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-ink-500">
        <Wrench size={11} /> 执行过程 · {steps.length} 步
      </div>
      <div>
        {steps.map((s, i) => (
          <StepRow key={s.id || `${i}`} step={s} last={i === steps.length - 1} />
        ))}
      </div>
    </div>
  );
}

export default StepTimeline;
