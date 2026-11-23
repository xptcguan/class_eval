"""
tools/demo_data.py —— 一键生成演示数据（本地试用/截图用）
=====================================================
用法：
    python tools/demo_data.py            # 生成演示班级与 12 名学生 + 近两周打分
    python tools/demo_data.py --clear    # 只清空演示数据（按班级名匹配）

演示内容：
  · 班主任账号：demo / demo123
  · 科任账号：   demo_math / demo123
  · 班级「八年级(3)班」，12 名学生分 3 组
  · 近 14 天的随机打分（含单人/小组、备注、部分撤回）
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import ensure_local_dirs, get_settings  # noqa: E402
from core import db  # noqa: E402

cfg = get_settings()
ensure_local_dirs(cfg)
db.init_db(cfg)

CLASS_NAME = "八年级(3)班"
NAMES = [
    ("01", "张晨曦", "女"), ("02", "李昊然", "男"), ("03", "王雨萱", "女"),
    ("04", "陈子轩", "男"), ("05", "刘思远", "男"), ("06", "赵语彤", "女"),
    ("07", "孙嘉懿", "男"), ("08", "周书瑶", "女"), ("09", "吴俊熙", "男"),
    ("10", "郑可欣", "女"), ("11", "冯梓涵", "女"), ("12", "何宇航", "男"),
]
REMARKS_PLUS = [
    "课堂主动举手，表达清晰", "作业书写工整，被当作范本", "帮同学讲解难题，很有耐心",
    "值日认真负责，教室里很干净", "这次小测比上次进步了 12 分",
]
REMARKS_MINUS = ["作业未按时提交", "上课与同桌讲话", "早读迟到 5 分钟", "值日未完成", "自习课上玩手机"]


def clear() -> None:
    cls = next((c for c in db.list_active_classes() if c["name"] == CLASS_NAME), None)
    if not cls:
        print("没有找到演示班级，无需清理")
        return
    cid = cls["id"]
    if db.one("SELECT id FROM score_logs WHERE class_id = ? LIMIT 1", [cid]):
        db.ex("DELETE FROM score_logs WHERE class_id = ?", [cid])
    if db.one("SELECT id FROM audit_logs WHERE class_id = ? LIMIT 1", [cid]):
        db.ex("DELETE FROM audit_logs WHERE class_id = ?", [cid])
    if db.one("SELECT id FROM students WHERE class_id = ? LIMIT 1", [cid]):
        db.ex("DELETE FROM students WHERE class_id = ?", [cid])
    if db.one("SELECT id FROM eval_tags WHERE class_id = ? LIMIT 1", [cid]):
        db.ex("DELETE FROM eval_tags WHERE class_id = ?", [cid])
    if db.one("SELECT id FROM groups WHERE class_id = ? LIMIT 1", [cid]):
        db.ex("DELETE FROM groups WHERE class_id = ?", [cid])
    if db.one("SELECT class_id FROM class_settings WHERE class_id = ?", [cid]):
        db.ex("DELETE FROM class_settings WHERE class_id = ?", [cid])
    if db.one("SELECT id FROM teacher_classes WHERE class_id = ? LIMIT 1", [cid]):
        db.ex("DELETE FROM teacher_classes WHERE class_id = ?", [cid])
    db.ex("DELETE FROM classes WHERE id = ?", [cid])
    print(f"已清空演示班级「{CLASS_NAME}」及其记录")


def build() -> None:
    # 1. 账号
    head = db.authenticate_teacher("demo", "demo123")
    if not head:
        ok, msg = db.create_teacher("demo", "demo123", "林老师", role="head_teacher")
        print(msg)
        head = db.authenticate_teacher("demo", "demo123")
    sub = db.authenticate_teacher("demo_math", "demo123")
    if not sub:
        ok, msg = db.create_teacher("demo_math", "demo123", "黄老师", role="subject_teacher")
        print(msg)
        sub = db.authenticate_teacher("demo_math", "demo123")

    if any(c["name"] == CLASS_NAME for c in db.list_active_classes()):
        print(f"演示班级「{CLASS_NAME}」已存在，先执行 --clear 再生成")
        return

    # 2. 班级
    cid = db.create_class(CLASS_NAME, head["id"], "八年级", "2026-2027学年")
    db.add_teacher_to_class(cid, sub["id"], "subject_teacher", "数学")
    print(f"已创建班级：{CLASS_NAME}")

    # 3. 学生
    groups = db.list_groups_of_class(cid)
    rows = []
    for i, (no, name, gender) in enumerate(NAMES):
        rows.append({
            "student_no": no, "name": name, "gender": gender,
            "group_name": groups[i % 3]["name"],
            "avatar_key": f"a{i % 16 + 1:02d}",
        })
    ok_n, errs = db.bulk_add_students(cid, rows)
    print(f"已导入 {ok_n} 名学生" + (f"，异常：{errs}" if errs else ""))

    students = db.list_students(cid)
    plus_tags = db.list_tags(cid, category="加分项")
    minus_tags = db.list_tags(cid, category="扣分项")
    random.seed(20261122)

    # 4. 近 14 天打分
    count = 0
    for day_offset in range(13, -1, -1):
        day = dt.datetime.now() - dt.timedelta(days=day_offset)
        if day.weekday() >= 5:  # 周末不打分
            continue
        for _ in range(random.randint(4, 9)):
            s = random.choice(students)
            use_plus = random.random() < 0.72
            tag = random.choice(plus_tags if use_plus else minus_tags)
            remark = random.choice(REMARKS_PLUS if use_plus else REMARKS_MINUS) if random.random() < 0.7 else ""
            teacher = head if random.random() < 0.6 else sub
            when = day.replace(hour=random.randint(8, 16), minute=random.randint(0, 59))
            db.add_scores(cid, [s["id"]], tag["id"], remark, "", teacher, now=when)
            count += 1

        # 每天来一次小组加分
        g = random.choice(groups)
        members = [s for s in students if s["group_name"] == g["name"]]
        if members and random.random() < 0.5:
            db.add_scores(cid, [m["id"] for m in members], plus_tags[0]["id"],
                          "小组合作完成任务", "", head,
                          target_type="group", group_id=g["id"],
                          now=day.replace(hour=15, minute=30))
            count += len(members)

    # 5. 制造一条撤回记录
    logs = db.query_logs(cid, limit=5)
    if logs:
        db.revoke_log(logs[-1]["id"], head, "演示：重复打分，已撤回")
        print("已演示一条撤回记录")

    print(f"\n完成！共写入 {count} 条打分记录")
    print("班主任账号：demo / demo123")
    print("科任账号：  demo_math / demo123")
    print("家长查看码请在「班级管理 → 家长查看码」查看")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="清空演示班级数据")
    args = ap.parse_args()
    clear() if args.clear else build()
