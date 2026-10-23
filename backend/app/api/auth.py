"""认证接口：登录 / 当前用户 / 登出（契约 §8.1）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, get_current_user, is_admin
from ..core.security import create_token, verify_password
from ..models import Employee, User, iso, utcnow

router = APIRouter(prefix="/auth", tags=["认证"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def public_user(user: User) -> dict:
    """对外用户视图（绝不包含 password_hash）。"""
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name or user.username,
        "email": user.email or "",
        "role": user.role,
        "dept": user.dept or "",
        "title": user.title or "",
        "avatar": user.avatar or "",
        "status": user.status,
        "memoryEnabled": bool(user.memory_enabled),
        "lastLoginAt": iso(user.last_login_at),
        "createdAt": iso(user.created_at),
    }


def permissions_for(user: User) -> dict:
    """能力摘要（对照契约 §5.2 RBAC 矩阵）。"""
    admin = is_admin(user)
    return {
        "isAdmin": admin,
        "canManageUsers": admin,
        "canReviewSkills": admin,
        "canManagePublicAgents": admin,
        "auditScope": user.role,  # platform_admin=all / dept_admin=dept / member=self
    }


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """账号口令登录：签发 12h JWT，写 last_login_at 并记录审计。"""
    username = payload.username.strip()
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(payload.password, user.password_hash):
        audit(
            db,
            actor=user,
            action="login",
            target_type="user",
            target_id=username,
            target_name=(user.name if user else username),
            detail={"username": username, "reason": "bad_credentials"},
            result="denied",
            request=request,
            commit=True,
        )
        raise HTTPException(
            status_code=401,
            detail={"code": "BAD_CREDENTIALS", "message": "账号或密码不正确"},
        )
    if user.status != "active":
        audit(
            db,
            actor=user,
            action="login",
            target_type="user",
            target_id=user.id,
            target_name=user.name or user.username,
            detail={"username": username, "reason": "account_disabled"},
            result="denied",
            request=request,
            commit=True,
        )
        raise HTTPException(
            status_code=403,
            detail={"code": "ACCOUNT_DISABLED", "message": "账号已被停用，请联系管理员"},
        )
    user.last_login_at = utcnow()
    audit(
        db,
        actor=user,
        action="login",
        target_type="user",
        target_id=user.id,
        target_name=user.name or user.username,
        detail={"role": user.role, "dept": user.dept or ""},
        request=request,
    )
    db.commit()
    db.refresh(user)
    return {"token": create_token(user.id, {"role": user.role}), "user": public_user(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """当前登录用户 + 能力摘要 + 名下员工数。"""
    count = db.scalar(
        select(func.count(Employee.id)).where(
            Employee.owner_id == user.id, Employee.status != "archived"
        )
    ) or 0
    return {
        "user": public_user(user),
        "permissions": permissions_for(user),
        "employeeCount": int(count),
    }


@router.post("/logout")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """登出（无状态 JWT，仅落审计）。"""
    audit(
        db,
        actor=user,
        action="logout",
        target_type="user",
        target_id=user.id,
        target_name=user.name or user.username,
        request=request,
        commit=True,
    )
    return {"ok": True}
