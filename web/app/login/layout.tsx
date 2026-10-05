import { pageMetadata } from '@/lib/seo';
export const metadata = {
  ...pageMetadata(
    '登录与注册 · 公众号发现',
    '登录账号以关注公众号、收藏文章和管理个人阅读地图。',
    '/login',
  ),
  robots: { index: false, follow: false },
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
