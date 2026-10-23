import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  ListChecks,
  MessageSquare,
  RefreshCw,
  Search,
} from "lucide-react";
import type { SessionItem } from "../lib/types";
import { api } from "../lib/api";
import { cx, formatNumber, timeAgo } from "../lib/format";
import { Avatar, Badge, Button, Card, Empty, Input, Skeleton, Tabs, toast } from "../components/ui";

/* ---------------- 工具 ---------------- */
function errText(e: unknown): string {
  const msg = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  if (!msg || /failed to fetch|networkerror|load failed/i.test(msg)) return "服务暂不可用，请确认后端已启动";
  return msg;
}

type TaskSession = SessionItem & { status?: string; employeeName?: string; employeeAvatar?: string };
type TaskState = "running" | "done" | "idle";
type ListResp<T> = { items?: T[]; total?: number };

const DAY = 24 * 60 * 60 * 1000;

/** V1 以会话为任务单元：24h 内有更新视为进行中，无消息视为待开始。 */
function taskState(s: TaskSession): TaskState {
  if (s.status && s.status !== "active") return "done";
  if (!s.messageCount) return "idle";
  const ts = s.lastMessageAt ? new Date(s.lastMessageAt).getTime() : 0;
  if (!ts) return "idle";
  return Date.now() - ts < DAY ? "running" : "done";
}

const STATE_META: Record<TaskState, { label: string; tone: "brand" | "green" | "amber" }> = {
  running: { label: "进行中", tone: "brand" },
  done: { label: "已完成", tone: "green" },
  idle: { label: "待开始", tone: "amber" },
};

