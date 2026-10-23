"""ChatBI 数据查询技能：表清单 / 字段结构 / 自然语言问数。

离线模式不调用 LLM：用「关键词 → 维度/指标模板」生成 SQL，再交给 sqlguard
做表/列/行级鉴权、AST 改写与脱敏。返回结构见任务契约
`{sql, rewrittenSql, rows, rowCount, columns, maskedColumns, durationMs, appliedRules}`。
"""
from __future__ import annotations

from datetime import date, timedelta

from .. import columns_of, datasource_path, get_demo_datasource, list_tables, resolve_policy, run_query
from ..types import ToolContext, ToolResult, ToolSpec
from . import STATE_CHATBI, json_safe, quarter_range, sample_rows

WORKTIME_KEYS = ("工时", "人效", "效率", "区域", "大屏", "分析", "报表", "上季度", "加班", "缺陷", "交付", "产能")
CRM_KEYS = ("客户", "商机", "合同额", "回款", "销售", "订单")
CONTRACT_KEYS = ("合同", "条款")


def _ds(ctx: ToolContext):
    return get_demo_datasource(ctx.db, ctx.datasource_id or None)


def _cols(ctx: ToolContext, table: str) -> list[dict]:
    cache: dict = ctx.state.setdefault("columns_cache", {})
    if table not in cache:
        cache[table] = columns_of(ctx.db, ctx.datasource_id or None, table)
    return cache[table]


def _has(ctx: ToolContext, table: str, col: str) -> bool:
    return any(c.get("name") == col for c in _cols(ctx, table))


def _pick(ctx: ToolContext, table: str, *names: str) -> str:
    existing = {c.get("name") for c in _cols(ctx, table)}
    for name in names:
        if name in existing:
            return name
    return ""


