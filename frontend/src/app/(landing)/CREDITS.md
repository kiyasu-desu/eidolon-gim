# 落地页用到、但不在仓库里的素材的来源

以下是上游落地页的历史来源署名，保留以便追溯。当前 GIM 单角色入口不加载这些素材。

这些素材放在立绘的那个公开存储桶里，不进仓库、不放进前端的 `public/`（ADR-0003 的 2026-10-12 修订），页面上不署名。放法见 `docs/deploy.md`。

## 来电卡图

第 4 幕演示来电的锁屏上，作联系人海报的那张卡图（存储桶的 `call-posters/mano.webp`）。

- 作品：《偶像大师 闪耀色彩》的卡面插画「【しじまに華ひととき】櫻木真乃」，原图 1136×640
- 版权：©Bandai Namco Entertainment Inc.
- 改动：取满高、从左起第 455 px 处裁出宽 295 px 的一块（约 9:19.5，和手机屏幕一样），转成 WebP（质量 86）

## 体素小人

第 5 幕「记忆」里站在浮岛上的四个方块小人（存储桶的 `landing-voxels/mano.json`、`kaho.json`、`fuyuko.json`、`kiriko.json`）：樱木真乃、小宫果穗、黛冬优子、幽谷雾子。

- 作品：《偶像大师 闪耀色彩》里四人的官方半身立绘和 Q 版图（只作参照，没有直接用进小人）
- 版权：©Bandai Namco Entertainment Inc.
- 做法：生图模型参照官方立绘和 Q 版图画出 Q 版三视图（白底、平光、约三头身）；切出正面放到 1024×1024 白底上，在混元 3D 网页版用「单图生成」带纹理生成网格，导出 GLB；`frontend/scripts/glb-voxelize.mts` 转成 96 格高的体素（2026-10-16）
- 中间产物（三视图、GLB）在维护者本地，不进仓库也不进存储桶。步骤见 `docs/deploy.md`「体素小人」
- 第 5 幕的静止图（存储桶的 `landing-memory/still.webp`）画的就是这四个小人：`frontend/scripts/landing-memory-still.mjs` 用页面上同一套场景代码渲染终局全景（2026-10-16）
