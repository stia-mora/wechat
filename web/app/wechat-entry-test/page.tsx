import Link from 'next/link';

export default function WechatEntryTest() {
  return (
    <section className="mx-auto max-w-2xl py-10">
      <Link href="/" className="text-sm text-[#245745]">返回首页</Link>
      <h1 className="mt-5 text-2xl font-semibold">安卓公众号直达验证结果</h1>
      <div className="mt-6 rounded-xl border border-stone-200 bg-white p-5">
        <p className="text-sm leading-7 text-stone-700">
          2026 年 9 月 30 日收到安卓手机实测反馈：三种携带公众号目标的链接均未能启动微信；
          对照链接能够启动微信，但没有进入目标公众号。
        </p>
        <ul className="mt-4 space-y-2 text-sm text-stone-500">
          <li>方式一：安卓应用链接 — 实测失败，已停用。</li>
          <li>方式二：公众号资料协议 — 实测失败，已停用。</li>
          <li>方式三：客户端资料协议 — 实测失败，已停用。</li>
        </ul>
        <a className="button secondary mt-5" href="weixin://">仅启动微信</a>
        <p className="mt-3 text-sm leading-7 text-stone-500">
          此按钮只请求打开微信应用，不携带公众号目标。进入具体公众号仍需扫码或搜索。
          上述结果来自本次测试设备，不能代表所有安卓设备和微信版本。
        </p>
      </div>
      <p className="mt-6 text-sm leading-7 text-stone-500">
        微信小程序提供打开公众号主页的接口，但官方要求目标公众号与小程序为同主体或关联主体，
        不能据此保证直达本网站收录的第三方公众号。
        <a className="ml-1 text-[#245745] underline" href="https://developers.weixin.qq.com/miniprogram/dev/api/navigate/wx.openOfficialAccountProfile.html"
          target="_blank" rel="noopener noreferrer">查看微信官方说明</a>。
      </p>
    </section>
  );
}
