"""渠道接入服务：配置校验、连通性测试、入站 webhook（免鉴权 + token 校验）。

V1 不建立真实长连接：`test` 做凭证字段校验与格式检查，`events` 走与 Web 端同一条
运行时链路（有 runner 时调用 `run_once`，没有时退化为知识库检索回复），并写
`channel_inbound` 审计。
"""
from __future__ import annotations

import importlib
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import DEMO_MODE
from ..models import AuditEvent, Channel, Employee, Message, SessionModel, User
from . import knowledge_service

#: 各渠道定义：展示名、必填字段（缺一即 400）、凭证字段（展示时打码）
CHANNEL_SPECS: dict[str, dict] = {
    "feishu": {
        "name": "飞书",
        "icon": "feishu",
        "required": [
            ("app_id", "App ID"),
            ("app_secret", "App Secret"),
        ],
        "secrets": ["app_secret", "verification_token", "token"],
        "hint": "飞书开放平台 → 应用凭证；事件订阅需填写 Verification Token 与 Encrypt Key。",
    },
    "wecom": {
        "name": "企业微信",
        "icon": "wecom",
        "required": [
            ("corp_id", "企业 ID（CorpID）"),
            ("agent_id", "应用 AgentId"),
            ("secret", "应用 Secret"),
        ],
        "secrets": ["secret", "token", "encoding_aes_key"],
        "hint": "企业微信管理后台 → 应用管理 → 自建应用。",
    },
    "dingtalk": {
        "name": "钉钉",
        "icon": "dingtalk",
        "required": [
            ("app_key", "AppKey"),
            ("app_secret", "AppSecret"),
        ],
        "secrets": ["app_secret", "token"],
        "hint": "钉钉开放平台 → 企业内部应用 → 机器人。",
    },
    "web": {
        "name": "Web / H5",
        "icon": "globe",
        "required": [],
        "secrets": [],
        "hint": "浏览器直接访问平台即可，无需额外配置。",
    },
    "api": {
        "name": "API 开放",
        "icon": "code",
        "required": [],
        "secrets": ["token"],
        "hint": "对外提供 /api/channels/api/events，建议配置 token 并放在 X-DataClaw-Token 头。",
    },
}

DEFAULT_CONFIG: dict[str, dict] = {
    "feishu": {"app_id": "", "app_secret": "", "verification_token": "", "token": "demo-feishu-token"},
    "wecom": {"corp_id": "", "agent_id": "", "secret": "", "token": "demo-wecom-token"},
    "dingtalk": {"app_key": "", "app_secret": "", "token": "demo-dingtalk-token"},
    "web": {"theme": "light", "defaultEmployeeId": ""},
    "api": {"token": "demo-api-token", "rateLimit": 60},
}


def _mask_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return text[:2] + "*" * max(2, len(text) - 4) + text[-2:]


def status_of(channel: Channel) -> str:
    spec = CHANNEL_SPECS.get(channel.type)
    if spec is None:
        return "error"
    cfg = channel.config or {}
    missing = [key for key, _label in spec["required"] if not str(cfg.get(key) or "").strip()]
    if missing:
        return "unconfigured"
    return "ready" if channel.enabled else "unconfigured"


def to_dict(channel: Channel, *, reveal: bool = False) -> dict:
    spec = CHANNEL_SPECS.get(channel.type, {"name": channel.type, "required": [], "secrets": [], "hint": ""})
    cfg = dict(channel.config or {})
    shown = {}
    for k, v in cfg.items():
        shown[k] = v if reveal or k not in spec.get("secrets", []) else _mask_secret(str(v))
    missing = [label for key, label in spec["required"] if not str(cfg.get(key) or "").strip()]
    return {
        "id": channel.id,
        "type": channel.type,
        "name": channel.name or spec["name"],
        "enabled": bool(channel.enabled),
        "status": status_of(channel),
        "config": shown,
        "required": [{"key": k, "label": label, "value": bool(str(cfg.get(k) or "").strip())} for k, label in spec["required"]],
        "missing": missing,
        "hint": spec.get("hint", ""),
        "lastCheckedAt": channel.last_checked_at.isoformat() + "Z" if channel.last_checked_at else None,
        "updatedAt": channel.updated_at.isoformat() + "Z" if channel.updated_at else None,
        "webhook": f"/api/channels/{channel.type}/events",
    }


def ensure_channels(db: Session) -> list[Channel]:
    """补齐 5 个渠道（幂等）。"""
    existing = {c.type: c for c in db.scalars(select(Channel)).all()}
    created: list[Channel] = []
    for ctype, spec in CHANNEL_SPECS.items():
        if ctype in existing:
            continue
        cfg = dict(DEFAULT_CONFIG.get(ctype, {}))
        ch = Channel(
            type=ctype,
            name=spec["name"],
            enabled=ctype in ("web", "api"),
            config=cfg,
            status="unconfigured",
        )
        db.add(ch)
        created.append(ch)
    if created:
        db.flush()
        for ch in created:
            ch.status = status_of(ch)
    return list(db.scalars(select(Channel).order_by(Channel.created_at)).all())


