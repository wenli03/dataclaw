"""Agent 运行时包。

同时承担「跨模块兼容层」：运行时优先调用 be-data 的
`services.policy_service` / `services.sqlguard` / `services.datasource_service` /
`services.knowledge_service`；若这些模块尚未就绪（并行开发期），退化为
runtime 内置的最小实现，保证三条标杆场景仍可离线跑通、可单测。

对外只暴露 runtime 内部使用的少量 helper；业务 API 不直接依赖本文件。
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import DEMO_DB, REPO

# --------------------------------------------------------------------------- #
# 通用
# --------------------------------------------------------------------------- #


def _service(name: str):
    try:
        return importlib.import_module(f"app.services.{name}")
    except Exception:  # ModuleNotFoundError / 依赖缺失 / 语法错误
        return None


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """同时兼容 dataclass 属性与 dict 键。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        for n in names:
            if n in obj:
                return obj[n]
        return default
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


# --------------------------------------------------------------------------- #
# 数据源
# --------------------------------------------------------------------------- #


def get_demo_datasource(db, ds_id: str | None = None):
    svc = _service("datasource_service")
    if svc is not None and hasattr(svc, "get_demo_datasource"):
        try:
            return svc.get_demo_datasource(db, ds_id) if ds_id else svc.get_demo_datasource(db)
        except TypeError:
            try:
                return svc.get_demo_datasource(db)
            except Exception:
                pass
        except Exception:
            pass
    from ..models import DataSource

    if ds_id:
        ds = db.get(DataSource, ds_id)
        if ds is not None:
            return ds
    ds = db.query(DataSource).filter(DataSource.name == "demo").first()
    if ds is None:
        ds = db.query(DataSource).order_by(DataSource.created_at.asc()).first()
    return ds


def datasource_path(ds) -> Path:
    if ds is None:
        return Path(DEMO_DB)
    cfg = _json_dict(getattr(ds, "config", None))
    raw = cfg.get("path") or cfg.get("file") or getattr(ds, "database", "") or ""
    if not raw:
        return Path(DEMO_DB)
    p = Path(str(raw))
    if not p.is_absolute():
        p = Path(REPO) / p
    if not p.exists():
        fallback = Path(DEMO_DB)
        return fallback if fallback.exists() else p
    return p


def list_tables(db, ds_id: str | None = None) -> list[dict]:
    svc = _service("datasource_service")
    if svc is not None and hasattr(svc, "list_tables"):
        try:
            rows = svc.list_tables(db, ds_id)
            if rows is not None:
                return [r if isinstance(r, dict) else getattr(r, "to_dict", lambda: {})() for r in rows]
        except Exception:
            pass

    ds = get_demo_datasource(db, ds_id)
    if ds is None:
        return []
    from ..models import TableMeta

    metas = db.query(TableMeta).filter(TableMeta.datasource_id == ds.id).all()
    if metas:
        return [{"name": m.name, "comment": m.comment, "rowCount": m.row_count} for m in metas]
    path = datasource_path(ds)
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        out = []
        for name in names:
            count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            out.append({"name": name, "comment": "", "rowCount": count})
        return out
    finally:
        conn.close()


def columns_of(db, ds_id: str | None, table: str) -> list[dict]:
    svc = _service("datasource_service")
    if svc is not None and hasattr(svc, "columns_of"):
        try:
            rows = svc.columns_of(db, ds_id, table)
            if rows is not None:
                return [r if isinstance(r, dict) else getattr(r, "to_dict", lambda: {})() for r in rows]
        except Exception:
            pass

    ds = get_demo_datasource(db, ds_id)
    if ds is None:
        return []
    from ..models import ColumnMeta

    metas = (
        db.query(ColumnMeta)
        .filter(ColumnMeta.datasource_id == ds.id, ColumnMeta.table_name == table)
        .order_by(ColumnMeta.id.asc())
        .all()
    )
    if metas:
        return [
            {
                "name": m.name,
                "type": m.type,
                "comment": m.comment,
                "sensitive_level": m.sensitive_level,
                "sensitiveLevel": m.sensitive_level,
                "category": m.category,
            }
            for m in metas
        ]
    path = datasource_path(ds)
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        cols = []
        for r in conn.execute(f'PRAGMA table_info("{table}")'):
            cols.append(
                {
                    "name": r[1],
                    "type": (r[2] or "TEXT"),
                    "comment": "",
                    "sensitive_level": "public",
                    "sensitiveLevel": "public",
                    "category": "",
                }
            )
        return cols
    except sqlite3.Error:
        return []
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 权限
# --------------------------------------------------------------------------- #


