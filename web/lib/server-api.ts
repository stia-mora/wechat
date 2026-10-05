import 'server-only';
import { cache } from 'react';
import { notFound } from 'next/navigation';
import { cookies } from 'next/headers';

// Deduplicate metadata/page reads within one request; never cache across requests.
export const serverApi = cache(async <T>(path: string): Promise<T> => {
  const session = (await cookies()).get('ws_session');
  const response = await fetch(`${process.env.API_URL || 'http://127.0.0.1:8500'}/api${path}`, {
    cache: 'no-store',
    headers: session ? { Cookie: `ws_session=${session.value}` } : undefined,
    signal: AbortSignal.timeout(30000),
  });
  if (response.status === 404 || response.status === 422) notFound();
  if (!response.ok) throw new Error(`Public API unavailable (${response.status})`);
  return response.json();
});
