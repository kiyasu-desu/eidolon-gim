# 月村手毬本地私用配置

此目录独立于上游的 28 人角色目录，是本项目后端和 Docker 的默认角色配置；可通过 `EIDOLON_CHARACTERS_PATH` 显式覆盖。目录中没有 `world.json`，因此不会加载上游的 283 世界设定。人设短文是依据[官方角色简介](https://gakuen.idolmaster-official.jp/idol/temari/)重新撰写的短文，该短文不包含剧情原文；本地剧情库和模型另外存放在 Git 忽略的 corpus/ 与数据库中。界面色、礼物项目均是原型占位配置。`speakers` 包含研究样本中的“手毬”和官方全名的常见空格写法；CSV 格式证据见 [research](../../.scratch/gim-completion/research.md)。

在仓库根目录创建被 Git 忽略的 `.env`，文字聊天至少需要以下模型参数，不要把密钥写进受跟踪文件：

```dotenv
CHAT_LLM_PROTOCOL=chat-completions
CHAT_LLM_BASE_URL=<模型接口根地址>
CHAT_LLM_MODEL=<模型名>
CHAT_LLM_API_KEY=<密钥>
```

如果本地兼容服务不检查密钥，仍需给 `CHAT_LLM_API_KEY` 一个非空的本地占位值，因为当前配置加载器要求它。根据服务实际协议调整 `CHAT_LLM_PROTOCOL`；支持的值见 `docs/configuration.md`。

从 `backend/` 目录在 PowerShell 中启动后端，再从 `frontend/` 启动构建版前端。访问 `http://localhost:3000/conversations`，用开发登录进入。第一次登录需同意条款。本机已把 `uv.exe` 放在被忽略的后端虚拟环境中；新环境需先按仓库 README 安装 `uv` 并同步依赖。

```powershell
$env:EIDOLON_CHARACTERS_PATH = '../characters/gim/characters.toml'
$env:EIDOLON_DATABASE_PATH = 'data/eidolon-gim.db'
$env:EIDOLON_AFFINITY_AND_GIFTS = '0'
$env:EIDOLON_REACH_OUTS = '0'
$env:EIDOLON_DEV_LOGIN = '1'
$env:EIDOLON_STATUS_SERVICES = 'none'
.\.venv\Scripts\uv.exe run --frozen --env-file=../.env eidolon serve
```

另开一个 PowerShell 窗口，在 `frontend/` 目录运行：

```powershell
$env:BACKEND_URL = 'http://127.0.0.1:8000'
npm ci
npm run build
npm run start
```

上面的最小模型配置可用于文字聊天。当前角色配置已绑定 Fish Audio 手毬音色和 stand_3d 模型目录；语音需要本机有效 STT/TTS 配置，3D 需要 corpus/ 中的本地模型资源，不能仅凭下载源码获得这些资源。礼物目录用于满足启动校验，好感度与礼物保持关闭。现有 `.env` 的显式数据库路径仍优先，不自动迁移旧 `gim-prototype.db`。剧情使用用户自备文件的 [import-gim](../../docs/gim-story-import.md)，不调用 SC 自动同步；没有 embedding key 也能建立目录。剧情现按审计保留 79 篇（77 篇关联手毬）、114 个有效向量；6 个 failure 和 129 个 unknown 已隔离，源文件保留。聊天检索依赖重排及判断服务；当前本机已补齐并完成真实 RAG 浏览器功能验收，保留查询质量缺口。语音、音色与动态模型状态见 [当前状态](../../coordination/PROJECT-STATUS.md)。文字一轮和刷新持久化已在 2026-10-21 验证；不要记录密钥。
