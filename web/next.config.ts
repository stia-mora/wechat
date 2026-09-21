import type { NextConfig } from 'next';
const nextConfig: NextConfig = {
  basePath: '/wechat',
  async redirects() {
    return [
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
    ];
  },
};
export default nextConfig;
