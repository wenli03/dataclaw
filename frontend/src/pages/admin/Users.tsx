import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Copy,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  ShieldAlert,
  UserCheck,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Paginated, Role, User } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { Avatar, Badge, Button, Card, Empty, Field, Input, Modal, Select, Skeleton, Tabs, Tip, toast } from "@/components/ui";
import { PageHeader } from "@/components/admin/PageHeader";
import { cx, formatDateTime, formatNumber, statusLabel, timeAgo } from "@/lib/format";

/* ------------------------------------------------------------------ 契约类型 */

interface RoleDef {
  id: Role;
  name: string;
  description: string;
  deptScoped?: boolean;
  grants: Record<string, string>;
}

interface Capability {
  key: string;
  label: string;
}

interface RolesResponse {
  items: RoleDef[];
  capabilities: Capability[];
  total?: number;
}

const ROLE_LABEL: Record<Role, string> = { platform_admin: "平台管理员", dept_admin: "部门管理员", member: "普通成员" };
const ROLE_TONE: Record<Role, "brand" | "teal" | "gray"> = { platform_admin: "brand", dept_admin: "teal", member: "gray" };
const ROLE_OPTIONS: { value: Role; label: string; desc: string }[] = [
  { value: "platform_admin", label: "平台管理员", desc: "平台全量：用户、公共员工、技能审核、数据权限、渠道、审计" },
  { value: "dept_admin", label: "部门管理员", desc: "仅本部门：本部门用户、本部门公共员工、本部门数据权限与审计" },
  { value: "member", label: "普通成员", desc: "使用数字员工、会话、技能安装；审计仅可见自己的记录" },
];

type UserForm = { username: string; name: string; email: string; role: Role; dept: string; password: string };
const EMPTY_FORM: UserForm = { username: "", name: "", email: "", role: "member", dept: "", password: "" };

function grantCell(grant: string | undefined) {
  if (grant === "all") return <Check size={14} className="mx-auto text-emerald-600" />;
  if (grant === "dept") return <Badge tone="amber">仅本部门</Badge>;
  if (grant === "self") return <Badge tone="blue">仅自己</Badge>;
  return <X size={14} className="mx-auto text-ink-300" />;
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制到剪贴板");
  } catch {
    toast("复制失败，请手动选择文本复制", "error");
  }
}

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/* ------------------------------------------------------------------ 页面 */

