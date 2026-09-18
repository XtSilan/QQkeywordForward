# QQ 群管理机器人设计

这份设计基于当前仓库的 NoneBot + NapCat Compose 方案，目标是让群管理员通过 WebUI 完成关键词、通知、历史记录和批量群发的全部配置。机器人使用 OneBot V11 事件和 API，数据使用 SQLite，所有状态放在挂载目录中。

参考了 [nonebot_plugin_forwarder](https://github.com/Utmost-Happiness-Planet/nonebot_plugin_forwarder) 的源群/目标群转发思路，但把固定环境变量扩展成 WebUI 配置、任务队列、审计和限速。

## 目标边界

第一版包含：

- 每个群独立维护关键词规则、启用状态和通知配置。
- 用普通文本添加关键词；系统内部生成安全的正则表达式，管理员不需要编写正则。
- 把关键词命中记录到 SQLite，可按群、关键词、时间和发送者查询。
- 命中后向多个 QQ 好友发送通知，也可向多个邮箱发送通知；QQ 和邮件通道可分别开关。
- 从 QQ 群列表读取群头像、群名称和群号，在 WebUI 中批量选择目标群。
- 创建批量群发任务，消息支持文本、换行和按位置插入图片。
- 任务显示在 Dashboard，逐群显示排队、发送中、成功、失败和跳过原因。
- 每个目标群有发送冷却时间，任务有群间延时；全局限制最多每分钟发送 5 个群。

第一版不包含自动私聊回复、复杂富文本编辑器、跨实例分布式队列和邮件附件。

## 系统结构

~~~mermaid
flowchart LR
    N[NapCatQQ / OneBot V11] -->|事件 WebSocket| NB[NoneBot Worker]
    NB --> K[关键词匹配器]
    K --> DB[(SQLite WAL)]
    K --> Q[通知队列]
    W[WebUI 管理员] --> API[FastAPI WebUI API]
    API --> DB
    API --> Q
    Q --> S[发送调度器]
    S -->|send_private_msg| N
    S -->|send_group_msg| N
    S -->|SMTP| M[邮件服务器]
~~~

生产 Compose 运行两个进程，共享同一个项目代码和 SQLite：

- nonebot：连接 NapCat，接收群消息，执行关键词匹配。
- webui：提供 FastAPI、静态前端和发送调度器；调度器读取同一个 SQLite 队列。

SQLite 开启 WAL。发送任务使用数据库租约和唯一键，进程重启后可以继续处理未完成任务。

## 消息处理

### 关键词

1. NoneBot 接收 GroupMessageEvent。
2. 提取纯文本用于匹配，同时保留原始 Message 段用于图片等内容的通知。
3. 读取该群启用的关键词规则，在内存中按更新时间增量缓存。
4. 用 Python re.search(pattern, normalized_text, flags) 匹配。普通文本先做 re.escape，所以加号、方括号、括号等字符按字面量匹配，管理员不需要理解正则。
5. 同一条消息命中多个关键词时写入多条命中记录，但同一个通知通道按消息合并，避免好友收到重复通知。
6. 写入 keyword_hits 后，把通知任务写入 notification_jobs。通知失败保留重试次数和最后错误。
7. 关键词命中默认不在群内回复。

WebUI 展示的是 display_text，不展示内部 pattern。以后如需高级模式，可以增加管理员模式，让受信任管理员明确选择字面量或正则，默认仍为字面量。

### 通知内容

QQ 好友通知至少包含：

~~~text
[关键词命中]
群：群名称（群号）
发送者：群名片/昵称（QQ号）
命中：关键词显示文本
时间：2026-09-18 12:34:56
消息：
原始消息内容
~~~

原始 Message 段按 OneBot V11 消息数组传给 send_private_msg，因此图片可以保留。邮件默认发送纯文本和图片 URL/文件说明；邮件内嵌图片附件作为后续版本。

## 关键词和群配置

关键词采用规则加群绑定模型：

- keyword_rules 是全局规则，保存显示文本和生成后的正则。
- group_keyword_bindings 把规则绑定到群，保存该群自己的启用开关和覆盖值。
- 群 A 修改开关或冷却时间不会改变群 B。
- 批量同步采用复制配置快照，不共享一行记录。页面先显示目标群和覆盖项，提交后写审计记录。

同一个关键词在同一群只允许一条绑定。关键词删除采用软删除，历史记录仍显示当时的关键词文本。

默认匹配规则：

| 配置 | 默认值 | 说明 |
|---|---:|---|
| 匹配模式 | literal_search | 先 re.escape，再 re.search |
| 忽略大小写 | 是 | 使用 re.IGNORECASE |
| 规范空白 | 是 | 连续空白折叠为一个空格，原文仍保留 |
| 群规则启用 | 否 | 新建规则显式启用 |
| 同群重复通知冷却 | 60 秒 | 同群、同关键词、同发送者冷却期内只通知一次 |

## 群发任务

### 选择和编辑

WebUI 调用 OneBot 的 get_group_list 获取群号和名称，调用 get_group_info 同步群资料。列表展示头像、名称、群号和当前冷却状态。

编辑器保存 OneBot V11 消息段数组，不把内容拼成 HTML：

~~~json
[
  {"type": "text", "data": {"text": "第一行\n第二行\n"}},
  {"type": "image", "data": {"file": "https://example/image.jpg"}},
  {"type": "text", "data": {"text": "\n图片后面的内容"}}
]
~~~

回车保存为换行符。图片插入位置由消息段数组决定，发送时传给 send_group_msg，所以 QQ 客户端显示顺序与编辑器一致。后端只允许受控上传文件或 HTTPS 图片地址，禁止任意本地路径。

### 限速和冷却

- group_cooldown_seconds：同一个目标群再次收到相同任务或内容前的最小间隔，防止重复点击。
- interval_seconds：本任务发送完一个群后等待多久再处理下一个群。

全局发送器限制任意连续 60 秒最多 5 个群：

- interval_seconds 小于 12 秒时拒绝保存，页面提示最小值为 12 秒。
- 预计最短完成时间为目标群数量乘以 12 秒。
- 单群失败不阻塞后续群，记录错误码和错误文本。
- 同一任务只能有一个调度租约，避免重复投递。

任务状态：draft -> queued -> running -> completed；也支持 completed_with_errors 和 cancelled。

## WebUI 信息架构

侧边栏：

1. Dashboard：在线状态、NapCat 连接状态、今日命中数、待发送任务、最近失败。
2. 关键词：关键词列表、按群过滤、启用开关、添加/编辑、批量同步。
3. 通知设置：QQ 好友列表、邮箱列表、通道开关、每群覆盖、批量应用。
4. 历史记录：按群查看时间线，按关键词、发送者和时间过滤。
5. 群发任务：创建任务、群选择器、消息编辑器、延时和冷却设置。
6. 任务详情：进度、每群结果、错误信息、重试失败群、取消未发送部分。
7. 系统设置：OneBot 状态、SMTP、管理员账号、保留天数、备份。

配置页面提供仅保存配置和立即测试两个动作。批量操作显示目标群数量和将覆盖的字段。

## SQLite 数据模型

~~~sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE groups (
  group_id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  avatar_url TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  last_synced_at TEXT NOT NULL
);

CREATE TABLE keyword_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  display_text TEXT NOT NULL,
  pattern TEXT NOT NULL,
  match_mode TEXT NOT NULL DEFAULT 'literal_search',
  ignore_case INTEGER NOT NULL DEFAULT 1,
  deleted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE group_keyword_bindings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id TEXT NOT NULL REFERENCES groups(group_id),
  keyword_id INTEGER NOT NULL REFERENCES keyword_rules(id),
  enabled INTEGER NOT NULL DEFAULT 0,
  cooldown_seconds INTEGER NOT NULL DEFAULT 60,
  updated_at TEXT NOT NULL,
  UNIQUE(group_id, keyword_id)
);

