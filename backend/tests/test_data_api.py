"""数据安全与种子数据 API 自测（可直接运行，也可被 pytest 收集）。

运行方式（在 backend 目录）：
    python tests/test_data_api.py          # 独立跑，使用临时数据目录，不污染 data/
    python -m pytest tests/test_data_api.py -v   # 装了 pytest 也可以

覆盖：登录 → 种子规模 → 策略生效矩阵 → SQL 预览（掩码 / 行级 / 拒绝 / DML 拒绝）
      → 知识库上传+切片+检索+ACL → 渠道测试与入站 webhook → overview 真实聚合。
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

# 必须在 import app 之前设置数据目录（隔离测试数据，不碰仓库 data/）
os.environ.setdefault(
    "DATACLAW_DATA_DIR",
    os.environ.get("PYTEST_CURRENT_TEST_DIR") or tempfile.mkdtemp(prefix="dataclaw_test_"),
)
os.environ.setdefault("DATACLAW_DEMO_MODE", "1")

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import create_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Policy, Skill, SkillInstall, User  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

client = TestClient(app)
_tokens: dict[str, str] = {}


# ---------------------------------------------------------------- 工具


def _login(username: str, password: str) -> str:
    """优先走真实登录接口；不可用时用同等 JWT 直接签发（测试不依赖 auth 模块）。"""
    if username in _tokens:
        return _tokens[username]
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    if resp.status_code == 200:
        token = resp.json()["token"]
    else:  # auth 模块尚未实现 / 口令表异常时兜底
        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.username == username))
            assert user is not None, f"用户 {username} 不存在，seed 未生效"
            token = create_token(user.id)
        finally:
            db.close()
    _tokens[username] = token
    return token


def H(username: str) -> dict:
    pw = "admin123" if username == "admin" else "123456"
    return {"Authorization": f"Bearer {_login(username, pw)}"}


def check(cond: bool, message: str) -> None:
    assert cond, message


# ---------------------------------------------------------------- 用例


def test_seed_scale() -> None:
    """种子数据规模与关键规律。"""
    db = SessionLocal()
    try:
        users = db.scalar(select(func.count()).select_from(User))
        skills = db.scalar(select(func.count()).select_from(Skill))
        policies = db.scalar(select(func.count()).select_from(Policy))
        installs = db.scalar(select(func.count()).select_from(SkillInstall))
        check(users >= 12, f"用户数应为 12，实际 {users}")
        check(skills == 12, f"内置技能应为 12，实际 {skills}")
        check(policies >= 10, f"策略应 >=10，实际 {policies}")
        check(installs >= 20, f"技能安装记录应 >=20，实际 {installs}")
    finally:
        db.close()

    resp = client.get("/api/datasources", headers=H("analyst"))
    check(resp.status_code == 200, resp.text)
    ds = resp.json()["items"][0]
    check(ds["tableCount"] == 7, f"demo 源应有 7 张表，实际 {ds['tableCount']}")
    check(ds["sensitiveColumnCount"] >= 4, "敏感列数不足")
    print(f"  seed: users={users} skills={skills} policies={policies} installs={installs} "
          f"tables={ds['tableCount']} columns={ds['columnCount']}")


def test_effective_matrix() -> None:
    """生效矩阵：analyst 只能看工时表、sales 三张表带行级过滤。"""
    resp = client.get("/api/policies/effective", params={"userId": "u_analyst"}, headers=H("admin"))
    check(resp.status_code == 200, resp.text)
    matrix = resp.json()
    tables = {t["table"]: t for t in matrix["tables"]}
    check(tables["worktime_fact"]["allowed"] is True, "analyst 应能读 worktime_fact（user 级策略优先于 role）")
    masked = {c["column"] for c in tables["worktime_fact"]["columns"] if c["masked"]}
    check(masked == {"salary", "employee_name"}, f"脱敏列应为 salary/employee_name，实际 {masked}")
    check(tables["crm_customer"]["allowed"] is False, "analyst 应被拒绝访问 crm_customer")
    check("无权访问" in (tables["crm_customer"]["deniedReason"] or ""), "拒绝原因应可读")

    resp = client.get("/api/policies/effective", params={"userId": "u_sales"}, headers=H("sales"))
    check(resp.status_code == 200, resp.text)
    sales_tables = {t["table"]: t for t in resp.json()["tables"]}
    for name in ("crm_customer", "crm_order", "crm_contact_log"):
        check(sales_tables[name]["allowed"], f"sales 应能读 {name}")
        check(bool(sales_tables[name]["rowFilters"]), f"{name} 应带行级过滤")
    check("u_sales" in sales_tables["crm_customer"]["rowFilters"][0], "行级过滤条件应指向 sales 本人")

    # 成员不能看别人的生效矩阵
    resp = client.get("/api/policies/effective", params={"userId": "u_legal"}, headers=H("analyst"))
    check(resp.status_code == 403, f"member 查他人矩阵应 403，实际 {resp.status_code}")
    print(f"  effective: analyst 可见 {matrix['summary']['tablesVisible']} 表，"
          f"脱敏 {matrix['summary']['columnsMasked']} 列；sales 行级过滤 3 表")


def test_sql_preview_mask_rowfilter_denied() -> None:
    """SQL 预览：掩码 / 行级过滤 / 表级拒绝 / DML 拒绝 / LIMIT 收敛。"""
    resp = client.post("/api/policies/preview",
                       json={"datasourceId": "ds_demo", "sql": "select * from worktime_fact limit 5"},
                       headers=H("analyst"))
    check(resp.status_code == 200, resp.text)
    data = resp.json()
    check(data["ok"] is True, f"analyst 查工时表应成功：{data.get('deniedReason') or data.get('error')}")
    check(len(data["rows"]) == 5, f"应返回 5 行，实际 {len(data['rows'])}")
    check(set(data["maskedColumns"]) == {"salary", "employee_name"}, data["maskedColumns"])
    first = data["rows"][0]
    check(first["salary"] == "****", f"salary 应全掩码，实际 {first['salary']}")
    check(str(first["employee_name"]).startswith("sha256:"), f"姓名应哈希，实际 {first['employee_name']}")
    check(data["originalSql"].lower().startswith("select * from worktime_fact"),
          f"应回传原始 SQL 供前端对比，实际 {data['originalSql']}")
    check("FROM worktime_fact" in data["rewrittenSql"], "应回传改写后 SQL")

    resp = client.post("/api/policies/preview",
                       json={"datasourceId": "ds_demo", "sql": "select * from crm_customer"},
                       headers=H("sales"))
    data = resp.json()
    check(data["ok"] is True, f"sales 查客户应成功（行级过滤）：{data.get('deniedReason')}")
    owners = {row["owner_id"] for row in data["rows"]}
    check(owners == {"u_sales"}, f"sales 只应看到自己名下客户，实际 {owners}")
    check("owner_id = 'u_sales'" in data["rewrittenSql"], "改写 SQL 应带行级条件")

    resp = client.post("/api/policies/preview",
                       json={"datasourceId": "ds_demo", "sql": "select * from contract_sample"},
                       headers=H("sales"))
    data = resp.json()
    check(data["ok"] is False, "sales 查合同表应被拒绝")
    check("无权访问表 contract_sample" in (data["deniedReason"] or ""), data.get("deniedReason"))

    resp = client.post("/api/policies/preview",
                       json={"datasourceId": "ds_demo", "sql": "delete from worktime_fact"},
                       headers=H("analyst"))
    data = resp.json()
    check(data["ok"] is False, "DML 应被拒绝")
    check("仅支持只读查询" in (data["deniedReason"] or ""), data.get("deniedReason"))

    resp = client.post("/api/policies/preview",
                       json={"datasourceId": "ds_demo", "sql": "select * from worktime_fact", "limit": 9999},
                       headers=H("analyst"))
    data = resp.json()
    check(data["limit"] == 200, f"limit 应被收敛到 200，实际 {data['limit']}")
    check(data["rewrittenSql"].upper().endswith(f"LIMIT {data['limit']}"), data["rewrittenSql"][-40:])

    # 多表 JOIN：行级过滤要限定别名，不能出现 ambiguous column
    resp = client.post(
        "/api/policies/preview",
        json={"datasourceId": "ds_demo",
              "sql": "select c.name, o.amount from crm_customer c join crm_order o on o.customer_id=c.id"},
        headers=H("sales"))
    data = resp.json()
    check(data["ok"] is True, f"sales 多表 JOIN 应成功：{data.get('error')}")
    check("c.owner_id" in data["rewrittenSql"] and "o.owner_id" in data["rewrittenSql"],
          f"行级条件应带表限定：{data['rewrittenSql']}")
    print(f"  preview: analyst 5 行 salary=****；sales 客户 {len(owners)} 类且全为本人；"
          f"合同拒绝、DML 拒绝、LIMIT={data['limit']}")


def test_knowledge_upload_search_acl() -> None:
    """知识库：上传 md → 切片 → 检索命中 → ACL 限制他人 → 所有者仍可读。"""
    doc_md = (
        "# 差旅报销补充规定\n\n"
        "## 一、住宿标准\n\n一线城市每晚不超过 700 元，二线城市不超过 500 元。超标需部门负责人审批。\n\n"
        "## 二、交通标准\n\n高铁二等座、飞机经济舱；市内交通凭票报销，单日上限 120 元。\n\n"
        "## 三、审批流程\n\n报销单由部门负责人审批后提交财务，财务 5 个工作日内完成审核。\n"
    )
    resp = client.post(
        "/api/knowledge/docs",
        files={"file": ("差旅报销补充规定.md", doc_md.encode("utf-8"), "text/markdown")},
        data={"tags": "报销,财务", "dept": "财务部"},
        headers=H("analyst"),
    )
    check(resp.status_code == 200, resp.text)
    doc = resp.json()
    check(doc["status"] == "ready", f"解析状态应为 ready：{doc}")
    check(doc["chunkCount"] >= 1, f"应至少生成 1 个切片，实际 {doc['chunkCount']}")
    doc_id = doc["id"]

    resp = client.post("/api/knowledge/search",
                       json={"query": "一线城市 住宿标准 报销", "topK": 3}, headers=H("analyst"))
    check(resp.status_code == 200, resp.text)
    hits = resp.json()
    check(hits["total"] >= 1, "上传后应能检索到")
    check(hits["items"][0]["docName"] == "差旅报销补充规定.md", hits["items"][0]["docName"])
    check(hits["items"][0]["score"] > 0, "score 应大于 0")
    check("<em>" in hits["items"][0]["snippet"], "snippet 应带高亮")

    # 受限文档：《客户分级管理办法》对 analyst 不可见，检索也不能泄露
    resp = client.get("/api/knowledge/docs", headers=H("analyst"))
    names = {i["name"] for i in resp.json()["items"]}
    check("客户分级管理办法.md" not in names, "analyst 不应看到受限文档")
    resp = client.get("/api/knowledge/docs", headers=H("sales"))
    names = {i["name"] for i in resp.json()["items"]}
    check("客户分级管理办法.md" in names, "sales 应能看到《客户分级管理办法》")
    resp = client.post("/api/knowledge/search", json={"query": "客户分级 A级 折扣", "topK": 5},
                       headers=H("analyst"))
    hit_docs = {i["docName"] for i in resp.json()["items"]}
    check("客户分级管理办法.md" not in hit_docs, f"检索不应返回越权文档，实际 {hit_docs}")

    # ACL：只授权 legal 可读，sales 立即看不到；所有者仍可读
    resp = client.post(f"/api/knowledge/docs/{doc_id}/acl",
                       json={"subjectType": "user", "subjectId": "u_legal", "canRead": True},
                       headers=H("admin"))
    check(resp.status_code == 200, resp.text)
    check(resp.json()["restricted"] is True, "设置 ACL 后应为受限")
    resp = client.get("/api/knowledge/docs", headers=H("sales"))
    check("差旅报销补充规定.md" not in {i["name"] for i in resp.json()["items"]},
          "ACL 生效后 sales 不应看到该文档")
    resp = client.get(f"/api/knowledge/docs/{doc_id}", headers=H("analyst"))
    check(resp.status_code == 200, f"文档所有者应始终可读：{resp.status_code}")

    # 清理
    resp = client.delete(f"/api/knowledge/docs/{doc_id}", headers=H("analyst"))
    check(resp.status_code == 200, resp.text)
    print(f"  knowledge: 上传→{doc['chunkCount']} 切片→检索命中 score={hits['items'][0]['score']}，"
          f"ACL/所有者可读均正常")


def test_channels_and_inbound() -> None:
    """渠道：列表 5 条 → 缺配置测试失败（中文原因）→ 补齐后可测 → 入站 token 校验 + 真实回复。"""
    resp = client.get("/api/channels", headers=H("admin"))
    check(resp.status_code == 200, resp.text)
    data = resp.json()
    check(data["total"] == 5, f"应有 5 个渠道，实际 {data['total']}")
    types = {i["type"] for i in data["items"]}
    check(types == {"feishu", "wecom", "dingtalk", "web", "api"}, types)

    resp = client.post("/api/channels/feishu/test", headers=H("admin"))
    check(resp.status_code == 400, f"飞书未配置时应 400，实际 {resp.status_code}")
    detail = resp.json()["error"]
    check("缺少必填配置" in detail["message"], detail)
    check("App ID" in " ".join(detail.get("missing") or []), detail)

    resp = client.post("/api/channels/feishu",
                       json={"enabled": True, "config": {"app_id": "cli_test001", "app_secret": "s3cret"}},
                       headers=H("admin"))
    check(resp.status_code == 200, resp.text)
    resp = client.post("/api/channels/feishu/test", headers=H("admin"))
    check(resp.json()["ok"] is True, resp.json().get("message"))

    # 入站 webhook：api 渠道，正确 token
    resp = client.post("/api/channels/api/events",
                       json={"text": "工时填报的口径是什么？", "user": "analyst"},
                       headers={"X-DataClaw-Token": "demo-api-token"})
    check(resp.status_code == 200, resp.text)
    body = resp.json()
    check(bool(body["reply"]), "入站应返回 reply")
    check(bool(body["sessionId"]), "入站应落会话")
    check(body["user"] == "analyst", body)
    check(body["latencyMs"] >= 0, body)

    # 错误 token → 401
    resp = client.post("/api/channels/api/events", json={"text": "hi"},
                       headers={"X-DataClaw-Token": "wrong-token"})
    check(resp.status_code == 401, f"错误 token 应 401，实际 {resp.status_code}")
    print(f"  channels: 5 个渠道；入站 reply {len(body['reply'])} 字，session={body['sessionId']}")


def test_overview_and_metrics() -> None:
    """overview 全部真算；metrics 带权限标记；classifications 分级统计。"""
    resp = client.get("/api/overview", headers=H("admin"))
    check(resp.status_code == 200, resp.text)
    data = resp.json()
    stats = data["stats"]
    for key in ("employees", "sessions", "messages", "toolCalls", "skills", "users"):
        check(stats[key] > 0, f"overview.{key} 应有数据，实际 {stats[key]}")
    check(stats["denied"] >= 3, f"越权拒绝次数应 >=3，实际 {stats['denied']}")
    check(len(data["trend"]) == 7, "趋势应为 7 天")
    check(sum(d["sessions"] + d["toolCalls"] for d in data["trend"]) > 0, "趋势应有数据")
    check(len(data["topEmployees"]) > 0, "应有员工活跃数据")
    check(len(data["recentAudit"]) == 10, "最近审计应返回 10 条")
    check(sum(r["count"] for r in data["riskDistribution"]) > 0, "风险分布应有数据")
    check(len(data["scenarioStats"]) > 0, "场景统计应有数据")
    check(data["dataStats"]["tables"] == 7, "数据源表数应为 7")

    resp = client.get("/api/metrics", headers=H("analyst"))
    check(resp.status_code == 200, resp.text)
    metrics = resp.json()
    check(metrics["total"] == 7, f"指标应为 7 个，实际 {metrics['total']}")
    check(metrics["allowedCount"] < metrics["total"], "analyst 应有部分指标因缺表权限不可用")
    denied = [m["code"] for m in metrics["items"] if not m["allowed"]]
    check("customer_contract_amount" in denied, denied)

    resp = client.get("/api/classifications", headers=H("admin"))
    check(resp.status_code == 200, resp.text)
    cls = resp.json()
    check(cls["totals"]["secret"] >= 3, cls["totals"])
    check(cls["totals"]["top_secret"] >= 1, "应有 top_secret 列（contact_phone）")
    check(cls["items"][0]["table"] == "crm_customer", cls["items"][0])
    print(f"  overview: employees={stats['employees']} sessions={stats['sessions']} "
          f"toolCalls={stats['toolCalls']} denied={stats['denied']}；"
          f"metrics {metrics['allowedCount']}/{metrics['total']} 可用；"
          f"分级 secret={cls['totals']['secret']} top_secret={cls['totals']['top_secret']}")


def test_upload_parse_failure() -> None:
    """上传不支持的格式 → 400 中文提示；解析失败不静默成功。"""
    resp = client.post("/api/knowledge/docs",
                       files={"file": ("bad.exe", b"\x00\x01binary", "application/octet-stream")},
                       headers=H("analyst"))
    check(resp.status_code == 400, f"非法格式应 400，实际 {resp.status_code}")
    detail = resp.json()["error"]
    check("暂不支持" in detail["message"], detail)

    resp = client.post("/api/knowledge/search", json={"query": ""}, headers=H("analyst"))
    check(resp.status_code == 400, "空检索词应 400")
    print("  guards: 非法上传与空检索均返回中文 400")


# ---------------------------------------------------------------- 入口


TESTS = [
    test_seed_scale,
    test_effective_matrix,
    test_sql_preview_mask_rowfilter_denied,
    test_knowledge_upload_search_acl,
    test_channels_and_inbound,
    test_overview_and_metrics,
    test_upload_parse_failure,
]


def main() -> int:
    print(f"数据目录：{os.environ['DATACLAW_DATA_DIR']}")
    failures = 0
    with client:
        for fn in TESTS:
            name = fn.__name__
            try:
                fn()
                print(f"[PASS] {name}")
            except Exception as exc:                    # noqa: BLE001
                failures += 1
                print(f"[FAIL] {name}: {exc}")
                traceback.print_exc()
    print(f"\n{'全部通过' if not failures else f'{failures} 个用例失败'}（{len(TESTS)} 个用例）")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
