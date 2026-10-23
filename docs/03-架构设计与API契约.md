# DataClaw 企业级数字员工平台 — 架构设计与 API 契约

> 版本：v1.0（实现基线）｜作者：Lead｜适用范围：本仓库全部代码
> 依据：`docs/01-PRD.md`（来自 DataClaw_V1.0.pdf）＋ `docs/02-技术调研报告.md`（开源选型）
> **本文件是前后端并行开发的唯一契约。字段/路径不一致时以本文件为准；确需变更先改本文件。**

---

## 1. 目标与非目标

### 1.1 目标（V1 可运行原型，必须全部可见可点）
1. **数字员工**：模板一键创建、SOUL.md 设定、记忆开关、技能配置、头像/形象。
2. **公共员工**：管理员统一定义 → 版本管理 → 一键分配给业务用户 → 用户侧出现专属副本（含用户级记忆）。
3. **技能超市**：内置企业级技能 + 用户级技能（隔离）+ SKILL.md 在线查看 + 安装/卸载 + 安全审核状态 + 资产沉淀。
4. **会话即交付**：一句话 → 流式回答 + 工具调用可视化 → 真实产物（ECharts 大屏 / Markdown 深度报告 / 带修订痕迹的 docx / 结构化拜访指南）。
5. **数据安全可控**：数据源/表/字段/指标四级访问策略 + 4 种脱敏（mask/hash/replace/truncate）+ 行级过滤 + 敏感分级 + **SQL AST 级改写** + 全链路审计。
6. **知识中台**：文档上传解析、切片、检索（含文档权限）。
7. **渠道接入**：飞书/企微/钉钉/Web/API 的配置与连通性测试 + 一个可用的入站 webhook。
8. **管理后台**：用户/角色、公共员工、技能、数据权限、知识库、渠道、审计、总览。

### 1.2 非目标（V1 不做，文档中给出演进路径）
真实企业 SSO/LDAP、真实 K8s 多租户调度、真实 Firecracker/gVisor 隔离、真实 IM 双向长连接、计费结算、移动 App 原生端、向量数据库集群、多活高可用。
> V1 用「可替换适配器」把这些留成接口：`runtime/sandbox.py`、`runtime/llm.py`、`services/channels.py` 均定义 Provider 接口 + 本地实现。

### 1.3 技术栈（与调研报告选型结论一致）
| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2 + Pydantic v2 | 数据/文档生态最强（pandas、python-docx、pymupdf） |
| 数据库 | SQLite（WAL）→ PostgreSQL 可平滑切换 | 零依赖演示；SQLAlchemy 方言无关 |
| 鉴权 | 自签 JWT（HS256）+ PBKDF2 口令散列 | 无外部依赖，接口与企业 SSO 对齐 |
| SQL 安全 | **sqlglot** AST 解析改写 | 行/列级权限注入与脱敏重写，源于 ShardingSphere/Ranger 思路（见 02 报告 5.3） |
| Agent 运行时 | **自研轻量循环**（Provider 抽象 + Tool Registry + SSE） | 调研结论：Dify/Coze 的编排层过重且改写成本高；运行时是本项目护城河，自研 |
| LLM | OpenAI-Compatible Provider；**无 Key 时启用内置确定性 Planner** | 演示可离线跑通，三条标杆场景产物由真实工具链生成 |
| 前端 | Vite + React 18 + TypeScript + Tailwind + ECharts + lucide-react | 构建快、组件自由度高 |
| 沙箱 | 进程级 Workspace 隔离（本地 Provider）→ Docker/OpenSandbox Provider 接口 | V1 可运行，V2 接容器 |

---

## 2. 系统架构

