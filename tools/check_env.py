"""
tools/check_env.py —— 环境自检（部署前跑一下，排查 90% 的问题）
=====================================================
用法：
    python tools/check_env.py            # 检查当前 .env 配置
    python tools/check_env.py --cloud    # 强制按云端模式检查

检查项：
  1. Python 版本与依赖是否齐全
  2. 运行模式（local / cloud）与数据库连通性
  3. SQLite 表是否建全 / Supabase 表是否已建
  4. Supabase Storage 桶是否可读写（云端）
  5. 文件目录权限（本地）
  6. 是否能生成 Excel
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, BAD, WARN = [], [], []


def ok(msg):
    OK.append(msg)
    print(f"  \033[92m✓\033[0m {msg}")


def bad(msg):
    BAD.append(msg)
    print(f"  \033[91m✗\033[0m {msg}")


def warn(msg):
    WARN.append(msg)
    print(f"  \033[93m!\033[0m {msg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", action="store_true", help="按云端模式检查")
    args = ap.parse_args()
    if args.cloud:
        os.environ["APP_MODE"] = "cloud"

    print("=" * 60)
    print(" 1. Python 与依赖")
    print("=" * 60)
    v = sys.version_info
    print(f"  Python {v.major}.{v.minor}.{v.micro}")
    if v >= (3, 9):
        ok("Python 版本满足要求（>=3.9）")
    else:
        bad("Python 版本过低，请升级到 3.11+")

    for mod, need in [("streamlit", True), ("pandas", True), ("openpyxl", True),
                      ("dotenv", False), ("psycopg", False), ("supabase", False)]:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "?")
            ok(f"{mod} 已安装（{ver}）")
        except ImportError:
            (bad if need else warn)(f"{mod} 未安装" + ("（必须）" if need else "（云端才需要）"))

    print("=" * 60)
    print(" 2. 配置读取")
    print("=" * 60)
    from config import ensure_local_dirs, get_settings

    cfg = get_settings()
    print(f"  APP_MODE = {cfg.mode}")
    if cfg.mode == "local":
        ok(f"本地模式，SQLite 路径：{cfg.db_path}")
    else:
        ok("云端模式，Supabase 配置已读取")
        if not cfg.supabase_url:
            bad("SUPABASE_URL 为空")
        if not cfg.supabase_key:
            bad("SUPABASE_SERVICE_KEY 为空")
        if not (os.getenv("DATABASE_URL") or "").strip():
            bad("DATABASE_URL 为空（直连查询需要）")
        else:
            ok("DATABASE_URL 已配置")

    ensure_local_dirs(cfg)

    print("=" * 60)
    print(" 3. 数据库连通与表结构")
    print("=" * 60)
    from core import db

    connected, msg = db.ping(cfg)
    if connected:
        ok(msg)
    else:
        bad(f"数据库连接失败：{msg}")
        print("\n  云端常见原因：\n"
              "   · DATABASE_URL 用了 Direct connection 而非 Session pooler\n"
              "   · 密码里有特殊字符没做 URL 编码\n"
              "   · Supabase 项目处于 Pausing 状态")
        return finish()

    # 表结构：先尝试自动初始化（local 模式会建表；cloud 模式只提示）
    need_tables = ["teachers", "classes", "teacher_classes", "students", "eval_tags",
                   "groups", "score_logs", "audit_logs", "class_settings"]
    try:
        db.one("SELECT COUNT(*) AS n FROM teachers", cfg=cfg)
    except Exception:
        if cfg.is_cloud:
            bad("核心表不存在：请到 Supabase SQL Editor 执行 sql/schema_supabase.sql")
        else:
            print("  首次运行，正在自动建表…")
            try:
                print("  " + db.init_db(cfg))
            except Exception as e:
                bad(f"自动建表失败：{e}")

    for t in need_tables:
        try:
            db.one(f"SELECT COUNT(*) AS n FROM {t}", cfg=cfg)
            ok(f"表 {t} 存在")
        except Exception as e:
            bad(f"表 {t} 缺失或不可读：{str(e)[:80]}")

    print("=" * 60)
    print(" 4. 存储与文件")
    print("=" * 60)
    if cfg.is_cloud:
        from core.storage import check_supabase_connection

        sok, smsg = check_supabase_connection(cfg)
        (ok if sok else bad)(smsg)
    else:
        try:
            probe = cfg.upload_dir / ".write_test"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            ok(f"上传目录可写：{cfg.upload_dir}")
        except Exception as e:
            bad(f"上传目录不可写：{e}")

    print("=" * 60)
    print(" 5. Excel 导出能力")
    print("=" * 60)
    try:
        import pandas as pd

        from core import exporter

        df = pd.DataFrame({"a": [1]})
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False)
        data = exporter.export_excel([], "测试班", [], "全部时间", "自检")
        ok(f"Excel 生成正常（空台账 {len(data)} 字节）")
    except Exception as e:
        bad(f"Excel 生成失败：{e}")

    print("=" * 60)
    print(" 6. 目录结构")
    print("=" * 60)
    for p in ["app.py", "Home.py", "pages", "core", "sql/schema_sqlite.sql", "sql/schema_supabase.sql"]:
        (ok if (ROOT / p).exists() else bad)(f"{p} {'存在' if (ROOT / p).exists() else '缺失'}")

    return finish()


def finish() -> int:
    print()
    print("=" * 60)
    print(f" 通过 {len(OK)} 项 · 警告 {len(WARN)} 项 · 失败 {len(BAD)} 项")
    if BAD:
        print(" 请先修复上面的 ✗ 项")
        return 1
    print(" 环境检查通过，可以启动：streamlit run app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
