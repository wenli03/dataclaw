import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Bot,
  Brain,
  Check,
  Copy,
  Loader2,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  UserRound,
  Users,
  X,
} from "lucide-react";
import type { Employee, EmployeeSkillRef, MemoryItem, Skill, Template } from "../lib/types";
import { api } from "../lib/api";
import { avatarPalette, cx, riskBadgeClass, riskLabel, timeAgo } from "../lib/format";
import { Avatar, Badge, Button, Card, Drawer, Empty, Field, Input, Modal, Select, Skeleton, Tabs, Textarea, Toggle, toast } from "../components/ui";

/* ---------------- 工具 ---------------- */
function errText(e: unknown): string {
  const msg = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  if (!msg || /failed to fetch|networkerror|load failed/i.test(msg)) return "服务暂不可用，请确认后端已启动";
  return msg;
}

type ListResp<T> = { items?: T[]; total?: number };
type TemplateItem = Template & { skills?: { id: string; name: string; displayName?: string }[] };
type EmployeeResp = { employee?: Employee };
type SkillResp = { skills?: EmployeeSkillRef[]; skillCount?: number };

const AVATAR_SEEDS = ["avatar-01", "avatar-02", "avatar-03", "avatar-04", "avatar-05", "avatar-06", "avatar-07", "avatar-08"];

function clip(text: string, limit = 90): string {
  return text.length > limit ? `${text.slice(0, limit).trim()}…` : text;
}

/**
 * 从 SOUL.md 提炼卡片摘要：跳过 frontmatter / 标题 / 引用 / 表格 / 列表行，
 * 取第一段有意义的正文（≥20 字），截断 90 字。取不到就返回空串，由调用方兜底。
 */
