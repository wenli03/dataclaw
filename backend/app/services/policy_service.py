"""数据权限策略求值器（表级 / 列级 / 行级 / 脱敏 / 敏感分级兜底）。

设计要点（对应契约 §5.3）：
1. 收集命中策略：`(subject_type=user, subject_id=user.id)` 优先于 `(role, user.role)`；
   同一优先级维度下 `priority` 大者优先。
2. 默认拒绝：一张表若没有任何 allow（表级或数据源级）→ 不可见，返回可解释原因。
3. 行级：所有命中的 `row_filter` 以 AND 合并（由 sqlguard 注入 WHERE）。
4. 脱敏：命中列的 `mask` 生效；`none` 保留原值。
5. 敏感分级兜底：`top_secret` / `secret` 列在无显式 allow 时按 `mask` 处理。
6. 每次求值都产出 `rules`，供审计 `detail.rules` 与前端"为什么"展示。

对外主入口：
    resolve(db, user, datasource_id, table, column=None) -> TableResolution
    resolve_all(db, user, datasource_id) -> list[TableResolution]
    effective_matrix(db, user) -> dict
    apply_mask(value, mask, param) -> Any
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ColumnMeta, DataSource, Policy, TableMeta, User

# ---------------------------------------------------------------- 常量

MASK_MODES = ("none", "mask", "hash", "replace", "truncate")
SENSITIVE_LEVELS = ("public", "internal", "secret", "top_secret")
LEVEL_RANK = {lvl: i for i, lvl in enumerate(SENSITIVE_LEVELS)}
#: 无显式策略时按 mask 处理的最低密级
FALLBACK_MASK_LEVEL = "secret"


# ---------------------------------------------------------------- 数据结构


@dataclass
class ColumnRule:
    """单列的有效规则。"""

    column: str
    action: str = "allow"                       # allow | deny
    mask: str = "none"                          # none|mask|hash|replace|truncate
    mask_param: dict = field(default_factory=dict)
    sensitive_level: str = "public"
    comment: str = ""
    policy_id: str | None = None
    reason: str = "默认可见"

    @property
    def visible(self) -> bool:
        return self.action != "deny"

    @property
    def masked(self) -> bool:
        return self.visible and self.mask not in (None, "", "none")

    def to_dict(self) -> dict:
        return {
            "column": self.column,
            "action": self.action,
            "mask": self.mask,
            "maskParam": dict(self.mask_param or {}),
            "sensitiveLevel": self.sensitive_level,
            "comment": self.comment,
            "policyId": self.policy_id,
            "reason": self.reason,
            "visible": self.visible,
            "masked": self.masked,
        }


@dataclass
class TableResolution:
    """一张表对某个用户的有效权限。可当 dict 用（兼容其它模块的取用方式）。"""

    table: str
    datasource_id: str
    user_id: str
    allowed: bool = False
    denied_reason: str | None = None
    columns: dict[str, ColumnRule] = field(default_factory=dict)
    denied_columns: dict[str, ColumnRule] = field(default_factory=dict)
    row_filters: list[str] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    table_comment: str = ""
    row_count: int = 0
    meta_known: bool = True

    # -- 便捷视图 -------------------------------------------------
    @property
    def visible_columns(self) -> list[str]:
        return [c for c, r in self.columns.items() if r.visible]

    @property
    def masked_columns(self) -> list[str]:
        return [c for c, r in self.columns.items() if r.masked]

    def column_rule(self, column: str) -> ColumnRule | None:
        return self.columns.get(column) or self.denied_columns.get(column)

    def can_use_column(self, column: str) -> bool:
        rule = self.column_rule(column)
        if rule is None:
            return True                      # 未知列交给上层（元数据缺失）
        return rule.visible

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "datasourceId": self.datasource_id,
            "userId": self.user_id,
            "allowed": self.allowed,
            "deniedReason": self.denied_reason,
            "comment": self.table_comment,
            "rowCount": self.row_count,
            "metaKnown": self.meta_known,
            "columns": [r.to_dict() for r in self.columns.values()],
            "deniedColumns": [r.to_dict() for r in self.denied_columns.values()],
            "rowFilters": list(self.row_filters),
            "rules": list(self.rules),
            "visibleColumns": self.visible_columns,
            "maskedColumns": self.masked_columns,
        }

    # 兼容 dict 取用
    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


# ---------------------------------------------------------------- 工具函数


def resource_key(datasource_id: str, table: str, column: str | None = None) -> str:
    """规范资源键：ds:table / ds:table.col。"""
    if column:
        return f"{datasource_id}:{table}.{column}"
    return f"{datasource_id}:{table}"


def _split_column_resource(resource_id: str) -> tuple[str, str, str]:
    """把 `ds:table.col` / `table.col` / `*.col` 解析成 (ds, table, column)。"""
    rid = (resource_id or "").strip()
    if not rid:
        return "", "", ""
    if "." not in rid:
        return "", "", ""
    head, column = rid.rsplit(".", 1)
    if ":" in head:
        ds, table = head.split(":", 1)
    else:
        ds, table = "", head
    return ds, table, column


def _split_table_resource(resource_id: str) -> tuple[str, str]:
    rid = (resource_id or "").strip()
    if not rid:
        return "", ""
    if ":" in rid:
        ds, table = rid.split(":", 1)
        return ds, table
    return "", rid


def _subject_scope(subject_type: str) -> int:
    return 2 if subject_type == "user" else 1


def load_policies(db: Session, user: User) -> list[Policy]:
    """取出与当前用户相关且启用的全部策略（已排序：用户 > 角色，priority 降序）。"""
    rows = db.scalars(
        select(Policy).where(
            Policy.enabled.is_(True),
            Policy.subject_type.in_(("user", "role")),
            Policy.subject_id.in_((user.id, user.role)),
        )
    ).all()
    out: list[Policy] = []
    for p in rows:
        if p.subject_type == "user" and p.subject_id != user.id:
            continue
        if p.subject_type == "role" and p.subject_id != user.role:
            continue
        out.append(p)
    out.sort(key=lambda p: (
        -_subject_scope(p.subject_type),
        -(p.priority or 0),
        p.created_at.timestamp() if p.created_at else 0.0,
    ))
    return out


def _match_table(policy: Policy, datasource_id: str, table: str) -> bool:
    if policy.resource_type == "datasource":
        rid = (policy.resource_id or "").strip()
        return rid in ("*", datasource_id, f"{datasource_id}:*")
    if policy.resource_type in ("table", "row"):
        ds, tbl = _split_table_resource(policy.resource_id)
        if tbl not in ("*", table):
            return False
        return ds in ("", "*", datasource_id)
    return False


def _match_column(policy: Policy, datasource_id: str, table: str, column: str) -> bool:
    if policy.resource_type != "column":
        return False
    ds, tbl, col = _split_column_resource(policy.resource_id)
    if col not in ("*", column):
        return False
    if tbl not in ("", "*", table):
        return False
    return ds in ("", "*", datasource_id)


def _rule_brief(p: Policy, reason: str) -> dict:
    return {
        "policyId": p.id,
        "subjectType": p.subject_type,
        "subjectId": p.subject_id,
        "resourceType": p.resource_type,
        "resourceId": p.resource_id,
        "action": p.action,
        "mask": p.mask or "none",
        "maskParam": dict(p.mask_param or {}),
        "rowFilter": p.row_filter or "",
        "priority": p.priority,
        "note": p.note or "",
        "reason": reason,
    }


# ---------------------------------------------------------------- 脱敏


def apply_mask(value: Any, mask: str | None, param: dict | None = None) -> Any:
    """按规则对单个值脱敏。None / 空值原样返回。"""
    param = param or {}
    mode = (mask or "none").lower()
    if mode in ("none", "") or value is None:
        return value
    text = "" if value is None else str(value)
    if text == "":
        return text

    if mode == "mask":
        keep = int(param.get("keep", 0) or 0)
        if keep <= 0:
            return "****"
        if len(text) <= keep * 2:
            return text[:keep] + "****"
        return f"{text[:keep]}****{text[-keep:]}"

    if mode == "hash":
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return "sha256:" + digest[:12]

    if mode == "replace":
        return str(param.get("replace_with", param.get("replaceWith", "***")))

    if mode == "truncate":
        keep = int(param.get("keep", 4) or 4)
        if keep <= 0:
            return "…"
        if len(text) <= keep:
            return text + ""
        return text[:keep] + "…"

    return value


def mask_row(row: dict, rules: dict[str, ColumnRule]) -> tuple[dict, list[str]]:
    """对结果行做后处理，返回 (新行, 被脱敏列名)。"""
    masked: list[str] = []
    out: dict = {}
    for key, val in row.items():
        rule = rules.get(key)
        if rule is not None and rule.masked:
            out[key] = apply_mask(val, rule.mask, rule.mask_param)
            masked.append(key)
        else:
            out[key] = val
    return out, masked


# ---------------------------------------------------------------- 主求值


def _resolve_impl(
    db: Session | None = None,
    user: User | None = None,
    datasource_id: str | None = None,
    table: str | None = None,
    column: str | None = None,
    *,
    datasource: str | None = None,
    table_name: str | None = None,
    policies: Iterable[Policy] | None = None,
    columns_meta: list[ColumnMeta] | None = None,
) -> TableResolution:
    """求某用户对 `datasource:table`（可选某一列）的有效权限。

    参数兼容位置与关键字两种写法；`column` 传 None 时返回整表解析结果。
    """
    if db is None or user is None:
        raise ValueError("policy_service.resolve 需要 db 与 user")
    ds_id = datasource_id or datasource or ""
    tbl = table or table_name or ""
    if not ds_id or not tbl:
        raise ValueError("policy_service.resolve 需要 datasource_id 与 table")

    plist = list(policies) if policies is not None else load_policies(db, user)
    if columns_meta is None:
        columns_meta = db.scalars(
            select(ColumnMeta)
            .where(ColumnMeta.datasource_id == ds_id, ColumnMeta.table_name == tbl)
            .order_by(ColumnMeta.name)
        ).all()
    tmeta = db.scalars(
        select(TableMeta).where(TableMeta.datasource_id == ds_id, TableMeta.name == tbl)
    ).first()

    res = TableResolution(
        table=tbl,
        datasource_id=ds_id,
        user_id=user.id,
        table_comment=(tmeta.comment if tmeta else "") or "",
        row_count=int(tmeta.row_count or 0) if tmeta else 0,
        meta_known=bool(columns_meta),
    )
    # 元数据缺失时向后兼容：按"列默认可见"处理（表可见性仍需显式 allow）

    # ---- 1. 表级判定（兼容数据源级 allow） ----
    # 求值顺序（契约 §5.3）：
    #   a. 先只收集 subject_type="user" 且命中该资源的策略；只要存在任意一条 user 级规则
    #      （allow 或 deny），就**以 user 级结果为准**（同级内 priority 大者优先）。
    #   b. 只有不存在任何 user 级规则时，才回退到 role 级「兜底」策略。
    # 这样"角色兜底"才真正是兜底，不会被角色 deny 反过来覆盖用户 allow。
    table_hits_all = [p for p in plist if _match_table(p, ds_id, tbl)]
    user_hits = [p for p in table_hits_all if p.subject_type == "user"]
    table_hits = user_hits if user_hits else [
        p for p in table_hits_all if p.subject_type == "role"
    ]
    decisive = table_hits[0] if table_hits else None
    allow_hit: Policy | None = decisive if decisive is not None and decisive.action == "allow" else None
    deny_hit: Policy | None = decisive if decisive is not None and decisive.action == "deny" else None

    if deny_hit is not None:
        res.allowed = False
        res.denied_reason = (
            f"无权访问表 {tbl}（命中拒绝策略：{deny_hit.subject_type}="
            f"{deny_hit.subject_id} / {deny_hit.note or deny_hit.id}）"
        )
        res.rules.append(_rule_brief(deny_hit, "表级拒绝优先"))
        for cm in columns_meta:
            rule = ColumnRule(
                column=cm.name,
                action="deny",
                sensitive_level=cm.sensitive_level or "public",
                comment=cm.comment or "",
                policy_id=deny_hit.id,
                reason="整表已拒绝",
            )
            res.denied_columns[cm.name] = rule
        return res

    if allow_hit is None:
        res.allowed = False
        res.denied_reason = f"无权访问表 {tbl}（默认拒绝：未找到授权策略）"
        res.rules.append(
            {
                "policyId": None,
                "subjectType": "default",
                "subjectId": user.role,
                "resourceType": "table",
                "resourceId": resource_key(ds_id, tbl),
                "action": "deny",
                "reason": "默认拒绝：该表没有任何 allow 策略",
            }
        )
        for cm in columns_meta:
            res.denied_columns[cm.name] = ColumnRule(
                column=cm.name,
                action="deny",
                sensitive_level=cm.sensitive_level or "public",
                comment=cm.comment or "",
                reason="默认拒绝",
            )
        return res

    res.allowed = True
    res.rules.append(_rule_brief(allow_hit, f"表级放行（{allow_hit.subject_type}）"))

    # ---- 2. 行级策略（表级或独立的 row 策略，按顺序 AND 合并） ----
    seen_filters: set[str] = set()
    for p in table_hits:
        if not p.row_filter:
            continue
        if p.action == "deny":
            continue
        expr = p.row_filter.strip()
        if expr and expr not in seen_filters:
            seen_filters.add(expr)
            res.row_filters.append(expr)
            res.rules.append(
                {
                    "policyId": p.id,
                    "subjectType": p.subject_type,
                    "subjectId": p.subject_id,
                    "resourceType": "row",
                    "resourceId": p.resource_id,
                    "action": "filter",
                    "rowFilter": expr,
                    "priority": p.priority,
                    "reason": "行级过滤注入 WHERE",
                    "note": p.note or "",
                }
            )

    # ---- 3. 列级判定 ----
    if not columns_meta:
        # 元数据缺失：不臆测列，表可见即全部可见
        return res

    for cm in columns_meta:
        level = cm.sensitive_level or "public"
        col_all = [p for p in plist if _match_column(p, ds_id, tbl, cm.name)]
        col_user = [p for p in col_all if p.subject_type == "user"]
        col_hits = col_user if col_user else [p for p in col_all if p.subject_type == "role"]
        # 同表级规则：同级内以 priority 最高的第一条为准（排序已保证）
        hit = col_hits[0] if col_hits else None
        if hit is not None:
            rule = ColumnRule(
                column=cm.name,
                action=hit.action,
                mask=hit.mask or "none",
                mask_param=dict(hit.mask_param or {}),
                sensitive_level=level,
                comment=cm.comment or "",
                policy_id=hit.id,
                reason=(
                    f"命中列级策略 {hit.subject_type}={hit.subject_id}"
                    f"（{hit.action}{'/' + hit.mask if hit.mask and hit.mask != 'none' else ''}）"
                ),
            )
            res.rules.append(_rule_brief(hit, rule.reason))
        elif LEVEL_RANK.get(level, 0) >= LEVEL_RANK[FALLBACK_MASK_LEVEL]:
            rule = ColumnRule(
                column=cm.name,
                action="allow",
                mask="mask",
                mask_param={"keep": 0},
                sensitive_level=level,
                comment=cm.comment or "",
                policy_id=None,
                reason=f"敏感分级兜底：{level} 列无显式授权，默认掩码",
            )
            res.rules.append(
                {
                    "policyId": None,
                    "subjectType": "classification",
                    "subjectId": level,
                    "resourceType": "column",
                    "resourceId": resource_key(ds_id, tbl, cm.name),
                    "action": "mask",
                    "mask": "mask",
                    "reason": rule.reason,
                }
            )
        else:
            rule = ColumnRule(
                column=cm.name,
                sensitive_level=level,
                comment=cm.comment or "",
                reason="默认可见",
            )

        if rule.visible:
            res.columns[cm.name] = rule
        else:
            res.denied_columns[cm.name] = rule

    return res


def resolve(
    db: Session | User | None = None,
    user: User | str | None = None,
    datasource_id: str | None = None,
    table: str | None = None,
    column: str | None = None,
    **kwargs,
) -> TableResolution:
    """求某用户对 `datasource:table`（可选某一列）的有效权限。

    兼容两种写法：
        resolve(db, user, datasource_id, table, column=None)   # 本仓库内部用法
        resolve(user, datasource_id, table, column=None)       # 契约 §5.3 写法
    第二种会临时开一个 Session，解析过程是 eager 的，返回前即关闭。
    """
    temp: Session | None = None
    if db is not None and not isinstance(db, Session) and isinstance(db, User):
        from ..core.db import SessionLocal

        temp = SessionLocal()
        db, user, datasource_id, table, column = temp, db, user, datasource_id, table  # type: ignore[assignment]
        kwargs.pop("datasource", None)
        kwargs.pop("table_name", None)
    try:
        return _resolve_impl(
            db=db, user=user, datasource_id=datasource_id, table=table, column=column, **kwargs
        )
    finally:
        if temp is not None:
            temp.close()


def resolve_column(db: Session, user: User, datasource_id: str, table: str, column: str) -> ColumnRule | None:
    """便捷入口：直接取某一列的有效规则（不存在返回 None）。"""
    return resolve(db, user, datasource_id, table, column).column_rule(column)



def resolve_all(
    db: Session,
    user: User,
    datasource_id: str,
    *,
    tables: list[str] | None = None,
) -> list[TableResolution]:
    """对数据源下所有（或指定）表求值。一次载入策略，避免 N 次查询。"""
    plist = load_policies(db, user)
    if tables is None:
        tables = [
            t.name
            for t in db.scalars(
                select(TableMeta)
                .where(TableMeta.datasource_id == datasource_id)
                .order_by(TableMeta.name)
            ).all()
        ]
    out: list[TableResolution] = []
    for tbl in tables:
        out.append(resolve(db, user, datasource_id, tbl, policies=plist))
    return out


def authorized_tables(db: Session, user: User, datasource_id: str) -> list[str]:
    return [r.table for r in resolve_all(db, user, datasource_id) if r.allowed]


def effective_matrix(db: Session, user: User, datasource_id: str | None = None) -> dict:
    """生成"用户 × 表 × 列 × 行 × 脱敏"的生效矩阵（供 /api/policies/effective 使用）。"""
    if datasource_id is None:
        ds_row = db.scalar(select(DataSource).order_by(DataSource.created_at))
        datasource_id = ds_row.id if ds_row else ""
    ds = db.get(DataSource, datasource_id) if datasource_id else None
    resolutions = resolve_all(db, user, datasource_id) if datasource_id else []
    tables = []
    for res in resolutions:
        tables.append(
            {
                "table": res.table,
                "comment": res.table_comment,
                "rowCount": res.row_count,
                "allowed": res.allowed,
                "deniedReason": res.denied_reason,
                "rowFilters": res.row_filters,
                "columns": [r.to_dict() for r in res.columns.values()],
                "deniedColumns": [r.to_dict() for r in res.denied_columns.values()],
                "rules": res.rules,
            }
        )
    return {
        "userId": user.id,
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "dept": user.dept,
        "datasourceId": datasource_id,
        "datasourceName": ds.name if ds else "",
        "tables": tables,
        "summary": {
            "tablesVisible": sum(1 for t in tables if t["allowed"]),
            "tablesDenied": sum(1 for t in tables if not t["allowed"]),
            "columnsMasked": sum(
                1 for t in tables for c in t["columns"] if c.get("masked")
            ),
            "columnsDenied": sum(len(t["deniedColumns"]) for t in tables),
            "rowFiltered": sum(1 for t in tables if t["rowFilters"]),
            "rowFilterTables": [t["table"] for t in tables if t["rowFilters"]],
        },
    }


def data_scope_summary(db: Session, user: User, datasource_id: str) -> str:
    """给 Agent System Prompt 用的一句话数据权限摘要。"""
    try:
        resolutions = resolve_all(db, user, datasource_id)
    except Exception:
        return ""
    allowed = [r for r in resolutions if r.allowed]
    if not allowed:
        return "当前用户在 demo 数据源上无任何可见表。"
    parts = []
    for res in allowed:
        bits = [f"{res.table}(可读 {len(res.visible_columns)} 列"]
        if res.masked_columns:
            bits.append(f"脱敏：{'/'.join(res.masked_columns)}")
        if res.row_filters:
            bits.append(f"行级：{' AND '.join(res.row_filters)}")
        parts.append("，".join(bits) + ")")
    denied = [r.table for r in resolutions if not r.allowed]
    text = "可见表：" + "；".join(parts) + "。"
    if denied:
        text += "不可见表：" + "、".join(denied) + "。"
    return text
