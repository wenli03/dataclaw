import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Database,
  EyeOff,
  ListChecks,
  Lock,
  Play,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Table2,
  Wand2,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ColumnMeta, DataSource, Paginated, Policy, User } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Empty,
  Field,
  Input,
  Modal,
  Select,
  Skeleton,
  Tabs,
  Textarea,
  Tip,
  Toggle,
  toast,
} from "@/components/ui";
import { JsonViewer, SqlBlock } from "@/components/admin/JsonViewer";
import { PageHeader } from "@/components/admin/PageHeader";
import { cx, formatNumber } from "@/lib/format";

/* ------------------------------------------------------------------ 契约类型（后端未就绪时按契约实现，字段全部可选以容错） */

interface TableItem {
  name: string;
  comment?: string;
  rowCount?: number;
  allowed?: boolean;
  deniedReason?: string;
  columnCount?: number;
  visibleColumnCount?: number;
  maskedColumnCount?: number;
  deniedColumnCount?: number;
  sensitiveColumns?: string[];
  rowFilters?: string[];
}

/** 字段元数据 + 当前账号在该表上的有效动作（后端 columns 接口一并给出）。 */
interface ColumnItem extends ColumnMeta {
  maskParam?: Record<string, unknown>;
  visible?: boolean;
  action?: string;
  reason?: string;
}

interface PolicyItem extends Policy {
  subjectName?: string;
  table?: string;
  column?: string;
  tableComment?: string;
  createdAt?: string;
}

interface EffectiveColumn {
  column: string;
  action?: string;
  mask?: string;
  maskParam?: Record<string, unknown>;
  sensitiveLevel?: string;
  comment?: string;
  policyId?: string | null;
  reason?: string;
  visible?: boolean;
  masked?: boolean;
}

interface EffectiveRule {
  policyId?: string;
  subjectType?: string;
  subjectId?: string;
  resourceType?: string;
  resourceId?: string;
  action?: string;
  mask?: string;
  priority?: number;
  note?: string;
  reason?: string;
}

interface EffectiveTable {
  table: string;
  comment?: string;
  rowCount?: number;
  allowed?: boolean;
  deniedReason?: string | null;
  rowFilters?: string[];
  columns?: EffectiveColumn[];
  deniedColumns?: EffectiveColumn[];
  rules?: EffectiveRule[];
}

interface EffectiveMatrix {
  userId: string;
  username?: string;
  name?: string;
  role?: string;
  datasourceId?: string;
  datasourceName?: string;
  dataScopeSummary?: string;
  tables?: EffectiveTable[];
  summary?: {
    tablesVisible?: number;
    tablesDenied?: number;
    columnsMasked?: number;
    columnsDenied?: number;
    rowFiltered?: number;
    rowFilterTables?: string[];
  };
}

interface PreviewRule {
  type?: string;
  detail?: string;
  table?: string;
  column?: string;
  columns?: string[];
  mask?: string;
}

interface PreviewResult {
  ok?: boolean;
  originalSql?: string;
  rewrittenSql?: string;
  columns?: string[];
  maskedColumns?: string[];
  rows?: Record<string, unknown>[];
  appliedRules?: PreviewRule[];
  deniedReason?: string | null;
  durationMs?: number;
  rowCount?: number;
  limit?: number;
  error?: string | null;
}

interface TestResult {
  ok?: boolean;
  status?: string;
  message?: string;
  latencyMs?: number;
}

interface ClassifyColumn {
  name: string;
  level: string;
  comment?: string;
}

interface ClassifyTable {
  table: string;
  comment?: string;
  /** 仅敏感列（secret / top_secret），用于标签展示 */
  columns: ClassifyColumn[];
  counts: Record<string, number>;
  total: number;
}

interface ClassifyResult {
  tables: ClassifyTable[];
  levels: { level: string; label?: string; count: number }[];
  tags: { name: string; level: string }[];
}

/* ------------------------------------------------------------------ 常量与小组件 */

const LEVEL_META: Record<string, { label: string; tone: "gray" | "blue" | "amber" | "rose"; color: string }> = {
  public: { label: "公开", tone: "gray", color: "#94A3B8" },
  internal: { label: "内部", tone: "blue", color: "#38BDF8" },
  secret: { label: "机密", tone: "amber", color: "#F59E0B" },
  top_secret: { label: "绝密", tone: "rose", color: "#F43F5E" },
};
const LEVEL_ORDER = ["public", "internal", "secret", "top_secret"];

const RESOURCE_LABEL: Record<string, string> = {
  datasource: "数据源",
  table: "表",
  column: "字段",
  metric: "指标",
  row: "行级",
};
const ACTION_LABEL: Record<string, string> = { allow: "允许", deny: "拒绝" };
const MASK_LABEL: Record<string, string> = { none: "不脱敏", mask: "掩码", hash: "哈希", replace: "常量替换", truncate: "截断" };
const RULE_LABEL: Record<string, string> = {
  table: "表级",
  column_denied: "列级拒绝",
  star_expand: "列展开",
  row_filter: "行级",
  limit: "LIMIT",
  mask: "脱敏",
  deny: "拒绝",
};
const ROLE_LABEL: Record<string, string> = { platform_admin: "平台管理员", dept_admin: "部门管理员", member: "普通成员" };

function LevelBadge({ level }: { level?: string }) {
  const meta = LEVEL_META[level || "public"] ?? LEVEL_META.public;
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

function maskParamText(mask?: string, param?: Record<string, unknown>): string {
  if (!mask || mask === "none") return "";
  const p = param ?? {};
  if (mask === "mask") return `keep=${String(p.keep ?? 0)}`;
  if (mask === "replace") return `→ ${String(p.replace_with ?? p.replaceWith ?? "***")}`;
  if (mask === "truncate") return `保留前 ${String(p.start ?? p.keep ?? 0)} 位`;
  if (mask === "hash") return "sha256";
  return "";
}

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/* ------------------------------------------------------------------ 分类统计归一化
 * 后端 /classifications 返回：
 * { items:[{table, comment, public, internal, secret, top_secret, total, sensitiveColumns:[{name,level,comment}]}],
 *   total, totals:{level:count}, levels:[{level,label,count}] }
 * 这里同时兼容 byLevel/counts 等替代写法，避免后端小改就白屏。
 */

function normalizeClassifications(raw: unknown): ClassifyResult {
  let list: Record<string, unknown>[] = [];
  let apiLevels: { level: string; label?: string; count: number }[] = [];

  if (Array.isArray(raw)) {
    list = raw.filter((x): x is Record<string, unknown> => typeof x === "object" && x !== null);
  } else if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    const arr = obj.items ?? obj.tables ?? obj.byTable;
    if (Array.isArray(arr)) list = arr.filter((x): x is Record<string, unknown> => typeof x === "object" && x !== null);
    if (Array.isArray(obj.levels)) {
      for (const item of obj.levels) {
        if (!item || typeof item !== "object") continue;
        const r = item as Record<string, unknown>;
        const level = String(r.level ?? r.sensitiveLevel ?? "");
        if (!level) continue;
        apiLevels.push({ level, label: r.label ? String(r.label) : undefined, count: Number(r.count ?? 0) || 0 });
      }
    }
  }

  const tables: ClassifyTable[] = list.map((row) => {
    const table = String(row.table ?? row.name ?? "未命名表");
    const counts: Record<string, number> = {};
    // 1) 后端扁平写法：public/internal/secret/top_secret
    for (const lvl of LEVEL_ORDER) {
      const v = row[lvl];
      if (typeof v === "number") counts[lvl] = v;
    }
    // 2) 兼容 byLevel / counts / levels 映射或数组
    const rawCounts = row.byLevel ?? row.counts ?? row.levels;
    if (rawCounts && typeof rawCounts === "object" && !Array.isArray(rawCounts)) {
      for (const [k, v] of Object.entries(rawCounts as Record<string, unknown>)) {
        counts[k] = Number(v) || 0;
      }
    } else if (Array.isArray(rawCounts)) {
      for (const item of rawCounts) {
        if (item && typeof item === "object") {
          const r = item as Record<string, unknown>;
          counts[String(r.level ?? r.sensitiveLevel ?? "public")] = Number(r.count ?? 0) || 0;
        }
      }
    }

    const columns: ClassifyColumn[] = [];
    const rawCols = row.sensitiveColumns ?? row.columns ?? row.cols;
    if (Array.isArray(rawCols)) {
      for (const c of rawCols) {
        if (!c || typeof c !== "object") continue;
        const r = c as Record<string, unknown>;
        const name = String(r.name ?? r.column ?? "");
        if (!name) continue;
        columns.push({
          name,
          level: String(r.sensitiveLevel ?? r.level ?? "secret"),
          comment: r.comment ? String(r.comment) : undefined,
        });
      }
    }
    if (columns.length && !Object.keys(counts).length) {
      for (const c of columns) counts[c.level] = (counts[c.level] ?? 0) + 1;
    }

    const total =
      Number(row.total ?? 0) ||
      Number(row.columnCount ?? 0) ||
      Object.values(counts).reduce((a, b) => a + b, 0);
    return { table, comment: row.comment ? String(row.comment) : undefined, columns, counts, total };
  });

  const sums: Record<string, number> = {};
  for (const t of tables) for (const [k, v] of Object.entries(t.counts)) sums[k] = (sums[k] ?? 0) + v;

  const levels: { level: string; label?: string; count: number }[] = apiLevels.length
    ? apiLevels
    : LEVEL_ORDER.map((l) => ({ level: l, count: sums[l] ?? 0 }));

  const tags: { name: string; level: string }[] = [];
  const seen = new Set<string>();
  for (const t of tables) {
    for (const c of t.columns) {
      const key = `${c.name}|${c.level}`;
      if (seen.has(key)) continue;
      seen.add(key);
      tags.push({ name: c.name, level: c.level });
    }
  }

  return { tables, levels, tags };
}

