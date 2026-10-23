# Eidolon-GIM

和《学园偶像大师》的月村手毬进行日文回复、中文字幕的本地文字对话和语音通话。当前默认只有手毬，使用原创短人设、无 `world.json`，好感度和礼物默认关闭；剧情和模型等本机资源不随源码分发。

本项目基于 [Sallyn0225/eidolon-sc](https://github.com/Sallyn0225/eidolon-sc)，保留其 [AGPL-3.0-or-later](LICENSE)、[许可说明](LICENSING.md) 及第三方来源。非官方粉丝项目，与万代南梦宫及《偶像大师》权利方无关。上游截图、英文/日文 README 与部署文档可能描述 SC 功能；本地 GIM 状态以本文和 [coordination](coordination/PROJECT-STATUS.md) 为准。

## 当前交付

- 单角色文字聊天、双向记录与刷新恢复已做过真实模型和构建版浏览器验收；角色由 AI 扮演，不保证原作一致性。
- 学马本机剧情来源 214 份已完成准入审计及分支还原：**79 篇正式经历、129 篇条件反应资料入库，6 篇明确失败排除**。两库各有 340 个有效 1024 维向量；条件资料不当作已确认经历。402 行转换截断已修复。长句语音回顾漏召回已修复，五类真实 WebRTC 场景最终通过；这是有限用例结果。见 [分支报告](.scratch/gim-branch-restoration/README.md)、[语音复验](.scratch/voice-rag-acceptance/repair.md) 与 [当前状态](coordination/PROJECT-STATUS.md)。
- Windows 中性语音及 Fish Audio 手毬音色已完成本地真实通话验收，百炼 STT 已接入。正常比例 3D 模型、骨骼、待机、表情和手指修复已接入通话层；用户试用反馈可用性不足，暂时停止投入，不作为本轮阻塞项。3D 材质和重定向含近似实现，上游 SC Spine/ShinyColorsDB 不用于学马资源。
- 近期仅本地私用；公开部署属于后续独立阶段。游戏剧情、译文、图像、模型、录音的使用条件需分别确认，代码许可不授予这些素材的权利。

## 本机运行

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/)、Node.js 与 npm。在仓库根目录把 `.env.example` 复制为被 Git 忽略的 `.env`，填写支持流式输出和工具调用的模型配置：

```dotenv
CHAT_LLM_PROTOCOL=chat-completions
CHAT_LLM_BASE_URL=<模型接口根地址>
CHAT_LLM_API_KEY=<本机密钥>
CHAT_LLM_MODEL=<模型名>
```

`CHAT_LLM_PROTOCOL` 也支持 `responses` 和 `anthropic`，详见 [配置指南](docs/configuration.md)。后端启动会实际检查对话模型；未配其他服务时仍可文字聊天。

在 `backend/` 目录执行：

```powershell
uv sync --frozen
$env:EIDOLON_DEV_LOGIN = '1'
$env:HOST = '127.0.0.1'
$env:PORT = '8001'
uv run --frozen --env-file=../.env eidolon serve
```

已安装的本机虚拟环境也可用 `.\.venv\Scripts\uv.exe` 代替 `uv`。若全局缓存权限受限，可先设 `$env:UV_CACHE_DIR = Join-Path $PWD '.venv/uv-cache'`。

另开终端，在 `frontend/` 目录执行：

```powershell
$env:BACKEND_URL = 'http://127.0.0.1:8001'
$env:PORT = '3001'
npm ci
npm run build
npm run start -- --hostname 127.0.0.1
```

