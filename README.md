# 公众号发现 · WeChat Source

按项目 PRD 实现的中文信息源发现与聚合平台。Next.js / TypeScript 前端，FastAPI 后端，PostgreSQL 数据库，独立采集与 AI worker。实际数据通过 `ref/wechat-download-api` HTTP API 获取，不以手写名单充当采集结果。

## 本机入口

- 网站：<http://localhost:3500>
- 管理后台：<http://localhost:3500/admin>（密钥在项目 `.env` 的 `ADMIN_TOKEN`）
- API 文档：<http://localhost:8500/docs>
- 参考服务扫码：<http://localhost:5500/login.html>
- PostgreSQL：`127.0.0.1:55439`，数据库 `wechat_source`

项目避开本机已有的 3000 / 5000 / 8000 / 5432 / 55432 服务。公开浏览不需要登录；站内注册登录后可以收藏、关注和查看浏览历史。站内账号不等于微信采集登录。

## 启动

需要 Python 3.11+、Node.js 20.9+ 和 Docker Desktop。Windows PowerShell：

```powershell
./scripts/start.ps1 -Install
```

以后运行 `./scripts/start.ps1`；`./scripts/stop.ps1` 只停止该启动脚本记录的进程，并校验进程创建时间，不影响其他项目。数据库卷不会删除。如果当前服务由开发终端启动，脚本会报告端口已占用，不会杀掉现有进程。

手动启动：

```powershell
Copy-Item .env.example .env
# 将 ADMIN_TOKEN 替换为至少 24 字符的随机密钥
python -m venv .venv
.venv/Scripts/python -X utf8 -m pip install -r backend/requirements.txt
docker compose up -d db
cd backend
../.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8500
# 另一终端，在 backend 目录：
../.venv/Scripts/python -m app.worker
# 另一终端，在 web 目录：
npm ci
npm run build
npm run start
```

参考服务保留独立代码库，不复制到产品后端。`source_bridge/service.py` 在参考应用内注册桥接接口（AGPL-3.0，许可证在 `source_bridge/LICENSE`），复用其订阅、正文解析、SQLite 存储与导出实现；原参考代码不作修改。当前参考版本为 `043c2f9828401220a00b7b125686b334581745e0`，AGPL-3.0。若 `ref` 缺失：

```powershell
git clone https://github.com/tmwgsicp/wechat-download-api.git ref/wechat-download-api
git -C ref/wechat-download-api checkout 043c2f9828401220a00b7b125686b334581745e0
.venv/Scripts/python -X utf8 -m pip install -r ref/wechat-download-api/requirements.txt
cd ref/wechat-download-api
$env:SITE_URL='http://localhost:5500'
$env:SKIP_BACKGROUND_TASKS='true'
../../.venv/Scripts/python -X utf8 -m uvicorn service:app --app-dir ../../source_bridge --host 127.0.0.1 --port 5500
```

使用可登录公众平台后台的微信扫码，参考服务自行将凭证保存到其 `.env`。产品只调用配置的参考服务地址，不读取或存储微信 Cookie。

## 功能

- 首页、发现、分类、搜索、排行、公众号详情、文章阅读、登录 / 注册、个人信息源与后台。
- 公众号 / 文章分别搜索；关键词检索覆盖账号资料、标签、AI 画像、文章标题、作者与正文。
- PostgreSQL FTS + `pg_trgm`，中文使用子串检索补充简单分词。排序分页在数据库执行。
- 四大一级分类与可扩展二级分类，多标签、账号类型和更新频率筛选。
- 综合、最新、活跃、质量、热门、近期增长与相关度排序；展示规则评分依据。
- 按分类 / 标签生成相似账号，并解释共同点与不同标签。
- 文章 HTML 清洗、移除脚本与危险属性、允许微信 CDN 图片、保留原文链接。
- HttpOnly 会话、scrypt 密码摘要、登录尝试限速、同源写入校验；用户收藏与历史互相隔离。
- 管理后台审核账号、编辑分类 / 标签 / 介绍，隐藏与恢复文章，触发采集 / 分析并重试任务，调整推荐权重，审核修改 AI 画像。
- 持久化 PostgreSQL 队列，`FOR UPDATE SKIP LOCKED` 领取、活动任务去重、重试退避、异常阻塞、崩溃任务恢复与定时增量同步。

## 实际采集

在 `backend` 目录执行：

```powershell
../.venv/Scripts/python -X utf8 -m app.collect --target 50 --wait-login
```

采集器使用四类人工精选**查询词**发起真实公众号搜索。保存接口返回的所有不同来源 ID，仅自动审核通过名称精确匹配的目标，其余结果留待人工审核。查询词不直接写入账号库，不生成假文章或假统计。每次完成查询都会更新 `data/collection-report.json`。

账号标识采用 `(platform, source_id)` 唯一约束；文章以 `__biz + mid + idx` 生成稳定标识，忽略分享追踪参数。短链以规范化路径为备选键。原公众号链接优先从文章真实 `__biz` 构建。

运行 `app.collect` 时，建议先不启动 crawler worker，避免两个采集进程同时请求。默认请求至少相隔 13 秒。需要验证或登录过期时停止采集，解决后重试；不自动绕过验证。后台完整采集默认抓取一页历史（每页最多 10 次群发，一次群发可含多篇文章），补齐本批最新 3 篇的正文，可通过任务 API 的 `pages` / `parse_limit` 扩大范围。

独立 worker 模式：

```powershell
../.venv/Scripts/python -m app.worker --mode crawler
../.venv/Scripts/python -m app.worker --mode ai
```

