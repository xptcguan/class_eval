-- ============================================================================
-- check_bool_types.sql —— 只查询、不改数据
-- ============================================================================
-- 用途：在 Supabase SQL Editor 里先跑这一段，确认布尔列的真实类型。
-- 判断标准：
--   data_type = boolean  → 表建对了（用的 schema_supabase.sql）
--   data_type = integer  → 表建错了（当初执行的是 schema_sqlite.sql），
--                          需要再跑 fix_bool_to_boolean.sql 规范化
-- ============================================================================

select
    table_name            as "表",
    column_name           as "列",
    data_type             as "当前类型",
    case
        when data_type = 'boolean' then '✅ 正确'
        when data_type = 'integer' then '⚠️ 需要转换'
        else '❓ 未知'
    end                   as "结论"
from information_schema.columns
where table_schema = 'public'
  and column_name in ('is_active', 'is_archived', 'show_rank', 'must_change_pwd')
order by table_name, column_name;
