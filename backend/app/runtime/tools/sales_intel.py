"""销售情报技能：客户 360 / 拜访指南 / 沟通纪要。

数据全部来自 CRM 真实表，经 sqlguard 行级过滤（sales 只能看自己负责的客户）。
外部情报由 web-search 工具写入当前会话黑板后融合，并在指南中标注来源。
"""
from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime

from .. import resolve_policy, run_query
from ..types import ToolContext, ToolResult, ToolSpec
from . import STATE_SALES, fmt_num, json_safe, to_float

INDUSTRY_PLAYBOOK: dict[str, dict[str, list[str]]] = {
    "软件": {
        "needs": ["数据中台与指标体系整合", "AI 辅助的分析/合同场景提效", "权限治理与审计合规"],
        "strategy": ["以同行业 ROI 案例开场，先对齐业务指标", "邀请 IT/安全负责人共同参与，提前回应私有化与权限问题", "用小范围试点降低决策风险，明确 2-4 周验收标准"],
        "talk": [
            "「我们注意到贵司在数据建设上已有投入，这次更关注提效还是合规？」",
            "「如果 3 周内先用一个业务域跑通，您希望看到哪两个指标变化？」",
            "「私有化部署、字段级脱敏和全链路审计，我们可以先在试点里一起验证。」",
        ],
    },
    "制造": {
        "needs": ["多工厂/供应链数据协同", "订单与交付周期可视化", "出海场景的多币种多语言支持"],
        "strategy": ["从交付周期与库存周转切入，量化损失", "强调与现有 ERP/MES 的对接能力", "安排现场或产线场景演示，邀请业务骨干参与"],
        "talk": [
            "「目前订单交付周期波动主要卡在哪个环节？」",
            "「如果能把排产、库存、交付放在一张大屏上，您最想先看哪一段？」",
            "「我们支持与现有 ERP/MES 对接，不需要替换核心系统。」",
        ],
    },
    "金融": {
        "needs": ["合同与合规条款智能审查", "数据分级分类与权限精细化", "审计留痕与可解释性"],
        "strategy": ["以监管要求与审计证据链开场", "准备私有化部署与模型可解释性说明", "先做合同审查试点，风险低、见效快"],
        "talk": [
            "「贵司合同审查目前主要靠人工还是规则引擎？平均一份要多久？」",
            "「如果审查结果能逐条给出依据和修订建议，法务的复核成本会降到多少？」",
            "「所有数据访问都有审计记录，满足监管追溯要求。」",
        ],
    },
    "零售": {
        "needs": ["会员/订单/库存数据打通", "门店人效与排班优化", "精细化运营与活动复盘"],
        "strategy": ["用坪效/人效双指标建立共同语言", "先选 3-5 家门店做试点对比", "强调活动复盘自动化，减少人工取数"],
        "talk": [
            "「目前门店人效和排班主要看哪些报表？多久更新一次？」",
            "「如果活动复盘能自动生成，运营团队每月能省多少时间？」",
            "「我们可以先选几家门店做 A/B 对比，用数据验证效果。」",
        ],
    },
    "默认": {
        "needs": ["数据整合与报表自动化", "AI 辅助的业务提效", "安全合规与权限治理"],
        "strategy": ["先问业务痛点，再谈方案，避免一上来讲产品", "用可量化指标定义成功标准", "明确试点范围、时间与验收人"],
        "talk": [
            "「这次拜访您最希望解决的一个问题是什么？」",
            "「如果三个月后回头看，什么变化会让您觉得这次投入值得？」",
            "「我们可以先用一份方案和一次演示，帮您判断是否值得推进。」",
        ],
    },
}


def _esc(value: str) -> str:
    return str(value or "").replace("'", "''")


def _is_masked(value) -> bool:
    if not isinstance(value, str):
        return False
    return "*" in value or "…" in value or value.startswith("sha256:")


def _money_text(value) -> str:
    return "已脱敏" if value is None else f"{fmt_num(value)} 元"


def _industry_key(industry: str) -> str:
    for key in INDUSTRY_PLAYBOOK:
        if key != "默认" and (key in industry or industry in key):
            return key
    return "默认"


def _ds_id(ctx: ToolContext) -> str:
    ds = ctx.datasource()
    return getattr(ds, "id", "") if ds is not None else ""


def _query(ctx: ToolContext, sql: str) -> tuple[list[dict], list[str]]:
    result = run_query(ctx.db, ctx.user, _ds_id(ctx), sql, limit=200)
    if not result.get("ok"):
        return [], [result.get("deniedReason") or result.get("error") or "查询失败"]
    return result.get("rows") or [], result.get("maskedColumns") or []


