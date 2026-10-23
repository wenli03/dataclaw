"""公共员工分配与版本同步：生成/复用用户侧员工副本，并保持版本一致。"""
from __future__ import annotations

from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .skill_service import resolve_skill_ids
from ..models import (
    Assignment,
    Employee,
    EmployeeSkill,
    Memory,
    Message,
    PublicAgent,
    SessionModel,
    User,
    iso,
)


def agent_employee(db: Session, agent_id: str, user_id: str) -> Employee | None:
    """某用户当前生效的公共员工副本（未归档）。"""
    return db.scalar(
        select(Employee)
        .where(
            Employee.public_agent_id == agent_id,
            Employee.owner_id == user_id,
            Employee.status != "archived",
        )
        .order_by(Employee.created_at.desc())
    )


def _valid_skill_ids(db: Session, skill_ids: Sequence[str] | None) -> list[str]:
    """把技能引用（id 或机器名）解析成技能 id，忽略已删除的技能。"""
    return resolve_skill_ids(db, skill_ids)


def replace_skills(db: Session, emp: Employee, skill_ids: Sequence[str] | None) -> None:
    """把副本技能整体同步为公共员工的技能集合。"""
    wanted = _valid_skill_ids(db, skill_ids)
    existing = {
        rel.skill_id: rel
        for rel in db.scalars(select(EmployeeSkill).where(EmployeeSkill.employee_id == emp.id))
    }
    for sid, rel in existing.items():
        if sid not in wanted:
            db.delete(rel)
    for sid in wanted:
        if sid in existing:
            existing[sid].enabled = True
        else:
            db.add(EmployeeSkill(employee_id=emp.id, skill_id=sid, enabled=True))
    db.flush()


def _sync_fields(emp: Employee, agent: PublicAgent) -> None:
    """同步源版本内容到副本；名字属于用户自定义，不覆盖。"""
    emp.avatar = agent.avatar or emp.avatar
    emp.role_title = agent.role_title or ""
    emp.soul_md = agent.soul_md or ""
    emp.status = "active"


def assign_users(db: Session, agent: PublicAgent, users: Sequence[User]) -> dict:
    """为一批用户创建/复用员工副本（幂等：已有副本记入 skipped）。"""
    created: list[dict] = []
    skipped: list[dict] = []
    for user in users:
        if user.status != "active":
            skipped.append(
                {
                    "userId": user.id,
                    "userName": user.name or user.username,
                    "username": user.username,
                    "employeeId": None,
                    "reason": "user_disabled",
                }
            )
            continue
        emp = agent_employee(db, agent.id, user.id)
        if emp is not None:
            skipped.append(
                {
                    "userId": user.id,
                    "userName": user.name or user.username,
                    "username": user.username,
                    "employeeId": emp.id,
                    "reason": "already_assigned",
                }
            )
            continue
        # 复用历史上同源但已归档的副本，避免同一用户出现多份同名员工
        emp = db.scalar(
            select(Employee)
            .where(Employee.public_agent_id == agent.id, Employee.owner_id == user.id)
            .order_by(Employee.created_at.desc())
        )
        if emp is None:
            emp = Employee(
                owner_id=user.id,
                name=agent.name,
                avatar=agent.avatar or "avatar-01",
                role_title=agent.role_title or "",
                soul_md=agent.soul_md or "",
                greeting="",
                source="from_public",
                public_agent_id=agent.id,
                memory_enabled=True,
                status="active",
                stats_json={"assignedFrom": agent.id, "assignedVersion": int(agent.version or 1)},
            )
            db.add(emp)
            db.flush()
        else:
            _sync_fields(emp, agent)
            emp.stats_json = {
                **(emp.stats_json or {}),
                "assignedFrom": agent.id,
                "assignedVersion": int(agent.version or 1),
            }
        replace_skills(db, emp, agent.default_skills)
        record = db.scalar(
            select(Assignment).where(
                Assignment.public_agent_id == agent.id, Assignment.user_id == user.id
            )
        )
        if record is None:
            db.add(Assignment(public_agent_id=agent.id, user_id=user.id, employee_id=emp.id))
        else:
            record.employee_id = emp.id
        created.append(
            {
                "userId": user.id,
                "userName": user.name or user.username,
                "username": user.username,
                "employeeId": emp.id,
            }
        )
    db.flush()
    return {"created": created, "skipped": skipped}


