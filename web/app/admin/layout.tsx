import { pageMetadata } from '@/lib/seo';
export const metadata = {
  ...pageMetadata('管理登录 · 公众号发现', '使用管理员凭证访问管理控制台。', '/admin'),
  robots: { index: false, follow: false },
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
