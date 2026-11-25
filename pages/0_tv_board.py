"""
pages/0_tv_board.py —— 纯净投屏榜单（教室大屏专用）
=====================================
两种视图，一键切换：
  · 学生榜：头像 + 姓名 + 积分（回到班级时用）
  · 小组榜：只显示小组名称 / 人均分 / 合计，完全不出现学生姓名与照片
    —— 投影到教室大屏做周评比时用这个，避免公开学生个人分数

其它：
  - 隐藏侧边栏与顶栏，全屏展示
  - 前三名金银铜特效；正数不带 "+"
  - 免登录投屏模式只读；教师登录后底部可快捷打分
  - 全部卡片单容器渲染，切周期不会触发前端 removeChild 报错
"""

from __future__ import annotations

import streamlit as st

from core import auth, cache as cdata, db, ui
from ui.nav import APP_TITLE, set_current_nav

st.set_page_config(page_title=f"{APP_TITLE} · 投屏", page_icon="📺", layout="wide",
                   initial_sidebar_state="collapsed")

if not (auth.is_play_mode() or auth.current_teacher()):
    st.switch_page("Home.py")

playing = auth.is_play_mode()
if playing:
    cid = auth.current_class_id()
    if not cid:
        st.warning("请从首页进入投屏")
        st.stop()
    cls = db.get_class(cid) or {}
    role = ""
    teacher = {"id": "", "display_name": "投屏"}
else:
    teacher, cls, role = __import__("ui.nav", fromlist=["teacher_shell"]).teacher_shell(required=True)
    cid = st.session_state.get(auth.K_CLASS)

set_current_nav("tv_board")
ui.inject_css(big_screen=True)

settings = cdata.get_class_settings(cid)
show_rank = bool(settings.get("show_rank", 1))
PERIODS = {"today": "今日", "week": "本周", "month": "本月", "all": "总榜"}

# ---------------------------------------------------------------------------
# 顶部控制（退出按钮挪到页面最下方，避免大屏误触）
# ---------------------------------------------------------------------------
c1, c2, c3 = st.columns([3, 2.2, 2.4])
with c1:
    st.markdown(
        f'<div class="page-title">{ui.esc(cls.get("name", ""))} · 积分榜</div>',
        unsafe_allow_html=True,
    )
with c2:
    period = st.radio("周期", list(PERIODS), format_func=lambda k: PERIODS[k],
                      horizontal=True, index=3, label_visibility="collapsed", key="tv_period")
with c3:
    view = st.radio("视图", ["学生榜", "小组榜"], horizontal=True, index=0,
                    label_visibility="collapsed", key="tv_view",
                    help="小组榜只显示小组名称与分数，不出现学生姓名与照片")

if not show_rank:
    st.caption("名次已在班级设置中关闭")

rows = db.apply_competition_rank(cdata.get_ranking(cid, period), "period_score")
group_rows = cdata.get_group_ranking(cid, period)

