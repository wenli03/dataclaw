"""外部检索技能（离线模拟版）。

无外部搜索 API Key 时：从 `knowledge_docs` 命中内部资料，再按客户行业生成
内置 `EXTERNAL_INTEL` 情报，所有结果带 `simulated: true`，绝不冒充真实联网结果。
"""
from __future__ import annotations

from datetime import date

from .. import search_knowledge
from ..types import ToolContext, ToolResult, ToolSpec

EXTERNAL_INTEL: dict[str, list[dict]] = {
    "软件": [
        {
            "title": "企业数字化预算回暖，SaaS 采购向「效果付费」倾斜",
            "snippet": "行业调研显示，2026 年企业软件预算同比增长约 8%，但采购方更关注可量化的降本增效指标，"
            "按效果/订阅计价的合同占比提升。建议在拜访中准备 ROI 测算与同行业标杆案例。",
            "source": "行业观察（模拟）",
            "url": "https://example.com/industry/saas-budget-2026",
        },
        {
            "title": "头部厂商加速 AI 原生能力整合，数据治理成为选型硬指标",
            "snippet": "多家厂商在合同管理、销售分析场景引入 Agent 能力；客户 IT 部门普遍把数据权限、审计与私有化部署列为前置条件。",
            "source": "科技媒体（模拟）",
            "url": "https://example.com/news/ai-agent-enterprise",
        },
    ],
    "制造": [
        {
            "title": "制造业出海带动供应链协同系统需求",
            "snippet": "出海企业在订单、报关、海外仓协同上投入增加，对多语言与多币种支持提出要求；交付周期与本地化服务能力是决策关键。",
            "source": "产业研究（模拟）",
            "url": "https://example.com/industry/manufacturing-global",
        },
        {
            "title": "智能工厂改造进入深水区，数据孤岛仍是主要障碍",
            "snippet": "设备数据与业务系统割裂导致分析滞后，客户更愿意为「连接 + 分析 + 行动」一体化方案付费。",
            "source": "行业报告（模拟）",
            "url": "https://example.com/report/smart-factory",
        },
    ],
    "金融": [
        {
            "title": "金融机构合规审查强度提升，合同智能审查需求增长",
            "snippet": "监管要求趋严，合同条款审查与留痕成为刚需；客户关注模型可解释性、私有化与审计追溯能力。",
            "source": "金融科技观察（模拟）",
            "url": "https://example.com/fintech/compliance",
        },
        {
            "title": "数据安全法与个人信息保护推动权限精细化",
            "snippet": "客户在数据分级、字段脱敏、行级权限上的投入明显增加，安全能力成为供应商准入项。",
            "source": "合规研究（模拟）",
            "url": "https://example.com/compliance/data-security",
        },
    ],
    "零售": [
        {
            "title": "零售企业加速会员与门店数据整合",
            "snippet": "客户希望打通线上线下的会员、订单与库存数据，实现精细化运营；对实时性与分析易用性要求高。",
            "source": "零售观察（模拟）",
            "url": "https://example.com/retail/omnichannel",
        },
        {
            "title": "门店人效成为降本重点，排班与工时分析受关注",
            "snippet": "多家连锁企业引入工时与排班分析工具，目标把人力成本与坪效挂钩，减少无效排班。",
            "source": "连锁经营研究（模拟）",
            "url": "https://example.com/retail/workforce",
        },
    ],
    "默认": [
        {
            "title": "企业采购更看重可验证的交付与安全合规",
            "snippet": "在当前预算环境下，客户倾向于小范围试点、按里程碑验收；数据权限、审计日志与私有化部署是常见前置条件。",
            "source": "行业观察（模拟）",
            "url": "https://example.com/enterprise/procurement",
        },
        {
            "title": "AI Agent 进入业务系统深水区，人机协同成为主流",
            "snippet": "从单点问答走向流程执行，客户关注 Agent 的边界控制、人工审批（HITL）与结果可追溯。",
            "source": "科技媒体（模拟）",
            "url": "https://example.com/news/agent-hitl",
        },
    ],
}


def _industry_from(ctx: ToolContext, query: str) -> str:
    sales = ctx.state.get("sales") or {}
    industry = str((sales.get("profile") or {}).get("industry") or "")
    if industry:
        for key in EXTERNAL_INTEL:
            if key != "默认" and (key in industry or industry in key):
                return key
    for key in EXTERNAL_INTEL:
        if key != "默认" and key in query:
            return key
    return "默认"


