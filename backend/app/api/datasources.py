"""数据源 API（契约 §8.9）：列表 / 创建 / 连通性测试 / 表 / 字段。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, ensure, get_current_user, is_admin
from ..models import DataSource, User
from ..services import datasource_service

router = APIRouter(tags=["datasources"])


def _get_or_404(db: Session, datasource_id: str) -> DataSource:
    ds = db.get(DataSource, datasource_id)
    ensure(ds is not None, "DATASOURCE_NOT_FOUND", "数据源不存在", 404)
    return ds


@router.get("/datasources")
def list_datasources(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return datasource_service.list_datasources(db, user)


@router.post("/datasources")
def create_datasource(
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只有管理员可以新建数据源"})
    try:
        ds = datasource_service.create(db, payload, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "DATASOURCE_INVALID", "message": str(exc)}) from exc
    test = datasource_service.test_connection(db, ds)
    audit(
        db, actor=user, action="datasource_create", target_type="datasource", target_id=ds.id,
        target_name=ds.name, detail={"type": ds.type, "test": test}, risk="medium",
        request=request, commit=False,
    )
    db.commit()
    db.refresh(ds)
    out = datasource_service.to_dict(ds, db)
    out["test"] = test
    return out


@router.post("/datasources/{datasource_id}/test")
def test_datasource(
    datasource_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ds = _get_or_404(db, datasource_id)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只有管理员可以测试数据源连通性"})
    result = datasource_service.test_connection(db, ds)
    audit(
        db, actor=user, action="datasource_test", target_type="datasource", target_id=ds.id,
        target_name=ds.name, detail=result, risk="low",
        result="success" if result["ok"] else "error", request=request, commit=False,
    )
    db.commit()
    return result


@router.get("/datasources/{datasource_id}/tables")
def list_tables(
    datasource_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ds = _get_or_404(db, datasource_id)
    return datasource_service.visible_tables(db, user, ds)


@router.get("/datasources/{datasource_id}/tables/{table}/columns")
def list_columns(
    datasource_id: str,
    table: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ds = _get_or_404(db, datasource_id)
    try:
        return datasource_service.columns_of(db, user, ds, table)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "TABLE_FORBIDDEN", "message": str(exc), "table": table},
        ) from exc
