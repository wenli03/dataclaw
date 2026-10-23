"""公共员工接口：定义、版本管理、发布同步、一键分配（契约 §8.4）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, ensure, require_admin
from ..models import (
    Assignment,
    Employee,
    PublicAgent,
    SessionModel,
    User,
    iso,
    utcnow,
)
from ..services.skill_service import resolve_skills, skill_ref_lookup
from ..services.assignment_service import (
    agent_visible,
    assign_users,
    list_assignments,
    remove_assignment,
    sync_assignments,
)

router = APIRouter(prefix="/public-agents", tags=["公共员工"])

AGENT_STATUS = ("draft", "published", "offline")


class PublicAgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    roleTitle: str = ""
    avatar: str = ""
    soulMd: str = ""
    skills: list[str] = Field(default_factory=list)
    status: str = "published"
    tags: list[str] = Field(default_factory=list)


class PublicAgentPatch(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = None
    roleTitle: str | None = None
    avatar: str | None = None
    soulMd: str | None = None
    skills: list[str] | None = None
    status: str | None = None
    tags: list[str] | None = None


class AssignIn(BaseModel):
    userIds: list[str] = Field(default_factory=list)


def _get_agent(db: Session, user: User, agent_id: str) -> PublicAgent:
    """取公共员工并校验可见性（部门管理员仅本部门创建）。"""
    agent = db.get(PublicAgent, agent_id)
    ensure(agent is not None, "AGENT_NOT_FOUND", "公共员工不存在", 404)
    ensure(agent_visible(db, user, agent), "FORBIDDEN", "无权访问该公共员工", 403)
    return agent


def _validate_skills(db: Session, skill_ids: list[str]) -> list[str]:
    """校验技能引用（id 或机器名）并归一化为技能 id。"""
    resolved, missing = resolve_skills(db, skill_ids)
    ensure(not missing, "SKILL_NOT_FOUND", f"技能不存在：{', '.join(missing[:3])}", 404)
    return resolved


def _stats(db: Session, ids: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    """批量统计分配人数与副本会话数。"""
    if not ids:
        return {}, {}
    assignees = dict(
        db.execute(
            select(Assignment.public_agent_id, func.count(Assignment.id))
            .where(Assignment.public_agent_id.in_(ids))
            .group_by(Assignment.public_agent_id)
        ).all()
    )
    sessions = dict(
        db.execute(
            select(Employee.public_agent_id, func.count(SessionModel.id))
            .select_from(Employee)
            .join(SessionModel, SessionModel.employee_id == Employee.id)
            .where(Employee.public_agent_id.in_(ids), Employee.status != "archived")
            .group_by(Employee.public_agent_id)
        ).all()
    )
    return (
        {str(k): int(v) for k, v in assignees.items()},
        {str(k): int(v) for k, v in sessions.items()},
    )


def _resolved_skills(agent: PublicAgent, lookup: dict[str, str]) -> list[str]:
    """把存储的技能引用（可能是机器名）解析为技能 id，保持顺序去重。"""
    out: list[str] = []
    for ref in agent.default_skills or []:
        skill_id = lookup.get(ref)
        if skill_id and skill_id not in out:
            out.append(skill_id)
    return out


def _agent_item(
    agent: PublicAgent,
    assignees: int,
    sessions: int,
    skills: list[str],
) -> dict:
    stats = dict(agent.stats_json or {})
    return {
        "id": agent.id,
        "name": agent.name,
        "avatar": agent.avatar or "",
        "roleTitle": agent.role_title or "",
        "description": agent.description or "",
        "version": int(agent.version or 1),
        "status": agent.status or "draft",
        "skillCount": len(skills),
        "assigneeCount": assignees,
        "sessionCount": sessions,
        "updatedAt": iso(agent.updated_at),
        "tags": list(stats.get("tags") or []),
        "soulMd": agent.soul_md or "",
        "skills": skills,
        "createdBy": agent.created_by,
        "publishedAt": iso(agent.published_at),
        "pendingSync": bool(stats.get("pendingSync")),
    }


@router.get("")
def list_agents(
    status: str = Query(default=""),
    keyword: str = Query(default=""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """公共员工列表（含分配人数、版本、技能数、待同步标记）。"""
    stmt = select(PublicAgent)
    if user.role == "dept_admin":
        dept_users = select(User.id).where(User.dept == (user.dept or ""))
        stmt = stmt.where(
            or_(PublicAgent.created_by == user.id, PublicAgent.created_by.in_(dept_users))
        )
    if status:
        ensure(status in AGENT_STATUS, "BAD_STATUS", "状态仅支持 draft/published/offline", 400)
        stmt = stmt.where(PublicAgent.status == status)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            or_(PublicAgent.name.like(like), PublicAgent.role_title.like(like))
        )
    agents = list(db.scalars(stmt.order_by(PublicAgent.updated_at.desc())))
    assignees, sessions = _stats(db, [a.id for a in agents])
    refs = [ref for a in agents for ref in (a.default_skills or [])]
    lookup = skill_ref_lookup(db, refs)
    items = [
        _agent_item(a, assignees.get(a.id, 0), sessions.get(a.id, 0), _resolved_skills(a, lookup))
        for a in agents
    ]
    return {"items": items, "total": len(items)}


@router.post("")
def create_agent(
    payload: PublicAgentIn,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """创建公共员工（管理员定义，可草稿或直接发布）。"""
    name = payload.name.strip()
    ensure(bool(name), "BAD_NAME", "公共员工名称不能为空", 400)
    ensure(payload.status in AGENT_STATUS, "BAD_STATUS", "状态仅支持 draft/published/offline", 400)
    skills = _validate_skills(db, payload.skills)
    agent = PublicAgent(
        name=name,
        description=payload.description or "",
        role_title=payload.roleTitle or "",
        avatar=payload.avatar or "avatar-01",
        soul_md=payload.soulMd or "",
        default_skills=skills,
        version=1,
        status=payload.status,
        created_by=user.id,
        published_at=utcnow() if payload.status == "published" else None,
        stats_json={"tags": list(payload.tags or []), "pendingSync": False},
    )
    db.add(agent)
    db.flush()
    audit(
        db,
        actor=user,
        action="agent_assign",
        target_type="public_agent",
        target_id=agent.id,
        target_name=agent.name,
        detail={"op": "create", "status": agent.status, "skillCount": len(skills)},
        risk="medium",
        request=request,
    )
    db.commit()
    db.refresh(agent)
    return {"agent": _agent_item(agent, 0, 0, list(agent.default_skills or []))}


@router.patch("/{agent_id}")
def patch_agent(
    agent_id: str,
    payload: PublicAgentPatch,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """编辑公共员工：version+1 并标记 pendingSync（待发布同步）。"""
    agent = _get_agent(db, user, agent_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    ensure(changes, "NOTHING_TO_UPDATE", "没有需要更新的字段", 400)
    if "status" in changes:
        ensure(changes["status"] in AGENT_STATUS, "BAD_STATUS", "状态不合法", 400)
    applied: list[str] = []
    if "name" in changes:
        name = str(changes["name"]).strip()[:64]
        ensure(bool(name), "BAD_NAME", "公共员工名称不能为空", 400)
        agent.name = name
        applied.append("name")
    for field, attr in (("description", "description"), ("roleTitle", "role_title"), ("avatar", "avatar"), ("soulMd", "soul_md")):
        if field in changes:
            setattr(agent, attr, changes[field])
            applied.append(field)
    if "skills" in changes:
        agent.default_skills = _validate_skills(db, changes["skills"] or [])
        applied.append("skills")
    stats = dict(agent.stats_json or {})
    if "tags" in changes:
        stats["tags"] = list(changes["tags"] or [])
        applied.append("tags")
    if "status" in changes:
        agent.status = changes["status"]
        if agent.status == "published" and agent.published_at is None:
            agent.published_at = utcnow()
        applied.append("status")
    agent.version = int(agent.version or 1) + 1
    stats["pendingSync"] = True
    agent.stats_json = stats
    audit(
        db,
        actor=user,
        action="agent_assign",
        target_type="public_agent",
        target_id=agent.id,
        target_name=agent.name,
        detail={"op": "update", "fields": applied, "version": agent.version},
        risk="medium",
        request=request,
    )
    db.commit()
    db.refresh(agent)
    assignees, sessions = _stats(db, [agent.id])
    lookup = skill_ref_lookup(db, agent.default_skills)
    return {
        "agent": _agent_item(
            agent, assignees.get(agent.id, 0), sessions.get(agent.id, 0),
            _resolved_skills(agent, lookup),
        )
    }


@router.post("/{agent_id}/publish")
def publish_agent(
    agent_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """发布当前版本，并把 SOUL/形象/技能同步到全部已分配副本。"""
    agent = _get_agent(db, user, agent_id)
    agent.status = "published"
    agent.published_at = utcnow()
    stats = dict(agent.stats_json or {})
    stats["pendingSync"] = False
    agent.stats_json = stats
    synced_ids = sync_assignments(db, agent)
    audit(
        db,
        actor=user,
        action="agent_assign",
        target_type="public_agent",
        target_id=agent.id,
        target_name=agent.name,
        detail={"op": "publish", "version": agent.version, "synced": len(synced_ids)},
        risk="medium",
        request=request,
    )
    db.commit()
    db.refresh(agent)
    return {
        "version": int(agent.version or 1),
        "synced": len(synced_ids),
        "status": agent.status,
        "employeeIds": synced_ids,
        "publishedAt": iso(agent.published_at),
    }


@router.post("/{agent_id}/assign")
def assign(
    agent_id: str,
    payload: AssignIn,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """一键分配：为每个用户创建/复用员工副本，幂等（已分配则跳过）。"""
    agent = _get_agent(db, user, agent_id)
    user_ids = [u for u in dict.fromkeys(payload.userIds or []) if u]
    ensure(bool(user_ids), "BAD_USER_IDS", "请至少选择一个用户", 400)
    ensure(agent.status != "offline", "AGENT_OFFLINE", "公共员工已下架，无法分配", 400)
    found = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
    users = [found[uid] for uid in user_ids if uid in found]
    result = assign_users(db, agent, users)
    for uid in user_ids:
        if uid not in found:
            result["skipped"].append(
                {"userId": uid, "userName": "", "username": "", "employeeId": None, "reason": "user_not_found"}
            )
    audit(
        db,
        actor=user,
        action="agent_assign",
        target_type="public_agent",
        target_id=agent.id,
        target_name=agent.name,
        detail={
            "op": "assign",
            "userIds": user_ids,
            "created": len(result["created"]),
            "skipped": len(result["skipped"]),
        },
        risk="medium",
        request=request,
    )
    db.commit()
    return {
        **result,
        "createdCount": len(result["created"]),
        "skippedCount": len(result["skipped"]),
        "agentId": agent.id,
    }


@router.get("/{agent_id}/assignments")
def get_assignments(
    agent_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """分配明细。"""
    agent = _get_agent(db, user, agent_id)
    items = list_assignments(db, agent)
    return {"items": items, "total": len(items)}


@router.delete("/{agent_id}/assign/{user_id}")
def unassign(
    agent_id: str,
    user_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """取消分配：删除用户侧副本与分配记录。"""
    agent = _get_agent(db, user, agent_id)
    target = db.get(User, user_id)
    ensure(target is not None, "USER_NOT_FOUND", "用户不存在", 404)
    result = remove_assignment(db, agent, user_id)
    ensure(
        result["removed"],
        "ASSIGNMENT_NOT_FOUND",
        "该用户未被分配此公共员工",
        404,
    )
    audit(
        db,
        actor=user,
        action="agent_assign",
        target_type="public_agent",
        target_id=agent.id,
        target_name=agent.name,
        detail={"op": "unassign", "userId": user_id, "employeeId": result["employeeId"]},
        risk="medium",
        request=request,
    )
    db.commit()
    return {"ok": True, **result, "userName": target.name or target.username}


@router.delete("/{agent_id}")
def offline_agent(
    agent_id: str,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """下架公共员工（status=offline，已分配副本保留）。"""
    agent = _get_agent(db, user, agent_id)
    agent.status = "offline"
    audit(
        db,
        actor=user,
        action="agent_assign",
        target_type="public_agent",
        target_id=agent.id,
        target_name=agent.name,
        detail={"op": "offline"},
        risk="medium",
        request=request,
    )
    db.commit()
    return {"ok": True, "id": agent.id, "status": agent.status}
