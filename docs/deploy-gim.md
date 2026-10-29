# Eidolon-GIM 部署

本项目支持本地 Docker 与 Linux 部署。本文使用示例域名和身份标识；实际地址、账号、凭据及私有资源由部署者单独配置。

默认月村手毬单角色，数据库和角色路径与参考 SC 项目分开。应用从当前源码构建，不拉取上游 SC 镜像。需要 Docker Compose v2；生产配置使用 Linux host 网络。

## 与参考项目共存

- **项目与卷隔离**：Compose 项目名默认 `eidolon-gim`，卷为独立持久卷 `eidolon-gim_eidolon-data`。不要用 `-p eidolon-sc`、`COMPOSE_PROJECT_NAME=eidolon-sc` 或把两个项目合并到同一个数据卷。
- **端口分配**：本地入口默认 `127.0.0.1:3001`；生产前后端为 `127.0.0.1:3001/8001`，由环境变量 `EIDOLON_FRONTEND_PORT`、`EIDOLON_BACKEND_PORT` 分别指定，与参考项目的 `3000/8000` 端口完全避开。
- **反向代理与 TURN 共用**：同机已有 Caddy（80/443）和 coturn（3478 等端口）时，本项目通过 Compose 覆盖配置（`.env.server-compose.yml`）将自身的 `caddy` 与 `coturn` 服务置于 `standalone` profile 下，默认不启动，避免端口冲突。
- **Caddy 反代配置**：在宿主原有的 Caddyfile 中为新域名追加独立反代块：
  ```caddyfile
  gim.example.com {
      bind {$EIDOLON_PRIVATE_IP}

      request_body /api/account/data-package {
          max_size 201MiB
      }

      handle {
          reverse_proxy 127.0.0.1:3001
      }
  }
  ```
  修改后先验证 Caddy 配置，再按宿主已有服务的方式重载；核对其他站点仍可访问。
- **资源路径**：模型和导入来源可在只读 `/corpus`；剧情 SQLite 使用 WAL，应放在可写目录，推荐 `EIDOLON_STORY_DATABASE_PATH=/data/gim.stories.db`。模型根目录可设置 `EIDOLON_MODEL_ROOT=/corpus/local-packs/models`。详见[资源包说明](local-resource-packs.md)。

## 本地 Docker

仓库根目录准备自己的 `.env`，至少填写 `CHAT_LLM_*`；已有文件保留。不要复制参考项目的密钥、数据库或账户ID。开发登录显式设置 `EIDOLON_DEV_LOGIN=1`，不要设置公网域名或访问白名单。

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').read().decode())"
```

打开 [本地对话列表](http://127.0.0.1:3001/conversations)。入口只绑定回环地址；后端通过数据库健康检查后再启动前端。

容器强制使用 `/characters/gim/characters.toml`、`/data/eidolon-gim.db`，避免宿主 Windows 路径覆盖。Linux 容器不能运行 System.Speech，Compose 会关闭本机语音开关；需要中性语音时按 [README](../README.md#windows-本机中性语音) 原生启动。当前角色已绑定 Fish Audio voice_id，容器需配置远程 STT/TTS 凭据。

`docker compose down` 只停止当前项目；不加 `-v`，保留数据卷。

## Linux 服务器（生产部署）

生产部署采用本地预先构建并导出镜像、打包应用与过滤数据、上传远端服务器并执行导入与恢复的幂等流水线。除外部模型与语音配置外，核心运行环境配置如下：

```dotenv
EIDOLON_DOMAIN=gim.example.com
EIDOLON_FRONTEND_PORT=3001
EIDOLON_BACKEND_PORT=8001
EIDOLON_PUBLIC_IP=<服务器公网IP>
EIDOLON_TURN_SECRET=<同机 coturn 共享密钥>
EIDOLON_SECRET_KEY=<独立生成的 64 位十六进制密钥>
EIDOLON_PRIVATE_MODE=1
EIDOLON_ALLOWED_IDENTITIES=google:<your-sub>
EIDOLON_ADMINS=google:<your-sub>
GOOGLE_CLIENT_ID=<Google OAuth Client ID>
GOOGLE_CLIENT_SECRET=<Google OAuth Client Secret>
```

### 部署与安全规范

1. **OAuth 与回调**：Google OAuth 回调路径为 `https://gim.example.com/api/auth/google/callback`。可与同机参考项目复用同一 OAuth 客户端（在 Google Cloud Console 中追加 Authorized redirect URIs）。
2. **私密模式与白名单**：生产开启 `EIDOLON_PRIVATE_MODE=1` 时，未在 `EIDOLON_ALLOWED_IDENTITIES` 白名单中的陌生用户登录后会被拒绝（返回 403）；未登录访问 `/api/account` 返回 401；`EIDOLON_DEV_LOGIN` 与域名互斥，生产构建访问 `/api/auth/dev-login` 恒为 404。
3. **数据卷恢复**：在首次部署或数据迁移时，通过备份归档将清洗后的 SQLite 数据库导入独立数据卷 `eidolon-gim_eidolon-data`，并校验 `PRAGMA integrity_check` 为 `ok`，绑定主账号的 Google `sub`，保留历史对话记录。
4. **服务共存部署命令**：
   ```sh
   # 校验配置
   docker compose -f docker-compose.prod.yml config --quiet
   # 仅启动 backend 与 frontend 容器（pull_policy: never，使用已加载的镜像构建标签）
   docker compose -f docker-compose.prod.yml up -d --build backend frontend
   # 查看状态
   docker compose -f docker-compose.prod.yml ps
   ```

## 线上验收基准

部署完成后需逐项执行以下线上验收：

1. **健康检查**：`GET https://gim.example.com/api/health` 返回 `200 {"ok":true}`（实测健康检查涵盖数据库可读性）。
2. **安全防护**：匿名 `GET /api/account` 返回 401；`GET /api/auth/dev-login` 返回 404。
3. **OAuth 启动**：`GET /api/auth/google/start` 返回 302 重定向至 `accounts.google.com` 且携带安全 state cookie。
4. **外部服务全链路探测**：通过后端执行 `/api/service-status`，验证 7 项服务状态全为 `ok`：
   - `chat_llm` / `memory_llm` / `tts` / `stt` / `judge` / `embedding` / `rerank`
5. **手毬 3D 资产可达性**：
   - `GET /api/characters/temari/stand/model.json` -> 200 OK（约 20.3MB）
   - `GET /api/characters/temari/stand/animations.json` -> 200 OK（约 3.8MB）
   - `GET /api/characters/temari/stand/textures/*.png` -> 200 OK
6. **宿主隔离性**：确认宿主机原有 既有容器保持持续正常运行，无端口或卷冲突。
