"""
pages/1_classes.py —— 班级管理
=====================================
  · 我的班级：列表 / 新建 / 编辑 / 归档。admin 这类"还没有班级"的账号，
    页面直接展开新建表单，不会再出现"提示去班级管理却进不去"的死循环。
  · 学生名单：单个添加 / 批量粘贴导入 / 32 款预设头像 / 上传自定义头像
  · 小组管理：增删改组，批量把学生分到组
  · 科任老师：录入「任教科目」，页面身份显示为「数学老师」
  · 家长查看码：一览、导出、重置
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from core import auth, avatars, cache as cdata, db, ui
from ui.nav import go, page_header, set_current_nav, teacher_shell

st.set_page_config(page_title="班级管理", page_icon="🏫", layout="wide",
                   initial_sidebar_state="expanded")

set_current_nav("classes")
teacher, cls, role = teacher_shell(required=False)
# 班主任授权看账号级角色（本班没有成员关系时 role 为空，但该账号本身可能是班主任/管理员）
is_head = (role == "head_teacher") or (teacher.get("role") == "head_teacher")
cid = st.session_state.get(auth.K_CLASS)

page_header("班级管理", "", (cls or {}).get("name", ""))

tab_class, tab_students, tab_groups, tab_teachers, tab_codes = st.tabs(
    ["我的班级", "学生名单", "小组管理", "科任老师", "家长查看码"]
)

# ===========================================================================
# 1. 我的班级
# ===========================================================================
with tab_class:
    classes = cdata.list_classes_for_teacher(teacher["id"])

    if is_head:
        with st.expander("新建班级", expanded=not classes, icon=":material/add:"):
            with st.form("create_class"):
                c1, c2, c3 = st.columns(3)
                name = c1.text_input("班级名称 *", placeholder="七年级二班")
                grade = c2.text_input("年级", placeholder="七年级")
                year = c3.text_input("学年", placeholder="2026-2027学年")
                with_defaults = st.checkbox("同时创建默认评价标签和 6 个小组", value=True)
                created = st.form_submit_button("创建班级", type="primary",
                                                use_container_width=True)
            if created:
                if not name.strip():
                    st.error("班级名称不能为空")
                else:
                    new_id = db.create_class(name, teacher["id"], grade, year, with_defaults)
                    db.write_audit(new_id, teacher, "create_class", f"新建班级 {name}")
                    auth.set_current_class(new_id)
                    ui.flash(f"班级「{name.strip()}」创建成功", "success")
                    go("scoring")

    if not classes:
        if is_head:
            ui.empty_state("还没有班级", "在下方填写班级名称即可创建（也可以展开上方的「新建班级」）", "🏫")
            # 空班级时把新建表单直接摆在页面上，避免只给一句提示却没有入口
            with st.form("create_class_inline"):
                c1, c2, c3 = st.columns(3)
                nm2 = c1.text_input("班级名称 *", placeholder="七年级二班", key="inline_name")
                gd2 = c2.text_input("年级", placeholder="七年级", key="inline_grade")
                yr2 = c3.text_input("学年", placeholder="2026-2027学年", key="inline_year")
                if st.form_submit_button("立即创建", type="primary", use_container_width=True):
                    if not nm2.strip():
                        st.error("班级名称不能为空")
                    else:
                        nid = db.create_class(nm2, teacher["id"], gd2, yr2, True)
                        db.write_audit(nid, teacher, "create_class", f"新建班级 {nm2}")
                        auth.set_current_class(nid)
                        ui.flash(f"班级「{nm2.strip()}」创建成功", "success")
                        go("classes")
        else:
            ui.empty_state("还没有班级", "请联系班主任把你加入班级。", "🏫")
    else:
        st.markdown('<div class="ce-title">我管理的班级</div>', unsafe_allow_html=True)
        for c in classes:
            role_label = ui.role_text(c["my_role"], c.get("my_subject") or "")
            with st.container():
                col1, col2, col3, col4 = st.columns([3.2, 1.1, 1.1, 1.8])
                with col1:
                    archived = (' <span class="tag-pill">已归档</span>'
                                if c["is_archived"] else "")
                    st.markdown(
                        f'<div style="font-weight:700;font-size:15px">{ui.esc(c["name"])}{archived}</div>'
                        f'<div class="ce-sub">{ui.esc(c.get("grade") or "")} '
                        f'{ui.esc(c.get("school_year") or "")} · 学生 {c["student_count"]} 人 · '
                        f'<span class="sb-role {"head" if c["my_role"] == "head_teacher" else "subject"}">'
                        f'{ui.esc(role_label)}</span></div>',
                        unsafe_allow_html=True,
                    )
                with col2:
                    if st.button("进入", key=f"enter_{c['id']}", use_container_width=True,
                                 type="primary" if c["id"] == cid else "secondary"):
                        auth.set_current_class(c["id"])
                        go("scoring")
                with col3:
                    if st.button("榜单", key=f"rank_{c['id']}", use_container_width=True):
                        auth.set_current_class(c["id"])
                        go("ranking")
                with col4:
                    if c["my_role"] == "head_teacher":
                        s1, s2 = st.columns(2)
                        if s1.button("编辑", key=f"edit_{c['id']}", use_container_width=True):
                            st.session_state[f"edit_class_{c['id']}"] = True
                        if s2.button("恢复" if c["is_archived"] else "归档",
                                     key=f"arch_{c['id']}", use_container_width=True):
                            db.archive_class(c["id"], not bool(c["is_archived"]))
                            ui.flash("已恢复" if c["is_archived"] else "已归档", "info")
                            st.rerun()
                    else:
                        st.caption("科任老师仅可打分")
                if st.session_state.get(f"edit_class_{c['id']}"):
                    with st.form(f"edit_form_{c['id']}"):
                        e1, e2, e3 = st.columns(3)
                        n = e1.text_input("班级名称", value=c["name"], key=f"n_{c['id']}")
                        g = e2.text_input("年级", value=c.get("grade") or "", key=f"g_{c['id']}")
                        y = e3.text_input("学年", value=c.get("school_year") or "", key=f"y_{c['id']}")
                        b1, b2 = st.columns(2)
                        if b1.form_submit_button("保存", type="primary", use_container_width=True):
                            db.update_class(c["id"], n, g, y)
                            st.session_state.pop(f"edit_class_{c['id']}", None)
                            ui.flash("班级信息已更新", "success")
                            st.rerun()
                        if b2.form_submit_button("取消", use_container_width=True):
                            st.session_state.pop(f"edit_class_{c['id']}", None)
                            st.rerun()

# ===========================================================================
# 2. 学生名单
# ===========================================================================
with tab_students:
    if not cid:
        st.info("请先选择或新建一个班级")
    else:
        students = cdata.list_students(cid, include_inactive=True)
        active = [s for s in students if s["is_active"]]
        st.markdown(
            ui.dashboard([
                {"label": "在班学生", "value": f"{len(active)} 人", "icon": "👥"},
                {"label": "已移出", "value": f"{len(students) - len(active)} 人", "icon": "🚪"},
                {"label": "小组数", "value": f"{len(db.list_groups_of_class(cid))} 个", "icon": "🧩"},
            ]),
            unsafe_allow_html=True,
        )
        groups = [g["name"] for g in db.list_groups_of_class(cid)]

        if is_head:
            t_add, t_bulk, t_edit = st.tabs(["单个添加", "批量导入", "编辑 / 头像"])
        else:
            t_add, t_bulk, t_edit = None, None, None

        if t_add is not None:
            with t_add:
                with st.form("add_student", clear_on_submit=True):
                    c1, c2, c3, c4 = st.columns([1, 1.6, 0.8, 1.2])
                    no = c1.text_input("学号 *", placeholder="01")
                    nm = c2.text_input("姓名 *")
                    gender = c3.selectbox("性别", ["", "男", "女"])
                    grp = c4.selectbox("小组", [""] + groups)
                    avatar_key = st.selectbox(
                        "预设头像（32 款）", avatars.AVATAR_KEYS,
                        format_func=lambda k: avatars.AVATAR_NAMES.get(k, k), index=1)
                    if st.form_submit_button("添加学生", type="primary",
                                             use_container_width=True):
                        ok, msg = db.add_student(cid, no, nm, gender, grp, avatar_key)
                        if ok:
                            ui.flash(msg, "success")
                            st.rerun()
                        else:
                            st.error(msg)

            with t_bulk:
                st.caption("每行一个：学号,姓名,性别,小组（后两项可空）；支持中文逗号与 Tab")
                text = st.text_area("粘贴名单", height=170,
                                    placeholder="01,郭宸瑄,女,一\n02,石舒白,女,一\n03,梁子轩,男,一",
                                    key="bulk_text")
                if st.button("导入名单", type="primary", disabled=not text.strip()):
                    rows = []
                    for line in text.splitlines():
                        line = line.strip().replace("\t", ",").replace("，", ",")
                        if not line:
                            continue
                        p = [x.strip() for x in line.split(",")]
                        rows.append({
                            "student_no": p[0] if len(p) > 0 else "",
                            "name": p[1] if len(p) > 1 else "",
                            "gender": p[2] if len(p) > 2 else "",
                            "group_name": p[3] if len(p) > 3 else "",
                        })
                    ok_n, errs = db.bulk_add_students(cid, rows)
                    ui.flash(f"成功导入 {ok_n} 名学生", "success")
                    if errs:
                        st.warning("部分未导入：\n- " + "\n- ".join(errs[:10]))
                    st.rerun()

            with t_edit:
                if not students:
                    st.info("暂无学生")
                else:
                    labels = {s["id"]: f"{s['student_no']} {s['name']}"
                                       + ("" if s["is_active"] else "（已移出）")
                              for s in students}
                    pick = st.selectbox("选择学生", list(labels),
                                        format_func=lambda i: labels[i])
                    cur = db.get_student(pick)
                    with st.form("edit_student"):
                        c1, c2, c3, c4 = st.columns([1, 1.6, 0.8, 1.2])
                        e_no = c1.text_input("学号", value=cur["student_no"])
                        e_nm = c2.text_input("姓名", value=cur["name"])
                        e_gender = c3.selectbox("性别", ["", "男", "女"],
                                                index=["", "男", "女"].index(cur["gender"] or ""))
                        e_grp = c4.selectbox("小组", [""] + groups,
                                             index=([""] + groups).index(cur["group_name"])
                                             if cur["group_name"] in groups else 0)
                        e_avatar = st.selectbox(
                            "预设头像（32 款）", avatars.AVATAR_KEYS,
                            index=avatars.AVATAR_KEYS.index(cur["avatar_key"])
                            if cur["avatar_key"] in avatars.AVATAR_KEYS else 0,
                            format_func=lambda k: avatars.AVATAR_NAMES.get(k, k))
                        note = st.text_area("备注", value=cur.get("remark") or "", height=68)
                        s1, s2 = st.columns(2)
                        save = s1.form_submit_button("保存修改", type="primary",
                                                     use_container_width=True)
                        toggle = s2.form_submit_button(
                            "移出班级" if cur["is_active"] else "恢复在班",
                            use_container_width=True)
                    if save:
                        db.update_student(pick, student_no=e_no.strip(), name=e_nm.strip(),
                                          gender=e_gender, group_name=e_grp,
                                          avatar_key=e_avatar, remark=note)
                        ui.flash("学生信息已更新", "success")
                        st.rerun()
                    if toggle:
                        if cur["is_active"]:
                            db.remove_student(pick)
                            ui.flash("已移出班级，历史积分保留", "info")
                        else:
                            db.update_student(pick, is_active=1)
                            ui.flash("已恢复在班", "success")
                        st.rerun()

                    st.markdown('<div class="ce-title" style="margin-top:14px">自定义头像</div>',
                                unsafe_allow_html=True)
                    st.caption("上传孩子自己的照片（≤5MB，jpg/png/webp），上传后优先使用这张图。")
                    up = st.file_uploader("选择图片", type=["png", "jpg", "jpeg", "webp"],
                                          key="avatar_upload")
                    a1, a2 = st.columns(2)
                    if up is not None and a1.button("应用为头像", type="primary",
                                                    use_container_width=True):
                        from config import MAX_UPLOAD_MB, get_settings
                        from core.storage import upload_image

                        if up.size > MAX_UPLOAD_MB * 1024 * 1024:
                            st.error(f"图片超过 {MAX_UPLOAD_MB}MB")
                        else:
                            url = upload_image(up.getvalue(), up.name, prefix="avatars",
                                               cfg=get_settings())
                            db.set_student_avatar(pick, avatar_key="", avatar_url=url)
                            ui.flash("头像已更新", "success")
                            st.rerun()
                    if cur.get("avatar_url") and a2.button("恢复预设头像",
                                                           use_container_width=True):
                        from core.storage import delete_image

                        delete_image(cur["avatar_url"])
                        db.set_student_avatar(pick,
                                              avatar_key=cur.get("avatar_key") or "a01",
                                              avatar_url="")
                        ui.flash("已恢复预设头像", "info")
                        st.rerun()

        st.markdown('<div class="ce-title" style="margin-top:14px">在班学生</div>',
                    unsafe_allow_html=True)
        if not active:
            st.info("还没有学生")
        else:
            from ui.cards import avatar_button_grid

            def _open_student(s: dict) -> None:
                st.session_state["st_pick"] = s["id"]
                st.session_state["st_tab"] = "edit"

            avatar_button_grid(active, 6, 60, "cls_stu", _open_student)

# ===========================================================================
# 3. 小组管理
# ===========================================================================
with tab_groups:
    if not cid:
        st.info("请先选择班级")
    else:
        groups = cdata.list_groups_of_class(cid)
        students = db.list_students(cid)
        c1, c2 = st.columns([1.2, 1])
        with c1:
            st.markdown('<div class="ce-title">小组列表</div>', unsafe_allow_html=True)
            if not groups:
                st.caption("还没有小组")
            for g in groups:
                members = [s for s in students if s["group_name"] == g["name"]]
                row1, row2 = st.columns([5, 1])
                with row1:
                    st.markdown(
                        f'<div style="padding:6px 0"><b>{ui.esc(g["name"])}</b>'
                        f'<span class="ce-sub"> · {len(members)} 人 · </span>'
                        f'<span class="ce-sub">{ui.esc("、".join(m["name"] for m in members[:10]))}'
                        f'{"…" if len(members) > 10 else ""}</span></div>',
                        unsafe_allow_html=True,
                    )
                with row2:
                    if is_head and st.button("删除", key=f"delg_{g['id']}",
                                             use_container_width=True):
                        db.delete_group(g["id"])
                        ui.flash(f"已删除小组 {g['name']}", "info")
                        st.rerun()
        with c2:
            if is_head:
                with st.form("group_form"):
                    gname = st.text_input("新建小组", placeholder="十一")
                    if st.form_submit_button("创建", type="primary", use_container_width=True):
                        ok, msg = db.save_group(cid, gname)
                        if ok:
                            ui.flash(msg, "success")
                            st.rerun()
                        else:
                            st.error(msg)
                st.markdown('<div class="ce-title" style="margin-top:12px">批量分组</div>',
                            unsafe_allow_html=True)
                if students:
                    sel = st.multiselect(
                        "选择学生", [s["id"] for s in students],
                        format_func=lambda i: next(
                            f"{x['student_no']} {x['name']}" for x in students
                            if x["id"] == i))
                    target = st.selectbox("目标小组", [""] + [g["name"] for g in groups])
                    if st.button("保存分组", type="primary", disabled=not sel):
                        for sid in sel:
                            db.update_student(sid, group_name=target)
                        ui.flash(f"已把 {len(sel)} 名学生分到「{target or '未分组'}」", "success")
                        st.rerun()
            else:
                st.caption("只有班主任可以管理小组")

# ===========================================================================
# 4. 科任老师（含任教科目）
# ===========================================================================
with tab_teachers:
    if not cid:
        st.info("请先选择班级")
    elif not is_head:
        st.caption("只有班主任可以管理科任老师")
    else:
        st.markdown('<div class="ce-title">本班任课老师</div>', unsafe_allow_html=True)
        rows = cdata.list_class_teachers(cid)
        for r in rows:
            c1, c2, c3 = st.columns([3, 2.2, 1])
            with c1:
                st.markdown(
                    f'<div style="padding:6px 0"><b>{ui.esc(r["display_name"])}</b>'
                    f'<span class="ce-sub">（{ui.esc(r["username"])}）</span> '
                    f'<span class="sb-role {"head" if r["teacher_role"] == "head_teacher" else "subject"}">'
                    f'{ui.esc(ui.role_text(r["teacher_role"], r.get("subject") or ""))}</span></div>',
                    unsafe_allow_html=True,
                )
            with c2:
                if r["teacher_role"] != "head_teacher":
                    opts = ui.subject_options()
                    cur_idx = opts.index(r["subject"]) if (r.get("subject") or "") in opts else 0
                    subj = st.selectbox("任教科目", opts, index=cur_idx,
                                        key=f"subj_sel_{r['id']}",
                                        label_visibility="collapsed")
                    other = ""
                    if subj == "其他":
                        other = st.text_input("其他科目", value=r.get("subject") or "",
                                              key=f"subj_other_{r['id']}", placeholder="如 书法")
                    if st.button("保存科目", key=f"save_subj_{r['id']}",
                                 use_container_width=True):
                        final = (other.strip() or "其他") if subj == "其他" else subj
                        db.add_teacher_to_class(cid, r["id"], "subject_teacher", final)
                        ui.flash(f"已设为「{ui.role_text('subject_teacher', final)}」", "success")
                        st.rerun()
            with c3:
                if r["teacher_role"] != "head_teacher":
                    if st.button("移除", key=f"rm_{r['id']}", use_container_width=True):
                        ok, msg = db.remove_teacher_from_class(cid, r["id"])
                        if ok:
                            ui.flash(msg, "info")
                            st.rerun()
                        else:
                            st.error(msg)

        st.markdown('<div class="ce-title" style="margin-top:16px">添加科任老师</div>',
                    unsafe_allow_html=True)
        t1, t2 = st.tabs(["已有账号加入", "新建账号并加入"])

        with t1:
            all_teachers = db.list_teachers()
            in_class = {r["id"] for r in rows}
            candidates = [t for t in all_teachers if t["id"] not in in_class]
            if not candidates:
                st.info("没有可添加的账号，可切到右侧新建")
            else:
                labels = {t["id"]: f"{t['display_name']}（{t['username']}）"
                          for t in candidates}
                pick = st.selectbox("老师", list(labels), format_func=lambda i: labels[i],
                                    key="add_pick")
                subj = st.selectbox("任教科目", ui.subject_options(), key="add_subj")
                other = st.text_input("其他科目（选「其他」时填）", key="add_subj_other",
                                      placeholder="如 书法")
                if st.button("加入本班", type="primary"):
                    final = (other.strip() or "其他") if subj == "其他" else subj
                    ok, msg = db.add_teacher_to_class(cid, pick, "subject_teacher", final)
                    db.write_audit(cid, teacher, "add_teacher",
                                   f"添加科任 {labels[pick]} 科目 {final}")
                    if ok:
                        ui.flash(f"{msg}，身份显示为「{ui.role_text('subject_teacher', final)}」",
                                 "success")
                        st.rerun()
                    else:
                        st.error(msg)

        with t2:
            with st.form("new_teacher"):
                c1, c2 = st.columns(2)
                u = c1.text_input("登录账号", placeholder="t_math01")
                d = c2.text_input("姓名", placeholder="王老师")
                p = c1.text_input("初始密码", type="password", placeholder="至少 6 位")
                subj2 = c2.selectbox("任教科目", ui.subject_options(), key="new_subj")
                go_btn = st.form_submit_button("创建并加入本班", type="primary")
            if go_btn:
                ok, msg = db.create_teacher(u, p, d, role="subject_teacher",
                                            must_change_pwd=True)
                if ok:
                    t_new = next((x for x in db.list_teachers()
                                  if x["username"] == u.strip()), None)
                    if t_new:
                        db.add_teacher_to_class(cid, t_new["id"], "subject_teacher", subj2)
                    ui.flash(f"{msg}，已加入本班并设为「"
                             f"{ui.role_text('subject_teacher', subj2)}」，请把账号密码告知该老师。",
                             "success")
                    st.rerun()
                else:
                    st.error(msg)

# ===========================================================================
# 5. 家长查看码
# ===========================================================================
with tab_codes:
    if not cid:
        st.info("请先选择班级")
    elif not is_head:
        st.caption("只有班主任可以查看和重置家长查看码")
    else:
        students = db.list_students(cid)
        st.caption("家长用「班级 + 学号 + 查看码」登录，只能看到自己孩子的记录。")
        if students:
            df = pd.DataFrame([{
                "学号": s["student_no"], "姓名": s["name"], "小组": s["group_name"],
                "家长查看码": s["parent_code"], "累计积分": s["total_score"],
            } for s in students])
            st.dataframe(df, use_container_width=True, hide_index=True,
                         height=min(560, 40 + 35 * len(df)))
            buf = io.BytesIO()
            df.to_csv(buf, index=False, encoding="utf-8-sig")
            st.download_button("导出查看码 CSV", buf.getvalue(), "家长查看码.csv",
                               "text/csv", icon=":material/download:")
            pick = st.selectbox("重置某学生的查看码", [s["id"] for s in students],
                                format_func=lambda i: next(
                                    f"{x['student_no']} {x['name']}" for x in students
                                    if x["id"] == i))
            if st.button("重置查看码"):
                new_code = db.reset_parent_code(pick)
                nm = next(x["name"] for x in students if x["id"] == pick)
                db.write_audit(cid, teacher, "reset_parent_code", f"重置 {nm} 的家长查看码")
                ui.flash(f"{nm} 的新查看码：{new_code}", "success")
                st.rerun()

ui.show_flash()
