"""生成 DataClaw 华为 4+1 设计视图 + 全场景时序图（单文件 HTML + Markdown 摘要）。

用法：python tools/build-4plus1.py
输出：
  docs/08-华为4+1设计视图与时序图.html
  docs/08-华为4+1设计视图与时序图.md
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from four_plus_one_data import SCENARIOS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_HTML = ROOT / "docs" / "08-华为4+1设计视图与时序图.html"
OUT_MD = ROOT / "docs" / "08-华为4+1设计视图与时序图.md"

STATUS = {
    "tested": {"label": "已测试", "dot": "🟢", "color": "var(--green)", "soft": "var(--green-soft)"},
    "developed": {"label": "已开发未测试", "dot": "🔵", "color": "var(--blue)", "soft": "var(--blue-soft)"},
    "design": {"label": "初始设计", "dot": "⚫", "color": "var(--ink)", "soft": "var(--ink-soft)"},
}

STATUS_ORDER = {"tested": 0, "developed": 1, "design": 2}


def esc(value: str) -> str:
    return html.escape(str(value), quote=True)


# ---------------------------------------------------------------- SVG 时序图


def text_width(s: str, size: float) -> float:
    w = 0.0
    for ch in s:
        w += size if ord(ch) > 127 else size * 0.57
    return w


def _tokens(s: str) -> list[str]:
    """把中英文拆成可换行单元：ASCII 单词保持完整，CJK 逐字。"""
    out: list[str] = []
    buf = ""
    for ch in s:
        if ord(ch) > 127:
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
        elif ch.isspace():
            if buf:
                out.append(buf)
                buf = ""
            out.append(" ")
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


def _hard_split(token: str, max_w: float, size: float) -> list[str]:
    chunks: list[str] = []
    cur = ""
    for ch in token:
        if cur and text_width(cur + ch, size) > max_w:
            chunks.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        chunks.append(cur)
    return chunks or [token]


def wrap(s: str, max_w: float, size: float, max_lines: int = 2) -> list[str]:
    if not s:
        return [""]
    lines: list[str] = []
    cur = ""
    cur_w = 0.0
    for tok in _tokens(s):
        if tok == " " and not cur:
            continue
        tw = text_width(tok, size)
        if not cur and tw > max_w:
            parts = _hard_split(tok, max_w, size)
            for part in parts[:-1]:
                if len(lines) >= max_lines:
                    break
                lines.append(part)
            cur = parts[-1] if parts else ""
            cur_w = text_width(cur, size)
            continue
        if cur and cur_w + tw > max_w:
            lines.append(cur.rstrip())
            if len(lines) >= max_lines:
                cur = ""
                break
            cur = "" if tok == " " else tok
            cur_w = text_width(cur, size)
        else:
            cur += tok
            cur_w += tw
    if cur and len(lines) < max_lines:
        lines.append(cur.rstrip())
    if not lines:
        lines = [s[:20]]
    if len(lines) == max_lines and text_width("".join(lines), size) < text_width(s, size):
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def short_code(code: str) -> str:
    """时序图里用短路径；完整路径保留在“代码锚点”表格。"""
    for p in ("frontend/src/", "backend/app/", "backend/tests/"):
        code = code.replace(p, "")
    for p in ("pages/admin/", "pages/", "components/", "lib/"):
        code = code.replace(p, "")
    return code


def code_lines(code: str, max_w: float) -> list[str]:
    if not code:
        return []
    code = short_code(code)
    if text_width(code, 8.8) <= max_w:
        return [code]
    mid = len(code) // 2
    for sep in ("/", ".", ":", " "):
        cut = code.rfind(sep, 0, mid + 12)
        if cut > 8:
            return [code[: cut + 1], code[cut + 1 :].lstrip()]
    return [code[:mid], code[mid:]]


def render_svg(sc: dict) -> str:
    parts = sc["participants"]
    n = len(parts)
    step_w = 160
    left = 88
    width = max(820, left * 2 + (n - 1) * step_w)
    xs = {p: left + i * step_w for i, p in enumerate(parts)}
    sid = sc["id"]

    # 计算每个步骤的高度与 y
    layout = []
    y = 96
    for idx, st in enumerate(sc["steps"], start=1):
        kind = st.get("kind", "msg")
        if kind == "note":
            lines = wrap(st["label"], width - 130, 11.5, 3)
            h = 18 + len(lines) * 16 + 12
        elif kind == "self":
            label_lines = wrap(st["label"], 300, 12, 3)
            code = code_lines(st.get("code", ""), 300)
            h = 22 + len(label_lines) * 15 + len(code) * 12 + 16
        else:
            x1, x2 = xs[st["f"]], xs[st["t"]]
            dist = abs(x2 - x1) or step_w
            label_lines = wrap(st["label"], max(220, dist - 10), 11.5, 3)
            code = code_lines(st.get("code", ""), min(360, width - 120))
            h = 18 + len(label_lines) * 15 + 6 + len(code) * 12 + 12
        h = max(h, 46)
        layout.append((idx, st, y, h))
        y += h + 8

    height = y + 54
    out: list[str] = []
    out.append(
        f'<svg class="seq-svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{esc(sc["id"] + " " + sc["title"])}" xmlns="http://www.w3.org/2000/svg">'
    )
    out.append(f"<title>{esc(sc['id'])} {esc(sc['title'])}</title>")
    out.append("<defs>")
    for key in ("tested", "developed", "design"):
        out.append(
            f'<marker id="ar-{sid}-{key}" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">'
            f'<path d="M0,0 L9,4.5 L0,9 z" style="fill:{STATUS[key]["color"]}"/></marker>'
        )
    out.append("</defs>")

    # 顶部分区标题（可选）
    # 参与者框
    for p in parts:
        x = xs[p]
        out.append(f'<rect class="pbox" x="{x - 64}" y="14" width="128" height="34" rx="8"/>')
        out.append(f'<text class="pname" x="{x}" y="36" text-anchor="middle">{esc(p)}</text>')
        out.append(f'<line class="life" x1="{x}" y1="48" x2="{x}" y2="{height - 48}"/>')

    # 步骤
    for idx, st, sy, sh in layout:
        kind = st.get("kind", "msg")
        color = STATUS[st.get("status", "developed")]["color"]
        soft = STATUS[st.get("status", "developed")]["soft"]

        if kind == "note":
            lines = wrap(st["label"], width - 130, 11.5, 3)
            box_h = 18 + len(lines) * 16 + 10
            out.append(f'<rect x="28" y="{sy}" width="{width - 56}" height="{box_h}" rx="8" style="fill:{soft};stroke:var(--border)" stroke-width="1"/>')
            out.append(f'<rect x="28" y="{sy}" width="4" height="{box_h}" rx="2" style="fill:{color}"/>')
            for i, line in enumerate(lines):
                out.append(
                    f'<text class="note-text" x="44" y="{sy + 18 + i * 16}" style="fill:{color}">{esc(line)}</text>'
                )
            if st.get("code"):
                out.append(
                    f'<text class="note-code" x="{width - 38}" y="{sy + 18}" text-anchor="end" style="fill:{color}">{esc(st["code"])}</text>'
                )
            continue

        # 序号
        out.append(f'<circle cx="18" cy="{sy + 20}" r="9" style="fill:{color}"/>')
        out.append(f'<text class="step-no" x="18" y="{sy + 24}" text-anchor="middle">{idx}</text>')

        if kind == "self":
            x = xs[st["f"]]
            label_lines = wrap(st["label"], 300, 12, 3)
            code = code_lines(st.get("code", ""), 300)
            line_y = sy + 20 + (len(label_lines) - 1) * 15
            cx = min(max(x + 52, 190), width - 190)
            for i, line in enumerate(label_lines):
                out.append(
                    f'<text class="msg-text" x="{cx}" y="{line_y - 8 - (len(label_lines) - 1 - i) * 15}" style="fill:{color}">{esc(line)}</text>'
                )
            path = f"M{x + 6},{line_y} L{x + 44},{line_y} L{x + 44},{line_y + 18} L{x + 8},{line_y + 18}"
            out.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.5" marker-end="url(#ar-{sid}-{st.get("status", "developed")})"/>'
            )
            for i, line in enumerate(code):
                out.append(
                    f'<text class="code-text" x="{cx}" y="{line_y + 16 + i * 12}" style="fill:{color}">{esc(line)}</text>'
                )
            continue

        x1, x2 = xs[st["f"]], xs[st["t"]]
        label_lines = wrap(st["label"], max(220, abs(x2 - x1) - 10), 11.5, 3)
        code = code_lines(st.get("code", ""), min(360, width - 120))
        line_y = sy + 20 + (len(label_lines) - 1) * 15
        mid = (x1 + x2) / 2
        cx = min(max(mid, 190), width - 190)
        for i, line in enumerate(label_lines):
            out.append(
                f'<text class="msg-text" x="{mid}" y="{line_y - 8 - (len(label_lines) - 1 - i) * 15}" text-anchor="middle" style="fill:{color}">{esc(line)}</text>'
            )
        dashed = ' stroke-dasharray="5 4"' if st.get("kind") == "return" else ""
        out.append(
            f'<line x1="{x1}" y1="{line_y}" x2="{x2}" y2="{line_y}" stroke="{color}" stroke-width="1.6"{dashed} marker-end="url(#ar-{sid}-{st.get("status", "developed")})"/>'
        )
        for i, line in enumerate(code):
            out.append(
                f'<text class="code-text" x="{cx}" y="{line_y + 15 + i * 12}" text-anchor="middle" style="fill:{color}">{esc(line)}</text>'
            )

    # 底部参与者
    for p in parts:
        x = xs[p]
        out.append(f'<rect class="pbox" x="{x - 64}" y="{height - 48}" width="128" height="30" rx="8"/>')
        out.append(f'<text class="pname" x="{x}" y="{height - 28}" text-anchor="middle">{esc(p)}</text>')

    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- HTML 片段


def pill(status: str) -> str:
    return f'<span class="pill {status}"><span class="dot"></span>{STATUS[status]["label"]}</span>'


def scenario_card(sc: dict) -> str:
    status = sc["status"]
    anchors = []
    seen = set()
    for i, st in enumerate(sc["steps"], start=1):
        code = st.get("code") or ""
        if not code:
            continue
        key = (code, st.get("status"))
        if key in seen:
            continue
        seen.add(key)
        anchors.append(
            f'<tr><td class="num">{i}</td><td>{esc(st["f"])} → {esc(st["t"]) if st["t"] and st["t"] != st["f"] else "自身"}</td>'
            f'<td><code>{esc(code)}</code></td><td>{pill(st.get("status", status))}</td></tr>'
        )
    anchor_html = (
        '<details class="anchors"><summary>代码锚点与排查索引（'
        + str(len(anchors))
        + " 条）</summary><div class=\"table-wrap\"><table class=\"anchor-table\"><thead><tr><th>#</th><th>交互</th><th>代码关键字 / 位置</th><th>状态</th></tr></thead><tbody>"
        + "".join(anchors)
        + "</tbody></table></div></details>"
    )
    note = f'<div class="sc-note">{esc(sc["note"])}</div>' if sc.get("note") else ""
    return f"""
