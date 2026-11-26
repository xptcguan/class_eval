"""
core/ui.py —— 视觉系统 / 通用组件 / 音效
=====================================================
视觉规范（校园简约风，干净稳重）
  · 主色   靛蓝 #3F6BD6
  · 加分   #12A150（绿）    扣分  #E8590C（橙红）
  · 底纹   #F6F7FB 浅灰蓝，卡片纯白 + 12px 圆角 + 极轻阴影
  · 文字   主 #1F2430 / 次 #6B7280 / 弱 #9AA3AF
  · 图标   Material Symbols 线性图标（Streamlit 内置）
  · 交互   触屏加大点击区；≤1024px 自动收紧留白（平板）

组件
  role_text()          「科任老师」→「语文老师」
  student_card_html()  学生卡（名次、组内排名、前三特效）
  group_card_html()    小组卡（投屏小组视图，含人不含照片）
  dashboard()          仪表盘卡片组
  empty_state()        空状态
  flash()/show_flash() 轻提示（toast）
  play_sound()         Web Audio 合成音，仅教师端打分后播放
"""

from __future__ import annotations

import base64
import html as _html

import streamlit as st

from core import avatars

BIG_SCREEN_KEY = "big_screen_mode"

C_PLUS = "#12A150"
C_MINUS = "#E8590C"
C_MUTED = "#9AA3AF"


