> 历史决定：当前 GIM 已停止采用此方案，见 [ADR-0029](0029-remove-sc-specific-content.md)。

# 立绘素材由 eidolon 直接从 ShinyColorsDB 拉取，不再依赖单独的立绘镜像

原作隔一两周出一次新卡，我们希望新衣装不用人盯着就能出现在换衣装面板上。原先立绘素材来自另一个仓库 `shinycolors-spine` 下载好的立绘镜像，eidolon 的同步脚本只读不写；镜像要自己记得去更新，而它的下载脚本把卡的列表永久缓存，重跑也看不到新卡。所以改为由 eidolon 自己拉取：`deploy/stand-sync.sh` 第一步运行 `eidolon stand fetch`，每次都重新向 `api.shinycolors.moe` 要卡的列表，从 `cf-static.shinycolors.moe` 下载本地还没有的衣装，只拉配了偶像编号的角色的私服和演出服；同步每周定时跑一次。下载目录归 eidolon 所有（默认在整理目录下），`shinycolors-spine` 留作独立工具，eidolon 不再读它。

## Considered Options

- **留在 `shinycolors-spine`，修好缓存后手动先跑它再同步**：两个仓库各管一段，但每次要记得跑两步，定时同步也得跨仓库编排。
- **`stand-sync.sh` 调用 `shinycolors-spine` 的下载脚本**：一条命令，但 eidolon 要依赖另一个仓库的脚本和它的 Python 环境，两边还能写同一个目录。

## Consequences

- 直接依赖 ShinyColorsDB 没有文档、没有服务保证的 API，和 ADR 0004 依赖的是同一个志愿者团队。它连不上或接口变了时，同步照常用本地已有的素材整理、渲染、上传，以退出码 6 结束；线上的立绘不受影响，只是新卡暂时进不来。
- 本地的卡清单只增不减：上游列表里少了的卡继续保留，免得接口返回不全一次，用户选过的衣装就从面板上消失。下架照旧靠清空存储桶。
- 上游列出了但还没有文件的新卡这次跳过、记进日志，下次同步再试。
- CDN 上约一半的贴图是改名成 `.png` 的 WebP，原样保留、按文件头设 Content-Type：只在浏览器里播放，不需要转成 PNG，文件也更小。