<article class="scenario" id="{sc['id']}" data-kind="{sc['kind']}" data-status="{status}">
  <header class="sc-head">
    <div class="sc-id">{sc['id']}</div>
    <div class="sc-title"><h3>{esc(sc['title'])}</h3><p>{esc(sc['summary'])}</p></div>
    {pill(status)}
  </header>
  <div class="sc-meta"><span class="meta-label">测试证据</span><code>{esc(sc['evidence'])}</code></div>
  {note}
  <div class="seq">{render_svg(sc)}</div>
  {anchor_html}
</article>"""


def group_cards() -> str:
    groups: dict[str, list[dict]] = {}
    for sc in SCENARIOS:
        groups.setdefault(sc["group"], []).append(sc)
    out = []
    for group, items in groups.items():
        kind = items[0]["kind"]
        tested = sum(1 for x in items if x["status"] == "tested")
        developed = sum(1 for x in items if x["status"] == "developed")
        design = sum(1 for x in items if x["status"] == "design")
        meta = " · ".join(filter(None, [
            f"{tested} 已测" if tested else "",
            f"{developed} 待测" if developed else "",
            f"{design} 设计" if design else "",
        ]))
        out.append(f'<section class="sc-group" data-kind="{kind}"><div class="group-head"><h2>{esc(group)}</h2><span>{meta}</span></div>')
        out.extend(scenario_card(sc) for sc in items)
        out.append("</section>")
    return "".join(out)


# ---------------------------------------------------------------- 4+1 视图


def view_logical() -> str:
    layers = [
        ("接入层", "鉴权 / 员工 / 技能 / 策略 / 数据源 / 知识 / 渠道 / 会话 / 产物 / 审计 / 用户 / 公共员工", "api/*.py"),
        ("领域服务层", "employee_service · skill_service · assignment_service · policy_service · datasource_service · knowledge_service · channel_service", "services/*.py"),
        ("Agent 运行时", "runner · planner · registry · approvals · artifacts · llm · sandbox · tools", "runtime/*.py"),
        ("安全与数据", "JWT/PBKDF2 · sqlguard(AST) · policy_mask · audit · SQLite(app.db/demo.db) · 文件工作区", "core/security.py · services/sqlguard.py"),
        ("交付层", "dashboard · report · html 指南 · docx 修订版 · xlsx · pptx", "runtime/tools/*.py"),
    ]
    rows = []
    for i, (name, comps, code) in enumerate(layers):
        rows.append(
            f'<div class="layer"><div class="layer-name">{esc(name)}</div><div class="layer-body"><div class="layer-comps">{esc(comps)}</div><code>{esc(code)}</code></div></div>'
        )
        if i < len(layers) - 1:
            rows.append('<div class="layer-arrow">↓ 依赖方向：上层调用下层，安全网关横切所有数据访问</div>')
    return f'<div class="layer-diagram">{"".join(rows)}</div>'


def view_process() -> str:
    nodes = [
        ("浏览器", "React / SSE", "lib/api.ts:87"),
        ("API", "FastAPI 路由 + JWT", "api/sessions.py:281"),
        ("Runner", "SSE 事件循环", "runner.py:368"),
        ("Planner/LLM", "离线规划 / function-calling", "planner.py:101"),
        ("Registry", "技能→工具注册", "registry.py:100"),
        ("Tool", "真实工具执行", "runner.py:248"),
        ("Guard", "SQL 鉴权/改写/脱敏", "sqlguard.py:294"),
        ("SQLite/FS", "demo.db / app.db / 产物", "artifacts.py:42"),
    ]
    out = ['<div class="pipeline">']
    for i, (name, desc, code) in enumerate(nodes):
        out.append(f'<div class="pipe-node"><b>{esc(name)}</b><span>{esc(desc)}</span><code>{esc(code)}</code></div>')
        if i < len(nodes) - 1:
            out.append('<div class="pipe-arrow">→</div>')
    out.append("</div>")
    out.append(
        '<div class="process-notes">'
        '<div><b>并发模型</b> FastAPI async + SSE 队列；单进程内审批 broker（`runtime/approvals.py:22`）；SQLite WAL；每员工独立工作区。</div>'
        '<div><b>HITL 回路</b> 工具请求审批 → SSE approval → 浏览器 POST decision → broker 唤醒 → 继续/跳过 → 审计。</div>'
        '<div><b>超时</b> 单轮 `SSE_QUEUE_TIMEOUT`、单轮 `MAX_STEPS`、审批 60s；超时发 error + done，不永久挂起。</div>'
        '</div>'
    )
    return "".join(out)


def view_development() -> str:
    modules = [
        ("backend/app/api", "HTTP 接入、鉴权、审计、DTO", "16 个路由模块 / 78 操作"),
        ("backend/app/services", "领域服务、权限求值、SQL 网关、知识/渠道", "8 个服务模块"),
        ("backend/app/runtime", "Agent 循环、Planner、工具注册表、HITL、沙箱", "runtime/*.py + tools/"),
        ("backend/app/seed", "演示数据：工时/CRM/合同/知识/技能", "seed/*.py"),
        ("backend/tests", "核心 API / 运行时 / 数据安全 3 套", "7 + 9 + 8 = 24 用例"),
        ("frontend/src", "React 页面、组件、SSE 客户端", "pages / components / lib"),
        ("lean/", "Go 单二进制精简实现", "3.5k 行 / 5 个 Go test"),
        ("tools/", "验收、截图、4+1 文档生成", "acceptance.py / manual-*.mjs"),
        ("docs/", "PRD / 调研 / 架构 / 验收 / 手册 / 4+1", "01–08"),
    ]
    cards = "".join(
        f'<div class="mod-card"><b>{esc(name)}</b><span>{esc(desc)}</span><code>{esc(code)}</code></div>'
        for name, desc, code in modules
    )
    return f'<div class="mod-grid">{cards}</div><div class="dev-rule"><b>依赖规则</b> api → services / runtime；runtime → services(sqlguard/policy) → models；frontend 只通过 `/api`；lean 独立，不依赖 Python/React。</div>'


def view_physical() -> str:
    return """
