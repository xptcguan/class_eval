"""
Home.py —— 入口页（登录 / 家长入口 / 投屏入口）
=====================================
- 老师登录（账号 + 密码，回车即提交）
- 家长查看（班级 + 学号 + 查看码）
- 教室投屏（班级 + 投屏口令，免登录只读）
- 首次启动自动建库 + 默认班主任账号
- 右侧不再堆功能清单（已迁到「关于本站」），只留身份速查
"""

from __future__ import annotations

import os

import streamlit as st

from config import get_settings
from core import auth, db, ui
from ui.nav import APP_TITLE, go

st.set_page_config(
    page_title=f"{APP_TITLE} · 登录",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ui.inject_css()


@st.cache_resource(show_spinner=False)
def _bootstrap() -> str:
    """首次启动建表 + 默认账号（每进程只执行一次）"""
    return db.init_db()


try:
    _db_msg = _bootstrap()
except Exception as e:  # 云端首启常见：Secrets 未配置 / schema 未执行
    st.error(f"数据库初始化失败：{e}")
    st.info("请检查 .env 或 Streamlit Secrets 里的 APP_MODE、DATABASE_URL。")
    st.stop()

cfg = get_settings()
ui.show_flash()

# ---------------------------------------------------------------------------
# 已登录则直接进入主页
# ---------------------------------------------------------------------------
role = st.session_state.get(auth.K_ROLE)
if role == "parent":
    go("parent_view")
if role == "teacher":
    go("scoring")
if role == "play":
    go("tv_board")

# ---------------------------------------------------------------------------
# 登录界面
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div style="text-align:center;padding:36px 0 16px">
      <div style="font-size:52px;line-height:1">🏫</div>
      <div class="login-h1">{APP_TITLE}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

left, right = st.columns([1, 1], gap="large")

with left:
    tab_t, tab_p, tab_s = st.tabs(["老师登录", "家长查看", "教室投屏"])

    with tab_t:
        with st.form("teacher_login"):
            username = st.text_input("账号", placeholder="例如 admin")
            password = st.text_input("密码", type="password", placeholder="至少 6 位")
            submitted = st.form_submit_button("登录", type="primary", use_container_width=True)
        if submitted:
            ok, msg = auth.login_teacher(username, password)
            if ok:
                go("scoring")
            else:
                st.error(msg)

        if cfg.allow_teacher_signup:
            with st.expander("没有账号？注册老师账号"):
                with st.form("teacher_signup"):
                    c1, c2 = st.columns(2)
                    new_user = c1.text_input("账号", key="su_user")
                    new_name = c2.text_input("姓名", key="su_name")
                    new_pwd = c1.text_input("密码", type="password", key="su_pwd")
                    new_pwd2 = c2.text_input("确认密码", type="password", key="su_pwd2")
                    role_sel = st.selectbox(
                        "申请身份", ["班主任", "科任老师"],
                        help="班主任可自行新建班级；科任老师需由班主任邀请加入",
                    )
                    reg = st.form_submit_button("注册", use_container_width=True)
                if reg:
                    if new_pwd != new_pwd2:
                        st.error("两次输入的密码不一致")
                    else:
                        ok2, msg2 = db.create_teacher(
                            new_user, new_pwd, new_name,
                            role="head_teacher" if role_sel == "班主任" else "subject_teacher",
                        )
                        if ok2:
                            ui.flash("注册成功，请直接登录", "success")
                            st.rerun()
                        else:
                            st.error(msg2)

    with tab_p:
        classes = db.list_active_classes()
        if not classes:
            st.info("暂无班级数据")
        else:
            labels = {c["id"]: c["name"] for c in classes}
            with st.form("parent_login"):
                cls_id = st.selectbox("选择班级", list(labels), format_func=lambda i: labels[i])
                c1, c2 = st.columns(2)
                no = c1.text_input("孩子学号", placeholder="例如 01")
                code = c2.text_input("家长查看码", placeholder="4 位数字")
                go_p = st.form_submit_button("查看孩子记录", type="primary", use_container_width=True)
            if go_p:
                ok, msg = auth.login_parent(cls_id, no, code)
                if ok:
                    go("parent_view")
                else:
                    st.error(msg)
            st.caption("查看码由班主任在「班级管理 → 家长查看码」下发，遗失请联系老师重置。")

    with tab_s:
        classes = db.list_active_classes()
        if not classes:
            st.info("暂无班级数据")
        else:
            labels = {c["id"]: c["name"] for c in classes}
            with st.form("play_login"):
                cls_id = st.selectbox("选择班级", list(labels), format_func=lambda i: labels[i], key="play_cls")
                code = st.text_input("投屏口令", placeholder="默认 0000", key="play_code")
                go_s = st.form_submit_button("进入投屏", use_container_width=True)
            if go_s:
                expect = str(os.getenv("PLAY_CODE") or "0000")
                if code.strip() == expect:
                    auth.login_play(cls_id)
                    go("tv_board")
                else:
                    st.error("投屏口令不正确")
            st.caption("投屏页隐藏侧边栏，适合教室大屏；免登录只读，不可打分。")

with right:
    st.markdown(
        """
        <div class="ce-card" style="padding:22px 24px">
          <div class="login-h1" style="font-size:22px;margin:0">星光评阅屋</div>
          <div class="ce-sub" style="margin-top:10px;line-height:1.9">
            班主任课堂评价 · 学生积分 · 小组评比系统
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("关于本站", use_container_width=True):
        go("about")
    st.caption(f"数据库：{_db_msg}")
