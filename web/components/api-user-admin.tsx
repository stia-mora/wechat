'use client';
import { useEffect, useState } from 'react';
import { api, date } from '@/lib/api';
import type { ApiAdminUser, ApiCapability, ApiPlan, ApiSubscription } from '@/lib/types';
import { ErrorState, Loading } from '@/components/ui';

export function ApiUserAdmin({ token }: { token: string }) {
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState<ApiAdminUser[]>([]);
  const [plans, setPlans] = useState<ApiPlan[]>([]);
  const [selected, setSelected] = useState<ApiAdminUser | null>(null);
  const [panel, setPanel] = useState<'subscriptions' | 'capabilities' | null>(null);
  const [subscriptions, setSubscriptions] = useState<ApiSubscription[]>([]);
  const [capabilities, setCapabilities] = useState<ApiCapability[]>([]);
  const [capabilityDrafts, setCapabilityDrafts] = useState<Record<string, {
    enabled: boolean; requests_per_minute: string; requests_per_day: string;
  }>>({});
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
  async function loadPlans() {
    try {
      setPlans(await admin<ApiPlan[]>('/api-plans'));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
    void loadPlans();
  }, []);
  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await fn();
      await load();
      if (selected && panel === 'subscriptions') {
        const rows = await admin<ApiSubscription[]>('/api-users/' + selected.id + '/subscriptions');
        setSubscriptions(rows);
      }
      if (selected && panel === 'capabilities') {
        const result = await admin<{ capabilities: ApiCapability[] }>('/api-users/' + selected.id + '/capabilities');
        setCapabilities(result.capabilities);
        setCapabilityDrafts(Object.fromEntries(result.capabilities.map((capability) => [capability.code, {
          enabled: capability.enabled,
          requests_per_minute: String(capability.requests_per_minute),
          requests_per_day: String(capability.requests_per_day),
        }])));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function showSubscriptions(user: ApiAdminUser) {
    setSelected(user);
    setPanel('subscriptions');
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
  async function showCapabilities(user: ApiAdminUser) {
    setSelected(user);
    setPanel('capabilities');
    setBusy(true);
    setError('');
    try {
      const result = await admin<{ capabilities: ApiCapability[] }>('/api-users/' + user.id + '/capabilities');
      setCapabilities(result.capabilities);
      setCapabilityDrafts(Object.fromEntries(result.capabilities.map((capability) => [capability.code, {
        enabled: capability.enabled,
        requests_per_minute: String(capability.requests_per_minute),
        requests_per_day: String(capability.requests_per_day),
      }])));
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
                <th>今日调用</th>
                <th>最近调用</th>
                <th>套餐</th>
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
                  <td>{user.calls_today}</td>
                  <td>{date(user.last_used_at)}</td>
                  <td>
                    <select
                      className="input min-w-28"
                      value={user.plan_code}
                      disabled={busy}
                      onChange={(e) => action(() =>
                        admin('/api-users/' + user.id + '/plan', {
                          method: 'PUT', body: JSON.stringify({ plan_code: e.target.value }),
                        }),
                      )}
                    >
                      {plans.map((plan) => <option value={plan.code} key={plan.code}>{plan.name}</option>)}
                    </select>
                  </td>
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
                    <div className="flex flex-wrap gap-2">
                      <button className="button secondary small" disabled={busy} onClick={() => showSubscriptions(user)}>
                        管理订阅
                      </button>
                      <button className="button secondary small" disabled={busy} onClick={() => showCapabilities(user)}>
                        能力 / 限额
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && panel === 'subscriptions' && (
        <div className="mt-6 border border-stone-200 bg-white p-5">
          <div className="flex items-center justify-between gap-4">
            <h3 className="font-semibold">{selected.email} 的 API 订阅</h3>
            <button className="button secondary small" onClick={() => { setSelected(null); setPanel(null); }}>关闭</button>
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
      {selected && panel === 'capabilities' && (
        <div className="mt-6 border border-stone-200 bg-white p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h3 className="font-semibold">{selected.email} 的 API 能力</h3>
              <p className="mt-1 text-sm text-stone-500">保存后会覆盖套餐默认值；重置将恢复套餐配置。</p>
            </div>
            <button className="button secondary small" onClick={() => { setSelected(null); setPanel(null); }}>关闭</button>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>能力</th>
                  <th>开通</th>
                  <th>每分钟</th>
                  <th>每日</th>
                  <th>定制</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {capabilities.map((capability) => {
                  const draft = capabilityDrafts[capability.code] || {
                    enabled: capability.enabled,
                    requests_per_minute: String(capability.requests_per_minute),
                    requests_per_day: String(capability.requests_per_day),
                  };
                  return (
                    <tr key={capability.code}>
                      <td>
                        <strong>{capability.name}</strong>
                        <p className="mt-1 font-mono text-xs text-stone-400">{capability.code}</p>
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={draft.enabled}
                          onChange={(e) => setCapabilityDrafts({
                            ...capabilityDrafts,
                            [capability.code]: { ...draft, enabled: e.target.checked },
                          })}
                        />
                      </td>
                      <td>
                        <input
                          className="input w-24"
                          type="number"
                          min={1}
                          value={draft.requests_per_minute}
                          onChange={(e) => setCapabilityDrafts({
                            ...capabilityDrafts,
                            [capability.code]: { ...draft, requests_per_minute: e.target.value },
                          })}
                        />
                      </td>
                      <td>
                        <input
                          className="input w-28"
                          type="number"
                          min={1}
                          value={draft.requests_per_day}
                          onChange={(e) => setCapabilityDrafts({
                            ...capabilityDrafts,
                            [capability.code]: { ...draft, requests_per_day: e.target.value },
                          })}
                        />
                      </td>
                      <td>{capability.customized ? '是' : '否'}</td>
                      <td>
                        <div className="flex gap-2">
                          <button
                            className="button secondary small"
                            disabled={busy}
                            onClick={() => action(() => admin(
                              '/api-users/' + selected.id + '/capabilities/' + capability.code,
                              {
                                method: 'PUT',
                                body: JSON.stringify({
                                  enabled: draft.enabled,
                                  requests_per_minute: Number(draft.requests_per_minute),
                                  requests_per_day: Number(draft.requests_per_day),
                                }),
                              },
                            ))}
                          >
                            保存
                          </button>
                          {capability.customized && (
                            <button
                              className="button secondary small"
                              disabled={busy}
                              onClick={() => action(() => admin(
                                '/api-users/' + selected.id + '/capabilities/' + capability.code,
                                { method: 'DELETE' },
                              ))}
                            >
                              重置
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
