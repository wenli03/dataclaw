import React, { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileText,
  Info,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import type { ArtifactRef, DashboardPayload, DocxPayload } from "../../lib/types";
import { cx, formatNumber, riskBadgeClass, riskLabel } from "../../lib/format";
import { EChart } from "../ui/EChart";
import { Markdown } from "../ui/Markdown";
import { toast } from "../ui";
import { downloadWithAuth } from "../../lib/api";

/* ---------------- 通用动作 ---------------- */
async function copyText(text: string, okMsg = "已复制") {
  try {
    await navigator.clipboard.writeText(text);
    toast(okMsg);
  } catch {
    toast("复制失败，请手动选择内容", "error");
  }
}

function downloadBlob(content: string, filename: string, mime = "text/markdown;charset=utf-8") {
  const blob = new Blob([content], { type: mime });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

function safeDownload(url: string, filename: string) {
  void downloadWithAuth(url, filename)
    .then(() => toast("已开始下载"))
    .catch((e: unknown) => toast(e instanceof Error ? e.message : "下载失败，接口可能尚未就绪", "error"));
}

/* ---------------- 归一化 ---------------- */
type View =
  | { type: "dashboard"; data: DashboardPayload }
  | { type: "report"; title: string; markdown: string }
  | { type: "docx"; data: DocxPayload }
  | { type: "html"; title: string; html: string }
  | { type: "json"; data: unknown }
  | { type: "pending" };

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : v === null || v === undefined ? fallback : String(v);
}

function normalize(a: ArtifactRef): View {
  const preview = asRecord(a.preview);
  const payload = asRecord(a.payload);
  const data = Object.keys(preview).length ? preview : payload;
  const declared = str(data.type, a.kind);

  if (declared === "dashboard" || Array.isArray(data.kpis) || Array.isArray(data.charts)) {
    const d = data as unknown as DashboardPayload;
    return {
      type: "dashboard",
      data: {
        type: "dashboard",
        title: str(d.title, a.title || "分析大屏"),
        subtitle: str(d.subtitle),
        kpis: Array.isArray(d.kpis) ? d.kpis : [],
        charts: Array.isArray(d.charts) ? d.charts : [],
        insights: Array.isArray(d.insights) ? d.insights : [],
        source: d.source,
      },
    };
  }

  if (declared === "docx") {
    const d = data as unknown as DocxPayload;
    return {
      type: "docx",
      data: {
        type: "docx",
        fileName: str(d.fileName, a.fileName || a.title || "交付文件.docx"),
        filePath: str(d.filePath, a.filePath),
        downloadUrl: str(d.downloadUrl, a.downloadUrl),
        stats: d.stats,
        redlines: Array.isArray(d.redlines) ? d.redlines : [],
      },
    };
  }

  if (declared === "html") {
    return { type: "html", title: a.title || "网页产物", html: str(data.html, a.text || "") };
  }

  if (declared === "report") {
    const md = str(data.markdown, "") || a.text || str(data.content, "");
    if (md) return { type: "report", title: a.title || str(data.title, "深度报告"), markdown: md };
  }

  if (a.text) return { type: "report", title: a.title || "报告", markdown: a.text };
  if (Object.keys(data).length === 0) return { type: "pending" };
  return { type: "json", data };
}

/* ---------------- 通用外壳 ---------------- */
function ArtifactShell({
  title,
  icon,
  subtitle,
  actions,
  children,
  className,
}: {
  title: string;
  icon: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("overflow-hidden rounded-2xl border border-surface-300/70 bg-white shadow-card", className)}>
      <div className="flex items-start justify-between gap-3 border-b border-surface-200 px-4 py-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600">{icon}</span>
          <div className="min-w-0">
            <div className="truncate text-[13.5px] font-semibold text-ink-900">{title}</div>
            {subtitle && <div className="mt-0.5 truncate text-[11.5px] text-ink-500">{subtitle}</div>}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
      </div>
      <div className="px-4 py-3">{children}</div>
    </div>
  );
}

