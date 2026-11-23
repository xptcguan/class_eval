"""
pages/6_settings_export.py —— 系统设置 / 数据导出 / 部署自检
=====================================
- 班级设置：班级名称、榜单是否显示名次
- 账号设置：修改密码、班主任分配账号
- 数据导出：一键导出全量德育台账 Excel
- 部署自检：当前运行模式、数据库连通性、存储桶状态（云端排查用）
- 数据备份：本地模式下载 SQLite 文件；云端提示到 Supabase 后台备份
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from config import get_settings
from core import auth, db, exporter, ui
from core.storage import check_supabase_connection
from ui.nav import go, page_header, set_current_nav, teacher_shell

st.set_page_config(page_title="设置与导出", page_icon="⚙️", layout="wide", initial_sidebar_state="expanded")

set_current_nav("settings_export")
teacher, cls, role = teacher_shell(required=True)
cid = st.session_state[auth.K_CLASS]
is_head = role == "head_teacher"
cfg = get_settings()

page_header("设置与导出", "", cls.get("name", ""))

tab_class, tab_account, tab_export, tab_sys = st.tabs(
    ["🏫 班级设置", "🔐 账号安全", "📤 数据导出", "🔧 运行状态"]
)

# ===========================================================================
# 班级设置
# ===========================================================================
with tab_class:
    if not is_head:
        st.caption("仅班主任可修改班级设置")
    else:
        with st.form("class_cfg"):
            c1, c2, c3 = st.columns(3)
            n = c1.text_input("班级名称", value=cls.get("name", ""))
            g = c2.text_input("年级", value=cls.get("grade") or "")
            y = c3.text_input("学年", value=cls.get("school_year") or "")
            if st.form_submit_button("保存班级信息", type="primary"):
                db.update_class(cid, n, g, y)
                ui.flash("班级信息已保存", "success")
                st.rerun()

        st.markdown("---")
        s = db.get_class_settings(cid)
        show = st.toggle("榜单显示名次", value=bool(s.get("show_rank", 1)),
                         help="关闭后学生端与投屏端只显示分数，不显示第几名，减少攀比")
        if show != bool(s.get("show_rank", 1)):
            db.set_show_rank(cid, show)
            ui.flash("设置已保存", "success")
            st.rerun()

        st.markdown("---")
        with st.expander("🗑 归档班级"):
            st.caption("归档后班级不出现在家长/投屏的班级列表，但数据全部保留，可随时恢复。")
            if st.button("归档本班"):
                db.archive_class(cid, True)
                ui.flash("已归档，可在「班级管理」恢复", "info")
                st.rerun()

# ===========================================================================
# 账号安全
# ===========================================================================
with tab_account:
    st.markdown(f"当前账号：**{teacher.get('display_name')}**（{teacher.get('username')}）")
    st.caption("首次登录请立即修改默认密码。密码以 PBKDF2 哈希存储，管理员也无法看到明文。")

    with st.form("change_pwd"):
        c1, c2, c3 = st.columns(3)
        old = c1.text_input("原密码", type="password")
        new = c2.text_input("新密码", type="password", placeholder="至少 6 位")
        new2 = c3.text_input("确认新密码", type="password")
        if st.form_submit_button("修改密码", type="primary"):
            if new != new2:
                st.error("两次输入的新密码不一致")
            else:
                ok, msg = db.change_password(teacher["id"], old, new)
                if ok:
                    ui.flash(msg, "success")
                    st.rerun()
                else:
                    st.error(msg)

    with st.form("change_name"):
        c1, c2 = st.columns([2, 1])
        dn = c1.text_input("显示姓名", value=teacher.get("display_name", ""))
        if c2.form_submit_button("保存", use_container_width=True):
            db.update_teacher(teacher["id"], display_name=dn.strip())
            fresh = db.get_teacher(teacher["id"])
            st.session_state[auth.K_TEACHER] = fresh
            ui.flash("姓名已更新", "success")
            st.rerun()

    if is_head:
        st.markdown("---")
        st.markdown('<div class="ce-title">本班老师账号</div>', unsafe_allow_html=True)
        rows = db.list_class_teachers(cid)
        st.dataframe(pd.DataFrame([{
            "姓名": r["display_name"], "账号": r["username"],
            "班级角色": "班主任" if r["teacher_role"] == "head_teacher" else "科任老师",
            "学科": r.get("subject") or "",
        } for r in rows]), use_container_width=True, hide_index=True)
        st.caption("添加 / 移除科任老师请到「班级管理 → 科任老师」")

# ===========================================================================
# 数据导出
# ===========================================================================
with tab_export:
    if not is_head:
        st.caption("导出功能仅班主任可用")
    else:
        st.markdown('<div class="ce-title">德育评价台账</div>', unsafe_allow_html=True)
        st.caption("导出全量记录（含已撤回标注），另附「学生积分汇总」sheet，表头可直接用于学校德育归档。")

        c1, c2 = st.columns(2)
        with c1:
            use_range = st.checkbox("限定时间范围", value=False)
        with c2:
            rng = st.date_input(
                "时间范围",
                value=(dt.date.today().replace(day=1), dt.date.today()),
                disabled=not use_range,
            )

        if st.button("生成台账文件", type="primary"):
            start = end = None
            label = "全部时间"
            if use_range and isinstance(rng, tuple) and len(rng) == 2:
                start = dt.datetime.combine(rng[0], dt.time.min)
                end = dt.datetime.combine(rng[1], dt.time.max)
                label = f"{rng[0]} ~ {rng[1]}"
            rows = db.export_rows(cid, start, end, include_revoked=True)
            stats = db.apply_competition_rank(db.get_ranking(cid, "all"))
            data = exporter.export_excel(rows, cls.get("name", ""), stats, label,
                                         teacher.get("display_name", ""), start, end)
            st.session_state["full_export"] = data
            st.session_state["full_export_name"] = exporter.filename(cls.get("name", ""), start, end)
            st.success(f"已生成，共 {len(rows)} 条记录")

        if st.session_state.get("full_export"):
            st.download_button(
                "⬇️ 下载 Excel",
                data=st.session_state["full_export"],
                file_name=st.session_state.get("full_export_name", "台账.xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )

        st.markdown("---")
        st.markdown("**学生花名册**")
        students = db.list_students(cid)
        if students:
            df = pd.DataFrame([{
                "学号": s["student_no"], "姓名": s["name"], "性别": s["gender"],
                "小组": s["group_name"], "累计积分": s["total_score"],
                "家长查看码": s["parent_code"],
            } for s in students])
            st.dataframe(df, use_container_width=True, hide_index=True)
            import io

            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, sheet_name="学生花名册", index=False)
            st.download_button("⬇️ 下载花名册 Excel", buf.getvalue(),
                               f"学生花名册_{cls.get('name','')}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.markdown("---")
        if not cfg.is_cloud:
            st.markdown("**本地数据备份**")
            st.caption("本地开发模式下，可直接下载 SQLite 数据库文件做备份。")
            try:
                st.download_button("⬇️ 下载数据库文件", cfg.db_path.read_bytes(),
                                   f"app_backup_{dt.date.today()}.db", mime="application/octet-stream")
            except Exception as e:
                st.caption(f"数据库文件不可读：{e}")
        else:
            st.info("云端模式：数据持久化在 Supabase。备份请在 Supabase 控制台 "
                    "Database → Backups 或使用 pg_dump 定期导出。")

# ===========================================================================
# 运行状态
# ===========================================================================
with tab_sys:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="ce-title">运行模式</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            - 模式：**{'cloud（Supabase）' if cfg.is_cloud else 'local（SQLite）'}**
            - 数据库：`{'Supabase PostgreSQL' if cfg.is_cloud else cfg.db_path}`
            - 图片存储：`{cfg.bucket + ' (Supabase Storage)' if cfg.is_cloud else cfg.upload_dir}`
            - 允许老师自助注册：{'是' if cfg.allow_teacher_signup else '否'}
            """
        )
        ok, msg = db.ping()
        (st.success if ok else st.error)(f"数据库：{msg}")
    with c2:
        st.markdown('<div class="ce-title">数据量</div>', unsafe_allow_html=True)
        if ok:
            counts = db.data_counts()
            st.markdown(
                ui.metric_row([
                    ("班级", str(counts.get("classes", 0))),
                    ("学生", str(counts.get("students", 0))),
                    ("评价记录", str(counts.get("score_logs", 0))),
                    ("教师", str(counts.get("teachers", 0))),
                ]),
                unsafe_allow_html=True,
            )
        if cfg.is_cloud:
            if st.button("检查 Supabase 存储桶"):
                sok, smsg = check_supabase_connection()
                (st.success if sok else st.error)(smsg)

    st.markdown("---")
    st.markdown('<div class="ce-title">自检提示</div>', unsafe_allow_html=True)
    st.markdown(
        """
        - **云端必须先执行** `sql/schema_supabase.sql`，否则所有表都不存在
        - **图片不显示**：检查 Storage 桶是否设置为 Public（或改用签名 URL）
        - **云端重启丢数据**：说明 APP_MODE 还是 local，SQLite 在容器里不持久
        - **家长看不到记录**：确认学生 `is_active=1` 且查看码正确
        - **投屏口令**：在 Secrets 里设置 `PLAY_CODE`，默认 0000
        """
    )

ui.show_flash()
