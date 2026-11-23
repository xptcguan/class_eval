"""
pages/7_parent_view.py —— 家长查看端
=====================================
权限硬约束（三重保障）：
  1. session 中绑定的 student_id 必须通过 HMAC 令牌校验（改 session 也会失效）
  2. 所有查询都以该 student_id 为 WHERE 条件，代码里不存在"全班"查询路径
  3. 页面不含任何榜单/班级排名入口，也不加载音效组件

家长可见内容：
  - 孩子累计积分、今日/本周/本月净积分
  - 评价明细（只显示有效记录）
  - 积分趋势（近 14 天）
  - 每位老师给的评语/备注
家长不可见：其他学生、班级榜单、名次
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from core import auth, db, ui

st.set_page_config(page_title="家长查看", page_icon="👨‍👩‍👦", layout="wide",
                   initial_sidebar_state="collapsed")

ui.inject_css()

student = auth.require_parent()
sid = student["id"]
cid = student["class_id"]
cls = db.get_class(cid) or {}

# ---------------------------------------------------------------------------
# 顶部
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div class="ce-card" style="display:flex;align-items:center;gap:16px">
      {ui.avatar_img_tag(student, 76)}
      <div style="flex:1">
        <div style="font-size:26px;font-weight:900">{student['name']}</div>
        <div class="ce-sub">{cls.get('name','')} · {student.get('student_no','')} 号
        {"· " + student['group_name'] if student.get('group_name') else ""} · 家长查看端</div>
      </div>
      <div style="text-align:right">
        <div class="ce-sub">累计积分</div>
        <div style="font-size:34px;font-weight:900" class="{ui.score_class(int(student['total_score'] or 0))}">
          {int(student['total_score'] or 0):+d}
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.button("退出登录", key="p_logout"):
    auth.logout()
    st.switch_page("Home.py")

# ---------------------------------------------------------------------------
# 周期汇总（只有自家孩子）
# ---------------------------------------------------------------------------
sums = {p: db.get_student_summary(sid, p) for p in ("today", "week", "month")}
my_logs = db.query_logs(cid, student_id=sid, include_revoked=False, limit=5000)
st.markdown(
    ui.metric_row([
        ("今日", f"{sums['today']['period_score']:+d}"),
        ("本周", f"{sums['week']['period_score']:+d}"),
        ("本月", f"{sums['month']['period_score']:+d}"),
        ("累计评价", f"{len(my_logs)} 次"),
    ]),
    unsafe_allow_html=True,
)
st.caption("说明：家长端只看得到自己孩子的记录，不显示班级排名（保护学生隐私、避免攀比）。")

tab_rec, tab_trend, tab_about = st.tabs(["📜 评价明细", "📈 积分趋势", "💡 关于积分"])

# ---------------------------------------------------------------------------
# 评价明细
# ---------------------------------------------------------------------------
with tab_rec:
    c1, c2, c3 = st.columns([1.2, 1.2, 1])
    with c1:
        period = st.selectbox("时间范围", ["近 7 天", "近 30 天", "全部"])
    with c2:
        kind = st.selectbox("类型", ["全部", "只看加分", "只看扣分"])
    with c3:
        with st.form("pwd_form"):
            new_code = st.text_input("新查看码", type="password", placeholder="4 位数字")
            if st.form_submit_button("修改查看码"):
                if not (new_code.isdigit() and len(new_code) == 4):
                    st.error("请输入 4 位数字")
                elif db.code_in_use(cid, new_code):
                    st.error("该查看码已被占用，请换一个")
                else:
                    db.set_parent_code(sid, new_code)
                    st.success("查看码已修改，请牢记")

    days = {"近 7 天": 7, "近 30 天": 30, "全部": None}[period]
    start = (dt.datetime.now() - dt.timedelta(days=days)) if days else None
    score_type = {"全部": None, "只看加分": "plus", "只看扣分": "minus"}[kind]
    logs = db.query_logs(cid, start=start, student_id=sid, score_type=score_type,
                         include_revoked=False, limit=500)

    if not logs:
        st.info("这段时间还没有评价记录")
    else:
        for lg in logs:
            chip = "chip-plus" if int(lg["score"]) > 0 else "chip-minus"
            t = lg["created_at"].strftime("%m-%d %H:%M") if isinstance(lg["created_at"], dt.datetime) else ""
            st.markdown(
                f'<div class="ce-card" style="padding:10px 14px;margin-bottom:8px">'
                f'<div style="display:flex;align-items:center;gap:8px">'
                f'<span class="tag-pill {chip}">{lg["tag_name"]} {int(lg["score"]):+d}</span>'
                f'<span class="ce-sub">{t} · {lg.get("recorded_by_name") or ""}</span>'
                f'</div>'
                + (f'<div style="margin-top:6px">{lg["remark"]}</div>' if lg.get("remark") else "")
                + '</div>',
                unsafe_allow_html=True,
            )
            if lg.get("image_url"):
                from core.storage import image_bytes_io

                bio = image_bytes_io(lg["image_url"])
                if bio:
                    st.image(bio, width=240)

# ---------------------------------------------------------------------------
# 积分趋势
# ---------------------------------------------------------------------------
with tab_trend:
    all_logs = db.query_logs(cid, student_id=sid, include_revoked=False, limit=2000)
    if not all_logs:
        st.info("暂无数据")
    else:
        records = [{
            "date": lg["created_at"].date() if isinstance(lg["created_at"], dt.datetime) else None,
            "score": int(lg["score"]),
        } for lg in all_logs]
        df = pd.DataFrame(records).dropna()
        if df.empty:
            st.info("暂无数据")
        else:
            daily = df.groupby("date", as_index=False)["score"].sum()
            daily = daily.sort_values("date")
            # 累计曲线
            daily["累计积分"] = daily["score"].cumsum()
            st.markdown('<div class="ce-title">累计积分趋势</div>', unsafe_allow_html=True)
            st.line_chart(daily.set_index("date")[["累计积分"]], height=260, use_container_width=True)
            st.markdown('<div class="ce-title">每日得分</div>', unsafe_allow_html=True)
            st.bar_chart(daily.set_index("date")[["score"]], height=220, use_container_width=True)

# ---------------------------------------------------------------------------
# 规则说明
# ---------------------------------------------------------------------------
with tab_about:
    plus = db.list_tags(cid, category="加分项")
    minus = db.list_tags(cid, category="扣分项")
    st.markdown("**本班加分项**")
    st.markdown(" ".join(
        f'<span class="tag-pill chip-plus">{t["icon"]} {t["name"]} {int(t["score"]):+d}</span>' for t in plus
    ) or "暂无", unsafe_allow_html=True)
    st.markdown("**本班扣分项**")
    st.markdown(" ".join(
        f'<span class="tag-pill chip-minus">{t["icon"]} {t["name"]} {int(t["score"]):+d}</span>' for t in minus
    ) or "暂无", unsafe_allow_html=True)
    st.markdown(
        """
        ---
        **关于积分**
        - 积分用于激励学生课堂表现与行为习惯，是教育工具，不与任何奖惩挂钩。
        - 如对某条记录有疑问，请联系班主任核对（老师端可查看完整记录与撤回日志）。
        - 本页面不会显示其他学生的成绩或班级排名。
        """
    )