def list_channels(db: Session) -> dict:
    rows = ensure_channels(db)
    items = [to_dict(c) for c in rows]
    return {
        "items": items,
        "total": len(items),
        "enabledCount": sum(1 for i in items if i["enabled"]),
        "readyCount": sum(1 for i in items if i["status"] == "ready"),
        "channels": items,
    }


def get_channel(db: Session, ctype: str) -> Channel:
    ctype = (ctype or "").lower()
    if ctype not in CHANNEL_SPECS:
        raise ValueError(f"不支持的渠道类型：{ctype}（可选：{'/'.join(CHANNEL_SPECS)}）")
    channel = db.scalar(select(Channel).where(Channel.type == ctype))
    if channel is None:
        ensure_channels(db)
        channel = db.scalar(select(Channel).where(Channel.type == ctype))
    if channel is None:
        raise ValueError(f"渠道 {ctype} 不存在")
    return channel


def save_channel(db: Session, ctype: str, payload: dict, *, actor: User | None = None) -> Channel:
    channel = get_channel(db, ctype)
    spec = CHANNEL_SPECS[channel.type]
    if payload.get("name"):
        channel.name = str(payload["name"])[:64]
    if "enabled" in payload and payload["enabled"] is not None:
        channel.enabled = bool(payload["enabled"])
    incoming = payload.get("config")
    if isinstance(incoming, dict):
        merged = dict(channel.config or {})
        for k, v in incoming.items():
            merged[str(k)] = v
        channel.config = merged

    # 开启前必须填齐必填项，否则给出中文提示（不静默保存成"假可用"）
    missing = [label for key, label in spec["required"] if not str((channel.config or {}).get(key) or "").strip()]
    if channel.enabled and missing:
        channel.enabled = False
        channel.status = "unconfigured"
        db.commit()
        raise ValueError(f"{spec['name']} 还缺少必填配置：{'、'.join(missing)}，已保存但保持停用状态")
    channel.status = status_of(channel)
    db.commit()
    db.refresh(channel)
    return channel


def test_channel(db: Session, ctype: str, *, actor: User | None = None) -> dict:
    channel = get_channel(db, ctype)
    spec = CHANNEL_SPECS[channel.type]
    started = time.perf_counter()
    cfg = channel.config or {}
    missing = [label for key, label in spec["required"] if not str(cfg.get(key) or "").strip()]
    channel.last_checked_at = datetime.utcnow()

    if missing:
        channel.status = "unconfigured"
        channel.enabled = False
        db.commit()
        return {
            "type": channel.type,
            "ok": False,
            "status": "unconfigured",
            "message": f"{spec['name']} 缺少必填配置：{'、'.join(missing)}",
            "missing": missing,
            "latencyMs": int((time.perf_counter() - started) * 1000),
        }

    if channel.type in ("feishu", "wecom", "dingtalk"):
        # V1：校验凭证格式，不建立真实长连接（不假装连上了）
        ok = True
        message = (
            f"{spec['name']} 凭证校验通过；V1 未建立真实长连接，"
            f"入站回调地址：/api/channels/{channel.type}/events（需带 X-DataClaw-Token）"
        )
        if channel.type == "feishu" and not str(cfg.get("app_id", "")).startswith("cli_"):
            message += "。提示：飞书 App ID 通常以 cli_ 开头，请确认是否填错"
    elif channel.type == "web":
        ok = channel.enabled
        message = "Web 渠道已启用，无需额外配置" if ok else "Web 渠道当前处于停用状态"
    else:
        ok = channel.enabled
        message = "API 渠道已启用" if ok else "API 渠道当前处于停用状态"
        if not str(cfg.get("token") or "").strip():
            message += "；未配置 token，入站请求将按宽松模式放行（仅建议演示环境）"

    channel.status = "ready" if ok else "unconfigured"
    db.commit()
    return {
        "type": channel.type,
        "ok": ok,
        "status": channel.status,
        "message": message,
        "latencyMs": int((time.perf_counter() - started) * 1000),
    }


# ---------------------------------------------------------------- 入站


def _verify_token(channel: Channel, token: str | None) -> tuple[bool, str]:
    expected = str((channel.config or {}).get("token") or "").strip()
    if not expected:
        return True, "未配置 token，宽松模式放行"
    if not token:
        return False, "缺少 X-DataClaw-Token 请求头"
    if token == expected:
        return True, "token 校验通过"
    if DEMO_MODE and token in ("demo-token", "demo"):
        return True, "演示 token 放行（DEMO_MODE=1）"
    return False, "token 校验失败"


