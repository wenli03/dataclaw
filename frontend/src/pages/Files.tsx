import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BarChart3,
  Code2,
  Download,
  FileText,
  FolderClosed,
  Globe,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import type { ArtifactRef } from "../lib/types";
import { api, downloadWithAuth } from "../lib/api";
import { cx, fileSize, formatDateTime, timeAgo } from "../lib/format";
import { Badge, Button, Card, Empty, Input, Modal, Skeleton, Tabs, toast } from "../components/ui";

/* ---------------- 工具 ---------------- */
function errText(e: unknown): string {
  const msg = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  if (!msg || /failed to fetch|networkerror|load failed/i.test(msg)) return "服务暂不可用，请确认后端已启动";
  return msg;
}

type FileItem = {
  id: string;
  name: string;
  size?: number;
  mime?: string;
  kind?: string;
  createdAt?: string;
  uploadedBy?: string;
  ownerName?: string;
  downloadUrl?: string;
};

type RawFileItem = Omit<FileItem, "id"> & { id?: string; fileId?: string };

type ArtifactItem = ArtifactRef & {
  artifactId?: string;
  createdAt?: string;
  sessionId?: string;
  employeeName?: string;
};

type ListResp<T> = { items?: T[]; total?: number };

/** 后端列表用 fileId / artifactId 作为主键，这里统一成 id。 */
function normalizeFile(raw: RawFileItem): FileItem | null {
  const id = raw.fileId || raw.id;
  if (!id) return null;
  return {
    id,
    name: raw.name || "未命名文件",
    size: raw.size,
    mime: raw.mime,
    kind: raw.kind,
    createdAt: raw.createdAt,
    uploadedBy: raw.uploadedBy,
    ownerName: raw.ownerName,
    downloadUrl: raw.downloadUrl,
  };
}

function normalizeArtifact(raw: ArtifactItem): ArtifactItem | null {
  const id = raw.artifactId || raw.id;
  if (!id) return null;
  return { ...raw, id };
}

const KIND_LABEL: Record<string, string> = {
  dashboard: "可视化大屏",
  report: "深度报告",
  docx: "Word 文档",
  html: "网页",
  json: "结构化数据",
};

function KindIcon({ kind }: { kind: string }) {
  if (kind === "dashboard") return <BarChart3 size={14} />;
  if (kind === "html") return <Globe size={14} />;
  if (kind === "json") return <Code2 size={14} />;
  return <FileText size={14} />;
}