# ---------------------------------------------------------------------------
# 学生榜
# ---------------------------------------------------------------------------
if view == "学生榜":
    if not rows:
        st.info("该班级还没有学生")
        st.stop()

    # 前三名单独大卡片（内容加大、更清晰）
    def _big_card(s: dict) -> str:
        rank = int(s["rank"]) if show_rank else None
        top_cls = f" tv-top tv-top{rank}" if rank and rank <= 3 else ""
        medal = f'<div class="tv-medal">{"🥇🥈🥉"[rank - 1]}</div>' if rank and rank <= 3 else ""
        rank_html = (f'<div class="{"rank-badge rank-" + str(rank) if rank <= 3 else "rank-badge"}">{rank}</div>'
                     if rank else "")
        return (
            f'<div class="student-card{top_cls}">{medal}{rank_html}'
            f'{ui.avatar_img_tag(s, 130)}'
            f'<div class="s-name tv-name">{ui.esc(s["name"])}</div>'
            f'<div class="s-score tv-score">{ui.fmt_score(int(s["period_score"]), False)}</div>'
            f'<div class="tv-meta">累计 {int(s["total_score"])}</div></div>'
        )

    top3 = [s for s in rows if int(s["rank"]) <= 3] if show_rank else []
    if top3:
        st.markdown('<div class="tv-sec">前三名</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="rank-grid" style="grid-template-columns:repeat(3,minmax(0,1fr));gap:20px">'
            + "".join(f'<div class="rank-cell">{_big_card(s)}</div>' for s in top3)
            + "</div>",
            unsafe_allow_html=True,
        )

    rest = [s for s in rows if s not in top3]
    if rest:
        if top3:
            st.markdown('<div class="tv-sec">其他同学</div>', unsafe_allow_html=True)
        cells = []
        for s in rest:
            card = ui.student_card_html(
                s, int(s["period_score"]),
                rank=int(s["rank"]) if show_rank else None,
                size=92, show_plus=False, show_no=False,
                meta=f"累计 {int(s['total_score'])}",
            )
            cells.append(f'<div class="rank-cell">{card}</div>')
        st.markdown(
            '<div class="rank-grid" style="grid-template-columns:repeat(6,minmax(0,1fr))">'
            + "".join(cells) + "</div>",
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# 小组榜（不出现学生姓名与照片）
# ---------------------------------------------------------------------------
else:
    if not group_rows:
        st.info("该班级还没有小组数据")
        st.stop()
    sorted_groups = sorted(group_rows, key=lambda g: -float(g["avg_score"]))
    cells = []
    for idx, g in enumerate(sorted_groups, start=1):
        card = ui.group_card_html(
            g["group_name"], g["avg_score"],
            member_count=g["member_count"],
            sum_score=g["sum_score"],
            rank=idx if show_rank else None,
            show_members=None,
        )
        cells.append(f'<div class="rank-cell">{card}</div>')
    st.markdown(
        '<div class="rank-grid" style="grid-template-columns:repeat(5,minmax(0,1fr))">'
        + "".join(cells) + "</div>",
        unsafe_allow_html=True,
    )
    st.caption("小组榜按人均分排序，仅展示小组维度成绩，不显示学生个人信息")

# ---------------------------------------------------------------------------
# 教师快捷打分（免登录投屏不显示）
# ---------------------------------------------------------------------------
if not playing and role:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    with st.expander("投屏快捷打分", expanded=False):
        tags = cdata.list_tags(cid)
        if not tags or not rows:
            st.caption("请先配置标签与学生")
        else:
            left, right = st.columns(2)
            with left:
                names = {s["id"]: f"{s['student_no']} {s['name']}" for s in rows}
                pick = st.selectbox("学生", list(names), format_func=lambda i: names[i],
                                    key="tv_pick")
            with right:
                tag_labels = {t["id"]: f"{t['name']} {int(t['score']):+d}" for t in tags}
                pick_tag = st.selectbox("标签", list(tag_labels),
                                        format_func=lambda i: tag_labels[i], key="tv_tag")
            remark = st.text_input("备注（可选）", max_chars=100, key="tv_remark")
            if st.button("确认打分", type="primary", key="tv_submit"):
                ok, msg, _ = db.add_scores(cid, [pick], pick_tag, remark, "", teacher)
                if ok:
                    score = next(int(t["score"]) for t in tags if t["id"] == pick_tag)
                    st.session_state["play_sound_now"] = "plus" if score > 0 else "minus"
                    ui.flash(msg, "success")
                    st.rerun()
                else:
                    st.error(msg)

ui.play_sound_if()
ui.show_flash()

# ---------------------------------------------------------------------------
# 退出按钮（放页面最下方，避免大屏误触）
# ---------------------------------------------------------------------------
st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
_exit_l, _exit_c, _exit_r = st.columns([4, 1.4, 4])
with _exit_c:
    if st.button("退出投屏", use_container_width=True, key="tv_exit_bottom"):
        auth.logout()
        st.switch_page("Home.py")
