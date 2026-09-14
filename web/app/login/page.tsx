'use client';
import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Plant } from '@phosphor-icons/react';
import { api } from '@/lib/api';
import { Loading } from '@/components/ui';
function Login() {
  const params = useSearchParams(),
    [register, setRegister] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      await api('/auth/' + (register ? 'register' : 'login'), {
        method: 'POST',
        body: JSON.stringify(Object.fromEntries(form)),
      });
      const next = params.get('next');
      location.href =
        next && next.startsWith('/') && !next.startsWith('//') && !next.includes('\\')
          ? next
          : '/library';
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <div className="mx-auto my-16 max-w-md rounded-2xl border border-stone-200 bg-white p-9">
      <Plant size={34} className="mb-7 text-[#245745]" />
      <h1 className="text-2xl font-semibold">
        {register ? '建立你的阅读地图' : '欢迎回到你的信息源'}
      </h1>
      <p className="mb-8 mt-3 text-sm leading-6 text-stone-500">
        登录后，收藏、关注与最近浏览会在账号中同步保存。
      </p>
      <form className="space-y-5" onSubmit={submit}>
        {register && (
          <label className="field">
            昵称
            <input name="display_name" required maxLength={40} autoComplete="nickname" />
          </label>
        )}
        <label className="field">
          邮箱
          <input name="email" type="email" required autoComplete="email" />
        </label>
        <label className="field">
          密码
          <input
            name="password"
            type="password"
            minLength={8}
            maxLength={128}
            required
            autoComplete={register ? 'new-password' : 'current-password'}
          />
          <span className="text-xs text-stone-400">至少 8 个字符</span>
        </label>
        {error && (
          <p className="text-sm text-red-700" role="alert">
            {error}
          </p>
        )}
        <button disabled={busy} className="button w-full">
          {busy ? '处理中…' : register ? '创建账号' : '登录'}
        </button>
      </form>
      <button
        className="mt-6 w-full text-center text-sm text-[#245745]"
        onClick={() => {
          setRegister(!register);
          setError('');
        }}
      >
        {register ? '已有账号？去登录' : '还没有账号？免费注册'}
      </button>
    </div>
  );
}
export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <Login />
    </Suspense>
  );
}
