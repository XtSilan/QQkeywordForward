# NoneBot + NapCat Docker Compose 部署方案

本文给出一个可重建、可备份、插件和 Python 包不依赖容器可写层的部署基线。当前目录没有现成项目文件，因此示例使用以下约定：

```text
.
├── compose.yaml
├── .env.prod                 # 仅放服务器配置和密钥，不提交 Git
├── src/                      # NoneBot 项目源码、插件源码
├── data/
│   ├── nonebot/              # NoneBot 工作目录和持久化数据
│   ├── python-packages/      # 持久化 pip 包（容器内安装）
│   └── napcat/               # NapCat 配置、设备信息、登录数据
├── requirements.txt          # 锁定直接依赖，建议另生成 requirements.lock
└── .gitignore
```

## 结论

可以使用 `docker compose up -d` 根据挂载目录启动并重建容器，而且容器删除/重建不会丢失源码、`.env.prod`、NapCat 登录数据或持久化 Python 包，前提是这些内容放在 bind mount 或 named volume 中，并且不要执行 `docker compose down -v`。

推荐的责任边界是：

| 内容 | 持久化位置 | 说明 |
|---|---|---|
| NoneBot `src/`、配置、插件源码 | 宿主机 `./src`、`./data/nonebot` | 便于 Git、审计和回滚 |
| `.env.prod` | 宿主机 `./.env.prod`，只读挂载 | 不提交仓库；权限建议 `0600` |
| pip 包 | `./data/python-packages` 或 named volume | 由容器内 Python 安装，避免宿主机 venv 的 ABI/路径问题 |
| NapCat 配置/登录态 | `./data/napcat` | 删除容器不会删除；备份时必须包含 |
| 镜像 | Registry + Compose 中的固定 tag/digest | `latest` 只适合测试，不适合生产 |

## 镜像与官方资料

### NoneBot

