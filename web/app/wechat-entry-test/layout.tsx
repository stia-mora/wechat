import { pageMetadata } from '@/lib/seo';
export const metadata = {
  ...pageMetadata(
    '微信入口验证 · 公众号发现',
    '验证公众号在微信与浏览器中的访问入口。',
    '/wechat-entry-test',
  ),
  robots: { index: false, follow: false },
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
