"""技能领域服务：序列化、安装/绑定校验、SKILL.md 静态安全扫描。"""
from __future__ import annotations

import re
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.deps import is_admin
from ..models import Skill, SkillInstall, User, iso, utcnow

# (正则, 严重级别, 规则说明)。高=可直接执行/下载/提权；中=可疑或有暴露面。
SCAN_RULES: list[tuple[str, str, str]] = [
    (r"\bcurl\b", "high", "外部网络下载（curl）"),
    (r"\bwget\b", "high", "外部网络下载（wget）"),
    (r"rm\s+-rf", "high", "递归强制删除"),
    (r"\beval\s*\(", "high", "动态代码执行（eval）"),
    (r"\bexec\s*\(", "high", "动态代码执行（exec）"),
    (r"\bsubprocess\b", "high", "拉起子进程"),
    (r"os\.system", "high", "拉起系统命令"),
    (r"\bsudo\b", "high", "提权执行"),
    (r"chmod\s+777", "high", "放开文件权限（chmod 777）"),
    (r"__import__", "high", "动态导入模块"),
    (r"pickle\.loads", "high", "反序列化不可信数据"),
    (r"(\.ssh/|id_rsa)", "high", "读取 SSH 私钥"),
    (r"http://", "medium", "明文 HTTP 外发"),
    (r"base64\s+-d", "medium", "base64 解码后执行"),
    (r"(api[_-]?key|secret|token|password)\s*[:=]\s*\S{6,}", "medium", "疑似硬编码凭证"),
    (r"(/bin/(sh|bash)|powershell|cmd\.exe)", "medium", "调用系统 Shell"),
    (r"\bsocket\.", "medium", "原始网络套接字"),
    (r"(os\.remove|shutil\.rmtree)", "medium", "文件删除操作"),
]

_MAX_FINDINGS = 200


def scan_skill_content(content: str) -> dict:
    """真实静态检查：逐行匹配危险模式，返回风险等级与命中明细。"""
    lines = (content or "").splitlines()
    findings: list[dict] = []
    for line_no, line in enumerate(lines, 1):
        for pattern, severity, label in SCAN_RULES:
            match = re.search(pattern, line, re.IGNORECASE)
            if not match:
                continue
            findings.append(
                {
                    "pattern": match.group(0)[:80],
                    "rule": label,
                    "regex": pattern,
                    "line": line_no,
                    "snippet": line.strip()[:160],
                    "severity": severity,
                }
            )
            if len(findings) >= _MAX_FINDINGS:
                break
        if len(findings) >= _MAX_FINDINGS:
            break
    if any(f["severity"] == "high" for f in findings):
        risk = "high"
    elif findings:
        risk = "medium"
    else:
        risk = "low"
    return {
        "riskLevel": risk,
        "findings": findings,
        "scannedAt": iso(utcnow()),
        "lineCount": len(lines),
        "rulesChecked": len(SCAN_RULES),
    }


