"""
core/avatars.py —— 内置 Q 版卡通头像（SVG 程序化生成）
=====================================================
为了避免任何版权风险，这里不使用任何第三方素材，
所有头像都是用 SVG 现场绘制的“Q版茶啊二中风格”扁平卡通：
  - 大头小身比例（头占整体 60%+）
  - 粗描边 + 马卡龙配色
  - 统一校园元素（校服领、发卡、眼镜等）
每个头像都有一个稳定的 key，学生表 avatar_key 存的就是这个 key。
"""

from __future__ import annotations

import base64
from functools import lru_cache

# 皮肤 / 头发 / 背景 配色（低饱和马卡龙，适合初中生）
SKINS = ["#FFE3CC", "#FFD9BC", "#F7CBA8", "#EFC08F"]
HAIRS = ["#2F2F38", "#4A3428", "#20232A", "#5B3A28", "#3B2F2F"]
BG = [
    "#D8F0FF", "#FFE7EE", "#E8FFE0", "#FFF6D6",
    "#F0E6FF", "#DFF7F4", "#FFEEDD", "#E7F0FF",
]

# 头像定义：(key, 名称, 发型, 发色索引, 肤色索引, 背景索引, 配饰)
# 发型：short / bob / twin / spiky / ponytail / curly / straight
#       braid（长辫）/ bun（丸子头）/ bowl（锅盖头）/ wave（微卷长发）
# 配饰：none / glasses / hairclip / cap（棒球帽）/ bow（蝴蝶结）
AVATAR_DEFS: list[tuple[str, str, str, int, int, int, str]] = [
    ("a01", "阳光男孩", "short", 0, 0, 0, "none"),
    ("a02", "文静女孩", "bob", 1, 1, 1, "hairclip"),
    ("a03", "学霸少年", "short", 2, 2, 2, "glasses"),
    ("a04", "双马尾", "twin", 0, 0, 3, "hairclip"),
    ("a05", "运动男孩", "spiky", 3, 1, 4, "none"),
    ("a06", "短发女孩", "bob", 4, 2, 5, "none"),
    ("a07", "马尾女孩", "ponytail", 2, 0, 6, "glasses"),
    ("a08", "卷发男孩", "curly", 1, 3, 7, "none"),
    ("a09", "齐刘海", "straight", 0, 2, 1, "hairclip"),
    ("a10", "黑框眼镜", "short", 4, 0, 2, "glasses"),
    ("a11", "元气少女", "twin", 2, 1, 3, "none"),
    ("a12", "乖乖女", "straight", 1, 2, 0, "none"),
    ("a13", "篮球少年", "spiky", 0, 3, 6, "none"),
    ("a14", "雨靴女孩", "bob", 2, 0, 5, "hairclip"),
    ("a15", "小卷毛", "curly", 3, 1, 4, "glasses"),
    ("a16", "斜刘海", "ponytail", 4, 2, 7, "none"),
    # ---------- 新增 16 款（共 32 款） ----------
    ("a17", "长辫女孩", "braid", 0, 1, 1, "bow"),
    ("a18", "丸子头", "bun", 1, 0, 3, "none"),
    ("a19", "锅盖头", "bowl", 2, 3, 0, "none"),
    ("a20", "微卷长发", "wave", 3, 2, 2, "glasses"),
    ("a21", "棒球帽少年", "short", 4, 1, 6, "cap"),
    ("a22", "双丸子", "twin", 1, 0, 4, "bow"),
    ("a23", "清爽短发", "short", 2, 2, 5, "none"),
    ("a24", "文艺女生", "wave", 0, 1, 7, "hairclip"),
    ("a25", "队长风", "spiky", 3, 2, 0, "cap"),
    ("a26", "低马尾", "ponytail", 1, 3, 2, "none"),
    ("a27", "圆眼镜女孩", "straight", 4, 0, 4, "glasses"),
    ("a28", "卷毛小生", "curly", 2, 1, 6, "none"),
    ("a29", "蝴蝶结少女", "braid", 3, 2, 3, "bow"),
    ("a30", "平头少年", "bowl", 0, 3, 7, "none"),
    ("a31", "运动女生", "twin", 4, 1, 5, "hairclip"),
    ("a32", "安静男生", "short", 1, 0, 1, "glasses"),
]

AVATAR_KEYS = [d[0] for d in AVATAR_DEFS]
AVATAR_NAMES = {d[0]: d[1] for d in AVATAR_DEFS}


