'use client';
import { Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { api, useApi, date } from '@/lib/api';
import type { Account, Article } from '@/lib/types';
import { AccountCard, ArticleRow, Empty, ErrorState, Loading } from '@/components/ui';
import { ApiAccessManager } from '@/components/api-access';
function Library() {
  const view = useSearchParams().get('view') || 'following';
  const { data, error, loading, reload } = useApi<{
    accounts?: Account[];
    articles?: Article[];
    history?: { kind: string; target_id: number; title: string; visited_at: string }[];
  }>(view === 'api' ? null : '/me/library?view=' + view);
  return (
    <>
      <section className="flex items-center justify-between gap-4 py-12">
        <div>
          <span className="eyebrow">YOUR READING MAP</span>
          <h1 className="mt-3 text-3xl font-semibold">我的信息源</h1>
        </div>
        <button
          className="button secondary small"
          onClick={async () => {
            await api('/auth/session', { method: 'DELETE' });
            location.href = '/';
          }}
        >
          退出登录
        </button>
      </section>
      <div className="tabs mb-8">
        {[
          ['following', '我的关注'],
          ['collections', '我的收藏'],
          ['history', '最近浏览'],
          ['api', 'Agent API'],
        ].map(([v, t]) => (
          <Link key={v} className={view === v ? 'selected' : ''} href={'/library?view=' + v}>
            {t}
          </Link>
        ))}
      </div>
      {view === 'api' ? (
        <ApiAccessManager />
      ) : loading ? (
        <Loading />
      ) : error ? (
        error === '请先登录' ? (
          <div className="py-14 text-center">
            <h2 className="text-xl font-semibold">登录，保存你的阅读地图。</h2>
            <Link href="/login?next=/library" className="button mt-6">
              登录 / 注册
            </Link>
          </div>
        ) : (
          <ErrorState message={error} retry={reload} />
        )
      ) : (
        <>
          {data?.accounts?.length ? (
            <div className="grid gap-5 md:grid-cols-2">
              {data.accounts.map((a) => (
                <AccountCard account={a} key={a.id} />
              ))}
            </div>
          ) : null}
          {data?.articles?.length ? (
            <section className="mt-9">
              <h2 className="text-xl font-semibold">收藏的文章</h2>
              {data.articles.map((a) => (
                <ArticleRow key={a.id} article={a} />
              ))}
            </section>
          ) : null}
          {data?.history?.map((h, i) => (
            <Link
              key={i}
              href={`/${h.kind === 'account' ? 'accounts' : 'articles'}/${h.target_id}`}
              className="flex items-center justify-between gap-5 border-b border-stone-200 py-6"
            >
              <span>{h.title}</span>
              <span className="shrink-0 text-xs text-stone-400">
                {h.kind === 'account' ? '公众号' : '文章'} · {date(h.visited_at)}
              </span>
            </Link>
          ))}
          {!data?.accounts?.length && !data?.articles?.length && !data?.history?.length && (
            <Empty
              title={
                view === 'history'
                  ? '还没有浏览记录'
                  : view === 'collections'
                    ? '把好内容收藏在这里'
                    : '关注让你持续感兴趣的账号'
              }
              description="从发现页出发，慢慢建立自己的信息源。"
            />
          )}
        </>
      )}
    </>
  );
}
export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <Library />
    </Suspense>
  );
}
