# 2026-10-11 网站运行时 OOM 故障与恢复记录

## 已确认的故障，尚未确认的触发点

前一轮启动的 kernel global OOM 日志记录（北京时间）：

- 03:02:57 杀死 `next-server`，容器 `840ddccea7ca`，对应 `wechat-web-1`。
- 03:07:31 杀死 `uvicorn`，容器 `5044dc43d4de`，对应 `wechat-api-1`。
- 当时 Swap 为 0，进程表中有大量 PostgreSQL 后端。

这是运行时全局内存不足，不是仅凭网页错误推测服务器损坏。PostgreSQL 共享
RSS 不能简单相加，没有当时完整请求/连接曲线，具体触发请求仍未确认；不能
断言某个查询、采集或模型调用就是直接原因。

服务器 14:32:45 已重启，本轮排查没有执行主机重启。14:33 公网曾返回
Cloudflare 530 / `error code: 1033`，随后服务完成启动恢复。云控制台“运行中”
只证明虚拟机运行，不证明应用、Docker 或隧道可用。

明确的配置风险：2 GiB 主机没有 Swap，主要内容服务无内存上限；API 每次
请求直接新建数据库连接，没有连接槽位和 SQL 超时；PostgreSQL 允许 100 个
连接、SQL 不限时间；动态请求没有入口并发保护。这些风险已修复。
本轮没有在 ECS 上构建镜像；此前构建事故不能因本次证据自动改称“确认 OOM”。

## 发布范围与备份

生产从原 HEAD `ab079ff` 单独制作热修复，运行时提交 `e826cf7`，其中应用
保护提交 `519ddc7`；主分支对应提交 `8e49b10`、`fab6cdf`。
没有混入尚未验收的补入口队列、扫码管理、桌面采集或文章外链功能。
没有安装根证书、调整微信代理、启动新增队列或重投 AI 任务。

备份位于 `/opt/wechat-backups/oom-20261011`：原代码归档、Compose 文件、
数据库自定义格式备份及可读索引、旧内核日志、原配置和容器记录。
`pg_restore -l` 验证通过；没有还原数据库。原数据库卷
`wechat_postgres_data`、运行报告、来源凭据、流量日志、迁移目录均保留。

API/网关镜像本地构建、SSH 传输、服务器加载；归档 SHA-256：
`9f403db1cf5c9958aeea1ad45e8c6581c96ed95aecf359be9093ac13e1d21542`。
本地/服务器 `docker image inspect .Id` 及层列表一致：

- API：`sha256:a81f4cddbe5d64f42ace1ce6541037b991445dd821e972a2d15d84573782d7c3`
- 网关：`sha256:57929675c3b755d51aee82b042fa4461f45b539016857c4c7be12cbb85c81618`
- Web 未重建，复用原镜像：
  `sha256:7b36e75f95f142e88cd07fb2e2ebf2c125e131a293bae995d155b22ecc873acc`

必须比较相同摘要字段。Compose 标签、OCI 配置摘要与 `.Id` 可能不同；
第一次核对因混比安全停止，确认本地和服务器相同字段一致后才继续替换。

## 已生效的保护

| 服务 | RAM 上限 | RAM + Swap 上限 | 其他保护 |
| --- | --- | --- | --- |
| API | 256 MiB | 384 MiB | 并发 32，backlog 64，keep-alive 2 秒 |
| Web | 384 MiB | 512 MiB | 直接启动 Node，旧生代堆 192 MiB |
| PostgreSQL | 384 MiB | 512 MiB | 总连接 32，work_mem 2MB，关闭并行查询/JIT |
| 每个 AI worker | 128 MiB | 192 MiB | 仍为 5 个，请求启动间隔仍为 12 秒 |
| 来源桥接 | 192 MiB | 256 MiB | 来源镜像/凭据不变 |
| 流量后台 | 256 MiB | 原有默认策略 | CPU 0.35，未重建/重启 |
| 网关 | 48 MiB | 默认 96 MiB | CPU 0.25，动态并发全站 24、单 IP 8 |

API 最多同时占用 6 个数据库连接，等槽位最多 2 秒，连接超时 5 秒；
API SQL 超时 15 秒，锁等待 5 秒，闲置事务 60 秒。
PostgreSQL 默认 SQL 超时 30 秒、闲置事务 60 秒、维护内存 32 MiB；
共享缓冲区仍为 128 MiB。AI 网络请求在事务外，没有改变模型或请求节奏。

数据库忙、不可连接、查询/锁超时返回脱敏 503 和 `Retry-After: 2`，异常
路径释放槽位。Uvicorn/网关达到并发上限也返回 503，而不是无限积累请求。
过载保护不保证任意并发全部成功；原有用户 API 计量/套餐限流没有改动。
`/wechat/_next/static/`、`/traffic` 不占动态并发预算，流量原有登录/事件限流保留。
旧 article worker、目录进程保持停止。

