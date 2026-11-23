"""
pages/2_scoring.py —— 快速评分（核心操作页）
=====================================
页面结构
  1. 仪表盘：今日评价数 / 在班学生 / 本周之星 / 小组积分 Top3
  2. 选标签（加分项绿、扣分项橙红），选中高亮
  3. 评语模板（点一下填入，仍可编辑）+ 图片凭证
  4. 单人打分 / 小组批量打分
  5. 最近评价：同一学生多条记录折叠成一条，点开看该生全部明细与评语

权限：班主任 + 科任老师都能用；撤回只在「评价记录」页且仅班主任。
"""

from __future__ import annotations

import datetime as dt

import streamlit as st

from config import MAX_UPLOAD_MB, get_settings
from core import auth, db, ui
from core.storage import upload_image
from ui.nav import (_remark_templates, page_header, quick_score_widget,
                    set_current_nav, teacher_shell)

st.set_page_config(page_title="快速评分", page_icon="✏️", layout="wide",
                   initial_sidebar_state="expanded")

set_current_nav("scoring")
teacher, cls, role = teacher_shell(required=True)
cid = st.session_state[auth.K_CLASS]

page_header("快速评分", "", cls.get("name", ""))

overview = db.class_overview(cid)
tags = db.list_tags(cid)
students = db.list_students(cid)
groups = db.list_groups_of_class(cid)

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
week_rank = db.get_ranking(cid, "week")
week_star = week_rank[0] if week_rank and int(week_rank[0]["period_score"]) > 0 else None
group_rows = db.get_group_ranking(cid, "all")
group_brief = " · ".join(
    f"{g['group_name']} {ui.fmt_score(int(g['sum_score']), False)}"
    for g in sorted(group_rows, key=lambda x: -x["sum_score"])[:3]
) or "暂无小组"

st.markdown(
    ui.dashboard([
        {"label": "今日评价", "value": f"{overview['today_logs']} 条", "icon": "📝"},
        {"label": "在班学生", "value": f"{overview['student_count']} 人", "icon": "👥"},
        {"label": "本周之星", "value": week_star["name"] if week_star else "暂无",
         "hint": (f"{ui.fmt_score(int(week_star['period_score']), False)} 分"
                  if week_star else "本周还没有加分"),
         "icon": "⭐"},
        {"label": "小组积分 Top3", "value": group_brief, "icon": "👨‍👩‍👧", "tone": "primary"},
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

r1, r2 = st.columns([3, 2])
with r1:
    st.text_input("评语", key="score_remark", max_chars=200,
                  placeholder="点上面的模板快速填入，也可以自己写")
with r2:
    st.file_uploader(f"图片凭证（≤{MAX_UPLOAD_MB}MB）",
                     type=["png", "jpg", "jpeg", "webp"], key="score_img")


def _do_score(student_ids: list[str], target_type: str = "student",
              group_id: str | None = None) -> None:
    image_url = ""
    f = st.session_state.get("score_img")
    if f is not None:
        if f.size > MAX_UPLOAD_MB * 1024 * 1024:
            st.error(f"图片超过 {MAX_UPLOAD_MB}MB，本次不含图片")
        else:
            try:
                image_url = upload_image(f.getvalue(), f.name, prefix="score", cfg=get_settings())
            except Exception as e:
                st.error(f"图片上传失败（本次打分不含图片）：{e}")
    ok, msg, _ = db.add_scores(
        cid, student_ids, st.session_state["sel_tag"],
        st.session_state.get("score_remark", ""), image_url, teacher,
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
        st.markdown(f'<div class="ce-sub">点名字即打分（{score_v:+d} 分）</div>',
                    unsafe_allow_html=True)
        btn_cols = st.columns(min(per_row, len(shown)))
        for i, s in enumerate(shown):
            with btn_cols[i % len(btn_cols)]:
                if st.button(s["name"], key=f"sc_{s['id']}", use_container_width=True):
                    _do_score([s["id"]])

else:
    if not groups:
        st.info("还没有小组，可到「班级管理 → 小组管理」创建")
    else:
        rank_map = {g["group_name"]: g for g in db.get_group_ranking(cid)}
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

recent = db.query_logs(cid, limit=60)
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
                if x.get("image_url"):
                    from core.storage import image_bytes_io

                    bio = image_bytes_io(x["image_url"])
                    if bio:
                        st.image(bio, width=220)

quick_score_widget(cid, role, show=False)  # 本页即完整打分界面
ui.play_sound_if()
ui.show_flash()