# ===========================================================================
# 样式
# ===========================================================================
CSS = """
<style>
:root{
  --primary:#3F6BD6; --primary-soft:#EEF3FE;
  --plus:#12A150; --plus-soft:#E9F8EF;
  --minus:#E8590C; --minus-soft:#FFF1E7;
  --ink:#1F2430; --sub:#6B7280; --muted:#9AA3AF;
  --line:#E6E9F0; --bg:#F6F7FB;
}

.stApp{ background:var(--bg); }
html, body, [class*="css"]{
  font-family:"PingFang SC","Microsoft YaHei","Hiragino Sans GB","Segoe UI",sans-serif;
  color:var(--ink);
}
h1,h2,h3{ color:var(--ink) !important; letter-spacing:.2px; font-weight:700; }
#MainMenu, footer{ visibility:hidden; }
header[data-testid="stHeader"]{ background:transparent; height:0; }
.block-container{ padding-top:1.5rem; padding-bottom:3rem; max-width:1320px; }

.ce-card{
  background:#fff; border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; box-shadow:0 1px 2px rgba(16,24,40,.04); margin-bottom:14px;
}
.ce-title{ font-size:16.5px; font-weight:700; color:var(--ink); margin:0 0 4px; }
.ce-sub{ font-size:13px; color:var(--sub); line-height:1.7; }

.page-head{ display:flex; align-items:flex-end; gap:12px; margin:0 0 14px; flex-wrap:wrap; }
.page-title{ font-size:23px; font-weight:700; color:var(--ink); line-height:1.3; }
.page-sub{ font-size:13px; color:var(--sub); margin-top:2px; }
.head-chip{
  font-size:12.5px; color:var(--primary); background:var(--primary-soft);
  border-radius:999px; padding:4px 12px; font-weight:600;
}

/* 按钮 */
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button{
  border-radius:10px !important; border:1px solid var(--line) !important;
  font-weight:600 !important; box-shadow:none !important; background:#fff;
  color:var(--ink) !important; transition:all .15s ease; min-height:38px;
}
.stButton>button:hover, .stDownloadButton>button:hover{
  border-color:var(--primary) !important; color:var(--primary) !important;
  background:var(--primary-soft) !important;
}
.stButton>button[kind="primary"], .stFormSubmitButton>button[kind="primary"]{
  background:var(--primary) !important; color:#fff !important; border-color:var(--primary) !important;
}
.stButton>button[kind="primary"]:hover{ background:#335BC0 !important; color:#fff !important; }
div[data-testid="stForm"]{ border:none; padding:0; }

/* 侧边栏按钮：整行左对齐 */
section[data-testid="stSidebar"] .stButton>button{
  justify-content:flex-start; text-align:left; border:none !important;
  background:transparent !important; padding:8px 12px; min-height:40px; font-weight:600;
  color:var(--ink) !important;
}
section[data-testid="stSidebar"] .stButton>button:hover{
  background:var(--primary-soft) !important; color:var(--primary) !important;
}
section[data-testid="stSidebar"] .stButton>button[kind="primary"]{
  background:var(--primary) !important; color:#fff !important;
}
section[data-testid="stSidebar"] .stButton>button [data-testid="stIconMaterial"]{
  font-size:19px;
}

/* 侧边栏 */
section[data-testid="stSidebar"]{ background:#fff; border-right:1px solid var(--line); }
.sb-brand{ display:flex; align-items:center; gap:9px; padding:2px 6px 14px;
  font-size:17px; font-weight:700; color:var(--ink); }
.sb-brand-icon{ font-size:21px; }
.sb-user{ display:flex; align-items:center; justify-content:space-between;
  padding:8px 12px; background:var(--bg); border-radius:10px; margin-bottom:10px; font-size:13px; }
.sb-user b{ font-size:14px; }
.sb-user span{ color:var(--sub); }
.sb-class{ padding:10px 12px; border:1px solid var(--line); border-radius:10px; margin-bottom:6px; }
.sb-class-name{ font-weight:700; font-size:14px; margin-bottom:6px; }
.sb-role{ display:inline-block; font-size:12px; padding:1px 10px; border-radius:999px; font-weight:600; }
.sb-role.head{ background:#FFF6E5; color:#B7791F; }
.sb-role.subject{ background:var(--primary-soft); color:var(--primary); }
.sb-group{ font-size:11.5px; color:var(--muted); font-weight:700; letter-spacing:.5px;
  padding:12px 12px 2px; }
.sb-divider{ border-top:1px solid var(--line); margin:10px 4px; }
.sb-hint{ font-size:12.5px; color:var(--muted); padding:6px 12px; line-height:1.6; }


/* ===== 侧边栏：班级优化大师风格 ===== */
section[data-testid="stSidebar"] .stButton>button{
  gap:10px; border-radius:10px !important; font-size:14.5px; letter-spacing:.2px;
}
section[data-testid="stSidebar"] .stButton>button [data-testid="stIconMaterial"]{
  font-size:20px; opacity:.9;
}
section[data-testid="stSidebar"] .stButton>button[kind="primary"] [data-testid="stIconMaterial"]{
  opacity:1;
}
/* 分组标题：更淡更小，像分寸感的分隔 */
.sb-group{
  font-size:11px; color:#A7AEBB; font-weight:600; letter-spacing:1.2px;
  padding:14px 12px 5px; border-top:1px solid #F0F2F6; margin-top:4px;
}
.sb-group:first-of-type{ border-top:none; margin-top:0; }
/* 用户区：只留姓名，右对齐小字 */
.sb-user{
  display:flex; align-items:center; padding:9px 12px; background:#F6F7FB;
  border-radius:10px; margin-bottom:10px; font-size:14px; font-weight:600;
}
.sb-brand{
  font-size:18px; font-weight:800; letter-spacing:.5px;
  padding:2px 8px 16px;
}

/* 侧边栏收起态：只留图标 */
section[data-testid="stSidebar"][aria-expanded="false"]{ min-width:3.6rem !important; width:3.6rem !important; }
section[data-testid="stSidebar"][aria-expanded="false"] .sb-brand-text,
section[data-testid="stSidebar"][aria-expanded="false"] .sb-user,
section[data-testid="stSidebar"][aria-expanded="false"] .sb-class,
section[data-testid="stSidebar"][aria-expanded="false"] .sb-group,
section[data-testid="stSidebar"][aria-expanded="false"] .sb-divider,
section[data-testid="stSidebar"][aria-expanded="false"] .sb-hint,
section[data-testid="stSidebar"][aria-expanded="false"] .stSelectbox{ display:none !important; }
section[data-testid="stSidebar"][aria-expanded="false"] .stButton>button{ justify-content:center; padding:10px 0; }
section[data-testid="stSidebar"][aria-expanded="false"] .stButton>button p{ display:none !important; }
section[data-testid="stSidebar"][aria-expanded="false"] .sb-brand{ justify-content:center; }

/* 仪表盘 */
.dash-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:14px; }
.dash-card{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 16px;
  box-shadow:0 1px 2px rgba(16,24,40,.04); }
.dash-label{ font-size:12.5px; color:var(--sub); }
.dash-value{ font-size:25px; font-weight:700; color:var(--ink); margin-top:3px; line-height:1.25; }
.dash-hint{ font-size:12px; color:var(--muted); margin-top:2px; }

/* 学生卡 */
.student-card{ position:relative; background:#fff; border:1px solid var(--line); border-radius:12px;
  padding:14px 10px 12px; text-align:center; box-shadow:0 1px 2px rgba(16,24,40,.04);
  transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease; }
.student-card:hover{ transform:translateY(-2px); box-shadow:0 6px 16px rgba(16,24,40,.09); border-color:#CBD5E1; }
.student-card img{ border-radius:50%; background:var(--bg); display:inline-block; }
.s-name{ font-weight:700; font-size:14.5px; margin-top:7px; color:var(--ink); }
.s-group{ font-size:11.5px; color:var(--muted); margin-top:1px; }
.s-score{ font-size:20px; font-weight:800; margin-top:3px; letter-spacing:-.2px; }
.score-plus{ color:var(--plus); }
.score-minus{ color:var(--minus); }
.score-zero{ color:var(--muted); }
.s-meta{ font-size:11px; color:var(--muted); margin-top:2px; }

/* 卡片网格：响应式 CSS Grid（PC/平板/大屏自适应，不依赖 st.columns） */
.rank-grid{ display:grid; gap:12px; margin-bottom:14px; }
.rank-cell{ min-width:0; }
@media (max-width:1180px){ .rank-grid{ grid-template-columns:repeat(4,minmax(0,1fr)) !important; } }
@media (max-width:860px){ .rank-grid{ grid-template-columns:repeat(3,minmax(0,1fr)) !important; } }
@media (max-width:620px){ .rank-grid{ grid-template-columns:repeat(2,minmax(0,1fr)) !important; } }
body.bigscreen .rank-grid{ grid-template-columns:repeat(auto-fill,minmax(150px,1fr)) !important; gap:16px; }

/* 名次徽章 */
.rank-badge{ position:absolute; top:8px; left:8px; min-width:22px; padding:1px 7px;
  border-radius:999px; font-size:11.5px; font-weight:700; color:#fff; background:#B4BCC8; }.rank-1{ background:linear-gradient(135deg,#F6C445,#E8A317); }
.rank-2{ background:linear-gradient(135deg,#C3CBD6,#96A1AF); }
.rank-3{ background:linear-gradient(135deg,#E0A46B,#C4834B); }
.grp-rank{ position:absolute; top:8px; right:8px; font-size:10.5px; color:var(--sub);
  background:var(--bg); border-radius:999px; padding:1px 7px; font-weight:600; }

/* 前三名特效 */
.card-top1,.card-top2,.card-top3{ border-width:2px; }
.card-top1{ border-color:#F0C14B; box-shadow:0 0 0 3px rgba(232,163,23,.12), 0 4px 14px rgba(232,163,23,.22); }
.card-top2{ border-color:#C3CBD6; box-shadow:0 0 0 3px rgba(154,163,175,.14), 0 4px 12px rgba(154,163,175,.18); }
.card-top3{ border-color:#DFA474; box-shadow:0 0 0 3px rgba(196,131,75,.14), 0 4px 12px rgba(196,131,75,.18); }
.medal{ position:absolute; top:-12px; right:-6px; font-size:21px; line-height:1;
  filter:drop-shadow(0 2px 3px rgba(0,0,0,.16)); }
@keyframes championshine{ 0%{ background-position:-120% 0; } 100%{ background-position:220% 0; } }
.card-top1::after{ content:""; position:absolute; inset:0; border-radius:12px; pointer-events:none;
  background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.55) 46%,transparent 62%);
  background-size:220% 100%; animation:championshine 3.2s ease-in-out infinite; }

/* 徽章 */
.tag-pill{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px;
  border:1px solid var(--line); margin:2px 4px 2px 0; background:#fff; color:var(--sub);
  font-weight:600; vertical-align:middle; }
.chip-plus{ background:var(--plus-soft); border-color:#BFE7CE; color:#0E7C3F; }
.chip-minus{ background:var(--minus-soft); border-color:#FBD3B6; color:#B4450A; }
.tag-icon-img{ width:18px; height:18px; object-fit:cover; border-radius:4px;
  vertical-align:-4px; margin-right:4px; }

/* 评价记录行 */
.log-row{ display:flex; align-items:center; gap:12px; padding:11px 14px; background:#fff;
  border:1px solid var(--line); border-radius:10px; margin-bottom:8px; }
.log-main{ flex:1; min-width:0; }
.log-title{ font-size:14px; font-weight:600; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.log-sub{ font-size:12.5px; color:var(--sub); margin-top:3px; }
.log-dim{ color:var(--muted); }
.strike{ text-decoration:line-through; opacity:.55; }

/* 空状态 */
.empty{ text-align:center; padding:44px 16px; background:#fff; border:1px dashed #D6DBE4;
  border-radius:12px; margin:8px 0 14px; }
.empty-icon{ font-size:38px; }
.empty-title{ font-size:16px; font-weight:700; margin-top:8px; }
.empty-sub{ font-size:13px; color:var(--sub); margin-top:6px; line-height:1.7; }

/* 登录页 */
.login-h1{ font-size:29px; font-weight:800; letter-spacing:1px; margin-top:8px; color:var(--ink); }
.role-row{ display:flex; gap:10px; padding:9px 0; border-bottom:1px dashed var(--line); font-size:13.5px; }
.role-row:last-of-type{ border-bottom:none; }
.role-row b{ width:76px; flex:none; }
.role-row span{ color:var(--sub); }

[data-testid="stDataFrame"]{ border-radius:10px; overflow:hidden; border:1px solid var(--line); }
.stTabs [data-baseweb="tab-list"]{ gap:4px; border-bottom:1px solid var(--line); }
.stTabs [data-baseweb="tab"]{ border-radius:8px 8px 0 0; padding:7px 15px; font-weight:600; color:var(--sub); }
.stTabs [aria-selected="true"]{ color:var(--primary) !important; }

/* 右下角悬浮快速评分 */
div[data-testid="stPopover"]{ position:fixed !important; right:26px; bottom:26px; z-index:999; }
div[data-testid="stPopover"] > button{
  background:var(--primary) !important; color:#fff !important; border:none !important;
  border-radius:999px !important; padding:11px 20px !important; font-weight:700 !important;
  box-shadow:0 8px 22px rgba(63,107,214,.38) !important; min-height:44px;
}
div[data-testid="stPopover"] > button:hover{ background:#335BC0 !important; color:#fff !important; }
.qs-title{ font-size:15px; font-weight:700; margin-bottom:6px; }

/* 投屏 */
body.bigscreen .block-container{ padding-top:1rem; max-width:100% !important; }
body.bigscreen .s-name{ font-size:19px; }
body.bigscreen .s-score{ font-size:27px; }
body.bigscreen .student-card{ border-width:2px; padding:18px 12px 14px; }
body.bigscreen .page-title{ font-size:30px; }
body.bigscreen .grp-card{ padding:26px 18px; }
.grp-name{ font-size:19px; font-weight:800; }
.grp-score{ font-size:32px; font-weight:800; letter-spacing:-1px; }
.grp-meta{ font-size:12.5px; color:var(--sub); margin-top:4px; }

/* 平板 / 小屏 */

/* 本周之星：呼吸光晕 + 扫光 */
.dash-shine{ position:relative; overflow:hidden; border-color:#F0C14B;
  box-shadow:0 0 0 3px rgba(232,163,23,.14), 0 4px 16px rgba(232,163,23,.20);
  animation:dashGlow 2.4s ease-in-out infinite; }
@keyframes dashGlow{
  0%,100%{ box-shadow:0 0 0 3px rgba(232,163,23,.12), 0 4px 14px rgba(232,163,23,.16); }
  50%{ box-shadow:0 0 0 6px rgba(232,163,23,.20), 0 6px 22px rgba(232,163,23,.32); }
}
.dash-shine::after{
  content:""; position:absolute; inset:0; pointer-events:none;
  background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.75) 46%,transparent 62%);
  background-size:220% 100%; animation:dashSweep 2.6s ease-in-out infinite;
}
@keyframes dashSweep{ 0%{ background-position:-140% 0; } 100%{ background-position:240% 0; } }
/* 小组积分放大 */
.dash-value-big{ font-size:22px !important; line-height:1.5; font-weight:800; }


/* ===== 投屏：前三名专属大卡 ===== */
.tv-sec{ font-size:15px; font-weight:700; color:var(--sub); letter-spacing:1px;
  margin:6px 0 10px; }
body.bigscreen .tv-sec{ font-size:18px; }
.tv-top{ padding:26px 18px 20px; }
.tv-top .s-name, .tv-name{ font-size:24px !important; margin-top:12px; }
.tv-top .s-score, .tv-score{ font-size:46px !important; font-weight:900;
  letter-spacing:-1px; margin-top:4px; }
.tv-meta{ font-size:13.5px; color:var(--sub); margin-top:6px; }
body.bigscreen .tv-top .s-name{ font-size:28px !important; }
body.bigscreen .tv-top .s-score{ font-size:54px !important; }
.tv-medal{ position:absolute; top:-20px; left:50%; transform:translateX(-50%);
  font-size:38px; line-height:1; filter:drop-shadow(0 3px 5px rgba(0,0,0,.2)); }
.tv-top1{ border-width:3px; }
.tv-top1::after{ animation-duration:2.2s; }

@media (max-width:1024px){
  .block-container{ padding-left:1rem; padding-right:1rem; }
  .page-title{ font-size:21px; }
  .dash-value{ font-size:22px; }
  .student-card{ padding:12px 8px 10px; }
  .s-score{ font-size:18px; }
  div[data-testid="stPopover"]{ right:14px; bottom:14px; }
}
@media (hover:none){
  .student-card:hover{ transform:none; box-shadow:0 1px 2px rgba(16,24,40,.04); }
  .stButton>button{ min-height:44px; }
}
</style>
"""

