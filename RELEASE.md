# Release 说明

这个文件用于记录 `release` 分支每次准备部署时包含的内容。

使用规则：

1. 每次准备把 `custom/dev` 合并到 `release` 前，先更新本文件。
2. 记录本次发布的日期、分支、提交、主要改动、部署后需要关注的点。
3. 已发布的记录保留在下面，新的发布追加到最上方。

---

## 2026-04-06

- 发布分支：`release`
- 开发来源：`custom/dev`
- 发布提交：`<pending>`

### 本次内容

- 新增 Sub2API 监控台页面，支持查看配置状态、运行检测并展示最新报告
- 新增 Sub2API 监控后端接口与报告落盘能力，支持分页拉取账号并执行远端 test
- 将 Sub2API `429 / usage_limit_reached` 归类为 `quota_exhausted`，前端单独展示“配额耗尽”指标
- 修复 `start_backend.ps1` 在当前 Windows PowerShell 环境下的启动兼容性问题，保留停止旧进程与 conda 环境解析流程

### 部署后重点检查

- 打开 `/sub2api-monitor`，确认页面可正常加载并显示最新报告
- 运行一次 Sub2API 检查，确认报告里的 `counts.quota_exhausted` 正常返回
- 执行 `GET /api/sub2api-monitor/status`，确认 API 正常返回配置与最新报告
- 在服务器环境确认 `conda` 可用后再执行 `./start_backend.ps1`，或按部署文档直接用目标 Python 启动 `main.py`

### 备注

- `reports/` 属于运行产物，不建议直接纳入发布审核结论；服务器按需保留历史报告
- 如果服务器没有初始化 `conda` shell，请优先使用已准备好的 Python 环境直接启动后端

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