CREATE TABLE notification_destinations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK(kind IN ('qq', 'email')),
  address TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  UNIQUE(kind, address)
);

CREATE TABLE group_notification_settings (
  group_id TEXT PRIMARY KEY REFERENCES groups(group_id),
  qq_enabled INTEGER NOT NULL DEFAULT 0,
  email_enabled INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE notification_destination_bindings (
  group_id TEXT NOT NULL REFERENCES groups(group_id),
  destination_id INTEGER NOT NULL REFERENCES notification_destinations(id),
  PRIMARY KEY(group_id, destination_id)
);

CREATE TABLE keyword_hits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id TEXT NOT NULL REFERENCES groups(group_id),
  group_name TEXT NOT NULL DEFAULT '',
  sender_id TEXT NOT NULL,
  sender_name TEXT NOT NULL DEFAULT '',
  keyword_id INTEGER REFERENCES keyword_rules(id),
  keyword_text_snapshot TEXT NOT NULL,
  message_json TEXT NOT NULL,
  message_text TEXT NOT NULL,
  message_id TEXT NOT NULL,
  hit_at TEXT NOT NULL,
  notify_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE broadcast_tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  message_json TEXT NOT NULL,
  interval_seconds INTEGER NOT NULL CHECK(interval_seconds >= 12),
  group_cooldown_seconds INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  total_count INTEGER NOT NULL DEFAULT 0,
  sent_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  cancelled_at TEXT
);

