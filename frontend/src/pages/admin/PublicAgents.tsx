import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  Check,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  RefreshCw,
  Rocket,
  Search,
  Settings2,
  ShieldAlert,
  Trash2,
  UserPlus,
  UserMinus,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Paginated, PublicAgent, User } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Drawer,
  Empty,
  Field,
  Input,
  Modal,
  Skeleton,
  Tabs,
  Textarea,
  Tip,
  toast,
} from "@/components/ui";
import { PageHeader } from "@/components/admin/PageHeader";
import { cx, formatDateTime, formatNumber, statusLabel, timeAgo } from "@/lib/format";

/* ------------------------------------------------------------------ 契约类型 */

interface AgentItem extends PublicAgent {
  skills?: string[];
  soulMd?: string;
  pendingSync?: boolean;
  publishedAt?: string;
  createdBy?: string;
}

interface AssignmentItem {
  userId: string;
  userName: string;
  username: string;
  dept?: string;
  employeeId?: string | null;
  createdAt?: string;
}

interface SkillLite {
  id: string;
  displayName: string;
  description?: string;
  category?: string;
  riskLevel?: string;
}

interface AssignResult {
  createdCount?: number;
  skippedCount?: number;
  created?: { userId: string; employeeId?: string | null }[];
  skipped?: { userId: string; reason?: string }[];
  version?: number;
  synced?: number;
}

interface AgentForm {
  name: string;
  roleTitle: string;
  avatar: string;
  description: string;
  soulMd: string;
  skills: string[];
}

const EMPTY_FORM: AgentForm = { name: "", roleTitle: "", avatar: "avatar-01", description: "", soulMd: "", skills: [] };

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/* ------------------------------------------------------------------ 页面 */

