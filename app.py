"""
app.py —— 应用入口（用 st.navigation 统一注册页面）
=====================================================
为什么需要它
------------
旧版把 Home.py 当主入口，另外 pages/ 目录里放页面。这种"双轨"结构有两个问题：
  1. 侧边栏导航和页面跳转的路径解析依赖"入口必须叫 Home.py"，
     一旦换成别的入口就报 PageNotFound，出现"点不动、进不去"的现象；
  2. 侧边栏会自动列出所有页面（包括不该给科任看的页），权限只能靠页面内部拦。

现在改用 Streamlit 官方推荐的 st.navigation：
  · 入口固定为 app.py，页面全部显式注册，路径解析不再依赖目录约定；
  · 侧边栏导航由我们自己的 ui/nav.py 渲染（按钮 + 分组 + 收起态仅图标），
    关掉默认导航，权限完全可控；
  · Home.py 仍然保留，作为"登录页"这个普通页面注册进来。

启动方式（两种都可用）：
    streamlit run app.py      ← 推荐
    streamlit run Home.py     ← 兼容旧习惯（会是登录页单独运行）
云端部署时把 Main file path 设为 app.py。
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="班级评价小屋",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 关闭 Streamlit 自动生成的侧边栏导航（我们自己渲染，才能做分组与权限）
pages = {
    "": [
        st.Page("Home.py", title="登录", icon=":material/login:", default=True),
    ],
    "评价操作": [
        st.Page("pages/2_scoring.py", title="快速评分", icon=":material/edit_note:"),
        st.Page("pages/0_tv_board.py", title="投屏榜单", icon=":material/tv:"),
    ],
    "数据查询": [
        st.Page("pages/3_ranking.py", title="积分榜单", icon=":material/emoji_events:"),
        st.Page("pages/4_logs.py", title="评价记录", icon=":material/fact_check:"),
    ],
    "系统设置": [
        st.Page("pages/1_classes.py", title="班级管理", icon=":material/school:"),
        st.Page("pages/5_students_tags.py", title="学生与标签", icon=":material/sell:"),
        st.Page("pages/6_settings_export.py", title="设置与导出", icon=":material/settings:"),
    ],
    "其他": [
        st.Page("pages/8_about.py", title="关于本站", icon=":material/info:"),
        # 家长端：不放进导航按钮，但必须注册，否则 st.switch_page 找不到该页
        st.Page("pages/7_parent_view.py", title="家长查看", icon=":material/family_restroom:"),
    ],
}

nav = st.navigation(pages, position="hidden")
nav.run()