```
┌──────────────────────────── 前端 (Vite/React) ────────────────────────────┐
│ 工作台：会话(SSE) / 员工 / 技能超市 / 任务 / 文件    管理后台：用户·公共员工· │
│                                                       数据权限·知识·渠道·审计 │
└───────────────┬───────────────────────────────────────────┬───────────────┘
                │ /api (JWT Bearer)                          │ SSE
┌───────────────▼───────────────────────────────────────────▼───────────────┐
│ FastAPI 应用层                                                            │
│  auth │ users │ employees │ public-agents │ skills │ templates │ audit     │
│  sessions(SSE) │ artifacts │ files │ knowledge │ datasources │ policies    │
│  channels(webhook) │ overview                                            │
├───────────────────────────────────────────────────────────────────────────┤
│ 领域服务层 services/                                                       │
│  employee_service │ skill_service │ assignment_service │ audit_service     │
│  policy_service(权限解析器) │ knowledge_service(切片/检索) │ channel_service│
├───────────────────────────────────────────────────────────────────────────┤
│ Agent 运行时 runtime/                                                      │
│  runner(循环/SSE) │ llm(Provider) │ planner(离线确定性) │ tools/*          │
│  sandbox(Workspace Provider) │ sqlguard(sqlglot 改写) │ artifacts(产物)   │
├───────────────────────────────────────────────────────────────────────────┤
│ 基础设施：SQLAlchemy Models │ SQLite/Postgres │ 本地文件存储(uploads/artifacts)│
│          audit_events(全链路) │ 演示数据 seed(工时/CRM/合同/知识库)         │
└───────────────────────────────────────────────────────────────────────────┘
```

### 2.1 与 PDF「产品架构」的映射
| PDF 层 | 本实现 |
|---|---|
| 知识中台·权限管理（文档/数据权限） | `doc_acls` + `policies` + `policy_service` |
| 知识中台·非结构化（文档/图片/邮件） | `knowledge_docs/chunks` + 上传解析 + 检索 |
| 知识中台·结构化（数据库/报表指标） | `datasources/tables/columns` + `metrics` + chatbi 工具 |
| 知识中台·↑Skill 统一输出 | 所有能力以 Skill 暴露（`skills`），运行时按员工已装技能装载工具 |
| 用户级隔离 Workspace | 每员工一目录 `data/workspaces/{employee_id}/`（sandbox 接口） |
| 公共小龙虾池→一键分配 | `public_agents` + `assignments` → 生成员工副本 |
| 统一 AI 员工管理 | `templates` + 管理后台「公共员工」 |
| 安全沙箱/容器运行时 | `runtime/sandbox.py`：LocalProvider（V1）/ DockerProvider（接口） |
| Channel 接入 | `channels` + `/api/channels/{type}/events` webhook + 出站消息适配器 |
| 物理隔离层 | 容器化部署（docker-compose 附录 A）+ 操作仅限 Workspace + HITL 审批 |
| 权限隔离层 | JWT 身份 + RBAC + Agent 权限继承绑定用户 + `audit_events` 全链路追溯 |

---

## 3. 目录与开发边界（并行开发的分工线）

```
C:\dataclaw\
├─ docs\                         # 00/01/02/03/04 文档
├─ backend\
│  ├─ requirements.txt
│  ├─ app\
│  │  ├─ main.py                 # 【Lead】应用组装、静态托管、health
│  │  ├─ core\{config,db,security,deps}.py  # 【Lead】
│  │  ├─ models.py               # 【Lead】全部 ORM 模型（契约，勿改结构）
│  │  ├─ api\{auth,users,employees,public_agents,skills,templates,audit}.py   # 【be-core】
│  │  ├─ api\{sessions,artifacts,files,knowledge,datasources,policies,channels,overview}.py # 【be-runtime】
│  │  ├─ services\{employee,skill,assignment,audit}*.py      # 【be-core】
│  │  ├─ services\{policy,knowledge,channel,stats}*.py       # 【be-runtime】
│  │  ├─ runtime\{runner,llm,planner,registry,sqlguard,sandbox,artifacts}.py  # 【be-runtime】
│  │  ├─ runtime\tools\*.py                                   # 【be-runtime】
│  │  └─ seed\{__init__,demo_data}.py                         # 【be-runtime】
│  └─ tests\
├─ frontend\
│  ├─ src\main.tsx / App.tsx / index.css / lib\{api,types,format}.ts / components\ui\*  # 【Lead】
│  ├─ src\components\{layout,chat}\*                          # 【fe-workspace】
│  ├─ src\pages\{Chat,Employees,Skills,Files}.tsx             # 【fe-workspace】
│  └─ src\pages\admin\*                                       # 【fe-admin】
├─ scripts\{dev.ps1,build.ps1,run.ps1}
└─ data\{app.db,uploads,artifacts,workspaces}
```

