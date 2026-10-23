export function cx(...args: (string | false | null | undefined)[]): string {
  return args.filter(Boolean).join(" ");
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = Date.now() - t;
  if (diff < 0) return "刚刚";
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function formatNumber(n?: number | null, digits = 0): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function compactNumber(n?: number | null): string {
  if (n === undefined || n === null) return "—";
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(1)} 万`;
  return formatNumber(n);
}

export function fileSize(bytes?: number): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function initials(name?: string): string {
  if (!name) return "?";
  const s = name.trim();
  if (s.length <= 2) return s;
  // 人名取后两字（林知微→知微）；较长的角色/岗位名取前两字（运营数据分析师→运营）
  return s.length <= 4 ? s.slice(-2) : s.slice(0, 2);
}

const AVATAR_COLORS = [
  ["#EEF2FF", "#4F46E5"],
  ["#ECFDF5", "#047857"],
  ["#FFF7ED", "#C2410C"],
  ["#F0F9FF", "#0369A1"],
  ["#FDF2F8", "#BE185D"],
  ["#F5F3FF", "#6D28D9"],
  ["#FEFCE8", "#A16207"],
  ["#F0FDFA", "#0F766E"],
];

export function avatarPalette(seed?: string): { bg: string; fg: string } {
  const s = seed || "x";
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  const [bg, fg] = AVATAR_COLORS[h % AVATAR_COLORS.length];
  return { bg, fg };
}

export const riskColor: Record<string, string> = {
  low: "text-emerald-600 bg-emerald-50 border-emerald-100",
  medium: "text-amber-600 bg-amber-50 border-amber-100",
  high: "text-rose-600 bg-rose-50 border-rose-100",
};

export function riskBadgeClass(risk?: string): string {
  return `${riskColor[risk || "low"] || riskColor.low} whitespace-nowrap`;
}

export const statusLabel: Record<string, string> = {
  approved: "已审核",
  pending: "待审核",
  rejected: "已驳回",
  published: "已发布",
  draft: "草稿",
  offline: "已下架",
  active: "正常",
  disabled: "已停用",
  connected: "已连接",
  error: "连接异常",
  ready: "就绪",
  unconfigured: "未配置",
  failed: "处理失败",
  success: "成功",
  denied: "已拒绝",
};

export function actionLabel(action: string): string {
  const map: Record<string, string> = {
    login: "登录",
    logout: "登出",
    chat: "会话提问",
    tool_call: "工具调用",
    sql_query: "数据查询",
    export: "导出文件",
    skill_install: "技能安装",
    skill_upload: "技能上传",
    skill_review: "技能审核",
    agent_assign: "公共员工分配",
    policy_change: "权限变更",
    doc_upload: "文档上传",
    doc_read: "文档读取",
    hitl_approval: "人工审批",
    channel_test: "渠道测试",
    channel_inbound: "渠道消息",
    employee_create: "创建员工",
    employee_update: "更新员工",
  };
  return map[action] || action;
}
