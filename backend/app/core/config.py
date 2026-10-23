"""全局配置。所有可调项均可通过环境变量覆盖（前缀 DATACLAW_）。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # backend/
REPO = ROOT.parent                                  # C:\dataclaw
DATA_DIR = Path(os.getenv("DATACLAW_DATA_DIR", REPO / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
ARTIFACT_DIR = DATA_DIR / "artifacts"
WORKSPACE_DIR = DATA_DIR / "workspaces"
STATIC_DIR = ROOT / "app" / "static"

for _d in (DATA_DIR, UPLOAD_DIR, ARTIFACT_DIR, WORKSPACE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("DATACLAW_DB_URL", f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}")

SECRET_KEY = os.getenv("DATACLAW_SECRET_KEY", "dataclaw-dev-secret-change-me-please-rotate-in-production")
TOKEN_TTL_HOURS = int(os.getenv("DATACLAW_TOKEN_TTL_HOURS", "12"))
DEMO_DB = DATA_DIR / "demo.db"

# LLM（OpenAI 兼容）。没有 Key 时运行时自动退化到离线确定性 Planner。
LLM_BASE_URL = os.getenv("DATACLAW_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
LLM_API_KEY = os.getenv("DATACLAW_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
LLM_MODEL = os.getenv("DATACLAW_LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
LLM_TIMEOUT = float(os.getenv("DATACLAW_LLM_TIMEOUT", "120"))

APP_NAME = "DataClaw 企业级数字员工平台"
APP_VERSION = "1.0.0"
MAX_STEPS = int(os.getenv("DATACLAW_MAX_STEPS", "12"))
TOOL_TIMEOUT = float(os.getenv("DATACLAW_TOOL_TIMEOUT", "60"))
SSE_QUEUE_TIMEOUT = float(os.getenv("DATACLAW_SSE_TIMEOUT", "180"))

DEMO_MODE = os.getenv("DATACLAW_DEMO_MODE", "1") == "1"

CORS_ORIGINS = [o for o in os.getenv(
    "DATACLAW_CORS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8787,http://127.0.0.1:8787",
).split(",") if o]
