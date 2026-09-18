# WebUI、NapCat 运维和日志设计

本文是 QQ 群管理机器人设计的第二轮补充，确定管理台 UI、NapCat 登录操作、服务重启、日志集成以及配置变更策略。实现目标是：管理员只访问一个 WebUI，不需要进入容器手工执行命令。

## UI 技术选型

采用 React + Vite + TypeScript + Tailwind CSS v4 + shadcn/ui。

选择理由：

- shadcn/ui 提供 Sidebar、Data Table、Dialog、Form、Tabs、Progress、Toast、Avatar、Textarea、Command 等组件，适合配置型后台。
- Tailwind CSS v4 通过 Vite 插件接入，样式可以保持小而可控，不引入大型运行时主题系统。
- React Query 用于 API 缓存、轮询和失效更新；Zod + React Hook Form 用于表单校验。
- lucide-react 用于按钮图标，消息段编辑器使用少量自定义组件。

页面采用固定左侧导航、顶部连接状态和窄内容区，不做营销式首页。重点信息优先显示：

| 页面 | 首屏内容 | 主要动作 |
|---|---|---|
| Dashboard | NapCat/NoneBot 状态、今日命中、待发送任务、最近错误 | 登录、重启、查看任务 |
| 关键词 | 当前群、启用状态、关键词表、批量应用 | 添加、编辑、复制、启用 |
| 通知 | QQ 好友、邮箱、群级通道开关 | 添加收件人、发送测试 |
| 历史 | 群选择器、时间线、关键词和发送者过滤 | 查看原消息、重新通知 |
| 群发任务 | 群选择列表、消息段编辑器、预计耗时 | 创建、暂停、取消、重试 |
| 登录与 NapCat | 二维码、登录阶段、账号信息、快速登录 | 刷新二维码、登录、重启 |
| 日志 | NoneBot 与 NapCat 标签页、实时滚动、级别过滤 | 暂停、复制、下载 |
| 系统设置 | SMTP、保留策略、OneBot 配置变更提示 | 保存、测试、重启 |

## NapCat 集成边界

当前 NapCat WebUI 后端源码提供以下路由。实际前缀和响应包装以部署的 NapCat 版本为准：

| NapCat 路由 | 方法 | 管理台用途 |
|---|---|---|
| /api/QQLogin/GetQQLoginQrcode | POST | 获取当前二维码 URL |
| /api/QQLogin/CheckLoginStatus | POST | 获取登录阶段、在线状态和错误 |
| /api/QQLogin/RefreshQRcode | POST | 刷新二维码 |
| /api/QQLogin/GetQuickLoginList | GET | 快速登录账号列表 |
| /api/QQLogin/SetQuickLogin | POST | 快速登录指定 QQ |
| /api/QQLogin/GetQQLoginInfo | POST | 当前登录账号信息 |
| /api/QQLogin/PasswordLogin | POST | 密码 MD5 登录 |
| /api/QQLogin/CaptchaLogin | POST | 验证码登录 |
| /api/QQLogin/NewDeviceLogin | POST | 新设备验证登录 |
| /api/QQLogin/GetNewDeviceQRCode | POST | 新设备二维码 |
| /api/QQLogin/PollNewDeviceQR | POST | 新设备二维码轮询 |
| /api/QQLogin/RestartNapCat | POST | 请求重启 NapCat |
| /api/Process/Restart | POST | 请求重启当前 NapCat 进程 |
| /api/Log/GetLogList | GET | 日志文件列表 |
| /api/Log/GetLog?id=... | GET | 读取指定日志 |
| /api/Log/GetLogRealTime | GET | SSE 实时日志 |

NapCat WebUI 的业务 API 使用 `Authorization: Bearer <credential>` 鉴权。`webui.json` 里的 token 是 WebUI 登录口令，不能直接当作 Bearer 值；后端先调用 `/api/auth/login`，提交 `SHA256(token + ".napcat")`，再在内存中缓存返回的 Credential。token 和 Credential 只保存在服务端环境变量/内存中，浏览器不直接调用 NapCat。

