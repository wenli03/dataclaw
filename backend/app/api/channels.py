"""渠道 API（契约 §8.10）：列表 / 保存 / 连通性测试 / 入站 webhook（免鉴权）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, get_current_user, is_admin
from ..models import User
from ..services import channel_service

router = APIRouter(tags=["channels"])


@router.get("/channels")
def list_channels(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    out = channel_service.list_channels(db)
    db.commit()
    return out


@router.post("/channels/{channel_type}")
def save_channel(
    channel_type: str,
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只有管理员可以修改渠道配置"})
    try:
        channel = channel_service.save_channel(db, channel_type, payload, actor=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "CHANNEL_INVALID", "message": str(exc)}) from exc
    audit(
        db, actor=user, action="channel_config", target_type="channel", target_id=channel.type,
        target_name=channel.name, detail={"enabled": channel.enabled, "status": channel.status},
        risk="medium", request=request, commit=False,
    )
    db.commit()
    db.refresh(channel)
    return channel_service.to_dict(channel)


@router.post("/channels/{channel_type}/test")
def test_channel(
    channel_type: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只有管理员可以测试渠道连通性"})
    try:
        result = channel_service.test_channel(db, channel_type, actor=user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "CHANNEL_INVALID", "message": str(exc)}) from exc
    audit(
        db, actor=user, action="channel_test", target_type="channel", target_id=channel_type,
        target_name=result.get("status", ""), detail=result,
        result="success" if result["ok"] else "error", request=request, commit=False,
    )
    db.commit()
    if not result["ok"]:
        # 必填配置缺失属于用户可修复的请求错误：按契约返回 400 + 中文原因
        missing = result.get("missing") or []
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CHANNEL_CONFIG_MISSING",
                "message": result.get("message") or "渠道配置不完整",
                "missing": missing,
                "type": result.get("type", channel_type),
                "latencyMs": result.get("latencyMs", 0),
            },
        )
    return result


@router.post("/channels/{channel_type}/events")
def inbound_event(
    channel_type: str,
    payload: dict,
    request: Request,
    x_dataclaw_token: str | None = Header(default=None, alias="X-DataClaw-Token"),
    db: Session = Depends(get_db),
) -> dict:
    """IM 入站回调：免鉴权，但要求 `X-DataClaw-Token` 与渠道 config.token 一致（宽松模式可用 demo token）。"""
    try:
        return channel_service.handle_event(
            db, channel_type.lower(), token=x_dataclaw_token, body=payload
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "CHANNEL_TOKEN_INVALID", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "CHANNEL_EVENT_INVALID", "message": str(exc)}) from exc