**写权限纪律**：只写自己名下的文件；需要跨域改动时 `send_message` 给对应 owner 或 lead。共用文件（models.py / main.py / api.ts / types.ts）只能由 Lead 修改。

---

## 4. 数据模型（`app/models.py` 实现，此处为字段契约）

通用：主键 `id` 为字符串（ULID/UUID hex）；时间 `created_at/updated_at`（UTC，ISO8601 带 Z 输出）。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `users` | username, name, email, password_hash, role(`platform_admin\|dept_admin\|member`), dept, avatar, status(`active\|disabled`), memory_enabled | 企业用户（V1 单租户，预留 `tenant_id`） |
| `templates` | code, name, role_title, avatar, description, soul_md, default_skills(JSON), category | 员工角色模板（林知微/程景舟/顾守正/自定义…） |
| `employees` | owner_id, name, avatar, soul_md, role_title, template_id, source(`personal\|from_public`), public_agent_id, memory_enabled, status, last_active_at | 数字员工；`owner_id` = 归属用户 |
| `employee_skills` | employee_id, skill_id, enabled | 员工已装技能 |
| `public_agents` | name, avatar, role_title, description, soul_md, default_skills(JSON), version(int), status(`draft\|published`), created_by, published_at, stats | 公共员工（管理员维护） |
| `assignments` | public_agent_id, user_id, employee_id, created_at | 公共员工→业务用户分配记录 |
| `skills` | name, display_name, description, content(SKILL.md 全文), category, source(`builtin\|user`), owner_id(nullable), status(`approved\|pending\|rejected`), version, risk_level(`low\|medium\|high`), installs(int), icon, tags(JSON), tool_names(JSON) | 技能超市条目 |
| `skill_installs` | user_id, skill_id, employee_id(nullable), installed_at | 用户级安装（隔离维度：user） |
| `sessions` | employee_id, user_id, title, status, last_message_at, message_count, pinned | 会话 |
| `messages` | session_id, role(`user\|assistant\|system`), content, steps(JSON), artifacts(JSON), tokens, latency_ms, created_at | 会话消息（steps 存工具调用轨迹，便于回放） |
| `tool_calls` | session_id, message_id, step_id, tool, title, input(JSON), output(JSON), status, risk, approval(`none\|pending\|approved\|rejected`), duration_ms | 工具调用审计（与 steps 同步落库） |
| `artifacts` | kind(`dashboard\|report\|docx\|html\|json`), title, payload(JSON/文本), file_path, session_id, employee_id, created_at | 交付物 |
| `files` | name, path, size, mime, kind, uploaded_by, doc_id(nullable) | 上传文件 |
| `datasources` | name, type(`sqlite\|mysql\|pg\|hive\|excel\|bi`), host/port/db/user/config(JSON), status(`connected\|error`), owner_id, description | 数据源（V1 内置 demo SQLite） |
| `table_meta` | datasource_id, name, comment, row_count | 表元数据 |
| `column_meta` | datasource_id, table_name, name, type, comment, sensitive_level(`public\|internal\|secret\|top_secret`), category(标签) | 字段元数据（含分级） |
| `metrics` | name, code, description, expression, owner_id, datasource_id | 指标 |
| `policies` | subject_type(`user\|role`), subject_id, resource_type(`datasource\|table\|column\|metric\|row`), resource_id, action(`allow\|deny`), mask(`none\|mask\|hash\|replace\|truncate`), mask_param(JSON: keep/replace_with/start/end), row_filter(SQL 片段), priority | 统一权限策略 |
| `doc_acls` | doc_id, subject_type, subject_id, can_read(bool) | 文档权限 |
| `knowledge_docs` | name, type(`doc\|wiki\|image\|audio\|email\|chat`), mime, size, path, text, status, owner_id, dept, tags(JSON), chunk_count | 知识中台文档 |
| `knowledge_chunks` | doc_id, seq, text, tokens, meta(JSON) | 切片 |
| `audit_events` | id, ts, actor_id, actor_name, action(`login\|logout\|chat\|tool_call\|sql_query\|export\|skill_install\|skill_upload\|agent_assign\|policy_change\|doc_upload\|doc_read\|hitl_approval\|channel_test`), target_type, target_id, target_name, detail(JSON), risk(`low\|medium\|high`), ip, result(`success\|denied\|error`), session_id | 全链路审计（含 denied） |
| `channels` | type(`feishu\|wecom\|dingtalk\|web\|api`), name, enabled, config(JSON), status, last_checked_at | 渠道接入 |
| `memories` | employee_id, kind(`fact\|preference\|playbook`), content, source_session_id, created_at | 用户级记忆（按员工隔离） |
| `approvals` | session_id, message_id, step_id, action, reason, risk, status(`pending\|approved\|rejected`), decided_by, decided_at | HITL 审批 |

