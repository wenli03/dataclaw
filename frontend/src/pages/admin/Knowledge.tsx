import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import {
  BookOpen,
  FileText,
  Image as ImageIcon,
  Mail,
  MessageSquare,
  RefreshCw,
  Search,
  ShieldAlert,
  Upload,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import type { KnowledgeDoc, Paginated, User } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Drawer,
  Empty,
  Field,
  Input,
  Modal,
  Select,
  Skeleton,
  Toggle,
  toast,
} from "@/components/ui";
import { PageHeader } from "@/components/admin/PageHeader";
import { fileSize, formatDateTime, formatNumber, timeAgo } from "@/lib/format";

/* ------------------------------------------------------------------ 类型 */

interface SearchHit {
  docId?: string;
  docName?: string;
  seq?: number;
  snippet?: string;
  score?: number;
  chunkId?: string;
}

interface SearchRule {
  detail?: string;
  rule?: string;
  type?: string;
}

interface SearchResponse {
  items?: SearchHit[];
  rules?: (string | SearchRule)[];
}

interface AclItem {
  subjectType: string;
  subjectId: string;
  subjectName?: string;
  canRead: boolean;
}

interface DocDetail extends KnowledgeDoc {
  chunks?: { seq: number; text: string }[];
  chunkTotal?: number;
  chars?: number;
  restricted?: boolean;
}

const DOC_TYPES: { value: string; label: string }[] = [
  { value: "doc", label: "文档" },
  { value: "wiki", label: "Wiki" },
  { value: "image", label: "图片" },
  { value: "email", label: "邮件" },
  { value: "chat", label: "聊天" },
];

const TYPE_ICON: Record<string, ReactNode> = {
  doc: <FileText size={15} />,
  wiki: <BookOpen size={15} />,
  image: <ImageIcon size={15} />,
  email: <Mail size={15} />,
  chat: <MessageSquare size={15} />,
  audio: <MessageSquare size={15} />,
};

const LEVEL_TONE: Record<string, "gray" | "blue" | "amber" | "rose"> = {
  public: "gray",
  internal: "blue",
  secret: "amber",
  top_secret: "rose",
};
const LEVEL_LABEL: Record<string, string> = { public: "公开", internal: "内部", secret: "机密", top_secret: "绝密" };
const ROLE_LABEL: Record<string, string> = { platform_admin: "平台管理员", dept_admin: "部门管理员", member: "普通成员" };

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/**
 * 片段高亮：后端 search 已把命中词包成 `<em>…</em>`，这里先解码→转义→再把 em 还原成 <mark>，
 * 保证既能复用后端高亮、又不会把用户内容当 HTML 执行。后端未标 em 时退回本地按关键词高亮。
 */