/* ------------------------------------------------------------------ 策略表单 */

type ResourceType = "datasource" | "table" | "column" | "metric" | "row";
type MaskType = "none" | "mask" | "hash" | "replace" | "truncate";

interface PolicyForm {
  subjectType: "user" | "role";
  subjectId: string;
  resourceType: ResourceType;
  datasourceId: string;
  table: string;
  column: string;
  metric: string;
  action: "allow" | "deny";
  mask: MaskType;
  maskKeep: string;
  maskReplace: string;
  maskStart: string;
  rowFilter: string;
  priority: string;
  note: string;
}

const EMPTY_POLICY: PolicyForm = {
  subjectType: "user",
  subjectId: "",
  resourceType: "table",
  datasourceId: "",
  table: "",
  column: "",
  metric: "",
  action: "allow",
  mask: "none",
  maskKeep: "3",
  maskReplace: "***",
  maskStart: "4",
  rowFilter: "",
  priority: "100",
  note: "",
};

function buildResourceId(f: PolicyForm): string {
  if (f.resourceType === "datasource") return f.datasourceId;
  if (f.resourceType === "metric") return f.metric.trim();
  if (f.resourceType === "column") return `${f.datasourceId}:${f.table}.${f.column}`;
  return `${f.datasourceId}:${f.table}`;
}

/* ------------------------------------------------------------------ 页面 */

