# 访问地域统计上线验收 · 2026-10-06

入口：<https://wechat.aim888888.xyz/traffic>，沿用已有独立登录。新增国家／地区、省／州、城市，分别显示浏览器PV和源站HTTP请求，支持今天、7天、30天。地区估算依据IP网络出口，不能认定访客实际位置，HTTP包含爬虫，两个渠道不相加。

## 实施

- 在现有Cloudflare域名启用“添加访问者位置标头”（Add visitor location headers）；未修改AI爬虫访问、安全、缓存及重定向策略。
- `traffic/gateway/default.conf` 只从原始连接的可信隧道/回环来源采纳CF国家、省／州和城市，覆盖客户端提供的X-Traffic位置头。公开日志末尾附加JSON位置字段，兼容既有COMBINED日志。
- `traffic/app.py` 浏览器事件只采用网关位置字段，仍使用匿名网络地址，不采集GPS，不存经纬度。
- `traffic/analyzer.py` 先创建完整有效记录的日志快照，GoAccess和地区统计读取同一份快照；发布前校对总数。忽略空白、损坏和未写完的记录，保留旧记录的未知位置，不猜历史。
- `traffic/static/dashboard.*`、`style.css` 增加三个地区面板及统计口径，安全文本输出，国家显示中文名称。
- `scripts/verify-traffic.py` 增加三窗口地区字段和计数校验；`traffic/tests/*` 增加真实解析引擎及回归测试。

位置采集的开始时间独立保存在私有state中的 `location-started.txt`，原监控开始时间和数据保留。账号/文章/分类页面及SEO策略未改动。

## 验证

| 项目 | 结果 |
| --- | --- |
| pytest | 17 passed，覆盖位置来源、隐私、损坏记录、持续写入时的快照一致性与原有登录保护 |
| 原生GoAccess | 带JSON尾部的7条HTTP记录、3条浏览器记录解析正确，AI/工具分类未改变 |
| 实际本机Nginx网关 | 可信CN/Zhejiang/Hangzhou和US/Virginia/Ashburn均进入统计；不可信JP/Tokyo伪造头成为未知；3PV、3HTTP在三级地理统计分别匹配 |
| 线上curl | 登录200；未登录summary/report 401；退出后401；详细报告200且no-store |
| 三窗口API | 1/7/30全部200；country/region/city字段齐全，国家统计与GoAccess原生总数一致 |
| 实际Cloudflare位置 | 一次本次验收浏览器访问与HTTP请求识别出新加坡/Singapore；省／州未提供，保持未知，没有写入合成位置 |
| 原站 | 首页curl仍有真实SSR内容、原有采集脚本；扫一扫/待分类文案未回退；原API的大请求仍转发到上游鉴权 |
| 界面 | 线上地区面板显示实际位置与历史未知，保存截图；未展示IP或凭据 |
| 审查 | 按代码审查技能进行独立多模型复核，修正计数快照问题后无剩余Critical/Important |

验收样例：HTTP337、浏览器PV3、按UA识别AI12。该数值会变化，包含此前诊断的伪造UA请求与验收访问，不能解读为12次官方AI爬虫访问或3位外部真人。地区功能上线前的335条HTTP记录及2条浏览器记录没有位置字段，显示未知是预期行为。

## 部署与回退

本机功能提交 `226dcc6`，服务器对应 `8889993`。监控和网关镜像全部在本机构建，经增量镜像包SHA256校验后加载；只更换这两个服务，Web/API/数据库/source及AI worker未重启。保留原服务资源限制，实测监控约39.8MiB，网关约2.9MiB，服务器约564MiB可用内存，cloudflared active。

回退备份：`/opt/wechat-backups/traffic-geo-226dcc6`。旧镜像标签为 `wechat-traffic:before-geo-226dcc6` 和 `wechat-traffic-gateway:before-geo-226dcc6`，恢复标签及对应代码后仅以 `--no-build --no-deps` 替换traffic/gateway即可；日志和state保留。服务器仍禁止原地构建。

地域精度及可用字段限制见 [Cloudflare官方说明](https://developers.cloudflare.com/network/ip-geolocation/)。CF不提供的地区显示未知；Cloudflare边缘未到源站的HTTP请求仍不在此日志统计中。下一轮GEO建议见 [GEO评估](geo-next-steps-2026-10-06.md)。