<div class="deploy">
  <div class="deploy-col">
    <div class="deploy-title">客户端</div>
    <div class="deploy-node"><b>浏览器</b><span>React SPA · SSE · ECharts</span></div>
    <div class="deploy-node muted"><b>IM / Webhook</b><span>飞书 / 企微 / 钉钉 / API（V1 单轮）</span></div>
  </div>
  <div class="deploy-link">HTTPS / SSE<br/>8787</div>
  <div class="deploy-col">
    <div class="deploy-title">单机私有化（V1）</div>
    <div class="deploy-node primary"><b>Uvicorn :8787</b><span>FastAPI + 静态前端 · 单进程</span><code>scripts/run.cmd</code></div>
    <div class="deploy-row">
      <div class="deploy-node"><b>SQLite</b><span>app.db · demo.db</span></div>
      <div class="deploy-node"><b>文件</b><span>uploads · artifacts · workspaces</span></div>
    </div>
    <div class="deploy-node ext"><b>外部依赖（可选）</b><span>LLM API（OpenAI 兼容）· 搜索/工商数据（V2）</span></div>
  </div>
</div>
<div class="deploy-note"><b>V2 部署形态</b> K8s + 每会话容器（Docker/OpenSandbox/Firecracker）· Postgres · Redis（审批/队列）· OIDC/SSO · IM 长连接 · 对象存储。当前单机形态适合演示、POC、内网小规模落地。</div>
"""


# ---------------------------------------------------------------- 排查与索引


def troubleshooting_rows() -> str:
    rows = [
        ("401 BAD_CREDENTIALS", "X01", "auth.py:53 login() → verify_password", "账号/口令错；看审计 reason=bad_credentials"),
        ("401 UNAUTHORIZED / TOKEN_INVALID", "X01", "core/deps.py:24 get_current_user()", "缺 Bearer 或 JWT 过期；重新登录"),
        ("403 ACCOUNT_DISABLED", "X01", "auth.py:53 login() status 判断", "账号停用；管理员改状态"),
        ("403 FORBIDDEN / 无权修改该员工", "X02", "employee_service.py:55/71 assert_*", "跨用户访问；确认 owner/admin"),
        ("403 SKILL_NOT_APPROVED", "X03", "skills.py:147 install_skill()", "技能未审核；管理员 review"),
        ("403 SKILL_NOT_INSTALLED", "X03", "employee_service.py:55 / skill_service.py:186", "先装技能再绑定员工"),
        ("无权访问表 / 默认拒绝", "X04", "policy_service.py:300 _resolve_impl()", "没有 allow 策略；到生效矩阵加策略"),
        ("仅支持只读查询（DML/多语句）", "X04", "sqlguard.py:294 guard_and_run()", "只允许单条 SELECT/WITH"),
        ("SQL 无法解析", "X04", "sqlguard.py:294 parse", "检查方言/语法；看 deniedReason"),
        ("回答含“无权/可见的表”", "X05", "runner.py:514 组装解释", "看 tool_call 审计 result=denied"),
        ("员工没有工具 / 能力不足", "X06", "planner.py:219 _fallback_text()", "安装技能并绑定员工"),
        ("LLM_FALLBACK", "X07", "runner.py:445 LLM 异常捕获", "检查 Key/BaseURL；已自动降级"),
        ("审批超时 / 拒绝 / APPROVAL_NOT_FOUND", "X08", "approvals.py:67/207", "看 hitl_approval 审计"),
        ("TIMEOUT / MAX_STEPS", "X09", "runner.py:462/465", "拆分任务或调大配置"),
        ("400 暂不支持 / 空检索词", "X10", "knowledge.py:106/218", "换格式或补充检索词"),
        ("401 BAD_TOKEN（渠道）", "X11", "channel_service.py:250 _verify_token()", "核对 X-DataClaw-Token"),
        ("DATASOURCE_INVALID", "X12", "datasource_service.py:390 create()", "检查 .xlsx/路径/首行表头"),
        ("created=0 / skipped=N", "X13", "assignment_service.py:67", "重复分配是幂等，不是错误"),
        ("400 BAD_FILTER / BAD_TIME", "X14", "audit.py:45/78", "检查 risk/from/to 参数"),
        ("404 Artifact/File not found", "X15", "artifacts.py:19 / files.py:32", "确认 id 与归属"),
        ("404 MEMORY_NOT_FOUND", "X16", "employees.py:268 delete_memory()", "记忆不存在或不属于该员工"),
        ("预览身份被重置", "X17", "DataSecurity.tsx:430 identityInitRef", "已修复；刷新前端缓存"),
    ]
    out = []
    for symptom, sid, code, hint in rows:
        out.append(
            f'<tr><td>{esc(symptom)}</td><td><a href="#{esc(sid)}">{esc(sid)}</a></td><td><code>{esc(code)}</code></td><td>{esc(hint)}</td></tr>'
        )
    return "".join(out)


def scenario_index_rows() -> str:
    out = []
    for sc in SCENARIOS:
        anchors = []
        seen = set()
        for st in sc["steps"]:
            code = st.get("code") or ""
            if code and code not in seen:
                seen.add(code)
                anchors.append(code)
        out.append(
            f'<tr><td><a href="#{esc(sc["id"])}">{esc(sc["id"])}</a></td><td>{esc(sc["title"])}</td>'
            f'<td>{pill(sc["status"])}</td><td><code>{esc(" · ".join(anchors[:4]))}{" …" if len(anchors) > 4 else ""}</code></td>'
            f'<td>{esc(sc["evidence"])}</td></tr>'
        )
    return "".join(out)


# ---------------------------------------------------------------- 模板

CSS = """
:root{
  --bg:#f6f4ef; --surface:#ffffff; --surface-2:#efebe2; --surface-3:#e4dfd3;
  --fg:#171a21; --muted:#5d6470; --faint:#8a909b; --border:#dcd6ca;
  --accent:#0c6b63; --accent-2:#3d4cc4; --accent-soft:#e3f2ef;
  --green:#15803d; --green-soft:#eaf7ef;
  --blue:#2563eb; --blue-soft:#eef4ff;
  --ink:#111111; --ink-soft:#f3f3f2;
  --warn:#a95d07; --danger:#b42318;
  --display:"Songti SC","Noto Serif CJK SC","Source Han Serif SC",SimSun,Georgia,serif;
  --body:"PingFang SC","Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei",system-ui,sans-serif;
  --mono:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0f1217; --surface:#161b22; --surface-2:#1e242d; --surface-3:#28303b;
    --fg:#edf0f4; --muted:#a2aab7; --faint:#7b8492; --border:#2b323d;
    --accent:#5fd0c4; --accent-2:#96a4ff; --accent-soft:#17302e;
    --green:#6fdc9d; --green-soft:#14301f;
    --blue:#96a4ff; --blue-soft:#18203c;
    --ink:#f2f4f8; --ink-soft:#1b1f27;
    --warn:#f0b35f; --danger:#ff8d80;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0f1217; --surface:#161b22; --surface-2:#1e242d; --surface-3:#28303b;
  --fg:#edf0f4; --muted:#a2aab7; --faint:#7b8492; --border:#2b323d;
  --accent:#5fd0c4; --accent-2:#96a4ff; --accent-soft:#17302e;
  --green:#6fdc9d; --green-soft:#14301f;
  --blue:#96a4ff; --blue-soft:#18203c;
  --ink:#f2f4f8; --ink-soft:#1b1f27;
  --warn:#f0b35f; --danger:#ff8d80;
  color-scheme:dark;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
html,body{background:var(--bg);color:var(--fg)}
body::before{content:"";position:fixed;inset:0 0 auto 0;height:env(safe-area-inset-top,0px);background:var(--bg);z-index:60;pointer-events:none}
.page{
  background:var(--bg);color:var(--fg);font-family:var(--body);min-height:100%;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-bottom:56px;font-size:14.5px;line-height:1.7;-webkit-font-smoothing:antialiased;
}
.page::before{content:"";position:fixed;inset:env(safe-area-inset-top,0px) 0 auto 0;height:3px;z-index:50;background:linear-gradient(90deg,var(--accent),var(--accent-2))}
a{color:var(--accent);text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--accent) 35%,transparent)}
a:hover{border-bottom-color:var(--accent)}
code,.mono{font-family:var(--mono);font-size:.86em}
code{background:var(--surface-2);padding:.1em .3em;border-radius:4px;word-break:break-word}
img{max-width:100%}
hr{border:0;border-top:1px solid var(--border);margin:30px 0}