索引：`employees(owner_id)`、`sessions(employee_id,user_id)`、`messages(session_id,created_at)`、`audit_events(ts)`、`policies(subject_type,subject_id)`、`knowledge_chunks(doc_id)`。

---

## 5. 鉴权与权限模型

### 5.1 认证
- `POST /api/auth/login {username, password}` → `{token, user}`；token 为 HS256 JWT，`sub=user.id`，有效期 12h。
- 所有 `/api/**`（除 login、health、`/api/channels/*/events`）要求 `Authorization: Bearer <token>`。
- `GET /api/auth/me` → 当前用户 + 权限摘要。

### 5.2 RBAC
| 能力 | platform_admin | dept_admin | member |
|---|---|---|---|
| 用户/角色管理、公共员工、技能审核、策略、渠道 | ✅ | 仅本部门 | ❌ |
| 数据权限策略查看 | 全部 | 本部门 | 仅自己生效结果 |
| 审计日志 | 全部 | 本部门 | 仅自己的 |
| 数字员工/会话/技能安装 | ✅ | ✅ | ✅ |

### 5.3 数据权限求值（`policy_service.resolve(user, datasource, table, column)`）
1. 收集命中策略：`(subject_type=user, subject_id=uid)` 优先于 `(role, user.role)`；`priority` 大者优先。
2. 默认拒绝：无任何 `allow` 的表 → 不可见；列默认可见（除非被 `deny` 或数据源要求显式授权）。
3. 行级：所有命中 `resource_type=row` 的 `row_filter` 以 `AND` 合并，注入 WHERE。
4. 脱敏：命中列的 `mask` 生效；`none` 保留原值。
5. 敏感分级兜底：`top_secret` 列在无显式 `allow` 时按 `mask` 处理。
6. 每次求值结果写入 `audit_events(detail.rules)` —— 可解释、可追溯。

### 5.4 Agent 权限继承（PDF「权限隔离层」）
运行时以**会话发起用户**身份执行工具：`runner` 携带 `ctx.user`，所有数据工具调用 `policy_service`。员工本身不带权限，只带技能；因此 `admin` 创建的公共员工分配给 `analyst` 后，analyst 看不到 admin 能看的数据列——这就是"权限严格继承自绑定用户"。

---

## 6. SQL 安全网关（`runtime/sqlguard.py`）

```python
guard(sql: str, ctx: GuardContext) -> GuardResult
# GuardResult(sql, columns, masked_columns, applied_rules, denied_reason)
```
规则：
1. 只允许单条 `SELECT`（含 WITH）；出现 DML/DDL/多语句/`into outfile`/`pragma` → 拒绝并审计 `result=denied`。
2. 强制 `LIMIT`（默认 500，最大 2000）。
3. 表级：未授权表 → 拒绝（返回可解释原因，而不是空结果）。
4. 列级：`SELECT *` 自动展开为授权列；未授权列直接剔除并在 `applied_rules` 标注。
5. 行级：`row_filter` 作为 `AND` 条件注入（sqlglot AST 的 where 节点），不依赖字符串拼接。
6. 脱敏：结果集后处理（mask: `138****8000`；hash: `sha256:前 12 位`；replace: 常量；truncate: `前 N 位…`），并标记 `masked_columns` 供前端显示"已脱敏"角标。
7. 查询耗时/行数/改写前后 SQL 全量入审计。

---

## 7. Agent 运行时

