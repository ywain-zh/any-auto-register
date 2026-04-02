# Branch And Remote Workflow

## Remote Layout

- `upstream`
  - 对方原仓库
  - URL: `https://github.com/zc-zhangchen/any-auto-register.git`
- `origin`
  - 你自己的 fork 仓库
  - URL: `https://github.com/ywain-zh/any-auto-register.git`

当前原则：

- `upstream` 只作为上游同步来源
- `origin` 只作为你自己的代码托管和部署来源

## Branch Layout

当前本地分支：

- `main`
  - 目标职责：尽量保持接近 `upstream/main`
  - 当前状态：`5becc82`
  - 当前跟踪：`upstream/main`
- `custom/dev`
  - 目标职责：你自己的开发分支
  - 所有本地定制、修复、复现都在这里做
  - 当前状态：基于当前干净 `main`
- `release`
  - 目标职责：准备部署的分支
  - 建议只从 `custom/dev` 合并测试通过的内容
  - 当前仍是旧历史状态，后面可重新整理
- `backup/current-mess`
  - 目标职责：保留之前混乱状态的完整备份
  - 不参与日常开发

## Backup State

为了避免之前的本地修改丢失，已经保留了两层备份：

- 备份分支：`backup/current-mess`
- stash 备份：
  - `stash@{0}`: `backup-current-mess-before-reset`
  - `stash@{1}`: `opencode-pre-merge-2026-04-02`

注意：

- 不要随便删除 `backup/current-mess` 和上述 stash
- 只有确认旧内容完全不需要时再清理

## Current Working State

当前你正在使用的开发分支是：

- `custom/dev`

当前未提交改动：

- `frontend/vite.config.ts`
  - 前端开发代理已改回 `7000`
- `services/turnstile_solver/api_solver.py`
  - 修复 Windows `gbk` 环境下 solver 启动时的编码崩溃

这两处改动已经验证有效，但当前还没有 commit。

## Recommended Daily Workflow

### 1. 日常开发

始终在 `custom/dev` 上开发：

```bash
git checkout custom/dev
```

不要直接在 `main` 上改代码。

### 2. 同步上游

先更新 `main`：

```bash
git checkout main
git fetch upstream
git merge upstream/main
```

如果网络需要代理，本地临时设置代理后再执行 fetch/merge。

### 3. 把上游同步到开发分支

```bash
git checkout custom/dev
git merge main
```

如果有冲突：

- 先保留上游主线结构
- 再把你自己的定制功能一点点补回去
- 不要一次性把旧 stash 全量覆盖回来

### 4. 进入发布分支

当 `custom/dev` 验证通过后：

```bash
git checkout release
git merge custom/dev
```

建议 `release` 只承载“准备部署”的稳定内容。

## Recommended Deployment Flow

建议服务器最终部署 `release` 分支，而不是 `main`。

推荐流程：

1. 本地开发：`custom/dev`
2. 本地验证通过后合并：`release`
3. 推送到你的 fork：`origin/release`
4. 服务器只拉 `release`

## Docker Deployment

推荐服务器直接通过 `docker compose` 部署 `release` 分支。

### 1. 推送发布分支

本地完成验证后：

```bash
git checkout custom/dev
git push -u origin custom/dev

git checkout release
git push -u origin release
```

### 2. 服务器首次部署

```bash
git clone https://github.com/ywain-zh/any-auto-register.git
cd any-auto-register
git checkout release
mkdir -p data _ext_targets external_logs
docker compose up -d --build
```

### 3. 服务器后续更新

```bash
cd any-auto-register
git fetch origin
git checkout release
git pull origin release
docker compose up -d --build
```

### 4. 默认端口

- 主服务：`8000`
- Solver：`8889`（默认仅绑定服务器本机）
- CLIProxyAPI：`8317`
- grok2api：`8011`

### 5. 数据持久化目录

`docker-compose.yml` 默认会把这些目录挂载到宿主机：

- `./data`
- `./_ext_targets`
- `./external_logs`

其中最重要的是 `./data`，它会保存：

- `account_manager.db`
- solver 日志
- SMSToMe 相关数据

### 6. 部署后访问

```text
http://服务器IP:8000
```

如果前面接 Nginx / Caddy，则把外部域名反向代理到容器的 `8000`。

### 7. 首次部署后需要检查的配置

进入页面后，优先确认这些全局配置：

- `YesCaptcha`
- `Cloud Mail`
- `CPA API`
- 默认执行器 / 默认验证码服务

如果服务器也要直接使用当前 Cloud Mail 实例，确认 `邮箱服务` 列表里的实例配置已经存在。

## Push Strategy

### 推送开发分支

```bash
git push -u origin custom/dev
```

### 推送发布分支

```bash
git push -u origin release
```

### 如需备份当前混乱状态到远端

```bash
git push -u origin backup/current-mess
```

默认不建议推送备份分支，除非你确实想在 GitHub 上也保留一份。

## Important Rules

- 不要直接在 `main` 上做业务开发
- 不要在没有备份时直接覆盖 `custom/dev`
- 每次要大改前，先确认当前在哪个分支
- 每次准备 pull 上游前，先确保工作区是干净的，或者先 stash/commit
- 以后所有“复现问题、修功能、做适配”，默认都在 `custom/dev`

## Current Priority

当前建议优先做的事：

1. 先把 `custom/dev` 上已验证的开发环境修复提交
2. 再继续恢复你真正需要的本地功能
3. 功能稳定后再整理 `release`
