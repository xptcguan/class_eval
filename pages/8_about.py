"""
pages/8_about.py —— 关于本站
=====================================
首页右侧的「它能做什么 / 数据安全」搬到这里，登录页只保留身份速查。
使用 st.navigation（见 run.py / 应用入口）后本页可从导航进入，也可直接访问。
"""

from __future__ import annotations

import streamlit as st

from core import auth, ui
from ui.nav import (APP_SUBTITLE, APP_TITLE, PAGE_FILES, teacher_shell)

st.set_page_config(page_title=f"关于 · {APP_TITLE}", page_icon="ℹ️", layout="wide",
                   initial_sidebar_state="expanded")

ui.inject_css()

# 已登录就走教师外壳（保留侧边栏），否则单独展示
if auth.current_teacher() and auth.current_class_id():
    teacher_shell(required=False)
else:
    st.markdown(
        f'<div style="text-align:center;padding:22px 0 6px">'
        f'<div style="font-size:44px">🏫</div>'
        f'<div class="login-h1">{APP_TITLE}</div>'
        f'<div class="ce-sub" style="margin-top:6px">{APP_SUBTITLE}</div></div>',
        unsafe_allow_html=True,
    )

st.markdown(f'<div class="page-title">{APP_TITLE}</div>'
            f'<div class="page-sub">{APP_SUBTITLE}</div>',
            unsafe_allow_html=True)

col1, col2 = st.columns([1.15, 1])

with col1:
    st.markdown(
        """
        <div class="ce-card">
          <div class="ce-title">它能做什么</div>
          <div class="role-row"><b>快速评分</b><span>点标签再点学生，一键加分/扣分，支持小组批量</span></div>
          <div class="role-row"><b>积分榜单</b><span>今日 / 本周 / 本月 / 总榜，同分并列，可关闭名次</span></div>
          <div class="role-row"><b>组内排名</b><span>每个学生卡片显示他在小组里第几名</span></div>
          <div class="role-row"><b>投屏展示</b><span>隐藏侧边栏，可切换为「小组榜」只显示小组名</span></div>
          <div class="role-row"><b>评价记录</b><span>默认按学生折叠，展开看全部明细；可撤回、可导出</span></div>
          <div class="role-row"><b>家长查看</b><span>凭学号 + 查看码，只看自己孩子</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="ce-card">
          <div class="ce-title">三种身份与权限</div>
          <div class="role-row"><b>班主任</b><span>建班、管学生、管标签、打分、撤回、导出、加科任老师</span></div>
          <div class="role-row"><b>科任老师</b><span>按任教科目显示身份（如「数学老师」），可打分、看榜单、看记录</span></div>
          <div class="role-row"><b>家长</b><span>只能用班级 + 学号 + 查看码登录，只能看自家孩子，页面无任何操作按钮</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        """
        <div class="ce-card">
          <div class="ce-title">数据与隐私</div>
          <div class="ce-sub">
            数据存放在 Supabase（PostgreSQL + Storage），容器休眠重启不丢数据；<br>
            账号密码以 PBKDF2 哈希存储，管理员也看不到明文；<br>
            评价记录永久存档，撤回为软删除并留痕，可追溯。
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="ce-card">
          <div class="ce-title">使用建议</div>
          <div class="ce-sub">
            1. 先在「班级管理」建班并导入学生名单<br>
            2. 在「学生与标签」微调标签（可上传图标图片）<br>
            3. 课堂上用「快速评分」或右下角悬浮按钮打分<br>
            4. 每周投屏一次「小组榜」公布评比结果<br>
            5. 学期末在「评价记录」导出德育台账
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="ce-card">
          <div class="ce-title">设计说明</div>
          <div class="ce-sub">
            积分以评价流水为准，学生累计分是派生值，撤回时同事务回滚；<br>
            头像为程序化 SVG 绘制，无第三方素材，无版权风险；<br>
            提示音由浏览器实时合成，不加载任何音频文件。
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("---")
if st.button("返回登录页", icon=":material/arrow_back:"):
    st.switch_page("Home.py")
