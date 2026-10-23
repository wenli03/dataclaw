import React, { useCallback, useEffect, useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  BookOpen,
  Check,
  Database,
  Download,
  Eye,
  FileScan,
  FileText,
  Filter,
  Globe,
  LayoutDashboard,
  Loader2,
  Monitor,
  Package,
  Plus,
  Presentation,
  RefreshCw,
  Scale,
  Search,
  ShieldAlert,
  Sparkles,
  Store,
  Table,
  Target,
  Trash2,
  Wrench,
} from "lucide-react";
import type { Skill } from "../lib/types";
import { api } from "../lib/api";
import { cx, formatNumber, riskBadgeClass, riskLabel, statusLabel, timeAgo } from "../lib/format";
import { Badge, Button, Card, Drawer, Empty, Field, Input, Modal, Select, Skeleton, Tabs, Textarea, toast } from "../components/ui";

/* ---------------- 工具 ---------------- */
function errText(e: unknown): string {
  const msg = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  if (!msg || /failed to fetch|networkerror|load failed/i.test(msg)) return "服务暂不可用，请确认后端已启动";
  return msg;
}

const ICONS: Record<string, LucideIcon> = {
  "bar-chart-3": BarChart3,
  "layout-dashboard": LayoutDashboard,
  "file-text": FileText,
  scale: Scale,
  target: Target,
  search: Search,
  "file-scan": FileScan,
  presentation: Presentation,
  table: Table,
  globe: Globe,
  filter: Filter,
  monitor: Monitor,
  sparkles: Sparkles,
  database: Database,
  "book-open": BookOpen,
  wrench: Wrench,
};

function skillIcon(icon?: string): LucideIcon {
  if (!icon) return Sparkles;
  return ICONS[icon.toLowerCase()] || Sparkles;
}

type ListResp<T> = { items?: T[]; total?: number };
type SkillResp = { skill?: Skill };

const SKILL_TEMPLATE = `---
name: my-skill
description: 一句话说明这个技能解决什么问题、给谁用
risk: low
tools: []
---

# 技能名称

## 能力边界

- 只做以下三件事：……
- 不拥有的能力：……

## 首选工作流

1. 先确认输入（数据/文档/参数）是否齐备，缺什么要问清楚。
2. 执行核心步骤，过程要可解释。
3. 输出前自检：结论是否有数据支撑、口径是否说明。

## 禁止事项

- 不执行未获授权的写操作。
- 不输出被脱敏的原始值。

## 输出规范

- 结论先行，再给依据。
- 数据结论必须标注口径与时间范围。
`;

const CATEGORY_OPTIONS = ["数据", "可视化", "分析", "法务", "销售", "知识", "文档", "办公", "自动化", "自定义"];

function splitFrontmatter(content: string): { front: string; body: string } {
  const text = content || "";
  if (!text.startsWith("---")) return { front: "", body: text };
  const end = text.indexOf("\n---", 3);
  if (end < 0) return { front: "", body: text };
  const front = text.slice(3, end).replace(/^\n/, "");
  const body = text.slice(end + 4).replace(/^\n/, "");
  return { front, body };
}

function SkillDoc({ content }: { content: string }) {
  const { front, body } = useMemo(() => splitFrontmatter(content), [content]);
  return (
    <div className="overflow-hidden rounded-xl border border-ink-800 bg-ink-900">
      {front && (
        <div className="border-b border-white/10 px-3.5 py-2.5 font-mono text-[11.5px] leading-5">
          {front.split("\n").map((line, i) => {
            const idx = line.indexOf(":");
            if (idx <= 0) {
              return (
                <div key={i} className="text-slate-400">
                  {line || " "}
                </div>
              );
            }
            return (
              <div key={i}>
                <span className="text-teal-300">{line.slice(0, idx)}</span>
                <span className="text-slate-500">: </span>
                <span className="text-amber-200">{line.slice(idx + 1).trim()}</span>
              </div>
            );
          })}
        </div>
      )}
      <pre className="max-h-[540px] overflow-auto whitespace-pre-wrap break-words p-3.5 font-mono text-[11.5px] leading-6 text-slate-100">
        {body || "（暂无 SKILL.md 内容）"}
      </pre>
    </div>
  );
}

function StatusBadge({ status }: { status: Skill["status"] }) {
  if (status === "approved") return <Badge tone="green">{statusLabel.approved}</Badge>;
  if (status === "pending") return <Badge tone="amber">{statusLabel.pending}</Badge>;
  return <Badge tone="rose">{statusLabel.rejected}</Badge>;
}

