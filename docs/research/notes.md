# 检索原始笔记（2026-10-23）

> 用途：02-技术调研报告.md 的事实底稿。所有 star/fork/license/最近提交均来自 `api.github.com/repos/<owner>/<repo>`（2026-10-23 抓取，UTC 时间）；license 以仓库 LICENSE 原文为准，API 的 `spdx_id` 仅作线索。
> 说明：本机 `web_fetch` 因 DNS/SSRF 校验不可用，页面正文用 `curl` + 去标签脚本抓取；`web_search` 正常。

## 一、OpenClaw（个人级 Agent 本体）

- 仓库：https://github.com/openclaw/openclaw ，392,832 star / 82,565 fork，MIT，TypeScript，最近 push 2026-10-23。
- 定位（README）：开源个人 AI 助手，跑在自己的电脑上，在 Discord/iMessage/Slack/Teams/Telegram/WhatsApp 等 20+ 渠道出现；一个 Gateway 既做个人助手也做团队部署，"configuration is the only difference"；由 OpenClaw Foundation（501(c)(3)）治理，无付费版/托管版/token。
- 架构（docs/concepts/architecture.md）：单长驻 Gateway 拥有全部消息面（WhatsApp/Baileys、Telegram/grammY、Slack、Discord、Signal、iMessage、WebChat）；控制面客户端（macOS app/CLI/Web UI）用 WebSocket 连 Gateway（默认 127.0.0.1:18789）；Nodes（macOS/iOS/Android/headless）也走 WS，role=node + caps/commands；协议为 JSON 文本帧，首帧必须 connect；req/res + event；设备配对 + device token；side-effecting 方法要求幂等键。
- 组件：Gateway / Control UI / Channels / Nodes / Tools / Skills / Plugins / MCP client+server / A2A 1.0 / ACP / OpenTelemetry+Prometheus / OpenAI 兼容 API。
- 沙箱（docs/gateway/sandboxing.md）：默认关闭（"Sandboxing is off by default"），Gateway 留在 host，只有工具执行进沙箱；官方明确"这不是完美的安全边界"；后端：Docker（默认）、Podman、SSH、OpenShell、Crabbox。
- Skills（docs/tools/skills.md）：目录 + `SKILL.md`（YAML frontmatter + Markdown）；加载优先级 7 级（workspace > project .agents > personal ~/.agents > managed > workshop > bundled > extraDirs）；按环境/配置/二进制存在性过滤；支持 per-agent allowlist；个人技能与团队共享技能分离。
- 技能市场：ClawHub（clawhub.ai），有发布、审核、security audits、per-release trust verdict；扫描来源 VirusTotal、ClawScan、静态分析；官方承认"pending or stale scan can allow installation with a warning"；`openclaw skills verify` 取注册中心验证信封，但**不 hash 本地当前文件**。
- 团队版（docs/start/teams.md）：一个 Gateway = 一个信任域；"Everyone who can message a tool-enabled agent shares that agent's delegated tool authority"；要服务互不信任的人/组织 → 每租户一个 Gateway；operator roles 绑定认证身份（会话/agent/scope/是否强制沙箱）；多用户会话有 creator/owner/prompter 三层归属；个人 provider 账号。
- 企业化论点核对：PDF 说"个人版无隔离、无员工管理"在 2026-10 已不完全成立（团队版有角色、共享会话、沙箱、审计线索）。真正缺的是：企业数据权限（行列级）、中国 IM 渠道、员工/技能资产化与版本分配、统一算力结算、私有技能市场的合规审核。
- 一手链接：https://docs.openclaw.ai/concepts/architecture 、/gateway/sandboxing 、/tools/skills 、/start/teams 、/start/why-openclaw 、https://openclaw.ai/blog/virustotal-partnership

## 二、企业级 Agent 平台（GitHub API，2026-10-23）