### 后端代理

我们的 WebUI API 提供稳定的内部接口：

| 我方接口 | 代理动作 |
|---|---|
| GET /api/ops/napcat/login | 调用 CheckLoginStatus，并返回脱敏状态 |
| POST /api/ops/napcat/qrcode | 调用 GetQQLoginQrcode |
| POST /api/ops/napcat/qrcode/refresh | 调用 RefreshQRcode |
| POST /api/ops/napcat/quick-login | 调用 SetQuickLogin |
| POST /api/ops/napcat/password-login | 在服务端转发密码 MD5，不记录密码 |
| POST /api/ops/napcat/restart | 调用 RestartNapCat |
| GET /api/ops/logs/napcat | 代理日志列表或历史内容 |
| GET /api/ops/logs/napcat/stream | 服务端代理 SSE，断线自动重连 |

登录页面显示二维码 URL 或 data URL。二维码过期时前端提示并调用刷新接口。登录状态采用 2 秒轮询，成功后停止轮询并刷新群列表。

密码登录默认关闭，只显示二维码和快速登录。只有管理员明确设置 `NAPCAT_PASSWORD_LOGIN_ENABLED=true` 时才展示表单，后端仅接收密码 MD5，日志和错误响应中不得回显凭据。

## NoneBot 配置热加载和重启

不能把所有配置变更都做成重启。配置分为两类：

### 运行时热加载

以下配置写入 SQLite，保存成功后立即对 worker 生效：

- 关键词和群绑定。
- 关键词启用开关、匹配冷却。
- QQ 好友和邮件收件人。
- 群级通知开关。
- 历史保留天数。
- 群发任务和调度参数。

NoneBot worker 每次消息到达时从带版本号的内存缓存读取规则。WebUI 写入后增加 config_revision；worker 通过同一 SQLite 的 revision 或内部轮询发现变更，清空对应群的缓存。SQLite revision 仍是重启后的事实来源。

### 需要重启 NoneBot

以下配置修改后必须提示保存成功，等待重启：

- .env.prod 中的 NoneBot 驱动、适配器、OneBot WebSocket 地址和 token。
- Python 依赖、插件安装、插件目录和项目入口。
- 监听端口、日志输出方式和进程参数。

WebUI 提供 POST /api/ops/services/nonebot/restart。生产实现不允许前端直接执行任意 shell；由受控服务控制器调用 Compose API 或 supervisor，只允许重启 nonebot、webui、napcat 三个白名单服务。重启按钮显示影响范围和预计中断时间。

重启流程：

1. 保存并校验配置。
2. 创建 audit_logs 记录，状态为 restart_pending。
3. 暂停新群发任务的领取，已发送消息不回滚。
4. 请求 NoneBot 优雅退出，等待最多 20 秒。
5. 由 Compose 或 supervisor 拉起服务。
6. 等待 OneBot 状态 online，并执行健康检查。
7. 恢复任务领取，记录成功或失败原因。

NapCat 重启和 NoneBot 重启是两个独立按钮。改 NoneBot 规则不重启 NapCat；改 NapCat 的 OneBot 连接配置通常要重启 NapCat，并在页面明确提示。

## 日志集成

### NoneBot

NoneBot 使用结构化 JSON 日志，同时写 stdout 和 ./data/logs/nonebot/nonebot.log，供 WebUI 历史查询。

WebUI 后端提供：

- GET /api/ops/logs/nonebot?level=&since=&limit=
- GET /api/ops/logs/nonebot/stream，SSE
- GET /api/ops/logs/nonebot/download

日志结构至少包含 timestamp、level、logger、event、message、group_id、user_id、task_id。QQ 号、邮箱、token、密码和消息正文按配置脱敏。日志轮转按 20 MB 或每日一次，保留 14 天。

### NapCat

优先使用 NapCat 官方的 GetLogList、GetLog 和 GetLogRealTime。WebUI 后端保存 NapCat credential，不把 NapCat log 目录硬编码到前端。

