import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  Bot,
  CheckCircle2,
  Flame,
  MessagesSquare,
  RefreshCw,
  ShieldAlert,
  Store,
  Users,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import type { OverviewStats } from "@/lib/types";
import { Avatar, Badge, Button, Card, CardHeader, Empty, Skeleton, Stat, toast } from "@/components/ui";
import { EChart } from "@/components/ui/EChart";
import { PageHeader } from "@/components/admin/PageHeader";
import { actionLabel, compactNumber, cx, formatDateTime, formatNumber, riskBadgeClass, riskLabel, timeAgo } from "@/lib/format";

const RISK_COLORS: Record<string, string> = { low: "#10B981", medium: "#F59E0B", high: "#F43F5E" };

export default function Overview() {
  const [data, setData] = useState<OverviewStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  const load = useCallback(async (mode: "initial" | "refresh" = "initial") => {
    if (mode === "refresh") setRefreshing(true);
    else setLoading(true);
    try {
      const res = await api.get<OverviewStats>("/overview");
      setData(res);
      setUpdatedAt(new Date().toISOString());
      setError(null);
      if (mode === "refresh") toast("运营数据已刷新");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "总览数据加载失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = data?.stats;
  /** 后端在 stats 里额外给了 highRisk / auditEvents 等聚合值（类型契约里是可选扩展）。 */
  const statsExtra = data?.stats as (OverviewStats["stats"] & { highRisk?: number; auditEvents?: number }) | undefined;
  const trend = useMemo(() => data?.trend ?? [], [data]);
  const risks = useMemo(() => data?.riskDistribution ?? [], [data]);
  const scenarios = useMemo(() => {
    const raw = (data?.scenarioStats ?? []) as unknown as { name?: string; key?: string; label?: string; action?: string; count: number }[];
    return raw
      .map((s) => ({
        key: s.key ?? s.action ?? s.label ?? "unknown",
        name: s.label ?? s.name ?? s.action ?? "未命名场景",
        count: s.count,
      }))
      .slice(0, 6);
  }, [data]);
  const topEmployees = useMemo(() => {
    const raw = (data?.topEmployees ?? []) as unknown as {
      id: string;
      name: string;
      avatar?: string;
      sessions: number;
      toolCalls?: number;
      ownerName?: string;
    }[];
    return raw;
  }, [data]);
  const recentAudit = useMemo(() => (data?.recentAudit ?? []).slice(0, 6), [data]);

  const last7Denied = stats?.denied ?? 0;
  const highApprovals =
    statsExtra?.highRisk ?? (data?.recentAudit ?? []).filter((a) => a.action === "hitl_approval" && a.risk === "high").length;

  const maxSessions = Math.max(1, ...topEmployees.map((e) => e.sessions));
  const maxScenario = Math.max(1, ...scenarios.map((s) => s.count));

  const isEmpty =
    !loading && !error && !!stats && stats.employees === 0 && stats.sessions === 0 && stats.toolCalls === 0 && stats.activeUsers === 0;

  const trendOption = useMemo(
    () => ({
      grid: { left: 4, right: 12, top: 32, bottom: 4, containLabel: true },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: {
        right: 0,
        top: 0,
        icon: "roundRect",
        itemWidth: 8,
        itemHeight: 8,
        itemGap: 14,
        textStyle: { fontSize: 11, color: "#6B7280" },
      },
      xAxis: {
        type: "category",
        data: trend.map((t) => t.date.slice(5)),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: "#E6E9F2" } },
        axisLabel: { color: "#8B93A7", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: "#EFF1F7" } },
        axisLabel: { color: "#8B93A7", fontSize: 11 },
      },
      series: [
        { name: "会话", type: "bar", barWidth: 14, itemStyle: { color: "#5B57E8", borderRadius: [4, 4, 0, 0] }, data: trend.map((t) => t.sessions) },
        {
          name: "工具调用",
          type: "line",
          smooth: true,
          symbolSize: 5,
          lineStyle: { width: 2, color: "#14B8A6" },
          itemStyle: { color: "#14B8A6" },
          areaStyle: { color: "rgba(20,184,166,.08)" },
          data: trend.map((t) => t.toolCalls),
        },
      ],
    }),
    [trend]
  );

  const riskOption = useMemo(() => {
    const order = ["low", "medium", "high"];
    const list = [...risks].sort((a, b) => order.indexOf(a.risk) - order.indexOf(b.risk));
    return {
      tooltip: { trigger: "item", formatter: "{b}：{c} 条（{d}%）" },
      legend: {
        bottom: 0,
        icon: "circle",
        itemWidth: 7,
        itemHeight: 7,
        itemGap: 12,
        textStyle: { fontSize: 11, color: "#6B7280" },
      },
      series: [
        {
          type: "pie",
          radius: ["52%", "72%"],
          center: ["50%", "44%"],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: "#fff", borderWidth: 2 },
          label: { show: false },
          labelLine: { show: false },
          data: list.map((r) => ({
            name: riskLabel[r.risk] ?? r.risk,
            value: r.count,
            itemStyle: { color: RISK_COLORS[r.risk] ?? "#8B93A7" },
          })),
        },
      ],
    };
  }, [risks]);

  const riskTotal = risks.reduce((sum, r) => sum + r.count, 0);

  return (
    <div className="h-full overflow-y-auto bg-surface-100">
      <div className="mx-auto max-w-[1440px] space-y-5 px-6 py-5">
        <PageHeader
          title="运营总览 · 平台运行状态"
          desc="数字员工、会话、工具调用与风险拦截的实时画像，用于回答「投了多少、用了多少、拦了多少」。"
          badge={
            <Badge tone="brand" dot>
              管理员视角
            </Badge>
          }
          meta={
            <>
              <span className="inline-flex items-center gap-1">
                <Activity size={12} /> 实时计算自会话 / 工具调用 / 审计三张表
              </span>
              <span>最近更新：{updatedAt ? formatDateTime(updatedAt) : "—"}</span>
            </>
          }
          actions={
            <>
              <span className="text-[11.5px] text-ink-400">{updatedAt ? timeAgo(updatedAt) : ""}</span>
              <Button
                variant="outline"
                icon={<RefreshCw size={14} className={cx(refreshing && "animate-spin")} />}
                loading={refreshing}
                onClick={() => void load("refresh")}
              >
                刷新
              </Button>
            </>
          }
        />

        {/* 安全提示条 */}
        {!error && (
          <div
            className={cx(
              "flex flex-wrap items-center gap-3 rounded-2xl border px-4 py-3",
              last7Denied > 0 || highApprovals > 0 ? "border-amber-200 bg-amber-50/70" : "border-emerald-200 bg-emerald-50/70"
            )}
          >
            <div
              className={cx(
                "grid h-8 w-8 shrink-0 place-items-center rounded-xl",
                last7Denied > 0 || highApprovals > 0 ? "bg-amber-100 text-amber-600" : "bg-emerald-100 text-emerald-600"
              )}
            >
              {last7Denied > 0 || highApprovals > 0 ? <ShieldAlert size={16} /> : <CheckCircle2 size={16} />}
            </div>
            <div className="min-w-0 flex-1 text-[12.5px] leading-relaxed text-ink-700">
              {last7Denied > 0 || highApprovals > 0 ? (
                <>
                  近 7 日共拦截 <b className="text-rose-600">{formatNumber(last7Denied)}</b> 次越权操作
                  {highApprovals > 0 && (
                    <>
                      ，其中 <b className="text-amber-600">{formatNumber(highApprovals)}</b> 条高风险动作经过人工审批
                    </>
                  )}
                  。拦截与审批均已留痕，可在审计日志按「已拒绝 / 高风险」复核。
                </>
              ) : (
                <>近 7 日没有越权拦截记录，数据权限网关与审计链路运行正常。</>
              )}
            </div>
            <Link to="/admin/audit" className="shrink-0 text-[12px] font-medium text-brand-600 hover:text-brand-700">
              查看审计日志 →
            </Link>
          </div>
        )}

        {loading && (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-[104px]" />
              ))}
            </div>
            <div className="grid gap-3 xl:grid-cols-3">
              <Skeleton className="h-[300px] xl:col-span-2" />
              <Skeleton className="h-[300px]" />
            </div>
          </>
        )}

        {!loading && error && (
          <Card>
            <Empty
              icon={<ShieldAlert size={20} />}
              title="总览数据加载失败"
              desc={`${error}。后端 /api/overview 可能尚未就绪，可稍后重试。`}
              action={
                <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void load()}>
                  重新加载
                </Button>
              }
            />
          </Card>
        )}

        {!loading && !error && isEmpty && (
          <Card>
            <Empty
              icon={<Bot size={20} />}
              title="还没有运营数据"
              desc="平台当前没有数字员工与会话记录。先创建一个员工、发起一轮会话，这里就会出现趋势与风险分布。"
              action={
                <Link to="/employees">
                  <Button>去创建数字员工</Button>
                </Link>
              }
            />
          </Card>
        )}

        {!loading && !error && !isEmpty && (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <Stat label="数字员工" value={formatNumber(stats?.employees)} icon={<Bot size={16} />} tone="brand" hint="含公共员工副本" />
              <Stat
                label="会话总数"
                value={formatNumber(stats?.sessions)}
                icon={<MessagesSquare size={16} />}
                tone="sky"
                hint={`${formatNumber(stats?.messages)} 条消息`}
              />
              <Stat label="工具调用" value={compactNumber(stats?.toolCalls)} icon={<Wrench size={16} />} tone="teal" hint="近 7 日" />
              <Stat label="拦截次数" value={formatNumber(stats?.denied)} icon={<ShieldAlert size={16} />} tone="rose" hint="越权被网关拒绝" />
              <Stat label="技能数" value={formatNumber(stats?.skills)} icon={<Store size={16} />} tone="amber" hint="内置 + 用户级" />
              <Stat label="活跃用户" value={formatNumber(stats?.activeUsers)} icon={<Users size={16} />} tone="brand" hint={`共 ${formatNumber(stats?.users)} 个账号`} />
            </div>

            <div className="grid gap-3 xl:grid-cols-3">
              <Card className="xl:col-span-2">
                <CardHeader
                  title="近 7 日会话与工具调用趋势"
                  desc="柱：会话数；线：工具调用数。两者背离说明「问得多、干得少」或反之。"
                  extra={<Badge tone="brand">{trend.length} 天</Badge>}
                />
                <div className="px-3 pb-4">
                  {trend.length ? <EChart option={trendOption} height={292} /> : <Empty title="暂无趋势数据" desc="近 7 日没有会话记录。" />}
                </div>
              </Card>

              <div className="space-y-3">
                <Card>
                  <CardHeader title="风险分布" desc="审计事件按风险等级聚合" extra={<Badge tone="gray">{formatNumber(riskTotal)} 条</Badge>} />
                  <div className="px-3 pb-3">
                    {riskTotal ? <EChart option={riskOption} height={172} /> : <Empty title="暂无风险事件" desc="审计里还没有风险等级数据。" />}
                  </div>
                </Card>

                <Card>
                  <CardHeader title="场景调用" desc="按动作类型统计的调用量（Top 6）" />
                  <div className="space-y-2.5 px-5 pb-4">
                    {scenarios.length ? (
                      scenarios.map((s) => (
                        <div key={s.key || s.name}>
                          <div className="mb-1 flex items-center justify-between text-[12px]">
                            <span className="truncate text-ink-700">{s.name}</span>
                            <span className="shrink-0 font-medium text-ink-500">{formatNumber(s.count)}</span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-surface-200">
                            <div
                              className="h-full rounded-full bg-gradient-to-r from-brand-500 to-teal-500"
                              style={{ width: `${Math.max(4, (s.count / maxScenario) * 100)}%` }}
                            />
                          </div>
                        </div>
                      ))
                    ) : (
                      <Empty title="暂无场景统计" desc="会话尚未标注场景。" />
                    )}
                  </div>
                </Card>
              </div>
            </div>

            <div className="grid gap-3 xl:grid-cols-2">
              <Card>
                <CardHeader
                  title="数字员工活跃榜"
                  desc="按会话数排序"
                  extra={
                    <Link to="/employees" className="text-[12px] text-brand-600 hover:text-brand-700">
                      全部员工 →
                    </Link>
                  }
                />
                <div className="divide-y divide-surface-200/80 px-2 pb-2">
                  {topEmployees.length ? (
                    topEmployees.slice(0, 8).map((e, i) => (
                      <div key={e.id} className="flex items-center gap-3 px-3 py-2.5">
                        <span className={cx("w-4 shrink-0 text-center text-[11px] font-semibold", i < 3 ? "text-brand-600" : "text-ink-300")}>
                          {i + 1}
                        </span>
                        <Avatar name={e.name} seed={e.avatar || e.id} size={32} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate text-[12.5px] font-medium text-ink-900">{e.name}</span>
                            <span className="shrink-0 text-[11.5px] text-ink-500">
                              {formatNumber(e.sessions)} 会话
                              {e.toolCalls !== undefined && <span className="ml-1.5 text-ink-400">{formatNumber(e.toolCalls)} 调用</span>}
                            </span>
                          </div>
                          {e.ownerName && <div className="mt-0.5 truncate text-[10.5px] text-ink-400">归属：{e.ownerName}</div>}
                          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-200">
                            <div
                              className="h-full rounded-full bg-brand-500/80"
                              style={{ width: `${Math.max(4, (e.sessions / maxSessions) * 100)}%` }}
                            />
                          </div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <Empty title="暂无员工活跃数据" desc="还没有产生会话的员工。" />
                  )}
                </div>
              </Card>

              <Card>
                <CardHeader
                  title="最近审计"
                  desc="最新 6 条全链路动作"
                  extra={
                    <Link to="/admin/audit" className="text-[12px] text-brand-600 hover:text-brand-700">
                      审计日志 →
                    </Link>
                  }
                />
                <div className="divide-y divide-surface-200/80 px-2 pb-2">
                  {recentAudit.length ? (
                    recentAudit.map((ev) => (
                      <div key={ev.id} className="flex items-center gap-3 px-3 py-2.5">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="truncate text-[12.5px] font-medium text-ink-900">
                              {ev.actionLabel && ev.actionLabel !== ev.action ? ev.actionLabel : actionLabel(ev.action)}
                            </span>
                            <span className={cx("chip", riskBadgeClass(ev.risk))}>{riskLabel[ev.risk] ?? ev.risk}</span>
                            {ev.result !== "success" && (
                              <Badge tone={ev.result === "denied" ? "rose" : "amber"}>{ev.result === "denied" ? "已拒绝" : "异常"}</Badge>
                            )}
                          </div>
                          <div className="mt-0.5 truncate text-[11.5px] text-ink-500">
                            {ev.actorName || "系统"}
                            {ev.targetName ? ` · ${ev.targetName}` : ""}
                          </div>
                        </div>
                        <span className="shrink-0 text-[11px] text-ink-400">{timeAgo(ev.ts)}</span>
                      </div>
                    ))
                  ) : (
                    <Empty title="暂无审计记录" desc="平台动作会自动写入审计。" />
                  )}
                </div>
              </Card>
            </div>

            <div className="flex items-center justify-center gap-2 pb-2 text-[11px] text-ink-400">
              <Flame size={12} className="text-brand-400" />
              拒绝与审批闭环、工具调用可回放，是本平台「管理难 / 安全不可控」的落点。
            </div>
          </>
        )}
      </div>
    </div>
  );
}
