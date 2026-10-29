# 学园 CSV 本机导入

`eidolon story import-gim` 是独立 adapter，复用 `StoryCorpus`，不采用 SC 的剧本编号、类别或失败正则。自动化测试使用原创夹具；当前本机 214 份来源已完成审计、完整性修复及分支还原，79 篇正式经历与 129 篇条件反应资料入库，6 个明确失败排除。见 审计报告（本地记录，不随源码发布） 与 分支还原（本地记录，不随源码发布）。技术验证不证明素材使用许可。

## 准备

把自备且允许使用的 CSV 留在 Git 忽略的 `corpus/gim-local/source/`。不要提交原文、译文或包含选择文本的报告。CSV 表头必须为 `id,name,text,trans`；编码 UTF-8，可带 BOM。`info` 的 name 列应为完整 `adv_*.txt`，例如原创夹具的 `adv_original_fixture_01.txt`。普通重复的 CSV id 不是行标识，不去重。

选择一个稳定版本或上游 commit SHA，准备 CSV 根目录之外的 `corpus/gim-local/manifest.json`：

```json
{
  "source_url": "https://example.invalid/my-original-data",
  "version": "original-v1",
  "usage_conditions": "原创样例，仅作本机 adapter 验证。实际资源请记录明确使用依据。",
  "episodes": {
    "adv_original_fixture_01.txt": "canon",
    "adv_original_fixture_02.txt": "failure",
    "adv_original_fixture_03.txt": "unknown"
  }
}
```

`source_url`、`version`、`usage_conditions` 必填非空字符串，manifest 是操作者的来源记录，不是导入器代为确认授权。`episodes` 中的 key 是原始文件 ID，不能填 CSV 路径或 `gim/` 前缀。outcome 接受四种值：

| Outcome | 行为 |
| --- | --- |
| `canon` | 人工核对为可进入角色回忆的正式 episode；保存并按配置向量化。 |
| `conditional` | 从原始脚本核验的限定情境反应，保存为 `gim-conditional-csv`；不能当作已发生的经历，额外证据要求见下文。 |
| `failure` | 明确失败结束，跳过；如库里已有相同 ID 则移除。 |
| `unknown` 或未列出 | 待核对，不入库；如之前入过库则移除，避免继续检索。 |

可选 index 是 `adv_*.txt` → CSV 路径的 JSON 对象，例如 `{"adv_original_fixture_01.txt":"./one.csv"}`。路径相对于传入的 CSV 根目录，因此若使用上游 `./data/adv/...csv` index，根目录应选包含 `data/` 的本机 checkout，不能选 `data/adv/` 本身。index 的每条映射都检查存在、扩展名、解析后仍在根目录内及 source ID；不接受多个 source 指向同一文件。JSON 重复 key 明确报错。

### 条件反应资料

`conditional` 不是把未知剧情改个分类即可准入。应先用原始 ADV 控制流核对选项、分支与整篇限定情境，生成条件投影，排除分支制作人台词，每条角色消息以 `【条件情境・未确认实际触发：...】` 开头。未证实的运行条件仍标明未确认，不拼接互斥路线。

manifest 须额外提供 `branch_restoration.entries[原始文件ID]`，记录 64 位十六进制的 `raw_sha256`、`graph_sha256` 和 `csv_sha256`。导入器检查字段格式、实际 CSV 摘要、逐条条件前缀及没有制作人发言；原始脚本/图的摘要对应关系与触发解释仍需操作者独立核验并留存证据。不能用伪造摘要替代来源核验。相关本机台账和核验流程见分支还原报告，原脚本及投影正文不进入源码仓库。

## 执行

从 `backend/` 运行；全局 `--db` 须放在 `story` 之前，默认库已与 SC 隔离：

```powershell
uv run --frozen --env-file=../.env eidolon story import-gim ../corpus/gim-local/source --manifest ../corpus/gim-local/manifest.json --report ../corpus/gim-local/import-report.json --offline
```

若需 index，追加 `--index ../corpus/gim-local/source/index.json`。`--characters` 可显式指定角色文件，默认只载入手毬。`--report` 必填，须为 CSV 根目录之外独立的 `.json` 文件，不能覆盖 manifest/index/数据库。不要开启 legacy SC 同步脚本。