async def customer360_handler(params: dict, ctx: ToolContext) -> ToolResult:
    customer = str(params.get("customer") or params.get("customerName") or "").strip()
    base_select = (
        "SELECT name, industry, scale, region, level, owner_name, annual_revenue, "
        "contracts_amount, last_contact_at, tags FROM crm_customer"
    )
    requested = customer
    fallback_used = False
    rows: list[dict] = []
    masked: list[str] = []
    if customer:
        rows, masked = _query(
            ctx,
            f"{base_select} WHERE name LIKE '%{_esc(customer)}%' "
            f"ORDER BY contracts_amount DESC, last_contact_at DESC LIMIT 5",
        )
    if not rows:
        # 容错：客户名不存在/不在名下时，改用当前用户有权限的客户（合同额最高/最近有联系）
        rows, masked = _query(
            ctx,
            f"{base_select} ORDER BY contracts_amount DESC, last_contact_at DESC LIMIT 5",
        )
        fallback_used = bool(rows)
    if not rows:
        ds = ctx.datasource()
        ds_id = getattr(ds, "id", "") if ds is not None else ""
        policy = resolve_policy(ctx.db, ctx.user, ds_id, "crm_customer")
        reasons = "；".join(policy.get("reasons") or []) or "行级策略未匹配到任何客户"
        policy_ids = [
            r.get("policyId") or r.get("policy_id")
            for r in (policy.get("rulesDetail") or [])
            if isinstance(r, dict)
        ]
        policy_hint = "、".join(p for p in policy_ids if p) or "（无命中策略）"
        return ToolResult(
            ok=False,
            error=(
                f"你的账号下暂无客户数据（{reasons}）。"
                f"请联系管理员分配客户，或检查行级权限策略 {policy_hint}。"
            ),
            output={
                "denied": not policy.get("allowed", True),
                "deniedReason": reasons,
                "policyIds": [p for p in policy_ids if p],
                "availableTables": [],
            },
        )

    profile_row = rows[0]
    customer_name = str(profile_row.get("name") or customer)
    orders, order_masked = _query(
        ctx,
        f"SELECT id AS order_no, amount, stage, sign_date FROM crm_order "
        f"WHERE customer_name='{_esc(customer_name)}' ORDER BY sign_date DESC LIMIT 50",
    )
    if not orders:
        orders, order_masked = _query(
            ctx,
            f"SELECT o.id AS order_no, o.amount, o.stage, o.sign_date FROM crm_order o "
            f"JOIN crm_customer c ON c.id = o.customer_id "
            f"WHERE c.name='{_esc(customer_name)}' ORDER BY o.sign_date DESC LIMIT 50",
        )
    contacts, contact_masked = _query(
        ctx,
        f"SELECT contact_date, channel, summary, next_action FROM crm_contact_log "
        f"WHERE customer_name='{_esc(customer_name)}' ORDER BY contact_date DESC LIMIT 50",
    )
    if not contacts:
        contacts, contact_masked = _query(
            ctx,
            f"SELECT l.contact_date, l.channel, l.summary, l.next_action FROM crm_contact_log l "
            f"JOIN crm_customer c ON c.id = l.customer_id "
            f"WHERE c.name='{_esc(customer_name)}' ORDER BY l.contact_date DESC LIMIT 50",
        )

    total_amount = sum(to_float(o.get("amount")) for o in orders if not _is_masked(o.get("amount")))
    amount_masked = "amount" in (order_masked or [])
    contracts_masked = "contracts_amount" in (masked or [])
    stages: dict[str, int] = {}
    for order in orders:
        stage = str(order.get("stage") or "未标注")
        stages[stage] = stages.get(stage, 0) + 1
    last_contact = contacts[0] if contacts else {}
    last_contact_at = str(profile_row.get("last_contact_at") or last_contact.get("contact_date") or "")
    days_since = None
    try:
        parsed = datetime.fromisoformat(last_contact_at.replace("Z", "")) if last_contact_at else None
        if parsed:
            days_since = (date.today() - parsed.date()).days
    except ValueError:
        days_since = None

    profile = {
        "name": customer_name,
        "industry": str(profile_row.get("industry") or ""),
        "scale": str(profile_row.get("scale") or ""),
        "region": str(profile_row.get("region") or ""),
        "level": str(profile_row.get("level") or ""),
        "ownerName": str(profile_row.get("owner_name") or ""),
        "annualRevenue": None if _is_masked(profile_row.get("annual_revenue")) else to_float(profile_row.get("annual_revenue")),
        "contractsAmount": None if contracts_masked else (to_float(profile_row.get("contracts_amount")) or total_amount),
        "contractsAmountMasked": contracts_masked,
        "lastContactAt": last_contact_at,
        "tags": profile_row.get("tags") or "",
    }
    data = {
        "customer": customer_name,
        "requestedName": requested,
        "fallbackUsed": fallback_used,
        "profile": profile,
        "orders": orders[:20],
        "contacts": contacts[:20],
        "summary": {
            "orderCount": len(orders),
            "totalOrderAmount": None if amount_masked else total_amount,
            "amountMasked": amount_masked,
            "stageDistribution": stages,
            "contactCount": len(contacts),
            "lastContactSummary": str(last_contact.get("summary") or ""),
            "nextAction": str(last_contact.get("next_action") or ""),
            "daysSinceContact": days_since,
            "contractsAmount": profile["contractsAmount"],
            "contractsMasked": contracts_masked,
        },
        "maskedColumns": sorted(set(masked) | set(order_masked) | set(contact_masked)),
        "candidates": [str(r.get("name") or "") for r in rows[1:]],
    }
    ctx.state[STATE_SALES] = data
    prefix = ""
    if fallback_used and requested and requested not in customer_name:
        prefix = f"你提到的『{requested}』不在你的客户列表，已改用你负责的「{customer_name}」作为示例。"
    summary_text = (
        prefix
        + f"{customer_name}：{profile['industry'] or '行业未标注'}，等级 {profile['level'] or '—'}，"
        f"历史订单 {len(orders)} 笔 / 累计 {_money_text(data['summary']['totalOrderAmount'])}，"
        f"最近沟通 {last_contact_at or '无记录'}"
    )
    return ToolResult(ok=True, summary=summary_text, output=json_safe({**data, "rows": len(rows)}))


