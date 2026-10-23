"""知识中台 API（契约 §8.8）：文档列表/上传解析/详情/删除/检索/ACL。"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import UPLOAD_DIR
from ..core.db import get_db
from ..core.deps import audit, ensure, get_current_user, is_admin
from ..models import DocAcl, KnowledgeChunk, KnowledgeDoc, User
from ..services import knowledge_service

router = APIRouter(tags=["knowledge"])

MAX_UPLOAD = 30 * 1024 * 1024
ALLOWED_SUFFIX = {".txt", ".md", ".markdown", ".pdf", ".docx", ".csv",
                  ".png", ".jpg", ".jpeg", ".webp", ".eml"}


def _doc_brief(doc: KnowledgeDoc, db: Session) -> dict:
    return {
        "id": doc.id,
        "name": doc.name,
        "type": doc.type,
        "mime": doc.mime or "",
        "size": int(doc.size or 0),
        "status": doc.status,
        "ownerId": doc.owner_id,
        "dept": doc.dept or "",
        "tags": list(doc.tags or []),
        "chunkCount": int(doc.chunk_count or 0),
        "sensitiveLevel": doc.sensitive_level or "internal",
        "chars": len(doc.text or ""),
        "restricted": bool(
            db.scalar(select(func.count()).select_from(DocAcl).where(DocAcl.doc_id == doc.id)) or 0
        ),
        "createdAt": doc.created_at.isoformat() + "Z" if doc.created_at else None,
        "updatedAt": doc.updated_at.isoformat() + "Z" if doc.updated_at else None,
    }


def _readable(db: Session, user: User, doc: KnowledgeDoc) -> bool:
    return knowledge_service.can_read(db, user, doc)


def _get_doc_or_404(db: Session, user: User, doc_id: str, *, write: bool = False) -> KnowledgeDoc:
    doc = db.get(KnowledgeDoc, doc_id)
    ensure(doc is not None, "DOC_NOT_FOUND", "文档不存在或已被删除", 404)
    doc = _assert_doc_access(db, user, doc)
    if write and not (is_admin(user) or doc.owner_id == user.id):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只有文档所有者或管理员可以修改该文档"})
    return doc


def _assert_doc_access(db: Session, user: User, doc: KnowledgeDoc) -> KnowledgeDoc:
    if not _readable(db, user, doc):
        raise HTTPException(
            status_code=403,
            detail={"code": "DOC_FORBIDDEN", "message": f"无权访问文档《{doc.name}》（未在文档 ACL 授权范围内）"},
        )
    return doc


@router.get("/knowledge/docs")
def list_docs(
    type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    dept: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(KnowledgeDoc)
    if type:
        stmt = stmt.where(KnowledgeDoc.type == type)
    if dept:
        stmt = stmt.where(KnowledgeDoc.dept == dept)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(KnowledgeDoc.name.like(like) | KnowledgeDoc.text.like(like))
    stmt = stmt.order_by(KnowledgeDoc.created_at.desc())

    rows = db.scalars(stmt).all()
    acl_cache: dict[str, list[DocAcl]] = {}
    visible = [d for d in rows if knowledge_service.can_read(db, user, d, acl_cache)]
    total = len(visible)
    page_rows = visible[(page - 1) * size: (page - 1) * size + size]
    items = [_doc_brief(d, db) for d in page_rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "hiddenCount": len(rows) - total,
        "types": sorted({d.type for d in visible}),
    }


@router.post("/knowledge/docs")
def upload_doc(
    request: Request,
    file: UploadFile = File(..., description="待上传文档"),
    type: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    dept: str | None = Form(default=None),
    sensitiveLevel: str | None = Form(default="internal"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    name = (file.filename or "未命名文档").strip()
    suffix = Path(name).suffix.lower()
    ensure(bool(suffix), "FILE_INVALID", "文件名缺少扩展名，无法判断文档类型")
    ensure(suffix in ALLOWED_SUFFIX, "FILE_TYPE_UNSUPPORTED",
           f"暂不支持 {suffix} 格式，请上传：{'、'.join(sorted(ALLOWED_SUFFIX))}")
    ensure((sensitiveLevel or "internal") in ("public", "internal", "secret", "top_secret"),
           "SENSITIVE_LEVEL_INVALID", "sensitiveLevel 仅支持 public/internal/secret/top_secret")

    content = file.file.read()
    ensure(len(content) <= MAX_UPLOAD, "FILE_TOO_LARGE", "文件超过 30MB 限制", 413)

    safe_stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", Path(name).stem)[:60] or "doc"
    stored = UPLOAD_DIR / f"{uuid.uuid4().hex[:10]}_{safe_stem}{suffix}"
    stored.write_bytes(content)

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    doc = knowledge_service.create_from_file(
        db,
        file_path=stored,
        name=name,
        doc_type=type or None,
        mime=file.content_type or "",
        owner=user,
        dept=dept or user.dept or "",
        tags=tag_list,
        sensitive_level=sensitiveLevel or "internal",
    )
    db.flush()
    audit(
        db, actor=user, action="doc_upload", target_type="doc", target_id=doc.id,
        target_name=doc.name,
        detail={"chars": len(doc.text or ""), "chunks": doc.chunk_count,
                "status": doc.status, "type": doc.type, "size": doc.size},
        risk="medium" if doc.sensitive_level in ("secret", "top_secret") else "low",
        request=request, commit=False,
    )
    db.commit()
    db.refresh(doc)
    out = _doc_brief(doc, db)
    out["message"] = (
        "上传成功，已解析并切片"
        if doc.status == "ready"
        else "文件已保存，但正文解析失败（可能是扫描件或格式异常），请确认文件内容"
    )
    if doc.status == "failed":
        out["extractor"] = "failed"
    return out


@router.get("/knowledge/docs/{doc_id}")
def get_doc(
    doc_id: str,
    request: Request,
    chunkSize: int = Query(default=20, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    doc = _get_doc_or_404(db, user, doc_id)
    chunks = db.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc.id).order_by(KnowledgeChunk.seq).limit(chunkSize)
    ).all()
    total_chunks = int(
        db.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc.id)) or 0
    )
    audit(
        db, actor=user, action="doc_read", target_type="doc", target_id=doc.id,
        target_name=doc.name, detail={"chunks": len(chunks)}, request=request, commit=False,
    )
    db.commit()
    out = _doc_brief(doc, db)
    out["text"] = doc.text or ""
    out["chunks"] = [
        {"id": c.id, "seq": c.seq, "text": c.text, "tokens": c.tokens, "chars": len(c.text or "")}
        for c in chunks
    ]
    out["chunkTotal"] = total_chunks
    out["acl"] = knowledge_service.acl_payload(db, doc.id)
    out["path"] = doc.path or ""
    return out


@router.delete("/knowledge/docs/{doc_id}")
def delete_doc(
    doc_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    doc = _get_doc_or_404(db, user, doc_id, write=True)
    name = doc.name
    db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc.id).delete()
    db.query(DocAcl).filter(DocAcl.doc_id == doc.id).delete()
    db.delete(doc)
    audit(
        db, actor=user, action="doc_delete", target_type="doc", target_id=doc_id,
        target_name=name, detail={"deleted": True}, request=request, commit=False,
    )
    db.commit()
    return {"deleted": True, "id": doc_id, "name": name}


@router.post("/knowledge/search")
def search_knowledge(
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = str(payload.get("query") or payload.get("q") or "").strip()
    ensure(bool(query), "QUERY_REQUIRED", "请输入检索关键词")
    top_k = int(payload.get("topK") or 5)
    doc_type = payload.get("type") or None
    ensure(1 <= top_k <= 50, "TOPK_INVALID", "topK 需在 1-50 之间")
    if doc_type:
        ensure(doc_type in ("doc", "wiki", "image", "audio", "email", "chat"),
               "TYPE_INVALID", "type 仅支持 doc/wiki/image/audio/email/chat")

    try:
        result = knowledge_service.search(db, user, query, top_k=top_k, doc_type=doc_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "SEARCH_INVALID", "message": str(exc)}) from exc

    audit(
        db, actor=user, action="doc_read", target_type="knowledge", target_id="search",
        target_name=query[:80],
        detail={"query": query, "hits": result["total"], "topK": top_k},
        request=request, commit=False,
    )
    db.commit()
    return result


@router.get("/knowledge/docs/{doc_id}/acl")
def get_acl(
    doc_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    doc = db.get(KnowledgeDoc, doc_id)
    ensure(doc is not None, "DOC_NOT_FOUND", "文档不存在或已被删除", 404)
    if not (is_admin(user) or doc.owner_id == user.id):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只有文档所有者或管理员可以查看 ACL 明细"})
    out = knowledge_service.acl_payload(db, doc.id)
    out["docName"] = doc.name
    out["sensitiveLevel"] = doc.sensitive_level
    return out


@router.post("/knowledge/docs/{doc_id}/acl")
def save_acl(
    doc_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只有管理员可以调整文档权限"})
    doc = db.get(KnowledgeDoc, doc_id)
    ensure(doc is not None, "DOC_NOT_FOUND", "文档不存在或已被删除", 404)
    subject_type = str(payload.get("subjectType") or "user")
    subject_id = str(payload.get("subjectId") or "").strip()
    can_read = bool(payload.get("canRead", True))
    try:
        row = knowledge_service.set_acl(db, doc, subject_type, subject_id, can_read)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "ACL_INVALID", "message": str(exc)}) from exc
    audit(
        db, actor=user, action="policy_change", target_type="doc", target_id=doc.id,
        target_name=doc.name,
        detail={"subjectType": subject_type, "subjectId": subject_id, "canRead": can_read},
        risk="medium", request=request, commit=False,
    )
    db.commit()
    out = knowledge_service.acl_payload(db, doc.id)
    out["docName"] = doc.name
    out["changed"] = {"subjectType": subject_type, "subjectId": subject_id, "canRead": can_read}
    return out
