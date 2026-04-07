## 邮箱服务改造计划

### Context
目标是在当前项目里新增一个独立的“邮箱服务”一级页面，和“平台管理”同级，用于统一管理 Microsoft/Hotmail 邮箱服务、账号导入、查邮件、以及后续预留的刷新令牌功能。

本轮新增收口目标：
- 支持 Hotmail 账号通过 `txt` 文件导入，也支持直接粘贴多行文本导入
- 新导入的微软邮箱账号按导入时间倒序展示，最新的排最前面
- “邮箱服务”页调整为二级分类，至少区分“微软邮箱”和“邮箱服务管理”
- 原“全局配置 -> 邮箱服务”里的 provider 管理能力迁移到新的“邮箱服务”页面内

核心验证点：
- 导入的 `email + client_id + refresh_token` 是否可以直接用于微软侧查信
- 页面是否能展示 Inbox + Junk 合并后的邮件列表
- 邮件是否按收件时间倒序排序
- 现有注册流程里的 Hotmail OTP 查信能力是否不回归

---

## 今日完成

### 已完成功能
- [x] 新增一级菜单“邮箱服务”
- [x] 新增 `/mailboxes` 路由
- [x] 新建前端页面 `frontend/src/pages/Mailboxes.tsx`
- [x] 实现邮箱服务实例列表
- [x] 实现邮箱服务新增 / 编辑 / 启停 / 删除
- [x] 实现 Hotmail 账号列表展示
- [x] 实现 Hotmail 批量导入接口与前端导入弹窗
- [x] 实现邮箱名筛选
- [x] 增加“刷新令牌（预留）”按钮占位
- [x] 增加“查询邮件”弹窗
- [x] 支持查看单封邮件内容
- [x] 新增后端接口 `GET /api/mailboxes/{mailbox_id}/hotmail/accounts/{account_id}/mails`
- [x] Hotmail 查信逻辑支持同时查询 Inbox 与 Junk
- [x] 合并邮件结果并按收件时间倒序排序
- [x] 保留 `latest-mail` 兼容逻辑
- [x] `core/base_mailbox.py` 已复用统一 Hotmail 查信逻辑，避免页面查信和 OTP 轮询走两套实现
- [x] 邮箱服务页面新增二级分类：“微软邮箱” / “邮箱服务管理”
- [x] 已把原“全局配置 -> 邮箱服务”里的 provider 管理能力迁移到 `Mailboxes.tsx`
- [x] Hotmail 导入弹窗支持 TXT 读取 + 手动粘贴双入口
- [x] Hotmail 账号列表已改为最新导入优先展示
- [x] 邮箱服务页面已收口为 Hotmail-only 文案与交互
- [x] 后端 create / update 已限制仅允许 `hotmail` provider

### 今日关键实现结论
- [x] 已确认当前仓库里**没有**现成的 `Microsoft-Email-Manager` 本地实现可直接复制
- [x] 已把 `https://github.com/Maishan-Inc/Microsoft-Email-Manager` clone 到本地临时目录：
  - `C:\Users\zhouyuan\AppData\Local\Temp\microsoft-email-manager`
- [x] 已定位对方项目关键实现都在：
  - `C:\Users\zhouyuan\AppData\Local\Temp\microsoft-email-manager\main.py`
- [x] 已确认对方项目的关键兼容点：
  - Graph token refresh 会尝试多个 token endpoint
  - Graph token refresh 会尝试多个 scope 组合
  - 其中 `https://graph.microsoft.com/.default` 是关键兼容项之一
  - `folder=all` 本质是 `inbox + junk` 并行查询后合并排序
  - message_id 采用 `graph:{folder}:{id}` 格式
- [x] 已把上述关键兼容逻辑移植到当前项目 `services/hotmail_accounts.py`

### 今日已验证结果
- [x] Jennifer 样本账号已在当前项目本地 service 层验证通过
- [x] 本地逻辑已能直接查到该账号邮件
- [x] 本地已成功查到 4 封邮件
- [x] 邮件结果按时间倒序正常
- [x] 当前关键兼容差异已定位并修复：本地原 Graph 刷新策略过窄，现已改为多 endpoint + 多 scope 尝试
- [x] 运行中的本地后端已确认加载 `/api/mailboxes/{mailbox_id}/hotmail/accounts/{account_id}/mails` 新路由
- [x] Jennifer 样本账号已在运行态接口 `GET /api/mailboxes/3/hotmail/accounts/35/mails` 验证通过
- [x] 返回结果已确认来自真实 Graph 查信链路，包含规范化后的 `message_id` / `folder` / `received_at` 等字段
- [x] 前端 `Mailboxes.tsx` 已确认实际调用 `/mails` 路由，不走旧 `latest-mail`
- [x] 前端生产构建已通过（使用本地二进制 `./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build`）
- [x] `Settings.tsx` 旧“邮箱服务管理”面板已移除，provider 管理不再在“全局配置”里重复出现
- [x] 已确认后端需从仓库根目录启动，否则会误读 `frontend/account_manager.db` 导致 `/api/mailboxes` 返回空列表
- [x] 已从根目录重启本地后端，并确认运行态 `POST /api/mailboxes` 会拒绝非 `hotmail` provider
- [x] 已从运行态确认 `/api/mailboxes/3/hotmail/accounts` 仍按最新导入优先返回账号
- [x] 已从运行态再次确认 Jennifer 样本 `/mails` 返回 Junk + Inbox 合并结果，最新测试邮件位于顶部
- [-] `npm run build` 在当前 Windows shell 下仍有 `"node" not recognized` 环境问题，但不是仓库代码问题