def visible_tables(ctx: ToolContext) -> list[dict]:
    ds = _ds(ctx)
    if ds is None:
        return []
    rows = list_tables(ctx.db, getattr(ds, "id", None))
    out = []
    for row in rows:
        name = row.get("name") or ""
        if not name:
            continue
        res = resolve_policy(ctx.db, ctx.user, getattr(ds, "id", ""), name)
        if not res.get("allowed"):
            continue
        out.append(
            {
                "name": name,
                "comment": row.get("comment") or "",
                "rowCount": row.get("rowCount") or row.get("row_count") or 0,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# 工具 1：list_tables
# --------------------------------------------------------------------------- #


async def list_tables_handler(params: dict, ctx: ToolContext) -> ToolResult:
    ds = _ds(ctx)
    if ds is None:
        return ToolResult(ok=False, error="未找到可用的演示数据源")
    tables = visible_tables(ctx)
    output = {
        "datasource": {"id": getattr(ds, "id", ""), "name": getattr(ds, "name", ""), "type": getattr(ds, "type", "sqlite")},
        "tables": tables,
        "tableCount": len(tables),
    }
    return ToolResult(
        ok=True,
        summary=f"数据源 {getattr(ds, 'name', 'demo')} 中当前用户可见 {len(tables)} 张表",
        output=output,
    )


# --------------------------------------------------------------------------- #
# 工具 2：describe_table
# --------------------------------------------------------------------------- #


async def describe_table_handler(params: dict, ctx: ToolContext) -> ToolResult:
    ds = _ds(ctx)
    if ds is None:
        return ToolResult(ok=False, error="未找到可用的演示数据源")
    table = str(params.get("table") or params.get("name") or "worktime_fact").strip()
    ds_id = getattr(ds, "id", "")
    res = resolve_policy(ctx.db, ctx.user, ds_id, table)
    if not res.get("allowed"):
        available = [t["name"] for t in visible_tables(ctx)]
        policy_ids = [
            r.get("policyId") or r.get("policy_id")
            for r in (res.get("rulesDetail") or [])
            if isinstance(r, dict)
        ]
        reason = "；".join(res.get("reasons") or []) or "无授权策略"
        return ToolResult(
            ok=False,
            error=f"无权访问表 {table}（{reason}）。当前账号可见表：{', '.join(available) or '无'}",
            output={
                "denied": True,
                "table": table,
                "deniedReason": reason,
                "policyIds": [p for p in policy_ids if p],
                "availableTables": available,
            },
        )
    cols = []
    for col in _cols(ctx, table):
        name = col.get("name") or ""
        rule = resolve_policy(ctx.db, ctx.user, ds_id, table, name)
        cols.append(
            {
                "name": name,
                "type": col.get("type") or "TEXT",
                "comment": col.get("comment") or "",
                "sensitiveLevel": col.get("sensitive_level") or col.get("sensitiveLevel") or "public",
                "mask": rule.get("mask") or "none",
                "allowed": bool(rule.get("allowed")),
            }
        )
    masked = [c["name"] for c in cols if c["mask"] != "none"]
    output = {
        "table": table,
        "columns": cols,
        "columnCount": len(cols),
        "maskedColumns": masked,
        "rowFilter": res.get("row_filters") or [],
        "reason": res.get("reasons") or [],
    }
    return ToolResult(
        ok=True,
        summary=f"{table} 共 {len(cols)} 个字段" + (f"，其中 {', '.join(masked)} 命中脱敏策略" if masked else ""),
        output=output,
    )


# --------------------------------------------------------------------------- #
# 工具 3：ask（自然语言 → SQL）
# --------------------------------------------------------------------------- #


def _table_candidates(question: str) -> list[str]:
    if any(k in question for k in CONTRACT_KEYS):
        return ["contract_sample", "worktime_fact"]
    if any(k in question for k in CRM_KEYS):
        return ["crm_customer", "crm_order", "worktime_fact"]
    return ["worktime_fact", "crm_customer"]


def _resolve_period(ctx: ToolContext, question: str) -> tuple[str, str, str, bool]:
    """返回 (start, end, label, explicit)。"""
    today = date.today()
    if "上上季度" in question:
        start, end, label = quarter_range(today, -2)
        return start.isoformat(), end.isoformat(), label, True
    if "上季度" in question or "上一季度" in question:
        start, end, label = quarter_range(today, -1)
        return start.isoformat(), end.isoformat(), label, True
    if "本季度" in question or "这季度" in question:
        start, end, label = quarter_range(today, 0)
        return start.isoformat(), end.isoformat(), label, True
    if "上月" in question:
        first = today.replace(day=1)
        end = first - timedelta(days=1)
        start = end.replace(day=1)
        return start.isoformat(), end.isoformat(), f"{start.year}年{start.month}月", True
    if "本月" in question:
        return today.replace(day=1).isoformat(), today.isoformat(), f"{today.year}年{today.month}月", True
    if "近30天" in question or "最近30天" in question:
        return (today - timedelta(days=29)).isoformat(), today.isoformat(), "近30天", True
    if "今年" in question:
        return date(today.year, 1, 1).isoformat(), today.isoformat(), f"{today.year}年", True
    if "去年" in question:
        start, end, _ = quarter_range(date(today.year - 1, 12, 31), 0)
        return date(today.year - 1, 1, 1).isoformat(), date(today.year - 1, 12, 31).isoformat(), f"{today.year - 1}年", True
    # 未指定：取数据中最新日期所在季度
    latest = _latest_date(ctx)
    if latest:
        start, end, label = quarter_range(latest, 0)
        return start.isoformat(), end.isoformat(), label, False
    start, end, label = quarter_range(today, -1)
    return start.isoformat(), end.isoformat(), label, False


def _latest_date(ctx: ToolContext) -> date | None:
    ds = _ds(ctx)
    if ds is None:
        return None
    date_col = _pick(ctx, "worktime_fact", "work_date", "date", "stat_date")
    if not date_col:
        return None
    result = run_query(ctx.db, ctx.user, getattr(ds, "id", ""), f"SELECT MAX({date_col}) AS max_date FROM worktime_fact", limit=10)
    if not result.get("ok") or not result.get("rows"):
        return None
    raw = result["rows"][0].get("max_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _build_worktime_sql(ctx: ToolContext, start: str, end: str) -> str:
    date_col = _pick(ctx, "worktime_fact", "work_date", "date", "stat_date")
    region_col = _pick(ctx, "worktime_fact", "region")
    hours_col = _pick(ctx, "worktime_fact", "hours", "work_hours")
    ot_col = _pick(ctx, "worktime_fact", "overtime_hours", "overtime")
    task_col = _pick(ctx, "worktime_fact", "delivered_tasks", "tasks", "delivered")
    defect_col = _pick(ctx, "worktime_fact", "defect_count", "defects")
    salary_col = _pick(ctx, "worktime_fact", "salary")

    month_expr = f"strftime('%Y-%m', {date_col})" if date_col else "substr(work_date, 1, 7)"
    if not region_col or not date_col or not hours_col:
        # 极端兜底：结构不符时直接全表采样
        return f"SELECT * FROM worktime_fact LIMIT 200"

    metrics = [f"SUM({hours_col}) AS hours"]
    metrics.append(f"SUM({ot_col}) AS overtime" if ot_col else "0 AS overtime")
    metrics.append(f"SUM({task_col}) AS tasks" if task_col else "0 AS tasks")
    metrics.append(f"SUM({defect_col}) AS defects" if defect_col else "0 AS defects")
    metrics.append(f"AVG({salary_col}) AS salary" if salary_col else "0 AS salary")
    return (
        f"SELECT {region_col} AS region, {month_expr} AS month, "
        + ", ".join(metrics)
        + f" FROM worktime_fact WHERE {date_col} BETWEEN '{start}' AND '{end}' "
        + f"GROUP BY {region_col}, {month_expr} ORDER BY month, region"
    )


def _build_crm_sql(ctx: ToolContext) -> str:
    if _has(ctx, "crm_customer", "annual_revenue"):
        return (
            "SELECT name, industry, scale, region, level, annual_revenue, contracts_amount "
            "FROM crm_customer ORDER BY contracts_amount DESC"
        )
    return "SELECT * FROM crm_customer LIMIT 200"


def _build_contract_sql(ctx: ToolContext) -> str:
    return "SELECT contract_name, clause_no, title, category, risk_hint FROM contract_sample ORDER BY contract_name, clause_no"


async def ask_handler(params: dict, ctx: ToolContext) -> ToolResult:
    question = str(params.get("question") or "").strip()
    if not question:
        return ToolResult(ok=False, error="缺少 question 参数")
    ds = _ds(ctx)
    if ds is None:
        return ToolResult(ok=False, error="未找到可用的演示数据源")
    ds_id = getattr(ds, "id", "")

    visible = {t["name"] for t in visible_tables(ctx)}
    table = next((t for t in _table_candidates(question) if t in visible), next(iter(visible), ""))
    if not table:
        available = [t["name"] for t in visible_tables(ctx)]
        denied_hint = ""
        for candidate in _table_candidates(question):
            denied = resolve_policy(ctx.db, ctx.user, ds_id, candidate)
            if not denied.get("allowed"):
                denied_hint = f"（{candidate} 未授权：{'；'.join(denied.get('reasons') or [])}）"
                break
        return ToolResult(
            ok=False,
            error=f"当前用户没有任何可查询的数据表，数据权限默认拒绝{denied_hint}",
            output={"denied": True, "availableTables": available, "deniedReason": denied_hint},
        )

    period = {"start": "", "end": "", "label": ""}
    sql = ""
    if table == "worktime_fact":
        start, end, label, explicit = _resolve_period(ctx, question)
        period = {"start": start, "end": end, "label": label}
        sql = _build_worktime_sql(ctx, start, end)
    elif table == "crm_customer":
        sql = _build_crm_sql(ctx)
    elif table == "contract_sample":
        sql = _build_contract_sql(ctx)
    else:
        sql = f"SELECT * FROM {table} LIMIT 200"

    result = run_query(ctx.db, ctx.user, ds_id, sql, limit=500)

    # 显式季度无数据时，自动回落到数据中最新季度（演示友好）
    if table == "worktime_fact" and result.get("ok") and not result.get("rows") and not period.get("label", "").endswith("月"):
        latest = _latest_date(ctx)
        if latest:
            start, end, label = quarter_range(latest, 0)
            sql = _build_worktime_sql(ctx, start.isoformat(), end.isoformat())
            result = run_query(ctx.db, ctx.user, ds_id, sql, limit=500)
            period = {"start": start.isoformat(), "end": end.isoformat(), "label": label, "fallback": True}

    if not result.get("ok"):
        reason = result.get("deniedReason") or result.get("error") or "查询失败"
        available = [t["name"] for t in visible_tables(ctx)]
        return ToolResult(
            ok=False,
            error=f"查询未执行：{reason}。当前账号可见表：{', '.join(available) or '无'}",
            output={
                "sql": sql,
                "table": table,
                "deniedReason": result.get("deniedReason"),
                "availableTables": available,
                "maskedColumns": result.get("maskedColumns") or [],
            },
        )

    rows = [json_safe(r) for r in result.get("rows") or []]
    masked = result.get("maskedColumns") or []
    state = {
        "question": question,
        "table": table,
        "datasourceId": ds_id,
        "datasourceName": getattr(ds, "name", "demo"),
        "datasourcePath": str(datasource_path(ds)),
        "sql": sql,
        "rewrittenSql": result.get("rewrittenSql") or sql,
        "rows": rows,
        "columns": result.get("columns") or (list(rows[0].keys()) if rows else []),
        "maskedColumns": masked,
        "appliedRules": result.get("appliedRules") or [],
        "rowCount": result.get("rowCount") or len(rows),
        "durationMs": result.get("durationMs") or 0,
        "period": period,
    }
    ctx.state[STATE_CHATBI] = state

    mask_note = f"；{', '.join(masked)} 已按策略脱敏" if masked else "；未触及脱敏字段"
    output = {
        "question": question,
        "table": table,
        "sql": sql,
        "rewrittenSql": state["rewrittenSql"],
        "columns": state["columns"],
        "rows": sample_rows(rows, 200),
        "rowCount": state["rowCount"],
        "maskedColumns": masked,
        "durationMs": state["durationMs"],
        "appliedRules": state["appliedRules"],
        "period": period,
        "maskedNote": mask_note,
    }
    return ToolResult(
        ok=True,
        summary=f"查询完成：{state['rowCount']} 行{mask_note}",
        output=json_safe(output),
    )


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="chatbi.list_tables",
        title="列出可用数据表",
        description="列出当前用户数据权限内可见的数据表（含行数），用于判断有没有相关数据。",
        params={"type": "object", "properties": {}},
        handler=list_tables_handler,
        risk="low",
        skill="chatbi",
    ),
    ToolSpec(
        name="chatbi.describe_table",
        title="查看表字段结构",
        description="查看表的字段、类型、敏感级别、脱敏与访问权限。",
        params={
            "type": "object",
            "properties": {"table": {"type": "string", "description": "表名，如 worktime_fact"}},
            "required": ["table"],
        },
        handler=describe_table_handler,
        risk="low",
        skill="chatbi",
    ),
    ToolSpec(
        name="chatbi.ask",
        title="执行自然语言问数",
        description="把业务问题翻译成只读 SQL，经数据权限网关改写后执行并返回结果、脱敏列与审计信息。",
        params={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "自然语言问题，例如：统计上季度各区域各月工时与效率"},
                "datasourceId": {"type": "string", "description": "可选数据源 ID"},
            },
            "required": ["question"],
        },
        handler=ask_handler,
        risk="low",
        skill="chatbi",
    ),
]
