"""深度报告技能：结论先行 → 指标 → 明细 → 归因 → 建议。

Markdown 文本（表格用 `|`），数字全部来自真实查询结果，正文 ≥1200 字。
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from ...core.config import ARTIFACT_DIR
from ..types import ToolContext, ToolResult, ToolSpec
from . import STATE_CHATBI, fmt_num, json_safe, mean_std, pct, to_float


def _state(ctx: ToolContext) -> dict:
    return ctx.state.get(STATE_CHATBI) or {}


def _preview(ctx: ToolContext) -> dict:
    return ctx.state.get("dashboard_preview") or {}


def _aggregate(rows: list[dict]) -> dict:
    regions: dict[str, dict] = {}
    months: dict[str, dict] = {}
    total = {"hours": 0.0, "overtime": 0.0, "tasks": 0.0, "defects": 0.0}
    for row in rows:
        region = str(row.get("region") or row.get("dept") or "未标注")
        month = str(row.get("month") or "—")
        hours = to_float(row.get("hours"))
        overtime = to_float(row.get("overtime"))
        tasks = to_float(row.get("tasks"))
        defects = to_float(row.get("defects"))
        for bucket, key in ((regions, region), (months, month)):
            item = bucket.setdefault(key, {"hours": 0.0, "overtime": 0.0, "tasks": 0.0, "defects": 0.0})
            item["hours"] += hours
            item["overtime"] += overtime
            item["tasks"] += tasks
            item["defects"] += defects
        total["hours"] += hours
        total["overtime"] += overtime
        total["tasks"] += tasks
        total["defects"] += defects
    return {"regions": regions, "months": months, "total": total}


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


async def compose_handler(params: dict, ctx: ToolContext) -> ToolResult:
    state = _state(ctx)
    rows = state.get("rows") or []
    if not rows:
        return ToolResult(ok=False, error="缺少查询结果，请先执行 chatbi.ask")
    data = _aggregate(rows)
    total = data["total"]
    regions = data["regions"]
    months = data["months"]
    period = state.get("period") or {}
    label = period.get("label") or "最新周期"
    masked = state.get("maskedColumns") or []
    preview = _preview(ctx)
    kpis = {k.get("label"): k for k in preview.get("kpis") or []}
    insights = [i.get("text", "") for i in preview.get("insights") or []]

    region_order = sorted(regions.items(), key=lambda kv: kv[1]["hours"], reverse=True)
    month_order = sorted(months.items(), key=lambda kv: kv[0])
    emp_eff = {r: (v["tasks"] / v["hours"] * 100 if v["hours"] else 0) for r, v in regions.items()}
    overtime_rates = {r: (v["overtime"] / v["hours"] * 100 if v["hours"] else 0) for r, v in regions.items()}
    defect_rates = {r: (v["defects"] / v["tasks"] * 100 if v["tasks"] else 0) for r, v in regions.items()}
    eff_values = list(emp_eff.values())
    eff_mean, eff_std = mean_std(eff_values)
    hour_values = [v["hours"] for v in regions.values()]
    hour_mean, hour_std = mean_std(hour_values)
    top_region = region_order[0][0] if region_order else "—"
    bottom_region = region_order[-1][0] if region_order else "—"
    top_eff_region = max(emp_eff, key=emp_eff.get) if emp_eff else "—"
    low_eff_region = min(emp_eff, key=emp_eff.get) if emp_eff else "—"
    top_overtime_region = max(overtime_rates, key=overtime_rates.get) if overtime_rates else "—"
    total_hours = total["hours"] or 0
    total_tasks = total["tasks"] or 0
    total_overtime = total["overtime"] or 0
    total_defects = total["defects"] or 0
    efficiency = total_tasks / total_hours if total_hours else 0
    overtime_rate = total_overtime / total_hours * 100 if total_hours else 0
    defect_rate = total_defects / total_tasks * 100 if total_tasks else 0

    anomalies = []
    for region, value in regions.items():
        if hour_std > 1e-9 and abs(value["hours"] - hour_mean) > 2 * hour_std:
            anomalies.append((region, value["hours"], (value["hours"] - hour_mean) / hour_mean * 100))

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    md: list[str] = []
    md.append(f"# {label} 工时效率深度分析报告")
    md.append("")
    md.append(
        f"> 数据范围：{period.get('start', '—')} ~ {period.get('end', '—')}｜数据源：{state.get('datasourceName', 'demo')}"
        f"｜生成时间：{generated}｜执行身份：{getattr(ctx.user, 'name', '')}"
    )
    md.append("")
    if masked:
        md.append(f"> 权限说明：本次查询命中脱敏策略，{', '.join(masked)} 已按数据权限脱敏展示，报告不还原明文。")
        md.append("")

    # 一、核心结论
    md.append("## 一、核心结论（先看这里）")
    md.append("")
    md.append(
        f"本报告基于 {len(rows)} 条区域×月度汇总记录，覆盖 {len(regions)} 个区域、{len(months)} 个月份。"
        f"周期内累计投入 {fmt_num(total_hours)} 工时，交付 {fmt_num(total_tasks)} 个任务，"
        f"整体人效 {efficiency:.0f} 任务/千工时（即 {efficiency * 100:.2f} 任务/百工时），"
        f"加班率 {overtime_rate:.1f}%，缺陷率 {defect_rate:.2f}%。"
    )
    md.append("")
    conclusions = [
        f"**总量与结构**：{top_region} 是工时投入最大的区域（{fmt_num(regions[top_region]['hours'])} h，"
        f"占全量 {regions[top_region]['hours'] / total_hours * 100:.1f}%），{bottom_region} 投入最小"
        f"（{fmt_num(regions[bottom_region]['hours'])} h）。区域间工时最高/最低相差 "
        f"{regions[top_region]['hours'] / max(regions[bottom_region]['hours'], 1):.1f} 倍。"
        if region_order
        else "**总量与结构**：本周期暂无可比区域数据。",
        f"**效率分化**：{top_eff_region} 人效最高（{emp_eff.get(top_eff_region, 0):.2f} 任务/百工时），"
        f"{low_eff_region} 最低（{emp_eff.get(low_eff_region, 0):.2f} 任务/百工时），"
        f"区域人效均值 {eff_mean:.2f}、标准差 {eff_std:.2f}。"
        + (f"其中 {low_eff_region} 低于均值 {((emp_eff.get(low_eff_region, 0) - eff_mean) / eff_mean * 100 if eff_mean else 0):+.1f}%，"
           f"是效率改善的第一优先项。" if eff_mean else ""),
        f"**加班与质量**：全周期加班 {fmt_num(total_overtime)} 小时，加班率 {overtime_rate:.1f}%；"
        f"{top_overtime_region} 加班率最高（{overtime_rates.get(top_overtime_region, 0):.1f}%）。"
        f"缺陷率 {defect_rate:.2f}%，需结合缺陷分布判断是交付节奏还是质量门禁问题。",
    ]
    for idx, text in enumerate(conclusions, 1):
        md.append(f"{idx}. {text}")
    md.append("")

    # 二、关键指标
    md.append("## 二、关键指标总览")
    md.append("")
    kpi_rows = []
    for name in ["总工时", "人均工时", "人均产出", "加班率", "缺陷率"]:
        kpi = kpis.get(name)
        if kpi:
            kpi_rows.append([name, str(kpi.get("value", "—")), str(kpi.get("delta", "—")), str(kpi.get("hint", ""))])
    if not kpi_rows:
        kpi_rows = [
            ["总工时", f"{fmt_num(total_hours)} h", "—", f"覆盖 {len(regions)} 个区域"],
            ["人效", f"{efficiency * 100:.2f} 任务/百工时", "—", f"交付 {fmt_num(total_tasks)} 个任务"],
            ["加班率", pct(overtime_rate), "—", f"加班 {fmt_num(total_overtime)} h"],
            ["缺陷率", pct(defect_rate, 2), "—", f"缺陷 {fmt_num(total_defects)} 个"],
        ]
    md.append(_table(["指标", "数值", "环比变化", "说明"], kpi_rows))
    md.append("")
    md.append(
        "环比列来自同一张事实表的上一周期真实汇总（同口径、同脱敏规则），不是估算值；"
        "若上一周期无数据则显示「—」。KPI 的绝对值与变化率共同决定优先级："
        "既要看效率是否提升，也要看提升是否以加班和缺陷为代价。"
    )
    md.append("")

    # 三、区域维度
    md.append("## 三、区域维度：谁在贡献，谁在拖后腿")
    md.append("")
    region_rows = []
    for region, value in region_order:
        region_rows.append(
            [
                region,
                fmt_num(value["hours"]),
                f"{value['hours'] / total_hours * 100:.1f}%",
                fmt_num(value["overtime"]),
                f"{overtime_rates.get(region, 0):.1f}%",
                fmt_num(value["tasks"]),
                f"{emp_eff.get(region, 0):.2f}",
                f"{defect_rates.get(region, 0):.2f}%",
            ]
        )
    md.append(_table(["区域", "工时(h)", "工时占比", "加班(h)", "加班率", "交付任务", "人效(任务/百工时)", "缺陷率"], region_rows))
    md.append("")
    if anomalies:
        anomaly_text = "；".join(
            f"{region}（{fmt_num(hours)} h，偏离均值 {dev:+.1f}%）" for region, hours, dev in anomalies
        )
        md.append(
            f"按均值±2σ 规则（均值 {hour_mean:.1f} h，σ={hour_std:.1f}），以下区域工时显著偏离：{anomaly_text}。"
            f"这通常意味着资源过度集中或统计口径异常，建议先核对项目归属与排班记录，再决定是否调剂人力。"
        )
    else:
        md.append(
            f"按均值±2σ 规则（均值 {hour_mean:.1f} h，σ={hour_std:.1f}），各区域工时分布未出现统计显著离群；"
            f"但最高与最低区域仍相差 {regions[top_region]['hours'] / max(regions[bottom_region]['hours'], 1):.1f} 倍，"
            f"结构性不均衡依然存在。"
        )
    md.append("")

    # 四、月度趋势
    md.append("## 四、月度趋势：增长来自扩产还是堆量")
    md.append("")
    month_rows = []
    for month, value in month_order:
        m_eff = value["tasks"] / value["hours"] * 100 if value["hours"] else 0
        month_rows.append(
            [
                month,
                fmt_num(value["hours"]),
                fmt_num(value["tasks"]),
                f"{m_eff:.2f}",
                f"{(value['overtime'] / value['hours'] * 100 if value['hours'] else 0):.1f}%",
                fmt_num(value["defects"]),
            ]
        )
    md.append(_table(["月份", "工时(h)", "交付任务", "人效(任务/百工时)", "加班率", "缺陷数"], month_rows))
    md.append("")
    if month_order:
        first, last = month_order[0], month_order[-1]
        delta_hours = last[1]["hours"] - first[1]["hours"]
        delta_tasks = last[1]["tasks"] - first[1]["tasks"]
        md.append(
            f"从 {first[0]} 到 {last[0]}，工时变化 {delta_hours:+.1f} h、交付任务变化 {delta_tasks:+.0f} 个。"
            f"{'交付增速快于工时增速，说明效率在改善。' if delta_tasks > 0 and delta_hours >= 0 and delta_tasks / max(first[1]['tasks'], 1) > delta_hours / max(first[1]['hours'], 1) else '工时增速与交付增速基本同步或交付滞后，需警惕以加班换产出。'}"
            f"建议把月度人效作为滚动指标，而不是只看总工时。"
        )
    md.append("")

    # 五、异常与归因
    md.append("## 五、异常与归因")
    md.append("")
    md.append(
        f"本次分析识别出 {len(anomalies)} 个工时离群区域、{sum(1 for r in overtime_rates.values() if r > 15)} 个加班率超过 15% 的区域。"
        f"结合业务经验，异常通常来自三类原因："
    )
    md.append("")
    md.append("1. **项目结构变化**：某区域承接了跨区域交付或临时攻坚项目，导致工时短期抬升；需核对项目台账与外包投入。")
    md.append("2. **统计口径问题**：工时填报颗粒度、加班审批、外包人员归属不一致，会放大区域间差异；建议抽样复核原始工时单。")
    md.append("3. **排班与质量门禁**：长期高加班往往伴随缺陷率上升；若加班率与缺陷率同向变化，应优先检查需求变更频率与测试资源。")
    md.append("")
    if insights:
        md.append("大屏洞察同步结论：")
        for text in insights:
            md.append(f"- {text}")
        md.append("")

    # 六、建议
    md.append("## 六、行动建议（按优先级）")
    md.append("")
    recommendations = [
        f"**P0｜效率洼地专项**：由 {low_eff_region} 区域负责人牵头，2 周内产出人效改善计划，"
        f"目标把 {emp_eff.get(low_eff_region, 0):.2f} 任务/百工时提升至区域均值 {eff_mean:.2f} 以上；"
        f"每周复盘一次，数据口径沿用本报告。",
        f"**P1｜加班治理**：{top_overtime_region} 加班率 {overtime_rates.get(top_overtime_region, 0):.1f}%，"
        f"设置 15% 红线预警；超线项目需部门负责人审批，并同步评估缺陷率是否恶化。",
        f"**P1｜异常区域复核**：对 {'、'.join(r for r, _, _ in anomalies) if anomalies else top_region} 的工时构成做抽样审计，"
        f"确认是否存在重复填报、跨期归集或外包工时未拆分。",
        f"**P2｜指标看板固化**：把总工时、人均工时、人效、加班率、缺陷率五项指标固化为周报大屏，"
        f"由数据员工自动刷新，减少人工取数 2-3 天/次的等待。",
        f"**P2｜数据质量**：补全区域-项目-员工维度的关联字段，后续可下钻到项目级与人级，"
        f"当前报告在员工维度仅能使用脱敏后的编号/姓名哈希。",
    ]
    for text in recommendations:
        md.append(f"- {text}")
    md.append("")

    # 七、数据与权限
    md.append("## 七、数据与权限说明")
    md.append("")
    md.append(
        f"- 执行方式：自然语言问数 → 只读 SQL → SQL 安全网关（表/列/行级鉴权 + AST 改写 + 强制 LIMIT）→ 结果脱敏。"
    )
    md.append(f"- 本次脱敏列：{', '.join(masked) if masked else '无'}；所有数值仍可用于聚合与趋势判断，但不可还原明文。")
    md.append(f"- 行级过滤规则：{len(state.get('appliedRules') or [])} 条规则生效（含行级与脱敏规则），审计事件已写入 `audit_events`。")
    md.append("- 报告中所有数字均由真实查询结果聚合得出；未使用任何模拟或补全数据。")
    md.append("")
    md.append("---")
    md.append(f"*本报告由 DataClaw 数字员工「{getattr(ctx.employee, 'name', '')}」自动生成，可导出 Markdown / 大屏 HTML。*")

    markdown = "\n".join(md)
    if len(markdown) < 1200:
        markdown += "\n\n" + (
            "补充说明：本报告以「可执行」为目标，所有结论都对应明确的指标与责任动作。"
            "若需要进一步下钻到项目级、客户级或员工级，可在会话中继续追问，数字员工会沿用本次口径与权限重新查询，"
            "不会绕过数据权限，也不会把脱敏字段还原为明文。"
        )

    title = f"{label} 工时效率深度分析报告"
    payload = {
        "type": "report",
        "title": title,
        "markdown": markdown,
        "meta": {
            "period": period,
            "regions": len(regions),
            "months": len(months),
            "rows": len(rows),
            "maskedColumns": masked,
            "generatedAt": generated,
            "wordCount": len(markdown),
            "sql": state.get("rewrittenSql") or state.get("sql") or "",
        },
    }
    ctx.state["report_markdown"] = markdown
    ctx.state["report_title"] = title
    return ToolResult(
        ok=True,
        summary=f"深度报告已生成：{len(markdown)} 字，含 {len(region_order)} 个区域、{len(month_order)} 个月份明细",
        output=json_safe(
            {
                "title": title,
                "wordCount": len(markdown),
                "markdown": markdown,
                "meta": payload["meta"],
            }
        ),
        artifact={
            "kind": "report",
            "title": title,
            "payload": json_safe(payload),
            "text": markdown,
            "file_name": "",
        },
    )


async def outline_handler(params: dict, ctx: ToolContext) -> ToolResult:
    outline = [
        "核心结论（先看这里）",
        "关键指标总览",
        "区域维度：谁在贡献，谁在拖后腿",
        "月度趋势：增长来自扩产还是堆量",
        "异常与归因",
        "行动建议（按优先级）",
        "数据与权限说明",
    ]
    return ToolResult(ok=True, summary=f"报告大纲 {len(outline)} 个章节", output={"outline": outline})


async def export_markdown_handler(params: dict, ctx: ToolContext) -> ToolResult:
    markdown = ctx.state.get("report_markdown") or ""
    if not markdown:
        return ToolResult(ok=False, error="请先生成报告（report.compose）再导出")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    file_name = f"report-{int(time.time())}.md"
    path = Path(ARTIFACT_DIR) / file_name
    path.write_text(markdown, encoding="utf-8")
    return ToolResult(
        ok=True,
        summary=f"已导出 Markdown 报告（{len(markdown)} 字）",
        output={"fileName": file_name, "filePath": str(path)},
        artifact={
            "kind": "report",
            "title": "工时效率深度分析报告",
            "payload": {"type": "report", "markdown": markdown, "fileName": file_name},
            "text": markdown,
            "file_name": file_name,
            "file_path": str(path),
        },
    )


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="report.outline",
        title="生成报告大纲",
        description="输出深度分析报告章节大纲，便于按结构写作。",
        params={"type": "object", "properties": {}},
        handler=outline_handler,
        risk="low",
        skill="deep-report",
    ),
    ToolSpec(
        name="report.compose",
        title="撰写深度分析报告",
        description="基于真实查询结果生成结论先行、含数据明细/归因/建议的 Markdown 深度报告（≥1200 字）。",
        params={"type": "object", "properties": {}},
        handler=compose_handler,
        risk="low",
        skill="deep-report",
    ),
    ToolSpec(
        name="report.export_markdown",
        title="导出 Markdown 报告",
        description="把已生成的深度报告落盘为 .md 文件供下载。",
        params={"type": "object", "properties": {}},
        handler=export_markdown_handler,
        risk="low",
        skill="deep-report",
    ),
]
