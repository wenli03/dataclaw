"""数字员工接口：列表/创建/详情/编辑/删除/技能/记忆/复制（契约 §8.3）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, ensure, get_current_user
from ..models import Memory, Skill, User, iso
from ..services.employee_service import (
    assert_employee_readable,
    assert_employee_writable,
    create_employee_from_template,
    duplicate_employee,
    employee_detail,
    employee_skills,
    employee_summaries,
    get_employee_or_404,
    list_employees,
    upsert_employee_skill,
)
from ..services.skill_service import can_bind_skill

router = APIRouter(prefix="/employees", tags=["数字员工"])


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    templateId: str | None = None
    avatar: str | None = None
    roleTitle: str | None = None
    soul: str | None = None
    skills: list[str] | None = None
    greeting: str | None = None


class EmployeePatch(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    avatar: str | None = None
    roleTitle: str | None = None
    soulMd: str | None = None
    memoryEnabled: bool | None = None
    greeting: str | None = None


class EmployeeSkillIn(BaseModel):
    skillId: str
    enabled: bool = True


def _check_bindable(db: Session, user: User, skill_ids: list[str]) -> list[Skill]:
    """校验技能存在且当前用户可用（已安装或内置已审核）。"""
    skills: list[Skill] = []
    for sid in skill_ids:
        skill = db.get(Skill, sid)
        ensure(skill is not None, "SKILL_NOT_FOUND", f"技能不存在：{sid}", 404)
        ok, message = can_bind_skill(db, user, skill)
        ensure(ok, "SKILL_NOT_INSTALLED", message, 403)
        skills.append(skill)
    return skills


@router.get("")
def list_my_employees(
    scope: str = Query(default="mine"),
    keyword: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """员工列表：mine=我的 / public=来自公共员工 / all=全部（管理员）。"""
    emps = list_employees(db, user=user, scope=scope, keyword=keyword, limit=500)
    items = employee_summaries(db, emps)
    return {"items": items, "total": len(items), "scope": scope}


@router.post("")
def create_employee(
    payload: EmployeeCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """创建个人员工（可从模板复制 SOUL/形象/默认技能）。"""
    name = payload.name.strip()
    ensure(bool(name), "BAD_NAME", "员工名称不能为空", 400)
    if payload.skills is not None:
        _check_bindable(db, user, payload.skills)
    emp = create_employee_from_template(
        db,
        user=user,
        name=name,
        template_id=payload.templateId,
        avatar=payload.avatar,
        role_title=payload.roleTitle,
        soul=payload.soul,
        skill_ids=payload.skills,
        greeting=payload.greeting,
    )
    audit(
        db,
        actor=user,
        action="employee_create",
        target_type="employee",
        target_id=emp.id,
        target_name=emp.name,
        detail={"templateId": emp.template_id, "skillCount": len(employee_skills(db, emp))},
        request=request,
    )
    db.commit()
    db.refresh(emp)
    return {"employee": employee_detail(db, emp)}


@router.get("/{employee_id}")
def get_employee(
    employee_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """员工详情（技能/记忆/统计/来源公共员工）。"""
    emp = get_employee_or_404(db, employee_id)
    assert_employee_readable(db, user, emp)
    return {"employee": employee_detail(db, emp)}


@router.patch("/{employee_id}")
def patch_employee(
    employee_id: str,
    payload: EmployeePatch,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """编辑员工名称/形象/职位/SOUL/记忆开关/开场白。"""
    emp = get_employee_or_404(db, employee_id)
    assert_employee_writable(user, emp)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    ensure(changes, "NOTHING_TO_UPDATE", "没有需要更新的字段", 400)
    mapping = {
        "name": "name",
        "avatar": "avatar",
        "roleTitle": "role_title",
        "soulMd": "soul_md",
        "memoryEnabled": "memory_enabled",
        "greeting": "greeting",
    }
    applied: list[str] = []
    for field, value in changes.items():
        attr = mapping.get(field)
        if attr is None:
            continue
        if field == "name":
            value = str(value).strip()[:64]
            ensure(bool(value), "BAD_NAME", "员工名称不能为空", 400)
        if field == "greeting":
            value = str(value)[:200]
        if getattr(emp, attr) != value:
            setattr(emp, attr, value)
            applied.append(field)
    ensure(applied, "NOTHING_TO_UPDATE", "没有实际变更", 400)
    detail: dict = {"op": "update", "fields": applied}
    if "soulMd" in applied:
        detail["field"] = "soul"
    audit(
        db,
        actor=user,
        action="employee_update",
        target_type="employee",
        target_id=emp.id,
        target_name=emp.name,
        detail=detail,
        request=request,
    )
    db.commit()
    db.refresh(emp)
    return {"employee": employee_detail(db, emp)}


@router.delete("/{employee_id}")
def delete_employee(
    employee_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """软删除员工（status=archived）。"""
    emp = get_employee_or_404(db, employee_id)
    assert_employee_writable(user, emp)
    emp.status = "archived"
    audit(
        db,
        actor=user,
        action="employee_update",
        target_type="employee",
        target_id=emp.id,
        target_name=emp.name,
        detail={"op": "archive"},
        request=request,
    )
    db.commit()
    return {"ok": True, "id": emp.id}


@router.post("/{employee_id}/skills")
def configure_skill(
    employee_id: str,
    payload: EmployeeSkillIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """为员工绑定/启停技能（需已安装或为内置已审核技能）。"""
    emp = get_employee_or_404(db, employee_id)
    assert_employee_writable(user, emp)
    skill = db.get(Skill, payload.skillId)
    ensure(skill is not None, "SKILL_NOT_FOUND", "技能不存在", 404)
    ok, message = can_bind_skill(db, user, skill)
    ensure(ok, "SKILL_NOT_INSTALLED", message, 403)
    upsert_employee_skill(db, emp, skill.id, payload.enabled)
    audit(
        db,
        actor=user,
        action="employee_update",
        target_type="employee",
        target_id=emp.id,
        target_name=emp.name,
        detail={"op": "skill_config", "skillId": skill.id, "enabled": payload.enabled},
        request=request,
    )
    db.commit()
    skills = employee_skills(db, emp)
    return {"ok": True, "skills": skills, "skillCount": len(skills)}


@router.get("/{employee_id}/memory")
def get_memory(
    employee_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """员工记忆列表。"""
    emp = get_employee_or_404(db, employee_id)
    assert_employee_readable(db, user, emp)
    rows = list(
        db.scalars(
            select(Memory)
            .where(Memory.employee_id == emp.id)
            .order_by(Memory.created_at.desc())
            .limit(200)
        )
    )
    items = [
        {
            "id": m.id,
            "kind": m.kind or "fact",
            "content": m.content or "",
            "sourceSessionId": m.source_session_id,
            "createdAt": iso(m.created_at),
        }
        for m in rows
    ]
    return {"items": items, "total": len(items)}


@router.delete("/{employee_id}/memory/{memory_id}")
def delete_memory(
    employee_id: str,
    memory_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """删除单条记忆。"""
    emp = get_employee_or_404(db, employee_id)
    assert_employee_writable(user, emp)
    mem = db.get(Memory, memory_id)
    ensure(
        mem is not None and mem.employee_id == emp.id,
        "MEMORY_NOT_FOUND",
        "记忆不存在",
        404,
    )
    db.delete(mem)
    audit(
        db,
        actor=user,
        action="employee_update",
        target_type="employee",
        target_id=emp.id,
        target_name=emp.name,
        detail={"op": "memory_delete", "memoryId": memory_id},
        request=request,
    )
    db.commit()
    return {"ok": True, "id": memory_id}


@router.post("/{employee_id}/duplicate")
def duplicate(
    employee_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """复制员工到「我的」（名称加「副本」，含技能）。"""
    emp = get_employee_or_404(db, employee_id)
    assert_employee_readable(db, user, emp)
    copy = duplicate_employee(db, emp, user)
    audit(
        db,
        actor=user,
        action="employee_create",
        target_type="employee",
        target_id=copy.id,
        target_name=copy.name,
        detail={"op": "duplicate", "fromId": emp.id},
        request=request,
    )
    db.commit()
    db.refresh(copy)
    return {"employee": employee_detail(db, copy)}