`--offline` 不调用向量化服务；省略时有 embedding key 则向量化，没有 key 则自动只存文本。新建或修改的 passage 用空 model 与空 blob 标记待向量化，搜索明确排除这些行，不生成假向量；未变 passage 保留原有向量及其模型标识。目录、cast、台词均可读取，随后配置 embedding 服务并运行 `eidolon reembed`，不需要重新取得原始文件。重新执行 import 对相同 Episode 只报告 `unchanged`；若正文改变，按原 ID 更新。在线导入只复用当前配置模型的向量。

## 规则与审计

- 稳定 ID 是 `gim/adv_original_fixture_01.txt`，来自 info；缺 info 时才用验证过的 index。info 与 index 冲突、多个矛盾 info、多个 CSV 使用相同 source 均报错，不选“最长版本”。同一个文件重复但相同的 info 可接受。
- 读取顺序就是 CSV 顺序；报告行号为原始文件的物理起始行号（包括表头、元数据及带换行的字段）。只规范化 BOM、CRLF、字面 `\n`、`{user}` 为“制作人”、`<em>`、`<r\=...>...</r>` / `<r=...>...</r>`。空译文为 `None`，不拿原文填充译文。
- `__narration__` 变为无 speaker 的叙述；`__title__` 提供 episode 标题，不成为台词。手毬、全名及空格版本可匹配配置 cast；其他说话人仍保留，但不成为已配置角色。
- 每组相邻 `select` 行只进入报告，保留行号、原文、译文和 `target: "unknown"`。CSV 转换已丢跳转目标和条件，后续反应的先后次序不能证明选择了哪个选项。不能据此把选择当成制作人的真实经历，也不宣称恢复了完整分支图。
- 未知尖括号标记、花括号、控制转义或特殊 `__...__` 标记记录行号并阻止该文件入库。未知标记不能混进角色台词；应先核对转换格式再扩展 adapter。无台词、错误列数、损坏引号、错误编码也会诊断。
- CSV 的符号链接若解析到根目录之外会被拒绝；index 路径越界、缺失文件或全局 manifest/index 错误阻止本次所有写入。单个 CSV 错误、重复 ID 或 embedding 失败保留该 episode 的旧版本；其他有效文件可以完成，因此出错后应查看报告而非只看退出码。

报告包含来源 URL/版本/使用条件、manifest/index 的 SHA-256、文件相对路径和 SHA-256、source ID、outcome、有效行数与行号、speaker 数量、cast、选择组与未知目标、未知控制标记、错误及 `imported / unchanged / pending_outcome / skipped_failure` 状态。原始文件与这些 hash 是对照依据；报告不是正文备份，需一起保留本机原始版本。`pending_passages` 是库中相对于当前 embedding 配置仍缺向量的条目数。

退出码 0 表示所有文件解析成功（包括已报告的失败或待核对 outcome），1 表示存在解析/配置/保存错误。再次导入会覆盖同一报告；需要历史审计时请更换报告文件名。未知 outcome 的数量和 status 仍须人工检查，不能把退出码 0 当成真实语料验收。

## 验证边界

`backend/tests/test_gim_story_import.py` 使用原创磁盘 CSV、实际 SQLite corpus、CLI 和测试 embedder，核对 speaker/行数/译文/选择组、重复导入、更新、failure/unknown、错误 CSV/info/index、离线检索排除及 reembed。测试 embedder 只验证接口契约，不代表真实云服务验收。Windows 没有符号链接创建权限时相应检查会 skip；路径越界仍有独立测试。

格式依据与来源记录见 .scratch/gim-completion/research.md（本地记录，不随源码发布） 和 coordination/SOURCES.md（本地记录，不随源码发布）。当前 129 篇原暂缓资料已从原始脚本恢复分支结构并作为 conditional 准入，未确认的实际触发仍不当作正式经历；素材使用条件独立待核实。不要运行会把转换成功自动标为 canon 的旧版批转换器；新来源仍应默认 unknown，核验后再分类。
