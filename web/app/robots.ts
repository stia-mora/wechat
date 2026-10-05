import type { MetadataRoute } from 'next';
import { absoluteUrl } from '@/lib/seo';

export const dynamic = 'force-dynamic';
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: [
        '/wechat/admin',
        '/wechat/api/admin',
        '/wechat/login',
        '/wechat/library',
        '/api/admin',
        '/login',
        '/library',
      ],
    },
    sitemap: absoluteUrl('/sitemap.xml'),
  };
}
