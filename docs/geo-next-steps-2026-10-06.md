# GEO 诊断评估与下一轮优化建议 · 2026-10-06

依据用户提供的桌面诊断文档，结合源码和本机 curl 抽查。本轮只上线访问地域统计；以下为建议，未调整内容展示、索引、缓存、重定向或 Cloudflare 爬虫规则。

## 再次确认的现象

- `/wechat/accounts/46` 和 `/wechat/discover?page=2` 的 HTML 确有 `http://localhost:5500/api/image`。源码直接使用 `avatar_url`，账号 JSON-LD 也直接使用该值，需在数据出口统一规范化。
- `/wechat/articles/19241` 200且含“正文尚未采集”，没有noindex；`/wechat/categories/40` 200且可索引。报告的全站薄页数量是抽样推断，本轮没有把“约9,700”当作数据库精确计数。
- 账号46与发现第2页的HTML没有可抓取的 `?page=` 链接；当前 Pagination 是交互式客户端组件。
- `/wechat/about` 和 `/wechat/favicon.ico` 均404。
- 用伪造UA访问文章3509：GPTBot、ClaudeBot、Bytespider为403；OAI-SearchBot、ChatGPT-User、PerplexityBot为200。该结果证明当前边缘响应差异，不能证明官方IP请求的结果，也不代表页面已被AI引用。
- HTTP首页仍200，根robots仍302。分页的noindex与干净canonical符合上一轮明确要求，本轮没有反向修改。

## 推荐实施顺序

| 顺序 | 改什么 | 为什么优先 | 无JS验收 |
| --- | --- | --- | --- |
| 1 | 修图片URL，在API/展示边界统一排除localhost和内网主机，升级HTTPS；JSON-LD使用公网绝对URL | 真实破图影响用户和可引用实体资料，修复范围小 | 核心账号及分类HTML无localhost/http图片；图片返回200；JSON-LD图片可访问 |
| 2 | 建立公开内容的索引资格，元信息和sitemap使用同一条件 | 减少空模板占据入口，保留有原创资料的实体页 | 缺乏有效内容页noindex且不在sitemap；有文章/原创画像页仍index |
| 3 | 修真实内链与目录分页；分类标签链接分类；面包屑为首页→分类→账号→文章，增加BreadcrumbList | 让搜索与AI能顺着主题关系发现内容 | HTML含真实a href分页/分类/账号链接，面包屑与JSON-LD一致 |
| 4 | 重点打造有独立信息的账号与专题页 | 解决“为什么引用本站”而非仅“能否抓取” | 名称、定位、适读人群、证据文章、更新时间、分析方法和局限均在HTML |
| 5 | 增加关于、数据/排行方法、隐私、版权与联系页；补favicon | 让统计口径与负责主体有可核实出处 | 页脚可达，内容真实，联系信息由运营方确认，不能编造资质与作者 |
| 6 | 拆分并预生成sitemap；再做搜索索引和有限公开缓存 | 降低抓取成本，避免把之前的空状态重新长期缓存 | sitemap索引及分片200；loc都符合索引资格；lastmod来自真实内容变化 |

索引资格应看独有价值，不采用“0篇文章就全部删掉”“分类不足3个账号就全部noindex”的机械阈值。已分类且有原创账号画像或人工说明的资料页，即使暂无文章也可有价值。文章没有全文，但有核实过的原创摘要、作者/时间和原文证据，也不必自动排除。真正只剩占位文案的页面先noindex，保留访问，资料补齐后再恢复收录。

## 不能直接照搬的建议

**训练爬虫与检索引用分开。** 搜索与用户代理当前已有200通路。优先核实其官方请求在Cloudflare与源站的状态、抓取正文及来源回访；是否开放训练型GPTBot/ClaudeBot/CCBot，需要独立内容政策。不要把“训练抓取更多”当成“更容易被搜索引用”。根robots/llms对不同UA的可达性值得修，但不能绕过整站安全策略来解决。Cloudflare也分别定义Search、Agent和Training行为：[Cloudflare AI bot分类](https://developers.cloudflare.com/bots/concepts/bot/#ai-bots)。

**分页与筛选不是同一类页面。** 过滤、排序、搜索变体继续noindex。报告建议基础目录分页自引用canonical，这与上一轮“page全部canonical回首页”的约定不同。若下一轮采用可索引目录分页，可以只针对基础分页换策略，并保留筛选规则；或另建清晰的目录入口，维持现有列表策略。Google官方建议分页以a href相连且每页使用自己的canonical；`rel=prev/next`不再被Google用于识别分页。依据：[Google分页指南](https://developers.google.com/search/docs/specialty/ecommerce/pagination-and-incremental-page-loading)。

**全文转成摘要应形成自己的编辑产品。** 推荐“本站核心观点/证据提要/适用人群/局限/原文出处”，避免只将原文换一种措辞。授权信息与展示政策需要逐源管理；200–300字不是通用的版权安全线。对仅复制原文、没有本站信息增量的页面，应评估摘要展示或指向原文的canonical，不能把全部文章一刀切改成跨域canonical。

**不优先堆AI专用文件与Schema。** llms.txt可以补真实数据口径和重点栏目；llms-full.txt、FAQ、Dataset不是必做项，更不能对不存在的内容标注。Google说明AI搜索沿用基础SEO，没有额外专用文件或结构化数据要求，符合条件也不保证收录/展示。依据：[Google AI功能与网站](https://developers.google.com/search/docs/appearance/ai-features)。这不代表其他AI产品有完全相同规则。

## 值得补的独有内容

- 以用户问题组织20–50个专题，例如“人工智能入门适合关注哪些公众号”“科技媒体与研究机构如何区分”。每个条目有具体理由、证据文章、适读人群与最近复核日期，避免批量生成空泛推荐。
- 账号画像给出可引用的简短事实摘要：运营类型、主要领域、更新频率的观测区间、分析使用的样本数；机器判断标注置信度/局限，不把AI评分当客观认证。
- 排行显示名次、分数、时间窗与方法链接；发现页强调新发现/编辑推荐，避免三个栏目总是同一批条目。
- 先核对文章发布日期、原文链接、作者实体，再让publisher、dateModified、sitemap lastmod使用相同数据来源；不能为了补字段捏造日期。

## 用什么判断改善有效

`/traffic`用于看浏览器PV、来源域名、AI平台引荐、声明的爬虫与IP出口地区。实际搜索曝光、已编入索引比例和抓取异常应结合Search Console/搜索资源平台；监控里出现GPTBot不代表AI已引用，AI引荐缺失也可能只是没有Referer。按上线日期比较重点内容页面的收录、搜索落地页和AI引荐变化，区分本次验收访问及外部访问。

当前优先建议实施前三项：图片修复、索引资格、真实内链；同时准备少量高质量专题与透明方法说明。性能、HTTPS与根路径入口另作部署批次，分别验收，避免一次改变过多策略。
