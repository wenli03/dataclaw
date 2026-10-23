"""指标 API：`GET /api/metrics`（含当前用户是否有权取数）。"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import get_current_user
from ..models import DataSource, Metric, TableMeta, User
from ..services import datasource_service, policy_service

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def list_metrics(
    datasourceId: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ds = datasource_service.get(db, datasourceId)
    stmt = select(Metric)
    if ds is not None:
        stmt = stmt.where((Metric.datasource_id == ds.id) | (Metric.datasource_id.is_(None)))
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(Metric.name.like(like) | Metric.code.like(like) | Metric.description.like(like))
    rows = db.scalars(stmt.order_by(Metric.created_at)).all()

    table_names = [
        t.name
        for t in db.scalars(select(TableMeta).where(TableMeta.datasource_id == (ds.id if ds else "ds_demo"))).all()
    ]
    allowed_tables = set(policy_service.authorized_tables(db, user, ds.id)) if ds else set()

    items = []
    for m in rows:
        referenced = sorted({t for t in table_names if re.search(rf"\b{re.escape(t)}\b", m.expression or "")})
        denied_tables = [t for t in referenced if t not in allowed_tables]
        items.append(
            {
                "id": m.id,
                "name": m.name,
                "code": m.code,
                "description": m.description or "",
                "expression": m.expression or "",
                "datasourceId": m.datasource_id,
                "ownerId": m.owner_id,
                "tables": referenced,
                "allowed": not denied_tables,
                "deniedTables": denied_tables,
                "permissionHint": (
                    "可查询" if not denied_tables
                    else f"缺少表权限：{'、'.join(denied_tables)}"
                ),
                "updatedAt": m.updated_at.isoformat() + "Z" if m.updated_at else None,
            }
        )
    allowed_count = sum(1 for i in items if i["allowed"])
    return {
        "items": items,
        "total": len(items),
        "allowedCount": allowed_count,
        "deniedCount": len(items) - allowed_count,
        "datasourceId": ds.id if ds else None,
        "datasourceName": ds.name if ds else "",
    }
