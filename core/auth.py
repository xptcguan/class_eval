"""
core/auth.py —— 登录态管理
=====================================
Streamlit 每个浏览器标签页是一个独立会话，登录态放 st.session_state 即可。
三类身份严格隔离：
    teacher      教师（班主任 / 科任老师，权限由 teacher_classes.teacher_role 决定）
    parent       家长（只绑定一个 student_id）
    play         投屏免登录模式（只读榜单与打分，绝对不能撤回/管理）
所有页面在渲染前都必须先调用 require_xxx()，未授权直接中断。
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from config import get_settings
from core import db
from core.security import sign_child_token, verify_child_token

# session_state 键名
K_ROLE = "auth_role"            # teacher / parent / play
K_TEACHER = "auth_teacher"
K_STUDENT = "auth_student"
K_CLASS = "current_class_id"
K_PARENT_TOKEN = "auth_parent_token"


# ---------------------------------------------------------------------------
# 教师端
# ---------------------------------------------------------------------------
def login_teacher(username: str, password: str) -> tuple[bool, str]:
    teacher = db.authenticate_teacher(username, password)
    if not teacher:
        return False, "账号或密码错误，或账号已被停用"
    st.session_state[K_ROLE] = "teacher"
    st.session_state[K_TEACHER] = teacher
    st.session_state.pop(K_STUDENT, None)
    _init_class_selection(teacher)
    return True, "登录成功"


def _init_class_selection(teacher: dict[str, Any]) -> None:
    """选一个有权限的班级作为当前班级"""
    classes = db.list_classes_for_teacher(teacher["id"])
    if classes and st.session_state.get(K_CLASS) not in [c["id"] for c in classes]:
        st.session_state[K_CLASS] = classes[0]["id"]


def current_teacher() -> dict[str, Any] | None:
    return st.session_state.get(K_TEACHER)


def is_teacher_logged_in() -> bool:
    return bool(st.session_state.get(K_TEACHER)) and st.session_state.get(K_ROLE) in ("teacher", "play")


def is_play_mode() -> bool:
    return st.session_state.get(K_ROLE) == "play"


def require_teacher() -> dict[str, Any]:
    """页面入口守卫：没有教师登录态就停止渲染"""
    t = current_teacher()
    if not t:
        st.warning("请先登录教师账号")
        st.stop()
    return t


def current_class_id() -> str | None:
    return st.session_state.get(K_CLASS)


def set_current_class(class_id: str) -> None:
    st.session_state[K_CLASS] = class_id
    # 切换班级时清掉页面级临时状态
    for k in ("pending_score_students", "flash", "last_batch"):
        st.session_state.pop(k, None)


def require_class() -> tuple[dict[str, Any], dict[str, Any], str]:
    """
    页面守卫：要求已登录 + 已选班级 + 对该班级有成员关系。
    返回 (teacher, class, role_in_class)
    """
    teacher = require_teacher()
    cid = current_class_id()
    if not cid:
        st.info("还没有班级，请先到「班级管理」新建一个班级")
        st.stop()
    cls = db.get_class(cid)
    membership = db.get_membership(teacher["id"], cid)
    if not cls or not membership:
        st.error("你没有该班级的访问权限")
        st.stop()
    return teacher, cls, membership["teacher_role"]


def is_head(teacher: dict[str, Any], class_id: str) -> bool:
    """当前用户是否是该班班主任（投屏模式一律视为无管理权限）"""
    if is_play_mode():
        return False
    return db.is_head_teacher(teacher["id"], class_id)


def require_head(class_id: str) -> dict[str, Any]:
    """只有班主任才能进入的操作"""
    teacher = require_teacher()
    if not is_head(teacher, class_id):
        st.error("该操作仅班主任可用")
        st.stop()
    return teacher


# ---------------------------------------------------------------------------
# 家长端
# ---------------------------------------------------------------------------
def login_parent(class_id: str, student_no: str, parent_code: str) -> tuple[bool, str]:
    student = db.find_student_by_parent(class_id, student_no, parent_code)
    if not student:
        return False, "班级、学号或查看码不正确"
    st.session_state[K_ROLE] = "parent"
    st.session_state[K_STUDENT] = student
    st.session_state[K_PARENT_TOKEN] = sign_child_token(student["id"])
    st.session_state.pop(K_TEACHER, None)
    return True, "登录成功"


def current_parent_student() -> dict[str, Any] | None:
    """
    返回当前家长绑定的学生。
    额外校验签名令牌，防止有人手工改 session_state 里的 student_id 越权查看他人。
    """
    role = st.session_state.get(K_ROLE)
    student = st.session_state.get(K_STUDENT)
    token = st.session_state.get(K_PARENT_TOKEN, "")
    if role != "parent" or not student:
        return None
    if not verify_child_token(student["id"], token):
        return None
    # 每次从库里取最新数据（姓名、头像可能被老师改过）
    fresh = db.get_student(student["id"])
    if not fresh or not fresh.get("is_active"):
        return None
    return fresh


def require_parent() -> dict[str, Any]:
    s = current_parent_student()
    if not s:
        st.warning("家长登录已失效，请重新登录")
        st.stop()
    return s


# ---------------------------------------------------------------------------
# 投屏模式 / 退出
# ---------------------------------------------------------------------------
def login_play(class_id: str) -> None:
    """
    投屏模式：面向教室大屏，默认无登录、只读。
    为免班级数据被任意访问，投屏入口需输入"投屏口令"（班主任在设置里查看）。
    """
    st.session_state[K_ROLE] = "play"
    st.session_state[K_CLASS] = class_id


def logout() -> None:
    for k in (K_ROLE, K_TEACHER, K_STUDENT, K_PARENT_TOKEN, K_CLASS):
        st.session_state.pop(k, None)


def role_label() -> str:
    role = st.session_state.get(K_ROLE)
    if role == "parent":
        return "家长"
    if role == "play":
        return "投屏"
    if role == "teacher":
        t = current_teacher() or {}
        classes = db.list_classes_for_teacher(t.get("id", "")) if t else []
        cur = next((c for c in classes if c["id"] == current_class_id()), None)
        if cur:
            return "班主任" if cur["my_role"] == "head_teacher" else "科任老师"
        return "班主任" if t.get("role") == "head_teacher" else "科任老师"
    return "未登录"
