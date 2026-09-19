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

- [ ] Phase 4：后端 api router 拆分（app/api/*）
  - [ ] deps.py（admin_guard / napcat_client）
  - [ ] auth router
  - [ ] keywords router
  - [ ] broadcast router
  - [ ] notification router
  - [ ] groups router
  - [ ] settings router
  - [ ] ops router (napcat/services)
  - [ ] dashboard / uploads / audit_logs / health
  - [ ] main.py 瘦身为 router 挂载

- [ ] Phase 3：后端 services 拆分（app/services/*）
  - [ ] dispatch_loop.py（从 nonebot_bot.py 抽出调度循环）
  - [ ] napcat_sync.py（启动时自动应用 ws 配置）

- [ ] Phase 2：后端 repositories 拆分（app/repositories/*）
  - [ ] keyword_repo / broadcast_repo / group_repo / notification_repo

- [ ] Phase 5：后端迁移 SQL 文件化
  - [ ] 002_keyword_sort_order.sql

- [ ] Phase 6：前端 types + api 层
  - [ ] types/keyword.ts broadcast.ts group.ts dashboard.ts napcat.ts auth.ts
  - [ ] api/client.ts keywords.ts broadcast.ts napcat.ts auth.ts

- [ ] Phase 7：前端 components 拆分
  - [ ] StatCard / StatusDot / ServiceRow / GroupCard / GroupPicker / DestinationPicker / BroadcastActivity / Wizard

- [ ] Phase 8：前端 pages 拆分
  - [ ] DashboardPage / KeywordPage / BroadcastPage / HistoryPage / SettingsPage / LogsPage / LoginPage

- [ ] Phase 9：前端 CSS 分层
  - [ ] styles/tokens.css base.css components/*.css pages/*.css

- [ ] Phase 10：前端 hooks 抽离
  - [ ] useApi / useBroadcastTasks / useBotStatus / useKeywords

- [ ] Phase 11：文档迁移到 docs/

- [ ] Phase 12：最终验证（build + health + 端到端 API）

## 执行规则
- 每个 phase 完成后 docker compose build + health check 必须通过
- 每个 phase 完成后建议 git commit（用户批准后）
- 如 context 接近上限，主动 commit + 把进度同步到本文件