def parse_frontmatter(content: str) -> dict:
    """解析 SKILL.md 顶部 YAML frontmatter 的少量字段（name/description/risk/tools）。"""
    text = content or ""
    if not text.lstrip().startswith("---"):
        return {}
    body = text.lstrip()
    end = body.find("\n---", 3)
    if end < 0:
        return {}
    block = body[3:end]
    meta: dict = {}
    tools: list[str] = []
    current_list: str | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        item = re.match(r"^\s*-\s+(.+)$", line)
        if item and current_list:
            tools.append(item.group(1).strip().strip("\"'"))
            continue
        kv = re.match(r"^([A-Za-z_]+)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key, value = kv.group(1).lower(), kv.group(2).strip()
        current_list = None
        if key == "tools":
            inner = value.strip("[]")
            tools.extend(p.strip().strip("\"'") for p in inner.split(",") if p.strip())
            current_list = "tools"
        elif key in ("name", "description", "risk"):
            meta[key] = value.strip("\"'")
    if tools:
        meta["tools"] = tools
    return meta


def slugify(display_name: str) -> str:
    """把中文/英文展示名压成 ascii 机器名（无法转换时返回空串）。"""
    text = (display_name or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s_-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:56]


def unique_skill_name(db: Session, display_name: str) -> str:
    """生成唯一技能机器名（基于 displayName 的 slug）。"""
    base = slugify(display_name) or "user-skill"
    if db.scalar(select(Skill.id).where(Skill.name == base)) is None:
        return base
    idx = 2
    while True:
        candidate = f"{base}-{idx}"[:64]
        if db.scalar(select(Skill.id).where(Skill.name == candidate)) is None:
            return candidate
        idx += 1


def skill_ref_lookup(db: Session, refs: Sequence[str] | None) -> dict[str, str]:
    """构建「技能 id / 机器名 → 技能 id」的查找表（只查一次）。"""
    wanted = [r for r in dict.fromkeys(refs or []) if r]
    if not wanted:
        return {}
    rows = db.execute(
        select(Skill.id, Skill.name).where(
            or_(Skill.id.in_(wanted), Skill.name.in_(wanted))
        )
    ).all()
    lookup: dict[str, str] = {}
    for skill_id, name in rows:
        lookup[skill_id] = skill_id
        if name:
            lookup[name] = skill_id
    return lookup


def resolve_skills(db: Session, refs: Sequence[str] | None) -> tuple[list[str], list[str]]:
    """把技能 id 或机器名解析为技能 id，返回 (已解析 id 列表, 无法解析的引用)。"""
    wanted = [r for r in dict.fromkeys(refs or []) if r]
    lookup = skill_ref_lookup(db, wanted)
    resolved: list[str] = []
    missing: list[str] = []
    for ref in wanted:
        skill_id = lookup.get(ref)
        if skill_id is None:
            missing.append(ref)
        elif skill_id not in resolved:
            resolved.append(skill_id)
    return resolved, missing


def resolve_skill_ids(db: Session, refs: Sequence[str] | None) -> list[str]:
    """解析技能引用为技能 id（忽略无法解析的项）。"""
    return resolve_skills(db, refs)[0]


def installed_skill_ids(db: Session, user_id: str) -> set[str]:
    """当前用户已安装的技能 id 集合。"""
    return set(db.scalars(select(SkillInstall.skill_id).where(SkillInstall.user_id == user_id)))


def install_counts(db: Session, user_ids: Sequence[str] | None = None) -> dict[str, int]:
    """技能安装数（可按用户过滤）。"""
    stmt = select(SkillInstall.skill_id, func.count(SkillInstall.id)).group_by(SkillInstall.skill_id)
    if user_ids:
        stmt = stmt.where(SkillInstall.user_id.in_(list(user_ids)))
    return {str(k): int(v) for k, v in db.execute(stmt).all()}


def can_bind_skill(db: Session, user: User, skill: Skill) -> tuple[bool, str]:
    """员工可用技能校验：内置且已审核，或当前用户已安装；管理员放行。"""
    if skill.status == "approved" and skill.source == "builtin":
        return True, ""
    if is_admin(user):
        return True, ""
    hit = db.scalar(
        select(SkillInstall.id).where(
            SkillInstall.user_id == user.id, SkillInstall.skill_id == skill.id
        )
    )
    if hit:
        return True, ""
    return False, f"技能「{skill.display_name}」尚未安装，请先在技能超市安装"


def can_install(db: Session, user: User, skill: Skill) -> tuple[bool, str]:
    """安装校验：已审核技能对所有人开放；未审核技能仅所有者/管理员可装。"""
    if skill.status == "approved":
        return True, ""
    if is_admin(user) or skill.owner_id == user.id:
        return True, ""
    return False, "该技能尚未通过安全审核，暂不可安装"


def skill_item(db: Session, skill: Skill, *, installed: bool, owner_name: str = "") -> dict:
    """技能列表项（契约 §8.5 字段）。"""
    return {
        "id": skill.id,
        "name": skill.name,
        "displayName": skill.display_name,
        "description": skill.description or "",
        "category": skill.category or "",
        "source": skill.source or "builtin",
        "status": skill.status or "approved",
        "version": skill.version or "1.0.0",
        "riskLevel": skill.risk_level or "low",
        "installs": int(skill.installs or 0),
        "icon": skill.icon or "sparkles",
        "tags": list(skill.tags or []),
        "installed": bool(installed),
        "ownerId": skill.owner_id,
        "ownerName": owner_name,
        "updatedAt": iso(skill.updated_at),
        "toolNames": list(skill.tool_names or []),
    }


def owner_names(db: Session, skills: Sequence[Skill]) -> dict[str, str]:
    """批量取技能所有者显示名。"""
    ids = sorted({s.owner_id for s in skills if s.owner_id})
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.name, User.username).where(User.id.in_(ids))).all()
    return {str(uid): (name or username or "") for uid, name, username in rows}


def serialize_skills(db: Session, skills: Sequence[Skill], user: User) -> list[dict]:
    """批量序列化技能列表（自动带 installed 标记与所有者名）。"""
    skills = list(skills)
    if not skills:
        return []
    installed = installed_skill_ids(db, user.id)
    names = owner_names(db, skills)
    return [
        skill_item(
            db,
            s,
            installed=s.id in installed,
            owner_name=names.get(s.owner_id or "", ""),
        )
        for s in skills
    ]


def skill_detail(db: Session, skill: Skill, user: User) -> dict:
    """技能详情：列表项 + SKILL.md 全文 + 扫描结果。"""
    item = skill_item(
        db,
        skill,
        installed=skill.id in installed_skill_ids(db, user.id),
        owner_name=(owner_names(db, [skill]).get(skill.owner_id or "", "")),
    )
    item["content"] = skill.content or ""
    item["scan"] = dict(skill.scan_json or {})
    item["createdAt"] = iso(skill.created_at)
    return item
