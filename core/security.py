"""
core/security.py —— 密码哈希 / 令牌签名 / 随机 ID
=====================================
不依赖 bcrypt，使用标准库 hashlib.pbkdf2_hmac，避免部署时的编译问题。
格式：pbkdf2_sha256$<迭代次数>$<盐hex>$<摘要hex>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid

from config import get_settings

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000
_FALLBACK_KEY: bytes | None = None


def hash_password(password: str) -> str:
    """生成密码哈希"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码（使用恒定时间比较，防时序攻击）"""
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 孩子查看令牌：家长登录后只允许查看自己孩子，
# 用 HMAC 把 student_id 绑定进 session，篡改即失效。
# ---------------------------------------------------------------------------
def _secret_key() -> bytes:
    """签名密钥：优先 APP_SECRET_KEY（云端放 Secrets），否则用进程内随机值"""
    global _FALLBACK_KEY
    raw = (os.getenv("APP_SECRET_KEY") or "").strip()
    if raw:
        return raw.encode("utf-8")
    if not raw:
        try:
            raw = str(get_settings().extra.get("APP_SECRET_KEY", "") or "")
        except Exception:
            raw = ""
    if raw:
        return raw.encode("utf-8")
    if _FALLBACK_KEY is None:
        _FALLBACK_KEY = secrets.token_bytes(32)
    return _FALLBACK_KEY


def sign_child_token(student_id: str) -> str:
    sig = hmac.new(_secret_key(), student_id.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def verify_child_token(student_id: str, token: str) -> bool:
    try:
        return hmac.compare_digest(sign_child_token(student_id), (token or "").strip())
    except Exception:
        return False


def random_code(length: int = 4) -> str:
    """生成家长查看码（纯数字，避开易混淆的 0/1）"""
    alphabet = "23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def new_id() -> str:
    """统一主键生成：服务端生成 UUID，SQLite 与 PostgreSQL 都使用 TEXT/uuid 存储"""
    return str(uuid.uuid4())


def safe_filename(name: str) -> str:
    """过滤文件名中的危险字符，保留中文"""
    keep = "-_.()"
    cleaned = "".join(
        c for c in name if c.isalnum() or c in keep or "\u4e00" <= c <= "\u9fff"
    )
    return cleaned.strip().replace(" ", "_") or "file"