def _policy_rows(db, user) -> list:
    from ..models import Policy

    rows = db.query(Policy).filter(Policy.enabled == True).all()  # noqa: E712
    uid = getattr(user, "id", "")
    role = getattr(user, "role", "member")

    def score(p) -> tuple[int, int]:
        subject_rank = 2 if (p.subject_type == "user" and p.subject_id == uid) else (
            1 if (p.subject_type == "role" and p.subject_id == role) else -1
        )
        return (subject_rank, p.priority or 0)

    return sorted([p for p in rows if score(p)[0] >= 0], key=score)


def _match_resource(resource_id: str, ds_id: str, table: str | None, column: str | None) -> bool:
    rid = resource_id or ""
    if column is not None:
        return rid in (f"{ds_id}:{table}.{column}", f"{ds_id}:*.*.{column}", f"{ds_id}:*.{column}")
    if table is not None:
        return rid in (f"{ds_id}:{table}", f"{ds_id}:*")
    return rid in (ds_id, f"{ds_id}:*", "")


def _fallback_resolve(db, user, ds_id: str, table: str | None = None, column: str | None = None) -> dict:
    rows = _policy_rows(db, user)
    reasons: list[str] = []
    table_rules = [p for p in rows if p.resource_type == "table" and _match_resource(p.resource_id, ds_id, table, None)]
    ds_rules = [p for p in rows if p.resource_type == "datasource" and (p.resource_id or "") in (ds_id, f"{ds_id}:*", "")]
    column_rules = [
        p for p in rows if p.resource_type == "column" and table and _match_resource(p.resource_id, ds_id, table, column)
    ]
    row_filters = [
        p.row_filter
        for p in table_rules + ds_rules + rows
        if p.row_filter and (p.resource_type in ("table", "datasource", "row")) and _match_resource(p.resource_id, ds_id, table, None)
    ]

    allow = any(p.action == "allow" for p in table_rules + ds_rules)
    deny = [p for p in table_rules + ds_rules if p.action == "deny"]
    if deny and not any(p.action == "allow" and (p.priority or 0) > max(d.priority or 0 for d in deny) for p in table_rules + ds_rules):
        allow = False
        reasons.append(deny[0].note or f"表 {table or ds_id} 被拒绝访问")
    if not allow and not table_rules and not ds_rules and not column_rules:
        # 并行开发期兜底：完全没有配置策略时按 DEMO_MODE 放行，避免演示全黑
        from ..core.config import DEMO_MODE

        allow = bool(DEMO_MODE)
        reasons.append("未配置策略，演示模式放行" if allow else "未配置策略，默认拒绝")

    mask = "none"
    mask_param: dict = {}
    if column is not None:
        for p in reversed(column_rules):
            if p.action == "deny":
                allow = False
                reasons.append(p.note or f"字段 {column} 被拒绝访问")
                break
            if p.action == "allow":
                allow = True
                mask = p.mask or "none"
                mask_param = _json_dict(p.mask_param)
                reasons.append(f"字段 {column} 命中 {p.mask or 'none'} 策略")
                break
    if allow and not reasons:
        reasons.append("命中允许策略" if (table_rules or ds_rules or column_rules) else "演示模式默认可见")
    return {
        "allowed": allow,
        "mask": mask,
        "mask_param": mask_param,
        "row_filters": row_filters,
        "reasons": reasons,
        "ds_id": ds_id,
        "table": table,
        "column": column,
    }


