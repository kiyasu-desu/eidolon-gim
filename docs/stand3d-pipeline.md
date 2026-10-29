# Stand3D 模型处理流水线

本工具把本次 Avatar 重建、原动作烘焙、制作待机和讲话保持层生成、浏览器验收、候选／回退打包整理为统一入口。代码在 `scripts/stand3d/`，运行产物留在 Git 忽略的 `corpus/gim-assets/pipeline/`，不再依赖 `.scratch/` 或固定的8770预览服务。

输入从已导出的模型／原生动画元数据、骨架 reference、恢复的 Avatar 配置及原动画 Bundle 开始。工具不负责从任意游戏目录自动发现或提取新服装；换服装时应先提供同一数据格式的导出结果和对应配置。私有原素材、贴图、Avatar 配置正文不纳入源码。

## 快速运行

需要 Python 3.11+、现有 `frontend/node_modules`（Three.js、TypeScript、Playwright），以及 Chrome。完整重烘焙还需要本机对应版本的 Unity Editor。本轮使用2022.3.62f3c1；6000.0.77f1同版本验证按用户选择跳过，不作为流程阻塞，也不宣称已验证数值等价。

仓库根目录 PowerShell：

```powershell
backend/.venv/Scripts/python.exe scripts/stand3d/pipeline.py build `
  --output corpus/gim-assets/pipeline/temari-run-001 `
  --editor D:/app/Unity/Editor/2022.3.62f3c1/Editor/Unity.exe
```

每次使用新输出目录，失败记录不会被下一次覆盖。Unity、生成器和验收按顺序执行；运行锁防止本工具并发执行重活。Unity会在独立工程中运行，沿用其正常的本机许可／缓存；受限环境无法访问许可IPC时，需要在允许Editor正常运行的环境调用。不要同时打开另一个Unity Editor。

也可以复用已核验的烘焙，省去Editor步骤：

```powershell
backend/.venv/Scripts/python.exe scripts/stand3d/pipeline.py build `
  --output corpus/gim-assets/pipeline/temari-run-002 `
  --reuse-bakes corpus/gim-assets/unity-reference/avatar-rebuild
```

首次历史烘焙只接受profile中明确固定SHA的采集目录。之后可以传入本工具运行的 `bakes/`：

```powershell
backend/.venv/Scripts/python.exe scripts/stand3d/pipeline.py build `
  --output corpus/gim-assets/pipeline/temari-run-003 `
  --reuse-bakes corpus/gim-assets/pipeline/temari-run-001/bakes
```

缓存中的源配置、编辑器版本、采样策略、探针和文件SHA必须匹配。缓存导入只记为复用，不伪称重新执行过Editor。生成步骤仍重新执行，输出统一为 Three 镜像坐标，镜像一次。

## 每轮产物与验收

- `inputs/`：当轮模型、动画、纹理、reference、Avatar配置和Bundle快照。`profile.json`固定来源与校准策略。
- `bakes/`：有效Humanoid Avatar、6段原身体动作、Unity报告与缓存指纹。新烘焙用 `Avatar.asset`，导入历史采集保留原文件名。
- `candidate/`：可直接作为衣装素材根目录使用的模型、动作和纹理；`candidate.zip`为内容确定的压缩包。
- `rollback/`、`rollback.zip`：当轮输入资产的完整副本，不依赖以后生产目录的状态。
- `acceptance/`：动作覆盖、长句循环、暂停、RAF、短停顿、90秒稳定性和桌面／手机图；`report.html`汇总结果。
- `acceptance.json`：将验收结果绑定到候选文件、配置、流水线代码、当前产品引擎及前端依赖锁文件的指纹。
- `manifest.json`、`candidate-manifest.json`：产物SHA。独立Unity工程的Library缓存不列为交付内容。

三个讲话动作各覆盖短句、中句、长句、晚相位、快速切换、减少动态，另跑一遍完整公共待机，共19组；去掉了按三个动作重复执行的相同待机。保持层另跑各26秒并跨过周期接缝。全量蒙皮的7组暂停检查、真实RAF恢复首步、28秒短停顿和90秒多情绪稳定性均保留。相同条件的输入／候选对照图在 `acceptance/comparison.png`。

阈值显式写入profile：选定手部边交叉0、代理残余≤5mm、内裙局部近面距离≤7mm、保持接缝手腕步进<2mm、暂停额外蒙皮位移≤0.01mm。手部和衣料检测都是限定区域的几何指标，不能解释为全模型零穿插或完整原生物理恢复。

默认验收运行当前产品 Stand3DEngine，并直接服务当轮候选文件，独立端口由操作系统分配，用完自动停止。它属于素材／引擎级验收，不冒充完整应用、真实语音或手机实机性能验证。正式切换后的完整应用7流程仍按 `docs/agents/local-acceptance.md` 复验；此前已完成的切换证据保存在 `avatar-activation` 交付目录。

## 重复生成与验收复用

```powershell
backend/.venv/Scripts/python.exe scripts/stand3d/pipeline.py verify corpus/gim-assets/pipeline/temari-run-001
```

相同输入、配置和工具生成相同候选内容与ZIP。元数据保留在Python中，JavaScript只返回制作合成轨迹，避免把原生64位PathID改成浮点近似值。

重新生成后，只有候选全部字节、profile、流水线源码、产品引擎和依赖锁文件指纹完全相同时，才可复用已有验收：

```powershell
backend/.venv/Scripts/python.exe scripts/stand3d/pipeline.py build `
  --output corpus/gim-assets/pipeline/temari-run-004 `
  --reuse-bakes corpus/gim-assets/pipeline/temari-run-001/bakes `
  --reuse-acceptance corpus/gim-assets/pipeline/temari-run-001
