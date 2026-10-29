# 本地用 Playwright 验收

票里写「本地构建版上用 Playwright 验收」时照这里做。验收脚本是一次性的：放在 `frontend/scripts/_accept-*.mts`（这样才找得到 `playwright` 包），用 `node` 跑，验完删掉，不提交（规格「组件不写测试」）。截图写到 `.scratch/_accept/`，同样用完删掉。

## 起服务、停服务

前端跑构建版，不跑 `next dev`（dev 模式会卡）：

```sh
# 后端（:8001），只对本次隔离验收启用开发登录
cd backend && HOST=127.0.0.1 PORT=8001 EIDOLON_DEV_LOGIN=1 uv run --quiet --env-file=../.env eidolon serve
# 前端（:3001），在 frontend/ 下，先 npm run build
BACKEND_URL=http://127.0.0.1:8001 PORT=3001 npm run start -- --hostname 127.0.0.1
```

两个都在后台运行，使用隔离数据库和空闲端口，避免占用已有服务。PowerShell逐项设置环境变量的写法见[README](../../README.md)。本地模型由同源接口和 `EIDOLON_MODEL_ROOT` 提供；只有额外资源域名才需配置 `EIDOLON_STAND_ASSETS_URL` 并核对CSP。

停服务时确认 `next start` 的子进程也结束；用 `Get-NetTCPConnection -LocalPort 3001 -State Listen` 查进程，并核实其命令行属于本次验收后再停止，8001同理。重新构建前先停止本次旧前端。

耗时长的活（`next build`、Playwright、后端完整 pytest）不要和别的 agent 同时跑，否则会卡住，一次只跑一个。

## 登录

只在隔离本地库中使用专用测试账户；管理者权限按本次隔离配置设置，不假定已有用户身份。请求带 `Origin`：

```ts
await context.request.post(`${origin}/api/auth/dev-login`, { data: { name: "gim-accept" }, headers: { origin } });
```

`frontend/scripts/screenshots.mts` 的 `signIn` 也是这么写的。

## 好感度和礼物

GIM默认关闭好感度和礼物，普通验收保持关闭。只有任务明确测试通用礼物能力时才在隔离配置中单独开启；不要修改正在使用的 `.env` 或生产后台。要显式验证关闭状态：

```sh
cd backend && EIDOLON_AFFINITY_AND_GIFTS=0 uv run --quiet --env-file=../.env eidolon serve
```

测试礼物状态时创建专用账户（例如 `gift-accept`），同意条款（`POST /api/account/consent`，`{"agree_to_terms": true, "at_least_13": true}`），读一次 `/api/gifts` 建立行，然后只向本次 `EIDOLON_DATABASE_PATH` 指定的隔离库写入：

- 背包：`INSERT INTO gift_backpacks VALUES ('<user_id>', '<礼物 id>', <件数>)`，礼物id和名字在本次角色目录的 `gifts.toml`
- 抽奖次数：`UPDATE gift_balances SET draws = <n> WHERE user_id = '<user_id>'`
- 好感度：`INSERT OR REPLACE INTO affinities (user_id, character_id, value, updated_at, cooling) VALUES ('<user_id>', '<角色 id>', <0–100>, '<ISO 时刻>', <冷却中 1，否则 0>)`

`user_id` 从 `GET /api/account` 获取。验完核对当前账户确为专用测试账户，再调 `POST /api/account/delete`（`{"confirm": true}`）；已有真实账户和数据保留。

## 通话

Chromium 用假麦克风，上下文给麦克风权限：

```ts
const browser = await chromium.launch({
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
});
const context = await browser.newContext({ viewport, permissions: ["microphone"] });
```

- 真实服务测试需等WebRTC接通并收到实际回复音频。若当前网络下Fish握手超时，按实际网络配置本次后端代理；语音服务不直接读取 `HTTPS_PROXY`。示例地址只作占位，不改已有 `.env`：

  ```sh
  cd backend && EIDOLON_PROXY_URL=http://127.0.0.1:10808 EIDOLON_PROXY_SERVICES=judge,tts uv run --quiet --env-file=../.env eidolon serve
  ```

  假麦克风接通不等于真人STT已验收。可用通话中打字触发真实LLM／TTS，并检查接收音频；人的听感和真人麦克风识别单独记录。主观试听可在本机3001入口进行。
- 页首电话键在对话打开前是禁用的，先等它可点再点：

  ```ts
  await page.getByRole("button", { name: "和月村手毬通话", exact: true }).waitFor();
  await page.waitForFunction(() => {
    const button = document.querySelector('button[aria-label="和月村手毬通话"]');
    return button && !button.hasAttribute("data-disabled") && !button.hasAttribute("disabled");
  });
  ```

- 通话层滑上来要 410ms，量位置、截图前先等一下。
- `page.goto` 是整页重载，会挂断通话。通话中换页要点页面上的链接和按钮（客户端跳转）。

### 造出结束卡

通话「因故结束」在本地也造得出来：拦下建立通话的请求 `/api/offer`，换成后端拒绝时的回答。

| 回答 | 结束卡 |
| --- | --- |
| `429`，`{"detail": "…"}` | 超限额（主操作「去设置自带密钥」） |
| 其他错误状态 | 没接通（主操作「重拨」） |

先把请求挂起不回，等换到别的页面再放行，就能造出「在别的页面上因故结束」：

```ts
let held: Route | null = null;
await page.route("**/api/offer", (route) => void (held = route));
// …拨号、收起通话层、换到设置…
await held!.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: "这一小时的通话次数用完了" }) });
```

### 造出后端在通话里发的消息

`ended`（她挂断、到上限）、`done` 这些是接通以后从数据通道来的，拦 `/api/offer` 只能造出拨号被拒。要造它们，在页面里另起一个 `RTCPeerConnection` 冒充后端（Chromium 本机回环接得通）：

1. `context.addInitScript` 注入假后端：`setRemoteDescription(offer)`，把 offer 里的音频收发器改成 `sendrecv` 并换上一条 `AudioContext().createMediaStreamDestination()` 的音轨，`createAnswer`，等 ICE 收集完再交出 SDP；`ondatachannel` 收到 `client-ready` 就回 `{"label":"rtvi-ai","type":"bot-ready","id":<同 id>,"data":{"version":"1.0.0"}}`。
2. `page.route("**/api/offer")`：POST 用 `page.evaluate` 交给假后端应答，回 `{sdp, type: "answer", pc_id: "fake-pc"}`；PATCH（补发的 ICE 候选）交给它 `addIceCandidate`，回 `200 {}`。
3. 接通后由假后端发 `{"label":"rtvi-ai","type":"server-message","data":<服务器消息>}`；挂断再发 `{"type":"signalling","message":{"type":"peerLeft"}}`。

这样造出来的对话事件等只在页面上，库里没有；对话列表按接口重读，看不到它。
