// 单角色入口与登录面板实际用字；旧光谱/来电/记忆演示不再进入页面或字体子集。
import { copy } from "@/i18n";
import { PROVIDER_LABELS } from "@/lib/signIn";

const ALWAYS = Array.from({ length: 0x7f - 0x21 }, (_, i) => String.fromCharCode(0x21 + i)).join("") +
  "、。，．・：；！？「」『』（）〈〉《》【】〔〕ー～…‥—―‘’“”♪☆★";

function strings(node: unknown): string[] {
  if (typeof node === "string") return [node];
  if (typeof node === "function") return strings((node as (...args: string[]) => unknown)("", "", ""));
  if (node && typeof node === "object") return Object.values(node).flatMap(strings);
  return [];
}

const unique = (parts: string[]) => [...new Set(parts.join("").replace(/\s/g, ""))].sort().join("");

export function landingText(): string {
  const { landing } = copy;
  return unique([
    ALWAYS,
    ...strings(copy.app),
    ...strings(landing.prototype),
    landing.disclaimer, landing.signIn, landing.continue, landing.panelTitle, landing.devSignIn,
    ...strings(copy.legal), ...strings(copy.login), ...Object.values(PROVIDER_LABELS),
  ]);
}

/** 日文名与拉丁字母由落地页的 Shippori Mincho B1 排版。 */
export function japaneseText(): string {
  return unique([copy.app.name, copy.landing.prototype.name]);
}

/** 桌面与手机首屏的文案，必须进入预载子集。 */
export function act0Text(): string {
  const { landing } = copy;
  const p = landing.prototype;
  return unique([
    ...strings(copy.app), landing.signIn, landing.continue, landing.disclaimer,
    p.skip, p.title, p.intro, p.name, p.placeholder, p.start, p.resume, p.scopeLink,
  ]);
}