def resolve_policy(db, user, ds_id: str, table: str | None = None, column: str | None = None) -> dict:
    """返回统一结构：{allowed, mask, mask_param, row_filters, reasons[, columns]}。"""
    svc = _service("policy_service")
    if svc is not None and hasattr(svc, "resolve"):
        try:
            try:
                res = svc.resolve(db, user, ds_id, table, column=column)
            except TypeError:
                res = svc.resolve(db, user, ds_id, table, column)
        except Exception:
            res = None
        if res is not None:
            raw_rules = list(_get(res, "rules", default=[]) or [])
            reasons = []
            for rule in raw_rules:
                if isinstance(rule, dict):
                    pid = rule.get("policyId") or rule.get("policy_id") or ""
                    text = rule.get("reason") or rule.get("note") or ""
                    reasons.append(f"{pid}: {text}".strip(": "))
                else:
                    reasons.append(str(rule))
            if column is not None:
                rules = _get(res, "columns", default={}) or {}
                rule = rules.get(column) if isinstance(rules, dict) else None
                denied = _get(res, "denied_columns", default={}) or {}
                allowed = bool(_get(res, "allowed", default=False)) and column not in denied and rule is not None
                return {
                    "allowed": allowed,
                    "mask": _get(rule, "mask", default="none") or "none",
                    "mask_param": _get(rule, "mask_param", default={}) or {},
                    "row_filters": list(_get(res, "row_filters", default=[]) or []),
                    "reasons": reasons,
                    "rulesDetail": raw_rules,
                    "ds_id": ds_id,
                    "table": table,
                    "column": column,
                }
            return {
                "allowed": bool(_get(res, "allowed", default=False)),
                "mask": "none",
                "mask_param": {},
                "row_filters": list(_get(res, "row_filters", default=[]) or []),
                "reasons": reasons,
                "rulesDetail": raw_rules,
                "ds_id": ds_id,
                "table": table,
                "column": None,
                "columns": _get(res, "columns", default={}) or {},
            }
    return _fallback_resolve(db, user, ds_id, table, column)


def table_allowed(db, user, ds_id: str, table: str) -> bool:
    try:
        return bool(resolve_policy(db, user, ds_id, table).get("allowed"))
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 查询执行（优先 sqlguard）
# --------------------------------------------------------------------------- #


def apply_mask(value: Any, mask: str, param: dict) -> Any:
    if value is None or mask in (None, "", "none"):
        return value
    text = str(value)
    param = param or {}
    if mask == "hash":
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    if mask == "replace":
        return param.get("replace_with", param.get("replaceWith", "***"))
    if mask == "truncate":
        keep = int(param.get("keep", param.get("start", 2)) or 2)
        return text[:keep] + "…"
    keep_start = int(param.get("start", 3) or 0)
    keep_end = int(param.get("end", 4) or 0)
    if "keep" in param:
        keep_start, keep_end = int(param.get("keep") or 0), 0
    if len(text) <= keep_start + keep_end:
        return "*" * max(len(text), 4)
    return text[:keep_start] + "****" + (text[-keep_end:] if keep_end else "")


@dataclass
class LocalGuardContext:
    db: Any
    user: Any
    datasource_id: str
    datasource_path: str | Path


