# 公众号发现 · WeChat Source

按项目 PRD 实现的中文信息源发现与聚合平台。Next.js / TypeScript 前端，FastAPI 后端，PostgreSQL 数据库，独立采集与 AI worker。公众号发现使用独立发现服务，文章列表和正文由独立 WeRead Adapter 获取，直接写入 PostgreSQL。协议参考 `ref/we-mp-rss`，不运行或复制整个参考应用。

## 本机入口

- 网站：<http://localhost:3500>
- 局域网：`http://本机局域网IP:3500`；Windows 启动脚本监听所有网卡，防火墙仅放行本地子网的 TCP 3500。
- 管理后台：<http://localhost:3500/admin>（密钥在项目 `.env` 的 `ADMIN_TOKEN`）
- API 文档：<http://localhost:8500/docs>
- 微信读书扫码：管理后台 →「微信读书账号池」→ 新增账号 → 扫码登录
- 公众号发现服务扫码（仅发现 / 兼容入口）：<http://localhost:5500/login.html>
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

参考服务保留独立代码库，不复制到产品后端。`source_bridge/service.py` 在参考应用内注册桥接接口（AGPL-3.0，许可证在 `source_bridge/LICENSE`），仅供公众号搜索、旧缓存导入和手工文章链接兼容；原参考代码不作修改。当前参考版本为 `043c2f9828401220a00b7b125686b334581745e0`，AGPL-3.0。若 `ref` 缺失：

```powershell
git clone https://github.com/tmwgsicp/wechat-download-api.git ref/wechat-download-api
git -C ref/wechat-download-api checkout 043c2f9828401220a00b7b125686b334581745e0
.venv/Scripts/python -X utf8 -m pip install -r ref/wechat-download-api/requirements.txt
cd ref/wechat-download-api
$env:SITE_URL='http://localhost:5500'
$env:SKIP_BACKGROUND_TASKS='true'
../../.venv/Scripts/python -X utf8 -m uvicorn service:app --app-dir ../../source_bridge --host 127.0.0.1 --port 5500
```

发现服务使用可登录公众平台后台的微信扫码，其凭证由该服务保管。微信读书是另一套独立登录，凭据经 Fernet 加密保存在 PostgreSQL，不返回给前端。默认密钥在忽略提交的 `data/private/source-credentials.key`；必须单独备份，并与数据库配套恢复。也可配置 `SOURCE_CREDENTIAL_KEY`，所有 API / worker 必须一致。Docker API 和 worker 共享该私有目录。

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

`app.collect` 用于发现公众号基本信息，不能代表历史正文已经采集。运行时避免与其他发现任务并发请求同一发现服务。原公众平台历史列表接口已退出主采集链路；微信读书账号登录后，worker 接管文章采集。

独立 worker 模式：

```powershell
../.venv/Scripts/python -m app.worker --mode crawler
../.venv/Scripts/python -m app.worker --mode ai
```

队列通过 PostgreSQL 行锁、任务去重、执行代次及租约支持多个 worker；同一发现服务仍建议只运行一个发现执行器。AI worker 可以独立部署。每分钟检查到期订阅，默认每 24 小时同步；历史未完成则继续回填，并检查最新一页，完成后从最新页做增量。默认自动任务每批 3 页、20 篇缺失正文，管理面板可以指定更小批次。

## 微信读书采集与账号池

具体源码核查、协议与设计见 [docs/weread-integration.md](docs/weread-integration.md)。

1. 在后台「微信读书账号池」新增账号，分别扫码（或导入 Cookie），系统验证书架后加密保存。重复 VID 不能算作两个账号。可以禁用、检查登录、调整最大任务数和最大公众号数；建议每账号并行任务数为 1。
2. 公众号发现得到唯一标识后加入订阅与采集队列。已审核的现有公众号也会自动建队列。调度器按健康状态、负载、容量、连续失败与最近分配时间选择账号。
3. Adapter 检查登录 / 续期、确保目标已入书架，获取分页列表和正文。每页、每篇独立入库，标准化来源和发布时间。缺正文会再次补采。公众号没有永久绑定某个微信读书用户，多对多书架记录仅表示可访问范围。
4. 登录失效、限流、网络失败分别记录，释放租约后重试时重新选账号。无可用账号进入等待状态，不消耗网络重试次数；冷却到期或重新登录后唤醒。进程中断超过 5 分钟的租约被回收，旧执行器不能完成新代次任务。
5. 站内搜索只查 PostgreSQL。无结果时，登录用户可提交发现请求；同词请求去重，后台发现后进入采集，待审核公众号不会直接公开。
6. 列表能力按订阅记录为 `history` 或 `latest_only`。后者只取得最新文章，不推进历史游标、不声称历史完成。账号池展示的是该账号最近任务能力，不表示该账号对所有公众号能力一致。

