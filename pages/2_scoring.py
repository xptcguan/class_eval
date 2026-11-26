"""
pages/2_scoring.py —— 快速评分（核心操作页）
=====================================
页面结构
  1. 仪表盘：今日评价数 / 在班学生 / 本周之星 / 小组积分 Top3
  2. 选标签（加分项绿、扣分项橙红），选中高亮
  3. 评语模板（点一下填入，仍可编辑）
  4. 单人打分 / 小组批量打分
  5. 最近评价：同一学生多条记录折叠成一条，点开看该生全部明细与评语

权限：班主任 + 科任老师都能用；撤回只在「评价记录」页且仅班主任。
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from core import auth, cache as cdata, db, ui
from ui.nav import (_remark_templates, page_header, quick_score_widget,
                    set_current_nav, teacher_shell)

st.set_page_config(page_title="快速评分", page_icon="✏️", layout="wide",
                   initial_sidebar_state="expanded")

set_current_nav("scoring")
teacher, cls, role = teacher_shell(required=True)
cid = st.session_state[auth.K_CLASS]

@st.dialog("快速评价")
def _eval_dialog(student: dict, class_id: str, teacher: dict,
                 all_tags: list[dict], default_tag: dict) -> None:
    """轻量评价面板：选标签 → 选快捷评语 → 提交"""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">'
        f'{ui.avatar_img_tag(student, 46)}'
        f'<div><div style="font-weight:700;font-size:16px">{ui.esc(student["name"])}</div>'
        f'<div class="ce-sub">当前 {int(student.get("total_score") or 0)} 分</div></div></div>',
        unsafe_allow_html=True,
    )
    plus = [t for t in all_tags if int(t["score"]) > 0]
    minus = [t for t in all_tags if int(t["score"]) < 0]
    labels = {t["id"]: f"{t['name']}  {int(t['score']):+d}" for t in all_tags}
    ids = [t["id"] for t in all_tags]
    default_idx = ids.index(default_tag["id"]) if default_tag["id"] in ids else 0

    tab_a, tab_b = st.tabs(["表扬", "待改进"])
    with tab_a:
        for row_start in range(0, len(plus), 3):
            cols = st.columns(3)
            for col, t in zip(cols, plus[row_start:row_start + 3]):
                with col:
                    if st.button(f"{t['name']} {int(t['score']):+d}", key=f"ed_p_{t['id']}",
                                 use_container_width=True):
                        st.session_state["ed_tag"] = t["id"]
    with tab_b:
        for row_start in range(0, len(minus), 3):
            cols = st.columns(3)
            for col, t in zip(cols, minus[row_start:row_start + 3]):
                with col:
                    if st.button(f"{t['name']} {int(t['score']):+d}", key=f"ed_m_{t['id']}",
                                 use_container_width=True):
                        st.session_state["ed_tag"] = t["id"]

    tag_id = st.selectbox("评价项", ids, index=ids.index(st.session_state["ed_tag"])
                          if st.session_state.get("ed_tag") in ids else default_idx,
                          format_func=lambda i: labels[i], key="ed_tag_select")
    tpls = _remark_templates(tag_id)
    if tpls:
        tcols = st.columns(min(3, len(tpls)))
        for idx, tpl in enumerate(tpls):
            with tcols[idx % len(tcols)]:
                if st.button(tpl, key=f"ed_tpl_{idx}", use_container_width=True):
                    st.session_state["ed_remark"] = tpl
                    st.rerun()
    remark = st.text_input("评语（可选）", key="ed_remark", max_chars=150, value="")

    c1, c2 = st.columns(2)
    if c1.button("提交评价", type="primary", use_container_width=True, key="ed_submit"):
        ok, msg, _ = db.add_scores(class_id, [student["id"]], tag_id, remark, "", teacher)
        st.session_state.pop("eval_target", None)
        if ok:
            score = next(int(t["score"]) for t in all_tags if t["id"] == tag_id)
            st.session_state["play_sound_now"] = "plus" if score > 0 else "minus"
            ui.flash(msg, "success")
            st.rerun()
        else:
            st.error(msg)
    if c2.button("取消", use_container_width=True, key="ed_cancel"):
        st.session_state.pop("eval_target", None)
        st.rerun()


page_header("快速评分", "", cls.get("name", ""))

overview = cdata.class_overview(cid)
tags = cdata.list_tags(cid)
students = cdata.list_students(cid)
groups = cdata.list_groups_of_class(cid)

if not students:
    ui.empty_state("本班还没有学生", "先到「班级管理 → 学生名单」录入名单，再回来打分", "👥")
    if st.button("前往班级管理 →", type="primary"):
        st.switch_page("pages/1_classes.py")
    st.stop()
if not tags:
    ui.empty_state("还没有评价标签", "班主任可在「学生与标签」新建加分项与扣分项", "🏷️")
    st.stop()

# ---------------------------------------------------------------------------
# 1. 仪表盘
# ---------------------------------------------------------------------------
week_rank = cdata.get_ranking(cid, "week")
week_star = week_rank[0] if week_rank and int(week_rank[0]["period_score"]) > 0 else None
group_rows = cdata.get_group_ranking(cid, "all")
group_brief = " · ".join(
    f"{g['group_name']} {ui.fmt_score(int(g['sum_score']), False)}"
    for g in sorted(group_rows, key=lambda x: -x["sum_score"])[:3]
) or "暂无小组"

st.markdown(
    ui.dashboard([
        {"label": "在班学生", "value": f"{overview['student_count']} 人", "icon": "👥"},
        {"label": "本周之星", "value": week_star["name"] if week_star else "暂无",
         "hint": (f"{ui.fmt_score(int(week_star['period_score']), False)} 分"
                  if week_star else "本周还没有加分"),
         "icon": "⭐", "tone": "primary", "shine": True},
        {"label": "小组积分 Top3", "value": group_brief, "icon": "👨‍👩‍👧",
         "tone": "primary", "big": True},
    ]),
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# 2. 选标签
# ---------------------------------------------------------------------------
plus_tags = [t for t in tags if int(t["score"]) > 0]
minus_tags = [t for t in tags if int(t["score"]) < 0]

tag_ids = [t["id"] for t in tags]
if st.session_state.get("sel_tag") not in tag_ids:
    st.session_state["sel_tag"] = tag_ids[0]


def _tag_row(items: list[dict], prefix: str) -> None:
    if not items:
        st.caption("暂无")
        return
    cols = st.columns(min(4, len(items)))
    for i, t in enumerate(items):
        selected = st.session_state["sel_tag"] == t["id"]
        with cols[i % len(cols)]:
            if st.button(f"{t['name']} {int(t['score']):+d}", key=f"{prefix}_{t['id']}",
                         use_container_width=True,
                         type="primary" if selected else "secondary"):
                st.session_state["sel_tag"] = t["id"]
                st.rerun()


st.markdown('<div class="ce-title">选择评价项目</div>', unsafe_allow_html=True)
left, right = st.columns(2)
with left:
    st.markdown('<div class="ce-sub" style="color:var(--plus);font-weight:600">加分项</div>',
                unsafe_allow_html=True)
    _tag_row(plus_tags, "pt")
with right:
    st.markdown('<div class="ce-sub" style="color:var(--minus);font-weight:600">扣分项</div>',
                unsafe_allow_html=True)
    _tag_row(minus_tags, "mt")

cur_tag = next(t for t in tags if t["id"] == st.session_state["sel_tag"])
score_v = int(cur_tag["score"])

# ---------------------------------------------------------------------------
# 3. 评语模板 + 图片
# ---------------------------------------------------------------------------
st.markdown('<div class="ce-title" style="margin-top:14px">评语（可选）</div>',
            unsafe_allow_html=True)
templates = _remark_templates(cur_tag["id"])
tcols = st.columns(min(3, len(templates)))
for idx, tpl in enumerate(templates):
    with tcols[idx % len(tcols)]:
        if st.button(tpl, key=f"tpl_{idx}", use_container_width=True):
            st.session_state["score_remark"] = tpl
            st.rerun()

st.text_input("评语", key="score_remark", max_chars=200,
              placeholder="点上面的模板快速填入，也可以自己写")


def _do_score(student_ids: list[str], target_type: str = "student",
              group_id: str | None = None) -> None:
    ok, msg, _ = db.add_scores(
        cid, student_ids, st.session_state["sel_tag"],
        st.session_state.get("score_remark", ""), "", teacher,
        target_type=target_type, group_id=group_id,
    )
    if ok:
        st.session_state["play_sound_now"] = "plus" if score_v > 0 else "minus"
        st.session_state["sound_tick"] = st.session_state.get("sound_tick", 0) + 1
        ui.flash(msg, "success")
        st.rerun()
    else:
        st.error(msg)


# ---------------------------------------------------------------------------
# 4. 打分
# ---------------------------------------------------------------------------
mode = st.radio("打分方式", ["单人打分", "小组批量"], horizontal=True,
                label_visibility="collapsed", key="score_mode")

if mode == "单人打分":
    f1, f2 = st.columns([2, 2])
    with f1:
        group_filter = st.selectbox("小组筛选", ["全部"] + [g["name"] for g in groups],
                                    key="f_group")
    with f2:
        sort_by = st.selectbox("排序", ["学号", "积分从高到低", "积分从低到高"], key="f_sort")

    shown = students if group_filter == "全部" else [
        s for s in students if s["group_name"] == group_filter]
    if sort_by == "积分从高到低":
        shown = sorted(shown, key=lambda s: -(s["total_score"] or 0))
    elif sort_by == "积分从低到高":
        shown = sorted(shown, key=lambda s: (s["total_score"] or 0))

    per_row = st.slider("每行人数", 4, 8, 6, label_visibility="collapsed", key="s_per_row")

    if not shown:
        st.info("该小组暂无学生")
    else:
        st.markdown(
            f'<div class="rank-grid" style="grid-template-columns:repeat({per_row},minmax(0,1fr))">'
            + "".join(
                f'<div class="rank-cell">{ui.student_card_html(s, int(s["total_score"] or 0), size=62)}</div>'
                for s in shown
            ) + "</div>",
            unsafe_allow_html=True,
        )
        st.caption(f"点击学生卡片即评价（当前选中 {cur_tag['name']} {score_v:+d} 分）；"
                   f"也可勾选多人后批量提交")
        # 卡片按钮：整卡热区，覆盖在卡片上方，点任意位置都能唤起评价
        btn_cols = st.columns(per_row, gap="small")
        for i, s in enumerate(shown):
            with btn_cols[i % per_row]:
                if st.button(f"评价 {s['name']}", key=f"sc_{s['id']}",
                             use_container_width=True):
                    st.session_state["eval_target"] = s["id"]
                    st.rerun()

        # 批量勾选
        pick_ids = st.multiselect(
            "批量选择学生", [s["id"] for s in shown],
            format_func=lambda i: next(f"{x['student_no']} {x['name']}"
                                       for x in shown if x["id"] == i),
            key="batch_pick", placeholder="可多选，一次给同一评价项")
        if pick_ids and st.button(f"批量提交：{cur_tag['name']} {score_v:+d} 分 × {len(pick_ids)} 人",
                                  type="primary", key="batch_submit"):
            _do_score(pick_ids)

else:
    if not groups:
        st.info("还没有小组，可到「班级管理 → 小组管理」创建")
    else:
        rank_map = {g["group_name"]: g for g in cdata.get_group_ranking(cid)}
        gcols = st.columns(min(3, len(groups)))
        for i, g in enumerate(groups):
            members = [s for s in students if s["group_name"] == g["name"]]
            info = rank_map.get(g["name"], {})
            with gcols[i % len(gcols)]:
                st.markdown(
                    ui.group_card_html(
                        g["name"], info.get("avg_score", 0),
                        member_count=len(members),
                        sum_score=info.get("sum_score", 0),
                        show_members=[m["name"] for m in members],
                    ),
                    unsafe_allow_html=True,
                )
                if st.button(f"整组 {score_v:+d} 分", key=f"grp_{g['id']}",
                             use_container_width=True, disabled=not members):
                    _do_score([m["id"] for m in members],
                              target_type="group", group_id=g["id"])

# ---------------------------------------------------------------------------
# 5. 最近评价（按学生折叠）
# ---------------------------------------------------------------------------
st.markdown('<div class="ce-title" style="margin-top:22px">最近评价</div>',
            unsafe_allow_html=True)

recent = cdata.query_logs(cid, limit=60)
grouped: dict[str, list[dict]] = {}
order: list[str] = []
for r in recent:
    key = r.get("student_id") or "unknown"
    if key not in grouped:
        grouped[key] = []
        order.append(key)
    grouped[key].append(r)

if not recent:
    ui.empty_state("还没有评价记录", "选好标签后点学生名字就能打分", "📝")
else:
    st.caption("同一学生的多条记录已合并为一条，展开可看该生全部明细与评语")
    for sid in order[:12]:
        items = grouped[sid]
        first = items[0]
        total = sum(int(x["score"]) for x in items)
        name = first.get("student_name") or "-"
        ts = first["created_at"]
        time_str = ts.strftime("%m-%d %H:%M") if isinstance(ts, dt.datetime) else str(ts)[:16]
        simg = ui.avatar_img_tag({"avatar_key": first.get("avatar_key"),
                                  "avatar_url": first.get("avatar_url")}, 36)
        chips = "".join(
            f'<span class="tag-pill {"chip-plus" if int(x["score"]) > 0 else "chip-minus"}">'
            f'{ui.esc(x["tag_name"])} {int(x["score"]):+d}</span>'
            for x in items[:3]
        )
        more = f'<span class="ce-sub">等 {len(items)} 条</span>' if len(items) > 3 else ""
        total_color = "var(--plus)" if total > 0 else ("var(--minus)" if total < 0 else "var(--muted)")
        st.markdown(
            f'<div class="log-row"><div>{simg}</div>'
            f'<div class="log-main"><div class="log-title">{ui.esc(name)}'
            f'<span class="ce-sub">{ui.esc(first.get("student_no") or "")} 号</span>'
            f'{chips}{more}</div>'
            f'<div class="log-sub">最近 {time_str} · 共 {len(items)} 条 · '
            f'小计 <b style="color:{total_color}">{ui.fmt_score(total)}</b></div></div></div>',
            unsafe_allow_html=True,
        )
        with st.expander(f"展开 {name} 的全部 {len(items)} 条明细", expanded=False):
            for x in items:
                t = (x["created_at"].strftime("%Y-%m-%d %H:%M")
                     if isinstance(x["created_at"], dt.datetime) else str(x["created_at"])[:16])
                st.markdown(
                    f'<div class="log-row"><div class="log-main">'
                    f'<div class="log-title">'
                    f'<span class="tag-pill {"chip-plus" if int(x["score"]) > 0 else "chip-minus"}">'
                    f'{ui.esc(x["tag_name"])} {int(x["score"]):+d}</span>'
                    f'<span class="log-dim">{t}</span>'
                    f'<span class="log-dim">· {ui.esc(x.get("recorded_by_name") or "")}</span>'
                    f'</div>'
                    + (f'<div class="log-sub">{ui.esc(x["remark"])}</div>' if x.get("remark") else "")
                    + '</div></div>',
                    unsafe_allow_html=True,
                )

quick_score_widget(cid, role, show=False)  # 本页即完整打分界面
ui.play_sound_if()
ui.show_flash()


# ---------------------------------------------------------------------------
# 整卡点击 → 评价面板（弹窗）
# ---------------------------------------------------------------------------
_target = st.session_state.get("eval_target")
if _target:
    _stu = next((x for x in students if x["id"] == _target), None)
    if _stu:
        _eval_dialog(_stu, cid, teacher, tags, cur_tag)
    else:
        st.session_state.pop("eval_target", None)

