# SEO / GEO 部署与 curl 验收（2026-10-05）

应用代码已部署。公网根域名与根路径 robots 仍被 Cloudflare 隧道的路径规则拦截，等待控制台登录后添加转发并清理根 robots 的旧 404 缓存；源站根路径已返回 302 到 `/wechat`。

## 修改文件

- `web/app/page.tsx`、`discover/page.tsx`、`rankings/page.tsx`、`search/page.tsx`、`categories/page.tsx`、`categories/[id]/page.tsx`、`accounts/[id]/page.tsx`、`articles/[id]/page.tsx`：服务端取数与独立元信息。
- `web/components/home.tsx`、`categories.tsx`、`account-detail.tsx`、`article-detail.tsx`、`explorer.tsx`、`explorer-page.tsx`：保留现有交互并预渲染真实数据，共享规范化查询参数。
- `web/lib/server-api.ts`、`seo.ts`、`api.ts`、`types.ts`、`web/components/json-ld.tsx`：请求内去重、会话传递、初始数据、SEO 与转义后的 JSON-LD。
- `web/app/layout.tsx`、`web/next.config.ts`、`web/app/robots.ts`、`sitemap.ts`、`llms.txt/route.ts`、`web/public/og-image.png`：动态渲染、缓存策略、爬虫入口、根路径重定向和社交图片。
- `web/components/shell.tsx`、`web/app/admin/page.tsx`、`admin/layout.tsx`、`login/layout.tsx`、`library/layout.tsx`、`wechat-entry-test/layout.tsx`：移除公开后台链接、隐藏配置提示、登录校验和禁止索引私人页面。
- `backend/app/main.py`、`auth.py`、`backend/tests/test_admin_security.py`、`test_core.py`、`scripts/verify-public-html.py`：最新日期、轻量公开索引、管理鉴权/限流、回归测试及 curl 验收。
- `docs/server-deployment.md`：明确禁止在 2 GiB ECS 上构建镜像，采用本机构建、传送、加载和只替换指定服务。

## 原始 HTML 验收

验证通过 curl 下载 HTML，再移除 script/style/template 后检查 main 中的真实文字和链接；没有运行 JavaScript。全部受测页面有独立 title/description、绝对 canonical、完整 OG、Twitter Card 和对应 JSON-LD。title/canonical 也直接位于 head 内。

| URL（均以 https://wechat.aim888888.xyz 开头） | HTTP | 标题 | 正文文字数 | 详情链接数 | JSON-LD |
| --- | --- | --- | ---: | ---: | --- |
| /wechat | 200 | 公众号发现 · 中文优质信息源 | 2516 | 31 | WebSite |
| /wechat/categories | 200 | 公众号分类 · 科技、财经、教育与生活 | 240 | 62 | ItemList |
| /wechat/categories/2 | 200 | 人工智能类公众号 | 3433 | 24 | ItemList |
| /wechat/discover | 200 | 发现公众号 · 中文信息源目录 | 3705 | 24 | ItemList |
| /wechat/rankings | 200 | 公众号排行 · 信息源排行榜 | 4085 | 24 | ItemList |
| /wechat/search?q=极客公园 | 200 | 搜索「极客公园」· 公众号 | 925 | 8 | ItemList |
| /wechat/search?tab=articles | 200 | 文章搜索 · 中文内容目录 | 695 | 12 | ItemList |
| /wechat/accounts/21 | 200 | 极客公园公众号 · 科技简介与文章 | 4304 | 29 | Organization |
| /wechat/articles/44394 | 200 | 10分钟消费20多万元，却没等来月饼！“Tiffany月饼”冲上热搜，Tiffany中国道歉：将依据规章制度，严肃处理 · 每日经济新闻 | 2146 | 7 | Article |

- 首页实际显示 9,908 个信息源、10,298 篇文章，日期来自数据库；不含空数字或“暂无日期”。
- 公众号页包含真实简介、分类、画像、文章和原始资料链接；文章页包含真实正文、作者、发布时间和原文链接。
- 所有受测公开页面页脚/导航均不含后台入口。管理登录页不含 `.env` 或 `ADMIN_TOKEN` 配置提示，管理 API 无凭证返回 403（达到失败预算后 429）。
- 每个受测 HTML 的 Cache-Control 均为 `private, no-cache, no-store, max-age=0, must-revalidate`，Cloudflare 状态均为 `DYNAMIC`；静态 Next 资源仍保留长缓存。
- `/wechat/robots.txt`、`/wechat/sitemap.xml`、`/wechat/llms.txt`、`/wechat/og-image.png` 均返回 200；robots 禁止管理、登录、个人收藏路径，允许公开内容。
- sitemap 共 20,273 个 URL，完整包含 9,908 个公开公众号、10,298 篇公开文章、62 个分类及 5 个主要页面；每个详情条目都有 lastmod。隐藏文章、隐藏公众号的文章不进入索引。
- 非数字的公众号/文章详情 ID 返回 404；`/wechat/rankings?page=-1` 规范化到第一页并返回 200。

## 构建、回归与部署

- Next.js 16.3.5 生产构建与 TypeScript 检查通过；全部内容路由为按请求渲染。
- 7 项后台安全测试在本机和 Linux API 镜像内通过；6 项数据库事务回滚测试通过，覆盖索引过滤、隐藏内容、文章详情、会话隔离、CSRF 和管理边界。
- 本机代码提交：`7f6ba2b`（主实现）、`5a0151c`（区分列表/搜索描述）。现有 exports 已另做本地快照，未传到服务器。
- 服务器通过增量补丁保留运行期数据改动，并以 `--no-build --no-deps` 只替换 api/web。
- API 镜像：`wechat-api:7f6ba2b`，`sha256:86658c1388003dd7e108c681637763bf6f3ee94649390843809d0894ac4456a1`。
- Web 镜像：`wechat-web:5a0151c`，`sha256:d42818b0ffa7fa08e72b0233eebbb07be14ea12722ccfb9030e085d35c654ac3`。
- 备份目录：`/opt/wechat-backups/seo-20261005T112254Z`，旧 Web/API 镜像保留为 `before-seo-20261005T112254Z` 标签。
- 初次原地构建期间出现 SSH/公网不可达；用户重启后原服务恢复 200，随后所有构建改在本机完成。未确认内核 OOM；未删除容器数据、数据库或迁移备份。

## 重跑验收

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/verify-public-html.py
```

原始响应与机器可读结果位于 `logs/public-html-verification/`（本地忽略目录）。
