"""
pages/3_ranking.py —— 积分榜单
=====================================
- 今日 / 本周 / 本月 / 总榜 切换（快速切换不会造成前端 DOM 错乱）
- 同分并列（竞争排名 1,2,2,4）
- 学生卡显示「组内第几名」
- 前三名：金银铜描边 + 奖牌角标 + 微光扫过
- 正数不带 "+"，直接显示数字
- 班主任可关闭名次（防攀比），设置持久化到 class_settings

抗 removeChild 的关键做法
------------------------
旧版用 st.columns + 逐列 st.markdown 增量渲染，快速连续切换周期时，
Streamlit 前端会在旧节点尚未卸载完成时插入新节点，从而触发
"Failed to execute 'removeChild' on 'Node'"。
现在改为：所有卡片拼成一个 HTML 字符串，用单次 st.markdown 渲染，
容器数量恒定（始终 1 个），不产生"多容器增删"，从根上消除该问题。
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from core import auth, cache as cdata, db, ui
from ui.nav import go, page_header, quick_score_widget, set_current_nav, teacher_shell

st.set_page_config(page_title="积分榜单", page_icon="🏆", layout="wide",
                   initial_sidebar_state="expanded")

set_current_nav("ranking")
teacher, cls, role = teacher_shell(required=True)
cid = st.session_state[auth.K_CLASS]
is_head = role == "head_teacher"

@st.dialog("确认清除全部积分？")
def _confirm_clear_dialog(cls: dict, class_id: str, teacher: dict) -> None:
    """二次确认弹窗：清除本班全部积分（软清空，可查回）"""
    st.warning(
        f"将把「{cls.get('name', '')}」本学期全部有效评分标记为已撤回，所有学生积分归零。\n\n"
        "记录不会被物理删除，可在「评价记录 → 仅已撤回」中查阅。"
    )
    c1, c2 = st.columns(2)
    if c1.button("确认清除", type="primary", use_container_width=True):
        ok, msg = db.clear_class_scores(class_id, teacher)
        st.session_state["confirm_clear"] = False
        if ok:
            ui.flash(msg, "success")
            st.rerun()
        else:
            st.error(msg)
    if c2.button("取消", use_container_width=True):
        st.session_state["confirm_clear"] = False
        st.rerun()


page_header("积分榜单", "", cls.get("name", ""))

PERIODS = {"today": "今日", "week": "本周", "month": "本月", "all": "总榜"}
PERIOD_DESC = {
    "today": "统计今天 00:00 起的净积分",
    "week": "统计本周一 00:00 起的净积分",
    "month": "统计本月 1 日起的净积分",
    "all": "统计全部有效记录的净积分",
}

settings = cdata.get_class_settings(cid)
show_rank = bool(settings.get("show_rank", 1))

# ---------------------------------------------------------------------------
# 控制区
# ---------------------------------------------------------------------------
c1, c2, c3 = st.columns([3.2, 1.8, 1.6])
with c1:
    period = st.radio("周期", list(PERIODS), format_func=lambda k: PERIODS[k],
                      horizontal=True, index=3, label_visibility="collapsed",
                      key="rank_period")
with c2:
    if is_head:
        toggled = st.toggle("显示名次", value=show_rank, key="rank_show_toggle",
                            help="关闭后只显示分数不显示名次")
        if toggled != show_rank:
            db.set_show_rank(cid, toggled)
            st.rerun()
    else:
        st.caption("名次由班主任设置")
with c3:
    if st.button("投屏展示", icon=":material/tv:", use_container_width=True):
        go("tv_board")

rows = cdata.get_ranking(cid, period)
if not rows:
    ui.empty_state("本班还没有学生", "先到「班级管理 → 学生名单」录入名单", "👥")
    st.stop()

rows = db.apply_competition_rank(rows, "period_score")
group_rows = cdata.get_group_ranking(cid, period)
grp_rank_map: dict[str, tuple[int, int]] = {}
for g in group_rows:
    for m in g["members"]:
        grp_rank_map[m["id"]] = (int(m.get("group_rank") or 0), int(m.get("group_total") or 0))

# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------
plus_total = sum(r["plus_sum"] for r in rows)
minus_total = sum(r["minus_sum"] for r in rows)
top1 = rows[0]
st.markdown(
    ui.dashboard([
        {"label": "参与学生", "value": f"{len(rows)} 人", "icon": "👥"},
        {"label": "本期加分", "value": ui.fmt_score(plus_total, False),
         "icon": "➕", "tone": "plus"},
        {"label": "本期扣分", "value": ui.fmt_score(minus_total, False),
         "icon": "➖", "tone": "minus"},
        {"label": "本期榜首", "value": top1["name"],
         "hint": f"{ui.fmt_score(int(top1['period_score']), False)} 分", "icon": "🏆"},
    ]),
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 学生榜（单容器一次性渲染）
# ---------------------------------------------------------------------------
st.markdown('<div class="ce-title">学生积分榜</div>', unsafe_allow_html=True)
st.caption(PERIOD_DESC[period] + " · 卡片右上角为组内名次")

per_row = st.slider("每行人数", 4, 8, 6, label_visibility="collapsed", key="rank_per_row")

cells = []
for s in rows:
    g_rank, g_total = grp_rank_map.get(s["id"], (None, None))
    card = ui.student_card_html(
        s,
        int(s["period_score"]),
        rank=int(s["rank"]) if show_rank else None,
        group_rank=g_rank if show_rank else None,
        group_total=g_total,
        size=64,
        show_plus=False,
        meta=f"累计 {int(s['total_score'])}",
    )
    cells.append(f'<div class="rank-cell">{card}</div>')

st.markdown(
    f'<div class="rank-grid" style="grid-template-columns:repeat({per_row},minmax(0,1fr))">'
    + "".join(cells) +
    "</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 小组评比
# ---------------------------------------------------------------------------
st.markdown('<div class="ce-title" style="margin-top:20px">小组评比</div>', unsafe_allow_html=True)
if not group_rows:
    st.caption("暂无小组数据")
else:
    gmode = st.radio("排序依据", ["按合计分", "按人均分"], horizontal=True,
                     label_visibility="collapsed", key="rank_gmode")
    gkey = "sum_score" if gmode == "按合计分" else "avg_score"
    sorted_groups = sorted(group_rows, key=lambda g: -float(g[gkey]))
    gcells = []
    for idx, g in enumerate(sorted_groups, start=1):
        score = g["sum_score"] if gmode == "按合计分" else g["avg_score"]
        card = ui.group_card_html(
            g["group_name"], score,
            member_count=g["member_count"],
            sum_score=g["sum_score"],
            rank=idx if show_rank else None,
            show_members=[m["name"] for m in g["members"]],
        )
        gcells.append(f'<div class="rank-cell">{card}</div>')
    gcols = min(5, len(sorted_groups)) or 1
    st.markdown(
        f'<div class="rank-grid" style="grid-template-columns:repeat({gcols},minmax(0,1fr))">'
        + "".join(gcells) + "</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# 明细表（固定表头 + 可排序）
# ---------------------------------------------------------------------------
with st.expander("表格明细（点击表头排序）", expanded=False):
    df = pd.DataFrame([{
        "名次": r["rank"] if show_rank else "",
        "组内": grp_rank_map.get(r["id"], (0, 0))[0] if show_rank else "",
        "学号": r["student_no"],
        "姓名": r["name"],
        "小组": r["group_name"] or "",
        "加分": r["plus_sum"],
        "扣分": r["minus_sum"],
        "净积分": r["period_score"],
        "评价次数": r["log_count"],
        "累计积分": r["total_score"],
    } for r in rows])
    st.dataframe(df, use_container_width=True, hide_index=True,
                 height=min(560, 38 + 35 * len(df)))

# ---------------------------------------------------------------------------
# 本周进步之星
# ---------------------------------------------------------------------------
st.markdown('<div class="ce-title" style="margin-top:20px">本周进步之星</div>',
            unsafe_allow_html=True)
now = dt.datetime.now()
this_week_start = (now - dt.timedelta(days=now.weekday())).replace(
    hour=0, minute=0, second=0, microsecond=0)
last_week_start = this_week_start - dt.timedelta(days=7)

this_week = {r["id"]: int(r["period_score"]) for r in cdata.get_ranking(cid, "week")}
last_week: dict[str, int] = {}
for lg in db.query_logs(cid, start=last_week_start, end=this_week_start, limit=100000):
    if lg.get("student_id"):
        last_week[lg["student_id"]] = last_week.get(lg["student_id"], 0) + int(lg["score"])

name_map = {r["id"]: r for r in rows}
deltas = []
for sid, sc in this_week.items():
    d = sc - last_week.get(sid, 0)
    if d > 0 and sid in name_map:
        deltas.append({"name": name_map[sid]["name"], "delta": d,
                       "now": sc, "last": last_week.get(sid, 0)})
deltas.sort(key=lambda x: -x["delta"])
if deltas:
    dcells = []
    for d in deltas[:5]:
        dcells.append(
            '<div class="rank-cell"><div class="student-card">'
            '<div style="font-size:20px">🌟</div>'
            f'<div class="s-name">{ui.esc(d["name"])}</div>'
            f'<div class="s-score score-plus">{ui.fmt_score(d["delta"], False)}</div>'
            f'<div class="s-meta">本周 {ui.fmt_score(d["now"], False)} · '
            f'上周 {ui.fmt_score(d["last"], False)}</div></div></div>'
        )
    st.markdown(
        f'<div class="rank-grid" style="grid-template-columns:repeat({min(5, len(dcells))},minmax(0,1fr))">'
        + "".join(dcells) + "</div>",
        unsafe_allow_html=True,
    )
else:
    st.caption("本周暂无进步数据（需要上周也有记录才能比较）")

# ---------------------------------------------------------------------------
# 一键清除积分（仅班主任，需对话框二次确认）
# ---------------------------------------------------------------------------
if is_head:
    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
    if st.button("清除本班所有学生积分", icon=":material/restart_alt:",
                 type="secondary", key="open_clear_dialog"):
        st.session_state["confirm_clear"] = True

    if st.session_state.get("confirm_clear"):
        _confirm_clear_dialog(cls, cid, teacher)

quick_score_widget(cid, role)
ui.show_flash()

