'use client';
import Link from 'next/link';
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  ChartLineUp,
  Cpu,
  Compass,
  GraduationCap,
} from '@phosphor-icons/react';
import { useApi, date } from '@/lib/api';
import type { Account, Article, Category, Page } from '@/lib/types';
import {
  AccountCard,
  ArticleRow,
  Empty,
  ErrorState,
  Loading,
  SearchBox,
  SectionTitle,
} from '@/components/ui';

export default function Home() {
  const accounts = useApi<Page<Account>>('/accounts?limit=6'),
    articles = useApi<Page<Article>>('/articles?limit=5');
  const { data: categories } = useApi<Category[]>('/categories');
  const { data: stats } = useApi<{ accounts: number; articles: number; last_crawled_at: string }>(
    '/stats',
  );
  const icons = [Cpu, ChartLineUp, GraduationCap, BookOpen];
  return (
    <>
      <section className="grid items-center gap-12 border-b border-stone-200 py-14 lg:grid-cols-[1.6fr_1fr] lg:py-20">
        <div>
          <p className="eyebrow mb-5">CURATE YOUR INFORMATION WORLD</p>
          <h1 className="text-[34px] font-semibold leading-[1.45] tracking-tight sm:text-[44px]">
            信息很多，
            <br />
            值得关注的<span className="text-[#245745]">不止眼前。</span>
          </h1>
          <p className="mb-8 mt-5 text-sm leading-7 text-stone-500 sm:text-base">
            发现优质公众号，读懂内容方向。
            <br className="sm:hidden" />
            让每一次关注，都更有价值。
          </p>
          <SearchBox large />
          <div className="mt-4 flex flex-wrap gap-4 text-xs text-stone-500">
            <span>试试搜索</span>
            {['人工智能', '商业', '大学', '阅读'].map((t) => (
              <Link key={t} href={'/search?q=' + encodeURIComponent(t)}>
                {t}
              </Link>
            ))}
          </div>
        </div>
        <div className="relative hidden min-h-72 overflow-hidden rounded-2xl border border-[#dee4d4] bg-[#edf1e6] p-8 lg:block">
          <div className="flex items-center justify-between">
            <span className="eyebrow">THE SOURCE INDEX</span>
            <Compass size={22} className="text-[#5b7354]" />
          </div>
          <p className="mt-8 text-[28px] font-medium leading-relaxed text-[#3a5234]">
            从一个好问题，
            <br />
            找到一片新视野。
          </p>
          <div className="mt-9 flex items-end gap-9 border-t border-[#d3dbc8] pt-5">
            <div>
              <span className="font-mono text-3xl text-[#34532d]">{stats?.accounts ?? '—'}</span>
              <span className="ml-2 text-xs text-[#7a8970]">个信息源</span>
            </div>
            <div>
              <span className="font-mono text-3xl text-[#34532d]">04</span>
              <span className="ml-2 text-xs text-[#7a8970]">个领域</span>
            </div>
          </div>
        </div>
      </section>
      <section className="py-10">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(categories?.filter((c) => !c.parent_id) || []).map((c, i) => {
            const Icon = icons[i] || Compass;
            return (
              <Link
                key={c.id}
                href={'/discover?category=' + c.id}
                className="group flex items-center gap-4 rounded-lg border border-stone-200 bg-white px-5 py-5"
              >
                <span className="flex size-11 items-center justify-center rounded-full bg-[#f1f3eb] text-[#6e805f]">
                  <Icon size={23} />
                </span>
                <span className="flex-1">
                  <strong className="block text-base font-medium">{c.name}</strong>
                  <span className="text-xs text-stone-400">{c.account_count} 个公众号</span>
                </span>
                <ArrowUpRight size={17} className="text-stone-400 group-hover:text-[#245745]" />
              </Link>
            );
          })}
        </div>
      </section>
      <section className="py-5">
        <SectionTitle
          title="值得发现的信息源"
          sub="从长期内容中，寻找值得持续关注的声音。"
          href="/discover"
        />
        {accounts.loading ? (
          <Loading />
        ) : accounts.error ? (
          <ErrorState message={accounts.error} retry={accounts.reload} />
        ) : accounts.data?.items.length ? (
          <div className="grid gap-5 md:grid-cols-2">
            {accounts.data.items.map((a) => (
              <AccountCard key={a.id} account={a} compact />
            ))}
          </div>
        ) : (
          <Empty title="信息源目录正在建立" description="完成采集与审核后，公众号会出现在这里。" />
        )}
      </section>
      <section className="mt-14 grid gap-12 lg:grid-cols-[1fr_300px]">
        <div>
          <SectionTitle
            title="最新收录"
            sub="来自不同领域的新内容，保留原文出处。"
            href="/search?tab=articles"
          />
          {articles.loading ? (
            <Loading />
          ) : articles.error ? (
            <ErrorState message={articles.error} />
          ) : articles.data?.items.length ? (
            articles.data.items.map((a) => <ArticleRow key={a.id} article={a} />)
          ) : (
            <Empty title="文章正在等待采集" description="你可以先浏览已收录的公众号。" />
          )}
        </div>
        <aside className="h-fit rounded-xl bg-[#f0f2e9] p-7">
          <span className="eyebrow">YOUR PERSONAL READING MAP</span>
          <h3 className="mt-4 text-xl font-semibold leading-8">
            建立你的
            <br />
            个人信息源。
          </h3>
          <p className="mt-4 text-sm leading-7 text-stone-500">
            收藏感兴趣的账号，关注持续更新的内容。让信息主动聚合，让阅读更有方向。
          </p>
          <Link
            href="/library"
            className="mt-6 flex items-center gap-2 text-sm font-medium text-[#245745]"
          >
            打开我的关注 <ArrowRight size={17} />
          </Link>
          <p className="mt-8 border-t border-stone-200 pt-4 text-xs leading-6 text-stone-400">
            已收录 {stats?.articles ?? 0} 篇文章
            <br />
            最近采集 {date(stats?.last_crawled_at)}
          </p>
        </aside>
      </section>
    </>
  );
}