### 7.1 一次会话执行流程
```
POST /api/sessions/{id}/messages  (SSE)
 1. 载入 employee（soul/skills/memory）+ user（身份/策略）
 2. 组装 System Prompt = SOUL.md + 记忆 + 已装技能描述 + 数据权限摘要 + 输出规范
 3. Planner 决策：LLM Provider（有 Key）或 OfflinePlanner（无 Key）
 4. 循环：tool_call → 权限校验 → HITL 审批(可选) → 执行 → tool_result → 继续
 5. 产物落 artifacts 表；步骤落 messages.steps / tool_calls
 6. 流式回传：start → delta* → step* → artifact* → done
```
- 硬约束：单轮最多 12 步、总时长 180s、单工具超时 60s；超限以 `error` 事件收尾。
- 所有工具调用必须落 `tool_calls` + `audit_events`（成功与失败都落）。

### 7.2 SSE 事件协议（`text/event-stream`，`Content-Type: text/event-stream`）
每次事件形如 `event: <type>\ndata: <json>\n\n`。前端按 `type` 分发。
| type | data 示例 | 说明 |
|---|---|---|
| `start` | `{"messageId":"m1","sessionId":"s1"}` | 开始 |
| `delta` | `{"text":"正在"}` | 增量文本 |
| `step` | `{"id":"st_1","type":"tool_call","tool":"chatbi.ask","title":"执行 SQL 查询","status":"running","input":{"question":"..."},"risk":"low"}` | 工具步骤（同 id 后续覆盖更新） |
| `step` | `{"id":"st_1","type":"tool_result","status":"done","output":{...},"durationMs":812,"summary":"返回 128 行"}` | 步骤完成 |
| `artifact` | `{"artifactId":"a1","kind":"dashboard","title":"上季度工时分析大屏","preview":{...}}` | 产物（preview 见 §8） |
| `approval` | `{"approvalId":"ap1","stepId":"st_3","action":"export_docx","reason":"将导出含企业条款的修订版文件","risk":"high"}` | 需人工审批，流挂起 |
| `error` | `{"message":"...","code":"TOOL_DENIED"}` | 出错（随后 done） |
| `done` | `{"messageId":"m1","usage":{"tokens":1234,"steps":3},"latencyMs":5200}` | 结束 |
> 审批：前端弹窗 → `POST /api/sessions/{sid}/approvals/{approvalId} {decision:"approved"|"rejected"}` → 服务端唤醒挂起的流继续（拒绝则跳过该步并在回答中说明）。

### 7.3 产物 preview 结构（前端按 kind 渲染）
- `dashboard`：`{"type":"dashboard","title":"...","subtitle":"...","kpis":[{"label":"人均工时","value":"168.2","delta":"+3.1%","trend":"up"}],"charts":[{"id":"c1","type":"heatmap\|bar\|line\|pie\|table","title":"...","option":{…ECharts option…}}],"insights":[{"level":"warn","text":"..."}],"source":{"datasource":"...","sql":"...","rows":128}}`
- `report`：`{"type":"report","markdown":"## ...","meta":{...}}`
- `docx`：`{"type":"docx","fileName":"合同审查-XX.docx","filePath":"...","downloadUrl":"/api/artifacts/{id}/download","stats":{"risks":7,"high":2},"redlines":[{"clause":"第 5.2 条","risk":"high","issue":"...","suggestion":"...","original":"..."}]}`
- `html`：`{"type":"html","html":"..."}`（如拜访指南卡片）

---

## 8. REST API 契约

约定：请求/响应 `application/json`；列表统一 `{items:[], total:int}`；错误 `{error:{code,message,detail?}}` + 4xx/5xx；时间 ISO8601。

### 8.1 认证
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | `{username,password}` → `{token,user}` |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/auth/logout` | 审计登出（无状态，仅记审计） |

### 8.2 用户与角色
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/users?keyword=&role=&page=` | 用户列表（admin） |
| POST | `/api/users` | 新建 `{username,name,email,role,dept,password}` |
| PATCH | `/api/users/{id}` | 改角色/状态/部门 |
| POST | `/api/users/{id}/reset-password` | 重置口令 |
| GET | `/api/roles` | 角色与能力矩阵 |

