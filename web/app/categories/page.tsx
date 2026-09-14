'use client';
import Link from 'next/link';
import { ArrowUpRight } from '@phosphor-icons/react';
import { useApi } from '@/lib/api';
import type { Category } from '@/lib/types';
import { Loading, ErrorState } from '@/components/ui';
export default function Categories() {
  const { data, error, loading, reload } = useApi<Category[]>('/categories');
  return (
    <>
      <section className="py-12">
        <span className="eyebrow">A MAP OF CURIOSITY</span>
        <h1 className="mt-3 text-3xl font-semibold">每一种好奇，都有去处。</h1>
        <p className="mt-4 text-sm text-stone-500">沿着领域探索，找到适合自己的信息源。</p>
      </section>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} retry={reload} />
      ) : (
        <div className="grid gap-7 md:grid-cols-2">
          {data
            ?.filter((c) => !c.parent_id)
            .map((c, i) => (
              <section key={c.id} className="rounded-xl border border-stone-200 bg-white p-8">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <span className="font-mono text-3xl text-[#b0bca4]">0{i + 1}</span>
                    <h2 className="text-2xl font-semibold">{c.name}</h2>
                  </div>
                  <Link
                    className="flex items-center gap-2 text-xs text-stone-500"
                    href={'/discover?category=' + c.id}
                  >
                    {c.account_count} 个公众号 <ArrowUpRight size={17} />
                  </Link>
                </div>
                <div className="mt-7 flex flex-wrap gap-3 border-t border-stone-100 pt-6">
                  {data
                    .filter((s) => s.parent_id === c.id)
                    .map((s) => (
                      <Link
                        key={s.id}
                        href={'/discover?category=' + s.id}
                        className="rounded-md bg-[#f4f5ef] px-3 py-2 text-sm text-stone-600 hover:bg-[#e7eddf]"
                      >
                        {s.name}
                      </Link>
                    ))}
                </div>
              </section>
            ))}
        </div>
      )}
    </>
  );
}