```

源动作／profile改动会拒绝旧烘焙；候选、运行时代码或验收阈值改动会拒绝旧验收。失败的运行没有可激活的验收凭据。

## 正式切换与回退

`build`只生成候选，不更改生产资产。确认结果后显式执行：

```powershell
backend/.venv/Scripts/python.exe scripts/stand3d/pipeline.py activate `
  corpus/gim-assets/pipeline/temari-run-001 --target corpus/gim-assets/animation

backend/.venv/Scripts/python.exe scripts/stand3d/pipeline.py rollback `
  corpus/gim-assets/pipeline/temari-run-001 --target corpus/gim-assets/animation
```

切换前检查完整产物SHA、当前代码与验收绑定，并要求目标仍等于本轮输入版本；回退要求目标仍等于本轮候选版本。任何未知修改都会拒绝覆盖。文件先暂存、验证，再逐个替换；某个替换失败会恢复已经替换的文件。多文件替换不是文件系统级原子事务，执行期间应暂停对该衣装的加载。不要把该本地命令当成远程部署。

当前profile固定的是已经上线的Campus制作版作为输入，重跑不会自动回到旧0.5 Twist或丢掉009入场保护。工具不会在每次运行时重复添加保护。默认profile是本轮手毬私服的版本锁定配置，并非任意服装通用参数。

## 改配置与检查工具

复制 `scripts/stand3d/profiles/temari-campus.json` 后调整来源路径、对应SHA、动作目录及校准策略，通过 `--profile` 指定。新输入目录中的原生片段需要已有导出元数据，讲话片段需有 `speakingGesture` role 和显式 `holdClipName`。目前支持52骨映射和30Hz原片段烘焙；缺骨或其他采样率会拒绝，不会静默省略。

```powershell
backend/.venv/Scripts/python.exe -m unittest discover -s scripts/stand3d/tests -v
backend/.venv/Scripts/ruff.exe check --config backend/pyproject.toml scripts/stand3d
node --check scripts/stand3d/generate.mjs
node --check scripts/stand3d/accept.mjs
```

事务回归覆盖输入／路径校验、过期验收、产物篡改、正式切换与回退、未知目标保护及中途失败恢复。浏览器几何验收直接测真实生成物，没有用只复述生成算法的测试代替。

## 本轮实跑记录

2026-10-28完成实际Unity2022重建／6片段烘焙，6份原始采样文件SHA与此前验收采集一致。流水线独立复验通过19组动作、3个26秒保持循环、7组暂停、真实RAF、28秒短停顿及90秒稳定性；候选报告在1280／390px无横向溢出，下载链接均HTTP200。输入／候选的制作保持层数值相同，待机差异≤约1.04e-14。

`corpus/gim-assets/pipeline/temari-20261028-02/`、`-03/`、`-04/` 三轮分别验证流水线烘焙缓存复用、相同候选验收复用及固定历史采集导入。三轮候选ZIP SHA均为 `2244220ef19359a4bb49ea136dd8e8572cf51d7a0f6ebaa94d0c8339c3e3704b`；回退ZIP SHA均为 `1f2bcc621130be89bc0637cfe6ddbd2ced4dcf3e67c63f38691feb7af04226dc`，ZIP目录／CRC／内容SHA同时复核。第一轮 `-01/` 保留修复截图加载时序前的失败记录，未生成可激活凭据；其有效原始烘焙经过校验后复用。

复现和隔离切换／回退证据在 `corpus/gim-assets/pipeline/verification/reproducibility.json`。5项文件边界回归、Python检查和Node语法检查通过。上述私有素材实跑阶段未改实际生产素材，当时尚未提交、推送或远程部署。随后工具及其必要运行时被整理为独立版本管理提交，CI配置见下节。

本地浏览任意一轮的静态报告可用：

```powershell
backend/.venv/Scripts/python.exe -m http.server 8772 --bind 127.0.0.1 --directory corpus/gim-assets/pipeline
# 打开 http://127.0.0.1:8772/temari-20261028-02/report.html
```

## CI 与版本管理

`ci.yml` 的 `stand3d` job 在 Ubuntu／Windows 上使用 Python 3.11、Node 22运行统一的无私有素材检查：

```powershell
backend/.venv/Scripts/python.exe scripts/check-stand3d.py
```

该入口检查全部流水线Python／JavaScript语法、profile JSON、必要的产品引擎依赖、命令行入口和5项文件事务回归。无需Unity、Chrome、npm安装、私有corpus或任何密钥；测试在临时目录生成合成的小JSON，结束后清理。后端job沿用锁定的Ruff版本检查流水线源码，镜像构建必须等待这项新job通过。

新profile或源码修改仍须在具备私有资源的本机跑实际烘焙／浏览器验收；无素材CI不会伪造这部分结果。流水线依赖的Stand3D引擎源码、配套测试及MIT许可声明应与工具一起进入版本管理。

远端使用自己的Fork作为`origin`，保留原项目为`upstream`。本地提交不等于远端CI已运行；当前PR、main、发布检查分支和版本标签的触发条件见[发布说明](releasing.md)。以对应完整提交的成功结果核对，不复用较早提交的绿灯。

源码按仓库约定统一为LF换行；历史运行若使用其他换行字节，严格源码指纹可能失效，需要重新生成／验收凭据。既有生产素材与其原验收结论不受这次源码归档影响。镜像路径现在使用当前Fork的仓库命名空间，不再固定为原项目的GHCR地址。
