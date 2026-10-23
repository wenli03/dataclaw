"""Agent 运行时自测：场景 A（大屏+报告）/ C（合同审查+docx）/ 兜底 / 权限降级 / SSE。

运行：cd backend && <python> -m pytest tests/test_runtime.py -q
测试使用独立临时 data 目录 + 真实 seed（不污染仓库 data/）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

# —— 必须在 import app 之前完成环境隔离 ——
_TMP = Path(tempfile.mkdtemp(prefix="dataclaw-test-"))
os.environ["DATACLAW_DATA_DIR"] = str(_TMP)
os.environ["DATACLAW_DB_URL"] = f"sqlite:///{(_TMP / 'app.db').as_posix()}"
os.environ["DATACLAW_LLM_API_KEY"] = ""
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("DATACLAW_LLM_BASE_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import create_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Approval,
    AuditEvent,
    Employee,
    EmployeeSkill,
    SessionModel,
    Skill,
    User,
)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _db():
    return SessionLocal()


def _user(db, username: str = "analyst") -> User:
    user = db.query(User).filter(User.username == username).first()
    assert user is not None, f"seed 缺少用户 {username}"
    return user


def _login(client: TestClient, username: str = "analyst") -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    if response.status_code == 200:
        return {"Authorization": f"Bearer {response.json()['token']}"}
    db = _db()
    try:
        user = _user(db, username)
        return {"Authorization": f"Bearer {create_token(user.id)}"}
    finally:
        db.close()


def _ensure_employee(db, owner_id: str, employee_id: str, name: str, skill_names: list[str]) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        employee = Employee(id=employee_id, owner_id=owner_id, name=name, role_title="测试员工", status="active")
        db.add(employee)
        db.commit()
    for skill_name in skill_names:
        skill = db.query(Skill).filter(Skill.name == skill_name).first()
        assert skill is not None, f"seed 缺少技能 {skill_name}"
        exists = (
            db.query(EmployeeSkill)
            .filter(EmployeeSkill.employee_id == employee.id, EmployeeSkill.skill_id == skill.id)
            .first()
        )
        if exists is None:
            db.add(EmployeeSkill(employee_id=employee.id, skill_id=skill.id, enabled=True))
    db.commit()
    return employee


def _seed_analyst_employee(db) -> Employee:
    employee = db.get(Employee, "emp_analyst_1")
    if employee is not None:
        return employee
    analyst = _user(db, "analyst")
    return _ensure_employee(db, analyst.id, "emp_analyst_1", "工时分析助手", ["chatbi", "dashboard-builder", "deep-report"])


def _make_session(client: TestClient, headers: dict, employee_id: str) -> dict:
    response = client.post("/api/sessions", json={"employeeId": employee_id}, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("employeeId") == employee_id
    return data


def _send(client: TestClient, headers: dict, session_id: str, content: str, attachments=None) -> dict:
    response = client.post(
        f"/api/sessions/{session_id}/messages?stream=false",
        json={"content": content, "attachments": attachments or []},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# 场景 A：工时分析 → 大屏 + 深度报告
# --------------------------------------------------------------------------- #


def test_session_crud_and_autotitle(client: TestClient):
    headers = _login(client, "analyst")
    db = _db()
    try:
        employee = _seed_analyst_employee(db)
        employee_id = employee.id
    finally:
        db.close()

    response = client.post("/api/sessions", json={"employeeId": employee_id}, headers=headers)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["employeeId"] == employee_id
    session_id = created["id"]

    # 首次提问自动改标题（取前 20 字，去掉「帮我」等）
    data = _send(client, headers, session_id, "帮我分析下上季度各区域工时效率情况")
    detail = client.get(f"/api/sessions/{session_id}", headers=headers).json()
    assert detail["employeeId"] == employee_id
    assert detail["title"] != "新会话"
    assert data["title"] == detail["title"]
    assert len(detail["title"]) <= 20
    assert detail["title"].startswith("分析下上季度")
    assert detail["messageCount"] >= 2
    assert len(detail["messages"]) >= 2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][-1]["role"] == "assistant"

    # 重命名 / 删除
    renamed = client.patch(f"/api/sessions/{session_id}", json={"title": "工时分析-回归"}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["title"] == "工时分析-回归"
    assert data["content"]


def test_scenario_a_dashboard_report(client: TestClient):
    headers = _login(client, "analyst")
    db = _db()
    try:
        employee = _seed_analyst_employee(db)
        employee_id, employee_name = employee.id, employee.name
    finally:
        db.close()

    session = _make_session(client, headers, employee_id)
    data = _send(client, headers, session["id"], "帮我分析下上季度各区域工时效率情况")

    assert data["messageId"] and data["content"], "回答不能为空"
    artifacts = data["artifacts"]
    dashboard = next((a for a in artifacts if a["kind"] == "dashboard"), None)
    report = next((a for a in artifacts if a["kind"] == "report"), None)
    assert dashboard, f"缺少 dashboard 产物: {[a['kind'] for a in artifacts]}"
    assert report, f"缺少 report 产物: {[a['kind'] for a in artifacts]}"

    preview = dashboard["preview"]
    assert preview["type"] == "dashboard"
    assert len(preview["kpis"]) >= 3
    assert len(preview["charts"]) >= 3
    assert {"heatmap", "bar", "line", "pie"}.issubset({c["type"] for c in preview["charts"]})
    assert len(preview["insights"]) >= 3
    # heatmap / bar / line 的 ECharts option 合法性
    charts = {c["type"]: c["option"] for c in preview["charts"]}
    assert charts["heatmap"]["xAxis"]["data"] and charts["heatmap"]["yAxis"]["data"]
    assert "visualMap" in charts["heatmap"] and charts["heatmap"]["series"][0]["data"]
    assert charts["bar"]["xAxis"]["data"] and charts["bar"]["series"]
    assert charts["line"]["xAxis"]["data"] and charts["line"]["series"]
    assert charts["pie"]["series"][0]["data"]

    markdown = report["preview"]["markdown"]
    assert report["preview"]["type"] == "report"
    assert len(markdown) >= 1200, f"报告只有 {len(markdown)} 字"

    steps = data["steps"]
    done_steps = [s for s in steps if s.get("type") == "tool_result" and s.get("status") == "done"]
    assert len(done_steps) >= 4, [(s.get("tool"), s.get("status")) for s in steps]
    ask = next(s for s in steps if s.get("tool") == "chatbi.ask")
    masked = (ask.get("output") or {}).get("maskedColumns") or []
    assert "salary" in masked, f"salary 未脱敏: {masked}"
    assert "salary" in (preview.get("source") or {}).get("maskedColumns", [])
    assert "数据权限" in data["content"] and "salary" in data["content"]

    # 产物持久化 + 列表 + 详情
    listed = client.get(f"/api/artifacts?sessionId={session['id']}", headers=headers).json()
    kinds = {item["kind"] for item in listed["items"]}
    assert {"dashboard", "report"}.issubset(kinds)
    detail = client.get(f"/api/artifacts/{dashboard['artifactId']}", headers=headers)
    assert detail.status_code == 200 and detail.json()["payload"]["type"] == "dashboard"

    # report 无文件时仍可下载 markdown
    download = client.get(f"/api/artifacts/{report['artifactId']}/download", headers=headers)
    assert download.status_code == 200
    assert "attachment" in download.headers.get("content-disposition", "")
    assert len(download.text) >= 1200

    # 会话标题与统计
    session_detail = client.get(f"/api/sessions/{session['id']}", headers=headers).json()
    assert session_detail["messageCount"] >= 2
    assert session_detail["employeeId"] == employee_id

    # 审计：chat + 多次 tool_call
    db = _db()
    try:
        audit_actions = [
            a.action
            for a in db.query(AuditEvent).filter(AuditEvent.session_id == session["id"]).all()
        ]
        assert "chat" in audit_actions
        assert audit_actions.count("tool_call") >= 4
    finally:
        db.close()


def test_scenario_a_sse_protocol(client: TestClient):
    headers = _login(client, "analyst")
    db = _db()
    try:
        employee = _seed_analyst_employee(db)
        employee_id = employee.id
    finally:
        db.close()
    session = _make_session(client, headers, employee_id)

    events: list[tuple[str, dict]] = []
    with client.stream(
        "POST",
        f"/api/sessions/{session['id']}/messages",
        json={"content": "帮我分析下上季度各区域工时效率情况"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers.get("cache-control") == "no-cache"
        assert response.headers.get("x-accel-buffering") == "no"
        current = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                current = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and current:
                events.append((current, json.loads(line.split(":", 1)[1].strip())))
                current = None

    kinds = [kind for kind, _ in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert "step" in kinds and "artifact" in kinds and "delta" in kinds
    done = events[-1][1]
    assert done["messageId"] and done["usage"]["steps"] >= 4 and done["latencyMs"] > 0
    artifact_events = [data for kind, data in events if kind == "artifact"]
    assert len(artifact_events) >= 2
    assert {a["kind"] for a in artifact_events} >= {"dashboard", "report"}
    assert all(a["preview"].get("type") for a in artifact_events)
    # step 同 id 先 running 后 done
    step_ids_running = {d["id"] for kind, d in events if kind == "step" and d.get("status") == "running"}
    step_ids_done = {d["id"] for kind, d in events if kind == "step" and d.get("status") == "done"}
    assert step_ids_done and step_ids_done.issubset(step_ids_running)


# --------------------------------------------------------------------------- #
# 场景 C：合同审查 → 风险清单 + 带修订痕迹 docx
# --------------------------------------------------------------------------- #


CONTRACT_LINES = [
    "技术开发与运维服务合同",
    "甲方：华东智造集团有限公司",
    "乙方：汉得灵舟数字科技有限公司",
    "第二条 付款方式",
    "甲方在合同签订后 90 日内向乙方支付合同总价 100% 的款项。",
    "第三条 违约责任",
    "乙方逾期交付的，每逾期一日按合同总额的 1% 支付违约金；甲方逾期付款的，按 0.1‰ 支付违约金。",
    "第四条 争议管辖",
    "协商不成的，任何一方均可向甲方所在地人民法院提起诉讼。",
    "第五条 合同期限与续约",
    "合同期满前 30 日内，如甲方未书面提出异议，本合同自动续约一年。",
    "第六条 责任承担",
    "乙方对第三方索赔、数据泄露承担无限连带责任。",
    "第七条 知识产权",
    "成果的知识产权归属由双方另行协商确定。",
    "第八条 保密义务",
    "保密期限为合同终止后 2 年。",
    "第九条 合同解除",
    "甲方有权单方解除本合同，乙方不得单方解除。",
    "第十条 验收标准",
    "验收以甲方单方书面确认为准。",
    "第十一条 不可抗力",
    "不可抗力包括市场价格波动、供应链中断及乙方供应商违约等情形。",
]


def _build_contract_docx(path: Path) -> None:
    from docx import Document

    doc = Document()
    for line in CONTRACT_LINES:
        doc.add_paragraph(line)
    doc.save(str(path))


def test_scenario_c_contract_docx(client: TestClient):
    headers = _login(client, "analyst")
    db = _db()
    try:
        analyst = _user(db, "analyst")
        employee = _ensure_employee(
            db, analyst.id, "emp_test_contract", "合同审查助手-测试", ["contract-review", "doc-parse", "knowhow-search"]
        )
        employee_id = employee.id
    finally:
        db.close()

    contract_path = _TMP / "test-contract.docx"
    _build_contract_docx(contract_path)
    with contract_path.open("rb") as handle:
        uploaded = client.post(
            "/api/files",
            files={
                "file": (
                    "测试合同.docx",
                    handle,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            headers=headers,
        )
    assert uploaded.status_code == 200, uploaded.text
    file_info = uploaded.json()
    assert file_info["fileId"] and file_info["size"] > 0

    session = _make_session(client, headers, employee_id)
    data = _send(
        client,
        headers,
        session["id"],
        "帮我按公司标准合同规则审查这份合同",
        attachments=[{"fileId": file_info["fileId"]}],
    )
    assert data["content"]
    assert data["approvals"], "JSON 聚合应保留审批记录"
    assert data["approvals"][0]["autoApprove"] is True
    assert data["approvals"][0]["status"] == "approved"
    docx_artifact = next((a for a in data["artifacts"] if a["kind"] == "docx"), None)
    assert docx_artifact, f"缺少 docx 产物: {[a['kind'] for a in data['artifacts']]}"
    preview = docx_artifact["preview"]
    assert preview["type"] == "docx"
    assert preview["title"].startswith("《测试合同》") and "审查报告（修订版）" in preview["title"]
    assert len(preview["redlines"]) >= 6, f"只有 {len(preview['redlines'])} 条 redline"
    assert preview["stats"]["risks"] >= 6
    assert preview["stats"]["high"] >= 2
    assert preview["downloadUrl"] == f"/api/artifacts/{docx_artifact['artifactId']}/download"

    # python-docx 能正常打开；OOXML 修订痕迹存在
    from docx import Document

    path = Path(preview["filePath"])
    assert path.is_file() and path.stat().st_size > 10_000
    reopened = Document(str(path))
    assert len(reopened.paragraphs) > 10
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "<w:ins " in xml and "<w:del " in xml and 'w:author="DataClaw"' in xml
    assert preview["trackedChanges"] is True
    assert preview["verified"]["hasInsertions"] is True

    # 下载接口
    download = client.get(preview["downloadUrl"], headers=headers)
    assert download.status_code == 200
    assert download.content[:2] == b"PK"
    assert "filename*=UTF-8''" in download.headers.get("content-disposition", "")

    # HITL：非流式模式自动通过，但审批与审计必须留痕
    db = _db()
    try:
        approval = db.query(Approval).filter(Approval.session_id == session["id"]).order_by(Approval.created_at.desc()).first()
        assert approval is not None and approval.status == "approved"
        audit_actions = [a.action for a in db.query(AuditEvent).filter(AuditEvent.session_id == session["id"]).all()]
        assert "hitl_approval" in audit_actions
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 兜底 & 权限降级
# --------------------------------------------------------------------------- #


def test_fallback_without_skills(client: TestClient):
    headers = _login(client, "analyst")
    db = _db()
    try:
        analyst = _user(db, "analyst")
        employee = _ensure_employee(db, analyst.id, "emp_test_noskill", "无技能员工-测试", [])
        employee_id = employee.id
    finally:
        db.close()

    session = _make_session(client, headers, employee_id)
    data = _send(client, headers, session["id"], "今天天气怎么样？")
    assert "技能" in data["content"] or "安装" in data["content"]
    assert not data["artifacts"]
    tools = [s.get("tool") for s in data["steps"]]
    assert not tools, tools
    # 会话仍可正常查看
    assert client.get(f"/api/sessions/{session['id']}", headers=headers).status_code == 200


def test_scenario_b_sales_guide(client: TestClient):
    headers = _login(client, "sales")
    import sqlite3

    from app.core.config import DEMO_DB

    conn = sqlite3.connect(str(DEMO_DB))
    try:
        row = conn.execute(
            "SELECT name FROM crm_customer WHERE owner_id='u_sales' ORDER BY contracts_amount DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row, "seed 缺少 sales 名下客户"
    customer = row[0]

    db = _db()
    try:
        employee = db.get(Employee, "emp_sales_1")
        assert employee is not None, "seed 缺少 emp_sales_1"
        employee_id = employee.id
    finally:
        db.close()

    session = _make_session(client, headers, employee_id)
    data = _send(client, headers, session["id"], "我要拜访星海科技，帮我准备拜访指南")
    assert "拜访" in data["content"] and "3 件事" in data["content"]
    # 客户名不存在时的容错：改用当前用户名下客户，并在回答中说明
    assert "不在你负责的客户列表" in data["content"]
    assert "已改用" in data["content"]
    guide = next((a for a in data["artifacts"] if a["kind"] == "html"), None)
    assert guide, f"缺少 html 拜访指南: {[a['kind'] for a in data['artifacts']]}"
    preview = guide["preview"]
    assert preview["type"] == "html"
    html = preview["html"]
    assert len(html.encode("utf-8")) < 60 * 1024
    assert "客户 360" in html and "话术要点" in html and "潜在需求预判" in html
    assert preview["meta"]["customer"] and preview["meta"]["customer"] != "星海科技"
    assert preview["meta"]["externalSimulated"] is True
    tool_names = [s.get("tool") for s in data["steps"]]
    assert tool_names[:4] == [
        "sales_intel.customer_360",
        "web_search.query",
        "knowledge_search.query",
        "sales_intel.build_guide",
    ]


def test_scenario_c_default_sample_has_risks(client: TestClient):
    """无附件 → 使用 seed 样例合同（risk_hint 融合），必须 ≥6 条风险且含 high。"""
    headers = _login(client, "legal")
    session = _make_session(client, headers, "emp_legal_1")
    data = _send(client, headers, session["id"], "帮我按照公司标准合同规则审查这份合同")
    docx_artifact = next((a for a in data["artifacts"] if a["kind"] == "docx"), None)
    assert docx_artifact, f"缺少 docx 产物: {[a['kind'] for a in data['artifacts']]}"
    preview = docx_artifact["preview"]
    assert len(preview["redlines"]) >= 6, f"样例合同只有 {len(preview['redlines'])} 条风险"
    assert preview["stats"]["high"] >= 2
    assert preview["title"].startswith("《") and "审查报告（修订版）" in preview["title"]
    assert "请按照" not in preview["title"]
    assert data["content"].startswith("合同审查完成")
    analyze = next(s for s in data["steps"] if s.get("tool") == "contract_review.analyze")
    assessments = (analyze.get("output") or {}).get("categoryAssessments") or []
    assert len(assessments) >= 8, "应逐类给出评估结论"

    db = _db()
    try:
        approval = db.query(Approval).filter(Approval.session_id == session["id"]).order_by(Approval.created_at.desc()).first()
        assert approval is not None and approval.status == "approved"
    finally:
        db.close()


def test_approval_timeout_cancels_not_hangs(client: TestClient):
    """流式审批超时必须自动取消并收尾（不能永远挂起）。"""
    import app.core.config as cfg

    headers = _login(client, "legal")
    session = _make_session(client, headers, "emp_legal_1")
    old_timeout = cfg.SSE_QUEUE_TIMEOUT
    cfg.SSE_QUEUE_TIMEOUT = 1.5
    events: list[tuple[str, dict]] = []
    try:
        with client.stream(
            "POST",
            f"/api/sessions/{session['id']}/messages",
            json={"content": "帮我按照公司标准合同规则审查这份合同"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            current = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    current = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and current:
                    events.append((current, json.loads(line.split(":", 1)[1].strip())))
                    current = None
    finally:
        cfg.SSE_QUEUE_TIMEOUT = old_timeout

    assert events[-1][0] == "done"
    approvals = [data for kind, data in events if kind == "approval"]
    assert any(a.get("decision") == "timeout" for a in approvals), approvals
    content = "".join(data.get("text", "") for kind, data in events if kind == "delta")
    assert "超时" in content or "跳过" in content
    db = _db()
    try:
        approval = db.query(Approval).filter(Approval.session_id == session["id"]).order_by(Approval.created_at.desc()).first()
        assert approval is not None and approval.status == "rejected"
        timeout_audit = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.session_id == session["id"],
                AuditEvent.action == "hitl_approval",
            )
            .all()
        )
        assert any((event.detail or {}).get("decision") == "timeout" for event in timeout_audit)
    finally:
        db.close()


def test_permission_denied_is_explainable(client: TestClient):
    headers = _login(client, "sales")
    db = _db()
    try:
        sales = _user(db, "sales")
        employee = _ensure_employee(db, sales.id, "emp_test_sales_chatbi", "销售问数-测试", ["chatbi"])
        employee_id = employee.id
    finally:
        db.close()

    session = _make_session(client, headers, employee_id)
    data = _send(client, headers, session["id"], "帮我分析上季度各区域工时效率情况")
    assert data["content"]
    assert "无权" in data["content"] or "权限" in data["content"] or "未授权" in data["content"]
    assert "可见的表" in data["content"] or "授权" in data["content"]
    tools = [(s.get("tool"), s.get("status")) for s in data["steps"]]
    assert any(tool for tool, status in tools if status in ("error", "denied")), tools

    db = _db()
    try:
        denied = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.session_id == session["id"],
                AuditEvent.action == "tool_call",
                AuditEvent.result == "denied",
            )
            .all()
        )
        assert denied, "权限拒绝必须写审计 result=denied"
        assert any((event.risk or "") == "high" for event in denied)
    finally:
        db.close()
