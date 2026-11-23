"""
tests/test_interactions.py —— 交互与权限端到端测试
=====================================================
用 Streamlit 官方 AppTest 模拟真实点击，验证：
  · 老师登录 → 打分 → 积分变化 → 音效标记
  · 科任老师看不到撤回入口
  · 家长越权（伪造 session）被拦截
  · 评分图表/榜单按周期切换不报错
跑法：python tests/test_interactions.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_tmp = tempfile.mkdtemp(prefix="ce_it_")
os.environ["APP_MODE"] = "local"
os.environ["SQLITE_PATH"] = str(Path(_tmp) / "it.db")
os.environ["UPLOAD_DIR"] = str(Path(_tmp) / "uploads")

from streamlit.testing.v1 import AppTest  # noqa: E402

from config import ensure_local_dirs, get_settings  # noqa: E402
from core import db  # noqa: E402
from core.security import sign_child_token  # noqa: E402

cfg = get_settings()
ensure_local_dirs(cfg)
db.init_db(cfg)

admin = db.authenticate_teacher(cfg.default_admin_user, cfg.default_admin_password)
cid = db.create_class("九年级(1)班", admin["id"], "九年级", "2026-2027")
db.bulk_add_students(cid, [
    {"student_no": "01", "name": "小明", "gender": "男", "group_name": "第一组"},
    {"student_no": "02", "name": "小红", "gender": "女", "group_name": "第一组"},
])
students = db.list_students(cid)
tag = db.list_tags(cid, category="加分项")[0]

# 建一个科任老师
db.create_teacher("sub1", "123456", "李老师", role="subject_teacher")
subject = db.authenticate_teacher("sub1", "123456")
db.add_teacher_to_class(cid, subject["id"], "subject_teacher", "英语")

PASS, FAIL = [], []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else f"  {extra}"))


def teacher_session(at: AppTest, who: dict) -> None:
    at.session_state["auth_role"] = "teacher"
    at.session_state["auth_teacher"] = who
    at.session_state["current_class_id"] = cid


print("== A. 班主任打分流程 ==")
at = AppTest.from_file(str(ROOT / "pages/2_scoring.py"), default_timeout=40)
teacher_session(at, admin)
at.run()
check("打分页正常渲染", not at.exception, str([e.value for e in at.exception]))

# 找到"01 小明"对应的打分按钮并点击
before = db.get_student(students[0]["id"])["total_score"]
target_id = students[0]["id"]
btn = next((b for b in at.button if b.key == f"sc_{target_id}"), None)
check("存在学生打分按钮", btn is not None)
if btn:
    ticks_before = at.session_state.get("sound_tick", 0)
    btn.click().run()
    after = db.get_student(students[0]["id"])["total_score"]
    check("点击后积分增加", after == before + int(tag["score"]), f"{before}->{after}")
    check("触发音效（页面底部已播放并清空标记）",
          at.session_state.get("sound_tick", 0) == ticks_before + 1
          and at.session_state.get("play_sound_now") is None,
          f"tick={at.session_state.get('sound_tick')}, flag={at.session_state.get('play_sound_now')}")
    # 轻提示改为 toast，成功信息不再占用页面元素，改从 session 状态验证
    check("打分写库成功", db.query_logs(cid, student_id=target_id, limit=1) != [])

print("== B. 切换标签后打分 ==")
minus = [t for t in db.list_tags(cid) if int(t["score"]) < 0][0]
at2 = AppTest.from_file(str(ROOT / "pages/2_scoring.py"), default_timeout=40)
teacher_session(at2, admin)
at2.run()
mbtn = next((b for b in at2.button if b.key == f"mt_{minus['id']}"), None)
check("存在扣分标签按钮", mbtn is not None)
if mbtn:
    mbtn.click().run()
    check("选中扣分标签", at2.session_state.get("sel_tag") == minus["id"])
    sbtn = next((b for b in at2.button if b.key == f"sc_{students[1]['id']}"), None)
    if sbtn:
        sbtn.click().run()
        check("扣分生效", db.get_student(students[1]["id"])["total_score"] == int(minus["score"]),
              str(db.get_student(students[1]["id"])["total_score"]))

print("== C. 小组批量打分 ==")
at3 = AppTest.from_file(str(ROOT / "pages/2_scoring.py"), default_timeout=40)
teacher_session(at3, admin)
at3.run()
grp = db.list_groups_of_class(cid)[0]
gbtn = next((b for b in at3.button if b.key == f"grp_{grp['id']}"), None)
check("小组页首次进入默认单人模式（无组按钮）", gbtn is None)
# 切到小组模式
radio = next((r for r in at3.radio if r.key == "score_mode"), None)
if radio is not None:
    radio.set_value("小组批量").run()
    gbtn = next((b for b in at3.button if b.key == f"grp_{grp['id']}"), None)
    check("切换后出现整组按钮", gbtn is not None)
    if gbtn:
        gbtn.click().run()
        batch = db.query_logs(cid, limit=50)
        check("整组打分生成 2 条记录",
              len([x for x in batch if x.get("group_id") == grp["id"]]) >= 2)

print("== D. 科任老师权限 ==")
at4 = AppTest.from_file(str(ROOT / "pages/4_logs.py"), default_timeout=40)
teacher_session(at4, subject)
at4.run()
check("科任老师可看日志", not at4.exception, str([e.value for e in at4.exception]))
revoke_btns = [b for b in at4.button if (b.key or "").startswith("rv_")]
check("科任老师看不到撤回按钮", len(revoke_btns) == 0, f"发现 {len(revoke_btns)} 个")

at5 = AppTest.from_file(str(ROOT / "pages/5_students_tags.py"), default_timeout=40)
teacher_session(at5, subject)
at5.run()
check("科任老师访问标签页被拦截", any("仅班主任" in (e.value or "") for e in at5.error))

print("== E. 家长越权 ==")
parent_ok = AppTest.from_file(str(ROOT / "pages/7_parent_view.py"), default_timeout=40)
parent_ok.session_state["auth_role"] = "parent"
parent_ok.session_state["auth_student"] = students[0]
parent_ok.session_state["auth_parent_token"] = sign_child_token(students[0]["id"])
parent_ok.run()
check("合法家长可访问", not parent_ok.exception, str([e.value for e in parent_ok.exception]))
check("家长页不含班级榜单", not any("积分榜" in (m.value or "") for m in parent_ok.markdown))

fake = AppTest.from_file(str(ROOT / "pages/7_parent_view.py"), default_timeout=40)
fake.session_state["auth_role"] = "parent"
fake.session_state["auth_student"] = students[1]        # 想偷看小红
fake.session_state["auth_parent_token"] = sign_child_token(students[0]["id"])  # 拿的是小明的令牌
fake.run()
check("伪造 session 被签名校验拦截",
      any("重新登录" in (w.value or "") for w in fake.warning) or bool(fake.exception))

print("== F. 榜单切换周期 ==")
at6 = AppTest.from_file(str(ROOT / "pages/3_ranking.py"), default_timeout=40)
teacher_session(at6, admin)
at6.run()
check("榜单渲染正常", not at6.exception, str([e.value for e in at6.exception]))
for p in ["today", "week", "month", "all"]:
    at6.radio[0].set_value(p).run()
    check(f"切换到 {p} 无异常", not at6.exception, str([e.value for e in at6.exception]) if at6.exception else "")

print("== G. 投屏模式只读 ==")
at7 = AppTest.from_file(str(ROOT / "pages/0_tv_board.py"), default_timeout=40)
at7.session_state["auth_role"] = "play"
at7.session_state["current_class_id"] = cid
at7.run()
check("投屏页正常渲染", not at7.exception, str([e.value for e in at7.exception]))
check("投屏模式无打分面板", not any((b.key or "").startswith("sc_") for b in at7.button))

print()
print("=" * 50)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    for f in FAIL:
        print("  FAIL:", f)
    sys.exit(1)
print("全部通过 ✅")
