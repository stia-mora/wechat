# 微信读书接入：源码核查与集成方案

## 核查对象

本地参考 `ref/we-mp-rss`，commit `d8feb6a42c6773d7374e03c487d3ae3426084af8`，MIT。仅参考协议与数据结构，不运行/复制整个服务，不引入其 SQLAlchemy、全局配置、RSS Feed 模型、Vue 前端或单例登录状态。

## 当前获取链路与实际限制

- `apis/mps.py`：发现得到的 fakeid 是 base64 数字标识；解码后组成 `MP_WXS_<数字>` bookId。不能把微信读书用户 vid 当公众号 ID。
- `driver/weread_qr.py`：`/api/auth/getLoginUid` → 本地生成 `/web/confirm?uid=...` 二维码 → `/api/auth/getLoginInfo` 长轮询；服务器接收 Cookie，调用书架验证。必要时 `/web/login/renewal` 续期。另支持管理页导入完整 Cookie。原实现单例且只存一套凭证，不适合作为多账号调度器直接复用。
- `core/wx/model/weread.py`：`GET /web/shelf/sync?userVid=&synckey=0&lectureSynckey=0` 检查书架；`POST /web/shelf/add`，JSON `bookIds:[bookId]` 加入公众号。书架成员关系与任务租约分开维护。
- `core/wx/model/weread_mp.py`：主路径 `GET /web/mp/articles?bookId=&offset=`；响应 `reviews[].subReviews[].review.mpInfo`。offset 按顶层 reviews 群组数量递增，不按文章数。正文 `GET /web/mp/content?reviewId=`，提取 `#js_content` / `.rich_media_content`。
- 列表不可用时原实现回退 `/api/mp/cover?bookId=`，只能取得最新一篇。`docs/weread-mp.md` 尚称列表废弃，而当前源码注释称已恢复，二者矛盾。我们的运行状态必须区分 history / latest_only，不能承诺凭证接入前已验证历史能力，也不能把 cover 采集时间伪装为发布时间。
- `-2012/-2010`、401 表示凭证问题；`-2041` 在参考代码里同时用于列表不可用或认证/风控，不能无条件把全部账号作废。先检查书架登录状态，再确定是否可降级；429/403 冷却，不连续轮换轰炸接口。
- 参考实现存在“已入库但正文为空便跳过”的分支；新实现将文章元数据与正文完成状态分开，缺正文独立重试。
- 协议所需依赖：HTTP 客户端、BeautifulSoup、本地 QR 生成；新服务继续使用已有 httpx/bs4/PostgreSQL，增加凭据加密与本地二维码依赖。不保存参考项目的全局 Cookie 文件。

## 独立集成方案（编码前确定）

1. `sources/weread.py` Adapter：统一封装登录、续期、书架、列表、cover、正文和异常分类。所有 weread.qq.com 细节集中在数据源层。
2. PostgreSQL 新表：data_sources、source_accounts（加密凭据/健康/容量/冷却/最近成功失败）、source_subscriptions（公众号到数据源 bookId）、source_memberships（多对多书架记录）、crawl_attempts（每次账号分配及失败审计）、article_origins（数据源文章唯一 ID）、article_embeddings。jobs 增加账号租约/心跳；公众号表没有永久 source_account_id。
3. `account_pool.py`：事务内 SKIP LOCKED 选择健康且未超负载账号，按任务负载、书架容量、连续失败、最近分配时间排序；原子创建租约。成功释放，异常标记失效或冷却并重新排队；重试重新调度，保留持久化进度。无健康账号进入待账号状态，不消耗网络重试预算。
4. `weread_crawler.py`：队列任务 → 池租约 → 加书架 → 列表分批标准化入库 → 缺失正文补全 → 搜索索引、分类/LLM、Embedding 队列。正文每篇提交；历史页 offset 可恢复；增量从最新扫描，历史完成标记独立，cover 不推进历史游标。租约心跳与崩溃恢复避免重复并发。
5. 主 sync 调用改为微信读书；旧公众号后台只用于发现，原历史接口不再用于主采集。旧文章、阅读、缓存导入/下载保留兼容，不作为新数据的中转。新增导出以 PostgreSQL 为准。
6. 管理后台账号池：新增两个或更多账号、扫码/导入 Cookie、检测、禁用、容量/并发配置；展示租约、关联公众号数、同步时间、失败、能力降级。公众号采集面板提供加入队列、续传、增量状态。
7. 站内搜索始终读取数据库。无结果时提供发现请求，合并重复关键词并限速，后台发现后创建待采集任务；已存在或待审核账号不重新请求外部搜索。持续增量由 worker 定时创建去重任务。
8. Embedding 使用显式配置的兼容接口，缺密钥/模型时等待配置，绝不生成假向量；现有 LLM 分类/摘要/账号画像保持结构化验证。

## 验证边界

按用户要求不做全量真实测试。使用事务回滚和临时凭据验证双账号分配、容量、迁移、租约回收、历史/增量去重、正文补采、搜索命中不出网、降级语义。扫码由用户完成；接入两账号后只采集小样本，明确记录真实接口能力。

## 实施与验证结果（2026-09-14）

上述模块已落地，原历史列表接口不再进入主 sync 路径。登录检查使用短期维护锁；任务使用执行代次、租约和心跳；续期凭据立即持久化，后续文章失败不会丢失新凭据。回填历史同时检查最新一页，增量请求不会倒退历史游标。Docker 的 API / worker 共享私有密钥目录。

- 两个真实微信读书账号均已扫码登录，凭据加密保存，服务重启后仍在健康池。
- 任务 126：极客公园，历史分页入库 21 篇元数据、1 篇 4259 字正文，游标 20，未宣称历史完成。
- 任务 127：36氪，历史列表未取得，书架验证成功后降级 cover，入库 1 篇 6628 字正文，状态 `latest_only`。
- 全库 235 个真实发现公众号，其中 50 个已审核；共 23 篇文章、3 篇正文（含之前的新智元文章）。两个账号当前容量各为 1，48 个订阅等待容量，避免执行全量真实测试。管理员可在账号池扩大容量。
- 25 项后端针对性测试、4 项旧桥接兼容测试通过；生产构建与 TypeScript 检查通过。真实阅读 API、后台账号池、七种 PostgreSQL 导出通过本机检查。
- LLM / Embedding 已接入任务链，但本机未配置模型密钥，相关任务明确等待配置；未声称已生成画像或向量。

可复查证据：`data/weread-report.json`；公开目录快照：`data/catalog.json`。导出样本与凭据密钥保存在忽略提交的 `data/private/`。参考项目仅作为协议来源，未加入运行依赖。
