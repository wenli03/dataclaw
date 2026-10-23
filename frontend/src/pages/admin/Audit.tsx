import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, AlertTriangle, Copy, RefreshCw, Search, ShieldAlert, ShieldCheck, Terminal } from "lucide-react";
import { api } from "@/lib/api";
import type { AuditEvent, Paginated } from "@/lib/types";
import { Badge, Button, Card, Drawer, Empty, Input, Select, Skeleton, toast } from "@/components/ui";
import { JsonViewer, SqlBlock } from "@/components/admin/JsonViewer";
import { PageHeader } from "@/components/admin/PageHeader";
import { actionLabel, cx, formatDateTime, formatNumber, riskBadgeClass, riskLabel, timeAgo } from "@/lib/format";

/* ------------------------------------------------------------------ 类型 */

interface AuditStats {
  byAction?: { action: string; label?: string; count: number }[];
  byRisk?: { risk: string; count: number }[];
  byResult?: { result: string; count: number }[];
  trend?: { date: string; count: number; denied: number }[];
  topActors?: { actorId: string; actorName: string; count: number }[];
  total?: number;
  denied?: number;
}

interface RuleItem {
  type?: string;
  detail?: string;
  table?: string;
  column?: string;
  columns?: string[];
  mask?: string;
}

const ACTION_OPTIONS: { value: string; label: string }[] = [
  "login",
  "logout",
  "chat",
  "tool_call",
  "sql_query",
  "export",
  "skill_install",
  "skill_upload",
  "skill_review",
  "agent_assign",
  "policy_change",
  "doc_upload",
  "doc_read",
  "hitl_approval",
  "channel_test",
  "employee_create",
  "employee_update",
].map((value) => ({ value, label: actionLabel(value) }));

const RESULT_META: Record<string, { label: string; tone: "green" | "rose" | "amber" }> = {
  success: { label: "成功", tone: "green" },
  denied: { label: "已拒绝", tone: "rose" },
  error: { label: "异常", tone: "amber" },
};

const RULE_LABEL: Record<string, string> = {
  table: "表级",
  column_denied: "列级拒绝",
  star_expand: "列展开",
  row_filter: "行级",
  limit: "LIMIT",
  mask: "脱敏",
  deny: "拒绝",
};

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制到剪贴板");
  } catch {
    toast("复制失败，请手动选择复制", "error");
  }
}

/** 审计动作文案：后端 label 缺失时会原样返回 action id，这时用前端映射兜底。 */
function labelOf(action: string, backendLabel?: string): string {
  if (backendLabel && backendLabel !== action) return backendLabel;
  return actionLabel(action);
}

function dayStart(days: number): string {
  const d = new Date(Date.now() - (days - 1) * 86400000);
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/** 审计时间的绝对格式：MM-DD HH:mm:ss（表格里一眼能对齐，截图/复盘时不用二次换算）。 */
function absTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 相对时间只在 24 小时内显示：更早的记录给绝对时间就够，避免"3 天前"这类低信息量。 */
function relTime(iso?: string | null): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const diff = Date.now() - t;
  if (diff < 0 || diff > 86400000) return null;
  return timeAgo(iso);
}

/* ------------------------------------------------------------------ 页面 */

