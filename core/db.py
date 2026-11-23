"""
core/db.py —— 数据访问层（同一套代码同时支持 SQLite 与 Supabase PostgreSQL）
==================================================================
设计要点：
1. 连接层 get_conn() 按 APP_MODE 返回 SQLite 或 Postgres 执行器，
   对上暴露一致的 one() / all_rows() / ex() 接口。
2. SQL 统一用 `?` 占位符，Postgres 侧自动改写为 psycopg 的 `%(p0)s` 命名参数，
   业务 SQL 只需维护一份。
3. 今日/本周/本月的时间边界在 Python 里算好再当参数传入，
   绕开 SQLite datetime() 与 Postgres now() 的时区差异。
4. 云端直连用 Supabase 官方推荐的 psycopg（Session Pooler 连接串），
   只在服务端使用，浏览器端拿不到任何数据库权限。

模块结构：
  A. 连接与初始化      B. 教师账号/登录     C. 班级（含老师-班级关系）
  D. 学生              E. 标签/小组         F. 打分与撤回
  G. 统计与榜单        H. 日志查询/审计
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Sequence

from config import Config, get_settings
from core.security import hash_password, new_id, random_code, verify_password

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "sql" / "schema_sqlite.sql"

# 新建班级时的默认评价标签：(名称, 分值, 分类, 图标)
DEFAULT_TAGS: list[tuple[str, int, str, str]] = [
    ("积极发言", 2, "加分项", "🙋"),
    ("作业优秀", 3, "加分项", "📚"),
    ("助人为乐", 2, "加分项", "🤝"),
    ("课堂专注", 1, "加分项", "👀"),
    ("卫生值日认真", 2, "加分项", "🧹"),
    ("进步明显", 3, "加分项", "📈"),
    ("纪律优秀", 2, "加分项", "🎖"),
    ("作业未交", -3, "扣分项", "📕"),
    ("上课讲话", -2, "扣分项", "🗣"),
    ("迟到", -2, "扣分项", "⏰"),
    ("值日未完成", -2, "扣分项", "🧺"),
    ("违规使用手机", -5, "扣分项", "📱"),
]
DEFAULT_GROUPS = ["第一组", "第二组", "第三组", "第四组", "第五组", "第六组"]


# ===========================================================================
# A. 连接与初始化
# ===========================================================================
# 数据库里所有"布尔语义"列。
# 注意：同一列在不同库里物理类型可能不同 ——
#   schema_sqlite.sql   用 INTEGER（0/1）
#   schema_supabase.sql 用 boolean（true/false）
# 而线上有人可能误用 sqlite 脚本建表，导致 PG 里也是 integer。
# 所以这里不能硬编码 true/false，要按"库里的真实列类型"来决定写什么。
_BOOL_COLUMNS = (
    "is_active",
    "is_archived",
    "show_rank",
    "must_change_pwd",
)

# 运行时探测结果缓存：{"is_active": "bool" | "int"}
_TYPE_CACHE: dict[str, str] = {}


def _detect_bool_columns(cfg: Config | None = None) -> dict[str, str]:
    """
    探测这些列在**当前连接的数据库**里到底是 boolean 还是 integer。

    返回 {"is_active": "bool", ...}；探测失败的列不出现在结果里（按 unknown 处理，
    由 _bool_safe 退化成不改写，避免把原本正确的 SQL 改坏）。
    """
    global _TYPE_CACHE
    cfg = cfg or get_settings()
    if _TYPE_CACHE:
        return _TYPE_CACHE

    result: dict[str, str] = {}
    # 表 → 该表里可能出现的布尔列
    mapping = {
        "teachers": ["is_active", "must_change_pwd"],
        "classes": ["is_archived"],
        "students": ["is_active"],
        "eval_tags": ["is_active"],
        "class_settings": ["show_rank"],
    }
    for table, cols in mapping.items():
        try:
            rows = all_rows(f"PRAGMA table_info({table})", cfg=cfg) if not cfg.is_cloud else \
                all_rows(
                    "SELECT column_name, data_type FROM information_schema.columns"
                    " WHERE table_name = ?", [table], cfg=cfg)
        except Exception:
            continue
        for r in rows:
            col = (r.get("name") or r.get("column_name") or "").lower()
            typ = (r.get("type") or r.get("data_type") or "").lower()
            if col in cols:
                if "bool" in typ:
                    result[col] = "bool"
                elif typ.startswith(("int", "smallint", "bigint", "numeric", "integer")):
                    result[col] = "int"
    _TYPE_CACHE = result
    return result


def _bool_value(value: Any, column: str, cfg: Config | None = None) -> Any:
    """
    写库前把布尔值转成目标列接受的物理类型。
      · 列是 boolean → 返回 True/False
      · 列是 integer → 返回 1/0
    云端库若是照 schema_sqlite 建的（integer），这一步能避免
    `column "is_archived" is of type integer but expression is of type boolean`。
    """
    kinds = _detect_bool_columns(cfg)
    kind = kinds.get(column)
    flag = bool(value)
    if kind == "bool":
        return flag
    if kind == "int":
        return 1 if flag else 0
    return flag


def reset_type_cache() -> None:
    """切换数据库（如本地↔云端）后清掉探测缓存"""
    global _TYPE_CACHE
    _TYPE_CACHE = {}


def _bool_safe(sql: str, cfg: Config | None = None) -> str:
    """
    按**数据库里的真实列类型**改写布尔常量：

      · 列是 boolean  → `= 1/0` 改写为 `= true/false`
      · 列是 integer  → `= true/false` 改写为 `= 1/0`

    这样无论线上库是照 schema_supabase（boolean）建的，
    还是误照 schema_sqlite（integer）建的，同一份 SQL 都能跑。
    探测不到的列保持不变，宁可报错也不乱改。
    """
    kinds = _detect_bool_columns(cfg)
    for col, kind in kinds.items():
        if kind == "bool":
            sql = re.sub(rf"({col})\s*=\s*1(?![\d.])", r"\1 = true", sql)
            sql = re.sub(rf"({col})\s*=\s*0(?![\d.])", r"\1 = false", sql)
        elif kind == "int":
            sql = re.sub(rf"({col})\s*=\s*true\b", r"\1 = 1", sql, flags=re.I)
            sql = re.sub(rf"({col})\s*=\s*false\b", r"\1 = 0", sql, flags=re.I)
    return sql


def _q(sql: str, cfg: Config | None = None) -> str:
    """把 `?` 占位符改写成 psycopg 的 `%(p0)s`，并按列类型做布尔常量兼容"""
    idx = 0

    def repl(_m):
        nonlocal idx
        token = f"%(p{idx})s"
        idx += 1
        return token

    return re.sub(r"\?", repl, _bool_safe(sql, cfg))


def _params(params: Sequence[Any]) -> dict[str, Any]:
    """参数转 psycopg 命名参数（布尔列请由调用方传 Python bool）"""
    return {f"p{i}": v for i, v in enumerate(params)}


def _normalize_row(row: Any) -> dict[str, Any]:
    """统一类型：UUID→str；带时区 datetime→本地 naive datetime"""
    if row is None:
        return {}
    items = row.items() if isinstance(row, dict) else dict(row).items()
    out: dict[str, Any] = {}
    for k, v in items:
        if isinstance(v, dt.datetime):
            out[k] = v.astimezone().replace(tzinfo=None) if v.tzinfo else v
        elif isinstance(v, dt.date):
            out[k] = dt.datetime(v.year, v.month, v.day)
        elif type(v).__name__ == "UUID":
            out[k] = str(v)
        else:
            out[k] = v
    return out


class _PgExec:
    """把 psycopg Cursor 包装成 sqlite3.Connection 的常用子集"""

    def __init__(self, cur, conn, cfg=None):
        self.cur = cur
        self.conn = conn
        self.cfg = cfg

    def execute(self, sql: str, params: Sequence[Any] = ()):
        # 占位符改写 + 按列真实类型做布尔常量兼容
        self.cur.execute(_q(sql, self.cfg), _params(list(params)))
        return self

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]):
        for p in seq:
            self.execute(sql, p)

    def fetchone(self):
        row = self.cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self.cur.description]
        return dict(zip(cols, row))

    def fetchall(self):
        cols = [d[0] for d in self.cur.description]
        return [dict(zip(cols, r)) for r in self.cur.fetchall()]

    def executescript(self, script: str):
        self.cur.execute(script)


@contextmanager
def get_conn(cfg: Config | None = None):
    """获取执行器；正常退出提交事务，异常回滚"""
    cfg = cfg or get_settings()
    if cfg.is_cloud:
        dsn = (os.getenv("DATABASE_URL") or str(cfg.extra.get("DATABASE_URL", "") or "")).strip()
        if not dsn:
            raise RuntimeError(
                "云端模式缺少 DATABASE_URL：请到 Supabase → Connect → Session pooler "
                "复制连接串，填入 Streamlit Secrets 的 DATABASE_URL。"
            )
        import psycopg  # 延迟导入，本地模式无需安装

        try:
            conn = psycopg.connect(dsn, autocommit=False, connect_timeout=15)
        except Exception as e:
            raise RuntimeError(
                "连接 Supabase 数据库失败。请检查：\n"
                "1) DATABASE_URL 是否用的是 Connect → Session pooler 的连接串"
                "（Direct connection 只有 IPv6，云端连不上）；\n"
                "2) 数据库密码是否含 @ : / ? # 等字符未做 URL 编码；\n"
                "3) 项目是否被暂停（免费版长期无访问会 pause）。\n"
                f"原始错误：{type(e).__name__}: {e}"
            ) from e
        try:
            cur = conn.cursor()
            yield _PgExec(cur, conn, cfg)
            conn.commit()
        except psycopg.errors.UndefinedFunction as e:
            conn.rollback()
            # 布尔列写成 = 0/1 已由 _bool_safe 改写；走到这里通常是
            # 表/函数真的不存在（没执行 schema_supabase.sql）或用了未知函数。
            raise RuntimeError(
                "数据库缺少表或函数。请到 Supabase → SQL Editor 全文执行 "
                "sql/schema_supabase.sql（可重复执行）。\n"
                f"原始错误：{e}"
            ) from e
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(cfg.db_path), check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield _SafeConn(conn, cfg)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class _SafeConn:
    """
    给 sqlite3.Connection 加一层包装：执行前把布尔列的 `= 1/0` 改写成 true/false。
    这样同一份 SQL 在 SQLite 与 Postgres 上语义完全一致（SQLite 3.23+ 支持
    true/false 字面量），本地跑通就等于云端能跑通。
    其余属性和方法（row_factory、execute 之外的调用）原样透传。
    """

    def __init__(self, conn, cfg=None):
        self._conn = conn
        self.cfg = cfg

    def execute(self, sql: str, params: Sequence[Any] = ()):
        return self._conn.execute(_bool_safe(sql, self.cfg), params)

    def executemany(self, sql: str, seq):
        return self._conn.executemany(_bool_safe(sql, self.cfg), seq)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def one(sql: str, params: Sequence[Any] = (), cfg: Config | None = None) -> dict[str, Any]:
    """查单行，返回 dict（无结果为空 dict）"""
    with get_conn(cfg) as cur:
        return _normalize_row(cur.execute(sql, list(params)).fetchone())


def all_rows(sql: str, params: Sequence[Any] = (), cfg: Config | None = None) -> list[dict[str, Any]]:
    """查多行"""
    with get_conn(cfg) as cur:
        return [_normalize_row(r) for r in (cur.execute(sql, list(params)).fetchall() or [])]


def ex(sql: str, params: Sequence[Any] = (), cfg: Config | None = None) -> None:
    """执行写操作"""
    with get_conn(cfg) as cur:
        cur.execute(sql, list(params))


def ex_many(sql: str, seq: Iterable[Sequence[Any]], cfg: Config | None = None) -> None:
    """批量写（同一事务）"""
    with get_conn(cfg) as cur:
        cur.executemany(sql, [list(p) for p in seq])


def init_db(cfg: Config | None = None) -> str:
    """
    初始化数据库：
      local → 自动执行 sql/schema_sqlite.sql
      cloud → 表结构需在 Supabase SQL Editor 执行一次 sql/schema_supabase.sql
    两种情况都会确保至少存在一个班主任账号。
    """
    cfg = cfg or get_settings()
    if not cfg.is_cloud:
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(cfg.db_path))
        try:
            conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()
        msg = f"SQLite 已就绪：{cfg.db_path.name}"
    else:
        msg = "云端模式：请确认已执行 sql/schema_supabase.sql"

    # 轻量迁移：老库补齐新增字段（幂等，失败不阻断启动）
    _migrate(cfg)

    try:
        _ensure_admin(cfg)
    except Exception:
        pass  # 云端首启表可能还没建，启动页会提示
    return msg


# 增量字段：(表, 字段, 类型定义)
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("eval_tags", "icon_img", "TEXT DEFAULT ''"),
    ("students", "avatar_url", "TEXT DEFAULT ''"),
    ("groups", "sort_order", "INTEGER NOT NULL DEFAULT 0"),
]


def _migrate(cfg: Config) -> None:
    """给已有数据库补字段：SQLite 用 ALTER TABLE，Postgres 用 ADD COLUMN IF NOT EXISTS"""
    for table, column, ddl in _MIGRATIONS:
        try:
            if cfg.is_cloud:
                ex(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}", cfg=cfg)
            else:
                cols = [r["name"] for r in all_rows(f"PRAGMA table_info({table})", cfg=cfg)]
                if cols and column not in cols:
                    ex(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}", cfg=cfg)
        except Exception:
            continue


def _ensure_admin(cfg: Config) -> None:
    """没有班主任账号时自动创建默认管理员（首次登录强制改密码）"""
    if one("SELECT id FROM teachers WHERE role = 'head_teacher' LIMIT 1", cfg=cfg):
        return
    ex(
        "INSERT INTO teachers (id, username, password_hash, display_name, role, is_active, must_change_pwd)"
        " VALUES (?, ?, ?, ?, 'head_teacher', 1, 1)",
        [new_id(), cfg.default_admin_user, hash_password(cfg.default_admin_password), "系统管理员"],
        cfg=cfg,
    )


def ping(cfg: Config | None = None) -> tuple[bool, str]:
    """连通性自检，供启动页显示状态"""
    try:
        with get_conn(cfg) as cur:
            cur.execute("SELECT 1").fetchone()
        return True, "数据库连接正常"
    except Exception as e:
        return False, str(e)[:300]


# ===========================================================================
# B. 教师账号 / 登录
# ===========================================================================
def authenticate_teacher(username: str, password: str,
                         cfg: Config | None = None) -> dict[str, Any] | None:
    row = one(
        "SELECT * FROM teachers WHERE lower(username) = lower(?) AND is_active = 1",
        [(username or "").strip()], cfg=cfg,
    )
    if not row or not verify_password(password or "", row["password_hash"]):
        return None
    row.pop("password_hash", None)
    return row


def get_teacher(teacher_id: str, cfg: Config | None = None) -> dict[str, Any] | None:
    row = one("SELECT * FROM teachers WHERE id = ?", [teacher_id], cfg=cfg)
    if row:
        row.pop("password_hash", None)
        return row
    return None


def create_teacher(username: str, password: str, display_name: str,
                   role: str = "subject_teacher", must_change_pwd: bool = False,
                   cfg: Config | None = None) -> tuple[bool, str]:
    cfg = cfg or get_settings()
    username = (username or "").strip()
    if not username or not password:
        return False, "账号和密码不能为空"
    if len(password) < 6:
        return False, "密码至少 6 位"
    if role not in ("head_teacher", "subject_teacher"):
        return False, "角色不合法"
    if one("SELECT id FROM teachers WHERE lower(username) = lower(?)", [username], cfg=cfg):
        return False, f"账号 {username} 已存在"
    ex(
        "INSERT INTO teachers (id, username, password_hash, display_name, role, is_active, must_change_pwd)"
        " VALUES (?, ?, ?, ?, ?, 1, ?)",
        [new_id(), username, hash_password(password), (display_name or username).strip(),
         role, int(must_change_pwd)], cfg=cfg,
    )
    return True, f"账号 {username} 创建成功"


def list_teachers(role: str | None = None, cfg: Config | None = None) -> list[dict[str, Any]]:
    if role:
        return all_rows(
            "SELECT id, username, display_name, role, is_active FROM teachers"
            " WHERE role = ? ORDER BY created_at", [role], cfg=cfg,
        )
    return all_rows(
        "SELECT id, username, display_name, role, is_active FROM teachers ORDER BY created_at", cfg=cfg
    )


def update_teacher(teacher_id: str, cfg: Config | None = None, **fields) -> None:
    data = {k: v for k, v in fields.items()
            if k in {"display_name", "is_active", "password_hash", "must_change_pwd", "role"}}
    if not data:
        return
    sets = ", ".join(f"{k} = ?" for k in data)
    ex(f"UPDATE teachers SET {sets} WHERE id = ?", list(data.values()) + [teacher_id], cfg=cfg)


def change_password(teacher_id: str, old_pwd: str, new_pwd: str,
                    cfg: Config | None = None) -> tuple[bool, str]:
    row = one("SELECT password_hash FROM teachers WHERE id = ?", [teacher_id], cfg=cfg)
    if not row:
        return False, "账号不存在"
    if not verify_password(old_pwd, row["password_hash"]):
        return False, "原密码错误"
    if len(new_pwd) < 6:
        return False, "新密码至少 6 位"
    ex("UPDATE teachers SET password_hash = ?, must_change_pwd = 0 WHERE id = ?",
       [hash_password(new_pwd), teacher_id], cfg=cfg)
    return True, "密码修改成功"


def reset_teacher_password(teacher_id: str, new_pwd: str, cfg: Config | None = None) -> None:
    ex("UPDATE teachers SET password_hash = ?, must_change_pwd = 1 WHERE id = ?",
       [hash_password(new_pwd), teacher_id], cfg=cfg)


# ===========================================================================
# C. 班级
# ===========================================================================
def create_class(name: str, head_teacher_id: str, grade: str = "", school_year: str = "",
                 with_defaults: bool = True, cfg: Config | None = None) -> str:
    """新建班级：创建者自动成为班主任，可选写入默认标签与小组"""
    cfg = cfg or get_settings()
    cid = new_id()
    ex("INSERT INTO classes (id, name, grade, school_year, head_teacher_id, created_by)"
       " VALUES (?, ?, ?, ?, ?, ?)",
       [cid, name.strip(), grade.strip(), school_year.strip(), head_teacher_id, head_teacher_id], cfg=cfg)
    ex("INSERT INTO teacher_classes (id, teacher_id, class_id, teacher_role)"
       " VALUES (?, ?, ?, 'head_teacher')", [new_id(), head_teacher_id, cid], cfg=cfg)
    ex("INSERT INTO class_settings (class_id, show_rank) VALUES (?, ?)",
       [cid, int(cfg.show_rank_default)], cfg=cfg)
    if with_defaults:
        ex_many("INSERT INTO eval_tags (id, class_id, name, score, category, icon, sort_order)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(new_id(), cid, n, s, c, ic, i) for i, (n, s, c, ic) in enumerate(DEFAULT_TAGS)], cfg=cfg)
        ex_many("INSERT INTO groups (id, class_id, name, sort_order) VALUES (?, ?, ?, ?)",
                [(new_id(), cid, g, i) for i, g in enumerate(DEFAULT_GROUPS)], cfg=cfg)
    return cid


def list_classes_for_teacher(teacher_id: str, cfg: Config | None = None) -> list[dict[str, Any]]:
    """某老师关联的全部班级（带他在该班的角色、学生人数）"""
    rows = all_rows(
        """
        SELECT c.id, c.name, c.grade, c.school_year, c.head_teacher_id,
               c.is_archived, c.created_at,
               tc.teacher_role AS my_role, tc.subject AS my_subject
        FROM classes c
        JOIN teacher_classes tc ON tc.class_id = c.id
        WHERE tc.teacher_id = ?
        ORDER BY c.is_archived, c.created_at DESC
        """,
        [teacher_id], cfg=cfg,
    )
    for r in rows:
        n = one("SELECT COUNT(*) AS n FROM students WHERE class_id = ? AND is_active = 1",
                [r["id"]], cfg=cfg)
        r["student_count"] = int(n.get("n") or 0)
    return rows


def get_class(class_id: str, cfg: Config | None = None) -> dict[str, Any] | None:
    return one("SELECT * FROM classes WHERE id = ?", [class_id], cfg=cfg) or None


def get_membership(teacher_id: str, class_id: str, cfg: Config | None = None) -> dict[str, Any] | None:
    """老师在某班的成员关系——权限判断的唯一依据"""
    return one("SELECT * FROM teacher_classes WHERE teacher_id = ? AND class_id = ?",
               [teacher_id, class_id], cfg=cfg) or None


def is_head_teacher(teacher_id: str, class_id: str, cfg: Config | None = None) -> bool:
    m = get_membership(teacher_id, class_id, cfg)
    return bool(m and m["teacher_role"] == "head_teacher")


def update_class(class_id: str, name: str, grade: str, school_year: str,
                 cfg: Config | None = None) -> None:
    ex("UPDATE classes SET name = ?, grade = ?, school_year = ? WHERE id = ?",
       [name.strip(), grade.strip(), school_year.strip(), class_id], cfg=cfg)


def archive_class(class_id: str, archived: bool = True, cfg: Config | None = None) -> None:
    """归档班级：不物理删除，历史全部保留"""
    ex("UPDATE classes SET is_archived = ? WHERE id = ?",
       [_bool_value(archived, "is_archived", cfg), class_id], cfg=cfg)


def add_teacher_to_class(class_id: str, teacher_id: str, role: str = "subject_teacher",
                         subject: str = "", cfg: Config | None = None) -> tuple[bool, str]:
    """添加科任老师 / 移交班主任身份"""
    if role not in ("head_teacher", "subject_teacher"):
        return False, "角色不合法"
    exists = one("SELECT id FROM teacher_classes WHERE teacher_id = ? AND class_id = ?",
                 [teacher_id, class_id], cfg=cfg)
    if exists:
        ex("UPDATE teacher_classes SET teacher_role = ?, subject = ? WHERE id = ?",
           [role, subject, exists["id"]], cfg=cfg)
    else:
        ex("INSERT INTO teacher_classes (id, teacher_id, class_id, teacher_role, subject)"
           " VALUES (?, ?, ?, ?, ?)", [new_id(), teacher_id, class_id, role, subject], cfg=cfg)
    if role == "head_teacher":
        ex("UPDATE classes SET head_teacher_id = ? WHERE id = ?", [teacher_id, class_id], cfg=cfg)
    return True, "已添加老师"


def remove_teacher_from_class(class_id: str, teacher_id: str,
                              cfg: Config | None = None) -> tuple[bool, str]:
    cls = get_class(class_id, cfg=cfg)
    if cls and cls.get("head_teacher_id") == teacher_id:
        return False, "班主任不能被移除，请先移交班主任身份"
    ex("DELETE FROM teacher_classes WHERE class_id = ? AND teacher_id = ?",
       [class_id, teacher_id], cfg=cfg)
    return True, "已移除该老师"


def list_class_teachers(class_id: str, cfg: Config | None = None) -> list[dict[str, Any]]:
    return all_rows(
        """
        SELECT t.id, t.username, t.display_name, t.role, t.is_active,
               tc.teacher_role, tc.subject, tc.joined_at
        FROM teacher_classes tc JOIN teachers t ON t.id = tc.teacher_id
        WHERE tc.class_id = ?
        ORDER BY CASE tc.teacher_role WHEN 'head_teacher' THEN 0 ELSE 1 END, tc.joined_at
        """,
        [class_id], cfg=cfg,
    )


def get_class_settings(class_id: str, cfg: Config | None = None) -> dict[str, Any]:
    row = one("SELECT * FROM class_settings WHERE class_id = ?", [class_id], cfg=cfg)
    if not row:
        ex("INSERT INTO class_settings (class_id, show_rank) VALUES (?, 1)", [class_id], cfg=cfg)
        row = {"class_id": class_id, "show_rank": 1}
    return row


def set_show_rank(class_id: str, show: bool, cfg: Config | None = None) -> None:
    ex("UPDATE class_settings SET show_rank = ? WHERE class_id = ?",
       [_bool_value(show, "show_rank", cfg), class_id], cfg=cfg)


def list_active_classes(cfg: Config | None = None) -> list[dict[str, Any]]:
    """家长登录页可选的班级列表"""
    return all_rows("SELECT id, name FROM classes WHERE is_archived = 0"
                    " ORDER BY created_at DESC", cfg=cfg)


# ===========================================================================
# D. 学生
# ===========================================================================
def _unique_parent_code(class_id: str, cfg: Config) -> str:
    """生成班内唯一的家长查看码"""
    for _ in range(50):
        code = random_code(4)
        if not one("SELECT id FROM students WHERE class_id = ? AND parent_code = ?",
                   [class_id, code], cfg=cfg):
            return code
    return random_code(6)


def add_student(class_id: str, student_no: str, name: str, gender: str = "",
                group_name: str = "", avatar_key: str = "", remark: str = "",
                cfg: Config | None = None) -> tuple[bool, str]:
    cfg = cfg or get_settings()
    student_no, name = student_no.strip(), name.strip()
    if not student_no or not name:
        return False, "学号和姓名不能为空"
    if one("SELECT id FROM students WHERE class_id = ? AND student_no = ?", [class_id, student_no], cfg=cfg):
        return False, f"学号 {student_no} 已存在"
    ex("INSERT INTO students (id, class_id, student_no, name, gender, group_name,"
       " avatar_key, parent_code, remark) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
       [new_id(), class_id, student_no, name, gender, group_name, avatar_key or "a01",
        _unique_parent_code(class_id, cfg), remark], cfg=cfg)
    return True, f"已添加 {name}"


def bulk_add_students(class_id: str, rows: list[dict[str, str]],
                      cfg: Config | None = None) -> tuple[int, list[str]]:
    """批量导入，返回 (成功数, 错误列表)"""
    ok, errs = 0, []
    for i, r in enumerate(rows, start=1):
        no = str(r.get("student_no", "")).strip()
        nm = str(r.get("name", "")).strip()
        if not no or not nm:
            errs.append(f"第 {i} 行：学号或姓名为空，已跳过")
            continue
        success, msg = add_student(
            class_id, no, nm,
            gender=str(r.get("gender", "")).strip(),
            group_name=str(r.get("group_name", "")).strip(),
            avatar_key=str(r.get("avatar_key", "")).strip() or f"a{(i % 16) + 1:02d}",
            cfg=cfg,
        )
        ok += 1 if success else 0
        if not success:
            errs.append(f"第 {i} 行：{msg}")
    return ok, errs


def list_students(class_id: str, include_inactive: bool = False,
                  group_name: str | None = None, cfg: Config | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM students WHERE class_id = ?"
    params: list[Any] = [class_id]
    if not include_inactive:
        sql += " AND is_active = 1"
    if group_name:
        sql += " AND group_name = ?"
        params.append(group_name)
    sql += " ORDER BY student_no"
    return all_rows(sql, params, cfg=cfg)


def get_student(student_id: str, cfg: Config | None = None) -> dict[str, Any] | None:
    return one("SELECT * FROM students WHERE id = ?", [student_id], cfg=cfg) or None


def update_student(student_id: str, cfg: Config | None = None, **fields) -> None:
    data = {k: v for k, v in fields.items()
            if k in {"student_no", "name", "gender", "group_name", "avatar_key",
                     "avatar_url", "remark", "is_active"}}
    if not data:
        return
    sets = ", ".join(f"{k} = ?" for k in data)
    ex(f"UPDATE students SET {sets} WHERE id = ?", list(data.values()) + [student_id], cfg=cfg)


def set_student_avatar(student_id: str, avatar_key: str = "", avatar_url: str = "",
                       cfg: Config | None = None) -> None:
    ex("UPDATE students SET avatar_key = ?, avatar_url = ? WHERE id = ?",
       [avatar_key, avatar_url, student_id], cfg=cfg)


def code_in_use(class_id: str, code: str, cfg: Config | None = None) -> bool:
    """查看码是否已被班内其他学生占用"""
    return bool(one("SELECT id FROM students WHERE class_id = ? AND parent_code = ?",
                    [class_id, (code or "").strip()], cfg=cfg))


def set_parent_code(student_id: str, code: str, cfg: Config | None = None) -> None:
    """家长自助修改查看码（仅作用于自己的记录）"""
    ex("UPDATE students SET parent_code = ? WHERE id = ?", [(code or "").strip(), student_id], cfg=cfg)


def reset_parent_code(student_id: str, cfg: Config | None = None) -> str:
    """重置家长查看码（家长码外泄时使用）"""
    cfg = cfg or get_settings()
    st = get_student(student_id, cfg=cfg)
    if not st:
        return ""
    code = _unique_parent_code(st["class_id"], cfg)
    ex("UPDATE students SET parent_code = ? WHERE id = ?", [code, student_id], cfg=cfg)
    return code


def remove_student(student_id: str, cfg: Config | None = None) -> None:
    """学生移出班级：软删除，积分与日志保留"""
    ex("UPDATE students SET is_active = 0 WHERE id = ?", [student_id], cfg=cfg)


def find_student_by_parent(class_id: str, student_no: str, parent_code: str,
                           cfg: Config | None = None) -> dict[str, Any] | None:
    """家长登录：班级 + 学号 + 家长码 三者匹配才放行"""
    return one(
        "SELECT * FROM students WHERE class_id = ? AND student_no = ? AND parent_code = ? AND is_active = 1",
        [class_id, (student_no or "").strip(), (parent_code or "").strip()], cfg=cfg,
    ) or None


def list_groups_of_class(class_id: str, cfg: Config | None = None) -> list[dict[str, Any]]:
    return all_rows("SELECT * FROM groups WHERE class_id = ? ORDER BY sort_order, name",
                    [class_id], cfg=cfg)


# ===========================================================================
# E. 标签 / 小组
# ===========================================================================
def list_tags(class_id: str, category: str | None = None, include_inactive: bool = False,
              cfg: Config | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM eval_tags WHERE class_id = ?"
    params: list[Any] = [class_id]
    if category:
        sql += " AND category = ?"
        params.append(category)
    if not include_inactive:
        sql += " AND is_active = 1"
    sql += " ORDER BY score DESC, sort_order, name"
    return all_rows(sql, params, cfg=cfg)


def save_tag(class_id: str, name: str, score: int, tag_id: str | None = None,
             icon: str = "⭐", icon_img: str | None = None,
             cfg: Config | None = None) -> tuple[bool, str]:
    """
    新增/编辑标签：分值正负自动决定属于加分项还是扣分项。
    icon_img 为自定义图标图片引用（本地相对路径 / Supabase URL）；
      传 None 表示不修改现有图片，传 "" 表示清空图片改用 emoji。
    """
    cfg = cfg or get_settings()
    name = (name or "").strip()
    if not name:
        return False, "标签名称不能为空"
    if int(score) == 0:
        return False, "分值不能为 0"
    category = "加分项" if int(score) > 0 else "扣分项"
    if tag_id:
        if icon_img is None:
            ex("UPDATE eval_tags SET name = ?, score = ?, category = ?, icon = ?, is_active = 1"
               " WHERE id = ?", [name, int(score), category, icon, tag_id], cfg=cfg)
        else:
            ex("UPDATE eval_tags SET name = ?, score = ?, category = ?, icon = ?, icon_img = ?,"
               " is_active = 1 WHERE id = ?",
               [name, int(score), category, icon, icon_img, tag_id], cfg=cfg)
        return True, f"标签「{name}」已更新"
    mx = one("SELECT COALESCE(MAX(sort_order), 0) AS m FROM eval_tags WHERE class_id = ?",
             [class_id], cfg=cfg)
    ex("INSERT INTO eval_tags (id, class_id, name, score, category, icon, icon_img, sort_order)"
       " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
       [new_id(), class_id, name, int(score), category, icon, icon_img or "",
        int(mx.get("m") or 0) + 1], cfg=cfg)
    return True, f"标签「{name}」已创建"


def delete_tag(tag_id: str, cfg: Config | None = None) -> None:
    """停用标签（不物理删除；历史日志存了 tag_name 快照）"""
    ex("UPDATE eval_tags SET is_active = 0 WHERE id = ?", [tag_id], cfg=cfg)


def save_group(class_id: str, name: str, group_id: str | None = None,
               cfg: Config | None = None) -> tuple[bool, str]:
    cfg = cfg or get_settings()
    name = (name or "").strip()
    if not name:
        return False, "小组名称不能为空"
    if group_id:
        if one("SELECT id FROM groups WHERE class_id = ? AND name = ? AND id <> ?",
               [class_id, name, group_id], cfg=cfg):
            return False, "小组名称重复"
        ex("UPDATE groups SET name = ? WHERE id = ?", [name, group_id], cfg=cfg)
        return True, "小组已更新"
    if one("SELECT id FROM groups WHERE class_id = ? AND name = ?", [class_id, name], cfg=cfg):
        return False, "小组名称重复"
    mx = one("SELECT COALESCE(MAX(sort_order), 0) AS m FROM groups WHERE class_id = ?",
             [class_id], cfg=cfg)
    ex("INSERT INTO groups (id, class_id, name, sort_order) VALUES (?, ?, ?, ?)",
       [new_id(), class_id, name, int(mx.get("m") or 0) + 1], cfg=cfg)
    return True, "小组已创建"


def delete_group(group_id: str, cfg: Config | None = None) -> None:
    """删除小组，并清空组内学生的小组名"""
    g = one("SELECT * FROM groups WHERE id = ?", [group_id], cfg=cfg)
    if g:
        ex("UPDATE students SET group_name = '' WHERE class_id = ? AND group_name = ?",
           [g["class_id"], g["name"]], cfg=cfg)
    ex("DELETE FROM groups WHERE id = ?", [group_id], cfg=cfg)


# ===========================================================================
# F. 打分与撤回
# ===========================================================================
def add_scores(class_id: str, student_ids: list[str], tag_id: str, remark: str,
               image_url: str, teacher: dict[str, Any], target_type: str = "student",
               group_id: str | None = None, now: dt.datetime | None = None,
               cfg: Config | None = None) -> tuple[bool, str, str]:
    """
    一次打分可覆盖多名学生（单人=1 条，小组=全组 N 条）。
    同一批共享 batch_id，便于整批撤回。
    返回 (成功?, 提示语, batch_id)
    """
    cfg = cfg or get_settings()
    if not student_ids:
        return False, "没有打分对象", ""
    tag = one("SELECT * FROM eval_tags WHERE id = ?", [tag_id], cfg=cfg)
    if not tag:
        return False, "标签不存在或已停用", ""
    batch_id = new_id()
    ts = (now or dt.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    score = int(tag["score"])

    with get_conn(cfg) as cur:
        for sid in student_ids:
            cur.execute(
                "INSERT INTO score_logs (id, class_id, target_type, student_id, group_id, batch_id,"
                " tag_id, tag_name, score, remark, image_url, recorded_by, recorded_by_name,"
                " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal', ?)",
                [new_id(), class_id, target_type, sid, group_id, batch_id, tag_id, tag["name"],
                 score, remark or "", image_url or "", teacher["id"],
                 teacher.get("display_name", ""), ts],
            )
            cur.execute("UPDATE students SET total_score = total_score + ? WHERE id = ?", [score, sid])

    word = "加分" if score > 0 else "扣分"
    return True, f"{word}成功：{tag['name']} {score:+d} 分 × {len(student_ids)} 人", batch_id


def get_log(log_id: str, cfg: Config | None = None) -> dict[str, Any] | None:
    return one("SELECT * FROM score_logs WHERE id = ?", [log_id], cfg=cfg) or None


def revoke_log(log_id: str, teacher: dict[str, Any], reason: str = "",
               cfg: Config | None = None) -> tuple[bool, str]:
    """撤回单条：软删除 + 回滚总分 + 写审计日志"""
    cfg = cfg or get_settings()
    log = get_log(log_id, cfg=cfg)
    if not log:
        return False, "记录不存在"
    if log["status"] == "revoked":
        return False, "该记录已被撤回"
    if not is_head_teacher(teacher["id"], log["class_id"], cfg):
        return False, "只有班主任可以撤回打分"

    st = get_student(log["student_id"], cfg=cfg) if log.get("student_id") else None
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn(cfg) as cur:
        cur.execute(
            "UPDATE score_logs SET status = 'revoked', revoked_by = ?, revoked_by_name = ?,"
            " revoked_at = ?, revoke_reason = ? WHERE id = ? AND status = 'normal'",
            [teacher["id"], teacher.get("display_name", ""), now, reason or "", log_id],
        )
        if log.get("student_id"):
            cur.execute("UPDATE students SET total_score = total_score - ? WHERE id = ?",
                        [int(log["score"]), log["student_id"]])
    write_audit(log["class_id"], teacher, "revoke_score",
                f"撤回 {(st or {}).get('name', '')} 的「{log['tag_name']}」"
                f"{int(log['score']):+d} 分；原因：{reason or '未填写'}", cfg=cfg)
    return True, "已撤回，操作已记入审计日志"


def revoke_batch(batch_id: str, teacher: dict[str, Any], reason: str = "",
                 cfg: Config | None = None) -> tuple[bool, str]:
    """整批撤回（撤销一次小组批量打分）"""
    cfg = cfg or get_settings()
    logs = all_rows("SELECT * FROM score_logs WHERE batch_id = ? AND status = 'normal'",
                    [batch_id], cfg=cfg)
    if not logs:
        return False, "没有可撤回的记录"
    if not is_head_teacher(teacher["id"], logs[0]["class_id"], cfg):
        return False, "只有班主任可以撤回打分"

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn(cfg) as cur:
        for lg in logs:
            cur.execute(
                "UPDATE score_logs SET status = 'revoked', revoked_by = ?, revoked_by_name = ?,"
                " revoked_at = ?, revoke_reason = ? WHERE id = ?",
                [teacher["id"], teacher.get("display_name", ""), now, reason or "", lg["id"]],
            )
            if lg.get("student_id"):
                cur.execute("UPDATE students SET total_score = total_score - ? WHERE id = ?",
                            [int(lg["score"]), lg["student_id"]])
    write_audit(logs[0]["class_id"], teacher, "revoke_batch",
                f"整批撤回 {len(logs)} 条「{logs[0]['tag_name']}」记录；原因：{reason or '未填写'}",
                cfg=cfg)
    return True, f"已整批撤回 {len(logs)} 条记录"


# ===========================================================================
# G. 统计与榜单
# ===========================================================================
def period_range(period: str, now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    """
    返回统计区间的 [起, 止)。周以周一为第一天。
      today / week / month / all
    """
    now = now or dt.datetime.now()
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return start_of_today, start_of_today + dt.timedelta(days=1)
    if period == "week":
        start = start_of_today - dt.timedelta(days=now.weekday())
        return start, start + dt.timedelta(days=7)
    if period == "month":
        start = start_of_today.replace(day=1)
        next_month = (start + dt.timedelta(days=32)).replace(day=1)
        return start, next_month
    # all
    return dt.datetime(1970, 1, 1), dt.datetime(2999, 1, 1)


def get_ranking(class_id: str, period: str = "all", group_name: str | None = None,
                include_inactive: bool = False, cfg: Config | None = None) -> list[dict[str, Any]]:
    """
    积分榜单：按指定周期汇总（只统计 status='normal' 的记录）。
    返回按分数降序排列的学生列表，含 period_score / total_score。
    同分并列在页面层处理（rank 用 competition 排名方式）。
    """
    cfg = cfg or get_settings()
    start, end = period_range(period)

    sql = """
        SELECT s.id, s.name, s.student_no, s.group_name, s.gender, s.avatar_key, s.avatar_url,
               s.total_score,
               COALESCE(SUM(CASE WHEN l.status = 'normal' THEN l.score ELSE 0 END), 0) AS period_score,
               COALESCE(SUM(CASE WHEN l.status = 'normal' AND l.score > 0 THEN l.score ELSE 0 END), 0) AS plus_sum,
               COALESCE(SUM(CASE WHEN l.status = 'normal' AND l.score < 0 THEN l.score ELSE 0 END), 0) AS minus_sum,
               COALESCE(SUM(CASE WHEN l.status = 'normal' THEN 1 ELSE 0 END), 0) AS log_count
        FROM students s
        LEFT JOIN score_logs l
               ON l.student_id = s.id
              AND l.created_at >= ? AND l.created_at < ?
        WHERE s.class_id = ?
    """
    params: list[Any] = [start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), class_id]
    if not include_inactive:
        sql += " AND s.is_active = 1"
    if group_name:
        sql += " AND s.group_name = ?"
        params.append(group_name)
    sql += " GROUP BY s.id, s.name, s.student_no, s.group_name, s.gender, s.avatar_key, s.avatar_url, s.total_score"
    sql += " ORDER BY period_score DESC, s.student_no"

    rows = all_rows(sql, params, cfg=cfg)
    for r in rows:
        r["period_score"] = int(r.get("period_score") or 0)
        r["plus_sum"] = int(r.get("plus_sum") or 0)
        r["minus_sum"] = int(r.get("minus_sum") or 0)
        r["log_count"] = int(r.get("log_count") or 0)
    return rows


def apply_competition_rank(rows: list[dict[str, Any]], score_key: str = "period_score") -> list[dict[str, Any]]:
    """
    给榜单算名次：同分并列（1,2,2,4 式竞争排名）。
    直接在传入的 list 上写 rank 字段并返回。
    """
    prev_score, prev_rank = None, 0
    for i, r in enumerate(rows, start=1):
        s = int(r.get(score_key) or 0)
        if prev_score is not None and s == prev_score:
            r["rank"] = prev_rank
        else:
            r["rank"] = i
            prev_rank = i
        prev_score = s
    return rows


def get_group_ranking(class_id: str, period: str = "all",
                      cfg: Config | None = None) -> list[dict[str, Any]]:
    """
    小组积分汇总（小组均分 = 组内学生周期得分之和 / 组内人数）。
    每组内每个成员会额外带 group_rank / group_total，方便做"组内第几"。
    组内排序口径：周期净积分降序，同分并列（1,2,2,4）。
    """
    students = get_ranking(class_id, period, cfg=cfg)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for s in students:
        g = (s.get("group_name") or "").strip() or "未分组"
        buckets.setdefault(g, []).append(s)

    out = []
    for g, members in buckets.items():
        total = sum(m["period_score"] for m in members)
        members.sort(key=lambda m: (-int(m["period_score"]), m.get("student_no") or ""))
        apply_competition_rank(members, "period_score")
        for m in members:
            m["group_rank"] = m.get("rank", 0)
            m["group_total"] = len(members)
        out.append({
            "group_name": g,
            "member_count": len(members),
            "sum_score": total,
            "avg_score": round(total / len(members), 1) if members else 0,
            "members": members,
        })
    out.sort(key=lambda x: x["sum_score"], reverse=True)
    return out


def get_student_summary(student_id: str, period: str = "all",
                        cfg: Config | None = None) -> dict[str, Any]:
    """单个学生的周期汇总（家长端用）"""
    cfg = cfg or get_settings()
    start, end = period_range(period)
    row = one(
        """
        SELECT COALESCE(SUM(CASE WHEN status = 'normal' THEN score ELSE 0 END), 0) AS period_score,
               COALESCE(SUM(CASE WHEN status = 'normal' AND score > 0 THEN score ELSE 0 END), 0) AS plus_sum,
               COALESCE(SUM(CASE WHEN status = 'normal' AND score < 0 THEN score ELSE 0 END), 0) AS minus_sum,
               COALESCE(SUM(CASE WHEN status = 'normal' THEN 1 ELSE 0 END), 0) AS log_count
        FROM score_logs
        WHERE student_id = ? AND created_at >= ? AND created_at < ?
        """,
        [student_id, start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")],
        cfg=cfg,
    )
    return {k: int(v or 0) for k, v in row.items()} or {
        "period_score": 0, "plus_sum": 0, "minus_sum": 0, "log_count": 0
    }


def class_overview(class_id: str, cfg: Config | None = None) -> dict[str, Any]:
    """班级概览：学生数、今日评价条数、总积分"""
    today_start, today_end = period_range("today")
    n_student = one("SELECT COUNT(*) AS n FROM students WHERE class_id = ? AND is_active = 1",
                    [class_id], cfg=cfg)
    n_today = one(
        "SELECT COUNT(*) AS n FROM score_logs WHERE class_id = ? AND status = 'normal'"
        " AND created_at >= ? AND created_at < ?",
        [class_id, today_start.strftime("%Y-%m-%d %H:%M:%S"), today_end.strftime("%Y-%m-%d %H:%M:%S")],
        cfg=cfg,
    )
    total = one("SELECT COALESCE(SUM(total_score), 0) AS s FROM students WHERE class_id = ? AND is_active = 1",
                [class_id], cfg=cfg)
    return {
        "student_count": int(n_student.get("n") or 0),
        "today_logs": int(n_today.get("n") or 0),
        "total_score": int(total.get("s") or 0),
    }


# ===========================================================================
# H. 日志查询 / 审计 / 导出
# ===========================================================================
def query_logs(
    class_id: str,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    student_id: str | None = None,
    group_name: str | None = None,
    tag_name: str | None = None,
    score_type: str | None = None,          # plus / minus
    recorded_by: str | None = None,
    keyword: str | None = None,
    include_revoked: bool = False,
    status: str | None = None,              # normal / revoked
    limit: int = 500,
    offset: int = 0,
    cfg: Config | None = None,
) -> list[dict[str, Any]]:
    """
    评价日志复合查询（返回时带上学生姓名）。
    include_revoked=False 时只返回有效记录；status 可显式指定。
    """
    cfg = cfg or get_settings()
    sql = """
        SELECT l.*, s.name AS student_name, s.student_no, s.group_name, s.avatar_key, s.avatar_url
        FROM score_logs l
        LEFT JOIN students s ON s.id = l.student_id
        WHERE l.class_id = ?
    """
    params: list[Any] = [class_id]

    if start:
        sql += " AND l.created_at >= ?"
        params.append(start.strftime("%Y-%m-%d %H:%M:%S"))
    if end:
        sql += " AND l.created_at < ?"
        params.append(end.strftime("%Y-%m-%d %H:%M:%S"))
    if student_id:
        sql += " AND l.student_id = ?"
        params.append(student_id)
    if group_name:
        sql += " AND s.group_name = ?"
        params.append(group_name)
    if tag_name:
        sql += " AND l.tag_name LIKE ?"
        params.append(f"%{tag_name}%")
    if score_type == "plus":
        sql += " AND l.score > 0"
    elif score_type == "minus":
        sql += " AND l.score < 0"
    if recorded_by:
        sql += " AND l.recorded_by = ?"
        params.append(recorded_by)
    if keyword:
        sql += " AND (l.remark LIKE ? OR l.tag_name LIKE ? OR s.name LIKE ?)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    if status in ("normal", "revoked"):
        sql += " AND l.status = ?"
        params.append(status)
    elif not include_revoked:
        sql += " AND l.status = 'normal'"

    sql += " ORDER BY l.created_at DESC, l.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return all_rows(sql, params, cfg=cfg)


def count_logs(class_id: str, include_revoked: bool = False,
               cfg: Config | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM score_logs WHERE class_id = ?"
    params: list[Any] = [class_id]
    if not include_revoked:
        sql += " AND status = 'normal'"
    return int(one(sql, params, cfg=cfg).get("n") or 0)


def get_batch_logs(batch_id: str, cfg: Config | None = None) -> list[dict[str, Any]]:
    return all_rows(
        "SELECT l.*, s.name AS student_name FROM score_logs l"
        " LEFT JOIN students s ON s.id = l.student_id WHERE l.batch_id = ? ORDER BY s.student_no",
        [batch_id], cfg=cfg,
    )


def write_audit(class_id: str | None, teacher: dict[str, Any], action: str,
                detail: str = "", cfg: Config | None = None) -> None:
    """写审计日志（失败不影响主流程）"""
    try:
        ex("INSERT INTO audit_logs (id, class_id, actor_id, actor_name, action, detail, created_at)"
           " VALUES (?, ?, ?, ?, ?, ?, ?)",
           [new_id(), class_id, teacher.get("id"), teacher.get("display_name", ""), action, detail,
            dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")], cfg=cfg)
    except Exception:
        pass


def list_audit_logs(class_id: str, limit: int = 100,
                    cfg: Config | None = None) -> list[dict[str, Any]]:
    return all_rows(
        "SELECT * FROM audit_logs WHERE class_id = ? ORDER BY created_at DESC LIMIT ?",
        [class_id, limit], cfg=cfg,
    )


def export_rows(class_id: str, start: dt.datetime | None = None, end: dt.datetime | None = None,
                include_revoked: bool = True, cfg: Config | None = None) -> list[dict[str, Any]]:
    """导出用：按时间正序返回全部记录（默认包含已撤回，标注状态）"""
    return query_logs(class_id, start=start, end=end, include_revoked=include_revoked,
                      status=None if include_revoked else "normal", limit=100000, cfg=cfg)


def data_counts(cfg: Config | None = None) -> dict[str, int]:
    """各表数据量，用于"系统设置"页展示"""
    out: dict[str, int] = {}
    for t in ("classes", "students", "score_logs", "teachers"):
        try:
            out[t] = int(one(f"SELECT COUNT(*) AS n FROM {t}", cfg=cfg).get("n") or 0)
        except Exception:
            out[t] = 0
    return out
