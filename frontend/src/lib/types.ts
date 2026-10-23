export type Role = "platform_admin" | "dept_admin" | "member";

export interface User {
  id: string;
  username: string;
  name: string;
  email?: string;
  role: Role;
  dept?: string;
  title?: string;
  avatar?: string;
  status?: string;
  memoryEnabled?: boolean;
  lastLoginAt?: string | null;
  employeeCount?: number;
}

export interface Template {
  id: string;
  code: string;
  name: string;
  roleTitle: string;
  avatar?: string;
  description: string;
  soulMd?: string;
  defaultSkills?: string[];
  category?: string;
}

export interface EmployeeSkillRef {
  id: string;
  name: string;
  displayName: string;
  icon?: string;
  category?: string;
  enabled: boolean;
  riskLevel?: string;
}

export interface Employee {
  id: string;
  ownerId: string;
  name: string;
  roleTitle?: string;
  avatar?: string;
  soulMd?: string;
  greeting?: string;
  templateId?: string | null;
  source: "personal" | "from_public";
  publicAgentId?: string | null;
  memoryEnabled: boolean;
  status?: string;
  lastActiveAt?: string | null;
  description?: string;
  skillCount?: number;
  sessionCount?: number;
  skills?: EmployeeSkillRef[];
  memory?: MemoryItem[];
  stats?: { sessions?: number; toolCalls?: number; artifacts?: number; lastActiveAt?: string | null };
  publicAgent?: { id: string; name: string; version: number } | null;
}

export interface MemoryItem {
  id: string;
  kind: string;
  content: string;
  createdAt: string;
}

export interface Skill {
  id: string;
  name: string;
  displayName: string;
  description: string;
  content?: string;
  category: string;
  source: "builtin" | "user";
  status: "approved" | "pending" | "rejected";
  version: string;
  riskLevel: "low" | "medium" | "high";
  installs: number;
  icon?: string;
  tags?: string[];
  toolNames?: string[];
  installed?: boolean;
  ownerId?: string | null;
  ownerName?: string;
  updatedAt?: string;
  scan?: { riskLevel?: string; findings?: { pattern: string; line: number; snippet: string; severity: string }[] };
}

export interface PublicAgent {
  id: string;
  name: string;
  roleTitle?: string;
  avatar?: string;
  description: string;
  soulMd?: string;
  version: number;
  status: string;
  skillCount?: number;
  assigneeCount?: number;
  sessionCount?: number;
  updatedAt?: string;
  tags?: string[];
  /** 后端额外返回 */
  skills?: string[];
  pendingSync?: boolean;
  publishedAt?: string;
  createdBy?: string;
}

export interface SessionItem {
  id: string;
  employeeId: string;
  title: string;
  pinned?: boolean;
  messageCount?: number;
  lastMessageAt?: string;
  employeeName?: string;
  employeeAvatar?: string;
}

export type StepItem = {
  id: string;
  type: "tool_call" | "tool_result" | "thinking" | "approval" | "plan";
  tool?: string;
  title: string;
  status: "running" | "done" | "error" | "pending";
  input?: any;
  output?: any;
  summary?: string;
  durationMs?: number;
  risk?: string;
};

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  steps?: StepItem[];
  artifacts?: ArtifactRef[];
  createdAt?: string;
  latencyMs?: number;
  streaming?: boolean;
}

export interface ArtifactRef {
  id: string;
  kind: "dashboard" | "report" | "docx" | "html" | "json";
  title: string;
  preview?: any;
  payload?: any;
  text?: string;
  fileName?: string;
  filePath?: string;
  downloadUrl?: string;
}

export interface DashboardPayload {
  type: "dashboard";
  title: string;
  subtitle?: string;
  kpis: { label: string; value: string; delta?: string; trend?: "up" | "down" | "flat"; hint?: string }[];
  charts: { id: string; type: string; title?: string; option: any; height?: number }[];
  insights: { level: "info" | "warn" | "risk" | "good"; text: string }[];
  source?: { datasource?: string; sql?: string; rewrittenSql?: string; rows?: number; maskedColumns?: string[] };
}

export interface ReportPayload {
  type: "report";
  markdown: string;
  meta?: Record<string, any>;
}

export interface DocxPayload {
  type: "docx";
  fileName: string;
  filePath?: string;
  downloadUrl?: string;
  stats?: { risks?: number; high?: number; medium?: number; low?: number };
  redlines?: { clause: string; title?: string; risk: string; issue: string; suggestion: string; original?: string }[];
}

export interface DataSource {
  id: string;
  name: string;
  type: string;
  host?: string;
  database?: string;
  status: string;
  description?: string;
  tableCount?: number;
  rowCount?: number;
}

export interface ColumnMeta {
  name: string;
  type: string;
  comment?: string;
  sensitiveLevel: "public" | "internal" | "secret" | "top_secret";
  category?: string;
  allowed?: boolean;
  mask?: string;
}

export interface Policy {
  id: string;
  subjectType: "user" | "role";
  subjectId: string;
  subjectName?: string;
  resourceType: "datasource" | "table" | "column" | "metric" | "row";
  resourceId: string;
  action: "allow" | "deny";
  mask: "none" | "mask" | "hash" | "replace" | "truncate";
  maskParam?: Record<string, any>;
  rowFilter?: string;
  priority: number;
  enabled: boolean;
  note?: string;
}

export interface KnowledgeDoc {
  id: string;
  name: string;
  type: string;
  mime?: string;
  size?: number;
  status: string;
  ownerId?: string;
  ownerName?: string;
  dept?: string;
  tags?: string[];
  chunkCount?: number;
  sensitiveLevel?: string;
  createdAt?: string;
  chunks?: { seq: number; text: string }[];
}

export interface AuditEvent {
  id: string;
  ts: string;
  actorName: string;
  actorId?: string;
  action: string;
  actionLabel?: string;
  targetType?: string;
  targetName?: string;
  detail?: any;
  risk: "low" | "medium" | "high";
  result: "success" | "denied" | "error";
  ip?: string;
  sessionId?: string;
}

export interface Channel {
  type: string;
  name: string;
  enabled: boolean;
  config: Record<string, any>;
  status: string;
  lastCheckedAt?: string | null;
  required?: { key: string; label: string; value?: boolean }[];
  webhookPath?: string;
}

export interface OverviewStats {
  stats: {
    employees: number;
    sessions: number;
    messages: number;
    toolCalls: number;
    denied: number;
    skills: number;
    users: number;
    activeUsers: number;
    /** 后端额外返回的聚合项（可选） */
    auditEvents?: number;
    highRisk?: number;
    knowledgeDocs?: number;
    policies?: number;
    chunks?: number;
  };
  trend: { date: string; sessions: number; toolCalls: number }[];
  topEmployees: { id: string; name: string; avatar?: string; sessions: number; toolCalls?: number }[];
  recentAudit: AuditEvent[];
  riskDistribution: { risk: string; count: number }[];
  /** 实际结构：按 action 聚合（label 为中文） */
  scenarioStats?: { action?: string; label?: string; count: number; name?: string; key?: string }[];
  dataStats?: Record<string, any>;
  days?: number;
  generatedAt?: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page?: number;
  size?: number;
}
