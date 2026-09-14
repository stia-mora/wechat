'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  ArrowUpRight,
  BookmarkSimple,
  List,
  MagnifyingGlass,
  Plant,
  X,
} from '@phosphor-icons/react';
import { useState } from 'react';
import { useApi } from '@/lib/api';
import type { User } from '@/lib/types';

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname(),
    [open, setOpen] = useState(false);
  const { data: user } = useApi<User>('/auth/me');
  return (
    <>
      <a href="#main" className="skip-link">
        跳转到主要内容
      </a>
      <header className="border-b border-stone-200 bg-white/95">
        <div className="mx-auto flex h-20 max-w-[1320px] items-center justify-between gap-6 px-6">
          <Link href="/" className="flex items-center gap-3" aria-label="公众号发现首页">
            <span className="flex size-9 items-center justify-center rounded-lg bg-[#245745] text-white">
              <Plant size={23} />
            </span>
            <span className="text-lg font-semibold tracking-tight">
              公众号发现
              <span className="mt-0.5 block text-[9px] font-medium tracking-[0.2em] text-stone-500">
                WECHAT SOURCE
              </span>
            </span>
          </Link>
          <nav aria-label="主导航" className="hidden items-center gap-8 text-sm md:flex">
            {[
              ['/', '首页'],
              ['/discover', '发现'],
              ['/categories', '分类'],
              ['/rankings', '排行'],
            ].map(([href, label]) => (
              <Link key={href} href={href} className={`nav-link ${path === href ? 'active' : ''}`}>
                {label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-5 text-sm">
            <Link href="/search" aria-label="搜索" className="icon-button">
              <MagnifyingGlass size={20} />
            </Link>
            <Link href="/library?view=collections" className="hidden items-center gap-2 sm:flex">
              <BookmarkSimple size={18} />
              收藏
            </Link>
            <Link href={user ? '/library' : '/login'} className="button small">
              {user ? user.display_name : '登录 / 注册'}
            </Link>
            <button
              className="icon-button mobile-menu-button"
              onClick={() => setOpen(!open)}
              aria-label="切换菜单"
              aria-expanded={open}
            >
              {open ? <X size={20} /> : <List size={20} />}
            </button>
          </div>
        </div>
        {open && (
          <nav className="flex flex-wrap gap-6 border-t border-stone-100 p-5 md:hidden">
            {[
              ['/', '首页'],
              ['/discover', '发现'],
              ['/categories', '分类'],
              ['/rankings', '排行'],
              ['/library', '我的关注'],
            ].map(([href, label]) => (
              <Link key={href} href={href} onClick={() => setOpen(false)}>
                {label}
              </Link>
            ))}
          </nav>
        )}
      </header>
      <main id="main" className="mx-auto min-h-[75dvh] max-w-[1320px] px-6 pb-20">
        {children}
      </main>
      <footer className="border-t border-stone-200">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-between gap-5 px-6 py-8 text-xs text-stone-500">
          <span>公众号发现 · 为持续阅读，找到更好的起点。</span>
          <div className="flex gap-6">
            <span>内容归原作者所有</span>
            <Link href="/admin" className="flex items-center gap-1">
              数据管理 <ArrowUpRight size={12} />
            </Link>
          </div>
        </div>
      </footer>
    </>
  );
}