### 8.3 员工
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/templates` | 角色模板列表 |
| GET | `/api/employees?scope=mine\|public\|all&keyword=` | 我的员工 / 公共员工（分配给我的） |
| POST | `/api/employees` | `{name,templateId?,avatar,roleTitle,soul,skills[]}` |
| GET | `/api/employees/{id}` | 详情（含 skills、memory 摘要、统计） |
| PATCH | `/api/employees/{id}` | 改名/形象/SOUL/记忆开关 |
| DELETE | `/api/employees/{id}` | 删除（软删） |
| POST | `/api/employees/{id}/skills` | `{skillId,enabled}` 配置技能 |
| GET | `/api/employees/{id}/memory` | 记忆列表 |
| DELETE | `/api/employees/{id}/memory/{mid}` | 删除单条记忆 |
| POST | `/api/employees/{id}/duplicate` | 复制为「我的」副本 |

### 8.4 公共员工
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/public-agents` | 列表（含已分配人数、版本、技能数） |
| POST | `/api/public-agents` | 创建（管理员） |
| PATCH | `/api/public-agents/{id}` | 编辑（版本+1 并标记待同步） |
| POST | `/api/public-agents/{id}/publish` | 发布新版本 → 同步到已分配用户副本 |
| DELETE | `/api/public-agents/{id}` | 下架 |
| POST | `/api/public-agents/{id}/assign` | `{userIds:[]}` → 为每个用户生成员工副本，返回 `{created,skipped}` |
| GET | `/api/public-agents/{id}/assignments` | 分配明细 |
| DELETE | `/api/public-agents/{id}/assign/{userId}` | 取消分配（解除副本） |

### 8.5 技能超市
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/skills?tab=installed\|market\|mine&keyword=&category=` | 列表（含 installed 标记） |
| GET | `/api/skills/{id}` | 详情（content = SKILL.md 全文） |
| POST | `/api/skills/{id}/install` | 安装到当前用户（可选 employeeId） |
| POST | `/api/skills/{id}/uninstall` | 卸载 |
| POST | `/api/skills` | 用户级技能创建 `{displayName,description,content,tags}`（source=user, status=pending） |
| PUT | `/api/skills/{id}` | 编辑（仅 owner/admin） |
| DELETE | `/api/skills/{id}` | 删除（仅 owner/admin） |
| POST | `/api/skills/{id}/review` | `{status:approved\|rejected}`（管理员审核） |
| POST | `/api/skills/{id}/scan` | 触发安全扫描 → `{riskLevel,findings[]}` |

### 8.6 会话与产物
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sessions?employeeId=&keyword=` | 会话列表 |
| POST | `/api/sessions` | `{employeeId,title?}` |
| GET | `/api/sessions/{id}` | 会话详情 + messages |
| PATCH | `/api/sessions/{id}` | 重命名/置顶 |
| DELETE | `/api/sessions/{id}` | 删除 |
| POST | `/api/sessions/{id}/messages` | **SSE**，`{content, attachments?:[{fileId}]}`（也接受 `{content}` 直接返回 JSON：`?stream=false`） |
| POST | `/api/sessions/{sid}/approvals/{approvalId}` | `{decision}` |
| GET | `/api/artifacts?sessionId=&kind=` | 产物列表 |
| GET | `/api/artifacts/{id}` | 产物（payload） |
| GET | `/api/artifacts/{id}/download` | 下载（docx/xlsx/md） |

### 8.7 文件
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/files` | multipart 上传 → `{fileId,name,size,mime}` |
| GET | `/api/files?tab=mine\|shared` | 文件列表 |
| GET | `/api/files/{id}/download` | 下载 |

### 8.8 知识中台
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/knowledge/docs?type=&keyword=` | 文档列表（按权限过滤） |
| POST | `/api/knowledge/docs` | multipart 上传 + 解析 + 切片（`type` 可选） |
| GET | `/api/knowledge/docs/{id}` | 详情（含切片前 20 条） |
| DELETE | `/api/knowledge/docs/{id}` | 删除 |
| POST | `/api/knowledge/search` | `{query,topK?}` → `{items:[{docId,docName,seq,snippet,score}], rules}` |
| GET | `/api/knowledge/docs/{id}/acl` | 文档 ACL |
| POST | `/api/knowledge/docs/{id}/acl` | `{subjectType,subjectId,canRead}` |

