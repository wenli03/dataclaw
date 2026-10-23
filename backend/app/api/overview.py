"""总览 API（契约 §8.11）：全部指标由 SQL 聚合实时计算，不写死数字。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import get_current_user, is_admin
from ..models import (
    AuditEvent, ColumnMeta, Employee, Message, SessionModel, Skill, TableMeta,
    ToolCall, User,
)
from ..services import datasource_service

router = APIRouter(tags=["overview"])


def _count(db: Session, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for w in where:
        stmt = stmt.where(w)
    return int(db.scalar(stmt) or 0)


@router.get("/overview")
def overview(
    days: int = Query(default=7, ge=1, le=90),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    stats = {
        "employees": _count(db, Employee, Employee.status == "active"),
        "sessions": _count(db, SessionModel),
        "messages": _count(db, Message),
        "toolCalls": _count(db, ToolCall),
        "denied": _count(db, AuditEvent, AuditEvent.result == "denied"),
        "skills": _count(db, Skill, Skill.status == "approved"),
        "users": _count(db, User, User.status == "active"),
        "activeUsers": int(
            db.scalar(
                select(func.count(func.distinct(AuditEvent.actor_id))).where(
                    AuditEvent.ts >= start, AuditEvent.actor_id.isnot(None)
                )
            ) or 0
        ),
        "auditEvents": _count(db, AuditEvent),
        "highRisk": _count(db, AuditEvent, AuditEvent.risk == "high", AuditEvent.ts >= start),
        "knowledgeDocs": 0,
        "policies": 0,
    }
    from ..models import KnowledgeDoc, Policy

    stats["knowledgeDocs"] = _count(db, KnowledgeDoc)
    stats["policies"] = _count(db, Policy, Policy.enabled.is_(True))
    stats["chunks"] = int(
        db.scalar(select(func.coalesce(func.sum(KnowledgeDoc.chunk_count), 0))) or 0
    )

    # 近 N 日趋势：chat 次数（约等于会话轮次）与工具调用次数
    trend_rows = db.execute(
        select(
            func.date(AuditEvent.ts).label("d"),
            func.sum(func.iif(AuditEvent.action == "chat", 1, 0)).label("chats"),
            func.sum(func.iif(AuditEvent.action == "tool_call", 1, 0)).label("tools"),
            func.sum(func.iif(AuditEvent.action == "sql_query", 1, 0)).label("sqls"),
            func.sum(func.iif(AuditEvent.result == "denied", 1, 0)).label("denied"),
        )
        .where(AuditEvent.ts >= start)
        .group_by(func.date(AuditEvent.ts))
        .order_by(func.date(AuditEvent.ts))
    ).all()
    by_date = {str(r[0]): r for r in trend_rows}
    trend: list[dict] = []
    for i in range(days):
        day = (start + timedelta(days=i)).date().isoformat()
        row = by_date.get(day)
        trend.append(
            {
                "date": day,
                "sessions": int(row[1] or 0) if row else 0,
                "toolCalls": int(row[2] or 0) if row else 0,
                "sqlQueries": int(row[3] or 0) if row else 0,
                "denied": int(row[4] or 0) if row else 0,
            }
        )

    # 员工活跃榜：会话数 / 消息数 / 工具调用数
    emp_rows = db.execute(
        select(
            Employee.id,
            Employee.name,
            Employee.avatar,
            Employee.owner_id,
            func.count(func.distinct(SessionModel.id)).label("sessions"),
            func.coalesce(func.sum(SessionModel.message_count), 0).label("messages"),
        )
        .join(SessionModel, SessionModel.employee_id == Employee.id, isouter=True)
        .where(Employee.status == "active")
        .group_by(Employee.id)
        .order_by(func.count(func.distinct(SessionModel.id)).desc(), Employee.created_at)
        .limit(8)
    ).all()

    tc_rows = db.execute(
        select(SessionModel.employee_id, func.count(ToolCall.id))
        .join(ToolCall, ToolCall.session_id == SessionModel.id, isouter=True)
        .group_by(SessionModel.employee_id)
    ).all()
    tc_map = {r[0]: int(r[1] or 0) for r in tc_rows}

    owners = {
        u.id: (u.name or u.username)
        for u in db.scalars(select(User)).all()
    }
    top_employees = [
        {
            "id": r[0],
            "name": r[1],
            "avatar": r[2] or "",
            "ownerId": r[3],
            "ownerName": owners.get(r[3], ""),
            "sessions": int(r[4] or 0),
            "messages": int(r[5] or 0),
            "toolCalls": tc_map.get(r[0], 0),
        }
        for r in emp_rows
    ]

    recent = db.scalars(select(AuditEvent).order_by(AuditEvent.ts.desc()).limit(10)).all()
    recent_audit = [
        {
            "id": e.id,
            "ts": e.ts.isoformat() + "Z" if e.ts else None,
            "actorId": e.actor_id,
            "actorName": e.actor_name,
            "action": e.action,
            "targetType": e.target_type,
            "targetName": e.target_name,
            "risk": e.risk,
            "result": e.result,
            "detail": e.detail or {},
        }
        for e in recent
    ]

    risk_rows = db.execute(
        select(AuditEvent.risk, func.count())
        .where(AuditEvent.ts >= start)
        .group_by(AuditEvent.risk)
    ).all()
    risk_map = {str(r[0]): int(r[1]) for r in risk_rows}
    risk_distribution = [
        {"risk": "low", "label": "低风险", "count": risk_map.get("low", 0)},
        {"risk": "medium", "label": "中风险", "count": risk_map.get("medium", 0)},
        {"risk": "high", "label": "高风险", "count": risk_map.get("high", 0)},
    ]

    action_labels = {
        "login": "登录", "chat": "对话", "tool_call": "工具调用", "sql_query": "SQL 查询",
        "doc_read": "文档阅读", "doc_upload": "文档上传", "skill_install": "技能安装",
        "agent_assign": "公共员工分配", "export": "导出", "hitl_approval": "人工审批",
        "channel_inbound": "渠道消息", "policy_change": "策略变更", "channel_test": "渠道测试",
    }
    act_rows = db.execute(
        select(AuditEvent.action, func.count())
        .where(AuditEvent.ts >= start)
        .group_by(AuditEvent.action)
        .order_by(func.count().desc())
    ).all()
    scenario_stats = [
        {"action": str(r[0]), "label": action_labels.get(str(r[0]), str(r[0])), "count": int(r[1])}
        for r in act_rows
    ]

    ds = datasource_service.get(db)
    data_stats = {
        "datasourceName": ds.name if ds else "",
        "tables": _count(db, TableMeta, TableMeta.datasource_id == (ds.id if ds else "ds_demo")),
        "columns": _count(db, ColumnMeta, ColumnMeta.datasource_id == (ds.id if ds else "ds_demo")),
        "sensitiveColumns": _count(
            db, ColumnMeta,
            ColumnMeta.datasource_id == (ds.id if ds else "ds_demo"),
            ColumnMeta.sensitive_level.in_(("secret", "top_secret")),
        ),
        "rows": int(
            db.scalar(
                select(func.coalesce(func.sum(TableMeta.row_count), 0)).where(
                    TableMeta.datasource_id == (ds.id if ds else "ds_demo")
                )
            ) or 0
        ),
    }

    return {
        "stats": stats,
        "trend": trend,
        "topEmployees": top_employees,
        "recentAudit": recent_audit,
        "riskDistribution": risk_distribution,
        "scenarioStats": scenario_stats,
        "dataStats": data_stats,
        "days": days,
        "scope": "all" if is_admin(user) else "self",
        "generatedAt": now.isoformat() + "Z",
    }
