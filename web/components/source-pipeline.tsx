'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { Account, Job } from '@/lib/types';

type State = { articles: number; bodies: number; job: Job | null };
const formats = [
  ['zip', 'Markdown 合集'],
  ['html', 'HTML 合集'],
  ['xlsx', 'Excel 清单'],
  ['json', 'JSON 清单'],
  ['docx', 'Word'],
  ['pdf', 'PDF'],
  ['epub', 'EPUB'],
];
const statuses: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  done: '已完成',
  failed: '失败',
  blocked: '等待处理',
};

export function SourcePipeline({
  account,
  token,
  onClose,
}: {
  account: Account;
  token: string;
  onClose: () => void;
}) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [pages, setPages] = useState(1);
  const [bodies, setBodies] = useState(3);
  const [format, setFormat] = useState('zip');
  const [links, setLinks] = useState('');
  const headers = { Authorization: 'Bearer ' + token };
  const base = '/admin/accounts/' + account.id;
  async function refresh() {
    try {
      setState(await api<State>(base + '/source', { headers }));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    let live = true;
    async function poll() {
      try {
        const value = await api<State>(base + '/source', {
          headers: { Authorization: 'Bearer ' + token },
        });
        if (live) {
          setState(value);
          setError('');
        }
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    }
    void poll();
    const timer = setInterval(poll, 5000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [base, token]);
  async function start(cacheOnly: boolean) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const value = await api<{ message: string }>('/admin/jobs', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          kind: 'sync',
          target_id: account.id,
          pages,
          parse_limit: bodies,
          cache_only: cacheOnly,
        }),
      });
      setMessage(value.message);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function retry() {
    setBusy(true);
    setError('');
    try {
      await api('/admin/jobs/' + state?.job?.id + '/retry', { method: 'POST', headers });
      setMessage('已从保存的进度重新排队');
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function download() {
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api' + base + '/export/' + format, { headers });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail || '导出失败，请稍后重试');
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = account.name + '.' + format;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      setMessage('导出文件已下载');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function addLinks() {
    setBusy(true);
    setError('');
    try {
      const result = await api<{ message: string }>(base + '/links', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          urls: links
            .split(/\r?\n/)
            .map((s) => s.trim())
            .filter(Boolean),
        }),
      });
      setMessage(result.message);
      setLinks('');
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const active = state?.job && ['queued', 'running'].includes(state.job.status);
  return (
    <section
      role="region"
      aria-label={account.name + '采集流程'}
      className="mb-7 rounded-xl border border-[#b8c9be] bg-white p-6"
    >
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 className="text-xl font-semibold">{account.name} · 采集与导出</h2>
        <button className="button secondary small" onClick={onClose}>
          收起
        </button>
      </div>
      <p className="mb-5 text-sm leading-7 text-stone-500">
        订阅 → 获取历史列表 → 保存正文 → 导入本站 →
        导出文件。已保存的正文会自动复用，任务中断后可继续。
      </p>
      <div className="grid gap-4 md:grid-cols-3">
        <label className="field">
          历史页数（每页最多 10 次群发）
          <input
            type="number"
            min={1}
            max={30}
            value={pages}
            onChange={(e) => setPages(Number(e.target.value))}
          />
        </label>
        <label className="field">
          本批最新文章的正文上限
          <input
            type="number"
            min={0}
            max={100}
            value={bodies}
            onChange={(e) => setBodies(Number(e.target.value))}
          />
        </label>
        <div className="flex flex-wrap items-end gap-2">
          <button
            className="button"
            disabled={
              busy ||
              !!active ||
              pages < 1 ||
              pages > 30 ||
              bodies < 0 ||
              bodies > 100 ||
              !Number.isInteger(pages) ||
              !Number.isInteger(bodies)
            }
            onClick={() => start(false)}
          >
            开始完整采集
          </button>
          <button
            className="button secondary"
            disabled={busy || !!active}
            onClick={() => start(true)}
          >
            仅导入已有缓存
          </button>
        </div>
      </div>
      <div className="my-5 rounded-lg bg-stone-50 p-4 text-sm leading-7" aria-live="polite">
        <p>
          参考库：{state?.articles ?? '—'} 篇文章，{state?.bodies ?? '—'} 篇正文
        </p>
        {state?.job && (
          <>
            <p>
              任务 #{state.job.id} · {statuses[state.job.status]} ·{' '}
              {String(
                state.job.result?.stage ||
                  (state.job.kind === 'parse' ? '文章链接正文采集' : '等待开始'),
              )}
            </p>
            {state.job.result && state.job.kind === 'sync' && (
              <p>
                已完成历史页数 {Number(state.job.result.pages_done || 0)} · 已导入{' '}
                {Number(state.job.result.imported || 0)} 篇
              </p>
            )}
            {state.job.result && state.job.kind === 'parse' && (
              <p>
                已保存正文 {Number(state.job.result.word_count || 0)} 字 ·{' '}
                <a className="underline" href={'/articles/' + state.job.result.article_id}>
                  打开阅读页
                </a>
              </p>
            )}
            {state.job.error && <p className="text-red-700">{state.job.error}</p>}
            {['blocked', 'failed'].includes(state.job.status) && (
              <button disabled={busy} className="button secondary small mt-2" onClick={retry}>
                处理后继续此任务
              </button>
            )}
          </>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="field">
          导出格式
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            {formats.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button className="button secondary" disabled={busy || !state?.bodies} onClick={download}>
          下载已保存文章
        </button>
        <a
          className="text-sm underline"
          href="http://localhost:5500/login.html"
          target="_blank"
          rel="noreferrer"
        >
          打开扫码登录
        </a>
      </div>
      <p className="mt-3 text-xs leading-6 text-stone-500">
        Excel / JSON 导出文章清单；其他格式包含正文。导出仅包含参考库已有正文的文章；Word、PDF、EPUB
        会下载配图。列表采集受微信登录与频率限制影响。
      </p>
      <details className="mt-5 border-t border-stone-200 pt-4">
        <summary className="cursor-pointer text-sm font-medium">已有文章链接？直接采集正文</summary>
        <label className="field mt-4">
          粘贴属于「{account.name}」的微信文章链接，每行一条，最多 20 条
          <textarea
            rows={3}
            value={links}
            onChange={(e) => setLinks(e.target.value)}
            placeholder="https://mp.weixin.qq.com/s/…"
          />
        </label>
        <button
          className="button secondary small mt-3"
          disabled={busy || !links.trim()}
          onClick={addLinks}
        >
          保存并采集正文
        </button>
        <p className="mt-2 text-xs text-stone-500">
          直接解析链接，无需获取历史列表；文章页面仍可能要求登录或验证。
        </p>
      </details>
      {error && (
        <p role="alert" className="mt-4 text-sm text-red-700">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="mt-4 text-sm text-[#245745]">
          {message}
        </p>
      )}
    </section>
  );
}
