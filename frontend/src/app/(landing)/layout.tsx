import "../globals.css";
import "./landing.css";
import "./gim.css";

import type { Metadata } from "next";
import localFont from "next/font/local";
import { headers } from "next/headers";

import { copy } from "@/i18n";

/**
 * 标题、描述和分享卡片（Open Graph、Twitter 卡片）。卡片由同目录下的 opengraph-image.tsx
 * 生成，Next 按文件约定给 `/` 和 `/about` 都加上；X 没有 twitter:image 时
 * 用 og:image，不另放一份。卡片要绝对地址，而自托管的构建不知道部署在哪个域名下：按这次请求的地址拼
 * （Caddy 转发时带着原来的 Host 和 X-Forwarded-Proto）。
 */
export async function generateMetadata(): Promise<Metadata> {
  const h = await headers();
  return {
    metadataBase: requestOrigin(h.get("x-forwarded-host") ?? h.get("host"), h.get("x-forwarded-proto")),
    title: copy.app.name,
    description: copy.app.description,
    openGraph: {
      type: "website",
      url: "/",
      siteName: copy.app.name,
      locale: "zh_CN",
      title: copy.share.title,
      description: copy.share.description,
    },
    twitter: {
      card: "summary_large_image",
      title: copy.share.title,
      description: copy.share.description,
    },
  };
}

/** 这次请求的站点地址。经过几层代理时转发头是逗号分隔的一串，取第一段（离访客最近的那层）；拼不出来时没有。 */
function requestOrigin(host: string | null, proto: string | null): URL | undefined {
  const first = (v: string | null) => v?.split(",")[0].trim() || null;
  const h = first(host);
  if (!h) return undefined;
  try {
    return new URL(`${first(proto) === "https" ? "https" : "http"}://${h}`);
  } catch {
    return undefined;
  }
}

// 落地页的字体：按落地页实际用字做的静态子集，自托管（scripts/landing-fonts.mts 生成，改了文案或角色
// 要重新生成）。每种两份：`-act0` 只有第 0 幕上的字，很小，首屏预载它；完整子集不预载，等页面要用到
// 第 0 幕以外的字时再取，免得和首屏的 CSS 抢带宽。样式表里两份排在同一个字体栈里，前一份没有的字
// 落到后一份（landing.css 的 --lp-ja 等）。
// 回退字体的度量由 landing.css 里的字体栈负责：子集的度量不代表整套字体，不让 next/font 去推算。
const jaAct0 = localFont({
  src: "./fonts/shippori-mincho-b1-600-act0.woff2",
  weight: "600",
  variable: "--lp-font-ja-act0",
  adjustFontFallback: false,
});
const ja = localFont({
  src: "./fonts/shippori-mincho-b1-600.woff2",
  weight: "600",
  variable: "--lp-font-ja",
  adjustFontFallback: false,
  preload: false,
});
const zhTitleAct0 = localFont({
  src: "./fonts/noto-serif-sc-600-act0.woff2",
  weight: "600",
  variable: "--lp-font-zh-title-act0",
  adjustFontFallback: false,
});
const zhTitle = localFont({
  src: "./fonts/noto-serif-sc-600.woff2",
  weight: "600",
  variable: "--lp-font-zh-title",
  adjustFontFallback: false,
  preload: false,
});
const zhAct0 = localFont({
  src: "./fonts/noto-sans-sc-400-act0.woff2",
  weight: "400",
  variable: "--lp-font-zh-act0",
  adjustFontFallback: false,
});
const zh = localFont({
  src: "./fonts/noto-sans-sc-400.woff2",
  weight: "400",
  variable: "--lp-font-zh",
  adjustFontFallback: false,
  preload: false,
});

const fontVariables = [jaAct0, ja, zhTitleAct0, zhTitle, zhAct0, zh].map((f) => f.variable).join(" ");

/**
 * 落地页自己的根 layout（ADR-0016 修订）：不加载应用根 layout 里 next/font 的 CJK 字体，那些切片 CSS
 * 会阻塞首屏；全局样式表只为登录面板和按钮（shadcn）引入。永远深色，不跟随系统。
 * 和应用之间跳转是整页加载。
 */
export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`dark ${fontVariables}`}>
      <body>{children}</body>
    </html>
  );
}
