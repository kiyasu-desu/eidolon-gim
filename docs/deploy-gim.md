# Eidolon-GIM 部署

当前范围为本地私用；以下部署步骤是配置说明，尚无本项目容器或公网验收结论。完整状态见 [PROJECT-STATUS](../coordination/PROJECT-STATUS.md)。

默认月村手毬单角色，数据库和角色路径与参考 SC 项目分开。应用从当前源码构建，不拉取上游 SC 镜像。需要 Docker Compose v2；生产配置使用 Linux host 网络。

## 与参考项目共存

- Compose 项目名默认 `eidolon-gim`，卷为 `eidolon-gim_eidolon-data`。不要用 `-p eidolon-sc`、`COMPOSE_PROJECT_NAME=eidolon-sc` 或外部卷把两个项目合并。
- 本地入口默认 `127.0.0.1:3001`；生产前后端为 `127.0.0.1:3001/8001`，可用 `EIDOLON_FRONTEND_PORT`、`EIDOLON_BACKEND_PORT` 调整。
- 生产 Caddy/coturn 仍用标准 80/443、3478 等端口。同一服务器已有它们时，只启动本项目的 `backend frontend`，在现有反向代理增加学马域名→`127.0.0.1:3001`，并另配可用 STUN/TURN。不要启动第二套占相同端口的服务。
- `characters/`、`corpus/` 只读挂载；原始 `E:\gakumas` 不挂入容器，`corpus/` 不作为公开静态文件目录。本地 3D 模型已接入通话层；容器需另外提供相同相对路径的派生模型、animations.json 与贴图，本项目尚未做容器运行验收。

## 本地 Docker

仓库根目录准备自己的 `.env`，至少填写 `CHAT_LLM_*`；已有文件保留。不要复制参考项目的密钥、数据库或账户ID。开发登录显式设置 `EIDOLON_DEV_LOGIN=1`，不要设置公网域名或访问白名单。

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').read().decode())"
```

打开 [本地对话列表](http://127.0.0.1:3001/conversations)。入口只绑定回环地址；后端通过数据库健康检查后再启动前端。

容器强制使用 `/characters/gim/characters.toml`、`/data/eidolon-gim.db`，避免宿主 Windows 路径覆盖。Linux 容器不能运行 System.Speech，Compose 会关闭本机语音开关；需要中性语音时按 [README](../README.md#windows-本机中性语音) 原生启动。当前角色已绑定 Fish Audio voice_id，宿主本地真实通话已有验收；容器仍需配置远程 STT/TTS 凭据并另行验收。

`docker compose down` 只停止当前项目；不加 `-v`，保留数据卷。

## Linux 服务器

准备当前源码、域名/DNS、Docker/Compose v2 和自己的 `.env`。除模型配置外，还需：

```dotenv
EIDOLON_DOMAIN=<学马域名>
EIDOLON_PUBLIC_IP=<服务器公网IPv4>
EIDOLON_TURN_SECRET=<随机密钥>
EIDOLON_SECRET_KEY=<另一随机密钥>
EIDOLON_PRIVATE_MODE=1
EIDOLON_ALLOWED_IDENTITIES=github:<固定数字ID>
GITHUB_CLIENT_ID=<OAuth应用ID>
GITHUB_CLIENT_SECRET=<OAuth密钥>
```

GitHub 回调为 `https://<学马域名>/api/auth/github/callback`；Google 为 `/api/auth/google/callback`，至少配一家。白名单使用 GitHub 数字 ID 或 Google `sub`，不是昵称/邮箱。private 模式空白名单拒启；开发登录与白名单互斥；已有未获准会话也会失效。`EIDOLON_ADMINS` 只授予管理权限，另行配置。固定 ID 未知时先在仅本机可访问的环境确认身份，不能先开放注册再补限制。

公网 IP 不在网卡上时填写 `EIDOLON_PRIVATE_IP`；NAT、TURN、OAuth 细节见 [上游部署资料](deploy.md)。保持 `.env` 私有。本轮不代表服务器、NAT 或云语音实测。

### 独立主机

```sh
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

应用镜像为 `eidolon-gim-backend:local`、`eidolon-gim-frontend:local`；`EIDOLON_IMAGE_TAG` 仅改变构建标签，配置仍从当前源码构建。Caddy 读取同一 `EIDOLON_FRONTEND_PORT`，默认代理到 3001。

### 已有反向代理的服务器

```sh
docker compose -f docker-compose.prod.yml up -d --build backend frontend
```

这条命令不启动本配置的 Caddy/coturn。部署者须在现有服务完成域名路由及 TURN 配置，并检查端口、共享密钥；应用容器启动不等于外网通话验收。

## 更新与观察

更新确认过的当前源码后，重新执行对应 `up -d --build`；改 `.env` 后重建服务，不只 `restart`。没有本项目镜像发布流水线时，不使用上游 GHCR `pull` 代替构建。

```sh
docker compose -f docker-compose.prod.yml logs --tail 100 backend
docker compose -f docker-compose.prod.yml exec backend eidolon user list
```

`/api/health` 实际检查数据库可读性，失败返回503；Docker健康状态不会自动重启。容器日志最多5×10 MB；后端停止宽限30秒，先给请求最多20秒完成，再清理通话/连接。通话全局上限默认10，由 `EIDOLON_CONCURRENT_CALLS` 或后台调整；每用户同时一通。

备份沿用应用的加密备份/数据导出机制，详见 [备份](deploy.md#备份)，上线前独立验证恢复。不要恢复SC数据库覆盖GIM原型库。剧情使用 [import-gim](gim-story-import.md)，不运行SC的 `story-sync.sh`、`world sync` 或 ShinyColorsDB 同步。
