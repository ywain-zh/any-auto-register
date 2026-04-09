# Release 说明

这个文件用于记录 `release` 分支每次准备部署时包含的内容。

使用规则：

1. 每次准备把 `custom/dev` 合并到 `release` 前，先更新本文件。
2. 记录本次发布的日期、分支、提交、主要改动、部署后需要关注的点。
3. 已发布的记录保留在下面，新的发布追加到最上方。

---

## 2026-04-09

- 发布分支：`release`
- 开发来源：`custom/dev`
- 发布提交：以本次 `release` 分支最新 HEAD 为准

### 本次内容

- 前端整体界面重做，统一为新的深色控制台风格，保留现有路由、接口与业务逻辑
- 邮箱服务新增 Gmail Alias 方案，补充微软邮箱状态维护、令牌刷新、删除接口和相关测试
- Codex 注册成功后补齐 access token / refresh token 等绑定结果持久化，并在账号数据中统一保存
- Sub2API 监控新增 `401账号`、`异常` 分类与可用账号统计逻辑调整，并补充对应回归测试
- Docker 部署说明更新为当前真实运行方式，补齐 `.env` 注入、`/runtime` 持久化目录和报告目录映射说明

### 部署后重点检查

- 打开首页、平台管理、邮箱服务页，确认新 UI 正常加载且接口返回正常
- 新建一条 Codex 注册任务，确认注册成功后账号记录包含 access token / refresh token 等绑定结果
- 打开微软邮箱页，确认列表、删除、刷新 token、查邮件和状态更新正常
- 打开 `/sub2api-monitor` 运行一次检查，确认 `counts.quota_exhausted`、`counts.account_401`、`counts.abnormal` 与可用账号统计正常
- Docker 部署后确认 `./data/account_manager.db`、`./data/logs/solver.log`、`./data/reports/` 持久化正常

### 备注

- 本次未纳入运行时文件 `codex-pool-manager/codex-pool-manager/hotmail_accounts_runtime.txt`
- 本次未纳入运行时配置 `codex-pool-manager/codex-pool-manager/*.runtime.yaml`
- `reports/` 目录和调试截图属于本地产物，未随本次发布提交

---

## 2026-04-07

- 发布分支：`release`
- 开发来源：`custom/dev`
- 发布提交：`092cced`

### 本次内容

- 重构邮箱管理入口，新增独立的邮箱服务页与微软邮箱账号页，支持服务实例切换、账号导入、列表分页和查邮件
- 后端统一邮箱服务解析与账号接口，补充 Hotmail 邮件拉取、Sub2API OAuth 绑定能力和相关测试
- 简化注册页与账号页中的邮箱选择逻辑，改为复用统一邮箱服务实例
- 增强 Sub2API 监控页运行反馈，补充执行中、成功、失败状态提示与错误展示

### 部署后重点检查

- 打开邮箱服务与微软邮箱页面，确认服务列表、账号分页、TXT 导入和查邮件功能正常
- 发起一条注册任务，确认注册流程能正确读取所选邮箱服务并继续后续绑定流程
- 打开 `/sub2api-monitor` 运行一次检查，确认执行状态提示、错误提示和最新报告刷新正常
- 如使用 Sub2API OAuth 绑定，确认后端接口可正常执行并返回结果

### 备注

- 本次未纳入运行时文件 `codex-pool-manager/codex-pool-manager/hotmail_accounts_runtime.txt`
- `reports/` 目录属于运行产物，未随本次发布提交

---

## 2026-04-06

- 发布分支：`release`
- 开发来源：`custom/dev`
- 发布提交：以本次 `release` 分支最新 HEAD 为准

### 本次内容

- 新增 Sub2API 监控台页面，支持查看配置状态、运行检测并展示最新报告
- 新增 Sub2API 监控后端接口与报告落盘能力，支持分页拉取账号并执行远端 test
- 将 Sub2API `429 / usage_limit_reached` 归类为 `quota_exhausted`，前端单独展示“配额耗尽”指标
- 修复 `start_backend.ps1` 在当前 Windows PowerShell 环境下的启动兼容性问题，保留停止旧进程与 conda 环境解析流程

### 部署后重点检查

- 打开 `/sub2api-monitor`，确认页面可正常加载并显示最新报告
- 运行一次 Sub2API 检查，确认报告里的 `counts.quota_exhausted` 正常返回
- 执行 `GET /api/sub2api-monitor/status`，确认 API 正常返回配置与最新报告
- Docker 部署时确认容器内 `APP_CONDA_ENV=docker` 生效，避免误判本地 conda 环境

### 备注

- `reports/` 属于运行产物，不建议直接纳入发布审核结论；服务器按需保留历史报告
- Docker 部署不依赖 `start_backend.ps1`，容器内直接通过 `docker/entrypoint.sh` 启动应用

---

## 2026-04-04

- 发布分支：`release`
- 开发来源：`custom/dev`
- 发布提交：`1fedb55`

### 本次内容

- 修复 Codex 注册链路中的代理透传问题
- 恢复并统一 Codex 注册后续 OAuth / CPA 绑定流程
- 改进 Codex 注册与绑定阶段的实时日志输出与结构化展示
- 修复 Windows `gbk` 环境下日志打印导致的编码问题
- Hotmail 账号列表增加分页，默认每页 10 条
- 设置页前端重新构建到 `static/`，继续使用后端单端口托管模式

### 部署后重点检查

- 设置页 Hotmail 账号列表是否按每页 10 条显示
- Codex 注册任务是否继续输出实时结构化日志
- CloudMail / Hotmail 的 Codex 流程是否都能进入绑定阶段
- 后端单端口页面是否正常加载最新前端静态资源

### 备注

- 本次没有把运行时文件 `codex-pool-manager/codex-pool-manager/pool_config.cloudmail.runtime.yaml` 带入发布
- 本地运行时目录 `hotmail_account/`、`reports/` 未纳入发布内容

---

## 后续更新模板

复制下面这段追加到最上方：

```md
## YYYY-MM-DD

- 发布分支：`release`
- 开发来源：`custom/dev`
- 发布提交：`<commit>`

### 本次内容

- 改动 1
- 改动 2
- 改动 3

### 部署后重点检查

- 检查项 1
- 检查项 2

### 备注

- 如有未纳入发布的运行时文件，在这里说明
```