- 社区镜像：[`rrorange/nonebot2-quickly-docker`](https://hub.docker.com/r/rrorange/nonebot2-quickly-docker)
- 对应项目：[`zhiyu1998/nonebot2-quickly-docker`](https://github.com/zhiyu1998/nonebot2-quickly-docker)
- 项目 README 给出的用法是挂载 `/nb2`，并在容器内执行 `pip install` 后重启。这说明它适合作为快速基线，但不是 NoneBot 官方发行镜像，生产环境应固定版本、保存依赖清单并自行验证镜像内容。
- NoneBot 官方文档：[`配置（dotenv 与环境变量）`](https://nonebot.dev/docs/appendices/config)、[`快速上手`](https://nonebot.dev/docs/quick-start)、[`NoneBot GitHub`](https://github.com/nonebot/nonebot2)。官方文档说明 `.env`、`.env.{ENVIRONMENT}` 可作为配置来源，环境变量会覆盖 dotenv 中同名值。

### NapCat / OneBot

- 使用的镜像：[`mlikiowa/napcat-docker`](https://hub.docker.com/r/mlikiowa/napcat-docker)
- 上游项目：[`NapNeko/NapCatQQ`](https://github.com/NapNeko/NapCatQQ)
- Docker Hub 查询到该仓库持续发布版本标签（例如 `v4.18.28`）并提供 amd64/arm64 镜像。生产环境应使用明确版本标签或 digest，不要依赖会漂移的 `latest`。
- NapCat 官方文档入口：[`napneko.github.io`](https://napneko.github.io/)。QQ 登录、设备验证、风控和账号合规问题仍由 NapCat/QQ 平台决定，Compose 不能消除这些风险。

### Docker Compose

- [`docker compose up` 官方参考](https://docs.docker.com/reference/cli/docker/compose/up/)
- [Docker volumes 官方文档](https://docs.docker.com/engine/storage/volumes/)
- `up -d` 会在后台创建/启动服务；配置或镜像变化时会重建容器，但不会删除 bind mount 或 named volume。 `--force-recreate` 可强制重建；`down -v` 会删除 Compose 管理的 named volume，必须谨慎。

## 推荐 Compose 基线

下面的文件把 NoneBot 和 NapCat 放在同一个 Compose 网络中。NoneBot 通过服务名 `napcat` 访问 OneBot 反向 WebSocket，避免写宿主机 IP。

```yaml
name: qq-bot

services:
  nonebot:
    image: rrorange/nonebot2-quickly-docker:0.0.6
    # 生产环境请将 tag 替换为已验证的固定版本或 digest。
    restart: unless-stopped
    working_dir: /nb2
    env_file:
      - ./.env.prod
    environment:
      ENVIRONMENT: prod
      PYTHONPATH: /nb2/src:/opt/python-packages
      PIP_TARGET: /opt/python-packages
      PIP_DISABLE_PIP_VERSION_CHECK: "1"
    volumes:
      - ./src:/nb2/src
      - ./data/nonebot:/nb2/data
      - ./data/python-packages:/opt/python-packages
      - ./requirements.txt:/nb2/requirements.txt:ro
      - ./.env.prod:/nb2/.env.prod:ro
    command: >-
      sh -c "python -m pip install --no-cache-dir --target /opt/python-packages
      -r /nb2/requirements.txt && python3 /nb2/bot.py"
    depends_on:
      napcat:
        condition: service_started
    networks:
      - botnet

  napcat:
    image: mlikiowa/napcat-docker:v4.18.28
    # 首次上线前应核对该 tag 的 digest，并在此处固定为 digest。
    restart: unless-stopped
    environment:
      NAPCAT_UID: "1000"
      NAPCAT_GID: "1000"
    volumes:
      - ./data/napcat:/app/napcat/config
    ports:
      # 仅在需要从宿主机访问 WebUI/调试端口时开放；OneBot 内网通信无需发布端口。
      - "6099:6099"
    networks:
      - botnet

networks:
  botnet:
    driver: bridge
```

### 关于 `command` 和项目入口

不同版本的社区镜像可能有不同入口脚本。第一次启动先检查：

```bash
docker compose config
docker compose run --rm nonebot sh -lc 'python --version; test -f /nb2/bot.py; ls -la /nb2'
```

该镜像当前 Dockerfile 的默认入口是 `python3 bot.py --reload`；上例去掉了生产环境不需要的 `--reload`，并在启动前补装挂载的依赖。若镜像自带的 entrypoint 已负责安装依赖和启动项目，应删除上面的 `command`，改为沿用镜像默认入口。若项目实际入口是其他脚本，也应按项目的 `pyproject.toml`/README 修改。不要在没有核对镜像 entrypoint 的情况下直接覆盖它。

## 虚拟环境、pip 包和插件如何不丢

### 推荐：持久化容器内安装目录

上例把 pip 包安装到 `./data/python-packages`，并通过 `PYTHONPATH` 加载。这样容器删除后目录仍在，`up -d` 重建时继续可用；`requirements.txt` 变化时启动命令会补装/更新包。更适合生产的做法是提交锁定文件：

```bash
docker compose exec -T nonebot python -m pip freeze --path /opt/python-packages > requirements.lock
```

不要把宿主机上用其他 Python 版本、操作系统或 CPU 架构生成的 `.venv/` 直接挂载到容器中。带有 C 扩展的包（例如 `cryptography`、`numpy`、`lxml`）通常不可移植，绝对路径和 Python minor version 也可能不匹配。

### 可选：命名卷保存完整 venv

如果确实需要完整虚拟环境，可以让容器自己创建它，并使用 Compose named volume 保存：

```yaml
services:
  nonebot:
    volumes:
      - nonebot-venv:/opt/venv
    environment:
      PATH: /opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    command: >-
      sh -c "python -m venv /opt/venv &&
      /opt/venv/bin/pip install -r /nb2/requirements.txt &&
      /opt/venv/bin/python /nb2/bot.py"

volumes:
  nonebot-venv:
```

该卷与镜像的 Python 主/次版本绑定，升级基础镜像或切换架构时要重新验证；升级前先备份或导出 `pip freeze`。如果使用 bind mount `./data/venv:/opt/venv`，请确保目录由容器内同版本 Python 创建，不能拿宿主机 venv 直接套用。

### 插件持久化策略

1. 自研插件放在 `./src`，随 Git 版本管理。
2. PyPI 插件写入 `requirements.txt`/`requirements.lock`，不要只在正在运行的容器里手工 `pip install`。
3. 通过 `nb plugin install` 或其他 CLI 安装的内容，先确认它写入哪个目录；该目录必须挂载到 `./data/nonebot` 或单独 named volume。
4. 插件升级先备份依赖锁文件和数据，再执行一次性更新，保留可回滚的镜像 tag。

## 日常操作

```bash
# 校验 Compose 展开结果（不会启动）
docker compose config

# 首次启动/后台启动
docker compose up -d

# 查看状态和日志
docker compose ps
docker compose logs -f --tail=200 nonebot
docker compose logs -f --tail=200 napcat

# 拉取已固定 tag 的新镜像并重建；卷和 bind mount 保留
docker compose pull
docker compose up -d --force-recreate

# 仅重建 NoneBot
docker compose up -d --no-deps --force-recreate nonebot

# 进入容器确认包和插件
docker compose exec nonebot python -m pip list
docker compose exec nonebot sh -lc 'python -c "import nonebot; print(nonebot.__version__)"'
```

不要把 `docker compose down -v` 作为普通重启命令；它会删除 Compose 管理的 named volumes。普通的 `docker compose down` 不删除 volumes，但会停止并删除容器。

## `.env.prod` 注意事项

NoneBot 会读取 `.env` 和 `.env.{ENVIRONMENT}`；本示例设置 `ENVIRONMENT=prod`，因此使用 `.env.prod`。Compose 的 `env_file` 是把变量注入进程环境，`./.env.prod:/nb2/.env.prod:ro` 则是把文件提供给 NoneBot 的 dotenv 加载器，两者用途不同，可以同时保留。

建议：

```bash
chmod 600 .env.prod
printf '\n.env.prod\n.env\n' >> .gitignore
```

不要把 QQ 密码、token、设备信息或 NapCat 登录数据写入镜像层、提交 Git 或贴到公开 issue。

## 备份与恢复

至少备份以下内容：

```text
compose.yaml
requirements.txt / requirements.lock
.env.prod                 # 加密存储
src/
data/nonebot/
data/python-packages/     # 或导出的 venv/命名卷
data/napcat/
```

备份前停止服务以避免 SQLite/会话文件处于写入中：

```bash
docker compose stop
tar --xattrs --acls -czf qq-bot-backup-$(date +%F).tar.gz \
  compose.yaml requirements.txt requirements.lock .env.prod src data
docker compose start
```

恢复时先解压到同一项目目录，检查文件属主/权限，再运行 `docker compose config` 和 `docker compose up -d`。恢复 NapCat 登录态后可能仍需重新验证设备。

## 风险和后续工作

- [x] 确认实际 NoneBot 项目入口、Python 版本和适配器（例如 OneBot V11）并把 `requirements.txt` 锁定。
- [ ] 核对 `mlikiowa/napcat-docker` 当前版本的实际挂载路径、UID/GID、WebUI 端口和 OneBot 配置格式；以该镜像仓库当前 README 为准更新 Compose。
- [ ] 首次启动后确认 NapCat 的反向 WebSocket 地址指向 `ws://nonebot:<port>/onebot/v11/ws`（具体路径以适配器配置为准）。
- [ ] 暴露nonebot和napcat的端口
- [ ] 对两个镜像记录 digest，并建立升级前备份和回滚步骤。
- [ ] 为 `data/napcat`、`.env.prod` 和依赖目录设置最小权限；必要时将 secrets 改用 Docker secrets 或外部密钥管理。
- [ ] 增加健康检查、日志轮转、资源限制和监控告警。
- [ ] 在干净主机做一次“备份 -> 删除容器 -> `up -d` -> 验证插件/登录态”的演练。
- [ ] 评估 QQ 账号风控、自动登录和机器人使用是否符合相关平台规则。

## 参考链接（访问日期：2026-09-18）

- [NoneBot 配置文档](https://nonebot.dev/docs/appendices/config)
- [NoneBot 快速上手](https://nonebot.dev/docs/quick-start)
- [NoneBot GitHub](https://github.com/nonebot/nonebot2)
- [NoneBot Quickly Docker GitHub](https://github.com/zhiyu1998/nonebot2-quickly-docker)
- [NoneBot Quickly Docker Hub](https://hub.docker.com/r/rrorange/nonebot2-quickly-docker)
- [NapCatQQ GitHub](https://github.com/NapNeko/NapCatQQ)
- [NapCat Docker Hub](https://hub.docker.com/r/mlikiowa/napcat-docker)
- [Docker Compose `up`](https://docs.docker.com/reference/cli/docker/compose/up/)
- [Docker volumes](https://docs.docker.com/engine/storage/volumes/)
