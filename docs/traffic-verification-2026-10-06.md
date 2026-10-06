# 独立流量监控上线验收 · 2026-10-06

入口：<https://wechat.aim888888.xyz/traffic>。用户名 `admin`；密码仅保存在本机仓库外的私有凭据文件，没有放入文档、Git 或聊天。

## 上线内容

基于 GoAccess1.12（MIT，核对时21,002Stars）新增独立监控服务、中文面板与登录；使用私有HTTP日志和匿名浏览器上报两个渠道。展示今天、7天、30天的PV、估算日UV合计、热门页面、搜索与AI平台引荐、声明的AI爬虫和其他请求类型。

主要文件：`traffic/app.py`（鉴权、上报、报表接口），`traffic/analyzer.py`（GoAccess窗口聚合），`traffic/static/*`（登录与图表、浏览器采集），`traffic/gateway/*`（代理与日志），`compose.server.yaml`，以及Web layout和robots的接入。凭据生成与curl验收分别在 `scripts/create-traffic-credentials.py`、`scripts/verify-traffic.py`。完整选型及统计局限见 [traffic/README.md](../traffic/README.md)。

本机代码提交：`d584f82`、`ade327e`；服务器对应提交：`b3ff203`、`a2c2c47`。镜像在本机构建、校验SHA256后传输及加载；服务器未构建镜像。原Compose及Web镜像已备份。只替换Web、监控、网关，数据库、API、source及5个AI worker保持运行，服务器运行时数据改动保留。

## curl（无JavaScript）验收

运行：`scripts/verify-traffic.py --url https://wechat.aim888888.xyz --credentials-file <私有凭据文件>`。登录体和Cookie使用临时文件，不输出密码或会话值。

| 检查 | 结果 |
| --- | --- |
| `/traffic` 未登录 | 200，独立登录表单；noindex、no-store |
| `/traffic/api/summary` 未登录 | 401 |
| `/traffic/report` 未登录 | 401 |
| 正确密码登录、受保护主页 | 200 |
| 登录后详细GoAccess报告 | 200，no-store；模板执行权限仅限该报告路径 |
| `?days=1/7/30` | 全部200，窗口及GoAccess版本正确 |
| 跨站Origin登录 | 403 |
| 上报admin路径、带query的页面路径 | 422 |
| 原内容管理API的9000字节PATCH请求 | 上游403，网关未返回413，未修改内容 |
| 退出后继续请求统计API | 401 |
| 首页SSR | 真实正文、精选列表及采集脚本存在；扫一扫说明、待分类均为0 |

生产浏览器打开首页后点击“发现”：URL切到 `/wechat/discover`，服务端记录2条浏览器事件，证明客户端内部导航会采集。它们是本次验收访问，不代表2位外部真人。验收时尚无识别出的真实AI抓取；合成AI数据只用于本机测试，没有写入生产。

复跑既有 `verify-public-html.py`：9个路由全部200，正文、独立SEO元信息及JSON-LD通过；robots/sitemap通过，sitemap含20,274条干净URL（9,908账号、10,298文章）。HTML缓存头仍为 `private, no-cache, no-store, max-age=0, must-revalidate`，原站缓存和URL策略没有另行调整。

## 本机与界面验证

- 12项测试通过，覆盖未授权、过期/伪造Cookie、登录失败限流、同源保护、路径与来源校验、查询参数/IP不入浏览器日志、来源条目截断及CSP边界。
- 实际GoAccess解析合成7条HTTP记录：AI2、传统爬虫1、自动化2、浏览器1、未知1；另3条浏览器事件：PV3、UV3、Google来源2、ChatGPT来源1。HOSTS面板和原始IP不在输出报告中，恶意脚本路径没有注入原生HTML。
- 实际本机网关与Linux卷权限：5条HTTP请求、AI2、自动化2；2条浏览器上报按搜索和AI引荐分组。预取、query与不可信客户端伪造的CF IP头均未影响预期结果。
- 浏览器验证登录、时间范围切换及320/375/414/768px布局；主面板和GoAccess详细报告能显示实际测试数据。修复了GoAccess模板编译与CSP的兼容问题，例外仅限已鉴权的原生报告。
- 多模型复核通过，无剩余Critical/Important必改项。

## 运行状态与限制

监控约34.5MiB，网关约3.5MiB；限制分别256MiB/0.35CPU、48MiB/0.25CPU。服务器约601MiB可用内存，cloudflared active，原API/数据库/source健康。私有.env模式600、日志目录2770且101:1000、state目录700且1000:1000。

统计每分钟更新，保留30天，从本次上线开始；上线前日期显示“—”。浏览器特征和UA声明不能百分之百证明真人或AI身份；Cloudflare边缘缓存/拦截的请求可能不进入源站日志，尚未接入完整边缘日志或付费Bot Score。
