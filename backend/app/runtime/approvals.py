"""HITL 审批：挂起/唤醒 + 审批落库与审计。

流程（契约 §7.2）：
runner 在需要审批的步骤前调用 `request_approval()`：
  1) 落 approvals(status=pending) + emit `approval` 事件；
  2) await broker.wait(approvalId, timeout) —— 期间流挂起；
  3) 前端 POST /api/sessions/{sid}/approvals/{id} → `decide_approval()`
     → broker.resolve() 唤醒等待者 → runner 继续或跳过该步。
非流式（?stream=false / 渠道）走 auto_approve=True：审批直接通过但仍落审计，
保证自动化调用与测试可跑通。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from ..core.deps import audit
from ..models import Approval, utcnow


class ApprovalBroker:
    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}

    def _entry(self, approval_id: str) -> dict[str, Any]:
        entry = self._entries.get(approval_id)
        if entry is None:
            entry = {"future": None, "decision": None}
            self._entries[approval_id] = entry
        return entry

    def bind_loop(self, approval_id: str) -> None:
        """在当前事件循环内为审批创建 Future（必须在 wait 前调用）。"""
        entry = self._entry(approval_id)
        if entry.get("future") is None or entry["future"].done():
            entry["future"] = asyncio.get_running_loop().create_future()

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """唤醒等待者；返回是否真的唤醒了挂起的流。"""
        entry = self._entry(approval_id)
        entry["decision"] = bool(approved)
        future: asyncio.Future | None = entry.get("future")
        if future is not None and not future.done():
            future.set_result(bool(approved))
            return True
        return False

    async def wait(self, approval_id: str, timeout: float) -> bool | None:
        entry = self._entry(approval_id)
        if entry.get("decision") is not None:
            return bool(entry["decision"])
        if entry.get("future") is None or entry["future"].done():
            entry["future"] = asyncio.get_running_loop().create_future()
        try:
            return bool(await asyncio.wait_for(entry["future"], timeout=timeout))
        except asyncio.TimeoutError:
            return None

    def cleanup(self, approval_id: str) -> None:
        self._entries.pop(approval_id, None)


broker = ApprovalBroker()


async def request_approval(
    db,
    ctx,
    *,
    action: str,
    reason: str,
    risk: str = "high",
    timeout: float | None = None,
) -> tuple[bool, Approval, str]:
    """创建审批并挂起等待；返回 (approved, approval, note)。"""
    from ..core.config import SSE_QUEUE_TIMEOUT

    approval = Approval(
        session_id=ctx.session_id,
        message_id=ctx.message_id,
        step_id=ctx.step_id,
        action=action,
        reason=(reason or "")[:300],
        risk=risk if risk in ("low", "medium", "high") else "high",
        status="pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)

    auto = bool(getattr(ctx, "auto_approve", False))
    if auto:
        note = "非流式模式：审批已自动通过（演示模式自动批准，已记录 hitl_approval 审计）"
        approval.status = "approved"
        approval.decided_by = getattr(ctx.user, "id", None)
        approval.decided_at = utcnow()
        db.add(approval)
        db.commit()
        audit(
            db,
            actor=ctx.user,
            action="hitl_approval",
            target_type="approval",
            target_id=approval.id,
            target_name=action,
            detail={"decision": "approved", "mode": "auto", "reason": reason},
            risk=approval.risk,
            session_id=ctx.session_id,
            commit=True,
        )
        ctx.approved[ctx.step_id] = True
        await ctx.emit(
            "approval",
            {
                "approvalId": approval.id,
                "stepId": ctx.step_id,
                "action": action,
                "reason": reason,
                "risk": approval.risk,
                "autoApprove": True,
                "status": "approved",
                "decision": "approved",
                "note": note,
            },
        )
        return True, approval, note

    await ctx.emit(
        "approval",
        {
            "approvalId": approval.id,
            "stepId": ctx.step_id,
            "action": action,
            "reason": reason,
            "risk": approval.risk,
            "autoApprove": False,
            "status": "pending",
            "decision": None,
        },
    )

    wait_timeout = float(timeout if timeout is not None else SSE_QUEUE_TIMEOUT)
    broker.bind_loop(approval.id)
    decision = await broker.wait(approval.id, wait_timeout)
    broker.cleanup(approval.id)

    if decision is None:
        # 超时：自动取消，不能永远挂起
        approval.status = "rejected"
        approval.decided_by = None
        approval.decided_at = utcnow()
        db.add(approval)
        db.commit()
        audit(
            db,
            actor=ctx.user,
            action="hitl_approval",
            target_type="approval",
            target_id=approval.id,
            target_name=action,
            detail={"decision": "timeout", "mode": "stream", "timeoutSeconds": wait_timeout, "reason": reason},
            risk=approval.risk,
            result="denied",
            session_id=ctx.session_id,
            commit=True,
        )
        await ctx.emit(
            "approval",
            {
                "approvalId": approval.id,
                "stepId": ctx.step_id,
                "action": action,
                "reason": reason,
                "risk": approval.risk,
                "autoApprove": False,
                "status": "rejected",
                "decision": "timeout",
                "note": "已取消（超时未审批）",
            },
        )
        return False, approval, "已取消（超时未审批）"

    approval.status = "approved" if decision else "rejected"
    approval.decided_by = getattr(ctx.user, "id", None)
    approval.decided_at = utcnow()
    db.add(approval)
    db.commit()
    ctx.approved[ctx.step_id] = decision
    await ctx.emit(
        "approval",
        {
            "approvalId": approval.id,
            "stepId": ctx.step_id,
            "action": action,
            "reason": reason,
            "risk": approval.risk,
            "autoApprove": False,
            "status": approval.status,
            "decision": approval.status,
            "note": "" if decision else "已按你的决定跳过导出",
        },
    )
    return decision, approval, "" if decision else "已按你的决定跳过导出"


def decide_approval(db, approval_id: str, approved: bool, user) -> Approval | None:
    approval = db.get(Approval, approval_id)
    if approval is None:
        return None
    if approval.status == "pending":
        approval.status = "approved" if approved else "rejected"
        approval.decided_by = getattr(user, "id", None)
        approval.decided_at = utcnow()
        db.add(approval)
        db.commit()
        audit(
            db,
            actor=user,
            action="hitl_approval",
            target_type="approval",
            target_id=approval.id,
            target_name=approval.action,
            detail={"decision": approval.status, "reason": approval.reason, "mode": "manual"},
            risk=approval.risk,
            session_id=approval.session_id,
            commit=True,
        )
    broker.resolve(approval_id, approved)
    return approval
