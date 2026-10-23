"""产物构造/落库/导出。

Artifact 是「对话即交付」的落点：dashboard / report / html / docx / xlsx / pptx。
payload 即前端 preview（见契约 §7.3）；文件类产物额外写 file_path/file_name，
下载 URL 统一为 /api/artifacts/{id}/download。
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

from ..core.config import ARTIFACT_DIR
from ..models import Artifact


def safe_filename(name: str, fallback: str = "download") -> str:
    name = (name or "").strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name)
    return name or fallback


def content_disposition(filename: str) -> str:
    """RFC 5987：ASCII fallback + UTF-8 文件名。"""
    name = safe_filename(filename)
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii") or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def download_url(artifact_id: str) -> str:
    return f"/api/artifacts/{artifact_id}/download"


def normalize_payload(kind: str, payload: dict | None) -> dict:
    payload = dict(payload or {})
    payload.setdefault("type", kind)
    return payload


def save_artifact(
    db,
    *,
    kind: str,
    title: str,
    payload: dict | None = None,
    text: str = "",
    file_path: str = "",
    file_name: str = "",
    session_id: str | None = None,
    employee_id: str | None = None,
    created_by: str | None = None,
) -> Artifact:
    payload = normalize_payload(kind, payload)
    if not payload.get("title"):
        payload["title"] = title
    artifact = Artifact(
        kind=kind,
        title=title[:200],
        payload=payload,
        text=text or "",
        file_path=file_path or "",
        file_name=file_name or "",
        session_id=session_id,
        employee_id=employee_id,
        created_by=created_by,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    if file_path:
        current_url = payload.get("downloadUrl") or ""
        if not current_url or "{id}" in current_url:
            artifact.payload = {**payload, "downloadUrl": download_url(artifact.id), "filePath": file_path}
            db.add(artifact)
            db.commit()
    return artifact


def artifact_public(artifact: Artifact) -> dict:
    """列表/SSE 用：返回前端渲染所需的最小结构。"""
    payload = dict(artifact.payload or {})
    file_name = artifact.file_name or payload.get("fileName") or ""
    if artifact.file_path and not payload.get("downloadUrl"):
        payload["downloadUrl"] = download_url(artifact.id)
    if file_name:
        payload.setdefault("fileName", file_name)
    return {
        "artifactId": artifact.id,
        "kind": artifact.kind,
        "title": artifact.title,
        "createdAt": artifact.created_at.isoformat() + "Z" if artifact.created_at else None,
        "sessionId": artifact.session_id,
        "employeeId": artifact.employee_id,
        "fileName": file_name,
        "filePath": artifact.file_path or payload.get("filePath") or "",
        "preview": payload,
    }


def artifact_file(artifact: Artifact) -> Path | None:
    """返回可下载文件路径；禁止逃逸出 ARTIFACT_DIR / data 目录。"""
    raw = artifact.file_path or (artifact.payload or {}).get("filePath") or ""
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(ARTIFACT_DIR) / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    roots = [Path(ARTIFACT_DIR).resolve()]
    try:
        from ..core.config import DATA_DIR

        roots.append(Path(DATA_DIR).resolve())
    except Exception:
        pass
    if not any(resolved == r or r in resolved.parents for r in roots):
        return None
    return resolved if resolved.is_file() else None


def json_clone(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return {}
