"""员工领域服务：序列化、访问控制、模板派生、技能绑定与复制。

约定：所有 ensure(...) 失败统一抛 HTTPException(detail={"code","message"})，
由 app.main 的异常处理器包装成 `{"error": {...}}`。
"""
from __future__ import annotations

import re
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.deps import ensure, is_admin
from ..models import (
    Artifact,
    Assignment,
    Employee,
    EmployeeSkill,
    Memory,
    PublicAgent,
    SessionModel,
    Skill,
    Template,
    ToolCall,
    User,
    iso,
)

_FRONTMATTER_KEY = re.compile(r"^[a-zA-Z_]+:\s")


def plain_text(text: str, limit: int = 140) -> str:
    """从 SOUL.md 中取第一行有效正文，用作员工列表简介。"""
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("#>-* ").strip()
        if not line or line == "---" or _FRONTMATTER_KEY.match(line):
            continue
        return line[:limit]
    return ""


def get_employee_or_404(db: Session, employee_id: str) -> Employee:
    """按 id 取员工；不存在或已归档 → 404。"""
    emp = db.get(Employee, employee_id)
    ensure(
        emp is not None and emp.status != "archived",
        "EMPLOYEE_NOT_FOUND",
        "数字员工不存在或已删除",
        404,
    )
    return emp  # type: ignore[return-value]


def assert_employee_readable(db: Session, user: User, emp: Employee) -> None:
    """可读：本人创建 / 管理员 / 该公共员工已分配给当前用户。"""
    if emp.owner_id == user.id or is_admin(user):
        return
    if emp.public_agent_id:
        hit = db.scalar(
            select(Assignment.id).where(
                Assignment.public_agent_id == emp.public_agent_id,
                Assignment.user_id == user.id,
            )
        )
        if hit:
            return
    ensure(False, "EMPLOYEE_FORBIDDEN", "无权访问该数字员工", 403)


def assert_employee_writable(user: User, emp: Employee) -> None:
    """可写：仅归属人或管理员。"""
    ensure(
        emp.owner_id == user.id or is_admin(user),
        "EMPLOYEE_FORBIDDEN",
        "只有数字员工的创建者可以修改",
        403,
    )


def _counts(db: Session, ids: Sequence[str], column, model) -> dict[str, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(column, func.count(model.id)).where(column.in_(list(ids))).group_by(column)
    ).all()
    return {str(k): int(v) for k, v in rows}


def _agents(db: Session, emps: Sequence[Employee]) -> dict[str, PublicAgent]:
    agent_ids = sorted({e.public_agent_id for e in emps if e.public_agent_id})
    if not agent_ids:
        return {}
    return {a.id: a for a in db.scalars(select(PublicAgent).where(PublicAgent.id.in_(agent_ids)))}


def employee_summaries(db: Session, emps: Sequence[Employee]) -> list[dict]:
    """批量序列化员工列表项（避免 N+1）。"""
    emps = list(emps)
    if not emps:
        return []
    ids = [e.id for e in emps]
    skill_counts = _counts(db, ids, EmployeeSkill.employee_id, EmployeeSkill)
    session_counts = _counts(db, ids, SessionModel.employee_id, SessionModel)
    agents = _agents(db, emps)
    out: list[dict] = []
    for e in emps:
        agent = agents.get(e.public_agent_id or "")
        desc = (agent.description if agent and agent.description else "") or plain_text(e.soul_md)
        out.append(
            {
                "id": e.id,
                "name": e.name,
                "avatar": e.avatar or "",
                "roleTitle": e.role_title or "",
                "source": e.source or "personal",
                "memoryEnabled": bool(e.memory_enabled),
                "skillCount": skill_counts.get(e.id, 0),
                "sessionCount": session_counts.get(e.id, 0),
                "lastActiveAt": iso(e.last_active_at),
                "publicAgentId": e.public_agent_id or None,
                "description": desc,
                "status": e.status,
                "greeting": e.greeting or "",
                "createdAt": iso(e.created_at),
            }
        )
    return out