function TinyBtn({
  icon,
  children,
  onClick,
}: {
  icon?: React.ReactNode;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-lg border border-surface-300 bg-white px-2 py-1 text-[11.5px] text-ink-600 transition hover:border-brand-300 hover:text-brand-700"
    >
      {icon}
      {children}
    </button>
  );
}

/* ---------------- 大屏 ---------------- */
const INSIGHT_STYLE: Record<string, { icon: React.ReactNode; cls: string }> = {
  info: { icon: <Info size={13} />, cls: "border-sky-100 bg-sky-50 text-sky-800" },
  warn: { icon: <AlertTriangle size={13} />, cls: "border-amber-100 bg-amber-50 text-amber-800" },
  danger: { icon: <ShieldAlert size={13} />, cls: "border-rose-100 bg-rose-50 text-rose-800" },
  risk: { icon: <ShieldAlert size={13} />, cls: "border-rose-100 bg-rose-50 text-rose-800" },
  good: { icon: <CheckCircle2 size={13} />, cls: "border-emerald-100 bg-emerald-50 text-emerald-800" },
  success: { icon: <CheckCircle2 size={13} />, cls: "border-emerald-100 bg-emerald-50 text-emerald-800" },
};

/** 表格型图表（type=table）用 HTML 表格渲染，其余交给 ECharts。 */
function ChartBlock({ chart }: { chart: DashboardPayload["charts"][number] }) {
  const option = asRecord(chart.option);
  const columns = Array.isArray(option.columns) ? (option.columns as unknown[]).map((c) => String(c)) : [];
  const rows = Array.isArray(option.rows) ? (option.rows as unknown[][]) : [];
  const isTable = chart.type === "table" || (columns.length > 0 && rows.length > 0);

  if (isTable) {
    if (columns.length === 0 || rows.length === 0) {
      return <div className="grid h-[140px] place-items-center text-[11.5px] text-ink-400">该表格暂无数据</div>;
    }
    return (
      <div className="max-h-[280px] overflow-auto rounded-lg border border-surface-200">
        <table className="table-base">
          <thead>
            <tr>
              {columns.map((c, i) => (
                <th key={`${c}-${i}`} className="!px-2.5 !py-2 whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri}>
                {(Array.isArray(row) ? row : [row]).map((cell, ci) => (
                  <td key={ci} className="!px-2.5 !py-1.5 whitespace-nowrap text-[11.5px] text-ink-700">
                    {cell === null || cell === undefined ? "—" : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (!chart.option) {
    return <div className="grid h-[180px] place-items-center text-[11.5px] text-ink-400">该图表暂无数据</div>;
  }
  return <EChart option={chart.option} height={chart.height || 280} />;
}

function TrendDelta({ delta, trend }: { delta?: string; trend?: string }) {
  if (!delta) return null;
  const down = trend === "down" || delta.trim().startsWith("-");
  const flat = trend === "flat" || delta.trim() === "0" || delta.trim() === "0%";
  if (flat) return <span className="text-[11px] text-ink-400">{delta}</span>;
  return (
    <span className={cx("inline-flex items-center gap-0.5 text-[11px] font-medium", down ? "text-rose-600" : "text-emerald-600")}>
      {down ? <ArrowDownRight size={11} /> : <ArrowUpRight size={11} />}
      {delta}
    </span>
  );
}

function DashboardView({ artifact, data }: { artifact: ArtifactRef; data: DashboardPayload }) {
  const [showSource, setShowSource] = useState(false);
  const kpis = data.kpis || [];
  const charts = data.charts || [];
  const insights = data.insights || [];

  const reportText = useMemo(() => {
    const lines: string[] = [`# ${data.title}`, data.subtitle || ""].filter(Boolean) as string[];
    if (kpis.length) {
      lines.push("\n## 核心指标");
      kpis.forEach((k) => lines.push(`- ${k.label}：${k.value}${k.delta ? `（${k.delta}）` : ""}`));
    }
    if (insights.length) {
      lines.push("\n## 洞察");
      const label: Record<string, string> = { info: "提示", warn: "预警", risk: "风险", good: "良好" };
      insights.forEach((i) => lines.push(`- [${label[i.level] || i.level}] ${i.text}`));
    }
    if (data.source?.sql) lines.push(`\n## 数据来源\n\`\`\`sql\n${data.source.sql}\n\`\`\``);
    return lines.join("\n");
  }, [data, kpis, insights]);

  const downloadUrl = artifact.downloadUrl || (artifact.id ? `/api/artifacts/${artifact.id}/download` : "");

  return (
    <ArtifactShell
      title={data.title}
      subtitle={data.subtitle || (data.source?.datasource ? `数据源：${data.source.datasource}` : undefined)}
      icon={<TrendingUp size={16} />}
      actions={
        <>
          <TinyBtn icon={<Copy size={11} />} onClick={() => void copyText(reportText, "报告摘要已复制")}>
            复制报告
          </TinyBtn>
          {downloadUrl && (
            <TinyBtn icon={<Download size={11} />} onClick={() => safeDownload(downloadUrl, `${data.title || "分析大屏"}.md`)}>
              下载
            </TinyBtn>
          )}
        </>
      }
    >
      {kpis.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2.5">
          {kpis.map((k, i) => (
            <div key={`${k.label}-${i}`} className="min-w-0 rounded-xl border border-surface-200 bg-surface-50/70 px-3 py-2.5">
              <div className="truncate text-[11px] text-ink-500">{k.label}</div>
              <div className="mt-1 truncate text-[19px] font-semibold leading-none tracking-tight text-ink-900">{k.value}</div>
              <div className="mt-1.5 flex items-center gap-1">
                <TrendDelta delta={k.delta} trend={k.trend} />
                {k.hint && <span className="truncate text-[10.5px] text-ink-400">{k.hint}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {charts.length > 0 && (
        <div className={cx("grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-3", kpis.length > 0 && "mt-3")}>
          {charts.map((c, i) => (
            <div key={c.id || `chart-${i}`} className="rounded-xl border border-surface-200 bg-white p-2">
              {c.title && <div className="px-1 pb-1 text-[12px] font-medium text-ink-700">{c.title}</div>}
              <ChartBlock chart={c} />
            </div>
          ))}
        </div>
      )}

      {insights.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {insights.map((ins, i) => {
            const style = INSIGHT_STYLE[ins.level] || INSIGHT_STYLE.info;
            return (
              <div key={i} className={cx("flex items-start gap-2 rounded-xl border px-3 py-2 text-[12px] leading-relaxed", style.cls)}>
                <span className="mt-0.5 shrink-0">{style.icon}</span>
                <span className="min-w-0">{ins.text}</span>
              </div>
            );
          })}
        </div>
      )}

      {data.source && (
        <div className="mt-3 overflow-hidden rounded-xl border border-surface-200">
          <button
            type="button"
            onClick={() => setShowSource((v) => !v)}
            className="flex w-full items-center gap-2 bg-surface-50 px-3 py-2 text-left text-[11.5px] font-medium text-ink-600 hover:bg-surface-100"
          >
            <Database size={12} />
            数据来源
            {data.source.rows !== undefined && <span className="text-[10.5px] text-ink-400">· {formatNumber(data.source.rows)} 行</span>}
            {Boolean(data.source.maskedColumns?.length) && (
              <span className="chip border border-amber-100 bg-amber-50 text-amber-700">已脱敏列</span>
            )}
            <span className="ml-auto text-ink-400">{showSource ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</span>
          </button>
          {showSource && (
            <div className="space-y-2 bg-white px-3 py-2.5">
              <div className="text-[11.5px] text-ink-500">
                数据源：<span className="font-medium text-ink-800">{data.source.datasource || "—"}</span>
                {data.source.rows !== undefined && <span className="ml-3">返回 {formatNumber(data.source.rows)} 行</span>}
              </div>
              {Boolean(data.source.maskedColumns?.length) && (
                <div className="flex flex-wrap gap-1">
                  {data.source.maskedColumns?.map((c) => (
                    <span key={c} className="chip border border-amber-100 bg-amber-50 text-amber-700">
                      已脱敏：{c}
                    </span>
                  ))}
                </div>
              )}
              {data.source.rewrittenSql && data.source.rewrittenSql !== data.source.sql && (
                <div>
                  <div className="text-[10.5px] font-medium text-ink-400">SQL 改写前</div>
                  <pre className="mt-1 max-h-32 overflow-auto rounded-lg bg-surface-50 p-2 font-mono text-[10.5px] leading-5 text-ink-600">
                    {data.source.sql || "—"}
                  </pre>
                  <div className="mt-1.5 text-[10.5px] font-medium text-brand-600">SQL 改写后（权限网关）</div>
                  <pre className="mt-1 max-h-32 overflow-auto rounded-lg bg-ink-900 p-2 font-mono text-[10.5px] leading-5 text-slate-100">
                    {data.source.rewrittenSql}
                  </pre>
                </div>
              )}
              {!data.source.rewrittenSql && data.source.sql && (
                <div>
                  <div className="text-[10.5px] font-medium text-ink-400">执行 SQL</div>
                  <pre className="mt-1 max-h-32 overflow-auto rounded-lg bg-ink-900 p-2 font-mono text-[10.5px] leading-5 text-slate-100">
                    {data.source.sql}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </ArtifactShell>
  );
}

/* ---------------- 报告 ---------------- */
function ReportView({ artifact, title, markdown }: { artifact: ArtifactRef; title: string; markdown: string }) {
  return (
    <ArtifactShell
      title={title || "深度报告"}
      icon={<FileText size={16} />}
      subtitle="Markdown 报告 · 可复制或下载"
      actions={
        <>
          <TinyBtn icon={<Copy size={11} />} onClick={() => void copyText(markdown, "报告正文已复制")}>
            复制
          </TinyBtn>
          <TinyBtn icon={<Download size={11} />} onClick={() => downloadBlob(markdown, `${title || "报告"}.md`)}>
            下载 .md
          </TinyBtn>
        </>
      }
    >
      <div className="max-h-[560px] overflow-y-auto pr-1">
        <Markdown text={markdown} />
      </div>
      {artifact.id && (
        <div className="mt-2 border-t border-dashed border-surface-200 pt-2 text-[10.5px] text-ink-400">
          产物编号 {artifact.id}
        </div>
      )}
    </ArtifactShell>
  );
}

/* ---------------- docx ---------------- */
function DocxView({ artifact, data }: { artifact: ArtifactRef; data: DocxPayload }) {
  const stats = data.stats || {};
  const redlines = data.redlines || [];
  const url = data.downloadUrl || artifact.downloadUrl || (artifact.id ? `/api/artifacts/${artifact.id}/download` : "");
  return (
    <ArtifactShell
      title={data.fileName}
      icon={<FileText size={16} />}
      subtitle="带修订痕迹的 Word 交付物"
      actions={
        url ? (
          <TinyBtn icon={<Download size={11} />} onClick={() => safeDownload(url, data.fileName)}>
            下载修订版
          </TinyBtn>
        ) : undefined
      }
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="chip border border-surface-300 bg-surface-50 text-ink-600">风险项 {stats.risks ?? redlines.length}</span>
        {stats.high !== undefined && <span className="chip border border-rose-100 bg-rose-50 text-rose-700">高 {stats.high}</span>}
        {stats.medium !== undefined && <span className="chip border border-amber-100 bg-amber-50 text-amber-700">中 {stats.medium}</span>}
        {stats.low !== undefined && <span className="chip border border-emerald-100 bg-emerald-50 text-emerald-700">低 {stats.low}</span>}
      </div>

      {redlines.length > 0 ? (
        <div className="mt-2.5 overflow-x-auto rounded-xl border border-surface-200">
          <table className="table-base">
            <thead>
              <tr>
                <th className="!px-2.5 !py-2 whitespace-nowrap">条款</th>
                <th className="!px-2.5 !py-2 whitespace-nowrap">风险</th>
                <th className="!px-2.5 !py-2">问题</th>
                <th className="!px-2.5 !py-2">修订建议</th>
              </tr>
            </thead>
            <tbody>
              {redlines.map((r, i) => (
                <tr key={i}>
                  <td className="!px-2.5 !py-2 whitespace-nowrap text-[11.5px] font-medium text-ink-800">
                    {r.clause}
                    {r.title && <div className="text-[10.5px] font-normal text-ink-400">{r.title}</div>}
                  </td>
                  <td className="!px-2.5 !py-2">
                    <span className={cx("chip border", riskBadgeClass(r.risk))}>{riskLabel[r.risk] || r.risk}</span>
                  </td>
                  <td className="!px-2.5 !py-2 text-[11.5px] text-ink-600">{r.issue}</td>
                  <td className="!px-2.5 !py-2 text-[11.5px] text-ink-700">{r.suggestion}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-2.5 rounded-xl border border-dashed border-surface-300 px-3 py-6 text-center text-[11.5px] text-ink-400">
          本文件未识别到需要修订的条款
        </div>
      )}
    </ArtifactShell>
  );
}

/* ---------------- HTML ---------------- */
function HtmlView({ artifact, title, html }: { artifact: ArtifactRef; title: string; html: string }) {
  const openNewWindow = () => {
    const w = window.open("", "_blank");
    if (!w) {
      toast("浏览器拦截了新窗口，请允许弹窗", "error");
      return;
    }
    w.document.open();
    w.document.write(html);
    w.document.close();
  };
  return (
    <ArtifactShell
      title={title}
      icon={<ExternalLink size={16} />}
      subtitle="网页产物 · 沙箱内渲染"
      actions={
        <>
          <TinyBtn icon={<ArrowRight size={11} />} onClick={openNewWindow}>
            新窗口打开
          </TinyBtn>
          {artifact.id && (
            <TinyBtn icon={<Download size={11} />} onClick={() => safeDownload(`/api/artifacts/${artifact.id}/download`, `${title || "产物"}.html`)}>
              下载
            </TinyBtn>
          )}
        </>
      }
    >
      <iframe
        title={title || "网页产物"}
        srcDoc={html}
        sandbox="allow-same-origin"
        className="h-[420px] w-full rounded-xl border border-surface-200 bg-white"
      />
    </ArtifactShell>
  );
}

/* ---------------- JSON ---------------- */
function JsonView({ artifact, data }: { artifact: ArtifactRef; data: unknown }) {
  const text = useMemo(() => {
    try {
      return JSON.stringify(data, null, 2) ?? "";
    } catch {
      return String(data);
    }
  }, [data]);
  return (
    <ArtifactShell
      title={artifact.title || "结构化产物"}
      icon={<Database size={16} />}
      actions={
        <TinyBtn icon={<Copy size={11} />} onClick={() => void copyText(text, "内容已复制")}>
          复制
        </TinyBtn>
      }
    >
      <pre className="max-h-[420px] overflow-auto rounded-xl bg-ink-900 p-3 font-mono text-[11px] leading-5 text-slate-100">{text}</pre>
    </ArtifactShell>
  );
}

/** 按 preview.type / kind 渲染产物：dashboard / report / docx / html / json。 */
export function ArtifactView({ artifact }: { artifact: ArtifactRef }) {
  const view = useMemo(() => normalize(artifact), [artifact]);

  if (view.type === "pending") {
    return (
      <div className="flex items-center gap-2 rounded-2xl border border-dashed border-surface-300 bg-white px-4 py-3 text-[12px] text-ink-500">
        <span className="h-3 w-3 animate-pulse rounded-full bg-brand-300" />
        产物「{artifact.title || artifact.kind}」正在加载预览…
      </div>
    );
  }
  if (view.type === "dashboard") return <DashboardView artifact={artifact} data={view.data} />;
  if (view.type === "docx") return <DocxView artifact={artifact} data={view.data} />;
  if (view.type === "html") return <HtmlView artifact={artifact} title={view.title} html={view.html} />;
  if (view.type === "report") return <ReportView artifact={artifact} title={view.title} markdown={view.markdown} />;
  return <JsonView artifact={artifact} data={view.data} />;
}

export default ArtifactView;