export default function Users() {
  const { user: me } = useAuth();

  const [tab, setTab] = useState("users");
  const [items, setItems] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [kwInput, setKwInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");

  const [roles, setRoles] = useState<RolesResponse | null>(null);
  const [rolesError, setRolesError] = useState<string | null>(null);

  const [editor, setEditor] = useState<{ mode: "create" | "edit"; user?: User } | null>(null);
  const [form, setForm] = useState<UserForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [tempPassword, setTempPassword] = useState<{ username: string; password: string } | null>(null);

  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    const timer = setTimeout(() => {
      setKeyword(kwInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [kwInput]);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Paginated<User>>("/users", { keyword, role, status, page, size: pageSize });
      setItems(res.items ?? []);
      setTotal(res.total ?? 0);
      setError(null);
    } catch (e: unknown) {
      setError(errText(e, "用户列表加载失败"));
    } finally {
      setLoading(false);
    }
  }, [keyword, role, status, page]);

  const loadRoles = useCallback(async () => {
    try {
      const res = await api.get<RolesResponse>("/roles");
      setRoles(res);
      setRolesError(null);
    } catch (e: unknown) {
      setRolesError(errText(e, "角色矩阵加载失败"));
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    void loadRoles();
  }, [loadRoles]);

  function openCreate() {
    setForm(EMPTY_FORM);
    setFormError(null);
    setEditor({ mode: "create" });
  }

  function openEdit(u: User) {
    setForm({ username: u.username, name: u.name || "", email: u.email || "", role: u.role, dept: u.dept || "", password: "" });
    setFormError(null);
    setEditor({ mode: "edit", user: u });
  }

  async function submitForm() {
    const isCreate = editor?.mode === "create";
    if (isCreate && form.username.trim().length < 2) {
      setFormError("账号至少 2 个字符");
      return;
    }
    if (!form.name.trim()) {
      setFormError("请填写姓名");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (isCreate) {
        const res = await api.post<{ user: User; tempPassword: string | null }>("/users", {
          username: form.username.trim(),
          name: form.name.trim(),
          email: form.email.trim(),
          role: form.role,
          dept: form.dept.trim(),
          password: form.password.trim() || undefined,
        });
        setEditor(null);
        toast(`已创建用户 ${res.user?.name || form.name.trim()}`);
        if (res.tempPassword) setTempPassword({ username: res.user?.username || form.username.trim(), password: res.tempPassword });
      } else if (editor?.user) {
        await api.patch<User>(`/users/${editor.user.id}`, {
          name: form.name.trim(),
          email: form.email.trim(),
          role: form.role,
          dept: form.dept.trim(),
        });
        setEditor(null);
        toast("用户信息已更新");
      }
      await loadUsers();
    } catch (e: unknown) {
      setFormError(errText(e, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(u: User) {
    const next = u.status === "disabled" ? "active" : "disabled";
    setBusyId(u.id);
    try {
      await api.patch<User>(`/users/${u.id}`, { status: next });
      toast(next === "disabled" ? `已停用 ${u.name || u.username}` : `已启用 ${u.name || u.username}`);
      await loadUsers();
    } catch (e: unknown) {
      toast(errText(e, "操作失败"), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function resetPassword(u: User) {
    setBusyId(u.id);
    try {
      const res = await api.post<{ tempPassword: string; username: string }>(`/users/${u.id}/reset-password`);
      setTempPassword({ username: res.username || u.username, password: res.tempPassword });
    } catch (e: unknown) {
      toast(errText(e, "重置口令失败"), "error");
    } finally {
      setBusyId(null);
    }
  }

  const isSelf = useCallback((u: User) => !!me && me.id === u.id, [me]);
  const hasFilter = Boolean(keyword || role || status);
  const roleList = useMemo(() => roles?.items ?? [], [roles]);

  return (
    <div className="h-full overflow-y-auto bg-surface-100">
      <div className="mx-auto max-w-[1440px] space-y-5 px-6 py-5">
        <PageHeader
          title="用户与角色"
          desc="企业用户的账号、部门与角色。角色决定可管理范围，数据权限则始终按「会话用户」求值。"
          badge={
            <Badge tone="brand" dot>
              管理员视角
            </Badge>
          }
          meta={<span>共 {formatNumber(total)} 个账号 · 每页 {pageSize} 条</span>}
          actions={
            <>
              <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadUsers()}>
                刷新
              </Button>
              <Button icon={<Plus size={14} />} onClick={openCreate}>
                新建用户
              </Button>
            </>
          }
        />

        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-200 px-4 py-3">
            <Tabs
              items={[
                { key: "users", label: "用户列表", count: total },
                { key: "roles", label: "角色与能力矩阵", count: roleList.length || undefined },
              ]}
              value={tab}
              onChange={setTab}
            />
            {tab === "users" && (
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                  <Input
                    value={kwInput}
                    onChange={(e) => setKwInput(e.target.value)}
                    placeholder="搜索姓名 / 账号 / 邮箱"
                    className="w-[240px] pl-8"
                  />
                </div>
                <Select
                  value={role}
                  onChange={(e) => {
                    setRole(e.target.value);
                    setPage(1);
                  }}
                  className="w-[136px]"
                >
                  <option value="">全部角色</option>
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </Select>
                <Select
                  value={status}
                  onChange={(e) => {
                    setStatus(e.target.value);
                    setPage(1);
                  }}
                  className="w-[120px]"
                >
                  <option value="">全部状态</option>
                  <option value="active">正常</option>
                  <option value="disabled">已停用</option>
                </Select>
              </div>
            )}
          </div>

          {tab === "users" && (
            <>
              {loading && (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <Skeleton key={i} className="h-11" />
                  ))}
                </div>
              )}

              {!loading && error && (
                <Empty
                  icon={<ShieldAlert size={20} />}
                  title="用户列表加载失败"
                  desc={`${error}。后端 /api/users 可能尚未就绪。`}
                  action={
                    <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadUsers()}>
                      重新加载
                    </Button>
                  }
                />
              )}

              {!loading && !error && items.length === 0 && (
                <Empty
                  icon={<UserCheck size={20} />}
                  title={hasFilter ? "没有匹配的用户" : "还没有企业用户"}
                  desc={hasFilter ? "换个关键词或清空筛选条件试试。" : "新建第一个账号，把业务同事接进来。"}
                  action={
                    hasFilter ? (
                      <Button
                        variant="outline"
                        onClick={() => {
                          setKwInput("");
                          setRole("");
                          setStatus("");
                          setPage(1);
                        }}
                      >
                        清空筛选
                      </Button>
                    ) : (
                      <Button icon={<Plus size={14} />} onClick={openCreate}>
                        新建用户
                      </Button>
                    )
                  }
                />
              )}

              {!loading && !error && items.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="table-base">
                    <thead>
                      <tr>
                        <th>用户</th>
                        <th className="w-[150px]">部门</th>
                        <th>角色</th>
                        <th className="w-[80px]">员工数</th>
                        <th>最近登录</th>
                        <th className="w-[90px]">状态</th>
                        <th className="w-[248px]">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((u) => {
                        const self = isSelf(u);
                        const disabled = busyId === u.id;
                        return (
                          <tr key={u.id}>
                            <td>
                              <div className="flex items-center gap-2.5">
                                <Avatar name={u.name || u.username} seed={u.avatar || u.username} size={32} />
                                <div className="min-w-0">
                                  <div className="flex items-center gap-1.5">
                                    <span className="truncate text-[13px] font-medium text-ink-900">{u.name || "—"}</span>
                                    {self && <Badge tone="brand">我</Badge>}
                                  </div>
                                  <div className="truncate text-[11.5px] text-ink-500">@{u.username}</div>
                                </div>
                              </div>
                            </td>
                            <td className="text-[12.5px] text-ink-600">{u.dept || "—"}</td>
                            <td>
                              <Badge tone={ROLE_TONE[u.role] ?? "gray"}>{ROLE_LABEL[u.role] ?? u.role}</Badge>
                            </td>
                            <td className="text-[12.5px] text-ink-600">{formatNumber(u.employeeCount ?? 0)}</td>
                            <td>
                              <div className="text-[12.5px] text-ink-600">{u.lastLoginAt ? formatDateTime(u.lastLoginAt) : "—"}</div>
                              <div className="text-[11px] text-ink-400">{u.lastLoginAt ? timeAgo(u.lastLoginAt) : "从未登录"}</div>
                            </td>
                            <td>
                              <Badge tone={u.status === "disabled" ? "gray" : "green"} dot>
                                {statusLabel[u.status || "active"] ?? u.status}
                              </Badge>
                            </td>
                            <td>
                              <div className="flex items-center gap-0.5">
                                <Button variant="ghost" size="sm" className="whitespace-nowrap" onClick={() => openEdit(u)}>
                                  编辑
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="whitespace-nowrap"
                                  loading={disabled}
                                  onClick={() => void resetPassword(u)}
                                >
                                  重置口令
                                </Button>
                                {self ? (
                                  <Tip text="不能停用自己的账号（后端同样会拦截）">
                                    <Button variant="ghost" size="sm" className="whitespace-nowrap" disabled>
                                      停用
                                    </Button>
                                  </Tip>
                                ) : (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className={cx("whitespace-nowrap", u.status === "disabled" ? "text-emerald-600" : "text-rose-600")}
                                    loading={disabled}
                                    onClick={() => void toggleStatus(u)}
                                  >
                                    {u.status === "disabled" ? "启用" : "停用"}
                                  </Button>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {!loading && !error && items.length > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-surface-200 px-4 py-3 text-[12px] text-ink-500">
                  <span>
                    共 {formatNumber(total)} 条 · 第 {page} / {totalPages} 页
                  </span>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                      上一页
                    </Button>
                    <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>
                      下一页
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}

          {tab === "roles" && (
            <div className="p-4">
              {rolesError && (
                <Empty
                  icon={<ShieldAlert size={20} />}
                  title="角色矩阵加载失败"
                  desc={`${rolesError}。后端 /api/roles 可能尚未就绪。`}
                  action={
                    <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadRoles()}>
                      重新加载
                    </Button>
                  }
                />
              )}

              {!rolesError && !roles && <Skeleton className="h-64" />}

              {!rolesError && roles && (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    {roleList.map((r) => (
                      <div key={r.id} className="rounded-xl border border-surface-200 bg-surface-50/60 p-3.5">
                        <div className="flex items-center gap-2">
                          <Badge tone={ROLE_TONE[r.id] ?? "gray"}>{r.name}</Badge>
                          {r.deptScoped && <span className="text-[11px] text-ink-400">部门范围</span>}
                        </div>
                        <p className="mt-2 text-[12px] leading-relaxed text-ink-600">{r.description}</p>
                      </div>
                    ))}
                  </div>

                  <div className="overflow-x-auto rounded-xl border border-surface-200">
                    <table className="table-base">
                      <thead>
                        <tr>
                          <th className="w-[240px]">能力</th>
                          {roleList.map((r) => (
                            <th key={r.id} className="text-center">
                              {r.name}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(roles.capabilities ?? []).map((cap) => (
                          <tr key={cap.key}>
                            <td className="text-[12.5px] text-ink-700">{cap.label}</td>
                            {roleList.map((r) => (
                              <td key={r.id} className="text-center">
                                {grantCell(r.grants?.[cap.key])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="flex items-start gap-2 rounded-xl border border-brand-100 bg-brand-50/50 px-3.5 py-2.5 text-[11.5px] leading-relaxed text-ink-600">
                    <ShieldCheck size={14} className="mt-0.5 shrink-0 text-brand-600" />
                    <span>
                      角色只决定「能管理什么」，不决定「能看什么数据」。数字员工执行工具时始终以会话发起人身份求值，
                      因此管理员创建的公共员工分配给分析师后，分析师看不到管理员能看的数据列。
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* 新建 / 编辑 */}
      <Modal
        open={!!editor}
        onClose={() => setEditor(null)}
        title={editor?.mode === "create" ? "新建用户" : "编辑用户"}
        desc={editor?.mode === "create" ? "账号创建后即生效，可先给一个初始口令或由系统生成临时口令。" : `修改 ${editor?.user?.username} 的资料与角色`}
        width="max-w-xl"
        footer={
          <>
            <Button variant="outline" onClick={() => setEditor(null)}>
              取消
            </Button>
            <Button loading={saving} onClick={() => void submitForm()}>
              {editor?.mode === "create" ? "创建用户" : "保存修改"}
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="账号（登录名）" hint={editor?.mode === "edit" ? "账号创建后不可修改" : "至少 2 个字符，登录使用"}>
              <Input
                value={form.username}
                disabled={editor?.mode === "edit"}
                placeholder="如 analyst"
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              />
            </Field>
            <Field label="姓名">
              <Input value={form.name} placeholder="如 林知微" onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="邮箱">
              <Input value={form.email} placeholder="name@company.com" onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            </Field>
            <Field label="部门">
              <Input value={form.dept} placeholder="如 数智事业部" onChange={(e) => setForm((f) => ({ ...f, dept: e.target.value }))} />
            </Field>
          </div>

          <div>
            <div className="label">角色</div>
            <div className="space-y-2">
              {ROLE_OPTIONS.map((opt) => {
                const disabled = editor?.mode === "edit" && !!editor.user && isSelf(editor.user) && opt.value !== editor.user.role;
                return (
                  <label
                    key={opt.value}
                    className={cx(
                      "flex cursor-pointer items-start gap-2.5 rounded-xl border px-3 py-2.5 transition",
                      form.role === opt.value ? "border-brand-300 bg-brand-50/60" : "border-surface-300 hover:border-brand-200",
                      disabled && "cursor-not-allowed opacity-50"
                    )}
                  >
                    <input
                      type="radio"
                      name="role"
                      className="mt-1 accent-[#5B57E8]"
                      checked={form.role === opt.value}
                      disabled={disabled}
                      onChange={() => setForm((f) => ({ ...f, role: opt.value }))}
                    />
                    <span className="min-w-0">
                      <span className="block text-[12.5px] font-medium text-ink-900">{opt.label}</span>
                      <span className="mt-0.5 block text-[11.5px] leading-relaxed text-ink-500">{opt.desc}</span>
                    </span>
                  </label>
                );
              })}
            </div>
            {editor?.mode === "edit" && editor.user && isSelf(editor.user) && (
              <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-amber-600">
                <ShieldAlert size={12} /> 不能修改自己的角色（避免把自己锁在后台之外）
              </div>
            )}
          </div>

          {editor?.mode === "create" && (
            <Field label="初始口令" hint="留空则系统生成一次性临时口令，创建后弹窗展示">
              <Input
                value={form.password}
                placeholder="留空自动生成"
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              />
            </Field>
          )}

          {formError && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
              <ShieldAlert size={13} className="mt-0.5 shrink-0" />
              {formError}
            </div>
          )}
        </div>
      </Modal>

      {/* 一次性临时口令 */}
      <Modal
        open={!!tempPassword}
        onClose={() => setTempPassword(null)}
        title="临时口令（仅显示一次）"
        desc="请通过安全渠道转交本人，并提醒其首次登录后修改。"
        width="max-w-md"
        footer={
          <Button variant="outline" onClick={() => setTempPassword(null)}>
            我已记录
          </Button>
        }
      >
        {tempPassword && (
          <div className="space-y-3">
            <div className="text-[12.5px] text-ink-600">
              用户：<span className="font-medium text-ink-900">{tempPassword.username}</span>
            </div>
            <div className="flex items-center gap-2 rounded-xl border border-surface-300 bg-surface-50 px-3 py-2.5">
              <code className="flex-1 select-all font-mono text-[15px] tracking-wider text-ink-900">{tempPassword.password}</code>
              <Button variant="outline" size="sm" icon={<Copy size={13} />} onClick={() => void copyText(tempPassword.password)}>
                复制
              </Button>
            </div>
            <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-[11.5px] leading-relaxed text-amber-700">
              <ShieldAlert size={13} className="mt-0.5 shrink-0" />
              关闭后无法再次查看，只能重新重置。重置动作会写入审计（风险等级：中）。
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
