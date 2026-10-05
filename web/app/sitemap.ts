import type { MetadataRoute } from 'next';
import { serverApi } from '@/lib/server-api';
import { absoluteUrl } from '@/lib/seo';
import type { Category } from '@/lib/types';

export const dynamic = 'force-dynamic';
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [catalog, categories] = await Promise.all([
    serverApi<{
      accounts: { id: number; updated_at: string }[];
      articles: { id: number; updated_at: string }[];
    }>('/public-sitemap'),
    serverApi<Category[]>('/categories'),
  ]);
  return [
    ...['', '/categories', '/discover', '/rankings', '/search'].map((path) => ({
      url: absoluteUrl(path),
    })),
    ...categories.map((category) => ({ url: absoluteUrl(`/categories/${category.id}`) })),
    ...catalog.accounts.map((account) => ({
      url: absoluteUrl(`/accounts/${account.id}`),
      lastModified: account.updated_at,
    })),
    ...catalog.articles.map((article) => ({
      url: absoluteUrl(`/articles/${article.id}`),
      lastModified: article.updated_at,
    })),
  ];
}