同一参考服务只启动一个 crawler worker。AI worker 可以独立部署。默认每小时检查一次超过 24 小时未同步的已审核账号，启动时也检查。

## 文章采集、缓存与导出

在管理后台的「公众号审核」找到目标账号，点击「采集 / 导出」：

1. **开始完整采集**：自动订阅 → 按页获取历史列表并写入参考库 → 逐篇获取正文并回写参考库 → 导入本站。每页、每篇完成即持久化；面板每 5 秒刷新进度。
2. **仅导入已有缓存**：分页读取参考库文章和正文，不请求微信、不要求扫码登录。按文章标识去重，并补全旧文章后来取得的正文、作者、时间。隐藏文章仍保持隐藏。
3. **已有文章链接**：展开链接入口，每行粘贴一条属于当前账号的 `mp.weixin.qq.com` 链接，最多 20 条。直接解析正文并写入两边数据库，进度和重试在「采集 / AI 任务」中查看。此入口不获取历史列表，文章页面本身仍可能要求登录或验证。
4. **下载已保存文章**：支持 Markdown ZIP、HTML、Excel、JSON、Word、PDF、EPUB。Excel / JSON 是清单，其余包含正文。仅导出参考库已保存正文的文章；无正文时明确提示。Markdown / HTML / Excel / JSON 读取本地数据；Word / PDF / EPUB 的内嵌图片需要下载微信 CDN 图片。
5. **失败续传**：登录过期或微信限流时任务进入「等待处理」，保留已成功的历史页和正文。处理原因后点击「处理后继续此任务」，不重复抓取已完成历史页和已有正文。新建完整采集任务从最新一页开始；需要更早的历史时扩大页数。

桥接接口通过服务端 `ADMIN_TOKEN` 鉴权，微信 Cookie 仍由参考服务保管，不传给产品或浏览器。启动脚本会自动加载桥接扩展；若手动启动，必须使用上文的 `service:app --app-dir ../../source_bridge` 命令。当前扩展依赖上述固定参考版本。

文章进入本站后自动排队 AI 摘要，累计满足条件时排队账号画像。未配置模型时 AI 任务会提示等待配置，已保存正文照常可读、可导出。

本次验证范围：后端事务回滚测试、临时 SQLite 桥接测试、前端生产构建与本机 API 冒烟检查，没有执行全量真实端到端测试。真实小样本历史任务 #79 在 2026-09-14 返回微信 `ret=200013`；登录仍有效，任务保留在历史列表步骤。隔离测试覆盖历史分页、正文保存→ZIP 导出、限流续传、同时间文章分页、缓存补全、手工链接入口与下载鉴权，测试文章不计入真实采集数据。随后使用用户提供的新智元文章链接完成真实正文采集（任务 #90、文章 #901、3295 字），通过本站 API 验证可读，并通过后台下载接口导出 Markdown ZIP / HTML / JSON；缓存导入任务 #92 完成且文章仍只有一条。证据见 `data/pipeline-report.json`，本机导出样本在 `data/private/exports/`。

## AI 配置

在根 `.env` 配置兼容 Chat Completions 的模型：

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=你的密钥
LLM_MODEL=你的模型名称
```

重启 worker 后在后台重试阻塞的分析任务。账号分析默认最多取最近 50 篇已读正文，每篇输入上限 6000 字符；不足 3 篇时不分析，3—19 篇会显示低样本提示。文章摘要上限 30000 字符。

结果经 Pydantic 验证，以 JSONB 存储画像、主题比例、适合 / 不适合人群、推荐理由、评分，以及 `model_name`、`prompt_version`、`generated_at`、样本量。模型未配置、文章不足、验证失败均如实记录，不用规则文案伪装为 AI。新增正文达到阈值时重新排队；已人工审核的画像不会被自动覆盖。

## 数据快照

`data/collection-report.json` 是来源与采集任务凭据清单。`data/catalog.json` 是可移植的公开目录快照，包含账号、分类、标签、文章与已有 AI 结果，不含用户、会话、密码、Cookie 或 API 密钥。

在 `backend` 中：

```powershell
../.venv/Scripts/python -m app.snapshot export ../data/catalog.json
# 新环境先初始化，再导入；仅允许账号库为空时导入
../.venv/Scripts/python -m app.snapshot import ../data/catalog.json
```

快照包含实际采集的文章内容，版权仍归原作者。生产数据库请另行用 `pg_dump` 备份；不要以目录快照代替用户数据备份。

## Docker

可使用 `docker compose up -d --build` 运行数据库、API、worker、web。`.env` 必须先创建，参考服务在宿主机运行，容器通过 `host.docker.internal:5500` 连接。`SOURCE_API_URL` 可以调整为独立参考服务地址。Web 通过同源 Next.js rewrite 访问 API，不将管理密钥发送到客户端。

默认端口仅映射本机地址；对外部署时使用 HTTPS 反向代理、强数据库密码，并将 `COOKIE_SECURE=true`。参考服务应置于可信网络内。这里未执行公网部署。

## 验证与范围

遵照请求，不做真实的完整端到端测试。执行了生产构建、TypeScript 检查和少量关键集成 / 单元验证；测试记录在单一 PostgreSQL 事务内回滚，不计入实际采集数量。

```powershell
cd backend
../.venv/Scripts/python -m pytest -q
cd ../web
npm run build
```

第一阶段使用可解释规则推荐，不实现 PRD 后期的 pgvector 语义搜索、个性化学习排序或其他内容平台。没有 LLM 配置时，账号画像与摘要功能处于待分析状态，数据发现 / 搜索 / 阅读 / 收藏仍可使用。