| 仓库 | Star | Fork | License（原文核对） | 最近 push | 语言 |
|---|---|---|---|---|---|
| langgenius/dify | 159,348 | 25,172 | Dify Open Source License（Apache 2.0 + 附加：不得做多租户服务；不得去前端 LOGO/版权） | 2026-10-23 | Python |
| langgenius/dify-sandbox | 1,276 | 329 | Apache-2.0 | 2026-10-22 | Go |
| coze-dev/coze-studio | 21,752 | 3,135 | Apache-2.0 | 2026-07-29 | TypeScript/Go |
| infiniflow/ragflow | 92,723 | 11,082 | Apache-2.0 | 2026-10-23 | Go/Python |
| labring/FastGPT | 29,897 | 7,339 | FastGPT Open Source License（Apache 2.0 + 不得做类似 FastGPT 的多租户 SaaS；不得去 LOGO） | 2026-10-23 | TypeScript |
| dataelement/bisheng | 12,072 | 1,984 | Apache-2.0 | 2026-10-23 | Python |
| 1Panel-dev/MaxKB | 23,017 | 3,195 | GPL-3.0 | 2026-10-23 | Python |
| langflow-ai/langflow | 155,955 | 10,241 | MIT | 2026-10-23 | Python |
| FlowiseAI/Flowise | 55,520 | 25,074 | Apache-2.0（enterprise 目录商业许可） | 2026-08-13，**archived=true** | TypeScript |
| n8n-io/n8n | 208,381 | 61,215 | Sustainable Use License（fair-code，非 OSI；.ee 文件需企业许可） | 2026-10-23 | TypeScript |
| open-webui/open-webui | 156,543 | 22,781 | Open WebUI License（BSD-3 + 品牌条款：>50 用户不得改品牌） | 2026-10-23 | Python |
| OpenHands/OpenHands | 91,637 | 12,161 | MIT | 2026-10-23 | TypeScript |

要点补充：
- Dify 文档（.md 直取）：4 个内置角色 Owner/Admin/Editor/Normal；**自定义角色与细粒度权限仅 Enterprise**；知识库权限是"整库可见/部分成员"级别。Agent 文档明确：社区版 Agent 运行时的文件访问控制"**not intended to provide a hardened security boundary between mutually untrusted users or workloads**"。
- Dify 插件签名：社区版支持第三方签名校验（生成密钥、签 `.difypkg`、把公钥加入信任列表），可作为私有技能市场的签名参考。https://docs.dify.ai/en/develop-plugin/publishing/standards/third-party-signature-verification.md
- Coze Studio README：Go + React/TS，微服务 + DDD；功能含 prompt/RAG/plugin/workflow/knowledge/database；**官方警告公网部署风险：注册开放、代码节点 Python 执行环境、SSRF、部分 API 水平越权**。
- Bisheng README：Task Mode（规划 + 并行子 agent + HITL + PPT/Excel/Word 技能包）；Knowledge Space（部门空间、Owner/Manager/Editor/Viewer 权限模板、权限到单文件、部门/用户组授权、继承）；企业特性：组织/用户/角色/配额、**RBAC + ReBAC**、审批流、审计、SSO/LDAP、信创 DM8、Open API 服务账号与"以员工身份调用"；仪表盘与 DSH 桌面企业接入属商业版。
- MaxKB：GPL-3.0（分发/闭源商用需评估 copyleft）。
- n8n：Sustainable Use License；master 分支 .ee 文件需企业许可；AI Agent 节点 + 400+ 集成，单实例单租户定位。
- Open WebUI：多用户/角色/分组、知识库、Tools/Pipelines；无 IM 渠道、无 Agent 执行沙箱。
- Flowise：仓库已归档（2026-08-13 最后 push），不适合做底座。

## 三、运行时与沙箱

| 项目 | Star | License | 关键事实 |
|---|---|---|---|
| e2b-dev/E2B | 14,517 | Apache-2.0 | SDK/云沙箱；每 sandbox 一台 Firecracker microVM |
| e2b-dev/runtime | 1,759 | Apache-2.0 | E2B 完整后端：控制面 + 每节点 orchestrator + VM 内 agent + edge router + template builder；sandbox = resume snapshot；userfaultfd 惰性加载 + CoW overlay；per-sandbox nftables + SNI/Host 域名白名单；secrets 只存元数据；workload identity 短期 token；OTel |
| opensandbox-group/OpenSandbox | 16,093 | Apache-2.0 | 阿里开源；本地 Docker / K8s operator；Fast Sandbox（Firecracker）创建 64ms P50 / 125.4ms P99(10 并发)；pause/resume 保留内存+磁盘；per-sandbox egress 策略（FQDN/CIDR、DNS 过滤、dns+nft 默认拒绝）；Credential Vault（沙箱内只见假凭据，sidecar 出站注入真实凭据）；SDK 含 Java/Kotlin；MCP |
| superradcompany/microsandbox | 8,779 | Apache-2.0 | 本地 microVM（libkrun 系），fork/snapshot、OCI 镜像、无基础设施依赖 |
| kubernetes-sigs/agent-sandbox | 4,366 | Apache-2.0 | Sandbox CRD（有状态、单例、稳定身份、PVC），隔离交给 RuntimeClass（gVisor/Kata）；SIG Apps |
| google/gvisor | 19,757 | Apache-2.0 | 用户态内核，syscall 拦截；runsc RuntimeClass；兼容性缺口 |
| firecracker-microvm/firecracker | 37,577 | Apache-2.0 | KVM microVM，最小设备模型，函数计算底座 |
| kata-containers/kata-containers | 8,996 | Apache-2.0 | OCI 兼容 microVM，K8s RuntimeClass 即插即用 |
| google/nsjail | 4,169 | Apache-2.0 | namespaces + cgroups + rlimits + seccomp-bpf（Kafel） |
| containers/bubblewrap | 9,173 | LGPL-2.1 | 非特权 sandbox，Flatpak 底座 |
| Docker（受限容器） | - | Apache-2.0 | namespaces/cgroups/seccomp/cap drop；共享内核，不是多租户安全边界 |