async def visit_guide_handler(params: dict, ctx: ToolContext) -> ToolResult:
    data = ctx.state.get(STATE_SALES)
    if not data:
        return ToolResult(ok=False, error="请先查询客户 360（sales.customer360）")
    profile = data.get("profile") or {}
    summary = data.get("summary") or {}
    industry_key = _industry_key(str(profile.get("industry") or ""))
    playbook = INDUSTRY_PLAYBOOK[industry_key]
    intel = ctx.state.get("web_results") or []
    internal_hits = ctx.state.get("knowledge") or []

    # 需求预判：结合订单阶段与行业剧本
    needs = list(playbook["needs"])
    stages = summary.get("stageDistribution") or {}
    if any("谈判" in str(s) or "签约" in str(s) for s in stages):
        needs.insert(0, f"推进 {next((s for s in stages if '谈判' in str(s) or '签约' in str(s)), '在谈')} 阶段：准备商务条款与同行业参考价")
    if summary.get("daysSinceContact") is not None and summary["daysSinceContact"] > 30:
        needs.insert(0, f"关系维护：已 {summary['daysSinceContact']} 天未沟通，先确认组织与预算是否变化")
    needs = needs[:4]

    strategy = list(playbook["strategy"])
    if summary.get("contractsAmount", 0) > 0:
        strategy.insert(0, "存量客户：先复盘上一期交付价值，再谈扩容/续约")
    else:
        strategy.insert(0, "新客户：首访目标是拿到业务痛点与决策链，不急于讲方案")
    strategy = strategy[:4]

    talk = list(playbook["talk"])
    guide_html = _render_guide_html(
        profile=profile,
        summary=summary,
        orders=data.get("orders") or [],
        contacts=data.get("contacts") or [],
        needs=needs,
        strategy=strategy,
        talk=talk,
        intel=intel,
        internal_hits=internal_hits,
        masked=data.get("maskedColumns") or [],
    )
    title = f"{profile.get('name', '客户')} 拜访指南"
    payload = {
        "type": "html",
        "title": title,
        "html": guide_html,
        "meta": {
            "customer": profile.get("name"),
            "industry": profile.get("industry"),
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "externalSimulated": bool(intel),
        },
    }
    ctx.state["visit_guide"] = payload
    size_kb = len(guide_html.encode("utf-8")) / 1024
    return ToolResult(
        ok=True,
        summary=f"拜访指南已生成：客户 360 + {len(needs)} 条需求预判 + {len(strategy)} 条沟通策略 + {len(talk)} 段话术（{size_kb:.1f}KB）",
        output=json_safe(
            {
                "title": title,
                "customer": profile.get("name"),
                "needs": needs,
                "strategy": strategy,
                "talk": talk,
                "intelCount": len(intel),
                "htmlSizeKB": round(size_kb, 1),
            }
        ),
        artifact={"kind": "html", "title": title, "payload": json_safe(payload), "text": guide_html},
    )


