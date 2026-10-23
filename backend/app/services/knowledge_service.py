"""知识中台服务：解析、切片、检索（BM25 + 文档 ACL）、ACL 管理。

检索实现：中文按 2-gram、英文/数字按词切分，标准 BM25（k1=1.5, b=0.75）打分，
返回带高亮 `<em>` 的 snippet。语料按文档 ACL 过滤，越权文档不会出现在结果里，
连标题都不会泄露。
"""
from __future__ import annotations

import html
import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DocAcl, KnowledgeChunk, KnowledgeDoc, User

CHUNK_SIZE = 500          # 目标切片长度（400-600 字）
CHUNK_OVERLAP = 60        # 切片重叠
SNIPPET_LEN = 180

_CN_RE = re.compile(r"[\u4e00-\u9fff]+")
_EN_RE = re.compile(r"[A-Za-z0-9_]+")
_PARA_RE = re.compile(r"\n\s*\n")
_STOP = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is", "are",
    "what", "how", "why", "please", "with", "by", "as", "at", "be", "this", "that",
}


# ---------------------------------------------------------------- 解析


def extract_text(path: Path, name: str = "") -> tuple[str, str]:
    """抽取文本，返回 (text, extractor)。失败返回 ("", "unsupported")，由调用方置 status=failed。"""
    suffix = (path.suffix or Path(name).suffix).lower()
    try:
        if suffix in (".txt", ".md", ".markdown", ".csv", ".log", ".json"):
            for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
                try:
                    return path.read_text(encoding=enc), "text"
                except UnicodeDecodeError:
                    continue
            return "", "text"
        if suffix == ".pdf":
            import pymupdf  # type: ignore

            parts: list[str] = []
            with pymupdf.open(str(path)) as doc:
                for i, page in enumerate(doc):
                    parts.append(f"\n[第 {i + 1} 页]\n" + (page.get_text() or ""))
            return "".join(parts).strip(), "pymupdf"
        if suffix == ".docx":
            import docx  # type: ignore

            d = docx.Document(str(path))
            parts = [p.text for p in d.paragraphs if p.text.strip()]
            for table in d.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
            return "\n".join(parts).strip(), "python-docx"
        if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"):
            # V1 不接真实 OCR：返回可检索的占位说明，避免"假装解析成功"
            return (
                f"[图片 {name or path.name}] 已入库，V1 未接入 OCR 引擎，"
                "图片内文字暂不可检索。请在描述中补充关键信息，或改用可复制文本的文件。"
            ), "image-placeholder"
    except Exception:
        return "", "failed"
    return "", "unsupported"


# ---------------------------------------------------------------- 切片


