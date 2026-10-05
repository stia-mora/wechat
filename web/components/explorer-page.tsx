import { cache } from 'react';
import { Explorer } from './explorer';
import { JsonLd } from './json-ld';
import { serverApi } from '@/lib/server-api';
import { itemList, pageMetadata } from '@/lib/seo';
import type { Account, Article, Category, Page } from '@/lib/types';

export type SearchParams = Record<string, string | string[] | undefined>;
export type ExplorerMode = 'discover' | 'search' | 'rankings';

const load = cache(async (mode: ExplorerMode, queryString: string) => {
  const query = new URLSearchParams(queryString);
  const isArticle = mode === 'search' && query.get('tab') === 'articles';
  query.delete('tab');
  query.set('limit', '12');
  const [result, categories] = await Promise.all([
    serverApi<Page<Account> | Page<Article>>(`/${isArticle ? 'articles' : 'accounts'}?${query}`),
    serverApi<Category[]>('/categories'),
  ]);
  return { result, categories, isArticle };
});

function queryFor(params: SearchParams, categoryId?: string) {
  const query = new URLSearchParams();
  for (const key of ['q', 'category', 'tab', 'sort', 'page', 'account_type', 'frequency']) {
    const raw = params[key];
    const value = Array.isArray(raw) ? raw[0] : raw;
    if (typeof value === 'string' && value) query.set(key, value);
  }
  if (categoryId) query.set('category', categoryId);
  if (query.has('category') && !/^[1-9]\d*$/.test(query.get('category')!)) query.delete('category');
  if (query.has('q')) query.set('q', query.get('q')!.slice(0, 200));
  const page = Number(query.get('page'));
  query.set(
    'page',
    String(Number.isFinite(page) ? Math.min(100000, Math.max(1, Math.floor(page))) : 1),
  );
  query.set('sort', query.get('sort') || 'recommended');
  return query;
}

export async function explorerMetadata(
  mode: ExplorerMode,
  params: SearchParams,
  categoryId?: string,
) {
  const query = queryFor(params, categoryId);
  const { categories } = await load(mode, query.toString());
  const category = categories.find((item) => String(item.id) === query.get('category'));
  const q = query.get('q');
  const name = category
    ? `${category.name}类公众号`
    : mode === 'search'
      ? q
        ? `搜索「${q}」· 公众号与文章`
        : '搜索公众号与文章'
      : mode === 'rankings'
        ? '公众号排行 · 信息源排行榜'
        : '发现公众号 · 中文信息源目录';
  const path = categoryId ? `/categories/${categoryId}` : `/${mode}`;
  if (categoryId) query.delete('category');
  if (query.get('page') === '1') query.delete('page');
  if (query.get('sort') === 'recommended') query.delete('sort');
  return pageMetadata(
    name,
    `浏览${category?.name || '中文'}信息源${q ? `中与「${q}」相关的` : '的'}真实简介、分类、历史文章和原文链接。${mode === 'rankings' ? '排行基于本站收录数据与关注行为。' : '所有条目均可打开独立详情页核对出处。'}`,
    path + (query.size ? `?${query}` : ''),
  );
}

export async function ExplorerPage({
  mode,
  params,
  categoryId,
}: {
  mode: ExplorerMode;
  params: SearchParams;
  categoryId?: string;
}) {
  const query = queryFor(params, categoryId);
  const { result, categories, isArticle } = await load(mode, query.toString());
  const selected = categories.find((item) => String(item.id) === query.get('category'));
  return (
    <>
      <JsonLd
        data={itemList(
          result.items,
          isArticle ? 'articles' : 'accounts',
          (Number(query.get('page')) - 1) * 12,
        )}
      />
      <Explorer
        key={`${mode}:${query}`}
        mode={mode}
        queryString={query.toString()}
        categoryId={categoryId}
        categoryName={selected?.name}
        initialResult={result}
        initialCategories={categories}
      />
    </>
  );
}