---

## 当前状态

### Phase 1: 页面与导航
- [x] 在侧边栏新增一级菜单“邮箱服务”
- [x] 新增 `/mailboxes` 路由
- [x] 新建 `frontend/src/pages/Mailboxes.tsx` 页面骨架
- [x] 实现邮箱服务实例列表
- [x] 实现“查看邮箱账号列表”的交互入口
- [x] 邮箱服务页调整为二级分类结构

### Phase 2: 服务实例管理
- [x] 接通 `GET /api/mailboxes` 服务实例列表
- [x] 接通 `POST /api/mailboxes` 新增服务实例
- [x] 接通 `PATCH /api/mailboxes/{id}` 编辑服务实例
- [x] 接通 `PATCH /api/mailboxes/{id}/toggle` 启停服务实例
- [x] 接通 `DELETE /api/mailboxes/{id}` 删除服务实例
- [x] 原全局配置中的 provider 管理 UI 已迁移到邮箱服务页内

### Phase 3: 邮箱账号列表与导入
- [x] 接通 `GET /api/mailboxes/{mailbox_id}/hotmail/accounts`
- [x] 页面展示邮箱账号列表
- [x] 增加“导入邮箱”弹窗
- [x] 接通 `POST /api/mailboxes/{mailbox_id}/hotmail/import`
- [x] 导入结果展示 `created / updated / skipped`
- [x] 支持 TXT 导入
- [x] 支持粘贴文本导入
- [x] 新导入账号优先展示

### Phase 4: 查邮件能力
- [x] 明确并统一项目内 Hotmail/Microsoft 查信入口
- [x] 让查信逻辑同时查询 Inbox 与 Junk
- [x] 合并邮件结果并按收件时间倒序排序
- [x] 增加“查询邮件”后端接口
- [x] 前端点击“查邮件”后弹出邮件列表弹窗
- [x] 邮件列表展示主题 / 发件人 / 文件夹 / 收件时间 / 摘要
- [x] 支持查看单封邮件完整内容

### Phase 5: 占位功能
- [x] 在邮箱账号列表顶部增加“按邮箱名筛选”
- [x] 增加“刷新令牌（预留）”按钮
- [x] 第一版按钮仅提示“暂未接入”

### Phase 6: 验证与联调
- [x] 导入真实 Microsoft/Hotmail 账号样本
- [x] 在 service 层验证能拿到 Inbox/Junk 合并后的邮件结果
- [x] 验证按收件时间排序正确
- [x] 已补 Hotmail message_id 稳定性修复，避免 Graph / Relay 切换时旧邮件被误判为新邮件
- [x] 已新增回归测试 `tests/test_hotmail_accounts.py`
- [x] 已通过 OTP / task control 回归测试
- [x] 已确认运行中的本地后端加载了新 `/mails` 路由
- [x] 已确认前端页面实际调用 `/mails` 接口，不走旧 `latest-mail`
- [x] 已完成前端生产构建并由当前 FastAPI 进程正常提供静态资源
- [x] 已从运行态确认 Hotmail-only API 限制生效（非 `hotmail` provider 返回 400）
- [x] 已确认本地后端必须从仓库根目录启动，避免误用 `frontend/account_manager.db`
- [-] 验证页面中能正常打开邮件弹窗并显示真实数据
- [-] 验证现有注册流程中 mailbox service 选择不回归
- [x] 已触发 Jennifer 新测试邮件，端到端验证已确认新邮件成功到件，且出现在 Inbox/Junk 合并列表顶部（当前在 Junk）

---

## 关键文件
- `frontend/src/App.tsx`
- `frontend/src/pages/Mailboxes.tsx`
- `frontend/src/pages/Settings.tsx`
- `api/mailboxes.py`
- `services/hotmail_accounts.py`
- `core/base_mailbox.py`