.topbar{position:sticky;top:env(safe-area-inset-top,0px);z-index:40;display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:12px 0 11px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:10px;font-weight:700}
.brand .mark{width:28px;height:28px;border-radius:9px;display:grid;place-items:center;background:linear-gradient(145deg,var(--accent),var(--accent-2));color:#fff;font-family:var(--display);font-size:17px}
.brand small{display:block;font-weight:400;font-size:10.5px;color:var(--muted);letter-spacing:.1em;text-transform:uppercase}
.topnav{display:flex;gap:2px;flex-wrap:wrap;margin-left:auto}
.topnav a{font-size:12px;color:var(--muted);padding:5px 8px;border-radius:999px;border:1px solid transparent}
.topnav a:hover{color:var(--fg);background:var(--surface-2);border-bottom-color:transparent}
.theme-btn{border:1px solid var(--border);background:var(--surface);color:var(--muted);border-radius:999px;padding:5px 11px;font-size:12px;cursor:pointer;font-family:var(--body)}
.theme-btn:hover{color:var(--fg);border-color:var(--accent)}

.layout{display:grid;grid-template-columns:238px minmax(0,1fr);gap:40px;max-width:1320px;margin:0 auto}
.toc-aside{padding-top:30px}
.toc-inner{position:sticky;top:74px;max-height:calc(100vh - 100px);overflow:auto;padding-right:4px}
.toc-title{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin:0 0 8px;font-weight:600}
.toc a{display:block;font-size:12px;color:var(--muted);padding:4px 9px;border-left:2px solid transparent;border-bottom:0;line-height:1.45}
.toc a.lv3{padding-left:20px;font-size:11.5px;color:var(--faint)}
.toc a:hover{color:var(--fg);background:var(--surface-2)}
.toc a.on{color:var(--accent);border-left-color:var(--accent);background:var(--accent-soft)}
main{min-width:0;padding-top:26px}

.hero{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:30px 32px 26px;position:relative;overflow:hidden}
.hero::after{content:"";position:absolute;right:-80px;top:-100px;width:300px;height:300px;border-radius:50%;background:radial-gradient(circle,color-mix(in srgb,var(--accent) 15%,transparent),transparent 68%);pointer-events:none}
.hero .kicker{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:700;margin-bottom:12px}
.hero h1{font-family:var(--display);font-size:clamp(30px,4vw,46px);line-height:1.14;margin:0 0 12px;font-weight:700;letter-spacing:.01em;text-wrap:balance}
.hero .lead{max-width:780px;color:var(--muted);font-size:14.5px;line-height:1.8;margin:0}
.hero .meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:18px}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--muted);background:var(--surface-2);border:1px solid var(--border);border-radius:999px;padding:4px 10px}
.chip b{color:var(--fg)}
.legend{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:22px}
.legend-item{display:flex;align-items:center;gap:9px;background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:9px 11px;font-size:12px;color:var(--muted)}
.legend-swatch{width:34px;height:0;border-top:3px solid;position:relative;flex:none}
.legend-swatch::after{content:"";position:absolute;right:-1px;top:-5px;border-left:7px solid;border-top:4px solid transparent;border-bottom:4px solid transparent}
.legend-tested{color:var(--green);border-color:var(--green)}
.legend-tested::after{border-left-color:var(--green)}
.legend-developed{color:var(--blue);border-color:var(--blue)}
.legend-developed::after{border-left-color:var(--blue)}
.legend-design{color:var(--ink);border-color:var(--ink)}
.legend-design::after{border-left-color:var(--ink)}
.legend-item b{color:var(--fg);font-weight:600}

h2.sec{font-family:var(--display);font-size:clamp(24px,2.8vw,31px);line-height:1.25;margin:44px 0 14px;padding-bottom:10px;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:10px;text-wrap:balance}
h2.sec .eyebrow{font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.08em;border:1px solid color-mix(in srgb,var(--accent) 35%,var(--border));border-radius:999px;padding:2px 8px;flex:none}
h3{font-family:var(--display);font-size:18px;margin:26px 0 8px}
p.lead{color:var(--muted);max-width:82ch;margin:0 0 14px}
.view-note{font-size:12.5px;color:var(--muted);margin:8px 0 16px}

.layer-diagram{display:flex;flex-direction:column;gap:0;background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px}
.layer{display:grid;grid-template-columns:130px minmax(0,1fr);gap:14px;align-items:start;padding:12px 14px;background:var(--surface-2);border:1px solid var(--border);border-radius:10px}
.layer-name{font-weight:700;font-size:13px;color:var(--accent)}
.layer-comps{font-size:12.5px;line-height:1.65;color:var(--fg)}
.layer-body code{display:block;margin-top:6px;font-size:10.5px;color:var(--muted);background:transparent;padding:0}
.layer-arrow{font-size:11px;color:var(--faint);text-align:center;padding:5px 0}

