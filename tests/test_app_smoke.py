"""
tests/test_app_smoke.py —— Streamlit 页面冒烟测试（用官方 AppTest，无需浏览器）
=====================================================
逐个页面跑一遍，捕捉任何异常（导入错误、KeyError、SQL 报错等）。
跑法：python tests/test_app_smoke.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_tmp = tempfile.mkdtemp(prefix="ce_app_")
os.environ["APP_MODE"] = "local"
os.environ["SQLITE_PATH"] = str(Path(_tmp) / "app.db")
os.environ["UPLOAD_DIR"] = str(Path(_tmp) / "uploads")
os.environ["DEFAULT_ADMIN_USER"] = "admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "admin123"

from streamlit.testing.v1 import AppTest  # noqa: E402

from config import ensure_local_dirs, get_settings  # noqa: E402
from core import db  # noqa: E402
from core.security import sign_child_token  # noqa: E402

cfg = get_settings()
ensure_local_dirs(cfg)
db.init_db(cfg)

# 准备一组演示数据
admin = db.authenticate_teacher("admin", "admin123")
cid = db.create_class("八年级(3)班", admin["id"], "八年级", "2026-2027")
db.bulk_add_students(cid, [
    {"student_no": f"{i:02d}", "name": f"张{i}", "gender": "男" if i % 2 else "女",
     "group_name": "第一组" if i <= 3 else "第二组"} for i in range(1, 7)
])
students = db.list_students(cid)
tag = db.list_tags(cid, category="加分项")[0]
minus = db.list_tags(cid, category="扣分项")[0]
db.add_scores(cid, [students[0]["id"]], tag["id"], "表现很好", "", admin)
db.add_scores(cid, [s["id"] for s in students[:3]], minus["id"], "", "", admin, target_type="group")
log = db.query_logs(cid, limit=1)[0]
db.revoke_log(log["id"], admin, "重复打分")

TARGET = students[1]

results: list[tuple[str, bool, str]] = []


def run(page: str, setup=None, label: str = "") -> None:
    """跑一个页面，收集异常"""
    name = label or page
    try:
        at = AppTest.from_file(str(ROOT / page), default_timeout=40)
        if setup:
            setup(at)
        at.run()
        if at.exception:
            msgs = "; ".join(f"{e.value}" for e in at.exception)
            results.append((name, False, msgs))
            print(f"  ❌ {name}: {msgs}")
        else:
            errs = [f"{e.value}" for e in at.error]
            if errs:
                print(f"  ⚠️  {name} 页面有 error 提示: {errs[:2]}")
            results.append((name, True, ""))
            print(f"  ✅ {name}")
    except Exception:
        tb = traceback.format_exc()
        results.append((name, False, tb.splitlines()[-1]))
        print(f"  ❌ {name}: {tb.splitlines()[-1]}")


def as_teacher(at: AppTest) -> None:
    at.session_state["auth_role"] = "teacher"
    at.session_state["auth_teacher"] = admin
    at.session_state["current_class_id"] = cid


def as_parent(at: AppTest) -> None:
    at.session_state["auth_role"] = "parent"
    at.session_state["auth_student"] = TARGET
    at.session_state["auth_parent_token"] = sign_child_token(TARGET["id"])


def as_play(at: AppTest) -> None:
    at.session_state["auth_role"] = "play"
    at.session_state["current_class_id"] = cid


print("== 页面冒烟测试 ==")
run("Home.py", label="首页/登录页")
run("pages/0_tv_board.py", as_play, "0 投屏榜单(投屏模式)")
run("pages/0_tv_board.py", as_teacher, "0 投屏榜单(教师模式)")
run("pages/1_classes.py", as_teacher, "1 班级管理")
run("pages/2_scoring.py", as_teacher, "2 积分评价")
run("pages/3_ranking.py", as_teacher, "3 积分榜单")
run("pages/4_logs.py", as_teacher, "4 评价日志")
run("pages/5_students_tags.py", as_teacher, "5 学生与标签")
run("pages/6_settings_export.py", as_teacher, "6 设置与导出")
run("pages/7_parent_view.py", as_parent, "7 家长查看(家长模式)")

print()
ok = sum(1 for _, p, _ in results if p)
print(f"通过 {ok}/{len(results)}")
if ok != len(results):
    sys.exit(1)
