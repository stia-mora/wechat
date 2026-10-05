import AccountDetail from '@/components/account-detail';
import { JsonLd } from '@/components/json-ld';
import { serverApi } from '@/lib/server-api';
import { absoluteUrl, pageMetadata } from '@/lib/seo';
import type { Account, Article, Page } from '@/lib/types';

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const account = await serverApi<Account>(`/accounts/${encodeURIComponent(id)}`);
  return pageMetadata(
    `${account.name}公众号 · ${account.category || '信息源'}简介与文章`,
    (
      account.description ||
      account.profile?.profile_summary ||
      `${account.name}的公众号资料、内容方向及历史文章。`
    ).slice(0, 160),
    `/accounts/${account.id}`,
  );
}

export default async function Page({ params }: Props) {
  const { id } = await params;
  const [account, articles] = await Promise.all([
    serverApi<Account>(`/accounts/${encodeURIComponent(id)}`),
    serverApi<Page<Article>>(
      `/articles?account_id=${encodeURIComponent(id)}&page=1&sort=latest&q=&limit=10`,
    ),
  ]);
  return (
    <>
      <JsonLd
        data={{
          '@context': 'https://schema.org',
          '@type': account.account_type === '个人IP' ? 'Person' : 'Organization',
          name: account.name,
          description: account.description || account.profile?.profile_summary,
          url: absoluteUrl(`/accounts/${account.id}`),
          sameAs: account.source_url ? [account.source_url] : undefined,
          image: account.avatar_url || undefined,
          keywords: account.tags.join(', '),
        }}
      />
      <AccountDetail key={account.id} initialAccount={account} initialArticles={articles} />
    </>
  );
}
