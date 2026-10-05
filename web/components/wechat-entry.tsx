'use client';
import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight } from '@phosphor-icons/react';
import { apiPath } from '@/lib/api';
import type { Account } from '@/lib/types';

export function WechatEntry({ account, className = 'flex items-center gap-1 font-medium text-[#245745]' }: {
  account: Account;
  className?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState('');
  const identity = account.wechat_id || account.name;
  useEffect(() => {
    if (open) dialog.current?.showModal();
  }, [open]);
  if (!account.source_url) return null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(identity);
      setFeedback('已复制，打开微信后在搜索中粘贴。');
    } catch {
      setFeedback('复制未成功，请手动选中上方文字复制。');
    }
  }

  return (
    <>
      <button type="button" className={className} onClick={() => {
        if (/MicroMessenger/i.test(navigator.userAgent)) {
          window.location.assign(account.source_url);
          return;
        }
        setOpen(true);
      }}>
        打开微信公众号 <ArrowUpRight size={15} />
      </button>
      {open && <dialog ref={dialog} onClose={() => { setOpen(false); setFeedback(''); }}
        className="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border border-stone-200 bg-white p-6 text-stone-800 backdrop:bg-stone-900/40"
        aria-label={'在微信中打开' + account.name}>
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-lg font-semibold">在微信中打开{account.name}</h2>
          <button type="button" onClick={() => dialog.current?.close()} className="shrink-0 text-sm text-stone-500">关闭</button>
        </div>
        <p className="mt-3 text-sm leading-6 text-stone-500">用微信扫一扫，进入该公众号。手机上也可保存二维码后，在微信扫一扫中选择图片。</p>
        <img src={apiPath(`/accounts/${account.id}/wechat-qr`)}
          alt={account.name + '的微信入口二维码'} width={240} height={240} className="mx-auto my-4" />
        <p className="text-sm text-stone-500">也可复制{account.wechat_id ? '微信号' : '公众号名称'}，打开微信后搜索：</p>
        <input readOnly value={identity} aria-label={account.wechat_id ? '公众号微信号' : '公众号名称'} className="input mt-3 w-full" />
        <div className="mt-4 flex flex-wrap gap-3">
          <button type="button" className="button secondary" onClick={copy}>复制{account.wechat_id ? '微信号' : '名称'}</button>
          <a className="button" href="weixin://">打开微信</a>
        </div>
        <p role="status" className="mt-3 text-xs leading-6 text-[#245745]">{feedback}</p>
        <p className="mt-3 text-xs leading-6 text-stone-500">打开微信只会启动应用；进入这个公众号请扫码或搜索。如浏览器没有唤起微信，请手动打开微信。</p>
      </dialog>}
    </>
  );
}
