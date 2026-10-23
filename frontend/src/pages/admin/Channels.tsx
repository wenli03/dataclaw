import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Bell,
  Building2,
  Check,
  Code2,
  Copy,
  Globe,
  MessageCircle,
  Plug,
  RefreshCw,
  Send,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { api, getToken } from "@/lib/api";
import type { Channel, Paginated } from "@/lib/types";
import { Badge, Button, Card, CardHeader, Empty, Field, Input, Select, Skeleton, Toggle, toast } from "@/components/ui";
import { PageHeader } from "@/components/admin/PageHeader";
import { cx, formatDateTime, timeAgo } from "@/lib/format";

/* ------------------------------------------------------------------ 渠道定义
 * 字段名与后端 channel_service.CHANNEL_SPECS / DEFAULT_CONFIG 对齐（snake_case），
 * 后端返回的 required[] 会在运行时覆盖 label 与必填标记，这里只是兜底默认值。
 */

interface FieldDef {
  key: string;
  label: string;
  placeholder?: string;
  hint?: string;
  secret?: boolean;
  required?: boolean;
  options?: string[];
  numeric?: boolean;
}

interface ChannelDef {
  type: string;
  name: string;
  subtitle: string;
  desc: string;
  icon: ReactNode;
  capabilities: string[];
  fields: FieldDef[];
}

const CHANNEL_DEFS: ChannelDef[] = [
  {
    type: "feishu",
    name: "飞书",
    subtitle: "机器人 / 多维表格",
    desc: "群聊里 @ 数字员工即可对话；多维表格可作为数据源接入。",
    icon: <MessageCircle size={17} />,
    capabilities: ["群机器人", "单聊机器人", "多维表格", "事件回调"],
    fields: [
      { key: "app_id", label: "App ID", placeholder: "cli_xxxxxxxxxxxx", required: true },
      { key: "app_secret", label: "App Secret", secret: true, required: true, placeholder: "应用密钥" },
      { key: "verification_token", label: "Verification Token", secret: true, hint: "事件订阅校验；留空保持现值" },
      { key: "token", label: "回调 Token", secret: true, hint: "入站请求需带 X-DataClaw-Token；留空保持现值" },
    ],
  },
  {
    type: "wecom",
    name: "企业微信",
    subtitle: "应用 / 群机器人",
    desc: "自建应用推送到成员与会话；群机器人用于群内问答。",
    icon: <Building2 size={17} />,
    capabilities: ["自建应用", "群机器人", "被动回复", "消息推送"],
    fields: [
      { key: "corp_id", label: "企业 ID（CorpID）", placeholder: "ww_xxxxxxxxxxxx", required: true },
      { key: "agent_id", label: "应用 AgentId", placeholder: "1000002", required: true },
      { key: "secret", label: "应用 Secret", secret: true, required: true },
      { key: "encoding_aes_key", label: "EncodingAESKey", secret: true, hint: "加密回调时必填；留空保持现值" },
      { key: "token", label: "回调 Token", secret: true, hint: "入站请求需带 X-DataClaw-Token" },
    ],
  },
  {
    type: "dingtalk",
    name: "钉钉",
    subtitle: "工作通知 / 机器人",
    desc: "工作通知触达个人，群机器人支持 @ 提问与卡片回复。",
    icon: <Bell size={17} />,
    capabilities: ["工作通知", "群机器人", "互动卡片", "事件回调"],
    fields: [
      { key: "app_key", label: "AppKey", placeholder: "dingxxxxxxxxxxxx", required: true },
      { key: "app_secret", label: "AppSecret", secret: true, required: true },
      { key: "token", label: "回调 Token", secret: true, hint: "入站请求需带 X-DataClaw-Token" },
    ],
  },
  {
    type: "web",
    name: "Web / H5",
    subtitle: "站内嵌入门户",
    desc: "浏览器直接访问平台即可对话，无需额外配置；V1 不限制嵌入域名。",
    icon: <Globe size={17} />,
    capabilities: ["内嵌会话", "扫码登录", "响应式 H5"],
    fields: [
      { key: "theme", label: "会话主题", options: ["light", "dark"], hint: "嵌入会话组件的默认主题" },
      { key: "defaultEmployeeId", label: "默认员工 ID", placeholder: "留空则由用户选择", hint: "打开即对话的员工（可空）" },
    ],
  },
  {
    type: "api",
    name: "API 开放",
    subtitle: "第三方系统直连",
    desc: "业务系统用 Token 直接调用 /api/channels/api/events，把数字员工接进既有工作流。",
    icon: <Code2 size={17} />,
    capabilities: ["REST / SSE", "Token 鉴权", "异步产物回调"],
    fields: [
      { key: "token", label: "访问 Token", secret: true, hint: "放在 X-DataClaw-Token 头；泄露后请立即轮换" },
      { key: "rateLimit", label: "限流（次/分钟）", numeric: true, placeholder: "60" },
    ],
  },
];