export default function Tasks() {
  const nav = useNavigate();
  const [sessions, setSessions] = useState<TaskSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [keyword, setKeyword] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get<ListResp<TaskSession>>("/sessions");
      setSessions(Array.isArray(res.items) ? res.items : []);
    } catch (e) {
      setError(errText(e));
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const withState = useMemo(
    () => sessions.map((s) => ({ session: s, state: taskState(s) })),
    [sessions]
  );

  const counts = useMemo(() => {
    const base = { all: withState.length, running: 0, done: 0, idle: 0 };
    withState.forEach((t) => {
      base[t.state] += 1;
    });
    return base;
  }, [withState]);

  const totalMessages = useMemo(
    () => sessions.reduce((sum, s) => sum + (s.messageCount || 0), 0),
    [sessions]
  );

  const visible = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return withState
      .filter((t) => (filter === "all" ? true : t.state === filter))
      .filter((t) => {
        if (!kw) return true;
        return (
          (t.session.title || "").toLowerCase().includes(kw) ||
          (t.session.employeeName || "").toLowerCase().includes(kw)
        );
      })
      .sort((a, b) => new Date(b.session.lastMessageAt || 0).getTime() - new Date(a.session.lastMessageAt || 0).getTime());
  }, [withState, filter, keyword]);

  const openTask = (s: TaskSession) => {
    if (!s.employeeId) {
      toast("该任务缺少员工信息，无法打开会话", "error");
      return;
    }
    nav(`/chat/${s.employeeId}/${s.id}`);
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[1320px] px-5 py-5 lg:px-7">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-semibold tracking-tight text-ink-900">任务</h1>
            <p className="mt-1 text-[12.5px] text-ink-500">
              数字员工的执行任务总览。V1 以「一次会话 = 一次任务」聚合，最近 24 小时内有更新视为进行中。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative w-[220px] max-w-full">
              <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
              <Input
                className="!py-1.5 !pl-8 !text-[12.5px]"
                placeholder="搜索任务或员工"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            </div>
            <Button variant="outline" onClick={() => void load()} icon={<RefreshCw size={14} />}>
              刷新
            </Button>
          </div>
        </div>

        {/* 概览 */}
        <div className="mt-4 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          {[
            { label: "全部任务", value: counts.all, icon: <ListChecks size={14} />, tone: "brand" },
            { label: "进行中", value: counts.running, icon: <Activity size={14} />, tone: "teal" },
            { label: "已完成", value: counts.done, icon: <CheckCircle2 size={14} />, tone: "green" },
            { label: "消息总数", value: totalMessages, icon: <MessageSquare size={14} />, tone: "amber" },
          ].map((s) => (
            <Card key={s.label} className="flex items-center gap-3 p-3.5">
              <span
                className={cx(
                  "grid h-9 w-9 shrink-0 place-items-center rounded-xl",
                  s.tone === "brand"
                    ? "bg-brand-50 text-brand-600"
                    : s.tone === "teal"
                      ? "bg-teal-50 text-teal-600"
                      : s.tone === "green"
                        ? "bg-emerald-50 text-emerald-600"
                        : "bg-amber-50 text-amber-600"
                )}
              >
                {s.icon}
              </span>
              <div className="min-w-0">
                <div className="text-[11px] text-ink-500">{s.label}</div>
                <div className="text-[19px] font-semibold leading-tight tracking-tight text-ink-900">
                  {formatNumber(s.value)}
                </div>
              </div>
            </Card>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Tabs
            items={[
              { key: "all", label: "全部", count: counts.all },
              { key: "running", label: "进行中", count: counts.running },
              { key: "done", label: "已完成", count: counts.done },
              { key: "idle", label: "待开始", count: counts.idle },
            ]}
            value={filter}
            onChange={setFilter}
          />
        </div>

        <div className="mt-3">
          {loading ? (
            <Card className="p-4">
              <div className="space-y-2.5">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="h-8 w-8 rounded-full" />
                    <Skeleton className="h-3 flex-1" />
                    <Skeleton className="h-5 w-16 rounded-full" />
                    <Skeleton className="h-3 w-20" />
                  </div>
                ))}
              </div>
            </Card>
          ) : error ? (
            <Card>
              <Empty
                title="任务列表加载失败"
                desc={error}
                icon={<ListChecks size={20} />}
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
                title={keyword || filter !== "all" ? "没有匹配的任务" : "还没有任务"}
                desc={
                  keyword || filter !== "all"
                    ? "试试切换状态筛选或清空搜索词。"
                    : "去会话页给数字员工下达第一个任务，这里会自动出现执行记录。"
                }
                icon={<ListChecks size={20} />}
                action={
                  keyword || filter !== "all" ? (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setKeyword("");
                        setFilter("all");
                      }}
                    >
                      清空筛选
                    </Button>
                  ) : (
                    <Button onClick={() => nav("/chat")} icon={<MessageSquare size={14} />}>
                      去创建任务
                    </Button>
                  )
                }
              />
            </Card>
          ) : (
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="table-base">
                  <thead>
                    <tr>
                      <th>任务</th>
                      <th className="w-[170px]">数字员工</th>
                      <th className="w-[100px]">状态</th>
                      <th className="w-[90px]">消息数</th>
                      <th className="w-[130px]">最近更新</th>
                      <th className="w-[100px] text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map(({ session: s, state }) => {
                      const meta = STATE_META[state];
                      return (
                        <tr
                          key={s.id}
                          onClick={() => openTask(s)}
                          className="cursor-pointer"
                        >
                          <td>
                            <div className="flex items-center gap-2">
                              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-surface-100 text-ink-500">
                                <MessageSquare size={13} />
                              </span>
                              <div className="min-w-0">
                                <div className="truncate text-[12.5px] font-medium text-ink-800">{s.title || "未命名任务"}</div>
                                <div className="truncate text-[10.5px] text-ink-400">会话 {s.id.slice(0, 8)}</div>
                              </div>
                            </div>
                          </td>
                          <td>
                            <div className="flex items-center gap-2">
                              <Avatar name={s.employeeName || "员工"} seed={s.employeeAvatar || s.employeeId} size={24} />
                              <span className="truncate text-[12px] text-ink-700">{s.employeeName || "数字员工"}</span>
                            </div>
                          </td>
                          <td>
                            <Badge tone={meta.tone} dot>
                              {meta.label}
                            </Badge>
                          </td>
                          <td className="tabular-nums text-[12px] text-ink-600">{s.messageCount ?? 0}</td>
                          <td className="text-[11.5px] text-ink-500">{s.lastMessageAt ? timeAgo(s.lastMessageAt) : "—"}</td>
                          <td>
                            <div className="flex justify-end">
                              <span className="inline-flex items-center gap-1 text-[11.5px] text-brand-600">
                                继续 <ArrowRight size={12} />
                              </span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
