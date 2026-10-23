"""产物 API：列表 / 详情 / 下载（docx/xlsx/pptx/md/html）。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, get_current_user
from ..models import Artifact, SessionModel, User
from ..runtime.artifacts import artifact_file, artifact_public, content_disposition, safe_filename

router = APIRouter(tags=["artifacts"])


def _owned_artifact(db: Session, user: User, artifact_id: str) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "ARTIFACT_NOT_FOUND", "message": "产物不存在"})
    if artifact.created_by and artifact.created_by != user.id and user.role != "platform_admin":
        # 会话归属用户也可看
        session = db.get(SessionModel, artifact.session_id) if artifact.session_id else None
        if session is None or session.user_id != user.id:
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "无权访问该产物"})
    return artifact


@router.get("/artifacts")
def list_artifacts(
    sessionId: str | None = None,
    kind: str | None = None,
    employeeId: str | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Artifact)
    if user.role != "platform_admin":
        query = query.filter(Artifact.created_by == user.id)
    if sessionId:
        query = query.filter(Artifact.session_id == sessionId)
    if kind:
        query = query.filter(Artifact.kind == kind)
    if employeeId:
        query = query.filter(Artifact.employee_id == employeeId)
    rows = query.order_by(Artifact.created_at.desc()).limit(limit).all()
    items = [artifact_public(a) for a in rows]
    return {"items": items, "total": len(items)}


@router.get("/artifacts/{artifact_id}")
def get_artifact(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    artifact = _owned_artifact(db, user, artifact_id)
    data = artifact_public(artifact)
    data["text"] = artifact.text or ""
    data["payload"] = artifact.payload or {}
    data["filePath"] = artifact.file_path or ""
    return data


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    artifact = _owned_artifact(db, user, artifact_id)
    file_path = artifact_file(artifact)
    if file_path is not None:
        filename = artifact.file_name or (artifact.payload or {}).get("fileName") or file_path.name
        audit(
            db,
            actor=user,
            action="export",
            target_type="artifact",
            target_id=artifact.id,
            target_name=artifact.title,
            detail={"kind": artifact.kind, "fileName": filename, "size": file_path.stat().st_size},
            risk="medium" if artifact.kind == "docx" else "low",
            session_id=artifact.session_id,
            commit=True,
        )
        return FileResponse(
            path=str(file_path),
            filename=safe_filename(filename),
            media_type=_media_type(filename),
            headers={"Content-Disposition": content_disposition(filename)},
        )

    payload = artifact.payload or {}
    title = artifact.title or payload.get("title") or "artifact"
    if payload.get("markdown") or artifact.text:
        text = str(payload.get("markdown") or artifact.text or "")
        filename = safe_filename((payload.get("fileName") or f"{title}.md"))
        audit(
            db,
            actor=user,
            action="export",
            target_type="artifact",
            target_id=artifact.id,
            target_name=title,
            detail={"kind": artifact.kind, "fileName": filename, "inline": True},
            session_id=artifact.session_id,
            commit=True,
        )
        return Response(
            content=text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": content_disposition(filename)},
        )
    if artifact.kind == "html" and payload.get("html"):
        filename = safe_filename((payload.get("fileName") or f"{title}.html"))
        audit(
            db,
            actor=user,
            action="export",
            target_type="artifact",
            target_id=artifact.id,
            target_name=title,
            detail={"kind": "html", "size": len(str(payload.get("html")))},
            session_id=artifact.session_id,
            commit=True,
        )
        return HTMLResponse(
            content=str(payload.get("html")),
            headers={"Content-Disposition": content_disposition(filename)},
        )
    raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND", "message": "该产物没有可下载文件"})


def _media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf",
        ".md": "text/markdown; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }.get(suffix, "application/octet-stream")