def employee_stats(db: Session, emp: Employee) -> dict:
    """员工维度统计：会话数 / 工具调用数 / 产物数 / 最近活跃时间。"""
    sessions = db.scalar(
        select(func.count(SessionModel.id)).where(SessionModel.employee_id == emp.id)
    ) or 0
    tool_calls = db.scalar(
        select(func.count(ToolCall.id))
        .select_from(ToolCall)
        .join(SessionModel, ToolCall.session_id == SessionModel.id)
        .where(SessionModel.employee_id == emp.id)
    ) or 0
    artifacts = db.scalar(
        select(func.count(Artifact.id)).where(Artifact.employee_id == emp.id)
    ) or 0
    last = emp.last_active_at or db.scalar(
        select(func.max(SessionModel.last_message_at)).where(SessionModel.employee_id == emp.id)
    )
    return {
        "sessions": int(sessions),
        "toolCalls": int(tool_calls),
        "artifacts": int(artifacts),
        "lastActiveAt": iso(last),
    }


def employee_skills(db: Session, emp: Employee) -> list[dict]:
    """员工已绑技能（含启用状态与风险等级）。"""
    rows = db.execute(
        select(EmployeeSkill, Skill)
        .join(Skill, EmployeeSkill.skill_id == Skill.id)
        .where(EmployeeSkill.employee_id == emp.id)
    ).all()
    items = [
        {
            "id": s.id,
            "name": s.name,
            "displayName": s.display_name,
            "icon": s.icon or "sparkles",
            "category": s.category or "",
            "enabled": bool(rel.enabled),
            "riskLevel": s.risk_level or "low",
        }
        for rel, s in rows
    ]
    items.sort(key=lambda x: (not x["enabled"], x["displayName"] or ""))
    return items


def employee_memory(db: Session, emp: Employee, limit: int = 100) -> list[dict]:
    """员工记忆条目（新→旧）。"""
    rows = db.scalars(
        select(Memory)
        .where(Memory.employee_id == emp.id)
        .order_by(Memory.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": m.id,
            "kind": m.kind or "fact",
            "content": m.content or "",
            "sourceSessionId": m.source_session_id,
            "createdAt": iso(m.created_at),
        }
        for m in rows
    ]


def public_agent_brief(db: Session, emp: Employee) -> dict | None:
    if not emp.public_agent_id:
        return None
    agent = db.get(PublicAgent, emp.public_agent_id)
    if agent is None:
        return None
    return {"id": agent.id, "name": agent.name, "version": int(agent.version or 1)}


def employee_detail(db: Session, emp: Employee) -> dict:
    """员工详情：基础字段 + 技能 + 记忆 + 统计 + 来源公共员工。"""
    base = employee_summaries(db, [emp])[0]
    base.update(
        {
            "soulMd": emp.soul_md or "",
            "templateId": emp.template_id,
            "skills": employee_skills(db, emp),
            "memory": employee_memory(db, emp),
            "stats": employee_stats(db, emp),
            "publicAgent": public_agent_brief(db, emp),
            "updatedAt": iso(emp.updated_at),
        }
    )
    return base


def employee_for_skill_binding(
    db: Session, user: User, employee_id: str, *, allow_archived: bool = False
) -> Employee:
    """取员工并校验技能绑定权限（安装/解绑技能场景）。"""
    emp = db.get(Employee, employee_id)
    ensure(
        emp is not None and (allow_archived or emp.status != "archived"),
        "EMPLOYEE_NOT_FOUND",
        "数字员工不存在",
        404,
    )
    ensure(
        emp.owner_id == user.id or is_admin(user),
        "EMPLOYEE_FORBIDDEN",
        "无权操作该数字员工",
        403,
    )
    return emp


def upsert_employee_skill(db: Session, emp: Employee, skill_id: str, enabled: bool = True) -> EmployeeSkill:
    """新增或启停员工技能（幂等）。"""
    rel = db.scalar(
        select(EmployeeSkill).where(
            EmployeeSkill.employee_id == emp.id, EmployeeSkill.skill_id == skill_id
        )
    )
    if rel is not None:
        rel.enabled = bool(enabled)
        return rel
    rel = EmployeeSkill(employee_id=emp.id, skill_id=skill_id, enabled=bool(enabled))
    db.add(rel)
    db.flush()
    return rel


