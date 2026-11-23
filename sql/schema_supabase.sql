-- =====================================================================
-- 班级评价管理系统 · Supabase (PostgreSQL) 建表脚本
-- 使用方式：Supabase 控制台 → SQL Editor → 新建查询 → 粘贴本文件全文 → Run
-- 说明：
--   1. 应用通过 service_role 密钥在服务端访问数据库，所有权限校验在应用层完成，
--      因此这里统一 RLS=ON + 不给 anon 任何策略（浏览器即使拿到 anon key 也读不到数据）。
--   2. 时间字段用 timestamptz，比 SQLite 的文本更规范。
-- =====================================================================

-- ---------- 0. 公共扩展 ----------
create extension if not exists pgcrypto;   -- 用于 gen_random_uuid()

-- =====================================================================
-- 1. 教师账号
-- =====================================================================
create table if not exists public.teachers (
    id              uuid primary key default gen_random_uuid(),
    username        text not null unique,
    password_hash   text not null,
    display_name    text not null,
    role            text not null check (role in ('head_teacher', 'subject_teacher')),
    is_active       boolean not null default true,
    must_change_pwd boolean not null default false,
    created_at      timestamptz not null default now()
);

-- =====================================================================
-- 2. 班级
-- =====================================================================
create table if not exists public.classes (
    id              uuid primary key default gen_random_uuid(),
    name            text not null,
    grade           text default '',
    school_year     text default '',
    head_teacher_id uuid references public.teachers(id) on delete set null,
    created_by      uuid references public.teachers(id) on delete set null,
    is_archived     boolean not null default false,
    created_at      timestamptz not null default now()
);

create table if not exists public.teacher_classes (
    id           uuid primary key default gen_random_uuid(),
    teacher_id   uuid not null references public.teachers(id) on delete cascade,
    class_id     uuid not null references public.classes(id) on delete cascade,
    teacher_role text not null check (teacher_role in ('head_teacher', 'subject_teacher')),
    subject      text default '',
    joined_at    timestamptz not null default now(),
    unique (teacher_id, class_id)
);

-- =====================================================================
-- 3. 学生档案
-- =====================================================================
create table if not exists public.students (
    id          uuid primary key default gen_random_uuid(),
    class_id    uuid not null references public.classes(id) on delete cascade,
    student_no  text not null,
    name        text not null,
    gender      text default '',
    group_name  text default '',
    avatar_key  text default '',
    avatar_url  text default '',
    total_score integer not null default 0,
    parent_code text not null,
    remark      text default '',
    is_active   boolean not null default true,
    created_at  timestamptz not null default now(),
    unique (class_id, student_no)
);
create index if not exists idx_students_class on public.students(class_id);

-- =====================================================================
-- 4. 评价标签
-- =====================================================================
create table if not exists public.eval_tags (
    id         uuid primary key default gen_random_uuid(),
    class_id   uuid not null references public.classes(id) on delete cascade,
    name       text not null,
    score      integer not null,
    category   text not null default '加分项',
    icon       text default '⭐',               -- emoji 图标
    icon_img   text default '',                -- 自定义图标图片 URL，优先于 emoji
    sort_order integer not null default 0,
    is_active  boolean not null default true,
    created_at timestamptz not null default now()
);
create index if not exists idx_tags_class on public.eval_tags(class_id);

-- =====================================================================
-- 5. 小组
-- =====================================================================
create table if not exists public.groups (
    id         uuid primary key default gen_random_uuid(),
    class_id   uuid not null references public.classes(id) on delete cascade,
    name       text not null,
    sort_order integer not null default 0,
    created_at timestamptz not null default now(),
    unique (class_id, name)
);

-- =====================================================================
-- 6. 评价流水（软删除，永不物理删除）
-- =====================================================================
create table if not exists public.score_logs (
    id               uuid primary key default gen_random_uuid(),
    class_id         uuid not null references public.classes(id) on delete cascade,
    target_type      text not null check (target_type in ('student', 'group')),
    student_id       uuid references public.students(id) on delete set null,
    group_id         uuid references public.groups(id) on delete set null,
    batch_id         uuid,
    tag_id           uuid references public.eval_tags(id) on delete set null,
    tag_name         text not null,
    score            integer not null,
    remark           text default '',
    image_url        text default '',
    recorded_by      uuid references public.teachers(id) on delete set null,
    recorded_by_name text default '',
    status           text not null default 'normal' check (status in ('normal', 'revoked')),
    revoked_by       uuid references public.teachers(id) on delete set null,
    revoked_by_name  text default '',
    revoked_at       timestamptz,
    revoke_reason    text default '',
    created_at       timestamptz not null default now()
);
create index if not exists idx_logs_class_time on public.score_logs(class_id, created_at desc);
create index if not exists idx_logs_student on public.score_logs(student_id);
create index if not exists idx_logs_batch on public.score_logs(batch_id);

-- =====================================================================
-- 7. 操作日志
-- =====================================================================
create table if not exists public.audit_logs (
    id         uuid primary key default gen_random_uuid(),
    class_id   uuid,
    actor_id   uuid,
    actor_name text default '',
    action     text not null,
    detail     text default '',
    created_at timestamptz not null default now()
);

-- =====================================================================
-- 8. 班级设置
-- =====================================================================
create table if not exists public.class_settings (
    class_id   uuid primary key references public.classes(id) on delete cascade,
    show_rank  boolean not null default true,
    updated_at timestamptz not null default now()
);

-- =====================================================================
-- 9. 行级安全：全部开启，不给 anon/authenticated 任何策略
--    应用只用 service_role（服务端）访问，因此浏览器端无法直连读数据
-- =====================================================================
alter table public.teachers        enable row level security;
alter table public.classes         enable row level security;
alter table public.teacher_classes enable row level security;
alter table public.students        enable row level security;
alter table public.eval_tags       enable row level security;
alter table public.groups          enable row level security;
alter table public.score_logs      enable row level security;
alter table public.audit_logs      enable row level security;
alter table public.class_settings  enable row level security;

-- 显式撤销 anon/authenticated 的表权限，双保险
revoke all on all tables in schema public from anon, authenticated;

-- =====================================================================
-- 10. Storage 存储桶（需先在 Storage 页面手工创建桶，见 documents/01_数据库设计.md）
--     这里给出通过 SQL 直接创建的等价写法（可选）
-- =====================================================================
insert into storage.buckets (id, name, public)
values ('class-eval', 'class-eval', true)
on conflict (id) do nothing;
