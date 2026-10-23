"""数据权限 API（契约 §8.9）：策略 CRUD / 生效矩阵 / SQL 预览 / 敏感分级统计。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import audit, ensure, get_current_user, is_admin
from ..models import ColumnMeta, DataSource, Policy, TableMeta, User
from ..services import datasource_service, policy_service, sqlguard

router = APIRouter(tags=["policies"])

ACTION_VALUES = ("allow", "deny")
MASK_VALUES = ("none", "mask", "hash", "replace", "truncate")
RESOURCE_VALUES = ("datasource", "table", "column", "metric", "row")
SUBJECT_VALUES = ("user", "role")


def _policy_dict(p: Policy, db: Session | None = None) -> dict:
    out = {
        "id": p.id,
        "subjectType": p.subject_type,
        "subjectId": p.subject_id,
        "resourceType": p.resource_type,
        "resourceId": p.resource_id,
        "action": p.action,
        "mask": p.mask or "none",
        "maskParam": dict(p.mask_param or {}),
        "rowFilter": p.row_filter or "",
        "priority": int(p.priority or 0),
        "enabled": bool(p.enabled),
        "note": p.note or "",
        "createdAt": p.created_at.isoformat() + "Z" if p.created_at else None,
        "updatedAt": p.updated_at.isoformat() + "Z" if p.updated_at else None,
    }
    if db is not None:
        subject = db.get(User, p.subject_id) if p.subject_type == "user" else None
        out["subjectName"] = (
            (subject.name or subject.username) if subject
            else ("角色：" + p.subject_id if p.subject_type == "role" else p.subject_id)
        )
        if p.resource_type == "column" and "." in (p.resource_id or ""):
            head, column = p.resource_id.rsplit(".", 1)
            table = head.split(":", 1)[-1]
            out["table"] = table
            out["column"] = column
        elif p.resource_type in ("table", "row"):
            out["table"] = (p.resource_id or "").split(":", 1)[-1]
        meta = None
        if out.get("table"):
            meta = db.scalar(
                select(TableMeta).where(TableMeta.datasource_id == "ds_demo", TableMeta.name == out["table"])
            )
        out["tableComment"] = meta.comment if meta else ""
    return out


def _admin_guard(user: User, action: str = "修改") -> None:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": f"只有管理员可以{action}数据权限策略"})


@router.get("/policies")
def list_policies(
    subjectType: str | None = Query(default=None),
    subjectId: str | None = Query(default=None),
    resourceType: str | None = Query(default=None),
    action: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Policy)
    if not is_admin(user):
        # 成员只能看到与自己相关（本人 + 所属角色）的策略
        stmt = stmt.where(
            ((Policy.subject_type == "user") & (Policy.subject_id == user.id))
            | ((Policy.subject_type == "role") & (Policy.subject_id == user.role))
        )
    if subjectType:
        ensure(subjectType in SUBJECT_VALUES, "SUBJECT_TYPE_INVALID", "subjectType 仅支持 user / role")
        stmt = stmt.where(Policy.subject_type == subjectType)
    if subjectId:
        stmt = stmt.where(Policy.subject_id == subjectId)
    if resourceType:
        ensure(resourceType in RESOURCE_VALUES, "RESOURCE_TYPE_INVALID", "resourceType 不合法")
        stmt = stmt.where(Policy.resource_type == resourceType)
    if action:
        ensure(action in ACTION_VALUES, "ACTION_INVALID", "action 仅支持 allow / deny")
        stmt = stmt.where(Policy.action == action)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(Policy.resource_id.like(like) | Policy.note.like(like))

    stmt = stmt.order_by(Policy.subject_type, Policy.subject_id, Policy.priority.desc(), Policy.created_at)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
    items = [_policy_dict(p, db) for p in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "scope": "all" if is_admin(user) else "self",
    }


def _apply_payload(p: Policy, payload: dict) -> None:
    if "subjectType" in payload and payload["subjectType"]:
        ensure(payload["subjectType"] in SUBJECT_VALUES, "SUBJECT_TYPE_INVALID", "subjectType 仅支持 user / role")
        p.subject_type = payload["subjectType"]
    if "subjectId" in payload and payload["subjectId"]:
        p.subject_id = str(payload["subjectId"])[:40]
    if "resourceType" in payload and payload["resourceType"]:
        ensure(payload["resourceType"] in RESOURCE_VALUES, "RESOURCE_TYPE_INVALID",
               "resourceType 仅支持 datasource/table/column/metric/row")
        p.resource_type = payload["resourceType"]
    if "resourceId" in payload and payload["resourceId"]:
        p.resource_id = str(payload["resourceId"])[:200]
    if "action" in payload and payload["action"]:
        ensure(payload["action"] in ACTION_VALUES, "ACTION_INVALID", "action 仅支持 allow / deny")
        p.action = payload["action"]
    if "mask" in payload and payload["mask"] is not None:
        ensure(payload["mask"] in MASK_VALUES, "MASK_INVALID",
               "mask 仅支持 none/mask/hash/replace/truncate")
        p.mask = payload["mask"]
    if "maskParam" in payload and isinstance(payload["maskParam"], dict):
        p.mask_param = payload["maskParam"]
    if "rowFilter" in payload:
        p.row_filter = str(payload["rowFilter"] or "")[:500]
    if "priority" in payload and payload["priority"] is not None:
        p.priority = int(payload["priority"])
    if "enabled" in payload and payload["enabled"] is not None:
        p.enabled = bool(payload["enabled"])
    if "note" in payload and payload["note"] is not None:
        p.note = str(payload["note"])[:200]


@router.post("/policies")
def upsert_policy(
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _admin_guard(user, "新建")
    policy_id = str(payload.get("id") or "").strip()
    if policy_id:
        p = db.get(Policy, policy_id)
        ensure(p is not None, "POLICY_NOT_FOUND", "策略不存在", 404)
        before = _policy_dict(p, db)
        _apply_payload(p, payload)
        db.flush()
        audit(db, actor=user, action="policy_change", target_type="policy", target_id=p.id,
              target_name=p.resource_id, detail={"before": before, "after": _policy_dict(p, db)},
              risk="medium", request=request, commit=False)
        db.commit()
        db.refresh(p)
        return _policy_dict(p, db)

    ensure(bool(payload.get("subjectId")), "SUBJECT_REQUIRED", "subjectId 不能为空")
    ensure(bool(payload.get("resourceId")), "RESOURCE_REQUIRED", "resourceId 不能为空（如 ds_demo:worktime_fact）")
    p = Policy(
        subject_type=str(payload.get("subjectType") or "user"),
        subject_id=str(payload["subjectId"])[:40],
        resource_type=str(payload.get("resourceType") or "table"),
        resource_id=str(payload["resourceId"])[:200],
        action=str(payload.get("action") or "allow"),
        mask=str(payload.get("mask") or "none"),
        mask_param=dict(payload.get("maskParam") or {}),
        row_filter=str(payload.get("rowFilter") or "")[:500],
        priority=int(payload.get("priority") or 100),
        enabled=bool(payload.get("enabled", True)),
        note=str(payload.get("note") or "")[:200],
    )
    _apply_payload(p, payload)
    db.add(p)
    db.flush()
    audit(db, actor=user, action="policy_change", target_type="policy", target_id=p.id,
          target_name=p.resource_id, detail={"created": True, "after": _policy_dict(p, db)},
          risk="medium", request=request, commit=False)
    db.commit()
    db.refresh(p)
    return _policy_dict(p, db)


@router.put("/policies/{policy_id}")
def update_policy(
    policy_id: str,
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _admin_guard(user, "更新")
    p = db.get(Policy, policy_id)
    ensure(p is not None, "POLICY_NOT_FOUND", "策略不存在", 404)
    before = _policy_dict(p, db)
    _apply_payload(p, payload)
    db.flush()
    audit(db, actor=user, action="policy_change", target_type="policy", target_id=p.id,
          target_name=p.resource_id, detail={"before": before, "after": _policy_dict(p, db)},
          risk="medium", request=request, commit=False)
    db.commit()
    db.refresh(p)
    return _policy_dict(p, db)


@router.delete("/policies/{policy_id}")
def delete_policy(
    policy_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _admin_guard(user, "删除")
    p = db.get(Policy, policy_id)
    ensure(p is not None, "POLICY_NOT_FOUND", "策略不存在", 404)
    snapshot = _policy_dict(p, db)
    db.delete(p)
    audit(db, actor=user, action="policy_change", target_type="policy", target_id=policy_id,
          target_name=snapshot["resourceId"], detail={"deleted": True, "before": snapshot},
          risk="medium", request=request, commit=False)
    db.commit()
    return {"deleted": True, "id": policy_id}


@router.get("/policies/effective")
def effective_policies(
    userId: str | None = Query(default=None),
    datasourceId: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    target_id = userId or user.id
    if target_id != user.id and not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只能查看自己的生效权限"})
    target = db.get(User, target_id)
    ensure(target is not None, "USER_NOT_FOUND", "用户不存在", 404)
    if datasourceId:
        ensure(db.get(DataSource, datasourceId) is not None, "DATASOURCE_NOT_FOUND", "数据源不存在", 404)
    matrix = policy_service.effective_matrix(db, target, datasourceId)
    matrix["dataScopeSummary"] = policy_service.data_scope_summary(
        db, target, matrix["datasourceId"]
    ) if matrix["datasourceId"] else ""
    return matrix


@router.post("/policies/preview")
def preview_sql(
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    sql = str(payload.get("sql") or "").strip()
    ensure(bool(sql), "SQL_REQUIRED", "请输入待预览的 SQL")
    ensure(len(sql) <= 8000, "SQL_TOO_LONG", "SQL 过长（上限 8000 字符）")
    target_id = payload.get("userId") or user.id
    if target_id != user.id and not is_admin(user):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "只能预览自己的数据权限"})
    target = db.get(User, str(target_id))
    ensure(target is not None, "USER_NOT_FOUND", "用户不存在", 404)

    ds = datasource_service.get(db, payload.get("datasourceId"))
    ensure(ds is not None, "DATASOURCE_NOT_FOUND", "数据源不存在（请先确认已 seed demo 数据源）", 404)
    path = datasource_service.resolve_path(ds)
    ensure(path.exists(), "DATASOURCE_FILE_MISSING", f"数据源文件不存在：{path}", 404)

    ctx = sqlguard.GuardContext(
        db=db, user=target, datasource_id=ds.id, datasource_path=str(path),
        audit_actor=user, datasource_name=ds.name,
    )
    limit = int(payload.get("limit") or 20)
    limit = max(1, min(limit, 200))
    result = sqlguard.guard_and_run(sql, ctx, limit=limit)
    return {
        "ok": result.ok,
        "originalSql": result.original_sql,
        "rewrittenSql": result.sql,
        "columns": result.columns,
        "rows": result.rows,
        "rowCount": result.row_count,
        "maskedColumns": result.masked_columns,
        "appliedRules": result.applied_rules,
        "deniedReason": result.denied_reason,
        "error": result.error,
        "durationMs": result.duration_ms,
        "limit": result.limit,
        "datasourceId": ds.id,
        "datasourceName": ds.name,
        "userId": target.id,
        "userName": target.name,
    }


@router.get("/classifications")
def classifications(
    datasourceId: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    ds = datasource_service.get(db, datasourceId)
    ensure(ds is not None, "DATASOURCE_NOT_FOUND", "数据源不存在", 404)
    rows = db.scalars(
        select(ColumnMeta).where(ColumnMeta.datasource_id == ds.id)
    ).all()
    table_meta = {
        t.name: t.comment
        for t in db.scalars(select(TableMeta).where(TableMeta.datasource_id == ds.id)).all()
    }
    buckets: dict[str, dict] = {}
    totals = {lvl: 0 for lvl in policy_service.SENSITIVE_LEVELS}
    for cm in rows:
        level = cm.sensitive_level or "public"
        totals[level] = totals.get(level, 0) + 1
        item = buckets.setdefault(
            cm.table_name,
            {
                "table": cm.table_name,
                "comment": table_meta.get(cm.table_name, ""),
                "public": 0, "internal": 0, "secret": 0, "top_secret": 0,
                "total": 0,
                "sensitiveColumns": [],
            },
        )
        item[level] = item.get(level, 0) + 1
        item["total"] += 1
        if level in ("secret", "top_secret"):
            item["sensitiveColumns"].append({"name": cm.name, "level": level, "comment": cm.comment or ""})
    items = sorted(buckets.values(), key=lambda x: (-(x["secret"] + x["top_secret"]), x["table"]))
    return {
        "items": items,
        "total": len(items),
        "totals": totals,
        "datasourceId": ds.id,
        "datasourceName": ds.name,
        "levels": [
            {"level": "public", "label": "公开", "count": totals.get("public", 0)},
            {"level": "internal", "label": "内部", "count": totals.get("internal", 0)},
            {"level": "secret", "label": "机密", "count": totals.get("secret", 0)},
            {"level": "top_secret", "label": "绝密", "count": totals.get("top_secret", 0)},
        ],
    }
