"""
pages/4_logs.py —— 评价记录（永久存档 + 软删除 + 撤回 + 导出）
=====================================
视图切换
  · 按学生折叠（默认）：同一学生的多条记录合并成一条摘要，点开看全部明细
  · 逐条明细：一条一条列出（排查单条记录时用）

权限
  · 班主任：查询、撤回单条/整批、导出 Excel
  · 科任老师：只能查询（撤回按钮不渲染，后端 revoke_log 仍会二次校验）
  · 已撤回记录不进积分统计，但永久留在库里，状态标记「已撤回」
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from core import auth, db, exporter, ui
from ui.nav import page_header, quick_score_widget, set_current_nav, teacher_shell

st.set_page_config(page_title="评价记录", page_icon="📋", layout="wide",
                   initial_sidebar_state="expanded")

set_current_nav("logs")
teacher, cls, role = teacher_shell(required=True)
cid = st.session_state[auth.K_CLASS]
is_head = role == "head_teacher"

page_header("评价记录", "", cls.get("name", ""))

students = db.list_students(cid, include_inactive=True)
groups = db.list_groups_of_class(cid)
tags = db.list_tags(cid, include_inactive=True)
teachers_of_class = db.list_class_teachers(cid)

# ---------------------------------------------------------------------------
# 筛选
# ---------------------------------------------------------------------------
with st.expander("筛选条件", expanded=True):
    c1, c2, c3, c4 = st.columns([1.4, 1, 1.4, 1.2])
    today = dt.date.today()
    with c1:
        date_range = st.date_input("日期范围", value=(today - dt.timedelta(days=30), today))
    with c2:
        status_sel = st.selectbox("状态", ["仅有效", "全部", "仅已撤回"])
    with c3:
        student_sel = st.selectbox(
            "学生", ["全部"] + [s["id"] for s in students],
            format_func=lambda i: "全部" if i == "全部"
            else next(f"{x['student_no']} {x['name']}" for x in students if x["id"] == i))
    with c4:
        group_sel = st.selectbox("小组", ["全部"] + [g["name"] for g in groups])

    c5, c6, c7, c8 = st.columns([1.2, 1.2, 1.4, 1.2])
    with c5:
        type_sel = st.selectbox("分值类型", ["全部", "只看加分", "只看扣分"])
    with c6:
        tag_sel = st.selectbox("标签", ["全部"] + [t["name"] for t in tags])
    with c7:
        teacher_sel = st.selectbox(
            "记录教师", ["全部"] + [t["id"] for t in teachers_of_class],
            format_func=lambda i: "全部" if i == "全部"
            else next(x["display_name"] for x in teachers_of_class if x["id"] == i))
    with c8:
        kw = st.text_input("关键词", placeholder="评语 / 标签 / 姓名")

start_dt = end_dt = None
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_dt = dt.datetime.combine(date_range[0], dt.time.min)
    end_dt = dt.datetime.combine(date_range[1], dt.time.max)

status_map = {"仅有效": "normal", "全部": None, "仅已撤回": "revoked"}
score_type = {"全部": None, "只看加分": "plus", "只看扣分": "minus"}[type_sel]

logs = db.query_logs(
    cid, start=start_dt, end=end_dt,
    student_id=None if student_sel == "全部" else student_sel,
    group_name=None if group_sel == "全部" else group_sel,
    tag_name=None if tag_sel == "全部" else tag_sel,
    score_type=score_type,
    recorded_by=None if teacher_sel == "全部" else teacher_sel,
    keyword=kw.strip() or None,
    status=status_map[status_sel],
    include_revoked=status_sel != "仅有效",
    limit=2000,
)

valid = [x for x in logs if x["status"] == "normal"]
revoked = [x for x in logs if x["status"] == "revoked"]
st.markdown(
    ui.dashboard([
        {"label": "命中记录", "value": f"{len(logs)} 条", "icon": "📋"},
        {"label": "有效", "value": f"{len(valid)} 条", "icon": "✅", "tone": "plus"},
        {"label": "已撤回", "value": f"{len(revoked)} 条", "icon": "↩️", "tone": "minus"},
        {"label": "净积分", "value": ui.fmt_score(sum(int(x["score"]) for x in valid), False),
         "icon": "∑"},
    ]),
    unsafe_allow_html=True,
)

if not logs:
    ui.empty_state("没有符合条件的记录", "试试放宽日期范围或清空关键词", "🔍")
    st.stop()

# ---------------------------------------------------------------------------
# 视图切换
# ---------------------------------------------------------------------------
view = st.radio("视图", ["按学生折叠", "逐条明细"], horizontal=True,
                label_visibility="collapsed", key="log_view")
PER_PAGE = 15


def _detail_html(x: dict) -> str:
    """单条记录的一行（纯 HTML）"""
    is_revoked = x["status"] == "revoked"
    chip = "chip-plus" if int(x["score"]) > 0 else "chip-minus"
    t = (x["created_at"].strftime("%Y-%m-%d %H:%M")
         if isinstance(x["created_at"], dt.datetime) else str(x["created_at"])[:16])
    strike = "text-decoration:line-through;opacity:.55" if is_revoked else ""
    badge = '<span class="tag-pill">已撤回</span>' if is_revoked else ""
    revoke_note = (
        f'<div class="log-sub" style="color:#B4450A">撤回：'
        f'{ui.esc(x.get("revoked_by_name") or "")} · '
        f'{ui.esc(x.get("revoke_reason") or "未填原因")}</div>' if is_revoked else "")
    remark = f'<div class="log-sub">{ui.esc(x.get("remark") or "")}</div>' if x.get("remark") else ""
    return (
        f'<div class="log-row{" log-revoked" if is_revoked else ""}">'
        f'<div class="log-main"><div class="log-title">'
        f'<span class="tag-pill {chip}" style="{strike}">{ui.esc(x["tag_name"])} {int(x["score"]):+d}</span>'
        f'{badge}<span class="log-dim">{t}</span>'
        f'<span class="log-dim">· {ui.esc(x.get("recorded_by_name") or "")}</span>'
        f'</div>{remark}{revoke_note}</div></div>'
    )


def _revoke_block(x: dict, key_prefix: str) -> None:
    """撤回按钮 + 原因表单（仅班主任 + 有效记录）"""
    if not is_head or x["status"] != "normal":
        return
    b1, b2 = st.columns([1, 4])
    with b1:
        if st.button("撤回", key=f"{key_prefix}_rv_{x['id']}", use_container_width=True):
            st.session_state["revoke_target"] = x["id"]
    if st.session_state.get("revoke_target") == x["id"]:
        with st.form(f"{key_prefix}_form_{x['id']}"):
            reason = st.text_input("撤回原因（必填，会记入审计）",
                                   key=f"{key_prefix}_reason_{x['id']}",
                                   placeholder="例如：重复打分 / 点错学生")
            s1, s2 = st.columns(2)
            do = s1.form_submit_button("确认撤回", type="primary", use_container_width=True)
            cancel = s2.form_submit_button("取消", use_container_width=True)
        if cancel:
            st.session_state.pop("revoke_target", None)
            st.rerun()
        if do:
            if not reason.strip():
                st.error("请填写撤回原因")
            else:
                ok, msg = db.revoke_log(x["id"], teacher, reason.strip())
                st.session_state.pop("revoke_target", None)
                if ok:
                    ui.flash(msg, "success")
                    st.rerun()
                else:
                    st.error(msg)


if view == "按学生折叠":
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for x in logs:
        key = x.get("student_id") or "unknown"
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(x)

    total_pages = max(1, (len(order) + PER_PAGE - 1) // PER_PAGE)
    page = st.number_input("页", 1, total_pages, 1, label_visibility="collapsed",
                           key="log_page_grouped")
    slice_keys = order[(page - 1) * PER_PAGE: page * PER_PAGE]
    st.caption(f"共 {len(order)} 名学生 · 第 {page}/{total_pages} 页 · 点标题展开明细")

    for sid in slice_keys:
        items = grouped[sid]
        first = items[0]
        name = first.get("student_name") or "-"
        total = sum(int(x["score"]) for x in items if x["status"] == "normal")
        ts = first["created_at"]
        time_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, dt.datetime) else str(ts)[:16]
        simg = ui.avatar_img_tag({"avatar_key": first.get("avatar_key"),
                                  "avatar_url": first.get("avatar_url")}, 36)
        chips = "".join(
            f'<span class="tag-pill {"chip-plus" if int(x["score"]) > 0 else "chip-minus"}">'
            f'{ui.esc(x["tag_name"])} {int(x["score"]):+d}</span>'
            for x in items[:4])
        more = f'<span class="ce-sub">等 {len(items)} 条</span>' if len(items) > 4 else ""
        total_color = ("var(--plus)" if total > 0
                       else ("var(--minus)" if total < 0 else "var(--muted)"))
        st.markdown(
            f'<div class="log-row"><div>{simg}</div><div class="log-main">'
            f'<div class="log-title">{ui.esc(name)}'
            f'<span class="ce-sub">{ui.esc(first.get("student_no") or "")} 号</span>'
            f'{chips}{more}</div>'
            f'<div class="log-sub">最近 {time_str} · 共 {len(items)} 条 · '
            f'净积分 <b style="color:{total_color}">{ui.fmt_score(total)}</b></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        with st.expander(f"展开 {name} 的全部 {len(items)} 条"):
            for x in items:
                st.markdown(_detail_html(x), unsafe_allow_html=True)
                if x.get("image_url"):
                    from core.storage import image_bytes_io

                    bio = image_bytes_io(x["image_url"])
                    if bio:
                        st.image(bio, width=240)
                _revoke_block(x, "g")

else:
    total_pages = max(1, (len(logs) + 20 - 1) // 20)
    page = st.number_input("页", 1, total_pages, 1, label_visibility="collapsed",
                           key="log_page_flat")
    page_rows = logs[(page - 1) * 20: page * 20]
    st.caption(f"共 {len(logs)} 条 · 第 {page}/{total_pages} 页")
    for x in page_rows:
        st.markdown(_detail_html(x), unsafe_allow_html=True)
        if x.get("image_url"):
            from core.storage import image_bytes_io

            bio = image_bytes_io(x["image_url"])
            if bio:
                st.image(bio, width=240)
        _revoke_block(x, "f")

# ---------------------------------------------------------------------------
# 批量撤回 / 导出 / 审计
# ---------------------------------------------------------------------------
st.markdown('<div class="ce-title" style="margin-top:20px">批量与导出</div>',
            unsafe_allow_html=True)
tab_batch, tab_export, tab_audit = st.tabs(["撤销整批", "导出 Excel", "操作审计"])

with tab_batch:
    if not is_head:
        st.caption("仅班主任可整批撤回")
    else:
        batches: dict[str, list[dict]] = {}
        for x in logs:
            if x.get("batch_id") and x["status"] == "normal":
                batches.setdefault(x["batch_id"], []).append(x)
        multi = {k: v for k, v in batches.items() if len(v) > 1}
        if not multi:
            st.caption("当前筛选结果里没有可撤回的批量打分")
        else:
            labels = {
                k: f"{v[0]['tag_name']} {int(v[0]['score']):+d} × {len(v)} 人 · "
                   + (v[0]["created_at"].strftime("%m-%d %H:%M")
                      if isinstance(v[0]["created_at"], dt.datetime) else "")
                   + f" · {v[0].get('recorded_by_name', '')}"
                for k, v in multi.items()
            }
            pick = st.selectbox("选择批次", list(labels), format_func=lambda i: labels[i])
            with st.form("batch_revoke"):
                st.caption("将撤回：" + "、".join(x.get("student_name") or ""
                                              for x in multi[pick][:12]))
                reason = st.text_input("撤回原因", key="batch_reason")
                if st.form_submit_button("确认整批撤回", type="primary"):
                    if not reason.strip():
                        st.error("请填写撤回原因")
                    else:
                        ok, msg = db.revoke_batch(pick, teacher, reason.strip())
                        if ok:
                            ui.flash(msg, "success")
                            st.rerun()
                        else:
                            st.error(msg)

with tab_export:
    if not is_head:
        st.caption("导出功能仅班主任可用")
    else:
        st.caption("导出当前时间范围内全部记录（含已撤回标注），另附学生积分汇总 sheet")
        if st.button("生成 Excel 台账", type="primary"):
            export_all = db.export_rows(cid, start_dt, end_dt, include_revoked=True)
            stats = db.apply_competition_rank(db.get_ranking(cid, "all"))
            label = (f"{date_range[0]} ~ {date_range[1]}"
                     if isinstance(date_range, tuple) and len(date_range) == 2 else "全部时间")
            data = exporter.export_excel(export_all, cls.get("name", ""), stats, label,
                                         teacher.get("display_name", ""), start_dt, end_dt)
            st.session_state["export_bytes"] = data
            st.session_state["export_name"] = exporter.filename(cls.get("name", ""),
                                                                start_dt, end_dt)
        if st.session_state.get("export_bytes"):
            st.download_button(
                "下载 Excel 文件",
                data=st.session_state["export_bytes"],
                file_name=st.session_state.get("export_name", "台账.xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary", icon=":material/download:",
            )

with tab_audit:
    audits = db.list_audit_logs(cid, limit=100)
    if not audits:
        st.caption("暂无审计记录")
    else:
        df = pd.DataFrame([{
            "时间": (a["created_at"].strftime("%Y-%m-%d %H:%M")
                     if isinstance(a["created_at"], dt.datetime) else a["created_at"]),
            "操作人": a["actor_name"],
            "操作": a["action"],
            "详情": a["detail"],
        } for a in audits])
        st.dataframe(df, use_container_width=True, hide_index=True, height=380)

quick_score_widget(cid, role)
ui.show_flash()
