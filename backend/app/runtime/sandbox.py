"""Workspace Provider：每个员工一个目录，所有产物/临时文件都落在这里。

V1：LocalProvider（进程级目录隔离 + 路径穿越防护 + 配额）。
V2：DockerProvider（接口占位）——对齐 OpenSandbox / E2B：每会话一个容器，
    仅挂载 /workspace，egress 走白名单代理，宿主机不可见。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol

from ..core.config import WORKSPACE_DIR

QUOTA_BYTES = 50 * 1024 * 1024  # 50MB / 员工


class WorkspaceProvider(Protocol):
    def ensure(self, employee_id: str) -> Path: ...
    def write(self, employee_id: str, rel_path: str, data: bytes | str) -> Path: ...
    def read(self, employee_id: str, rel_path: str) -> bytes: ...
    def list(self, employee_id: str) -> list[dict]: ...
    def remove(self, employee_id: str, rel_path: str) -> bool: ...
    def usage(self, employee_id: str) -> int: ...


def _safe_join(root: Path, rel_path: str) -> Path:
    """把 rel_path 解析到 root 内；越界直接拒绝（含符号链接穿越）。"""
    rel = (rel_path or "").replace("\\", "/").lstrip("/")
    if not rel or rel in (".", ".."):
        raise ValueError("非法路径")
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f"路径越界: {rel_path}")
    return target


class LocalProvider:
    """本地目录隔离实现（默认）。"""

    def __init__(self, base: Path | None = None) -> None:
        self.base = Path(base or WORKSPACE_DIR)
        self.base.mkdir(parents=True, exist_ok=True)

    def ensure(self, employee_id: str) -> Path:
        safe = "".join(c for c in (employee_id or "anon") if c.isalnum() or c in "-_") or "anon"
        root = self.base / safe
        (root / "tmp").mkdir(parents=True, exist_ok=True)
        (root / "out").mkdir(parents=True, exist_ok=True)
        return root

    def usage(self, employee_id: str) -> int:
        root = self.ensure(employee_id)
        total = 0
        for p in root.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total

    def _check_quota(self, employee_id: str, extra: int) -> None:
        if self.usage(employee_id) + extra > QUOTA_BYTES:
            raise ValueError("工作区配额已满（50MB），请清理临时文件")

    def write(self, employee_id: str, rel_path: str, data: bytes | str) -> Path:
        root = self.ensure(employee_id)
        target = _safe_join(root, rel_path)
        raw = data.encode("utf-8") if isinstance(data, str) else data
        self._check_quota(employee_id, len(raw))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return target

    def read(self, employee_id: str, rel_path: str) -> bytes:
        root = self.ensure(employee_id)
        target = _safe_join(root, rel_path)
        if not target.is_file():
            raise FileNotFoundError(rel_path)
        return target.read_bytes()

    def list(self, employee_id: str) -> list[dict]:
        root = self.ensure(employee_id)
        out: list[dict] = []
        for p in sorted(root.rglob("*")):
            if p.is_file():
                st = p.stat()
                out.append(
                    {
                        "path": p.relative_to(root).as_posix(),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    }
                )
        return out

    def remove(self, employee_id: str, rel_path: str) -> bool:
        root = self.ensure(employee_id)
        target = _safe_join(root, rel_path)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            return True
        if target.is_file():
            target.unlink(missing_ok=True)
            return True
        return False


class DockerProvider:
    """V2 容器沙箱接口（占位，不改调用方）。

    实现建议（与 OpenSandbox / E2B 对齐）：
    - ensure(): POST /sandboxes {image:"dataclaw/agent-runtime:py311", mounts:[{host: <workspace>, target:"/workspace"}], egress_allowlist:[...]}
    - write/read/list/remove(): 通过 sandbox files API 或挂载目录直接操作 /workspace
    - 每会话容器生命周期 = 会话生命周期；空闲 30min 回收；配额由 cgroup 限制
    - 产物导出：容器内 /workspace/out -> 宿主 data/artifacts
    """

    def __init__(self, endpoint: str = "", image: str = "dataclaw/agent-runtime:py311") -> None:
        self.endpoint = endpoint or os.getenv("DATACLAW_SANDBOX_ENDPOINT", "")
        self.image = image
        self._local = LocalProvider()  # 未配置 endpoint 时降级本地，保证 V1 可用

    def ensure(self, employee_id: str) -> Path:
        return self._local.ensure(employee_id)

    def write(self, employee_id: str, rel_path: str, data: bytes | str) -> Path:
        return self._local.write(employee_id, rel_path, data)

    def read(self, employee_id: str, rel_path: str) -> bytes:
        return self._local.read(employee_id, rel_path)

    def list(self, employee_id: str) -> list[dict]:
        return self._local.list(employee_id)

    def remove(self, employee_id: str, rel_path: str) -> bool:
        return self._local.remove(employee_id, rel_path)

    def usage(self, employee_id: str) -> int:
        return self._local.usage(employee_id)


_provider: WorkspaceProvider | None = None


def get_provider() -> WorkspaceProvider:
    global _provider
    if _provider is None:
        mode = os.getenv("DATACLAW_SANDBOX", "local").lower()
        _provider = DockerProvider() if mode == "docker" else LocalProvider()
    return _provider