活跃服务 RAM 上限合计约 2160 MiB，尚未包含主机服务，超过物理可用内存。
上限不是内存预留量，不能把它当作满载安全容量。Swap 仅应急，不能据此
增加 worker；正常请求持续大量 503、Swap 持续增大或可用内存长期不足
256 MiB 时，应进一步减负载或扩容，不能取消保护。

## Swap 持久化

实际文件 `/var/lib/wechat/swapfile`，2 GiB，权限 600；安装前确认文件、
同名 unit 和 sysctl 文件均不存在，没有覆盖原文件，没有改变 `/etc/fstab`。
只在确认目标不存在、磁盘空间充分的新主机上执行一次：

```sh
set -eu
test ! -e /var/lib/wechat/swapfile
test ! -e /etc/systemd/system/var-lib-wechat-swapfile.swap
test ! -e /etc/sysctl.d/90-wechat-memory.conf
install -d -m 700 /var/lib/wechat
fallocate -l 2G /var/lib/wechat/swapfile
chmod 600 /var/lib/wechat/swapfile
mkswap /var/lib/wechat/swapfile
install -m 644 scripts/ops/var-lib-wechat-swapfile.swap /etc/systemd/system/var-lib-wechat-swapfile.swap
install -m 644 scripts/ops/90-wechat-memory.conf /etc/sysctl.d/90-wechat-memory.conf
systemctl daemon-reload
systemctl enable --now var-lib-wechat-swapfile.swap
sysctl -p /etc/sysctl.d/90-wechat-memory.conf
swapon --show
free -m
```

本机确认 unit active/ enabled，Swap 优先级 10，`vm.swappiness=10`。
没有为验证持久化额外重启生产主机。

## 验收（北京时间 14:49—14:56）

- 主分支后端 129 项、生产基线后端 82 项通过；前端类型、Compose、Nginx
  配置检查通过；独立代码审查没有发现阻断问题。
- 本地 API 48 请求突发：27 个 200、21 个 503，压力后健康检查 200。
- 本地延迟上游：动态路径 24 请求为 8 个 200、16 个 503；静态资源、
  流量后台分别 24 请求，均全部 200。
- 生产源站/公网 `/wechat`、`/wechat/library`、`/wechat/api/health`、
  `/traffic` 均 200，首页引用的真实静态资源 200。
- 生产 API 40 同时建连全部触发 Uvicorn 503；24 请求得到 12 个 200、
  12 个 503（连接槽位等待超时）。这是预期过载降级，不能要求突发全成功。
- 生产网关 24 请求：8 个 200、16 个 503；API 数据库连接峰值 6，不含
  监测连接。压力后健康检查恢复 200，正常 2 请求均 200。
- API 会话实测超时 15 秒/5 秒/1 分钟，PostgreSQL 总连接实测 32。
- 压力后可用内存约 785 MiB，首次 Swap 使用约 94 MiB；14:56 再次验证
  脱敏 503、Retry-After 和恢复成功后，Swap 约 196 MiB，可用 RAM 仍约
  785 MiB。首次短时 vmstat 无持续换入/换出；Web/API/DB/网关无 OOM 标记、无重启。
  复核结果留在备份目录的 `acceptance-after.txt`，不能忽略 Swap 的增长。
- DB 重启前 4 种 AI 任务均无 queued/running；5 个旧 AI 进程因数据库连接
  断开各自动重启一次，镜像未改变，此后仍为 5 个。未重新投放任务。
- 原卷中存在 10,002 个账号、10,640 篇文章；验收时运行 AI 任务 0。
- 14:32:45 重启后内核日志无新 OOM，Cloudflare Tunnel active。

这是短时验收，不是长期满载稳定性证明。

## 回滚与再发处理

1. 先查源站、公网、内存、Swap、容器 OOM/重启、隧道状态，保留证据。
2. 仅 API 新镜像异常时，将 `wechat-api:before-oom-20261011` 标记回
   `wechat-api:latest`，用 `docker compose -p wechat -f compose.yaml -f compose.server.yaml up -d --no-build --no-deps api`
   只替换 API。回退会失去应用连接槽位保护，必须保留其他保护并检查 DB 负载。
3. 网关确需回退时用 `wechat-traffic-gateway:before-oom-20261011`，仅替换
   gateway；旧镜像无动态并发保护，必须减负载，不是永久修复。
4. Web 未换镜像，也保留 `wechat-web:before-oom-20261011`。不重建、不启动
   旧 crawler，不用全服务 up 顺带更新依赖。
5. 源码用聚焦的 git revert，不 reset --hard，不覆盖运行数据。代码回滚
   不需要 pg_restore --clean，不删除备份/迁移目录。
6. 不盲目 swapoff。须先确认 Swap 为 0 或 RAM 余量充分、暂停有关负载并评估
   风险；本次无需移除 Swap 或内存保护。

以后验收必须同时检查资源与公网，不以“容器 Up/云主机运行中”交付。
若再发，先保留时间/请求/进程证据，不未经确认反复重启或恢复危险构建。
