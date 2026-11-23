"""
tools/screenshot.py —— 用真实浏览器截图（自检 UI 用）
=====================================================
依赖 playwright，用系统已装的 Edge（channel="msedge"），不额外下载浏览器。
用法：
    python tools/screenshot.py                  # 默认截 4 张关键页面
    python tools/screenshot.py --user demo --pwd demo123
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / ".shots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8601")
    ap.add_argument("--user", default="demo")
    ap.add_argument("--pwd", default="demo123")
    ap.add_argument("--channel", default="msedge")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    shots: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel, headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=1, locale="zh-CN")
        page = ctx.new_page()

        def snap(name: str, wait: float = 2.0) -> None:
            time.sleep(wait)
            f = OUT / f"{name}.png"
            page.screenshot(path=str(f), full_page=False)
            shots.append(str(f))
            print("  saved", f.name)

        print("→ 首页")
        page.goto(args.url, wait_until="networkidle")
        time.sleep(3)
        snap("01_home", 0.5)

        print("→ 老师在登录页输入账号")
        page.get_by_label("账号").first.fill(args.user)
        page.get_by_label("密码").first.fill(args.pwd)
        page.get_by_role("button", name="登录").first.click()
        time.sleep(4)
        snap("02_scoring", 1.0)

        print("→ 班级管理")
        page.get_by_role("button", name="🏫 班级管理").click()
        time.sleep(3.5)
        snap("03_classes", 0.5)

        print("→ 积分榜单")
        page.get_by_role("button", name="🏆 积分榜单").click()
        time.sleep(3.5)
        snap("04_ranking", 0.5)

        print("→ 评价日志")
        page.get_by_role("button", name="📒 评价日志").click()
        time.sleep(3.5)
        snap("05_logs", 0.5)

        print("→ 纯净投屏")
        page.get_by_role("button", name="📺 纯净投屏").click()
        time.sleep(3.5)
        snap("06_tv", 0.5)

        browser.close()

    print(f"\n共 {len(shots)} 张，输出目录：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
