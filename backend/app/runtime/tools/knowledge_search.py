"""知识检索技能：kb.search / kb.read_doc（走知识中台 + 文档权限）。"""
from __future__ import annotations

from .. import search_knowledge
from ..types import ToolContext, ToolResult, ToolSpec
from . import STATE_KNOWLEDGE


async def search_handler(params: dict, ctx: ToolContext) -> ToolResult:
    query = str(params.get("query") or params.get("q") or "").strip()
    if not query:
        return ToolResult(ok=False, error="缺少 query 参数")
    top_k = int(params.get("topK") or params.get("top_k") or 5)
    hits = search_knowledge(ctx.db, ctx.user, query, top_k=top_k)
    ctx.state.setdefault(STATE_KNOWLEDGE, []).extend(hits)
    output = {
        "query": query,
        "hits": hits,
        "count": len(hits),
        "rules": ["文档 ACL 过滤生效"] if hits else [],
    }
    return ToolResult(
        ok=True,
        summary=f"知识库命中 {len(hits)} 条（{', '.join(h['docName'] for h in hits[:3]) or '无'}）",
        output=output,
    )


async def read_doc_handler(params: dict, ctx: ToolContext) -> ToolResult:
    doc_id = str(params.get("docId") or params.get("doc_id") or "").strip()
    if not doc_id:
        hits = ctx.state.get(STATE_KNOWLEDGE) or []
        doc_id = hits[0].get("docId") if hits else ""
    if not doc_id:
        return ToolResult(ok=False, error="缺少 docId，且当前会话没有已命中的文档")
    from ...models import KnowledgeDoc

    doc = ctx.db.get(KnowledgeDoc, doc_id)
    if doc is None:
        return ToolResult(ok=False, error=f"文档不存在：{doc_id}")
    text = doc.text or ""
    return ToolResult(
        ok=True,
        summary=f"读取《{doc.name}》{len(text)} 字",
        output={"docId": doc.id, "docName": doc.name, "text": text[:8000], "truncated": len(text) > 8000},
    )


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="kb.search",
        title="检索企业知识库",
        description="按关键词检索知识中台文档切片，返回可溯源片段与文档名。",
        params={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "topK": {"type": "integer", "description": "返回条数，默认 5"},
            },
            "required": ["query"],
        },
        handler=search_handler,
        risk="low",
        skill="knowhow-search",
    ),
    ToolSpec(
        name="kb.read_doc",
        title="读取知识文档全文",
        description="按文档 ID 读取知识库文档正文（用于规则比对）。",
        params={
            "type": "object",
            "properties": {"docId": {"type": "string", "description": "文档 ID"}},
            "required": ["docId"],
        },
        handler=read_doc_handler,
        risk="low",
        skill="knowhow-search",
    ),
]
