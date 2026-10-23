"""Agent 运行时主循环：Planner/LLM → 工具调用 → SSE 事件 → 持久化 → HITL。

`stream_chat()` 是唯一入口：
    async for event, data in stream_chat(db, user, employee, session, content, attachments):
        yield f"event: {event}\\ndata: {json.dumps(data)}\\n\\n"

事件严格为 start/delta/step/artifact/approval/error/done（契约 §7.2）。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from ..core.config import MAX_STEPS, SSE_QUEUE_TIMEOUT
from ..models import EmployeeSkill, Message, SessionModel, Skill, Template, utcnow, new_id
from . import registry
from .approvals import request_approval
from .artifacts import artifact_public, save_artifact
from .llm import get_provider, tool_call_to_step
from .planner import detect_scenario, plan as offline_plan
from .sandbox import get_provider as get_workspace_provider
from .types import PlanStep, ToolContext, ToolResult, new_step_id

# --------------------------------------------------------------------------- #
# 上下文装配
# --------------------------------------------------------------------------- #


def load_employee_skills(db, employee) -> list[str]:
    rows = (
        db.query(EmployeeSkill, Skill)
        .join(Skill, EmployeeSkill.skill_id == Skill.id)
        .filter(EmployeeSkill.employee_id == employee.id, EmployeeSkill.enabled == True)  # noqa: E712
        .all()
    )
    names = [skill.name for _, skill in rows]
    if names:
        return names
    # 兼容：从模板默认技能推导
    if getattr(employee, "template_id", None):
        template = db.get(Template, employee.template_id)
        for code in (template.default_skills or []) if template else []:
            skill = db.query(Skill).filter((Skill.name == code) | (Skill.id == code)).first()
            if skill:
                names.append(skill.name)
    return list(dict.fromkeys(names))


def _employee_memories(db, employee) -> list[str]:
    if not getattr(employee, "memory_enabled", True):
        return []
    from ..models import Memory

    rows = db.query(Memory).filter(Memory.employee_id == employee.id).order_by(Memory.created_at.desc()).limit(10).all()
    return [m.content for m in rows if m.content]


def build_system_prompt(db, user, employee, skills: list[str], tools, data_scope: str) -> str:
    soul = (employee.soul_md or "").strip() or f"你是「{employee.name}」，{employee.role_title or '企业数字员工'}。"
    memories = _employee_memories(db, employee)
    lines = [
        soul,
        "",
        f"你是 DataClaw 平台上的数字员工「{employee.name}」，当前以用户「{user.name}」的身份执行任务。",
        "原则：先查证再回答；只调用已安装技能提供的工具；不编造数据；产物必须来自真实工具结果。",
        "输出使用简体中文，结论先行，给具体数字与可执行下一步。",
        "",
        "## 已装技能",
        "、".join(skills) if skills else "（无）",
        "",
        "## 可用工具",
        registry.tool_catalog_text(tools),
        "",
        "## 数据权限",
        data_scope,
    ]
    if memories:
        lines += ["", "## 长期记忆", *[f"- {m}" for m in memories]]
    return "\n".join(lines)


def _make_title(content: str) -> str:
    import re

    text = (content or "").strip().replace("\n", " ")
    for prefix in ("帮我", "请帮我", "麻烦", "请", "帮忙", "我想", "我要", "麻烦帮我", "能不能"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    text = re.sub(r"^(一下|下|看看|查一下)[，,。\s]*", "", text)
    return (text[:20] or "新会话").strip()


def _attachment_context(attachments: list[dict]) -> str:
    if not attachments:
        return ""
    from .tools.doc_parse import extract_text

    parts = []
    for att in attachments:
        name = att.get("name") or ""
        path = att.get("path") or ""
        text = ""
        try:
            text, _ = extract_text(path, name) if path else ("", "")
        except Exception as exc:  # 附件解析失败不阻断主流程
            text = f"（附件解析失败：{exc}）"
        parts.append(f"### 附件：{name}\n{text[:15000]}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# 合成回答
# --------------------------------------------------------------------------- #


def _find_trace(trace: list[dict], *tools: str) -> dict | None:
    for item in reversed(trace):
        if item.get("tool") in tools:
            return item
    return None


def synthesize(scenario: str, state: dict, trace: list[dict], plan_title: str = "") -> str:
    if scenario == "worktime":
        chatbi = state.get("chatbi") or {}
        preview = state.get("dashboard_preview") or {}
        rows = chatbi.get("rows") or []
        regions = sorted({str(r.get("region") or "—") for r in rows})
        months = sorted({str(r.get("month") or "—") for r in rows})
        masked = chatbi.get("maskedColumns") or []
        kpis = {k.get("label"): k for k in preview.get("kpis") or []}
        total_hours = kpis.get("总工时", {}).get("value", "—")
        hours_delta = kpis.get("总工时", {}).get("delta", "—")
        efficiency = kpis.get("人均产出", {}).get("value", "—")
        overtime = kpis.get("加班率", {}).get("value", "—")
        report_chars = len(state.get("report_markdown") or "")
        report_title = state.get("report_title") or "工时效率深度分析报告"
        chart_count = len(preview.get("charts") or [])
        anomalies = [i.get("text", "") for i in preview.get("insights") or [] if i.get("level") in ("warn", "danger")]
        lines = [f"已完成{chatbi.get('period', {}).get('label') or '本周期'}工时效率分析，结论如下："]
        lines.append(
            f"1. 覆盖 **{len(regions)} 个区域 / {len(months)} 个月**，总工时 **{total_hours}**（环比 {hours_delta}），"
            f"整体人效 **{efficiency}**，加班率 {overtime}。"
        )
        if anomalies:
            lines.append(f"2. 异常提示：{anomalies[0]}")
        else:
            lines.append("2. 区域分布整体平稳，未出现均值±2σ 的显著离群点。")
        artifact_bits = []
        if preview:
            artifact_bits.append(f"「{preview.get('title')}」（{chart_count} 张图表）")
        if report_chars:
            artifact_bits.append(f"《{report_title}》深度报告（{report_chars} 字）")
        if artifact_bits:
            lines.append(f"3. 已交付：{'、'.join(artifact_bits)}，可直接查看或下载。")
        else:
            lines.append("3. 已完成数据查询，可继续让我生成大屏或报告。")
        permission = f"{', '.join(masked)} 已脱敏" if masked else "未触及脱敏字段"
        lines.append(f"4. 已按你的数据权限执行（{permission} / 行级过滤生效）。")
        return "\n".join(lines)

    if scenario == "sales":
        sales = state.get("sales") or {}
        profile = sales.get("profile") or {}
        summary = sales.get("summary") or {}
        guide = state.get("visit_guide") or {}
        web = state.get("web_results") or []
        if not sales:
            return "没有查到可用的客户数据，请确认客户名称或数据权限。"

        def _money(value) -> str:
            return "已按权限脱敏" if value is None else f"{value:,.0f} 元"

        lines: list[str] = []
        if sales.get("fallbackUsed") and sales.get("requestedName"):
            lines.append(
                f"> 说明：你提到的「{sales.get('requestedName')}」不在你负责的客户列表，"
                f"已改用你负责的「{profile.get('name', '客户')}」作为示例。\n"
            )
        lines.append(f"拜访 **{profile.get('name', '客户')}** 前，先做这 3 件事：")
        lines.append(
            f"1. **复盘合作底账**：历史订单 {summary.get('orderCount', 0)} 笔 / 累计 {_money(summary.get('totalOrderAmount'))}，"
            f"合同额 {_money(summary.get('contractsAmount'))}；最近沟通 {profile.get('lastContactAt') or '无记录'}"
            + (f"（已 {summary.get('daysSinceContact')} 天未联系）" if summary.get("daysSinceContact") is not None else "")
            + "。"
        )
        lines.append(
            f"2. **带着假设去**：客户属于{profile.get('industry') or '目标'}行业、等级 {profile.get('level') or '—'}，"
            f"优先验证「{((guide.get('meta') or {}).get('topNeed') or '数据整合与提效')}」；"
            f"已融合 {len(web)} 条内外部情报（外部为离线模拟，已标注）。"
        )
        lines.append(
            "3. **准备好话术与下一步**：按「痛点确认 → 价值假设 → 小范围试点」三段推进，"
            "结束时明确下次沟通时间与验收指标。"
        )
        if guide:
            lines.append("")
            lines.append(f"已生成《{guide.get('title') or '拜访指南'}》：含客户 360 画像、潜在需求预判、沟通策略与 3 段话术。")
        return "\n".join(lines)

    if scenario == "contract":
        data = state.get("contract") or {}
        stats = data.get("stats") or {}
        risks = data.get("risks") or []
        docx = state.get("contract_docx") or {}
        docx_step = _find_trace(trace, "contract_review.export_docx", "contract.redline_docx")
        lines = [
            f"合同审查完成：《{data.get('docName', '合同')}》共识别 **{stats.get('risks', len(risks))} 项风险**"
            f"（高 {stats.get('high', 0)} / 中 {stats.get('medium', 0)} / 低 {stats.get('low', 0)}）。"
        ]
        highlights = []
        for risk in risks:
            if risk.get("risk") == "high" and len(highlights) < 3:
                highlights.append(f"{risk.get('clause')} {risk.get('title')}")
        if highlights:
            lines.append(f"1. 高风险优先处理：{'；'.join(highlights)}。")
        if risks:
            medium = [r for r in risks if r.get("risk") == "medium"][:2]
            if medium:
                medium_text = "；".join(f"{r.get('clause')} {r.get('title')}" for r in medium)
                lines.append(f"2. 中风险需确认：{medium_text}。")
        if docx:
            lines.append(
                f"3. 已生成**带修订痕迹的修订版 docx**（{docx.get('stats', {}).get('risks', 0)} 项红黄标注，"
                f"作者 {docx.get('author', 'DataClaw')}），可在产物区下载；导出前的 HITL 审批已记录。"
            )
        elif docx_step and docx_step.get("status") == "skipped":
            note = docx_step.get("summary") or "已按你的审批决定跳过 docx 导出"
            lines.append(f"3. {note}；风险清单与修订建议见上方步骤结果。")
        elif docx_step and docx_step.get("status") == "error":
            lines.append(f"3. 修订版 docx 生成失败：{docx_step.get('error') or docx_step.get('summary') or '未知原因'}。")
        else:
            lines.append("3. 修订版 docx 暂未生成；如需导出，请在审批弹窗中确认。")
        lines.append("")
        lines.append("所有条款原文、风险等级与修订建议均已结构化留档，建议法务复核后用于商务谈判。")
        return "\n".join(lines)

    return ""


# --------------------------------------------------------------------------- #
# 单步执行
# --------------------------------------------------------------------------- #


async def _run_step(
    spec,
    step: PlanStep,
    *,
    db,
    user,
    employee,
    session_id: str,
    message_id: str,
    emit,
    approved: dict[str, bool],
    workspaces,
    attachments: list[dict],
    state: dict,
    trace: list[dict],
    auto_approve: bool,
    skill_names: list[str],
) -> ToolResult:
    ctx = ToolContext(
        db=db,
        user=user,
        employee=employee,
        session_id=session_id,
        message_id=message_id,
        emit=emit,
        approved=approved,
        workspaces=workspaces,
        step_id=step.step_id,
        tool_name=spec.name,
        skill_names=skill_names,
        attachments=attachments,
        state=state,
        auto_approve=auto_approve,
        trace=trace,
    )
    approval_status = "none"
    if spec.requires_approval and not approved.get(step.step_id):
        await emit(
            "step",
            {
                "id": step.step_id,
                "type": "tool_call",
                "tool": spec.name,
                "title": step.title or spec.title,
                "status": "running",
                "input": step.params,
                "risk": spec.risk,
            },
        )
        ok, approval, note = await request_approval(
            db,
            ctx,
            action="export_docx",
            reason="将导出含企业条款的修订版文件（人工审批后执行）",
            risk="high",
        )
        approval_status = approval.status
        if not ok:
            trace.append(
                {
                    "id": step.step_id,
                    "type": "tool_result",
                    "tool": spec.name,
                    "title": step.title or spec.title,
                    "status": "skipped",
                    "summary": note or "审批未通过，已跳过",
                    "risk": spec.risk,
                }
            )
            await emit(
                "step",
                {
                    "id": step.step_id,
                    "type": "tool_result",
                    "tool": spec.name,
                    "title": step.title or spec.title,
                    "status": "skipped",
                    "summary": note or "审批未通过，已跳过",
                },
            )
            return ToolResult(ok=False, error=note or "审批未通过")
    return await registry.execute_tool(spec, step.params, ctx, approval_status=approval_status)


async def _publish_artifact(db, user, employee, session_id: str, result: ToolResult, emit) -> dict | None:
    art = result.artifact
    if not art:
        return None
    saved = save_artifact(
        db,
        kind=art.get("kind") or "json",
        title=art.get("title") or "产物",
        payload=art.get("payload") or {},
        text=art.get("text") or "",
        file_path=art.get("file_path") or (art.get("payload") or {}).get("filePath") or "",
        file_name=art.get("file_name") or (art.get("payload") or {}).get("fileName") or "",
        session_id=session_id,
        employee_id=getattr(employee, "id", None),
        created_by=getattr(user, "id", None),
    )
    public = artifact_public(saved)
    await emit(
        "artifact",
        {
            "artifactId": saved.id,
            "kind": saved.kind,
            "title": saved.title,
            "preview": public["preview"],
            "fileName": public.get("fileName") or "",
            "downloadUrl": public["preview"].get("downloadUrl") or "",
        },
    )
    return public


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


async def _execute(
    db,
    user,
    employee,
    session,
    content: str,
    *,
    attachments: list[dict],
    emit,
    auto_approve: bool,
    result_meta: dict,
) -> None:
    started = time.time()
    message_id = new_id("msg")
    result_meta["messageId"] = message_id
    title = session.title if session.title and session.title != "新会话" else _make_title(content)
    await emit("start", {"messageId": message_id, "sessionId": session.id, "title": title})

    skill_names = load_employee_skills(db, employee)
    tools = registry.get_tools(skill_names)
    tool_map = {t.name: t for t in tools}
    workspaces = get_workspace_provider().ensure(getattr(employee, "id", "anon"))
    approved: dict[str, bool] = {}
    state: dict[str, Any] = {}
    trace: list[dict] = []
    artifacts_public: list[dict] = []
    final_text = ""
    step_count = 0
    tokens = 0
    scenario = detect_scenario(content, employee, attachments)

    # 附件文本注入规划上下文（LLM 模式用；工具也会各自解析）
    attachment_text = _attachment_context(attachments)
    try:
        data_scope = ""
        ds = None
        try:
            from . import get_demo_datasource, data_scope_summary

            ds = get_demo_datasource(db)
            if ds is not None:
                data_scope = data_scope_summary(db, user, ds.id)
        except Exception:
            data_scope = "数据权限：以当前登录用户身份执行。"
        system_prompt = build_system_prompt(db, user, employee, skill_names, tools, data_scope)
        if attachment_text:
            system_prompt += f"\n\n## 本次附件内容\n{attachment_text[:20000]}"

        provider = get_provider()
        use_llm = provider is not None and bool(tools)
        plan_title = ""
        completed = False

        if use_llm:
            try:
                final_text, step_count, tokens = await _run_llm_loop(
                    provider,
                    system_prompt=system_prompt,
                    content=content,
                    tools=tools,
                    db=db,
                    user=user,
                    employee=employee,
                    session=session,
                    message_id=message_id,
                    emit=emit,
                    approved=approved,
                    workspaces=workspaces,
                    attachments=attachments,
                    state=state,
                    trace=trace,
                    artifacts_public=artifacts_public,
                    auto_approve=auto_approve,
                    skill_names=skill_names,
                    started=started,
                )
                completed = bool(final_text)
            except Exception as exc:  # noqa: BLE001 LLM 故障降级离线
                await emit("error", {"message": f"LLM 调用失败，已切换离线规划：{exc}", "code": "LLM_FALLBACK"})

        if not completed:
            plan = offline_plan(
                user,
                employee,
                content,
                tools,
                skill_names=skill_names,
                attachments=attachments,
                db=db,
            )
            scenario = plan.scenario if plan.scenario != "fallback" else scenario
            plan_title = plan.title
            final_text = plan.final_text or ""
            for step in plan.steps:
                if step_count >= MAX_STEPS:
                    await emit("error", {"message": f"已达到单轮最大步数 {MAX_STEPS}", "code": "MAX_STEPS"})
                    break
                if time.time() - started > SSE_QUEUE_TIMEOUT:
                    await emit("error", {"message": "本轮执行超过最大时长，已提前结束", "code": "TIMEOUT"})
                    break
                spec = registry.get_tool(step.tool) or tool_map.get(step.tool)
                if spec is None:
                    await emit(
                        "step",
                        {
                            "id": step.step_id,
                            "type": "tool_result",
                            "tool": step.tool,
                            "title": step.title,
                            "status": "error",
                            "summary": f"工具未装载：{step.tool}",
                        },
                    )
                    trace.append(
                        {
                            "id": step.step_id,
                            "type": "tool_result",
                            "tool": step.tool,
                            "title": step.title,
                            "status": "error",
                            "summary": f"工具未装载：{step.tool}",
                        }
                    )
                    continue
                result = await _run_step(
                    spec,
                    step,
                    db=db,
                    user=user,
                    employee=employee,
                    session_id=session.id,
                    message_id=message_id,
                    emit=emit,
                    approved=approved,
                    workspaces=workspaces,
                    attachments=attachments,
                    state=state,
                    trace=trace,
                    auto_approve=auto_approve,
                    skill_names=skill_names,
                )
                step_count += 1
                if result.artifact:
                    public = await _publish_artifact(db, user, employee, session.id, result, emit)
                    if public:
                        artifacts_public.append(public)
                if not result.ok:
                    err = result.error or ""
                    output = result.output or {}
                    denied = bool(output.get("denied")) or any(k in err for k in ("无权", "拒绝", "denied"))
                    if denied:
                        available = output.get("availableTables") or []
                        reason = output.get("deniedReason") or err
                        final_text = (
                            f"这次无法继续执行：{reason}\n\n"
                            + (f"当前账号可见的表：{', '.join(available)}。\n\n" if available else "")
                            + "你可以：\n"
                            + "1. 让我改用上述有权限的表重新分析；\n"
                            + "2. 请管理员在「数据权限」中为当前账号授权后再试。\n\n"
                            + "本次越权尝试已写入审计（result=denied, risk=high）。"
                        )
                        break
                    if scenario in ("worktime", "sales") and step_count == 1:
                        # 第一步就失败（多数是权限/数据问题）：不继续串行，避免错误级联
                        final_text = (
                            f"任务没有继续执行：{err}\n\n"
                            "这通常表示当前账号的数据权限（表/列/行级）不足，或演示数据未就绪。"
                            "你可以让管理员在「数据权限」中授权后重试。"
                        )
                        break

            if not final_text:
                final_text = synthesize(scenario, state, trace, plan_title) or (
                    "任务已执行完成，但没有可汇总的结果。请补充更具体的业务对象与时间范围后重试。"
                )

        if not final_text:
            final_text = synthesize(scenario, state, trace) or "已执行完成。"

    except Exception as exc:  # noqa: BLE001
        await emit("error", {"message": f"执行异常：{type(exc).__name__}: {exc}", "code": "INTERNAL_ERROR"})
        final_text = final_text or "抱歉，本次执行遇到内部错误，已记录审计日志。请稍后重试或换一种问法。"
    finally:
        # 流式输出最终回答
        for chunk in _chunks(final_text, 60):
            await emit("delta", {"text": chunk})

        tokens = tokens or max(1, len(final_text) // 4 + sum(len(str(t.get("output", ""))) // 4 for t in trace))
        latency = int((time.time() - started) * 1000)
        _persist_assistant(
            db,
            session=session,
            message_id=message_id,
            content=final_text,
            trace=trace,
            artifacts=artifacts_public,
            tokens=tokens,
            latency_ms=latency,
        )
        result_meta.update(
            {
                "content": final_text,
                "steps": trace,
                "artifacts": artifacts_public,
                "usage": {"tokens": tokens, "steps": len([t for t in trace if t.get("type") == "tool_result"])},
                "latencyMs": latency,
            }
        )
        await emit(
            "done",
            {
                "messageId": message_id,
                "usage": {"tokens": tokens, "steps": result_meta["usage"]["steps"]},
                "latencyMs": latency,
            },
        )


def _chunks(text: str, size: int = 60):
    text = text or ""
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _persist_assistant(db, *, session, message_id, content, trace, artifacts, tokens, latency_ms) -> None:
    msg = Message(
        id=message_id,
        session_id=session.id,
        role="assistant",
        content=content,
        steps=[_trim_step(t) for t in trace],
        artifacts=artifacts,
        tokens=tokens,
        latency_ms=latency_ms,
    )
    db.add(msg)
    session.message_count = (session.message_count or 0) + 1
    session.last_message_at = utcnow()
    if not session.title or session.title == "新会话":
        last_user = (
            db.query(Message)
            .filter(Message.session_id == session.id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .first()
        )
        if last_user:
            session.title = _make_title(last_user.content)
    db.add(session)
    employee = None
    try:
        from ..models import Employee

        employee = db.get(Employee, session.employee_id)
        if employee is not None:
            employee.last_active_at = utcnow()
            db.add(employee)
    except Exception:
        pass
    db.commit()


def _trim_step(step: dict) -> dict:
    out = dict(step)
    output = out.get("output")
    if isinstance(output, dict):
        text = json.dumps(output, ensure_ascii=False, default=str)
        if len(text) > 4000:
            out["output"] = {k: v for k, v in output.items() if k in ("rowCount", "columns", "maskedColumns", "tables", "stats", "title", "charts", "kpis", "filePath", "fileName")}
    return out


async def _run_llm_loop(
    provider,
    *,
    system_prompt: str,
    content: str,
    tools,
    db,
    user,
    employee,
    session,
    message_id: str,
    emit,
    approved: dict[str, bool],
    workspaces,
    attachments: list[dict],
    state: dict,
    trace: list[dict],
    artifacts_public: list[dict],
    auto_approve: bool,
    skill_names: list[str],
    started: float,
) -> tuple[str, int, int]:
    schemas = [t.schema_for_llm() for t in tools]
    name_index = {t.name.replace(".", "__"): t.name for t in tools}
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    history = (
        db.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.created_at.desc())
        .limit(8)
        .all()
    )
    for item in reversed(history):
        if item.role in ("user", "assistant") and item.content:
            if item.role == "user" and item.content == content:
                continue
            messages.append({"role": item.role, "content": item.content[:4000]})
    messages.append({"role": "user", "content": content})

    step_count = 0
    tokens = 0
    final_text = ""
    for _ in range(MAX_STEPS):
        if time.time() - started > SSE_QUEUE_TIMEOUT:
            await emit("error", {"message": "本轮执行超过最大时长", "code": "TIMEOUT"})
            break
        resp = await provider.complete(messages, schemas)
        usage = resp.get("usage") or {}
        tokens += int(usage.get("total_tokens") or 0)
        tool_calls = resp.get("tool_calls") or []
        text = (resp.get("content") or "").strip()
        if not tool_calls:
            final_text = text
            break
        messages.append({"role": "assistant", "content": text, "tool_calls": tool_calls})
        for call in tool_calls:
            norm = tool_call_to_step(call)
            name = name_index.get(norm["name"], norm["name"].replace("__", "."))
            spec = registry.get_tool(name)
            if spec is None:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": norm.get("callId") or "",
                        "content": json.dumps({"ok": False, "error": f"工具未装载：{name}"}, ensure_ascii=False),
                    }
                )
                continue
            step = PlanStep(tool=name, params=norm.get("params") or {}, step_id=new_step_id(), title=spec.title)
            step_count += 1
            result = await _run_step(
                spec,
                step,
                db=db,
                user=user,
                employee=employee,
                session_id=session.id,
                message_id=message_id,
                emit=emit,
                approved=approved,
                workspaces=workspaces,
                attachments=attachments,
                state=state,
                trace=trace,
                auto_approve=auto_approve,
                skill_names=skill_names,
            )
            if result.artifact:
                public = await _publish_artifact(db, user, employee, session.id, result, emit)
                if public:
                    artifacts_public.append(public)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": norm.get("callId") or "",
                    "content": json.dumps(result.to_step_output(), ensure_ascii=False, default=str)[:6000],
                }
            )
    if not final_text:
        final_text = synthesize(detect_scenario(content, employee, attachments), state, trace)
    return final_text, step_count, tokens


async def stream_chat(
    db,
    user,
    employee,
    session,
    content: str,
    attachments: list[dict] | None = None,
    *,
    auto_approve: bool = False,
) -> AsyncIterator[tuple[str, dict]]:
    """产出 (event, data)；由 API 层格式化为 SSE 或聚合为 JSON。"""
    queue: asyncio.Queue = asyncio.Queue()
    meta: dict[str, Any] = {}

    async def emit(event: str, data: dict) -> None:
        await queue.put((event, dict(data)))

    async def runner() -> None:
        try:
            await _execute(
                db,
                user,
                employee,
                session,
                content,
                attachments=list(attachments or []),
                emit=emit,
                auto_approve=auto_approve,
                result_meta=meta,
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        await task
    finally:
        if not task.done():
            task.cancel()


async def collect_chat(
    db,
    user,
    employee,
    session,
    content: str,
    attachments: list[dict] | None = None,
    *,
    auto_approve: bool = True,
) -> dict:
    """非流式聚合（?stream=false / 渠道 / 测试）。"""
    content_parts: list[str] = []
    steps: dict[str, dict] = {}
    step_order: list[str] = []
    artifacts: list[dict] = []
    approvals: dict[str, dict] = {}
    usage: dict = {}
    latency = 0
    message_id = ""
    started = time.time()
    async for event, data in stream_chat(
        db, user, employee, session, content, attachments, auto_approve=auto_approve
    ):
        if event == "start":
            message_id = data.get("messageId") or message_id
        elif event == "delta":
            content_parts.append(str(data.get("text") or ""))
        elif event == "step":
            step_id = str(data.get("id") or "")
            if step_id and step_id not in steps:
                step_order.append(step_id)
            if step_id:
                steps.setdefault(step_id, {}).update(data)
        elif event == "artifact":
            artifacts.append(data)
        elif event == "approval":
            approval_id = str(data.get("approvalId") or "")
            if approval_id:
                approvals.setdefault(approval_id, {}).update(data)
        elif event == "error":
            steps.setdefault("__error__", {"type": "error", **data})
        elif event == "done":
            usage = data.get("usage") or {}
            latency = int(data.get("latencyMs") or 0)
            message_id = data.get("messageId") or message_id

    # 审批最终状态以 DB 为准（autoApprove / approved / rejected / timeout）
    try:
        from ..models import Approval

        rows = db.query(Approval).filter(Approval.message_id == message_id).all() if message_id else []
        for row in rows:
            approvals.setdefault(row.id, {}).update(
                {
                    "approvalId": row.id,
                    "action": row.action,
                    "reason": row.reason,
                    "risk": row.risk,
                    "status": row.status,
                    "autoApprove": bool(approvals.get(row.id, {}).get("autoApprove", False)),
                }
            )
        db.refresh(session)
    except Exception:
        pass

    ordered_steps = [steps[s] for s in step_order if s in steps]
    if "__error__" in steps:
        ordered_steps.append(steps["__error__"])
    if not latency:
        latency = int((time.time() - started) * 1000)
    return {
        "messageId": message_id,
        "sessionId": session.id,
        "title": session.title,
        "content": "".join(content_parts),
        "steps": ordered_steps,
        "artifacts": artifacts,
        "approvals": list(approvals.values()),
        "usage": usage,
        "latencyMs": latency,
    }