export function soulSummary(soul?: string): string {
  if (!soul) return "";
  const text = soul.replace(/^\uFEFF/, "").replace(/^---[\s\S]*?\n---\s*\n?/, "");
  const cleanInline = (s: string) =>
    s
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/\*\*|__|`/g, "")
      .replace(/\s+/g, " ")
      .trim();

  const candidates: string[] = [];
  for (const block of text.split(/\r?\n\s*\r?\n/)) {
    const lines = block
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(
        (l) =>
          Boolean(l) &&
          !/^(#{1,6}\s|>|\||[-*+]\s|\d+[.、)]\s|---|\*\*\*)/.test(l) &&
          !/^\|?[\s:|-]{3,}\|?$/.test(l)
      );
    if (lines.length === 0) continue;
    const paragraph = cleanInline(lines.join(" "));
    if (paragraph) candidates.push(paragraph);
  }

  const good = candidates.find((c) => c.length >= 20) || candidates.sort((a, b) => b.length - a.length)[0] || "";
  if (good.length < 8) return "";
  return clip(good);
}

function AvatarPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {AVATAR_SEEDS.map((seed) => {
        const { bg, fg } = avatarPalette(seed);
        const active = value === seed;
        return (
          <button
            key={seed}
            type="button"
            onClick={() => onChange(seed)}
            className={cx(
              "relative grid h-9 w-9 place-items-center rounded-full transition",
              active ? "ring-2 ring-brand-500 ring-offset-2" : "hover:opacity-85"
            )}
            style={{ background: bg, color: fg }}
            title={seed}
          >
            <Bot size={16} />
            {active && <Check size={11} className="absolute -right-1 -top-1 rounded-full bg-brand-600 p-[1px] text-white" />}
          </button>
        );
      })}
    </div>
  );
}

/* ---------------- 页面 ---------------- */
export default function Employees() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();

  const [tab, setTab] = useState("mine");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");

  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [catalog, setCatalog] = useState<Skill[]>([]);
  const [soulById, setSoulById] = useState<Record<string, string>>({});

  const [createOpen, setCreateOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [form, setForm] = useState({
    name: "",
    roleTitle: "",
    avatar: "avatar-01",
    soul: "",
    templateId: null as string | null,
    skills: [] as string[],
  });
  const [submitting, setSubmitting] = useState(false);

  const [detailOpen, setDetailOpen] = useState(false);
  const [detailId, setDetailId] = useState("");
  const [detail, setDetail] = useState<Employee | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [soulEditing, setSoulEditing] = useState(false);
  const [soulDraft, setSoulDraft] = useState("");
  const [profileEditing, setProfileEditing] = useState(false);
  const [profileDraft, setProfileDraft] = useState({ name: "", roleTitle: "", avatar: "avatar-01" });
  const [saving, setSaving] = useState(false);
  const [addSkillId, setAddSkillId] = useState("");
  const [busySkillId, setBusySkillId] = useState("");

  const [deleteTarget, setDeleteTarget] = useState<Employee | null>(null);
  const [deleting, setDeleting] = useState(false);

  /* ---------------- 列表 ---------------- */
  const load = useCallback(async (scope: string) => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get<ListResp<Employee>>("/employees", { scope });
      setEmployees(Array.isArray(res.items) ? res.items : []);
    } catch (e) {
      setError(errText(e));
      setEmployees([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(tab);
  }, [tab, load]);

  /**
   * 列表接口只给 description（常是 SOUL 里的标题行），卡片摘要需要 SOUL 正文：
   * 对还没有缓存的员工补一次详情（上限 24 个），结果按 id 缓存。
   */
  useEffect(() => {
    const pending = employees.filter((e) => e.id && soulById[e.id] === undefined).slice(0, 24);
    if (pending.length === 0) return;
    let alive = true;
    void Promise.all(
      pending.map(async (e) => {
        try {
          const res = await api.get<EmployeeResp>(`/employees/${e.id}`);
          return [e.id, res.employee?.soulMd || ""] as const;
        } catch {
          return [e.id, ""] as const;
        }
      })
    ).then((entries) => {
      if (!alive) return;
      setSoulById((prev) => {
        const next = { ...prev };
        entries.forEach(([id, soul]) => {
          next[id] = soul;
        });
        return next;
      });
    });
    return () => {
      alive = false;
    };
  }, [employees, soulById]);

  const loadCatalog = useCallback(async () => {
    try {
      const [installed, market] = await Promise.all([
        api.get<ListResp<Skill>>("/skills", { tab: "installed", size: 200 }),
        api.get<ListResp<Skill>>("/skills", { tab: "market", size: 200 }),
      ]);
      const map = new Map<string, Skill>();
      [...(installed.items || []), ...(market.items || [])].forEach((s) => map.set(s.id, s));
      setCatalog(Array.from(map.values()));
    } catch {
      setCatalog([]);
    }
  }, []);

  useEffect(() => {
    void loadCatalog();
    void (async () => {
      try {
        const res = await api.get<ListResp<TemplateItem>>("/templates");
        setTemplates(Array.isArray(res.items) ? res.items : []);
      } catch {
        setTemplates([]);
      }
    })();
  }, [loadCatalog]);

  /* ---------------- 详情 ---------------- */
  const openDetail = useCallback(async (id: string) => {
    setDetailOpen(true);
    setDetailId(id);
    setDetailLoading(true);
    setDetailError("");
    setSoulEditing(false);
    setProfileEditing(false);
    try {
      const res = await api.get<EmployeeResp>(`/employees/${id}`);
      const emp = res.employee || null;
      setDetail(emp);
      setSoulDraft(emp?.soulMd || "");
      setProfileDraft({ name: emp?.name || "", roleTitle: emp?.roleTitle || "", avatar: emp?.avatar || "avatar-01" });
    } catch (e) {
      setDetail(null);
      setDetailError(errText(e));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    const focus = params.get("focus");
    if (!focus) return;
    void openDetail(focus);
    const next = new URLSearchParams(params);
    next.delete("focus");
    setParams(next, { replace: true });
  }, [openDetail, params, setParams]);

  const refreshDetail = useCallback(async (id: string) => {
    try {
      const res = await api.get<EmployeeResp>(`/employees/${id}`);
      setDetail(res.employee || null);
    } catch {
      /* 忽略刷新失败 */
    }
  }, []);

  /* ---------------- 新建 ---------------- */
  /**
   * 绑定技能前先确保可用：内置已审核技能可直接绑定；
   * 其它技能必须先安装到当前用户（否则后端 can_bind_skill 会 403）。
   */
  const ensureBindable = useCallback(
    async (ids: string[]) => {
      for (const id of ids) {
        const skill = catalog.find((s) => s.id === id);
        if (!skill) continue;
        if (skill.installed) continue;
        if (skill.source === "builtin" && skill.status === "approved") continue;
        await api.post<unknown>(`/skills/${id}/install`, {});
      }
    },
    [catalog]
  );

  const openCreate = () => {
    setStep(1);
    setForm({ name: "", roleTitle: "", avatar: "avatar-01", soul: "", templateId: null, skills: [] });
    setCreateOpen(true);
  };

  const selectTemplate = (tpl: TemplateItem | null) => {
    const skillIds = tpl
      ? tpl.skills?.map((s) => s.id) ?? (tpl.defaultSkills || []).map((code) => catalog.find((s) => s.name === code)?.id).filter((x): x is string => Boolean(x))
      : [];
    setForm({
      name: tpl?.name || "",
      roleTitle: tpl?.roleTitle || "",
      avatar: tpl?.avatar || "avatar-01",
      soul: tpl?.soulMd || "",
      templateId: tpl?.id || null,
      skills: Array.from(new Set(skillIds)),
    });
    setStep(2);
  };

  const submitCreate = async () => {
    if (!form.name.trim()) {
      toast("请填写员工名称", "error");
      return;
    }
    setSubmitting(true);
    try {
      await ensureBindable(form.skills);
      await api.post<EmployeeResp>("/employees", {
        name: form.name.trim(),
        templateId: form.templateId,
        roleTitle: form.roleTitle.trim(),
        avatar: form.avatar,
        soul: form.soul,
        skills: form.skills,
      });
      toast("数字员工已创建");
      setCreateOpen(false);
      if (tab !== "mine") setTab("mine");
      else await load("mine");
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setSubmitting(false);
    }
  };

  /* ---------------- 详情内操作 ---------------- */
  const patchEmployee = useCallback(
    async (body: Record<string, unknown>, okMsg: string): Promise<boolean> => {
      if (!detail) return false;
      setSaving(true);
      try {
        const res = await api.patch<EmployeeResp>(`/employees/${detail.id}`, body);
        if (res.employee) {
          setDetail(res.employee);
          setSoulDraft(res.employee.soulMd || "");
          setProfileDraft({ name: res.employee.name, roleTitle: res.employee.roleTitle || "", avatar: res.employee.avatar || "avatar-01" });
          setEmployees((prev) => prev.map((e) => (e.id === res.employee?.id ? { ...e, ...res.employee } : e)));
        }
        toast(okMsg);
        return true;
      } catch (e) {
        toast(errText(e), "error");
        return false;
      } finally {
        setSaving(false);
      }
    },
    [detail]
  );

  const toggleSkill = async (skill: EmployeeSkillRef, enabled: boolean) => {
    if (!detail) return;
    setBusySkillId(skill.id);
    try {
      const res = await api.post<SkillResp>(`/employees/${detail.id}/skills`, { skillId: skill.id, enabled });
      const skills = res.skills || [];
      setDetail({ ...detail, skills });
      toast(enabled ? `已启用「${skill.displayName}」` : `已移除「${skill.displayName}」`);
      void refreshDetail(detail.id);
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setBusySkillId("");
    }
  };

  const addSkill = async () => {
    if (!detail || !addSkillId) return;
    const skill = catalog.find((s) => s.id === addSkillId);
    if (!skill) return;
    setBusySkillId(addSkillId);
    try {
      await ensureBindable([addSkillId]);
      const res = await api.post<SkillResp>(`/employees/${detail.id}/skills`, { skillId: addSkillId, enabled: true });
      setDetail({ ...detail, skills: res.skills || [] });
      setAddSkillId("");
      toast(`已添加「${skill.displayName}」`);
      void refreshDetail(detail.id);
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setBusySkillId("");
    }
  };

  const removeMemory = async (mid: string) => {
    if (!detail) return;
    try {
      await api.del<unknown>(`/employees/${detail.id}/memory/${mid}`);
      setDetail({ ...detail, memory: (detail.memory || []).filter((m) => m.id !== mid) });
      toast("记忆已删除");
    } catch (e) {
      toast(errText(e), "error");
    }
  };

  const duplicate = async (emp: Employee) => {
    try {
      await api.post<EmployeeResp>(`/employees/${emp.id}/duplicate`);
      toast("已复制为我的员工");
      void load(tab);
    } catch (e) {
      toast(errText(e), "error");
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del<unknown>(`/employees/${deleteTarget.id}`);
      toast("员工已删除");
      setDeleteTarget(null);
      if (detail?.id === deleteTarget.id) setDetailOpen(false);
      void load(tab);
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setDeleting(false);
    }
  };

  /* ---------------- 派生 ---------------- */
  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return employees;
    return employees.filter(
      (e) => (e.name || "").toLowerCase().includes(kw) || (e.roleTitle || "").toLowerCase().includes(kw)
    );
  }, [employees, keyword]);

  const boundSkillIds = new Set((detail?.skills || []).map((s) => s.id));
  const addableSkills = catalog.filter((s) => !boundSkillIds.has(s.id));
  const memoryList = detail?.memory || [];

  const sourceBadge = (emp: Employee) =>
    emp.publicAgent ? `公共 v${emp.publicAgent.version}` : emp.source === "from_public" ? "公共员工" : "个人";

  /* ---------------- 渲染 ---------------- */
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[1320px] px-5 py-5 lg:px-7">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-semibold tracking-tight text-ink-900">数字员工</h1>
            <p className="mt-1 text-[12.5px] text-ink-500">
              基于角色模板一键创建，绑定技能与 SOUL 设定，权限继承自你的账号。
            </p>
          </div>
          <Button onClick={openCreate} icon={<Plus size={14} />}>
            新建员工
          </Button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Tabs
            items={[
              { key: "mine", label: "我的员工" },
              { key: "public", label: "公共员工" },
            ]}
            value={tab}
            onChange={setTab}
          />
          <div className="relative ml-auto w-[220px] max-w-full">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
            <Input
              className="!py-1.5 !pl-8 !text-[12.5px]"
              placeholder="搜索名称或角色"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </div>
        </div>

        {tab === "public" && (
          <div className="mt-3 rounded-xl border border-brand-100 bg-brand-50/60 px-3 py-2 text-[11.5px] text-brand-800">
            公共员工由管理员统一定义并按版本下发，这里是分配给你的专属副本：可独立编辑 SOUL、记忆与技能，产出的数据仍按你的权限过滤。
          </div>
        )}

        <div className="mt-4">
          {loading ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-3.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Card key={i} className="p-4">
                  <div className="flex items-center gap-3">
                    <Skeleton className="h-11 w-11 rounded-full" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-3 w-1/2" />
                      <Skeleton className="h-2.5 w-2/3" />
                    </div>
                  </div>
                  <Skeleton className="mt-3 h-8 w-full" />
                  <Skeleton className="mt-3 h-3 w-3/4" />
                </Card>
              ))}
            </div>
          ) : error ? (
            <Card>
              <Empty
                title="员工列表加载失败"
                desc={error}
                icon={<Users size={20} />}
                action={
                  <Button variant="outline" onClick={() => void load(tab)} icon={<RefreshCw size={14} />}>
                    重试
                  </Button>
                }
              />
            </Card>
          ) : filtered.length === 0 ? (
            <Card>
              <Empty
                title={keyword ? "没有匹配的员工" : tab === "public" ? "还没有分配给你的公共员工" : "还没有数字员工"}
                desc={
                  keyword
                    ? "换个关键词试试"
                    : tab === "public"
                      ? "管理员把公共员工分配给你之后，这里会出现带团队定义的专属副本。"
                      : "从一个角色模板开始，3 步内建成一个可对话的数字员工。"
                }
                icon={<Bot size={20} />}
                action={
                  keyword ? undefined : (
                    <Button onClick={tab === "public" ? () => setTab("mine") : openCreate} icon={<Sparkles size={14} />}>
                      {tab === "public" ? "看看我的员工" : "新建员工"}
                    </Button>
                  )
                }
              />
            </Card>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-3.5">
              {filtered.map((emp) => {
                const summary =
                  soulSummary(soulById[emp.id]) || soulSummary(emp.description) || soulSummary(emp.greeting) || "";
                return (
                <Card key={emp.id} className="card-hover flex flex-col p-4">
                  <div className="flex items-start gap-3">
                    <Avatar name={emp.name} seed={emp.avatar || emp.id} size={44} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[13.5px] font-semibold text-ink-900">{emp.name}</span>
                        <Badge tone={emp.source === "from_public" ? "brand" : "gray"}>{sourceBadge(emp)}</Badge>
                      </div>
                      <div className="mt-0.5 truncate text-[11.5px] text-ink-500">
                        {emp.roleTitle && emp.roleTitle !== emp.name ? emp.roleTitle : "数字员工"}
                      </div>
                    </div>
                    <button
                      onClick={() => void openDetail(emp.id)}
                      className="rounded-lg p-1 text-ink-300 transition hover:bg-surface-100 hover:text-ink-700"
                      title="编辑"
                    >
                      <Pencil size={13} />
                    </button>
                  </div>

                  <p className="mt-3 line-clamp-2 min-h-[34px] text-[12px] leading-[1.6] text-ink-500">
                    {summary || "还没有 SOUL 摘要，点「编辑」补充角色定位与工作方式。"}
                  </p>

                  <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-400">
                    <span className="inline-flex items-center gap-1">
                      <Sparkles size={11} /> {emp.skillCount ?? 0} 技能
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <MessageSquare size={11} /> {emp.sessionCount ?? 0} 会话
                    </span>
                    <span>{emp.lastActiveAt ? timeAgo(emp.lastActiveAt) : "未使用"}</span>
                  </div>

                  <div className="mt-3 flex items-center gap-1.5 border-t border-surface-200 pt-3">
                    <Button
                      size="sm"
                      onClick={() => nav(`/chat/${emp.id}`)}
                      icon={<MessageSquare size={13} />}
                      className="!px-2.5 !py-1.5"
                    >
                      对话
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void openDetail(emp.id)}
                      icon={<Pencil size={13} />}
                      className="!px-2.5 !py-1.5"
                    >
                      编辑
                    </Button>
                    <div className="ml-auto flex items-center gap-0.5">
                      <button
                        title="复制为我自己的员工"
                        onClick={() => void duplicate(emp)}
                        className="rounded-lg p-1.5 text-ink-400 hover:bg-surface-100 hover:text-ink-800"
                      >
                        <Copy size={13} />
                      </button>
                      <button
                        title="删除"
                        onClick={() => setDeleteTarget(emp)}
                        className="rounded-lg p-1.5 text-ink-400 hover:bg-rose-50 hover:text-rose-600"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ---------------- 新建员工 ---------------- */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={step === 1 ? "选择角色模板" : "创建数字员工"}
        desc={step === 1 ? "从内置角色模板开始，或自定义一个空白员工" : "填写基础信息、SOUL 设定与初始技能"}
        width="max-w-3xl"
        footer={
          step === 1 ? (
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => setStep(1)} disabled={submitting}>
                上一步
              </Button>
              <Button onClick={() => void submitCreate()} loading={submitting} icon={<Check size={14} />}>
                创建员工
              </Button>
            </>
          )
        }
      >
        {step === 1 ? (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {templates.map((tpl) => (
              <button
                key={tpl.id}
                type="button"
                onClick={() => selectTemplate(tpl)}
                className="card card-hover flex items-start gap-3 p-3.5 text-left"
              >
                <Avatar name={tpl.name} seed={tpl.avatar || tpl.id} size={38} />
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold text-ink-900">{tpl.name}</div>
                  <div className="text-[11px] text-ink-500">{tpl.roleTitle}</div>
                  <div className="mt-1 line-clamp-2 text-[11.5px] leading-relaxed text-ink-400">{tpl.description}</div>
                </div>
              </button>
            ))}
            <button
              type="button"
              onClick={() => selectTemplate(null)}
              className="card card-hover flex items-start gap-3 border-dashed p-3.5 text-left"
            >
              <span className="grid h-[38px] w-[38px] shrink-0 place-items-center rounded-full bg-surface-100 text-ink-400">
                <Plus size={17} />
              </span>
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-ink-900">自定义员工</div>
                <div className="text-[11px] text-ink-500">从空白开始</div>
                <div className="mt-1 text-[11.5px] leading-relaxed text-ink-400">
                  自己写 SOUL.md、选技能，适合有明确岗位职责的场景。
                </div>
              </div>
            </button>
            {templates.length === 0 && (
              <div className="col-span-full rounded-xl border border-dashed border-surface-300 px-3 py-4 text-center text-[11.5px] text-ink-400">
                角色模板接口暂不可用，可直接使用「自定义员工」创建。
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3.5">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="员工名称" hint="会显示在会话列表与回复署名上">
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="例如：林知微"
                  maxLength={64}
                />
              </Field>
              <Field label="角色 / 岗位">
                <Input
                  value={form.roleTitle}
                  onChange={(e) => setForm({ ...form, roleTitle: e.target.value })}
                  placeholder="例如：数据分析师"
                />
              </Field>
            </div>

            <Field label="头像" hint="选择一个头像色板">
              <AvatarPicker value={form.avatar} onChange={(avatar) => setForm({ ...form, avatar })} />
            </Field>

            <Field label="SOUL 设定（Markdown）" hint="决定数字员工的角色、语气、工作方式与输出规范">
              <Textarea
                rows={7}
                value={form.soul}
                onChange={(e) => setForm({ ...form, soul: e.target.value })}
                placeholder={"# 你是谁\n你是……\n\n## 核心原则\n1. ……"}
                className="!min-h-[150px] font-mono !text-[12px]"
              />
            </Field>

            <div>
              <div className="label">初始技能（可选）</div>
              {catalog.length === 0 ? (
                <div className="rounded-xl border border-dashed border-surface-300 px-3 py-3 text-[11.5px] text-ink-400">
                  技能列表暂不可用，可先创建员工，稍后在详情里添加技能。
                </div>
              ) : (
                <>
                  <div className="flex max-h-[168px] flex-wrap gap-1.5 overflow-y-auto rounded-xl border border-surface-200 p-2.5">
                    {catalog.map((s) => {
                      const active = form.skills.includes(s.id);
                      return (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() =>
                            setForm({
                              ...form,
                              skills: active ? form.skills.filter((id) => id !== s.id) : [...form.skills, s.id],
                            })
                          }
                          className={cx(
                            "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11.5px] transition",
                            active
                              ? "border-brand-300 bg-brand-50 text-brand-700"
                              : "border-surface-300 bg-white text-ink-600 hover:border-brand-200"
                          )}
                        >
                          {active && <Check size={11} />}
                          {s.displayName}
                          <span className={cx("chip border !px-1.5 !py-0 !text-[9.5px]", riskBadgeClass(s.riskLevel))}>
                            {riskLabel[s.riskLevel] || s.riskLevel}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="mt-1 text-[10.5px] text-ink-400">
                    未安装的市场技能会在创建时自动安装到你的账号；之后可在详情里随时启用或移除。
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* ---------------- 员工详情 ---------------- */}
      <Drawer
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title={
          <span className="flex items-center gap-2">
            <UserRound size={15} className="text-brand-600" /> {detail?.name || "员工详情"}
          </span>
        }
        desc={detail ? `${detail.roleTitle || "数字员工"} · ${sourceBadge(detail)}` : "配置形象、SOUL 与技能"}
        width="w-[600px]"
        footer={
          detail ? (
            <>
              <Button variant="danger" onClick={() => setDeleteTarget(detail)} icon={<Trash2 size={14} />}>
                删除员工
              </Button>
              <Button onClick={() => nav(`/chat/${detail.id}`)} icon={<MessageSquare size={14} />}>
                开始对话
              </Button>
            </>
          ) : undefined
        }
      >
        {detailLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : detailError ? (
          <Empty
            title="员工详情加载失败"
            desc={detailError}
            icon={<Bot size={18} />}
            action={
              <Button variant="outline" onClick={() => void openDetail(detailId)} icon={<RefreshCw size={14} />}>
                重试
              </Button>
            }
          />
        ) : detail ? (
          <div className="space-y-3">
            {/* 基本信息 */}
            <section className="card p-3.5">
              {profileEditing ? (
                <div className="space-y-2.5">
                  <div className="flex items-center gap-3">
                    <Avatar name={profileDraft.name} seed={profileDraft.avatar} size={44} />
                    <div className="flex-1 space-y-1.5">
                      <Input
                        value={profileDraft.name}
                        onChange={(e) => setProfileDraft({ ...profileDraft, name: e.target.value })}
                        placeholder="员工名称"
                      />
                      <Input
                        value={profileDraft.roleTitle}
                        onChange={(e) => setProfileDraft({ ...profileDraft, roleTitle: e.target.value })}
                        placeholder="角色 / 岗位"
                      />
                    </div>
                  </div>
                  <AvatarPicker value={profileDraft.avatar} onChange={(avatar) => setProfileDraft({ ...profileDraft, avatar })} />
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => setProfileEditing(false)}>
                      取消
                    </Button>
                    <Button
                      size="sm"
                      loading={saving}
                      onClick={() => {
                        void patchEmployee(
                          { name: profileDraft.name, roleTitle: profileDraft.roleTitle, avatar: profileDraft.avatar },
                          "员工资料已更新"
                        ).then((ok) => ok && setProfileEditing(false));
                      }}
                    >
                      保存
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-3">
                  <Avatar name={detail.name} seed={detail.avatar || detail.id} size={48} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-[15px] font-semibold text-ink-900">{detail.name}</span>
                      <Badge tone={detail.source === "from_public" ? "brand" : "gray"}>{sourceBadge(detail)}</Badge>
                    </div>
                    <div className="mt-0.5 text-[12px] text-ink-500">{detail.roleTitle || "数字员工"}</div>
                    <div className="mt-1.5 text-[11px] text-ink-400">
                      {detail.stats?.sessions ?? 0} 次会话 · {detail.stats?.toolCalls ?? 0} 次工具调用 · {detail.stats?.artifacts ?? 0} 个产物
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      setProfileDraft({
                        name: detail.name,
                        roleTitle: detail.roleTitle || "",
                        avatar: detail.avatar || "avatar-01",
                      });
                      setProfileEditing(true);
                    }}
                    className="rounded-lg p-1.5 text-ink-400 hover:bg-surface-100 hover:text-ink-800"
                    title="编辑资料"
                  >
                    <Pencil size={13} />
                  </button>
                </div>
              )}
            </section>

            {/* 记忆开关 */}
            <section className="card flex items-center gap-3 p-3.5">
              <span className="grid h-8 w-8 place-items-center rounded-xl bg-teal-50 text-teal-600">
                <Brain size={15} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] font-medium text-ink-800">记忆</div>
                <div className="mt-0.5 text-[11px] text-ink-500">
                  开启后，数字员工会记住你的偏好与分析口径，记忆按员工隔离、可随时删除。
                </div>
              </div>
              <Toggle
                checked={detail.memoryEnabled}
                disabled={saving}
                onChange={(v) => void patchEmployee({ memoryEnabled: v }, v ? "记忆已开启" : "记忆已关闭")}
              />
            </section>

            {/* Agent 设定 */}
            <section className="card p-3.5">
              <div className="flex items-center gap-2">
                <span className="grid h-8 w-8 place-items-center rounded-xl bg-brand-50 text-brand-600">
                  <Sparkles size={15} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] font-medium text-ink-800">Agent 设定（SOUL.md）</div>
                  <div className="mt-0.5 text-[11px] text-ink-500">风格与职责说明，修改后立即生效</div>
                </div>
                <button
                  onClick={() => {
                    setSoulDraft(detail.soulMd || "");
                    setSoulEditing((v) => !v);
                  }}
                  className="rounded-lg p-1.5 text-ink-400 hover:bg-surface-100 hover:text-ink-800"
                  title="编辑 SOUL"
                >
                  <Pencil size={13} />
                </button>
              </div>
              {soulEditing ? (
                <div className="mt-2.5">
                  <Textarea
                    rows={9}
                    value={soulDraft}
                    onChange={(e) => setSoulDraft(e.target.value)}
                    className="!min-h-[180px] font-mono !text-[12px]"
                    placeholder="# 你是谁……"
                  />
                  <div className="mt-2 flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => setSoulEditing(false)} disabled={saving}>
                      取消
                    </Button>
                    <Button
                      size="sm"
                      loading={saving}
                      onClick={() => {
                        void patchEmployee({ soulMd: soulDraft }, "SOUL 已更新").then((ok) => ok && setSoulEditing(false));
                      }}
                    >
                      保存设定
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="mt-2.5 max-h-[220px] overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-surface-200 bg-surface-50/60 p-3 text-[12px] leading-relaxed text-ink-600">
                  {detail.soulMd || "尚未配置 SOUL.md"}
                </div>
              )}
            </section>

            {/* 技能配置 */}
            <section className="card p-3.5">
              <div className="flex items-center gap-2">
                <span className="grid h-8 w-8 place-items-center rounded-xl bg-amber-50 text-amber-600">
                  <Bot size={15} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] font-medium text-ink-800">技能配置（{(detail.skills || []).filter((s) => s.enabled).length}）</div>
                  <div className="mt-0.5 text-[11px] text-ink-500">没装技能 = 没有工具，这是「权限即能力」的落点</div>
                </div>
              </div>

              <div className="mt-2.5 space-y-1.5">
                {(detail.skills || []).length === 0 ? (
                  <div className="rounded-xl border border-dashed border-surface-300 px-3 py-3 text-center text-[11.5px] text-ink-400">
                    还没有绑定技能
                  </div>
                ) : (
                  (detail.skills || []).map((s) => (
                    <div key={s.id} className="flex items-center gap-2 rounded-xl border border-surface-200 px-2.5 py-2">
                      <span className={cx("chip border", riskBadgeClass(s.riskLevel))}>{riskLabel[s.riskLevel || "low"] || s.riskLevel}</span>
                      <span className="min-w-0 flex-1 truncate text-[12px] text-ink-800">{s.displayName}</span>
                      <span className="text-[10.5px] text-ink-400">{s.enabled ? "已启用" : "已停用"}</span>
                      {s.enabled ? (
                        <button
                          onClick={() => void toggleSkill(s, false)}
                          disabled={busySkillId === s.id}
                          className="rounded-lg p-1 text-ink-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50"
                          title="移除"
                        >
                          {busySkillId === s.id ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
                        </button>
                      ) : (
                        <button
                          onClick={() => void toggleSkill(s, true)}
                          disabled={busySkillId === s.id}
                          className="rounded-lg p-1 text-ink-400 hover:bg-emerald-50 hover:text-emerald-600 disabled:opacity-50"
                          title="启用"
                        >
                          {busySkillId === s.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                        </button>
                      )}
                    </div>
                  ))
                )}
              </div>

              <div className="mt-2.5 flex items-center gap-2">
                <Select
                  value={addSkillId}
                  onChange={(e) => setAddSkillId(e.target.value)}
                  className="!py-1.5 !text-[12px]"
                >
                  <option value="">选择要添加的技能…</option>
                  {addableSkills.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.displayName}（{riskLabel[s.riskLevel] || s.riskLevel}）
                    </option>
                  ))}
                </Select>
                <Button size="sm" variant="outline" onClick={() => void addSkill()} disabled={!addSkillId || Boolean(busySkillId)} icon={<Plus size={13} />}>
                  添加
                </Button>
              </div>
              {addableSkills.length === 0 && catalog.length > 0 && (
                <div className="mt-1.5 text-[10.5px] text-ink-400">已装技能都已绑定，去技能超市安装更多技能。</div>
              )}
              {catalog.length === 0 && (
                <div className="mt-1.5 text-[10.5px] text-ink-400">技能列表暂不可用，稍后重试。</div>
              )}
            </section>

            {/* 记忆 */}
            <section className="card p-3.5">
              <div className="flex items-center gap-2">
                <span className="grid h-8 w-8 place-items-center rounded-xl bg-sky-50 text-sky-600">
                  <Brain size={15} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] font-medium text-ink-800">记忆（{memoryList.length}）</div>
                  <div className="mt-0.5 text-[11px] text-ink-500">按员工隔离的用户级记忆，可逐条删除</div>
                </div>
              </div>
              <div className="mt-2.5 space-y-1.5">
                {memoryList.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-surface-300 px-3 py-3 text-center text-[11.5px] text-ink-400">
                    还没有记忆，多聊几次会自动沉淀
                  </div>
                ) : (
                  memoryList.map((m: MemoryItem) => (
                    <div key={m.id} className="flex items-start gap-2 rounded-xl border border-surface-200 px-2.5 py-2">
                      <span className="chip border border-surface-300 bg-surface-50 text-ink-500">
                        {m.kind === "preference" ? "偏好" : m.kind === "playbook" ? "打法" : "事实"}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="whitespace-pre-wrap break-words text-[12px] text-ink-700">{m.content}</div>
                        <div className="mt-0.5 text-[10.5px] text-ink-400">{timeAgo(m.createdAt)}</div>
                      </div>
                      <button
                        onClick={() => void removeMemory(m.id)}
                        className="rounded-lg p-1 text-ink-400 hover:bg-rose-50 hover:text-rose-600"
                        title="删除记忆"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </section>
          </div>
        ) : null}
      </Drawer>

      {/* ---------------- 删除确认 ---------------- */}
      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="删除数字员工"
        desc="删除后该员工将不再出现在列表与会话入口；历史会话与产物保留在审计中。"
        width="max-w-md"
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" onClick={() => void confirmDelete()} loading={deleting} icon={<Trash2 size={14} />}>
              删除
            </Button>
          </>
        }
      >
        <div className="text-[12.5px] text-ink-600">
          确认删除「{deleteTarget?.name}」？该员工已装 {deleteTarget?.skillCount ?? 0} 个技能、{deleteTarget?.sessionCount ?? 0} 个会话。
        </div>
      </Modal>
    </div>
  );
}
