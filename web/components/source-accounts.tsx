'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

type PoolAccount = {
  id: number;
  name: string;
  external_id: string | null;
  enabled: boolean;
  health: string;
  capability: string;
  max_tasks: number;
  max_subscriptions: number;
  subscriptions: number;
  current_tasks: number;
  consecutive_failures: number;
  total_failures: number;
  last_sync_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  verification_url?: string | null;
  cooldown_until: string | null;
};
type QR = { status: string; message: string; image?: string };
type Attempt = {
  id: number;
  name: string;
  job_id: number;
  status: string;
  started_at: string;
  error: string | null;
};
const health: Record<string, string> = {
  unconfigured: '待登录',
  healthy: '健康',
  expired: '登录失效',
  cooldown: '冷却中',
  error: '异常',
};
const capability: Record<string, string> = {
  unknown: '待验证',
  history: '历史分页',
  latest_only: '仅最新文章（降级）',
};
const time = (value: string | null) => (value ? new Date(value).toLocaleString('zh-CN') : '暂无');

export function SourceAccounts({ token }: { token: string }) {
  const [accounts, setAccounts] = useState<PoolAccount[]>([]);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [selected, setSelected] = useState<PoolAccount | null>(null);
  const [qr, setQR] = useState<QR | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const headers = { Authorization: 'Bearer ' + token };
  const base = '/admin/source-accounts';
  async function load() {
    const [a, b] = await Promise.all([
      api<PoolAccount[]>(base, { headers }),
      api<Attempt[]>(base + '/attempts/recent', { headers }),
    ]);
    setAccounts(a);
    setAttempts(b);
  }
  useEffect(() => {
    let live = true;
    async function poll() {
      try {
        const [a, b] = await Promise.all([
          api<PoolAccount[]>(base, { headers: { Authorization: 'Bearer ' + token } }),
          api<Attempt[]>(base + '/attempts/recent', {
            headers: { Authorization: 'Bearer ' + token },
          }),
        ]);
        if (live) {
          setAccounts(a);
          setAttempts(b);
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
  }, [token]);
  useEffect(() => {
    if (!selected || qr?.status !== 'waiting') return;
    let live = true;
    const timer = setInterval(async () => {
      try {
        const result = await api<QR>(base + '/' + selected.id + '/qr', {
          headers: { Authorization: 'Bearer ' + token },
        });
        if (live) setQR(result);
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    }, 2500);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [selected?.id, qr?.status, token]);
  async function action(fn: () => Promise<unknown>, text: string) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await fn();
      setMessage(text);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2 className="mb-3 text-xl font-semibold">微信读书账号池</h2>
      <p className="mb-6 max-w-4xl text-sm leading-7 text-stone-500">
        公众号采集任务会按健康状态与负载动态分配账号。书架记录不是永久绑定；账号失效后任务会释放租约，由其他健康账号接手。历史分页与仅最新文章能力分别记录。
      </p>
      <form
        className="mb-6 flex flex-wrap items-end gap-4 rounded-xl border border-stone-200 bg-white p-5"
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const f = new FormData(form);
          void action(async () => {
            await api(base, {
              method: 'POST',
              headers,
              body: JSON.stringify({
                name: f.get('name'),
                max_tasks: Number(f.get('tasks')),
                max_subscriptions: Number(f.get('capacity')),
              }),
            });
            form.reset();
          }, '已创建账号，请扫码或导入 Cookie');
        }}
      >
        <label className="field">
          账号备注
          <input required name="name" maxLength={80} placeholder="微信读书账号 1" />
        </label>
        <label className="field">
          最大并行任务
          <input required name="tasks" type="number" min={1} max={4} defaultValue={1} />
        </label>
        <label className="field">
          最大公众号数
          <input required name="capacity" type="number" min={1} max={1000} defaultValue={100} />
        </label>
        <button className="button" disabled={busy}>
          新增账号
        </button>
      </form>
      {error && (
        <p role="alert" className="mb-4 text-red-700">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="mb-4 text-[#245745]">
          {message}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="admin-table">
          <thead>
            <tr>
              <th>账号 / 状态</th>
              <th>负载 / 能力</th>
              <th>最近同步与失败</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.id}>
                <td>
                  <strong>{a.name}</strong>
                  <p>{a.enabled ? health[a.health] : '已禁用'}</p>
                  <p className="text-xs text-stone-400">
                    {a.external_id ? 'VID ' + a.external_id : '尚未登录'}
                  </p>
                </td>
                <td>
                  <p>
                    任务 {a.current_tasks} / {a.max_tasks}
                  </p>
                  <p>
                    公众号 {a.subscriptions} / {a.max_subscriptions}
                  </p>
                  <p>最近任务：{capability[a.capability]}</p>
                </td>
                <td>
                  <p>{time(a.last_sync_at)}</p>
                  <p className="text-xs">
                    最近失败：{time(a.last_failure_at)} · 连续 {a.consecutive_failures} / 累计{' '}
                    {a.total_failures}
                  </p>
                  {a.cooldown_until && <p className="text-xs">冷却至 {time(a.cooldown_until)}</p>}
                  {a.last_error && <p className="max-w-sm text-xs text-red-700">{a.last_error}</p>}
                  {a.last_error?.includes('正文页面要求验证') && <p className="max-w-sm text-xs">请用对应微信打开原文并处理验证，再点击「检测」。浏览器验证不一定解除采集接口限制。{a.verification_url && <a href={a.verification_url} target="_blank" rel="noreferrer" className="underline">打开失败原文</a>}</p>}
                </td>
                <td>
                  <div className="flex flex-wrap gap-2">
                    <button
                      disabled={busy}
                      className="button secondary small"
                      onClick={() => {
                        setSelected(a);
                        setQR(null);
                      }}
                    >
                      登录 / 配置
                    </button>
                    <button
                      disabled={busy || !!a.current_tasks}
                      className="button secondary small"
                      onClick={() =>
                        action(
                          () => api(base + '/' + a.id + '/check', { method: 'POST', headers }),
                          '登录与书架检查成功',
                        )
                      }
                    >
                      检测
                    </button>
                    <button
                      disabled={busy}
                      className="button secondary small"
                      onClick={() =>
                        action(
                          () =>
                            api(base + '/' + a.id, {
                              method: 'PATCH',
                              headers,
                              body: JSON.stringify({ ...a, enabled: !a.enabled }),
                            }),
                          a.enabled ? '已禁用，新任务将选择其他账号' : '已启用',
                        )
                      }
                    >
                      {a.enabled ? '禁用' : '启用'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!accounts.length && (
          <p className="p-6 text-sm text-stone-500">
            请先添加账号。可以依次添加并登录两个账号，再开始小样本采集。
          </p>
        )}
      </div>
      {selected && (
        <section className="my-6 rounded-xl border border-[#b8c9be] bg-white p-6">
          <div className="flex justify-between">
            <h3 className="text-lg font-semibold">{selected.name}</h3>
            <button
              className="button secondary small"
              onClick={() => {
                setSelected(null);
                setQR(null);
              }}
            >
              收起
            </button>
          </div>
          <div className="mt-5 grid gap-6 md:grid-cols-2">
            <div>
              <button
                disabled={busy}
                className="button"
                onClick={() =>
                  action(
                    async () =>
                      setQR(
                        await api<QR>(base + '/' + selected.id + '/qr', {
                          method: 'POST',
                          headers,
                        }),
                      ),
                    '二维码已获取',
                  )
                }
              >
                获取登录二维码
              </button>
              {qr?.image && (
                <img
                  src={qr.image}
                  alt="微信读书登录二维码"
                  width={240}
                  height={240}
                  className="mt-4"
                />
              )}
              {qr && (
                <p role="status" className="mt-3 text-sm">
                  {qr.message}
                </p>
              )}
              <p className="mt-3 text-xs leading-6 text-stone-500">
                扫码会话按账号隔离，二维码有效期 5 分钟。只有书架校验通过后才进入健康池。
              </p>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const form = e.currentTarget;
                const f = new FormData(form);
                void action(async () => {
                  await api(base + '/' + selected.id + '/cookie', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ cookie: f.get('cookie'), ticket: f.get('ticket') }),
                  });
                  form.reset();
                }, '凭据已验证并加密保存');
              }}
            >
              <label className="field">
                或粘贴浏览器完整 Cookie
                <textarea
                  name="cookie"
                  rows={4}
                  required
                  autoComplete="off"
                  placeholder="wr_vid=…; wr_skey=…; wr_rt=…"
                />
              </label>
              <label className="field mt-3">
                Ticket（可选，旧会话兼容）
                <input type="password" name="ticket" autoComplete="off" />
              </label>
              <button disabled={busy} className="button secondary mt-4">
                验证并保存 Cookie
              </button>
              <p className="mt-2 text-xs leading-6 text-stone-500">
                在 weread.qq.com 登录，从请求头取得
                Cookie。凭据只发送到本机后台，不会在账号列表或日志回显。
              </p>
            </form>
          </div>
          <form
            className="mt-6 flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void action(
                () =>
                  api(base + '/' + selected.id, {
                    method: 'PATCH',
                    headers,
                    body: JSON.stringify({
                      name: f.get('name'),
                      enabled: selected.enabled,
                      max_tasks: Number(f.get('tasks')),
                      max_subscriptions: Number(f.get('capacity')),
                    }),
                  }),
                '负载配置已保存',
              );
            }}
          >
            <label className="field">
              备注
              <input name="name" required defaultValue={selected.name} />
            </label>
            <label className="field">
              并行任务
              <input
                name="tasks"
                required
                type="number"
                min={1}
                max={4}
                defaultValue={selected.max_tasks}
              />
            </label>
            <label className="field">
              公众号容量
              <input
                name="capacity"
                required
                type="number"
                min={1}
                max={1000}
                defaultValue={selected.max_subscriptions}
              />
            </label>
            <button className="button secondary" disabled={busy}>
              保存负载
            </button>
          </form>
        </section>
      )}
      <h3 className="mb-3 mt-8 text-lg font-semibold">最近采集分配记录</h3>
      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="admin-table">
          <thead>
            <tr>
              <th>任务</th>
              <th>执行账号</th>
              <th>状态</th>
              <th>时间 / 失败原因</th>
            </tr>
          </thead>
          <tbody>
            {attempts.map((a) => (
              <tr key={a.id}>
                <td>#{a.job_id}</td>
                <td>{a.name}</td>
                <td>{a.status}</td>
                <td>
                  {time(a.started_at)}
                  {a.error && <p className="text-xs text-red-700">{a.error}</p>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
