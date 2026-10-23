"""技能超市接口：浏览/安装/自定义上传/审核/静态安全扫描（契约 §8.5）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, not_, or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, ensure, get_current_user, is_admin, require_admin
from ..models import Employee, EmployeeSkill, Skill, SkillInstall, User
from ..services.employee_service import employee_for_skill_binding, upsert_employee_skill
from ..services.skill_service import (
    can_install,
    owner_names,
    parse_frontmatter,
    scan_skill_content,
    serialize_skills,
    skill_detail,
    skill_item,
    unique_skill_name,
)

router = APIRouter(prefix="/skills", tags=["技能超市"])

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


class InstallIn(BaseModel):
    employeeId: str | None = None


class SkillCreate(BaseModel):
    displayName: str = Field(min_length=1, max_length=64)
    description: str = ""
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    icon: str = "sparkles"
    category: str = "自定义"


class SkillUpdate(BaseModel):
    displayName: str | None = Field(default=None, max_length=64)
    description: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    icon: str | None = None
    category: str | None = None


class ReviewIn(BaseModel):
    status: str


def _get_skill(db: Session, skill_id: str) -> Skill:
    skill = db.get(Skill, skill_id)
    ensure(skill is not None, "SKILL_NOT_FOUND", "技能不存在", 404)
    return skill


def _assert_owner(user: User, skill: Skill) -> None:
    ensure(
        skill.owner_id == user.id or is_admin(user),
        "FORBIDDEN",
        "只有技能所有者或管理员可以执行该操作",
        403,
    )


def _employee_skill_rel(db: Session, emp: Employee, skill: Skill) -> EmployeeSkill | None:
    return db.scalar(
        select(EmployeeSkill).where(
            EmployeeSkill.employee_id == emp.id, EmployeeSkill.skill_id == skill.id
        )
    )


@router.get("")
def list_skills(
    tab: str = Query(default="market"),
    keyword: str = Query(default=""),
    category: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """技能列表：installed=已装 / market=可装市场 / mine=我上传的。"""
    ensure(tab in ("installed", "market", "mine", "all"), "BAD_TAB", "tab 仅支持 installed/market/mine", 400)
    my_installs = select(SkillInstall.skill_id).where(SkillInstall.user_id == user.id)
    stmt = select(Skill)
    if tab == "installed":
        stmt = stmt.where(Skill.id.in_(my_installs))
    elif tab == "market":
        stmt = stmt.where(Skill.status == "approved", not_(Skill.id.in_(my_installs)))
    elif tab == "mine":
        stmt = stmt.where(Skill.owner_id == user.id)
    else:  # all：全部已审核 + 自己的
        stmt = stmt.where(or_(Skill.status == "approved", Skill.owner_id == user.id))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            or_(
                Skill.name.like(like),
                Skill.display_name.like(like),
                Skill.description.like(like),
            )
        )
    if category:
        stmt = stmt.where(Skill.category == category)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(Skill.updated_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    )
    return {
        "items": serialize_skills(db, rows, user),
        "total": int(total),
        "page": page,
        "size": size,
        "tab": tab,
    }


@router.get("/{skill_id}")
def get_skill(
    skill_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """技能详情（含 SKILL.md 全文与扫描结果）。"""
    skill = _get_skill(db, skill_id)
    ensure(
        skill.status == "approved" or skill.owner_id == user.id or is_admin(user),
        "SKILL_FORBIDDEN",
        "该技能尚未通过审核，暂不可查看",
        403,
    )
    return {"skill": skill_detail(db, skill, user)}


@router.post("/{skill_id}/install")
def install_skill(
    skill_id: str,
    request: Request,
    body: InstallIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """安装技能到当前用户（幂等）；可选同时绑定到某个员工。"""
    skill = _get_skill(db, skill_id)
    ok, message = can_install(db, user, skill)
    ensure(ok, "SKILL_NOT_APPROVED", message, 403)
    existing = db.scalar(
        select(SkillInstall).where(
            SkillInstall.user_id == user.id, SkillInstall.skill_id == skill.id
        )
    )
    employee_id = body.employeeId if body else None
    if existing is None:
        db.add(SkillInstall(user_id=user.id, skill_id=skill.id, employee_id=employee_id))
        skill.installs = int(skill.installs or 0) + 1
    if employee_id:
        upsert_employee_skill(db, employee_for_skill_binding(db, user, employee_id), skill.id, True)
    audit(
        db,
        actor=user,
        action="skill_install",
        target_type="skill",
        target_id=skill.id,
        target_name=skill.display_name,
        detail={
            "op": "install",
            "already": existing is not None,
            "employeeId": employee_id,
            "riskLevel": skill.risk_level,
        },
        risk="medium" if skill.risk_level == "high" else "low",
        request=request,
    )
    db.commit()
    db.refresh(skill)
    item = skill_item(
        db,
        skill,
        installed=True,
        owner_name=owner_names(db, [skill]).get(skill.owner_id or "", ""),
    )
    return {"ok": True, "already": existing is not None, "skill": item}


@router.post("/{skill_id}/uninstall")
def uninstall_skill(
    skill_id: str,
    request: Request,
    body: InstallIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """卸载技能（删除当前用户的安装记录，可选解绑员工）。"""
    skill = _get_skill(db, skill_id)
    rows = list(
        db.scalars(
            select(SkillInstall).where(
                SkillInstall.user_id == user.id, SkillInstall.skill_id == skill.id
            )
        )
    )
    for row in rows:
        db.delete(row)
    if rows:
        skill.installs = max(0, int(skill.installs or 0) - len(rows))
    employee_id = body.employeeId if body else None
    if employee_id:
        emp = employee_for_skill_binding(db, user, employee_id, allow_archived=True)
        rel = _employee_skill_rel(db, emp, skill)
        if rel is not None:
            db.delete(rel)
    audit(
        db,
        actor=user,
        action="skill_install",
        target_type="skill",
        target_id=skill.id,
        target_name=skill.display_name,
        detail={"op": "uninstall", "installs": len(rows), "employeeId": employee_id},
        risk="low",
        request=request,
    )
    db.commit()
    db.refresh(skill)
    return {"ok": True, "installed": False, "skillId": skill.id, "removed": len(rows)}


@router.post("")
def create_skill(
    payload: SkillCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """创建用户级技能：source=user，status=pending，等待管理员审核。"""
    display_name = payload.displayName.strip()
    ensure(bool(display_name), "BAD_NAME", "技能名称不能为空", 400)
    name = unique_skill_name(db, display_name)
    meta = parse_frontmatter(payload.content)
    scan = scan_skill_content(payload.content)
    risk = scan["riskLevel"]
    declared = str(meta.get("risk") or "").lower()
    if declared in _SEVERITY_RANK and _SEVERITY_RANK[declared] > _SEVERITY_RANK[risk]:
        risk = declared
    skill = Skill(
        name=name,
        display_name=display_name[:64],
        description=(payload.description or meta.get("description") or "")[:2000],
        content=payload.content,
        category=(payload.category or "自定义")[:32],
        source="user",
        owner_id=user.id,
        status="pending",
        version="1.0.0",
        risk_level=risk,
        installs=0,
        icon=(payload.icon or "sparkles")[:32],
        tags=list(payload.tags or []),
        tool_names=list(meta.get("tools") or []),
        scan_json=scan,
    )
    db.add(skill)
    db.flush()
    audit(
        db,
        actor=user,
        action="skill_upload",
        target_type="skill",
        target_id=skill.id,
        target_name=skill.display_name,
        detail={"op": "create", "riskLevel": risk, "findings": len(scan["findings"])},
        risk="medium",
        request=request,
    )
    db.commit()
    db.refresh(skill)
    item = skill_item(db, skill, installed=False, owner_name=user.name or user.username)
    return {"ok": True, **item, "scan": scan}


@router.put("/{skill_id}")
def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """编辑技能（仅 owner/admin）；用户改动内容后回到待审核状态。"""
    skill = _get_skill(db, skill_id)
    _assert_owner(user, skill)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    ensure(changes, "NOTHING_TO_UPDATE", "没有需要更新的字段", 400)
    applied: list[str] = []
    if "displayName" in changes:
        value = str(changes["displayName"]).strip()[:64]
        ensure(bool(value), "BAD_NAME", "技能名称不能为空", 400)
        skill.display_name = value
        applied.append("displayName")
    for field, attr in (("description", "description"), ("icon", "icon"), ("category", "category")):
        if field in changes:
            setattr(skill, attr, changes[field])
            applied.append(field)
    if "tags" in changes:
        skill.tags = list(changes["tags"] or [])
        applied.append("tags")
    rescan = False
    if "content" in changes:
        content = str(changes["content"])
        ensure(bool(content.strip()), "BAD_CONTENT", "SKILL.md 内容不能为空", 400)
        skill.content = content
        meta = parse_frontmatter(content)
        skill.tool_names = list(meta.get("tools") or skill.tool_names or [])
        if not changes.get("description") and meta.get("description"):
            skill.description = str(meta["description"])[:2000]
        rescan = True
        applied.append("content")
    if rescan:
        scan = scan_skill_content(skill.content)
        skill.scan_json = scan
        skill.risk_level = scan["riskLevel"]
        if not is_admin(user):
            skill.status = "pending"
    audit(
        db,
        actor=user,
        action="skill_upload",
        target_type="skill",
        target_id=skill.id,
        target_name=skill.display_name,
        detail={"op": "update", "fields": applied, "status": skill.status},
        risk="medium" if rescan else "low",
        request=request,
    )
    db.commit()
    db.refresh(skill)
    return {"skill": skill_detail(db, skill, user)}


@router.delete("/{skill_id}")
def delete_skill(
    skill_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """删除技能（仅 owner/admin），同时清理安装与员工绑定。"""
    skill = _get_skill(db, skill_id)
    _assert_owner(user, skill)
    name = skill.display_name
    # 按外键顺序先清依赖行，再删技能本体
    db.execute(delete(SkillInstall).where(SkillInstall.skill_id == skill.id))
    db.execute(delete(EmployeeSkill).where(EmployeeSkill.skill_id == skill.id))
    db.delete(skill)
    audit(
        db,
        actor=user,
        action="skill_upload",
        target_type="skill",
        target_id=skill_id,
        target_name=name,
        detail={"op": "delete"},
        risk="low",
        request=request,
    )
    db.commit()
    return {"ok": True, "id": skill_id}


@router.post("/{skill_id}/review")
def review_skill(
    skill_id: str,
    payload: ReviewIn,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """管理员审核用户技能：approved / rejected。"""
    ensure(payload.status in ("approved", "rejected"), "BAD_STATUS", "审核结果仅支持 approved/rejected", 400)
    skill = _get_skill(db, skill_id)
    skill.status = payload.status
    audit(
        db,
        actor=actor,
        action="skill_review",
        target_type="skill",
        target_id=skill.id,
        target_name=skill.display_name,
        detail={"op": "review", "status": payload.status, "riskLevel": skill.risk_level},
        risk="medium",
        request=request,
    )
    db.commit()
    db.refresh(skill)
    return {"ok": True, "skill": skill_detail(db, skill, actor)}


@router.post("/{skill_id}/scan")
def scan_skill(
    skill_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """对 SKILL.md 做一次真实静态检查，写回 scan_json 与风险等级。"""
    skill = _get_skill(db, skill_id)
    ensure(
        skill.status == "approved" or skill.owner_id == user.id or is_admin(user),
        "SKILL_FORBIDDEN",
        "该技能尚未通过审核，暂不可扫描",
        403,
    )
    scan = scan_skill_content(skill.content or "")
    skill.scan_json = scan
    skill.risk_level = scan["riskLevel"]
    db.commit()
    db.refresh(skill)
    return {
        "skillId": skill.id,
        "riskLevel": scan["riskLevel"],
        "findings": scan["findings"],
        "scannedAt": scan["scannedAt"],
        "lineCount": scan["lineCount"],
        "rulesChecked": scan["rulesChecked"],
    }