export default function Audit() {
  const nav = useNavigate();

  const [items, setItems] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [stats, setStats] = useState<AuditStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);

  const [action, setAction] = useState("");
  const [risk, setRisk] = useState("");
  const [result, setResult] = useState("");
  const [kwInput, setKwInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [days, setDays] = useState(7);

  const [active, setActive] = useState<AuditEvent | null>(null);

  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    const t = setTimeout(() => {
      setKeyword(kwInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [kwInput]);

  const loadAudit = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Paginated<AuditEvent>>("/audit", {
        action,
        risk,
        result,
        keyword,
        from: dayStart(days),
        page,
        size: pageSize,
      });
      setItems(res.items ?? []);
      setTotal(res.total ?? 0);
      setError(null);
    } catch (e: unknown) {
      setError(errText(e, "审计日志加载失败"));
    } finally {
      setLoading(false);
    }
  }, [action, risk, result, keyword, days, page]);

  const loadStats = useCallback(async () => {
    try {
      const res = await api.get<AuditStats>("/audit/stats", { days });
      setStats(res);
      setStatsError(null);
    } catch (e: unknown) {
      setStatsError(errText(e, "审计统计加载失败"));
    }
  }, [days]);

  useEffect(() => {
    void loadAudit();
  }, [loadAudit]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  const detail = useMemo(() => (active?.detail && typeof active.detail === "object" ? (active.detail as Record<string, unknown>) : null), [active]);
  const rules = useMemo<RuleItem[]>(() => {
    const raw = detail?.appliedRules;
    return Array.isArray(raw) ? (raw as RuleItem[]) : [];
  }, [detail]);
  const employeeId = detail && typeof detail.employeeId === "string" ? (detail.employeeId as string) : "";

  const topActions = useMemo(() => (stats?.byAction ?? []).slice(0, 5), [stats]);
  /** 动作下拉以统计接口返回的真实 action 为准（后端新增动作时无需改前端），静态表只做兜底。 */
  const actionOptions = useMemo(() => {
    const fromStats = (stats?.byAction ?? []).map((a) => ({ value: a.action, label: a.label || actionLabel(a.action) }));
    const seen = new Set(fromStats.map((o) => o.value));
    return [...fromStats, ...ACTION_OPTIONS.filter((o) => !seen.has(o.value))];
  }, [stats]);
  const maxActionCount = Math.max(1, ...topActions.map((a) => a.count));
  const highRisk = (stats?.byRisk ?? []).find((r) => r.risk === "high")?.count ?? 0;
  const deniedCount = stats?.denied ?? (stats?.byResult ?? []).find((r) => r.result === "denied")?.count ?? 0;

  const hasFilter = Boolean(action || risk || result || keyword);

  function resetFilters() {
    setKwInput("");
    setAction("");
    setRisk("");
    setResult("");
    setPage(1);
  }

  function openDetail(ev: AuditEvent) {
    setActive(ev);
  }

  return (
    <div className="h-full overflow-y-auto bg-surface-100">
      <div className="mx-auto max-w-[1440px] space-y-5 px-6 py-5">
        <PageHeader
          title="审计日志 · 每一次动作都留痕"
          desc="登录、会话、工具调用、SQL 改写、导出、技能、分配、策略、审批全链路记录；越权拦截（denied）同样入账。"
          badge={
            <Badge tone="brand" dot>
              管理员视角
            </Badge>
          }
          meta={
            <>
              <span>共 {formatNumber(total)} 条记录</span>
              <span>当前范围：近 {days} 天</span>
              <span className="inline-flex items-center gap-1">
                <ShieldCheck size={11} /> 按角色自动收窄可见范围
              </span>
            </>
          }
          actions={
            <Button
              variant="outline"
              icon={<RefreshCw size={14} />}
              onClick={() => {
                void loadAudit();
                void loadStats();
              }}
            >
              刷新
            </Button>
          }
        />

        {/* 统计小卡 */}
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <Card className="px-3.5 py-3">
            <div className="text-[11.5px] text-ink-500">审计总数</div>
            <div className="mt-1 text-[22px] font-semibold leading-none text-ink-900">{formatNumber(stats?.total ?? 0)}</div>
            <div className="mt-1 text-[10.5px] text-ink-400">近 {days} 天</div>
          </Card>
          <Card className="px-3.5 py-3">
            <div className="text-[11.5px] text-ink-500">越权拦截</div>
            <div className={cx("mt-1 text-[22px] font-semibold leading-none", deniedCount > 0 ? "text-rose-600" : "text-ink-900")}>
              {formatNumber(deniedCount)}
            </div>
            <div className="mt-1 text-[10.5px] text-ink-400">result=denied，网关拒绝</div>
          </Card>
          <Card className="px-3.5 py-3">
            <div className="text-[11.5px] text-ink-500">高风险动作</div>
            <div className={cx("mt-1 text-[22px] font-semibold leading-none", highRisk > 0 ? "text-amber-600" : "text-ink-900")}>
              {formatNumber(highRisk)}
            </div>
            <div className="mt-1 text-[10.5px] text-ink-400">含 HITL 审批</div>
          </Card>
          <Card className="px-3.5 py-3">
            <div className="flex items-center justify-between">
              <span className="text-[11.5px] text-ink-500">动作 Top5</span>
            </div>
            {statsError && <div className="mt-1 text-[10.5px] text-amber-600">统计接口不可用</div>}
            {!statsError && topActions.length === 0 && <div className="mt-1 text-[10.5px] text-ink-400">暂无数据</div>}
            <div className="mt-1.5 space-y-1">
              {topActions.map((a) => (
                <div key={a.action} className="flex items-center gap-1.5">
                  <span className="w-[64px] shrink-0 truncate text-[10.5px] text-ink-600">{a.label || actionLabel(a.action)}</span>
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-200">
                    <span
                      className="block h-full rounded-full bg-brand-500/80"
                      style={{ width: `${Math.max(5, (a.count / maxActionCount) * 100)}%` }}
                    />
                  </span>
                  <span className="w-6 shrink-0 text-right text-[10px] text-ink-400">{a.count}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* 筛选条 */}
        <Card>
          <div className="flex flex-wrap items-center gap-2 border-b border-surface-200 px-4 py-3">
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
              <Input
                value={kwInput}
                onChange={(e) => setKwInput(e.target.value)}
                placeholder="搜索操作人 / 对象"
                className="w-[200px] pl-8"
              />
            </div>
            <Select
              value={action}
              onChange={(e) => {
                setAction(e.target.value);
                setPage(1);
              }}
              className="w-[150px]"
            >
              <option value="">全部动作</option>
              {actionOptions.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </Select>
            <Select
              value={risk}
              onChange={(e) => {
                setRisk(e.target.value);
                setPage(1);
              }}
              className="w-[120px]"
            >
              <option value="">全部风险</option>
              <option value="low">低风险</option>
              <option value="medium">中风险</option>
              <option value="high">高风险</option>
            </Select>
            <Select
              value={result}
              onChange={(e) => {
                setResult(e.target.value);
                setPage(1);
              }}
              className="w-[120px]"
            >
              <option value="">全部结果</option>
              <option value="success">成功</option>
              <option value="denied">已拒绝</option>
              <option value="error">异常</option>
            </Select>
            <Select
              value={String(days)}
              onChange={(e) => {
                setDays(Number(e.target.value) || 7);
                setPage(1);
              }}
              className="w-[120px]"
            >
              <option value="1">近 1 天</option>
              <option value="7">近 7 天</option>
              <option value="30">近 30 天</option>
            </Select>
            {hasFilter && (
              <Button variant="ghost" size="sm" onClick={resetFilters}>
                清空筛选
              </Button>
            )}
            <span className="ml-auto text-[11.5px] text-ink-400">共 {formatNumber(total)} 条 · 第 {page} / {totalPages} 页</span>
          </div>

          {loading && (
            <div className="space-y-2 p-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-11" />
              ))}
            </div>
          )}

          {!loading && error && (
            <Empty
              icon={<ShieldAlert size={20} />}
              title="审计日志加载失败"
              desc={`${error}。后端 /api/audit 可能尚未就绪。`}
              action={
                <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadAudit()}>
                  重新加载
                </Button>
              }
            />
          )}

          {!loading && !error && items.length === 0 && (
            <Empty
              icon={<Activity size={20} />}
              title={hasFilter ? "没有匹配的审计记录" : "还没有审计记录"}
              desc={hasFilter ? "换个动作 / 风险 / 时间范围试试。" : "任何登录、会话、工具调用都会自动写入审计。"}
              action={
                hasFilter ? (
                  <Button variant="outline" onClick={resetFilters}>
                    清空筛选
                  </Button>
                ) : undefined
              }
            />
          )}

          {!loading && !error && items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th className="w-[136px]">时间</th>
                    <th className="w-[120px]">操作人</th>
                    <th className="w-[110px]">动作</th>
                    <th>对象</th>
                    <th className="w-[92px]">风险</th>
                    <th className="w-[86px]">结果</th>
                    <th className="w-[110px]">IP</th>
                    <th className="w-[64px]">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((ev) => {
                    const rm = RESULT_META[ev.result] ?? RESULT_META.success;
                    return (
                      <tr key={ev.id} className="cursor-pointer" onClick={() => openDetail(ev)}>
                        <td>
                          <div className="whitespace-nowrap font-mono text-[11.5px] text-ink-700">{absTime(ev.ts)}</div>
                          {relTime(ev.ts) && <div className="text-[10px] text-ink-400">{relTime(ev.ts)}</div>}
                        </td>
                        <td className="text-[12.5px] text-ink-800">{ev.actorName || "系统"}</td>
                        <td>
                          <span className="whitespace-nowrap text-[12.5px] text-ink-800">{labelOf(ev.action, ev.actionLabel)}</span>
                        </td>
                        <td>
                          <div className="max-w-[320px] truncate text-[12px] text-ink-700">{ev.targetName || ev.targetType || "—"}</div>
                          {ev.targetType && <div className="text-[10.5px] text-ink-400">{ev.targetType}</div>}
                        </td>
                        <td>
                          <span className={cx("chip", riskBadgeClass(ev.risk))}>{riskLabel[ev.risk] ?? ev.risk}</span>
                        </td>
                        <td>
                          <Badge tone={rm.tone} dot>
                            {rm.label}
                          </Badge>
                        </td>
                        <td className="font-mono text-[11px] text-ink-500">{ev.ip || "—"}</td>
                        <td>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="!px-0 whitespace-nowrap"
                            onClick={(e) => {
                              e.stopPropagation();
                              openDetail(ev);
                            }}
                          >
                            详情
                          </Button>
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
        </Card>
      </div>

      {/* ---------------- 详情抽屉 ---------------- */}
      <Drawer
        open={!!active}
        onClose={() => setActive(null)}
        title={active ? labelOf(active.action, active.actionLabel) : "审计详情"}
        desc={active ? `${active.actorName || "系统"} · ${formatDateTime(active.ts)}` : undefined}
        width="w-[620px]"
        footer={
          <>
            {active?.sessionId && (
              <Button
                variant="outline"
                icon={<Terminal size={13} />}
                onClick={() => {
                  if (employeeId) {
                    setActive(null);
                    nav(`/chat/${employeeId}/${active.sessionId}`);
                  } else {
                    void copyText(active.sessionId || "");
                  }
                }}
              >
                {employeeId ? "查看会话" : "复制会话 ID"}
              </Button>
            )}
            <Button variant="outline" onClick={() => setActive(null)}>
              关闭
            </Button>
          </>
        }
      >
        {active && (
          <div className="space-y-3.5">
            <div className="grid grid-cols-2 gap-2 text-[12px]">
              <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                <div className="text-[10.5px] text-ink-400">风险等级</div>
                <div className="mt-0.5">
                  <span className={cx("chip", riskBadgeClass(active.risk))}>{riskLabel[active.risk] ?? active.risk}</span>
                </div>
              </div>
              <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                <div className="text-[10.5px] text-ink-400">执行结果</div>
                <div className="mt-0.5">
                  <Badge tone={(RESULT_META[active.result] ?? RESULT_META.success).tone} dot>
                    {(RESULT_META[active.result] ?? RESULT_META.success).label}
                  </Badge>
                </div>
              </div>
              <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                <div className="text-[10.5px] text-ink-400">对象</div>
                <div className="mt-0.5 truncate text-ink-800">
                  {active.targetName || "—"}
                  {active.targetType ? `（${active.targetType}）` : ""}
                </div>
              </div>
              <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                <div className="text-[10.5px] text-ink-400">IP / 会话</div>
                <div className="mt-0.5 truncate font-mono text-[11px] text-ink-700">
                  {active.ip || "—"}
                  {active.sessionId ? ` · ${active.sessionId.slice(0, 10)}…` : ""}
                </div>
              </div>
            </div>

            {active.result === "denied" && (
              <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] leading-relaxed text-rose-700">
                <ShieldAlert size={14} className="mt-0.5 shrink-0" />
                该操作被权限网关拒绝，已记录可解释原因；在「数据安全 → SQL 改写预览」可用同一身份复现。
              </div>
            )}

            {rules.length > 0 && (
              <div>
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="text-[12.5px] font-semibold text-ink-900">命中规则</span>
                  <Badge tone="gray">{rules.length} 条</Badge>
                </div>
                <div className="space-y-1">
                  {rules.map((r, i) => (
                    <div key={i} className="flex items-start gap-1.5 rounded-lg bg-surface-50 px-2 py-1.5">
                      <Badge tone="gray">{RULE_LABEL[r.type ?? ""] ?? r.type ?? "规则"}</Badge>
                      <span className="min-w-0 flex-1 text-[11.5px] leading-relaxed text-ink-600">{r.detail ?? "—"}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {typeof detail?.originalSql === "string" && (
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-[12.5px] font-semibold text-ink-900">原始 SQL</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Copy size={12} />}
                    onClick={() => void copyText(String(detail?.originalSql ?? ""))}
                  >
                    复制
                  </Button>
                </div>
                <SqlBlock sql={String(detail.originalSql)} tone="light" />
              </div>
            )}

            {typeof detail?.rewrittenSql === "string" && (
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-[12.5px] font-semibold text-ink-900">改写后 SQL</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Copy size={12} />}
                    onClick={() => void copyText(String(detail?.rewrittenSql ?? ""))}
                  >
                    复制
                  </Button>
                </div>
                <SqlBlock sql={String(detail.rewrittenSql)} />
              </div>
            )}

            <div>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-[12.5px] font-semibold text-ink-900">详情 JSON</span>
                <span className="text-[11px] text-ink-400">可逐层展开</span>
              </div>
              <JsonViewer data={active.detail} emptyText="该动作没有附加详情" />
            </div>

            {active.sessionId && !employeeId && (
              <div className="flex items-start gap-2 rounded-xl bg-surface-50 px-3 py-2 text-[11.5px] leading-relaxed text-ink-500">
                <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-500" />
                详情里没有 employeeId，无法直接跳转到会话页；可复制会话 ID 后在会话列表中检索。
              </div>
            )}

            <div className="flex items-center gap-1.5 text-[10.5px] text-ink-400">
              <ShieldCheck size={11} /> 审计记录不可编辑、不可删除，用于事后追溯与合规留痕。
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
