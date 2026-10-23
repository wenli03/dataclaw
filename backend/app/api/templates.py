"""角色模板与技能超市的模板读取接口（契约 §8.3）。

模板数据由 seed 写入，本模块只读。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.deps import get_current_user
from ..models import Skill, Template, User, iso

router = APIRouter(tags=["角色模板"])


def template_dict(tpl: Template, skills_by_name: dict[str, Skill]) -> dict:
    """模板对外视图：字段 + 默认技能（code 与解析后的技能摘要）。"""
    codes = [c for c in (tpl.default_skills or []) if c]
    resolved = []
    for code in codes:
        skill = skills_by_name.get(code)
        if skill is None:
            continue
        resolved.append(
            {
                "id": skill.id,
                "name": skill.name,
                "displayName": skill.display_name,
                "icon": skill.icon or "sparkles",
                "category": skill.category or "",
                "riskLevel": skill.risk_level or "low",
            }
        )
    return {
        "id": tpl.id,
        "code": tpl.code,
        "name": tpl.name,
        "roleTitle": tpl.role_title or "",
        "avatar": tpl.avatar or "",
        "description": tpl.description or "",
        "soulMd": tpl.soul_md or "",
        "category": tpl.category or "",
        "sort": int(tpl.sort or 0),
        "defaultSkills": codes,
        "skills": resolved,
        "createdAt": iso(tpl.created_at),
    }


@router.get("/templates")
def list_templates(
    _: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    """角色模板列表（按 sort 升序）。"""
    templates = list(db.scalars(select(Template).order_by(Template.sort.asc(), Template.name.asc())))
    codes = {c for tpl in templates for c in (tpl.default_skills or []) if c}
    skills_by_name: dict[str, Skill] = {}
    if codes:
        skills_by_name = {s.name: s for s in db.scalars(select(Skill).where(Skill.name.in_(codes)))}
    items = [template_dict(tpl, skills_by_name) for tpl in templates]
    return {"items": items, "total": len(items)}
