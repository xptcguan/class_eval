"""
tools/seed_grade7_class2.py —— 建立「七年级二班」并导入 60 名学生
=====================================================
数据来源：用户提供的名单（小组 一~十，每组 6 人，共 60 人）
- 学号按名单顺序编号 01~60
- 小组名统一成「一组、二组…十组」，与名单里的「一、二、三…」对应
- 默认挂到 demo（林老师）名下；可用 --owner admin 改挂
- 幂等：班级已存在则只补缺失学生，不重复创建

用法：
    python tools/seed_grade7_class2.py
    python tools/seed_grade7_class2.py --owner admin
    python tools/seed_grade7_class2.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import ensure_local_dirs, get_settings  # noqa: E402
from core import avatars, db  # noqa: E402

CLASS_NAME = "七年级二班"

# (小组, 姓名, 性别)
ROSTER: list[tuple[str, str, str]] = [
    ("一", "郭宸瑄", "女"), ("一", "石舒白", "女"), ("一", "梁子轩", "男"),
    ("一", "韩佳萱", "女"), ("一", "贺世嘉", "男"), ("一", "冯铭泽", "男"),
    ("二", "樊梓辰", "男"), ("二", "雷程博", "男"), ("二", "郝皓宇", "男"),
    ("二", "张雨晗", "女"), ("二", "许晨悦", "女"), ("二", "王千慈", "女"),
    ("三", "郭佳怡", "女"), ("三", "杨秋锦", "女"), ("三", "弓名宣", "男"),
    ("三", "李君瑶", "女"), ("三", "柳彦淇", "女"), ("三", "贾天琦", "男"),
    ("四", "冯诚悦", "女"), ("四", "孙艺涵", "女"), ("四", "程琦真", "女"),
    ("四", "徐子皓", "男"), ("四", "潘伟博", "男"), ("四", "王靖恺", "男"),
    ("五", "巩晓曼", "女"), ("五", "赵鑫舒", "女"), ("五", "霍浩轩", "男"),
    ("五", "李博鑫", "男"), ("五", "李姿彤", "女"), ("五", "樊思岩", "男"),
    ("六", "张子涵", "女"), ("六", "师奕祥", "女"), ("六", "王泽鑫", "男"),
    ("六", "轩浩然", "男"), ("六", "胡浩钦", "男"), ("六", "王佳美", "女"),
    ("七", "贺婉君", "女"), ("七", "王若彤", "女"), ("七", "蔡欣凌", "女"),
    ("七", "王硕", "男"), ("七", "毛晓菲", "女"), ("七", "王嘉俊", "男"),
    ("八", "李西豫", "男"), ("八", "张书豪", "男"), ("八", "刘一澎", "男"),
    ("八", "师钰龙", "男"), ("八", "王恩彤", "女"), ("八", "刘佳潼", "女"),
    ("九", "曾珂新", "女"), ("九", "李子萱", "女"), ("九", "孙雨辰", "女"),
    ("九", "于梓睿", "男"), ("九", "王明宇", "男"), ("九", "侯宇浩", "男"),
    ("十", "周子恒", "男"), ("十", "孙御钦", "男"), ("十", "王梓萌", "女"),
    ("十", "马颂扬", "男"), ("十", "杨旻睿", "男"), ("十", "刘雨铃", "女"),
]

CN_NUM = {"一": "一", "二": "二", "三": "三", "四": "四", "五": "五",
          "六": "六", "七": "七", "八": "八", "九": "九", "十": "十"}


def group_label(raw: str) -> str:
    """「一」→「一组」；已经是「第X组」就原样返回"""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.endswith("组"):
        return raw
    return f"{CN_NUM.get(raw, raw)}组"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="demo", help="班主任账号（默认 demo）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = ap.parse_args()

    cfg = get_settings()
    ensure_local_dirs(cfg)
    db.init_db(cfg)

    owner = db.authenticate_teacher(args.owner, cfg.default_admin_password) or \
        db.one("SELECT * FROM teachers WHERE username = ?", [args.owner])
    if not owner:
        print(f"找不到账号 {args.owner}，请先登录该账号或改用 --owner")
        return 1
    owner.pop("password_hash", None)

    # 1. 班级
    existing = next((c for c in db.list_classes_for_teacher(owner["id"])
                     if c["name"] == CLASS_NAME), None)
    if existing:
        cid = existing["id"]
        print(f"班级「{CLASS_NAME}」已存在，复用")
    else:
        if args.dry_run:
            print(f"[dry-run] 将创建班级「{CLASS_NAME}」并归属 {args.owner}")
            return 0
        cid = db.create_class(CLASS_NAME, owner["id"], "七年级", "2026-2027学年")
        print(f"已创建班级「{CLASS_NAME}」")

    # 2. 小组：默认 6 个够用，但名单有 10 个组，补齐
    want_groups = ["一组", "二组", "三组", "四组", "五组",
                   "六组", "七组", "八组", "九组", "十组"]
    have = {g["name"] for g in db.list_groups_of_class(cid)}
    for g in want_groups:
        if g not in have and not args.dry_run:
            db.save_group(cid, g)
    if not args.dry_run:
        print(f"小组：共 {len(db.list_groups_of_class(cid))} 个")

    # 3. 学生
    exist_nos = {s["student_no"] for s in db.list_students(cid, include_inactive=True)}
    rows = []
    for idx, (raw_group, name, gender) in enumerate(ROSTER, start=1):
        no = f"{idx:02d}"
        if no in exist_nos:
            continue
        rows.append({
            "student_no": no,
            "name": name,
            "gender": gender,
            "group_name": group_label(raw_group),
            "avatar_key": avatars.AVATAR_KEYS[(idx - 1) % len(avatars.AVATAR_KEYS)],
        })

    if args.dry_run:
        print(f"[dry-run] 将导入 {len(rows)} 名学生")
        for r in rows[:5]:
            print("   ", r)
        return 0

    ok_n, errs = db.bulk_add_students(cid, rows)
    print(f"已导入 {ok_n} 名学生" + (f"（{len(errs)} 条异常）" if errs else ""))
    for e in errs[:8]:
        print("   ", e)

    total = db.list_students(cid)
    print(f"当前班级学生总数：{len(total)} 人")
    from collections import Counter
    for gname, cnt in sorted(Counter(s["group_name"] for s in total).items()):
        print(f"   {gname or '未分组'}：{cnt} 人")
    return 0


if __name__ == "__main__":
    sys.exit(main())
