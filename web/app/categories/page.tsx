import Categories from '@/components/categories';
import { JsonLd } from '@/components/json-ld';
import { serverApi } from '@/lib/server-api';
import { itemList, pageMetadata } from '@/lib/seo';
import type { Category } from '@/lib/types';

export const metadata = pageMetadata(
  '公众号分类 · 科技、财经、教育与生活',
  '按科技、人工智能、财经、教育与生活等具体分类浏览公众号目录，查看已收录的信息源与简介。',
  '/categories',
);

export default async function Page() {
  const categories = await serverApi<Category[]>('/categories');
  return (
    <>
      <JsonLd data={itemList(categories, 'categories')} />
      <Categories data={categories} />
    </>
  );
}
