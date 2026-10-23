"""全部 ORM 模型（唯一契约来源，勿在业务模块内另建表）。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text

from .core.db import Base


def utcnow() -> datetime:
    return datetime.utcnow()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(microsecond=0).isoformat() + "Z"


class TimestampMixin:
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class BaseMixin(Base):
    __abstract__ = True
    id = Column(String(40), primary_key=True, default=lambda: new_id("row"))

    def to_dict(self, *, exclude: set[str] | None = None) -> dict:
        exclude = exclude or set()
        out: dict = {}
        for col in self.__table__.columns:
            name = col.name
            if name in exclude:
                continue
            val = getattr(self, name)
            if isinstance(val, datetime):
                val = iso(val)
            out[name] = val
        return out


class User(BaseMixin, TimestampMixin):
    __tablename__ = "users"
    tenant_id = Column(String(40), default="t_default", nullable=False)
    username = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(64), nullable=False, default="")
    email = Column(String(128), default="")
    password_hash = Column(String(200), nullable=False)
    role = Column(String(32), default="member", nullable=False)      # platform_admin|dept_admin|member
    dept = Column(String(64), default="")
    title = Column(String(64), default="")
    avatar = Column(String(64), default="")
    status = Column(String(16), default="active")                   # active|disabled
    memory_enabled = Column(Boolean, default=True)
    last_login_at = Column(DateTime, nullable=True)


class Template(BaseMixin, TimestampMixin):
    __tablename__ = "templates"
    code = Column(String(48), unique=True, nullable=False)
    name = Column(String(64), nullable=False)
    role_title = Column(String(64), default="")
    avatar = Column(String(64), default="")
    description = Column(Text, default="")
    soul_md = Column(Text, default="")
    default_skills = Column(JSON, default=list)                     # [skill.code]
    category = Column(String(32), default="分析")
    sort = Column(Integer, default=0)


class Employee(BaseMixin, TimestampMixin):
    __tablename__ = "employees"
    owner_id = Column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    role_title = Column(String(64), default="")
    avatar = Column(String(64), default="")
    soul_md = Column(Text, default="")
    greeting = Column(String(200), default="")
    template_id = Column(String(40), nullable=True)
    source = Column(String(16), default="personal")                 # personal|from_public
    public_agent_id = Column(String(40), nullable=True, index=True)
    memory_enabled = Column(Boolean, default=True)
    status = Column(String(16), default="active")                   # active|archived
    last_active_at = Column(DateTime, nullable=True)
    stats_json = Column(JSON, default=dict)

    __table_args__ = (Index("ix_employees_owner_status", "owner_id", "status"),)


class EmployeeSkill(BaseMixin):
    __tablename__ = "employee_skills"
    employee_id = Column(String(40), ForeignKey("employees.id"), nullable=False, index=True)
    skill_id = Column(String(40), ForeignKey("skills.id"), nullable=False)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class PublicAgent(BaseMixin, TimestampMixin):
    __tablename__ = "public_agents"
    name = Column(String(64), nullable=False)
    role_title = Column(String(64), default="")
    avatar = Column(String(64), default="")
    description = Column(Text, default="")
    soul_md = Column(Text, default="")
    default_skills = Column(JSON, default=list)
    version = Column(Integer, default=1)
    status = Column(String(16), default="published")                # draft|published|offline
    created_by = Column(String(40), nullable=True)
    published_at = Column(DateTime, nullable=True)
    stats_json = Column(JSON, default=dict)


class Assignment(BaseMixin):
    __tablename__ = "assignments"
    public_agent_id = Column(String(40), ForeignKey("public_agents.id"), nullable=False, index=True)
    user_id = Column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    employee_id = Column(String(40), ForeignKey("employees.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Skill(BaseMixin, TimestampMixin):
    __tablename__ = "skills"
    name = Column(String(64), unique=True, nullable=False)           # 机器名
    display_name = Column(String(64), nullable=False)
    description = Column(Text, default="")
    content = Column(Text, default="")                                # SKILL.md 全文
    category = Column(String(32), default="数据")
    source = Column(String(16), default="builtin")                    # builtin|user
    owner_id = Column(String(40), nullable=True, index=True)
    status = Column(String(16), default="approved")                   # approved|pending|rejected
    version = Column(String(16), default="1.0.0")
    risk_level = Column(String(16), default="low")
    installs = Column(Integer, default=0)
    icon = Column(String(32), default="sparkles")
    tags = Column(JSON, default=list)
    tool_names = Column(JSON, default=list)
    scan_json = Column(JSON, default=dict)


class SkillInstall(BaseMixin):
    __tablename__ = "skill_installs"
    user_id = Column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    skill_id = Column(String(40), ForeignKey("skills.id"), nullable=False)
    employee_id = Column(String(40), nullable=True)
    installed_at = Column(DateTime, default=utcnow)


class SessionModel(BaseMixin, TimestampMixin):
    __tablename__ = "sessions"
    employee_id = Column(String(40), ForeignKey("employees.id"), nullable=False, index=True)
    user_id = Column(String(40), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), default="新会话")
    status = Column(String(16), default="active")
    pinned = Column(Boolean, default=False)
    last_message_at = Column(DateTime, default=utcnow)
    message_count = Column(Integer, default=0)


class Message(BaseMixin):
    __tablename__ = "messages"
    session_id = Column(String(40), ForeignKey("sessions.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False)                        # user|assistant|system
    content = Column(Text, default="")
    steps = Column(JSON, default=list)
    artifacts = Column(JSON, default=list)
    tokens = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)


class ToolCall(BaseMixin):
    __tablename__ = "tool_calls"
    session_id = Column(String(40), nullable=False, index=True)
    message_id = Column(String(40), nullable=True)
    step_id = Column(String(40), default="")
    tool = Column(String(64), default="")
    title = Column(String(200), default="")
    input = Column(JSON, default=dict)
    output = Column(JSON, default=dict)
    status = Column(String(16), default="done")
    risk = Column(String(16), default="low")
    approval = Column(String(16), default="none")
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)


class Artifact(BaseMixin):
    __tablename__ = "artifacts"
    kind = Column(String(16), nullable=False)                        # dashboard|report|docx|html|json
    title = Column(String(200), default="")
    payload = Column(JSON, default=dict)
    text = Column(Text, default="")
    file_path = Column(String(400), default="")
    file_name = Column(String(200), default="")
    session_id = Column(String(40), nullable=True, index=True)
    employee_id = Column(String(40), nullable=True)
    created_by = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class FileModel(BaseMixin):
    __tablename__ = "files"
    name = Column(String(255), default="")
    path = Column(String(400), default="")
    size = Column(Integer, default=0)
    mime = Column(String(120), default="")
    kind = Column(String(24), default="doc")                         # doc|image|audio|email|chat
    uploaded_by = Column(String(40), nullable=True, index=True)
    doc_id = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class DataSource(BaseMixin, TimestampMixin):
    __tablename__ = "datasources"
    name = Column(String(64), nullable=False)
    type = Column(String(16), default="sqlite")                      # sqlite|mysql|pg|hive|excel|bi
    host = Column(String(120), default="")
    port = Column(Integer, nullable=True)
    database = Column(String(120), default="")
    username = Column(String(64), default="")
    config = Column(JSON, default=dict)
    status = Column(String(16), default="connected")
    owner_id = Column(String(40), nullable=True)
    description = Column(Text, default="")


class TableMeta(BaseMixin):
    __tablename__ = "table_meta"
    datasource_id = Column(String(40), ForeignKey("datasources.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    comment = Column(String(200), default="")
    row_count = Column(Integer, default=0)


class ColumnMeta(BaseMixin):
    __tablename__ = "column_meta"
    datasource_id = Column(String(40), ForeignKey("datasources.id"), nullable=False, index=True)
    table_name = Column(String(128), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    type = Column(String(32), default="TEXT")
    comment = Column(String(200), default="")
    sensitive_level = Column(String(16), default="public")           # public|internal|secret|top_secret
    category = Column(String(32), default="")


class Metric(BaseMixin, TimestampMixin):
    __tablename__ = "metrics"
    name = Column(String(64), nullable=False)
    code = Column(String(64), unique=True, nullable=False)
    description = Column(Text, default="")
    expression = Column(Text, default="")
    datasource_id = Column(String(40), nullable=True)
    owner_id = Column(String(40), nullable=True)


class Policy(BaseMixin, TimestampMixin):
    __tablename__ = "policies"
    subject_type = Column(String(16), default="user")                # user|role
    subject_id = Column(String(40), nullable=False, index=True)
    resource_type = Column(String(16), default="table")              # datasource|table|column|metric|row
    resource_id = Column(String(200), default="")                    # table: datasource:table / column: ds:table.col / metric code
    action = Column(String(8), default="allow")                      # allow|deny
    mask = Column(String(16), default="none")                        # none|mask|hash|replace|truncate
    mask_param = Column(JSON, default=dict)
    row_filter = Column(Text, default="")                            # SQL 片段，如 owner_id='u_sales'
    priority = Column(Integer, default=100)
    enabled = Column(Boolean, default=True)
    note = Column(String(200), default="")


class DocAcl(BaseMixin):
    __tablename__ = "doc_acls"
    doc_id = Column(String(40), ForeignKey("knowledge_docs.id"), nullable=False, index=True)
    subject_type = Column(String(16), default="user")
    subject_id = Column(String(40), nullable=False)
    can_read = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)


class KnowledgeDoc(BaseMixin, TimestampMixin):
    __tablename__ = "knowledge_docs"
    name = Column(String(255), nullable=False)
    type = Column(String(16), default="doc")                         # doc|wiki|image|audio|email|chat
    mime = Column(String(120), default="")
    size = Column(Integer, default=0)
    path = Column(String(400), default="")
    text = Column(Text, default="")
    status = Column(String(16), default="ready")
    owner_id = Column(String(40), nullable=True)
    dept = Column(String(64), default="")
    tags = Column(JSON, default=list)
    chunk_count = Column(Integer, default=0)
    sensitive_level = Column(String(16), default="internal")


class KnowledgeChunk(BaseMixin):
    __tablename__ = "knowledge_chunks"
    doc_id = Column(String(40), ForeignKey("knowledge_docs.id"), nullable=False, index=True)
    seq = Column(Integer, default=0)
    text = Column(Text, default="")
    tokens = Column(Integer, default=0)
    meta = Column(JSON, default=dict)


class AuditEvent(BaseMixin):
    __tablename__ = "audit_events"
    ts = Column(DateTime, default=utcnow, index=True)
    actor_id = Column(String(40), nullable=True, index=True)
    actor_name = Column(String(64), default="")
    action = Column(String(32), nullable=False, index=True)
    target_type = Column(String(32), default="")
    target_id = Column(String(64), default="")
    target_name = Column(String(200), default="")
    detail = Column(JSON, default=dict)
    risk = Column(String(8), default="low")
    ip = Column(String(64), default="")
    result = Column(String(16), default="success")                   # success|denied|error
    session_id = Column(String(40), nullable=True)


class Channel(BaseMixin, TimestampMixin):
    __tablename__ = "channels"
    type = Column(String(16), unique=True, nullable=False)           # feishu|wecom|dingtalk|web|api
    name = Column(String(64), default="")
    enabled = Column(Boolean, default=False)
    config = Column(JSON, default=dict)
    status = Column(String(16), default="unconfigured")              # unconfigured|ready|error
    last_checked_at = Column(DateTime, nullable=True)


class Memory(BaseMixin):
    __tablename__ = "memories"
    employee_id = Column(String(40), ForeignKey("employees.id"), nullable=False, index=True)
    kind = Column(String(16), default="fact")                        # fact|preference|playbook
    content = Column(Text, default="")
    source_session_id = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Approval(BaseMixin):
    __tablename__ = "approvals"
    session_id = Column(String(40), nullable=False, index=True)
    message_id = Column(String(40), default="")
    step_id = Column(String(40), default="")
    action = Column(String(64), default="")
    reason = Column(String(300), default="")
    risk = Column(String(8), default="high")
    status = Column(String(16), default="pending")
    decided_by = Column(String(40), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
