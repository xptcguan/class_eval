-- ============================================================================
-- add_unique_student_no.sql —— 给 students 加「同班学号唯一」约束
-- ============================================================================
-- 目的：防止导入时前端漏判，重复学号在数据库层被拦住
--       （对应需求文档 3.1.2「数据库兜底」）
--
-- 前提：已确认同班内没有重复学号（你已线上验证通过）
-- 特点：幂等，可重复执行；索引已存在时不会报错
--
-- 执行位置：Supabase → SQL Editor → 全文粘贴 → Run
-- ============================================================================

-- ① 先复查一次（应为 0 行）
--     如果这里还有结果，说明存在重复，先清理再加索引
select class_id, student_no, count(*) as 重复次数
from public.students
group by class_id, student_no
having count(*) > 1;

-- ② 建唯一索引（同班内学号不可重复；不同班可以同学号）
create unique index if not exists uq_students_class_no
    on public.students (class_id, student_no);

-- ③ 验证：应看到 uq_students_class_no
select indexname, indexdef
from pg_indexes
where tablename = 'students' and schemaname = 'public';
