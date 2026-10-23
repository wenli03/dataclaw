"""Excel 工具：读取上传表格 / 轻量清洗 / 从查询结果导出 xlsx。

真实生成 .xlsx（openpyxl）：表头样式、冻结窗格、列宽、数字格式，并附带图表。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from ...core.config import ARTIFACT_DIR
from ..types import ToolContext, ToolResult, ToolSpec
from . import STATE_CHATBI, fmt_num, json_safe, to_float


def _chatbi_rows(ctx: ToolContext) -> tuple[list[dict], list[str]]:
    state = ctx.state.get(STATE_CHATBI) or {}
    rows = state.get("rows") or []
    columns = state.get("columns") or (list(rows[0].keys()) if rows else [])
    return rows, columns


def _load_xlsx(path: Path, max_rows: int = 2000) -> tuple[list[str], list[list]]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb.active
    rows: list[list] = []
    headers: list[str] = []
    for idx, row in enumerate(ws.iter_rows(values_only=True)):
        if idx == 0:
            headers = ["" if c is None else str(c) for c in row]
            continue
        if idx > max_rows:
            break
        if all(c is None for c in row):
            continue
        rows.append(["" if c is None else c for c in row])
    wb.close()
    return headers, rows


async def read_handler(params: dict, ctx: ToolContext) -> ToolResult:
    file_id = str(params.get("fileId") or params.get("file_id") or "")
    if not file_id:
        for att in ctx.attachments or []:
            if str(att.get("name") or "").lower().endswith((".xlsx", ".xlsm")):
                file_id = att.get("fileId") or ""
                break
    if not file_id:
        return ToolResult(ok=False, error="请提供 Excel 文件（fileId）或在消息中附带表格")
    from ...models import FileModel

    record = ctx.db.get(FileModel, file_id)
    if record is None:
        return ToolResult(ok=False, error=f"文件不存在：{file_id}")
    path = Path(record.path)
    if not path.exists():
        return ToolResult(ok=False, error="文件已丢失")
    headers, rows = _load_xlsx(path)
    ctx.state["excel"] = {"headers": headers, "rows": rows, "fileId": file_id, "name": record.name}
    return ToolResult(
        ok=True,
        summary=f"已读取《{record.name}》：{len(rows)} 行 × {len(headers)} 列",
        output={
            "fileId": file_id,
            "name": record.name,
            "headers": headers,
            "rowCount": len(rows),
            "preview": rows[:20],
        },
    )


async def transform_handler(params: dict, ctx: ToolContext) -> ToolResult:
    data = ctx.state.get("excel")
    if not data:
        return ToolResult(ok=False, error="请先执行 excel.read 读取表格")
    headers: list[str] = list(data.get("headers") or [])
    rows: list[list] = [list(r) for r in data.get("rows") or []]
    ops = params.get("operations") or ["dedupe", "trim", "sum"]
    if "trim" in ops:
        rows = [[c.strip() if isinstance(c, str) else c for c in row] for row in rows]
    if "dedupe" in ops:
        seen = set()
        unique = []
        for row in rows:
            key = tuple(str(c) for c in row)
            if key not in seen:
                seen.add(key)
                unique.append(row)
        rows = unique
    totals = {}
    if "sum" in ops:
        for idx, header in enumerate(headers):
            values = [to_float(row[idx]) for row in rows if idx < len(row)]
            if values and any(v != 0 for v in values):
                totals[header] = round(sum(values), 2)
    ctx.state["excel"]["rows"] = rows
    return ToolResult(
        ok=True,
        summary=f"清洗完成：{len(rows)} 行；数值列合计 {len(totals)} 个",
        output={"rowCount": len(rows), "operations": ops, "totals": totals, "headers": headers},
    )


async def export_handler(params: dict, ctx: ToolContext) -> ToolResult:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    state = ctx.state.get(STATE_CHATBI) or {}
    rows, columns = _chatbi_rows(ctx)
    source_name = "工时分析明细"
    if not rows:
        excel = ctx.state.get("excel") or {}
        rows = [dict(zip(excel.get("headers") or [], row)) for row in excel.get("rows") or []]
        columns = list(excel.get("headers") or [])
        source_name = excel.get("name") or "表格明细"
    if not rows:
        return ToolResult(ok=False, error="没有可导出的数据，请先查询或读取表格")

    wb = Workbook()
    ws = wb.active
    ws.title = "数据明细"
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True, size=10.5)
    thin = Side(style="thin", color="D9E2EC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.append([str(c) for c in columns])
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    for row in rows:
        ws.append([row.get(col) for col in columns])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.border = border
    for idx in range(1, len(columns) + 1):
        ws.column_dimensions[get_column_letter(idx)].width = max(12, min(28, len(str(columns[idx - 1])) * 2 + 6))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(max(len(columns), 1))}{ws.max_row}"

    # 汇总 sheet
    summary = wb.create_sheet("指标汇总")
    summary.append(["指标", "数值"])
    summary["A1"].font = header_font
    summary["A1"].fill = header_fill
    summary["B1"].font = header_font
    summary["B1"].fill = header_fill
    total_hours = sum(to_float(r.get("hours")) for r in rows)
    total_tasks = sum(to_float(r.get("tasks")) for r in rows)
    total_overtime = sum(to_float(r.get("overtime")) for r in rows)
    total_defects = sum(to_float(r.get("defects")) for r in rows)
    summary.append(["总工时(h)", round(total_hours, 1)])
    summary.append(["交付任务", round(total_tasks, 1)])
    summary.append(["加班工时(h)", round(total_overtime, 1)])
    summary.append(["缺陷数", round(total_defects, 1)])
    summary.append(["人效(任务/百工时)", round(total_tasks / total_hours * 100, 2) if total_hours else 0])
    summary.append(["加班率", f"{(total_overtime / total_hours * 100 if total_hours else 0):.1f}%"])
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 18

    # 图表（若存在 region / hours）
    if "region" in columns and "hours" in columns:
        chart = BarChart()
        chart.type = "col"
        chart.title = "区域工时对比"
        chart.y_axis.title = "小时"
        chart.x_axis.title = "区域"
        data_ref = Reference(ws, min_col=columns.index("hours") + 1, min_row=1, max_row=min(ws.max_row, 30))
        cats = Reference(ws, min_col=columns.index("region") + 1, min_row=2, max_row=min(ws.max_row, 30))
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats)
        chart.height = 8
        chart.width = 16
        ws.add_chart(chart, f"{get_column_letter(len(columns) + 2)}2")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>|\s]+", "-", source_name)[:40] or "export"
    file_name = f"{safe}-{int(time.time())}.xlsx"
    path = Path(ARTIFACT_DIR) / file_name
    wb.save(str(path))

    return ToolResult(
        ok=True,
        summary=f"已导出 Excel：{len(rows)} 行 × {len(columns)} 列（{path.stat().st_size // 1024}KB）",
        output=json_safe(
            {
                "fileName": file_name,
                "filePath": str(path),
                "rowCount": len(rows),
                "columnCount": len(columns),
                "totals": {"hours": round(total_hours, 1), "tasks": round(total_tasks, 1)},
            }
        ),
        artifact={
            "kind": "xlsx",
            "title": f"{source_name} Excel 导出",
            "payload": {
                "type": "xlsx",
                "fileName": file_name,
                "filePath": str(path),
                "rowCount": len(rows),
                "downloadUrl": "/api/artifacts/{id}/download",
            },
            "text": f"共 {len(rows)} 行",
            "file_name": file_name,
            "file_path": str(path),
        },
    )


# ---- data-cleaner 技能（轻量包装，避免装了技能却没有工具） ----


async def clean_profile_handler(params: dict, ctx: ToolContext) -> ToolResult:
    data = ctx.state.get("excel") or {}
    rows = data.get("rows") or []
    headers = data.get("headers") or []
    if not rows:
        return ToolResult(ok=False, error="请先读取表格（excel.read）")
    nulls: dict[str, int] = {}
    for idx, header in enumerate(headers):
        nulls[header] = sum(1 for row in rows if idx >= len(row) or row[idx] in ("", None))
    return ToolResult(
        ok=True,
        summary=f"数据画像：{len(rows)} 行，{len(headers)} 列，空值列 {sum(1 for v in nulls.values() if v)} 个",
        output={"rowCount": len(rows), "headers": headers, "nullCounts": nulls, "duplicates": len(rows) - len({tuple(str(c) for c in r) for r in rows})},
    )


async def clean_transform_handler(params: dict, ctx: ToolContext) -> ToolResult:
    return await transform_handler(params, ctx)


async def clean_save_handler(params: dict, ctx: ToolContext) -> ToolResult:
    return await export_handler(params, ctx)


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="excel.read",
        title="读取 Excel/CSV",
        description="读取上传的 xlsx 文件为表头 + 行数据，供清洗与导出。",
        params={
            "type": "object",
            "properties": {"fileId": {"type": "string", "description": "上传文件 ID"}},
        },
        handler=read_handler,
        risk="low",
        skill="excel-toolkit",
    ),
    ToolSpec(
        name="excel.transform",
        title="清洗表格数据",
        description="去重、去空格、数值列求和等轻量清洗。",
        params={
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["dedupe", "trim", "sum"]},
                }
            },
        },
        handler=transform_handler,
        risk="low",
        skill="excel-toolkit",
    ),
    ToolSpec(
        name="excel.export",
        title="导出 Excel",
        description="把查询结果或读取的表格导出为带样式与图表的 xlsx 文件。",
        params={"type": "object", "properties": {}},
        handler=export_handler,
        risk="low",
        skill="excel-toolkit",
    ),
    ToolSpec(
        name="clean.profile",
        title="数据画像",
        description="统计行数、空值、重复行，快速了解表格质量。",
        params={"type": "object", "properties": {}},
        handler=clean_profile_handler,
        risk="low",
        skill="data-cleaner",
    ),
    ToolSpec(
        name="clean.transform",
        title="数据清洗",
        description="执行去重/去空格/求和等清洗操作。",
        params={"type": "object", "properties": {}},
        handler=clean_transform_handler,
        risk="low",
        skill="data-cleaner",
    ),
    ToolSpec(
        name="clean.save",
        title="保存清洗结果",
        description="把清洗后的数据导出为 xlsx。",
        params={"type": "object", "properties": {}},
        handler=clean_save_handler,
        risk="low",
        skill="data-cleaner",
    ),
]
