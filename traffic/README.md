# WeChat Source 独立流量监控

入口：`https://wechat.aim888888.xyz/traffic`。单独的登录、会话密钥、日志和报表，不复用内容管理的 ADMIN_TOKEN 或数据库。

## 开源选型（2026-10-06）

GitHub API 核对的星数，后续会变化：

| 项目 | Stars | 许可证 | 本项目适配判断 |
| --- | ---: | --- | --- |
| [GoAccess](https://github.com/allinurl/goaccess) | 21,002 | MIT | 采用。直接分析 HTTP 日志，不要求爬虫运行 JavaScript；1.12 增加 AI Crawlers 分类。 |
| [Umami](https://github.com/umami-software/umami) | 39,184 | MIT | 浏览器分析成熟，但单靠追踪脚本覆盖不了不执行 JavaScript 的抓取，需要再接日志。 |
| [Plausible](https://github.com/plausible/analytics) | 29,318 | AGPL-3.0 | 产品成熟，自托管依赖比本服务器适合的日志分析方案重。 |
| [Matomo](https://github.com/matomo-org/matomo) | 21,924 | GPL-3.0 | 功能全面，PHP/数据库与维护成本更高。 |
| [Rybbit](https://github.com/rybbit-io/rybbit) | 13,096 | AGPL-3.0 | 现代分析界面，但新增数据存储及完整应用栈较重。 |

依据：[GoAccess 1.12 ChangeLog](https://github.com/allinurl/goaccess/blob/v1.12/ChangeLog)、[官方手册](https://goaccess.io/man)。本实现使用 GoAccess 原生解析、分类和聚合，增加本站中文视图、来源分组及独立登录。未完整 fork 上游 UI。容器内保留上游 MIT 许可 `/app/GOACCESS-LICENSE`。

## 采集与口径

- Nginx 网关：80 端口接收原 cloudflared 转发；`/traffic` 交给独立监控，其余转到 Next.js。只从已验证的 host/Docker 网关 `172.18.0.1`、回环地址信任 `CF-Connecting-IP`，覆盖传入的 `X-Real-IP` / `X-Forwarded-For`。
- HTTP 日志：记录公开请求；去掉 query 和完整引荐地址，只保留引荐域名。排除后台、API、静态资源、Next.js 预取及 RSC 请求。原始 IP 仅在服务器私有日志内，保留 30 天；报表禁用 HOSTS 面板，监控页面不展示原始 IP。
- 浏览器上报：仅公开内容路由，支持 Next.js 内部导航；排除声明的机器人、webdriver 和 Do Not Track。以按日 HMAC 网络地址代替 IP。按地址、UA、日期估算访客数；多日 UV 是日访客数合计。
- HTTP 总请求与浏览器 PV 是两个渠道，不相加。AI UA 声明可以伪造，浏览器上报也不能证明一定是真人；界面明确展示“已识别”和估算口径。
- 搜索引擎引荐和 AI 平台引荐分别分组。AI 平台引荐是点击来源，AI 爬虫是抓取请求；搜索词和 AI 对话路径不持久化。
- 报表每分钟生成，今天、7 天、30 天三个窗口；超过列表条数上限的引荐流量单独显示，不归为直接访问。HTTP 原生详细报表是近 30 天窗口。
- `started.txt` 持久保存启动日期；早于上线的图表日期显示“—”，不伪造历史统计。
- Cloudflare 缓存命中或被边缘拦截的请求不一定到源站。完整边缘覆盖或高置信度 bot score 需要另接 Cloudflare 对应能力与权限，当前未启用付费功能。参见 [Cloudflare 检测机制](https://developers.cloudflare.com/bots/concepts/bot-detection-engines/)。

## 登录保护

PBKDF2-SHA256（随机盐，180,000 次）密码散列；独立随机 HMAC 会话密钥；Secure、HttpOnly、SameSite=Strict Cookie，12 小时到期；同源写入检查；网关按 IP 限流，应用对失败登录再限流。统计 API 与详细报表未登录返回 401，后台 noindex / no-store。采集 API 允许公开上报并限制请求大小与频率，数据属于浏览器声明，无法保证不可伪造。

## 生成凭据与部署

只能在本机 Docker 构建。生产 ECS 为 2 核 / 2 GiB、无 swap，禁止在服务器构建。

1. 在本机运行 `scripts/create-traffic-credentials.py --env-file .env.traffic --credentials-file <仓库外的私有文件>`。脚本拒绝覆盖已有文件，不输出秘密。只把散列与密钥的 `.env.traffic` 传到服务器；明文密码留在本机私有笔记。
2. 本机分别构建并测试 `wechat-web`、`wechat-traffic`、`wechat-traffic-gateway`；导出镜像，经 SSH 传输、服务器 `docker load`。
3. 备份原 Compose 文件、Git 状态和 Web 镜像。仅更新本次代码，不覆盖服务器运行时数据及私有 `.env`。
4. 创建 `/opt/wechat/data/private/traffic/logs`，`chown 101:1000`、`chmod 2770`。Nginx worker UID101 写日志，监控 GID1000 读/清理；SGID 保持新日志的共享组。创建 `state`，`chown 1000:1000`、`chmod 700`；`.env.traffic` 为 root 所有，模式 600。生产 Docker 网络变更时，先核对并修改信任网关地址，不能把全部网络加入信任。
5. 先启动 `traffic`（`--no-build --no-deps`），临时网关在回环端口 18080 验证路由、登录与主站。再替换 `web gateway`（同样 `--no-build --no-deps`）：Web 保留回环3500，网关接管80。API、数据库、采集及 AI worker 不重启。
6. 监控限制256MiB / 0.35CPU，网关48MiB / 0.25CPU及单worker，防止挤占现有服务。验收新镜像、内存、隧道和原站服务。

回滚：停止网关；恢复备份的 Compose 和 Web 镜像，然后仅 `up -d --no-build --no-deps web`，恢复原80监听。日志与监控 state 保留，后续可恢复监控。

## 验证

- 本机：`.venv/Scripts/python.exe -m pytest traffic/tests -q`。
- 实际解析引擎：GoAccess builder 容器挂载 `traffic` 到 `/app`，运行 `python /app/tests/verify_goaccess.py`。全部使用合成记录，不发送到生产监控。
- curl验收：`scripts/verify-traffic.py --url https://wechat.aim888888.xyz --credentials-file <私有凭据文件>`；测试登录、401、三种窗口、同源保护、非公开路径拒绝、原API大请求转发及主站SSR。Cookie和登录体仅放临时文件，不回显。
- `/traffic/health` 是不包含统计或凭据的公开健康检查；`/traffic/report` 与 `/traffic/api/summary?days=1` 必须登录。
