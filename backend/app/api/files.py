"""文件 API：multipart 上传（20MB / 扩展名白名单）/ 列表 / 下载。"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.config import UPLOAD_DIR
from ..core.db import get_db
from ..core.deps import audit, get_current_user
from ..models import FileModel, User
from ..runtime.artifacts import content_disposition, safe_filename

router = APIRouter(tags=["files"])

MAX_SIZE = 20 * 1024 * 1024
ALLOWED = {
    ".pdf", ".docx", ".doc", ".txt", ".md", ".xlsx", ".xls", ".csv",
    ".pptx", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".json", ".html", ".eml", ".msg",
}
KIND_BY_EXT = {
    ".pdf": "doc", ".docx": "doc", ".doc": "doc", ".txt": "doc", ".md": "doc",
    ".xlsx": "doc", ".xls": "doc", ".csv": "doc", ".pptx": "doc",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
    ".eml": "email", ".msg": "email",
}


def _file_or_404(db: Session, file_id: str) -> FileModel:
    record = db.get(FileModel, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND", "message": "文件不存在"})
    return record


@router.post("/files")
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    name = file.filename or "upload.bin"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(
            status_code=400,
            detail={"code": "FILE_TYPE_NOT_ALLOWED", "message": f"不支持的文件类型 {suffix or '（无扩展名）'}"},
        )
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail={"code": "FILE_TOO_LARGE", "message": "文件超过 20MB 限制"})
    if not data:
        raise HTTPException(status_code=400, detail={"code": "EMPTY_FILE", "message": "文件为空"})

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(data)
    record = FileModel(
        name=safe_filename(name),
        path=str(stored),
        size=len(data),
        mime=file.content_type or "application/octet-stream",
        kind=KIND_BY_EXT.get(suffix, "doc"),
        uploaded_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    audit(
        db,
        actor=user,
        action="doc_upload",
        target_type="file",
        target_id=record.id,
        target_name=record.name,
        detail={"size": record.size, "mime": record.mime, "stored": stored.name},
        risk="low",
        commit=True,
    )
    return {"fileId": record.id, "name": record.name, "size": record.size, "mime": record.mime, "kind": record.kind}


@router.get("/files")
def list_files(
    tab: str = Query(default="mine"),
    keyword: str | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(FileModel)
    if tab == "shared":
        query = query.filter(FileModel.uploaded_by != user.id)
    else:
        query = query.filter(FileModel.uploaded_by == user.id)
    if keyword:
        query = query.filter(FileModel.name.like(f"%{keyword}%"))
    rows = query.order_by(FileModel.created_at.desc()).limit(limit).all()
    items = [
        {
            "fileId": r.id,
            "name": r.name,
            "size": r.size,
            "mime": r.mime,
            "kind": r.kind,
            "uploadedBy": r.uploaded_by,
            "createdAt": r.created_at.isoformat() + "Z" if r.created_at else None,
            "downloadUrl": f"/api/files/{r.id}/download",
        }
        for r in rows
    ]
    return {"items": items, "total": len(items), "tab": tab}


@router.delete("/files/{file_id}")
def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """删除自己上传的文件（管理员可删任意）。软删记录 + 清理磁盘副本。"""
    record = _file_or_404(db, file_id)
    if record.uploaded_by != user.id and user.role != "platform_admin":
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只能删除自己上传的文件"})
    try:
        Path(record.path).unlink(missing_ok=True)
    except OSError:
        pass
    name = record.name
    db.delete(record)
    db.commit()
    audit(
        db,
        actor=user,
        action="doc_delete",
        target_type="file",
        target_id=file_id,
        target_name=name,
        detail={"op": "delete"},
        risk="low",
        commit=True,
    )
    return {"ok": True, "fileId": file_id}


@router.get("/files/{file_id}/download")
def download_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = _file_or_404(db, file_id)
    if record.uploaded_by not in (None, user.id) and user.role not in ("platform_admin", "dept_admin"):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "无权下载该文件"})
    path = Path(record.path)
    try:
        resolved = path.resolve()
        upload_root = Path(UPLOAD_DIR).resolve()
    except OSError:
        resolved, upload_root = path, Path(UPLOAD_DIR)
    if resolved != upload_root and upload_root not in resolved.parents:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "非法文件路径"})
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND", "message": "文件已丢失"})
    filename = record.name or resolved.name
    return FileResponse(
        path=str(resolved),
        filename=safe_filename(filename),
        media_type=record.mime or "application/octet-stream",
        headers={"Content-Disposition": content_disposition(filename)},
    )