def _split_paragraphs(text: str) -> list[str]:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    paras = [p.strip() for p in _PARA_RE.split(text) if p.strip()]
    out: list[str] = []
    for p in paras:
        # 超长段落再按行拆，避免一个切片超过 1200 字
        if len(p) <= CHUNK_SIZE * 2:
            out.append(p)
        else:
            buf = ""
            for line in p.split("\n"):
                if len(buf) + len(line) + 1 > CHUNK_SIZE:
                    if buf:
                        out.append(buf)
                    buf = line
                else:
                    buf = f"{buf}\n{line}" if buf else line
            if buf:
                out.append(buf)
    return out


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按段落聚合成 400-600 字左右的切片，相邻切片重叠约 60 字。"""
    paras = _split_paragraphs(text)
    if not paras:
        return []
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if not cur:
            cur = p
            continue
        if len(cur) + len(p) + 2 <= size:
            cur = f"{cur}\n\n{p}"
            continue
        chunks.append(cur)
        tail = cur[-overlap:] if overlap > 0 and len(cur) > overlap else ""
        cur = f"{tail}\n\n{p}" if tail else p
        # 单段就很长时，硬切
        while len(cur) > size * 1.4:
            chunks.append(cur[:size])
            cur = cur[size - overlap:]
    if cur.strip():
        chunks.append(cur)
    return [c.strip() for c in chunks if c.strip()]


# ---------------------------------------------------------------- 建文档


def create_doc(
    db: Session,
    *,
    name: str,
    text: str,
    doc_type: str = "doc",
    mime: str = "text/plain",
    size: int = 0,
    path: str = "",
    owner: User | None = None,
    dept: str = "",
    tags: list[str] | None = None,
    sensitive_level: str = "internal",
    status: str = "ready",
) -> KnowledgeDoc:
    doc = KnowledgeDoc(
        name=name,
        type=doc_type,
        mime=mime,
        size=size or len((text or "").encode("utf-8")),
        path=path,
        text=text or "",
        status=status,
        owner_id=owner.id if owner else None,
        dept=dept or (owner.dept if owner else ""),
        tags=list(tags or []),
        sensitive_level=sensitive_level,
    )
    db.add(doc)
    db.flush()

    chunks = split_text(text or "") if status == "ready" else []
    for i, chunk in enumerate(chunks):
        db.add(
            KnowledgeChunk(
                doc_id=doc.id,
                seq=i,
                text=chunk,
                tokens=len(tokenize(chunk)),
                meta={"chars": len(chunk)},
            )
        )
    doc.chunk_count = len(chunks)
    return doc


def create_from_file(
    db: Session,
    *,
    file_path: Path,
    name: str,
    doc_type: str | None = None,
    mime: str = "",
    owner: User | None = None,
    dept: str = "",
    tags: list[str] | None = None,
    sensitive_level: str = "internal",
) -> KnowledgeDoc:
    text, extractor = extract_text(file_path, name)
    status = "ready" if text else "failed"
    suffix = file_path.suffix.lower()
    if doc_type is None:
        doc_type = {
            ".md": "wiki", ".eml": "email", ".msg": "email",
            ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
        }.get(suffix, "doc")
    doc = create_doc(
        db,
        name=name,
        text=text,
        doc_type=doc_type,
        mime=mime or "application/octet-stream",
        size=file_path.stat().st_size if file_path.exists() else 0,
        path=str(file_path),
        owner=owner,
        dept=dept,
        tags=tags,
        sensitive_level=sensitive_level,
        status=status,
    )
    if status == "failed":
        doc.text = ""
        doc.chunk_count = 0
        doc.status = "failed"
        db.add(doc)
    return doc


# ---------------------------------------------------------------- ACL


def acl_entries(db: Session, doc_id: str) -> list[DocAcl]:
    return db.scalars(select(DocAcl).where(DocAcl.doc_id == doc_id).order_by(DocAcl.created_at)).all()


def acl_payload(db: Session, doc_id: str) -> dict:
    rows = acl_entries(db, doc_id)
    return {
        "docId": doc_id,
        "restricted": bool(rows),
        "items": [
            {
                "id": a.id,
                "subjectType": a.subject_type,
                "subjectId": a.subject_id,
                "canRead": bool(a.can_read),
            }
            for a in rows
        ],
        "total": len(rows),
    }


def set_acl(
    db: Session, doc: KnowledgeDoc, subject_type: str, subject_id: str, can_read: bool = True
) -> DocAcl:
    if subject_type not in ("user", "role", "dept"):
        raise ValueError("subjectType 仅支持 user / role / dept")
    if not subject_id:
        raise ValueError("subjectId 不能为空")
    row = db.scalar(
        select(DocAcl).where(
            DocAcl.doc_id == doc.id,
            DocAcl.subject_type == subject_type,
            DocAcl.subject_id == subject_id,
        )
    )
    if row is None:
        row = DocAcl(doc_id=doc.id, subject_type=subject_type, subject_id=subject_id, can_read=can_read)
        db.add(row)
    else:
        row.can_read = can_read
    return row


def can_read(db: Session, user: User, doc: KnowledgeDoc, cache: dict[str, list[DocAcl]] | None = None) -> bool:
    """文档可读判定。

    - 文档所有者与平台管理员（platform_admin）始终可读，ACL 只约束"其他人"；
    - 有 ACL 时：用户 / 角色 / 部门任一条 can_read=True 即可读；
    - 没有任何 ACL 记录时：所有登录用户可读。
    """
    if doc.owner_id and doc.owner_id == user.id:
        return True
    if user.role == "platform_admin":
        return True
    rows = None
    if cache is not None:
        if doc.id not in cache:
            cache[doc.id] = acl_entries(db, doc.id)
        rows = cache[doc.id]
    if rows is None:
        rows = acl_entries(db, doc.id)
    if not rows:
        return True
    for a in rows:
        if not a.can_read:
            continue
        if a.subject_type == "user" and a.subject_id == user.id:
            return True
        if a.subject_type == "role" and a.subject_id == user.role:
            return True
        if a.subject_type == "dept" and a.subject_id == user.dept:
            return True
    return False


# ---------------------------------------------------------------- 分词 / BM25


def tokenize(text: str) -> list[str]:
    text = text or ""
    tokens: list[str] = []
    for run in _CN_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    for word in _EN_RE.findall(text):
        w = word.lower()
        if len(w) >= 2 and w not in _STOP:
            tokens.append(w)
    return tokens


_SENT_END = "。！？；\n"


def _best_window(raw: str, tokens: list[str], limit: int) -> tuple[str, int]:
    """以第一处命中为中心，向两侧对齐句子边界后截取，返回 (窗口文本, 起点)。"""
    hit = -1
    for t in tokens:
        idx = raw.find(t)
        if idx >= 0 and (hit < 0 or idx < hit):
            hit = idx
    if hit < 0:
        return raw[:limit], 0
    window_floor = max(0, hit - limit + 40)
    seg = raw[window_floor:hit]
    cut = max((i for i, ch in enumerate(seg) if ch in _SENT_END), default=-1)
    start = window_floor + cut + 1 if cut >= 0 else max(0, hit - 60)
    end = min(len(raw), start + limit)
    tail = raw[end:min(len(raw), end + 40)]
    stop = min((i for i, ch in enumerate(tail) if ch in _SENT_END), default=-1)
    if stop >= 0:
        end = end + stop + 1
    window = re.sub(r"^[^\w\u4e00-\u9fff]+", "", raw[start:end])
    return window, start


def _highlight(text: str, tokens: Iterable[str], limit: int = SNIPPET_LEN) -> tuple[str, list[str]]:
    """截取命中密度最高的窗口并做 <em> 高亮，返回 (html 片段, 命中词)。"""
    raw = (text or "").replace("\n", " ")
    tokens = list(tokens)
    if len(raw) > limit:
        window, start = _best_window(raw, tokens, limit)
        prefix = "…" if start > 0 else ""
        suffix = "…" if start + len(window) < len(raw) else ""
    else:
        window, prefix, suffix = raw, "", ""
    hits: list[str] = []
    escaped = html.escape(window)
    for t in sorted({t for t in tokens if t}, key=len, reverse=True):
        if t and t in escaped:
            escaped = escaped.replace(t, f"<em>{t}</em>")
            if t not in hits:
                hits.append(t)
    # 避免嵌套 <em><em> 这类畸形标记
    while "<em><em>" in escaped:
        escaped = escaped.replace("<em><em>", "<em>").replace("</em></em>", "</em>")
    return f"{prefix}{escaped}{suffix}", hits[:8]


def search(
    db: Session,
    user: User,
    query: str,
    *,
    top_k: int = 5,
    doc_type: str | None = None,
) -> dict:
    q = (query or "").strip()
    if not q:
        raise ValueError("检索关键词不能为空")
    top_k = max(1, min(int(top_k or 5), 50))
    tokens = [t for t in tokenize(q) if t]
    if not tokens:
        raise ValueError("检索关键词无法分词，请换用中文或英文关键词")

    # 1. 语料：只取用户可读的 ready 文档
    docs = db.scalars(
        select(KnowledgeDoc).where(KnowledgeDoc.status == "ready")
    ).all()
    acl_cache: dict[str, list[DocAcl]] = {}
    allowed_docs = {d.id: d for d in docs if can_read(db, user, d, acl_cache)}
    if not allowed_docs:
        return {"items": [], "total": 0, "query": q, "rules": ["当前用户没有可检索的文档"]}

    chunks = db.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.doc_id.in_(list(allowed_docs.keys())))
    ).all()
    if not chunks:
        return {"items": [], "total": 0, "query": q, "rules": ["知识库中还没有切片"]}

    # 2. 统计
    token_lists: list[list[str]] = []
    df: Counter = Counter()
    for c in chunks:
        toks = tokenize(c.text)
        token_lists.append(toks)
        for t in set(tokens) & set(toks):
            df[t] += 1
    n_docs = len(chunks)
    avgdl = sum(len(t) for t in token_lists) / max(n_docs, 1)
    k1, b = 1.5, 0.75

    # 3. 打分
    scored: list[tuple[float, int]] = []
    for i, toks in enumerate(token_lists):
        if not toks:
            continue
        tf = Counter(toks)
        score = 0.0
        dl = len(toks)
        for t in tokens:
            f = tf.get(t, 0)
            if not f:
                continue
            idf = math.log(1 + (n_docs - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / max(avgdl, 1e-9)))
        if score > 0:
            scored.append((score, i))

    scored.sort(key=lambda x: x[0], reverse=True)
    max_score = scored[0][0] if scored else 1.0
    items: list[dict] = []
    for score, idx in scored[:top_k * 3]:
        chunk = chunks[idx]
        doc = allowed_docs.get(chunk.doc_id)
        if doc is None:
            continue
        if doc_type and doc.type != doc_type:
            continue
        snippet, hits = _highlight(chunk.text, tokens)
        items.append(
            {
                "docId": doc.id,
                "docName": doc.name,
                "docType": doc.type,
                "dept": doc.dept or "",
                "seq": chunk.seq,
                "snippet": snippet,
                "highlights": hits,
                "score": round(score / max_score, 4),
                "rawScore": round(score, 4),
                "sensitiveLevel": doc.sensitive_level or "internal",
            }
        )
        if len(items) >= top_k:
            break

    rules = [
        f"检索词切片：{' / '.join(tokens[:12])}",
        f"语料范围：{len(allowed_docs)} 篇可读文档 / {len(chunks)} 个切片（已按文档 ACL 过滤）",
        "打分：BM25(k1=1.5, b=0.75)，score 为归一化后的相对得分",
    ]
    if not items:
        rules.append("未命中任何切片，建议换用更具体的业务词")
    return {"items": items, "total": len(items), "query": q, "rules": rules}


__all__ = [
    "extract_text", "split_text", "create_doc", "create_from_file",
    "acl_entries", "acl_payload", "set_acl", "can_read",
    "tokenize", "search", "CHUNK_SIZE", "CHUNK_OVERLAP",
]
