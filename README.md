# DataClaw

> 参考《DataClaw_V1.0.pdf》（汉得信息 · 汉得灵舟 DataClaw 企业级数字员工平台）完成的开源技术调研 + 二次开发实现。
> **一句话**：把"个人的龙虾（OpenClaw）"变成"企业的数字员工队伍"——私有化部署、每人独占沙箱、权限继承自员工账号、内置数据能力的 AI Agent 平台。

![version](https://img.shields.io/badge/version-v1.0.0-5B57E8) ![Python](https://img.shields.io/badge/Python-3.11+-3776AB) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688) ![React](https://img.shields.io/badge/React-18-61DAFB)

## 两个实现（同一产品）

| 版本 | 技术 | 代码量 | 启动 | 适合 |
|---|---|---|---|---|
| **v1.0 参考实现** | Python(FastAPI) + React/Vite/TS | 31,000 行 | `scripts
un.cmd`（3 步依赖安装） | 产品化、长期演进 |
| **v1.1 精简实现** | **Go 单二进制 + 原生 Web** | **3,488 行（−89%）** | `scripts\lean.cmd`（双击即用） | 演示 / POC / 单机私有化 |

> 精简实现把 25 张表压成单表文档存储、78 个 API 压到 19 个、React 换原生 JS，功能保留三条标杆场景 + 权限/审计/公共员工/技能/HITL。
> 取舍与对比见 [docs/06-精简实现（Go单二进制）.md](docs/06-精简实现（Go单二进制）.md)。

## 交付物

| 文件 | 内容 |
|---|---|
| [docs/01-PRD.md](docs/01-PRD.md) | 产品需求文档：定位、角色、四座大山解法、能力清单、三大标杆场景验收 |
| [docs/02-技术调研报告.md](docs/02-技术调研报告.md) | GitHub 开源生态调研：OpenClaw / Dify / Coze / RAGFlow / Bisheng / 沙箱 / SQL 权限 / 合同审查 / 渠道，选型结论 |
| [docs/03-架构设计与API契约.md](docs/03-架构设计与API契约.md) | 架构、数据模型、权限求值、SQL 安全网关、Agent 运行时、SSE 协议、完整 REST API |
| [docs/04-实现说明与验收.md](docs/04-实现说明与验收.md) | 实现清单、运行方式、验收证据（含 18 张截图）、已知限制与 V2 路线 |
| [docs/05-演示与讲解脚本.md](docs/05-演示与讲解脚本.md) | 5 分钟演示时间轴、10 个可讲的架构决策、8 个高频追问与回答、演示雷区 |
| [docs/06-精简实现（Go单二进制）.md](docs/06-精简实现（Go单二进制）.md) | v1.1：Go 单二进制实现、代码量对比（31k→3.5k）、砍掉了什么/保留了什么、取舍与代价、验证 |
| [docs/07-角色操作手册.md](docs/07-角色操作手册.md) | **角色操作手册**：管理员/分析师/销售/法务四条任务线，36 张真实操作截图，FAQ + PDF 能力对照（[单文件 HTML 版](docs/07-角色操作手册.html)） |
| [docs/08-华为4+1设计视图与时序图.md](docs/08-华为4+1设计视图与时序图.md) | **华为 4+1 设计视图**：逻辑/过程/开发/物理视图 + 42 个正常/异常/V2 场景时序图，逐条带代码锚点（[可视化 HTML 版](docs/08-华为4+1设计视图与时序图.html)） |

## 快速开始

```bash
# 1) 后端依赖（Python 3.11+）
cd backend && pip install -r requirements.txt

# 2) 前端构建（Node 18+ / pnpm）
cd ../frontend && pnpm install && pnpm build

# 3) 启动（单端口 8787，前后端同源）
cd ../backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```
Windows 一键：双击 `scripts\run.cmd`（自动选 Python、自动构建前端）｜开发模式 `scripts\dev.cmd`｜重建演示数据 `scripts\seed.cmd --reset`｜跑全部测试 `scripts\test.cmd`（24 个用例）

打开 http://127.0.0.1:8787 ，演示账号：

| 账号 | 口令 | 角色 |
|---|---|---|
| `admin` | `admin123` | 平台管理员 |
| `analyst` | `123456` | 数据分析师（薪资列脱敏、客户表拒绝） |
| `sales` | `123456` | 销售（仅自己客户，行级过滤） |
| `legal` | `123456` | 法务（合同可读，金额截断） |

> 无需 LLM API Key：内置「离线确定性 Planner」驱动真实工具链（SQL 执行、ECharts 大屏、Markdown 报告、docx 修订版）。
> 接入真实模型：`DATACLAW_LLM_API_KEY` / `DATACLAW_LLM_BASE_URL` / `DATACLAW_LLM_MODEL`（OpenAI 兼容）。

## 三大标杆场景（开箱可跑）

1. **工时分析**：问"帮我分析下上季度各区域工时效率情况" → 自动识别数据集 → 生成 SQL → **经过数据权限网关**（行级过滤 + 薪资脱敏）→ 产出可视化大屏（热力图/对比柱状/趋势/部门占比）+ ≥1200 字深度报告。
2. **销售情报**：问"我要拜访 XX 客户" → 调 CRM（受行级权限）→ 外部信息 → 知识库方法论 → 产出结构化拜访指南（客户 360 + 需求预判 + 话术）。
3. **合同审查**：上传合同 → 解析 → 匹配企业审查规则库 → 风险分级 + 逐条修订建议 → **HITL 审批** → 生成带修订痕迹的 docx。

## 企业级能力

- **用户级隔离**：每位用户独立工作空间（沙箱 Provider 可切换 Docker/OpenSandbox）
- **公共员工**：统一定义 → 版本管理 → 一键分配 → 用户侧副本同步
- **技能超市**：12 个内置技能（SKILL.md 规范）+ 用户级技能 + 静态安全扫描 + 审核上架
- **数据安全**：数据源/表/字段/指标/行级五层策略 + mask/hash/replace/truncate 四类脱敏 + **sqlglot AST 改写** + 生效矩阵 + 改写预览
- **多源接入**：SQLite 直连 + **Excel 自动导入**（每个工作表建表、列类型推断、敏感列识别，复用同一套 SQL 网关）
- **长期记忆**：显式偏好即时落库；成功完成标杆场景后自动沉淀一条「任务打法」，按员工隔离、可删除
- **全链路审计**：登录/会话/工具/SQL/导出/技能/分配/策略/HITL，含越权拦截（denied）
- **渠道接入**：飞书/企微/钉钉/Web/API，配置、连通性测试、入站 webhook

## 目录

```
backend/app/{api,services,runtime,seed,core}   FastAPI + SQLAlchemy + Agent 运行时
frontend/src/{pages,components,lib}            React 18 + Vite + Tailwind + ECharts
docs/                                          调研报告 / PRD / 架构契约 / 验收
scripts/                                       run.ps1 / dev.ps1
data/                                          app.db · demo.db · uploads · artifacts · workspaces
```

## 说明

本项目是**技术方案与原型实现**，用于验证 PDF 中的产品形态与技术可行性；生产化所需的容器沙箱、企业 SSO、IM 长连接、多租户计费、向量检索等在 `docs/03` §12 给出演进路径。