打开 [本机对话列表](http://localhost:3001/conversations)，用开发登录进入。开发登录允许按名字进入任意本地账户，只在自己的机器启用；3001/8001 避开参考项目的3000/8000。

后端从 `backend/` 启动时默认角色路径为 `../characters/gim/characters.toml`，数据库为 `data/eidolon-gim.db`，与旧 `data/eidolon.db` 隔离。已有 `.env` 或进程环境中的显式设置优先，升级不会迁移、覆盖旧库或更改用户密钥。`EIDOLON_CHARACTERS_PATH`、`EIDOLON_DATABASE_PATH` 可显式选择其他配置；原型说明见 [characters/gim](characters/gim/README.md)。

## Windows 本机中性语音

默认不开语音。在 Windows 的 `backend/` 终端中设置本次进程环境，无需改已有模型或填写假语音 key：

```powershell
$env:EIDOLON_LOCAL_SPEECH = 'windows'
uv run --no-sync --env-file=../.env eidolon speech check
uv run --no-sync --env-file=../.env eidolon serve
```

`speech check` 列出已安装的声音、识别器并验证配置，不读取麦克风或输出密钥。默认 `EIDOLON_WINDOWS_STT_LANGUAGE=zh-CN`、`EIDOLON_WINDOWS_TTS_LANGUAGE=ja-JP`、`EIDOLON_WINDOWS_TTS_VOICE=Microsoft Haruka Desktop`；可在进程环境或自己的 `.env` 选择其他已安装组件。它是 Windows 中性日语声音，**不是月村手毬的音色**。不支持 Linux/Docker；缺组件时启动会给出错误，不自动安装。

音频由 Silero VAD 切段，在本机识别；完整回复片段去除语气标签后合成单声道 PCM，再经现有 WebRTC 播放。连续音频每 20 秒拆块，识别稿等用户真正停顿后合并提交，避免对前半句提前回答；待识别最多积压四块，超限或进程超过 45 秒会报错结束。挂断和打断会终止相关进程并清理临时 WAV。识别准确率取决于已安装组件与录音质量，实际验收出现过“结束→接受”的同音错误。

已配置的部署者远程语音 key、用户自带语音 key 优先于对应侧的本机语音；选中的远程服务失败时不会改用本机。通话记录中本机语音 provider 为 `windows-system-speech`，model 记下识别语言或声音名，外部语音 API 费用为 0；LLM 仍调用配置的服务并记录用量，实际费用以该服务为准。远程 Fish Audio 仍需要可用的 `voice_id`。

可重复的真实组件检查：`$env:EIDOLON_TEST_WINDOWS_SPEECH='1'` 后运行 `.venv/Scripts/python -m pytest tests/test_windows_speech.py::test_installed_windows_speech_round_trip -q`。普通 CI 默认跳过真实系统组件测试。

## 剧情导入

原始剧情、index、manifest、报告和数据库留在被忽略的本机目录，不提交游戏正文。示例（从 `backend/` 执行）：

```powershell
uv run --frozen --env-file=../.env eidolon story import-gim ../corpus/gim-local/source --manifest ../corpus/gim-local/manifest.json --index ../corpus/gim-local/source/index.json --report ../corpus/gim-local/import-report.json --offline
```

manifest 需记录来源 URL、固定版本、使用条件，以及每个 `adv_*.txt` 的 `canon / conditional / failure / unknown` outcome。人工核对的正式经历及带来源证据、逐条条件标签的条件资料可入库；失败与待核对条目跳过。普通 CSV 已丢失的分支目标不会推测恢复，条件资料须从原始 ADV 解析并单独核验。详细格式、错误处理与重跑说明见 [GIM 剧情导入](docs/gim-story-import.md)。

没有 embedding key 也能离线导入和查看目录；待向量化文本不参与向量搜索。之后配置 embedding 服务，运行 `uv run --env-file=../.env eidolon reembed`，使用库中的文本补齐向量。实际对话检索还需要重排和判断模型，见 [配置指南](docs/configuration.md)。当前本机已配置 Jev，并完成文字及真实语音 RAG 的本地浏览器验收，见 [语音复验报告](.scratch/voice-rag-acceptance/repair.md)。

`story import-csv`、`story import-json`、`story sync`、`world sync` 和 `deploy/*sync*` 是 **legacy SC 工具**，不用于学马自动同步。SC 的 story sync 需要显式 `--characters` 和全局 `--db`，world sync 需要显式 `--characters`；不要把 GIM 目录传给它们。当前 GIM 没有自动下载或定时同步剧情的任务。

## Docker

在根目录配置 `.env` 后运行 `docker compose up -d --build`，入口为 `http://127.0.0.1:3001`。项目名 `eidolon-gim`、数据卷、GIM数据库和角色路径均独立，应用从当前源码构建。容器不支持Windows本机语音。服务器部署和与参考服务共存见 [学马部署说明](docs/deploy-gim.md)；不要用上游SC镜像替代当前构建。

## 开发与来源

后端针对性检查：`cd backend` 后执行 `uv run pytest tests/test_gim_story_import.py -q`、`uv run pyright`、`uv run ruff check src tests`。前端遵循 [frontend/AGENTS.md](frontend/AGENTS.md) 与 [DESIGN.md](DESIGN.md)。

人物事实来源：[官方月村手毬人物页](https://gakuen.idolmaster-official.jp/idol/temari/)。数据格式研究参考 [imas-tools 原文项目](https://github.com/imas-tools/gakuen-adapted-stories) 与 [译文项目](https://github.com/imas-tools/gakuen-adapted-translation-data)；公开仓库不等于剧情或译文获授权。本仓库未包含这些原作正文。详细来源及未确认条件见 [coordination/SOURCES.md](coordination/SOURCES.md)。Spine Runtime 的独立许可见 [LICENSING.md](LICENSING.md)，历史架构见 [docs/adr](docs/adr/)。
