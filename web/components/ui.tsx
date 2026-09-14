'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import {
  ArrowRight,
  ArrowUpRight,
  BookmarkSimple,
  Check,
  MagnifyingGlass,
  Plus,
} from '@phosphor-icons/react';
import { api, date } from '@/lib/api';
import type { Account, Article } from '@/lib/types';

export function SearchBox({ initial = '', large = false }: { initial?: string; large?: boolean }) {
  const [q, setQ] = useState(initial),
    router = useRouter();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        router.push('/search?q=' + encodeURIComponent(q));
      }}
      className={`search-box ${large ? 'large' : ''}`}
      role="search"
    >
      <label className="sr-only" htmlFor="source-search">
        搜索公众号、文章、关键词
      </label>
      <MagnifyingGlass size={22} className="shrink-0 text-stone-400" />
      <input
        id="source-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="搜索公众号、文章、关键词…"
        maxLength={200}
      />
      <button className="button" type="submit">
        搜索 <ArrowRight size={17} />
      </button>
    </form>
  );
}
export function Avatar({ account, large = false }: { account: Account; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={`avatar ${large ? 'large' : ''}`}>
      {account.avatar_url && !failed ? (
        <img
          src={account.avatar_url}
          alt=""
          onError={() => setFailed(true)}
          referrerPolicy="no-referrer"
        />
      ) : (
        account.name.slice(0, 2)
      )}
    </span>
  );
}
export function AccountCard({
  account,
  compact = false,
  rank,
}: {
  account: Account;
  compact?: boolean;
  rank?: number;
}) {
  return (
    <article className={`account-card ${compact ? 'compact' : ''}`}>
      <div className="flex gap-4">
        {rank !== undefined && <span className="rank-number">{String(rank).padStart(2, '0')}</span>}
        <Avatar account={account} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <Link
              href={'/accounts/' + account.id}
              className="text-lg font-semibold hover:text-[#245745]"
            >
              {account.name}
            </Link>
            <span className="whitespace-nowrap text-xs text-stone-500">
              {account.category || '待分类'}
            </span>
          </div>
          <p className="mt-1 text-xs text-stone-500">
            {account.wechat_id || '微信公众账号'}
            {account.account_type ? ' · ' + account.account_type : ''}
          </p>
        </div>
      </div>
      <p className="mt-5 line-clamp-2 min-h-12 text-sm leading-6 text-stone-600">
        {account.description || '账号基本信息已从微信公众平台收录，简介待完善。'}
      </p>
      <div className="mt-4 flex min-h-6 flex-wrap gap-2">
        {account.tags.slice(0, 4).map((tag) => (
          <Link className="tag" href={'/search?q=' + encodeURIComponent(tag)} key={tag}>
            {tag}
          </Link>
        ))}
      </div>
      {!compact && account.profile && (
        <div className="mt-5 border-l-2 border-[#b8cdbf] pl-3 text-sm leading-6 text-stone-600">
          <span className="eyebrow block">AI 推荐理由</span>
          {account.recommendation_reason}
        </div>
      )}
      <div className="mt-5 flex items-center justify-between border-t border-stone-100 pt-4 text-xs text-stone-500">
        <span>
          {account.article_count} 篇收录 · 近 30 天 {account.articles_last_30d} 篇
        </span>
        <Link
          href={'/accounts/' + account.id}
          className="flex items-center gap-1 font-medium text-[#245745]"
        >
          查看账号 <ArrowUpRight size={15} />
        </Link>
      </div>
      {rank !== undefined && (
        <p className="mt-3 text-xs leading-5 text-stone-500">
          综合分 {account.rank_score} · 活跃 {account.rank_factors?.activity} · 完整度{' '}
          {account.rank_factors?.completeness} ·{' '}
          {account.quality_score === null ? '质量待分析' : '质量 ' + account.quality_score}
        </p>
      )}
      {account.similarity_reason && (
        <div className="mt-4 text-xs leading-6 text-stone-500">
          <p>
            规则相似度 {account.similarity}% · {account.similarity_reason}
          </p>
          <p>{account.difference}</p>
        </div>
      )}
    </article>
  );
}
export function ArticleRow({ article }: { article: Article }) {
  return (
    <article className="article-row">
      <div className="min-w-0 flex-1">
        <p className="mb-2 text-xs text-stone-500">
          {article.account_name} <span className="px-2">/</span> {date(article.publish_time)}
        </p>
        <Link
          className="text-lg font-semibold leading-7 hover:text-[#245745]"
          href={'/articles/' + article.id}
        >
          {article.title}
        </Link>
        {article.summary && (
          <p className="mt-2 line-clamp-2 text-sm leading-6 text-stone-500">{article.summary}</p>
        )}
        <p className="mt-3 text-xs text-stone-400">
          {article.status === 'ready'
            ? `${Math.max(1, Math.ceil(article.word_count / 500))} 分钟阅读`
            : '已收录标题 · 正文待采集'}
        </p>
      </div>
      {article.cover_url && (
        <img
          src={article.cover_url}
          referrerPolicy="no-referrer"
          className="hidden h-24 w-36 rounded-lg object-cover sm:block"
          alt=""
          onError={(e) => {
            e.currentTarget.style.display = 'none';
          }}
        />
      )}
    </article>
  );
}
export function ActionButton({
  kind,
  targetId,
  initial = false,
}: {
  kind: 'follow' | 'account' | 'article';
  targetId: number;
  initial?: boolean;
}) {
  const [enabled, setEnabled] = useState(initial),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const router = useRouter();
  async function toggle() {
    setBusy(true);
    setError('');
    try {
      await api('/me/actions', {
        method: 'PUT',
        body: JSON.stringify({ kind, target_id: targetId, enabled: !enabled }),
      });
      setEnabled(!enabled);
    } catch (e) {
      const message = (e as Error).message;
      if (message === '请先登录')
        router.push('/login?next=' + encodeURIComponent(location.pathname));
      else setError(message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <button
        disabled={busy}
        onClick={toggle}
        className={`button ${kind === 'follow' ? '' : 'secondary'}`}
      >
        {enabled ? (
          <Check size={17} />
        ) : kind === 'follow' ? (
          <Plus size={17} />
        ) : (
          <BookmarkSimple size={17} />
        )}{' '}
        {busy
          ? '保存中…'
          : enabled
            ? kind === 'follow'
              ? '已关注'
              : '已收藏'
            : kind === 'follow'
              ? '关注公众号'
              : '收藏'}
      </button>
      {error && (
        <p role="alert" className="mt-2 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
export function Empty({
  title = '这里还没有内容',
  description = '换一个关键词，或浏览其他分类。',
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="empty-state">
      <span className="mb-4 block text-4xl font-light text-stone-300">—</span>
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-3 text-sm text-stone-500">{description}</p>
      <Link href="/discover" className="mt-6 inline-flex items-center gap-2 text-sm text-[#245745]">
        去发现信息源 <ArrowRight size={16} />
      </Link>
    </div>
  );
}
export function Loading() {
  return (
    <div aria-label="加载中" className="grid gap-5 py-8 md:grid-cols-2">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="skeleton h-44 rounded-xl" />
      ))}
    </div>
  );
}
export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div
      role="alert"
      className="my-8 rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800"
    >
      <p>{message}</p>
      {retry && (
        <button className="button secondary mt-4" onClick={retry}>
          重新加载
        </button>
      )}
    </div>
  );
}
export function Pagination({
  page,
  total,
  limit,
  onChange,
}: {
  page: number;
  total: number;
  limit: number;
  onChange: (p: number) => void;
}) {
  if (total <= limit) return null;
  return (
    <div className="mt-8 flex items-center justify-center gap-6">
      <button className="button secondary" disabled={page === 1} onClick={() => onChange(page - 1)}>
        上一页
      </button>
      <span className="text-sm text-stone-500">
        {page} / {Math.ceil(total / limit)}
      </span>
      <button
        className="button secondary"
        disabled={page * limit >= total}
        onClick={() => onChange(page + 1)}
      >
        下一页
      </button>
    </div>
  );
}
export function SectionTitle({ title, sub, href }: { title: string; sub?: string; href?: string }) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
        {sub && <p className="mt-2 text-sm text-stone-500">{sub}</p>}
      </div>
      {href && (
        <Link href={href} className="flex shrink-0 items-center gap-2 text-sm text-[#245745]">
          查看全部 <ArrowRight size={16} />
        </Link>
      )}
    </div>
  );
}