.pipeline{display:flex;flex-wrap:wrap;align-items:stretch;gap:6px;background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:14px}
.pipe-node{flex:1 1 120px;min-width:0;background:var(--surface-2);border:1px solid var(--border);border-radius:9px;padding:9px 10px;display:flex;flex-direction:column;gap:3px}
.pipe-node b{font-size:12.5px;color:var(--accent)}
.pipe-node span{font-size:11px;color:var(--muted);line-height:1.4}
.pipe-node code{font-size:9.5px;background:transparent;padding:0;color:var(--faint);word-break:break-all}
.pipe-arrow{display:grid;place-items:center;color:var(--faint);font-size:16px;flex:none}
.process-notes{display:grid;gap:7px;margin-top:12px}
.process-notes div{font-size:12.5px;color:var(--muted);background:var(--surface-2);border-left:3px solid var(--accent);padding:8px 11px;border-radius:0 8px 8px 0}
.process-notes b{color:var(--fg)}

.mod-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.mod-card{background:var(--surface);border:1px solid var(--border);border-radius:11px;padding:11px 12px;display:flex;flex-direction:column;gap:4px;min-width:0}
.mod-card b{font-size:12.5px;color:var(--accent);font-family:var(--mono);word-break:break-all}
.mod-card span{font-size:11.5px;color:var(--muted);line-height:1.5}
.mod-card code{font-size:10px;color:var(--faint);background:transparent;padding:0}
.dev-rule{margin-top:12px;font-size:12.5px;color:var(--muted);background:var(--surface-2);border-left:3px solid var(--accent-2);padding:9px 12px;border-radius:0 8px 8px 0}
.dev-rule b{color:var(--fg)}

.deploy{display:grid;grid-template-columns:1fr auto 1.35fr;gap:14px;align-items:stretch}
.deploy-col{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:12px;display:flex;flex-direction:column;gap:8px;min-width:0}
.deploy-title{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);font-weight:600}
.deploy-node{background:var(--surface-2);border:1px solid var(--border);border-radius:9px;padding:9px 10px;display:flex;flex-direction:column;gap:2px}
.deploy-node b{font-size:12.5px;color:var(--fg)}
.deploy-node span{font-size:11px;color:var(--muted);line-height:1.45}
.deploy-node code{font-size:9.5px;background:transparent;padding:0;color:var(--faint)}
.deploy-node.primary{border-color:color-mix(in srgb,var(--accent) 45%,var(--border));background:var(--accent-soft)}
.deploy-node.ext{border-style:dashed}
.deploy-node.muted{opacity:.85}
.deploy-row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.deploy-link{display:grid;place-items:center;text-align:center;font-size:10.5px;color:var(--faint);line-height:1.5;padding:0 2px}
.deploy-note{margin-top:12px;font-size:12.5px;color:var(--muted);background:var(--surface-2);border-left:3px solid var(--warn);padding:9px 12px;border-radius:0 8px 8px 0}
.deploy-note b{color:var(--fg)}

.filters{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 18px;align-items:center}
.filters .group-label{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);margin-left:6px}
.filters button{border:1px solid var(--border);background:var(--surface);color:var(--muted);border-radius:999px;padding:5px 11px;font-size:12px;cursor:pointer;font-family:var(--body)}
.filters button:hover{color:var(--fg);border-color:var(--accent)}
.filters button.on{background:var(--accent);border-color:var(--accent);color:#fff}
.filters .spacer{flex:1}

.sc-group{margin:26px 0 0}
.group-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;border-bottom:1px solid var(--border);padding-bottom:8px;margin-bottom:12px}
.group-head h2{font-family:var(--display);font-size:21px;margin:0}
.group-head span{font-size:11px;color:var(--faint);white-space:nowrap}
.scenario{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px 16px 12px;margin:0 0 14px;scroll-margin-top:76px}
.scenario[hidden]{display:none!important}
.sc-head{display:grid;grid-template-columns:58px minmax(0,1fr) auto;gap:12px;align-items:start}
.sc-id{font-family:var(--mono);font-size:12px;font-weight:700;color:var(--accent);background:var(--accent-soft);border:1px solid color-mix(in srgb,var(--accent) 30%,var(--border));border-radius:8px;padding:4px 6px;text-align:center}
.sc-title h3{margin:0 0 3px;font-size:16.5px}
.sc-title p{margin:0;font-size:12.5px;color:var(--muted);line-height:1.65}
.pill{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:700;letter-spacing:.02em;padding:3px 8px;border-radius:999px;white-space:nowrap;border:1px solid}
.pill .dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.pill.tested{color:var(--green);background:var(--green-soft);border-color:color-mix(in srgb,var(--green) 35%,transparent)}
.pill.developed{color:var(--blue);background:var(--blue-soft);border-color:color-mix(in srgb,var(--blue) 35%,transparent)}
.pill.design{color:var(--ink);background:var(--ink-soft);border-color:color-mix(in srgb,var(--ink) 25%,transparent)}
.sc-meta{display:flex;gap:7px;align-items:baseline;flex-wrap:wrap;margin:9px 0 0;font-size:11px;color:var(--faint)}
.sc-meta .meta-label{letter-spacing:.08em;text-transform:uppercase;font-size:9.5px}
.sc-meta code{font-size:10.5px;background:var(--surface-2);color:var(--muted);word-break:break-word}
.sc-note{margin:7px 0 0;font-size:11.5px;color:var(--muted);background:var(--surface-2);border-left:3px solid var(--warn);padding:6px 9px;border-radius:0 7px 7px 0}
.seq{margin:10px 0 4px;overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:var(--surface)}
.seq-svg{display:block;min-width:820px}
.pbox{fill:var(--surface-2);stroke:var(--border);stroke-width:1}
.pname{fill:var(--fg);font-family:var(--body);font-size:11.5px;font-weight:600}
.life{stroke:var(--border);stroke-width:1;stroke-dasharray:4 4}
.step-no{fill:#fff;font-family:var(--mono);font-size:9.5px;font-weight:700}
.msg-text{font-family:var(--body);font-size:11.5px}
.code-text{font-family:var(--mono);font-size:8.8px;opacity:.9}
.note-text{font-family:var(--body);font-size:11.5px}
.note-code{font-family:var(--mono);font-size:9px;opacity:.75}
.anchors{margin-top:6px;border-top:1px solid var(--border);padding-top:7px}
.anchors summary{cursor:pointer;font-size:11.5px;color:var(--muted);user-select:none}
.anchors summary:hover{color:var(--accent)}
.anchor-table{min-width:620px;font-size:11.5px}
.anchor-table th{font-size:9.5px;padding:7px 8px}
.anchor-table td{padding:6px 8px}
.anchor-table .num{width:34px;color:var(--faint);font-family:var(--mono)}

.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:var(--surface)}
table{width:100%;border-collapse:collapse;font-size:12.5px;min-width:620px}
thead th{text-align:left;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);background:var(--surface-2);padding:9px 10px;border-bottom:1px solid var(--border);white-space:nowrap;font-weight:600}
tbody td{padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:top;line-height:1.55}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:color-mix(in srgb,var(--accent) 5%,transparent)}
tbody code{font-size:10.5px;background:transparent;padding:0;color:var(--muted)}
.ts-table td:first-child{font-weight:600;color:var(--fg)}

