# Codex Pool Manager

OpenAI Codex 账号池自动管理工具。自动注册 OpenAI 账号、完成 OAuth 登录、将 token 回填到 CLIProxyAPI。

## 架构

```
注册 (HTTP + Playwright Sentinel)
  ↓
OAuth 登录 (Playwright Firefox + Stealth)
  ↓
Token 上传到 CLIProxyAPI
  ↓
号池监控 (可用号不足时自动补充)
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `codex_reg_and_login.py` | 主脚本：注册 + OAuth 登录一条龙 |
| `codex_oauth_login.py` | 纯 OAuth 登录脚本（已有账号用） |
| `sentinel_browser.py` | Playwright 获取 Sentinel Token 模块 |
| `http_register.py` | 纯 HTTP 注册脚本（独立使用） |
| `clean_auth_files.py` | 清理 CLIProxyAPI 失效认证文件 |
| `pool_config.yaml` | 配置文件 |
| `Dockerfile.oauth` | Docker 镜像 |
| `docker-compose.yml` | Docker 编排 |
| `entrypoint.sh` | 容器启动脚本（WARP 初始化） |

## 快速开始

### 1. 配置

编辑 `pool_config.yaml`，填入你的：
- CLIProxyAPI 地址和管理密钥
- 邮箱域名列表
- Inbucket 邮件服务地址
- （可选）5SIM 接码 API Key

### 2. Docker 部署

```bash
mkdir -p data warp-oauth-data
docker compose build
docker compose up -d
```

### 3. 运行

```bash
# 单次注册+登录
docker exec -it oauth_worker python codex_reg_and_login.py --loop --count 1

# 循环 10 次
docker exec -it oauth_worker python codex_reg_and_login.py --loop --count 10

# 号池监控模式（默认，可用号不足自动补充）
docker exec -it oauth_worker python codex_reg_and_login.py

# 纯 OAuth 登录（已有账号）
docker exec -it oauth_worker python codex_oauth_login.py \
  --accounts /app/data/accounts.txt \
  --cpa-url http://your-server:8317 \
  --cpa-key your-key \
  --mail-api http://your-mail:9000

# 纯 HTTP 注册（不含 OAuth）
docker exec -it oauth_worker python http_register.py --count 5 --workers 3

# 清理失效认证文件
docker exec -it oauth_worker python clean_auth_files.py \
  --url http://your-server:8317 --key your-key
```

### 4. 本地开发

```bash
pip install curl_cffi playwright requests playwright-stealth pyyaml
playwright install firefox chromium

# 测试 Sentinel Token 获取
python sentinel_browser.py

# 测试注册
python http_register.py --count 1 --no-headless

# 测试注册+登录
python codex_reg_and_login.py --loop --count 1
```

## 配置说明

### pool_config.yaml

```yaml
cliproxy:
  url: "http://your-server:8317"   # CLIProxyAPI 地址
  key: "your-key"                   # 管理密钥

pool:
  min: 5        # 可用号低于此值时补充
  target: 10    # 补充到此数量

workers: 3      # 并发线程数

email_domains:  # 邮箱域名（* 替换为随机子域名）
  - "*.mail.example.com"

mail_api: "http://your-inbucket:9000"  # 如果自建可以自行配置

mail_api: "http://mail.nas6.eu.org" #如果用我的可以用这个

****************************************************
注意：如果希望用我的域名服务，可以把你的*.xxxx.com mx 指向：mail.nas6.eu.org
****************************************************

fivesim:        # 5SIM 接码（可选）
  api_key: ""   # 留空=遇到手机验证跳过
  max_price: 50 # 最高单价（分）
```

## 注册流程

1. **HTTP**: 从 chatgpt.com 获取 CSRF + session
2. **HTTP**: 通过 chatgpt.com/api/auth/signin/openai 发起注册
3. **Playwright**: 打开 Sentinel frame，调用 SentinelSDK.token() 获取真实 token
4. **HTTP**: 提交邮箱 → 设置密码 → 发送验证码 → 验证 OTP → 创建账户
5. **Playwright**: Firefox + Stealth 完成 Codex OAuth 登录
6. **HTTP**: 用 code 换 token，上传到 CLIProxyAPI

## 依赖

- Python 3.9+
- curl_cffi
- playwright + playwright-stealth
- requests, pyyaml
- Firefox + Chromium (Playwright)
- Docker (生产部署)
- Cloudflare WARP (Docker 内置，用于 IP 轮换)

## 注意事项

- 新注册账号大概率要求手机验证（add-phone），配置 5SIM 可自动接码
- WARP 出口 IP 由服务器位置决定，无法选择国家
- 建议单线程或低并发（3-5），避免触发 OpenAI 风控
- 昨天一天可以跑1000多个号出来，今天感觉凉凉