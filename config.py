"""
config.py —— 全局配置
=====================================
通过环境变量 APP_MODE 区分两种运行模式：
  local : 本地开发，SQLite + 本地文件系统（.env）
  cloud : 云端部署，Supabase PostgreSQL + Supabase Storage（Streamlit Secrets）

业务代码只依赖 `get_settings()` 返回的 Config 对象，不关心底层是哪种模式，
所以切换模式不需要改动任何业务逻辑。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
SQL_DIR = BASE_DIR / "sql"

# 允许上传的图片后缀与大小上限
ALLOWED_IMAGE_TYPES = ["png", "jpg", "jpeg", "webp"]
MAX_UPLOAD_MB = 5

# 评价分值范围（防止误输入）
SCORE_MIN, SCORE_MAX = -100, 100


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Config:
    """运行配置（只读）"""

    mode: str = "local"                     # local / cloud
    db_path: Path = DATA_DIR / "app.db"     # local 模式的 SQLite 文件
    supabase_url: str = ""
    supabase_key: str = ""                  # service_role key（仅服务端使用）
    bucket: str = "class-eval"              # Supabase Storage 桶名
    upload_dir: Path = UPLOAD_DIR           # local 模式的上传目录
    default_admin_user: str = "admin"
    # 首次启动生成的默认密码；强烈建议在 .env / Secrets 里覆盖
    default_admin_password: str = "pass1234"
    allow_teacher_signup: bool = True
    show_rank_default: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_cloud(self) -> bool:
        return self.mode == "cloud"


def _read_env_file() -> dict[str, str]:
    """读取本地 .env（不覆盖已存在的真实环境变量）"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return {}
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except Exception:  # python-dotenv 未安装时退化为手工解析
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return dict(os.environ)


def _load_secrets() -> Mapping[str, Any]:
    """读取 Streamlit Secrets（云端；本地若没有 secrets.toml 则返回空）"""
    try:
        import streamlit as st

        return st.secrets  # 类型：Mapping
    except Exception:
        return {}


def get_settings() -> Config:
    """
    组装最终配置。优先级：真实环境变量 > .env > Streamlit Secrets > 默认值。
    Streamlit Cloud 部署时把变量写进 Secrets，本地写 .env，两边代码完全一致。
    """
    _read_env_file()
    secrets = _load_secrets()
    try:
        secrets = dict(secrets)
    except Exception:
        secrets = {}

    def pick(key: str, default: Any = "") -> Any:
        v = os.getenv(key)
        if v not in (None, ""):
            return v
        sv = secrets.get(key)
        return sv if sv not in (None, "") else default

    mode = str(pick("APP_MODE", "local")).strip().lower()
    if mode not in {"local", "cloud"}:
        mode = "local"

    cfg = Config(
        mode=mode,
        db_path=Path(os.getenv("SQLITE_PATH") or DATA_DIR / "app.db"),
        supabase_url=str(pick("SUPABASE_URL", "")).strip(),
        supabase_key=str(pick("SUPABASE_SERVICE_KEY", "")).strip(),
        bucket=str(pick("SUPABASE_BUCKET", "class-eval")).strip(),
        upload_dir=Path(os.getenv("UPLOAD_DIR") or UPLOAD_DIR),
        default_admin_user=str(pick("DEFAULT_ADMIN_USER", "admin")),
        default_admin_password=str(pick("DEFAULT_ADMIN_PASSWORD", "pass1234")),
        allow_teacher_signup=_as_bool(pick("ALLOW_TEACHER_SIGNUP", "true"), True),
        show_rank_default=_as_bool(pick("SHOW_RANK_DEFAULT", "true"), True),
    )
    return cfg


def ensure_local_dirs(cfg: Config) -> None:
    """本地模式准备目录"""
    if not cfg.is_cloud:
        cfg.upload_dir.mkdir(parents=True, exist_ok=True)
        cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
