"""
core/exporter.py —— Excel 台账导出
=====================================
表头按学校德育记录习惯编排，方便直接打印/归档：
    序号 | 日期时间 | 班级 | 学号 | 姓名 | 小组 | 评价项目 | 类型 | 分值 | 说明 | 记录教师 | 记录状态 | 撤回人 | 撤回时间 | 撤回原因

另外提供两个 sheet：
    "学生积分汇总"：按学生统计周期得分（可直接交给德育处）
    "导出信息"    ：导出人、导出时间、区间、统计口径说明
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Any

import pandas as pd

# 德育台账标准列名与字段映射
COLUMNS: list[tuple[str, str]] = [
    ("序号", "_idx"),
    ("日期时间", "_time"),
    ("班级", "_class"),
    ("学号", "student_no"),
    ("姓名", "student_name"),
    ("小组", "group_name"),
    ("评价项目", "tag_name"),
    ("类型", "_type"),
    ("分值", "score"),
    ("说明", "remark"),
    ("记录教师", "recorded_by_name"),
    ("记录状态", "_status"),
    ("撤回人", "revoked_by_name"),
    ("撤回时间", "_revoked_at"),
    ("撤回原因", "revoke_reason"),
]


def _fmt_time(v: Any) -> str:
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    return str(v or "")[:16]


def build_dataframe(rows: list[dict[str, Any]], class_name: str) -> pd.DataFrame:
    """把数据库行转换成德育台账 DataFrame"""
    records = []
    for i, r in enumerate(rows, start=1):
        score = int(r.get("score") or 0)
        records.append({
            "_idx": i,
            "_time": _fmt_time(r.get("created_at")),
            "_class": class_name,
            "student_no": r.get("student_no") or "",
            "student_name": r.get("student_name") or "",
            "group_name": r.get("group_name") or "",
            "tag_name": r.get("tag_name") or "",
            "_type": "加分" if score > 0 else "扣分",
            "score": score,
            "remark": r.get("remark") or "",
            "recorded_by_name": r.get("recorded_by_name") or "",
            "_status": "已撤回" if r.get("status") == "revoked" else "有效",
            "revoked_by_name": r.get("revoked_by_name") or "",
            "_revoked_at": _fmt_time(r.get("revoked_at")) if r.get("revoked_at") else "",
            "revoke_reason": r.get("revoke_reason") or "",
        })
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=[c[0] for c in COLUMNS])
    return df[[key for _, key in COLUMNS]].rename(columns={key: label for label, key in COLUMNS})


def build_summary(rows: list[dict[str, Any]], stats: list[dict[str, Any]]) -> pd.DataFrame:
    """
    学生积分汇总 sheet。
    stats 来自 db.get_ranking()，包含 plus_sum / minus_sum / period_score / rank。
    """
    records = []
    for s in stats:
        records.append({
            "名次": s.get("rank", ""),
            "学号": s.get("student_no", ""),
            "姓名": s.get("name", ""),
            "小组": s.get("group_name", ""),
            "加分合计": int(s.get("plus_sum") or 0),
            "扣分合计": int(s.get("minus_sum") or 0),
            "本期净积分": int(s.get("period_score") or 0),
            "评价次数": int(s.get("log_count") or 0),
            "累计总积分": int(s.get("total_score") or 0),
        })
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["名次", "学号", "姓名", "小组", "加分合计",
                                     "扣分合计", "本期净积分", "评价次数", "累计总积分"])
    return df


def export_excel(
    rows: list[dict[str, Any]],
    class_name: str,
    stats: list[dict[str, Any]],
    period_label: str,
    exporter: str = "",
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> bytes:
    """生成 Excel 字节流（多 sheet），供 st.download_button 使用"""
    df_log = build_dataframe(rows, class_name)
    df_sum = build_summary(rows, stats)

    info = pd.DataFrame([
        {"项目": "班级", "内容": class_name},
        {"项目": "统计区间", "内容": period_label},
        {"项目": "起始时间", "内容": start.strftime("%Y-%m-%d %H:%M") if start else "不限"},
        {"项目": "截止时间", "内容": end.strftime("%Y-%m-%d %H:%M") if end else "不限"},
        {"项目": "导出人", "内容": exporter},
        {"项目": "导出时间", "内容": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        {"项目": "记录条数", "内容": str(len(rows))},
        {"项目": "说明", "内容": "「已撤回」记录仍保留在台账中，但不计入积分统计；"
                             "本表口径与学校德育记录一致，可直接打印归档。"},
    ])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_log.to_excel(writer, sheet_name="德育评价台账", index=False)
        df_sum.to_excel(writer, sheet_name="学生积分汇总", index=False)
        info.to_excel(writer, sheet_name="导出信息", index=False)

        # 简单美化：列宽自适应、表头加粗、冻结首行
        wb = writer.book
        widths = {
            "德育评价台账": [6, 17, 16, 8, 10, 10, 16, 7, 7, 30, 12, 9, 12, 17, 20],
            "学生积分汇总": [6, 8, 10, 10, 10, 10, 12, 10, 12],
            "导出信息": [14, 60],
        }
        for sheet_name, ws in zip(wb.sheetnames, wb.worksheets):
            for i, w in enumerate(widths.get(sheet_name, []), start=1):
                ws.column_dimensions[chr(64 + i) if i <= 26 else "A" + chr(64 + i - 26)].width = w
            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
    buf.seek(0)
    return buf.getvalue()


def filename(class_name: str, start: dt.datetime | None, end: dt.datetime | None) -> str:
    safe = class_name.replace("/", "_").replace("\\", "_")
    s = start.strftime("%Y%m%d") if start else "全部"
    e = end.strftime("%Y%m%d") if end else "至今"
    stamp = dt.datetime.now().strftime("%H%M%S")
    return f"班级德育评价台账_{safe}_{s}-{e}_{stamp}.xlsx"
