"""
core/storage.py —— 图片存储抽象层
=====================================
local 模式：保存到 data/uploads/...，返回相对路径，由 pages 通过 file:// 或 base64 展示
cloud 模式：上传到 Supabase Storage 桶，返回公开 URL

业务层只调用 upload_image() / delete_image()，两种模式无缝切换。
"""

from __future__ import annotations

import datetime as dt
import io
import mimetypes
import uuid

from config import Config, ensure_local_dirs, get_settings
from core.security import safe_filename

_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def _ext(filename: str, fallback: str = "png") -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return ext if ext in _MIME else fallback


def _guess_mime(filename: str) -> str:
    return _MIME.get(_ext(filename), mimetypes.guess_type(filename)[0] or "application/octet-stream")


# ---------------------------------------------------------------------------
# Supabase 客户端（懒加载 + 进程内缓存）
# ---------------------------------------------------------------------------
_SB_CLIENT = None
_SB_CLIENT_KEY = None


def _clean_key(raw: str) -> str:
    """清理密钥：去掉首尾空格、误加的引号、误加的 'Bearer ' 前缀"""
    k = (raw or "").strip().strip('"').strip("'")
    if k.lower().startswith("bearer "):
        k = k[7:].strip()
    return k


def get_supabase(cfg: Config | None = None):
    """
    获取 Supabase 客户端（延迟创建单例）。

    403 Invalid Compact JWS 的常见原因就是这里的两个值不匹配：
      · SUPABASE_URL 与 SUPABASE_SERVICE_KEY 来自**不同的项目**；
      · 或者 SERVICE_KEY 贴的是 anon key / publishable key，而不是
        Project Settings → API Keys 里的 service_role（JWT 形如 eyJhbGci...）。
    """
    global _SB_CLIENT, _SB_CLIENT_KEY
    cfg = cfg or get_settings()
    url = (cfg.supabase_url or "").strip().rstrip("/")
    key = _clean_key(cfg.supabase_key)
    if not url or not key:
        raise RuntimeError(
            "云端模式缺少 SUPABASE_URL / SUPABASE_SERVICE_KEY，请检查 Streamlit Secrets。"
        )
    # 配置变了就重建客户端
    cache_key = (url, key)
    if _SB_CLIENT is not None and _SB_CLIENT_KEY == cache_key:
        return _SB_CLIENT
    if not url.startswith("https://") or ".supabase.co" not in url:
        raise RuntimeError(f"SUPABASE_URL 格式不对：{url}，应形如 https://xxxx.supabase.co")
    if not key.startswith("eyJ"):
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY 不是 JWT（应以 eyJ 开头）。"
            "请到 Supabase → Project Settings → API Keys 复制 service_role 密钥，"
            "不要用 anon / publishable key。"
        )
    from supabase import create_client  # 延迟导入，本地模式无需安装

    _SB_CLIENT = create_client(url, key)
    _SB_CLIENT_KEY = cache_key
    return _SB_CLIENT


def check_supabase_connection(cfg: Config | None = None) -> tuple[bool, str]:
    """启动自检：确认能连上 Supabase 且桶存在"""
    cfg = cfg or get_settings()
    try:
        sb = get_supabase(cfg)
        buckets = sb.storage.list_buckets()
        names = [getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None) for b in buckets]
        if cfg.bucket not in names:
            return False, f"已连接 Supabase，但找不到存储桶 [{cfg.bucket}]，请先在 Storage 中创建。"
        return True, f"云端模式：Supabase 连接正常，存储桶 [{cfg.bucket}] 就绪。"
    except Exception as e:  # pragma: no cover - 依赖网络
        return False, f"Supabase 连接失败：{e}"


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def upload_image(
    file_bytes: bytes,
    filename: str,
    prefix: str = "score",
    cfg: Config | None = None,
) -> str:
    """
    上传图片，返回可持久化的引用：
      local → "uploads/score/20261122/xxxx.png"（相对 data 目录）
      cloud → Supabase 公开 URL
    """
    cfg = cfg or get_settings()
    ext = _ext(filename)
    today = dt.datetime.now().strftime("%Y%m%d")
    object_name = f"{prefix}/{today}/{uuid.uuid4().hex[:12]}_{safe_filename(filename)[:40]}"
    if not object_name.lower().endswith("." + ext):
        object_name += "." + ext

    if cfg.is_cloud:
        sb = get_supabase(cfg)
        # upsert=False：文件名带 uuid，不会冲突
        sb.storage.from_(cfg.bucket).upload(
            path=object_name,
            file=file_bytes,
            file_options={"content-type": _guess_mime(filename), "upsert": "false"},
        )
        return sb.storage.from_(cfg.bucket).get_public_url(object_name)

    # local
    ensure_local_dirs(cfg)
    target = cfg.upload_dir / object_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file_bytes)
    # 统一存相对 data/ 的路径，方便迁移
    return f"uploads/{object_name}"


def resolve_local_path(ref: str, cfg: Config | None = None):
    """local 模式下把引用转成绝对路径（cloud 模式或 http 链接返回 None）"""
    if not ref or ref.startswith("http"):
        return None
    cfg = cfg or get_settings()
    base = cfg.upload_dir.parent  # data/
    return base / ref.replace("\\", "/")


def read_image_bytes(ref: str, cfg: Config | None = None) -> bytes | None:
    """读取图片二进制（用于 st.image 展示与 Excel 嵌入）"""
    if not ref:
        return None
    cfg = cfg or get_settings()
    if ref.startswith("http"):
        try:
            import urllib.request

            with urllib.request.urlopen(ref, timeout=8) as resp:
                return resp.read()
        except Exception:
            return None
    path = resolve_local_path(ref, cfg)
    try:
        if path and path.exists():
            return path.read_bytes()
    except Exception:
        return None
    return None


def delete_image(ref: str, cfg: Config | None = None) -> None:
    """删除图片（撤回图片或更换头像时调用；失败不阻断主流程）"""
    if not ref:
        return
    cfg = cfg or get_settings()
    try:
        if ref.startswith("http"):
            sb = get_supabase(cfg)
            marker = f"/object/public/{cfg.bucket}/"
            if marker in ref:
                object_name = ref.split(marker, 1)[1].split("?")[0]
                sb.storage.from_(cfg.bucket).remove([object_name])
            return
        path = resolve_local_path(ref, cfg)
        if path and path.exists():
            path.unlink()
    except Exception:
        pass


def image_bytes_io(ref: str) -> io.BytesIO | None:
    data = read_image_bytes(ref)
    if data is None:
        return None
    buf = io.BytesIO(data)
    buf.seek(0)
    return buf
