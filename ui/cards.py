"""
ui/cards.py —— 桌面大按钮网格（解决"卡片下有按钮"的布局问题）
=====================================================
Streamlit 的 st.button 无法塞进 HTML 卡片内部，所以：
  · 卡片区（头像/姓名/积分）用 HTML 渲染，展示信息
  · 按钮区紧跟其后，用同样列数的一行按钮，按钮文字即学生姓名
在平板上，按钮接触面积 ≥44px，比点小图标更稳。
"""

from __future__ import annotations

from typing import Callable

import streamlit as st

from core import ui


def avatar_button_grid(students: list[dict], per_row: int, size: int,
                       key_prefix: str, on_click: Callable[[dict], None],
                       score_key: str = "total_score", show_plus: bool = True,
                       rank_key: str | None = None) -> None:
    """
    学生卡 + 姓名按钮网格。
      students   学生列表
      per_row    每行人数
      on_click   点击按钮的回调（参数是该学生 dict）
      rank_key   若给 "rank"，卡片右上显示名次
    """
    if not students:
        return
    for i in range(0, len(students), per_row):
        chunk = students[i:i + per_row]
        cols = st.columns(per_row, gap="small")
        for col, s in zip(cols, chunk):
            with col:
                st.markdown(
                    ui.student_card_html(
                        s, int(s.get(score_key) or 0), size=size,
                        rank=int(s[rank_key]) if rank_key and s.get(rank_key) else None,
                        show_plus=show_plus,
                    ),
                    unsafe_allow_html=True,
                )
                if st.button(s["name"], key=f"{key_prefix}_{s['id']}",
                             use_container_width=True):
                    on_click(s)
