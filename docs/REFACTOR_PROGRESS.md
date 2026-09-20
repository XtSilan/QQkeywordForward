# 架构重构进度

## 目标
拆解 main.py (1391 行) 和 main.tsx (556 行) 单体文件，按业务域分层。

## 目标目录结构

### 后端
```
app/
  main.py              # 仅 app = FastAPI() + include_router + startup
  settings.py          # 配置
  db.py                 # 连接 + 迁移调度
  control.py            # Docker 控制
  napcat.py             # NapCat client
  nonebot_bot.py        # NoneBot 适配
  schemas/              # Pydantic 模型
    auth.py group.py keyword.py notification.py broadcast.py settings.py
  api/                  # FastAPI router
    deps.py auth.py groups.py keywords.py history.py destinations.py
    notification_configs.py notification_settings.py broadcast.py
    settings.py ops.py dashboard.py uploads.py health.py audit_logs.py
  services/             # 业务逻辑（dispatch_loop、napcat_sync）
  repositories/         # SQL（后续抽）
  migrations/
    001_initial.sql
    002_keyword_sort_order.sql
```

### 前端
```
web/src/
  main.tsx             # 仅 ReactDOM.render
  App.tsx              # 路由 + 布局
  api/ types/ pages/ components/ hooks/ utils/ styles/
```

### 文档
```
docs/                  # 设计文档（从根目录迁入）
```

## 进度