def _hair_back(style: str, color: str) -> str:
    """后脑勺头发（画在脸后面）"""
    if style == "twin":
        return (
            f'<ellipse cx="26" cy="46" rx="11" ry="15" fill="{color}"/>'
            f'<ellipse cx="102" cy="46" rx="11" ry="15" fill="{color}"/>'
        )
    if style == "ponytail":
        return f'<ellipse cx="104" cy="52" rx="12" ry="18" fill="{color}" transform="rotate(18 104 52)"/>'
    if style == "braid":
        return (
            f'<path d="M20 58 Q22 20 64 20 Q106 20 108 58 L108 104 Q96 96 88 104 Q80 96 64 104 '
            f'Q48 96 40 104 Q32 96 20 104 Z" fill="{color}"/>'
        )
    if style == "bun":
        return (
            f'<circle cx="64" cy="18" r="14" fill="{color}"/>'
            f'<path d="M20 58 Q22 22 64 22 Q106 22 108 58 L108 74 Q94 62 64 62 Q34 62 20 74 Z" fill="{color}"/>'
        )
    if style == "wave":
        return (
            f'<path d="M18 60 Q18 18 64 18 Q110 18 110 60 L110 96 '
            f'Q100 88 94 96 Q88 88 80 96 Q72 88 64 96 Q56 88 48 96 Q40 88 34 96 Q28 88 18 96 Z" fill="{color}"/>'
        )
    if style == "bob":
        return f'<path d="M18 62 Q20 20 64 20 Q108 20 110 62 L110 78 Q96 64 64 64 Q32 64 18 78 Z" fill="{color}"/>'
    if style == "curly":
        return (
            f'<circle cx="30" cy="40" r="13" fill="{color}"/><circle cx="98" cy="40" r="13" fill="{color}"/>'
            f'<circle cx="40" cy="26" r="12" fill="{color}"/><circle cx="88" cy="26" r="12" fill="{color}"/>'
            f'<circle cx="64" cy="22" r="14" fill="{color}"/>'
        )
    return ""


def _hair_front(style: str, color: str) -> str:
    """刘海 / 前额头发"""
    if style == "spiky":
        return (
            f'<path d="M22 52 L30 26 L42 44 L52 20 L66 42 L78 20 L88 44 L100 28 L106 54 '
            f'Q64 34 22 52 Z" fill="{color}"/>'
        )
    if style == "straight":
        return f'<path d="M20 56 Q22 22 64 22 Q106 22 108 56 L100 56 Q96 40 64 40 Q32 40 28 56 Z" fill="{color}"/>'
    if style == "bob":
        return f'<path d="M22 54 Q26 24 64 24 Q102 24 106 54 Q88 42 64 42 Q40 42 22 54 Z" fill="{color}"/>'
    if style in {"twin", "ponytail"}:
        return f'<path d="M22 56 Q24 22 64 22 Q104 22 106 56 Q84 38 64 38 Q44 38 22 56 Z" fill="{color}"/>'
    if style == "curly":
        return f'<path d="M26 50 Q34 22 64 22 Q94 22 102 50 Q84 40 64 40 Q44 40 26 50 Z" fill="{color}"/>'
    if style == "braid":
        return f'<path d="M24 56 Q26 22 64 22 Q102 22 104 56 Q86 38 64 38 Q42 38 24 56 Z" fill="{color}"/>'
    if style == "bun":
        return f'<path d="M26 52 Q34 24 64 24 Q94 24 102 52 Q84 40 64 40 Q44 40 26 52 Z" fill="{color}"/>'
    if style == "wave":
        return (
            f'<path d="M22 56 Q24 22 64 22 Q104 22 106 56 Q96 44 86 50 Q76 38 64 46 '
            f'Q52 36 42 48 Q30 44 22 56 Z" fill="{color}"/>'
        )
    if style == "bowl":
        return f'<path d="M20 58 Q22 20 64 20 Q106 20 108 58 L100 58 Q96 32 64 32 Q32 32 28 58 Z" fill="{color}"/>'
    # short
    return f'<path d="M22 52 Q24 24 64 24 Q104 24 106 52 Q86 36 64 36 Q42 36 22 52 Z" fill="{color}"/>'


