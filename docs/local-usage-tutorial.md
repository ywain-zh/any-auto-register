# 本地使用教程

这份文档只讲当前仓库里的**真实本地流程**：依赖怎么装、项目怎么启动、后台注册任务怎么跑、以后让 Claude 帮你注册时应该走什么入口，以及哪些文件属于依赖/构建/运行产物。

## 1. 依赖整理

### 1.1 后端依赖

后端依赖定义在 `requirements.txt:1`。

核心依赖分为几类：

- Web/API：`fastapi`、`uvicorn`、`quart`
- 数据与模型：`sqlmodel`、`pydantic`
- 网络请求：`curl_cffi`、`requests`、`httpx`、`pysocks`
- 浏览器自动化：`playwright`、`patchright`、`camoufox`
- 认证/编码：`jwcrypto`、`cbor2`
- 其他辅助：`aiofiles`、`rich`、`pyinstaller`、`selectolax`

建议环境：

- Python 3.12+
- Conda 环境名默认是 `any-auto-register`

安装：

```bash
conda create -n any-auto-register python=3.12 -y
conda activate any-auto-register
pip install -r requirements.txt
python -m playwright install chromium
python -m camoufox fetch
```

说明：

- `playwright` / `camoufox` 不是只靠 `pip install` 就够，还要执行额外安装命令。
- `main.py:23-54` 会在启动时检查 conda 环境；如果不是期望环境，Solver 可能起不来。

### 1.2 前端依赖

前端依赖定义在 `frontend/package.json:1`。

运行依赖：

- `react`
- `react-dom`
- `react-router-dom`
- `antd`
- `@ant-design/icons`

开发/构建依赖：

- `vite`
- `typescript`
- `eslint`
- `@vitejs/plugin-react`
- `typescript-eslint`

安装：

```bash
cd frontend
npm install
npm run build
cd ..
```

说明：

- `npm run build` 会把前端静态资源构建到 `static/`，后端启动后直接托管。
- 如果只是调试前端，也可以不 build，直接跑 Vite 开发模式。

### 1.3 Electron 依赖

Electron 依赖定义在 `electron/package.json:1`。

主要用于桌面壳和打包：

- `electron`
- `electron-builder`

常用命令：

```bash
cd electron
npm install
npm run dev
```

说明：

- Electron 不是主注册链路的必需部分。
- 开发模式下仍然需要先启动 Python 后端。

### 1.4 Docker 依赖边界

Docker 运行定义在 `docker-compose.yml:1-32`。

容器里已经覆盖：

- 后端运行环境
- 本地 Solver
- 基础端口与运行目录挂载

默认关键端口：

- `8000`：主应用
- `8889`：本地 Solver
- `8317`：CLIProxyAPI 端口映射（如果启用）
- `8011`：grok2api 端口映射（如果启用）

说明：

- Docker 更适合主应用 + Solver。
- 某些依赖宿主机环境的插件，仍然更适合本机运行。

## 2. 启动项目

### 2.1 Windows 推荐启动方式

优先使用仓库自带脚本：

- `start_backend.ps1:1-42`
- `start_backend.bat:1-40`

PowerShell：

```powershell
.\start_backend.ps1
```

CMD：

```bat
start_backend.bat
```

这两个脚本会：

- 切到仓库根目录
- 解析 `any-auto-register` conda 环境
- 启动前先清理旧的后端 / Solver 进程
- 最后运行 `main.py`

注意：

- `start_backend.ps1` 已兼容当前 Windows PowerShell 写法，但前提仍是当前终端能识别 `conda`
- 如果 PowerShell 执行时提示 `conda command not found`，先执行 `conda init powershell` 并重新打开终端
- 如果服务器或当前终端本来就不使用 conda，直接用目标 Python 执行 `main.py` 更稳妥

### 2.2 手动启动

只有在你已经确认当前 Python 就是正确 conda 环境时，再手动执行：

