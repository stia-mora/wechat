'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api, date, useApi } from '@/lib/api';
import type { ApiAccess, ApiCandidate, ApiKey } from '@/lib/types';
import { ErrorState, Loading } from '@/components/ui';

export function ApiAccessManager() {
  const access = useApi<ApiAccess>('/me/api');
  const [query, setQuery] = useState('');
  const candidates = useApi<ApiCandidate[]>('/me/api/candidates?q=' + encodeURIComponent(query));
  const [keyName, setKeyName] = useState('默认 Agent');
  const [newKey, setNewKey] = useState<ApiKey & { key: string } | null>(null);
  const [apiRoot, setApiRoot] = useState('/wechat/api/v1');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => setApiRoot(location.origin + '/wechat/api/v1'), []);

  async function change(fn: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await fn();
      access.reload();
      candidates.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function createKey() {
    setBusy(true);
    setError('');
    try {
      const result = await api<{ key: string; api_key: ApiKey }>('/me/api/keys', {
        method: 'POST',
        body: JSON.stringify({ name: keyName }),
      });
      setNewKey({ ...result.api_key, key: result.key });
      access.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (access.loading) return <Loading />;
  if (access.error)
    return access.error === '请先登录' ? (
      <div className="py-14 text-center">
        <h2 className="text-xl font-semibold">登录后管理 Agent API。</h2>
        <Link href="/login?next=/library?view=api" className="button mt-6">
          登录 / 注册
        </Link>
      </div>
    ) : (
      <ErrorState message={access.error} retry={access.reload} />
    );
  const data = access.data;
  if (!data) return null;
  return (
    <div className="space-y-9">
      {error && <ErrorState message={error} />}
      <section className="border-y border-stone-200 py-6">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="eyebrow">AGENT API</p>
            <h2 className="mt-2 text-2xl font-semibold">API 订阅额度</h2>
          </div>
          <div className="flex gap-6 text-sm">
            <span>已用 {data.subscriptions_used}</span>
            <span>剩余 {data.subscriptions_remaining}</span>
            <span>上限 {data.subscription_limit}</span>
          </div>
        </div>
      </section>

      <section>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold">API Key</h2>
            <p className="mt-1 text-sm text-stone-500">所有 Key 共享同一订阅集合和额度。</p>
          </div>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void createKey();
            }}
          >
            <input
              className="input w-48"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              maxLength={80}
              required
              aria-label="Key 名称"
            />
            <button disabled={busy} className="button small">
              创建 Key
            </button>
          </form>
        </div>
        {newKey && (
          <div className="mb-4 border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-semibold">请立即保存此 API Key，关闭后无法再次查看。</p>
            <code className="mt-3 block break-all rounded bg-white p-3">{newKey.key}</code>
            <button className="button secondary small mt-3" onClick={() => setNewKey(null)}>
              我已保存
            </button>
          </div>
        )}
        <div className="overflow-x-auto border border-stone-200 bg-white">
          <table className="admin-table">
            <thead>
              <tr>
                <th>名称</th>
                <th>前缀</th>
                <th>创建时间</th>
                <th>最近调用</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {data.keys.map((key) => (
                <tr key={key.id}>
                  <td>{key.name}</td>
                  <td className="font-mono text-xs">{key.key_prefix}...</td>
                  <td>{date(key.created_at)}</td>
                  <td>{date(key.last_used_at)}</td>
                  <td>{key.revoked_at ? '已撤销' : '有效'}</td>
                  <td>
                    {!key.revoked_at && (
                      <button
                        disabled={busy}
                        className="button secondary small"
                        onClick={() => change(() => api('/me/api/keys/' + key.id, { method: 'DELETE' }))}
                      >
                        撤销
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold">API 订阅</h2>
            <p className="mt-1 text-sm text-stone-500">仅影响 Agent API，不改变站内关注。</p>
          </div>
          <input
            className="input w-64"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索全站已审核公众号"
            maxLength={100}
          />
        </div>
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="border border-stone-200 bg-white p-5">
            <h3 className="font-semibold">已导出订阅</h3>
            <div className="mt-3 divide-y divide-stone-100">
              {data.subscriptions.map((account) => (
                <div className="flex items-center justify-between gap-3 py-3" key={account.id}>
                  <div className="min-w-0">
                    <p className="truncate font-medium">{account.name}</p>
                    <p className="text-xs text-stone-500">{account.wechat_id || '微信公众账号'} · {account.status === 'approved' ? '已审核' : '已隐藏'}</p>
                  </div>
                  <button
                    disabled={busy}
                    className="button secondary small"
                    onClick={() =>
                      change(() => api('/me/api/subscriptions/' + account.id, { method: 'DELETE' }))
                    }
                  >
                    移除
                  </button>
                </div>
              ))}
              {!data.subscriptions.length && <p className="py-5 text-sm text-stone-500">尚未选择 API 订阅。</p>}
            </div>
          </div>
          <div className="border border-stone-200 bg-white p-5">
            <h3 className="font-semibold">可添加公众号</h3>
            <p className="mt-1 text-xs text-stone-500">已关注公众号优先显示。</p>
            {candidates.loading ? (
              <p className="py-5 text-sm text-stone-500">加载中…</p>
            ) : candidates.error ? (
              <p className="py-5 text-sm text-red-700">{candidates.error}</p>
            ) : (
              <div className="mt-3 divide-y divide-stone-100">
                {candidates.data?.map((account) => (
                  <div className="flex items-center justify-between gap-3 py-3" key={account.id}>
                    <div className="min-w-0">
                      <p className="truncate font-medium">{account.name}</p>
                      <p className="text-xs text-stone-500">
                        {account.wechat_id || '微信公众账号'}{account.following ? ' · 已关注' : ''}
                      </p>
                    </div>
                    <button
                      disabled={busy || account.subscribed || data.subscriptions_remaining === 0}
                      className="button secondary small"
                      onClick={() =>
                        change(() =>
                          api('/me/api/subscriptions', {
                            method: 'POST',
                            body: JSON.stringify({ account_id: account.id }),
                          }),
                        )
                      }
                    >
                      {account.subscribed ? '已订阅' : '添加'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="border-y border-stone-200 py-6">
        <h2 className="text-xl font-semibold">Agent 接入</h2>
        <p className="mt-2 text-sm text-stone-500">接口根地址：<code>{apiRoot}</code></p>
        <pre className="mt-4 overflow-x-auto bg-stone-950 p-4 text-xs leading-6 text-stone-100">{`curl -H "Authorization: Bearer YOUR_API_KEY" \\
  ${apiRoot}/feed?limit=20\n\nOpenAPI: ${apiRoot}/openapi.json`}</pre>
      </section>
    </div>
  );
}
