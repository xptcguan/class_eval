-- ============================================================================
-- fix_bool_to_boolean.sql —— 把误建成 INTEGER 的布尔列统一改成真正的 BOOLEAN
-- ============================================================================
-- 适用场景：
--   当初在 Supabase SQL Editor 里执行的是 sql/schema_sqlite.sql，
--   导致 is_active / is_archived / show_rank / must_change_pwd 是 integer（0/1）。
--   程序虽然已经做了兼容（按列真实类型自动改写 SQL），但规范化之后更稳，
--   也能避免以后换别的客户端时再踩坑。
--
-- 特点：
--   · 幂等：已经 boolean 的列会被跳过，可重复执行
--   · 安全：只在列确实是 integer 时才转换，转换时 1→true、其余→false
--   · 不删数据：只改列类型
--
-- 执行位置：Supabase 控制台 → SQL Editor → New query → 全文粘贴 → Run
-- 执行完记得回 Streamlit → Manage app → Reboot（程序会重新探测列类型）
-- ============================================================================

-- ① 先看一眼当前类型（确认确实需要转）
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and column_name in ('is_active', 'is_archived', 'show_rank', 'must_change_pwd')
order by table_name, column_name;

-- ② 逐列转换（using 子句负责把 0/1 转成 false/true）
do $$
begin
  -- teachers.is_active
  if exists (select 1 from information_schema.columns
             where table_schema='public' and table_name='teachers'
               and column_name='is_active' and data_type='integer') then
    alter table public.teachers
      alter column is_active drop default;
    alter table public.teachers
      alter column is_active type boolean using (is_active = 1);
    alter table public.teachers
      alter column is_active set default true;
    alter table public.teachers
      alter column is_active set not null;
  end if;

  -- teachers.must_change_pwd
  if exists (select 1 from information_schema.columns
             where table_schema='public' and table_name='teachers'
               and column_name='must_change_pwd' and data_type='integer') then
    alter table public.teachers
      alter column must_change_pwd drop default;
    alter table public.teachers
      alter column must_change_pwd type boolean using (must_change_pwd = 1);
    alter table public.teachers
      alter column must_change_pwd set default false;
    alter table public.teachers
      alter column must_change_pwd set not null;
  end if;

  -- classes.is_archived
  if exists (select 1 from information_schema.columns
             where table_schema='public' and table_name='classes'
               and column_name='is_archived' and data_type='integer') then
    alter table public.classes
      alter column is_archived drop default;
    alter table public.classes
      alter column is_archived type boolean using (is_archived = 1);
    alter table public.classes
      alter column is_archived set default false;
    alter table public.classes
      alter column is_archived set not null;
  end if;

  -- students.is_active
  if exists (select 1 from information_schema.columns
             where table_schema='public' and table_name='students'
               and column_name='is_active' and data_type='integer') then
    alter table public.students
      alter column is_active drop default;
    alter table public.students
      alter column is_active type boolean using (is_active = 1);
    alter table public.students
      alter column is_active set default true;
    alter table public.students
      alter column is_active set not null;
  end if;

  -- eval_tags.is_active
  if exists (select 1 from information_schema.columns
             where table_schema='public' and table_name='eval_tags'
               and column_name='is_active' and data_type='integer') then
    alter table public.eval_tags
      alter column is_active drop default;
    alter table public.eval_tags
      alter column is_active type boolean using (is_active = 1);
    alter table public.eval_tags
      alter column is_active set default true;
    alter table public.eval_tags
      alter column is_active set not null;
  end if;

  -- class_settings.show_rank
  if exists (select 1 from information_schema.columns
             where table_schema='public' and table_name='class_settings'
               and column_name='show_rank' and data_type='integer') then
    alter table public.class_settings
      alter column show_rank drop default;
    alter table public.class_settings
      alter column show_rank type boolean using (show_rank = 1);
    alter table public.class_settings
      alter column show_rank set default true;
    alter table public.class_settings
      alter column show_rank set not null;
  end if;
end $$;

-- ③ 再查一次，确认都变成 boolean
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and column_name in ('is_active', 'is_archived', 'show_rank', 'must_change_pwd')
order by table_name, column_name;
