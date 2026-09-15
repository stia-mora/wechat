'use client';
import { use, useState } from 'react';
import Link from 'next/link';
import { ArrowUpRight, Check, Minus } from '@phosphor-icons/react';
import { useApi, date } from '@/lib/api';
import type { Account, Article, Page } from '@/lib/types';
import {
  AccountCard,
  ActionButton,
  ArticleRow,
  Avatar,
  Empty,
  ErrorState,
  Loading,
  Pagination,
  SectionTitle,
} from '@/components/ui';
export default function AccountPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params),
    [page, setPage] = useState(1),
    [sort, setSort] = useState('latest'),
    [keyword, setKeyword] = useState('');
  const account = useApi<Account>('/accounts/' + id),
    articles = useApi<Page<Article>>(
      `/articles?account_id=${id}&page=${page}&sort=${sort}&q=${encodeURIComponent(keyword)}&limit=10`,
    );
  if (account.loading) return <Loading />;
  if (account.error) return <ErrorState message={account.error} retry={account.reload} />;
  const a = account.data;
  if (!a) return null;
  const profile = a.profile;
  return (
    <>
      <div className="flex gap-2 py-7 text-xs text-stone-500">
        <Link href="/discover">发现</Link>
        <span>/</span>
        <Link href={'/discover?category=' + a.primary_category_id}>{a.category || '待分类'}</Link>
        <span>/</span>
        <span>{a.name}</span>
      </div>
      <section className="rounded-xl border border-stone-200 bg-white p-6 md:p-9">
        <div className="flex flex-wrap items-start justify-between gap-7">
          <div className="flex min-w-0 gap-5">
            <Avatar account={a} large />
            <div>
              <h1 className="text-2xl font-semibold md:text-3xl">{a.name}</h1>
              <p className="mt-3 text-sm text-stone-500">
                {a.wechat_id || '微信公众号'} · {a.category || '待分类'}
                {a.account_type ? ' / ' + a.account_type : ''}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {a.tags.map((t) => (
                  <Link href={'/search?q=' + encodeURIComponent(t)} className="tag" key={t}>
                    {t}
                  </Link>
                ))}
              </div>
            </div>
          </div>
          <div className="flex gap-3">
            <ActionButton kind="follow" targetId={a.id} initial={a.following} />
            <ActionButton kind="account" targetId={a.id} initial={a.collected} />
          </div>
        </div>
        {a.description?.trim() && (
          <p className="mt-7 max-w-3xl text-sm leading-7 text-stone-600">
            {a.description}
          </p>
        )}
        <div className="mt-7 flex flex-wrap items-center justify-between gap-5 border-t border-stone-100 pt-6">
          <div className="flex flex-wrap gap-7 text-xs text-stone-500">
            <span>
              <strong className="mr-2 font-mono text-xl font-medium text-stone-800">
                {a.article_count}
              </strong>
              篇已收录
            </span>
            <span>
              <strong className="mr-2 font-mono text-xl font-medium text-stone-800">
                {a.articles_last_30d}
              </strong>
              篇近 30 天
            </span>
            <span>
              <strong className="mr-2 font-mono text-xl font-medium text-stone-800">
                {a.following_count}
              </strong>
              人站内关注
            </span>
          </div>
          {a.source_url && (
            <a
              href={a.source_url}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1 text-xs text-[#245745]"
            >
              查看原公众号 <ArrowUpRight size={14} />
            </a>
          )}
        </div>
      </section>
      <div className="mt-8 grid items-start gap-8 lg:grid-cols-[1fr_330px]">
        <div>
          <section className="rounded-xl border border-stone-200 bg-white p-7">
            <div className="mb-5 flex items-center gap-3">
              <h2 className="text-xl font-semibold">账号内容画像</h2>
              <span className="tag">AI 分析</span>
            </div>
            {profile ? (
              <>
                <p className="text-sm leading-7 text-stone-600">{profile.profile_summary}</p>
                <div className="mt-7 grid gap-8 sm:grid-cols-2">
                  <div>
                    <h3 className="mb-4 text-sm font-semibold">主要内容方向</h3>
                    {profile.topic_distribution.map((t) => (
                      <div className="mb-4" key={t.name}>
                        <div className="mb-2 flex justify-between text-xs text-stone-600">
                          <span>{t.name}</span>
                          <span className="font-mono">{t.percentage}%</span>
                        </div>
                        <div className="h-1.5 rounded bg-[#eff2e9]">
                          <div
                            className="h-1.5 rounded bg-[#719064]"
                            style={{ width: t.percentage + '%' }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <div>
                    <h3 className="mb-4 text-sm font-semibold">内容能力评分</h3>
                    {Object.entries(profile.quality_scores).map(([name, value]) => (
                      <div key={name} className="mb-3 flex justify-between text-sm">
                        <span className="text-stone-500">{name}</span>
                        <span className="font-mono text-[#55734a]">{value.toFixed(1)} / 5</span>
                      </div>
                    ))}
                  </div>
                </div>
                <p className="mt-5 border-t border-stone-100 pt-4 text-xs leading-6 text-stone-400">
                  基于 {a.source_article_count} 篇已采集文章 · {a.model_name} · {a.prompt_version} ·{' '}
                  {date(a.generated_at)}
                  <br />
                  评分为平台 AI 分析，不代表官方评价。
                  {(a.source_article_count || 0) < 20 ? '当前样本较少，画像仅供初步参考。' : ''}
                </p>
              </>
            ) : (
              <div className="rounded-lg bg-[#f5f6f0] p-5 text-sm leading-7 text-stone-500">
                画像尚未生成。需要先采集文章正文，再运行内容分析。建议使用最近 20—50
                篇文章，以形成更可靠的账号理解。
              </div>
            )}
          </section>
          <section className="mt-10">
            <SectionTitle title="历史文章" sub="所有数量仅指平台实际收录的文章。" />
            <div className="mb-3 flex flex-wrap gap-3">
              <label className="sr-only" htmlFor="article-keyword">
                筛选文章关键词
              </label>
              <input
                id="article-keyword"
                className="input min-w-0 flex-1"
                placeholder="在该账号文章中搜索…"
                value={keyword}
                onChange={(e) => {
                  setKeyword(e.target.value);
                  setPage(1);
                }}
              />
              <label className="sr-only" htmlFor="article-sort">
                文章排序
              </label>
              <select
                id="article-sort"
                className="rounded-md border border-stone-200 bg-white px-3 text-sm"
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value);
                  setPage(1);
                }}
              >
                <option value="latest">最新发布</option>
                <option value="popular">最多收藏</option>
                <option value="recommended">AI 推荐</option>
              </select>
            </div>
            {articles.loading ? (
              <Loading />
            ) : articles.error ? (
              <ErrorState message={articles.error} />
            ) : articles.data?.items.length ? (
              articles.data.items.map((ar) => <ArticleRow key={ar.id} article={ar} />)
            ) : (
              <Empty
                title="暂未收录匹配的文章"
                description="账号已收录，文章可以在管理后台发起同步。"
              />
            )}
            <Pagination
              page={page}
              total={articles.data?.total || 0}
              limit={10}
              onChange={setPage}
            />
          </section>
        </div>
        <aside className="space-y-6">
          <section className="rounded-xl bg-[#ecf1e5] p-6">
            <span className="eyebrow">WHY FOLLOW</span>
            <h3 className="mb-3 mt-2 text-lg font-semibold">为什么值得关注</h3>
            <p className="text-sm leading-7 text-stone-600">{a.recommendation_reason}</p>
            {profile && (
              <>
                <h4 className="mb-3 mt-6 text-sm font-semibold">适合这些读者</h4>
                {profile.target_audience.map((t) => (
                  <p key={t} className="mt-2 flex items-center gap-2 text-sm text-stone-600">
                    <Check size={15} className="text-[#688357]" />
                    {t}
                  </p>
                ))}
                <h4 className="mb-3 mt-6 text-sm font-semibold">可能不适合</h4>
                {profile.not_recommended_for.map((t) => (
                  <p key={t} className="mt-2 flex items-start gap-2 text-sm text-stone-500">
                    <Minus size={15} className="mt-1 shrink-0" />
                    {t}
                  </p>
                ))}
              </>
            )}
          </section>
          <section className="rounded-xl border border-stone-200 bg-white p-6">
            <h3 className="mb-4 text-sm font-semibold">收录信息</h3>
            <dl className="space-y-4 text-xs">
              <div className="flex justify-between">
                <dt className="text-stone-400">最近更新</dt>
                <dd>{date(a.last_article_at)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-stone-400">最近采集</dt>
                <dd>{date(a.last_crawled_at)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-stone-400">正文已就绪</dt>
                <dd>{a.readable_count} 篇</dd>
              </div>
            </dl>
          </section>
        </aside>
      </div>
      <section className="mt-14">
        <SectionTitle
          title="沿着兴趣，继续发现"
          sub="基于分类和标签的规则相似度，不是内容质量评分。"
        />
        {a.similar?.length ? (
          <div className="grid gap-5 md:grid-cols-2">
            {a.similar.map((other) => (
              <AccountCard key={other.id} account={other} compact />
            ))}
          </div>
        ) : (
          <Empty title="暂无相似账号" description="更多同领域公众号收录后，会出现在这里。" />
        )}
      </section>
    </>
  );
}
