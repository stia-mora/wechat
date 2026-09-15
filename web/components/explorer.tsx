'use client';
import { useSearchParams, useRouter } from 'next/navigation';
import { api, useApi } from '@/lib/api';
import { useState } from 'react';
import type { Account, Article, Category, Page } from '@/lib/types';
import { AccountCard, ArticleRow, Empty, ErrorState, Loading, Pagination, SearchBox } from './ui';

export function Explorer({ mode = 'discover' }: { mode?: 'discover' | 'search' | 'rankings' }) {
  const [discoveryMessage, setDiscoveryMessage] = useState('');
  const [requesting, setRequesting] = useState(false);
  async function discover(query: string) {
    setRequesting(true);
    try {
      const result = await api<{ message: string }>('/discovery-requests', {
        method: 'POST',
        body: JSON.stringify({ query }),
      });
      setDiscoveryMessage(result.message);
    } catch (e) {
      setDiscoveryMessage((e as Error).message + '；首次申请发现请先登录本站');
    } finally {
      setRequesting(false);
    }
  }
  const params = useSearchParams(),
    router = useRouter();
  const q = params.get('q') || '',
    category = params.get('category') || '',
    tab = params.get('tab') || 'accounts',
    sort = params.get('sort') || 'recommended',
    page = Number(params.get('page')) || 1;
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== 'page') next.delete('page');
    router.push('?' + next.toString(), { scroll: false });
  };
  const query = new URLSearchParams({ q, sort, page: String(page), limit: '12' });
  if (category) query.set('category', category);
  if (params.get('account_type')) query.set('account_type', params.get('account_type')!);
  if (params.get('frequency')) query.set('frequency', params.get('frequency')!);
  const isArticle = tab === 'articles' && mode === 'search';
  const accounts = useApi<Page<Account>>(!isArticle ? '/accounts?' + query : null),
    articles = useApi<Page<Article>>(isArticle ? '/articles?' + query : null),
    categories = useApi<Category[]>('/categories');
  const result = isArticle ? articles : accounts,
    total = result.data?.total || 0;
  const selectedCategory = categories.data?.find((c) => String(c.id) === category);
  const parentCategory = selectedCategory?.parent_id ? String(selectedCategory.parent_id) : category;
  const root = categories.data?.filter((c) => !c.parent_id) || [],
    children = categories.data?.filter((c) => String(c.parent_id) === parentCategory) || [];
  return (
    <>
      <section className="pb-9 pt-12">
        <span className="eyebrow">
          {mode === 'rankings' ? 'THE SOURCE RANKING' : 'EXPLORE THE SOURCE'}
        </span>
        <h1 className="mb-4 mt-3 text-3xl font-semibold">
          {mode === 'search'
            ? q
              ? `搜索「${q}」`
              : '搜索你的下一处信息源'
            : mode === 'rankings'
              ? '信息源排行榜'
              : '发现值得长期关注的声音'}
        </h1>
        <p className="mb-7 text-sm text-stone-500">
          {mode === 'rankings'
            ? '基于平台收录数据与真实关注行为，展示可解释的排序。'
            : '循着兴趣探索，把有价值的内容留在自己的阅读地图里。'}
        </p>
        {mode === 'search' && (
          <div className="max-w-3xl">
            <SearchBox key={q} initial={q} />
          </div>
        )}
      </section>
      {mode === 'search' && (
        <div className="tabs mb-8">
          <button
            className={!isArticle ? 'selected' : ''}
            onClick={() => update('tab', 'accounts')}
          >
            公众号
          </button>
          <button className={isArticle ? 'selected' : ''} onClick={() => update('tab', 'articles')}>
            文章
          </button>
        </div>
      )}
      <div className="grid gap-8 lg:grid-cols-[200px_1fr]">
        <aside aria-label="筛选公众号" className="self-start lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:overflow-y-auto lg:overscroll-contain">
          <h2 className="mb-4 text-sm font-semibold">内容领域</h2>
          <div className="flex flex-wrap gap-2 lg:flex-col">
            <button
              onClick={() => update('category', '')}
              className={`rounded-md px-3 py-2 text-left text-sm ${!category ? 'bg-[#e9eee2] text-[#245745]' : 'text-stone-500 hover:bg-stone-100'}`}
            >
              全部领域
            </button>
            {root.map((c) => (
              <button
                key={c.id}
                onClick={() => update('category', String(c.id))}
                className={`flex justify-between gap-6 rounded-md px-3 py-2 text-left text-sm ${category === String(c.id) ? 'bg-[#e9eee2] text-[#245745]' : 'text-stone-500 hover:bg-stone-100'}`}
              >
                {c.name}
                <span className="text-xs text-stone-400">{c.account_count}</span>
              </button>
            ))}
          </div>
          {children.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {children.map((c) => (
                <button key={c.id} aria-pressed={category === String(c.id)} className={`tag ${category === String(c.id) ? 'ring-1 ring-[#245745]' : ''}`} onClick={() => update('category', String(c.id))}>
                  {c.name}
                </button>
              ))}
            </div>
          )}
          {!isArticle && (
            <>
              <label className="field mt-8">
                账号类型
                <select
                  value={params.get('account_type') || ''}
                  onChange={(e) => update('account_type', e.target.value)}
                >
                  <option value="">不限</option>
                  {[
                    '媒体',
                    '个人IP',
                    '企业',
                    '高校',
                    '政府',
                    '研究机构',
                    '垂直社区',
                    '品牌账号',
                  ].map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </label>
              <label className="field mt-6">
                近 30 天更新
                <select
                  value={params.get('frequency') || ''}
                  onChange={(e) => update('frequency', e.target.value)}
                >
                  <option value="">不限频率</option>
                  <option value="high">高频 · 20 篇以上</option>
                  <option value="medium">中频 · 5—19 篇</option>
                  <option value="low">低频 · 0—4 篇</option>
                </select>
              </label>
            </>
          )}
          {mode === 'rankings' && (
            <p className="mt-8 border-t border-stone-200 pt-5 text-xs leading-6 text-stone-500">
              综合分由内容质量、更新活跃、资料完整度、关注行为加权计算。未完成 AI 分析的质量项为
              0。所有数量仅指本站收录，不代表微信全量数据。
            </p>
          )}
        </aside>
        <section>
          <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
            <span className="text-sm text-stone-500">
              共 <strong className="font-mono text-stone-800">{total}</strong>{' '}
              {isArticle ? '篇文章' : '个公众号'}
            </span>
            <label className="flex items-center gap-2 text-xs text-stone-500">
              排序
              <select
                value={sort}
                onChange={(e) => update('sort', e.target.value)}
                className="rounded-md border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700"
              >
                {(isArticle
                  ? [
                      ['latest', '最新发布'],
                      ['popular', '最多收藏'],
                      ['recommended', '内容推荐'],
                    ]
                  : [
                      ['recommended', '综合推荐'],
                      ['latest', '最新更新'],
                      ['active', '更新活跃'],
                      ['quality', '内容质量'],
                      ['popular', '热门关注'],
                      ['growth', '近期增长'],
                      ['relevance', '相关度'],
                    ]
                ).map(([v, t]) => (
                  <option key={v} value={v}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {result.loading ? (
            <Loading />
          ) : result.error ? (
            <ErrorState message={result.error} retry={result.reload} />
          ) : !total ? (
            <Empty title="没有找到匹配的内容" />
          ) : isArticle ? (
            <div>
              {articles.data?.items.map((a) => (
                <ArticleRow key={a.id} article={a} />
              ))}
            </div>
          ) : (
            <div className="grid gap-5 xl:grid-cols-2">
              {accounts.data?.items.map((a, i) => (
                <AccountCard
                  key={a.id}
                  account={a}
                  rank={mode === 'rankings' ? (page - 1) * 12 + i + 1 : undefined}
                />
              ))}
            </div>
          )}
          <Pagination
            page={page}
            total={total}
            limit={12}
            onChange={(p) => update('page', String(p))}
          />
          {mode === 'search' && !isArticle && q.length >= 2 && !result.loading && total === 0 && (
            <div className="mt-6 rounded-xl border border-stone-200 bg-white p-5">
              <p className="mb-3 text-sm text-stone-500">
                本站尚无匹配结果。可申请发现公众号，找到后进入采集与审核流程。
              </p>
              <button
                disabled={requesting}
                className="button secondary"
                onClick={() => discover(q)}
              >
                申请发现并采集
              </button>
              {discoveryMessage && (
                <p role="status" className="mt-3 text-sm">
                  {discoveryMessage}
                </p>
              )}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
