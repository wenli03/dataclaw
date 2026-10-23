"""Dashboard 技能：把真实查询结果算成 KPI + 合法 ECharts option。

只产出 ECharts option JSON（前端直接 setOption），不在服务端渲染图片。
数据来自 chatbi.ask 写入的 ctx.state（同一会话内共享）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import run_query
from ...core.config import ARTIFACT_DIR
from ..types import ToolContext, ToolResult, ToolSpec
from . import STATE_CHATBI, fmt_num, json_safe, mean_std, pct, to_float

COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899"]


def _state(ctx: ToolContext) -> dict:
    return ctx.state.get(STATE_CHATBI) or {}


def _prev_period(period: dict) -> tuple[str, str, str] | None:
    start, end = period.get("start"), period.get("end")
    if not start or not end:
        return None
    try:
        from datetime import date

        sd = date.fromisoformat(start)
        ed = date.fromisoformat(end)
    except Exception:
        return None
    days = (ed - sd).days + 1
    prev_end = sd.fromordinal(sd.toordinal() - 1)
    prev_start = prev_end.fromordinal(prev_end.toordinal() - days + 1)
    return prev_start.isoformat(), prev_end.isoformat(), f"上一周期（{prev_start}~{prev_end}）"


def _sum_query(ctx: ToolContext, ds_id: str, date_col: str, start: str, end: str) -> dict:
    cols = {c.get("name") for c in ctx.state.get("columns_cache", {}).get("worktime_fact", [])}
    hours = "hours" if "hours" in cols else ("work_hours" if "work_hours" in cols else "")
    ot = "overtime_hours" if "overtime_hours" in cols else ("overtime" if "overtime" in cols else "")
    tasks = "delivered_tasks" if "delivered_tasks" in cols else ("tasks" if "tasks" in cols else "")
    defects = "defect_count" if "defect_count" in cols else ("defects" if "defects" in cols else "")
    emp = "employee_id" if "employee_id" in cols else ""
    if not hours or not date_col:
        return {}
    parts = [f"SUM({hours}) AS hours"]
    parts.append(f"SUM({ot}) AS overtime" if ot else "0 AS overtime")
    parts.append(f"SUM({tasks}) AS tasks" if tasks else "0 AS tasks")
    parts.append(f"SUM({defects}) AS defects" if defects else "0 AS defects")
    parts.append(f"COUNT(DISTINCT {emp}) AS employees" if emp else "0 AS employees")
    sql = f"SELECT {', '.join(parts)} FROM worktime_fact WHERE {date_col} BETWEEN '{start}' AND '{end}'"
    result = run_query(ctx.db, ctx.user, ds_id, sql, limit=10)
    if not result.get("ok") or not result.get("rows"):
        return {}
    return result["rows"][0]


def _delta(cur: float, prev: float) -> dict:
    if not prev:
        return {"delta": "—", "trend": "flat"}
    change = (cur - prev) / abs(prev) * 100
    trend = "up" if change > 0.5 else ("down" if change < -0.5 else "flat")
    return {"delta": f"{change:+.1f}%", "trend": trend}


async def build_handler(params: dict, ctx: ToolContext) -> ToolResult:
    state = _state(ctx)
    rows = state.get("rows") or []
    if not rows:
        return ToolResult(ok=False, error="缺少查询结果，请先执行 chatbi.ask")
    ds_id = state.get("datasourceId") or ctx.datasource_id
    period = state.get("period") or {}
    columns_cache = ctx.state.setdefault("columns_cache", {})
    if "worktime_fact" not in columns_cache:
        from .. import columns_of

        columns_cache["worktime_fact"] = columns_of(ctx.db, ds_id or None, "worktime_fact")
    cols = {c.get("name") for c in columns_cache.get("worktime_fact", [])}
    date_col = "work_date" if "work_date" in cols else ("date" if "date" in cols else "")

    # ---------- 明细聚合 ----------
    regions: list[str] = []
    months: list[str] = []
    region_hours: dict[str, float] = {}
    region_overtime: dict[str, float] = {}
    region_tasks: dict[str, float] = {}
    month_hours: dict[str, float] = {}
    month_tasks: dict[str, float] = {}
    total = {"hours": 0.0, "overtime": 0.0, "tasks": 0.0, "defects": 0.0}
    for row in rows:
        region = str(row.get("region") or row.get("dept") or "未标注")
        month = str(row.get("month") or "—")
        hours = to_float(row.get("hours"))
        overtime = to_float(row.get("overtime"))
        tasks = to_float(row.get("tasks"))
        defects = to_float(row.get("defects"))
        if region not in regions:
            regions.append(region)
        if month not in months:
            months.append(month)
        region_hours[region] = region_hours.get(region, 0) + hours
        region_overtime[region] = region_overtime.get(region, 0) + overtime
        region_tasks[region] = region_tasks.get(region, 0) + tasks
        month_hours[month] = month_hours.get(month, 0) + hours
        month_tasks[month] = month_tasks.get(month, 0) + tasks
        total["hours"] += hours
        total["overtime"] += overtime
        total["tasks"] += tasks
        total["defects"] += defects

    regions.sort(key=lambda r: region_hours.get(r, 0), reverse=True)
    months.sort()

    # ---------- 上一周期 KPI（真算同比/环比） ----------
    prev = {"hours": 0.0, "overtime": 0.0, "tasks": 0.0, "defects": 0.0, "employees": 0.0}
    prev_label = ""
    prev_period = _prev_period(period)
    if prev_period and date_col:
        prev_start, prev_end, prev_label = prev_period
        prev_row = _sum_query(ctx, ds_id, date_col, prev_start, prev_end)
        if prev_row:
            for key in prev:
                prev[key] = to_float(prev_row.get(key))

    emp_row = _sum_query(ctx, ds_id, date_col, period.get("start", ""), period.get("end", "")) if date_col else {}
    employees = to_float((emp_row or {}).get("employees"))
    prev_employees = to_float(prev.get("employees"))
    avg_hours = total["hours"] / employees if employees else 0.0
    prev_avg_hours = (prev["hours"] / prev_employees) if prev_employees else 0.0
    efficiency = (total["tasks"] / total["hours"]) if total["hours"] else 0.0
    prev_efficiency = (prev["tasks"] / prev["hours"]) if prev["hours"] else 0.0
    overtime_rate = (total["overtime"] / total["hours"] * 100) if total["hours"] else 0.0
    prev_overtime_rate = (prev["overtime"] / prev["hours"] * 100) if prev["hours"] else 0.0
    defect_rate = (total["defects"] / total["tasks"] * 100) if total["tasks"] else 0.0
    prev_defect_rate = (prev["defects"] / prev["tasks"] * 100) if prev["tasks"] else 0.0
    avg_hours_per_region = total["hours"] / len(regions) if regions else 0.0
    prev_avg_region = (prev["hours"] / len(regions)) if prev["hours"] and regions else 0.0

    kpis = [
        {
            "label": "总工时",
            "value": f"{fmt_num(total['hours'])} h",
            "delta": _delta(total["hours"], prev["hours"])["delta"],
            "trend": _delta(total["hours"], prev["hours"])["trend"],
            "hint": f"覆盖 {len(regions)} 个区域 / {len(months)} 个月",
        },
        {
            "label": "人均工时",
            "value": f"{avg_hours:.1f} h",
            "delta": _delta(avg_hours, prev_avg_hours)["delta"] if prev_avg_hours else "—",
            "trend": _delta(avg_hours, prev_avg_hours)["trend"] if prev_avg_hours else "flat",
            "hint": f"{int(employees) if employees else '—'} 名员工",
        },
        {
            "label": "人均产出",
            "value": f"{efficiency:.2f} 任务/h",            "delta": _delta(efficiency, prev_efficiency)["delta"] if prev_efficiency else "—",
            "trend": _delta(efficiency, prev_efficiency)["trend"] if prev_efficiency else "flat",
            "hint": f"累计交付 {fmt_num(total['tasks'])} 个任务",
        },
        {
            "label": "加班率",
            "value": pct(overtime_rate),
            "delta": _delta(overtime_rate, prev_overtime_rate)["delta"] if prev_overtime_rate else "—",
            "trend": _delta(overtime_rate, prev_overtime_rate)["trend"] if prev_overtime_rate else "flat",
            "goodWhenDown": True,
            "hint": f"加班 {fmt_num(total['overtime'])} h",
        },
        {
            "label": "缺陷率",
            "value": pct(defect_rate, 2),
            "delta": _delta(defect_rate, prev_defect_rate)["delta"] if prev_defect_rate else "—",
            "trend": _delta(defect_rate, prev_defect_rate)["trend"] if prev_defect_rate else "flat",
            "goodWhenDown": True,
            "hint": f"缺陷 {fmt_num(total['defects'])} 个",
        },
    ]

    # ---------- 异常判定：均值 ± 2σ ----------
    region_values = [region_hours[r] for r in regions]
    mean_v, std_v = mean_std(region_values)
    warnings: list[dict] = []
    for r in regions:
        value = region_hours[r]
        if std_v > 1e-9 and abs(value - mean_v) > 2 * std_v:
            warnings.append(
                {
                    "region": r,
                    "value": value,
                    "deviation": (value - mean_v) / mean_v * 100 if mean_v else 0,
                    "direction": "above" if value > mean_v else "below",
                }
            )

    # ---------- 图表 1：热力图 ----------
    heat_data = []
    for region in regions:
        for xi, month in enumerate(months):
            value = 0.0
            for row in rows:
                if str(row.get("region") or row.get("dept") or "未标注") == region and str(row.get("month") or "—") == month:
                    value += to_float(row.get("hours"))
            heat_data.append([xi, regions.index(region), round(value, 2)])
    heat_values = [d[2] for d in heat_data] or [0]
    heatmap = {
        "tooltip": {"position": "top"},
        "grid": {"top": "10%", "left": "12%", "right": "6%", "bottom": "20%", "height": "58%"},
        "xAxis": {"type": "category", "data": months, "splitArea": {"show": True}, "axisLabel": {"fontSize": 11}},
        "yAxis": {"type": "category", "data": regions, "splitArea": {"show": True}, "axisLabel": {"fontSize": 11}},
        "visualMap": {
            "min": min(heat_values),
            "max": max(heat_values),
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": "2%",
            "inRange": {"color": ["#e0f3f8", "#abd9e9", "#74add1", "#4575b4", "#313695"]},
            "textStyle": {"fontSize": 10},
        },
        "series": [
            {
                "name": "工时",
                "type": "heatmap",
                "data": heat_data,
                "label": {"show": True, "fontSize": 9},
                "emphasis": {"itemStyle": {"shadowBlur": 8, "shadowColor": "rgba(0,0,0,0.4)"}},
            }
        ],
    }

    # ---------- 图表 2：区域对比柱状图 + 异常标注 ----------
    mark_points = []
    for warn in warnings:
        idx = regions.index(warn["region"])
        mark_points.append(
            {
                "name": "异常预警",
                "coord": [idx, round(warn["value"], 2)],
                "value": round(warn["value"], 2),
                "itemStyle": {"color": "#ef4444"},
            }
        )
    if not mark_points and regions:
        top = regions[0]
        mark_points.append(
            {
                "name": f"最高（{top}）",
                "coord": [0, round(region_hours[top], 2)],
                "value": round(region_hours[top], 2),
            }
        )
    bar = {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"data": ["总工时", "加班工时"], "top": 0},
        "grid": {"top": "16%", "left": "10%", "right": "5%", "bottom": "10%"},
        "xAxis": {"type": "category", "data": regions, "axisLabel": {"interval": 0, "fontSize": 11}},
        "yAxis": {"type": "value", "name": "小时"},
        "series": [
            {
                "name": "总工时",
                "type": "bar",
                "barMaxWidth": 36,
                "data": [round(region_hours[r], 2) for r in regions],
                "itemStyle": {"borderRadius": [6, 6, 0, 0], "color": "#3b82f6"},
                "markPoint": {"symbolSize": 46, "data": mark_points},
            },
            {
                "name": "加班工时",
                "type": "bar",
                "barMaxWidth": 36,
                "data": [round(region_overtime[r], 2) for r in regions],
                "itemStyle": {"borderRadius": [6, 6, 0, 0], "color": "#f59e0b"},
            },
        ],
    }

    # ---------- 图表 3：月度趋势（工时 / 人效） ----------
    efficiency_months = []
    for month in months:
        h = month_hours.get(month, 0)
        efficiency_months.append(round((month_tasks.get(month, 0) / h * 100), 2) if h else 0)

    line = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": ["总工时", "人效"], "top": 0},
        "grid": {"top": "16%", "left": "10%", "right": "10%", "bottom": "10%"},
        "xAxis": {"type": "category", "boundaryGap": False, "data": months},
        "yAxis": [
            {"type": "value", "name": "小时"},
            {"type": "value", "name": "任务/百工时"},
        ],
        "series": [
            {
                "name": "总工时",
                "type": "line",
                "smooth": True,
                "symbolSize": 7,
                "areaStyle": {"opacity": 0.12},
                "lineStyle": {"width": 3},
                "data": [round(month_hours.get(m, 0), 2) for m in months],
            },
            {
                "name": "人效",
                "type": "line",
                "smooth": True,
                "yAxisIndex": 1,
                "symbolSize": 7,
                "lineStyle": {"width": 3},
                "data": efficiency_months,
            },
        ],
    }

    # ---------- 图表 4：部门占比（真实查询，不 join 未授权表） ----------
    pie_data: list[dict] = []
    dept_col = "dept" if "dept" in cols else ""
    if dept_col and period.get("start") and period.get("end"):
        ds_sql = (
            f"SELECT {dept_col} AS dept, SUM({'hours' if 'hours' in cols else 'work_hours'}) AS hours "
            f"FROM worktime_fact WHERE {date_col} BETWEEN '{period['start']}' AND '{period['end']}' "
            f"GROUP BY {dept_col} ORDER BY hours DESC"
        )
        dept_result = run_query(ctx.db, ctx.user, ds_id, ds_sql, limit=100)
        if dept_result.get("ok"):
            pie_data = [
                {"name": str(r.get("dept") or "未标注"), "value": round(to_float(r.get("hours")), 2)}
                for r in dept_result.get("rows") or []
            ]
    if not pie_data:
        pie_data = [{"name": r, "value": round(region_hours[r], 2)} for r in regions]
    pie = {
        "tooltip": {"trigger": "item", "formatter": "{b}<br/>工时：{c} h（{d}%）"},
        "legend": {"bottom": 0, "type": "scroll"},
        "series": [
            {
                "name": "部门工时占比",
                "type": "pie",
                "radius": ["42%", "68%"],
                "center": ["50%", "45%"],
                "avoidLabelOverlap": True,
                "itemStyle": {"borderRadius": 8, "borderColor": "#fff", "borderWidth": 2},
                "label": {"formatter": "{b}\n{d}%", "fontSize": 11},
                "data": pie_data[:8],
            }
        ],
    }

    # ---------- 洞察（≥3，含异常预警） ----------
    insights: list[dict] = []
    top_region = regions[0] if regions else ""
    if top_region:
        share = region_hours[top_region] / total["hours"] * 100 if total["hours"] else 0
        top_eff = (region_tasks[top_region] / region_hours[top_region] * 100) if region_hours[top_region] else 0
        insights.append(
            {
                "level": "info",
                "text": f"{top_region} 工时最高（{fmt_num(region_hours[top_region])} h，占全量 {share:.1f}%），"
                f"单区域人效 {top_eff:.2f} 任务/百工时。",
            }
        )
    if warnings:
        worst = max(warnings, key=lambda w: abs(w["deviation"]))
        insights.append(
            {
                "level": "danger" if abs(worst["deviation"]) > 25 else "warn",
                "text": f"异常预警：{worst['region']} 工时 {fmt_num(worst['value'])} h，"
                f"偏离区域均值 {mean_v:.1f} h 达 {worst['deviation']:+.1f}%，"
                f"超过均值±2σ（σ={std_v:.1f}）阈值，建议核查排班与项目分配。",
            }
        )
    else:
        dev = 0.0
        if regions and mean_v:
            dev = (region_hours[top_region] - mean_v) / mean_v * 100
        insights.append(
            {
                "level": "warn",
                "text": f"异常监测：区域工时均值 {mean_v:.1f} h、σ={std_v:.1f}；最大偏离为 {top_region} "
                f"{dev:+.1f}%，仍在均值±2σ 区间内，暂无统计显著异常，建议持续观察。",
            }
        )
    if months:
        first, last = months[0], months[-1]
        trend = month_hours.get(last, 0) - month_hours.get(first, 0)
        insights.append(
            {
                "level": "success" if trend >= 0 else "info",
                "text": f"月度趋势：{first}→{last} 工时{'增长' if trend >= 0 else '下降'} {fmt_num(abs(trend))} h，"
                f"同期人效 {efficiency * 100:.2f} 任务/百工时，需结合交付任务量判断是扩产还是加班堆量。",
            }
        )
    if total["hours"]:
        insights.append(
            {
                "level": "warn" if overtime_rate > 15 else "info",
                "text": f"加班率 {overtime_rate:.1f}%（{fmt_num(total['overtime'])} h），缺陷率 {defect_rate:.2f}%；"
                f"{'加班强度偏高，质量风险需关注' if overtime_rate > 15 else '整体处于可控区间'}。",
            }
        )

    masked = state.get("maskedColumns") or []
    title = f"{period.get('label') or '最新周期'} 工时效率分析大屏"
    subtitle = f"数据范围 {period.get('start')} ~ {period.get('end')} · {len(regions)} 个区域 · {len(months)} 个月"
    if masked:
        subtitle += f" · 已脱敏：{', '.join(masked)}"

    preview = {
        "type": "dashboard",
        "title": title,
        "subtitle": subtitle,
        "kpis": kpis,
        "charts": [
            {"id": "c1", "type": "heatmap", "title": "区域 × 月份工时热力图", "option": heatmap},
            {"id": "c2", "type": "bar", "title": "区域工时对比（含异常标注）", "option": bar},
            {"id": "c3", "type": "line", "title": "月度工时与人效趋势", "option": line},
            {"id": "c4", "type": "pie", "title": "部门工时占比", "option": pie},
        ],
        "insights": insights,
        "source": {
            "datasource": state.get("datasourceName") or "demo",
            "sql": state.get("rewrittenSql") or state.get("sql") or "",
            "rows": len(rows),
            "period": period,
            "maskedColumns": masked,
            "appliedRules": state.get("appliedRules") or [],
        },
    }
    ctx.state["dashboard_preview"] = preview

    output = json_safe(
        {
            "title": title,
            "subtitle": subtitle,
            "kpis": kpis,
            "charts": [{"id": c["id"], "type": c["type"], "title": c["title"]} for c in preview["charts"]],
            "chartCount": len(preview["charts"]),
            "insights": insights,
            "maskedColumns": masked,
            "warnings": warnings,
            "period": period,
        }
    )
    artifact = {
        "kind": "dashboard",
        "title": title,
        "payload": json_safe(preview),
        "text": subtitle,
        "file_name": "",
    }
    return ToolResult(
        ok=True,
        summary=f"大屏已生成：{len(kpis)} 个 KPI、{len(preview['charts'])} 张图表、{len(insights)} 条洞察"
        + (f"；已脱敏 {', '.join(masked)}" if masked else ""),
        output=output,
        artifact=artifact,
    )


async def export_html_handler(params: dict, ctx: ToolContext) -> ToolResult:
    state = _state(ctx)
    preview = state.get("dashboard_preview")
    if not preview:
        return ToolResult(ok=False, error="请先生成大屏再导出 HTML")
    html = _render_html(preview)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    file_name = f"dashboard-{int(time.time())}.html"
    path = Path(ARTIFACT_DIR) / file_name
    path.write_text(html, encoding="utf-8")
    return ToolResult(
        ok=True,
        summary=f"已导出 HTML 大屏（{len(html.encode('utf-8')) // 1024} KB）",
        output={"fileName": file_name, "filePath": str(path)},
        artifact={
            "kind": "html",
            "title": preview.get("title") or "工时分析大屏",
            "payload": {"type": "html", "html": html, "title": preview.get("title")},
            "text": "可离线打开的 ECharts 大屏",
            "file_name": file_name,
            "file_path": str(path),
        },
    )


def _render_html(preview: dict) -> str:
    options = [c["option"] for c in preview.get("charts") or []]
    kpis = "".join(
        f'<div class="kpi"><div class="label">{k["label"]}</div><div class="value">{k["value"]}</div>'
        f'<div class="delta">{k.get("delta", "")}</div></div>'
        for k in preview.get("kpis") or []
    )
    insights = "".join(f'<li class="{i.get("level")}">{i.get("text")}</li>' for i in preview.get("insights") or [])
    chart_divs = "".join(f'<div class="chart" id="chart{i}"></div>' for i in range(len(options)))
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<title>{preview.get("title")}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0b1220;color:#e5e7eb;margin:0;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#94a3b8;margin-bottom:18px}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:18px}}
.kpi{{background:linear-gradient(160deg,#111c33,#0f172a);border:1px solid #1f2a44;border-radius:14px;padding:14px}}
.kpi .label{{color:#93a4bd;font-size:12px}} .kpi .value{{font-size:24px;font-weight:700;margin:6px 0}}
.kpi .delta{{color:#22c55e;font-size:12px}}
.charts{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}}
.chart{{background:#0f172a;border:1px solid #1f2a44;border-radius:14px;height:360px}}
ul{{background:#0f172a;border:1px solid #1f2a44;border-radius:14px;padding:14px 14px 14px 30px;line-height:1.8}}
li.warn{{color:#fbbf24}} li.danger{{color:#f87171}} li.success{{color:#34d399}}
</style></head><body>
<h1>{preview.get("title")}</h1><div class="sub">{preview.get("subtitle", "")}</div>
<div class="kpis">{kpis}</div><div class="charts">{chart_divs}</div>
<h3>关键洞察</h3><ul>{insights}</ul>
<script>
const opts={json.dumps(options, ensure_ascii=False)};
opts.forEach((o,i)=>{{const el=document.getElementById('chart'+i); if(el) echarts.init(el).setOption(o);}});
</script></body></html>"""


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="dashboard.build",
        title="生成可视化大屏",
        description="基于真实查询结果生成 KPI、ECharts 热力图/柱状图/折线图/饼图与异常预警洞察。",
        params={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "大屏标题（可选）"},
            },
        },
        handler=build_handler,
        risk="low",
        skill="dashboard-builder",
    ),
    ToolSpec(
        name="dashboard.export_html",
        title="导出 HTML 大屏",
        description="把已生成的大屏导出为可离线打开的 HTML 文件。",
        params={"type": "object", "properties": {}},
        handler=export_html_handler,
        risk="low",
        skill="dashboard-builder",
    ),
]
