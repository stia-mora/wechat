'use client';
import { use, useState } from 'react';
import Link from 'next/link';
import { ArrowUpRight, ShareNetwork } from '@phosphor-icons/react';
import { useApi, date } from '@/lib/api';
import type { Article } from '@/lib/types';
import { ActionButton, Empty, ErrorState, Loading } from '@/components/ui';
export default function ArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params),
    { data: a, error, loading, reload } = useApi<Article>('/articles/' + id),
    [copied, setCopied] = useState(false),
    [copyError, setCopyError] = useState('');
  if (loading) return <Loading />;
  if (error) return <ErrorState message={error} retry={reload} />;
  if (!a) return null;
  const summary = a.ai_summary;
  return (
    <>
      <div className="flex gap-2 py-8 text-xs text-stone-500">
        <Link href="/discover">发现</Link>
        <span>/</span>
        <Link href={'/accounts/' + a.account_id}>{a.account_name}</Link>
        <span>/</span>
        <span>文章</span>
      </div>
      <div className="grid items-start gap-12 lg:grid-cols-[1fr_290px]">
        <article className="min-w-0 rounded-xl border border-stone-200 bg-white p-6 md:p-12">
          <span className="eyebrow">{a.category || '公众号文章'}</span>
          <h1 className="mb-6 mt-4 text-[27px] font-semibold leading-[1.6] md:text-[34px]">
            {a.title}
          </h1>
          <div className="flex flex-wrap gap-4 border-b border-stone-100 pb-6 text-xs text-stone-500">
            <Link href={'/accounts/' + a.account_id} className="text-[#245745]">
              {a.account_name}
            </Link>
            <span>{a.author}</span>
            <span>{date(a.publish_time)}</span>
            {a.status === 'ready' && (
              <span>
                {a.word_count} 字 · {Math.max(1, Math.ceil(a.word_count / 500))} 分钟阅读
              </span>
            )}
          </div>
          {a.status === 'ready' && a.content_html ? (
            <div
              className="reading-body pt-9"
              dangerouslySetInnerHTML={{ __html: a.content_html }}
            />
          ) : (
            <Empty
              title="正文尚未采集"
              description="你可以通过原文链接阅读，或在后台发起正文解析。"
            />
          )}
          <div className="mt-10 flex flex-wrap items-center gap-4 border-t border-stone-200 pt-7">
            <ActionButton kind="article" targetId={a.id} initial={a.collected} />
            <button
              className="button secondary"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(location.href);
                  setCopied(true);
                  setCopyError('');
                } catch {
                  setCopyError('复制失败，请手动复制地址栏链接');
                }
              }}
            >
              <ShareNetwork size={17} />
              {copied ? '链接已复制' : '分享'}
            </button>
            <a
              href={a.source_url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto flex items-center gap-1 text-sm text-[#245745]"
            >
              查看原文 <ArrowUpRight size={16} />
            </a>
          </div>
          {copyError && (
            <p role="alert" className="mt-3 text-sm text-red-700">
              {copyError}
            </p>
          )}
          <p className="mt-6 text-xs leading-6 text-stone-400">
            内容版权归原作者所有。平台保留原文出处，文章以原始发布页面为准。
          </p>
        </article>
        <aside className="lg:sticky lg:top-6">
          <details open className="rounded-xl bg-[#eff2e8] p-6">
            <summary className="cursor-pointer text-lg font-semibold">AI 阅读助手</summary>
            {summary ? (
              <div className="mt-6 space-y-6 text-sm">
                <section>
                  <h3 className="mb-2 font-semibold">一句话摘要</h3>
                  <p className="leading-7 text-stone-600">{summary.summary}</p>
                </section>
                <section>
                  <h3 className="mb-3 font-semibold">核心观点</h3>
                  {summary.key_points.map((p, i) => (
                    <p key={i} className="mb-3 leading-7 text-stone-600">
                      <span className="mr-2 font-mono text-[#789264]">0{i + 1}</span>
                      {p}
                    </p>
                  ))}
                </section>
                <section>
                  <h3 className="mb-3 font-semibold">关键词</h3>
                  <div className="flex flex-wrap gap-2">
                    {summary.keywords.map((t) => (
                      <Link href={'/search?q=' + encodeURIComponent(t)} className="tag" key={t}>
                        {t}
                      </Link>
                    ))}
                  </div>
                </section>
                <section>
                  <h3 className="mb-2 font-semibold">适合谁</h3>
                  <p className="leading-6 text-stone-600">{summary.target_audience.join(' / ')}</p>
                </section>
                <p className="border-t border-stone-200 pt-4 text-xs leading-6 text-stone-400">
                  AI 生成，请以原文为准。
                  <br />
                  {a.model_name} · {date(a.generated_at)}
                </p>
              </div>
            ) : (
              <p className="mt-5 text-sm leading-7 text-stone-500">
                本文摘要尚未生成。正文采集并完成分析后，将展示摘要、观点与关键词。
              </p>
            )}
          </details>
          <div className="mt-8">
            <h3 className="mb-4 text-sm font-semibold">继续阅读</h3>
            {a.related?.length ? (
              a.related.map((r) => (
                <Link
                  key={r.id}
                  href={'/articles/' + r.id}
                  className="block border-b border-stone-200 py-4"
                >
                  <p className="mb-2 text-xs text-stone-400">{r.account_name}</p>
                  <p className="text-sm leading-6">{r.title}</p>
                </Link>
              ))
            ) : (
              <p className="text-sm text-stone-400">暂无相关文章。</p>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}