```bash
conda activate any-auto-register
python main.py
```

### 2.3 启动后的行为

`main.py:57-159` 启动时会自动：

- 初始化数据库
- 加载平台插件
- 启动 scheduler
- 启动本地 Turnstile Solver
- 如果 `static/` 存在，则直接托管前端构建结果

默认访问地址：

- 主站：`http://localhost:8000`
- Solver 状态：`http://localhost:8000/api/solver/status`
- Solver 服务：`http://localhost:8889`

### 2.4 前端开发模式

终端 1：

```powershell
.\start_backend.ps1
```

终端 2：

```bash
cd frontend
npm run dev
```

访问：

- `http://localhost:5173`

此时 `/api` 会代理到本地 `8000` 后端。

## 3. 注册前要确认的配置

后端配置键在 `api/config.py:6-82`，前端设置页字段在 `frontend/src/pages/Settings.tsx:20-190`。

重点只看下面几组：

### 3.1 邮箱服务

在设置页先确认：

- `mail_provider`
- 对应邮箱服务的 API / 账号 / 域名配置

如果是 Hotmail：

- 先去邮箱服务实例里确认账号池已导入
- 后面批量注册会直接消费其中 `unregistered` 的账号

### 3.2 默认注册方式

重点配置：

- `default_executor`
- `default_proxy`
- `default_captcha_solver`
- `yescaptcha_key`

如果本地 Solver 要用：

- 确认后端已启动
- 确认 `http://localhost:8000/api/solver/status` 返回 `{"running":true}`

### 3.3 ChatGPT / Codex / 下游同步

在设置页 `ChatGPT` 分组里重点确认：

- `cpa_api_url`
- `cpa_api_key`
- `sub2api_api_url`
- `sub2api_api_key`
- `codex_bind_target`
- `codex_proxy_url`
- `codex_proxy_key`
- `codex_proxy_upload_type`

如果你现在走的是 Codex + Sub2API：

- `codex_bind_target` 设为 `sub2api`
- `sub2api_api_url` / `sub2api_api_key` 必须可用

## 4. 后台注册任务怎么进行

### 4.1 任务入口

注册入口在 `api/tasks.py:28-98` 和 `api/tasks.py:333-418`。

前端注册页在 `frontend/src/pages/RegisterTaskPage.tsx:109-205`，点击提交后会调用：

- `POST /api/tasks/register`

请求体核心字段：

- `platform`
- `count`
- `proxy`
- `executor_type`
- `captcha_solver`
- `extra`

其中 `extra` 里会带上当前邮箱服务配置、验证码配置、代理、SMS 配置等。

### 4.2 后端如何接任务

后端收到请求后会：

1. 用 `_prepare_register_request(...)` 整理参数
2. 根据 `mailbox_service_id` 注入邮箱服务配置
3. 创建任务记录
4. 启动后台线程执行 `_run_register(...)`

也就是说，前端提交后不是同步等待浏览器全跑完，而是交给后台任务系统执行。

### 4.3 Codex / Hotmail 的特殊链路

Codex 原脚本桥接在 `api/tasks.py:122-318`。

这条链路会：

1. 读取邮箱服务与绑定目标配置
2. 从 Hotmail 账号池里取一个 `unregistered` 邮箱
3. 调用原脚本完成注册
4. 把 Hotmail 状态先更新成 `pending_bind`
5. 再执行 OAuth 绑定（CPA 或 Sub2API）
6. 成功后把 Hotmail 状态改成 `success`

如果绑定失败：

- 任务会失败
- Hotmail 侧会保留失败信息，便于后续排查

## 5. 任务状态、日志和历史怎么看

### 5.1 实时任务状态

后端接口在 `api/tasks.py`：

- `GET /api/tasks/{id}`
- `GET /api/tasks/{id}/logs/stream`
- `POST /api/tasks/{id}/skip-current`
- `POST /api/tasks/{id}/stop`

前端实时日志组件在 `frontend/src/components/TaskLogPanel.tsx:13-258`。

