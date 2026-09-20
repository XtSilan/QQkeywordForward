# QQ Bot Forward

基于 NapCat + OneBot V11 + NoneBot 的 QQ 群管理机器人，并提供 FastAPI/React WebUI 控制台。

当前支持：

- 群级关键词配置、批量绑定和历史命中记录
- 关键词命中后发送 QQ 私聊或 SMTP 邮件通知
- 群发任务、任务进度、发送限速和群间延时
- 文本换行以及 JPG/PNG/GIF/WEBP 图片上传群发
- NoneBot 自动同步 OneBot 群列表
- 按环境变量自动配置 NapCat OneBot 反向 WebSocket 与鉴权 token
- NapCat 二维码登录、状态、重启和日志查看
- 管理员会话认证、Bearer API 兼容和审计日志
- SQLite WAL 数据库，数据通过宿主机目录持久化

## 运行要求

- Docker Engine 24+ 和 Docker Compose v2+
- 能访问 Docker Hub
- 一个用于登录 NapCat 的 QQ 账号
- SMTP 账号（仅在需要邮件通知时）

## 快速部署

### 1. 准备项目和数据目录

```bash
git clone https://github.com/XtSilan/qq_bot_forward.git
cd qq_bot_forward
mkdir -p data/napcat data/nonebot data/logs/nonebot
```

NapCat 登录态、SQLite、图片和日志都写入 `data/`，该目录已被 Git 忽略。

### 2. 配置 .env.prod

创建根目录 `.env.prod`：

```dotenv
APP_ENV=prod
ENVIRONMENT=prod

# 必须替换
ADMIN_TOKEN=请替换为高强度随机字符串
AUTH_SESSION_SECRET=请替换为另一组高强度随机字符串
AUTH_SESSION_TTL=86400

# NapCat WebUI token，来自 data/napcat/webui.json
NAPCAT_WEBUI_URL=http://napcat:6099
NAPCAT_WEBUI_TOKEN=NapCat-WebUI-token

# OneBot V11 鉴权 token（两组必须填相同值，留空则不做鉴权）
ONEBOT_ACCESS_TOKEN=
ONEBOT_V11_ACCESS_TOKEN=
ONEBOT_WS_URL=ws://nonebot:8081/onebot/v11/ws

# SMTP（不需要邮件时可留空）
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=bot@example.com
SMTP_PASSWORD=邮箱密码
SMTP_FROM=bot@example.com
SMTP_STARTTLS=true
SMTP_SSL=false
SMTP_TIMEOUT=15

# 必须是 NapCat 容器可访问的地址
PUBLIC_BASE_URL=http://你的服务器IP:8080
MAX_UPLOAD_SIZE_MB=10
```

```bash
chmod 600 .env.prod
```

不要提交 `.env.prod`、NapCat token、QQ 密码、SMTP 密码或 `data/`。

### 3. 校验并启动

```bash
docker compose config
docker compose up -d --build
docker compose ps
```

WebUI：<http://localhost:8080>

| 服务 | 宿主机端口 | 用途 |
| --- | ---: | --- |
| WebUI | 8080 | 管理控制台 |
| NoneBot | 8081 | OneBot V11 反向连接入口 |
| NapCat | 6099 | NapCat WebUI |
| NapCat | 3001 | OneBot 网络端口 |

查看日志：

```bash
docker compose logs -f --tail=200 webui
docker compose logs -f --tail=200 nonebot
docker compose logs -f --tail=200 napcat
```

## 首次配置

### NapCat 登录

1. 打开 WebUI 的“登录与 NapCat”。
2. 生成二维码并使用 QQ 扫码登录。
3. 等待状态显示已登录。
4. 二维码过期时点击刷新；必要时执行重启。

也可以直接访问 <http://localhost:6099> 检查 NapCat 状态。

### OneBot 反向 WebSocket

反向 WS 由环境变量驱动，不需要在 WebUI 里手工配置。WebUI 容器启动后会跑一个后台同步任务：等 NapCat 登录完成后，每 30 秒检查一次 OneBot 配置，把名为 `websocket-client` 的条目对齐到：

```text
url   = ONEBOT_WS_URL      （默认 ws://nonebot:8081/onebot/v11/ws）
token = ONEBOT_ACCESS_TOKEN
```

只在 `url` / `enable` / `token` 与上述值不一致时才写回，其余字段（如 `reconnectInterval`）保持不动。因此改这两项后不需要手动改 NapCat，只要重启 webui 容器即可生效。

鉴权 token 需要**两个变量填相同的值**，因为两侧读的是不同的环境变量：

- `ONEBOT_ACCESS_TOKEN`：由 WebUI 下发给 NapCat，NapCat 用它作为 `Authorization: Bearer` 头发起连接
- `ONEBOT_V11_ACCESS_TOKEN`：NoneBot 的 OneBot V11 适配器用它校验入站连接

