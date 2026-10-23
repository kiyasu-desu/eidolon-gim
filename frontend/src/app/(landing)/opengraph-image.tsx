import { ImageResponse } from "next/og";

export const alt = "Eidolon-GIM：月村手毬的本地文字对话原型，深色底上的原创文字排版，无角色图像。";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** 原创文字分享图；不载入上游游戏卡面，也不要求运行中的后端或字体服务。 */
export default function Image() {
  return new ImageResponse(
    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", width: "100%", height: "100%", padding: 80, background: "#020203", color: "#eeecf2" }}>
      <div style={{ display: "flex", fontSize: 88, letterSpacing: -2 }}>Eidolon-GIM</div>
      <div style={{ display: "flex", fontSize: 36, marginTop: 30 }}>Temari Tsukimura</div>
      <div style={{ display: "flex", fontSize: 28, marginTop: 24, color: "#b4b2b8" }}>Local text conversation prototype</div>
      <div style={{ display: "flex", fontSize: 20, marginTop: 72, color: "#b4b2b8" }}>Unofficial fan project · AI character</div>
    </div>,
    size,
  );
}
