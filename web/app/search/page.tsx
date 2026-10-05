import { ExplorerPage, explorerMetadata, type SearchParams } from '@/components/explorer-page';
type Props = { searchParams: Promise<SearchParams> };
export async function generateMetadata({ searchParams }: Props) {
  return explorerMetadata('search', await searchParams);
}
export default async function Page({ searchParams }: Props) {
  return <ExplorerPage mode="search" params={await searchParams} />;
}
