"""工具注册表：技能 → 工具装载 + 统一执行壳（超时/事件/tool_calls/审计）。

命名约定：
- 权威 toolNames 与 be-data 的 `seed/skills_data.py` 完全一致（见 SKILL_TO_TOOLS）。
- 任务书/前端契约里出现的旧名（dashboard.build、report.write、
  sales_intel.customer_360、contract_review.analyze ...）作为别名注册，
  与权威名指向同一 handler；`get_tools()` 会把别名一并挂给已装技能。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..core.config import TOOL_TIMEOUT
from ..core.deps import audit
from ..models import ToolCall
from .types import ToolContext, ToolResult, ToolSpec, emit_step

# 与 seed/skills_data.py 的 skills.tool_names 严格一致（be-data 定稿）
SKILL_TO_TOOLS: dict[str, list[str]] = {
    "chatbi": ["chatbi.list_tables", "chatbi.describe_table", "chatbi.ask"],
    "dashboard-builder": ["dashboard.build", "dashboard.export_html"],
    "deep-report": ["report.outline", "report.compose", "report.export_markdown"],
    "contract-review": ["contract.parse_clauses", "contract.risk_scan", "contract.redline_docx"],
    "sales-intel": ["sales.customer360", "sales.visit_guide", "sales.contact_summary"],
    "knowhow-search": ["kb.search", "kb.read_doc"],
    "doc-parse": ["doc.list_files", "doc.parse_text", "doc.save_note"],
    "pptx-export": ["pptx.outline", "pptx.build"],
    "excel-toolkit": ["excel.read", "excel.transform", "excel.export"],
    "web-search": ["web.search", "web.fetch"],
    "data-cleaner": ["clean.profile", "clean.transform", "clean.save"],
    "agent-browser": ["browser.open", "browser.extract"],
}

# 任务书/契约别名 → 权威名
ALIASES: dict[str, str] = {
    "report.write": "report.compose",
    "report.build": "report.compose",
    "sales_intel.customer_360": "sales.customer360",
    "sales_intel.build_guide": "sales.visit_guide",
    "knowledge_search.query": "kb.search",
    "doc_parse.parse": "doc.parse_text",
    "contract_review.analyze": "contract.risk_scan",
    "contract_review.export_docx": "contract.redline_docx",
    "web_search.query": "web.search",
    "pptx_export.build": "pptx.build",
    "excel.export_report": "excel.export",
}

_SPECS: dict[str, ToolSpec] | None = None


def _load_specs() -> dict[str, ToolSpec]:
    global _SPECS
    if _SPECS is not None:
        return _SPECS
    specs: dict[str, ToolSpec] = {}
    # 延迟导入，避免 runtime 包初始化时与工具模块循环依赖
    from .tools import chatbi, contract, dashboard, excel_toolkit, knowledge_search, pptx_export, report, sales_intel, doc_parse, web_search

    modules = [chatbi, dashboard, report, sales_intel, contract, knowledge_search, doc_parse, web_search, excel_toolkit, pptx_export]
    for mod in modules:
        for spec in getattr(mod, "TOOLS", []):
            if not spec.skill:
                spec.skill = next((s for s, names in SKILL_TO_TOOLS.items() if spec.name in names), "")
            specs[spec.name] = spec

    # 注册别名（同一 handler，独立 spec 名称）
    for alias, canonical in ALIASES.items():
        if alias in specs or canonical not in specs:
            continue
        base = specs[canonical]
        specs[alias] = ToolSpec(
            name=alias,
            title=base.title,
            description=base.description,
            params=base.params,
            handler=base.handler,
            risk=base.risk,
            requires_approval=base.requires_approval,
            skill=base.skill,
        )
    _SPECS = specs
    return specs


def available_tool_names() -> list[str]:
    return sorted(_load_specs().keys())


def get_tool(name: str) -> ToolSpec | None:
    specs = _load_specs()
    if name in specs:
        return specs[name]
    canonical = ALIASES.get(name)
    return specs.get(canonical) if canonical else None


def get_tools(skill_names: list[str]) -> list[ToolSpec]:
    """按员工已装技能装载工具；未装技能 = 没有工具（权限即能力）。"""
    specs = _load_specs()
    selected: list[str] = []
    for skill in skill_names or []:
        for name in SKILL_TO_TOOLS.get(skill, []):
            canonical = name
            if canonical in specs and canonical not in selected:
                selected.append(canonical)
            # 同一技能的别名也挂上，保证规划器/前端两种叫法都能跑
            for alias, target in ALIASES.items():
                if target == canonical and alias not in selected:
                    selected.append(alias)
    return [specs[n] for n in selected if n in specs]


def tool_catalog_text(tools: list[ToolSpec]) -> str:
    if not tools:
        return "（当前员工未安装任何技能，没有可用工具）"
    lines = []
    for spec in tools:
        lines.append(f"- {spec.name}（{spec.title}，risk={spec.risk}）：{spec.description}")
    return "\n".join(lines)


def _summarize(params: dict, limit: int = 300) -> dict:
    out: dict = {}
    for k, v in (params or {}).items():
        text = v if isinstance(v, (int, float, bool)) or v is None else str(v)
        if isinstance(text, str) and len(text) > limit:
            text = text[:limit] + "…"
        out[k] = text
    return out


async def execute_tool(
    spec: ToolSpec,
    params: dict,
    ctx: ToolContext,
    *,
    timeout: float | None = None,
    approval_status: str = "none",
) -> ToolResult:
    """统一执行壳：emit running → wait_for(handler) → tool_calls/审计 → emit done。"""
    started = time.time()
    ctx.tool_name = spec.name
    step_id = ctx.step_id
    call = ToolCall(
        session_id=ctx.session_id,
        message_id=ctx.message_id,
        step_id=step_id,
        tool=spec.name,
        title=spec.title,
        input=_summarize(params),
        status="running",
        risk=spec.risk,
        approval=approval_status,
        duration_ms=0,
    )
    ctx.db.add(call)
    ctx.db.commit()

    await emit_step(
        ctx,
        "running",
        title=spec.title,
        input=_summarize(params),
        risk=spec.risk,
        requiresApproval=spec.requires_approval,
    )

    effective_timeout = float(timeout or TOOL_TIMEOUT)
    try:
        result = await asyncio.wait_for(spec.handler(params or {}, ctx), timeout=effective_timeout)
        if not isinstance(result, ToolResult):
            result = ToolResult(ok=False, error="工具返回了非法结果类型")
    except asyncio.TimeoutError:
        result = ToolResult(ok=False, error=f"工具执行超时（>{effective_timeout:.0f}s）")
    except Exception as exc:  # noqa: BLE001 工具内部异常统一转 ToolResult
        result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    duration = int((time.time() - started) * 1000)
    step_record = {
        "id": step_id,
        "type": "tool_result",
        "tool": spec.name,
        "title": spec.title,
        "status": "done" if result.ok else ("denied" if "无权" in (result.error or "") else "error"),
        "input": _summarize(params),
        "output": result.to_step_output(),
        "summary": result.summary,
        "durationMs": duration,
        "risk": spec.risk,
        "error": result.error,
    }
    ctx.trace.append(step_record)

    # 持久化 tool_calls
    call.status = "done" if result.ok else "error"
    call.output = _summarize(result.to_step_output(), 2000)
    call.duration_ms = duration
    ctx.db.add(call)
    ctx.db.commit()

    # 审计：成功/失败都落；权限拒绝按高风险记录
    denied = (not result.ok) and bool((result.output or {}).get("denied") or "无权" in (result.error or "") or "拒绝" in (result.error or ""))
    audit(
        ctx.db,
        actor=ctx.user,
        action="tool_call",
        target_type="tool",
        target_id=spec.name,
        target_name=spec.title,
        detail={
            "tool": spec.name,
            "risk": "high" if denied else spec.risk,
            "ok": result.ok,
            "durationMs": duration,
            "input": _summarize(params, 200),
            "error": result.error[:300],
            "deniedReason": (result.output or {}).get("deniedReason") or "",
            "availableTables": (result.output or {}).get("availableTables") or [],
            "approval": approval_status,
        },
        risk="high" if denied else (spec.risk if spec.risk in ("low", "medium", "high") else "low"),
        result="denied" if denied else ("success" if result.ok else "error"),
        session_id=ctx.session_id,
        commit=True,
    )

    await emit_step(
        ctx,
        "done" if result.ok else "error",
        title=spec.title,
        output=result.to_step_output(),
        durationMs=duration,
        summary=result.summary,
        error=result.error,
    )
    return result


async def execute_by_name(name: str, params: dict, ctx: ToolContext, **kwargs: Any) -> ToolResult:
    spec = get_tool(name)
    if spec is None:
        return ToolResult(ok=False, error=f"工具未装载：{name}（请为员工安装对应技能）")
    return await execute_tool(spec, params, ctx, **kwargs)
