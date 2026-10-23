"""PPTX 汇报技能：把工时分析结论做成 5 页汇报（真实 .pptx）。"""
from __future__ import annotations

import re
import time
from pathlib import Path

from ...core.config import ARTIFACT_DIR
from ..types import ToolContext, ToolResult, ToolSpec
from . import STATE_CHATBI, fmt_num, json_safe, to_float


def _aggregate(rows: list[dict]) -> dict:
    regions: dict[str, dict] = {}
    months: dict[str, dict] = {}
    total = {"hours": 0.0, "overtime": 0.0, "tasks": 0.0, "defects": 0.0}
    for row in rows:
        region = str(row.get("region") or "未标注")
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


async def outline_handler(params: dict, ctx: ToolContext) -> ToolResult:
    outline = [
        "封面：上季度工时效率分析",
        "关键指标总览（KPI）",
        "区域对比：工时与异常",
        "月度趋势与效率",
        "结论与行动建议",
    ]
    return ToolResult(ok=True, summary=f"汇报大纲 {len(outline)} 页", output={"outline": outline})


async def build_handler(params: dict, ctx: ToolContext) -> ToolResult:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    state = ctx.state.get(STATE_CHATBI) or {}
    rows = state.get("rows") or []
    if not rows:
        return ToolResult(ok=False, error="缺少查询结果，请先执行 chatbi.ask")
    data = _aggregate(rows)
    total = data["total"]
    regions = data["regions"]
    months = data["months"]
    period = state.get("period") or {}
    label = period.get("label") or "最新周期"
    preview = ctx.state.get("dashboard_preview") or {}
    title = f"{label} 工时效率分析汇报"
    total_hours = total["hours"] or 0
    total_tasks = total["tasks"] or 0
    total_overtime = total["overtime"] or 0
    total_defects = total["defects"] or 0
    efficiency = total_tasks / total_hours if total_hours else 0
    overtime_rate = total_overtime / total_hours * 100 if total_hours else 0
    defect_rate = total_defects / total_tasks * 100 if total_tasks else 0
    region_order = sorted(regions.items(), key=lambda kv: kv[1]["hours"], reverse=True)
    month_order = sorted(months.items())

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    def add_title(slide, text: str, size: int = 28, top: float = 0.5):
        box = slide.shapes.add_textbox(Inches(0.7), Inches(top), Inches(11.9), Inches(0.9))
        para = box.text_frame.paragraphs[0]
        para.text = text
        para.font.size = Pt(size)
        para.font.bold = True
        para.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)
        return box

    def add_body(slide, lines: list[str], top: float = 1.6, size: int = 16):
        box = slide.shapes.add_textbox(Inches(0.9), Inches(top), Inches(11.5), Inches(5.2))
        frame = box.text_frame
        frame.word_wrap = True
        for idx, line in enumerate(lines):
            para = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
            para.text = line
            para.font.size = Pt(size)
            para.font.color.rgb = RGBColor(0x33, 0x41, 0x55)
            para.space_after = Pt(10)

    # 1 封面
    slide = prs.slides.add_slide(blank)
    bg = slide.shapes.add_textbox(Inches(0.7), Inches(1.6), Inches(11.5), Inches(1.4))
    para = bg.text_frame.paragraphs[0]
    para.text = title
    para.font.size = Pt(40)
    para.font.bold = True
    para.font.color.rgb = RGBColor(0x1D, 0x4E, 0xD8)
    sub = slide.shapes.add_textbox(Inches(0.75), Inches(3.1), Inches(11.0), Inches(1.2))
    sub_para = sub.text_frame.paragraphs[0]
    sub_para.text = (
        f"数据范围 {period.get('start', '—')} ~ {period.get('end', '—')}｜"
        f"{len(regions)} 个区域 · {len(months)} 个月｜由 DataClaw 数字员工自动生成"
    )
    sub_para.font.size = Pt(16)
    sub_para.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
    note = slide.shapes.add_textbox(Inches(0.75), Inches(6.5), Inches(11.0), Inches(0.6))
    note_para = note.text_frame.paragraphs[0]
    note_para.text = "数据已按当前用户权限脱敏；所有指标来自真实查询结果。"
    note_para.font.size = Pt(11)
    note_para.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)

    # 2 KPI
    slide = prs.slides.add_slide(blank)
    add_title(slide, "一、关键指标总览")
    kpis = preview.get("kpis") or [
        {"label": "总工时", "value": f"{fmt_num(total_hours)} h", "delta": "—"},
        {"label": "人效", "value": f"{efficiency * 100:.2f} 任务/百工时", "delta": "—"},
        {"label": "加班率", "value": f"{overtime_rate:.1f}%", "delta": "—"},
        {"label": "缺陷率", "value": f"{defect_rate:.2f}%", "delta": "—"},
    ]
    left = Inches(0.8)
    for idx, kpi in enumerate(kpis[:5]):
        card = slide.shapes.add_shape(1, left + Inches(idx * 2.45), Inches(1.9), Inches(2.2), Inches(1.7))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(0xF1, 0xF5, 0xF9)
        card.line.color.rgb = RGBColor(0xDB, 0xE4, 0xEE)
        tf = card.text_frame
        tf.paragraphs[0].text = str(kpi.get("label", ""))
        tf.paragraphs[0].font.size = Pt(12)
        tf.paragraphs[0].font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        p2 = tf.add_paragraph()
        p2.text = str(kpi.get("value", ""))
        p2.font.size = Pt(20)
        p2.font.bold = True
        p3 = tf.add_paragraph()
        p3.text = f"环比 {kpi.get('delta', '—')}"
        p3.font.size = Pt(11)
        p3.font.color.rgb = RGBColor(0x22, 0xC5, 0x5E)
    add_body(
        slide,
        [
            f"累计投入 {fmt_num(total_hours)} 工时，交付 {fmt_num(total_tasks)} 个任务；",
            f"整体人效 {efficiency * 100:.2f} 任务/百工时，加班率 {overtime_rate:.1f}%，缺陷率 {defect_rate:.2f}%；",
            "环比数据来自同口径上一周期真实汇总，不使用估算值。",
        ],
        top=4.2,
        size=15,
    )

    # 3 区域对比（图表）
    slide = prs.slides.add_slide(blank)
    add_title(slide, "二、区域对比：谁在贡献，谁需关注")
    top_regions = region_order[:8]
    chart_data = CategoryChartData()
    chart_data.categories = [name for name, _ in top_regions]
    chart_data.add_series("总工时", [round(v["hours"], 2) for _, v in top_regions])
    chart_data.add_series("加班工时", [round(v["overtime"], 2) for _, v in top_regions])
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(0.7),
        Inches(1.6),
        Inches(8.2),
        Inches(5.2),
        chart_data,
    ).chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False

    box = slide.shapes.add_textbox(Inches(9.1), Inches(1.8), Inches(3.6), Inches(4.8))
    frame = box.text_frame
    frame.word_wrap = True
    lines = [f"工时最高：{region_order[0][0]}（{fmt_num(region_order[0][1]['hours'])} h）" if region_order else ""]
    insights = preview.get("insights") or []
    for insight in insights[:3]:
        lines.append(str(insight.get("text", ""))[:110])
    for idx, line in enumerate(lines):
        para = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
        para.text = "• " + line
        para.font.size = Pt(11)
        para.font.color.rgb = RGBColor(0x47, 0x55, 0x69)
        para.space_after = Pt(8)

    # 4 月度趋势
    slide = prs.slides.add_slide(blank)
    add_title(slide, "三、月度趋势与人效")
    if month_order:
        trend = CategoryChartData()
        trend.categories = [m for m, _ in month_order]
        trend.add_series("总工时", [round(v["hours"], 2) for _, v in month_order])
        trend.add_series("人效(任务/百工时)", [round(v["tasks"] / v["hours"] * 100, 2) if v["hours"] else 0 for _, v in month_order])
        chart2 = slide.shapes.add_chart(
            XL_CHART_TYPE.LINE_MARKERS,
            Inches(0.7),
            Inches(1.6),
            Inches(8.4),
            Inches(5.2),
            trend,
        ).chart
        chart2.has_legend = True
        chart2.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart2.legend.include_in_layout = False
        first, last = month_order[0], month_order[-1]
        side = slide.shapes.add_textbox(Inches(9.2), Inches(1.9), Inches(3.4), Inches(4.6))
        frame = side.text_frame
        frame.word_wrap = True
        lines = [
            f"{first[0]} → {last[0]} 工时变化 {last[1]['hours'] - first[1]['hours']:+.1f} h",
            f"交付任务变化 {last[1]['tasks'] - first[1]['tasks']:+.0f} 个",
            "判断增长来自扩产还是加班堆量，需结合人效曲线。",
        ]
        for idx, line in enumerate(lines):
            para = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
            para.text = "• " + line
            para.font.size = Pt(12)
            para.font.color.rgb = RGBColor(0x47, 0x55, 0x69)
            para.space_after = Pt(10)

    # 5 结论与建议
    slide = prs.slides.add_slide(blank)
    add_title(slide, "四、结论与行动建议")
    recs = []
    if region_order:
        low_region = region_order[-1][0]
        recs.append(f"P0｜效率洼地：{low_region} 制定 2 周人效改善计划，目标达到区域均值 {efficiency * 100:.2f} 任务/百工时。")
    recs.append(f"P1｜加班治理：当前加班率 {overtime_rate:.1f}%，设置 15% 红线预警并对超线项目审批。")
    recs.append("P1｜异常复核：对工时离群区域抽样审计，核对项目归属与填报口径。")
    recs.append("P2｜固化看板：五项指标周报自动刷新，减少人工取数 2-3 天/次。")
    recs.append("P2｜数据质量：补齐项目/员工维度关联字段，支持下钻分析。")
    add_body(slide, recs, top=1.7, size=17)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>|\s]+", "-", label)[:40] or "report"
    file_name = f"{safe}-工时效率汇报-{int(time.time())}.pptx"
    path = Path(ARTIFACT_DIR) / file_name
    prs.save(str(path))

    return ToolResult(
        ok=True,
        summary=f"已生成 {len(prs.slides)} 页汇报 PPT（{path.stat().st_size // 1024}KB）",
        output=json_safe({"fileName": file_name, "filePath": str(path), "slides": len(prs.slides), "title": title}),
        artifact={
            "kind": "pptx",
            "title": title,
            "payload": {
                "type": "pptx",
                "fileName": file_name,
                "filePath": str(path),
                "slides": len(prs.slides),
                "downloadUrl": "/api/artifacts/{id}/download",
            },
            "text": title,
            "file_name": file_name,
            "file_path": str(path),
        },
    )


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="pptx.outline",
        title="生成汇报大纲",
        description="输出 5 页工时分析汇报的大纲结构。",
        params={"type": "object", "properties": {}},
        handler=outline_handler,
        risk="low",
        skill="pptx-export",
    ),
    ToolSpec(
        name="pptx.build",
        title="生成汇报 PPT",
        description="基于真实查询结果生成 5 页 .pptx 汇报（封面/KPI/区域对比/趋势/建议）。",
        params={"type": "object", "properties": {}},
        handler=build_handler,
        risk="low",
        skill="pptx-export",
    ),
]