async def search_handler(params: dict, ctx: ToolContext) -> ToolResult:
    query = str(params.get("query") or params.get("q") or "").strip()
    if not query:
        return ToolResult(ok=False, error="缺少 query 参数")
    industry = _industry_from(ctx, query)
    results = []
    hits = search_knowledge(ctx.db, ctx.user, query, top_k=3)
    for hit in hits:
        results.append(
            {
                "title": f"内部知识库｜{hit.get('docName')}",
                "snippet": hit.get("snippet", "")[:240],
                "source": "企业知识库",
                "url": f"kb://{hit.get('docId')}",
                "simulated": False,
            }
        )
    for item in EXTERNAL_INTEL.get(industry, EXTERNAL_INTEL["默认"]):
        results.append({**item, "simulated": True})
    ctx.state["web_results"] = results
    output = {
        "query": query,
        "industry": industry,
        "simulated": True,
        "results": results,
        "note": "离线模式：外部公开信息为内置模拟情报（simulated=true），内部资料来自企业知识库真实检索；未调用真实联网搜索。",
        "fetchedAt": date.today().isoformat(),
    }
    return ToolResult(
        ok=True,
        summary=f"检索到 {len(results)} 条情报（外部为模拟，内部为知识库真实命中）",
        output=output,
    )


async def browser_open_handler(params: dict, ctx: ToolContext) -> ToolResult:
    url = str(params.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, error="缺少 url 参数")
    return ToolResult(
        ok=True,
        summary="浏览器沙箱未启用，返回离线占位页（simulated）",
        output={
            "url": url,
            "title": "页面已打开（离线模拟）",
            "status": 200,
            "simulated": True,
            "note": "V1 未开放真实浏览器 egress；V2 由 Sandbox DockerProvider 提供隔离浏览器。",
        },
    )


async def browser_extract_handler(params: dict, ctx: ToolContext) -> ToolResult:
    url = str(params.get("url") or "").strip()
    return ToolResult(
        ok=True,
        summary="离线模式未抓取真实 DOM，返回模拟结构化结果",
        output={
            "url": url,
            "items": [],
            "simulated": True,
            "note": "生产环境通过 browser.extract 返回标题/正文/链接等结构化字段。",
        },
    )


async def fetch_handler(params: dict, ctx: ToolContext) -> ToolResult:
    url = str(params.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, error="缺少 url 参数")
    return ToolResult(
        ok=True,
        summary="离线模式未联网抓取，返回模拟摘要",
        output={
            "url": url,
            "title": "页面摘要（模拟）",
            "snippet": "离线演示环境未启用真实 egress；生产环境由 Sandbox 的 egress 白名单代理抓取并脱敏。",
            "simulated": True,
        },
    )


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="web.search",
        title="检索外部公开情报",
        description="检索客户行业的外部公开信息；离线模式返回内置模拟情报并显式标注 simulated=true。",
        params={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索式，例如：客户所在行业趋势"},
            },
            "required": ["query"],
        },
        handler=search_handler,
        risk="low",
        skill="web-search",
    ),
    ToolSpec(
        name="web.fetch",
        title="抓取网页内容",
        description="按 URL 抓取网页正文；离线模式返回模拟摘要。",
        params={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "网页 URL"}},
            "required": ["url"],
        },
        handler=fetch_handler,
        risk="medium",
        skill="web-search",
    ),
    ToolSpec(
        name="browser.open",
        title="打开网页（沙箱浏览器）",
        description="在隔离浏览器中打开 URL；V1 离线模式返回 simulated 占位页。",
        params={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "要打开的 URL"}},
            "required": ["url"],
        },
        handler=browser_open_handler,
        risk="medium",
        skill="agent-browser",
    ),
    ToolSpec(
        name="browser.extract",
        title="提取网页结构化内容",
        description="从已打开页面提取标题/正文/链接；V1 离线模式返回 simulated 结果。",
        params={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "selector": {"type": "string", "description": "可选 CSS 选择器"},
            },
        },
        handler=browser_extract_handler,
        risk="low",
        skill="agent-browser",
    ),
]
