"""Agent 运行时的公共类型（唯一来源，供 api/seed/tools 复用）。

设计要点：
- 工具只依赖 ToolContext，不直接摸 HTTP / 事件循环，便于单测与复用。
- ToolResult 永远不抛异常：工具内部异常在 registry 的 execute 包装层统一转成 ok=False。
- state 是同一次会话内跨工具共享的临时黑板（例如 chatbi.ask 的查询结果交给 dashboard.build）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

EmitFn = Callable[[str, dict], Awaitable[None]]
ToolHandler = Callable[[dict, "ToolContext"], Awaitable["ToolResult"]]


def new_step_id() -> str:
    return f"st_{uuid.uuid4().hex[:10]}"


def new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


@dataclass
class ToolContext:
    """一次工具调用所需的全部上下文（以会话发起用户身份执行）。"""

    db: Any
    user: Any
    employee: Any
    session_id: str
    message_id: str
    emit: EmitFn
    approved: dict[str, bool]
    workspaces: Path

    # —— 扩展字段（有默认值，不影响按契约构造） ——
    step_id: str = ""
    tool_name: str = ""
    skill_names: list[str] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    datasource_id: str = ""
    auto_approve: bool = False
    trace: list[dict] = field(default_factory=list)

    # —— 便捷访问器 ——
    def datasource(self):
        from . import get_demo_datasource

        return get_demo_datasource(self.db, self.datasource_id or None)

    def ds_id(self) -> str:
        ds = self.datasource()
        return getattr(ds, "id", "") if ds is not None else ""

    def employees_workspace(self) -> Path:
        return Path(self.workspaces)


@dataclass
class ToolResult:
    ok: bool
    summary: str = ""
    output: dict = field(default_factory=dict)
    artifact: dict | None = None  # {"kind","title","payload","text","file_name","file_path"}
    error: str = ""

    def to_step_output(self) -> dict:
        """裁剪为 SSE step 事件的 output（避免把大结果全塞进事件）。"""
        out = dict(self.output or {})
        preview = out.get("preview")
        if isinstance(preview, str) and len(preview) > 1500:
            out["preview"] = preview[:1500] + "…"
        if len(str(out)) > 12000:
            out = {k: v for k, v in out.items() if k in ("rowCount", "columns", "maskedColumns", "tables", "summary", "title", "stats", "charts", "kpis", "insights", "deniedReason")}
        return out


@dataclass
class ToolSpec:
    name: str
    title: str
    description: str
    params: dict
    handler: ToolHandler
    risk: str = "low"
    requires_approval: bool = False
    skill: str = ""

    def schema_for_llm(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name.replace(".", "__"),
                "description": self.description,
                "parameters": self.params or {"type": "object", "properties": {}},
            },
        }


@dataclass
class PlanStep:
    tool: str
    params: dict = field(default_factory=dict)
    title: str = ""
    step_id: str = ""

    def __post_init__(self) -> None:
        if not self.step_id:
            self.step_id = new_step_id()


@dataclass
class PlannerPlan:
    scenario: str
    steps: list[PlanStep] = field(default_factory=list)
    reason: str = ""
    final_text: str = ""  # fallback 场景直接给出的回答
    title: str = ""


async def emit_step(ctx: ToolContext, status: str, **payload: Any) -> None:
    """工具向 SSE 推送 step 事件（running/done/skipped/error）。"""
    data: dict[str, Any] = {
        "id": ctx.step_id or new_step_id(),
        "type": "tool_call" if status == "running" else "tool_result",
        "tool": ctx.tool_name,
        "status": status,
    }
    data.update(payload)
    await ctx.emit("step", data)


def make_error(context: str, exc: BaseException) -> str:
    return f"{context}: {type(exc).__name__}: {exc}"
