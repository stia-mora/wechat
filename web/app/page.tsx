import Home from '@/components/home';
import { JsonLd } from '@/components/json-ld';
import { serverApi } from '@/lib/server-api';
import { absoluteUrl, pageMetadata } from '@/lib/seo';
import type { Account, Article, Category, Page } from '@/lib/types';

export const metadata = pageMetadata(
  '公众号发现 · 中文优质信息源',
  '浏览中文公众号的真实简介、分类与文章，发现值得长期关注的信息源，并通过原文链接核对出处。',
  '',
);

export default async function Page() {
  const [accounts, articles, categories, stats] = await Promise.all([
    serverApi<Page<Account>>('/accounts?limit=12&sort=featured'),
    serverApi<Page<Article>>('/articles?limit=5'),
    serverApi<Category[]>('/categories'),
    serverApi<{
      accounts: number;
      articles: number;
      last_crawled_at: string | null;
      last_article_at: string | null;
    }>('/stats'),
  ]);
  return (
    <>
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@type': 'WebSite',
          name: '公众号发现',
          url: absoluteUrl(),
          inLanguage: 'zh-CN',
          potentialAction: {
            '@type': 'SearchAction',
            target: {
              '@type': 'EntryPoint',
              urlTemplate: absoluteUrl('/search?q={search_term_string}'),
            },
            'query-input': 'required name=search_term_string',
          },
        }}
      />
      <Home
        initialAccounts={accounts}
        initialArticles={articles}
        categories={categories}
        stats={stats}
      />
    </>
  );
}