def _runtime_reply(db: Session, user: User, employee: Employee, text: str) -> tuple[str, str | None]:
    """优先走运行时；没有 runner 时退化为知识库检索回复。返回 (reply, artifactId)。"""
    for mod_name, func_name in (
        ("app.runtime.runner", "run_once"),
        ("app.runtime.runner", "run"),
    ):
        try:
            mod = importlib.import_module(mod_name)
            func = getattr(mod, func_name, None)
            if func is None:
                continue
            out = func(db=db, user=user, employee=employee, content=text)
            if isinstance(out, dict):
                reply = str(out.get("reply") or out.get("text") or "").strip()
                if reply:
                    return reply, out.get("artifactId") or (out.get("artifact") or {}).get("id")
            elif isinstance(out, str) and out.strip():
                return out.strip(), None
        except TypeError:
            continue
        except Exception:
            continue

    # 退化路径：真实检索知识库，回复带来源
    try:
        found = knowledge_service.search(db, user, text, top_k=3)
        if found["items"]:
            top = found["items"][0]
            snippet = top["snippet"].replace("<em>", "").replace("</em>", "")
            reply = (
                f"我在知识库中找到《{top['docName']}》的相关内容：\n\n{snippet}\n\n"
                f"（来源：{top['docName']} 第 {top['seq'] + 1} 段，相关度 {top['score']:.2f}）"
            )
            if len(found["items"]) > 1:
                others = "、".join(f"《{i['docName']}》" for i in found["items"][1:])
                reply += f"\n\n其他相关文档：{others}"
            return reply, None
    except Exception:
        pass
    return (
        "已收到你的消息。当前数字员工还没有可在该渠道直接执行的技能，"
        "请在 DataClaw 工作台为员工安装相应技能后再试。",
        None,
    )


def handle_event(db: Session, ctype: str, *, token: str | None, body: dict) -> dict:
    started = time.perf_counter()
    channel = get_channel(db, ctype)
    ok, token_msg = _verify_token(channel, token)
    if not ok:
        db.add(
            AuditEvent(
                ts=datetime.utcnow(),
                actor_name="渠道入站",
                action="channel_inbound",
                target_type="channel",
                target_id=channel.type,
                target_name=channel.name or channel.type,
                detail={"type": channel.type, "reason": token_msg},
                risk="high",
                result="denied",
            )
        )
        db.commit()
        raise PermissionError(token_msg)

    text = str(body.get("text") or body.get("content") or "").strip()
    if not text:
        raise ValueError("消息内容 text 不能为空")

    # 发起人：优先 body.user（用户名），其次渠道默认用户，最后管理员
    user: User | None = None
    if body.get("user"):
        user = db.scalar(select(User).where(User.username == str(body["user"])))
        if user is None:
            raise ValueError(f"用户 {body['user']} 不存在")
    if user is None:
        default_id = str((channel.config or {}).get("defaultUserId") or "")
        if default_id:
            user = db.get(User, default_id)
    if user is None:
        user = db.scalar(select(User).where(User.role == "platform_admin").order_by(User.created_at))
    if user is None:
        raise ValueError("系统中没有可用用户，无法处理渠道消息")

    # 员工：body.employeeId，否则该用户第一个在用员工
    employee: Employee | None = None
    emp_id = body.get("employeeId") or body.get("employee_id")
    if emp_id:
        employee = db.get(Employee, str(emp_id))
        if employee is None or employee.owner_id != user.id:
            raise ValueError("指定的员工不存在或不属于该用户")
    else:
        employee = db.scalar(
            select(Employee)
            .where(Employee.owner_id == user.id, Employee.status == "active")
            .order_by(Employee.created_at)
        )
    if employee is None:
        raise ValueError(f"用户 {user.username} 还没有数字员工，请先在工作台创建")

    session = SessionModel(
        employee_id=employee.id,
        user_id=user.id,
        title=f"[{channel.name}] {text[:40]}",
        status="active",
        last_message_at=datetime.utcnow(),
        message_count=1,
    )
    db.add(session)
    db.flush()
    db.add(
        Message(
            session_id=session.id,
            role="user",
            content=text,
            steps=[{"id": "st_channel", "type": "channel", "channel": channel.type, "status": "done"}],
            tokens=len(text),
        )
    )

    reply, artifact_id = _runtime_reply(db, user, employee, text)
    db.add(
        Message(
            session_id=session.id,
            role="assistant",
            content=reply,
            tokens=len(reply),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    )
    session.message_count = 2
    session.last_message_at = datetime.utcnow()

    latency = int((time.perf_counter() - started) * 1000)
    db.add(
        AuditEvent(
            ts=datetime.utcnow(),
            actor_id=user.id,
            actor_name=user.name or user.username,
            action="channel_inbound",
            target_type="channel",
            target_id=channel.type,
            target_name=channel.name or channel.type,
            detail={
                "type": channel.type,
                "text": text[:200],
                "sessionId": session.id,
                "employeeId": employee.id,
                "replyChars": len(reply),
                "latencyMs": latency,
                "tokenCheck": token_msg,
            },
            risk="low",
            result="success",
            session_id=session.id,
        )
    )
    db.commit()

    return {
        "reply": reply,
        "sessionId": session.id,
        "artifactId": artifact_id,
        "employeeId": employee.id,
        "employeeName": employee.name,
        "channel": channel.type,
        "user": user.username,
        "latencyMs": latency,
    }


__all__ = [
    "CHANNEL_SPECS", "ensure_channels", "list_channels", "get_channel",
    "save_channel", "test_channel", "handle_event", "to_dict",
]
