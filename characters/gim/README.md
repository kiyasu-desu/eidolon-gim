# 月村手毬配置

模型与剧情均为可选本地资源包，不在Git中；默认角色配置可在没有这些资源的机器上启动。详见[装卸说明](../../docs/local-resource-packs.md)。

此目录是本项目后端和Docker的默认角色配置，可通过 `EIDOLON_CHARACTERS_PATH` 覆盖。当前仅月村手毬，没有 `world.json`；上游旧作品角色与世界资料已移除。人设依据[官方角色简介](https://gakuen.idolmaster-official.jp/idol/temari/)及有来源的称呼事实编写，不包含剧情原文。剧情库、模型和本机报告独立于源码。`speakers` 包含“手毬”及官方全名的常见空格写法，导入格式见[GIM剧情导入](../../docs/gim-story-import.md)。

在仓库根目录创建被 Git 忽略的 `.env`，文字聊天至少需要以下模型参数，不要把密钥写进受跟踪文件：

```dotenv
CHAT_LLM_PROTOCOL=chat-completions
CHAT_LLM_BASE_URL=<模型接口根地址>
CHAT_LLM_MODEL=<模型名>
CHAT_LLM_API_KEY=<密钥>
```

如果本地兼容服务不检查密钥，仍需给 `CHAT_LLM_API_KEY` 一个非空的本地占位值，因为当前配置加载器要求它。根据服务实际协议调整 `CHAT_LLM_PROTOCOL`；支持的值见 `docs/configuration.md`。

从 `backend/` 目录在PowerShell中启动后端，再从 `frontend/` 启动构建版前端，访问 `http://localhost:3001/conversations`。本机开发登录首次进入需同意条款；公网私密部署使用OAuth白名单。新环境先按[README](../../README.md)安装uv并同步依赖。

```powershell
$env:EIDOLON_CHARACTERS_PATH = '../characters/gim/characters.toml'
$env:EIDOLON_DATABASE_PATH = 'data/eidolon-gim.db'
$env:EIDOLON_AFFINITY_AND_GIFTS = '0'
$env:EIDOLON_REACH_OUTS = '0'
$env:EIDOLON_DEV_LOGIN = '1'
$env:EIDOLON_STATUS_SERVICES = 'none'
$env:HOST = '127.0.0.1'
$env:PORT = '8001'
.\.venv\Scripts\uv.exe run --frozen --env-file=../.env eidolon serve
```

另开一个 PowerShell 窗口，在 `frontend/` 目录运行：

```powershell
$env:BACKEND_URL = 'http://127.0.0.1:8001'
$env:PORT = '3001'
npm ci
npm run build
npm run start -- --hostname 127.0.0.1
```

上述最小模型配置用于文字聊天。Fish音色需要有效STT/TTS配置；姓名字典包含多种写法，爱称遵守说话人与对象关系，不增加可对话角色。立绘通过 `EIDOLON_MODEL_ROOT/<角色ID>/` 可选挂载，剧情通过 `EIDOLON_STORY_DATABASE_PATH` 独立挂载，缺包仍可文字对话。资源装卸、旧库无损迁移和开关见[本地资源包](../../docs/local-resource-packs.md)。好感度、礼物保持关闭，已有 `.env` 的显式用户库路径继续有效。

用户自备剧情可通过[import-gim](../../docs/gim-story-import.md)导入，不调用旧作品同步。当前资源验收覆盖79篇正式经历、129篇条件资料及340条向量；6篇failure排除。检索需要重排和判断服务，已有有限真实RAG验收，不保证任意查询正确。交付范围和待启动目标统一见[项目路线图](../../docs/project-roadmap.md)。
