'use client';
import { useEffect, useState } from 'react';
import { api, date } from '@/lib/api';
import type { ApiAdminUser, ApiSubscription } from '@/lib/types';
import { ErrorState, Loading } from '@/components/ui';

export function ApiUserAdmin({ token }: { token: string }) {
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState<ApiAdminUser[]>([]);
  const [selected, setSelected] = useState<ApiAdminUser | null>(null);
  const [subscriptions, setSubscriptions] = useState<ApiSubscription[]>([]);
  const [limits, setLimits] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const headers = { Authorization: 'Bearer ' + token };
  async function admin<T>(path: string, options: RequestInit = {}) {
    return api<T>('/admin' + path, { ...options, headers: { ...headers, ...options.headers } });
  }
  async function load() {
    setLoading(true);
    setError('');
    try {
      const rows = await admin<ApiAdminUser[]>('/api-users?q=' + encodeURIComponent(query));
      setUsers(rows);
      setLimits(Object.fromEntries(rows.map((user) => [user.id, String(user.subscription_limit)])));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await fn();
      await load();
      if (selected) {
        const rows = await admin<ApiSubscription[]>('/api-users/' + selected.id + '/subscriptions');
        setSubscriptions(rows);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function showSubscriptions(user: ApiAdminUser) {
    setSelected(user);
    setBusy(true);
    setError('');
    try {
      setSubscriptions(await admin<ApiSubscription[]>('/api-users/' + user.id + '/subscriptions'));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">用户 API</h2>
          <p className="mt-1 text-sm text-stone-500">Key 只显示数量和最近使用时间，不能查看密钥内容。</p>
        </div>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void load();
          }}
        >
          <input
            className="input w-64"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="邮箱或昵称"
            maxLength={100}
          />
          <button className="button secondary small" disabled={busy}>搜索</button>
        </form>
      </div>
      {error && <ErrorState message={error} />}
      {loading ? (
        <Loading />
      ) : (
        <div className="overflow-x-auto border border-stone-200 bg-white">
          <table className="admin-table">
            <thead>
              <tr>
                <th>用户</th>
                <th>API 订阅</th>
                <th>有效 Key</th>
                <th>最近调用</th>
                <th>订阅上限</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>
                    <strong>{user.display_name}</strong>
                    <p className="mt-1 text-xs text-stone-400">{user.email}</p>
                  </td>
                  <td>{user.subscriptions_used} / {user.subscription_limit}</td>
                  <td>{user.key_count}</td>
                  <td>{date(user.last_used_at)}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <input
                        aria-label={user.email + ' 的订阅上限'}
                        className="input w-20"
                        type="number"
                        min={0}
                        value={limits[user.id] ?? String(user.subscription_limit)}
                        onChange={(e) => setLimits({ ...limits, [user.id]: e.target.value })}
                      />
                      <button
                        className="button secondary small"
                        disabled={busy}
                        onClick={() =>
                          action(() =>
                            admin('/api-users/' + user.id + '/access', {
                              method: 'PUT',
                              body: JSON.stringify({ subscription_limit: Number(limits[user.id]) }),
                            }),
                          )
                        }
                      >
                        保存
                      </button>
                    </div>
                  </td>
                  <td>
                    <button className="button secondary small" disabled={busy} onClick={() => showSubscriptions(user)}>
                      管理订阅
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && (
        <div className="mt-6 border border-stone-200 bg-white p-5">
          <div className="flex items-center justify-between gap-4">
            <h3 className="font-semibold">{selected.email} 的 API 订阅</h3>
            <button className="button secondary small" onClick={() => setSelected(null)}>关闭</button>
          </div>
          <div className="mt-3 divide-y divide-stone-100">
            {subscriptions.map((account) => (
              <div className="flex items-center justify-between gap-4 py-3" key={account.id}>
                <span>{account.name} <small className="text-stone-400">{account.wechat_id}</small></span>
                <button
                  className="button secondary small"
                  disabled={busy}
                  onClick={() =>
                    action(() =>
                      admin('/api-users/' + selected.id + '/subscriptions/' + account.id, { method: 'DELETE' }),
                    )
                  }
                >
                  移除订阅
                </button>
              </div>
            ))}
            {!subscriptions.length && <p className="py-4 text-sm text-stone-500">没有 API 订阅。</p>}
          </div>
        </div>
      )}
    </section>
  );
}