interface RequiredItem {
  key: string;
  label: string;
  value?: boolean;
}

interface ChannelDraft {
  name: string;
  enabled: boolean;
  config: Record<string, string>;
}

interface EventReply {
  reply?: string;
  sessionId?: string;
  artifactId?: string | null;
  employeeId?: string;
  employeeName?: string;
  channel?: string;
  latencyMs?: number;
  error?: string;
}

const STATUS_META: Record<string, { label: string; tone: "green" | "amber" | "gray" | "rose" }> = {
  ready: { label: "已启用", tone: "green" },
  unconfigured: { label: "未配置", tone: "amber" },
  error: { label: "配置异常", tone: "rose" },
};

function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

/** 后端把 secret 打码成 ab****yz；打码值不能回填到输入框，否则会把密钥写成星号。 */
function isMaskedValue(v: unknown): boolean {
  return typeof v === "string" && v.includes("*");
}

function fieldsOf(def: ChannelDef, server?: Channel): FieldDef[] {
  const required = (server as (Channel & { required?: RequiredItem[] }) | undefined)?.required ?? [];
  return def.fields.map((f) => {
    const req = required.find((r) => r.key === f.key);
    return {
      ...f,
      label: req?.label || f.label,
      required: req ? true : f.required,
    };
  });
}

function draftOf(def: ChannelDef, server?: Channel): ChannelDraft {
  const config: Record<string, string> = {};
  for (const f of fieldsOf(def, server)) {
    const raw = server?.config?.[f.key];
    config[f.key] = f.secret && isMaskedValue(raw) ? "" : raw === undefined || raw === null ? "" : String(raw);
  }
  return { name: server?.name || def.name, enabled: !!server?.enabled, config };
}

function missingOf(def: ChannelDef, server: Channel | undefined, draft: ChannelDraft): string[] {
  const required = (server as (Channel & { required?: RequiredItem[] }) | undefined)?.required ?? [];
  return fieldsOf(def, server)
    .filter((f) => f.required)
    .filter((f) => {
      const typed = (draft.config[f.key] || "").trim();
      const saved = required.find((r) => r.key === f.key)?.value;
      return !typed && !saved;
    })
    .map((f) => f.label);
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制");
  } catch {
    toast("复制失败，请手动复制", "error");
  }
}

/* ------------------------------------------------------------------ 页面 */

