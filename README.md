# 班级评价小屋 · 使用说明

> 游戏化班级积分评价系统｜Python + Streamlit｜教师自用、不商用
> 教师端 + 家长查看端，全部走网页链接，无需小程序。

---

## 一分钟了解

| 谁 | 登录方式 | 能做什么 |
|---|---|---|
| **班主任** | 账号 + 密码 | 建班、管学生、管标签、打分、撤回、导出、加科任老师 |
| **科任老师** | 账号 + 密码 | 只打分、看榜单、看日志（不能建班/删班/撤回/导出） |
| **学生家长** | 班级 + 学号 + 4 位查看码 | 只看自己孩子的积分与记录，看不到榜单和别的学生 |
| **教室大屏** | 投屏口令 | 纯净全屏榜单，隐藏侧边栏 |

## 三份文档怎么用

| 文档 | 什么时候看 |
|---|---|
| **documents/02_本地运行.md** | 第一次在自己电脑上跑起来 |
| **documents/03_云端部署.md** | 想让家长用手机链接访问 |
| **documents/04_功能测试清单.md** | 交付/验收时逐项打勾 |
| **documents/01_数据库设计.md** | 想改表结构 / 理解数据口径 |

## 设计取舍（为什么这么做）

1. **为什么云端不用 SQLite？**
   Streamlit Community Cloud 是临时容器，休眠重启后本地文件全部重置。所以数据库、图片必须放 Supabase。

2. **为什么切换模式不用改代码？**
   `config.py` 把环境变量收拢成一个配置对象，`core/db.py` 在连接层分流（SQLite / Postgres），
   业务 SQL 只用 `?` 占位符，云端自动改写为 psycopg 的命名参数。页面代码完全感知不到差异。

3. **为什么家长端那么「简陋」？**
   这是刻意的。家长端只有一条数据路径：`WHERE student_id = 当前登录学生`。
   页面里不存在任何"查全班"的代码分支，也就不存在越权查询的可能。
   另外 session 里的学生 ID 还带 HMAC 签名，改了 session 也进不去。

4. **为什么积分用"流水 + 冗余字段"而不是触发器？**
   `score_logs` 是唯一事实来源，`students.total_score` 只是列表排序用的快缓存。
   撤回时两处一起改（同一事务），榜单统计永远从流水重算，所以不会出现"总分和明细对不上"。

5. **同分并列怎么做？**
   竞争排名（1,2,2,4）在应用层 `apply_competition_rank()` 里算，SQLite/Postgres 都能跑，不依赖窗口函数。

6. **头像版权怎么办？**
   16 款头像全部用 SVG 代码画出来（大头小身、粗描边、马卡龙配色），没有任何第三方素材文件，也就没有版权风险。
   老师也可以给学生上传真实照片。

---

## 目录速览

```
class_eval/
├── app.py                    入口（st.navigation 注册页面，云端 Main file 填这个）
├── Home.py                   登录页（老师 / 家长 / 投屏三入口）
├── config.py                 local / cloud 双模式配置
├── core/
│   ├── db.py                 数据访问层（一套代码跑两种库）
│   ├── auth.py               三身份登录态 + 权限守卫
│   ├── security.py           PBKDF2 密码 + HMAC 令牌
│   ├── storage.py            图片存储（本地 / Supabase Storage）
│   ├── avatars.py            程序化 SVG 卡通头像
│   ├── exporter.py           德育台账 Excel
│   └── ui.py                 卡通样式 / 学生卡片 / 提示音
├── ui/nav.py                 侧边栏与页面外壳
├── pages/                    8 个页面
├── sql/                      两套建表脚本
├── tools/check_env.py        环境自检
├── tests/                    自动化测试（3 个文件）
└── documents/                这套文档
```

## 默认账号

- 账号：`admin`
- 密码：`.env` 或 Secrets 里的 `DEFAULT_ADMIN_PASSWORD`
- **首次登录后请立即到「设置与导出 → 账号安全」改密码。**

## 快速开始

```bash
cd class_eval
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
copy .env.example .env
python tools/check_env.py
streamlit run app.py
```

## 辅助工具（tools/）

| 脚本 | 作用 |
|---|---|
| `tools/check_env.py` | 部署前自检：依赖、配置、建表、存储、Excel（24 项） |
| `tools/demo_data.py` | 一键生成演示数据（演示班 + 12 名学生 + 近两周 70 条打分）；`--clear` 清空 |
| `tools/ui_check.py` | 真实浏览器（Edge）打开各页面，检查报错、关键文案、侧边栏、家长隔离 |
| `tools/screenshot.py` | 批量截图关键页面，用于写汇报/教案 |

## 自动化测试结果（本机实测）

```
python tests/test_core.py          → 通过 44 项，失败 0   （业务逻辑）
python tests/test_app_smoke.py     → 通过 10/10 页面      （每页无异常）
python tests/test_interactions.py  → 通过 24 项，失败 0   （点击/权限/越权）
python tools/check_env.py          → 通过 24 项，失败 0   （环境自检）
python tools/ui_check.py           → 通过 41 项，失败 0   （真实 Edge 渲染 + 快切周期 + 投屏小组榜）
```

## v1.1 更新要点

| 类别 | 内容 |
|---|---|
| 修 Bug | admin 无法进入班级管理（改为 st.navigation 注册页面 + 空班级直接给建班表单）；榜单快速切换周期的 removeChild 渲染错乱（卡片改为单容器一次性渲染） |
| 功能 | 科任显示「数学老师」；最近评价按学生折叠；榜单去副标题/正数去 +/组内排名/前三特效；投屏可切「小组榜」隐藏个人信息；头像 32 款 + 自定义上传；标签图标可上传图片 |
| 界面 | 校园简约风（靛蓝主色、加分绿/扣分橙红、线性图标）；侧边栏分组 + 可收起；右下角悬浮快速评分；仪表盘卡；评语模板；平板适配 |
| 数据 | 新建「七年级二班」，10 个小组 60 名学生（`tools/seed_grade7_class2.py`） |

## 最低运行要求

- Python 3.9+（推荐 3.11）
- 内存 512MB 足够（低并发，几十人）
- 云端：Supabase 免费版 + Streamlit Community Cloud 免费版