def replace_employee_skills(db: Session, emp: Employee, skill_ids: Sequence[str]) -> None:
    """把员工技能集合整体替换为 skill_ids（忽略不存在的技能）。"""
    wanted = [sid for sid in dict.fromkeys(skill_ids or []) if sid]
    valid = set()
    if wanted:
        valid = set(db.scalars(select(Skill.id).where(Skill.id.in_(wanted))))
    wanted = [sid for sid in wanted if sid in valid]
    existing = {
        rel.skill_id: rel
        for rel in db.scalars(
            select(EmployeeSkill).where(EmployeeSkill.employee_id == emp.id)
        )
    }
    for sid, rel in existing.items():
        if sid not in wanted:
            db.delete(rel)
    for sid in wanted:
        if sid in existing:
            existing[sid].enabled = True
        else:
            db.add(EmployeeSkill(employee_id=emp.id, skill_id=sid, enabled=True))
    db.flush()


def _template_skill_ids(db: Session, tpl: Template | None) -> list[str]:
    """模板 default_skills 存的是技能机器名（code），映射成已审核技能的 id。"""
    codes = [c for c in (tpl.default_skills or []) if c] if tpl else []
    if not codes:
        return []
    rows = db.scalars(
        select(Skill).where(Skill.name.in_(codes), Skill.status == "approved")
    )
    return [s.id for s in rows]


def create_employee_from_template(
    db: Session,
    *,
    user: User,
    name: str,
    template_id: str | None = None,
    avatar: str | None = None,
    role_title: str | None = None,
    soul: str | None = None,
    skill_ids: Sequence[str] | None = None,
    greeting: str | None = None,
) -> Employee:
    """基于模板（可选）创建个人员工；skill_ids 为空时复制模板默认技能。"""
    tpl: Template | None = None
    if template_id:
        tpl = db.get(Template, template_id)
        ensure(tpl is not None, "TEMPLATE_NOT_FOUND", "角色模板不存在", 404)
    emp = Employee(
        owner_id=user.id,
        name=name,
        avatar=(avatar or (tpl.avatar if tpl else "") or "avatar-01"),
        role_title=(role_title if role_title is not None else (tpl.role_title if tpl else "")) or "",
        soul_md=(soul if soul is not None else (tpl.soul_md if tpl else "")) or "",
        greeting=(greeting or "")[:200],
        template_id=tpl.id if tpl else None,
        source="personal",
        memory_enabled=True,
        status="active",
        stats_json={},
    )
    db.add(emp)
    db.flush()
    chosen = list(skill_ids) if skill_ids is not None else _template_skill_ids(db, tpl)
    if chosen:
        replace_employee_skills(db, emp, chosen)
    return emp


def duplicate_employee(db: Session, emp: Employee, user: User) -> Employee:
    """把员工复制到当前用户名下（名字加「副本」），技能一并复制。"""
    copy = Employee(
        owner_id=user.id,
        name=f"{emp.name} 副本"[:64],
        avatar=emp.avatar or "",
        role_title=emp.role_title or "",
        soul_md=emp.soul_md or "",
        greeting=emp.greeting or "",
        template_id=emp.template_id,
        source="personal",
        memory_enabled=bool(emp.memory_enabled),
        status="active",
        stats_json={"duplicatedFrom": emp.id},
    )
    db.add(copy)
    db.flush()
    skill_ids = list(
        db.scalars(select(EmployeeSkill.skill_id).where(EmployeeSkill.employee_id == emp.id))
    )
    if skill_ids:
        replace_employee_skills(db, copy, skill_ids)
    return copy


def list_employees(
    db: Session,
    *,
    user: User,
    scope: str = "mine",
    keyword: str = "",
    limit: int = 200,
) -> list[Employee]:
    """按 scope 取员工：mine=我的 / public=来自公共员工的副本 / all=全部（管理员）。"""
    ensure(scope in ("mine", "public", "all"), "BAD_SCOPE", "scope 仅支持 mine/public/all", 400)
    stmt = select(Employee).where(Employee.status != "archived")
    if scope == "mine":
        stmt = stmt.where(Employee.owner_id == user.id)
    elif scope == "public":
        stmt = stmt.where(Employee.source == "from_public")
        if not is_admin(user):
            stmt = stmt.where(Employee.owner_id == user.id)
    else:
        ensure(is_admin(user), "FORBIDDEN", "仅管理员可查看全部数字员工", 403)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(or_(Employee.name.like(like), Employee.role_title.like(like)))
    stmt = stmt.order_by(Employee.created_at.desc()).limit(max(1, min(limit, 500)))
    return list(db.scalars(stmt))
