"""
ui/nav.py —— 登录后统一外壳：侧边栏导航 / 身份信息 / 页面标题
=====================================================
设计要点
--------
1. 侧边栏用 st.button + st.switch_page（不用 st.page_link）：
   st.page_link 只有在入口脚本恰好是 Home.py 时才能解析 pages/ 目录，
   一旦把某个页面设成主入口就会抛 PageNotFound，是"进不去页面"的隐患。
2. 菜单按三组归类：评价操作 / 数据查询 / 系统设置；当前页高亮。
3. Streamlit 侧边栏自带展开↔收起（左上角箭头），收起后只剩图标。
   我们用 CSS 在收起态放大居中图标、隐藏文字与分组标题。
4. 高频「快速加分」不占侧边栏，做成右下角悬浮按钮（st.popover 定位到视口右下）。
5. 权限：菜单按班级内角色动态生成，科任老师看不到「学生与标签」。

⚠️ 本模块被 pages/ 下所有页面导入，中文注释里的字面量请勿随意改动。
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from core import auth, cache as cdata, db, ui

APP_TITLE = "星光评阅屋"
APP_SUBTITLE = "班主任课堂评价 · 学生积分 · 小组评比系统"

# 页面文件（与 pages/ 下真实文件名一致）
PAGE_FILES: dict[str, str] = {
    "tv_board": "pages/0_tv_board.py",
    "classes": "pages/1_classes.py",
    "scoring": "pages/2_scoring.py",
    "ranking": "pages/3_ranking.py",
    "logs": "pages/4_logs.py",
    "students_tags": "pages/5_students_tags.py",
    "settings_export": "pages/6_settings_export.py",
    "parent_view": "pages/7_parent_view.py",
    "about": "pages/8_about.py",
}


def go(page_key: str) -> None:
    """
    页面跳转唯一入口。
    - 用 app.py 启动（st.navigation 注册过页面）→ 用 st.switch_page 按文件切换
    - 直接跑单个页面（旧方式）→ 同样按文件切换，st.switch_page 在两种模式下都可用
    """
    st.switch_page(PAGE_FILES[page_key])


# 菜单：(分组, key, 图标, 文字)
MENU: list[tuple[str, str, str, str]] = [
    ("评价操作", "scoring", "✏️", "快速评分"),
    ("评价操作", "tv_board", "📺", "投屏榜单"),
    ("数据查询", "ranking", "🏆", "积分榜单"),
    ("数据查询", "logs", "📋", "评价记录"),
    ("系统设置", "classes", "🏫", "班级管理"),
    ("系统设置", "students_tags", "🏷️", "学生与标签"),
    ("系统设置", "settings_export", "⚙️", "设置与导出"),
]
HEAD_ONLY = {"students_tags"}


def set_current_nav(key: str) -> None:
    """页面开头声明"我是哪一页"：侧边栏高亮 + 悬浮按钮显隐"""
    st.session_state["nav_current"] = key


def _sidebar_brand() -> None:
    st.sidebar.markdown(
        f'<div class="sb-brand"><span class="sb-brand-icon">🏫</span>'
        f'<span class="sb-brand-text">{APP_TITLE}</span></div>',
        unsafe_allow_html=True,
    )


def _class_switcher(teacher: dict) -> None:
    """教师端班级切换（一个老师可管理多个班级）"""
    classes = cdata.list_classes_for_teacher(teacher["id"])
    if not classes:
        st.sidebar.markdown(
            '<div class="sb-hint">还没有班级，请到「班级管理」新建</div>',
            unsafe_allow_html=True,
        )
        return
    labels = {
        c["id"]: f"{c['name']}{'（已归档）' if c['is_archived'] else ''}"
        for c in classes
    }
    ids = [c["id"] for c in classes]
    cur = st.session_state.get(auth.K_CLASS)
    index = ids.index(cur) if cur in ids else 0
    chosen = st.sidebar.selectbox(
        "当前班级",
        ids,
        index=index,
        format_func=lambda i: labels.get(i, i),
        key="nav_class_select",
        label_visibility="collapsed",
    )
    if chosen != cur:
        auth.set_current_class(chosen)
        st.rerun()


def _sidebar_menu(role_in_class: str, is_head_level: bool = False) -> None:
    """按分组渲染侧边栏按钮；当前页用 primary 高亮。
    is_head_level：账号级班主任（即使尚未加入任何班级，也应看到完整菜单）"""
    current = st.session_state.get("nav_current", "")
    can_head = is_head_level or role_in_class == "head_teacher"
    last_group = None
    for group, key, icon, label in MENU:
        if key in HEAD_ONLY and not can_head:
            continue
        if group != last_group:
            st.sidebar.markdown(f'<div class="sb-group">{group}</div>', unsafe_allow_html=True)
            last_group = group
        st.sidebar.button(
            label,
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if key == current else "secondary",
            icon=icon,
            on_click=go,
            args=(key,),
        )


def _class_badge(cls: dict, role_in_class: str, subject: str = "") -> None:
    """当前班级 + 身份（科任按科目展示，如"数学老师"）"""
    tone = "head" if role_in_class == "head_teacher" else "subject"
    st.sidebar.markdown(
        f'<div class="sb-class">'
        f'<div class="sb-class-name">{cls.get("name", "未选择班级")}</div>'
        f'<span class="sb-role {tone}">{ui.role_text(role_in_class, subject)}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def teacher_shell(required: bool = True) -> tuple[dict[str, Any], dict[str, Any], str]:
    """
    教师/投屏端外壳。返回 (teacher, class, role_in_class)。
    required=False 时允许没有班级（班级管理页要用）。
    """
    playing = auth.is_play_mode()
    ui.inject_css(big_screen=playing)
    teacher = auth.require_teacher()
    _sidebar_brand()

    st.sidebar.markdown(
        f'<div class="sb-user"><b>{teacher.get("display_name", "")}</b>'
        f'<span>{auth.role_label()}</span></div>',
        unsafe_allow_html=True,
    )

    cid = auth.current_class_id()
    cls = cdata.get_class(cid) if cid else None
    # 当前班级失效（被删/无权限）时自动回落到他有权限的第一个班级
    if cid and not cdata.get_membership(teacher["id"], cid):
        others = cdata.list_classes_for_teacher(teacher["id"])
        if others:
            cid = others[0]["id"]
            auth.set_current_class(cid)
            cls = cdata.get_class(cid)
        else:
            cls = None
    membership = cdata.get_membership(teacher["id"], cid) if cid else None
    role_in_class = membership["teacher_role"] if membership else ""
    subject = (membership or {}).get("subject") or ""

    _class_switcher(teacher)
    if cls:
        _class_badge(cls, role_in_class, subject)

    st.sidebar.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    _sidebar_menu(role_in_class, is_head_level=(teacher.get("role") == "head_teacher"))

    st.sidebar.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)
    if st.sidebar.button("退出登录", key="nav_logout", use_container_width=True):
        auth.logout()
        st.switch_page("Home.py")

    if required:
        if not cid or not cls:
            is_head_level = teacher.get("role") == "head_teacher"
            ui.empty_state(
                "还没有可用的班级",
                "先去「班级管理」新建一个班级，再录入学生名单。" if is_head_level
                else "请联系班主任把你加入班级。",
                "🏫",
            )
            if is_head_level:
                if st.button("前往班级管理 →", type="primary", key="goto_classes_empty"):
                    go("classes")
            st.stop()
        if not cls or not membership:
            st.error("你没有该班级的访问权限，请切换班级或联系班主任。")
            st.stop()
    return teacher, cls or {}, role_in_class


def quick_score_widget(class_id: str = "", role_in_class: str = "",
                       show: bool = True) -> None:
    """
    右下角悬浮「快速评分」popover。
    - 打分页自身就是完整界面，传 show=False 不渲染
    - 投屏只读 / 家长端不会调用本函数
    """
    teacher = auth.current_teacher()
    if not show or not teacher or not class_id or auth.is_play_mode() or not role_in_class:
        return

    with st.popover("快速评分", icon=":material/bolt:"):
        st.markdown('<div class="qs-title">快速评分</div>', unsafe_allow_html=True)
        tags = cdata.list_tags(class_id)
        students = cdata.list_students(class_id)
        if not tags or not students:
            st.caption("请先在「学生与标签」配置标签、在「班级管理」录入学生")
            return

        tag_labels = {
            t["id"]: f"{t['name']}  {int(t['score']):+d}" for t in tags
        }
        tag_id = st.selectbox("评价项目", list(tag_labels),
                              format_func=lambda i: tag_labels[i], key="qs_tag")
        stu_labels = {s["id"]: f"{s['student_no']} {s['name']}" for s in students}
        stu_ids = st.multiselect("学生（可多选）", list(stu_labels),
                                 format_func=lambda i: stu_labels[i], key="qs_stu")

        # 评语模板：点一下填进输入框
        templates = _remark_templates(tag_id)
        if templates:
            cols = st.columns(min(3, len(templates)))
            for idx, tpl in enumerate(templates):
                with cols[idx % len(cols)]:
                    if st.button(tpl, key=f"qs_tpl_{idx}", use_container_width=True):
                        st.session_state["qs_remark"] = tpl
                        st.rerun()

        remark = st.text_input("评语（可选）", key="qs_remark", max_chars=120)
        if st.button("提交", type="primary", use_container_width=True, key="qs_submit"):
            if not stu_ids:
                st.warning("请选择至少一名学生")
                return
            ok, msg, _ = db.add_scores(class_id, stu_ids, tag_id, remark, "", teacher)
            if ok:
                score = next(int(t["score"]) for t in tags if t["id"] == tag_id)
                st.session_state["play_sound_now"] = "plus" if score > 0 else "minus"
                ui.flash(msg, "success")
                st.session_state["qs_stu"] = []
                st.session_state["qs_remark"] = ""
                st.rerun()
            else:
                st.error(msg)


# 评语模板（按标签名匹配，命中不到就用通用模板）
_TEMPLATES: dict[str, list[str]] = {
    "积极发言": ["主动举手发言，表达清楚", "课堂讨论很有观点", "敢于提问，思路清晰"],
    "作业优秀": ["作业书写工整", "作业按时完成且质量高", "订正认真，全部改对"],
    "助人为乐": ["主动帮助同学", "乐于分享学习资料", "关心集体，热心服务"],
    "课堂专注": ["全程专注听讲", "笔记完整条理清晰", "课堂参与度高"],
    "卫生值日认真": ["值日认真负责", "主动维护教室卫生", "地面清洁到位"],
    "进步明显": ["本次小测进步明显", "作业质量提升较大", "学习态度明显好转"],
    "纪律优秀": ["课堂纪律良好", "自习安静专注", "集会纪律表现好"],
    "作业未交": ["作业未按时提交", "作业缺交，请尽快补上", "连续两次未交作业"],
    "上课讲话": ["上课与同学讲话", "课堂随意插话", "影响周围同学听讲"],
    "迟到": ["早读迟到", "课前迟到几分钟", "体育课集合迟到"],
    "值日未完成": ["值日未完成", "值日区未打扫干净", "逃避值日任务"],
    "违规使用手机": ["课堂使用手机", "自习课玩手机", "违规携带手机入教室"],
}
_GENERIC = {
    "plus": ["表现优秀，继续保持", "值得表扬", "为班级做出贡献"],
    "minus": ["请及时改正", "注意课堂纪律", "下次请注意"],
}


def _remark_templates(tag_id: str) -> list[str]:
    tag = db.one("SELECT name, score FROM eval_tags WHERE id = ?", [tag_id])
    if tag and tag.get("name") in _TEMPLATES:
        return _TEMPLATES[tag["name"]]
    if tag:
        return _GENERIC["plus"] if int(tag["score"]) > 0 else _GENERIC["minus"]
    return _GENERIC["plus"]


def page_header(title: str, sub: str = "", class_name: str = "") -> None:
    """页面顶部标题条（没有副标题就省略，避免无谓文字堆积）"""
    right = f'<span class="head-chip">{class_name}</span>' if class_name else ""
    sub_html = f'<div class="page-sub">{sub}</div>' if sub else ""
    st.markdown(
        f'<div class="page-head"><div><div class="page-title">{title}</div>{sub_html}</div>'
        f'<div style="flex:1"></div>{right}</div>',
        unsafe_allow_html=True,
    )


def parent_shell() -> dict[str, Any]:
    """家长端外壳：没有侧边栏，只能看自己孩子"""
    ui.inject_css()
    student = auth.require_parent()
    st.markdown(
        f"""
        <div class="ce-card" style="display:flex;align-items:center;gap:14px">
          {ui.avatar_img_tag(student, 56)}
          <div style="flex:1">
            <div class="ce-title" style="margin:0">{student['name']}</div>
            <div class="ce-sub">{student.get('student_no','')} 号 · 家长查看</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("退出登录", key="parent_logout"):
        auth.logout()
        st.switch_page("Home.py")
    return student
