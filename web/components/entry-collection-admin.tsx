'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

type EntryStatus = {
  run_id: string; phase: string; status: string; blocked: boolean; reason: string;
  last_heartbeat: string | null; requests_today: number; daily_limit: number;
  sample_passed: boolean; canary_passed: boolean;
  counts: { status: string; outcome: string; count: number }[];
  failures: { error: string; count: number }[];
  samples: { id: number; name: string; source_id: string; status: string; error: string | null;
    sample_group: string; result: { outcome: string; pre_captured: boolean; request_count: number } | null }[];
  current_jobs: EntryStatus['samples']; page: number;
};
const outcomeNames: Record<string, string> = {
  pending: '待采集', success: '入口已补齐', empty: '暂无文章', unknown: '未捕获账号凭据',
  auth: '登录失效', verification: '需要人工验证', rate_limit: '上游限流',
  network: '网络失败', identity: '作者不匹配', invalid: '响应无效',
};

export function MPLogin({ token }: { token: string }) {
  const [session, setSession] = useState<{ session_id: string; qr: string } | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  async function action(name: string) {
    setBusy(true);
    try {
      const data = await api<{ session_id: string; qr: string; state: string }>('/admin/mp-login/' + name, {
        method: 'POST', headers: { Authorization: 'Bearer ' + token },
        body: JSON.stringify(name === 'poll' ? { session_id: session?.session_id } : {}),
      });
      if (name === 'start') { setSession(data); setMessage('请用有公众平台权限的微信扫码确认，再检查结果。二维码约 5 分钟有效。'); }
      else if (data.state === 'verified') { setSession(null); setMessage('公众平台登录已通过接口验证并保存。'); }
      else if (name === 'cancel') { setSession(null); setMessage('扫码会话已取消。'); }
      else setMessage(data.state === 'scanned' ? '已扫码，请在手机确认。' : '等待扫码确认。');
    } catch (e) { setMessage((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="space-y-4 rounded-xl border border-stone-200 bg-white p-6">
    <h2 className="text-lg font-semibold">公众平台扫码恢复</h2>
    <p className="text-sm text-stone-500">与桌面微信、微信读书账号池独立。凭据只保存在采集服务，不返回浏览器。</p>
    <div className="flex flex-wrap gap-3">
      <button className="button secondary small" disabled={busy || !!session} onClick={() => void action('start')}>生成登录二维码</button>
      {session && <><button className="button small" disabled={busy} onClick={() => void action('poll')}>检查扫码结果</button>
        <button className="button secondary small" disabled={busy} onClick={() => void action('cancel')}>取消会话</button></>}
    </div>
    {session && <img src={session.qr} alt="公众平台管理员登录二维码" width={240} height={240} />}
    {message && <p role="status" className="text-sm">{message}</p>}
  </section>;
}

export function EntryCollectionAdmin({ token }: { token: string }) {
  const [data, setData] = useState<EntryStatus | null>(null);
  const [secret, setSecret] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const headers = { Authorization: 'Bearer ' + token };
  const [page, setPage] = useState(1);
  async function load() {
    try { setData(await api<EntryStatus>('/admin/entry-collection?page=' + page, { headers })); }
    catch (e) { setMessage((e as Error).message); }
  }
  useEffect(() => { void load(); }, [token, page]);
  async function action(path: string, body?: object, method = 'POST') {
    setBusy(true); setMessage('');
    try {
      const reply = await api<{ token?: string }>('/admin/entry-collection' + path, {
        method, headers, body: body ? JSON.stringify(body) : undefined,
      });
      if (reply.token) setSecret(reply.token);
      if (method === 'DELETE') setSecret('');
      await load(); setMessage('操作完成；以当前队列状态及验收结果为准。');
    } catch (e) { setMessage((e as Error).message); }
    finally { setBusy(false); }
  }
  const count = (outcome: string) => data?.counts.filter(c => c.outcome === outcome).reduce((n, c) => n + c.count, 0) || 0;
  return <div className="space-y-6">
    <MPLogin token={token} />
    <section className="space-y-5 rounded-xl border border-stone-200 bg-white p-6">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">独立单篇补入口</h2>
        <button className="button secondary small" disabled={busy} onClick={() => void load()}>刷新状态</button></div>
      <p className="text-sm leading-7 text-stone-500">单桌面微信、单并发、间隔 20–30 秒、每日最多 500 次请求。只补公开文章链接，不采正文、图片或 AI，不改变关注和 API 订阅。先 20 个样本，再 50 个灰度，通过验收才允许全量。</p>
      {data && <>
        <p>阶段：{data.phase} · 状态：{data.status} · {data.reason || '等待桌面端执行'}</p>
        <div className="grid gap-4 sm:grid-cols-4">
          {[['目标与对照', data.counts.reduce((n, c) => n + c.count, 0)], ['成功', count('success')], ['暂无入口 / 未捕获', count('empty') + count('unknown')], ['今日请求', `${data.requests_today} / ${data.daily_limit}`]].map(([label, value]) =>
            <div className="rounded-lg bg-stone-50 p-4" key={label}><p className="text-sm text-stone-500">{label}</p><p className="mt-2 font-mono text-2xl">{value}</p></div>)}
        </div>
        <p className="text-sm">待处理：{data.counts.filter(c => ['queued', 'running', 'blocked', 'failed'].includes(c.status)).reduce((n, c) => n + c.count, 0)} · 桌面端最近心跳：{data.last_heartbeat ? new Date(data.last_heartbeat).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '尚未连接'}</p>
        <div className="flex flex-wrap gap-3">
          <button className="button secondary small" disabled={busy || !!data.run_id} onClick={() => void action('/prepare')}>固定目标与 20 个样本</button>
          <button className="button small" disabled={busy || !data.run_id} onClick={() => void action('/control', { action: 'resume' })}>{data.blocked ? '单条复验后恢复' : '开始 / 继续当前阶段'}</button>
          <button className="button secondary small" disabled={busy} onClick={() => void action('/control', { action: 'pause' })}>暂停</button>
          <button className="button secondary small" disabled={busy || !data.sample_passed || data.phase !== 'sample'} onClick={() => void action('/control', { action: 'canary' })}>启动 50 个灰度</button>
          <button className="button secondary small" disabled={busy || !data.canary_passed || data.phase !== 'canary'} onClick={() => { if (confirm('确认启动固定快照中的剩余缺入口账号？')) void action('/control', { action: 'full' }); }}>启动剩余目标</button>
        </div>
        <div className="flex flex-wrap gap-3 border-t border-stone-100 pt-5">
          <button className="button secondary small" disabled={busy} onClick={() => { if (confirm('轮换会使旧采集端令牌立即失效并暂停队列，是否继续？')) void action('/token'); }}>创建 / 轮换采集端令牌</button>
          <button className="button secondary small" disabled={busy} onClick={() => { if (confirm('确认撤销采集端令牌并暂停队列？')) void action('/token', undefined, 'DELETE'); }}>撤销令牌</button>
        </div>
        {secret && <div className="space-y-3 rounded-lg bg-amber-50 p-4"><p className="text-sm">令牌仅此次显示，请保存到本机私有配置；不要放进聊天、Git 或命令行参数。</p><code className="block break-all">{secret}</code><button className="button secondary small" onClick={() => setSecret('')}>已保存，隐藏令牌</button></div>}
        {data.failures.map(f => <p key={f.error} className="text-sm text-amber-800">{f.error}：{f.count}</p>)}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-3">样本公众号</th><th>分组</th><th>结果</th><th>预捕获凭据</th><th>请求数</th><th>操作</th></tr></thead><tbody>
          {data.current_jobs.map(s => <tr key={s.id} className="border-t border-stone-100"><td className="p-3">{s.name}</td><td>{s.sample_group === 'control' ? '对照' : '缺入口'}</td><td>{s.error || outcomeNames[s.result?.outcome || 'pending']}</td><td>{s.result ? (s.result.pre_captured ? '是' : '否') : '—'}</td><td>{s.result?.request_count ?? '—'}</td><td>{['failed', 'blocked', 'done'].includes(s.status) && <button className="button secondary small" disabled={busy} onClick={() => { if (confirm('确认重试该任务？成功结果也会重新验证。')) void action(`/jobs/${s.id}/retry`); }}>重试</button>}</td></tr>)}
        </tbody></table></div>
        <div className="flex items-center gap-4"><button className="button secondary small" disabled={page === 1 || busy} onClick={() => setPage(page-1)}>上一页</button><span>当前阶段第 {page} 页</span><button className="button secondary small" disabled={busy || data.current_jobs.length < 100} onClick={() => setPage(page+1)}>下一页</button></div>
      </>}
      {message && <p role="status" className="text-sm">{message}</p>}
    </section>
  </div>;
}
