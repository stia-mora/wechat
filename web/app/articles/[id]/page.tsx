import ArticleDetail from '@/components/article-detail';
import { JsonLd } from '@/components/json-ld';
import { serverApi } from '@/lib/server-api';
import { absoluteUrl, pageMetadata } from '@/lib/seo';
import type { Article } from '@/lib/types';

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const article = await serverApi<Article>(`/articles/${encodeURIComponent(id)}`);
  const metadata = pageMetadata(
    `${article.title} · ${article.account_name}`,
    (
      article.ai_summary?.summary ||
      article.summary ||
      article.content_text ||
      `${article.account_name}发布的文章，查看发布时间、内容与原文出处。`
    ).slice(0, 160),
    `/articles/${article.id}`,
  );
  metadata.openGraph = {
    ...metadata.openGraph,
    type: 'article',
    publishedTime: article.publish_time || undefined,
    authors: [article.author || article.account_name],
  };
  return metadata;
}

export default async function Page({ params }: Props) {
  const { id } = await params;
  const article = await serverApi<Article>(`/articles/${encodeURIComponent(id)}`);
  return (
    <>
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@type': 'Article',
          headline: article.title,
          description: article.ai_summary?.summary || article.summary || undefined,
          datePublished: article.publish_time || undefined,
          dateModified: article.updated_at || article.publish_time || undefined,
          author: {
            '@type': 'Organization',
            name: article.author || article.account_name,
            url: absoluteUrl(`/accounts/${article.account_id}`),
          },
          url: absoluteUrl(`/articles/${article.id}`),
          mainEntityOfPage: absoluteUrl(`/articles/${article.id}`),
          isBasedOn: article.source_url,
          image: article.cover_url || absoluteUrl('/og-image.png'),
          inLanguage: 'zh-CN',
        }}
      />
      <ArticleDetail key={article.id} initialArticle={article} />
    </>
  );
}