### 8.9 数据与权限
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/datasources` | 数据源列表（含表数、状态） |
| POST | `/api/datasources` | 创建（sqlite/mysql/pg 连接串；V1 内置 demo） |
| POST | `/api/datasources/{id}/test` | 连通性测试 |
| GET | `/api/datasources/{id}/tables` | 表元数据（按权限过滤） |
| GET | `/api/datasources/{id}/tables/{table}/columns` | 字段元数据 |
| GET | `/api/metrics` | 指标列表 |
| GET | `/api/policies?subjectType=&subjectId=` | 策略列表 |
| POST | `/api/policies` | 新建/更新策略 |
| DELETE | `/api/policies/{id}` | 删除 |
| GET | `/api/policies/effective?userId=` | **生效矩阵**（用户 × 表 × 列 × 行 × 脱敏） |
| POST | `/api/policies/preview` | `{datasourceId,sql,userId?}` → `{rewrittenSql,appliedRules,columns,rows,maskedColumns,deniedReason}` |
| GET | `/api/classifications` | 敏感分级汇总（按表/列统计数量） |

### 8.10 渠道
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/channels` | 渠道列表与配置状态（每项含 `required:[{key,label}]` 供前端动态渲染表单） |
| POST | `/api/channels/{type}` | 保存配置 `{name,enabled,config}`；缺必填字段 → 400 + `missing[]` |
| POST | `/api/channels/{type}/test` | 连通性测试（V1 校验凭证完整性，不建长连接） |
| POST | `/api/channels/{type}/events` | 入站 webhook（免 JWT，但需 `X-DataClaw-Token` 头 = `config.token`），`{text,user?,employeeId?}` → `{reply,sessionId?,artifactId?,latencyMs}` |

**实现中的配置字段（snake_case，与代码一致）**
| type | config 字段（必填加 *） |
|---|---|
| `feishu` | `app_id*`、`app_secret*`、`verification_token`、`token`（入站校验） |
| `wecom` | `corp_id*`、`agent_id*`、`secret*`、`token` |
| `dingtalk` | `app_key*`、`app_secret*`、`token` |
| `web` | `theme`、`defaultEmployeeId` |
| `api` | `token`、`rateLimit` |

### 8.11 审计与总览
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/audit?action=&actorId=&risk=&result=&from=&to=&page=` | 审计流水 |
| GET | `/api/audit/stats?days=7` | 统计（按 action/risk/result 聚合、趋势） |
| GET | `/api/overview` | 总览：员工数、会话数、工具调用、拒绝次数、技能数、活跃用户、近 7 日趋势 |
| GET | `/api/health` | `{status,version,llm:"provider|offline",uptime}` |

---

## 9. 技能规范（SKILL.md，对标 OpenClaw / Agent Skills）

```markdown
---
name: chatbi
description: ChatBI 数据查询技能。提供三张能力：数据集清单、表字段结构、自然语言问数。
risk: low
tools: [chatbi.list_tables, chatbi.describe_table, chatbi.ask]
---