如果当前镜像版本没有可用 WebUI 日志接口，则降级到：

1. NapCat 容器 stdout 的 Compose 日志。
2. 由控制器读取 Docker Engine API 的容器日志。
3. 最后才读取显式挂载的日志目录。

Docker socket 是高权限能力，只在需要 Docker 日志或服务重启时挂载，WebUI 仍只允许服务名白名单和日志读取操作。不能把 Docker socket 暴露给浏览器。

日志页面采用两个来源标签：NoneBot 和 NapCat。

## 数据库选型

继续使用 SQLite，不引入 MySQL。

原因：

- 当前服务是单机 Compose，配置、历史和队列都属于单实例数据。
- SQLite WAL 支持 NoneBot worker 和 WebUI worker 共享读写，备份只需要复制数据文件和图片目录。
- 关键词命中和群发任务不是高并发写入场景，SQLite 足够。
- 加入 MySQL 会增加一个容器、账号、备份和升级依赖，当前收益不明显。

迁移到 MySQL 的触发条件是多 worker、多节点或每秒持续数百条以上命中写入。

SQLite 文件位置固定为 ./data/nonebot/bot.sqlite3，开启 WAL、foreign_keys 和 busy_timeout。数据库迁移使用版本号脚本，WebUI 启动前执行迁移，失败则不启动发送器。

## 控制器和 Compose

服务分为：

- napcat：现有 mlikiowa/napcat-docker，挂载账号和配置。
- nonebot：NoneBot worker，监听 `8081` 的 OneBot V11 反向 WebSocket/HTTP，并连接 NapCat。
- webui：React 静态文件、FastAPI API、调度器和 NapCat 代理。
- 可选 control：只在需要 Docker 重启和 Docker 日志时启用的受限控制器。

控制器接口只接受 service = napcat | nonebot | webui，以及 action = restart | logs。logs 只能使用 tail、since、follow，restart 需要管理员二次确认 token，并写审计日志。不能传入任意容器名、命令或 shell 字符串。

建议优先用 Docker Engine API 的受限服务账号；开发环境可以暂时在 webui 使用 Docker socket，生产环境再拆成 control 服务。

## 配置文件和挂载

~~~text
.
├── compose.yaml
├── .env.prod
├── src/
├── data/
│   ├── nonebot/bot.sqlite3
│   ├── nonebot/uploads/
│   ├── logs/nonebot/
│   └── napcat/
└── web/
    └── dist/
~~~

WebUI、NoneBot 和控制器共享 data/nonebot、data/logs 和 .env.prod 的必要挂载。NapCat 账号目录只挂载给 napcat 和必要的备份任务，不挂载给前端。

## 第一轮实施范围

本轮完成文档、选型和接口边界，提交后开始写代码：

- [x] 选定 React + Vite + TypeScript + Tailwind v4 + shadcn/ui。
- [x] 核对 NapCat 当前源码中的二维码、登录、重启和日志路由。
- [x] 确定 SQLite 继续使用及迁移条件。
- [x] 规定热加载配置和需要重启 NoneBot 的配置。
- [x] 规定 WebUI 后端代理和日志来源。

下一轮实现：

- [ ] 创建 FastAPI/NoneBot 项目骨架和 SQLite migration。
- [ ] 创建 Vite 前端和 Sidebar/Dashboard 初始页面。
- [ ] 接入 NapCat 状态、二维码、重启和日志代理。
- [ ] 接入 NoneBot 健康状态和受控重启接口。

## 参考

- [shadcn/ui Vite 安装](https://ui.shadcn.com/docs/installation/vite)
- [shadcn/ui 组件](https://ui.shadcn.com/docs/components)
- [Tailwind CSS Vite 安装](https://tailwindcss.com/docs/installation/using-vite)
- [NapCatQQ GitHub](https://github.com/NapNeko/NapCatQQ)
- [OneBot 11 API](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)
- [Docker Compose logs](https://docs.docker.com/reference/cli/docker/compose/logs/)
- [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/)
