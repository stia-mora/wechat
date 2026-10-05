import type { NextConfig } from 'next';
const nextConfig: NextConfig = {
  basePath: '/wechat',
  async redirects() {
    return [
      { source: '/', destination: '/wechat', statusCode: 302, basePath: false },
      { source: '/robots.txt', destination: '/wechat/robots.txt', statusCode: 302, basePath: false },
      { source: '/sitemap.xml', destination: '/wechat/sitemap.xml', statusCode: 302, basePath: false },
      { source: '/llms.txt', destination: '/wechat/llms.txt', statusCode: 302, basePath: false },
      {
        source: '/library',
        destination: '/wechat/library',
        permanent: true,
        basePath: false,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.API_URL || 'http://127.0.0.1:8500'}/api/:path*`,
      },
      {
        source: '/api/:path*',
        destination: `${process.env.API_URL || 'http://127.0.0.1:8500'}/api/:path*`,
        basePath: false,
      },
    ];
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
        ],
      },
      {
        source: '/:path((?!_next/static/).*)',
        headers: [
          { key: 'Cache-Control', value: 'private, no-cache, no-store, max-age=0, must-revalidate' },
          { key: 'CDN-Cache-Control', value: 'no-store' },
          { key: 'Cloudflare-CDN-Cache-Control', value: 'no-store' },
        ],
      },
    ];
  },
};
export default nextConfig;
