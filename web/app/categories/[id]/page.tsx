import { notFound } from 'next/navigation';
import { ExplorerPage, explorerMetadata, type SearchParams } from '@/components/explorer-page';
import { serverApi } from '@/lib/server-api';
import type { Category } from '@/lib/types';
type Props = { params: Promise<{ id: string }>; searchParams: Promise<SearchParams> };
async function categoryId(params: Props['params']) {
  const { id } = await params;
  const categories = await serverApi<Category[]>('/categories');
  if (!categories.some((category) => String(category.id) === id)) notFound();
  return id;
}
export async function generateMetadata({ params, searchParams }: Props) {
  return explorerMetadata('discover', await searchParams, await categoryId(params));
}
export default async function Page({ params, searchParams }: Props) {
  return (
    <ExplorerPage
      mode="discover"
      categoryId={await categoryId(params)}
      params={await searchParams}
    />
  );
}