export default function Files() {
  const [tab, setTab] = useState("mine");
  const [files, setFiles] = useState<FileItem[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<FileItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      if (tab === "mine") {
        const res = await api.get<ListResp<RawFileItem>>("/files", { tab: "mine" });
        setFiles((res.items || []).map(normalizeFile).filter((f): f is FileItem => Boolean(f)));
      } else {
        const res = await api.get<ListResp<ArtifactItem>>("/artifacts");
        setArtifacts((res.items || []).map(normalizeArtifact).filter((a): a is ArtifactItem => Boolean(a)));
      }
    } catch (e) {
      setError(errText(e));
      if (tab === "mine") setFiles([]);
      else setArtifacts([]);
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  const upload = useCallback(
    async (list: File[]) => {
      if (list.length === 0) return;
      setUploading(true);
      let ok = 0;
      let lastError = "";
      for (const f of list) {
        try {
          await api.upload<unknown>("/files", f);
          ok += 1;
        } catch (e) {
          lastError = errText(e);
        }
      }
      setUploading(false);
      if (ok > 0) toast(ok === 1 ? "文件已上传" : `已上传 ${ok} 个文件`);
      if (lastError) toast(lastError, "error");
      if (ok > 0) {
        if (tab !== "mine") setTab("mine");
        else await load();
      }
    },
    [tab, load]
  );

  const downloadFile = async (f: FileItem) => {
    setBusyId(f.id);
    try {
      await downloadWithAuth(f.downloadUrl || `/api/files/${f.id}/download`, f.name);
      toast("已开始下载");
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setBusyId("");
    }
  };

  const downloadArtifact = async (a: ArtifactItem) => {
    setBusyId(a.id);
    try {
      await downloadWithAuth(a.downloadUrl || `/api/artifacts/${a.id}/download`, a.fileName || `${a.title || "产物"}`);
      toast("已开始下载");
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setBusyId("");
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del<unknown>(`/files/${deleteTarget.id}`);
      setFiles((prev) => prev.filter((f) => f.id !== deleteTarget.id));
      toast("文件已删除");
      setDeleteTarget(null);
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setDeleting(false);
    }
  };

  const visibleFiles = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return files;
    return files.filter((f) => (f.name || "").toLowerCase().includes(kw) || (f.kind || "").toLowerCase().includes(kw));
  }, [files, keyword]);

  const visibleArtifacts = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return artifacts;
    return artifacts.filter(
      (a) => (a.title || "").toLowerCase().includes(kw) || (KIND_LABEL[a.kind] || a.kind || "").toLowerCase().includes(kw)
    );
  }, [artifacts, keyword]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-[1320px] px-5 py-5 lg:px-7">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-semibold tracking-tight text-ink-900">文件</h1>
            <p className="mt-1 text-[12.5px] text-ink-500">
              上传合同、表格等材料供数字员工解析；会话里产出的交付物集中归档在「交付物」。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative w-[220px] max-w-full">
              <Input
                className="!py-1.5 !pl-3 !text-[12.5px]"
                placeholder="搜索文件名 / 类型"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            </div>
            <Button onClick={() => inputRef.current?.click()} loading={uploading} icon={<Upload size={14} />}>
              上传文件
            </Button>
          </div>
        </div>

        {/* 上传区 */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            void upload(Array.from(e.dataTransfer.files));
          }}
          onClick={() => inputRef.current?.click()}
          className={cx(
            "mt-4 cursor-pointer rounded-2xl border-2 border-dashed px-5 py-6 text-center transition",
            dragActive ? "border-brand-400 bg-brand-50/70" : "border-surface-300 bg-white hover:border-brand-300 hover:bg-brand-50/30"
          )}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              const list = Array.from(e.target.files || []);
              e.target.value = "";
              void upload(list);
            }}
          />
          <div className="mx-auto grid h-10 w-10 place-items-center rounded-2xl bg-brand-50 text-brand-600">
            {uploading ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
          </div>
          <div className="mt-2 text-[13px] font-medium text-ink-800">
            {uploading ? "正在上传…" : "拖拽文件到此处，或点击选择"}
          </div>
          <div className="mt-1 text-[11.5px] text-ink-400">
            支持 PDF / Word / Excel / 图片等格式；文件仅用于你的数字员工解析，按数据权限隔离。
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Tabs
            items={[
              { key: "mine", label: "我的文件", count: files.length },
              { key: "artifacts", label: "交付物", count: artifacts.length },
            ]}
            value={tab}
            onChange={setTab}
          />
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => void load()} icon={<RefreshCw size={13} />}>
            刷新
          </Button>
        </div>

        <div className="mt-3">
          {loading ? (
            <Card className="p-4">
              <div className="space-y-2.5">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <Skeleton className="h-8 w-8 rounded-lg" />
                    <Skeleton className="h-3 flex-1" />
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="h-3 w-20" />
                  </div>
                ))}
              </div>
            </Card>
          ) : error ? (
            <Card>
              <Empty
                title={tab === "mine" ? "文件列表加载失败" : "交付物加载失败"}
                desc={error}
                icon={<FolderClosed size={20} />}
                action={
                  <Button variant="outline" onClick={() => void load()} icon={<RefreshCw size={14} />}>
                    重试
                  </Button>
                }
              />
            </Card>
          ) : tab === "mine" ? (
            <Card className="overflow-hidden">
              {visibleFiles.length === 0 ? (
                <Empty
                  title={keyword ? "没有匹配的文件" : "还没有上传文件"}
                  desc={keyword ? "换个关键词试试" : "上传合同或数据表，让数字员工解析后再对话。"}
                  icon={<FolderClosed size={20} />}
                  action={
                    keyword ? (
                      <Button variant="outline" onClick={() => setKeyword("")}>
                        清空搜索
                      </Button>
                    ) : (
                      <Button onClick={() => inputRef.current?.click()} icon={<Upload size={14} />}>
                        上传文件
                      </Button>
                    )
                  }
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table-base">
                    <thead>
                      <tr>
                        <th>文件名</th>
                        <th className="w-[90px]">类型</th>
                        <th className="w-[90px]">大小</th>
                        <th className="w-[130px]">上传时间</th>
                        <th className="w-[120px] text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleFiles.map((f) => (
                        <tr key={f.id}>
                          <td>
                            <div className="flex items-center gap-2">
                              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-surface-100 text-ink-500">
                                <FileText size={13} />
                              </span>
                              <span className="truncate text-[12.5px] font-medium text-ink-800">{f.name || "未命名文件"}</span>
                            </div>
                          </td>
                          <td className="text-[11.5px] text-ink-500">{f.mime || f.kind || "—"}</td>
                          <td className="text-[11.5px] tabular-nums text-ink-500">{fileSize(f.size)}</td>
                          <td className="text-[11.5px] text-ink-500">{formatDateTime(f.createdAt)}</td>
                          <td>
                            <div className="flex items-center justify-end gap-1">
                              <button
                                onClick={() => void downloadFile(f)}
                                disabled={busyId === f.id}
                                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11.5px] text-ink-600 hover:bg-surface-100 hover:text-brand-700 disabled:opacity-50"
                              >
                                {busyId === f.id ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                                下载
                              </button>
                              <button
                                onClick={() => setDeleteTarget(f)}
                                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11.5px] text-ink-500 hover:bg-rose-50 hover:text-rose-600"
                              >
                                <Trash2 size={12} />
                                删除
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          ) : (
            <Card className="overflow-hidden">
              {visibleArtifacts.length === 0 ? (
                <Empty
                  title={keyword ? "没有匹配的交付物" : "还没有交付物"}
                  desc={keyword ? "换个关键词试试" : "数字员工产出的大屏、报告、文档会归档在这里。"}
                  icon={<FolderClosed size={20} />}
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table-base">
                    <thead>
                      <tr>
                        <th>交付物</th>
                        <th className="w-[120px]">类型</th>
                        <th className="w-[130px]">生成时间</th>
                        <th className="w-[110px] text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleArtifacts.map((a) => (
                        <tr key={a.id}>
                          <td>
                            <div className="flex items-center gap-2">
                              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600">
                                <KindIcon kind={a.kind} />
                              </span>
                              <span className="truncate text-[12.5px] font-medium text-ink-800">{a.title || a.fileName || "未命名交付物"}</span>
                            </div>
                          </td>
                          <td>
                            <Badge tone="gray">{KIND_LABEL[a.kind] || a.kind}</Badge>
                          </td>
                          <td className="text-[11.5px] text-ink-500">
                            {a.createdAt ? timeAgo(a.createdAt) : "—"}
                          </td>
                          <td>
                            <div className="flex justify-end">
                              <button
                                onClick={() => void downloadArtifact(a)}
                                disabled={busyId === a.id}
                                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11.5px] text-ink-600 hover:bg-surface-100 hover:text-brand-700 disabled:opacity-50"
                              >
                                {busyId === a.id ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                                下载
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="删除文件"
        desc="删除后该文件不可恢复；已生成的交付物不受影响。"
        width="max-w-md"
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" onClick={() => void confirmDelete()} loading={deleting} icon={<Trash2 size={14} />}>
              删除文件
            </Button>
          </>
        }
      >
        <div className="text-[12.5px] text-ink-600">确认删除「{deleteTarget?.name}」？</div>
      </Modal>
    </div>
  );
}