在「公众号审核」点击「采集 / 导出」可创建小批次任务、继续历史回填、查看来源状态与失败。旧缓存导入和已有文章链接入口仍可兼容，但不调用原历史接口。

**导出直接读取 PostgreSQL**，不依赖发现服务、微信读书登录或参考 SQLite。支持 Markdown ZIP、HTML、Excel、JSON（最多 3000 篇）、Word / EPUB（500 篇）、PDF（200 篇）。只导出已保存正文的文章：Excel / JSON 为清单，HTML 保留正文及图片引用，Markdown / Word / PDF / EPUB 为文字正文；当前不打包离线图片。

真实小样本（2026-09-14）：两套微信读书账号均完成扫码与书架验证。极客公园入库 21 篇列表、1 篇正文（4259 字），历史分页有效但未采完；36氪入库 1 篇正文（6628 字），本次列表降级为仅最新文章。连同此前新智元正文，数据库共 23 篇文章、3 篇正文，50 个已审核公众号。真实样本与任务证据见 `data/weread-report.json`。当前两账号最大公众号数各设为 **1**，用于限定验证规模；其余 48 个订阅等待容量，在账号池编辑容量后可继续采集。

## AI 配置

在根 `.env` 配置兼容 Chat Completions 的模型：

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=你的密钥
LLM_MODEL=你的模型名称
```

Embedding 使用硅基流动 `Qwen/Qwen3-VL-Embedding-8B`，重排使用 `Qwen/Qwen3-VL-Reranker-8B`，分别配置 `EMBEDDING_*` / `RERANK_*`。本机两套 API_KEY 通过 `${LLM_API_KEY}` 引用已有硅基流动密钥，LLM 分析模型保持独立。向量以模型 / 内容哈希 / 向量写入 PostgreSQL 的 `article_embeddings`。文章关键词搜索的「内容推荐」会对最多 100 条数据库候选重排后分页，模型不可用时退回数据库排序；其他排序不调用模型。正文入库后自动排队 Embedding，缺配置明确阻塞。

正文范围由 `BODY_SINCE=2026-06-01` 控制（北京时间零点，包含当天）。微信读书只请求已知发布日期在范围内的缺失正文；日期不明的 cover 记录暂留元数据。已有正文不删除。手工链接日期未知时也会等待确认。待采集任务每批补采 20 篇，账号容量仅决定能接手多少公众号，不等于每批正文数。

正文页面要求验证时，账号进入异常暂停，不自动轮换账号继续撞验证；后台显示失败原文链接。用对应微信处理页面验证后点击「检测」，系统会验证书架并重新探测失败正文；仍失败则保持暂停。验证在浏览器与采集会话间不一定通用。账号画像至少需要该公众号 3 篇正文，数量不足属于等待采集，满足条件后会自动排队。

验证判断只看页面可见的明确挑战提示，不以 HTML 脚本中的“验证 / captcha”关键词判定。单篇无可读正文按文章记录 `body_error`、`body_failures`、`body_retry_after`，跳过并延后 24 小时重试，继续其他文章，不使整个账号失效。2026-09-14 真实任务已验证：跳过文章 3506 后，同账号另外两篇正文成功入库；两个账号均能取得其他文章正文。

本轮接口依据：[硅基流动 Embedding](https://api-docs.siliconflow.cn/docs/api/embeddings-post)、[Rerank](https://docs.siliconflow.cn/docs/api/rerank-post)。2026-09-14 已验证真实正文生成 4096 维向量并写入 PostgreSQL，关键词检索返回指定 VL Reranker 的重排结果。29 项后端回归测试及生产构建通过。

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

可使用 `docker compose up -d --build` 运行数据库、API、worker、web。`.env` 必须先创建，参考服务在宿主机运行，容器通过 `host.docker.internal:5500` 连接。`SOURCE_API_URL` 可以调整为独立参考服务地址。Web 通过同源 Next.js rewrite 访问 API，管理员需在后台输入管理密钥，服务端以 Bearer token 校验管理请求。

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
