import { ExplorerPage, explorerMetadata, type SearchParams } from '@/components/explorer-page';
type Props = { searchParams: Promise<SearchParams> };
export async function generateMetadata({ searchParams }: Props) {
  return explorerMetadata('discover', await searchParams);
}
export default async function Page({ searchParams }: Props) {
  return <ExplorerPage mode="discover" params={await searchParams} />;
}
