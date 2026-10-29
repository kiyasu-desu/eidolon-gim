> 历史决定：当前 GIM 已停止采用此方案，见 [ADR-0029](0029-remove-sc-specific-content.md)。

# 通话层立绘用官方 Spine 3.6 runtime，暂不购买 Spine Editor 许可证

通话层的立绘是原作的 Spine 3.6.53 素材，能读它的只有官方 spine-ts 3.6 runtime，pixi-spine 等其他选择也受同一份 Spine 许可证约束。现行的 Spine Runtimes 许可证要求集成 runtime 的人持有有效的 Spine Editor 许可证；3.6 文件自带的 v2.5 许可证更严，只允许个人或内部使用。系统对公众开放，浏览器会下载 runtime，这就算分发。我们选择**不买 Editor 许可证、接受这层风险**：素材本身就是未经授权使用的原作素材，runtime 许可证只是在同一种风险上多加一层；真有人追究时，再买一份 Editor 许可证就能补上，不需要改代码。

runtime 的放法是为了让风险只停留在这一个文件上：`spine-webgl.js` 原样放在单独的 vendor 目录里，附上它自己的 LICENSE 和一份记下来源、版本、校验和的 README，一个字都不改（连 README 建议加的 `export` 也不加）；页面用 `<script>` 加载，代码通过 `window.spine` 调用。项目是 AGPL-3.0-or-later，而 Spine runtime 不能按 AGPL 授权，所以版权人在项目许可证里加一条 AGPL 第 7 节的附加许可，允许本项目和 Esoteric Software 的 Spine Runtimes 组合在一起、一起分发；vendor 目录不受 AGPL 约束。目前所有代码都出自同一位版权人，所以现在就能加。

## Considered Options

- **买一份 Spine Editor 许可证**（Essential 版就够）：公开部署在 runtime 这一层完全合规，花费不多。暂不采用，但这是被追究时的补救办法。
- **自己实现一个 3.6 渲染器，绕开 Spine runtime**：要支持 mesh、deform、约束和事件时间轴，工作量不现实。
- **pixi-spine（PixiJS v7）**：一样受 Spine 许可证约束，体积大 4–5 倍，对 3.7 以下的版本只是「有限支持」。

## Consequences

- 以后如果有别人贡献代码，他们的代码也要同意这条附加许可。
- 仓库改为公开时，要重新考虑这一条：按许可证字面理解，修改或开发包含 runtime 的产物的人，各自都需要 Editor 许可证。
