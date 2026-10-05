# 列表变体、微信弹窗与精选分类验收（2026-10-05）

本轮三项修改已部署，生产镜像为 `wechat-web:b8428f2` 和 `wechat-api:b8428f2`。

## 修改文件

- `web/components/explorer-page.tsx`、`web/app/categories/page.tsx`：发现、排行、搜索、分类目录及分类详情的 canonical 始终使用栏目无参数 URL；带任意 query 的变体使用 `noindex, follow`。分类详情保留自身 ID，OG URL 与 canonical 一致。
- `web/components/explorer.tsx`：第 1 页导航省略 `page=1`、默认排序、默认账号标签，以及分类详情中多余的 category 参数；有实际筛选条件时保留筛选参数。
- `web/components/wechat-entry.tsx`：保持短入口按钮，将整个 dialog（扫码/复制/唤起说明及二维码）改为点击后才挂载；关闭后卸载，下次点击可重新打开。
- `web/components/ui.tsx`、`web/components/account-detail.tsx`、`backend/app/repository.py`：无分类时隐藏公开分类标签和面包屑项，并去掉推荐理由中的“待分类”回退文案。
- `backend/app/main.py`：精选查询只展示主分类为有效分类的公开账号，保持原有精选排序与分页。
- `backend/app/repair_featured_categories.py`：按既有精选账号真实 source_id 补齐缺失分类。新增粗分类“媒体与时政”，人民日报、央视新闻、新华社、人民网、中国政府网、中国新闻网、光明日报、中国日报、中国青年报归入此类；央视财经归入现有“财经”。仅更新当前精选、已公开、主分类为空的微信账号，保留已有分类，并刷新搜索索引。重复运行不再修改记录。
- `backend/tests/test_directory_discovery.py`：验证精选排除无分类账号；修复不会覆盖已有分类、不会修改非精选号，并可重复运行。
- `scripts/verify-list-variants.py`：使用 curl 获取原始 HTML、公开 API 和 sitemap，无 JavaScript，验证本轮要求。

缓存策略、重定向配置、既有分类/账号/文章 URL 结构均未修改；`sitemap.ts` 未修改。

## 三组 curl 验收

全部下载通过 curl 完成，原始 HTML 与响应头保存在本机忽略目录 `logs/list-variants-verification/`，结果在同目录 `report.json`。

1. URL 变体：13 个受测变体均返回 200，canonical 无 query，robots 均为 `noindex, follow`。例如：

   | 请求 | canonical |
   | --- | --- |
   | `/wechat/discover?page=1`、`?page=2`、`?sort=featured` | `https://wechat.aim888888.xyz/wechat/discover` |
   | `/wechat/discover?category=2`、`?account_type=媒体`、`?frequency=high` | `https://wechat.aim888888.xyz/wechat/discover` |
   | `/wechat/rankings?page=2&sort=active` | `https://wechat.aim888888.xyz/wechat/rankings` |
   | `/wechat/categories?page=2` | `https://wechat.aim888888.xyz/wechat/categories` |
   | `/wechat/categories/2?page=2`、`?sort=featured` | `https://wechat.aim888888.xyz/wechat/categories/2` |
   | `/wechat/search?q=人民日报`、`?q=`、`?tab=articles&page=2` | `https://wechat.aim888888.xyz/wechat/search` |

   五个干净栏目 URL 均保持可索引。sitemap 共 20,274 个 URL，带 query 的 URL 数量为 0。

2. 微信弹窗：首页原始 HTML 中“用微信扫一扫”出现 0 次，dialog 元素为 0。13 个列表变体及 `/wechat/accounts/7976`、`/wechat/accounts/21` 同样没有扫码说明或 dialog；详情正文继续由服务端输出。

3. 精选分类：首页原始 HTML 中“待分类”出现 0 次。11 个精选账号均有主分类及分类文字，分别为 9 个“媒体与时政”和 2 个“财经”；本次补齐 10 个原本缺分类的账号，经济日报既有“财经”分类保留。验收逐卡片核对了分类和指向独立详情的链接。

## 验证与部署

- TypeScript 检查、Linux Web 生产构建通过；独立代码复核通过。
- 针对本轮的两项数据库回归均通过，测试记录及设置修改全部通过事务回滚。
- 扩展运行的两个既有用例（目录浏览及 QR）因固定测试 source_id 已存在于生产数据而发生唯一约束冲突；本轮未修改这些既有用例，失败事务已回滚。这两项未计入本轮通过数量。
- 本机构建镜像，经 SHA-256 校验后在 ECS 加载；以 `--no-build --no-deps` 只替换 API/Web。运行容器镜像 ID 与已传送镜像一致；API 健康返回 200，数据库、源服务及 AI worker 保持运行。
- 备份保存在服务器 `/opt/wechat-backups/list-variants-20261005T1208Z/`，包含修改前源码、categories/official_accounts/search_documents 的数据备份、旧镜像标签及本轮镜像增量归档。运行期数据文件改动保留。

重跑命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/verify-list-variants.py
```
