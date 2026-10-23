"""通用依赖：鉴权、角色校验、审计埋点、分页与错误。"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import decode_token
from ..models import AuditEvent, User


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "缺少登录凭证"})
    payload = decode_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail={"code": "TOKEN_INVALID", "message": "登录已过期，请重新登录"})
    user = db.get(User, payload["sub"])
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail={"code": "USER_DISABLED", "message": "账号不可用"})
    return user


def get_optional_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User | None:
    try:
        return get_current_user(authorization, db)
    except HTTPException:
        return None


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("platform_admin", "dept_admin"):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "需要管理员权限"})
    return user


def is_admin(user: User) -> bool:
    return user.role in ("platform_admin", "dept_admin")


def audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str = "",
    target_id: str = "",
    target_name: str = "",
    detail: dict | None = None,
    risk: str = "low",
    result: str = "success",
    session_id: str | None = None,
    request: Request | None = None,
    commit: bool = False,
) -> AuditEvent:
    ip = ""
    if request is not None:
        ip = request.headers.get("x-forwarded-for", "") or (request.client.host if request.client else "")
    ev = AuditEvent(
        actor_id=actor.id if actor else None,
        actor_name=actor.name if actor else "系统",
        action=action,
        target_type=target_type,
        target_id=str(target_id)[:64] if target_id else "",
        target_name=(target_name or "")[:200],
        detail=detail or {},
        risk=risk,
        ip=ip[:64],
        result=result,
        session_id=session_id,
    )
    db.add(ev)
    if commit:
        db.commit()
    return ev


def paginate(db: Session, stmt, page: int, size: int) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
    return {"items": rows, "total": total, "page": page, "size": size}


PageQuery = Query(default=1, ge=1)
SizeQuery = Query(default=20, ge=1, le=200)


def ensure(cond: bool, code: str, message: str, status: int = 400) -> None:
    if not cond:
        raise HTTPException(status_code=status, detail={"code": code, "message": message})


def as_dict_list(rows: list[Any], exclude: set[str] | None = None) -> list[dict]:
    return [r.to_dict(exclude=exclude) for r in rows]