两者都留空则不校验，任何能访问 8081 端口的客户端都能连上来。只填其中一个会导致连接失败（适配器有值而 NapCat 没带 token，会返回 403）。

### 群列表同步

OneBot 连接成功后，NoneBot 默认每 5 分钟调用 `get_group_list`，自动写入群号、群名和头像地址。关键词和群发页面直接读取这份 SQLite 群列表。

## WebUI 使用

### 关键词和通知

“关键词”页面支持按换行、中文/英文逗号或空格一次输入多个关键词，再批量选择群聊和 QQ/邮箱提醒地址。群聊列表支持全选与取消全选，系统内部使用安全的字面量正则匹配。

“系统设置”提供跨群重复消息过滤。默认同一完整消息正文首次命中正常提醒，第 2 次开始过滤 10 分钟；触发重复过滤的 QQ 账号也会同时冷却 10 分钟，在此期间该账号发送的其他关键词消息同样被过滤。空格、换行、大小写和全角/半角差异不影响重复识别，其他账号和正文不同的消息不会互相影响。被过滤的消息不会写入关键词历史。一次消息命中多个关键词时会合并为一条历史和一条提醒，提醒只包含关键词与消息内容；每个已配置收件人各收到一份，发送失败会进入后台重试。

### 群发和图片

1. 在“群发任务”中多选已同步群聊，也可以一键全选。
2. 输入正文，回车会作为换行发送。
3. 上传可选图片并预览。
4. 设置群间延时，最小 5 秒；后台仍执行每分钟最多 5 个群的保护限速。
5. 创建任务后查看排队、成功和失败数量。

图片保存在 `data/nonebot/uploads`。不要把 `PUBLIC_BASE_URL` 填成容器不可访问的浏览器专用 `localhost`，否则 NapCat 无法下载图片。

## 认证和审计

生产环境访问 WebUI 时使用管理员 token 登录。脚本仍可使用：

```http
Authorization: Bearer <ADMIN_TOKEN>
```

所有 `/api/` 的 POST、PUT、PATCH、DELETE 会写入 SQLite `audit_logs`。查询：

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8080/api/audit-logs
```

审计不会保存 token、NapCat credential、SMTP 密码或消息正文。

## 持久化、重建和备份

重要数据位置：

```text
data/napcat/       NapCat 配置、登录态和设备信息
data/nonebot/      SQLite、上传图片和 NoneBot 数据
data/logs/nonebot/ NoneBot 日志
.env.prod          密钥和运行配置
```

普通重建不会丢失这些数据：

```bash
docker compose up -d --build --force-recreate
```

不要把宿主机虚拟环境直接挂载到容器。新增插件依赖时更新 `requirements.txt`，再重新构建镜像。不要在日常操作中执行 `docker compose down -v`。

备份：

```bash
docker compose stop
tar --xattrs --acls -czf qq-bot-backup-$(date +%F).tar.gz \
  compose.yaml Dockerfile requirements.txt .env.prod app web data
docker compose start
```

恢复后执行：

```bash
docker compose config
docker compose up -d --build
```

NapCat 登录态恢复后仍可能因设备验证或风控要求重新登录。

## 更新和故障排查

```bash
git pull
docker compose build --pull
docker compose up -d --force-recreate
```

- WebUI 未授权：检查 `APP_ENV=prod`、`ADMIN_TOKEN`，重新登录并确认浏览器允许 Cookie。
- NapCat 返回 Not Login：先完成 QQ 登录，再重试状态或 OneBot 配置。
- 群列表为空：检查 OneBot URL、NapCat 登录状态和 `nonebot` 日志。
- 邮件失败：检查 SMTP 主机、端口、STARTTLS/SSL 和发件地址权限。
- 图片失败：确认 `PUBLIC_BASE_URL` 能从 NapCat 容器访问，并检查上传目录权限。
- 数据消失：确认没有删除 `data/`，且所有服务使用当前 Compose 文件。

健康检查：

```bash
curl http://localhost:8080/api/health
```

## 安全建议

- 生产环境替换 `ADMIN_TOKEN`、`AUTH_SESSION_SECRET` 和 NapCat token。
- 不要把 6099、3001、8081 暴露到公网，优先用防火墙限制来源。
- Docker socket 挂载允许 WebUI 控制容器；不需要服务重启时应移除该挂载并关闭控制能力。
- 定期加密备份 `data/napcat`、`data/nonebot` 和 `.env.prod`。
- 生产环境使用固定镜像版本，不使用 `latest`。

## 相关文档

- [NoneBot + NapCat Compose 方案](nonebot-napcat-docker-compose.md)
- [QQ 机器人设计](qq-bot-design.md)
- [WebUI 与 NapCat 运维设计](webui-ui-operations-design.md)
- [NoneBot 官方文档](https://nonebot.dev/docs/)
- [NapCat 官方文档](https://napneko.github.io/)
