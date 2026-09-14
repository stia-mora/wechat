import type { Metadata } from 'next';
import { Shell } from '@/components/shell';
import './globals.css';

export const metadata: Metadata = {
  title: { default: '公众号发现 · WeChat Source', template: '%s · 公众号发现' },
  description: '发现值得长期关注的中文信息源。搜索公众号、浏览文章，建立自己的阅读地图。',
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