CREATE TABLE broadcast_task_groups (
  task_id TEXT NOT NULL REFERENCES broadcast_tasks(id),
  group_id TEXT NOT NULL REFERENCES groups(group_id),
  status TEXT NOT NULL DEFAULT 'queued',
  scheduled_at TEXT NOT NULL,
  sent_at TEXT,
  message_id TEXT,
  error_code TEXT,
  error_text TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(task_id, group_id)
);

CREATE TABLE notification_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  hit_id INTEGER NOT NULL REFERENCES keyword_hits(id),
  destination_id INTEGER NOT NULL REFERENCES notification_destinations(id),
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  last_error TEXT,
  sent_at TEXT
);

CREATE TABLE audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_keyword_hits_group_time ON keyword_hits(group_id, hit_at DESC);
CREATE INDEX idx_keyword_hits_keyword_time ON keyword_hits(keyword_id, hit_at DESC);
CREATE INDEX idx_broadcast_task_groups_due ON broadcast_task_groups(status, scheduled_at);
CREATE INDEX idx_notification_jobs_due ON notification_jobs(status, next_attempt_at);
CREATE UNIQUE INDEX uq_keyword_rules_active_text
  ON keyword_rules(display_text) WHERE deleted_at IS NULL;
~~~

时间统一使用 UTC ISO 8601 存储，WebUI 按 Asia/Shanghai 显示。message_json 保存原始 OneBot 消息段，历史详情和通知重试才能保留图片。

## API 合同

API 只接受登录 WebUI 会话或管理员 Bearer token：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /api/dashboard | 统计、连接状态、近期任务 |
| GET | /api/groups | 同步和查询群列表 |
| GET/POST/PATCH/DELETE | /api/keywords | 关键词增删改查 |
| POST | /api/keywords/bulk-apply | 把规则复制到选中的群 |
| GET/PUT | /api/groups/{id}/keyword-settings | 群级启用和冷却 |
| GET/POST/PATCH/DELETE | /api/destinations | QQ 好友/邮箱收件人 |
| PUT | /api/groups/{id}/notification-settings | 群级通道开关和收件人绑定 |
| POST | /api/notifications/test | 测试 QQ 或邮件通道 |
| GET | /api/history | 分页、按群/关键词/时间过滤 |
| POST | /api/broadcast-tasks | 创建群发任务 |
| GET | /api/broadcast-tasks/{id} | 任务进度和逐群结果 |
| POST | /api/broadcast-tasks/{id}/cancel | 取消未发送部分 |
| POST | /api/broadcast-tasks/{id}/retry-failed | 重新排队失败群 |
| POST | /api/uploads/image | 上传图片并返回受控资源 ID |

批量应用请求：

~~~json
{
  "keyword_id": 12,
  "group_ids": ["10001", "10002"],
  "copy": {
    "enabled": true,
    "cooldown_seconds": 60,
    "notification_settings": true
  }
}
~~~

后端对每个请求开启事务，写 audit_logs，并返回变更数量和跳过原因。前端不能提交 SQL 或任意正则。

## 发送器

发送器在独立 asyncio 任务中循环：

1. 取一个已到期的 broadcast_task_groups 或 notification_jobs。
2. 用 SQLite BEGIN IMMEDIATE 抢占记录并写入短租约，租约超时可恢复。
3. 检查任务取消状态、群冷却和全局 5/分钟令牌桶。

当前实现已经在 NoneBot worker 内启动单实例调度循环：关键词命中会根据群级通知设置写入 `notification_jobs`，群发任务由 WebUI 写入 `broadcast_task_groups`；worker 通过 OneBot V11 Bot API 发送 QQ 私聊和群消息，并更新发送、失败和完成状态。邮箱任务会保留为失败状态并记录“email sender not configured”，待 SMTP 适配器接入后重试。
4. 调用 NoneBot Bot 的 OneBot V11 API：好友通知使用 send_private_msg，群发使用 send_group_msg。
5. 成功写入 OneBot 返回的 message_id；失败按指数退避，最多 3 次。
6. 更新 Dashboard 计数，前端通过 WebSocket 或短轮询刷新进度。

OneBot API 由 NapCat 暴露，WebUI 不直接连接 NapCat。所有 QQ 操作都经过 NoneBot 的 Bot 生命周期。

## 部署升级