- [x] Phase 1：后端 schemas 拆分（app/schemas/*）
  - [x] auth.py / group.py / keyword.py / notification.py / broadcast.py / settings.py
  - [x] main.py import 调整，删除本地 class 定义
  - [x] 验证：docker compose build webui + health + /api/keywords + /api/broadcast-tasks POST 全通过
  - [x] main.py 行数：1391 → 1293

- [x] Phase 4：后端 api router 拆分（app/api/*）
  - [x] deps.py（admin_guard / napcat / row_dict / session_token / valid_session）
  - [x] auth.py / health.py / settings.py
  - [x] keywords.py / broadcast.py / notifications.py / groups.py / history.py
  - [x] dashboard.py / uploads.py / audit.py / ops.py
  - [x] main.py 瘦身为 router 挂载：1293 → 135 行
  - [x] 验证：路由集合重构前后完全一致（54 → 54）；本地 venv + TestClient 跑通 20 项端点检查
  - 备注：本机 Docker Desktop 未运行，未执行 docker compose build；已用等价运行时验证替代

- [x] Phase 3：后端 services 拆分（app/services/*）
  - [x] email.py（从 nonebot_bot 抽出 SMTP 发送，避免循环导入）
  - [x] dispatch.py（调度循环：群同步 / 通知分发 / 群发分发 / 频率限制，含 start/stop 生命周期）
  - [x] napcat_sync.py（main.py 的 _auto_apply_onebot_config 抽出；run_onebot_sync）
  - [x] nonebot_bot.py 瘦身为 NoneBot 接线：472 → 284 行；main.py 102 行
  - [x] api/notifications.py 改用 services.email
  - [x] 验证：compileall + venv 下 dispatch 生命周期 / email config / napcat_sync import / nonebot_bot 委托 + API 全量回归通过

- [x] Phase 2：后端 repositories 拆分（app/repositories/*）
  - [x] keyword_repo / broadcast_repo / group_repo / notification_repo / meta_repo / history_repo / audit_repo
  - [x] repo 函数接收 conn，事务边界由 api 层控制（保留多表写入原子性）
  - [x] 消除重复 SQL：group_notification_settings 的 3 种 upsert 收敛到 group_repo
  - [x] row_dict 下沉到 db.py（repo 不再依赖 api 层）
  - [x] api/*.py 不再直接写 SQL；db.py 110 → 118 行
  - [x] 验证：路由一致性 54==54 + 48 项行为断言（含级联重算、幂等、409/404/400 边界）全通过

- [x] Phase 5：后端迁移 SQL 文件化
  - [x] migrations/001_initial.sql（主 schema）
  - [x] migrations/002_broadcast_interval.sql
  - [x] migrations/003_duplicate_message_cooldowns.sql
  - [x] migrations/004_keyword_sort_order.sql
  - [x] db.py 新增 load_migration()，SCHEMA 常量删除；db.py 359 → 110 行
  - [x] 验证：legacy DB 升级（interval≥12→≥5 / 去 keyword_id / 加 sort_order）+ 幂等性 + 全新库 schema 全通过

- [x] Phase 6：前端 types + api 层
  - [x] types/api.ts（全部领域类型 + 状态文案映射；类型都很小，未再按域拆碎）
  - [x] api/client.ts（apiJson / apiText / apiUpload）
  - [x] api/auth|dashboard|groups|keywords|notifications|history|broadcast|napcat|settings|ops.ts
  - [x] 页面不再散落魔法字符串路径，改为具名函数调用

- [x] Phase 7：前端 components 拆分
  - [x] StatusDot / StatCard / ServiceRow / QuickAction / InfoRow / GroupCard / GroupPicker / DestinationPicker / EmptyState / BroadcastActivity(+BroadcastCountCard)
  - [x] 新增 EmptyState：原先 5 处重复的 empty-state 结构收敛为一个组件

- [x] Phase 8：前端 pages 拆分
  - [x] LoginPage / DashboardPage / KeywordPage / HistoryPage / NapCatPage / LogsPage / BroadcastPage / SystemSettingsPage / PlaceholderPage
  - [x] 原先 4000+ 字符的单行 JSX 全部拆成可读多行；KeywordPage 抽出 KeywordRow、BroadcastPage 抽出 TaskActions
  - [x] 删除从未被渲染的 NotificationsPage（死代码）

- [x] Phase 9：前端 CSS 分层
  - [x] styles/index.css + tokens / layout / dashboard / forms / napcat / responsive / theme / overlays / overlays-responsive
  - [x] 按原文件「连续区间」切分，import 顺序即层叠顺序
  - [x] 验证：拆分后重组内容与原文件逐字节一致；实际构建产物 CSS sha256 完全相同（FEBDC992…）

- [x] Phase 10：前端 hooks 抽离
  - [x] hooks/usePoll.ts：收敛 5 处 useEffect+setInterval+cleanup 轮询样板
  - [x] lib/parse.ts：收敛关键词/地址解析（原先内联两处）

- [x] Phase 11：文档迁移到 docs/
  - [x] docs/REFACTOR_PROGRESS.md（本文件）

- [x] Phase 12：最终验证
  - [x] 后端：路由集合 54==54；48 项行为断言；迁移升级/幂等验证
  - [x] 前端：tsc -b（strict）+ vite build 通过；CSS 产物 sha256 与重构前一致
  - [x] 本地 npm ci 后真实构建（Docker Desktop 未运行，未跑 compose build）

## 成果概览（前端）

| 项 | 重构前 | 重构后 |
|---|---|---|
| main.tsx | 555 行（全部页面/组件/类型/请求） | 11 行（仅挂载） |
| style.css | 357 行单文件 | 9 个按层拆分的样式文件 |
| 前端文件数 | 2 | 45 |

## 历史记录性能修复 + 日期筛选（已完成）

背景：历史列表接口每页都在做全表扫描。`WHERE (? IS NULL OR group_id=?)` 这种参数化 OR 无法被 SQLite 规划进索引（实测 `SCAN keyword_hits` + `USE TEMP B-TREE FOR ORDER BY`，**即使带了 group_id 也一样**）；`ORDER BY hit_at DESC` 没有对应索引；`COUNT(*)` 每页都单独跑一次。

### 改动

- [x] `migrations/008_history_indexes.sql`：`idx_keyword_hits_hit_at(hit_at DESC)`，并种子 `history_retention_days=0`
- [x] `app/db.py`：`_migrate_history_indexes()` 守卫（检查索引是否已存在）+ 接入 `init_db`
- [x] `app/repositories/history_repo.py`：`_where()` 动态拼 WHERE；`since`/`until` 走字符串范围比较；排序只用 `hit_at DESC`（加 `id DESC` 反而让"按群筛选"多出一次 `USE TEMP B-TREE FOR RIGHT PART OF ORDER BY`）；新增 `HIT_AT_FORMAT` + `storage_timestamp()` 统一时间戳形状
- [x] `app/api/history.py`：新增可选 `since`/`until`（datetime，UTC 瞬时）；路由数不变
- [x] `app/services/dispatch.py`：`_prune_history()` 挂进每小时清扫，按 `history_retention_days` 清理（**默认 0 = 不删任何数据**；删除 hit 前必须先删其 `notification_jobs`，否则外键 RESTRICT 会报错）
- [x] `web/src/api/history.ts`：`listHistory({groupId, since, until, limit, offset})`
- [x] `web/src/pages/HistoryPage.tsx`：日期筛选（URL 存 `?date=YYYY-MM-DD`，由浏览器把本地日历日换算成 `since`/`until`，所以"哪一天"按操作者本机时区算；不选=全部历史，`全部历史` 按钮同时清群聊与日期）+ 页码跳转框（配合既有 `?page=`）
- [x] `web/src/styles/forms.css`：`.history-date` / `.pager-jump`
- [x] `tests/test_history_api.py`（7 项）：无筛选排序、按本地日范围、边界形状归一（`Z` / `+00:00` / 裸时间）、群筛选与范围组合、关键词筛选+分页、非法 `since` 422、EXPLAIN 回归断言（三条查询都走索引且无 TEMP B-TREE）
- [x] 验证：history 7/7、broadcast_loop 6/6、dispatch 21/21、order_dedup 7/7、settings 3/3；`tsc -b` + `vite build` 通过

### 已验证的查询计划（新索引下）

| 查询 | 计划 |
|---|---|
| 无筛选，`ORDER BY hit_at DESC` | `SCAN keyword_hits USING COVERING INDEX idx_keyword_hits_hit_at` |
| `WHERE hit_at >= ? AND hit_at < ?` | `SEARCH ... USING COVERING INDEX idx_keyword_hits_hit_at` |
| `WHERE group_id = ?` | `SEARCH ... USING COVERING INDEX idx_keyword_hits_group_time` |
| 上述各筛选下的 `COUNT(*)` | 走索引，无临时排序 |

## 群发任务自动循环（已完成）

- [x] `migrations/009_broadcast_loop.sql`：`broadcast_tasks` 加 `loop_total`（总轮数，含首轮，0=不循环）/ `loop_current`（进行中的轮次，1-based）/ `loop_interval_seconds`（轮间隔）
- [x] `app/repositories/broadcast_repo.py`：`create()` 写循环字段；`list_tasks`/`get_task` 返回 `round_sent`/`round_failed`（只统计进行中那一轮）；`start_next_round()` 重置并重排全部群行；`update_intervals()`
- [x] `app/api/broadcast.py`：新增 `PUT /api/broadcast-tasks/{task_id}`——轮间隔随时可改；群间延时会影响已排定的队列，仍限制为暂停后（沿用原有约定）。**路由装饰器 51 → 52**
- [x] `app/services/dispatch.py`：本轮跑完且 `loop_current < loop_total` → `start_next_round()`，否则照旧收尾
- [x] 前端 `BroadcastPage.tsx`：创建表单加「自动循环发送」开关（勾选后展开循环次数/每轮间隔）；任务行显示 `循环 N 轮 · 轮间隔 M 秒`、状态显示"循环中"、进度显示 `第 X/Y 轮 · 本轮 N/M`（进度条按当前轮走）、操作列加轮间隔编辑器
- [x] `tests/test_broadcast_loop.py`（6 项）+ `tests/test_dispatch.py` 两个轮次推进用例
- 取舍：每轮开始会重置群行，因此上一轮的逐群明细会被覆盖（任务级 `sent_count` 累计值保留）；需要保留每轮明细就得再加轮次明细表

## 线上运维记录

- 2026-09-20 远程 `/opt/qq_bot_forward`（instance1）：`.env.prod` 的 `ONEBOT_WS_URL` 一直是默认值 `ws://napcat:3001`（NapCat 连自己容器的 3001），`napcat_sync` 每 30 秒把 env 值推进 NapCat，于是反向 WS 永久 `ECONNREFUSED`——现象是"更新后只推了一条消息"（那一条是配置被覆盖前 16 秒窗口里进来的）。已改为 `ws://nonebot:8081/onebot/v11/ws` 并重建 webui。**教训：`.env.prod` 必须显式覆盖 `ONEBOT_WS_URL` 与 `ONEBOT_ACCESS_TOKEN`，否则会退回 `app/settings.py` 的默认值。**
- 远程只有 `docker-compose` v1.29.2，与新版 Docker 引擎不兼容（`KeyError: 'ContainerConfig'`），且没有 compose v2 插件。重建单个服务不要直接 `up --force-recreate`，改用：`docker-compose config -q` 校验 → `docker rm -f <container>` → `docker-compose up -d --no-deps <service>`。

## 执行规则
- 每个 phase 完成后 docker compose build + health check 必须通过
- 每个 phase 完成后建议 git commit（用户批准后）
- 如 context 接近上限，主动 commit + 把进度同步到本文件
