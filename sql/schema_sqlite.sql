-- =====================================================================
-- 班级评价管理系统 · SQLite 建表脚本（本地开发模式）
-- 由 core/db.py 在首次启动时自动执行，无需手动运行
-- 执行方式（可选，手工建库时用）：
--     sqlite3 data/app.db < sql/schema_sqlite.sql
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 1. 教师账号（班主任 / 科任老师）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teachers (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,                 -- PBKDF2 哈希，绝不存明文
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('head_teacher', 'subject_teacher')),
    is_active     INTEGER NOT NULL DEFAULT 1,    -- 1=启用 0=停用（停用后无法登录）
    must_change_pwd INTEGER NOT NULL DEFAULT 0,  -- 1=首次登录强制修改密码
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- 2. 班级
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classes (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,                    -- 例：八年级(3)班
    grade      TEXT DEFAULT '',                  -- 例：八年级
    school_year TEXT DEFAULT '',                 -- 例：2026-2027学年
    head_teacher_id TEXT REFERENCES teachers(id),
    created_by TEXT REFERENCES teachers(id),
    is_archived INTEGER NOT NULL DEFAULT 0,      -- 1=归档（不删除历史数据）
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 教师与班级的多对多关系：一个老师可管理多个班级
-- 角色 teacher_role: head_teacher=班主任(高权限) / subject_teacher=科任(只能打分)
CREATE TABLE IF NOT EXISTS teacher_classes (
    id           TEXT PRIMARY KEY,
    teacher_id   TEXT NOT NULL REFERENCES teachers(id),
    class_id     TEXT NOT NULL REFERENCES classes(id),
    teacher_role TEXT NOT NULL CHECK (teacher_role IN ('head_teacher', 'subject_teacher')),
    subject      TEXT DEFAULT '',                -- 科任老师任教学科
    joined_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (teacher_id, class_id)
);

-- ---------------------------------------------------------------------
-- 3. 学生档案
-- ---------------------------------------------------------------------
-- parent_code: 与学号组合成家长登录账号（学号 + 家长码，免密码登录，可随时重置）
CREATE TABLE IF NOT EXISTS students (
    id          TEXT PRIMARY KEY,
    class_id    TEXT NOT NULL REFERENCES classes(id),
    student_no  TEXT NOT NULL,                   -- 学号（班内唯一）
    name        TEXT NOT NULL,
    gender      TEXT DEFAULT '',                 -- 男/女
    group_name  TEXT DEFAULT '',                 -- 小组名（如：第一组）
    avatar_key  TEXT DEFAULT '',                 -- 预设头像 key（assets/avatars 下文件名）
    avatar_url  TEXT DEFAULT '',                 -- 自定义头像作品集（本地路径 / Supabase 公共 URL）
    total_score INTEGER NOT NULL DEFAULT 0,      -- 冗余总分，仅用于列表排序展示；真实分以积分流水为准
    parent_code TEXT NOT NULL,                   -- 家长查看码（4~6 位），可重置
    remark      TEXT DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (class_id, student_no)
);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);

-- ---------------------------------------------------------------------
-- 4. 评价标签（加分项 / 扣分项）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_tags (
    id         TEXT PRIMARY KEY,
    class_id   TEXT NOT NULL REFERENCES classes(id),
    name       TEXT NOT NULL,
    score      INTEGER NOT NULL,                 -- 正数=加分项，负数=扣分项
    category   TEXT NOT NULL DEFAULT '加分项',    -- 加分项 / 扣分项
    icon       TEXT DEFAULT '⭐',               -- emoji 图标
    icon_img   TEXT DEFAULT '',                -- 自定义图标图片（本地相对路径 / Supabase URL），优先于 emoji
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active  INTEGER NOT NULL DEFAULT 1,       -- 0=停用（历史记录不受影响）
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tags_class ON eval_tags(class_id);

-- ---------------------------------------------------------------------
-- 5. 学生分组（小组批量打分用的实体）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS groups (
    id         TEXT PRIMARY KEY,
    class_id   TEXT NOT NULL REFERENCES classes(id),
    name       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (class_id, name)
);

-- ---------------------------------------------------------------------
-- 6. 评价流水（打分记录，永久存档 + 软删除）
-- ---------------------------------------------------------------------
-- target_type: student=单人 / group=小组批量（每个学生一条明细，方便统计与家长查询）
-- status     : normal=正常 / revoked=已撤回（软删除，UI 与统计均隐藏，但永不物理删除）
CREATE TABLE IF NOT EXISTS score_logs (
    id               TEXT PRIMARY KEY,
    class_id         TEXT NOT NULL REFERENCES classes(id),
    target_type      TEXT NOT NULL CHECK (target_type IN ('student', 'group')),
    student_id       TEXT REFERENCES students(id),
    group_id         TEXT REFERENCES groups(id),
    batch_id         TEXT,                        -- 同一次批量打分共享（用于整批撤回）
    tag_id           TEXT REFERENCES eval_tags(id),
    tag_name         TEXT NOT NULL,               -- 快照：标签改名/删除后历史仍可读
    score            INTEGER NOT NULL,            -- 快照：当时的分值
    remark           TEXT DEFAULT '',             -- 文字备注
    image_url        TEXT DEFAULT '',             -- 图片证据（本地相对路径 / Supabase URL）
    recorded_by      TEXT REFERENCES teachers(id),
    recorded_by_name TEXT DEFAULT '',             -- 快照：打分老师姓名
    status           TEXT NOT NULL DEFAULT 'normal',
    revoked_by       TEXT,
    revoked_by_name  TEXT DEFAULT '',
    revoked_at       TEXT,
    revoke_reason    TEXT DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_logs_class_time ON score_logs(class_id, created_at);
CREATE INDEX IF NOT EXISTS idx_logs_student ON score_logs(student_id);

-- ---------------------------------------------------------------------
-- 7. 操作日志（撤回等关键操作审计）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id         TEXT PRIMARY KEY,
    class_id   TEXT,
    actor_id   TEXT,
    actor_name TEXT DEFAULT '',
    action     TEXT NOT NULL,                    -- revoke_score / revoke_batch / reset_parent_code ...
    detail     TEXT DEFAULT '',                  -- 人类可读说明
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- 8. 班级设置（榜单是否显示名次等）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS class_settings (
    class_id    TEXT PRIMARY KEY REFERENCES classes(id),
    show_rank   INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
