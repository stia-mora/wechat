import { pageMetadata } from '@/lib/seo';
export const metadata = {
  ...pageMetadata(
    '我的关注与收藏 · 公众号发现',
    '管理已关注的公众号、收藏文章和个人阅读记录。',
    '/library',
  ),
  robots: { index: false, follow: false },
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