# ChatBI 数据查询技能
## 能力边界（仅三种）
| 能力 | 命令 | 说明 |
...
## 首选工作流
1. 先 `list-tables` 判断有没有相关数据 …
```
- 内置技能 12 个：`chatbi`、`dashboard-builder`、`deep-report`、`contract-review`、`sales-intel`、`knowhow-search`、`doc-parse`、`pptx-export`、`excel-toolkit`、`web-search`、`data-cleaner`、`agent-browser`。
- 用户技能：创建时 `status=pending`，管理员 `review` 后 `approved` 才能被普通用户安装；管理员可直接用。
- `tool_names` 决定运行时把哪些工具挂给该员工（**没装技能 = 没有工具**，这是"权限即能力"的落点）。

---

## 10. 演示数据（seed）

| 数据 | 内容 |
|---|---|
| 用户 | `admin`（平台管理员，张明）、`analyst`（数据分析师，林知微）、`sales`（销售，程景舟）、`legal`（法务，顾守正）、`dev`（数据开发）、`ops`（运营）；另有 6 个用于公共员工分配的账号 |
| 数据源 | `demo`（SQLite，内置）：`worktime_fact`（工时事实：日期/区域/部门/项目/员工/工时/加班/交付/缺陷）、`dim_region`、`dim_dept`、`crm_customer`（客户：行业/规模/地区/负责人/等级/年合同额）、`crm_order`（订单/合同额/阶段/日期）、`crm_contact_log`（沟通记录）、`contract_sample`（合同条款：合同名/条款号/条款正文/类型/金额/期限） |
| 指标 | 人均工时、工时利用率、超时工单率、区域人均产出、客户合同额、回款率、合同风险条款数 |
| 知识库 | 《标准合同审查规则》《销售拜访方法论》《工时管理规范》《产品介绍》等 4-6 篇；含图片/邮件类型各 1 |
| 合同 | 样例合同 3 份（PDF/DOCX/文本），含 7-9 个可识别风险条款（付款账期过长、违约金不对等、管辖法院不利、自动续约、无限连带责任、知识产权归属模糊、保密期限过短等） |
| 公共员工 | `社媒排期官`（DataClaw-Scheduler，4 技能）、`数据分析师 2`（DataClaw-Data，3 技能） |
| 策略 | analyst：工时表全表可见但 `salary` 列 mask、`employee_name` hash；sales：只能看自己负责的客户（行级 `owner_id='u_sales'`）；legal：合同表可读、金额列 truncate；dev：全表但 `id_card` 列 deny |
| 审计 | 近 7 天 ~80 条，含 3 条 denied（越权查询）、2 条 high risk 审批 |

启动：`python -m app.seed`（幂等，`--reset` 清库重建）。

---

## 11. 运行与验证

| 命令 | 作用 |
|---|---|
| `scripts/dev.ps1` | 后端 8787 + 前端 5173（Vite 代理 /api） |
| `scripts/build.ps1` | 前端构建到 `backend/app/static`，后端单端口 8787 托管 |
| `scripts/run.ps1` | 生产式启动（8787） |

**验收清单（V1）**
1. `admin/admin123` 登录 → 总览看到员工/会话/工具调用/拒绝统计。
2. 用「数据分析师」模板创建员工 → 装 `chatbi` → 会话问「帮我分析下上季度各区域工时效率情况」→ 5 分钟内产出：KPI 卡 + 热力图 + 区域对比柱状图 + 异常标注 + 深度报告，且 SQL 里带行级过滤、薪资列已脱敏。
3. `sales` 问「我要拜访 XX 客户」→ 产出结构化拜访指南（客户 360 + 内外部信息 + 话术）。
4. `legal` 上传合同 → 「按公司标准合同规则审查」→ 产出风险分级列表 + 带修订痕迹 docx 下载；导出前触发 HITL 审批。
5. 管理员把「公共员工」分配给 `analyst` → analyst 侧出现副本，改管理员版本 → publish → 副本同步。
6. 安全：`sales` 试图查询全量客户 → 被行级过滤；`analyst` 查 `salary` → 掩码；越权查 `contract` → 审计出现 denied。
7. 审计页可按 action/risk/result 过滤，看到每次工具调用与 SQL 改写前后语句。

---

## 12. 附录

### A. 容器化部署（V2 生产形态，V1 提供 docker-compose 示例）
```yaml
services:
  api:      {build: ./backend, ports: ["8787:8787"], volumes: ["./data:/app/data"], environment: [OPENAI_API_KEY] }
  web:      {build: ./frontend, ports: ["80:80"], depends_on: [api]}
  postgres: {image: postgres:16, environment: [POSTGRES_PASSWORD=...]}
  # 每用户 Agent 沙箱：由 runtime/sandbox.py 的 DockerProvider 按需拉起
```

### B. V2 演进（与调研报告对应）
1. 沙箱：LocalProvider → OpenSandbox/Docker（每会话容器 + egress 白名单）。
2. 向量检索：关键词/BM25 → pgvector / Qdrant + 混合检索 + rerank。
3. SQL 网关：sqlglot 单机 → 代理层（兼容 ShardingSphere 思路）+ 查询结果水印。
4. 渠道：webhook 单轮 → 飞书/企微/钉钉双向长连接 + 多轮会话映射。
5. 可观测：审计表 → OpenTelemetry + Langfuse 式 trace（token/时延/成本）。
6. 技能生态：内置 12 → 私有市场（签名、审核流、版本回滚、依赖声明）。
