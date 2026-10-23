import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Bot,
  ChevronRight,
  Download,
  ExternalLink,
  FileText,
  Info,
  Loader2,
  Menu,
  MessageSquare,
  MessageSquarePlus,
  PanelLeftOpen,
  PanelRight,
  RefreshCw,
  Settings2,
  Sparkles,
  Trash2,
  UserPlus,
  X,
} from "lucide-react";
import type { ArtifactRef, ChatMessage, Employee, SessionItem, StepItem } from "../lib/types";
import { api, downloadWithAuth, streamChat } from "../lib/api";
import { cx, formatNumber, timeAgo } from "../lib/format";
import { Avatar, Badge, Button, Empty, Modal, Skeleton, Tabs, toast } from "../components/ui";
import { SessionList } from "../components/chat/SessionList";
import { Composer, type Attachment } from "../components/chat/Composer";
import { MessageBubble, type UiMessage } from "../components/chat/MessageBubble";
import { EmptyChat } from "../components/chat/EmptyChat";
import { ArtifactView } from "../components/chat/ArtifactView";
import { ApprovalDialog, type ApprovalRequest } from "../components/chat/ApprovalDialog";

/* ---------------- 响应解析小工具 ---------------- */
function asRec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}
function str(v: unknown, fallback = ""): string {
  if (typeof v === "string") return v;
  if (v === null || v === undefined) return fallback;
  return String(v);
}
function errText(e: unknown): string {
  const msg = e instanceof Error ? e.message : str(e);
  if (!msg || /failed to fetch|networkerror|load failed/i.test(msg)) return "服务暂不可用，请确认后端已启动";
  return msg;
}
const STEP_TYPES: StepItem["type"][] = ["tool_call", "tool_result", "thinking", "approval", "plan"];
const STEP_STATUS: StepItem["status"][] = ["running", "done", "error", "pending"];
const ARTIFACT_KINDS: ArtifactRef["kind"][] = ["dashboard", "report", "docx", "html", "json"];

const KIND_LABEL: Record<ArtifactRef["kind"], string> = {
  dashboard: "可视化大屏",
  report: "深度报告",
  docx: "Word 文档",
  html: "网页",
  json: "结构化数据",
};

/** 产物 + 生成时间（列表/面板展示用） */
type ArtifactWithTime = ArtifactRef & { createdAt?: string };

function toStep(raw: unknown): StepItem | null {
  const r = asRec(raw);
  if (!Object.keys(r).length) return null;
  const rawType = str(r.type, "tool_call") as StepItem["type"];
  const rawStatus = str(r.status, "running") as StepItem["status"];
  const duration =
    typeof r.durationMs === "number" ? r.durationMs : typeof r.duration_ms === "number" ? (r.duration_ms as number) : undefined;
  return {
    id: str(r.id) || `step_${Math.random().toString(36).slice(2, 9)}`,
    type: STEP_TYPES.includes(rawType) ? rawType : "tool_call",
    tool: str(r.tool) || undefined,
    title: str(r.title),
    status: STEP_STATUS.includes(rawStatus) ? rawStatus : "running",
    input: r.input,
    output: r.output,
    summary: str(r.summary) || undefined,
    durationMs: duration,
    risk: str(r.risk) || undefined,
  };
}

function toArtifact(raw: unknown): ArtifactWithTime | null {
  const r = asRec(raw);
  const inner = asRec(r.artifact);
  const src = Object.keys(inner).length ? { ...r, ...inner } : r;
  const id = str(src.artifactId) || str(src.id);
  if (!id) return null;
  const preview = asRec(src.preview);
  const rawKind = str(src.kind) || str(preview.type) || "json";
  const kind = (ARTIFACT_KINDS.includes(rawKind as ArtifactRef["kind"]) ? rawKind : "json") as ArtifactRef["kind"];
  return {
    id,
    kind,
    title: str(src.title) || "产物",
    preview: src.preview ?? src.payload,
    text: str(src.text) || undefined,
    fileName: str(src.fileName) || undefined,
    downloadUrl: str(src.downloadUrl) || undefined,
    createdAt: str(src.createdAt) || undefined,
  };
}

type ListResp<T> = { items?: T[]; total?: number };
type SessionDetailResp = { session?: SessionItem; messages?: ChatMessage[]; items?: ChatMessage[] };
type CreateSessionResp = { session?: SessionItem } & Partial<SessionItem>;
type EmployeeResp = { employee?: Employee };

