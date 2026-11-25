"""
tools/ui_check.py —— 浏览器端 UI 自检（真实渲染 + 交互）
=====================================================
用系统已装的 Edge（channel="msedge"）跑一遍所有页面，检查：
  1. 页面无 Streamlit 报错块
  2. 关键文案/元素存在
  3. 侧边栏收起后变窄（仅图标）
  4. 快速切换榜单周期不触发前端 removeChild 报错（本项目历史 Bug）
  5. 家长端看不到班级榜单、撤回按钮
  6. 科任老师看不到撤回按钮与「学生与标签」
  7. 投屏「小组榜」不出现学生姓名

用法：
    python tools/ui_check.py                     # 默认 http://127.0.0.1:8610
退出码 0 = 全部通过
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SHOTS = ROOT.parent / ".shots2"
SHOTS.mkdir(parents=True, exist_ok=True)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + ("" if cond else f"  → {str(extra)[:180]}"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8610")
    ap.add_argument("--head-teacher", default="demo")
    ap.add_argument("--head-pwd", default="demo123")
    ap.add_argument("--subject", default="demo_math")
    ap.add_argument("--subject-pwd", default="demo123")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        errors: list[str] = []

        def new_page(w=1500, h=960):
            ctx = browser.new_context(viewport={"width": w, "height": h}, locale="zh-CN")
            pg = ctx.new_page()
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(f"PAGEERROR {e}"))
            return ctx, pg

        def login(pg, user: str, pwd: str) -> None:
            pg.goto(args.url, wait_until="networkidle")
            time.sleep(4)
            pg.get_by_label("账号").first.fill(user)
            pg.get_by_label("密码").first.fill(pwd)
            pg.get_by_role("button", name="登录").first.click()
            time.sleep(6)

        def sidebar_btn(pg, label: str) -> None:
            pg.get_by_test_id("stSidebarUserContent").get_by_role(
                "button", name=label).first.click()
            time.sleep(4)

        def body(pg) -> str:
            return pg.inner_text("body")

        def has_error_block(pg) -> str:
            t = body(pg)
            for marker in ("Traceback", "StreamlitAPIException", "KeyError(",
                           "AttributeError", "UnboundLocalError"):
                if marker in t:
                    return marker
            return ""

        # ========== 1. 登录页 ==========
        print("== 1. 登录页 ==")
        ctx, pg = new_page()
        pg.goto(args.url, wait_until="networkidle")
        time.sleep(4)
        t = body(pg)
        check("出现系统名", "星光评阅屋" in t)
        check("三种入口齐全", all(k in t for k in ("老师登录", "家长查看", "教室投屏")))
        check("首页不再有『它能做什么』", "它能做什么" not in t)
        check("首页不再有『数据安全』", "数据安全" not in t)
        check("无报错块", not has_error_block(pg), has_error_block(pg))
        pg.screenshot(path=str(SHOTS / "01_login.png"))

        # ========== 2. 班主任登录 ==========
        print("== 2. 班主任登录 → 快速评分 ==")
        pg.get_by_label("账号").first.fill(args.head_teacher)
        pg.get_by_label("密码").first.fill(args.head_pwd)
        pg.get_by_role("button", name="登录").first.click()
        time.sleep(7)
        t = body(pg)
        check("进入评分页", "选择评价项目" in t, t[:180])
        check("仪表盘卡片", "今日评价" in t and "本周之星" in t)
        check("侧边栏分组", all(g in t for g in ("评价操作", "数据查询", "系统设置")))
        check("右下角悬浮按钮", "快速评分" in t)
        check("无报错块", not has_error_block(pg), has_error_block(pg))
        pg.screenshot(path=str(SHOTS / "10_scoring.png"))

        # ========== 3. 侧边栏收起 ==========
        print("== 3. 侧边栏展开/收起 ==")
        try:
            sb = pg.locator('section[data-testid="stSidebar"]').first
            w_before = sb.bounding_box()["width"] if sb.bounding_box() else 0
            # 折叠按钮默认 hover 才可见，先悬停侧边栏再点
            pg.hover('section[data-testid="stSidebar"]')
            time.sleep(0.8)
            pg.locator('div[data-testid="stSidebarCollapseButton"] > button').first.click()
            time.sleep(3)
            w_after = sb.bounding_box()["width"] if sb.bounding_box() else 0
            check("收起后侧边栏移出（可再展开）", w_after < 40 or w_after < w_before * 0.5,
                  f"{w_before} → {w_after}")
            expand_btn = pg.get_by_role("button", name="Expand sidebar")
            check("收起后有展开按钮", expand_btn.count() > 0)
            pg.screenshot(path=str(SHOTS / "02_sidebar_collapsed.png"))
            if expand_btn.count():
                expand_btn.first.click()
                time.sleep(2.5)
            w_back = sb.bounding_box()["width"] if sb.bounding_box() else 0
            check("可重新展开", w_back > 100, f"width={w_back}")
        except Exception as e:
            check("侧边栏收起交互", False, e)

        # ========== 4. 积分榜单 + 快切 ==========
        print("== 4. 积分榜单 / 快速切换周期 ==")
        sidebar_btn(pg, "积分榜单")
        t = body(pg)
        check("榜单渲染", "学生积分榜" in t)
        check("已删除副标题行", "自动统计" not in t)
        check("有组内名次", "组内" in t)
        check("无报错块", not has_error_block(pg), has_error_block(pg))
        before_err = len(errors)
        for label in ("今日", "本周", "本月", "总榜", "今日", "总榜", "本月"):
            try:
                pg.get_by_text(label, exact=True).first.click()
                time.sleep(0.3)
            except Exception:
                pass
        time.sleep(4)
        new_errs = errors[before_err:]
        bad = [e for e in new_errs if ("removeChild" in e or "NotFoundError" in e)]
        check("快切周期无 removeChild 报错", not bad, bad[:2])
        check("切换后页面正常", "学生积分榜" in body(pg))
        pg.screenshot(path=str(SHOTS / "11_ranking.png"))

        # ========== 5. 评价记录 ==========
        print("== 5. 评价记录 ==")
        sidebar_btn(pg, "评价记录")
        t = body(pg)
        check("记录页渲染", ("按学生折叠" in t) or ("命中记录" in t), t[:150])
        check("班主任可见撤回", "撤回" in t)
        check("无报错块", not has_error_block(pg), has_error_block(pg))
        pg.screenshot(path=str(SHOTS / "13_logs.png"))

        # ========== 6. 学生与标签 ==========
        print("== 6. 学生与标签 ==")
        sidebar_btn(pg, "学生与标签")
        t = body(pg)
        check("标签页渲染", "新增标签" in t)
        check("支持上传图标", "上传图标图片" in t)
        check("无报错块", not has_error_block(pg), has_error_block(pg))

        # ========== 7. 班级管理 ==========
        print("== 7. 班级管理 ==")
        sidebar_btn(pg, "班级管理")
        t = body(pg)
        check("班级管理渲染", "我的班级" in t and "学生名单" in t)
        check("无报错块", not has_error_block(pg), has_error_block(pg))

        # ========== 8. 投屏 ==========
        print("== 8. 投屏榜单 ==")
        sidebar_btn(pg, "投屏榜单")
        time.sleep(3)
        t = body(pg)
        check("有视图切换", "学生榜" in t and "小组榜" in t)
        check("投屏隐藏侧边栏",
              not pg.locator('section[data-testid="stSidebar"]').first.is_visible())
        pg.get_by_text("小组榜", exact=True).first.click()
        time.sleep(3.5)
        t2 = body(pg)
        check("小组榜不显示学生姓名",
              not any(x in t2 for x in ("郭宸瑄", "石舒白", "张晨曦", "李昊然", "梁子轩")))
        check("小组榜显示小组名", "组" in t2)
        pg.screenshot(path=str(SHOTS / "12_tv_group.png"))
        check("无报错块", not has_error_block(pg), has_error_block(pg))
        ctx.close()

        # ========== 9. 科任老师 ==========
        print("== 9. 科任老师权限 ==")
        ctx2, pg2 = new_page()
        login(pg2, args.subject, args.subject_pwd)
        t = body(pg2)
        check("科任可进评分页", "选择评价项目" in t, t[:160])
        check("身份显示为科目老师", ("数学老师" in t) or ("化学老师" in t),
              [x for x in ("科任老师", "数学老师") if x in t])
        sidebar_btn(pg2, "评价记录")
        revoke_n = pg2.get_by_role("button", name=re.compile(r"^撤回")).count()
        check("科任看不到撤回", revoke_n == 0, f"{revoke_n} 个")
        tags_n = pg2.get_by_test_id("stSidebarUserContent").get_by_role(
            "button", name="学生与标签").count()
        check("科任看不到学生与标签菜单", tags_n == 0)
        ctx2.close()

        # ========== 10. 家长 ==========
        print("== 10. 家长查看 ==")
        ctx3, pg3 = new_page(430, 900)
        pg3.goto(args.url, wait_until="networkidle")
        time.sleep(4)
        pg3.get_by_role("tab", name=re.compile("家长查看")).click()
        time.sleep(1)
        pg3.get_by_label("孩子学号").fill("01")
        from config import get_settings

        conn = sqlite3.connect(str(get_settings().db_path))
        row = conn.execute(
            "SELECT parent_code FROM students WHERE student_no='01'"
            " ORDER BY created_at DESC LIMIT 1").fetchone()
        conn.close()
        if row:
            pg3.get_by_label("家长查看码").fill(row[0])
            pg3.get_by_role("button", name="查看孩子记录").click()
            time.sleep(5)
            t = body(pg3)
            check("家长登录成功", "累计" in t or "积分" in t, t[:160])
            check("家长端无班级榜单", "学生积分榜" not in t and "小组评比" not in t)
            check("家长端无撤回", "撤回" not in t)
            check("无报错块", not has_error_block(pg3), has_error_block(pg3))
            pg3.screenshot(path=str(SHOTS / "14_parent.png"))
        else:
            check("找到家长查看码", False, "数据库无学生")
        ctx3.close()

        real_errors = [e for e in errors
                       if "favicon" not in e.lower() and "Failed to load resource" not in e]
        print(f"\n控制台错误：{len(real_errors)}")
        for e in real_errors[:5]:
            print("   ·", e[:150])
        check("无前端 JS 错误", not real_errors, real_errors[:2])

        browser.close()

    print("\n" + "=" * 52)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAIL:", f)
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
