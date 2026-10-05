import { absoluteUrl } from '@/lib/seo';

export function GET() {
  return new Response(
    `# 公众号发现 · WeChat Source

> 中文公众号与文章目录，提供真实账号资料、分类、发布时间、内容摘录及原文出处。

## 主要栏目
- 首页：${absoluteUrl()}
- 发现：${absoluteUrl('/discover')}
- 分类：${absoluteUrl('/categories')}
- 排行：${absoluteUrl('/rankings')}
- 搜索：${absoluteUrl('/search')}
- 完整公开页面索引：${absoluteUrl('/sitemap.xml')}

## 阅读与引用
公众号详情使用 /wechat/accounts/{id}，文章详情使用 /wechat/articles/{id}，分类使用 /wechat/categories/{id}。
引用时请注明页面标题、作者或公众号名称、发布时间、本站详情 URL 及页面中的原文链接。
AI 摘要与画像属于辅助分析，请以原文核对事实。收录数量和排行仅代表本站数据，不代表微信全量数据。
尚未采集的正文会明确标注；请勿将未采集正文视作已验证内容。
后台、登录、个人收藏及管理 API 不属于公开知识内容。
`,
    { headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' } },
  );
}