.callout{margin:12px 0;padding:10px 13px;background:var(--surface-2);border-left:3px solid var(--accent);border-radius:0 8px 8px 0;font-size:12.5px;color:var(--muted)}
.callout b{color:var(--fg)}
.warn{border-left-color:var(--warn)}
.foot{max-width:1320px;margin:48px auto 0;padding-top:16px;border-top:1px solid var(--border);font-size:11.5px;color:var(--faint);display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
.to-top{position:fixed;right:max(16px,env(safe-area-inset-right,0px));bottom:max(18px,env(safe-area-inset-bottom,0px));width:36px;height:36px;border-radius:50%;border:1px solid var(--border);background:var(--surface);color:var(--muted);cursor:pointer;display:none;font-size:15px;box-shadow:0 6px 18px rgba(0,0,0,.12);z-index:45}
.to-top.show{display:block}
.to-top:hover{color:var(--accent);border-color:var(--accent)}

@media (max-width:1080px){
  .layout{grid-template-columns:1fr;gap:0}
  .toc-aside{display:none}
  .topnav{display:none}
  .legend{grid-template-columns:1fr}
  .mod-grid{grid-template-columns:1fr 1fr}
  .deploy{grid-template-columns:1fr}
  .deploy-link{padding:2px 0}
}
@media (max-width:640px){
  .page{font-size:14px}
  .hero{padding:22px 18px 20px;border-radius:14px}
  .scenario{padding:12px 12px 10px}
  .sc-head{grid-template-columns:48px minmax(0,1fr);gap:9px}
  .sc-head .pill{grid-column:2;justify-self:start}
  .mod-grid{grid-template-columns:1fr}
  .layer{grid-template-columns:1fr;gap:5px}
  .pipeline{flex-direction:column}
  .pipe-arrow{transform:rotate(90deg)}
  .sc-title h3{font-size:15.5px}
  .seq-svg{min-width:760px}
}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important;animation:none!important}}
"""


def build_html() -> str:
    counts = {
        "all": len(SCENARIOS),
        "normal": sum(1 for s in SCENARIOS if s["kind"] == "normal"),
        "exception": sum(1 for s in SCENARIOS if s["kind"] == "exception"),
        "v2": sum(1 for s in SCENARIOS if s["kind"] == "v2"),
        "tested": sum(1 for s in SCENARIOS if s["status"] == "tested"),
        "developed": sum(1 for s in SCENARIOS if s["status"] == "developed"),
        "design": sum(1 for s in SCENARIOS if s["status"] == "design"),
    }
    toc = [
        ("sec-views", "4+1 视图"),
        ("sec-logical", "逻辑视图"),
        ("sec-process", "过程视图"),
        ("sec-development", "开发视图"),
        ("sec-physical", "物理视图"),
        ("sec-scenarios", "场景视图 · 时序图"),
        ("sec-trouble", "排查速查表"),
        ("sec-index", "场景与代码索引"),
    ]
    toc_html = "".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in toc)
    # 子目录：按 group
    groups = []
    seen = set()
    for sc in SCENARIOS:
        if sc["group"] in seen:
            continue
        seen.add(sc["group"])
        items = [x for x in SCENARIOS if x["group"] == sc["group"]]
        groups.append(
            f'<a class="lv3" href="#{esc(items[0]["id"])}">{esc(sc["group"])} · {len(items)}</a>'
        )
    toc_html += "".join(groups)

    return f"""<title>DataClaw 4+1 设计图</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>{CSS}</style>
<div class="page">
  <header class="topbar">
    <div class="brand"><span class="mark">4+1</span><span>DataClaw<small>华为 4+1 设计视图</small></span></div>
    <nav class="topnav">
      <a href="#sec-logical">逻辑</a><a href="#sec-process">过程</a><a href="#sec-development">开发</a>
      <a href="#sec-physical">物理</a><a href="#sec-scenarios">场景</a><a href="#sec-trouble">排查</a>
    </nav>
    <button class="theme-btn" id="themeBtn" type="button" aria-label="切换深浅色">切换主题</button>
  </header>

  <div class="layout">
    <aside class="toc-aside"><div class="toc-inner">
      <p class="toc-title">目录</p><nav class="toc">{toc_html}</nav>
    </div></aside>

    <main>
      <section class="hero" id="sec-views">
        <div class="kicker">DataClaw V1.0 · 华为 4+1 视图 · 全场景时序</div>
        <h1>DataClaw 4+1 设计图</h1>
        <p class="lead">用逻辑、过程、开发、物理四个视图说明系统“由什么组成、怎么跑、怎么组织、部署在哪”，再用场景视图把正常业务与异常处理逐条展开。每条消息都带代码关键字/位置，便于从现象直接定位实现。</p>
        <div class="meta">
          <span class="chip"><b>{counts['all']}</b> 个场景</span>
          <span class="chip"><b>{counts['normal']}</b> 正常</span>
          <span class="chip"><b>{counts['exception']}</b> 异常</span>
          <span class="chip"><b>{counts['v2']}</b> V2 设计</span>
          <span class="chip"><b>{counts['tested']}</b> 已测试</span>
          <span class="chip"><b>{counts['developed']}</b> 待测</span>
          <span class="chip"><b>{counts['design']}</b> 初始设计</span>
        </div>
        <div class="legend">
          <div class="legend-item"><span class="legend-swatch legend-design"></span><span><b>黑色</b> 初始设计：尚未实现 / V2 路线</span></div>
          <div class="legend-item"><span class="legend-swatch legend-developed"></span><span><b>蓝色</b> 已开发未测试：有代码，无自动化/完整验收</span></div>
          <div class="legend-item"><span class="legend-swatch legend-tested"></span><span><b>绿色</b> 已测试：自动化测试、黑盒验收或明确手工验收</span></div>
        </div>
      </section>

      <h2 class="sec" id="sec-logical"><span class="eyebrow">逻辑</span><span>逻辑视图：分层与组件职责</span></h2>
      <p class="lead">按“接入 → 领域服务 → Agent 运行时 → 安全与数据 → 交付”分层。安全网关不是某一层，而是横切所有数据访问。</p>
      {view_logical()}

      <h2 class="sec" id="sec-process"><span class="eyebrow">过程</span><span>过程视图：一次对话的运行时</span></h2>
      <p class="lead">浏览器只与 API 打交道；API 把会话交给 Runner，Runner 按技能注册工具，Planner/LLM 产步骤，工具经 SQL 网关访问数据，产物落文件，事件通过 SSE 回传。</p>
      {view_process()}

      <h2 class="sec" id="sec-development"><span class="eyebrow">开发</span><span>开发视图：代码组织与依赖规则</span></h2>
      <p class="lead">同一产品两份实现：Python/React 参考实现负责完整能力，Go 单二进制负责演示/POC。两份实现不共享代码，但共享产品契约。</p>
      {view_development()}

      <h2 class="sec" id="sec-physical"><span class="eyebrow">物理</span><span>物理视图：部署与数据落点</span></h2>
      <p class="lead">V1 是单机私有化：一个 Uvicorn 进程 + SQLite + 本地文件目录。V2 才引入容器、Postgres、Redis、OIDC 与 IM 长连接。</p>
      {view_physical()}

      <h2 class="sec" id="sec-scenarios"><span class="eyebrow">场景</span><span>场景视图：正常业务与异常处理时序</span></h2>
      <p class="lead">按“身份与工作台 → 员工 → 技能 → 数据与权限 → 知识/渠道 → 会话与运行时 → 三条标杆场景 → 记忆/审计/交付 → V2”分组。每个场景的每条消息都按状态着色；展开“代码锚点”可复制文件:行号与关键字。</p>
      <div class="callout"><b>状态口径</b> 绿色 = 已有自动化测试 / 26 项黑盒验收 / 明确手工角色验收；蓝色 = 已实现但缺少自动化或完整验收；黑色 = 只有设计/V2 路线。混合场景在标题上取较保守的状态，具体分支颜色以消息为准。</div>
      <div class="filters" id="filters">
        <span class="group-label">类型</span>
        <button type="button" data-kind="all" class="on">全部 {counts['all']}</button>
        <button type="button" data-kind="normal">正常 {counts['normal']}</button>
        <button type="button" data-kind="exception">异常 {counts['exception']}</button>
        <button type="button" data-kind="v2">V2 {counts['v2']}</button>
        <span class="spacer"></span>
        <span class="group-label">状态</span>
        <button type="button" data-status="all" class="on">全部</button>
        <button type="button" data-status="tested">🟢 已测试</button>
        <button type="button" data-status="developed">🔵 已开发未测试</button>
        <button type="button" data-status="design">⚫ 初始设计</button>
      </div>
      <div id="scenarioList">{group_cards()}</div>

      <h2 class="sec" id="sec-trouble"><span class="eyebrow">排查</span><span>排查速查表：从现象到代码</span></h2>
      <p class="lead">先用错误码/现象找到场景，再在时序图里看对应消息的代码锚点。行号会随重构变化，<code>函数名/关键字</code>更稳定。</p>
      <div class="table-wrap"><table class="ts-table"><thead><tr><th>现象 / 错误码</th><th>场景</th><th>第一落点</th><th>排查提示</th></tr></thead><tbody>{troubleshooting_rows()}</tbody></table></div>

      <h2 class="sec" id="sec-index"><span class="eyebrow">索引</span><span>场景与代码索引</span></h2>
      <p class="lead">路径前缀：<code>backend/app/</code> 对应 <code>api/ services/ runtime/ core/</code>；<code>frontend/src/</code> 对应 <code>pages/ components/ lib/</code>；<code>lean/</code> 为 Go 精简实现。</p>
      <div class="table-wrap"><table><thead><tr><th>ID</th><th>场景</th><th>状态</th><th>主要代码锚点</th><th>测试证据</th></tr></thead><tbody>{scenario_index_rows()}</tbody></table></div>

      <div class="callout warn" style="margin-top:22px"><b>使用建议</b> 排查线上问题时，先按错误码在速查表定位场景，再打开该场景的“代码锚点”表格，按 <code>文件:行号 + 函数名</code> 搜索；不要在时序图里从第一条消息开始逐条读，先看红色/蓝色分支对应的异常消息。</div>
    </main>
  </div>

  <footer class="foot">
    <span>DataClaw V1.0 · 华为 4+1 视图 · 2026-10</span>
    <span>状态以当前代码与测试为准；V2 项为设计路线，不代表已交付。</span>
  </footer>
  <button class="to-top" id="toTop" type="button" aria-label="回到顶部">↑</button>
