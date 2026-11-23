-- ============================================================================
-- create_admin.sql —— 在 Supabase 里建一个可登录的班主任账号
-- ============================================================================
-- 账号：admin     密码：teacher2026
-- 说明：本系统的密码格式是 PBKDF2（pbkdf2_sha256$迭代$盐$摘要），
--       不能用 bcrypt 的 "$2b$12$..." 那种串，否则永远登录失败。
--       下面的 hash 是上面这个密码实际算出来的，已本地验证通过。
-- 用法：Supabase → SQL Editor → 全文粘贴 → Run，然后回 Streamlit Reboot。
-- ============================================================================

-- 若已存在同账号，先删掉（保留其他数据不动）
delete from public.teachers where username = 'admin';

insert into public.teachers
    (id, username, password_hash, display_name, role, is_active, must_change_pwd)
values
    ('0468e660-c2e4-45d8-a99d-aba1eb8771b4',
     'admin',
     'pbkdf2_sha256$200000$d0f740b39fd6e4653e6d488f0134c376$b3b0b27b1e83f789cccb72af3af701bcc6a9185d62f2771a1b08c38ba1209839',
     '系统管理员',
     'head_teacher',
     true,
     false);

-- 验证：应返回 1 行，is_active = true
select id, username, display_name, role, is_active
from public.teachers
where username = 'admin';
