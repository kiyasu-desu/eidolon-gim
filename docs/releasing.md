# 源码发布检查

发布源码、配置示例、处理工具、合成测试和维护文档。角色模型、贴图、动作、剧情原文／译文、向量、用户库、录音、凭据及本机报告不随源码发布。

`release-policy.json` 列出源码根目录、根文件、大小上限和逐文件固定 SHA 的界面资源。二进制仅保留列明的字体、图标、通用礼物插画和通话提示音等资源；新增或修改时须显式复核清单。模型、数据库等禁止路径不能通过清单豁免。

`.scratch/`、`coordination/`、`corpus/`、调研截图和运行产物留在本机。历史上已跟踪的文件必须从 Git 索引移出；忽略规则不会将它们移除。上游许可、第三方署名及必要的历史 ADR 保留。

## 检查实际提交

暂存期望源码后在根目录执行：

```sh
python scripts/check-release.py
git diff --cached --check
git diff --cached --stat
```

默认检查 Git 索引中的 blob，能识别被暂存的敏感文件，不读取忽略的本机资源。提交后和 CI 使用：

```sh
python scripts/check-release.py --ref HEAD
python scripts/check-gim-scope.py
python -m unittest discover -s scripts/tests -v
```

检查拒绝私有目录、模型／数据库／归档、未批准的二进制、越界符号链接、模型／剧情／向量 JSON 载荷和常见凭据格式。输出只含路径、行号和原因，不输出匹配值。规则不能保证识别任意秘密或剧情文本，仍需人工复核文件清单和新增正文。

`--report <本机报告路径>` 可保存只含元数据的 JSON。报告留在忽略目录，不提交原始扫描内容。

## 分支与 CI

`codex/gim-release` 推送会运行 CI，无需 PR。该分支只检查、测试和构建镜像，不登录 GHCR 或推送镜像；镜像发布仍限于 `main` 和版本标签。发布分支推送不修改默认分支，也不部署服务器。

普通推送保留 Git 历史。当前文件树的移除不等于历史擦除；本流程不重写历史，不清除上游或此前提交中的文件。
