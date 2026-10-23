"""SQL 安全网关：sqlglot AST 级改写（表/列/行权限 + 强制 LIMIT + 结果脱敏 + 审计）。

调用（其它模块的唯一入口）：
    from app.services.sqlguard import GuardContext, GuardResult, guard_and_run
    ctx = GuardContext(db=db, user=user, datasource_id=ds.id, datasource_path=path)
    res = guard_and_run("select * from worktime_fact limit 5", ctx)

返回 `GuardResult`（dataclass）。安全拒绝时 `ok=False` 且 `denied_reason` 具体可读；
执行期 SQL 报错时 `ok=False, denied_reason=None, error="..."`。每次调用都写一条
`sql_query` 审计（含 originalSql / rewrittenSql / rows / durationMs / appliedRules /
maskedColumns / datasource），被拒绝时 `result="denied", risk="high"`。
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import sqlglot
from sqlglot import exp
from sqlalchemy.orm import Session

from ..models import User
from . import policy_service
from .policy_service import ColumnRule, TableResolution

DIALECT = "sqlite"
DEFAULT_LIMIT = 500
MAX_LIMIT = 2000

_FORBIDDEN_NAMES = (
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "TruncateTable",
    "Attach", "Detach", "Pragma", "Command", "Grant", "Revoke", "Merge", "AlterTable",
    "LoadData", "Export", "Copy", "Set", "Use", "Analyze", "Vacuum", "Reindex",
)
_FORBIDDEN = tuple(
    getattr(exp, name) for name in _FORBIDDEN_NAMES if hasattr(exp, name)
)
_QUERY_TYPES = tuple(
    getattr(exp, name) for name in ("Select", "Union", "Intersect", "Except", "Query")
    if hasattr(exp, name)
)


# ---------------------------------------------------------------- 数据结构


@dataclass
class GuardContext:
    db: Session
    user: User
    datasource_id: str
    datasource_path: str
    #: 审计里记的"发起人"，预览他人权限时由 API 传入；默认等于 user
    audit_actor: User | None = None
    datasource_name: str = ""


@dataclass
class GuardResult:
    ok: bool
    sql: str
    original_sql: str
    columns: list[str] = field(default_factory=list)
    masked_columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    applied_rules: list[dict] = field(default_factory=list)
    denied_reason: str | None = None
    duration_ms: int = 0
    # 扩展字段（带默认值，不影响按位置构造）
    error: str | None = None
    limit: int = DEFAULT_LIMIT
    row_count: int = 0

    # -- 兼容 dict 风格取用（camelCase，便于工具/前端直用） --------------
    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "sql": self.sql,
            "originalSql": self.original_sql,
            "rewrittenSql": self.sql,
            "columns": list(self.columns),
            "maskedColumns": list(self.masked_columns),
            "rows": list(self.rows),
            "appliedRules": list(self.applied_rules),
            "deniedReason": self.denied_reason,
            "durationMs": self.duration_ms,
            "error": self.error,
            "limit": self.limit,
            "rowCount": self.row_count,
        }

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


# ---------------------------------------------------------------- 内部工具


def _deny(
    ctx: GuardContext,
    original: str,
    reason: str,
    *,
    rules: list[dict] | None = None,
    duration_ms: int = 0,
    sql: str = "",
) -> GuardResult:
    """构造拒绝结果并落审计。"""
    applied = list(rules or [])
    applied.append({"type": "deny", "detail": reason})
    _audit(
        ctx,
        original_sql=original,
        rewritten_sql=sql or original,
        rows=0,
        duration_ms=duration_ms,
        applied_rules=applied,
        masked_columns=[],
        denied=True,
        extra={"deniedReason": reason},
    )
    return GuardResult(
        ok=False,
        sql=sql or original,
        original_sql=original,
        columns=[],
        masked_columns=[],
        rows=[],
        applied_rules=applied,
        denied_reason=reason,
        duration_ms=duration_ms,
    )


def _audit(
    ctx: GuardContext,
    *,
    original_sql: str,
    rewritten_sql: str,
    rows: int,
    duration_ms: int,
    applied_rules: Iterable[dict],
    masked_columns: Iterable[str],
    denied: bool,
    extra: dict | None = None,
) -> None:
    from ..core.deps import audit as write_audit

    detail = {
        "originalSql": original_sql,
        "rewrittenSql": rewritten_sql,
        "rows": rows,
        "durationMs": duration_ms,
        "appliedRules": list(applied_rules),
        "maskedColumns": list(masked_columns),
        "datasource": ctx.datasource_id,
    }
    if extra:
        detail.update(extra)
    try:
        write_audit(
            ctx.db,
            actor=ctx.audit_actor or ctx.user,
            action="sql_query",
            target_type="datasource",
            target_id=ctx.datasource_id,
            target_name=ctx.datasource_name or "demo",
            detail=detail,
            risk="high" if denied else "low",
            result="denied" if denied else "success",
            commit=True,
        )
    except Exception:          # 审计失败不能打断查询主链路
        try:
            ctx.db.rollback()
        except Exception:
            pass


def _find_forbidden(node: exp.Expression) -> str | None:
    for sub in node.walk():
        if _FORBIDDEN and isinstance(sub, _FORBIDDEN):
            # PRAGMA 等被拒；纯 SELECT 的 SELECT .. INTO 也视为写操作
            return type(sub).__name__.upper()
        if isinstance(sub, exp.Select) and sub.args.get("into") is not None:
            return "SELECT INTO"
    return None


def _real_tables(root: exp.Expression) -> list[tuple[str, str]]:
    """返回 [(table_name, alias)]，已剔除 CTE 名称。"""
    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE) if c.alias_or_name}
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for tbl in root.find_all(exp.Table):
        name = (tbl.name or "").strip()
        if not name or name.lower() in cte_names:
            continue
        alias = (tbl.alias_or_name or name).strip()
        key = (name, alias)
        if key in seen:
            continue
        seen.add(key)
        out.append((name, alias))
    return out


def _int_limit(node: exp.Expression | None) -> int | None:
    if node is None:
        return None
    try:
        expr = node.args.get("expression") if hasattr(node, "args") else None
        expr = expr or node
        val = expr.this if isinstance(expr, exp.Literal) else None
        return int(str(val))
    except Exception:
        return None


def _q(alias: str, column: str, *, qualify: bool) -> exp.Expression:
    return exp.column(column, table=alias) if qualify else exp.column(column)


def _apply_row_filters(
    select: exp.Expression,
    filters: list[str],
    rules: list[dict],
    table: str,
    *,
    alias: str | None = None,
    qualify: bool = False,
) -> None:
    for raw in filters:
        try:
            parsed = sqlglot.parse_one(f"SELECT 1 WHERE {raw}", read=DIALECT)
            cond = parsed.args.get("where")
            cond = cond.this if cond is not None else None
        except Exception as exc:                      # row_filter 写错 → 安全失败
            raise ValueError(f"行级策略表达式无法解析：{raw}（{exc}）") from exc
        if cond is None:
            continue
        # 多表 JOIN 时给过滤列补上表限定，避免 "ambiguous column name"
        if qualify and alias:
            for col in cond.find_all(exp.Column):
                if col.table:
                    continue
                if col.find_ancestor(exp.Subquery) is not None:
                    continue           # 子查询内部的列属于子查询自己的 FROM
                col.set("table", exp.to_identifier(alias))
        existing = select.args.get("where")
        if existing is not None and existing.this is not None:
            left = existing.this
            if isinstance(left, (exp.Or, exp.And)) and not isinstance(left, exp.Paren):
                left = exp.Paren(this=left)
            merged = exp.and_(left, cond)
        else:
            merged = cond
        select.set("where", exp.Where(this=merged))
        rules.append(
            {
                "type": "row_filter",
                "table": table,
                "expression": raw,
                "detail": f"行级过滤注入 WHERE：{raw}"
                + (f"（已限定表别名 {alias}）" if qualify and alias else ""),
            }
        )


def _column_rule_map(resolutions: list[TableResolution]) -> dict[str, ColumnRule]:
    """按结果列名合并脱敏规则（同名多表取最严格）。"""
    merged: dict[str, ColumnRule] = {}
    weight = {"none": 0, "truncate": 1, "mask": 2, "replace": 2, "hash": 3}
    for res in resolutions:
        for name, rule in res.columns.items():
            cur = merged.get(name)
            if cur is None or weight.get(rule.mask, 0) > weight.get(cur.mask, 0):
                merged[name] = rule
    return merged


# ---------------------------------------------------------------- 主入口


def guard_and_run(sql: str, ctx: GuardContext, *, limit: int = DEFAULT_LIMIT) -> GuardResult:
    """解析 → 鉴权 → 改写 → 只读执行 → 脱敏，全链路审计。"""
    started = time.perf_counter()
    original = (sql or "").strip()
    cap = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    def done(result: GuardResult) -> GuardResult:
        result.duration_ms = result.duration_ms or int((time.perf_counter() - started) * 1000)
        return result

    if not original:
        return done(_deny(ctx, original, "SQL 不能为空"))

    # 1. 解析：只允许单条 SELECT / WITH
    try:
        statements = sqlglot.parse(original, read=DIALECT)
    except Exception as exc:
        return done(_deny(ctx, original, f"SQL 无法解析：{exc}"))
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return done(_deny(ctx, original, "仅支持只读查询（检测到多语句）"))

    root = statements[0]
    forbidden = _find_forbidden(root)
    if forbidden or not isinstance(root, _QUERY_TYPES):
        kind = forbidden or type(root).__name__.upper()
        return done(
            _deny(
                ctx,
                original,
                "仅支持只读查询"
                + (f"（检测到 {kind} 语句）" if forbidden else "（仅允许 SELECT / WITH 查询）"),
            )
        )
    if isinstance(root, exp.Select):
        target = root
    else:
        target = root
        if not isinstance(target, _QUERY_TYPES):
            return done(_deny(ctx, original, "仅支持只读查询"))

    # 2. 表级鉴权
    real_tables = _real_tables(root)
    if not real_tables:
        return done(_deny(ctx, original, "查询未引用任何数据表"))

    resolutions: list[TableResolution] = []
    for name, _alias in real_tables:
        res = policy_service.resolve(ctx.db, ctx.user, ctx.datasource_id, name)
        if not res.allowed:
            return done(
                _deny(
                    ctx,
                    original,
                    res.denied_reason or f"无权访问表 {name}",
                    rules=[{"type": "table", "table": name, "detail": res.denied_reason or "拒绝"}],
                )
            )
        resolutions.append(res)

    applied_rules: list[dict] = []
    for res in resolutions:
        applied_rules.append(
            {
                "type": "table",
                "table": res.table,
                "detail": f"表级放行：{res.table}",
                "policyId": (res.rules[0].get("policyId") if res.rules else None),
            }
        )

    # 3. 列级：显式引用未授权列 → 拒绝；SELECT * → 展开授权列
    res_by_name = {r.table: r for r in resolutions}
    alias_to_table = {alias: name for name, alias in real_tables}
    alias_to_table.update({name: name for name, _ in real_tables})
    single_table = real_tables[0][0] if len({n for n, _ in real_tables}) == 1 else None

    denied_used: list[tuple[str, str]] = []
    for col in root.find_all(exp.Column):
        if isinstance(col.this, exp.Star):
            continue
        cname = (col.name or "").strip()
        if not cname:
            continue
        qualifier = (col.table or "").strip()
        if qualifier:
            tname = alias_to_table.get(qualifier)
            if tname is None:
                continue
        else:
            if not single_table:
                continue
            tname = single_table
        res = res_by_name.get(tname)
        if res is None:
            continue
        rule = res.column_rule(cname)
        if rule is not None and not rule.visible:
            denied_used.append((tname, cname))
    if denied_used:
        tname, cname = denied_used[0]
        return done(
            _deny(
                ctx,
                original,
                f"无权访问字段 {cname}（表 {tname}）",
                rules=applied_rules
                + [
                    {
                        "type": "column_denied",
                        "table": tname,
                        "column": cname,
                        "detail": f"列 {cname} 被策略拒绝，不允许显式查询",
                    }
                ],
            )
        )

    # SELECT * 展开
    def expand_star_for(tname: str, qualify: bool, table_alias: str) -> list[exp.Expression]:
        res = res_by_name.get(tname)
        if res is None:
            return []
        allowed = res.visible_columns
        dropped = list(res.denied_columns)
        if dropped:
            applied_rules.append(
                {
                    "type": "column_denied",
                    "table": tname,
                    "columns": dropped,
                    "detail": f"{'、'.join(dropped)} 未授权，已从 SELECT * 中剔除",
                }
            )
        applied_rules.append(
            {
                "type": "star_expand",
                "table": tname,
                "columns": allowed,
                "detail": f"SELECT * 展开为 {len(allowed)} 个授权列",
            }
        )
        return [_q(table_alias, c, qualify=qualify) for c in allowed]

    if isinstance(target, exp.Select):
        new_expressions: list[exp.Expression] = []
        changed = False
        for item in target.expressions:
            if isinstance(item, exp.Star):
                changed = True
                for tname, alias in real_tables:
                    new_expressions.extend(expand_star_for(tname, len(real_tables) > 1, alias))
                continue
            if isinstance(item, exp.Column) and isinstance(item.this, exp.Star):
                changed = True
                qualifier = (item.table or "").strip()
                tname = alias_to_table.get(qualifier) if qualifier else single_table
                if tname is None and len(real_tables) == 1:
                    tname = real_tables[0][0]
                if tname is None:
                    new_expressions.append(item)
                    continue
                alias = dict((n, a) for n, a in real_tables).get(tname, tname)
                new_expressions.extend(expand_star_for(tname, len(real_tables) > 1, alias))
                continue
            new_expressions.append(item)
        if changed:
            target.set("expressions", new_expressions)

    # 4. 行级过滤
    multi_table = len({n for n, _ in real_tables}) > 1
    alias_by_table = {name: alias for name, alias in real_tables}
    for res in resolutions:
        if res.row_filters:
            try:
                _apply_row_filters(
                    target,
                    res.row_filters,
                    applied_rules,
                    res.table,
                    alias=alias_by_table.get(res.table, res.table),
                    qualify=multi_table,
                )
            except ValueError as exc:
                return done(_deny(ctx, original, str(exc), rules=applied_rules))

    # 5. 强制 LIMIT
    existing_limit = None
    limit_node = target.args.get("limit") if hasattr(target, "args") else None
    if limit_node is not None:
        existing_limit = _int_limit(limit_node)
    effective_limit = min(cap, existing_limit) if existing_limit else cap
    applied_rules.append(
        {
            "type": "limit",
            "detail": f"强制 LIMIT {effective_limit}"
            + (f"（原 LIMIT {existing_limit}）" if existing_limit else f"（用户上限 {cap}）"),
        }
    )
    try:
        target.set("limit", exp.Limit(expression=exp.Literal.number(effective_limit)))
    except Exception:
        pass

    # 6. 生成改写 SQL
    try:
        rewritten = target.sql(dialect=DIALECT)
    except Exception as exc:
        return done(_deny(ctx, original, f"SQL 改写失败：{exc}", rules=applied_rules))

    # 7. 只读执行
    path = Path(ctx.datasource_path)
    if not str(path) or not path.exists():
        _audit(
            ctx,
            original_sql=original,
            rewritten_sql=rewritten,
            rows=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
            applied_rules=applied_rules,
            masked_columns=[],
            denied=False,
            extra={"error": "数据源文件不存在"},
        )
        return done(
            GuardResult(
                ok=False,
                sql=rewritten,
                original_sql=original,
                applied_rules=applied_rules,
                error=f"数据源文件不存在：{path}",
                limit=effective_limit,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        )

    columns: list[str] = []
    raw_rows: list[dict] = []
    exec_error: str | None = None
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(rewritten)
            columns = [str(d[0]) for d in (cur.description or [])]
            raw_rows = [dict(r) for r in cur.fetchmany(effective_limit)]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        exec_error = f"SQL 执行失败：{exc}"

    duration_ms = int((time.perf_counter() - started) * 1000)

    # 8. 结果脱敏
    rule_map = _column_rule_map(resolutions)
    masked_columns: list[str] = []
    rows: list[dict] = []
    if not exec_error:
        for row in raw_rows:
            out, masked = policy_service.mask_row(row, rule_map)
            if masked:
                for col in masked:
                    if col not in masked_columns:
                        masked_columns.append(col)
            rows.append(out)
        for col in masked_columns:
            rule = rule_map[col]
            applied_rules.append(
                {
                    "type": "mask",
                    "column": col,
                    "mask": rule.mask,
                    "maskParam": dict(rule.mask_param or {}),
                    "detail": f"列 {col} 按 {rule.mask} 脱敏",
                }
            )

    _audit(
        ctx,
        original_sql=original,
        rewritten_sql=rewritten,
        rows=len(rows),
        duration_ms=duration_ms,
        applied_rules=applied_rules,
        masked_columns=masked_columns,
        denied=False,
        extra={"error": exec_error} if exec_error else None,
    )

    return done(
        GuardResult(
            ok=exec_error is None,
            sql=rewritten,
            original_sql=original,
            columns=columns,
            masked_columns=masked_columns,
            rows=rows,
            applied_rules=applied_rules,
            denied_reason=None,
            duration_ms=duration_ms,
            error=exec_error,
            limit=effective_limit,
            row_count=len(rows),
        )
    )


#: 契约 §6 里的简写
guard = guard_and_run


def rewrite_only(sql: str, ctx: GuardContext, *, limit: int = DEFAULT_LIMIT) -> GuardResult:
    """只做鉴权与改写，不执行（用于策略页展示改写前后差异）。"""
    result = guard_and_run(sql, ctx, limit=limit)
    result.rows = []
    return result


__all__ = [
    "GuardContext",
    "GuardResult",
    "guard_and_run",
    "guard",
    "rewrite_only",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
]
