"""审计接口：全链路审计流水与统计（契约 §8.11）。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import get_current_user, paginate
from ..models import AuditEvent, User, iso, utcnow

router = APIRouter(prefix="/audit", tags=["审计"])

ACTION_LABELS: dict[str, str] = {
    "login": "登录",
    "logout": "登出",
    "chat": "会话提问",
    "tool_call": "工具调用",
    "sql_query": "数据查询",
    "export": "导出",
    "skill_install": "技能安装",
    "skill_upload": "技能上传",
    "agent_assign": "公共员工分配",
    "policy_change": "权限变更",
    "doc_upload": "文档上传",
    "doc_read": "文档读取",
    "hitl_approval": "人工审批",
    "channel_test": "渠道测试",
    "employee_create": "员工创建",
    "employee_update": "员工配置",
    "skill_review": "技能审核",
}

RISK_LEVELS = ("low", "medium", "high")
RESULTS = ("success", "denied", "error")


def action_label(action: str) -> str:
    """审计动作的中文标签（未知动作原样返回）。"""
    return ACTION_LABELS.get(action, action or "")


def _parse_time(value: str, *, end: bool = False) -> datetime | None:
    """解析 YYYY-MM-DD 或 ISO8601（允许带 Z）为 UTC naive 时间。"""
    raw = (value or "").strip()
    if not raw:
        return None
    text = raw[:-1] if raw.endswith("Z") else raw
    try:
        if len(text) == 10:
            day = datetime.strptime(text, "%Y-%m-%d")
            return day + timedelta(days=1) - timedelta(microseconds=1) if end else day
        return datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_TIME", "message": "时间格式不正确，应为 YYYY-MM-DD 或 ISO8601"},
        )


def visibility_filter(db: Session, user: User) -> list:
    """可见范围：platform_admin=全部 / dept_admin=本部门 / member=仅自己。"""
    if user.role == "platform_admin":
        return []
    if user.role == "dept_admin":
        dept_ids = select(User.id).where(User.dept == (user.dept or ""))
        return [or_(AuditEvent.actor_id.in_(dept_ids), AuditEvent.actor_id == user.id)]
    return [AuditEvent.actor_id == user.id]


def _base_stmt(db: Session, user: User):
    return select(AuditEvent).where(*visibility_filter(db, user))


@router.get("")
def list_audit(
    action: str = Query(default=""),
    actorId: str = Query(default=""),
    risk: str = Query(default=""),
    result: str = Query(default=""),
    keyword: str = Query(default=""),
    from_: str = Query(default="", alias="from"),
    to: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """审计流水（倒序分页，按角色自动收窄可见范围）。"""
    stmt = _base_stmt(db, user)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if actorId:
        stmt = stmt.where(AuditEvent.actor_id == actorId)
    if risk:
        if risk not in RISK_LEVELS:
            raise HTTPException(
                status_code=400,
                detail={"code": "BAD_RISK", "message": "风险等级仅支持 low/medium/high"},
            )
        stmt = stmt.where(AuditEvent.risk == risk)
    if result:
        if result not in RESULTS:
            raise HTTPException(
                status_code=400,
                detail={"code": "BAD_RESULT", "message": "结果仅支持 success/denied/error"},
            )
        stmt = stmt.where(AuditEvent.result == result)
    start = _parse_time(from_)
    if start is not None:
        stmt = stmt.where(AuditEvent.ts >= start)
    end = _parse_time(to, end=True)
    if end is not None:
        stmt = stmt.where(AuditEvent.ts <= end)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            or_(
                AuditEvent.actor_name.like(like),
                AuditEvent.target_name.like(like),
                AuditEvent.target_id.like(like),
                AuditEvent.action.like(like),
            )
        )
    stmt = stmt.order_by(AuditEvent.ts.desc())
    page_data = paginate(db, stmt, page, size)
    rows: list[AuditEvent] = page_data["items"]
    items = [
        {
            "id": ev.id,
            "ts": iso(ev.ts),
            "actorId": ev.actor_id,
            "actorName": ev.actor_name or "系统",
            "action": ev.action,
            "actionLabel": action_label(ev.action),
            "targetType": ev.target_type or "",
            "targetId": ev.target_id or "",
            "targetName": ev.target_name or "",
            "detail": ev.detail or {},
            "risk": ev.risk or "low",
            "result": ev.result or "success",
            "ip": ev.ip or "",
            "sessionId": ev.session_id,
        }
        for ev in rows
    ]
    return {"items": items, "total": page_data["total"], "page": page, "size": size}


@router.get("/stats")
def audit_stats(
    days: int = Query(default=7, ge=1, le=90),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """审计统计：按动作/风险/结果聚合 + 每日趋势 + Top 操作人。"""
    now = utcnow()
    start_day = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    scope = visibility_filter(db, user)

    def _group(column) -> list[dict]:
        rows = db.execute(
            select(column, func.count(AuditEvent.id))
            .where(AuditEvent.ts >= start_day, *scope)
            .group_by(column)
            .order_by(func.count(AuditEvent.id).desc())
        ).all()
        return [{"key": k, "count": int(v)} for k, v in rows]

    by_action = [
        {"action": row["key"] or "", "label": action_label(row["key"] or ""), "count": row["count"]}
        for row in _group(AuditEvent.action)
    ]
    by_risk = [{"risk": row["key"] or "low", "count": row["count"]} for row in _group(AuditEvent.risk)]
    by_result = [
        {"result": row["key"] or "success", "count": row["count"]} for row in _group(AuditEvent.result)
    ]

    actor_rows = db.execute(
        select(AuditEvent.actor_id, AuditEvent.actor_name, func.count(AuditEvent.id))
        .where(AuditEvent.ts >= start_day, *scope, AuditEvent.actor_id.is_not(None))
        .group_by(AuditEvent.actor_id)
        .order_by(func.count(AuditEvent.id).desc())
        .limit(10)
    ).all()
    top_actors = [
        {
            "actorId": actor_id,
            "actorName": (name or actor_id),
            "count": int(count),
        }
        for actor_id, name, count in actor_rows
    ]

    trend_rows = db.execute(
        select(AuditEvent.ts, AuditEvent.result).where(AuditEvent.ts >= start_day, *scope)
    ).all()
    buckets: dict[str, list[int]] = {}
    for day in range(days):
        key = (start_day + timedelta(days=day)).strftime("%Y-%m-%d")
        buckets[key] = [0, 0]
    for ts, result in trend_rows:
        if ts is None:
            continue
        key = ts.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(key, [0, 0])
        bucket[0] += 1
        if result == "denied":
            bucket[1] += 1
    trend = [{"date": key, "count": val[0], "denied": val[1]} for key, val in sorted(buckets.items())]

    total = sum(item["count"] for item in by_action)
    denied = next((item["count"] for item in by_result if item["result"] == "denied"), 0)
    return {
        "byAction": by_action,
        "byRisk": by_risk,
        "byResult": by_result,
        "trend": trend,
        "topActors": top_actors,
        "total": total,
        "denied": denied,
        "days": days,
        "from": iso(start_day),
        "to": iso(now),
    }