def _local_guard_and_run(sql: str, ctx: LocalGuardContext, limit: int = 500) -> dict:
    """最小可用 SQL 安全网关（仅当 services.sqlguard 尚未就绪时启用）。"""
    import sqlglot
    from sqlglot import exp

    started = time.time()
    base = {
        "ok": False,
        "sql": sql,
        "originalSql": sql,
        "rewrittenSql": sql,
        "rows": [],
        "columns": [],
        "maskedColumns": [],
        "appliedRules": [],
        "deniedReason": None,
        "durationMs": 0,
        "rowCount": 0,
        "error": None,
    }
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except Exception as exc:
        base.update(deniedReason=f"SQL 解析失败：{exc}", durationMs=int((time.time() - started) * 1000))
        return base
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        base.update(deniedReason="仅支持单条只读查询", durationMs=int((time.time() - started) * 1000))
        return base
    parsed = statements[0]
    ctes = {c.alias_or_name.lower() for c in parsed.find_all(exp.CTE)}
    tables = [t for t in parsed.find_all(exp.Table) if (t.name or "").lower() not in ctes]

    allowed_tables: list[str] = []
    for t in tables:
        name = t.name
        if not name:
            continue
        res = resolve_policy(ctx.db, ctx.user, ctx.datasource_id, name)
        if not res.get("allowed"):
            base.update(deniedReason=f"无权访问表 {name}：{'；'.join(res.get('reasons') or [])}")
            base["durationMs"] = int((time.time() - started) * 1000)
            return base
        allowed_tables.append(name)

    # 列权限：显式引用被 deny 的列直接拒绝
    cols_by_table: dict[str, set[str]] = {}
    for t in tables:
        cols_by_table[t.name] = {c["name"] for c in columns_of(ctx.db, ctx.datasource_id, t.name)}
    selected_cols: set[str] = set()
    for col in parsed.find_all(exp.Column):
        selected_cols.add(col.name)
    for table, cols in cols_by_table.items():
        for col in list(selected_cols):
            if col not in cols or col == "*":
                continue
            res = resolve_policy(ctx.db, ctx.user, ctx.datasource_id, table, col)
            if not res.get("allowed"):
                base.update(deniedReason=f"无权访问字段 {table}.{col}")
                base["durationMs"] = int((time.time() - started) * 1000)
                return base

    # 行级过滤：AST 注入 WHERE
    applied: list[dict] = []
    for table in allowed_tables:
        res = resolve_policy(ctx.db, ctx.user, ctx.datasource_id, table)
        for rf in res.get("row_filters") or []:
            try:
                cond = sqlglot.parse_one(str(rf), read="sqlite")
                if isinstance(cond, exp.Condition):
                    parsed = parsed.where(cond, copy=False)
                    applied.append({"rule": "row_filter", "table": table, "sql": rf})
            except Exception:
                continue

    # 强制 LIMIT
    try:
        current = parsed.args.get("limit")
        if current is None:
            parsed = parsed.limit(limit)
            applied.append({"rule": "force_limit", "value": limit})
        else:
            try:
                cur = int(current.expression.this)
                if cur <= 0 or cur > limit:
                    parsed = parsed.limit(limit)
                    applied.append({"rule": "clamp_limit", "value": limit})
            except Exception:
                parsed = parsed.limit(limit)
    except Exception:
        parsed = parsed.limit(limit)

    rewritten = parsed.sql(dialect="sqlite")
    base["rewrittenSql"] = rewritten
    path = Path(ctx.datasource_path)
    if not path.exists():
        base.update(error=f"数据源不存在：{path}", durationMs=int((time.time() - started) * 1000))
        return base
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(rewritten)
        columns = [d[0] for d in cur.description or []]
        rows = [dict(r) for r in cur.fetchall()]
    except sqlite3.Error as exc:
        base.update(error=str(exc), durationMs=int((time.time() - started) * 1000))
        return base
    finally:
        conn.close()

    # 脱敏后处理
    masked_columns: list[str] = []
    for table in allowed_tables:
        for col in columns:
            res = resolve_policy(ctx.db, ctx.user, ctx.datasource_id, table, col)
            mask = res.get("mask") or "none"
            if not res.get("allowed"):
                continue
            if mask != "none":
                for row in rows:
                    row[col] = apply_mask(row.get(col), mask, res.get("mask_param") or {})
                masked_columns.append(col)
                applied.append({"rule": "mask", "column": f"{table}.{col}", "mask": mask})
    base.update(
        ok=True,
        rows=rows,
        columns=columns,
        maskedColumns=sorted(set(masked_columns)),
        appliedRules=applied,
        rowCount=len(rows),
        durationMs=int((time.time() - started) * 1000),
    )
    return base


def _normalize_guard_result(res: Any, original_sql: str, limit: int) -> dict:
    ok = _get(res, "ok", default=None)
    denied = _get(res, "denied_reason", "deniedReason", default=None)
    error = _get(res, "error", default=None)
    if ok is None:
        ok = not bool(denied) and not bool(error)
    columns = list(_get(res, "columns", default=[]) or [])
    rows_raw = _get(res, "rows", default=[]) or []
    rows: list[dict] = []
    for r in rows_raw:
        if isinstance(r, dict):
            rows.append({k: v for k, v in r.items()})
        elif isinstance(r, (list, tuple)):
            rows.append({columns[i] if i < len(columns) else f"c{i}": v for i, v in enumerate(r)})
    applied = _get(res, "applied_rules", "appliedRules", default=[]) or []
    return {
        "ok": bool(ok),
        "sql": original_sql,
        "originalSql": _get(res, "original_sql", "originalSql", default=original_sql),
        "rewrittenSql": _get(res, "rewritten_sql", "rewrittenSql", "sql", default=original_sql),
        "rows": rows,
        "columns": columns,
        "maskedColumns": list(_get(res, "masked_columns", "maskedColumns", default=[]) or []),
        "appliedRules": list(applied),
        "deniedReason": denied,
        "error": error,
        "durationMs": int(_get(res, "duration_ms", "durationMs", default=0) or 0),
        "rowCount": int(_get(res, "row_count", "rowCount", default=len(rows)) or len(rows)),
        "limit": int(_get(res, "limit", default=limit) or limit),
    }


