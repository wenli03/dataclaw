import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cx } from "@/lib/format";

/* ------------------------------------------------------------------ SQL 块 */

const SQL_TEXT_RE = /^\s*(select|with|insert|update|delete|create|drop|alter|pragma|explain)\b/i;

/** 等宽 SQL 展示块（审计详情 / SQL 改写预览共用）。 */
export function SqlBlock({
  sql,
  tone = "dark",
  className,
  emptyText = "（无）",
}: {
  sql?: string | null;
  tone?: "dark" | "light";
  className?: string;
  emptyText?: string;
}) {
  const text = (sql || "").trim();
  if (!text) {
    return <div className={cx("rounded-xl border border-dashed border-surface-300 px-3 py-2 text-[12px] text-ink-400", className)}>{emptyText}</div>;
  }
  return (
    <pre
      className={cx(
        "max-h-[320px] overflow-auto whitespace-pre-wrap break-words rounded-xl px-3.5 py-3 font-mono text-[12px] leading-6",
        tone === "dark" ? "bg-ink-900 text-slate-100" : "border border-surface-200 bg-surface-50 text-ink-800",
        className
      )}
    >
      <code>{text}</code>
    </pre>
  );
}

/* ------------------------------------------------------------------ 工具函数 */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSqlKey(key?: string): boolean {
  if (!key) return false;
  return /^sql$/i.test(key) || /sql$/i.test(key) || /^rewritten$/i.test(key);
}

function isSqlString(value: unknown): value is string {
  return typeof value === "string" && SQL_TEXT_RE.test(value);
}

function keyLabel(key: string): string {
  return key;
}

/* ------------------------------------------------------------------ 原始值 */

function PrimitiveValue({ value }: { value: unknown }) {
  if (value === null) return <span className="text-ink-400">null</span>;
  if (value === undefined) return <span className="text-ink-400">—</span>;
  if (typeof value === "boolean") return <span className="text-amber-600">{String(value)}</span>;
  if (typeof value === "number") return <span className="text-sky-700">{String(value)}</span>;
  if (typeof value === "string") {
    if (value === "") return <span className="text-ink-400">""</span>;
    return <span className="break-all text-ink-700">"{value}"</span>;
  }
  return <span className="text-ink-500">{String(value)}</span>;
}

/* ------------------------------------------------------------------ 递归节点 */

function JsonNode({
  name,
  value,
  depth,
  defaultDepth,
}: {
  name?: string;
  value: unknown;
  depth: number;
  defaultDepth: number;
}) {
  const entries: [string, unknown][] | null = isRecord(value) ? Object.entries(value) : null;
  const isArray = Array.isArray(value);
  const container = entries !== null || isArray;
  const [open, setOpen] = useState(depth < defaultDepth);

  // SQL 字符串（originalSql / rewrittenSql / sql）→ 代码块
  if (isSqlString(value) && (isSqlKey(name) || SQL_TEXT_RE.test(value))) {
    return (
      <div className="py-1">
        {name && <div className="mb-1 font-mono text-[11.5px] text-brand-700">{keyLabel(name)}</div>}
        <SqlBlock sql={value} />
      </div>
    );
  }

  // 长文本 → 折叠为浅色块，避免撑破抽屉
  if (typeof value === "string" && value.length > 240) {
    return (
      <div className="py-1">
        {name && <div className="mb-1 font-mono text-[11.5px] text-brand-700">{keyLabel(name)}</div>}
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-surface-200 bg-surface-50 px-3 py-2 text-[11.5px] leading-5 text-ink-700">
          {value}
        </pre>
      </div>
    );
  }

  if (!container) {
    return (
      <div className="flex gap-2 py-0.5">
        {name !== undefined && <span className="shrink-0 font-mono text-[11.5px] text-brand-700">{keyLabel(name)}</span>}
        {name !== undefined && <span className="text-ink-400">:</span>}
        <span className="min-w-0 flex-1">
          <PrimitiveValue value={value} />
        </span>
      </div>
    );
  }

  const list = isArray ? (value as unknown[]) : [];
  const size = isArray ? list.length : entries!.length;
  const summary = isArray ? `[ ${size} ]` : `{ ${size} }`;

  return (
    <div className="py-0.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-surface-100"
      >
        {open ? <ChevronDown size={12} className="shrink-0 text-ink-400" /> : <ChevronRight size={12} className="shrink-0 text-ink-400" />}
        {name !== undefined && <span className="font-mono text-[11.5px] text-brand-700">{keyLabel(name)}</span>}
        <span className="font-mono text-[10.5px] text-ink-400">{summary}</span>
      </button>
      {open && (
        <div className="ml-3 border-l border-surface-200 pl-3">
          {isArray
            ? list.map((item, i) => <JsonNode key={i} name={String(i)} value={item} depth={depth + 1} defaultDepth={defaultDepth} />)
            : entries!.map(([k, v]) => <JsonNode key={k} name={k} value={v} depth={depth + 1} defaultDepth={defaultDepth} />)}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ 对外组件 */

/**
 * 折叠 JSON 展示（审计详情 / SQL 详情复用）。
 * - 对象/数组可逐层展开，默认展开前 2 层
 * - 值看起来是 SQL 的字段（originalSql/rewrittenSql/sql）自动渲染为等宽代码块
 */
export function JsonViewer({
  data,
  className,
  defaultDepth = 2,
  emptyText = "无详情",
}: {
  data: unknown;
  className?: string;
  defaultDepth?: number;
  emptyText?: string;
}) {
  const empty =
    data === null ||
    data === undefined ||
    (isRecord(data) && Object.keys(data).length === 0) ||
    (Array.isArray(data) && data.length === 0);

  if (empty) {
    return <div className={cx("rounded-xl border border-dashed border-surface-300 px-3 py-6 text-center text-[12px] text-ink-400", className)}>{emptyText}</div>;
  }

  return (
    <div className={cx("rounded-xl border border-surface-200 bg-surface-50/60 px-3 py-2 font-mono", className)}>
      <JsonNode value={data} depth={0} defaultDepth={defaultDepth} />
    </div>
  );
}

export default JsonViewer;
