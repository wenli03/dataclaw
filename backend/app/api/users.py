"""用户与角色管理接口（管理员，契约 §8.2）。"""
from __future__ import annotations

import secrets
import string

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, ensure, get_current_user, paginate, require_admin
from ..core.security import hash_password
from ..models import Employee, User
from .auth import public_user

router = APIRouter(tags=["用户管理"])

ROLE_IDS = ("platform_admin", "dept_admin", "member")
USER_STATUS = ("active", "disabled")

# 能力矩阵（对照契约 §5.2）：all=全部 / dept=本部门 / self=仅自己 / none=无
CAPABILITIES = [
    {"key": "manageUsers", "label": "用户与角色管理"},
    {"key": "managePublicAgents", "label": "公共员工管理"},
    {"key": "reviewSkills", "label": "技能审核"},
    {"key": "managePolicies", "label": "数据权限策略"},
    {"key": "manageChannels", "label": "渠道配置"},
    {"key": "viewAudit", "label": "审计日志"},
    {"key": "useEmployees", "label": "数字员工/会话/技能安装"},
]

ROLE_DEFS = [
    {
        "id": "platform_admin",
        "name": "平台管理员",
        "description": "平台级全部管理权限：用户与角色、公共员工、技能审核、数据权限、渠道、审计。",
        "deptScoped": False,
        "grants": {
            "manageUsers": "all",
            "managePublicAgents": "all",
            "reviewSkills": "all",
            "managePolicies": "all",
            "manageChannels": "all",
            "viewAudit": "all",
            "useEmployees": "all",
        },
    },
    {
        "id": "dept_admin",
        "name": "部门管理员",
        "description": "本部门范围内的管理权限：本部门用户、本部门创建的公共员工、技能审核、审计查询。",
        "deptScoped": True,
        "grants": {
            "manageUsers": "dept",
            "managePublicAgents": "dept",
            "reviewSkills": "dept",
            "managePolicies": "dept",
            "manageChannels": "dept",
            "viewAudit": "dept",
            "useEmployees": "all",
        },
    },
    {
        "id": "member",
        "name": "普通成员",
        "description": "使用数字员工、会话、技能安装；只能查看自己的审计记录。",
        "deptScoped": True,
        "grants": {
            "manageUsers": "none",
            "managePublicAgents": "none",
            "reviewSkills": "none",
            "managePolicies": "none",
            "manageChannels": "none",
            "viewAudit": "self",
            "useEmployees": "all",
        },
    },
]

_PWD_ALPHABET = string.ascii_letters + string.digits


def temp_password(length: int = 10) -> str:
    """生成随机临时口令。"""
    return "".join(secrets.choice(_PWD_ALPHABET) for _ in range(length))


def _validate_role(role: str) -> str:
    ensure(role in ROLE_IDS, "BAD_ROLE", "角色不合法，仅支持 platform_admin/dept_admin/member", 400)
    return role


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    name: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=128)
    role: str = "member"
    dept: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=64)
    avatar: str = Field(default="", max_length=64)
    password: str | None = Field(default=None, max_length=128)


