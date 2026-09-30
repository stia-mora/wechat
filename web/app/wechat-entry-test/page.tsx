'use client';
import Link from 'next/link';
import { useState } from 'react';
import { useApi } from '@/lib/api';
import type { Account, Page } from '@/lib/types';
import { ErrorState, Loading } from '@/components/ui';

export default function WechatEntryTest() {
  const accounts = useApi<Page<Account>>('/accounts?sort=featured&limit=12');
  const [selected, setSelected] = useState('');
  const [originalId, setOriginalId] = useState('');
  const [attempt, setAttempt] = useState('');
  const account = accounts.data?.items.find((item) => String(item.id) === selected)
    || accounts.data?.items[0];
  const identity = originalId.trim() || account?.wechat_id || '';
  const valid = /^[A-Za-z0-9_-]{1,64}$/.test(identity);
  const target = encodeURIComponent(identity);
  const fallback = account ? encodeURIComponent(window.location.origin + '/wechat/wechat-entry-test') : '';
  const methods = [
    { name: '方式一：安卓应用链接', href: `intent://profile/${target}#Intent;scheme=weixin;package=com.tencent.mm;S.browser_fallback_url=${fallback};end` },
    { name: '方式二：公众号资料协议', href: `weixin://profile/${target}` },
    { name: '方式三：客户端资料协议', href: `weixin://dl/profile/${target}` },
  ];

  return (
    <section className="mx-auto max-w-2xl py-10">
      <Link href="/" className="text-sm text-[#245745]">返回首页</Link>
      <h1 className="mt-5 text-2xl font-semibold">安卓公众号直达验证</h1>
      <p className="mt-4 text-sm leading-7 text-stone-500">
        请用安装了微信的安卓手机，在 Chrome 或手机自带浏览器中打开本页。
        以下是待验证的跳转方式，尚未确认兼容当前微信版本。
        成功标准是一次点击后进入所选公众号的资料页或会话页。
      </p>
      {accounts.loading ? <Loading /> : accounts.error ? (
        <ErrorState message={accounts.error} retry={accounts.reload} />
      ) : account ? (
        <div className="mt-6 rounded-xl border border-stone-200 bg-white p-5">
          <label htmlFor="test-account" className="block text-sm font-medium">目标公众号</label>
          <select id="test-account" className="input mt-2 w-full" value={account.id}
            onChange={(event) => { setSelected(event.target.value); setOriginalId(''); setAttempt(''); }}>
            {accounts.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <p className="mt-3 text-sm text-stone-500">微信号：{account.wechat_id || '暂无'}</p>
          <label htmlFor="test-original-id" className="mt-5 block text-sm font-medium">公众号原始 ID（可选）</label>
          <input id="test-original-id" className="input mt-2 w-full" placeholder="如有已确认的 gh_ 原始 ID，可填写"
            maxLength={64} value={originalId} onChange={(event) => { setOriginalId(event.target.value); setAttempt(''); }} />
          <p className="mt-2 text-xs leading-6 text-stone-500">
            未填写时用真实微信号尝试。原始 ID、微信号和 biz 是不同字段，不会将 biz 冒充原始 ID；
            协议是否接受微信号也需要验证。
          </p>
          {valid ? (
            <div className="mt-5 grid gap-3">
              {methods.map((method) => (
                <a key={method.name} className="button" href={method.href}
                  onClick={() => setAttempt(`${method.name} → ${account.name}。返回此页后，请确认是否已进入该公众号。`)}>
                  {method.name}
                </a>
              ))}
              <a className="button secondary" href="weixin://"
                onClick={() => setAttempt('对照测试：仅请求启动微信，不请求进入公众号。')}>
                对照测试：仅启动微信
              </a>
            </div>
          ) : <p role="alert" className="mt-4 text-sm text-red-700">请输入有效的公众号原始 ID 或微信号。</p>}
          <p role="status" className="mt-4 text-sm leading-7 text-[#245745]">{attempt}</p>
          <p className="mt-3 text-sm leading-7 text-stone-500">
            仅打开微信首页、自己的个人资料、公众号列表或搜索页，都不算直达成功。
            若三种方式都不成功，请反馈手机型号、浏览器、微信版本及实际打开的页面。
          </p>
        </div>
      ) : <p className="mt-6 text-stone-500">暂无可测试的公开精选账号。</p>}
      <p className="mt-6 text-xs leading-6 text-stone-500">
        本页只用于验证，结果确认前不替换首页入口。浏览器离开页面不能证明进入了目标公众号。
      </p>
    </section>
  );
}