function highlight(text: string, query: string): string {
  if (!text) return "";
  const decoded = text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
  const escaped = escapeHtml(decoded);
  const openTag = '<mark class="rounded bg-amber-100 px-0.5 text-ink-900">';

  if (escaped.includes("&lt;em&gt;")) {
    return escaped.replace(/&lt;em&gt;/g, openTag).replace(/&lt;\/em&gt;/g, "</mark>");
  }

  const q = query.trim();
  if (!q) return escaped;
  const safe = escapeHtml(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (!safe) return escaped;
  try {
    return escaped.replace(new RegExp(`(${safe})`, "gi"), `${openTag}$1</mark>`);
  } catch {
    return escaped;
  }
}

/* ------------------------------------------------------------------ 页面 */

export default function Knowledge() {
  const fileRef = useRef<HTMLInputElement>(null);

  const [docs, setDocs] = useState<DocDetail[]>([]);
  const [total, setTotal] = useState(0);
  const [hiddenCount, setHiddenCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [kwInput, setKwInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [type, setType] = useState("");

  const [uploadType, setUploadType] = useState("");
  const [uploading, setUploading] = useState(false);

  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searchRules, setSearchRules] = useState<string[]>([]);

  const [activeDoc, setActiveDoc] = useState<DocDetail | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [acl, setAcl] = useState<AclItem[]>([]);
  const [aclLoading, setAclLoading] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [aclForm, setAclForm] = useState({ subjectType: "user", subjectId: "", canRead: true });
  const [aclSaving, setAclSaving] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<DocDetail | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setKeyword(kwInput.trim()), 300);
    return () => clearTimeout(t);
  }, [kwInput]);

  const loadDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Paginated<DocDetail> & { hiddenCount?: number }>("/knowledge/docs", { type, keyword });
      setDocs(res.items ?? []);
      setTotal(res.total ?? res.items?.length ?? 0);
      setHiddenCount(res.hiddenCount ?? 0);
      setError(null);
    } catch (e: unknown) {
      setError(errText(e, "文档列表加载失败"));
    } finally {
      setLoading(false);
    }
  }, [type, keyword]);

  useEffect(() => {
    void loadDocs();
  }, [loadDocs]);

  useEffect(() => {
    api
      .get<Paginated<User>>("/users", { size: 200 })
      .then((res) => setUsers(res.items ?? []))
      .catch(() => setUsers([]));
  }, []);

  async function onPickFiles(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    setUploading(true);
    let ok = 0;
    const failures: string[] = [];
    for (const file of files) {
      try {
        const fd = new FormData();
        fd.append("file", file);
        if (uploadType) fd.append("type", uploadType);
        await api.upload("/knowledge/docs", fd);
        ok += 1;
      } catch (err: unknown) {
        failures.push(`${file.name}：${errText(err, "上传失败")}`);
      }
    }
    setUploading(false);
    if (ok > 0) toast(`已上传 ${ok} 个文档，正在解析切片`);
    if (failures.length) toast(failures[0], "error");
    await loadDocs();
  }

  async function runSearch() {
    const q = query.trim();
    if (!q) {
      setSearchError("请输入检索问题");
      return;
    }
    setSearching(true);
    setSearchError(null);
    try {
      const res = await api.post<SearchResponse>("/knowledge/search", { query: q, topK: 8 });
      setHits(res.items ?? []);
      const rules = (res.rules ?? []).map((r) => (typeof r === "string" ? r : r.detail || r.rule || r.type || "")).filter(Boolean);
      setSearchRules(rules);
    } catch (e: unknown) {
      setHits(null);
      setSearchError(errText(e, "检索失败"));
    } finally {
      setSearching(false);
    }
  }

  const loadAcl = useCallback(async (docId: string) => {
    setAclLoading(true);
    try {
      const res = await api.get<Paginated<AclItem>>(`/knowledge/docs/${docId}/acl`);
      setAcl(res.items ?? []);
    } catch {
      setAcl([]);
    } finally {
      setAclLoading(false);
    }
  }, []);

  async function openDoc(doc: DocDetail) {
    setActiveDoc(doc);
    setDrawerOpen(true);
    setDetailLoading(true);
    setAcl([]);
    setAclForm({ subjectType: "user", subjectId: "", canRead: true });
    try {
      const res = await api.get<{ doc?: DocDetail } & DocDetail>(`/knowledge/docs/${doc.id}`);
      setActiveDoc(res.doc ?? res);
    } catch (e: unknown) {
      toast(errText(e, "文档详情加载失败"), "error");
    } finally {
      setDetailLoading(false);
    }
    void loadAcl(doc.id);
  }

  async function addAcl() {
    if (!activeDoc) return;
    if (!aclForm.subjectId) {
      toast("请选择授权对象", "error");
      return;
    }
    setAclSaving(true);
    try {
      await api.post(`/knowledge/docs/${activeDoc.id}/acl`, {
        subjectType: aclForm.subjectType,
        subjectId: aclForm.subjectId,
        canRead: aclForm.canRead,
      });
      toast("文档权限已更新");
      await loadAcl(activeDoc.id);
    } catch (e: unknown) {
      toast(errText(e, "保存权限失败"), "error");
    } finally {
      setAclSaving(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del(`/knowledge/docs/${deleteTarget.id}`);
      toast(`已删除 ${deleteTarget.name}`);
      setDeleteTarget(null);
      if (activeDoc?.id === deleteTarget.id) setDrawerOpen(false);
      await loadDocs();
    } catch (e: unknown) {
      toast(errText(e, "删除失败"), "error");
    } finally {
      setDeleting(false);
    }
  }

  const maxScore = useMemo(() => Math.max(0.0001, ...(hits ?? []).map((h) => h.score ?? 0)), [hits]);
  const userById = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);

  /** 上传人展示：优先 ownerName；后端只给 ownerId 时用用户表映射；再兜底显示 id 后 6 位。 */
  const ownerLabel = useCallback(
    (doc: DocDetail): string => {
      if (doc.ownerName) return doc.ownerName;
      const owner = doc.ownerId ? userById.get(doc.ownerId) : undefined;
      if (owner) return owner.name || owner.username;
      if (doc.ownerId) return `#${doc.ownerId.slice(-6)}`;
      return "系统";
    },
    [userById]
  );

  const sensitiveCount = useMemo(
    () => docs.filter((d) => d.sensitiveLevel && d.sensitiveLevel !== "public").length,
    [docs]
  );
  const hasFilter = Boolean(keyword || type);

  return (
    <div className="h-full overflow-y-auto bg-surface-100">
      <div className="mx-auto max-w-[1440px] space-y-5 px-6 py-5">
        <PageHeader
          title="知识中台 · 文档解析与检索"
          desc="非结构化知识在这里变成可检索的切片；检索结果按文档 ACL 过滤，数字员工能看到什么取决于绑定用户。"
          badge={
            <Badge tone="brand" dot>
              管理员视角
            </Badge>
          }
          meta={
            <>
              <span>{formatNumber(total)} 份文档</span>
              <span>{formatNumber(sensitiveCount)} 份含敏感级别</span>
              <span>支持 pdf / docx / md / txt / 图片 / 邮件</span>
            </>
          }
          actions={
            <>
              <Select value={uploadType} onChange={(e) => setUploadType(e.target.value)} className="w-[132px]">
                <option value="">自动识别类型</option>
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
              <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => void onPickFiles(e)} />
              <Button icon={<Upload size={14} />} loading={uploading} onClick={() => fileRef.current?.click()}>
                上传文档
              </Button>
            </>
          }
        />

        <div className="grid gap-3 xl:grid-cols-3">
          {/* ---------------- 文档列表 ---------------- */}
          <Card className="xl:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-200 px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="text-[14px] font-semibold text-ink-900">文档列表</span>
                <Badge tone="gray">{formatNumber(total)}</Badge>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                  <Input value={kwInput} onChange={(e) => setKwInput(e.target.value)} placeholder="搜索文档名" className="w-[200px] pl-8" />
                </div>
                <Select value={type} onChange={(e) => setType(e.target.value)} className="w-[120px]">
                  <option value="">全部类型</option>
                  {DOC_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </Select>
                <Button variant="ghost" size="sm" icon={<RefreshCw size={13} />} onClick={() => void loadDocs()}>
                  刷新
                </Button>
              </div>
            </div>

            {hiddenCount > 0 && (
              <div className="mx-4 mb-2 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2 text-[11.5px] leading-relaxed text-amber-800">
                <ShieldAlert size={13} className="mt-0.5 shrink-0" />
                另有 {formatNumber(hiddenCount)} 篇文档因文档 ACL 不可见（当前账号不在授权范围内）。
              </div>
            )}

            {loading && (
              <div className="space-y-2 p-4">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-12" />
                ))}
              </div>
            )}

            {!loading && error && (
              <Empty
                icon={<ShieldAlert size={20} />}
                title="文档列表加载失败"
                desc={`${error}。后端 /api/knowledge/docs 可能尚未就绪。`}
                action={
                  <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadDocs()}>
                    重新加载
                  </Button>
                }
              />
            )}

            {!loading && !error && docs.length === 0 && (
              <Empty
                icon={<BookOpen size={20} />}
                title={hasFilter ? "没有匹配的文档" : "知识库还是空的"}
                desc={
                  hasFilter
                    ? "换个关键词或清空筛选条件试试。"
                    : "上传合同范本、审查规则、拜访方法论，数字员工就能引用企业自己的知识回答问题。"
                }
                action={
                  hasFilter ? (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setKwInput("");
                        setType("");
                      }}
                    >
                      清空筛选
                    </Button>
                  ) : (
                    <Button icon={<Upload size={14} />} onClick={() => fileRef.current?.click()}>
                      上传文档
                    </Button>
                  )
                }
              />
            )}

            {!loading && !error && docs.length > 0 && (
              <div className="overflow-x-auto">
                <table className="table-base">
                  <thead>
                    <tr>
                      <th>文档</th>
                      <th className="w-[120px]">切片</th>
                      <th className="w-[90px]">敏感级别</th>
                      <th className="w-[90px]">状态</th>
                      <th className="w-[140px]">上传人 / 时间</th>
                      <th className="w-[70px]">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs.map((d) => (
                      <tr key={d.id} className="cursor-pointer" onClick={() => void openDoc(d)}>
                        <td>
                          <div className="flex items-center gap-2.5">
                            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600">
                              {TYPE_ICON[d.type] ?? <FileText size={15} />}
                            </span>
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="truncate text-[12.5px] font-medium text-ink-900">{d.name}</span>
                                {d.restricted && <Badge tone="amber">已限权</Badge>}
                              </div>
                              <div className="truncate text-[11px] text-ink-400">
                                {String(d.type || "").toUpperCase()} · {fileSize(d.size)}
                                {d.dept ? ` · ${d.dept}` : ""}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="text-[12.5px] text-ink-600">{formatNumber(d.chunkCount ?? d.chunks?.length ?? 0)}</td>
                        <td>
                          <Badge tone={LEVEL_TONE[d.sensitiveLevel || "internal"] ?? "gray"}>
                            {LEVEL_LABEL[d.sensitiveLevel || "internal"] ?? d.sensitiveLevel}
                          </Badge>
                        </td>
                        <td>
                          <Badge tone={d.status === "failed" ? "rose" : d.status === "ready" ? "green" : "amber"} dot>
                            {d.status === "ready" ? "就绪" : d.status === "failed" ? "处理失败" : "解析中"}
                          </Badge>
                        </td>
                        <td>
                          <div className="truncate text-[11.5px] text-ink-600">{ownerLabel(d)}</div>
                          <div className="text-[10.5px] text-ink-400">{d.createdAt ? timeAgo(d.createdAt) : "—"}</div>
                        </td>
                        <td>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="!px-0 whitespace-nowrap text-rose-600"
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteTarget(d);
                            }}
                          >
                            删除
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* ---------------- 检索试验台 ---------------- */}
          <Card className="self-start xl:sticky xl:top-4">
            <CardHeader title="检索试验台" desc="按当前账号权限检索，验证「命中什么、为什么命中」" />
            <div className="space-y-2.5 px-4 pb-4">
              <div className="flex items-center gap-2">
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void runSearch();
                  }}
                  placeholder="如：合同付款账期风险"
                  className="flex-1"
                />
                <Button size="sm" icon={<Search size={13} />} loading={searching} onClick={() => void runSearch()}>
                  检索
                </Button>
              </div>

              <div className="flex items-start gap-1.5 rounded-lg bg-surface-50 px-2.5 py-2 text-[11px] leading-relaxed text-ink-500">
                <Users size={12} className="mt-0.5 shrink-0" />
                权限过滤：只返回你有权阅读的文档片段（公开 + 显式授权给你的文档），越权文档不会出现在结果里。
              </div>

              {searchError && (
                <div className="flex items-start gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-[11.5px] text-rose-700">
                  <ShieldAlert size={12} className="mt-0.5 shrink-0" />
                  {searchError}
                </div>
              )}

              {!searching && hits === null && !searchError && (
                <div className="py-6 text-center text-[11.5px] text-ink-400">输入问题回车，看看知识库里能检索到什么。</div>
              )}

              {searching && (
                <div className="space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-16" />
                  ))}
                </div>
              )}

              {!searching && hits && hits.length === 0 && (
                <Empty title="没有命中片段" desc="换一种说法，或确认相关文档已上传并解析完成。" />
              )}

              {!searching && hits && hits.length > 0 && (
                <div className="max-h-[52vh] space-y-2 overflow-y-auto pr-1">
                  {hits.map((h, i) => (
                    <div key={`${h.docId ?? i}-${h.seq ?? i}`} className="rounded-xl border border-surface-200 bg-white px-3 py-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-[12px] font-medium text-ink-900">{h.docName || "未命名文档"}</span>
                        <span className="shrink-0 rounded bg-brand-50 px-1.5 py-0.5 font-mono text-[10.5px] text-brand-700">
                          {typeof h.score === "number" ? h.score.toFixed(3) : "—"}
                        </span>
                      </div>
                      <div
                        className="mt-1 line-clamp-4 text-[11.5px] leading-relaxed text-ink-600"
                        dangerouslySetInnerHTML={{ __html: highlight(h.snippet || "", query) }}
                      />
                      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-200">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-brand-500 to-teal-500"
                          style={{ width: `${Math.max(6, ((h.score ?? 0) / maxScore) * 100)}%` }}
                        />
                      </div>
                      {h.seq !== undefined && <div className="mt-1 text-[10.5px] text-ink-400">切片 #{h.seq}</div>}
                    </div>
                  ))}
                </div>
              )}

              {searchRules.length > 0 && (
                <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                  <div className="text-[11px] font-medium text-ink-600">权限过滤说明</div>
                  <div className="mt-1 space-y-0.5">
                    {searchRules.map((r, i) => (
                      <div key={i} className="text-[10.5px] text-ink-500">
                        · {r}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* ---------------- 文档详情抽屉 ---------------- */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={activeDoc?.name || "文档详情"}
        desc={activeDoc ? `${String(activeDoc.type || "").toUpperCase()} · ${fileSize(activeDoc.size)} · ${formatNumber(activeDoc.chunkCount ?? 0)} 个切片` : undefined}
        width="w-[640px]"
        footer={
          <Button variant="outline" onClick={() => setDrawerOpen(false)}>
            关闭
          </Button>
        }
      >
        {detailLoading && <Skeleton className="h-40" />}
        {!detailLoading && activeDoc && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-[12px]">
              <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                <div className="text-[10.5px] text-ink-400">上传人</div>
                <div className="mt-0.5 text-ink-800">{ownerLabel(activeDoc)}</div>
              </div>
              <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                <div className="text-[10.5px] text-ink-400">上传时间</div>
                <div className="mt-0.5 text-ink-800">{activeDoc.createdAt ? formatDateTime(activeDoc.createdAt) : "—"}</div>
              </div>
              <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                <div className="text-[10.5px] text-ink-400">敏感级别</div>
                <div className="mt-0.5">
                  <Badge tone={LEVEL_TONE[activeDoc.sensitiveLevel || "internal"] ?? "gray"}>
                    {LEVEL_LABEL[activeDoc.sensitiveLevel || "internal"] ?? activeDoc.sensitiveLevel}
                  </Badge>
                </div>
              </div>
              <div className="rounded-lg bg-surface-50 px-2.5 py-2">
                <div className="text-[10.5px] text-ink-400">状态</div>
                <div className="mt-0.5 text-ink-800">{activeDoc.status === "ready" ? "就绪" : activeDoc.status}</div>
              </div>
            </div>

            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[12.5px] font-semibold text-ink-900">切片预览</span>
                <span className="text-[11px] text-ink-400">最多展示前 20 条</span>
              </div>
              {(activeDoc.chunks ?? []).length === 0 && <div className="text-[11.5px] text-ink-400">暂无切片（可能还在解析）。</div>}
              <div className="max-h-[36vh] space-y-1.5 overflow-y-auto pr-1">
                {(activeDoc.chunks ?? []).slice(0, 20).map((c) => (
                  <div key={c.seq} className="rounded-lg border border-surface-200 bg-white px-2.5 py-2">
                    <div className="text-[10.5px] text-ink-400">#{c.seq}</div>
                    <div className="mt-0.5 whitespace-pre-wrap break-words text-[11.5px] leading-relaxed text-ink-700">{c.text}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="border-t border-surface-200 pt-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[12.5px] font-semibold text-ink-900">文档 ACL</span>
                <span className="text-[11px] text-ink-400">{formatNumber(acl.length)} 条授权</span>
              </div>
              {aclLoading && <Skeleton className="h-16" />}
              {!aclLoading && acl.length === 0 && (
                <div className="rounded-lg bg-surface-50 px-2.5 py-2 text-[11.5px] leading-relaxed text-ink-500">
                  未配置 ACL：文档按「公开 + 部门」默认规则可见。需要限制时在下方显式授权。
                </div>
              )}
              {!aclLoading && acl.length > 0 && (
                <div className="space-y-1">
                  {acl.map((a, i) => {
                    const user = a.subjectType === "user" ? users.find((u) => u.id === a.subjectId) : undefined;
                    const name = a.subjectName || user?.name || user?.username || ROLE_LABEL[a.subjectId] || a.subjectId;
                    return (
                      <div key={`${a.subjectType}-${a.subjectId}-${i}`} className="flex items-center gap-2 rounded-lg px-1 py-1 text-[11.5px]">
                        <Badge tone={a.subjectType === "user" ? "brand" : a.subjectType === "dept" ? "blue" : "teal"}>
                          {a.subjectType === "user" ? "用户" : a.subjectType === "dept" ? "部门" : "角色"}
                        </Badge>
                        <span className="min-w-0 flex-1 truncate text-ink-800">{name}</span>
                        <Badge tone={a.canRead ? "green" : "gray"}>{a.canRead ? "可读" : "不可读"}</Badge>
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="mt-2.5 rounded-xl border border-surface-200 bg-surface-50/60 p-2.5">
                <div className="grid gap-2 sm:grid-cols-[110px_1fr_auto_auto] sm:items-end">
                  <Field label="对象类型">
                    <Select
                      value={aclForm.subjectType}
                      onChange={(e) => setAclForm((f) => ({ ...f, subjectType: e.target.value, subjectId: "" }))}
                    >
                      <option value="user">用户</option>
                      <option value="role">角色</option>
                    </Select>
                  </Field>
                  <Field label="对象">
                    <Select value={aclForm.subjectId} onChange={(e) => setAclForm((f) => ({ ...f, subjectId: e.target.value }))}>
                      <option value="">选择…</option>
                      {aclForm.subjectType === "user"
                        ? users.map((u) => (
                            <option key={u.id} value={u.id}>
                              {u.name || u.username}
                            </option>
                          ))
                        : Object.entries(ROLE_LABEL).map(([k, v]) => (
                            <option key={k} value={k}>
                              {v}
                            </option>
                          ))}
                    </Select>
                  </Field>
                  <div className="flex items-center gap-1.5 pb-1">
                    <Toggle checked={aclForm.canRead} onChange={(v) => setAclForm((f) => ({ ...f, canRead: v }))} />
                    <span className="text-[11.5px] text-ink-600">可读</span>
                  </div>
                  <Button size="sm" loading={aclSaving} onClick={() => void addAcl()}>
                    授权
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </Drawer>

      {/* ---------------- 删除确认 ---------------- */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="删除文档？"
        desc={deleteTarget?.name}
        width="max-w-md"
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button loading={deleting} onClick={() => void confirmDelete()} className="!bg-rose-600 hover:!bg-rose-700">
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-[12.5px] leading-relaxed text-ink-600">
          删除后文档及其 {formatNumber(deleteTarget?.chunkCount ?? 0)} 个切片将从知识库移除，检索结果不再命中。此操作不可撤销。
        </p>
      </Modal>
    </div>
  );
}
