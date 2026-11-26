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


def key_kind(key: str) -> str:
    """
    判断 Supabase 密钥类型：
      jwt        —— 传统 Service Role Key，形如 eyJhbGci...
      secret     —— 新版 Secret Key，形如 sb_secret_xxxx
      publishable—— 新版 Publishable Key（**不能用于服务端写存储**）
      anon       —— 传统 anon key（不能用于服务端写存储）
      unknown
    """
    k = _clean_key(key)
    if k.startswith("sb_secret_"):
        return "secret"
    if k.startswith("sb_publishable_"):
        return "publishable"
    if k.startswith("eyJ"):
        # 传统 JWT：payload 里含 role 字段，可直接区分 service_role / anon
        return "jwt"
    return "unknown"


def _jwt_role(key: str) -> str:
    """从 JWT payload 里读 role（不解密，只做 base64 解码）"""
    try:
        import base64
        import json

        body = key.split(".")[1]
        body += "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body))
        return str(payload.get("role", ""))
    except Exception:
        return ""


def get_supabase(cfg: Config | None = None):
    """
    获取 Supabase 客户端（延迟创建单例）。

    支持两种服务端密钥：
      · 传统 Service Role Key（JWT，eyJ 开头，role=service_role）
      · 新版 Secret Key（sb_secret_ 开头）

    403 Invalid Compact JWS 的常见原因：
      · SUPABASE_URL 与 KEY 来自不同项目；
      · 贴的是 anon / publishable key，而不是 service_role / secret key；
      · 新版 Secret Key 被当成 JWT 送进 Authorization 头（本项目已特殊处理）。
    """
    global _SB_CLIENT, _SB_CLIENT_KEY
    cfg = cfg or get_settings()
    url = (cfg.supabase_url or "").strip().rstrip("/")
    key = _clean_key(cfg.supabase_key)
    if not url or not key:
        raise RuntimeError(
            "云端模式缺少 SUPABASE_URL / SUPABASE_SERVICE_KEY，请检查 Streamlit Secrets。"
        )

    cache_key = (url, key)
    if _SB_CLIENT is not None and _SB_CLIENT_KEY == cache_key:
        return _SB_CLIENT

    if not url.startswith("https://") or ".supabase.co" not in url:
        raise RuntimeError(f"SUPABASE_URL 格式不对：{url}，应形如 https://xxxx.supabase.co")

    kind = key_kind(key)
    if kind == "publishable":
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY 填的是 Publishable Key（sb_publishable_ 开头），"
            "它只能给浏览器用，服务端写入存储会被拒绝。请改用 Secret Key（sb_secret_）"
            "或传统 Service Role Key（eyJ 开头）。"
        )
    if kind == "jwt":
        role = _jwt_role(key)
        if role and role != "service_role":
            raise RuntimeError(
                f"SUPABASE_SERVICE_KEY 的 role 是「{role}」，不是 service_role。"
                "请到 Supabase → Project Settings → API Keys 复制 service_role 密钥。"
            )
    if kind == "unknown":
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY 格式无法识别。应为：\n"
            "· 新版：sb_secret_ 开头\n"
            "· 传统：eyJ 开头的 Service Role JWT"
        )

    from supabase import create_client  # 延迟导入，本地模式无需安装

    # 新版 Secret Key 不是 JWT，supabase-py 默认会把它塞进
    # `Authorization: Bearer <key>`，存储服务会报 Invalid Compact JWS。
    # 这里显式把两个头都设成该 key，SDK 便不再自行改写 Authorization。
    if kind == "secret":
        _SB_CLIENT = create_client(url, key)
        _force_secret_headers(_SB_CLIENT, key)
    else:
        _SB_CLIENT = create_client(url, key)
    _SB_CLIENT_KEY = cache_key
    return _SB_CLIENT


def _force_secret_headers(client, key: str) -> None:
    """
    新版 Secret Key（sb_secret_...）不是 JWT。
    supabase-py 会把它同时塞进 `apikey` 和 `Authorization: Bearer ...`，
    但两个 header 名大小写不同（apikey / apiKey），httpx 合并后会变成
    "xxx, xxx"，存储服务判定 JWS 非法 → 403 Invalid Compact JWS。

    这里创建完客户端后直接**覆写**底层 httpx 客户端的 headers，
    保证每个头只有一个值。
    """
    auth = f"Bearer {key}"
    targets = []

    # storage 子客户端（图片上传/下载走这里）
    st_obj = getattr(client, "storage", None)
    hx = getattr(st_obj, "_client", None) or getattr(st_obj, "session", None)
    if hx is not None and hasattr(hx, "headers"):
        targets.append(hx)

    # postgrest 子客户端（本项目不直接用，一并处理防止意外）
    rest_obj = getattr(client, "postgrest", None)
    hx2 = getattr(rest_obj, "_client", None)
    if hx2 is not None and hasattr(hx2, "headers"):
        targets.append(hx2)

    for hx in targets:
        try:
            hx.headers.pop("apikey", None)
            hx.headers.pop("apiKey", None)
            hx.headers.pop("authorization", None)
            hx.headers.pop("Authorization", None)
            hx.headers["apikey"] = key
            hx.headers["Authorization"] = auth
        except Exception:
            continue


def check_supabase_connection(cfg: Config | None = None) -> tuple[bool, str]:
    """
    启动自检：确认 key 格式、能连上 Supabase、桶存在、能上传。
    返回 (是否正常, 说明文字)，说明文字里会明确告诉你是哪一环出的问题。
    """
    cfg = cfg or get_settings()
    key = _clean_key(cfg.supabase_key)
    kind = key_kind(key)
    kind_cn = {"secret": "新版 Secret Key", "jwt": "Service Role JWT",
               "publishable": "Publishable Key（不可用于服务端）",
               "unknown": "无法识别的格式"}.get(kind, kind)
    try:
        sb = get_supabase(cfg)
    except Exception as e:
        return False, f"客户端初始化失败（key 类型：{kind_cn}）：{e}"

    try:
        buckets = sb.storage.list_buckets()
    except Exception as e:
        msg = str(e)
        if "Compact JWS" in msg or "Unauthorized" in msg:
            return False, (
                f"鉴权失败（key 类型：{kind_cn}）。常见原因：\n"
                "1) SUPABASE_URL 与 KEY 来自不同项目；\n"
                "2) key 是 anon / publishable，不是 service_role / secret；\n"
                f"原始错误：{msg}"
            )
        return False, f"连接失败（key 类型：{kind_cn}）：{msg}"

    names = [getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None)
             for b in buckets]
    if cfg.bucket not in names:
        return False, (f"连上了（key 类型：{kind_cn}），但找不到存储桶 [{cfg.bucket}]。"
                       f"现有桶：{', '.join(filter(None, names)) or '无'}。"
                       "请到 Supabase → Storage 新建该桶并设为 Public。")
    return True, f"云端模式正常：{kind_cn}，存储桶 [{cfg.bucket}] 就绪。"


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