当前部署文档中的 NoneBot 社区镜像可以继续用于验证。正式运行 WebUI 时建议构建自己的项目镜像，固定 Python、依赖和前端产物：

~~~yaml
services:
  nonebot:
    build: .
    command: python /app/run_nonebot.py
    env_file: ./.env.prod
    volumes:
      - ./src:/app/src
      - ./data/nonebot:/app/data
      - ./data/python-packages:/opt/python-packages
      - ./.env.prod:/app/.env.prod:ro
    expose:
      - "8080"

  webui:
    build: .
    command: uvicorn app.web:app --host 0.0.0.0 --port 8080
    env_file: ./.env.prod
    volumes:
      - ./src:/app/src
      - ./data/nonebot:/app/data
      - ./.env.prod:/app/.env.prod:ro
    ports:
      - "8080:8080"
    depends_on:
      - nonebot
~~~

这段是升级方向，不能直接替换现有 NapCat 挂载路径。正式落地前需要针对当前 mlikiowa/napcat-docker 版本实测配置目录、WebUI 端口和反向 WebSocket 地址，并把镜像 tag 改为 digest。

启动和重建：

~~~bash
docker compose config
docker compose up -d
docker compose logs -f webui
docker compose up -d --force-recreate webui nonebot
~~~

删除容器不会删除 data/nonebot、data/python-packages、data/napcat 和 SQLite。备份时停止发送器，复制 SQLite、图片目录、.env.prod、依赖锁文件和 NapCat 配置。

## 权限和安全

- 第一个版本只允许一个管理员账号或管理员 token，接口默认不开放匿名写入。
- WebUI 只发布到内网或 HTTPS 反向代理；NapCat WebUI 和 OneBot 端口不要暴露到公网。
- QQ 号、邮箱、SMTP 密码和消息内容属于敏感数据，日志脱敏，.env.prod 使用 0600。
- 上传图片保存到受控目录，校验 MIME、大小和扩展名，禁止路径穿越。
- SQLite 每天备份；历史和图片按配置保留 30/90/180 天。
- 关键词配置、批量同步、群发任务和取消操作都写审计日志。

## 分阶段实施

### 阶段 1：可运行骨架

- [ ] 创建 FastAPI + NoneBot 项目镜像和共享配置模块。
- [ ] 建立 SQLite schema、迁移脚本和 WAL 初始化。
- [ ] 接入 OneBot V11，完成群列表、好友列表和群消息监听。
- [ ] 实现关键词 CRUD、字面量转正则、命中历史。

### 阶段 2：通知和历史

- [ ] 实现 QQ 好友通知队列和重试。
- [ ] 实现 SMTP 邮件通知、测试接口和群级开关。
- [ ] 完成历史页面、筛选、详情和图片展示。
- [ ] 完成批量关键词复制及审计。

### 阶段 3：群发和任务中心

- [ ] 实现图片上传、消息段编辑器和 OneBot 消息段校验。
- [ ] 实现群选择器、任务队列、5 群/分钟令牌桶和群冷却。
- [ ] 实现 Dashboard 进度、取消、失败重试和恢复租约。
- [ ] 做删除容器重建、SQLite 恢复和 NapCat 登录态恢复演练。

### 阶段 4：上线加固

- [ ] 固定镜像 digest，补健康检查、日志轮转和资源限制。
- [ ] 增加管理员登录审计、CSRF 防护和 HTTPS 反代说明。
- [ ] 增加自动备份、保留策略和升级回滚脚本。
- [ ] 在测试群验证文本、图片、换行、重复命中、冷却和取消任务。

## 验收标准

- 修改一个群的关键词开关不会改变其他群。
- 批量同步后每个群都有独立配置快照和审计记录。
- 一条消息命中关键词后，历史可见，多个 QQ 好友收到一次合并通知。
- WebUI 选择 6 个群创建任务时，实际发送间隔满足每分钟不超过 5 个群，任务进度可追踪。
- 文本换行和图片位置在 QQ 群消息中保持一致。
- 删除并重建 NoneBot/WebUI 容器后，关键词、历史、未完成任务、插件依赖和 NapCat 配置仍可读取。

## 参考

- [NoneBot 配置文档](https://nonebot.dev/docs/appendices/config)
- [NoneBot OneBot 适配器](https://github.com/nonebot/adapter-onebot)
- [NapCatQQ](https://github.com/NapNeko/NapCatQQ)
- [nonebot_plugin_forwarder](https://github.com/Utmost-Happiness-Planet/nonebot_plugin_forwarder)
- [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/)
- [Docker volumes](https://docs.docker.com/engine/storage/volumes/)
