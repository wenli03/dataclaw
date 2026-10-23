"""离线确定性 Planner（无 LLM Key 时的默认决策器）。

策略：先做场景识别（关键词 + 员工角色 + 已装技能），再产出有序步骤。
三条标杆场景的步骤与契约一一对应，参数全部来自用户原话，不做臆造。
"""
from __future__ import annotations

import re

from .types import PlanStep, PlannerPlan, ToolSpec

CONTRACT_KEYS = ("合同", "审查", "条款", "法务", "风险扫描", "修订")
SALES_KEYS = ("拜访", "客户", "情报", "商机", "销售", "话术")
WORKTIME_KEYS = ("工时", "效率", "人效", "区域", "大屏", "分析", "报表", "上季度", "加班", "交付", "产能", "缺陷")

SKILL_SAMPLES: dict[str, list[str]] = {
    "chatbi": ["帮我分析上季度各区域工时效率", "查一下本季度各部门交付与缺陷情况"],
    "dashboard-builder": ["把刚才的查询做成可视化大屏", "生成一版带异常标注的区域对比图"],
    "deep-report": ["基于这次分析写一份深度报告", "给我一份可用于汇报的周报"],
    "pptx-export": ["把这份分析做成 5 页汇报 PPT"],
    "excel-toolkit": ["把工时明细导出成 Excel"],
    "data-cleaner": ["帮我检查这张表的空值和重复行"],
    "contract-review": ["按公司标准合同规则审查这份合同", "帮我看看这份合同的付款和违约条款风险"],
    "sales-intel": ["我要拜访华东智造集团，帮我准备拜访指南", "查一下这个客户的历史订单和沟通记录"],
    "knowhow-search": ["查一下标准合同审查规则", "知识库里关于工时管理的规定是什么"],
    "doc-parse": ["解析我上传的 PDF 合同", "把这份 docx 的条款提出来"],
    "web-search": ["搜一下客户所在行业的最新动态"],
    "agent-browser": ["打开客户官网并提取关键信息"],
}

SKILL_LABELS = {
    "chatbi": "数据问数（ChatBI）",
    "dashboard-builder": "可视化大屏",
    "deep-report": "深度报告",
    "contract-review": "合同审查",
    "sales-intel": "销售情报",
    "knowhow-search": "知识检索",
    "doc-parse": "文档解析",
    "pptx-export": "汇报 PPT",
    "excel-toolkit": "Excel 工具",
    "web-search": "外部检索",
    "data-cleaner": "数据清洗",
    "agent-browser": "浏览器操作",
}


def _available(tools: list[ToolSpec]) -> set[str]:
    return {t.name for t in tools}


def _extract_customer(content: str) -> str:
    text = (content or "").strip()
    patterns = [
        r"拜访\s*[：:]?\s*([^\s，。,.!?！？]{2,24})",
        r"客户\s*[：:]?\s*([^\s，。,.!?！？]{2,24})",
        r"去\s*([^\s，。,.!?！？]{2,24})\s*(?:拜访|沟通|谈)",
        r"关于\s*([^\s，。,.!?！？]{2,24}?)\s*的",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1)
            name = re.sub(r"(客户|公司|集团|股份|有限)$", "", name).strip()
            name = re.sub(r"(帮我|麻烦|请|准备|生成|进行|做|一份|一个)", "", name).strip()
            if name and name not in ("拜访", "客户", "指南"):
                return name
    return ""


def _extract_contract_name(content: str) -> str:
    text = content or ""
    quoted = re.search(r"《([^》]{2,50})》", text)
    if quoted:
        return quoted.group(1).strip()
    for match in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9（）()\-]{2,40}?(?:合同|协议))", text):
        name = match.group(1)
        if any(bad in name for bad in ("审查", "规则", "标准", "按照", "公司", "这份", "该", "此")):
            continue
        if name in ("合同", "协议"):
            continue
        return name
    return ""


def detect_scenario(content: str, employee=None, attachments: list[dict] | None = None) -> str:
    text = content or ""
    attachments = attachments or []
    has_doc = any(str(a.get("name") or "").lower().endswith((".pdf", ".docx", ".doc", ".txt", ".md")) for a in attachments)
    contract_hit = any(k in text for k in CONTRACT_KEYS)
    sales_hit = any(k in text for k in SALES_KEYS)
    work_hit = any(k in text for k in WORKTIME_KEYS)
    if (contract_hit and ("合同" in text or has_doc)) or ("审查" in text and has_doc):
        return "contract"
    if sales_hit and ("拜访" in text or "客户" in text or "商机" in text):
        return "sales"
    if work_hit:
        return "worktime"
    return "fallback"


