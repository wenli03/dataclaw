import React, { useMemo } from "react";
import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  BookOpen,
  Database,
  FileSearch,
  FileText,
  Globe,
  Presentation,
  Sparkles,
  Table,
  Target,
} from "lucide-react";
import type { Employee } from "../../lib/types";
import { Avatar } from "../ui";

type Example = { icon: LucideIcon; title: string; desc: string; text: string };

const GENERIC: Example[] = [
  { icon: Database, title: "看看有什么数据", desc: "盘点你有权限访问的数据集", text: "帮我看看我有哪些数据可以分析" },
  { icon: FileText, title: "整理成报告", desc: "把结论整理成给领导看的材料", text: "把这次分析结论整理成一份给领导看的报告" },
  { icon: Sparkles, title: "能力清单", desc: "了解这位数字员工能做什么", text: "你能做什么？给我一份能力清单" },
  { icon: Target, title: "本周重点", desc: "从数据里找出需要关注的事", text: "帮我看看本周最需要关注的三件事" },
];

/** 按员工已装技能生成示例问句（技能名为机器名，如 chatbi / contract-review）。 */
function buildExamples(employee: Employee | null): Example[] {
  const names = new Set((employee?.skills || []).map((s) => (s.name || "").toLowerCase()));
  const pool: Example[] = [];

  if (names.has("chatbi")) {
    pool.push({
      icon: Database,
      title: "工时效率分析",
      desc: "查数据 + 出可视化大屏",
      text: "帮我分析下上季度各区域工时效率情况",
    });
  }
  if (names.has("contract-review")) {
    pool.push({
      icon: FileSearch,
      title: "审查合同",
      desc: "按企业规则识别风险条款",
      text: "按公司标准合同规则审查这份合同",
    });
  }
  if (names.has("sales-intel")) {
    pool.push({
      icon: Target,
      title: "拜访前准备",
      desc: "客户 360 + 沟通策略",
      text: "我要拜访 XX 客户，帮我准备拜访指南",
    });
  }
  if (names.has("knowhow-search")) {
    pool.push({
      icon: BookOpen,
      title: "查企业知识",
      desc: "检索内部规范与制度",
      text: "查一下公司《工时管理规范》对加班是怎么规定的",
    });
  }
  if (names.has("deep-report")) {
    pool.push({
      icon: FileText,
      title: "深度报告",
      desc: "结论先行，≥1200 字",
      text: "生成一份上季度工时效率的深度报告，结论先行",
    });
  }
  if (names.has("dashboard-builder")) {
    pool.push({
      icon: BarChart3,
      title: "做一版大屏",
      desc: "KPI + 图表 + 洞察",
      text: "把上季度工时分析做成一块可视化大屏",
    });
  }
  if (names.has("web-search")) {
    pool.push({
      icon: Globe,
      title: "联网补充信息",
      desc: "公开情报检索",
      text: "帮我检索一下 XX 客户最近的公开动态",
    });
  }
  if (names.has("doc-parse")) {
    pool.push({
      icon: FileSearch,
      title: "解析文档",
      desc: "提取条款与关键字段",
      text: "解析我上传的合同，列出关键条款和金额",
    });
  }
  if (names.has("excel-toolkit")) {
    pool.push({ icon: Table, title: "处理表格", desc: "清洗、透视、汇总", text: "帮我把上传的工时表做清洗和汇总" });
  }
  if (names.has("pptx-export")) {
    pool.push({ icon: Presentation, title: "出汇报材料", desc: "一键生成演示文稿", text: "把上季度工时分析做成一份汇报材料" });
  }

  const seen = new Set<string>();
  const out: Example[] = [];
  for (const e of [...pool, ...GENERIC]) {
    if (seen.has(e.text)) continue;
    seen.add(e.text);
    out.push(e);
    if (out.length === 4) break;
  }
  return out;
}

export function EmptyChat({
  employee,
  subtitle,
  onPick,
}: {
  employee: Employee | null;
  subtitle?: string;
  onPick: (text: string) => void;
}) {
  const examples = useMemo(() => buildExamples(employee), [employee]);
  const name = employee?.name || "数字员工";
  const greeting =
    employee?.greeting ||
    `Hi，我是 ${name}${employee?.roleTitle && employee.roleTitle !== name ? `，${employee.roleTitle}` : ""}。告诉我你想完成的事，我会按你的数据权限调用工具，直接交付结果。`;

  const skills = (employee?.skills || []).filter((s) => s.enabled !== false);

  return (
    <div className="mx-auto flex max-w-[760px] flex-col items-center px-4 py-8 text-center">
      <Avatar name={name} seed={employee?.avatar || employee?.id} size={60} className="shadow-card" />
      <div className="mt-3 text-[17px] font-semibold tracking-tight text-ink-900">{name}</div>
      {subtitle && <div className="mt-0.5 text-[12px] text-ink-500">{subtitle}</div>}

      <p className="mt-4 max-w-[560px] whitespace-pre-wrap text-[13.5px] leading-7 text-ink-600">{greeting}</p>

      {skills.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5">
          {skills.slice(0, 8).map((s) => (
            <span key={s.id} className="chip border border-surface-300 bg-white text-ink-500">
              {s.displayName}
            </span>
          ))}
          {skills.length > 8 && <span className="text-[11px] text-ink-400">+{skills.length - 8}</span>}
        </div>
      )}

      <div className="mt-7 w-full">
        <div className="mb-2 flex items-center justify-center gap-2 text-[11px] text-ink-400">
          <span className="h-px w-10 bg-surface-300" />
          试着这样问
          <span className="h-px w-10 bg-surface-300" />
        </div>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {examples.map((e) => (
            <button
              key={e.text}
              type="button"
              onClick={() => onPick(e.text)}
              aria-label={`示例问句：${e.text}`}
              className="card card-hover group flex items-start gap-2.5 p-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2"
            >
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600 transition group-hover:bg-brand-100">
                <e.icon size={15} />
              </span>
              <span className="min-w-0">
                <span className="block text-[12.5px] font-medium text-ink-800">{e.title}</span>
                <span className="mt-0.5 block truncate text-[11.5px] text-ink-500">{e.text}</span>
                <span className="mt-0.5 block text-[10.5px] text-ink-400">{e.desc}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default EmptyChat;
