# 本地模型／剧情资源包

源码、用户数据与可选资源分开：账户／聊天／用户记忆仍由 `EIDOLON_DATABASE_PATH` 管理；剧情及原向量单独存放；立绘由独立模型根目录提供。原始模型、贴图、动作、剧本、译文、向量和运行库都留在 Git 忽略的本地目录，不随源码分发。

## 开关与目录

在被忽略的 `.env` 中设置，修改后重启后端并刷新页面：

```dotenv
EIDOLON_DATABASE_PATH=data/eidolon-gim.db
EIDOLON_STORIES_ENABLED=1
EIDOLON_STORY_DATABASE_PATH=../corpus/local-packs/stories/gim.stories.db
EIDOLON_MODELS_ENABLED=1
EIDOLON_MODEL_ROOT=../corpus/local-packs/models
```

以上相对路径以在 `backend/` 启动为例；本机配置使用绝对路径，避免从不同目录启动时误选数据。这里只切换立绘素材和剧情检索，不影响对话模型或语音服务的配置。

模型目录结构：

```text
models/
└── temari/
    ├── model.json
    ├── animations.json
    └── textures/
```

角色ID决定子目录。根目录可放入多个角色包；每个包必须至少有两个JSON。缺包不展示本地模型入口；`EIDOLON_MODELS_ENABLED=0` 会同时隐藏立绘和停止其文件接口，文字／语音通话继续可用。旧角色配置显式声明的 `stand_model` 仍可用；默认GIM源码配置已不依赖本机资源目录。包的运行内容可由模型流水线的 `candidate/` 或候选ZIP取得，来源SHA见其manifest。

剧情路径留空时，默认使用应用库同目录的 `*.stories.db`，例如 `data/eidolon-gim.stories.db`。文件不存在或 `EIDOLON_STORIES_ENABLED=0` 时，剧情源不挂载，不自动创建空库，也不回读旧用户库里的剧情。角色资料和用户记忆的检索仍按现有服务配置运行。停用剧情不会删除过去的聊天和记忆，也不会抹去已经出现在聊天历史里的内容。

## 从旧共库安全迁移

在 `backend/` 中，使用已加载 `.env` 的CLI：

```powershell
.venv/Scripts/uv.exe run --env-file=../.env eidolon story migrate `
  --source data/gim-prototype.db `
  --output ../corpus/local-packs/stories/gim.stories.db
```

迁移只读取旧库，先保存完整一致性备份，再导出 `episodes`、`episode_cast`、`episode_lines`、`episode_passages`。它保留来源、分类、原文／译文、时间及向量BLOB，不调用向量API，不复制账户／聊天／个人记忆表。每张剧情表的行数和逻辑SHA均核对，旁边生成 `*.manifest.json`。

目标已存在且内容相同可重复执行；内容不同、包含用户／其他应用表、表结构或关联异常时拒绝，不覆盖目标。新包通过校验后，设置 `EIDOLON_STORY_DATABASE_PATH` 指向它。原库和原库中的旧剧情副本保留作回退；后续运行不再从旧剧情表检索，后续导入写新库。资源卸载不包括删除这份迁移前副本。

原库整体备份仍是敏感用户数据，必须继续留在忽略的本地数据目录。若需要瘦身旧库，应在备份和新包验证后另行操作，不能直接删除应用数据库。

## 新剧情导入与重新向量化

```powershell
.venv/Scripts/uv.exe run --env-file=../.env eidolon `
  --story-db ../corpus/local-packs/stories/gim.stories.db `
  story import-gim <CSV目录> --manifest <来源分类.json> --report <目录外报告.json> --offline

.venv/Scripts/uv.exe run --env-file=../.env eidolon `
  --story-db ../corpus/local-packs/stories/gim.stories.db reembed
```

`--offline` 保留待向量化状态，不生成假向量；`reembed` 同时维护启用的剧情包及应用库中的角色资料／用户记忆，关闭剧情时跳过该包。也可通过正常在线导入只向量化新剧情。

全局 `--db` 对账户等命令仍表示应用库。旧 `story import-*`／`sync` 的显式 `--db` 保留为独立剧情库目标的兼容写法，但拒绝指向已有账户／其他应用表的库；新命令推荐用 `--story-db`，避免混淆。GIM不自动调用上游SC同步。

## 停用、卸载与恢复

1. 结束正在进行的通话，设置对应 `*_ENABLED=0`，重启后端。也可以在服务关闭后移走对应资源目录／剧情文件。
2. 账户、聊天、记忆和应用库继续保留。模型停用时文件接口404；剧情停用时回忆检索不访问该包。
3. 需要恢复时，将资源放回原位置或更新路径，设为1并重启，模型与剧情可以各自恢复。

Windows下运行中的SQLite可能占用剧情文件，因此物理移走／删除前先停止后端。不要同时复制正在写入的SQLite主文件和不配套的WAL；迁移命令使用SQLite快照备份处理一致性。

## 资源拆分的本地验收（2026-10-29）

- 合成数据覆盖四种组合、重建服务后聊天／个人记忆保留及继续检索、缺包和旧共库禁止回读、模型接口停用。
- 迁移覆盖原始向量／分类保留、完整源库备份、重复执行、不同／混合目标拒绝、CLI导出。
- 实际从 `backend/data/gim-prototype.db` 导出208篇剧情（79正式经历、129条件资料）、5049行、340条向量；源文件SHA和全部非剧情表的行数／逻辑SHA保持不变。
- 本机28份实际模型文件安装到 `corpus/local-packs/models/temari/`，SHA与已验收素材一致；原模型目录仍保留。
- 现有构建版以真实新资源目录、隔离用户库和假WebRTC做桌面／390px手机视口四组合共8流程，均进入接通计时，麦克风控制、讲话、收起／恢复和挂断正常；有模型时载入制作待机／保持层，无页面异常。这是资源／页面验收，未把假WebRTC描述为真实语音服务测试。
- 本机 `.env` 已备份并指向新资源包；应用数据库路径未变。验收数据和截图位于忽略的 `corpus/local-packs/`。这是资源拆分完成时的历史验收记录；后续源码发布与生产升级已经开展，当前阶段见[项目路线图](project-roadmap.md)。

## 容器路径

模型和导入来源可放在只读 `/corpus`；剧情 SQLite 使用 WAL 且支持导入和重新向量化，应放在可写目录，推荐 `/data/gim.stories.db`。详见[部署说明](deploy-gim.md)。
