'use client';
import { useEffect, useState } from 'react';
import { ArrowClockwise, LockKey } from '@phosphor-icons/react';
import { api, date, useApi } from '@/lib/api';
import type { Account, Article, Category, Job } from '@/lib/types';
import { ErrorState, Loading } from '@/components/ui';

type Overview = {
  accounts: { status: string; count: number }[];
  articles: { status: string; count: number }[];
  jobs: { status: string; count: number }[];
  source: { loggedIn: boolean; status: string };
  source_counts: { accounts: number; unique_accounts: number; last_crawled_at: string };
  llm_configured: boolean;
};
const stateNames: Record<string, string> = {
  pending: '待审核',
  approved: '已通过',
  hidden: '已隐藏',
  error: '异常',
  queued: '排队中',
  running: '运行中',
  done: '已完成',
  failed: '失败',
  blocked: '待处理',
  metadata: '待采集正文',
  ready: '可阅读',
};
const kindNames: Record<string, string> = {
  discover: '发现公众号',
  sync: '同步文章',
  parse: '解析正文',
  account_ai: '账号画像',
  article_ai: '文章摘要',
};

export default function Admin() {
  const [token, setToken] = useState(''),
    [draft, setDraft] = useState(''),
    [tab, setTab] = useState('overview'),
    [error, setError] = useState(''),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false);
  const [overview, setOverview] = useState<Overview | null>(null),
    [accounts, setAccounts] = useState<Account[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [articles, setArticles] = useState<Article[]>([]),
    [tags, setTags] = useState<{ id: number; name: string; account_count: number }[]>([]),
    [ranking, setRanking] = useState<Record<string, number>>({});
  const [editing, setEditing] = useState<Account | null>(null),
    [profileText, setProfileText] = useState(''),
    [search, setSearch] = useState(''),
    [status, setStatus] = useState(''),
    [page, setPage] = useState(1);
  const categories = useApi<Category[]>('/categories');
  const headers = { Authorization: 'Bearer ' + token };
  async function admin<T>(path: string, options: RequestInit = {}): Promise<T> {
    return api<T>('/admin' + path, { ...options, headers: { ...headers, ...options.headers } });
  }
  async function load() {
    setError('');
    setBusy(true);
    try {
      if (tab === 'overview') setOverview(await admin<Overview>('/overview'));
      if (tab === 'accounts')
        setAccounts(
          await admin<Account[]>(
            `/accounts?q=${encodeURIComponent(search)}&status=${status}&page=${page}`,
          ),
        );
      if (tab === 'jobs') setJobs(await admin<Job[]>('/jobs?page=' + page));
      if (tab === 'articles') setArticles(await admin<Article[]>('/articles?page=' + page));
      if (tab === 'tags') setTags(await admin<typeof tags>('/tags'));
      if (tab === 'ranking') setRanking(await admin<Record<string, number>>('/ranking'));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const saved = sessionStorage.getItem('ws-admin');
    if (saved) setToken(saved);
  }, []);
  useEffect(() => {
    if (token) void load();
  }, [token, tab, page]); // User-triggered refresh; no hidden background polling.
  async function action(fn: () => Promise<unknown>, success = '已保存') {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await fn();
      setMessage(success);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function queue(kind: string, target_id: number) {
    await action(
      () =>
        admin('/jobs', {
          method: 'POST',
          body: JSON.stringify({ kind, target_id, pages: 1, parse_limit: 3 }),
        }),
      '任务已排队',
    );
  }
  if (!token)
    return (
      <div className="mx-auto my-16 max-w-md rounded-xl border border-stone-200 bg-white p-8">
        <LockKey size={28} className="mb-6 text-[#245745]" />
        <h1 className="mb-3 text-2xl font-semibold">数据管理</h1>
        <p className="mb-6 text-sm leading-7 text-stone-500">
          输入本机 .env 中的 ADMIN_TOKEN。密钥仅保存在当前浏览器会话，不会进入公开页面。
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sessionStorage.setItem('ws-admin', draft);
            setToken(draft);
          }}
        >
          <label className="field">
            管理员密钥
            <input
              type="password"
              required
              minLength={24}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <button className="button mt-5 w-full">进入后台</button>
        </form>
      </div>
    );
  return (
    <>
      <section className="flex flex-wrap items-center justify-between gap-5 py-10">
        <div>
          <span className="eyebrow">SOURCE OPERATIONS</span>
          <h1 className="mt-2 text-3xl font-semibold">数据管理</h1>
        </div>
        <div className="flex gap-3">
          <button disabled={busy} className="button secondary small" onClick={load}>
            <ArrowClockwise size={16} />
            刷新
          </button>
          <button
            className="button secondary small"
            onClick={() => {
              sessionStorage.removeItem('ws-admin');
              setToken('');
            }}
          >
            退出后台
          </button>
        </div>
      </section>
      <div className="tabs mb-7">
        {[
          ['overview', '概览'],
          ['accounts', '公众号审核'],
          ['articles', '文章管理'],
          ['jobs', '采集 / AI 任务'],
          ['categories', '分类'],
          ['tags', '标签'],
          ['ranking', '推荐 / 排行'],
        ].map(([v, t]) => (
          <button
            key={v}
            className={tab === v ? 'selected' : ''}
            onClick={() => {
              setTab(v);
              setPage(1);
              setEditing(null);
              setMessage('');
            }}
          >
            {t}
          </button>
        ))}
      </div>
      {error && <ErrorState message={error} />}{' '}
      {message && (
        <p role="status" className="mb-6 rounded-lg bg-[#eaf0e2] p-4 text-sm text-[#3e6231]">
          {message}
        </p>
      )}
      {busy && !overview && tab === 'overview' ? <Loading /> : null}
      {tab === 'overview' && overview && (
        <>
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
            {[
              ['已采集公众号', overview.source_counts.accounts],
              ['独立来源 ID', overview.source_counts.unique_accounts],
              ['已公开', overview.accounts.find((a) => a.status === 'approved')?.count || 0],
              ['正文可读', overview.articles.find((a) => a.status === 'ready')?.count || 0],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-stone-200 bg-white p-6">
                <p className="text-sm text-stone-500">{label}</p>
                <p className="mt-4 font-mono text-3xl">{value}</p>
              </div>
            ))}
          </div>
          <div className="mt-7 grid gap-6 md:grid-cols-2">
            <section className="rounded-xl border border-stone-200 bg-white p-7">
              <h2 className="mb-4 text-lg font-semibold">采集服务</h2>
              <p className="text-sm">
                {overview.source.loggedIn ? '微信已登录' : overview.source.status || '微信尚未登录'}
              </p>
              <p className="mt-3 text-xs text-stone-500">
                最近采集 {date(overview.source_counts.last_crawled_at)}
              </p>
              <a
                href="http://localhost:5500/login.html"
                target="_blank"
                rel="noreferrer"
                className="button secondary mt-5 small"
              >
                打开本机扫码入口
              </a>
            </section>
            <section className="rounded-xl border border-stone-200 bg-white p-7">
              <h2 className="mb-4 text-lg font-semibold">任务与分析</h2>
              <p className="text-sm">
                {overview.llm_configured ? 'LLM 已配置' : 'LLM 未配置，分析任务将等待处理'}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {overview.jobs.map((j) => (
                  <span className="tag" key={j.status}>
                    {stateNames[j.status]} {j.count}
                  </span>
                ))}
              </div>
              <p className="mt-5 text-xs leading-6 text-stone-500">
                分析结果保留模型、提示版本、样本数与生成时间。没有结果时不会显示虚构画像。
              </p>
            </section>
          </div>
        </>
      )}
      {tab === 'accounts' && (
        <>
          <form
            className="mb-5 flex flex-wrap gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              setPage(1);
              void load();
            }}
          >
            <label className="sr-only" htmlFor="admin-search">
              公众号名称
            </label>
            <input
              id="admin-search"
              className="input max-w-xs"
              placeholder="搜索公众号名称"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <label className="sr-only" htmlFor="admin-status">
              审核状态
            </label>
            <select
              id="admin-status"
              className="input max-w-40"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">全部状态</option>
              {['pending', 'approved', 'hidden', 'error'].map((s) => (
                <option key={s} value={s}>
                  {stateNames[s]}
                </option>
              ))}
            </select>
            <button className="button secondary">筛选</button>
          </form>
          {editing && (
            <form
              className="mb-7 rounded-xl border border-[#c2d1b7] bg-white p-7"
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                void action(async () => {
                  await admin('/accounts/' + editing.id, {
                    method: 'PATCH',
                    body: JSON.stringify({
                      description: f.get('description'),
                      primary_category_id: Number(f.get('category')) || null,
                      account_type: f.get('account_type'),
                      status: f.get('status'),
                      tags: String(f.get('tags')).split(/[,，]/).filter(Boolean),
                      category_ids: f.getAll('subcategories').map(Number),
                    }),
                  });
                  setEditing(null);
                });
              }}
            >
              <div className="mb-5 flex justify-between">
                <h2 className="text-lg font-semibold">编辑 · {editing.name}</h2>
                <button
                  type="button"
                  onClick={() => setEditing(null)}
                  className="text-sm text-stone-500"
                >
                  关闭
                </button>
              </div>
              <div className="grid gap-5 md:grid-cols-2">
                <label className="field md:col-span-2">
                  简介
                  <textarea name="description" defaultValue={editing.description} />
                </label>
                <label className="field">
                  主分类
                  <select name="category" defaultValue={editing.primary_category_id || ''}>
                    <option value="">未分类</option>
                    {categories.data
                      ?.filter((c) => !c.parent_id)
                      .map((c) => (
                        <option value={c.id} key={c.id}>
                          {c.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="field">
                  账号类型
                  <select name="account_type" defaultValue={editing.account_type}>
                    <option value="">未确定</option>
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
                <label className="field">
                  标签（逗号分隔）
                  <input name="tags" defaultValue={editing.tags.join(',')} />
                </label>
                <label className="field">
                  审核状态
                  <select name="status" defaultValue={editing.status}>
                    {['pending', 'approved', 'hidden', 'error'].map((s) => (
                      <option value={s} key={s}>
                        {stateNames[s]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field md:col-span-2">
                  二级分类（按 Ctrl 多选）
                  <select
                    name="subcategories"
                    multiple
                    size={6}
                    defaultValue={editing.subcategories?.map((c) => String(c.id)) || []}
                  >
                    {categories.data
                      ?.filter((c) => c.parent_id)
                      .map((c) => (
                        <option value={c.id} key={c.id}>
                          {c.slug}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              <button disabled={busy} className="button mt-5">
                保存账号
              </button>
              {editing.profile && (
                <div className="mt-7 border-t border-stone-200 pt-5">
                  <label className="field">
                    AI 画像人工审核（JSON）
                    <textarea
                      className="min-h-60 font-mono text-xs"
                      value={profileText}
                      onChange={(e) => setProfileText(e.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={busy}
                    className="button secondary mt-3"
                    onClick={() =>
                      action(() =>
                        admin('/profiles/' + editing.id, {
                          method: 'PUT',
                          body: JSON.stringify(JSON.parse(profileText)),
                        }),
                      )
                    }
                  >
                    保存已审核画像
                  </button>
                </div>
              )}
            </form>
          )}
          <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>公众号</th>
                  <th>分类</th>
                  <th>状态</th>
                  <th>文章</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <strong>{a.name}</strong>
                      <p className="mt-1 text-xs text-stone-400">{a.wechat_id || a.source_id}</p>
                    </td>
                    <td>{a.category || '未分类'}</td>
                    <td>{stateNames[a.status]}</td>
                    <td>{a.article_count}</td>
                    <td>
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="button secondary small"
                          onClick={() => {
                            setEditing(a);
                            setProfileText(JSON.stringify(a.profile, null, 2));
                          }}
                        >
                          审核编辑
                        </button>
                        <button
                          disabled={busy}
                          className="button secondary small"
                          onClick={() => queue('sync', a.id)}
                        >
                          同步
                        </button>
                        <button
                          disabled={busy}
                          className="button secondary small"
                          onClick={() => queue('account_ai', a.id)}
                        >
                          AI 画像
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {tab === 'jobs' && (
        <>
          <form
            className="mb-7 grid gap-4 rounded-xl border border-stone-200 bg-white p-6 md:grid-cols-[1fr_200px_auto]"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void action(
                () =>
                  admin('/jobs', {
                    method: 'POST',
                    body: JSON.stringify({
                      kind: 'discover',
                      query: f.get('query'),
                      category_id: Number(f.get('category_id')) || null,
                    }),
                  }),
                '发现任务已排队',
              );
            }}
          >
            <label className="field">
              搜索公众号
              <input name="query" placeholder="公众号名称或关键词" required />
            </label>
            <label className="field">
              初始分类
              <select name="category_id">
                <option value="">待分类</option>
                {categories.data
                  ?.filter((c) => !c.parent_id)
                  .map((c) => (
                    <option value={c.id} key={c.id}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </label>
            <button disabled={busy} className="button self-end">
              发起发现
            </button>
          </form>
          <p className="mb-4 text-xs leading-6 text-stone-500">
            文章同步与分析可在公众号、文章管理中发起。登录过期或需要验证时会暂停采集；处理后手动重试。
          </p>
          <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>ID / 类型</th>
                  <th>参数</th>
                  <th>状态</th>
                  <th>结果 / 错误</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td>
                      #{j.id}
                      <br />
                      {kindNames[j.kind]}
                    </td>
                    <td>
                      <pre className="max-w-64 whitespace-pre-wrap break-all text-xs">
                        {JSON.stringify(j.payload)}
                      </pre>
                    </td>
                    <td>
                      {stateNames[j.status]}
                      <p className="mt-1 text-xs text-stone-400">尝试 {j.attempts} 次</p>
                    </td>
                    <td>
                      <p className="max-w-md break-all text-xs leading-6">
                        {j.error || JSON.stringify(j.result || {})}
                      </p>
                    </td>
                    <td>
                      {['failed', 'blocked'].includes(j.status) && (
                        <button
                          disabled={busy}
                          className="button secondary small"
                          onClick={() =>
                            action(
                              () => admin('/jobs/' + j.id + '/retry', { method: 'POST' }),
                              '重试已排队',
                            )
                          }
                        >
                          重试
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {tab === 'articles' && (
        <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
          <table className="admin-table">
            <thead>
              <tr>
                <th>文章</th>
                <th>状态</th>
                <th>字数</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {articles.map((a) => (
                <tr key={a.id}>
                  <td className="max-w-lg">
                    <p>{a.title}</p>
                    <p className="mt-2 text-xs text-stone-400">
                      {a.account_name} · {date(a.publish_time)}
                    </p>
                  </td>
                  <td>{stateNames[a.status]}</td>
                  <td>{a.word_count}</td>
                  <td>
                    <div className="flex flex-wrap gap-2">
                      <button
                        disabled={busy}
                        className="button secondary small"
                        onClick={() => queue('parse', a.id)}
                      >
                        采集正文
                      </button>
                      <button
                        disabled={busy}
                        className="button secondary small"
                        onClick={() => queue('article_ai', a.id)}
                      >
                        AI 摘要
                      </button>
                      <button
                        disabled={busy}
                        className="button secondary small"
                        onClick={() =>
                          action(() =>
                            admin('/articles/' + a.id, {
                              method: 'PATCH',
                              body: JSON.stringify({
                                status:
                                  a.status === 'hidden'
                                    ? a.word_count
                                      ? 'ready'
                                      : 'metadata'
                                    : 'hidden',
                              }),
                            }),
                          )
                        }
                      >
                        {a.status === 'hidden' ? '恢复' : '隐藏'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === 'categories' && (
        <>
          <form
            className="mb-7 flex flex-wrap items-end gap-4 rounded-xl border border-stone-200 bg-white p-6"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void action(async () => {
                await admin('/categories', {
                  method: 'POST',
                  body: JSON.stringify({
                    name: f.get('name'),
                    parent_id: Number(f.get('parent_id')) || null,
                  }),
                });
                categories.reload();
              });
            }}
          >
            <label className="field">
              分类名称
              <input required name="name" />
            </label>
            <label className="field">
              父分类
              <select name="parent_id">
                <option value="">一级分类</option>
                {categories.data
                  ?.filter((c) => !c.parent_id)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </label>
            <button className="button" disabled={busy}>
              新增分类
            </button>
          </form>
          <div className="grid gap-5 md:grid-cols-2">
            {categories.data
              ?.filter((c) => !c.parent_id)
              .map((c) => (
                <section className="rounded-xl border border-stone-200 bg-white p-6" key={c.id}>
                  <h2 className="mb-4 text-lg font-semibold">{c.name}</h2>
                  <div className="flex flex-wrap gap-2">
                    {categories.data
                      ?.filter((s) => s.parent_id === c.id)
                      .map((s) => (
                        <span className="tag" key={s.id}>
                          {s.name}
                        </span>
                      ))}
                  </div>
                </section>
              ))}
          </div>
        </>
      )}
      {tab === 'tags' && (
        <div className="grid gap-4 md:grid-cols-2">
          {tags.map((t) => (
            <form
              key={t.id}
              className="flex items-center gap-3 rounded-lg border border-stone-200 bg-white p-4"
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                void action(() =>
                  admin('/tags/' + t.id, {
                    method: 'PATCH',
                    body: JSON.stringify({ name: f.get('name') }),
                  }),
                );
              }}
            >
              <label className="field flex-1">
                {t.account_count} 个公众号
                <input name="name" defaultValue={t.name} required />
              </label>
              <button className="button secondary small self-end" disabled={busy}>
                改名
              </button>
            </form>
          ))}
        </div>
      )}
      {tab === 'ranking' && (
        <form
          className="max-w-xl space-y-6 rounded-xl border border-stone-200 bg-white p-7"
          onSubmit={(e) => {
            e.preventDefault();
            void action(() => admin('/ranking', { method: 'PUT', body: JSON.stringify(ranking) }));
          }}
        >
          <h2 className="text-xl font-semibold">推荐与综合排行权重</h2>
          <p className="text-sm leading-7 text-stone-500">
            四项均为 0—1，权重之和必须为 1。排序分数来自本站数据；质量项仅在完成 AI 分析后计入。
          </p>
          {Object.entries(ranking).map(([key, value]) => (
            <label key={key} className="field">
              {
                {
                  quality: '内容质量',
                  activity: '更新活跃',
                  completeness: '资料完整度',
                  following: '站内关注',
                }[key]
              }
              <input
                type="number"
                min={0}
                max={1}
                step="0.01"
                value={value}
                onChange={(e) => setRanking({ ...ranking, [key]: Number(e.target.value) })}
              />
            </label>
          ))}
          <button disabled={busy} className="button">
            保存权重
          </button>
        </form>
      )}
      {['accounts', 'jobs', 'articles'].includes(tab) && (
        <div className="mt-7 flex items-center justify-center gap-5">
          <button
            className="button secondary small"
            disabled={page === 1 || busy}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </button>
          <span className="text-sm">第 {page} 页</span>
          <button
            className="button secondary small"
            disabled={
              busy ||
              (tab === 'accounts'
                ? accounts.length
                : tab === 'jobs'
                  ? jobs.length
                  : articles.length) < 100
            }
            onClick={() => setPage(page + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </>
  );
}