async def contact_summary_handler(params: dict, ctx: ToolContext) -> ToolResult:
    data = ctx.state.get(STATE_SALES) or {}
    contacts = data.get("contacts") or []
    if not contacts:
        return ToolResult(ok=False, error="没有可总结的沟通记录，请先查询客户 360")
    lines = [f"# {data.get('customer', '客户')} 沟通纪要", ""]
    for contact in contacts[:10]:
        lines.append(f"- {contact.get('contact_date')}｜{contact.get('channel') or '沟通'}：{contact.get('summary') or ''}")
        if contact.get("next_action"):
            lines.append(f"  - 下一步：{contact.get('next_action')}")
    markdown = "\n".join(lines)
    return ToolResult(
        ok=True,
        summary=f"已整理 {min(len(contacts), 10)} 条沟通记录",
        output={"markdown": markdown, "count": min(len(contacts), 10)},
        artifact={
            "kind": "report",
            "title": f"{data.get('customer', '客户')} 沟通纪要",
            "payload": {"type": "report", "markdown": markdown},
            "text": markdown,
        },
    )


def _render_guide_html(*, profile: dict, summary: dict, orders: list[dict], contacts: list[dict], needs: list[str], strategy: list[str], talk: list[str], intel: list[dict], internal_hits: list[dict], masked: list[str]) -> str:
    name = html_lib.escape(str(profile.get("name") or "客户"))
    industry = html_lib.escape(str(profile.get("industry") or "行业未标注"))
    level = html_lib.escape(str(profile.get("level") or "—"))
    region = html_lib.escape(str(profile.get("region") or "—"))
    scale = html_lib.escape(str(profile.get("scale") or "—"))
    owner = html_lib.escape(str(profile.get("ownerName") or "—"))
    last_contact = html_lib.escape(str(profile.get("lastContactAt") or "无记录"))

    def esc_list(items: list[str]) -> str:
        return "".join(f"<li>{html_lib.escape(str(i))}</li>" for i in items)

    order_rows = "".join(
        f"<tr><td>{html_lib.escape(str(o.get('order_no') or '—'))}</td><td>{html_lib.escape(str(o.get('stage') or '—'))}</td>"
        f"<td style='text-align:right'>{fmt_num(o.get('amount'))}</td><td>{html_lib.escape(str(o.get('sign_date') or '—'))}</td></tr>"
        for o in orders[:6]
    ) or "<tr><td colspan='4' style='color:#94a3b8'>暂无可见订单</td></tr>"

    contact_rows = "".join(
        f"<li><b>{html_lib.escape(str(c.get('contact_date') or '—'))}</b>｜{html_lib.escape(str(c.get('channel') or '沟通'))}："
        f"{html_lib.escape(str(c.get('summary') or ''))}"
        + (f"<br/><span style='color:#64748b'>下一步：{html_lib.escape(str(c.get('next_action')))}</span>" if c.get("next_action") else "")
        + "</li>"
        for c in contacts[:5]
    ) or "<li style='color:#94a3b8'>暂无沟通记录</li>"

    intel_items = "".join(
        f"<li><b>{html_lib.escape(str(i.get('title') or ''))}</b>"
        f"<div style='color:#475569;margin-top:4px'>{html_lib.escape(str(i.get('snippet') or '')[:220])}</div>"
        f"<div style='color:#94a3b8;font-size:12px;margin-top:4px'>{html_lib.escape(str(i.get('source') or ''))}"
        f"{' · 模拟情报' if i.get('simulated') else ''}</div></li>"
        for i in (intel or [])[:4]
    ) or "<li style='color:#94a3b8'>未调用外部检索</li>"

    kb_items = "".join(
        f"<li>{html_lib.escape(str(h.get('docName') or ''))}：{html_lib.escape(str(h.get('snippet') or '')[:180])}</li>"
        for h in (internal_hits or [])[:3]
    )

    masked_note = f"<div class='note'>已按数据权限脱敏：{html_lib.escape(', '.join(masked))}</div>" if masked else ""

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{name} 拜访指南</title>
<style>
body{{margin:0;padding:24px;background:#f1f5f9;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#0f172a}}
.wrap{{max-width:760px;margin:0 auto}}
.card{{background:#fff;border-radius:16px;padding:20px 22px;margin-bottom:14px;box-shadow:0 1px 3px rgba(15,23,42,.08)}}
.hero{{background:linear-gradient(135deg,#1d4ed8,#0ea5e9);color:#fff}}
.hero h1{{margin:0 0 6px;font-size:24px}} .hero .sub{{opacity:.9;font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:16px}}
.stat{{background:rgba(255,255,255,.16);border-radius:12px;padding:10px 12px}}
.stat .k{{font-size:12px;opacity:.85}} .stat .v{{font-size:18px;font-weight:700;margin-top:3px}}
h2{{font-size:16px;margin:0 0 12px;padding-left:10px;border-left:4px solid #2563eb}}
ul{{margin:0;padding-left:20px;line-height:1.85;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:8px 6px;border-bottom:1px solid #e2e8f0;text-align:left}} th{{color:#64748b;font-weight:600}}
.pill{{display:inline-block;padding:2px 10px;border-radius:999px;background:#dbeafe;color:#1d4ed8;font-size:12px;margin-right:6px}}
.talk{{background:#f8fafc;border-left:4px solid #0ea5e9;padding:10px 14px;border-radius:8px;margin-bottom:8px;font-size:14px;line-height:1.7}}
.note{{font-size:12px;color:#b45309;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:8px 10px;margin-top:12px}}
.footer{{text-align:center;color:#94a3b8;font-size:12px;margin:18px 0 4px}}
</style></head><body><div class="wrap">
<div class="card hero">
  <h1>{name}</h1>
  <div class="sub">{industry} · {scale} · {region} · 客户等级 {level}｜负责人 {owner}</div>
  <div class="grid">
    <div class="stat"><div class="k">历史订单</div><div class="v">{summary.get('orderCount', 0)} 笔</div></div>
    <div class="stat"><div class="k">累计订单额</div><div class="v">{_money_text(summary.get('totalOrderAmount'))}</div></div>
    <div class="stat"><div class="k">合同额</div><div class="v">{_money_text(summary.get('contractsAmount'))}</div></div>
    <div class="stat"><div class="k">最近沟通</div><div class="v" style="font-size:14px">{last_contact}</div></div>
  </div>
  {masked_note}
</div>

<div class="card"><h2>客户 360° 画像</h2>
  <div><span class="pill">行业：{industry}</span><span class="pill">规模：{scale}</span><span class="pill">地区：{region}</span><span class="pill">等级：{level}</span></div>
  <p style="font-size:14px;line-height:1.8;color:#334155;margin:12px 0 6px">
  最近一次沟通：{html_lib.escape(str(summary.get('lastContactSummary') or '暂无记录'))}
  {('｜已 ' + str(summary.get('daysSinceContact')) + ' 天未联系') if summary.get('daysSinceContact') is not None else ''}
  </p>
  <table><thead><tr><th>订单号</th><th>阶段</th><th style="text-align:right">金额</th><th>签约日期</th></tr></thead>
  <tbody>{order_rows}</tbody></table>
</div>

<div class="card"><h2>近期沟通记录</h2><ul>{contact_rows}</ul></div>

<div class="card"><h2>潜在需求预判</h2><ul>{esc_list(needs)}</ul></div>

<div class="card"><h2>沟通策略</h2><ul>{esc_list(strategy)}</ul></div>

<div class="card"><h2>话术要点</h2>
  {''.join(f'<div class="talk">{html_lib.escape(t)}</div>' for t in talk)}
</div>

<div class="card"><h2>外部情报（公开信息 / 模拟）</h2><ul>{intel_items}</ul></div>

{'<div class="card"><h2>内部知识库参考</h2><ul>' + kb_items + '</ul></div>' if kb_items else ''}

<div class="footer">由 DataClaw 数字员工自动生成 · 内外数据交叉关联 · 敏感字段已按权限处理</div>
</div></body></html>"""


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="sales.customer360",
        title="生成客户 360 画像",
        description="查询 CRM 客户、历史订单、沟通记录与合同额，形成客户 360° 画像（行级权限生效）。",
        params={
            "type": "object",
            "properties": {
                "customer": {"type": "string", "description": "客户名称（可为空，默认取负责客户中合同额最高者）"},
            },
        },
        handler=customer360_handler,
        risk="low",
        skill="sales-intel",
    ),
    ToolSpec(
        name="sales.visit_guide",
        title="生成销售拜访指南",
        description="融合客户 360、外部情报与内部方法论，生成结构化 HTML 拜访指南（画像+需求预判+策略+话术）。",
        params={"type": "object", "properties": {}},
        handler=visit_guide_handler,
        risk="low",
        skill="sales-intel",
    ),
    ToolSpec(
        name="sales.contact_summary",
        title="整理沟通纪要",
        description="把 CRM 沟通记录整理为可复盘的沟通纪要与下一步动作。",
        params={"type": "object", "properties": {}},
        handler=contact_summary_handler,
        risk="low",
        skill="sales-intel",
    ),
]