def run_query(db, user, ds_id: str, sql: str, limit: int = 500) -> dict:
    """执行只读 SQL：优先走 services.sqlguard，缺失时用内置最小网关。"""
    ds = get_demo_datasource(db, ds_id)
    if ds is None:
        return {
            "ok": False,
            "sql": sql,
            "originalSql": sql,
            "rewrittenSql": sql,
            "rows": [],
            "columns": [],
            "maskedColumns": [],
            "appliedRules": [],
            "deniedReason": "未找到演示数据源",
            "error": None,
            "durationMs": 0,
            "rowCount": 0,
        }
    ds_id = getattr(ds, "id", ds_id)
    path = datasource_path(ds)
    svc = _service("sqlguard")
    if svc is not None and hasattr(svc, "guard_and_run"):
        try:
            GuardContext = getattr(svc, "GuardContext")
            try:
                ctx = GuardContext(db=db, user=user, datasource_id=ds_id, datasource_path=str(path))
            except TypeError:
                ctx = GuardContext(db, user, ds_id, str(path))
            res = svc.guard_and_run(sql, ctx, limit=limit)
            return _normalize_guard_result(res, sql, limit)
        except Exception as exc:
            # 业务拒绝以 GuardResult(ok=False) 返回；抛异常说明网关自身故障，
            # 降级到内置最小网关，保证演示链路不断（审计里仍会记录本异常）。
            fallback = _local_guard_and_run(sql, LocalGuardContext(db, user, ds_id, path), limit=limit)
            fallback.setdefault("appliedRules", []).append(
                {"rule": "fallback_local_guard", "error": f"{type(exc).__name__}: {exc}"}
            )
            fallback["guardFallback"] = True
            return fallback
    return _local_guard_and_run(sql, LocalGuardContext(db, user, ds_id, path), limit=limit)


# --------------------------------------------------------------------------- #
# 知识检索
# --------------------------------------------------------------------------- #


def search_knowledge(db, user, query: str, top_k: int = 5) -> list[dict]:
    svc = _service("knowledge_service")
    if svc is not None and hasattr(svc, "search"):
        try:
            hits = svc.search(db, user, query, top_k=top_k)
            if isinstance(hits, dict):
                raw_items = hits.get("items") or []
            elif isinstance(hits, (list, tuple)):
                raw_items = list(hits)
            else:
                raw_items = getattr(hits, "items", None) or []
            if raw_items:
                out = []
                for h in raw_items[:top_k]:
                    snippet = str(_get(h, "snippet", "text", default="") or "")
                    snippet = re.sub(r"</?em>", "", snippet)
                    out.append(
                        {
                            "docId": _get(h, "docId", "doc_id", default=""),
                            "docName": _get(h, "docName", "doc_name", "name", default=""),
                            "seq": _get(h, "seq", default=0),
                            "snippet": snippet,
                            "score": float(_get(h, "score", default=0) or 0),
                        }
                    )
                return out
            if isinstance(hits, (dict, list, tuple)) and not raw_items:
                return []
        except Exception:
            pass

    from ..models import KnowledgeChunk, KnowledgeDoc

    terms = [t for t in re.split(r"[\s,，。;；、/]+", query or "") if len(t) >= 2]
    docs = db.query(KnowledgeDoc).all()
    hits: list[dict] = []
    for doc in docs:
        for chunk in db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc.id).all():
            text = chunk.text or ""
            score = sum(text.count(t) for t in terms) + (3 if query and query[:6] in text else 0)
            if score <= 0:
                continue
            pos = min([text.find(t) for t in terms if text.find(t) >= 0] or [0])
            snippet = text[max(0, pos - 80) : pos + 260]
            hits.append(
                {
                    "docId": doc.id,
                    "docName": doc.name,
                    "seq": chunk.seq,
                    "snippet": snippet,
                    "score": float(score),
                }
            )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]


def data_scope_summary(db, user, ds_id: str) -> str:
    svc = _service("policy_service")
    if svc is not None and hasattr(svc, "data_scope_summary"):
        try:
            return str(svc.data_scope_summary(db, user, ds_id))
        except Exception:
            pass
    return "数据权限：以当前登录用户身份执行，表/列/行级策略实时生效。"


__all__ = [
    "get_demo_datasource",
    "datasource_path",
    "list_tables",
    "columns_of",
    "resolve_policy",
    "table_allowed",
    "run_query",
    "search_knowledge",
    "data_scope_summary",
    "apply_mask",
]