class UserPatch(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    dept: str | None = None
    title: str | None = None
    avatar: str | None = None
    status: str | None = None
    memoryEnabled: bool | None = None


def _employee_counts(db: Session, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(Employee.owner_id, func.count(Employee.id))
        .where(Employee.owner_id.in_(ids), Employee.status != "archived")
        .group_by(Employee.owner_id)
    ).all()
    return {str(k): int(v) for k, v in rows}


@router.get("/users")
def list_users(
    keyword: str = Query(default=""),
    role: str = Query(default=""),
    status: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """用户列表（部门管理员仅本部门）。"""
    stmt = select(User)
    if actor.role == "dept_admin":
        stmt = stmt.where(User.dept == (actor.dept or ""))
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            or_(User.username.like(like), User.name.like(like), User.email.like(like))
        )
    if role:
        stmt = stmt.where(User.role == _validate_role(role))
    if status:
        ensure(status in USER_STATUS, "BAD_STATUS", "状态仅支持 active/disabled", 400)
        stmt = stmt.where(User.status == status)
    stmt = stmt.order_by(User.created_at.desc())
    page_data = paginate(db, stmt, page, size)
    rows: list[User] = page_data["items"]
    counts = _employee_counts(db, [u.id for u in rows])
    items = [{**public_user(u), "employeeCount": counts.get(u.id, 0)} for u in rows]
    return {"items": items, "total": page_data["total"], "page": page, "size": size}


@router.post("/users")
def create_user(
    payload: UserCreate,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """新建用户（用户名唯一）。"""
    username = payload.username.strip()
    ensure(len(username) >= 2, "BAD_USERNAME", "用户名至少 2 个字符", 400)
    role = _validate_role(payload.role or "member")
    ensure(
        db.scalar(select(User.id).where(User.username == username)) is None,
        "USER_EXISTS",
        "用户名已存在",
        409,
    )
    dept = (payload.dept or "").strip()
    if actor.role == "dept_admin":
        ensure(role != "platform_admin", "FORBIDDEN", "部门管理员不能创建平台管理员", 403)
        ensure(
            not actor.dept or dept in ("", actor.dept),
            "FORBIDDEN",
            "部门管理员只能创建本部门用户",
            403,
        )
        dept = actor.dept or dept
    password = payload.password or temp_password()
    user = User(
        username=username,
        name=(payload.name or username)[:64],
        email=(payload.email or "")[:128],
        password_hash=hash_password(password),
        role=role,
        dept=dept[:64],
        title=(payload.title or "")[:64],
        avatar=(payload.avatar or "")[:64],
        status="active",
        memory_enabled=True,
    )
    db.add(user)
    db.flush()
    audit(
        db,
        actor=actor,
        action="policy_change",
        target_type="user",
        target_id=user.id,
        target_name=user.name or user.username,
        detail={"op": "user_create", "role": role, "dept": dept},
        risk="medium",
        request=request,
    )
    db.commit()
    db.refresh(user)
    return {"user": {**public_user(user), "employeeCount": 0}, "tempPassword": None if payload.password else password}


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    payload: UserPatch,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """修改用户角色/部门/状态/资料；禁止管理员为自己降级或停用。"""
    target = db.get(User, user_id)
    ensure(target is not None, "USER_NOT_FOUND", "用户不存在", 404)
    if actor.role == "dept_admin":
        ensure(
            target.dept == (actor.dept or "") and target.role != "platform_admin",
            "FORBIDDEN",
            "部门管理员只能管理本部门用户",
            403,
        )
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    ensure(changes, "NOTHING_TO_UPDATE", "没有需要更新的字段", 400)
    if "role" in changes:
        _validate_role(changes["role"])
    if "status" in changes:
        ensure(changes["status"] in USER_STATUS, "BAD_STATUS", "状态仅支持 active/disabled", 400)
    if target.id == actor.id:
        ensure(
            changes.get("role", actor.role) == actor.role,
            "CANNOT_DEMOTE_SELF",
            "不能修改自己的角色",
            400,
        )
        ensure(
            changes.get("status", actor.status) == "active",
            "CANNOT_DISABLE_SELF",
            "不能停用自己的账号",
            400,
        )
    if actor.role == "dept_admin":
        ensure(
            changes.get("role") != "platform_admin",
            "FORBIDDEN",
            "部门管理员不能授予平台管理员角色",
            403,
        )
        changes.pop("dept", None)
    changed: list[str] = []
    for field, value in changes.items():
        if field not in {"name", "email", "role", "dept", "title", "avatar", "status", "memoryEnabled"}:
            continue
        attr = "memory_enabled" if field == "memoryEnabled" else field
        if getattr(target, attr) != value:
            setattr(target, attr, value)
            changed.append(field)
    ensure(changed, "NOTHING_TO_UPDATE", "没有实际变更", 400)
    audit(
        db,
        actor=actor,
        action="policy_change",
        target_type="user",
        target_id=target.id,
        target_name=target.name or target.username,
        detail={"op": "user_update", "fields": changed},
        risk="medium" if {"role", "status"} & set(changed) else "low",
        request=request,
    )
    db.commit()
    db.refresh(target)
    counts = _employee_counts(db, [target.id])
    return {"user": {**public_user(target), "employeeCount": counts.get(target.id, 0)}}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """重置口令，返回一次性临时密码。"""
    target = db.get(User, user_id)
    ensure(target is not None, "USER_NOT_FOUND", "用户不存在", 404)
    if actor.role == "dept_admin":
        ensure(
            target.dept == (actor.dept or "") and target.role != "platform_admin",
            "FORBIDDEN",
            "部门管理员只能管理本部门用户",
            403,
        )
    password = temp_password()
    target.password_hash = hash_password(password)
    audit(
        db,
        actor=actor,
        action="policy_change",
        target_type="user",
        target_id=target.id,
        target_name=target.name or target.username,
        detail={"op": "reset_password"},
        risk="medium",
        request=request,
    )
    db.commit()
    return {"tempPassword": password, "userId": target.id, "username": target.username}


@router.get("/roles")
def list_roles(_: User = Depends(get_current_user)) -> dict:
    """三角色与能力矩阵。"""
    return {"items": ROLE_DEFS, "capabilities": CAPABILITIES, "total": len(ROLE_DEFS)}