HIDE_SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"]{ display:none !important; }
[data-testid="collapsedControl"]{ display:none !important; }
header[data-testid="stHeader"]{ display:none !important; }
.block-container{ padding-top:1.1rem !important; max-width:100% !important; }
footer{ display:none !important; }
div[data-testid="stPopover"]{ display:none !important; }
</style>
"""


# 侧边栏折叠按钮常显（单独一段注入）
# Streamlit 默认把折叠按钮设为 visibility:hidden，鼠标悬停侧边栏才出现。
# 平板上没有 hover，老师会以为"侧边栏不能收起"，这里强制可见。
SIDEBAR_TOGGLE_CSS = """
<style>
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"],
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] > button{
  visibility:visible !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] > button{ opacity:.62 !important; }
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] > button:hover{ opacity:1 !important; }
</style>
"""


def inject_css(big_screen: bool = False) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(SIDEBAR_TOGGLE_CSS, unsafe_allow_html=True)
    if big_screen:
        st.markdown(HIDE_SIDEBAR_CSS, unsafe_allow_html=True)


# ===========================================================================
# 文案
# ===========================================================================
def role_text(role_in_class: str, subject: str = "") -> str:
    """班主任 → 班主任；科任+科目 → 语文老师；科任无科目 → 科任老师"""
    if role_in_class == "head_teacher":
        return "班主任"
    subj = (subject or "").strip()
    if subj:
        if subj.endswith(("老师", "教师")):
            return subj
        return f"{subj}老师"
    return "科任老师"


def subject_options() -> list[str]:
    return ["语文", "数学", "英语", "物理", "化学", "生物",
            "道德与法治", "历史", "地理", "体育", "音乐", "美术",
            "信息技术", "心理健康", "劳动", "其他"]


def fmt_score(v: int, show_plus: bool = True) -> str:
    """show_plus=False 时正数不带 +（榜单展示口径）"""
    v = int(v or 0)
    if v > 0 and show_plus:
        return f"+{v}"
    return str(v)


def esc(text: object) -> str:
    return _html.escape(str(text if text is not None else ""))


# ===========================================================================
# 提示
# ===========================================================================
def flash(msg: str, kind: str = "success") -> None:
    st.session_state["flash"] = (kind, msg)


def show_flash() -> None:
    data = st.session_state.pop("flash", None)
    if not data:
        return
    kind, msg = data
    icon = {"success": "✅", "error": "⚠️", "warning": "⚠️", "info": "ℹ️"}.get(kind, "ℹ️")
    try:
        st.toast(f"{icon} {msg}")
    except Exception:
        st.info(msg)


# ===========================================================================
# 音效
# ===========================================================================
_TONES = {"plus": [(880, 0.10), (1320, 0.14)], "minus": [(392, 0.16)], "click": [(660, 0.06)]}


def play_sound(kind: str = "plus", enabled: bool = True) -> str:
    if not enabled:
        return ""
    tones = _TONES.get(kind, _TONES["plus"])
    notes = ",".join(f"{{f:{f},d:{d}}}" for f, d in tones)
    return f"""
    <div style="display:none"><script>
    (function(){{
      try{{
        var AC = window.AudioContext || window.webkitAudioContext;
        if(!AC) return;
        var ctx = new AC(); var t0 = ctx.currentTime;
        [{notes}].forEach(function(n){{
          var o = ctx.createOscillator(), g = ctx.createGain();
          o.type='sine'; o.frequency.value=n.f;
          g.gain.setValueAtTime(0.0001, t0);
          g.gain.exponentialRampToValueAtTime(0.16, t0+0.01);
          g.gain.exponentialRampToValueAtTime(0.0001, t0+n.d);
          o.connect(g); g.connect(ctx.destination);
          o.start(t0); o.stop(t0+n.d+0.02); t0 += n.d;
        }});
        setTimeout(function(){{ try{{ ctx.close(); }}catch(e){{}} }}, 800);
      }}catch(e){{}}
    }})();
    </script></div>
    """


def play_sound_if(flag_key: str = "play_sound_now") -> None:
    kind = st.session_state.pop(flag_key, None)
    if kind:
        st.markdown(play_sound(kind), unsafe_allow_html=True)


# ===========================================================================
# 图片 / 头像
# ===========================================================================
def img_src(url: str, fallback_key: str = "a01") -> str:
    """把存储引用转成 <img src>：http/相对路径/base64 都支持"""
    url = (url or "").strip()
    if not url:
        return avatars.avatar_data_uri(fallback_key or "a01")
    if url.startswith(("http://", "https://", "data:")):
        return url
    from core.storage import read_image_bytes

    data = read_image_bytes(url)
    if not data:
        return avatars.avatar_data_uri(fallback_key or "a01")
    ext = url.rsplit(".", 1)[-1].lower() if "." in url else "png"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def avatar_img_tag(student: dict, size: int = 64, ring: str = "") -> str:
    src = img_src(student.get("avatar_url") or "", student.get("avatar_key") or "a01")
    style = "border-radius:50%;object-fit:cover;border:2px solid #fff;"
    if ring:
        style += f"box-shadow:0 0 0 2px {ring};"
    return f'<img src="{src}" width="{size}" height="{size}" style="{style}"/>'


def tag_icon_html(tag: dict, size: int = 18) -> str:
    """标签图标：优先上传的图片 icon_img，否则 emoji icon"""
    img = (tag.get("icon_img") or "").strip()
    if img:
        src = img_src(img, "")
        return (f'<img class="tag-icon-img" src="{src}" '
                f'style="width:{size}px;height:{size}px"/>')
    return esc(tag.get("icon") or "•")


# ===========================================================================
# 卡片
# ===========================================================================
def score_class(v: int) -> str:
    return "score-plus" if v > 0 else ("score-minus" if v < 0 else "score-zero")


def student_card_html(student: dict, score: int, rank: int | None = None,
                      size: int = 62, show_no: bool = False,
                      group_rank: int | None = None, group_total: int | None = None,
                      show_plus: bool = True, meta: str = "") -> str:
    top_cls, medal = "", ""
    if rank is not None and 1 <= rank <= 3:
        top_cls = f" card-top{rank}"
        medal = f'<div class="medal">{"🥇🥈🥉"[rank - 1]}</div>'
    rank_html = ""
    if rank is not None:
        cls = f"rank-badge rank-{rank}" if rank <= 3 else "rank-badge"
        rank_html = f'<div class="{cls}">{rank}</div>'
    grp_html = ""
    if group_rank is not None:
        suffix = f"/{group_total}" if group_total else ""
        grp_html = f'<div class="grp-rank">组内 {group_rank}{suffix}</div>'
    no_html = f'<div class="s-group">{esc(student.get("student_no", ""))} 号</div>' if show_no else ""
    meta_html = f'<div class="s-meta">{esc(meta)}</div>' if meta else ""
    return (
        f'<div class="student-card{top_cls}">{medal}{rank_html}{grp_html}'
        f'{avatar_img_tag(student, size)}'
        f'<div class="s-name">{esc(student.get("name", ""))}</div>'
        f'{no_html}<div class="s-group">{esc(student.get("group_name") or "")}</div>'
        f'<div class="s-score {score_class(score)}">{fmt_score(score, show_plus)}</div>'
        f'{meta_html}</div>'
    )


def group_card_html(name: str, score: float | int, member_count: int = 0,
                    sum_score: int = 0, rank: int | None = None,
                    show_members: list[str] | None = None) -> str:
    """小组卡：小组名 + 人均分 + 人数/合计（不含学生照片）"""
    top_cls = f" card-top{rank}" if rank and 1 <= rank <= 3 else ""
    medal = (f'<div class="medal">{"🥇🥈🥉"[rank - 1]}</div>'
             if rank and 1 <= rank <= 3 else "")
    if rank:
        cls = f"rank-badge rank-{rank}" if rank <= 3 else "rank-badge"
        rank_html = f'<div class="{cls}">{rank}</div>'
    else:
        rank_html = ""
    members_html = ""
    if show_members:
        text = "、".join(show_members[:8]) + ("…" if len(show_members) > 8 else "")
        members_html = f'<div class="grp-meta">{esc(text)}</div>'
    shown = int(round(float(score)))
    return (
        f'<div class="student-card grp-card{top_cls}">{medal}{rank_html}'
        f'<div class="grp-name">{esc(name)}</div>'
        f'<div class="grp-score {score_class(shown)}">{fmt_score(shown, False)}</div>'
        f'<div class="grp-meta">{member_count} 人 · 合计 {fmt_score(int(sum_score), False)}</div>'
        f'{members_html}</div>'
    )


def dashboard(cards: list[dict]) -> str:
    """
    仪表盘卡片组。
    card 支持：{label, value, hint?, tone?(plus/minus/primary), icon?,
               shine?(本周之星闪光特效), big?(小组积分放大)}
    """
    tone_color = {"plus": "var(--plus)", "minus": "var(--minus)", "primary": "var(--primary)"}
    cells = []
    for c in cards:
        color = tone_color.get(c.get("tone", ""), "var(--ink)")
        hint = f'<div class="dash-hint">{esc(c["hint"])}</div>' if c.get("hint") else ""
        icon = f'{c["icon"]} ' if c.get("icon") else ""
        extra = ""
        if c.get("shine"):
            extra += " dash-shine"
        cells.append(
            f'<div class="dash-card{extra}">'
            f'<div class="dash-label">{icon}{esc(c["label"])}</div>'
            f'<div class="dash-value{" dash-value-big" if c.get("big") else ""}" '
            f'style="color:{color}">{esc(c["value"])}</div>{hint}</div>'
        )
    return f'<div class="dash-grid">{"".join(cells)}</div>'


def metric_row(items: list[tuple[str, str]]) -> str:
    return dashboard([{"label": a, "value": b} for a, b in items])


def empty_state(title: str, sub: str = "", icon: str = "📭") -> None:
    st.markdown(
        f'<div class="empty"><div class="empty-icon">{icon}</div>'
        f'<div class="empty-title">{esc(title)}</div>'
        f'<div class="empty-sub">{esc(sub)}</div></div>',
        unsafe_allow_html=True,
    )


def is_big_screen() -> bool:
    return bool(st.session_state.get(BIG_SCREEN_KEY))