export default function PublicAgents() {
  const { user: me } = useAuth();

  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [users, setUsers] = useState<User[]>([]);
  const [skills, setSkills] = useState<SkillLite[]>([]);
  const [refLoading, setRefLoading] = useState(true);

  // 分配明细
  const [expanded, setExpanded] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<Record<string, AssignmentItem[]>>({});
  const [assignLoading, setAssignLoading] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // 分配弹窗
  const [assignTarget, setAssignTarget] = useState<AgentItem | null>(null);
  const [assignSearch, setAssignSearch] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [assigning, setAssigning] = useState(false);

  // 编辑抽屉
  const [editor, setEditor] = useState<{ mode: "create" | "edit"; agent?: AgentItem } | null>(null);
  const [editorTab, setEditorTab] = useState("basic");
  const [form, setForm] = useState<AgentForm>(EMPTY_FORM);
  const [skillSearch, setSkillSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // 删除（下架）确认
  const [deleteTarget, setDeleteTarget] = useState<AgentItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadAgents = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Paginated<AgentItem>>("/public-agents");
      setAgents(res.items ?? []);
      setError(null);
    } catch (e: unknown) {
      setError(errText(e, "公共员工列表加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRefs = useCallback(async () => {
    setRefLoading(true);
    try {
      const [userRes, skillRes] = await Promise.all([
        api.get<Paginated<User>>("/users", { size: 200 }),
        api.get<Paginated<SkillLite>>("/skills", { tab: "market", size: 200 }),
      ]);
      setUsers(userRes.items ?? []);
      setSkills(skillRes.items ?? []);
    } catch {
      // 分配 / 技能下拉属于辅助数据，失败不阻塞主流程
      setUsers([]);
      setSkills([]);
    } finally {
      setRefLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAgents();
    void loadRefs();
  }, [loadAgents, loadRefs]);

  const loadAssignments = useCallback(async (agentId: string) => {
    setAssignLoading(agentId);
    try {
      const res = await api.get<Paginated<AssignmentItem>>(`/public-agents/${agentId}/assignments`);
      setAssignments((prev) => ({ ...prev, [agentId]: res.items ?? [] }));
    } catch (e: unknown) {
      toast(errText(e, "分配明细加载失败"), "error");
    } finally {
      setAssignLoading(null);
    }
  }, []);

  async function toggleExpand(agent: AgentItem) {
    if (expanded === agent.id) {
      setExpanded(null);
      return;
    }
    setExpanded(agent.id);
    if (!assignments[agent.id]) await loadAssignments(agent.id);
  }

  async function openAssign(agent: AgentItem) {
    setAssignTarget(agent);
    setAssignSearch("");
    setSelected([]);
    if (!assignments[agent.id]) await loadAssignments(agent.id);
  }

  const assignedIds = useMemo(() => {
    const list = assignTarget ? assignments[assignTarget.id] ?? [] : [];
    return new Set(list.map((a) => a.userId));
  }, [assignTarget, assignments]);

  const visibleUsers = useMemo(() => {
    const kw = assignSearch.trim().toLowerCase();
    if (!kw) return users;
    return users.filter(
      (u) =>
        (u.name || "").toLowerCase().includes(kw) ||
        (u.username || "").toLowerCase().includes(kw) ||
        (u.dept || "").toLowerCase().includes(kw)
    );
  }, [users, assignSearch]);

  function toggleUser(id: string) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function submitAssign() {
    if (!assignTarget || selected.length === 0) return;
    setAssigning(true);
    try {
      const res = await api.post<AssignResult>(`/public-agents/${assignTarget.id}/assign`, { userIds: selected });
      const created = res.createdCount ?? res.created?.length ?? 0;
      const skipped = res.skippedCount ?? res.skipped?.length ?? 0;
      toast(`新建 ${created} 个，跳过 ${skipped} 个`);
      setAssignTarget(null);
      setExpanded(assignTarget.id);
      await Promise.all([loadAgents(), loadAssignments(assignTarget.id)]);
    } catch (e: unknown) {
      toast(errText(e, "分配失败"), "error");
    } finally {
      setAssigning(false);
    }
  }

  async function unassign(agent: AgentItem, record: AssignmentItem) {
    setBusyId(record.userId);
    try {
      await api.del(`/public-agents/${agent.id}/assign/${record.userId}`);
      toast(`已取消 ${record.userName || record.username} 的分配`);
      await Promise.all([loadAgents(), loadAssignments(agent.id)]);
    } catch (e: unknown) {
      toast(errText(e, "取消分配失败"), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function publish(agent: AgentItem) {
    setBusyId(agent.id);
    try {
      const res = await api.post<AssignResult>(`/public-agents/${agent.id}/publish`);
      toast(`已发布 v${res.version ?? agent.version}，同步 ${res.synced ?? 0} 个用户副本`);
      await loadAgents();
    } catch (e: unknown) {
      toast(errText(e, "发布失败"), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del(`/public-agents/${deleteTarget.id}`);
      toast(`已下架 ${deleteTarget.name}`);
      setDeleteTarget(null);
      await loadAgents();
    } catch (e: unknown) {
      toast(errText(e, "下架失败"), "error");
    } finally {
      setDeleting(false);
    }
  }

  function openCreate() {
    setForm(EMPTY_FORM);
    setEditorTab("basic");
    setSkillSearch("");
    setFormError(null);
    setEditor({ mode: "create" });
  }

  function openEdit(agent: AgentItem, tab: "basic" | "skills" = "basic") {
    setForm({
      name: agent.name || "",
      roleTitle: agent.roleTitle || "",
      avatar: agent.avatar || "avatar-01",
      description: agent.description || "",
      soulMd: agent.soulMd || "",
      skills: agent.skills ?? [],
    });
    setEditorTab(tab);
    setSkillSearch("");
    setFormError(null);
    setEditor({ mode: "edit", agent });
  }

  async function submitForm() {
    if (!form.name.trim()) {
      setFormError("请填写公共员工名称");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        name: form.name.trim(),
        roleTitle: form.roleTitle.trim(),
        avatar: form.avatar.trim() || "avatar-01",
        description: form.description.trim(),
        soulMd: form.soulMd,
        skills: form.skills,
      };
      if (editor?.mode === "create") {
        await api.post("/public-agents", { ...payload, status: "published" });
        toast(`已创建公共员工 ${payload.name}`);
      } else if (editor?.agent) {
        await api.patch(`/public-agents/${editor.agent.id}`, payload);
        toast(`已保存 v${(editor.agent.version || 1) + 1}，记得发布以同步用户副本`);
      }
      setEditor(null);
      await loadAgents();
    } catch (e: unknown) {
      setFormError(errText(e, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  const filteredSkills = useMemo(() => {
    const kw = skillSearch.trim().toLowerCase();
    if (!kw) return skills;
    return skills.filter(
      (s) => (s.displayName || "").toLowerCase().includes(kw) || (s.category || "").toLowerCase().includes(kw)
    );
  }, [skills, skillSearch]);

  const totalAssigned = agents.reduce((sum, a) => sum + (a.assigneeCount ?? 0), 0);

  return (
    <div className="h-full overflow-y-auto bg-surface-100">
      <div className="mx-auto max-w-[1440px] space-y-5 px-6 py-5">
        <PageHeader
          title="公共员工 · 统一定义，一键分配"
          desc="管理员在这里统一定义员工的能力与人格（SOUL.md），按版本下发；业务用户拿到的是带自己记忆的独立副本。"
          badge={
            <Badge tone="brand" dot>
              管理员视角
            </Badge>
          }
          meta={
            <>
              <span>{formatNumber(agents.length)} 个公共员工</span>
              <span>已分配 {formatNumber(totalAssigned)} 人次</span>
              <span className="inline-flex items-center gap-1">
                <Rocket size={11} /> 版本变更需「发布」才会同步到用户副本
              </span>
            </>
          }
          actions={
            <>
              <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadAgents()}>
                刷新
              </Button>
              <Button icon={<Plus size={14} />} onClick={openCreate}>
                新建公共员工
              </Button>
            </>
          }
        />

        {loading && (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-[196px]" />
            ))}
          </div>
        )}

        {!loading && error && (
          <Card>
            <Empty
              icon={<ShieldAlert size={20} />}
              title="公共员工加载失败"
              desc={`${error}。后端 /api/public-agents 可能尚未就绪。`}
              action={
                <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadAgents()}>
                  重新加载
                </Button>
              }
            />
          </Card>
        )}

        {!loading && !error && agents.length === 0 && (
          <Card>
            <Empty
              icon={<Bot size={20} />}
              title="还没有公共员工"
              desc="把部门里最好用的那套能力沉淀成公共员工：定义 SOUL.md 与技能，然后一键分配给业务同事。"
              action={
                <Button icon={<Plus size={14} />} onClick={openCreate}>
                  新建公共员工
                </Button>
              }
            />
          </Card>
        )}

        {!loading && !error && agents.length > 0 && (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => {
              const open = expanded === agent.id;
              const list = assignments[agent.id];
              const pending = agent.pendingSync;
              return (
                <Card key={agent.id} className="card-hover flex flex-col overflow-hidden">
                  <div className="flex flex-1 flex-col p-3.5">
                    <div className="flex items-start gap-2.5">
                      <Avatar name={agent.name} seed={agent.avatar || agent.id} size={38} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="truncate text-[13.5px] font-semibold text-ink-900">{agent.name}</span>
                          <Badge tone="brand">公共</Badge>
                          <Badge tone={pending ? "amber" : "gray"}>v{agent.version}</Badge>
                          <Badge tone={agent.status === "published" ? "green" : agent.status === "offline" ? "gray" : "amber"}>
                            {statusLabel[agent.status] ?? agent.status}
                          </Badge>
                        </div>
                        <div className="mt-0.5 truncate text-[11.5px] text-ink-500">{agent.roleTitle || "未设置岗位"}</div>
                      </div>
                    </div>

                    <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-ink-600">
                      {agent.description || "未填写描述：建议说明这个员工替谁干活、交付什么。"}
                    </p>

                    <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-ink-500">
                      <span className="inline-flex items-center gap-1">
                        <Settings2 size={11} /> {formatNumber(agent.skillCount ?? agent.skills?.length ?? 0)} 技能
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Users size={11} /> 已分配 {formatNumber(agent.assigneeCount ?? 0)} 人
                      </span>
                      <span>{formatNumber(agent.sessionCount ?? 0)} 会话</span>
                      {agent.updatedAt && <span className="text-ink-400">更新 {timeAgo(agent.updatedAt)}</span>}
                    </div>

                    <div className="mt-2.5 flex flex-wrap items-center gap-1 border-t border-surface-200 pt-2">
                      <Button variant="ghost" size="sm" icon={<Pencil size={13} />} onClick={() => openEdit(agent, "basic")}>
                        编辑
                      </Button>
                      <Button variant="ghost" size="sm" icon={<Settings2 size={13} />} onClick={() => openEdit(agent, "skills")}>
                        配置
                      </Button>
                      <Button variant="ghost" size="sm" icon={<UserPlus size={13} />} onClick={() => void openAssign(agent)}>
                        分配
                      </Button>
                      <Tip text="下架后不再可分配，已分配的副本保留在用户侧">
                        <Button variant="ghost" size="sm" icon={<Trash2 size={13} />} className="text-rose-600" onClick={() => setDeleteTarget(agent)}>
                          删除
                        </Button>
                      </Tip>
                      <div className="ml-auto flex items-center gap-1.5">
                        <Button
                          variant={pending ? "primary" : "outline"}
                          size="sm"
                          icon={<Rocket size={13} />}
                          loading={busyId === agent.id}
                          onClick={() => void publish(agent)}
                        >
                          {pending ? "发布变更" : "发布"}
                        </Button>
                      </div>
                    </div>

                    {pending && (
                      <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-700">
                        <ShieldAlert size={12} className="mt-0.5 shrink-0" />
                        已保存 v{agent.version} 但尚未发布，{formatNumber(agent.assigneeCount ?? 0)} 个用户副本仍是旧版本。
                      </div>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => void toggleExpand(agent)}
                    className="flex items-center justify-between gap-2 border-t border-surface-200 bg-surface-50/60 px-3.5 py-1.5 text-[11px] text-ink-600 hover:bg-surface-100"
                  >
                    <span>
                      已分配 {formatNumber(agent.assigneeCount ?? 0)} 人 · {open ? "收起" : "展开"}
                    </span>
                    {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  </button>

                  {open && (
                    <div className="border-t border-surface-200 bg-white px-3 py-2">
                      {assignLoading === agent.id && <Skeleton className="h-16" />}
                      {assignLoading !== agent.id && list && list.length > 0 && (
                        <div className="divide-y divide-surface-200/80">
                          {list.map((rec) => (
                            <div key={rec.userId} className="flex items-center gap-2 py-2">
                              <Avatar name={rec.userName} seed={rec.username} size={26} />
                              <div className="min-w-0 flex-1">
                                <div className="truncate text-[12px] font-medium text-ink-900">{rec.userName}</div>
                                <div className="truncate text-[11px] text-ink-500">
                                  @{rec.username}
                                  {rec.dept ? ` · ${rec.dept}` : ""}
                                </div>
                              </div>
                              <span className="shrink-0 text-[10.5px] text-ink-400">{rec.createdAt ? formatDateTime(rec.createdAt) : ""}</span>
                              <Tip text="解除分配会删除该用户侧副本（含其会话）">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  icon={<UserMinus size={12} />}
                                  className="text-rose-600"
                                  loading={busyId === rec.userId}
                                  onClick={() => void unassign(agent, rec)}
                                >
                                  解除
                                </Button>
                              </Tip>
                            </div>
                          ))}
                        </div>
                      )}
                      {assignLoading !== agent.id && list && list.length === 0 && (
                        <div className="py-3 text-center text-[11.5px] text-ink-400">还没有分配给任何用户，点「分配」开始。</div>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </div>

      {/* ---------------- 分配弹窗（对齐 p14） ---------------- */}
      <Modal
        open={!!assignTarget}
        onClose={() => setAssignTarget(null)}
        title="分配公共员工"
        desc={assignTarget ? `${assignTarget.name} · v${assignTarget.version}` : undefined}
        width="max-w-2xl"
        footer={
          <>
            <span className="mr-auto text-[12px] text-ink-500">
              将分配给 <b className="text-brand-700">{selected.length}</b> 个用户
            </span>
            <Button variant="outline" onClick={() => setAssignTarget(null)}>
              取消
            </Button>
            <Button disabled={selected.length === 0} loading={assigning} onClick={() => void submitAssign()}>
              确认分配
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
            <Input value={assignSearch} onChange={(e) => setAssignSearch(e.target.value)} placeholder="搜索用户姓名 / 账号 / 部门" className="pl-8" />
          </div>

          {assignTarget?.createdBy && assignTarget.createdBy === me?.id && (
            <div className="rounded-xl bg-surface-50 px-3 py-2 text-[11.5px] leading-relaxed text-ink-500">
              创建者（{me?.name || me?.username}）已拥有该公共员工的源定义，无需在此分配。
            </div>
          )}

          {refLoading && <Skeleton className="h-40" />}

          {!refLoading && visibleUsers.length === 0 && (
            <Empty title="没有可分配的用户" desc="换个关键词，或先到「用户与角色」里新建账号。" />
          )}

          {!refLoading && visibleUsers.length > 0 && (
            <div className="grid max-h-[46vh] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
              {visibleUsers.map((u) => {
                const already = assignedIds.has(u.id);
                const checked = selected.includes(u.id);
                const disabledUser = u.status === "disabled";
                const disabled = already || disabledUser;
                return (
                  <button
                    key={u.id}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleUser(u.id)}
                    className={cx(
                      "flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition",
                      checked ? "border-brand-400 bg-brand-50/60" : "border-surface-300 bg-white",
                      disabled ? "cursor-not-allowed opacity-60" : "hover:border-brand-300"
                    )}
                  >
                    <span
                      className={cx(
                        "grid h-4 w-4 shrink-0 place-items-center rounded border",
                        checked ? "border-brand-600 bg-brand-600 text-white" : "border-surface-300 bg-white"
                      )}
                    >
                      {checked && <Check size={11} />}
                    </span>
                    <Avatar name={u.name || u.username} seed={u.avatar || u.username} size={28} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-[12.5px] font-medium text-ink-900">{u.name || u.username}</span>
                        {already && <Badge tone="gray">已分配</Badge>}
                        {disabledUser && <Badge tone="amber">已停用</Badge>}
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-ink-500">
                        @{u.username}
                        {u.dept ? ` · ${u.dept}` : ""}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </Modal>

      {/* ---------------- 编辑 / 新建抽屉 ---------------- */}
      <Drawer
        open={!!editor}
        onClose={() => setEditor(null)}
        title={editor?.mode === "create" ? "新建公共员工" : `编辑 ${editor?.agent?.name ?? ""}`}
        desc={
          editor?.mode === "create"
            ? "定义后即可分配给业务用户，用户侧会生成带独立记忆的副本。"
            : `当前版本 v${editor?.agent?.version ?? 1}，保存后版本 +1，需要「发布」才会同步到用户副本。`
        }
        width="w-[640px]"
        footer={
          <>
            <span className="mr-auto text-[11.5px] text-ink-400">
              {editor?.mode === "edit" ? `保存后 v${(editor.agent?.version ?? 1) + 1}` : "创建后为 v1"}
            </span>
            <Button variant="outline" onClick={() => setEditor(null)}>
              取消
            </Button>
            <Button loading={saving} onClick={() => void submitForm()}>
              {editor?.mode === "create" ? "创建" : "保存"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Tabs
            items={[
              { key: "basic", label: "基础设定" },
              { key: "skills", label: "技能编排", count: form.skills.length },
            ]}
            value={editorTab}
            onChange={setEditorTab}
          />

          {editorTab === "basic" && (
            <div className="space-y-3.5">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="名称">
                  <Input value={form.name} placeholder="如 社媒排期官" onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
                </Field>
                <Field label="岗位 / 角色">
                  <Input
                    value={form.roleTitle}
                    placeholder="如 DataClaw-Scheduler"
                    onChange={(e) => setForm((f) => ({ ...f, roleTitle: e.target.value }))}
                  />
                </Field>
              </div>

              <Field label="头像标识" hint="V1 使用内置头像编号，如 avatar-01 ~ avatar-08">
                <Input value={form.avatar} onChange={(e) => setForm((f) => ({ ...f, avatar: e.target.value }))} />
              </Field>

              <Field label="描述" hint="一句话说清「替谁干什么活」，会显示在用户侧的员工卡片上">
                <Textarea
                  value={form.description}
                  rows={3}
                  placeholder="如：负责多平台账号排期，把待发布的内容按最佳时间铺开。"
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </Field>

              <Field label="SOUL.md" hint="人格与工作准则：职责边界、输出规范、话术风格。发布时原样同步给每个用户副本">
                <Textarea
                  value={form.soulMd}
                  rows={14}
                  className="min-h-[280px] font-mono !text-[12px] leading-6"
                  placeholder={"# 角色\n你是……\n\n## 职责\n1. ……\n\n## 输出规范\n- ……"}
                  onChange={(e) => setForm((f) => ({ ...f, soulMd: e.target.value }))}
                />
              </Field>
            </div>
          )}

          {editorTab === "skills" && (
            <div className="space-y-3">
              <div className="relative">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                <Input value={skillSearch} onChange={(e) => setSkillSearch(e.target.value)} placeholder="搜索技能" className="pl-8" />
              </div>
              {refLoading && <Skeleton className="h-40" />}
              {!refLoading && filteredSkills.length === 0 && <Empty title="没有可选技能" desc="技能超市里还没有可安装的技能。" />}
              {!refLoading && filteredSkills.length > 0 && (
                <div className="max-h-[52vh] space-y-1.5 overflow-y-auto pr-1">
                  {filteredSkills.map((s) => {
                    const checked = form.skills.includes(s.id);
                    return (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() =>
                          setForm((f) => ({
                            ...f,
                            skills: checked ? f.skills.filter((x) => x !== s.id) : [...f.skills, s.id],
                          }))
                        }
                        className={cx(
                          "flex w-full items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left transition",
                          checked ? "border-brand-400 bg-brand-50/60" : "border-surface-300 hover:border-brand-300"
                        )}
                      >
                        <span
                          className={cx(
                            "mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded border",
                            checked ? "border-brand-600 bg-brand-600 text-white" : "border-surface-300 bg-white"
                          )}
                        >
                          {checked && <Check size={11} />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="text-[12.5px] font-medium text-ink-900">{s.displayName}</span>
                            {s.category && <Badge tone="gray">{s.category}</Badge>}
                            {s.riskLevel === "high" && <Badge tone="rose">高风险</Badge>}
                          </span>
                          {s.description && <span className="mt-0.5 block text-[11.5px] leading-relaxed text-ink-500">{s.description}</span>}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
              <div className="rounded-xl bg-surface-50 px-3 py-2 text-[11.5px] leading-relaxed text-ink-500">
                技能决定「这个员工能用哪些工具」——没装技能就等于没有工具，这是权限即能力的落点。
              </div>
            </div>
          )}

          {formError && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
              <ShieldAlert size={13} className="mt-0.5 shrink-0" />
              {formError}
            </div>
          )}
        </div>
      </Drawer>

      {/* ---------------- 删除（下架）确认 ---------------- */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="下架公共员工？"
        desc={deleteTarget ? `${deleteTarget.name} · v${deleteTarget.version}` : undefined}
        width="max-w-md"
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button loading={deleting} onClick={() => void confirmDelete()} className="!bg-rose-600 hover:!bg-rose-700">
              确认下架
            </Button>
          </>
        }
      >
        <div className="space-y-2 text-[12.5px] leading-relaxed text-ink-600">
          <p>
            下架后该公共员工不再出现在分配列表，也无法再分给新用户；已分配的
            <b className="text-ink-900"> {formatNumber(deleteTarget?.assigneeCount ?? 0)} </b>
            个用户副本会保留，用户侧仍可继续使用。
          </p>
          <p className="text-[11.5px] text-ink-500">如需彻底收回，请先在「分配明细」里逐个解除分配。</p>
        </div>
      </Modal>
    </div>
  );
}
