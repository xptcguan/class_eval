"""
tests/test_core.py —— 核心业务逻辑自测（不需要启动 Streamlit）
=====================================================
直接跑：  python tests/test_core.py
覆盖：建库、建班、录学生、打分、撤回、榜单并列名次、家长登录隔离、导出 Excel
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 用临时数据库，避免污染真实数据
_tmp = tempfile.mkdtemp(prefix="ce_test_")
os.environ["APP_MODE"] = "local"
os.environ["SQLITE_PATH"] = str(Path(_tmp) / "test.db")
os.environ["UPLOAD_DIR"] = str(Path(_tmp) / "uploads")

from config import ensure_local_dirs, get_settings  # noqa: E402
from core import db, exporter  # noqa: E402

cfg = get_settings()
ensure_local_dirs(cfg)

PASS, FAIL = [], []


def check(name: str, cond: bool, extra: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(f"{name} {extra}")
        print(f"  ❌ {name} {extra}")


print("== 1. 初始化 ==")
db.init_db(cfg)
admin = db.authenticate_teacher(cfg.default_admin_user, cfg.default_admin_password)
check("默认管理员可登录", admin is not None)
check("错误密码被拒绝", db.authenticate_teacher(cfg.default_admin_user, "wrong") is None)

print("== 2. 班级 ==")
cid = db.create_class("测试班", admin["id"], "八年级", "2026-2027")
check("新建班级成功", bool(db.get_class(cid)))
check("默认标签已创建(12个)", len(db.list_tags(cid)) == 12)
check("默认小组已创建(6个)", len(db.list_groups_of_class(cid)) == 6)
check("创建者是班主任", db.is_head_teacher(admin["id"], cid))

print("== 3. 学生 ==")
rows = [{"student_no": f"{i:02d}", "name": f"学生{i}", "gender": "男" if i % 2 else "女",
         "group_name": "第一组" if i <= 3 else "第二组"} for i in range(1, 7)]
ok_n, errs = db.bulk_add_students(cid, rows)
check("批量导入 6 人", ok_n == 6, str(errs))
students = db.list_students(cid)
check("学生列表 6 人", len(students) == 6)
check("学号不可重复", db.add_student(cid, "01", "重复")[0] is False)

print("== 4. 打分 ==")
tag = db.list_tags(cid, category="加分项")[0]           # 积极发言 +2
minus_tag = db.list_tags(cid, category="扣分项")[0]      # 作业未交 -3
t1 = students[0]
ok, msg, batch1 = db.add_scores(cid, [t1["id"]], tag["id"], "课堂表现好", "", admin)
check("单人打分成功", ok, msg)
check("总分 +2", db.get_student(t1["id"])["total_score"] == int(tag["score"]))

group_ids = [s["id"] for s in students if s["group_name"] == "第一组"]
ok, msg, batch2 = db.add_scores(cid, group_ids, minus_tag["id"], "集体迟到", "",
                                admin, target_type="group")
check("小组批量打分", ok and len(db.get_batch_logs(batch2)) == 3, msg)
check("小组每人 -3", all(db.get_student(g)["total_score"] == int(minus_tag["score"]) for g in group_ids[1:]),
      str([db.get_student(g)["total_score"] for g in group_ids]))

print("== 5. 科任老师权限 ==")
ok, _ = db.create_teacher("teacher2", "123456", "王老师", role="subject_teacher")
db.add_teacher_to_class(cid, db.list_teachers("subject_teacher")[0]["id"], "subject_teacher", "数学")
subject = db.authenticate_teacher("teacher2", "123456")
check("科任老师已入班", db.get_membership(subject["id"], cid) is not None)
check("科任老师不是班主任", not db.is_head_teacher(subject["id"], cid))

log_id = db.query_logs(cid, limit=1)[0]["id"]
ok, msg = db.revoke_log(log_id, subject, "想撤回")
check("科任老师不能撤回", ok is False and "班主任" in msg, msg)

print("== 6. 撤回（班主任） ==")
before = db.get_student(t1["id"])["total_score"]
# 撤回 t1 的那条加分（先找出来）
logs_t1 = db.query_logs(cid, student_id=t1["id"], score_type="plus")
ok, msg = db.revoke_log(logs_t1[0]["id"], admin, "重复打分")
check("班主任撤回成功", ok, msg)
check("总分已回滚", db.get_student(t1["id"])["total_score"] == before - int(tag["score"]))
check("软删除：记录仍可查到", len(db.query_logs(cid, student_id=t1["id"], status="revoked")) == 1)
check("重复撤回被拒绝", db.revoke_log(logs_t1[0]["id"], admin, "again")[0] is False)
check("审计日志已写入", len(db.list_audit_logs(cid)) >= 1)

ok, msg = db.revoke_batch(batch2, admin, "整批打错了")
check("整批撤回", ok, msg)
check("整批后总分为 0", db.get_student(group_ids[0])["total_score"] == 0)

print("== 7. 榜单 ==")
# 造成 5 分、5 分、5 分、1 分的分布，验证竞争排名 1、1、1、4
for i, s in enumerate(students[:4]):
    db.add_scores(cid, [s["id"]], tag["id"], "", "", admin, now=dt.datetime.now())
for _ in range(2):
    db.add_scores(cid, [students[3]["id"]], minus_tag["id"], "", "", admin)

rank = db.apply_competition_rank(db.get_ranking(cid, "all"))
check("榜单人数正确", len(rank) == 6)
ranks = [r["rank"] for r in rank]
check("前三名并列第一", ranks[:3] == [1, 1, 1], f"ranks={ranks}")
check("第 4 位是第 4 名（竞争排名）", ranks[3] == 4, f"ranks={ranks}")
today = db.period_range("today")
check("今日区间正确", today[0].date() == dt.date.today())
week = db.period_range("week")
check("本周起点为周一", week[0].weekday() == 0)

groups = db.get_group_ranking(cid, "all")
check("小组榜有数据", len(groups) > 0)

print("== 8. 家长隔离 ==")
st_a = students[0]
found = db.find_student_by_parent(cid, st_a["student_no"], st_a["parent_code"])
check("正确查看码可登录", found is not None and found["id"] == st_a["id"])
check("错误查看码被拒", db.find_student_by_parent(cid, st_a["student_no"], "0000") is None)
check("错班级被拒", db.find_student_by_parent("fake-class", st_a["student_no"], st_a["parent_code"]) is None)
mine = db.query_logs(cid, student_id=st_a["id"], include_revoked=False)
check("家长查询只含自己孩子", all(x["student_id"] == st_a["id"] for x in mine))

print("== 9. 标签/小组 CRUD ==")
ok, msg = db.save_tag(cid, "主动擦黑板", 2, icon="🧽")
check("新增标签", ok, msg)
new_tag = next(t for t in db.list_tags(cid) if t["name"] == "主动擦黑板")
ok, msg = db.save_tag(cid, "主动擦黑板(改)", 3, new_tag["id"], "🧽")
check("编辑标签", ok and int(db.list_tags(cid, include_inactive=True)[0]["score"]) >= 0, msg)
db.delete_tag(new_tag["id"])
check("停用标签后不在启用列表", new_tag["id"] not in [t["id"] for t in db.list_tags(cid)])
ok, msg = db.save_group(cid, "第七组")
check("新增小组", ok, msg)

print("== 10. 导出 Excel ==")
rows = db.export_rows(cid)
stats = db.apply_competition_rank(db.get_ranking(cid, "all"))
data = exporter.export_excel(rows, "测试班", stats, "全部时间", "系统管理员")
check("Excel 生成成功", len(data) > 3000, f"{len(data)} bytes")
out = Path(_tmp) / "out.xlsx"
out.write_bytes(data)
try:
    import pandas as pd

    xl = pd.ExcelFile(out)
    check("包含 3 个 sheet", len(xl.sheet_names) == 3, str(xl.sheet_names))
    df = xl.parse("德育评价台账")
    need = ["日期时间", "学号", "姓名", "评价项目", "分值", "记录状态"]
    check("表头符合德育台账", all(c in df.columns for c in need), str(list(df.columns)))
    check("包含已撤回记录", "已撤回" in set(df["记录状态"].astype(str)))
except Exception as e:
    check("Excel 可读", False, str(e))

print("== 11. 修改密码 ==")
ok, msg = db.change_password(admin["id"], cfg.default_admin_password, "newpass123")
check("改密码成功", ok, msg)
check("新密码可登录", db.authenticate_teacher(cfg.default_admin_user, "newpass123") is not None)
check("旧密码失效", db.authenticate_teacher(cfg.default_admin_user, cfg.default_admin_password) is None)

print()
print("=" * 50)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    for f in FAIL:
        print("  FAIL:", f)
    sys.exit(1)
print("全部通过 ✅")
