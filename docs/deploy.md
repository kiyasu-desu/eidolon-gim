# 部署

Eidolon-GIM 的本地 Docker、Linux 和与其他实例共存部署统一见 [GIM 部署指南](deploy-gim.md)。

模型与剧情均由部署者单独提供，不随源码或镜像分发。路径、启停、迁移和恢复见 [本地资源包](local-resource-packs.md)。Compose 把 `corpus/` 只读挂载为 `/corpus`；容器中的资源路径必须使用 `/corpus/...`，不能直接使用 Windows 本机盘符。

## 备份与恢复

账户、对话和个人记忆仍在 `EIDOLON_DATABASE_PATH`。使用 `eidolon backup`、`deploy/db-backup.sh` 及 `deploy/db-restore.sh` 管理应用数据库备份；停服后恢复，并先用 `eidolon restore --check <文件>` 检查。独立剧情库及模型包需要另行保留原包和完整性清单，不包含在应用库备份中。不要通过删除用户数据库卸载剧情。

## 后台

`EIDOLON_ADMINS` 配置管理员身份。后台保存过的可覆盖项优先于 `.env`；需恢复环境变量配置时，在后台将对应项恢复默认。资源包路径和开关在启动时读取，修改后重启后端。

## 当前范围

当前仅提供学马 CSV 的显式本地导入，不包含旧作品的剧情、世界、立绘镜像下载或 cron 同步任务。服务健康检查、日志轮转、并发限制与通用备份仍可使用。部署凭据和实际资源不得提交到 Git。
