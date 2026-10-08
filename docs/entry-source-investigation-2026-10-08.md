# 公众号单篇入口采集：2026-10-08 实测与方案筛选

## 结论与当前交付边界

目标是让每个目录公众号有一篇**属于该账号的真实文章**可供外链跳转，
不是开启全部账号的持续采集、历史回补、正文下载或 AI 解析。

本轮完成生产诊断、少量接口实测与 GitHub 筛选；没有启动 9,738 个账号的
全量采集，没有修改生产配置或部署应用。现有登录均失效，自动续期也失败，
因此还没有一条经过有效登录实测通过的替代采集链路。不能把 README 声明、
项目仍更新或 HTTP 200 当作当前生产采集成功的证据。

## 生产证据（北京时间 2026-10-08 晚间）

- 已审核目录账号 9,738 个，这 9,738 个全部没有非隐藏且 source_url 非空的文章；
  全站已审核账号中有 169 个已具备文章入口。
- `wechat-worker-1` 当前 exited，最后结束时间 2026-09-30 03:29:39 UTC，退出码 1，
  OOMKilled=false。最后日志包含 psycopg 无法解析数据库主机 `db` 的错误。
  重启策略为 unless-stopped、历史 RestartCount=16。不能据此认定硬件损坏、OOM，
  或断言是谁停止了容器。部署文档也记录过目录扩展时暂停文章 worker 的安排。
- 数据库记录的最后成功 sync 为 2026-09-30 03:31:27 UTC。
- 微信读书 5 个来源账号没有 healthy 状态：3 个 expired，2 个为早已结束冷却但
  状态尚未更新的 cooldown。历史能力记录中 256 个为 latest_only、8 个 unknown。
- 对账号 9、180 实测 `/web/shelf/sync` 均返回 `-2012`；同一凭据请求
  `/api/mp/cover` 返回 HTTP 401。无登录凭据请求两个目录账号也均为 401。
- 两个账号都存在续期凭据，但正常自动续期均返回 `-2013`；未恢复登录。
- 公众平台来源存在登录凭据，但已过期；实测 `/cgi-bin/appmsgpublish` 返回
  HTTP 200、业务错误 `200003`、0 组文章。这是登录错误，不是有效空列表。
- 从同一 ECS 请求搜狗文章搜索，新智元返回 8 条、惠省科技返回 10 条。
  后者前几条实际作者为金科财智、创新长沙等，属于关键词拆分后的其他账号。
  **搜索返回结果不等于该公众号有文章入口**，必须校验账号身份。

只输出账号编号、错误码、数量等诊断字段；没有输出 Cookie、Token、加密凭据。
`scripts/probe-entry-sources.py` 是可复用的只读探针，不添加订阅、不续期、不入库。

## GitHub 与近期官方项目资料

| 路线 | 当前资料证据 | 对本项目的判断 |
| --- | --- | --- |
| [tmwgsicp/wechat-download-api](https://github.com/tmwgsicp/wechat-download-api) | 当前代码使用 appmsgpublish，支持 fakeid + begin + count 获取文章；本项目已集成该来源 | 优先用重新扫码后的有效登录实测 count=1，不需要再安装同类系统。现有过期登录无法证明登录后可用 |
| [monkeychen/wx-kit](https://github.com/monkeychen/wx-kit) | 当前 v0.12.2 明确保留微信读书最新一篇能力，历史列表按账号受限，后台批量下载入口停用 | 可参考轻量 cover 流程，不是绕开微信读书的新数据源，不能替代失效登录 |
| [Pengyf04/weread-mp-fetcher](https://github.com/Pengyf04/weread-mp-fetcher) | 明确只面向十几个号以内，复用已登录浏览器；默认每日请求预算 40，遇验证码人工处理 | 不适合直接承担 9,738 个号的服务器无人值守采集 |
| [rachelos/we-mp-rss](https://github.com/rachelos/we-mp-rss/issues/469) | 2026-09-25 自托管用户报告 appmsgpublish/appmsg 的 200013 风控与降级逻辑缺陷 | 仍有维护/使用记录，但不能宣称换到它就解决上游限制；不直接替换生产系统 |
| [nobiyou/wx_channel](https://github.com/nobiyou/wx_channel/releases/tag/v5.7.10) | 2026-10-05 发布公众号推送列表凭据刷新与格式兼容修复；需已登录桌面微信打开对应页面 | 与微信读书不同的可验证候选，适合本地辅助采集；不是仅凭 9,738 个 biz 就能在 ECS 自动运行 |
| [WupfAGI/wechat-search-skill](https://github.com/WupfAGI/wechat-search-skill) | Tavily + 搜狗的搜索聚合，不是官方账号列表源 | 搜狗已实测能搜索，但小号样本误匹配；只做身份校验后的兜底，索引不保证全覆盖 |
| [redfox-data/redfox-python-sdk](https://github.com/redfox-data/redfox-python-sdk) | 商业数据平台 SDK 描述账号搜索、账号文章列表、文章详情，需付费服务 API Key | 可评估批量覆盖率，但本轮没有 Key、未实测；未购买或接入，不能将其标记为已验证可用 |
| [Wechat2RSS](https://wechat2rss.xlab.app/deploy/changelog) | 私有部署发布记录最近列出 v1.4.9（2026-07-31） | 商业部署候选，更新记录不是覆盖 9,738 个号的证据；未购买、未实测 |

排除旧方案：

- [cooderl/wewe-rss](https://github.com/cooderl/wewe-rss) 已于 2026-05-11 归档。
- [Moore-developers/moore-wechat-article-downloader](https://github.com/Moore-developers/moore-wechat-article-downloader)
  明确声明依赖的后台文章列表核心接口自 2026-07-30 关闭，暂时停止维护。

## 推荐的实施边界与验收

1. 先恢复一个公众平台来源登录，按已存 fakeid 直接请求一页，返回后只取一篇；
   选择大小账号等不同样本实测。若业务返回限流、登录或验证错误，暂停来源，
   不重复请求全部目录账号。微信读书仅作为有效登录后的备选。
2. 独立的“补入口”任务只选还没有可用链接的账号。取得标题、真实原文链接与
   上游实际返回的时间即可；不强制下载正文、不触发 AI、不改变关注/API 订阅，
   也不把目录账号改成持续采集账号。对需要书架会员关系的接口先验证要求，
   不能假设任意未订阅账号都可读取。
3. 每个账号一次成功后退出；断点记录每个账号的成功、待重试、来源暂停或无文章，
   单来源限速、冷却、登录失效熔断。不能将所有账号永久加入只有有限容量的书架。
4. 搜索兜底必须核对原文中的 `__biz` 与目录 source_id，不按名称模糊匹配直接入库。
   短链在取得页面后核对真实作者身份；遇验证页面停止，不能把页面状态 200 当成功。
5. 已注销、从未发文、上游未收录或不公开文章的账号应如实记录“暂无入口”，
   不伪造文章、不承诺必然 100% 补齐。成功标准是可打开且作者身份匹配，
   而不是任务成功数或数据库 source_url 非空。

当前应用的文章入口改动在本地提交 `7a98bfe`，本轮没有部署到生产。
生产 Git 当前为 `ab079ff`；不得把本地完成等同于服务器已生效。
