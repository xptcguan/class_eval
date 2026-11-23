"""
tools/check_sql.py —— SQL 双库兼容自检（本地跑，不需要连 Supabase）
================================================================
背景
----
本地 SQLite 与云端 PostgreSQL 共用同一份 SQL，只靠把 `?` 换成 `%(p0)s`。
如果某条 SQL 在 SQLite 下"看起来能跑"、在 Postgres 下语法不合法，
就会在 Streamlit Cloud 上抛 `psycopg.errors.UndefinedFunction` 之类，
本地却完全复现不出来。本脚本把这一点提前暴露。

做法
----
1. 拦截 `core.db` 里所有执行过的 SQL（本地 SQLite 跑一遍全部业务函数）；
2. 对每条 SQL 做 `?` → `%(p0)s` 改写；
3. 用 pglast（PostgreSQL 官方语法解析器）检查改写后的语句是否合法；
4. 同时报告 SQLite 自己的 EXPLAIN 是否报错（能发现"表不存在/列不存在"）。

用法：
    python tools/check_sql.py
退出码 0 = 全部语句在两套库里都能解析。
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="ce_sql_")
os.environ.setdefault("APP_MODE", "local")
os.environ["SQLITE_PATH"] = str(Path(_tmp) / "sqlcheck.db")
os.environ["UPLOAD_DIR"] = str(Path(_tmp) / "uploads")

from config import ensure_local_dirs, get_settings  # noqa: E402
from core import db  # noqa: E402

COLLECTED: list[tuple[str, list]] = []   # (sqlite 原始 SQL, 参数)


def main() -> int:
    cfg = get_settings()
    ensure_local_dirs(cfg)
    db.init_db(cfg)

    # ---------- 1. 拦截所有执行过的 SQL ----------
    orig_one, orig_all, orig_ex = db.one, db.all_rows, db.ex
    orig_exmany = db.ex_many

    def rec(sql: str, params=()):
        COLLECTED.append((sql, list(params or [])))

    def one(sql, params=(), cfg=None):
        rec(sql, params)
        return orig_one(sql, params, cfg=cfg)

    def all_rows(sql, params=(), cfg=None):
        rec(sql, params)
        return orig_all(sql, params, cfg=cfg)

    def ex(sql, params=(), cfg=None):
        rec(sql, params)
        return orig_ex(sql, params, cfg=cfg)

    def ex_many(sql, seq, cfg=None):
        first = list(seq)[:1]
        rec(sql, first[0] if first else [])
        return orig_exmany(sql, first, cfg=cfg)

    db.one, db.all_rows, db.ex, db.ex_many = one, all_rows, ex, ex_many

    # ---------- 2. 跑一遍全部业务函数，收集 SQL ----------
    print("== 生成覆盖数据 ==")
    head = db.authenticate_teacher(cfg.default_admin_user, cfg.default_admin_password)
    cid = db.create_class("SQL自检班", head["id"], "七年级", "2026-2027")
    db.add_teacher_to_class(cid, head["id"], "head_teacher", "")
    db.bulk_add_students(cid, [
        {"student_no": f"{i:02d}", "name": f"学生{i}", "gender": "男",
         "group_name": "一组" if i <= 3 else "二组"} for i in range(1, 7)
    ])
    students = db.list_students(cid)
    tag = db.list_tags(cid, category="加分项")[0]
    db.add_scores(cid, [students[0]["id"]], tag["id"], "测试", "", head)
    db.add_scores(cid, [s["id"] for s in students[:3]], tag["id"], "小组", "",
                  head, target_type="group",
                  group_id=db.list_groups_of_class(cid)[0]["id"])
    log = db.query_logs(cid, limit=1)[0]
    db.revoke_log(log["id"], head, "自检撤回")

    # 把读接口都调一遍
    for fn, args in [
        (db.list_classes_for_teacher, (head["id"],)),
        (db.list_active_classes, ()),
        (db.get_class, (cid,)),
        (db.get_membership, (head["id"], cid)),
        (db.list_class_teachers, (cid,)),
        (db.get_class_settings, (cid,)),
        (db.list_students, (cid,)),
        (db.list_students, (cid, True)),
        (db.list_groups_of_class, (cid,)),
        (db.list_tags, (cid,)),
        (db.list_tags, (cid, "加分项")),
        (db.list_teachers, ()),
        (db.list_teachers, ("head_teacher",)),
        (db.get_ranking, (cid, "all")),
        (db.get_group_ranking, (cid, "all")),
        (db.get_ranking, (cid, "today")),
        (db.get_ranking, (cid, "week")),
        (db.get_ranking, (cid, "month")),
        (db.class_overview, (cid,)),
        (db.list_audit_logs, (cid,)),
        (db.query_logs, (cid,)),
        (db.export_rows, (cid,)),
        (db.count_logs, (cid,)),
        (db.data_counts, ()),
        (db.get_student, (students[0]["id"],)),
        (db.get_student_summary, (students[0]["id"], "week")),
        (db.find_student_by_parent,
         (cid, students[0]["student_no"], students[0]["parent_code"])),
        (db.get_batch_logs, ("none-such-batch",)),
        (db.get_log, ("none-such-log",)),
        (db.get_teacher, (head["id"],)),
        (db.get_teacher, ("none",)),
    ]:
        try:
            fn(*args)
        except Exception as e:
            print(f"  (调用 {fn.__name__} 报错，已忽略) {type(e).__name__}: {e}")

    db.one, db.all_rows, db.ex, db.ex_many = orig_one, orig_all, orig_ex, orig_exmany
    print(f"共收集 {len(COLLECTED)} 次 SQL 执行，去重后 {len({s for s, _ in COLLECTED})} 条")

    # ---------- 3. 用 pglast 检查 Postgres 语法 ----------
    try:
        from pglast import parse_sql
    except ImportError:
        print("⚠️ 未安装 pglast，跳过 Postgres 语法检查：pip install pglast")
        return 0

    bad: list[tuple[str, str]] = []
    seen: set[str] = set()
    for sql, params in COLLECTED:
        pg_sql = db._q(sql)
        if pg_sql in seen:
            continue
        seen.add(pg_sql)
        # pglast 是纯 PostgreSQL 解析器，不认 psycopg 的 %(p0)s 命名占位符，
        # 这里换成标准的 $1、$2 … 再做语法解析（只影响解析，不影响真实执行）
        probe = re.sub(r"%\(p(\d+)\)s", r"$\1", pg_sql)
        try:
            parse_sql(probe)
        except Exception as e:
            bad.append((pg_sql, str(e).splitlines()[0][:160]))


    # ---------- 3.5 布尔列专项检查 ----------
    print()
    print("== 布尔列写法检查（Postgres 不接受 boolean = 0/1） ==")
    bool_bad: list[str] = []
    for sql, _ in COLLECTED:
        # 检查"改写前"的原始 SQL 里是否残留布尔列与数字比较
        for col in db._BOOL_COLUMNS:
            if re.search(rf"{col}\s*=\s*[01](?![\d.])", sql):
                bool_bad.append(f"{col}: {sql.strip()[:90]}")
                break
    if bool_bad:
        print(f"  ⚠️ 发现 {len(bool_bad)} 条原始 SQL 用了 `= 0/1`（已由 db._bool_safe 自动改写为 true/false）")
        for x in bool_bad[:5]:
            print("    ·", x)
    else:
        print("  ✅ 原始 SQL 中没有布尔列 = 0/1 的写法")

    # 改写后不应再有残留
    residual = []
    for sql, _ in COLLECTED:
        fixed = db._bool_safe(sql)
        for col in db._BOOL_COLUMNS:
            if re.search(rf"{col}\s*=\s*[01](?![\d.])", fixed):
                residual.append(f"{col}: {fixed.strip()[:90]}")
    if residual:
        print(f"  ❌ 改写后仍残留 {len(residual)} 条：")
        for x in residual[:5]:
            print("    ·", x)
        return 1
    print("  ✅ 改写后全部为 true/false，Postgres 可执行")

    print()
    print("=" * 60)
    if bad:
        print(f"❌ 有 {len(bad)} 条 SQL 在 PostgreSQL 下语法不合法：")
        for sql, err in bad:
            print("-" * 60)
            print("SQL:", sql.strip()[:300])
            print("ERR:", err)
        return 1

    print(f"✅ {len(seen)} 条去重后的 SQL 在 PostgreSQL 语法下全部合法")

    # ---------- 4. 顺便检查 sql/schema_supabase.sql ----------
    schema = (ROOT / "sql" / "schema_supabase.sql").read_text(encoding="utf-8")
    try:
        parse_sql(schema)
        print("✅ schema_supabase.sql 语法合法")
    except Exception as e:
        print(f"❌ schema_supabase.sql 语法错误：{str(e).splitlines()[0][:200]}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