/* ---------------- 页面 ---------------- */
export default function Chat() {
  const { employeeId, sessionId } = useParams<{ employeeId?: string; sessionId?: string }>();
  const nav = useNavigate();

  /* 员工 */
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [empLoading, setEmpLoading] = useState(true);
  const [empError, setEmpError] = useState("");
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [templateNames, setTemplateNames] = useState<Record<string, string>>({});

  /* 会话 */
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sessLoading, setSessLoading] = useState(false);
  const [sessError, setSessError] = useState("");
  const [creatingSession, setCreatingSession] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SessionItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [listCollapsed, setListCollapsed] = useState(false);
  const [mobileList, setMobileList] = useState(false);

  /* 消息 */
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgError, setMsgError] = useState("");
  const [msgReloadKey, setMsgReloadKey] = useState(0);

  /* 输入 */
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);

  /* 流式 */
  const [streaming, setStreaming] = useState(false);
  const [idle, setIdle] = useState(false);
  const [approval, setApproval] = useState<ApprovalRequest | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const streamIdRef = useRef<string | null>(null);
  const sessionRef = useRef<string | null>(null);
  const abortRef = useRef<{ abort: () => void } | null>(null);
  const pendingRef = useRef("");
  const timerRef = useRef<number | null>(null);
  const lastTokenRef = useRef(0);
  const justCreatedRef = useRef<string | null>(null);
  const lastArtifactRef = useRef<{ messageId: string; kind: string } | null>(null);

  /* 右栏 */
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelTab, setPanelTab] = useState("artifacts");
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactRef | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  /* ---------------- 数据加载 ---------------- */
  const loadEmployees = useCallback(async () => {
    setEmpLoading(true);
    setEmpError("");
    try {
      const res = await api.get<ListResp<Employee>>("/employees", { scope: "mine" });
      setEmployees(Array.isArray(res.items) ? res.items : []);
    } catch (e) {
      setEmpError(errText(e));
      setEmployees([]);
    } finally {
      setEmpLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEmployees();
  }, [loadEmployees]);

  /* 角色模板名（用于「基于模板：X」副标题） */
  useEffect(() => {
    void (async () => {
      try {
        const res = await api.get<ListResp<{ id: string; name: string }>>("/templates");
        const map: Record<string, string> = {};
        (res.items || []).forEach((t) => {
          if (t.id) map[t.id] = t.name;
        });
        setTemplateNames(map);
      } catch {
        /* 模板接口不可用时副标题退回来源徽标 */
      }
    })();
  }, []);

  const loadSessions = useCallback(async (eid: string) => {
    setSessLoading(true);
    setSessError("");
    try {
      const res = await api.get<ListResp<SessionItem>>("/sessions", { employeeId: eid });
      setSessions(Array.isArray(res.items) ? res.items : []);
    } catch (e) {
      setSessError(errText(e));
      setSessions([]);
    } finally {
      setSessLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!employeeId) {
      setSessions([]);
      return;
    }
    void loadSessions(employeeId);
  }, [employeeId, loadSessions]);

  /* 无 employeeId → 默认选"我的员工"第一个 */
  useEffect(() => {
    if (empLoading || employeeId || empError) return;
    if (employees.length > 0) nav(`/chat/${employees[0].id}`, { replace: true });
  }, [empLoading, employeeId, empError, employees, nav]);

  /* 员工详情（补全技能 / 公共员工版本 / 统计） */
  useEffect(() => {
    if (!employeeId) {
      setEmployee(null);
      return;
    }
    const summary = employees.find((e) => e.id === employeeId) || null;
    setEmployee((prev) => (prev?.id === employeeId ? prev : summary));
    let alive = true;
    void (async () => {
      try {
        const res = await api.get<EmployeeResp>(`/employees/${employeeId}`);
        if (alive && res.employee) setEmployee(res.employee);
      } catch {
        /* 详情接口失败时退回列表摘要，不打断对话 */
      }
    })();
    return () => {
      alive = false;
    };
  }, [employeeId, employees]);

  /* 会话消息 */
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setMsgError("");
      setMsgLoading(false);
      return;
    }
    if (justCreatedRef.current === sessionId) {
      justCreatedRef.current = null;
      return;
    }
    let alive = true;
    setMsgLoading(true);
    setMsgError("");
    void (async () => {
      try {
        const res = await api.get<SessionDetailResp>(`/sessions/${sessionId}`);
        if (!alive) return;
        const list = (res.messages ?? res.items ?? []).map((m) => ({
          ...m,
          steps: Array.isArray(m.steps) ? m.steps : [],
          artifacts: Array.isArray(m.artifacts) ? m.artifacts.map((a) => toArtifact(a) ?? a) : [],
          streaming: false,
        }));
        setMessages(list);
        const detailSession = res.session ?? (res as unknown as SessionItem);
        if (detailSession && detailSession.id) {
          setSessions((prev) => prev.map((s) => (s.id === detailSession.id ? { ...s, ...detailSession } : s)));
        }
        /* 历史消息里的产物只带 id/kind/title，需要补全 preview 才能渲染 */
        const missing = new Set<string>();
        list.forEach((m) => (m.artifacts || []).forEach((a) => a && a.id && !a.preview && missing.add(a.id)));
        void Promise.all(
          Array.from(missing).map(async (artifactId) => {
            try {
              const data = await api.get<unknown>(`/artifacts/${artifactId}`);
              const full = toArtifact(data);
              if (!full || !alive) return;
              setMessages((prev) =>
                prev.map((m) => ({
                  ...m,
                  artifacts: (m.artifacts || []).map((a) => (a.id === full.id ? { ...a, ...full } : a)),
                }))
              );
            } catch {
              /* 预览补全失败时保留占位卡片 */
            }
          })
        );
      } catch (e) {
        if (alive) {
          setMsgError(errText(e));
          setMessages([]);
        }
      } finally {
        if (alive) setMsgLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [sessionId, msgReloadKey]);

  /* ---------------- 流式工具 ---------------- */
  const flush = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const chunk = pendingRef.current;
    pendingRef.current = "";
    if (!chunk) return;
    const mid = streamIdRef.current;
    setMessages((prev) => prev.map((m) => (m.id === mid ? { ...m, content: m.content + chunk } : m)));
  }, []);

  const appendDelta = useCallback(
    (text: string) => {
      if (!text) return;
      lastTokenRef.current = Date.now();
      pendingRef.current += text;
      if (timerRef.current === null) {
        timerRef.current = window.setTimeout(() => {
          timerRef.current = null;
          flush();
        }, 40);
      }
    },
    [flush]
  );

  /**
   * 流结束后把本轮的产物滚到视野顶部（大屏优先）；用户已上滑查看历史时不打断。
   * 只针对刚刚结束的这一条消息，避免跳到历史产物。
   */
  const revealLastArtifact = useCallback((messageId: string) => {
    /* done 与 artifact 可能在同一批事件里到达，此时 React 还没提交产物节点，延后查询 */
    window.setTimeout(() => {
      if (!stickRef.current) return;
      const root = scrollRef.current;
      if (!root) return;
      const msgNode = Array.from(root.querySelectorAll<HTMLElement>("[data-message-id]")).find(
        (n) => n.dataset.messageId === messageId
      );
      if (!msgNode) return;
      const arts = Array.from(msgNode.querySelectorAll<HTMLElement>("[data-artifact-id]"));
      if (arts.length === 0) return;
      const dashboards = arts.filter((a) => a.dataset.artifactKind === "dashboard");
      const target = dashboards.length > 0 ? dashboards[dashboards.length - 1] : arts[arts.length - 1];
      /* 停在产物处：停止自动跟随，保留用户后续手动滚动的结果 */
      stickRef.current = false;
      const box = root.getBoundingClientRect();
      const rect = target.getBoundingClientRect();
      const top = root.scrollTop + (rect.top - box.top) - 8;
      root.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    }, 420);
  }, []);

  const settle = useCallback(
    (error?: string) => {
      flush();
      const currentId = streamIdRef.current;
      const artifact = lastArtifactRef.current;
      lastArtifactRef.current = null;
      setStreaming(false);
      setIdle(false);
      abortRef.current = null;
      streamIdRef.current = null;
      setMessages((prev) => prev.map((m) => (m.streaming ? { ...m, streaming: false, error: error || m.error } : m)));
      if (!error && artifact && artifact.messageId === currentId) {
        revealLastArtifact(artifact.messageId);
      }
    },
    [flush, revealLastArtifact]
  );

  const upsertStep = useCallback((step: StepItem) => {
    const mid = streamIdRef.current;
    if (!mid) return;
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== mid) return m;
        const steps = [...(m.steps || [])];
        const idx = steps.findIndex((s) => s.id === step.id);
        if (idx >= 0) {
          const prevStep = steps[idx];
          steps[idx] = {
            ...prevStep,
            ...step,
            type: prevStep.type,
            title: step.title || prevStep.title,
            tool: step.tool || prevStep.tool,
            summary: step.summary || prevStep.summary,
            input: step.input !== undefined ? step.input : prevStep.input,
            output: step.output !== undefined ? step.output : prevStep.output,
            durationMs: step.durationMs ?? prevStep.durationMs,
            risk: step.risk || prevStep.risk,
          };
        } else {
          steps.push(step);
        }
        return { ...m, steps };
      })
    );
  }, []);

  const appendArtifact = useCallback((a: ArtifactRef) => {
    const mid = streamIdRef.current;
    if (!mid) return;
    lastArtifactRef.current = { messageId: mid, kind: a.kind };
    const withTime: ArtifactWithTime = {
      ...a,
      createdAt: (a as ArtifactWithTime).createdAt || new Date().toISOString(),
    };
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== mid) return m;
        const list = [...(m.artifacts || [])];
        const idx = list.findIndex((x) => x.id === withTime.id);
        if (idx >= 0) list[idx] = { ...list[idx], ...withTime };
        else list.push(withTime);
        return { ...m, artifacts: list };
      })
    );
  }, []);

  /* 流式但无新 token → “正在执行…” */
  useEffect(() => {
    if (!streaming) {
      setIdle(false);
      return;
    }
    const t = window.setInterval(() => setIdle(Date.now() - lastTokenRef.current > 700), 400);
    return () => window.clearInterval(t);
  }, [streaming]);

  /* 卸载清理 */
  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    []
  );

  /* 自动滚动到底（用户上滑查看历史时不强制拉回） */
  useEffect(() => {
    if (!stickRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  /* ---------------- 会话操作 ---------------- */
  const createSession = useCallback(
    async (targetEmployeeId?: string): Promise<string | null> => {
      const eid = targetEmployeeId || employeeId;
      if (!eid) return null;
      if (streamIdRef.current) {
        toast("当前回答还在生成，请先停止或稍后再新建会话", "info");
        return null;
      }
      setCreatingSession(true);
      try {
        const res = await api.post<CreateSessionResp>("/sessions", { employeeId: eid });
        const created = res.session ?? (res as unknown as SessionItem);
        if (!created || !created.id) throw new Error("会话创建接口未返回会话 ID");
        const item: SessionItem = {
          ...created,
          employeeId: eid,
          title: created.title || "新会话",
          messageCount: created.messageCount ?? 0,
        };
        setSessions((prev) => [item, ...prev.filter((s) => s.id !== item.id)]);
        justCreatedRef.current = item.id;
        sessionRef.current = item.id;
        setMessages([]);
        nav(`/chat/${eid}/${item.id}`, { replace: true });
        return item.id;
      } catch (e) {
        toast(errText(e), "error");
        return null;
      } finally {
        setCreatingSession(false);
      }
    },
    [employeeId, nav]
  );

  const renameSession = useCallback(
    async (id: string, title: string) => {
      const prevTitle = sessions.find((s) => s.id === id)?.title;
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
      try {
        await api.patch<unknown>(`/sessions/${id}`, { title });
        toast("会话已重命名");
      } catch (e) {
        setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title: prevTitle || s.title } : s)));
        toast(errText(e), "error");
      }
    },
    [sessions]
  );

  const togglePin = useCallback(async (id: string, pinned: boolean) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, pinned } : s)));
    try {
      await api.patch<unknown>(`/sessions/${id}`, { pinned });
    } catch (e) {
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, pinned: !pinned } : s)));
      toast(errText(e), "error");
    }
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del<unknown>(`/sessions/${deleteTarget.id}`);
      setSessions((prev) => prev.filter((s) => s.id !== deleteTarget.id));
      toast("会话已删除");
      if (sessionId === deleteTarget.id) {
        setMessages([]);
        nav(`/chat/${deleteTarget.employeeId || employeeId || ""}`, { replace: true });
      }
      setDeleteTarget(null);
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setDeleting(false);
    }
  }, [deleteTarget, employeeId, nav, sessionId]);

  /* ---------------- 发送 / SSE ---------------- */
  const send = useCallback(
    async (raw?: string) => {
      const content = (raw ?? input).trim();
      /* 路由还没带上 employeeId 时（首屏跳转瞬间）回落到第一个员工，避免点击示例无反应 */
      const eid = employeeId || employees[0]?.id || "";
      if (!content || streaming || !eid) return;

      let sid = sessionId || null;
      if (!sid) {
        sid = await createSession(eid);
        if (!sid) return;
      }
      sessionRef.current = sid;
      lastArtifactRef.current = null;

      const atts = attachments.map((a) => ({ fileId: a.fileId }));
      const userMsg: UiMessage = {
        id: `local_u_${Date.now()}`,
        role: "user",
        content,
        createdAt: new Date().toISOString(),
      };
      const localId = `local_a_${Date.now()}`;
      const assistantMsg: UiMessage = {
        id: localId,
        role: "assistant",
        content: "",
        steps: [],
        artifacts: [],
        streaming: true,
        createdAt: new Date().toISOString(),
      };

      setInput("");
      setAttachments([]);
      stickRef.current = true;
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      streamIdRef.current = localId;
      lastTokenRef.current = Date.now();
      setStreaming(true);

      abortRef.current = streamChat(
        `/sessions/${sid}/messages`,
        { content, attachments: atts },
        {
          onEvent: (event, data) => {
            const d = asRec(data);
            switch (event) {
              case "start": {
                const mid = str(d.messageId);
                if (mid && streamIdRef.current) {
                  const old = streamIdRef.current;
                  streamIdRef.current = mid;
                  setMessages((prev) => prev.map((m) => (m.id === old ? { ...m, id: mid } : m)));
                }
                break;
              }
              case "delta": {
                appendDelta(str(d.text));
                break;
              }
              case "step": {
                const step = toStep(d);
                if (step) upsertStep(step);
                break;
              }
              case "artifact": {
                const artifact = toArtifact(d);
                if (!artifact) break;
                appendArtifact(artifact);
                if (!artifact.preview) {
                  void api
                    .get<unknown>(`/artifacts/${artifact.id}`)
                    .then((data) => {
                      const full = toArtifact(data);
                      if (full) appendArtifact({ ...artifact, ...full });
                    })
                    .catch(() => {
                      /* 预览补全失败时保留占位卡片 */
                    });
                }
                break;
              }
              case "approval": {
                const request: ApprovalRequest = {
                  approvalId: str(d.approvalId),
                  stepId: str(d.stepId) || undefined,
                  action: str(d.action) || "high_risk_action",
                  reason: str(d.reason),
                  risk: str(d.risk) || "high",
                };
                if (!request.approvalId) break;
                setApproval(request);
                upsertStep({
                  id: `approval_${request.approvalId}`,
                  type: "approval",
                  title: "等待人工审批",
                  status: "running",
                  summary: request.reason,
                  risk: request.risk,
                });
                break;
              }
              case "error": {
                const message = str(d.message) || str(d.code) || "执行出错";
                toast(message, "error");
                settle(message);
                break;
              }
              case "done": {
                settle();
                void loadSessions(eid);
                break;
              }
              default:
                break;
            }
          },
          onError: (err) => {
            const message = errText(err);
            toast(message, "error");
            settle(message);
            void loadSessions(eid);
          },
          onClose: () => {
            if (streamIdRef.current) {
              settle();
              void loadSessions(eid);
            }
          },
        }
      );
    },
    [appendArtifact, appendDelta, attachments, createSession, employeeId, employees, input, loadSessions, sessionId, settle, streaming, upsertStep]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    settle();
    toast("已停止生成", "info");
    if (employeeId) void loadSessions(employeeId);
  }, [employeeId, loadSessions, settle]);

  const decideApproval = useCallback(
    async (decision: "approved" | "rejected") => {
      const current = approval;
      const sid = sessionRef.current || sessionId;
      if (!current || !sid) return;
      setApprovalBusy(true);
      try {
        await api.post<unknown>(`/sessions/${sid}/approvals/${current.approvalId}`, { decision });
        upsertStep({
          id: `approval_${current.approvalId}`,
          type: "approval",
          title: decision === "approved" ? "人工审批：已批准" : "人工审批：已拒绝",
          status: "done",
        });
        setApproval(null);
        toast(decision === "approved" ? "已批准，数字员工继续执行" : "已拒绝，该步骤将被跳过");
      } catch (e) {
        toast(errText(e), "error");
      } finally {
        setApprovalBusy(false);
      }
    },
    [approval, sessionId, upsertStep]
  );

  const uploadFile = useCallback(async (file: File) => {
    setUploading(true);
    try {
      const res = await api.upload<{ fileId?: string; id?: string; name?: string; size?: number }>("/files", file);
      const fileId = res.fileId || res.id;
      if (!fileId) throw new Error("上传接口未返回文件 ID");
      setAttachments((prev) => [...prev, { fileId, name: res.name || file.name, size: res.size ?? file.size }]);
      toast("附件已添加");
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      setUploading(false);
    }
  }, []);

  /* ---------------- 派生数据 ---------------- */
  const allArtifacts = useMemo(() => {
    const map = new Map<string, ArtifactWithTime>();
    messages.forEach((m) =>
      (m.artifacts || []).forEach((a) => {
        const art = a as ArtifactWithTime;
        if (art.id) map.set(art.id, art);
      })
    );
    return Array.from(map.values()).reverse();
  }, [messages]);

  const activeSession = useMemo(() => sessions.find((s) => s.id === sessionId) || null, [sessions, sessionId]);

  /* 副标题：角色与名称重复时不重复展示，改为展示来源 */
  const employeeSubtitle = useMemo(() => {
    if (!employee) return "";
    const name = (employee.name || "").trim();
    const role = (employee.roleTitle || "").trim();
    if (role && role !== name) return role;
    if (employee.publicAgent) return `来自公共员工 v${employee.publicAgent.version}`;
    const tplName = employee.templateId ? templateNames[employee.templateId] : "";
    if (tplName) return `基于模板：${tplName}`;
    return "";
  }, [employee, templateNames]);

  const subtitleHasSource = employeeSubtitle.startsWith("来自公共员工");

  const downloadArtifact = useCallback(async (a: ArtifactRef) => {
    try {
      await downloadWithAuth(a.downloadUrl || `/api/artifacts/${a.id}/download`, a.fileName || `${a.title || "产物"}`);
      toast("已开始下载");
    } catch (e) {
      toast(errText(e), "error");
    }
  }, []);

  /* ---------------- 空 / 错误态（员工） ---------------- */
  if (empLoading) {
    return (
      <div className="flex h-full items-center justify-center bg-surface-100">
        <div className="flex items-center gap-2 text-[12.5px] text-ink-500">
          <Loader2 size={15} className="animate-spin" /> 正在加载工作台…
        </div>
      </div>
    );
  }

  if (empError) {
    return (
      <div className="grid h-full place-items-center bg-surface-100">
        <Empty
          title="工作台暂时不可用"
          desc={`${empError}。可稍后重试，或联系管理员检查服务状态。`}
          icon={<Bot size={20} />}
          action={
            <Button variant="outline" onClick={() => void loadEmployees()} icon={<RefreshCw size={14} />}>
              重试
            </Button>
          }
        />
      </div>
    );
  }

  if (employees.length === 0) {
    return (
      <div className="grid h-full place-items-center bg-surface-100">
        <Empty
          title="你还没有数字员工"
          desc="数字员工是你的专属 AI 同事：绑定技能、继承你的数据权限，说完话就直接交付大屏、报告或文档。"
          icon={<UserPlus size={20} />}
          action={
            <Button onClick={() => nav("/employees")} icon={<Sparkles size={14} />}>
              去创建一个员工
            </Button>
          }
        />
      </div>
    );
  }

  const employeeSkills = (employee?.skills || []).filter((s) => s.enabled !== false);
  const stats = employee?.stats;

  /* ---------------- 会话栏 ---------------- */
  const sessionList = (
    <SessionList
      sessions={sessions}
      activeId={sessionId}
      loading={sessLoading}
      error={sessError}
      creating={creatingSession}
      onSelect={(id) => {
        if (streamIdRef.current) {
          abortRef.current?.abort();
          abortRef.current = null;
          settle();
        }
        nav(`/chat/${employeeId}/${id}`);
        setMobileList(false);
      }}
      onCreate={() => {
        void createSession();
        setMobileList(false);
      }}
      onRename={(id, title) => void renameSession(id, title)}
      onDelete={(id) => {
        const target = sessions.find((s) => s.id === id);
        if (target) setDeleteTarget(target);
      }}
      onTogglePin={(id, pinned) => void togglePin(id, pinned)}
      onRetry={() => employeeId && void loadSessions(employeeId)}
      onClose={() => setMobileList(false)}
    />
  );

  /* ---------------- 右栏内容 ---------------- */
  const panelBody = (
    <>
      <div className="flex items-center gap-2 border-b border-surface-200 px-3 py-2.5">
        <div className="text-[13px] font-semibold text-ink-900">内容</div>
        <span className="truncate text-[10.5px] text-ink-400">{activeSession?.title || "当前会话"}</span>
        <button
          onClick={() => setPanelOpen(false)}
          className="ml-auto rounded-lg p-1 text-ink-400 hover:bg-surface-100 hover:text-ink-700"
          aria-label="收起内容面板"
        >
          <X size={14} />
        </button>
      </div>
      <div className="px-3 py-2">
        <Tabs
          items={[
            { key: "artifacts", label: "产物", count: allArtifacts.length },
            { key: "detail", label: "详情" },
          ]}
          value={panelTab}
          onChange={setPanelTab}
          className="w-full"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        {panelTab === "artifacts" ? (
          allArtifacts.length === 0 ? (
            <Empty
              title="本会话还没有产物"
              desc="数字员工产出大屏、报告或文档后，会集中显示在这里，方便重复打开与下载。"
              icon={<FileText size={18} />}
            />
          ) : (
            <div className="space-y-2">
              {allArtifacts.map((a) => (
                <div key={a.id} className="card flex items-start gap-2 p-2.5">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600">
                    <FileText size={14} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[12.5px] font-medium text-ink-800">{a.title || "未命名产物"}</div>
                    <div className="truncate text-[10.5px] text-ink-400">
                      {KIND_LABEL[a.kind] || a.kind}
                      {a.createdAt ? ` · ${timeAgo(a.createdAt)}` : ""}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button
                      type="button"
                      title="打开预览"
                      onClick={() => setPreviewArtifact(a)}
                      className="rounded-lg p-1 text-ink-400 transition hover:bg-surface-100 hover:text-brand-600"
                    >
                      <ExternalLink size={13} />
                    </button>
                    <button
                      type="button"
                      title="下载"
                      onClick={() => void downloadArtifact(a)}
                      className="rounded-lg p-1 text-ink-400 transition hover:bg-surface-100 hover:text-brand-600"
                    >
                      <Download size={13} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : employee ? (
          <div className="space-y-3">
            <div className="rounded-xl border border-surface-200 bg-surface-50/70 p-3">
              <div className="flex items-center gap-2.5">
                <Avatar name={employee.name} seed={employee.avatar || employee.id} size={38} />
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-semibold text-ink-900">{employee.name}</div>
                  <div className="truncate text-[11px] text-ink-500">{employee.roleTitle || "数字员工"}</div>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {employee.memoryEnabled && (
                  <Badge tone="teal" dot>
                    记忆已开启
                  </Badge>
                )}
                {employee.publicAgent && <Badge tone="brand">来自公共员工 v{employee.publicAgent.version}</Badge>}
                <Badge tone="gray">{employeeSkills.length} 个技能</Badge>
              </div>
              <div className="mt-2 text-[10.5px] leading-relaxed text-ink-500">
                来源：
                {employee.source === "from_public" ? `公共员工${employee.publicAgent ? ` v${employee.publicAgent.version}` : ""}` : "个人创建"}
                {employee.templateId && templateNames[employee.templateId] ? ` · 模板 ${templateNames[employee.templateId]}` : ""}
                {employee.memoryEnabled ? " · 记忆已开启" : " · 记忆已关闭"}
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {[
                { label: "会话", value: stats?.sessions ?? sessions.length },
                { label: "工具调用", value: stats?.toolCalls ?? 0 },
                { label: "产物", value: stats?.artifacts ?? allArtifacts.length },
              ].map((s) => (
                <div key={s.label} className="rounded-xl border border-surface-200 px-2 py-2 text-center">
                  <div className="text-[16px] font-semibold leading-none text-ink-900">{formatNumber(Number(s.value) || 0)}</div>
                  <div className="mt-1 text-[10.5px] text-ink-400">{s.label}</div>
                </div>
              ))}
            </div>

            <div className="rounded-xl border border-surface-200 p-3">
              <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium text-ink-600">
                <Sparkles size={12} /> 已装技能
              </div>
              {employeeSkills.length === 0 ? (
                <div className="text-[11.5px] text-ink-400">尚未配置技能，去员工设置里添加。</div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {employeeSkills.map((s) => (
                    <span key={s.id} className="chip border border-surface-300 bg-white text-ink-600">
                      {s.displayName}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-surface-200 p-3">
              <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium text-ink-600">
                <Info size={12} /> Agent 设定（SOUL）
              </div>
              <div className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-[11.5px] leading-relaxed text-ink-500">
                {employee.soulMd || "未配置 SOUL.md"}
              </div>
              <button
                onClick={() => nav(`/employees?focus=${employee.id}`)}
                className="mt-2 inline-flex items-center gap-1 text-[11.5px] text-brand-600 hover:underline"
              >
                打开员工设置 <ChevronRight size={11} />
              </button>
            </div>

            {employee.lastActiveAt && (
              <div className="text-center text-[10.5px] text-ink-400">最近活跃：{timeAgo(employee.lastActiveAt)}</div>
            )}
          </div>
        ) : null}
      </div>
    </>
  );

  /* ---------------- 渲染 ---------------- */
  return (
    <div className="flex h-full min-h-0 bg-surface-100">
      {!listCollapsed && <div className="hidden h-full lg:block">{sessionList}</div>}

      {mobileList && (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <div className="absolute inset-0 bg-ink-900/30" onClick={() => setMobileList(false)} />
          <div className="relative h-full">{sessionList}</div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col bg-white">
        {/* 顶部 */}
        <header className="flex items-center gap-2 border-b border-surface-200 px-3 py-2.5">
          <button onClick={() => setMobileList(true)} className="rounded-lg p-1.5 text-ink-600 hover:bg-surface-100 lg:hidden">
            <Menu size={17} />
          </button>
          {listCollapsed && (
            <button
              onClick={() => setListCollapsed(false)}
              className="hidden rounded-lg p-1.5 text-ink-500 hover:bg-surface-100 hover:text-ink-800 lg:block"
              title="展开会话列表"
            >
              <PanelLeftOpen size={16} />
            </button>
          )}

          <Avatar name={employee?.name} seed={employee?.avatar || employeeId} size={34} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-[13.5px] font-semibold text-ink-900">{employee?.name || "数字员工"}</span>
              {activeSession?.title && (
                <span className="hidden min-w-0 truncate text-[11px] text-ink-400 2xl:inline">/ {activeSession.title}</span>
              )}
            </div>
            {employeeSubtitle && <div className="truncate text-[11px] text-ink-500">{employeeSubtitle}</div>}
          </div>

          <div className="hidden shrink-0 items-center gap-1 2xl:flex">
            {employee?.memoryEnabled && (
              <Badge tone="teal" dot>
                记忆已开启
              </Badge>
            )}
            {employee?.publicAgent && !subtitleHasSource && <Badge tone="brand">来自公共员工 v{employee.publicAgent.version}</Badge>}
            {employeeSkills.length > 0 && <Badge tone="gray">已装 {employeeSkills.length} 个技能</Badge>}
          </div>

          <div className="ml-auto flex shrink-0 items-center gap-1">
            <button
              onClick={() => setListCollapsed(false)}
              className="rounded-lg p-1.5 text-ink-500 hover:bg-surface-100 lg:hidden"
              title="会话列表"
            >
              <MessageSquare size={15} />
            </button>
            <button
              onClick={() => employeeId && nav(`/employees?focus=${employeeId}`)}
              title="员工设置"
              className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-lg px-2 py-1.5 text-[11.5px] text-ink-600 transition hover:bg-surface-100 hover:text-ink-900"
            >
              <Settings2 size={14} /> <span className="hidden xl:inline">员工设置</span>
            </button>
            <button
              onClick={() => void createSession()}
              disabled={creatingSession}
              title="新建会话"
              className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-lg px-2 py-1.5 text-[11.5px] text-ink-600 transition hover:bg-surface-100 hover:text-ink-900 disabled:opacity-50"
            >
              {creatingSession ? <Loader2 size={14} className="animate-spin" /> : <MessageSquarePlus size={14} />}
              <span className="hidden xl:inline">新会话</span>
            </button>
            <button
              onClick={() => setPanelOpen((v) => !v)}
              title="产物/详情"
              aria-pressed={panelOpen}
              className={cx(
                "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-lg px-2 py-1.5 text-[11.5px] transition",
                panelOpen ? "bg-brand-50 text-brand-700" : "text-ink-600 hover:bg-surface-100 hover:text-ink-900"
              )}
            >
              <PanelRight size={14} /> <span className="hidden xl:inline">产物/详情</span>
            </button>
          </div>
        </header>

        {/* 消息区 */}
        <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto bg-surface-50/40">
          <div className="mx-auto w-full max-w-[880px] px-4 py-5">
            {msgLoading ? (
              <div className="space-y-5">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="flex gap-2.5">
                    <Skeleton className="h-8 w-8 shrink-0 rounded-full" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-2.5 w-24" />
                      <Skeleton className="h-3 w-4/5" />
                      <Skeleton className="h-3 w-3/5" />
                    </div>
                  </div>
                ))}
              </div>
            ) : msgError ? (
              <Empty
                title="消息加载失败"
                desc={msgError}
                icon={<MessageSquare size={18} />}
                action={
                  <Button variant="outline" onClick={() => setMsgReloadKey((k) => k + 1)} icon={<RefreshCw size={14} />}>
                    重新加载
                  </Button>
                }
              />
            ) : messages.length === 0 ? (
              <EmptyChat employee={employee} subtitle={employeeSubtitle} onPick={(text) => void send(text)} />
            ) : (
              <div className="space-y-5">
                {messages.map((m) => (
                  <MessageBubble key={m.id} message={m} employee={employee} />
                ))}
              </div>
            )}

            {streaming && idle && (
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-surface-200 bg-white px-3 py-2 text-[12px] text-ink-500">
                <Loader2 size={13} className="animate-spin text-brand-600" />
                正在执行…
              </div>
            )}
            <div className="h-2" />
          </div>
        </div>

        <Composer
          value={input}
          onChange={setInput}
          onSend={() => void send()}
          onStop={stop}
          streaming={streaming}
          attachments={attachments}
          onUpload={(f) => void uploadFile(f)}
          onRemoveAttachment={(fileId) => setAttachments((prev) => prev.filter((a) => a.fileId !== fileId))}
          uploading={uploading}
          disabled={!employeeId}
          placeholder={employee ? `向 ${employee.name} 下达任务：说清目标、时间范围与期望的交付物` : undefined}
        />
      </div>

      {panelOpen && (
        <>
          <aside className="hidden w-[360px] shrink-0 flex-col border-l border-surface-200 bg-white xl:flex">{panelBody}</aside>
          <div className="fixed inset-0 z-40 flex xl:hidden">
            <div className="absolute inset-0 bg-ink-900/30" onClick={() => setPanelOpen(false)} />
            <div className="relative ml-auto flex h-full w-[360px] max-w-[92vw] flex-col bg-white shadow-pop">{panelBody}</div>
          </div>
        </>
      )}

      {/* 产物全屏预览 */}
      <Modal
        open={Boolean(previewArtifact)}
        onClose={() => setPreviewArtifact(null)}
        title={previewArtifact?.title || "产物预览"}
        width="max-w-5xl"
      >
        {previewArtifact && <ArtifactView artifact={previewArtifact} />}
      </Modal>

      {/* 删除会话确认 */}
      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="删除会话"
        desc="删除后会话内容不可恢复；已产出的交付物与审计记录会保留。"
        width="max-w-md"
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" onClick={() => void confirmDelete()} loading={deleting} icon={<Trash2 size={14} />}>
              删除会话
            </Button>
          </>
        }
      >
        <div className="text-[12.5px] text-ink-600">
          确认删除会话「{deleteTarget?.title || "未命名会话"}」？该会话共 {deleteTarget?.messageCount ?? 0} 条消息。
        </div>
      </Modal>

      <ApprovalDialog approval={approval} busy={approvalBusy} onDecide={(d) => void decideApproval(d)} />
    </div>
  );
}
