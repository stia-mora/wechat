import { Suspense } from 'react';
import { Explorer } from '@/components/explorer';
import { Loading } from '@/components/ui';
export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <Explorer mode="rankings" />
    </Suspense>
  );
}