def plan(
    user,
    employee,
    content: str,
    tools: list[ToolSpec],
    *,
    skill_names: list[str] | None = None,
    attachments: list[dict] | None = None,
    db=None,
) -> PlannerPlan:
    """离线确定性规划。tools 为空时直接兜底（不臆造数据）。"""
    names = _available(tools)
    skills = list(skill_names or [])
    attachments = attachments or []
    scenario = detect_scenario(content, employee, attachments)

    def has(*candidates: str) -> bool:
        return any(c in names for c in candidates)

    if not names:
        return PlannerPlan(
            scenario="fallback",
            steps=[],
            reason="员工未安装任何技能，没有可用工具",
            final_text=_fallback_text(skills, has_tools=False),
            title="能力介绍",
        )

    if scenario == "contract":
        if not has("doc.parse_text", "doc_parse.parse"):
            return PlannerPlan(
                scenario="fallback",
                steps=[],
                reason="员工未安装文档解析技能",
                final_text="这项任务需要「文档解析」与「合同审查」技能。请先在技能超市为当前数字员工安装 `doc-parse` 与 `contract-review`，再上传合同重试。",
                title="能力不足",
            )
        steps = [_step("doc_parse.parse", {"fileId": _first_file_id(attachments), "contractName": _extract_contract_name(content)}, "解析合同文档")]
        if has("kb.search", "knowledge_search.query"):
            steps.append(_step("knowledge_search.query", {"query": "标准合同审查规则", "topK": 5}, "检索合同审查规则"))
        if not has("contract.risk_scan", "contract_review.analyze"):
            return PlannerPlan(
                scenario="fallback",
                steps=steps,
                reason="缺少合同审查技能",
                final_text="已解析合同，但当前员工未安装 `contract-review` 技能，无法执行风险扫描。",
                title="能力不足",
            )
        steps.append(_step("contract_review.analyze", {}, "按 12 条规则扫描风险"))
        if has("contract.redline_docx", "contract_review.export_docx"):
            steps.append(_step("contract_review.export_docx", {}, "生成带修订痕迹的 docx"))
        return PlannerPlan(scenario="contract", steps=steps, reason="识别为合同审查场景", title="合同审查")

    if scenario == "sales":
        if not has("sales.customer360", "sales_intel.customer_360"):
            return PlannerPlan(
                scenario="fallback",
                steps=[],
                reason="员工未安装销售情报技能",
                final_text="这项任务需要「销售情报」技能。请为数字员工安装 `sales-intel` 后再试。",
                title="能力不足",
            )
        customer = _extract_customer(content)
        steps = [_step("sales_intel.customer_360", {"customer": customer}, "查询客户 360（CRM）")]
        if has("web.search", "web_search.query"):
            steps.append(
                _step(
                    "web_search.query",
                    {"query": f"{customer or '目标客户'} 所在行业 最新动态 财报 新闻 2026"},
                    "检索外部公开情报",
                )
            )
        if has("kb.search", "knowledge_search.query"):
            steps.append(_step("knowledge_search.query", {"query": "销售拜访方法论", "topK": 4}, "检索拜访方法论"))
        if has("sales.visit_guide", "sales_intel.build_guide"):
            steps.append(_step("sales_intel.build_guide", {}, "生成结构化拜访指南"))
        return PlannerPlan(scenario="sales", steps=steps, reason="识别为客户拜访场景", title="客户拜访指南")

    if scenario == "worktime":
        if not has("chatbi.ask"):
            return PlannerPlan(
                scenario="fallback",
                steps=[],
                reason="员工未安装 ChatBI 技能",
                final_text="这项任务需要「ChatBI 数据查询」技能。请先为数字员工安装 `chatbi` 后再试。",
                title="能力不足",
            )
        steps = [
            _step("chatbi.list_tables", {}, "查看可用数据表"),
            _step("chatbi.describe_table", {"table": "worktime_fact"}, "读取工时表字段结构"),
            _step("chatbi.ask", {"question": content}, "生成并执行 SQL（权限网关）"),
        ]
        if has("dashboard.build"):
            steps.append(_step("dashboard.build", {}, "生成 KPI 与可视化大屏"))
        if has("report.write", "report.compose"):
            steps.append(_step("report.write", {}, "撰写深度分析报告"))
        return PlannerPlan(scenario="worktime", steps=steps, reason="识别为工时/效率分析场景", title="工时效率分析")

    return PlannerPlan(
        scenario="fallback",
        steps=[],
        reason="未命中标杆场景",
        final_text=_fallback_text(skills, has_tools=True),
        title="能力介绍",
    )


def _step(tool: str, params: dict, title: str) -> PlanStep:
    return PlanStep(tool=tool, params=params or {}, title=title)


def _first_file_id(attachments: list[dict]) -> str:
    for att in attachments or []:
        if att.get("fileId"):
            return str(att["fileId"])
    return ""


def _fallback_text(skills: list[str], *, has_tools: bool) -> str:
    if not has_tools or not skills:
        return (
            "当前数字员工还没有安装任何技能，所以暂时不能调用数据、文档或外部工具。\n\n"
            "你可以在「技能超市」为它安装技能（例如 ChatBI 数据问数、合同审查、销售情报），"
            "安装后我就能直接查库、读文档、产出大屏和报告。"
        )
    labels = [SKILL_LABELS.get(s, s) for s in skills]
    samples: list[str] = []
    for skill in skills:
        for sample in SKILL_SAMPLES.get(skill, [])[:1]:
            if sample not in samples:
                samples.append(sample)
        if len(samples) >= 3:
            break
    lines = [
        "我可以帮你做这些事（基于当前已安装的技能）：",
        f"- 已具备能力：{'、'.join(labels)}。",
    ]
    for idx, sample in enumerate(samples, 1):
        lines.append(f"{idx}. 「{sample}」")
    lines.append("")
    lines.append("把需求说得具体一些（对象、时间范围、期望产物），我会直接调用工具产出真实结果，而不是只给建议。")
    return "\n".join(lines)
