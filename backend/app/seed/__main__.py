"""`python -m app.seed [--reset]`：建种子数据并打印每张表行数。

用法（在 backend 目录下）：
    python -m app.seed            # 幂等：已有用户则跳过建库，仅补齐 demo.db
    python -m app.seed --reset    # 清库重建（会删除 data/demo.db 后重新生成）
"""
from __future__ import annotations

import json
import logging
import sys

from sqlalchemy import func, select, text

from ..core.db import SessionLocal, engine, init_db
from . import ensure_seed, reset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _table_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    with engine.connect() as conn:
        names = [
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            )
        ]
        for name in names:
            try:
                out[name] = int(conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar() or 0)
            except Exception:
                out[name] = -1
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    do_reset = "--reset" in argv or "-r" in argv

    init_db()
    if do_reset:
        print("== 重置数据库（drop_all → 重新 seed）==")
        summary = reset()
    else:
        summary = ensure_seed()

    counts = _table_counts()
    print("\n== seed 结果 ==")
    print(f"模式：{'重建' if do_reset else ('跳过（已有数据）' if summary.get('skipped') else '初始化')}")
    if summary.get("demoRows"):
        print(f"demo.db：{json.dumps(summary['demoRows'], ensure_ascii=False)}")
    print(f"耗时：{summary.get('elapsedMs', 0)} ms")

    print("\n== 各表行数（app.db）==")
    for name, n in counts.items():
        print(f"  {name:22s} {n:>8d}")
    print(f"  {'表数量':22s} {len(counts):>8d}")
    print(f"  {'总行数':22s} {sum(v for v in counts.values() if v > 0):>8d}")

    db = SessionLocal()
    try:
        from ..models import User

        users = db.scalars(select(User).order_by(User.username)).all()
        print("\n== 演示账号（口令 123456，admin 为 admin123）==")
        for u in users:
            print(f"  {u.username:12s} {u.name:6s} {u.role:14s} {u.dept}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
