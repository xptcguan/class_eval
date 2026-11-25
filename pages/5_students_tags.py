"""
pages/5_students_tags.py —— 学生与标签（仅班主任）
=====================================
标签
  · 新增 / 编辑 / 停用 / 批量添加
  · 图标两种方式：输入 emoji，或从电脑上传图片（jpg/png/webp，≤2MB）
  · 上传后打分页与列表都显示这张图，优先级高于 emoji

学生
  · 按小组筛选、按积分排序总览
  · 单个学生的评价流水 / 档案编辑 / 头像更换
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from config import MAX_UPLOAD_MB, get_settings
from core import auth, avatars, cache as cdata, db, ui
from core.storage import delete_image, upload_image
from ui.nav import page_header, set_current_nav, teacher_shell

st.set_page_config(page_title="学生与标签", page_icon="🏷️", layout="wide",
                   initial_sidebar_state="expanded")

set_current_nav("students_tags")
teacher, cls, role = teacher_shell(required=True)
cid = st.session_state[auth.K_CLASS]

if role != "head_teacher":
    page_header("学生与标签", "", cls.get("name", ""))
    st.error("该页面仅班主任可访问。科任老师可以打分、看榜单、看记录。")
    st.stop()

page_header("学生与标签", "", cls.get("name", ""))

tab_tags, tab_students = st.tabs(["评价标签", "学生档案"])

# ===========================================================================
# 标签
# ===========================================================================
with tab_tags:
    tags_all = cdata.list_tags(cid, include_inactive=True)
    active_count = len([t for t in tags_all if t["is_active"]])
    st.caption(f"启用中 {active_count} 个 · 分值正数=加分项，负数=扣分项 · "
               "停用不影响历史记录 · 图标可上传图片")

    left, right = st.columns([1, 1])

    with left:
        st.markdown('<div class="ce-title">新增标签</div>', unsafe_allow_html=True)
        with st.form("new_tag", clear_on_submit=True):
            c1, c2, c3 = st.columns([1.8, 0.8, 0.8])
            name = c1.text_input("名称", placeholder="主动擦黑板")
            score = c2.number_input("分值", min_value=-100, max_value=100, value=2, step=1)
            icon = c3.text_input("emoji", value="⭐", max_chars=2)
            icon_file = st.file_uploader("或上传图标图片（可选，≤2MB）",
                                         type=["png", "jpg", "jpeg", "webp"],
                                         key="new_tag_icon")
            if st.form_submit_button("创建标签", type="primary", use_container_width=True):
                icon_img = ""
                if icon_file is not None:
                    if icon_file.size > 2 * 1024 * 1024:
                        st.error("图标图片超过 2MB")
                    else:
                        icon_img = upload_image(icon_file.getvalue(), icon_file.name,
                                                prefix="tagicons", cfg=get_settings())
                ok, msg = db.save_tag(cid, name, int(score), icon=icon or "⭐",
                                      icon_img=icon_img or None)
                if ok:
                    ui.flash(msg, "success")
                    st.rerun()
                else:
                    st.error(msg)

        with st.expander("批量添加", expanded=False):
            st.caption("每行一个：名称,分值（负数为扣分项）")
            bulk = st.text_area("内容", height=110, key="bulk_tags",
                                placeholder="主动擦黑板,2\n拾金不昧,3\n午休讲话,-2")
            if st.button("批量创建", disabled=not bulk.strip()):
                added, errs = 0, []
                for line in bulk.splitlines():
                    line = line.strip().replace("，", ",")
                    if not line:
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) < 2:
                        errs.append(f"格式不对：{line}")
                        continue
                    try:
                        v = int(float(parts[1]))
                    except ValueError:
                        errs.append(f"分值不是数字：{line}")
                        continue
                    ok, _ = db.save_tag(cid, parts[0], v)
                    added += 1 if ok else 0
                ui.flash(f"已创建 {added} 个标签", "success")
                if errs:
                    st.warning("部分未创建：\n- " + "\n- ".join(errs))
                st.rerun()

    with right:
        st.markdown('<div class="ce-title">现有标签</div>', unsafe_allow_html=True)

        def render_tags(items: list[dict]) -> None:
            if not items:
                st.caption("暂无")
                return
            for t in items:
                c0, c1, c2, c3, c4 = st.columns([0.5, 2.6, 1, 1, 1])
                with c0:
                    st.markdown(ui.tag_icon_html(t, 20), unsafe_allow_html=True)
                with c1:
                    state = "" if t["is_active"] else ' <span class="ce-sub">(已停用)</span>'
                    st.markdown(f"**{ui.esc(t['name'])}**{state}", unsafe_allow_html=True)
                with c2:
                    st.markdown(
                        f'<span class="tag-pill {"chip-plus" if int(t["score"])>0 else "chip-minus"}">'
                        f'{int(t["score"]):+d}</span>', unsafe_allow_html=True)
                with c3:
                    if st.button("编辑", key=f"etag_{t['id']}", use_container_width=True):
                        st.session_state["editing_tag"] = t["id"]
                with c4:
                    if t["is_active"]:
                        if st.button("停用", key=f"dtag_{t['id']}", use_container_width=True):
                            db.delete_tag(t["id"])
                            ui.flash(f"已停用「{t['name']}」", "info")
                            st.rerun()
                    else:
                        if st.button("启用", key=f"atag_{t['id']}", use_container_width=True):
                            db.save_tag(cid, t["name"], int(t["score"]), t["id"],
                                        t["icon"], t.get("icon_img") or None)
                            ui.flash("已重新启用", "success")
                            st.rerun()

                if st.session_state.get("editing_tag") == t["id"]:
                    with st.form(f"edittag_{t['id']}"):
                        e1, e2, e3 = st.columns([1.6, 0.8, 0.8])
                        nn = e1.text_input("名称", value=t["name"], key=f"n_{t['id']}")
                        ns = e2.number_input("分值", value=int(t["score"]), min_value=-100,
                                             max_value=100, step=1, key=f"s_{t['id']}")
                        ni = e3.text_input("emoji", value=t["icon"] or "⭐", max_chars=2,
                                           key=f"i_{t['id']}")
                        new_icon = st.file_uploader("换图标图片（上传后优先用图片）",
                                                    type=["png", "jpg", "jpeg", "webp"],
                                                    key=f"ic_{t['id']}")
                        b1, b2, b3 = st.columns(3)
                        save = b1.form_submit_button("保存", type="primary",
                                                     use_container_width=True)
                        clear = b2.form_submit_button("清除图片", use_container_width=True)
                        cancel = b3.form_submit_button("取消", use_container_width=True)
                    if cancel:
                        st.session_state.pop("editing_tag", None)
                        st.rerun()
                    if clear:
                        if t.get("icon_img"):
                            delete_image(t["icon_img"])
                        db.save_tag(cid, t["name"], int(t["score"]), t["id"],
                                    t["icon"] or "⭐", "")
                        st.session_state.pop("editing_tag", None)
                        ui.flash("已改回 emoji 图标", "info")
                        st.rerun()
                    if save:
                        icon_img = None
                        if new_icon is not None:
                            if new_icon.size > 2 * 1024 * 1024:
                                st.error("图标图片超过 2MB")
                            else:
                                if t.get("icon_img"):
                                    delete_image(t["icon_img"])
                                icon_img = upload_image(new_icon.getvalue(), new_icon.name,
                                                        prefix="tagicons", cfg=get_settings())
                        ok, msg = db.save_tag(cid, nn, int(ns), t["id"], ni or "⭐", icon_img)
                        st.session_state.pop("editing_tag", None)
                        if ok:
                            ui.flash(msg, "success")
                            st.rerun()
                        else:
                            st.error(msg)

        st.markdown("**加分项**")
        render_tags([t for t in tags_all if int(t["score"]) > 0])
        st.markdown("**扣分项**")
        render_tags([t for t in tags_all if int(t["score"]) < 0])

# ===========================================================================
# 学生档案
# ===========================================================================
with tab_students:
    students = cdata.list_students(cid)
    groups = cdata.list_groups_of_class(cid)
    if not students:
        ui.empty_state("还没有学生", "到「班级管理 → 学生名单」录入", "👥")
        st.stop()

    c1, c2 = st.columns(2)
    with c1:
        gfilter = st.selectbox("按小组看", ["全部"] + [g["name"] for g in groups], key="st_g")
    with c2:
        sfilter = st.selectbox("排序", ["按学号", "积分从高到低", "积分从低到高"], key="st_s")

    shown = students if gfilter == "全部" else [
        s for s in students if s["group_name"] == gfilter]
    if sfilter == "积分从高到低":
        shown = sorted(shown, key=lambda s: -(s["total_score"] or 0))
    elif sfilter == "积分从低到高":
        shown = sorted(shown, key=lambda s: (s["total_score"] or 0))

    if not shown:
        st.info("该小组暂无学生")
    else:
        st.markdown(
            '<div class="rank-grid" style="grid-template-columns:repeat(6,minmax(0,1fr))">'
            + "".join(
                f'<div class="rank-cell">'
                f'{ui.student_card_html(s, int(s["total_score"] or 0), size=58)}</div>'
                for s in shown) + "</div>",
            unsafe_allow_html=True,
        )

    st.markdown('<div class="ce-title" style="margin-top:16px">单个学生</div>',
                unsafe_allow_html=True)
    labels = {s["id"]: f"{s['student_no']} {s['name']}" for s in students}
    pick = st.selectbox("选择学生", list(labels), format_func=lambda i: labels[i])
    st_flow, st_edit = st.tabs(["评价流水", "档案与头像"])

    with st_flow:
        cur = db.get_student(pick)
        logs = db.query_logs(cid, student_id=pick, include_revoked=False, limit=200)
        valid = [x for x in logs if x["status"] == "normal"]
        st.markdown(
            ui.dashboard([
                {"label": "累计积分", "value": ui.fmt_score(int(cur["total_score"] or 0), False),
                 "icon": "∑"},
                {"label": "有效评价", "value": f"{len(valid)} 条", "icon": "📋"},
                {"label": "家长查看码", "value": cur["parent_code"], "icon": "🔑"},
                {"label": "学号", "value": cur["student_no"], "icon": "#"},
            ]),
            unsafe_allow_html=True,
        )
        if not logs:
            st.caption("暂无评价记录")
        else:
            df = pd.DataFrame([{
                "时间": (x["created_at"].strftime("%Y-%m-%d %H:%M")
                         if isinstance(x["created_at"], dt.datetime) else x["created_at"]),
                "标签": x["tag_name"],
                "分值": int(x["score"]),
                "评语": x["remark"] or "",
                "教师": x["recorded_by_name"] or "",
                "状态": "已撤回" if x["status"] == "revoked" else "有效",
            } for x in logs])
            st.dataframe(df, use_container_width=True, hide_index=True,
                         height=min(480, 38 + 35 * len(df)))

    with st_edit:
        cur = db.get_student(pick)
        with st.form(f"std_edit_{pick}"):
            c1, c2, c3 = st.columns(3)
            n_no = c1.text_input("学号", value=cur["student_no"])
            n_name = c2.text_input("姓名", value=cur["name"])
            n_gender = c3.selectbox("性别", ["", "男", "女"],
                                    index=["", "男", "女"].index(cur["gender"] or ""))
            c4, c5 = st.columns(2)
            gnames = [""] + [g["name"] for g in groups]
            n_group = c4.selectbox("小组", gnames,
                                   index=gnames.index(cur["group_name"])
                                   if cur["group_name"] in gnames else 0)
            n_avatar = c5.selectbox("预设头像（32 款）", avatars.AVATAR_KEYS,
                                    index=avatars.AVATAR_KEYS.index(cur["avatar_key"])
                                    if cur["avatar_key"] in avatars.AVATAR_KEYS else 0,
                                    format_func=lambda k: avatars.AVATAR_NAMES.get(k, k))
            n_remark = st.text_area("备注", value=cur.get("remark") or "", height=68)
            if st.form_submit_button("保存", type="primary"):
                db.update_student(pick, student_no=n_no.strip(), name=n_name.strip(),
                                  gender=n_gender, group_name=n_group,
                                  avatar_key=n_avatar, remark=n_remark)
                ui.flash("已保存", "success")
                st.rerun()

        st.markdown('<div class="ce-title" style="margin-top:12px">自定义头像</div>',
                    unsafe_allow_html=True)
        up = st.file_uploader("上传图片（≤5MB）", type=["png", "jpg", "jpeg", "webp"],
                              key="det_avatar")
        if up is not None and st.button("使用该图片作为头像", type="primary"):
            if up.size > MAX_UPLOAD_MB * 1024 * 1024:
                st.error(f"图片超过 {MAX_UPLOAD_MB}MB")
            else:
                url = upload_image(up.getvalue(), up.name, prefix="avatars",
                                   cfg=get_settings())
                db.set_student_avatar(pick, avatar_key="", avatar_url=url)
                ui.flash("头像已更新", "success")
                st.rerun()
        if cur.get("avatar_url") and st.button("恢复预设头像"):
            delete_image(cur["avatar_url"])
            db.set_student_avatar(pick, avatar_key=cur.get("avatar_key") or "a01",
                                  avatar_url="")
            ui.flash("已恢复预设头像", "info")
            st.rerun()

ui.show_flash()