@lru_cache(maxsize=64)
def avatar_svg(key: str) -> str:
    """根据 key 生成完整 SVG 字符串（带缓存）"""
    item = next((d for d in AVATAR_DEFS if d[0] == key), AVATAR_DEFS[0])
    _, _, style, hi, si, bi, acc = item
    hair = HAIRS[hi % len(HAIRS)]
    skin = SKINS[si % len(SKINS)]
    bg = BG[bi % len(BG)]

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">',
        f'<rect width="128" height="128" rx="26" fill="{bg}"/>',
        # 背景装饰小圆点
        f'<circle cx="108" cy="22" r="7" fill="#FFFFFF" opacity="0.55"/>',
        f'<circle cx="20" cy="102" r="9" fill="#FFFFFF" opacity="0.4"/>',
        # 身体（校服）
        '<path d="M28 128 Q30 96 64 92 Q98 96 100 128 Z" fill="#FFFFFF"/>',
        '<path d="M28 128 Q30 96 64 92 Q98 96 100 128 Z" fill="none" stroke="#3A3A46" stroke-width="4"/>',
        # 领口
        '<path d="M52 96 L64 112 L76 96 L70 92 L58 92 Z" fill="#5DA9F0"/>',
        _hair_back(style, hair),
        # 脸
        f'<ellipse cx="64" cy="62" rx="40" ry="38" fill="{skin}" stroke="#3A3A46" stroke-width="4"/>',
        # 耳朵
        f'<circle cx="24" cy="64" r="6" fill="{skin}" stroke="#3A3A46" stroke-width="3"/>',
        f'<circle cx="104" cy="64" r="6" fill="{skin}" stroke="#3A3A46" stroke-width="3"/>',
        _hair_front(style, hair),
        # 眉毛
        '<path d="M44 54 q6 -5 12 -1" stroke="#3A3A46" stroke-width="3.2" fill="none" stroke-linecap="round"/>',
        '<path d="M72 53 q6 -4 12 1" stroke="#3A3A46" stroke-width="3.2" fill="none" stroke-linecap="round"/>',
        # 眼睛（高光）
        '<ellipse cx="49" cy="66" rx="5.4" ry="6.4" fill="#2B2B33"/>',
        '<ellipse cx="79" cy="66" rx="5.4" ry="6.4" fill="#2B2B33"/>',
        '<circle cx="50.8" cy="63.6" r="1.9" fill="#FFFFFF"/>',
        '<circle cx="80.8" cy="63.6" r="1.9" fill="#FFFFFF"/>',
        # 腮红
        '<ellipse cx="38" cy="78" rx="6" ry="3.6" fill="#FF9AA8" opacity="0.55"/>',
        '<ellipse cx="90" cy="78" rx="6" ry="3.6" fill="#FF9AA8" opacity="0.55"/>',
        # 嘴
        '<path d="M58 80 q6 7 12 0" stroke="#3A3A46" stroke-width="3.2" fill="none" stroke-linecap="round"/>',
    ]

    if acc == "glasses":
        parts.append(
            '<circle cx="49" cy="66" r="11" fill="none" stroke="#3A3A46" stroke-width="3"/>'
            '<circle cx="79" cy="66" r="11" fill="none" stroke="#3A3A46" stroke-width="3"/>'
            '<path d="M60 66 h8" stroke="#3A3A46" stroke-width="3"/>'
        )
    elif acc == "hairclip":
        parts.append(
            '<path d="M92 34 l10 -6 l2 8 z" fill="#FF7A9A"/><circle cx="94" cy="32" r="3" fill="#FFD1DC"/>'
        )
    elif acc == "bow":
        parts.append(
            '<g transform="translate(88,30) rotate(12)">'
            '<path d="M0 0 L-12 -7 L-12 7 Z" fill="#FF7A9A"/>'
            '<path d="M0 0 L12 -7 L12 7 Z" fill="#FF7A9A"/>'
            '<circle cx="0" cy="0" r="3.4" fill="#FFB3C6"/></g>'
        )
    elif acc == "cap":
        parts.append(
            '<g transform="translate(0,-6)">'
            '<path d="M20 50 Q22 18 64 18 Q106 18 108 50 Z" fill="#3F6BD6" stroke="#2E4FA8" stroke-width="3"/>'
            '<path d="M104 46 Q122 50 118 58 L104 58 Z" fill="#2E4FA8"/>'
            '<circle cx="64" cy="20" r="4" fill="#FFFFFF" opacity="0.85"/></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


def avatar_data_uri(key: str) -> str:
    """返回可直接放进 <img src> 的 data URI"""
    svg = avatar_svg(key)
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def default_avatar_for_index(index: int) -> str:
    """按录入顺序循环分配预设头像"""
    return AVATAR_KEYS[index % len(AVATAR_KEYS)]