def sync_assignments(db: Session, agent: PublicAgent) -> list[str]:
    """发布时把源版本字段同步到全部已分配副本，返回被同步的员工 id。"""
    emps = list(
        db.scalars(
            select(Employee).where(
                Employee.public_agent_id == agent.id, Employee.status != "archived"
            )
        )
    )
    for emp in emps:
        _sync_fields(emp, agent)
        replace_skills(db, emp, agent.default_skills)
        emp.stats_json = {
            **(emp.stats_json or {}),
            "assignedFrom": agent.id,
            "assignedVersion": int(agent.version or 1),
        }
    db.flush()
    return [e.id for e in emps]


def list_assignments(db: Session, agent: PublicAgent) -> list[dict]:
    """分配明细（含用户名与副本 id）。"""
    rows = db.execute(
        select(Assignment, User)
        .join(User, Assignment.user_id == User.id)
        .where(Assignment.public_agent_id == agent.id)
        .order_by(Assignment.created_at.asc())
    ).all()
    out: list[dict] = []
    for record, user in rows:
        emp_id = record.employee_id
        if not emp_id:
            emp = agent_employee(db, agent.id, user.id)
            emp_id = emp.id if emp else None
        out.append(
            {
                "userId": user.id,
                "userName": user.name or user.username,
                "username": user.username,
                "dept": user.dept or "",
                "employeeId": emp_id,
                "createdAt": iso(record.created_at),
            }
        )
    return out


def remove_assignment(db: Session, agent: PublicAgent, user_id: str) -> dict:
    """取消分配：删除副本（含技能/记忆/会话）与分配记录。

    显式按外键顺序批量删除，避免 SQLAlchemy 无 relationship 时的删除顺序歧义。
    """
    record = db.scalar(
        select(Assignment).where(
            Assignment.public_agent_id == agent.id, Assignment.user_id == user_id
        )
    )
    emp = agent_employee(db, agent.id, user_id)
    if emp is None and record is not None and record.employee_id:
        candidate = db.get(Employee, record.employee_id)
        emp = candidate if candidate is not None else None
    removed_employee = None
    if emp is not None:
        session_ids = list(
            db.scalars(select(SessionModel.id).where(SessionModel.employee_id == emp.id))
        )
        if session_ids:
            db.execute(delete(Message).where(Message.session_id.in_(session_ids)))
            db.execute(delete(SessionModel).where(SessionModel.employee_id == emp.id))
        db.execute(delete(EmployeeSkill).where(EmployeeSkill.employee_id == emp.id))
        db.execute(delete(Memory).where(Memory.employee_id == emp.id))
        db.execute(delete(Assignment).where(Assignment.employee_id == emp.id))
        db.execute(delete(Employee).where(Employee.id == emp.id))
        removed_employee = emp.id
    elif record is not None:
        db.execute(delete(Assignment).where(Assignment.id == record.id))
    db.flush()
    return {
        "userId": user_id,
        "employeeId": removed_employee,
        "removed": removed_employee is not None or record is not None,
    }


def agent_visible(db: Session, user: User, agent: PublicAgent) -> bool:
    """可见性：平台管理员全部；部门管理员仅本部门创建（created_by 所属部门）。"""
    if user.role == "platform_admin":
        return True
    if agent.created_by == user.id:
        return True
    if not agent.created_by:
        return False
    creator = db.get(User, agent.created_by)
    return bool(creator and user.dept and creator.dept == user.dept)
