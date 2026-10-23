"""数据源服务：路径解析、连通性测试、表/字段元数据（按权限过滤）。"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import DATA_DIR, REPO
from ..models import ColumnMeta, DataSource, TableMeta, User
from . import policy_service

SUPPORTED_TYPES = ("sqlite", "mysql", "pg", "hive", "excel", "bi")


def resolve_path(ds: DataSource) -> Path:
    """把 config.path 解析成绝对路径（兼容相对仓库根 / 相对 data 目录 / 绝对路径）。"""
    cfg: dict = ds.config or {}
    raw = str(cfg.get("path") or "").strip()
    if not raw:
        raw = ds.database or ""
    if not raw:
        return Path("")
    p = Path(raw)
    if p.is_absolute():
        return p
    # 相对路径依次尝试：
    #   1) 数据目录下的同名文件（DATACLAW_DATA_DIR，seed 实际落盘位置）
    #   2) 仓库根 / 仓库 data 目录（config 里写 data/demo.db 的常规情况）
    #   3) 数据目录 / backend 根（兜底）
    name = Path(raw).name
    candidates = [
        DATA_DIR / name,
        REPO / raw,
        REPO / "data" / name,
        DATA_DIR / raw,
        REPO / "backend" / raw,
    ]
    for cand in candidates:
        if cand.exists():
            return cand.resolve()
    return (DATA_DIR / name).resolve()


def demo_datasource(db: Session) -> DataSource | None:
    # SQLite JSON 查询在跨版本上有差异，直接按创建顺序取第一条（seed 只会建一条 demo）
    return db.scalar(select(DataSource).order_by(DataSource.created_at))


def get(db: Session, datasource_id: str | None = None) -> DataSource | None:
    if datasource_id:
        ds = db.get(DataSource, datasource_id)
        if ds:
            return ds
    return db.scalar(select(DataSource).order_by(DataSource.created_at))


def _table_count(db: Session, ds_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(TableMeta).where(TableMeta.datasource_id == ds_id)) or 0)


def to_dict(ds: DataSource, db: Session | None = None) -> dict:
    cfg = dict(ds.config or {})
    out = {
        "id": ds.id,
        "name": ds.name,
        "type": ds.type,
        "host": ds.host or "",
        "port": ds.port,
        "database": ds.database or "",
        "username": ds.username or "",
        "status": ds.status,
        "ownerId": ds.owner_id,
        "description": ds.description or "",
        "config": cfg,
        "path": str(resolve_path(ds)),
        "createdAt": ds.created_at.isoformat() + "Z" if ds.created_at else None,
        "updatedAt": ds.updated_at.isoformat() + "Z" if ds.updated_at else None,
    }
    if db is not None:
        out["tableCount"] = _table_count(db, ds.id)
        out["rowCount"] = int(
            db.scalar(select(func.coalesce(func.sum(TableMeta.row_count), 0)).where(TableMeta.datasource_id == ds.id)) or 0
        )
        out["columnCount"] = int(
            db.scalar(select(func.count()).select_from(ColumnMeta).where(ColumnMeta.datasource_id == ds.id)) or 0
        )
        out["sensitiveColumnCount"] = int(
            db.scalar(
                select(func.count())
                .select_from(ColumnMeta)
                .where(
                    ColumnMeta.datasource_id == ds.id,
                    ColumnMeta.sensitive_level.in_(("secret", "top_secret")),
                )
            ) or 0
        )
    return out


def list_datasources(db: Session, user: User) -> dict:
    rows = db.scalars(select(DataSource).order_by(DataSource.created_at)).all()
    items = []
    for ds in rows:
        item = to_dict(ds, db)
        # 表可见数（按当前用户权限）
        try:
            visible = [t for t in policy_service.resolve_all(db, user, ds.id) if t.allowed]
            item["visibleTableCount"] = len(visible)
        except Exception:
            item["visibleTableCount"] = 0
        items.append(item)
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------- 表 / 字段


def visible_tables(db: Session, user: User, ds: DataSource) -> dict:
    """只返回当前用户有权限的表；同时给出列数与敏感列数。"""
    metas = db.scalars(
        select(TableMeta).where(TableMeta.datasource_id == ds.id).order_by(TableMeta.name)
    ).all()
    resolutions = {r.table: r for r in policy_service.resolve_all(db, user, ds.id)}
    items: list[dict] = []
    denied = 0
    for meta in metas:
        res = resolutions.get(meta.name)
        if res is None or not res.allowed:
            denied += 1
            continue
        items.append(
            {
                "name": meta.name,
                "comment": meta.comment or "",
                "rowCount": int(meta.row_count or 0),
                "columnCount": len(res.columns),
                "visibleColumnCount": len(res.visible_columns),
                "maskedColumnCount": len(res.masked_columns),
                "deniedColumnCount": len(res.denied_columns),
                "sensitiveColumns": [
                    c for c, rule in res.columns.items()
                    if rule.sensitive_level in ("secret", "top_secret")
                ],
                "rowFilters": res.row_filters,
                "allowed": True,
            }
        )
    return {
        "items": items,
        "total": len(items),
        "datasourceId": ds.id,
        "deniedColumnCount": 0,
        "hiddenTableCount": denied,
    }


def columns_of(db: Session, user: User, ds: DataSource, table: str) -> dict:
    """字段元数据（含敏感级别与当前用户的有效动作/脱敏方式）。"""
    res = policy_service.resolve(db, user, ds.id, table)
    if not res.allowed:
        raise PermissionError(res.denied_reason or f"无权访问表 {table}")
    metas = db.scalars(
        select(ColumnMeta)
        .where(ColumnMeta.datasource_id == ds.id, ColumnMeta.table_name == table)
        .order_by(ColumnMeta.name)
    ).all()
    items: list[dict] = []
    for cm in metas:
        rule = res.column_rule(cm.name)
        items.append(
            {
                "name": cm.name,
                "type": cm.type,
                "comment": cm.comment or "",
                "sensitiveLevel": cm.sensitive_level or "public",
                "category": cm.category or "",
                "action": (rule.action if rule else "allow"),
                "mask": (rule.mask if rule else "none"),
                "maskParam": dict(rule.mask_param or {}) if rule else {},
                "visible": bool(rule.visible) if rule else True,
                "reason": rule.reason if rule else "默认可见",
            }
        )
    return {
        "items": items,
        "total": len(items),
        "table": table,
        "datasourceId": ds.id,
        "rowFilters": res.row_filters,
        "allowed": True,
    }


# ---------------------------------------------------------------- 连通性


def test_connection(db: Session, ds: DataSource) -> dict:
    started = time.perf_counter()
    result: dict[str, Any] = {
        "datasourceId": ds.id,
        "type": ds.type,
        "ok": False,
        "latencyMs": 0,
        "message": "",
    }
    try:
        if ds.type == "sqlite":
            path = resolve_path(ds)
            if not str(path) or not path.exists():
                result["message"] = f"SQLite 文件不存在：{path}"
            else:
                conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
                try:
                    row = conn.execute("select 1").fetchone()
                    tables = conn.execute(
                        "select count(*) from sqlite_master where type='table'"
                    ).fetchone()[0]
                finally:
                    conn.close()
                result.update(
                    ok=bool(row and row[0] == 1),
                    message=f"连接成功，共 {tables} 张表",
                    tableCount=int(tables),
                    path=str(path),
                )
        elif ds.type in ("mysql", "pg", "hive"):
            result["message"] = (
                f"V1 仅演示 sqlite：{ds.type} 驱动未随原型内置，"
                "请在 requirements 中安装对应驱动后启用（连接串已保存）"
            )
            result["retryable"] = False
        else:
            result["message"] = f"暂不支持的数据源类型：{ds.type}"
    except Exception as exc:
        result["message"] = f"连接失败：{exc}"
        result["retryable"] = True

    result["latencyMs"] = int((time.perf_counter() - started) * 1000)
    ds.status = "connected" if result["ok"] else "error"
    db.commit()
    return result


# ---------------------------------------------------------------- 创建


def create(db: Session, payload: dict, user: User) -> DataSource:
    ds_type = str(payload.get("type") or "sqlite").lower()
    if ds_type not in SUPPORTED_TYPES:
        raise ValueError(f"不支持的数据源类型：{ds_type}（可选：{'/'.join(SUPPORTED_TYPES)}）")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("数据源名称不能为空")
    config = dict(payload.get("config") or {})
    if ds_type == "sqlite":
        path = str(config.get("path") or payload.get("database") or "").strip()
        if not path:
            raise ValueError("SQLite 数据源必须提供文件路径（config.path）")
        if not Path(path).is_absolute():
            config["path"] = path.replace("\\", "/")
        else:
            config["path"] = path
    ds = DataSource(
        name=name,
        type=ds_type,
        host=str(payload.get("host") or ""),
        port=int(payload["port"]) if payload.get("port") else None,
        database=str(payload.get("database") or ""),
        username=str(payload.get("username") or ""),
        config=config,
        status="connected" if ds_type == "sqlite" else "error",
        owner_id=user.id,
        description=str(payload.get("description") or ""),
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


__all__ = [
    "resolve_path", "demo_datasource", "get", "to_dict", "list_datasources",
    "visible_tables", "columns_of", "test_connection", "create", "SUPPORTED_TYPES",
]
