"""会话 API：列表/创建/详情/重命名/删除 + SSE 消息 + HITL 审批。

SSE 协议严格遵守契约 §7.2：`event: <type>\\ndata: <json>\\n\\n`。
`?stream=false` 时返回同一轮的 JSON 聚合结果，便于测试、渠道与自动化调用。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.db import SessionLocal, get_db
from ..core.deps import audit, get_current_user
from ..models import Employee, FileModel, Message, SessionModel, User, utcnow
from ..runtime import approvals as approvals_mod
from ..runtime import runner

router = APIRouter(tags=["sessions"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class SessionCreate(BaseModel):
    employeeId: str = ""
    title: str | None = None
    employee_id: str | None = None
    pinned: bool = False


class SessionPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class AttachmentIn(BaseModel):
    fileId: str = ""


class MessageCreate(BaseModel):
    content: str = ""
    attachments: list[Any] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    decision: str = "approved"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _iso(dt) -> str | None:
    return dt.replace(microsecond=0).isoformat() + "Z" if dt else None


def _session_payload(session: SessionModel, employee: Employee | None = None) -> dict:
    """统一 camelCase 响应（前端按契约字段名取值）。"""
    return {
        "id": session.id,
        "employeeId": session.employee_id,
        "userId": session.user_id,
        "title": session.title,
        "status": session.status,
        "pinned": bool(session.pinned),
        "lastMessageAt": _iso(session.last_message_at),
        "messageCount": int(session.message_count or 0),
        "createdAt": _iso(session.created_at),
        "updatedAt": _iso(session.updated_at),
        "employeeName": employee.name if employee else "",
        "employeeAvatar": employee.avatar if employee else "",
        "employeeRole": employee.role_title if employee else "",
    }


def _message_payload(message: Message) -> dict:
    return {
        "id": message.id,
        "sessionId": message.session_id,
        "role": message.role,
        "content": message.content or "",
        "steps": message.steps or [],
        "artifacts": message.artifacts or [],
        "tokens": int(message.tokens or 0),
        "latencyMs": int(message.latency_ms or 0),
        "createdAt": _iso(message.created_at),
    }


def _employee_or_404(db: Session, user: User, employee_id: str, *, allow_admin: bool = True) -> Employee:
    employee = db.get(Employee, employee_id) if employee_id else None
    if employee is None or employee.status == "archived":
        raise HTTPException(status_code=404, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "数字员工不存在"})
    if employee.owner_id != user.id and not (allow_admin and user.role in ("platform_admin", "dept_admin")):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "无权使用该数字员工"})
    return employee


def _session_or_404(db: Session, user: User, session_id: str) -> SessionModel:
    session = db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    if session.user_id != user.id and user.role != "platform_admin":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "无权访问该会话"})
    return session


def _normalize_attachments(db: Session, user: User, raw: list[Any]) -> list[dict]:
    out: list[dict] = []
    for item in raw or []:
        file_id = ""
        if isinstance(item, str):
            file_id = item
        elif isinstance(item, dict):
            file_id = str(item.get("fileId") or item.get("file_id") or item.get("id") or "")
        if not file_id:
            continue
        record = db.get(FileModel, file_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND", "message": f"附件不存在：{file_id}"})
        if record.uploaded_by and record.uploaded_by != user.id and user.role != "platform_admin":
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "无权使用该附件"})
        out.append(
            {
                "fileId": record.id,
                "name": record.name,
                "path": record.path,
                "mime": record.mime,
                "size": record.size,
            }
        )
    return out


@router.get("/sessions")
def list_sessions(
    employeeId: str | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(SessionModel).filter(SessionModel.user_id == user.id)
    if employeeId:
        query = query.filter(SessionModel.employee_id == employeeId)
    if keyword:
        query = query.filter(SessionModel.title.like(f"%{keyword}%"))
    total = query.count()
    rows = (
        query.order_by(SessionModel.pinned.desc(), SessionModel.last_message_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    employee_ids = {s.employee_id for s in rows}
    employees = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(employee_ids)).all()} if employee_ids else {}
    items = []
    for session in rows:
        items.append(_session_payload(session, employees.get(session.employee_id)))
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/sessions")
def create_session(
    payload: SessionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    employee_id = payload.employeeId or payload.employee_id or ""
    employee = _employee_or_404(db, user, employee_id)
    session = SessionModel(
        employee_id=employee.id,
        user_id=user.id,
        title=(payload.title or "新会话")[:200],
        status="active",
        pinned=bool(payload.pinned),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_payload(session, employee)


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _session_or_404(db, user, session_id)
    employee = db.get(Employee, session.employee_id)
    messages = (
        db.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    data = _session_payload(session, employee)
    data["employee"] = {
        "id": employee.id,
        "name": employee.name,
        "avatar": employee.avatar,
        "roleTitle": employee.role_title,
        "soul": employee.soul_md,
    } if employee else None
    data["messages"] = [_message_payload(m) for m in messages]
    return data


@router.patch("/sessions/{session_id}")
def patch_session(
    session_id: str,
    payload: SessionPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _session_or_404(db, user, session_id)
    if payload.title is not None:
        session.title = payload.title.strip()[:200] or session.title
    if payload.pinned is not None:
        session.pinned = bool(payload.pinned)
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_payload(session, db.get(Employee, session.employee_id))


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _session_or_404(db, user, session_id)
    db.query(Message).filter(Message.session_id == session.id).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    audit(
        db,
        actor=user,
        action="chat",
        target_type="session",
        target_id=session_id,
        detail={"op": "delete"},
        session_id=session_id,
        commit=True,
    )
    return {"deleted": True, "id": session_id}


async def _run_stream(local: Session, user_id: str, session_id: str, content: str, attachments: list[dict], auto_approve: bool = False):
    """在独立 DB 会话中执行，避免依赖请求级 Session 的生命周期。"""
    try:
        session = local.get(SessionModel, session_id)
        user = local.get(User, user_id)
        employee = local.get(Employee, session.employee_id) if session else None
        if session is None or user is None or employee is None:
            yield _sse("error", {"message": "会话或员工不存在", "code": "NOT_FOUND"})
            yield _sse("done", {"messageId": "", "usage": {"tokens": 0, "steps": 0}, "latencyMs": 0})
            return
        async for event, data in runner.stream_chat(
            local, user, employee, session, content, attachments, auto_approve=auto_approve
        ):
            yield _sse(event, data)
    except Exception as exc:  # noqa: BLE001 流内异常也必须以 error+done 收尾
        yield _sse("error", {"message": f"会话执行失败：{type(exc).__name__}: {exc}", "code": "STREAM_ERROR"})
        yield _sse("done", {"messageId": "", "usage": {"tokens": 0, "steps": 0}, "latencyMs": 0})
    finally:
        local.close()


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    payload: MessageCreate,
    stream: bool = Query(default=True),
    autoApprove: bool = Query(default=False, description="流式模式下自动批准 HITL（演示/自动化用）"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _session_or_404(db, user, session_id)
    employee = _employee_or_404(db, user, session.employee_id)
    content = (payload.content or "").strip()
    attachments = _normalize_attachments(db, user, payload.attachments)
    if not content and not attachments:
        raise HTTPException(status_code=400, detail={"code": "EMPTY_MESSAGE", "message": "消息内容不能为空"})

    # 1) 用户消息先落库
    user_msg = Message(session_id=session.id, role="user", content=content or "（已上传附件）")
    db.add(user_msg)
    session.message_count = (session.message_count or 0) + 1
    session.last_message_at = utcnow()
    if not session.title or session.title == "新会话":
        session.title = runner._make_title(content or (attachments[0]["name"] if attachments else "新会话"))
    db.add(session)
    db.commit()
    db.refresh(user_msg)

    # 2) 审计 chat（输入摘要）
    audit(
        db,
        actor=user,
        action="chat",
        target_type="session",
        target_id=session.id,
        target_name=session.title,
        detail={
            "employeeId": employee.id,
            "employeeName": employee.name,
            "input": (content or "")[:300],
            "attachments": [a["fileId"] for a in attachments],
            "stream": bool(stream),
        },
        risk="low",
        session_id=session.id,
        commit=True,
    )

    if not stream:
        result = await runner.collect_chat(
            db, user, employee, session, content, attachments, auto_approve=True
        )
        return result

    return StreamingResponse(
        _run_stream(
            SessionLocal(),
            user.id,
            session.id,
            content,
            attachments,
            auto_approve=bool(autoApprove),
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/sessions/{session_id}/approvals/{approval_id}")
def decide_approval(
    session_id: str,
    approval_id: str,
    payload: ApprovalDecision,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session = _session_or_404(db, user, session_id)
    from ..models import Approval

    approval = db.get(Approval, approval_id)
    if approval is None or approval.session_id != session.id:
        raise HTTPException(status_code=404, detail={"code": "APPROVAL_NOT_FOUND", "message": "审批不存在"})
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail={"code": "INVALID_DECISION", "message": "decision 只能是 approved/rejected"})
    updated = approvals_mod.decide_approval(db, approval_id, payload.decision == "approved", user)
    return {
        "approvalId": approval_id,
        "status": updated.status if updated else "unknown",
        "decision": payload.decision,
    }