你能在界面里：

- 看实时日志
- 跳过当前账号
- 停止任务
- 复制全部日志

### 5.2 历史记录

前端页面在 `frontend/src/pages/TaskHistory.tsx:28-161`。

这里可以查看：

- 时间
- 平台
- 邮箱
- 成功/失败
- 错误信息

## 6. 以后让 Claude 帮你注册，应该怎么走

以后不要把“临时脚本”当成默认入口，优先让 Claude 复用现有系统。

推荐顺序：

1. 确认后端已经启动
2. 让 Claude 读取当前配置或检查设置页相关配置
3. 让 Claude 查询邮箱池状态
4. 让 Claude 通过现有任务入口发起后台任务
5. 让 Claude 持续读取任务状态、日志、历史记录或报告文件

### 6.1 Hotmail 批量注册的实际顺序

如果是 Hotmail 批量跑 Codex / Sub2API，推荐让 Claude 按这个顺序做：

1. 查询指定邮箱服务实例下还有多少 `unregistered`
2. 确认 `codex_bind_target=sub2api`
3. 发起 `POST /api/tasks/register`
4. 轮询 `GET /api/tasks/{id}`
5. 读取日志流确认每个账号的注册 / 绑定 / 检测结果
6. 如有需要，把结果写到 `reports/` 形成报告

注意：

- `reports/*.md` / `reports/*.json` 是结果产物，不是主流程入口。
- 一次性的 runner 脚本只能算排障手段，不建议当成长期标准操作。

## 7. 常见排查点

### 7.1 后端能起，但 Solver 不工作

先检查：

```bash
curl http://localhost:8000/api/solver/status
```

再确认当前 Python 是否来自正确 conda 环境。

### 7.2 端口占用

先执行：

```powershell
.\stop_backend.ps1
```

再重启：

```powershell
.\start_backend.ps1
```

### 7.3 Hotmail 跑不起来

先确认：

- 邮箱服务实例存在且启用
- 账号池里还有 `unregistered`
- `sub2api_api_url` / `sub2api_api_key` 已配置
- 如果用了 Hotmail 验证码，收件箱和 Junk 都要检查

### 7.4 OpenAI / OAuth 中途卡住

常见原因：

- 手机号验证拦截
- 代理不可用
- Sub2API / CPA 配置缺失
- 浏览器执行器和验证码服务不匹配

## 8. 哪些文件是依赖、构建或运行产物

下面这些通常不是源码：

### 8.1 依赖目录

- `.venv/`
- `frontend/node_modules/`
- `electron/node_modules/`

说明：

- 这些通常不提交到 git。
- 但 `.venv/` 是否删除要看你本机是否还在使用，**不要为了清理顺手删掉自己的环境**。

### 8.2 构建产物

- `frontend/dist/`
- `electron/dist/`
- `static/`

说明：

- `static/` 是前端构建后给后端托管的输出。
- 如果当前正在本地直接访问 `8000` 的前端页面，`static/` 往往就是正在使用的产物，不要盲删。

### 8.3 运行产物

- `__pycache__/`
- `*.pyc`
- `*.log`
- 调试截图，如 `debug_*_exception.png`
- 临时数据库或缓存文件（需逐个确认用途）

### 8.4 结果与证据文件

- `reports/*.md`
- `reports/*.json`

说明：

- 这些是运行结果与排查证据。
- 如果你后面还要回看注册/绑定/检测结果，不建议直接删。

## 9. 推荐的清理原则

只优先清理下面这类高置信度产物：

- `__pycache__/`
- `*.pyc`
- 明确无用的 `debug_*_exception.png`
- 明确无用的日志文件
- 可重建的 `frontend/dist/`、`electron/dist/`

谨慎处理：

- `.venv/`
- `static/`
- `account_manager.db`
- `reports/`
- 任意运行时脚本或配置文件

如果不确定，先保留，再确认用途。
