import type { Metadata } from 'next';

export const siteUrl = 'https://wechat.aim888888.xyz/wechat';
export const absoluteUrl = (path = '') => siteUrl + path;

export function pageMetadata(title: string, description: string, path: string): Metadata {
  const url = absoluteUrl(path);
  const image = {
    url: absoluteUrl('/og-image.png'),
    width: 1200,
    height: 630,
    alt: '公众号发现 · WeChat Source',
  };
  return {
    title: { absolute: title },
    description,
    alternates: { canonical: url },
    openGraph: {
      title,
      description,
      url,
      type: 'website',
      locale: 'zh_CN',
      siteName: '公众号发现',
      images: [image],
    },
    twitter: { card: 'summary_large_image', title, description, images: [image.url] },
  };
}

export function itemList(
  items: { id: number; name?: string; title?: string }[],
  kind: 'accounts' | 'articles' | 'categories',
  offset = 0,
) {
  return {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: offset + index + 1,
      name: item.name || item.title,
      url: absoluteUrl(`/${kind}/${item.id}`),
    })),
  };
}