/* ---------------- 页面 ---------------- */
export default function Skills() {
  const [tab, setTab] = useState("installed");
  const [lists, setLists] = useState<Record<string, Skill[]>>({ installed: [], market: [], mine: [] });
  const [counts, setCounts] = useState<Record<string, number>>({ installed: 0, market: 0, mine: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState("");
  const [busyId, setBusyId] = useState("");

  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<Skill | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ displayName: "", description: "", category: "自定义", tags: "", content: SKILL_TEMPLATE });
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [installed, market, mine] = await Promise.all([
        api.get<ListResp<Skill>>("/skills", { tab: "installed", size: 200 }),
        api.get<ListResp<Skill>>("/skills", { tab: "market", size: 200 }),
        api.get<ListResp<Skill>>("/skills", { tab: "mine", size: 200 }),
      ]);
      setLists({
        installed: installed.items || [],
        market: market.items || [],
        mine: mine.items || [],
      });
      setCounts({
        installed: installed.total ?? (installed.items || []).length,
        market: market.total ?? (market.items || []).length,
        mine: mine.total ?? (mine.items || []).length,
      });
    } catch (e) {
      setError(errText(e));
      setLists({ installed: [], market: [], mine: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openSkill = useCallback(async (id: string) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailError("");
    setDetail(null);
    try {
      const res = await api.get<SkillResp>(`/skills/${id}`);
      setDetail(res.skill || null);
    } catch (e) {
      setDetailError(errText(e));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const install = async (skill: Skill) => {
    setBusyId(skill.id);
    try {
      await api.post<unknown>(`/skills/${skill.id}/install`, {});
      toast(`已安装「${skill.displayName}」`);
      await load();
      if (detail?.id === skill.id) void openSkill(skill.id);
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setBusyId("");
    }
  };

  const uninstall = async (skill: Skill) => {
    setBusyId(skill.id);
    try {
      await api.post<unknown>(`/skills/${skill.id}/uninstall`);
      toast(`已卸载「${skill.displayName}」`);
      await load();
      if (detail?.id === skill.id) void openSkill(skill.id);
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setBusyId("");
    }
  };

  const submitCreate = async () => {
    if (!form.displayName.trim()) {
      toast("请填写技能名称", "error");
      return;
    }
    if (!form.content.includes("name:")) {
      toast("SKILL.md 需包含 YAML frontmatter（name / description）", "error");
      return;
    }
    setCreating(true);
    try {
      await api.post<unknown>("/skills", {
        displayName: form.displayName.trim(),
        description: form.description.trim(),
        content: form.content,
        category: form.category,
        tags: form.tags
          .split(/[,，\s]+/)
          .map((t) => t.trim())
          .filter(Boolean),
        icon: "sparkles",
      });
      toast("技能已提交，等待管理员审核");
      setCreateOpen(false);
      setForm({ displayName: "", description: "", category: "自定义", tags: "", content: SKILL_TEMPLATE });
      setTab("mine");
      await load();
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setCreating(false);
    }
  };

  const categories = useMemo(() => {
    const set = new Set<string>();
    Object.values(lists).forEach((arr) => arr.forEach((s) => s.category && set.add(s.category)));
    return Array.from(set).sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [lists]);

  const visible = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return (lists[tab] || []).filter((s) => {
      if (category && s.category !== category) return false;
      if (!kw) return true;
      return (
        (s.displayName || "").toLowerCase().includes(kw) ||
        (s.name || "").toLowerCase().includes(kw) ||
        (s.description || "").toLowerCase().includes(kw) ||
        (s.tags || []).some((t) => t.toLowerCase().includes(kw))
      );
    });
  }, [lists, tab, category, keyword]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[1320px] px-5 py-5 lg:px-7">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-semibold tracking-tight text-ink-900">技能超市</h1>
            <p className="mt-1 text-[12.5px] text-ink-500">
              内置企业级技能开箱即用；你自己创建的技能经管理员审核后可在团队内复用。
            </p>
          </div>
          <Button onClick={() => setCreateOpen(true)} icon={<Plus size={14} />}>
            创建技能
          </Button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Tabs
            items={[
              { key: "installed", label: "已安装", count: counts.installed },
              { key: "market", label: "技能市场", count: counts.market },
              { key: "mine", label: "我创建的", count: counts.mine },
            ]}
            value={tab}
            onChange={setTab}
          />
          <div className="relative ml-auto w-[230px] max-w-full">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <Input
              className="!py-1.5 !pl-8 !text-[12.5px]"
              placeholder="搜索技能名称、描述、标签"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </div>
          <Select className="!w-[130px] !py-1.5 !text-[12.5px]" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">全部分类</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
          {tab === "mine" && (
            <Button variant="outline" size="sm" onClick={() => void load()} icon={<RefreshCw size={13} />}>
              刷新
            </Button>
          )}
        </div>

        <div className="mt-4">
          {loading ? (
            <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Card key={i} className="p-4">
                  <div className="flex items-center gap-3">
                    <Skeleton className="h-10 w-10 rounded-xl" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-3 w-1/2" />
                      <Skeleton className="h-2.5 w-1/3" />
                    </div>
                  </div>
                  <Skeleton className="mt-3 h-8 w-full" />
                  <Skeleton className="mt-3 h-3 w-2/3" />
                </Card>
              ))}
            </div>
          ) : error ? (
            <Card>
              <Empty
                title="技能列表加载失败"
                desc={error}
                icon={<Store size={20} />}
                action={
                  <Button variant="outline" onClick={() => void load()} icon={<RefreshCw size={14} />}>
                    重试
                  </Button>
                }
              />
            </Card>
          ) : visible.length === 0 ? (
            <Card>
              <Empty
                title={
                  keyword || category
                    ? "没有匹配的技能"
                    : tab === "installed"
                      ? "还没有安装技能"
                      : tab === "mine"
                        ? "你还没有创建技能"
                        : "市场里暂时没有可安装的技能"
                }
                desc={
                  keyword || category
                    ? "试试清空搜索词或切换分类。"
                    : tab === "installed"
                      ? "去「技能市场」装一个，员工装上技能后才会获得对应工具。"
                      : tab === "mine"
                        ? "把部门里的做事方法写成 SKILL.md，提交审核后可复用。"
                        : "等管理员上架新技能，或自己创建一个。"
                }
                icon={<Package size={20} />}
                action={
                  keyword || category ? (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setKeyword("");
                        setCategory("");
                      }}
                    >
                      清空筛选
                    </Button>
                  ) : tab === "installed" ? (
                    <Button onClick={() => setTab("market")} icon={<Store size={14} />}>
                      去技能市场
                    </Button>
                  ) : tab === "mine" ? (
                    <Button onClick={() => setCreateOpen(true)} icon={<Plus size={14} />}>
                      创建技能
                    </Button>
                  ) : undefined
                }
              />
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
              {visible.map((s) => {
                const Icon = skillIcon(s.icon);
                const busy = busyId === s.id;
                return (
                  <Card
                    key={s.id}
                    className="card-hover flex cursor-pointer flex-col p-4"
                    onClick={() => void openSkill(s.id)}
                  >
                    <div className="flex items-start gap-3">
                      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600">
                        <Icon size={17} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-[13px] font-semibold text-ink-900">{s.displayName}</span>
                          <span className="shrink-0 text-[10.5px] text-ink-400">v{s.version}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-1">
                          <span className={cx("chip border", riskBadgeClass(s.riskLevel))}>
                            {riskLabel[s.riskLevel] || s.riskLevel}
                          </span>
                          <span className="chip border border-surface-300 bg-surface-50 text-ink-500">
                            {s.source === "builtin" ? "内置" : "用户"}
                          </span>
                          <span className="chip border border-surface-300 bg-surface-50 text-ink-500">{s.category || "未分类"}</span>
                          {tab === "mine" && <StatusBadge status={s.status} />}
                        </div>
                      </div>
                      {s.installed && tab !== "installed" && (
                        <Badge tone="green" className="shrink-0">
                          已安装
                        </Badge>
                      )}
                    </div>

                    <p className="mt-3 line-clamp-2 min-h-[34px] text-[12px] leading-[1.6] text-ink-500">{s.description}</p>

                    {(s.tags || []).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {(s.tags || []).slice(0, 4).map((t) => (
                          <span key={t} className="rounded-md bg-surface-100 px-1.5 py-0.5 text-[10px] text-ink-500">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="mt-3 flex items-center gap-2 border-t border-surface-200 pt-3">
                      <span className="inline-flex items-center gap-1 text-[11px] text-ink-400">
                        <Download size={11} /> {formatNumber(s.installs)} 次安装
                      </span>
                      <div className="ml-auto flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="!px-2 !py-1.5"
                          onClick={() => void openSkill(s.id)}
                          icon={<Eye size={13} />}
                        >
                          查看
                        </Button>
                        {s.installed ? (
                          <Button
                            size="sm"
                            variant="outline"
                            className="!px-2 !py-1.5"
                            loading={busy}
                            onClick={() => void uninstall(s)}
                            icon={<Trash2 size={13} />}
                          >
                            卸载
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            className="!px-2 !py-1.5"
                            loading={busy}
                            disabled={s.status !== "approved"}
                            onClick={() => void install(s)}
                            icon={<Check size={13} />}
                          >
                            安装
                          </Button>
                        )}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ---------------- SKILL.md 详情 ---------------- */}
      <Drawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title={
          <span className="flex items-center gap-2">
            <BookOpen size={15} className="text-brand-600" /> {detail?.displayName || "SKILL.md"}
          </span>
        }
        desc={detail ? `${detail.name} · v${detail.version} · ${detail.source === "builtin" ? "内置技能" : "用户技能"}` : "查看技能定义与安全扫描结果"}
        width="w-[640px]"
        footer={
          detail ? (
            detail.installed ? (
              <Button variant="outline" loading={busyId === detail.id} onClick={() => void uninstall(detail)} icon={<Trash2 size={14} />}>
                卸载技能
              </Button>
            ) : (
              <Button
                loading={busyId === detail.id}
                disabled={detail.status !== "approved"}
                onClick={() => void install(detail)}
                icon={<Check size={14} />}
              >
                安装技能
              </Button>
            )
          ) : undefined
        }
      >
        {detailLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        ) : detailError ? (
          <Empty title="技能详情加载失败" desc={detailError} icon={<Store size={18} />} />
        ) : detail ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className={cx("chip border", riskBadgeClass(detail.riskLevel))}>
                {riskLabel[detail.riskLevel] || detail.riskLevel}
              </span>
              <span className="chip border border-surface-300 bg-surface-50 text-ink-500">{detail.category || "未分类"}</span>
              <span className="chip border border-surface-300 bg-surface-50 text-ink-500">{formatNumber(detail.installs)} 次安装</span>
              {detail.installed && <Badge tone="green">已安装</Badge>}
              {detail.source === "user" && <StatusBadge status={detail.status} />}
              {detail.updatedAt && <span className="text-[10.5px] text-ink-400">更新于 {timeAgo(detail.updatedAt)}</span>}
            </div>

            <p className="text-[12.5px] leading-relaxed text-ink-600">{detail.description || "暂无描述"}</p>

            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <div className="card p-3">
                <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium text-ink-600">
                  <Wrench size={12} /> 工具清单（{(detail.toolNames || []).length}）
                </div>
                {(detail.toolNames || []).length === 0 ? (
                  <div className="text-[11.5px] text-ink-400">该技能未声明工具（前端仅展示文档能力）</div>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {(detail.toolNames || []).map((t) => (
                      <code key={t} className="rounded-md bg-surface-100 px-1.5 py-0.5 font-mono text-[10.5px] text-ink-600">
                        {t}
                      </code>
                    ))}
                  </div>
                )}
              </div>
              <div className="card p-3">
                <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium text-ink-600">
                  <ShieldAlert size={12} /> 安全扫描
                </div>
                {detail.scan?.findings?.length ? (
                  <div className="space-y-1">
                    {detail.scan.findings.map((f, i) => (
                      <div key={i} className="rounded-lg border border-surface-200 px-2 py-1.5">
                        <div className="flex items-center gap-1.5">
                          <span className={cx("chip border", riskBadgeClass(f.severity))}>{riskLabel[f.severity] || f.severity}</span>
                          <span className="truncate font-mono text-[10.5px] text-ink-600">{f.pattern}</span>
                          <span className="ml-auto text-[10px] text-ink-400">L{f.line}</span>
                        </div>
                        <div className="mt-1 truncate font-mono text-[10.5px] text-ink-400">{f.snippet}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[11.5px] text-emerald-600">未发现敏感指令、外联地址或危险调用。</div>
                )}
              </div>
            </div>

            <div>
              <div className="mb-1.5 text-[11.5px] font-medium text-ink-600">SKILL.md</div>
              <SkillDoc content={detail.content || ""} />
            </div>
          </div>
        ) : null}
      </Drawer>

      {/* ---------------- 创建技能 ---------------- */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="创建技能"
        desc="编写 SKILL.md 描述能力边界与工作流；提交后需管理员审核通过才能被其他人安装。"
        width="max-w-3xl"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreateOpen(false)} disabled={creating}>
              取消
            </Button>
            <Button onClick={() => void submitCreate()} loading={creating} icon={<Check size={14} />}>
              提交审核
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="技能名称">
              <Input
                value={form.displayName}
                onChange={(e) => setForm({ ...form, displayName: e.target.value })}
                placeholder="例如：合同条款比对"
                maxLength={64}
              />
            </Field>
            <Field label="分类">
              <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                {CATEGORY_OPTIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="一句话描述" hint="说明解决什么问题、给谁用">
            <Input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="例如：按公司标准规则比对合同条款并给出修订建议"
            />
          </Field>
          <Field label="标签" hint="用逗号或空格分隔">
            <Input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder="合同, 法务, 风险" />
          </Field>
          <Field label="SKILL.md 内容" hint="包含 YAML frontmatter（name / description / risk / tools）与能力边界">
            <Textarea
              rows={14}
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              className="!min-h-[260px] font-mono !text-[11.5px]"
            />
          </Field>
          <div className="flex items-start gap-1.5 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2 text-[11.5px] text-amber-800">
            <Loader2 size={12} className="mt-0.5 shrink-0" />
            提交后进入「待审核」，管理员审核通过后其他用户才能安装；你自己的员工可先使用。
          </div>
        </div>
      </Modal>
    </div>
  );
}