export default function Channels() {
  const [channels, setChannels] = useState<Record<string, Channel>>({});
  const [drafts, setDrafts] = useState<Record<string, ChannelDraft>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [saving, setSaving] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [replies, setReplies] = useState<Record<string, EventReply>>({});
  const [testText, setTestText] = useState<Record<string, string>>({});

  const loadChannels = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Paginated<Channel>>("/channels");
      const map: Record<string, Channel> = {};
      for (const c of res.items ?? []) map[c.type] = c;
      setChannels(map);
      const nextDrafts: Record<string, ChannelDraft> = {};
      for (const def of CHANNEL_DEFS) nextDrafts[def.type] = draftOf(def, map[def.type]);
      setDrafts(nextDrafts);
      setError(null);
    } catch (e: unknown) {
      setError(errText(e, "渠道配置加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadChannels();
  }, [loadChannels]);

  const webhookBase = useMemo(() => (typeof window === "undefined" ? "" : window.location.origin), []);

  function patchDraft(type: string, patch: Partial<ChannelDraft>) {
    setDrafts((prev) => {
      const cur = prev[type] ?? { name: type, enabled: false, config: {} };
      return { ...prev, [type]: { ...cur, ...patch } };
    });
  }

  function patchConfig(type: string, key: string, value: string) {
    setDrafts((prev) => {
      const cur = prev[type] ?? { name: type, enabled: false, config: {} };
      return { ...prev, [type]: { ...cur, config: { ...cur.config, [key]: value } } };
    });
  }

  function isDirty(def: ChannelDef): boolean {
    const draft = drafts[def.type];
    if (!draft) return false;
    return JSON.stringify(draft) !== JSON.stringify(draftOf(def, channels[def.type]));
  }

  async function saveChannel(def: ChannelDef) {
    const draft = drafts[def.type];
    if (!draft) return;
    setSaving(def.type);
    try {
      const config: Record<string, unknown> = {};
      for (const f of fieldsOf(def, channels[def.type])) {
        const value = (draft.config[f.key] || "").trim();
        if (f.secret && !value) continue; // 未改动 = 保留服务端现值
        config[f.key] = f.numeric ? Number(value) || 0 : value;
      }
      await api.post(`/channels/${def.type}`, { name: draft.name, enabled: draft.enabled, config });
      toast(`${def.name} 配置已保存`);
      await loadChannels();
    } catch (e: unknown) {
      toast(errText(e, "保存失败"), "error");
    } finally {
      setSaving(null);
    }
  }

  async function testChannel(def: ChannelDef) {
    setTesting(def.type);
    setTestResult((prev) => {
      const next = { ...prev };
      delete next[def.type];
      return next;
    });
    try {
      const res = await api.post<{ ok?: boolean; message?: string; latencyMs?: number }>(`/channels/${def.type}/test`);
      const ok = res?.ok !== false;
      setTestResult((prev) => ({
        ...prev,
        [def.type]: { ok, message: res?.message || (ok ? `连通正常${res?.latencyMs ? `（${res.latencyMs}ms）` : ""}` : "连通失败") },
      }));
      toast(ok ? `${def.name} 连通正常` : `${def.name} 连通失败`, ok ? "success" : "error");
      await loadChannels();
    } catch (e: unknown) {
      setTestResult((prev) => ({ ...prev, [def.type]: { ok: false, message: errText(e, "连通测试失败") } }));
      toast(errText(e, "连通测试失败"), "error");
    } finally {
      setTesting(null);
    }
  }

  /**
   * 真实走一次入站 webhook：POST /api/channels/{type}/events。
   * 后端免鉴权但校验 X-DataClaw-Token（DEMO_MODE 下 demo-token 可放行），因此这里手工 fetch 传头。
   */
  async function sendTestMessage(def: ChannelDef) {
    const draft = drafts[def.type];
    const text = (testText[def.type] || "").trim() || "你好，这是一条来自 DataClaw 的渠道连通性测试消息。";
    const token = (draft?.config?.token || "").trim() || "demo-token";
    setSending(def.type);
    setReplies((prev) => ({ ...prev, [def.type]: {} }));
    try {
      const authToken = getToken();
      const res = await fetch(`/api/channels/${def.type}/events`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-DataClaw-Token": token,
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ text, user: "admin" }),
      });
      const data = (await res.json().catch(() => null)) as (EventReply & { error?: { message?: string } }) | null;
      if (!res.ok) {
        throw new Error(data?.error?.message || `请求失败（${res.status}）`);
      }
      setReplies((prev) => ({ ...prev, [def.type]: data ?? {} }));
      if (data?.reply) toast("已收到数字员工回复");
    } catch (e: unknown) {
      const message = errText(e, "发送测试消息失败");
      setReplies((prev) => ({ ...prev, [def.type]: { error: message } }));
      toast(message, "error");
    } finally {
      setSending(null);
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-surface-100">
      <div className="mx-auto max-w-[1440px] space-y-5 px-6 py-5">
        <PageHeader
          title="渠道接入 · 让数字员工出现在员工已经在的地方"
          desc="飞书 / 企业微信 / 钉钉 / Web / API 五类入口。配置即生效；入站 webhook 免登录，但必须校验 X-DataClaw-Token。"
          badge={
            <Badge tone="brand" dot>
              管理员视角
            </Badge>
          }
          meta={
            <>
              <span>{Object.values(channels).filter((c) => c.enabled).length} 个渠道已启用</span>
              <span className="inline-flex items-center gap-1">
                <Plug size={11} /> 测试与发消息都走已保存的配置
              </span>
            </>
          }
          actions={
            <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadChannels()}>
              刷新
            </Button>
          }
        />

        {loading && (
          <div className="grid gap-3 xl:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[300px]" />
            ))}
          </div>
        )}

        {!loading && error && (
          <Card>
            <Empty
              icon={<ShieldAlert size={20} />}
              title="渠道配置加载失败"
              desc={`${error}。后端 /api/channels 可能尚未就绪。`}
              action={
                <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => void loadChannels()}>
                  重新加载
                </Button>
              }
            />
          </Card>
        )}

        {!loading && !error && (
          <>
            <div className="grid gap-3 xl:grid-cols-2">
              {CHANNEL_DEFS.map((def) => {
                const server = channels[def.type];
                const draft = drafts[def.type] ?? { name: def.name, enabled: false, config: {} };
                const fields = fieldsOf(def, server);
                const dirty = isDirty(def);
                const result = testResult[def.type];
                const reply = replies[def.type];
                const missing = missingOf(def, server, draft);
                const status = STATUS_META[server?.status || (server?.enabled ? "ready" : "unconfigured")] ?? STATUS_META.unconfigured;
                const webhook = `${webhookBase}${(server as (Channel & { webhook?: string }) | undefined)?.webhook || `/api/channels/${def.type}/events`}`;
                return (
                  <Card key={def.type} className="flex flex-col p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-2.5">
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600">{def.icon}</span>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-[14px] font-semibold text-ink-900">{def.name}</span>
                            <Badge tone="gray">{def.subtitle}</Badge>
                            <Badge tone={status.tone} dot>
                              {server?.enabled ? "已启用" : status.label}
                            </Badge>
                            {dirty && <Badge tone="amber">未保存</Badge>}
                          </div>
                          <p className="mt-1 text-[11.5px] leading-relaxed text-ink-500">{def.desc}</p>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <Toggle
                          checked={draft.enabled}
                          onChange={(v) => patchDraft(def.type, { enabled: v })}
                          disabled={!draft.enabled && missing.length > 0}
                        />
                        <span className="text-[10px] text-ink-400">启用</span>
                      </div>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-1">
                      {def.capabilities.map((c) => (
                        <span key={c} className="rounded-md bg-surface-100 px-1.5 py-0.5 text-[10.5px] text-ink-500">
                          {c}
                        </span>
                      ))}
                    </div>

                    <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
                      {fields.map((f) => (
                        <Field key={f.key} label={f.required ? `${f.label} *` : f.label} hint={f.hint}>
                          {f.options ? (
                            <Select value={draft.config[f.key] ?? ""} onChange={(e) => patchConfig(def.type, f.key, e.target.value)}>
                              {f.options.map((o) => (
                                <option key={o} value={o}>
                                  {o}
                                </option>
                              ))}
                            </Select>
                          ) : (
                            <Input
                              type={f.secret ? "password" : "text"}
                              value={draft.config[f.key] ?? ""}
                              placeholder={
                                f.secret && server?.config?.[f.key] ? "已配置（留空保持不变）" : f.placeholder
                              }
                              onChange={(e) => patchConfig(def.type, f.key, e.target.value)}
                            />
                          )}
                        </Field>
                      ))}
                    </div>

                    {missing.length > 0 && (
                      <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-amber-50 px-2 py-1.5 text-[11px] leading-relaxed text-amber-800">
                        <ShieldAlert size={12} className="mt-0.5 shrink-0" />
                        还缺少必填项：{missing.join("、")}。补齐并保存后才能启用。
                      </div>
                    )}

                    <div className="mt-2.5 flex flex-wrap items-center gap-1.5 rounded-lg bg-surface-50 px-2 py-1.5">
                      <span className="text-[10.5px] text-ink-400">Webhook</span>
                      <code className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-ink-700">{webhook}</code>
                      <button
                        type="button"
                        onClick={() => void copyText(webhook)}
                        className="rounded p-1 text-ink-400 hover:bg-white hover:text-ink-700"
                        title="复制 webhook 地址"
                      >
                        <Copy size={12} />
                      </button>
                    </div>

                    <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                      <Button size="sm" loading={saving === def.type} onClick={() => void saveChannel(def)}>
                        保存
                      </Button>
                      <Button variant="outline" size="sm" icon={<Plug size={12} />} loading={testing === def.type} onClick={() => void testChannel(def)}>
                        测试连接
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        icon={<Send size={12} />}
                        loading={sending === def.type}
                        onClick={() => void sendTestMessage(def)}
                      >
                        发送测试消息
                      </Button>
                      <Input
                        value={testText[def.type] ?? ""}
                        onChange={(e) => setTestText((prev) => ({ ...prev, [def.type]: e.target.value }))}
                        placeholder="测试消息内容"
                        className="ml-auto !w-[160px] !py-1 !text-[11.5px]"
                      />
                    </div>

                    {result && (
                      <div
                        className={cx(
                          "mt-2 flex items-start gap-1.5 rounded-lg px-2 py-1.5 text-[11px] leading-relaxed",
                          result.ok ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
                        )}
                      >
                        {result.ok ? <Check size={12} className="mt-0.5 shrink-0" /> : <ShieldAlert size={12} className="mt-0.5 shrink-0" />}
                        {result.message}
                      </div>
                    )}

                    {reply?.reply && (
                      <div className="mt-2 rounded-xl border border-brand-100 bg-brand-50/50 px-2.5 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[10.5px] font-medium text-brand-700">
                            数字员工回复{reply.employeeName ? ` · ${reply.employeeName}` : ""}
                          </span>
                          {typeof reply.latencyMs === "number" && <span className="text-[10px] text-ink-400">{reply.latencyMs}ms</span>}
                        </div>
                        <div className="mt-1 whitespace-pre-wrap break-words text-[11.5px] leading-relaxed text-ink-700">{reply.reply}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[10px] text-ink-400">
                          {reply.sessionId && <span>会话 {reply.sessionId.slice(-8)}</span>}
                          {reply.employeeId && <span>员工 {reply.employeeId}</span>}
                          {reply.artifactId && <span>产物 {reply.artifactId}</span>}
                          <span className="text-teal-600">端到端可达 ✓</span>
                        </div>
                      </div>
                    )}
                    {reply?.error && !reply.reply && (
                      <div className="mt-2 rounded-lg bg-rose-50 px-2 py-1.5 text-[11px] leading-relaxed text-rose-700">{reply.error}</div>
                    )}

                    {server?.lastCheckedAt && (
                      <div className="mt-2 text-[10.5px] text-ink-400">
                        最近检测 {formatDateTime(server.lastCheckedAt)} · {timeAgo(server.lastCheckedAt)}
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <Card>
                <CardHeader title="接入指引" desc="三步把一个渠道跑通" />
                <div className="space-y-2.5 px-4 pb-4">
                  {[
                    { n: 1, t: "在渠道侧创建应用 / 机器人", d: "拿到 App ID / Secret / Verification Token 等凭据，开启消息与事件权限。" },
                    { n: 2, t: "回到本页填配置并保存", d: "保存后立即生效；点「测试连接」验证凭据，缺必填项会明确提示。" },
                    { n: 3, t: "把 webhook 地址填回渠道侧", d: "订阅消息事件，再点「发送测试消息」走一次真实的入站回调，确认能收到回复。" },
                  ].map((s) => (
                    <div key={s.n} className="flex items-start gap-2.5">
                      <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-50 text-[11px] font-semibold text-brand-700">
                        {s.n}
                      </span>
                      <div className="min-w-0">
                        <div className="text-[12.5px] font-medium text-ink-900">{s.t}</div>
                        <div className="mt-0.5 text-[11.5px] leading-relaxed text-ink-500">{s.d}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>

              <Card>
                <CardHeader title="安全提示" desc="开放入口但不开权限" />
                <div className="space-y-2 px-4 pb-4">
                  {[
                    { t: "回调必须校验 token", d: "入站 webhook 免登录，靠 X-DataClaw-Token 与渠道 config.token 比对；不匹配直接 401 并记 denied 审计。" },
                    { t: "出站只允许白名单域名", d: "避免数字员工把数据推给未授权的外部地址；白名单由管理员维护。" },
                    { t: "凭据不落前端", d: "Secret 只写库内、只用于服务端调用；接口下发时已打码，前端不会回填星号。" },
                    { t: "全链路留痕", d: "渠道测试、配置变更、入站消息都会写入审计（channel_test / channel_config / channel_inbound）。" },
                  ].map((s) => (
                    <div key={s.t} className="flex items-start gap-2">
                      <ShieldCheck size={13} className="mt-0.5 shrink-0 text-teal-600" />
                      <div className="min-w-0">
                        <div className="text-[12px] font-medium text-ink-900">{s.t}</div>
                        <div className="mt-0.5 text-[11.5px] leading-relaxed text-ink-500">{s.d}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