export default function DataSecurity() {
  const [tab, setTab] = useState("sources");

  /* 数据源 */
  const [sources, setSources] = useState<DataSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [dsId, setDsId] = useState("");
  const [testingId, setTestingId] = useState<string | null>(null);
  const [sourceModal, setSourceModal] = useState(false);
  const [sourceForm, setSourceForm] = useState({ name: "", type: "sqlite", host: "", port: "", database: "", username: "", password: "", description: "" });
  const [sourceSaving, setSourceSaving] = useState(false);
  const [sourceFormError, setSourceFormError] = useState<string | null>(null);

  /* 表与字段 */
  const [tables, setTables] = useState<TableItem[]>([]);
  const [tablesLoading, setTablesLoading] = useState(true);
  const [tablesError, setTablesError] = useState<string | null>(null);
  /** 后端返回的「因默认拒绝而不可见」的表数量 */
  const [hiddenTables, setHiddenTables] = useState(0);
  const [openTable, setOpenTable] = useState<string | null>(null);
  const [columnsByTable, setColumnsByTable] = useState<Record<string, ColumnItem[]>>({});
  const [columnsLoading, setColumnsLoading] = useState<string | null>(null);
  const [columnsError, setColumnsError] = useState<Record<string, string>>({});

  /* 用户（主体 / 生效矩阵 / 预览） */
  const [users, setUsers] = useState<User[]>([]);

  /* 策略 */
  const [policies, setPolicies] = useState<PolicyItem[]>([]);
  const [policiesLoading, setPoliciesLoading] = useState(false);
  const [policiesError, setPoliciesError] = useState<string | null>(null);
  const [busyPolicyId, setBusyPolicyId] = useState<string | null>(null);
  const [policyModal, setPolicyModal] = useState(false);
  const [policyForm, setPolicyForm] = useState<PolicyForm>(EMPTY_POLICY);
  const [policySaving, setPolicySaving] = useState(false);
  const [policyFormError, setPolicyFormError] = useState<string | null>(null);

  /* 生效矩阵 */
  const [effUserId, setEffUserId] = useState("");
  const [effData, setEffData] = useState<EffectiveMatrix | null>(null);
  const [effLoading, setEffLoading] = useState(false);
  const [effError, setEffError] = useState<string | null>(null);

  /* SQL 预览 */
  const [previewUserId, setPreviewUserId] = useState("");
  const [sqlText, setSqlText] = useState("select * from worktime_fact limit 5");
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  /* 分级统计 */
  const [classify, setClassify] = useState<ReturnType<typeof normalizeClassifications> | null>(null);
  const [classifyLoading, setClassifyLoading] = useState(false);
  const [classifyError, setClassifyError] = useState<string | null>(null);

  /* ---------------- 加载 ---------------- */

  const loadSources = useCallback(async () => {
    setSourcesLoading(true);
    try {
      const res = await api.get<Paginated<DataSource>>("/datasources");
      const list = res.items ?? [];
      setSources(list);
      setDsId((prev) => (prev && list.some((d) => d.id === prev) ? prev : list[0]?.id ?? ""));
      setSourcesError(null);
    } catch (e: unknown) {
      setSourcesError(errText(e, "数据源加载失败"));
    } finally {
      setSourcesLoading(false);
    }
  }, []);

  const loadUsers = useCallback(async () => {
    try {
      const res = await api.get<Paginated<User>>("/users", { size: 200 });
      setUsers(res.items ?? []);
    } catch {
      setUsers([]);
    }
  }, []);

  const loadTables = useCallback(async (id: string) => {
    if (!id) {
      setTables([]);
      setHiddenTables(0);
      setTablesLoading(false);
      return;
    }
    setTablesLoading(true);
    setTables([]);
    setHiddenTables(0);
    setOpenTable(null);
    setColumnsError({});
    try {
      const res = await api.get<Paginated<TableItem> & { hiddenTableCount?: number }>(`/datasources/${id}/tables`);
      setTables(res.items ?? []);
      setHiddenTables(res.hiddenTableCount ?? 0);
      setTablesError(null);
    } catch (e: unknown) {
      setTablesError(errText(e, "表元数据加载失败"));
    } finally {
      setTablesLoading(false);
    }
  }, []);

  const loadPolicies = useCallback(async () => {
    setPoliciesLoading(true);
    try {
      const res = await api.get<Paginated<PolicyItem>>("/policies");
      setPolicies(res.items ?? []);
      setPoliciesError(null);
    } catch (e: unknown) {
      setPoliciesError(errText(e, "策略加载失败"));
    } finally {
      setPoliciesLoading(false);
    }
  }, []);

  const loadClassify = useCallback(async () => {
    setClassifyLoading(true);
    try {
      const res = await api.get<unknown>("/classifications");
      setClassify(normalizeClassifications(res));
      setClassifyError(null);
    } catch (e: unknown) {
      setClassifyError(errText(e, "分级统计加载失败"));
    } finally {
      setClassifyLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSources();
    void loadUsers();
    // 策略计数在首屏就要准（页头展示「N 条策略」），不等到切 tab 才拉
    void loadPolicies();
  }, [loadSources, loadUsers, loadPolicies]);

  useEffect(() => {
    void loadTables(dsId);
  }, [dsId, loadTables]);

  useEffect(() => {
    if (tab === "classify" && !classify && !classifyLoading) void loadClassify();
  }, [tab, classify, classifyLoading, loadClassify]);

  useEffect(() => {
    if (!users.length) return;
    // 默认落在 analyst：这是演示「行级过滤 + salary 掩码 + employee_name 哈希」的主角
    const preferred = users.find((u) => u.username === "analyst") ?? users[0];
    if (!effUserId) setEffUserId(preferred.id);
    if (!previewUserId) setPreviewUserId(preferred.id);
  }, [users, effUserId, previewUserId]);

  /* ---------------- 字段展开 ---------------- */

  async function ensureColumns(table: string) {
    if (!dsId || columnsByTable[table]) return;
    if (columnsError[table]) return;
    setColumnsLoading(table);
    try {
      const res = await api.get<Paginated<ColumnItem> & { rowFilters?: string[] }>(`/datasources/${dsId}/tables/${table}/columns`);
      setColumnsByTable((prev) => ({ ...prev, [table]: res.items ?? [] }));
    } catch (e: unknown) {
      // 403 = 当前账号在该表上没有授权（默认拒绝），属正常业务状态，不当异常弹 toast
      const status = (e as { status?: number }).status ?? 0;
      const message =
        status === 403
          ? "当前账号在该表上没有授权（默认拒绝）。可到「生效矩阵」按用户查看，或为当前角色补一条表级 allow 策略。"
          : errText(e, "字段元数据加载失败");
      setColumnsError((prev) => ({ ...prev, [table]: message }));
    } finally {
      setColumnsLoading(null);
    }
  }

  async function toggleTable(table: string) {
    if (openTable === table) {
      setOpenTable(null);
      return;
    }
    setOpenTable(table);
    await ensureColumns(table);
  }

  /* ---------------- 数据源操作 ---------------- */

  async function testConnection(ds: DataSource) {
    setTestingId(ds.id);
    try {
      const res = await api.post<TestResult>(`/datasources/${ds.id}/test`);
      const ok = res?.ok !== false && res?.status !== "error";
      toast(ok ? `连接正常${res?.latencyMs ? `（${res.latencyMs}ms）` : ""}` : res?.message || "连接失败", ok ? "success" : "error");
      await loadSources();
    } catch (e: unknown) {
      toast(errText(e, "测试连接失败"), "error");
    } finally {
      setTestingId(null);
    }
  }

  async function submitSource() {
    if (!sourceForm.name.trim()) {
      setSourceFormError("请填写数据源名称");
      return;
    }
    setSourceSaving(true);
    setSourceFormError(null);
    try {
      await api.post("/datasources", {
        name: sourceForm.name.trim(),
        type: sourceForm.type,
        host: sourceForm.host.trim(),
        port: sourceForm.port ? Number(sourceForm.port) : undefined,
        database: sourceForm.database.trim(),
        username: sourceForm.username.trim(),
        password: sourceForm.password,
        description: sourceForm.description.trim(),
      });
      toast("数据源已创建");
      setSourceModal(false);
      setSourceForm({ name: "", type: "sqlite", host: "", port: "", database: "", username: "", password: "", description: "" });
      await loadSources();
    } catch (e: unknown) {
      setSourceFormError(errText(e, "创建数据源失败"));
    } finally {
      setSourceSaving(false);
    }
  }

  /* ---------------- 策略操作 ---------------- */

  function openPolicyModal() {
    setPolicyForm({ ...EMPTY_POLICY, datasourceId: dsId || sources[0]?.id || "", subjectId: users[0]?.id || "", table: tables[0]?.name || "" });
    setPolicyFormError(null);
    setPolicyModal(true);
  }

  async function submitPolicy() {
    const resourceId = buildResourceId(policyForm);
    if (!policyForm.subjectId) {
      setPolicyFormError("请选择策略主体");
      return;
    }
    if (!resourceId) {
      setPolicyFormError("请选择资源（数据源 / 表 / 字段 / 指标）");
      return;
    }
    const maskParam: Record<string, unknown> = {};
    if (policyForm.mask === "mask") maskParam.keep = Number(policyForm.maskKeep) || 0;
    if (policyForm.mask === "replace") maskParam.replace_with = policyForm.maskReplace || "***";
    if (policyForm.mask === "truncate") maskParam.start = Number(policyForm.maskStart) || 0;

    setPolicySaving(true);
    setPolicyFormError(null);
    try {
      await api.post("/policies", {
        subjectType: policyForm.subjectType,
        subjectId: policyForm.subjectId,
        resourceType: policyForm.resourceType,
        resourceId,
        action: policyForm.action,
        mask: policyForm.mask,
        maskParam,
        rowFilter: policyForm.rowFilter.trim(),
        priority: Number(policyForm.priority) || 100,
        enabled: true,
        note: policyForm.note.trim(),
      });
      toast("策略已创建，下一次求值即时生效");
      setPolicyModal(false);
      await loadPolicies();
    } catch (e: unknown) {
      setPolicyFormError(errText(e, "创建策略失败"));
    } finally {
      setPolicySaving(false);
    }
  }

  async function togglePolicy(p: PolicyItem) {
    setBusyPolicyId(p.id);
    try {
      // 只提交 id + enabled：后端 upsert 对部分字段做局部更新，避免用列表里的旧快照覆盖 maskParam 等
      await api.post("/policies", { id: p.id, enabled: !p.enabled });
      toast(p.enabled ? "策略已停用" : "策略已启用");
      await loadPolicies();
    } catch (e: unknown) {
      toast(errText(e, "操作失败"), "error");
    } finally {
      setBusyPolicyId(null);
    }
  }

  async function deletePolicy(p: PolicyItem) {
    setBusyPolicyId(p.id);
    try {
      await api.del(`/policies/${p.id}`);
      toast("策略已删除");
      await loadPolicies();
    } catch (e: unknown) {
      toast(errText(e, "删除失败"), "error");
    } finally {
      setBusyPolicyId(null);
    }
  }

  /* ---------------- 生效矩阵 ---------------- */

  const loadEffective = useCallback(async (userId: string) => {
    if (!userId) return;
    setEffLoading(true);
    try {
      const res = await api.get<EffectiveMatrix>("/policies/effective", { userId });
      setEffData(res);
      setEffError(null);
    } catch (e: unknown) {
      setEffError(errText(e, "生效矩阵加载失败"));
      setEffData(null);
    } finally {
      setEffLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "effective" && effUserId) void loadEffective(effUserId);
  }, [tab, effUserId, loadEffective]);

  /* ---------------- SQL 预览 ---------------- */

  async function runPreview() {
    if (!sqlText.trim()) {
      setPreviewError("请输入要预览的 SQL");
      return;
    }
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const res = await api.post<PreviewResult>("/policies/preview", {
        datasourceId: dsId || sources[0]?.id || undefined,
        sql: sqlText.trim(),
        userId: previewUserId || undefined,
      });
      setPreviewResult(res);
    } catch (e: unknown) {
      setPreviewResult(null);
      setPreviewError(errText(e, "SQL 预览失败"));
    } finally {
      setPreviewLoading(false);
    }
  }

  /* ---------------- 派生数据 ---------------- */

  const activeSource = useMemo(() => sources.find((s) => s.id === dsId), [sources, dsId]);
  const userById = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);
  const previewColumns = useMemo(() => {
    if (previewResult?.columns?.length) return previewResult.columns;
    const first = previewResult?.rows?.[0];
    return first ? Object.keys(first) : [];
  }, [previewResult]);
  const maskedSet = useMemo(() => new Set(previewResult?.maskedColumns ?? []), [previewResult]);

  const tabItems = [
    { key: "sources", label: "数据源与元数据", count: sources.length || undefined },
    { key: "policies", label: "访问策略", count: policies.length || undefined },
    { key: "effective", label: "生效矩阵" },
    { key: "preview", label: "SQL 改写预览" },
    { key: "classify", label: "分级统计" },
  ];

  return (
    <div className="h-full overflow-y-auto bg-surface-100">
      <div className="mx-auto max-w-[1440px] space-y-5 px-6 py-5">
        <PageHeader
          title="数据安全可控 · 统一数据应用权限管控"
          desc="数据源 → 表 → 字段 → 行级四级策略，配合 4 种脱敏与 SQL AST 改写。管理员在这里解释「为什么他看不到」，也在这里证明「越权一定被拦」。"
          badge={
            <Badge tone="brand" dot>
              管理员视角
            </Badge>
          }
          meta={
            <>
              <span className="inline-flex items-center gap-1">
                <Database size={11} /> {formatNumber(sources.length)} 个数据源
              </span>
              <span className="inline-flex items-center gap-1">
                <ListChecks size={11} /> {formatNumber(policies.length)} 条策略
              </span>
              <span className="inline-flex items-center gap-1">
                <ShieldCheck size={11} /> Agent 权限严格继承自绑定用户
              </span>
            </>
          }
          actions={
            <>
              <Button
                variant="outline"
                icon={<RefreshCw size={14} />}
                onClick={() => {
                  void loadSources();
                  if (tab === "policies") void loadPolicies();
                  if (tab === "classify") void loadClassify();
                  if (tab === "effective" && effUserId) void loadEffective(effUserId);
                }}
              >
                刷新
              </Button>
              <Button icon={<Plus size={14} />} onClick={() => setSourceModal(true)}>
                新增数据源
              </Button>
            </>
          }
        />

        <div className="flex items-center gap-2 rounded-xl border border-brand-100 bg-brand-50/50 px-3.5 py-2.5 text-[11.5px] leading-relaxed text-ink-600">
          <Lock size={13} className="shrink-0 text-brand-600" />
          默认拒绝：没有任何 allow 策略的表对用户不可见；列默认可见（除非被 deny）；行级过滤以 AND 合并；top_secret 列在无显式 allow 时按脱敏处理。
        </div>

        <Tabs items={tabItems} value={tab} onChange={setTab} />

        {/* ============================ Tab 1 数据源与元数据 ============================ */}
        {tab === "sources" && (
          <div className="space-y-3">
            {sourcesLoading && (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-[132px]" />
                ))}
              </div>
            )}

            {!sourcesLoading && sourcesError && (
              <Card>
                <Empty
                  icon={<ShieldAlert size={20} />}
                  title="数据源加载失败"
                  desc={`${sourcesError}。后端 /api/datasources 可能尚未就绪。`}
                  action={
                    <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadSources()}>
                      重新加载
                    </Button>
                  }
                />
              </Card>
            )}

            {!sourcesLoading && !sourcesError && sources.length === 0 && (
              <Card>
                <Empty
                  icon={<Database size={20} />}
                  title="还没有数据源"
                  desc="先接入一个数据源（V1 内置 demo SQLite 可直接测试），之后才能配置表 / 字段 / 行级策略。"
                  action={
                    <Button icon={<Plus size={14} />} onClick={() => setSourceModal(true)}>
                      新增数据源
                    </Button>
                  }
                />
              </Card>
            )}

            {!sourcesLoading && !sourcesError && sources.length > 0 && (
              <>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {sources.map((ds) => (
                    <div
                      key={ds.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setDsId(ds.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") setDsId(ds.id);
                      }}
                      className={cx(
                        "card cursor-pointer p-4 text-left transition",
                        dsId === ds.id ? "border-brand-300 ring-2 ring-brand-500/15" : "card-hover"
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand-50 text-brand-600">
                            <Database size={16} />
                          </div>
                          <div className="min-w-0">
                            <div className="truncate text-[13.5px] font-semibold text-ink-900">{ds.name}</div>
                            <div className="mt-0.5 flex items-center gap-1.5">
                              <Badge tone="gray">{String(ds.type || "").toUpperCase()}</Badge>
                              <Badge tone={ds.status === "error" ? "rose" : "green"} dot>
                                {ds.status === "error" ? "连接异常" : "已连接"}
                              </Badge>
                            </div>
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<RefreshCw size={12} />}
                          loading={testingId === ds.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            void testConnection(ds);
                          }}
                        >
                          测试连接
                        </Button>
                      </div>
                      <div className="mt-3 flex items-center gap-4 text-[11.5px] text-ink-500">
                        <span className="inline-flex items-center gap-1">
                          <Table2 size={12} /> {formatNumber(ds.tableCount ?? 0)} 表
                        </span>
                        <span>{formatNumber(ds.rowCount ?? 0)} 行</span>
                        {ds.database && <span className="truncate text-ink-400">{ds.database}</span>}
                      </div>
                      {ds.description && <p className="mt-2 line-clamp-2 text-[11.5px] leading-relaxed text-ink-500">{ds.description}</p>}
                    </div>
                  ))}
                </div>

                <Card>
                  <CardHeader
                    title="表与字段元数据"
                    desc={activeSource ? `${activeSource.name} · 点击表名展开字段与敏感级别` : "点击表名展开字段"}
                    extra={
                      <div className="flex items-center gap-1.5">
                        <Badge tone="gray">{formatNumber(tables.length)} 张可见表</Badge>
                        {hiddenTables > 0 && <Badge tone="amber">{formatNumber(hiddenTables)} 张不可见</Badge>}
                      </div>
                    }
                  />
                  {!tablesLoading && !tablesError && hiddenTables > 0 && (
                    <div className="mx-4 mb-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2 text-[11.5px] leading-relaxed text-amber-800">
                      <ShieldAlert size={13} className="mt-0.5 shrink-0" />
                      <span>
                        该数据源共 {formatNumber(tables.length + hiddenTables)} 张表，其中 <b>{formatNumber(hiddenTables)}</b> 张因「默认拒绝」对当前账号不可见。
                        想看某个人能看到什么，请到「生效矩阵」选人查看；想让当前管理员也能看到全部元数据，可给自己的角色补一条数据源级 allow 策略。
                      </span>
                    </div>
                  )}
                  {tablesLoading && (
                    <div className="space-y-2 px-4 pb-4">
                      {Array.from({ length: 4 }).map((_, i) => (
                        <Skeleton key={i} className="h-11" />
                      ))}
                    </div>
                  )}
                  {!tablesLoading && tablesError && (
                    <Empty
                      icon={<ShieldAlert size={20} />}
                      title="表元数据加载失败"
                      desc={tablesError}
                      action={
                        <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadTables(dsId)}>
                          重新加载
                        </Button>
                      }
                    />
                  )}
                  {!tablesLoading && !tablesError && tables.length === 0 && (
                    <Empty
                      title="该数据源没有可见的表"
                      desc={
                        hiddenTables > 0
                          ? `有 ${formatNumber(hiddenTables)} 张表存在，但当前账号没有表级授权（默认拒绝）。到「生效矩阵」按用户查看权限明细。`
                          : "元数据可能尚未采集，或当前账号没有任何表级授权。"
                      }
                      action={
                        <Button variant="outline" onClick={() => setTab("effective")}>
                          去生效矩阵查看
                        </Button>
                      }
                    />
                  )}
                  {!tablesLoading && !tablesError && tables.length > 0 && (
                    <div className="overflow-x-auto">
                      <table className="table-base">
                        <thead>
                          <tr>
                            <th>表名</th>
                            <th>注释</th>
                            <th className="w-[90px]">行数</th>
                            <th className="w-[150px]">字段（可见 / 脱敏 / 拒绝）</th>
                            <th className="w-[110px]">字段</th>
                          </tr>
                        </thead>
                        <tbody>
                          {tables.map((t) => {
                            const open = openTable === t.name;
                            const cols = columnsByTable[t.name];
                            const err = columnsError[t.name];
                            return (
                              <Fragment key={t.name}>
                                <tr className="cursor-pointer" onClick={() => void toggleTable(t.name)}>
                                  <td>
                                    <div className="flex items-center gap-1.5">
                                      {open ? <ChevronDown size={13} className="text-ink-400" /> : <ChevronRight size={13} className="text-ink-400" />}
                                      <span className="font-mono text-[12.5px] font-medium text-ink-900">{t.name}</span>
                                    </div>
                                  </td>
                                  <td className="max-w-[240px] truncate text-[12.5px] text-ink-600">{t.comment || "—"}</td>
                                  <td className="text-[12.5px] text-ink-600">{formatNumber(t.rowCount ?? 0)}</td>
                                  <td>
                                    <div className="flex items-center gap-1">
                                      <Badge tone="green">{formatNumber(t.visibleColumnCount ?? t.columnCount ?? 0)} 可见</Badge>
                                      {(t.maskedColumnCount ?? 0) > 0 && <Badge tone="amber">{formatNumber(t.maskedColumnCount)} 脱敏</Badge>}
                                      {(t.deniedColumnCount ?? 0) > 0 && <Badge tone="gray">{formatNumber(t.deniedColumnCount)} 拒绝</Badge>}
                                    </div>
                                    {(t.rowFilters ?? []).length > 0 && (
                                      <div className="mt-1 truncate font-mono text-[10.5px] text-brand-700">行过滤：{(t.rowFilters ?? []).join(" AND ")}</div>
                                    )}
                                  </td>
                                  <td className="text-[12px] text-brand-600">{open ? "收起" : "查看字段"}</td>
                                </tr>
                                {open && (
                                  <tr key={`${t.name}-cols`}>
                                    <td colSpan={5} className="!bg-surface-50/60 !py-0">
                                      <div className="px-4 py-3">
                                        {columnsLoading === t.name && <Skeleton className="h-24" />}
                                        {columnsLoading !== t.name && err && (
                                          <div className="flex items-start gap-2 py-2 text-[11.5px] leading-relaxed text-amber-700">
                                            <ShieldAlert size={13} className="mt-0.5 shrink-0" />
                                            {err}
                                          </div>
                                        )}
                                        {columnsLoading !== t.name && !err && (!cols || cols.length === 0) && (
                                          <div className="py-3 text-center text-[11.5px] text-ink-400">暂无字段元数据</div>
                                        )}
                                        {columnsLoading !== t.name && !err && cols && cols.length > 0 && (
                                          <table className="w-full text-[12px]">
                                            <thead>
                                              <tr className="text-[11px] text-ink-500">
                                                <th className="py-1.5 text-left font-medium">字段</th>
                                                <th className="py-1.5 text-left font-medium">类型</th>
                                                <th className="py-1.5 text-left font-medium">注释</th>
                                                <th className="py-1.5 text-left font-medium">敏感级别</th>
                                                <th className="py-1.5 text-left font-medium">当前账号</th>
                                              </tr>
                                            </thead>
                                            <tbody>
                                              {cols.map((c) => {
                                                const masked = !!c.mask && c.mask !== "none";
                                                return (
                                                  <tr key={c.name} className="border-t border-surface-200">
                                                    <td className="py-1.5 font-mono text-[11.5px] text-ink-900">{c.name}</td>
                                                    <td className="py-1.5 text-ink-500">{c.type}</td>
                                                    <td className="py-1.5 text-ink-600">{c.comment || "—"}</td>
                                                    <td className="py-1.5">
                                                      <LevelBadge level={c.sensitiveLevel} />
                                                    </td>
                                                    <td className="py-1.5">
                                                      {c.visible === false ? (
                                                        <Badge tone="gray">
                                                          <EyeOff size={10} /> 受限
                                                        </Badge>
                                                      ) : masked ? (
                                                        <Badge tone="amber">已脱敏 · {MASK_LABEL[c.mask ?? ""] ?? c.mask}</Badge>
                                                      ) : (
                                                        <span className="text-[11px] text-ink-400">正常可读</span>
                                                      )}
                                                    </td>
                                                  </tr>
                                                );
                                              })}
                                            </tbody>
                                          </table>
                                        )}
                                      </div>
                                    </td>
                                  </tr>
                                )}
                              </Fragment>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </Card>
              </>
            )}
          </div>
        )}

        {/* ============================ Tab 2 访问策略 ============================ */}
        {tab === "policies" && (
          <Card>
            <CardHeader
              title="访问策略"
              desc="主体可以是「用户」或「角色」；同一资源上用户策略优先于角色策略，priority 大者优先。"
              extra={
                <div className="flex items-center gap-2">
                  <Button variant="outline" size="sm" icon={<RefreshCw size={13} />} onClick={() => void loadPolicies()}>
                    刷新
                  </Button>
                  <Button size="sm" icon={<Plus size={13} />} onClick={openPolicyModal}>
                    新建策略
                  </Button>
                </div>
              }
            />

            {policiesLoading && (
              <div className="space-y-2 px-4 pb-4">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-11" />
                ))}
              </div>
            )}

            {!policiesLoading && policiesError && (
              <Empty
                icon={<ShieldAlert size={20} />}
                title="策略加载失败"
                desc={`${policiesError}。后端 /api/policies 可能尚未就绪。`}
                action={
                  <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadPolicies()}>
                    重新加载
                  </Button>
                }
              />
            )}

            {!policiesLoading && !policiesError && policies.length === 0 && (
              <Empty
                icon={<ListChecks size={20} />}
                title="还没有访问策略"
                desc="默认拒绝意味着「没策略 = 看不到」。给分析师配一条工时表 allow + salary 掩码，是最快见效的一步。"
                action={
                  <Button icon={<Plus size={14} />} onClick={openPolicyModal}>
                    新建策略
                  </Button>
                }
              />
            )}

            {!policiesLoading && !policiesError && policies.length > 0 && (
              <div className="overflow-x-auto">
                <table className="table-base">
                  <thead>
                    <tr>
                      <th>主体</th>
                      <th>资源类型</th>
                      <th>资源</th>
                      <th className="w-[80px]">动作</th>
                      <th>脱敏</th>
                      <th>行过滤</th>
                      <th className="w-[80px]">优先级</th>
                      <th className="w-[80px]">启用</th>
                      <th className="w-[72px]">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {policies.map((p) => {
                      const subjectUser = p.subjectType === "user" ? userById.get(p.subjectId) : undefined;
                      const subjectName =
                        p.subjectType === "user"
                          ? p.subjectName || subjectUser?.name || subjectUser?.username || p.subjectId
                          : ROLE_LABEL[p.subjectId] || (p.subjectName ? p.subjectName.replace(/^角色：/, "") : p.subjectId);
                      return (
                        <tr key={p.id}>
                          <td>
                            <div className="flex items-center gap-1.5">
                              <Badge tone={p.subjectType === "user" ? "brand" : "teal"}>{p.subjectType === "user" ? "用户" : "角色"}</Badge>
                              <span className="truncate text-[12.5px] font-medium text-ink-900">{subjectName}</span>
                            </div>
                          </td>
                          <td>
                            <Badge tone="gray">{RESOURCE_LABEL[p.resourceType] ?? p.resourceType}</Badge>
                          </td>
                          <td>
                            {p.table ? (
                              <div>
                                <span className="font-mono text-[12px] text-ink-800">
                                  {p.table}
                                  {p.column ? <span className="text-brand-700">.{p.column}</span> : null}
                                </span>
                                {p.tableComment && <div className="mt-0.5 max-w-[220px] truncate text-[11px] text-ink-400">{p.tableComment}</div>}
                              </div>
                            ) : (
                              <span className="font-mono text-[11.5px] text-ink-700">{p.resourceId}</span>
                            )}
                            {p.note && <div className="mt-0.5 max-w-[240px] truncate text-[11px] text-ink-400">{p.note}</div>}
                          </td>
                          <td>
                            <Badge tone={p.action === "deny" ? "rose" : "green"}>{ACTION_LABEL[p.action] ?? p.action}</Badge>
                          </td>
                          <td>
                            {p.mask && p.mask !== "none" ? (
                              <div className="flex flex-wrap items-center gap-1">
                                <Badge tone="amber">{MASK_LABEL[p.mask] ?? p.mask}</Badge>
                                <span className="text-[11px] text-ink-400">{maskParamText(p.mask, p.maskParam)}</span>
                              </div>
                            ) : (
                              <span className="text-[11.5px] text-ink-400">不脱敏</span>
                            )}
                          </td>
                          <td>
                            {p.rowFilter ? (
                              <Tip text={p.rowFilter}>
                                <span className="inline-block max-w-[180px] truncate rounded bg-surface-100 px-1.5 py-0.5 font-mono text-[11px] text-ink-700">
                                  {p.rowFilter}
                                </span>
                              </Tip>
                            ) : (
                              <span className="text-[11.5px] text-ink-400">—</span>
                            )}
                          </td>
                          <td className="text-[12.5px] text-ink-600">{p.priority}</td>
                          <td>
                            <Toggle checked={!!p.enabled} onChange={() => void togglePolicy(p)} disabled={busyPolicyId === p.id} />
                          </td>
                          <td>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="!px-0 whitespace-nowrap text-rose-600"
                              loading={busyPolicyId === p.id}
                              onClick={() => void deletePolicy(p)}
                            >
                              删除
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {/* ============================ Tab 3 生效矩阵 ============================ */}
        {tab === "effective" && (
          <div className="space-y-3">
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12.5px] font-medium text-ink-700">查看用户</span>
                  <Select value={effUserId} onChange={(e) => setEffUserId(e.target.value)} className="w-[260px]">
                    <option value="">选择用户…</option>
                    <optgroup label="按用户">
                      {users
                        .filter((u) => u.role === "member")
                        .map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.name || u.username}（{u.username}）
                          </option>
                        ))}
                    </optgroup>
                    <optgroup label="按角色（取该角色首位用户为代表）">
                      {(["platform_admin", "dept_admin", "member"] as const).map((role) => {
                        const rep = users.find((u) => u.role === role);
                        if (!rep) return null;
                        return (
                          <option key={`role-${role}`} value={rep.id}>
                            角色：{ROLE_LABEL[role]}（代表 {rep.name || rep.username}）
                          </option>
                        );
                      })}
                    </optgroup>
                    <optgroup label="全部账号">
                      {users
                        .filter((u) => u.role !== "member")
                        .map((u) => (
                          <option key={`all-${u.id}`} value={u.id}>
                            {u.name || u.username}（{ROLE_LABEL[u.role] ?? u.role}）
                          </option>
                        ))}
                    </optgroup>
                  </Select>
                  {effData?.datasourceName && <Badge tone="gray">数据源：{effData.datasourceName}</Badge>}
                </div>
                <Button variant="outline" size="sm" icon={<RefreshCw size={13} />} onClick={() => void loadEffective(effUserId)} disabled={!effUserId}>
                  重新求值
                </Button>
              </div>
              <div className="mx-4 mb-3 flex items-start gap-2 rounded-xl border border-brand-100 bg-brand-50/50 px-3 py-2 text-[11.5px] leading-relaxed text-ink-600">
                <ShieldCheck size={13} className="mt-0.5 shrink-0 text-brand-600" />
                <span>
                  Agent 权限严格继承自绑定用户：员工本身不带权限，只带技能；工具调用一律以会话发起人身份求值。
                  {effData?.dataScopeSummary && (
                    <span className="mt-1 block rounded-lg bg-white/70 px-2 py-1 font-mono text-[10.5px] text-ink-500">
                      注入 System Prompt 的权限摘要：{effData.dataScopeSummary}
                    </span>
                  )}
                </span>
              </div>
            </Card>

            {!effUserId && (
              <Card>
                <Empty icon={<ShieldCheck size={20} />} title="选择一个用户" desc="选人后即可看到「这个账号能看到什么表、哪些列被脱敏、命中哪些行过滤」。" />
              </Card>
            )}

            {effUserId && effLoading && (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-28" />
                ))}
              </div>
            )}

            {effUserId && !effLoading && effError && (
              <Card>
                <Empty
                  icon={<ShieldAlert size={20} />}
                  title="生效矩阵加载失败"
                  desc={`${effError}。后端 /api/policies/effective 可能尚未就绪。`}
                  action={
                    <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadEffective(effUserId)}>
                      重新加载
                    </Button>
                  }
                />
              </Card>
            )}

            {effUserId && !effLoading && !effError && effData && (
              <>
                <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
                  {[
                    { label: "可见表", value: effData.summary?.tablesVisible ?? 0, tone: "text-emerald-600" },
                    { label: "不可见表", value: effData.summary?.tablesDenied ?? 0, tone: "text-rose-600" },
                    { label: "脱敏列", value: effData.summary?.columnsMasked ?? 0, tone: "text-amber-600" },
                    { label: "拒绝列", value: effData.summary?.columnsDenied ?? 0, tone: "text-ink-500" },
                    { label: "行过滤表", value: effData.summary?.rowFiltered ?? 0, tone: "text-brand-600" },
                  ].map((s) => (
                    <Card key={s.label} className="px-3 py-2.5">
                      <div className="text-[11px] text-ink-500">{s.label}</div>
                      <div className={cx("mt-1 text-[20px] font-semibold leading-none", s.tone)}>{formatNumber(s.value)}</div>
                    </Card>
                  ))}
                </div>

                {(effData.tables ?? []).length === 0 && (
                  <Card>
                    <Empty title="该用户在当前数据源上没有任何可见表" desc="默认拒绝生效：需要为他或他的角色配置 allow 策略。" />
                  </Card>
                )}

                <div className="grid gap-3 xl:grid-cols-2">
                  {(effData.tables ?? []).map((t) => {
                    const cols = t.columns ?? [];
                    const denied = t.deniedColumns ?? [];
                    return (
                      <Card key={t.table} className={cx("p-4", !t.allowed && "opacity-90")}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <Table2 size={14} className="text-ink-400" />
                            <span className="font-mono text-[13px] font-semibold text-ink-900">{t.table}</span>
                            {t.allowed ? <Badge tone="green">可访问</Badge> : <Badge tone="rose">不可见</Badge>}
                          </div>
                          <span className="text-[11.5px] text-ink-400">{formatNumber(t.rowCount ?? 0)} 行</span>
                        </div>
                        {t.comment && <div className="mt-1 text-[11.5px] text-ink-500">{t.comment}</div>}
                        {t.deniedReason && <div className="mt-1.5 text-[11.5px] text-rose-600">拒绝原因：{t.deniedReason}</div>}

                        <div className="mt-2.5 flex flex-wrap gap-1.5">
                          {(t.rowFilters ?? []).map((f, i) => (
                            <span key={i} className="rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-[10.5px] text-brand-700">
                              行过滤：{f}
                            </span>
                          ))}
                          {!(t.rowFilters ?? []).length && <span className="text-[11px] text-ink-400">无行级过滤</span>}
                        </div>

                        <div className="mt-2.5 space-y-1">
                          {cols.map((c) => {
                            const masked = c.masked ?? (!!c.mask && c.mask !== "none");
                            return (
                              <div key={c.column} className="flex items-center gap-2 rounded-lg px-1 py-0.5 text-[11.5px]">
                                <span
                                  className={cx(
                                    "h-1.5 w-1.5 shrink-0 rounded-full",
                                    masked ? "bg-amber-500" : (c.visible ?? c.action !== "deny") ? "bg-emerald-500" : "bg-surface-300"
                                  )}
                                />
                                <span className="font-mono text-ink-800">{c.column}</span>
                                <LevelBadge level={c.sensitiveLevel} />
                                {masked ? (
                                  <span className="text-amber-700">
                                    已脱敏 · {MASK_LABEL[c.mask ?? ""] ?? c.mask}
                                    {maskParamText(c.mask, c.maskParam) ? `（${maskParamText(c.mask, c.maskParam)}）` : ""}
                                  </span>
                                ) : (
                                  <span className="text-ink-400">可读</span>
                                )}
                              </div>
                            );
                          })}
                          {denied.map((c) => (
                            <div key={c.column} className="flex items-center gap-2 rounded-lg px-1 py-0.5 text-[11.5px] text-ink-400">
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-surface-300" />
                              <span className="font-mono line-through">{c.column}</span>
                              <LevelBadge level={c.sensitiveLevel} />
                              <span>不可读</span>
                            </div>
                          ))}
                          {cols.length === 0 && denied.length === 0 && <div className="text-[11px] text-ink-400">没有字段元数据</div>}
                        </div>

                        {(t.rules ?? []).length > 0 && (
                          <details className="mt-2.5 rounded-lg bg-surface-50 px-2.5 py-1.5">
                            <summary className="cursor-pointer text-[11.5px] font-medium text-ink-600">解释：命中了 {(t.rules ?? []).length} 条策略</summary>
                            <div className="mt-1.5 space-y-1">
                              {(t.rules ?? []).map((r, i) => (
                                <div key={i} className="text-[11px] leading-relaxed text-ink-600">
                                  <span className="font-mono text-ink-800">{r.policyId ?? "—"}</span>
                                  <span className="mx-1 text-ink-400">·</span>
                                  {r.subjectType === "role" ? "角色" : "用户"} {r.subjectId}
                                  <span className="mx-1 text-ink-400">·</span>
                                  {RESOURCE_LABEL[r.resourceType ?? ""] ?? r.resourceType} {r.resourceId}
                                  <span className="mx-1 text-ink-400">·</span>
                                  {ACTION_LABEL[r.action ?? ""] ?? r.action}
                                  {r.mask && r.mask !== "none" ? ` / ${MASK_LABEL[r.mask] ?? r.mask}` : ""}
                                  {r.priority !== undefined ? ` · 优先级 ${r.priority}` : ""}
                                  {r.reason ? <span className="ml-1 text-ink-400">（{r.reason}）</span> : null}
                                </div>
                              ))}
                            </div>
                          </details>
                        )}
                      </Card>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        )}

        {/* ============================ Tab 4 SQL 改写预览 ============================ */}
        {tab === "preview" && (
          <div className="space-y-3">
            <Card>
              <CardHeader
                title="SQL 改写预览"
                desc="以所选用户身份跑一次真实改写：表级拒绝、列级剔除、行级注入、脱敏后处理，全链路可解释。"
                extra={
                  <Select value={previewUserId} onChange={(e) => setPreviewUserId(e.target.value)} className="w-[260px]">
                    <option value="">以当前账号身份</option>
                    <optgroup label="按用户">
                      {users
                        .filter((u) => u.role === "member")
                        .map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.name || u.username}（{u.username}）
                          </option>
                        ))}
                    </optgroup>
                    <optgroup label="按角色（取该角色首位用户为代表）">
                      {(["platform_admin", "dept_admin", "member"] as const).map((role) => {
                        const rep = users.find((u) => u.role === role);
                        if (!rep) return null;
                        return (
                          <option key={`role-${role}`} value={rep.id}>
                            角色：{ROLE_LABEL[role]}（代表 {rep.name || rep.username}）
                          </option>
                        );
                      })}
                    </optgroup>
                    <optgroup label="全部账号">
                      {users
                        .filter((u) => u.role !== "member")
                        .map((u) => (
                          <option key={`all-${u.id}`} value={u.id}>
                            {u.name || u.username}（{ROLE_LABEL[u.role] ?? u.role}）
                          </option>
                        ))}
                    </optgroup>
                  </Select>
                }
              />
              <div className="px-4 text-[10.5px] leading-relaxed text-ink-400">
                提示：角色选项代表该角色的首位用户（后端 /policies/preview 以 userId 求值）。切到「数据分析师」再执行，可看到
                <span className="mx-0.5 font-mono text-brand-600">SELECT *</span> 被展开为授权列、salary 脱敏、employee_name 哈希。
              </div>
              <div className="space-y-2.5 px-4 pb-4">
                <Textarea
                  value={sqlText}
                  onChange={(e) => setSqlText(e.target.value)}
                  rows={4}
                  className="font-mono !text-[12px]"
                  placeholder="select * from worktime_fact limit 5"
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-400">
                    <Wand2 size={12} /> 只允许单条 SELECT；强制 LIMIT；未授权表直接拒绝而不是返回空结果。
                  </div>
                  <Button icon={<Play size={13} />} loading={previewLoading} onClick={() => void runPreview()}>
                    执行预览
                  </Button>
                </div>
              </div>
            </Card>

            {previewError && (
              <Card className="border-rose-200 bg-rose-50/50">
                <div className="flex items-start gap-2 px-4 py-3">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0 text-rose-600" />
                  <div className="text-[12.5px] leading-relaxed text-rose-700">{previewError}</div>
                </div>
              </Card>
            )}

            {!previewError && !previewResult && (
              <Card>
                <Empty
                  icon={<Wand2 size={20} />}
                  title="还没有执行预览"
                  desc="点「执行预览」看改写前后的 SQL、命中的规则与脱敏后的结果。试试把表名换成 contract_sample，或用无法访问的表名看拒绝原因。"
                />
              </Card>
            )}

            {previewResult && (
              <>
                {previewResult.ok === false || previewResult.deniedReason ? (
                  <Card className="border-rose-200">
                    <div className="flex items-start gap-2.5 px-4 py-3.5">
                      <ShieldAlert size={18} className="mt-0.5 shrink-0 text-rose-600" />
                      <div className="min-w-0">
                        <div className="text-[13px] font-semibold text-rose-700">SQL 网关拒绝了这条查询</div>
                        <div className="mt-1 break-words text-[12.5px] leading-relaxed text-rose-700">
                          {previewResult.deniedReason || previewResult.error || "未授权访问"}
                        </div>
                        {(previewResult.appliedRules ?? []).length > 0 && (
                          <div className="mt-2 space-y-1">
                            {(previewResult.appliedRules ?? []).map((r, i) => (
                              <div key={i} className="text-[11.5px] text-rose-600">
                                · {r.detail ?? r.type ?? "规则"}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </Card>
                ) : (
                  <>
                    <div className="grid gap-3 xl:grid-cols-2">
                      <Card className="p-4">
                        <div className="mb-2 flex items-center justify-between">
                          <span className="text-[12.5px] font-semibold text-ink-900">原始 SQL</span>
                          <Badge tone="gray">用户输入</Badge>
                        </div>
                        <SqlBlock sql={previewResult.originalSql ?? sqlText} tone="light" />
                      </Card>
                      <Card className="p-4">
                        <div className="mb-2 flex items-center justify-between">
                          <span className="text-[12.5px] font-semibold text-ink-900">改写后 SQL</span>
                          <Badge tone="brand">网关输出</Badge>
                        </div>
                        <SqlBlock sql={previewResult.rewrittenSql} />
                      </Card>
                    </div>

                    <div className="grid gap-3 xl:grid-cols-3">
                      <Card className="xl:col-span-2">
                        <CardHeader
                          title="结果预览"
                          desc={`前 ${Math.min(20, previewResult.rows?.length ?? 0)} 行 · 脱敏列显示为 ****`}
                          extra={
                            <div className="flex items-center gap-1.5 text-[11px] text-ink-500">
                              <Badge tone="gray">{formatNumber(previewResult.rowCount ?? previewResult.rows?.length ?? 0)} 行</Badge>
                              <Badge tone="gray">{formatNumber(previewResult.durationMs ?? 0)} ms</Badge>
                              {previewResult.limit ? <Badge tone="gray">LIMIT {previewResult.limit}</Badge> : null}
                            </div>
                          }
                        />
                        <div className="overflow-x-auto px-1 pb-3">
                          {!previewResult.rows?.length ? (
                            <Empty title="查询成功但无数据" desc="改写与执行都通过了，只是结果集为空。" />
                          ) : (
                            <table className="table-base">
                              <thead>
                                <tr>
                                  {previewColumns.map((c) => (
                                    <th key={c}>
                                      <span className="font-mono">{c}</span>
                                      {maskedSet.has(c) && (
                                        <span className="ml-1 rounded bg-amber-50 px-1 py-0.5 text-[10px] font-medium text-amber-700">已脱敏</span>
                                      )}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {(previewResult.rows ?? []).slice(0, 20).map((row, i) => (
                                  <tr key={i}>
                                    {previewColumns.map((c) => {
                                      const v = row[c];
                                      const masked = maskedSet.has(c);
                                      const text = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
                                      return (
                                        <td key={c} className="whitespace-nowrap">
                                          {masked ? (
                                            <span className="font-mono text-[12px] text-amber-700" title={text || "已脱敏"}>
                                              ****
                                            </span>
                                          ) : text === "" ? (
                                            <span className="text-ink-300">NULL</span>
                                          ) : (
                                            <span className="text-[12px] text-ink-700">{text}</span>
                                          )}
                                        </td>
                                      );
                                    })}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </div>
                      </Card>

                      <Card>
                        <CardHeader title="应用规则" desc="每条都可在审计里追溯" extra={<Badge tone="brand">{(previewResult.appliedRules ?? []).length} 条</Badge>} />
                        <div className="space-y-1.5 px-4 pb-4">
                          {(previewResult.appliedRules ?? []).length === 0 && (
                            <div className="text-[11.5px] text-ink-400">本次查询没有触发额外规则。</div>
                          )}
                          {(previewResult.appliedRules ?? []).map((r, i) => (
                            <div key={i} className="flex items-start gap-1.5 rounded-lg bg-surface-50 px-2 py-1.5">
                              <Badge tone="gray">{RULE_LABEL[r.type ?? ""] ?? r.type ?? "规则"}</Badge>
                              <span className="min-w-0 flex-1 text-[11.5px] leading-relaxed text-ink-600">{r.detail ?? "—"}</span>
                            </div>
                          ))}
                          {(previewResult.maskedColumns ?? []).length > 0 && (
                            <div className="mt-2 flex flex-wrap items-center gap-1">
                              <EyeOff size={12} className="text-amber-600" />
                              {(previewResult.maskedColumns ?? []).map((c) => (
                                <span key={c} className="rounded bg-amber-50 px-1.5 py-0.5 font-mono text-[10.5px] text-amber-700">
                                  {c}
                                </span>
                              ))}
                            </div>
                          )}
                          <details className="mt-2">
                            <summary className="cursor-pointer text-[11px] text-ink-500">查看网关原始响应</summary>
                            <div className="mt-1.5">
                              <JsonViewer data={{ ...previewResult, rows: undefined }} defaultDepth={1} />
                            </div>
                          </details>
                        </div>
                      </Card>
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        )}

        {/* ============================ Tab 5 分级统计 ============================ */}
        {tab === "classify" && (
          <div className="space-y-3">
            {classifyLoading && (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-20" />
                ))}
              </div>
            )}

            {!classifyLoading && classifyError && (
              <Card>
                <Empty
                  icon={<ShieldAlert size={20} />}
                  title="分级统计加载失败"
                  desc={`${classifyError}。后端 /api/classifications 可能尚未就绪。`}
                  action={
                    <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadClassify()}>
                      重新加载
                    </Button>
                  }
                />
              </Card>
            )}

            {!classifyLoading && !classifyError && classify && (
              <>
                <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                  {LEVEL_ORDER.map((lvl) => {
                    const item = classify.levels.find((l) => l.level === lvl);
                    const count = item?.count ?? 0;
                    const meta = LEVEL_META[lvl];
                    return (
                      <Card key={lvl} className="px-3.5 py-3">
                        <div className="flex items-center gap-1.5 text-[11.5px] text-ink-500">
                          <span className="h-2 w-2 rounded-full" style={{ background: meta.color }} />
                          {item?.label || meta.label}
                        </div>
                        <div className="mt-1.5 text-[22px] font-semibold leading-none text-ink-900">{formatNumber(count)}</div>
                        <div className="mt-1 text-[10.5px] text-ink-400">个字段</div>
                      </Card>
                    );
                  })}
                </div>

                {classify.tables.length === 0 && (
                  <Card>
                    <Empty title="暂无分级数据" desc="数据源的字段还没有标注敏感级别。" />
                  </Card>
                )}

                {classify.tables.length > 0 && (
                  <Card>
                    <CardHeader
                      title="每表敏感列分布"
                      desc="堆叠条按敏感级别着色；数字为列数。分级是脱敏兜底的依据：top_secret 列在无显式 allow 时按脱敏处理。"
                      extra={<Badge tone="gray">{formatNumber(classify.tables.length)} 张表</Badge>}
                    />
                    <div className="space-y-3 px-4 pb-4">
                      {classify.tables.map((t) => (
                        <div key={t.table}>
                          <div className="mb-1 flex flex-wrap items-center justify-between gap-1 text-[12px]">
                            <span className="font-mono text-ink-800">{t.table}</span>
                            <span className="text-[11px] text-ink-400">
                              {formatNumber(t.total)} 列 · 敏感 {formatNumber(t.columns.length)}
                            </span>
                          </div>
                          <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-200">
                            {LEVEL_ORDER.map((lvl) => {
                              const count = t.counts[lvl] ?? 0;
                              if (!count) return null;
                              const pct = t.total ? (count / t.total) * 100 : 0;
                              return (
                                <div
                                  key={lvl}
                                  title={`${LEVEL_META[lvl].label}：${count} 列`}
                                  style={{ width: `${pct}%`, background: LEVEL_META[lvl].color }}
                                  className="h-full"
                                />
                              );
                            })}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px] text-ink-500">
                            {LEVEL_ORDER.filter((lvl) => (t.counts[lvl] ?? 0) > 0).map((lvl) => (
                              <span key={lvl} className="inline-flex items-center gap-1">
                                <span className="h-1.5 w-1.5 rounded-full" style={{ background: LEVEL_META[lvl].color }} />
                                {LEVEL_META[lvl].label} {t.counts[lvl]}
                              </span>
                            ))}
                            {t.columns.map((c) => (
                              <span
                                key={`${t.table}-${c.name}`}
                                title={`${c.name}（${LEVEL_META[c.level]?.label ?? c.level}）${c.comment ? ` · ${c.comment}` : ""}`}
                                className="rounded border border-surface-300 bg-surface-50 px-1.5 py-0.5 font-mono text-[10px] text-ink-600"
                                style={{ borderColor: `${LEVEL_META[c.level]?.color ?? "#CBD5E1"}55` }}
                              >
                                {c.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </Card>
                )}

                {classify.tags.length > 0 && (
                  <Card>
                    <CardHeader
                      title="敏感字段标签云"
                      desc="按敏感级别着色的字段名，用于快速定位「哪些列需要脱敏 / 谁能看」。字号随出现频次放大。"
                      extra={<Badge tone="gray">{formatNumber(classify.tags.length)} 个字段</Badge>}
                    />
                    <div className="flex flex-wrap items-center gap-2 px-4 pb-4">
                      {classify.tags.map((tag) => {
                        const meta = LEVEL_META[tag.level] ?? LEVEL_META.secret;
                        return (
                          <span
                            key={`${tag.name}-${tag.level}`}
                            className="rounded-lg border px-2 py-1 font-mono text-[11px]"
                            style={{ borderColor: `${meta.color}66`, background: `${meta.color}12`, color: "#334155" }}
                          >
                            {tag.name}
                            <span className="ml-1 font-sans text-[9.5px]" style={{ color: meta.color }}>
                              {meta.label}
                            </span>
                          </span>
                        );
                      })}
                    </div>
                  </Card>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* ---------------- 新增数据源 ---------------- */}
      <Modal
        open={sourceModal}
        onClose={() => setSourceModal(false)}
        title="新增数据源"
        desc="V1 支持 sqlite / mysql / pg / hive / excel / bi；连接串只写库内，不回传前端。"
        width="max-w-xl"
        footer={
          <>
            <Button variant="outline" onClick={() => setSourceModal(false)}>
              取消
            </Button>
            <Button loading={sourceSaving} onClick={() => void submitSource()}>
              创建并测试
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="名称">
              <Input value={sourceForm.name} placeholder="如 工时数仓" onChange={(e) => setSourceForm((f) => ({ ...f, name: e.target.value }))} />
            </Field>
            <Field label="类型">
              <Select value={sourceForm.type} onChange={(e) => setSourceForm((f) => ({ ...f, type: e.target.value }))}>
                {["sqlite", "mysql", "pg", "hive", "excel", "bi"].map((t) => (
                  <option key={t} value={t}>
                    {t.toUpperCase()}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="主机">
              <Input value={sourceForm.host} placeholder="127.0.0.1" onChange={(e) => setSourceForm((f) => ({ ...f, host: e.target.value }))} />
            </Field>
            <Field label="端口">
              <Input value={sourceForm.port} placeholder="3306" onChange={(e) => setSourceForm((f) => ({ ...f, port: e.target.value }))} />
            </Field>
            <Field label="库名 / 路径">
              <Input value={sourceForm.database} placeholder="dataclaw" onChange={(e) => setSourceForm((f) => ({ ...f, database: e.target.value }))} />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="账号">
              <Input value={sourceForm.username} onChange={(e) => setSourceForm((f) => ({ ...f, username: e.target.value }))} />
            </Field>
            <Field label="口令" hint="仅用于连接，接口不返回明文">
              <Input type="password" value={sourceForm.password} onChange={(e) => setSourceForm((f) => ({ ...f, password: e.target.value }))} />
            </Field>
          </div>
          <Field label="描述">
            <Textarea rows={2} value={sourceForm.description} onChange={(e) => setSourceForm((f) => ({ ...f, description: e.target.value }))} />
          </Field>
          {sourceFormError && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
              <ShieldAlert size={13} className="mt-0.5 shrink-0" />
              {sourceFormError}
            </div>
          )}
        </div>
      </Modal>

      {/* ---------------- 新建策略 ---------------- */}
      <Modal
        open={policyModal}
        onClose={() => setPolicyModal(false)}
        title="新建访问策略"
        desc="主体 × 资源 × 动作 × 脱敏 × 行过滤，是数据权限的最小单元。"
        width="max-w-2xl"
        footer={
          <>
            <span className="mr-auto font-mono text-[11px] text-ink-400">{buildResourceId(policyForm) || "resource_id 待填写"}</span>
            <Button variant="outline" onClick={() => setPolicyModal(false)}>
              取消
            </Button>
            <Button loading={policySaving} onClick={() => void submitPolicy()}>
              创建策略
            </Button>
          </>
        }
      >
        <div className="space-y-3.5">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="主体类型">
              <Select
                value={policyForm.subjectType}
                onChange={(e) => setPolicyForm((f) => ({ ...f, subjectType: e.target.value as "user" | "role", subjectId: "" }))}
              >
                <option value="user">用户</option>
                <option value="role">角色</option>
              </Select>
            </Field>
            <Field label="主体">
              <Select value={policyForm.subjectId} onChange={(e) => setPolicyForm((f) => ({ ...f, subjectId: e.target.value }))}>
                <option value="">选择主体…</option>
                {policyForm.subjectType === "user"
                  ? users.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name || u.username}（{u.username}）
                      </option>
                    ))
                  : Object.entries(ROLE_LABEL).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
              </Select>
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="资源类型">
              <Select
                value={policyForm.resourceType}
                onChange={(e) => setPolicyForm((f) => ({ ...f, resourceType: e.target.value as ResourceType, column: "" }))}
              >
                <option value="datasource">数据源</option>
                <option value="table">表</option>
                <option value="column">字段</option>
                <option value="row">行级过滤</option>
                <option value="metric">指标</option>
              </Select>
            </Field>
            {policyForm.resourceType !== "metric" && (
              <Field label="数据源">
                <Select
                  value={policyForm.datasourceId}
                  onChange={(e) => setPolicyForm((f) => ({ ...f, datasourceId: e.target.value, table: "", column: "" }))}
                >
                  <option value="">选择数据源…</option>
                  {sources.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            {policyForm.resourceType === "metric" && (
              <Field label="指标编码" hint="如 avg_worktime / contract_risk_count">
                <Input value={policyForm.metric} onChange={(e) => setPolicyForm((f) => ({ ...f, metric: e.target.value }))} />
              </Field>
            )}
            {["table", "column", "row"].includes(policyForm.resourceType) && (
              <Field label="表">
                <Select
                  value={policyForm.table}
                  onChange={(e) => {
                    const name = e.target.value;
                    setPolicyForm((f) => ({ ...f, table: name, column: "" }));
                    void ensureColumns(name);
                  }}
                >
                  <option value="">选择表…</option>
                  {tables.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
          </div>

          {policyForm.resourceType === "column" && (
            <Field label="字段">
              <Select value={policyForm.column} onChange={(e) => setPolicyForm((f) => ({ ...f, column: e.target.value }))}>
                <option value="">选择字段…</option>
                {(columnsByTable[policyForm.table] ?? []).map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}（{LEVEL_META[c.sensitiveLevel]?.label ?? c.sensitiveLevel}）
                  </option>
                ))}
              </Select>
            </Field>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="动作">
              <Select value={policyForm.action} onChange={(e) => setPolicyForm((f) => ({ ...f, action: e.target.value as "allow" | "deny" }))}>
                <option value="allow">允许（allow）</option>
                <option value="deny">拒绝（deny）</option>
              </Select>
            </Field>
            <Field label="优先级" hint="数值大者优先；用户策略优先于角色策略">
              <Input value={policyForm.priority} onChange={(e) => setPolicyForm((f) => ({ ...f, priority: e.target.value }))} />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="脱敏方式">
              <Select value={policyForm.mask} onChange={(e) => setPolicyForm((f) => ({ ...f, mask: e.target.value as MaskType }))}>
                <option value="none">不脱敏</option>
                <option value="mask">掩码（保留首尾）</option>
                <option value="hash">哈希（sha256 前 12 位）</option>
                <option value="replace">常量替换</option>
                <option value="truncate">截断</option>
              </Select>
            </Field>
            <div className="grid content-end">
              {policyForm.mask === "mask" && (
                <Field label="保留位数 keep">
                  <Input value={policyForm.maskKeep} onChange={(e) => setPolicyForm((f) => ({ ...f, maskKeep: e.target.value }))} />
                </Field>
              )}
              {policyForm.mask === "replace" && (
                <Field label="替换为">
                  <Input value={policyForm.maskReplace} onChange={(e) => setPolicyForm((f) => ({ ...f, maskReplace: e.target.value }))} />
                </Field>
              )}
              {policyForm.mask === "truncate" && (
                <Field label="保留前 N 位">
                  <Input value={policyForm.maskStart} onChange={(e) => setPolicyForm((f) => ({ ...f, maskStart: e.target.value }))} />
                </Field>
              )}
              {(policyForm.mask === "none" || policyForm.mask === "hash") && (
                <div className="pb-1 text-[11px] text-ink-400">
                  {policyForm.mask === "hash" ? "输出 sha256 前 12 位，不可逆。" : "保持原值可读。"}
                </div>
              )}
            </div>
          </div>

          <Field label="行过滤 SQL 片段" hint="注入 WHERE 并与其他行过滤以 AND 合并，如 owner_id='u_sales'">
            <Input
              value={policyForm.rowFilter}
              placeholder="owner_id='u_sales'"
              className="font-mono !text-[12px]"
              onChange={(e) => setPolicyForm((f) => ({ ...f, rowFilter: e.target.value }))}
            />
          </Field>

          <Field label="备注">
            <Input value={policyForm.note} placeholder="如：分析师只能看自己区域的工时" onChange={(e) => setPolicyForm((f) => ({ ...f, note: e.target.value }))} />
          </Field>

          {policyFormError && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
              <ShieldAlert size={13} className="mt-0.5 shrink-0" />
              {policyFormError}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