</div>

<script>
(function(){{
  var root=document.documentElement;
  try{{var saved=localStorage.getItem('dc-41-theme'); if(saved) root.dataset.theme=saved;}}catch(e){{}}
  var btn=document.getElementById('themeBtn');
  function label(){{var dark=root.dataset.theme==='dark'||(!root.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);btn.textContent=dark?'浅色':'深色';}}
  label();
  btn.addEventListener('click',function(){{
    var dark=root.dataset.theme==='dark'||(!root.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);
    root.dataset.theme=dark?'light':'dark';
    try{{localStorage.setItem('dc-41-theme',root.dataset.theme);}}catch(e){{}}
    label();
  }});

  var cards=[].slice.call(document.querySelectorAll('.scenario'));
  var kind='all', status='all';
  function apply(){{
    cards.forEach(function(c){{
      var okK = kind==='all' || c.getAttribute('data-kind')===kind;
      var okS = status==='all' || c.getAttribute('data-status')===status;
      c.hidden = !(okK && okS);
    }});
    document.querySelectorAll('.sc-group').forEach(function(g){{
      var any=[].slice.call(g.querySelectorAll('.scenario')).some(function(c){{return !c.hidden;}});
      g.hidden=!any;
    }});
  }}
  document.querySelectorAll('#filters button').forEach(function(b){{
    b.addEventListener('click',function(){{
      var k=b.getAttribute('data-kind'), s=b.getAttribute('data-status');
      if(k){{kind=k;document.querySelectorAll('#filters [data-kind]').forEach(function(x){{x.classList.toggle('on',x===b);}});}}
      if(s){{status=s;document.querySelectorAll('#filters [data-status]').forEach(function(x){{x.classList.toggle('on',x===b);}});}}
      apply();
    }});
  }});

  var top=document.getElementById('toTop');
  window.addEventListener('scroll',function(){{top.classList.toggle('show',window.scrollY>700);}},{{passive:true}});
  top.addEventListener('click',function(){{window.scrollTo({{top:0,behavior:'smooth'}});}});

  var links=[].slice.call(document.querySelectorAll('.toc a'));
  var map={{}};links.forEach(function(a){{map[a.getAttribute('href').slice(1)]=a;}});
  if('IntersectionObserver' in window){{
    var obs=new IntersectionObserver(function(entries){{
      entries.forEach(function(en){{
        if(en.isIntersecting){{links.forEach(function(a){{a.classList.remove('on');}});var a=map[en.target.id];if(a)a.classList.add('on');}}
      }});
    }},{{rootMargin:'-15% 0px -75% 0px'}});
    document.querySelectorAll('h2[id],article[id]').forEach(function(h){{obs.observe(h);}});
  }}
}})();
</script>"""


# ---------------------------------------------------------------- Markdown


def build_md() -> str:
    lines = [
        "# DataClaw 华为 4+1 设计视图与时序图",
        "",
        f"> 配套可视化版本（含 {len(SCENARIOS)} 张内嵌 SVG 时序图）：`docs/08-华为4+1设计视图与时序图.html`",
        "> 状态口径：🟢 已测试 · 🔵 已开发未测试 · ⚫ 初始设计（V2）",
        "",
        "## 1. 4+1 视图总览",
        "",
        "| 视图 | 关注点 | 本仓库落点 |",
        "|---|---|---|",
        "| 逻辑视图 | 系统由哪些组件组成、职责边界 | `backend/app/{api,services,runtime,core}`；`frontend/src` |",
        "| 过程视图 | 一次请求/对话在运行时如何流动 | FastAPI + SSE + Runner + Planner/LLM + Registry + Tools + sqlguard |",
        "| 开发视图 | 代码如何组织、依赖方向 | api → services/runtime → models；frontend 只走 `/api`；`lean/` 独立 |",
        "| 物理视图 | 部署形态与数据落点 | 单机 Uvicorn:8787 + SQLite + 本地文件；V2 容器/Postgres/Redis/OIDC |",
        f"| 场景视图 | 正常与异常场景的时序 | 下文 {len(SCENARIOS)} 个场景，逐条带代码锚点 |",
        "",
        "## 2. 逻辑视图",
        "",
        "```mermaid",
        "flowchart TB",
        "  UI[浏览器 React] --> API[接入层 api/*.py]",
        "  API --> SVC[领域服务 services/*.py]",
        "  API --> RT[Agent 运行时 runtime/*.py]",
        "  RT --> REG[Registry 技能→工具]",
        "  RT --> PLAN[Planner / LLM]",
        "  REG --> TOOL[Tools]",
        "  TOOL --> GUARD[SQL Guard]",
        "  GUARD --> POLICY[Policy Service]",
        "  GUARD --> DB[(SQLite app.db / demo.db)]",
        "  SVC --> DB",
        "  RT --> FS[(uploads / artifacts / workspaces)]",
        "  API --> AUDIT[(audit_events)]",
        "```",
        "",
        "## 3. 过程视图",
        "",
        "```mermaid",
        "sequenceDiagram",
        "  participant B as 浏览器",
        "  participant A as API",
        "  participant R as Runner",
        "  participant P as Planner/LLM",
        "  participant T as Tool",
        "  participant G as SQL Guard",
        "  participant D as SQLite/FS",
        "  B->>A: POST /sessions/{id}/messages",
        "  A->>R: stream_chat()",
        "  R->>P: detect_scenario + plan",
        "  P-->>R: steps / tool_calls",
        "  R->>T: execute_tool()",
        "  T->>G: guard_and_run(sql)",
        "  G->>D: 只读查询",
        "  D-->>G: rows",
        "  G-->>T: masked rows + rules",
        "  T-->>R: ToolResult + artifact",
        "  R-->>A: SSE start/step/artifact/delta/done",
        "  A-->>B: SSE",
        "```",
        "",
        "## 4. 开发视图",
        "",
        "| 模块 | 职责 | 规模/证据 |",
        "|---|---|---|",
        "| `backend/app/api` | HTTP 接入、鉴权、审计、DTO | 16 个路由模块 / 78 操作 |",
        "| `backend/app/services` | 领域服务、权限求值、SQL 网关、知识/渠道 | 8 个服务模块 |",
        "| `backend/app/runtime` | Agent 循环、Planner、工具注册表、HITL、沙箱 | runner/planner/registry/approvals/sandbox + 10 工具 |",
        "| `backend/app/seed` | 演示数据：工时/CRM/合同/知识/技能 | demo.db 28,720 行工时 |",
        "| `backend/tests` | 核心 API / 运行时 / 数据安全 | 7 + 9 + 8 = 24 用例 |",
        "| `frontend/src` | React 页面、组件、SSE 客户端 | 12 页面 + 15 原子组件 |",
        "| `lean/` | Go 单二进制精简实现 | 3.5k 行 / 5 个 Go test |",
        "| `tools/` | 验收、截图、4+1 文档生成 | acceptance.py / manual-*.mjs |",
        "",
        "## 5. 物理视图",
        "",
        "```mermaid",
        "flowchart LR",
        "  B[浏览器] -->|HTTPS/SSE| U[Uvicorn :8787]",
        "  IM[IM/Webhook] -->|POST /channels/{type}/events| U",
        "  U --> DB[(app.db / demo.db)]",
        "  U --> FS[(uploads / artifacts / workspaces)]",
        "  U -.可选.-> LLM[LLM API]",
        "  subgraph V2[V2 部署形态]",
        "    K8S[K8s + 每会话容器]",
        "    PG[(Postgres)]",
        "    REDIS[(Redis)]",
        "    OIDC[OIDC/SSO]",
        "  end",
        "```",
        "",
        "## 6. 场景目录",
        "",
        "| ID | 类型 | 状态 | 场景 | 测试证据 |",
        "|---|---|---|---|---|",
    ]
    for sc in SCENARIOS:
        kind = {"normal": "正常", "exception": "异常", "v2": "V2"}[sc["kind"]]
        lines.append(
            f"| {sc['id']} | {kind} | {STATUS[sc['status']]['dot']} {STATUS[sc['status']]['label']} | {sc['title']} | {sc['evidence']} |"
        )
    lines += [
        "",
        "## 7. 场景与代码锚点",
        "",
        "> 每条锚点格式：`文件:行号 函数/关键字`。行号会随重构变化，函数名更稳定。",
        "",
    ]
    current_group = None
    for sc in SCENARIOS:
        if sc["group"] != current_group:
            current_group = sc["group"]
            lines += ["", f"### {current_group}", ""]
        lines.append(f"#### {sc['id']} {sc['title']}  {STATUS[sc['status']]['dot']}")
        lines.append("")
        lines.append(sc["summary"])
        lines.append("")
        lines.append(f"- 测试证据：{sc['evidence']}")
        if sc.get("note"):
            lines.append(f"- 说明：{sc['note']}")
        lines.append("")
        lines.append("| # | 交互 | 代码锚点 | 状态 |")
        lines.append("|---|---|---|---|")
        for i, st in enumerate(sc["steps"], start=1):
            who = f"{st['f']} → {st['t']}" if st["t"] and st["t"] != st["f"] else (st["f"] or "说明")
            lines.append(
                f"| {i} | {who} | `{st.get('code') or st['label']}` | {STATUS[st.get('status', sc['status'])]['dot']} |"
            )
        lines.append("")
    lines += [
        "",
        "## 8. 排查速查表",
        "",
        "| 现象 / 错误码 | 场景 | 第一落点 | 提示 |",
        "|---|---|---|---|",
    ]
    trouble = [
        ("401 BAD_CREDENTIALS", "X01", "auth.py:53 login() → verify_password", "账号/口令错；看审计 reason=bad_credentials"),
        ("401 UNAUTHORIZED / TOKEN_INVALID", "X01", "core/deps.py:24 get_current_user()", "缺 Bearer 或 JWT 过期；重新登录"),
        ("403 ACCOUNT_DISABLED", "X01", "auth.py:53 login() status 判断", "账号停用；管理员改状态"),
        ("403 FORBIDDEN / 无权修改该员工", "X02", "employee_service.py:55/71 assert_*", "跨用户访问；确认 owner/admin"),
        ("403 SKILL_NOT_APPROVED", "X03", "skills.py:147 install_skill()", "技能未审核；管理员 review"),
        ("403 SKILL_NOT_INSTALLED", "X03", "skill_service.py:186 can_bind_skill()", "先装技能再绑定员工"),
        ("无权访问表 / 默认拒绝", "X04", "policy_service.py:300 _resolve_impl()", "没有 allow 策略；到生效矩阵加策略"),
        ("仅支持只读查询（DML/多语句）", "X04", "sqlguard.py:294 guard_and_run()", "只允许单条 SELECT/WITH"),
        ("SQL 无法解析", "X04", "sqlguard.py:294 parse", "检查方言/语法；看 deniedReason"),
        ("回答含“无权/可见的表”", "X05", "runner.py:514 组装解释", "看 tool_call 审计 result=denied"),
        ("员工没有工具 / 能力不足", "X06", "planner.py:219 _fallback_text()", "安装技能并绑定员工"),
        ("LLM_FALLBACK", "X07", "runner.py:445 LLM 异常捕获", "检查 Key/BaseURL；已自动降级"),
        ("审批超时 / 拒绝 / APPROVAL_NOT_FOUND", "X08", "approvals.py:67/207", "看 hitl_approval 审计"),
        ("TIMEOUT / MAX_STEPS", "X09", "runner.py:462/465", "拆分任务或调大配置"),
        ("400 暂不支持 / 空检索词", "X10", "knowledge.py:106/218", "换格式或补充检索词"),
        ("401 BAD_TOKEN（渠道）", "X11", "channel_service.py:250 _verify_token()", "核对 X-DataClaw-Token"),
        ("DATASOURCE_INVALID", "X12", "datasource_service.py:390 create()", "检查 .xlsx/路径/首行表头"),
        ("created=0 / skipped=N", "X13", "assignment_service.py:67", "重复分配是幂等，不是错误"),
        ("400 BAD_FILTER / BAD_TIME", "X14", "audit.py:45/78", "检查 risk/from/to 参数"),
        ("404 Artifact/File not found", "X15", "artifacts.py:19 / files.py:32", "确认 id 与归属"),
        ("404 MEMORY_NOT_FOUND", "X16", "employees.py:268 delete_memory()", "记忆不存在或不属于该员工"),
        ("预览身份被重置", "X17", "DataSecurity.tsx:430 identityInitRef", "已修复；刷新前端缓存"),
    ]
    for row in trouble:
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "## 9. 状态统计",
        "",
        f"- 场景总数：{len(SCENARIOS)}",
        f"- 🟢 已测试：{sum(1 for s in SCENARIOS if s['status'] == 'tested')}",
        f"- 🔵 已开发未测试：{sum(1 for s in SCENARIOS if s['status'] == 'developed')}",
        f"- ⚫ 初始设计（V2）：{sum(1 for s in SCENARIOS if s['status'] == 'design')}",
        "",
        "> 生成命令：`python tools/build-4plus1.py`。修改场景数据请编辑 `tools/four_plus_one_data.py`。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    html_out = build_html()
    OUT_HTML.write_text(html_out, encoding="utf-8")
    OUT_MD.write_text(build_md(), encoding="utf-8")
    print(f"wrote {OUT_HTML} ({OUT_HTML.stat().st_size / 1024:.1f} KB)")
    print(f"wrote {OUT_MD} ({OUT_MD.stat().st_size / 1024:.1f} KB)")
    print(f"scenarios={len(SCENARIOS)}")


if __name__ == "__main__":
    main()
