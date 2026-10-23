"""工具包公共工具函数与状态键约定。"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from typing import Any

STATE_CHATBI = "chatbi"
STATE_DOC = "doc"
STATE_SALES = "sales"
STATE_CONTRACT = "contract"
STATE_KNOWLEDGE = "knowledge"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace(",", "").replace("%", "").strip()
        if text in ("", "-", "—", "None", "null"):
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def fmt_num(value: Any, digits: int = 1) -> str:
    num = to_float(value)
    if abs(num) >= 1_0000_0000:
        return f"{num / 1_0000_0000:.{digits}f}亿"
    if abs(num) >= 1_0000:
        return f"{num / 1_0000:.{digits}f}万"
    if abs(num - int(num)) < 1e-9:
        return f"{int(num):,}"
    return f"{num:,.{digits}f}"


def pct(value: Any, digits: int = 1) -> str:
    return f"{to_float(value):.{digits}f}%"


def mean_std(values: list[float]) -> tuple[float, float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0, 0.0
    avg = sum(vals) / len(vals)
    var = sum((v - avg) ** 2 for v in vals) / max(len(vals), 1)
    return avg, math.sqrt(var)


def json_safe(value: Any):
    """产物 payload 必须是 JSON 可序列化（Decimal/datetime/NaN 统一处理）。"""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 4)
    if value is None or isinstance(value, (int, bool, str)):
        return value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def quarter_range(anchor: date, offset: int = 0) -> tuple[date, date, str]:
    """返回锚点所在季度（offset=0）或前后季度的起止日期。"""
    q = (anchor.month - 1) // 3 + 1 + offset
    year = anchor.year
    while q < 1:
        q += 4
        year -= 1
    while q > 4:
        q -= 4
        year += 1
    start_month = (q - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end, f"{year}年Q{q}"


def parse_period_label(label: str) -> str:
    m = re.search(r"(\d{4})年Q([1-4])", label or "")
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    return label or ""


def sample_rows(rows: list[dict], limit: int = 100) -> list[dict]:
    return rows[:limit]