## 四、MCP / 技能生态

- 规范版本：**2026-07-28（latest）**；传输：stdio（newline-delimited JSON-RPC）+ Streamable HTTP（POST + 可选 SSE 流）；server features：tools/resources/prompts；client features：roots/sampling/elicitation；授权可选，HTTP 传输用 OAuth 2.1 风格（资源指示器、scope 选择、step-up authorization）。
- 许可：modelcontextprotocol 仓库正从 MIT 迁移到 Apache-2.0，规范文档 CC-BY-4.0。
- 注册中心：modelcontextprotocol/registry（7,398★，Apache-2.0，Go）。
- 网关：IBM/mcp-context-forge（4,685★，Apache-2.0）：工具/agent/API 三网关、虚拟服务器、40+ 插件、限流/认证/重试、OTel；agentic-community/mcp-gateway-registry（1,012★，Apache-2.0）：OAuth（Keycloak/Entra）、动态发现、统一治理。
- Agent Skills / SKILL.md（agentskills.io 规范）：frontmatter 必填 `name`（≤64，小写+连字符）、`description`（≤1024，说明"做什么+何时用"）；可选 `license`、`allowed-tools`（实验）；渐进披露三级：元数据 ~100 token 常驻 → 触发后读 body（<5k token）→ 按需读引用文件/跑脚本。
- anthropics/skills：183,186★，**GitHub API license=None**（未检测到标准许可证）→ 技能内容不能默认 MIT，需逐目录看声明。
- 技能市场安全：ClawHub 用 VirusTotal + ClawScan + 静态分析，扫描未完成可"带警告安装"；Dify 用签名 + 公钥信任列表；可补 Sigstore/cosign + SBOM + 权限声明。

## 五、数据权限与安全（GitHub API，2026-10-23）

| 项目 | Star | License | 作用 |
|---|---|---|---|
| apache/ranger | 1,085 | Apache-2.0 | 集中策略管理 + 行过滤/列脱敏 + 各服务插件 + 审计（Solr/ES） |
| apache/sentry | 121 | Apache-2.0 | **已归档（2020）**，功能并入 Ranger，勿选 |
| open-metadata/OpenMetadata | 15,560 | Apache-2.0 | 元数据/血缘/术语/标签/owner，分类分级底座 |
| datahub-project/datahub | 12,881 | Apache-2.0 | 同上，数据目录 + 血缘 |
| apache/casbin | 20,466 | Apache-2.0 | 多语言授权库（RBAC/ABAC/ReBAC），无策略 UI |
| open-policy-agent/opa | 12,397 | Apache-2.0 | 策略即代码（Rego），决策 API，K8s admission |
| apache/shardingsphere | 20,813 | Apache-2.0 | 分库分表/加密/数据脱敏（SQL 改写），JDBC+Proxy |
| tobymao/sqlglot | 9,712 | MIT | SQL 解析/转译/优化，Scope 支持 CTE/子查询/UNION |
| JSQLParser/JSqlParser | 5,966 | Apache-2.0 | Java SQL 解析（Visitor） |
| apache/calcite | 5,198 | Apache-2.0 | SQL 解析/校验/优化框架 |
| data-privacy-stack/presidio | 11,471 | MIT | PII 识别（NER+正则+校验）+ 匿名化（mask/hash/encrypt/replace） |

