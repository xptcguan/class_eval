"""
core/cache.py —— 只读查询的缓存层
=====================================================
为什么单独一层，而不是直接给 db.py 加 @st.cache_data：
  db.py 的函数大多带 cfg（Config dataclass 不可哈希），直接加装饰器会报错。
  这里只暴露"纯参数"的包装，参数全为可哈希基础类型。

⚠️ 隐私红线（务必遵守）
  st.cache_data 是**进程内跨会话共享**的。因此：
  · 缓存函数内部绝不能读 st.session_state，也不能按"当前用户"隐式过滤；
  · 所有参数必须显式带上 class_id / student_id / teacher_id；
  · 家长端只缓存以 student_id 为键的查询，绝不缓存"全班"结果给家长用。

失效策略
  · 写操作后由 db._invalidate_cache() 调 st.cache_data.clear() 全清（最简单可靠）；
  · TTL 60~90 秒兜底多进程延迟（Streamlit Cloud 多 worker 各自持有缓存）。
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from core import db


# ------------------------------------------------ 班级 / 身份
@st.cache_data(ttl=90, show_spinner=False)
def list_classes_for_teacher(teacher_id: str) -> list[dict[str, Any]]:
    return db.list_classes_for_teacher(teacher_id)


@st.cache_data(ttl=90, show_spinner=False)
def list_active_classes() -> list[dict[str, Any]]:
    return db.list_active_classes()


@st.cache_data(ttl=90, show_spinner=False)
def get_class(class_id: str) -> dict[str, Any] | None:
    return db.get_class(class_id)


@st.cache_data(ttl=90, show_spinner=False)
def get_membership(teacher_id: str, class_id: str) -> dict[str, Any] | None:
    return db.get_membership(teacher_id, class_id)


@st.cache_data(ttl=90, show_spinner=False)
def list_class_teachers(class_id: str) -> list[dict[str, Any]]:
    return db.list_class_teachers(class_id)


@st.cache_data(ttl=90, show_spinner=False)
def get_class_settings(class_id: str) -> dict[str, Any]:
    return db.get_class_settings(class_id)


# ------------------------------------------------ 学生 / 小组 / 标签
@st.cache_data(ttl=90, show_spinner=False)
def list_students(class_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
    return db.list_students(class_id, include_inactive=include_inactive)


@st.cache_data(ttl=90, show_spinner=False)
def get_student(student_id: str) -> dict[str, Any] | None:
    return db.get_student(student_id)


@st.cache_data(ttl=90, show_spinner=False)
def list_groups_of_class(class_id: str) -> list[dict[str, Any]]:
    return db.list_groups_of_class(class_id)


@st.cache_data(ttl=90, show_spinner=False)
def list_tags(class_id: str, category: str | None = None,
              include_inactive: bool = False) -> list[dict[str, Any]]:
    return db.list_tags(class_id, category=category, include_inactive=include_inactive)


# ------------------------------------------------ 统计 / 榜单
@st.cache_data(ttl=60, show_spinner=False)
def class_overview(class_id: str) -> dict[str, Any]:
    return db.class_overview(class_id)


@st.cache_data(ttl=60, show_spinner=False)
def get_ranking(class_id: str, period: str = "all") -> list[dict[str, Any]]:
    return db.get_ranking(class_id, period)


@st.cache_data(ttl=60, show_spinner=False)
def get_group_ranking(class_id: str, period: str = "all") -> list[dict[str, Any]]:
    return db.get_group_ranking(class_id, period)


@st.cache_data(ttl=30, show_spinner=False)
def query_logs(class_id: str, student_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """只用于"最近评价"这类轻量列表；复杂筛选仍直接查库"""
    return db.query_logs(class_id, student_id=student_id, limit=limit)


@st.cache_data(ttl=60, show_spinner=False)
def list_audit_logs(class_id: str, limit: int = 100) -> list[dict[str, Any]]:
    return db.list_audit_logs(class_id, limit=limit)


def invalidate() -> None:
    """写操作后清全部查询缓存（db._invalidate_cache 已自动调用，这里供页面显式用）"""
    try:
        st.cache_data.clear()
    except Exception:
        pass