sqlglot 行级权限注入工程要点（AskTable 博客 + 实践）：
- 用 `Scope` 遍历 `derived_table_scopes`/`cte_scopes`/`subquery_scopes`，在每个 SELECT 的 WHERE 注入谓词；别名识别要区分"真实别名 vs 表名"；`SELECT *` 场景列级脱敏必须展开列清单；同表多次出现要按 SQL 文本/集合去重，避免重复注入。
- 坑：方言引号（MySQL 反引号 / PG 双引号 / Oracle 大写）、函数与视图不可下推、CTE/UNION/窗口函数、HAVING/ORDER BY 引用、语义等价与性能（博客称改写 <10ms）、失败降级（catch → 拒绝或 LLM 改写，生产应"拒绝优先"，不能降级为放行）。
- 必须搭配：查询网关（禁止绕过）、策略服务（OPA/Casbin）、结果集二次脱敏（兜底）、审计。

## 六、BI / 生成式分析

| 项目 | Star | License | 要点 |
|---|---|---|---|
| Canner/WrenAI | 17,956 | 多许可：core/sdk/skills Apache-2.0，docs CC-BY-4.0，预留 AGPL 模块 | GenBI：MDL 语义层（YAML/Markdown 进 Git）、CLI/MCP、dry-plan 校验、行数限制、22+ 数据源（DataFusion） |
| eosphoros-ai/DB-GPT | 20,185 | MIT | Agentic 数据助手、AWEL、Text2SQL |
| vanna-ai/vanna | 23,812 | MIT | **已归档（最后 push 2026-02-02）**，勿作底座 |
| apache/superset | 75,269 | Apache-2.0 | SQL Lab + 仪表盘 + 嵌入式 SDK |
| apache/echarts | 67,575 | Apache-2.0 | 图表库 |
| antvis/G2 | 12,641 | MIT | 图表库 |
| vega/vega-lite | 5,527 | BSD-3-Clause | 图表语法 |

## 七、文档解析 / 合同

| 项目 | Star | License | 要点 |
|---|---|---|---|
| opendatalab/MinerU | 82,360 | Apache-2.0 + 附加条款（MAU>1 亿或月收入>2000 万美元需商业许可；在线服务有署名义务） | PDF/Office → Markdown/JSON，版面/OCR/表格 |
| docling-project/docling | 69,434 | MIT | IBM，版面+表格+OCR，docling-serve |
| microsoft/markitdown | 191,753 | MIT | 轻量转换（pdf/docx/xlsx/pptx/图片） |
| Unstructured-IO/unstructured | 15,599 | Apache-2.0 | 多格式 ETL / partition |
| pymupdf/PyMuPDF | 10,974 | **AGPL-3.0** | 能力强，但闭源分发需商业授权 |
| python-openxml/python-docx | 5,750 | MIT | 不支持修订痕迹 |
| balalofernandez/docx-revisions | 18 | MIT | 给 python-docx 补 `<w:ins>/<w:del>` 读写 |

Word 修订：OOXML 用 `w:ins`/`w:del`（删除文本在 `w:delText`）、`w:rPr/w:ins` 标记段落标记插入、`w:author`/`w:date`；表格/页眉页脚/批注需单独处理；生成后要能被 Word "接受/拒绝修订"。

## 八、渠道

- 企微群机器人：https://developer.work.weixin.qq.com/document/path/91770 —— **每个机器人 20 条/分钟**；只能发不能收。
- 企微应用消息：https://developer.work.weixin.qq.com/document/path/90236 —— 每应用 ≤ 账号上限×200 人次/天；同一成员 ≤30 次/分钟、1000 次/小时。
- 飞书：事件订阅回调需 URL 校验（challenge）+ 加密（Encrypt Key，AES）+ Verification Token；要求快速响应否则重推；提供长连接（WebSocket）模式免公网回调；文档页为 SPA，正文未取到，具体配额**未核实**。
- 钉钉：机器人 webhook / 工作通知 / Stream 模式（open-dingtalk/dingtalk-stream-sdk-python，176★，MIT）；文档站 TLS 被阻断，频率数字**未核实**。
- SDK：larksuite/oapi-sdk-java（313★，Apache-2.0）。

## 九、明确未核实清单

1. 飞书开放平台"主动消息/发送消息"的精确 QPS/日配额与处罚规则（文档页 SPA 未取到正文）。
2. 钉钉机器人/工作通知的精确频率限制（帮助站 TLS 握手被阻断）。
3. 各平台"多租户/RBAC"细节以其商业版文档为准（社区版代码未逐行读）。
4. OpenClaw 各渠道在中国的合规可用性（WhatsApp/Telegram 等不在境内合规范围）。
5. anthropics/skills 的具体授权条款（仓库无标准 LICENSE 文件）。
6. Coze Studio 开源版缺失功能清单（官方对比页未取到，仅据 README 风险提示）。
7. Flowise 仓库归档原因。
8. 所有 star/fork 为 2026-10-23 抓取瞬时值，会持续变化。
