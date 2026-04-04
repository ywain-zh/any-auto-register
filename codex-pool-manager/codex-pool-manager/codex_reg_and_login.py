#!/usr/bin/env python3
"""
Codex 注册 + OAuth 登录一条龙
==============================
1. curl_cffi 注册 OpenAI 账号 (邮箱/密码/验证码/创建账户)
2. Playwright 浏览器完成 Codex OAuth 登录
3. 将 token 回填到 CLIProxyAPI

依赖:
  pip install curl_cffi playwright requests playwright-stealth
  playwright install --with-deps firefox

使用:
  # 单次注册+登录
  python codex_reg_and_login.py --cpa-url http://api.xxx.com --cpa-key xxx

  # 循环模式 (持续注册)
  python codex_reg_and_login.py --loop --count 10 --cpa-url http://api.xxx.com --cpa-key xxx

  # 指定邮箱域名和 Worker
  python codex_reg_and_login.py --loop --count 5 \
    --email-domain example.org \
    --cf-worker-url https://cloudmail.xxx.workers.dev \
    --cf-api-token xxx \
    --mail-api http://your-inbucket-server:9000 \
    --cpa-url http://api.xxx.com --cpa-key xxx
"""

import argparse, base64, hashlib, json, os, random, re, secrets, string
import sys, time, urllib.parse
from typing import Optional
from datetime import datetime

import yaml
from curl_cffi import requests as cffi_requests
import requests as http_requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from mail_api_adapter import (
    create_mailbox_address,
    fetch_email_code,
    normalize_mail_config,
)


# ==========================================
# 配置加载
# ==========================================
def load_config(path="pool_config.yaml"):
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


DEFAULTS = {
    "email_domain": "example.org",
    "cf_worker_url": "https://your-cf-worker.workers.dev",
    "cf_api_token": "your-cf-api-token",
    "mail_api": "http://your-inbucket-server:9000",
    "cpa_url": "http://your-cpa-server:8317",
    "cpa_key": "your-management-key",
}


# ==========================================
# Sentinel 指纹构造
# ==========================================
def build_sentinel_p(
    did,
    ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
):
    """构造 sentinel p 字段 (浏览器指纹)"""
    now = time.time() * 1000
    react_id = "__reactContainer$" + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=11)
    )
    fingerprint = [
        random.randint(1000, 9999),
        time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)"),
        4294967296,
        random.randint(15, 35),
        ua,
        "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js",
        None,
        "en-US",
        "en-US",
        3,
        "webkitGetUserMedia\u2212function webkitGetUserMedia() { [native code] }",
        react_id,
        "clearTimeout",
        random.randint(3000, 30000),
        did,
        "",
        11,
        now,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ]
    encoded = base64.b64encode(
        json.dumps(fingerprint, ensure_ascii=False, separators=(",", ":")).encode()
    ).decode()
    return f"gAAAAACW{encoded}~S"


# ==========================================
# 邮箱生成 (随机域名 + 随机用户名)
# ==========================================
def generate_email(email_domains):
    """
    从域名列表随机选一个，* 替换为随机字符串作为子域名。
    *.icoa.example.cc -> user@a7kx2m.icoa.example.cc
    """
    pattern = random.choice(email_domains)
    if "*" in pattern:
        sub = "".join(
            random.choices(
                string.ascii_lowercase + string.digits, k=random.randint(5, 8)
            )
        )
        domain = pattern.replace("*", sub, 1)
    else:
        domain = pattern
    # 去掉开头可能的点
    domain = domain.lstrip(".")
    local = "".join(
        random.choices(string.ascii_lowercase, k=random.randint(4, 8))
    ) + "".join(random.choices(string.digits, k=random.randint(2, 4)))
    return f"{local}@{domain}"


def generate_mailbox_email(email_domains, mail_cfg):
    return create_mailbox_address(mail_cfg, email_domains)


def _resolve_runtime_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        return os.path.join(os.getcwd(), "data")
    if os.name == "nt" and raw.startswith("/app/"):
        suffix = raw[len("/app/") :].replace("/", os.sep)
        return os.path.join(os.getcwd(), suffix)
    return raw


# ==========================================
# 验证码获取 (Cloudflare Worker API)
# ==========================================
def get_oai_code_cf(cf_worker_url, cf_token, email, proxies=None):
    """从 Cloudflare Worker 获取验证码"""
    url = f"{cf_worker_url}/api/messages?to={email}"
    headers = {"Authorization": f"Bearer {cf_token}"}
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen = set()
    print(f"  [邮件-CF] 等待验证码", end="", flush=True)
    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = cffi_requests.get(
                url, headers=headers, proxies=proxies, timeout=10, impersonate="chrome"
            )
            if resp.status_code == 200:
                for msg in resp.json():
                    mid = msg.get("id", "")
                    if mid in seen:
                        continue
                    seen.add(mid)
                    content = f"{msg.get('subject', '')}\n{msg.get('text_body', '')}\n{msg.get('html_body', '')}"
                    sender = msg.get("mail_from", "")
                    if (
                        "openai" not in sender.lower()
                        and "openai" not in content.lower()
                    ):
                        continue
                    m = re.search(regex, content)
                    if m:
                        print(f" OK:{m.group(1)}")
                        try:
                            cffi_requests.delete(
                                f"{cf_worker_url}/api/messages?to={email}",
                                headers=headers,
                                proxies=proxies,
                                timeout=10,
                                impersonate="chrome",
                            )
                        except:
                            pass
                        return m.group(1)
        except:
            pass
        time.sleep(3)
    print(" 超时")
    return ""


# ==========================================
# 验证码获取 (Inbucket API)
# ==========================================
def get_oai_code_inbucket(mail_api, email, since_ts, used_codes, timeout_secs=120):
    """兼容 Inbucket / Cloud Mail 获取验证码"""
    return (
        fetch_email_code(
            mail_api,
            email,
            since_ts,
            used_codes,
            timeout_secs=timeout_secs,
            label="[邮件]",
        )
        or ""
    )


# ==========================================
# OAuth 工具
# ==========================================
AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REDIRECT_URI = "http://localhost:1455/auth/callback"


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url(s):
    return _b64url(hashlib.sha256(s.encode("ascii")).digest())


def generate_oauth_url():
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = _sha256_b64url(verifier)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "openid email profile offline_access",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return url, state, verifier


def exchange_code_for_token(code, verifier):
    """用 authorization code 换 token"""
    import urllib.request, urllib.error

    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def decode_jwt_payload(token):
    if not token or token.count(".") < 2:
        return {}
    seg = token.split(".")[1]
    pad = "=" * ((4 - len(seg) % 4) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode((seg + pad).encode()).decode())
    except:
        return {}


def build_codex_auth_json(token_resp, email, password):
    """构建 CLIProxyAPI 兼容的 codex auth JSON"""
    claims = decode_jwt_payload(token_resp.get("id_token", ""))
    auth_claims = claims.get("https://api.openai.com/auth", {})
    now = int(time.time())
    expires_in = int(token_resp.get("expires_in", 0))
    return {
        "id_token": token_resp.get("id_token", ""),
        "access_token": token_resp.get("access_token", ""),
        "refresh_token": token_resp.get("refresh_token", ""),
        "account_id": auth_claims.get("chatgpt_account_id", ""),
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "email": claims.get("email", email),
        "type": "codex",
        "expired": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0))
        ),
        "password": password,
    }


# ==========================================
# CLIProxyAPI
# ==========================================
def cpa_get_pool_status(cpa_url, cpa_key):
    """查询号池状态: 返回 (总数, 可用数, 不可用数)"""
    r = http_requests.get(
        f"{cpa_url}/v0/management/auth-files",
        headers={"Authorization": f"Bearer {cpa_key}"},
        timeout=30,
        verify=False,
    )
    r.raise_for_status()
    files = r.json().get("files", [])
    total = len(files)
    # 只统计 codex 类型
    codex_files = [
        f
        for f in files
        if f.get("provider") == "codex" or "codex" in f.get("name", "").lower()
    ]
    if not codex_files:
        codex_files = files  # 如果没有 provider 字段，用全部
    available = sum(
        1 for f in codex_files if not f.get("unavailable") and not f.get("disabled")
    )
    unavailable = sum(1 for f in codex_files if f.get("unavailable"))
    return len(codex_files), available, unavailable


def cpa_upload_auth(cpa_url, cpa_key, auth_json):
    email = auth_json.get("email", "unknown")
    filename = f"codex-{email}.json"
    import io

    files = {
        "file": (
            filename,
            io.BytesIO(json.dumps(auth_json).encode()),
            "application/json",
        )
    }
    r = http_requests.post(
        f"{cpa_url}/v0/management/auth-files",
        headers={"Authorization": f"Bearer {cpa_key}"},
        files=files,
        data={"channel": "codex"},
        timeout=15,
        verify=False,
    )
    return r.status_code, r.text


def cpa_forward_callback(cpa_url, code, state):
    r = http_requests.get(
        f"{cpa_url}/codex/callback",
        params={"code": code, "state": state},
        timeout=15,
        verify=False,
    )
    return r.status_code


def cpa_request_codex_auth_url(cpa_url, cpa_key):
    r = http_requests.get(
        f"{cpa_url}/v0/management/codex-auth-url",
        headers={"Authorization": f"Bearer {cpa_key}"},
        timeout=30,
        verify=False,
    )
    r.raise_for_status()
    return r.json()


def cpa_check_auth_status(cpa_url, cpa_key, state):
    r = http_requests.get(
        f"{cpa_url}/v0/management/get-auth-status",
        headers={"Authorization": f"Bearer {cpa_key}"},
        params={"state": state},
        timeout=10,
        verify=False,
    )
    r.raise_for_status()
    return r.json()


# ==========================================
# 第一阶段: HTTP 注册 + Playwright Sentinel
# ==========================================
def do_register(
    email_domains, cf_worker_url, cf_token, mail_api, proxy=None, headless=True
):
    """HTTP 注册 + Playwright Sentinel 获取 token"""
    from sentinel_browser import get_sentinel_tokens
    from curl_cffi import requests as cffi_req

    email = generate_mailbox_email(email_domains, mail_api)
    password = (
        "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "aA1!"
    )
    ts = lambda: time.strftime("%H:%M:%S")
    print(f"  [{ts()}] [注册] 邮箱: {email}", flush=True)

    proxies = {"http": proxy, "https": proxy} if proxy else None
    s = cffi_req.Session(proxies=proxies, impersonate="chrome")

    try:
        # 1) 获取 session
        print(f"  [{ts()}] [注册] 获取 session...", flush=True)
        s.get("https://chatgpt.com", timeout=15)
        csrf_resp = s.get("https://chatgpt.com/api/auth/csrf", timeout=10)
        csrf_token = (
            csrf_resp.json().get("csrfToken", "")
            if csrf_resp.status_code == 200
            else ""
        )
        did = s.cookies.get("oai-did", "")

        # 2) 发起注册
        print(f"  [{ts()}] [注册] 发起注册...", flush=True)
        signin_resp = s.post(
            "https://chatgpt.com/api/auth/signin/openai",
            params={
                "prompt": "login",
                "ext-oai-did": did,
                "screen_hint": "login_or_signup",
                "login_hint": email,
            },
            data={"csrfToken": csrf_token, "callbackUrl": "/", "json": "true"},
            headers={"content-type": "application/x-www-form-urlencoded"},
            allow_redirects=True,
            timeout=30,
        )
        if signin_resp.status_code != 200:
            return (f"signin_{signin_resp.status_code}", None)
        auth_url = signin_resp.json().get("url", "")
        if auth_url:
            s.get(auth_url, timeout=15, allow_redirects=True)

        # 3) Sentinel token
        print(f"  [{ts()}] [注册] 获取 sentinel...", flush=True)
        tokens = get_sentinel_tokens(
            ["username_password_create"], proxy=proxy, headless=headless
        )
        if not tokens or not tokens.get("username_password_create"):
            return ("sentinel_fail", None)
        sentinel_header = json.dumps(tokens["username_password_create"])

        # 4) 提交邮箱
        print(f"  [{ts()}] [注册] 提交邮箱...", flush=True)
        signup_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel_header,
                "referer": "https://auth.openai.com/create-account",
            },
            data=json.dumps(
                {"username": {"value": email, "kind": "email"}, "screen_hint": "signup"}
            ),
        )
        if signup_resp.status_code != 200:
            return (f"signup_{signup_resp.status_code}", None)
        try:
            cont = signup_resp.json().get("continue_url", "")
            if cont:
                s.get(cont, timeout=15)
        except:
            pass

        # 5) 设置密码
        print(f"  [{ts()}] [注册] 获取 register sentinel...", flush=True)
        tokens2 = get_sentinel_tokens(
            ["username_password_create"], proxy=proxy, headless=headless
        )
        sentinel2 = (
            json.dumps(tokens2["username_password_create"])
            if tokens2 and tokens2.get("username_password_create")
            else sentinel_header
        )

        print(f"  [{ts()}] [注册] 设置密码...", flush=True)
        reg_resp = s.post(
            "https://auth.openai.com/api/accounts/user/register",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel2,
                "origin": "https://auth.openai.com",
                "referer": "https://auth.openai.com/create-account/password",
            },
            data=json.dumps({"password": password, "username": email}),
        )
        if reg_resp.status_code != 200:
            print(
                f"  [{ts()}] [!] register: {reg_resp.status_code} {reg_resp.text[:200]}",
                flush=True,
            )
            return (f"reg_{reg_resp.status_code}", None)

        # 6) 发送验证码
        print(f"  [{ts()}] [注册] 发送验证码...", flush=True)
        send_resp = s.get(
            "https://auth.openai.com/api/accounts/email-otp/send",
            headers={"accept": "application/json"},
        )
        if send_resp.status_code != 200:
            return (f"send_otp_{send_resp.status_code}", None)

        # 7) 获取验证码
        since_ts = int(time.time() * 1000) - 10000
        code = get_oai_code_inbucket(mail_api, email, since_ts, set(), timeout_secs=60)
        if not code:
            return ("otp_timeout", None)

        # 8) 验证
        print(f"  [{ts()}] [注册] 验证 OTP...", flush=True)
        s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={"accept": "application/json", "content-type": "application/json"},
            data=json.dumps({"code": code}),
        )

        # 9) 创建账户
        print(f"  [{ts()}] [注册] 获取 create sentinel...", flush=True)
        tokens3 = get_sentinel_tokens(
            ["oauth_create_account"], proxy=proxy, headless=headless
        )
        sentinel3 = (
            json.dumps(tokens3["oauth_create_account"])
            if tokens3 and tokens3.get("oauth_create_account")
            else ""
        )

        name = random.choice(string.ascii_uppercase) + "".join(
            random.choices(string.ascii_lowercase, k=random.randint(4, 8))
        )
        print(f"  [{ts()}] [注册] 创建账户...", flush=True)
        create_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://auth.openai.com",
            "referer": "https://auth.openai.com/about-you",
        }
        if sentinel3:
            create_headers["openai-sentinel-token"] = sentinel3
        create_resp = s.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers=create_headers,
            data=json.dumps(
                {
                    "name": name,
                    "birthdate": f"{random.randint(1985, 2002)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
                }
            ),
        )
        if create_resp.status_code != 200:
            print(
                f"  [{ts()}] [!] create: {create_resp.status_code} {create_resp.text[:200]}",
                flush=True,
            )
            return (f"create_{create_resp.status_code}", None)

        print(f"  [{ts()}] [注册] 成功! {email}", flush=True)
        return email, password

    except Exception as e:
        print(f"  [{ts()}] [!] 异常: {e}", flush=True)
        return ("exception", None)


# ==========================================
# 第二阶段: Playwright 浏览器 OAuth 登录
# ==========================================
def _wait_stable(page, t=3):
    try:
        page.wait_for_load_state("networkidle", timeout=t * 1000)
    except:
        pass


def _page_type(page):
    url = page.url
    if "localhost:1455" in url:
        return "callback"
    if "email-verification" in url or "verify" in url:
        return "otp"
    if "consent" in url:
        return "consent"
    if "about-you" in url:
        return "about_you"
    if "create-account/password" in url or (
        "password" in url and "auth.openai.com" in url
    ):
        return "password"
    if "log-in" in url or ("login" in url and "auth.openai.com" in url):
        return "login"
    if "create-account" in url and "auth.openai.com" in url:
        return "login"
    if "add-phone" in url:
        return "add_phone"
    if page.query_selector('text="Oops, an error occurred"'):
        return "error"
    # Cloudflare 验证页
    if page.query_selector('text="Verify you are human"') or page.query_selector(
        'iframe[src*="challenges.cloudflare.com"]'
    ):
        return "cf_challenge"
    # chatgpt.com 主页 (有 Sign up / Log in 按钮)
    if "chatgpt.com" in url and page.query_selector(
        'button:has-text("Sign up"), a:has-text("Sign up"), [data-testid="signup-button"]'
    ):
        return "chatgpt_home"
    # chatgpt.com 已登录主页
    if (
        "chatgpt.com" in url
        and "auth" not in url
        and not any(k in url for k in ["signup", "login", "create-account"])
    ):
        # 检查是否真的登录了
        if page.query_selector(
            'textarea, [data-testid="send-button"], button:has-text("Send")'
        ):
            return "chatgpt_logged_in"
    body = ""
    try:
        body = page.inner_text("body").lower()
    except:
        pass
    if "max_check_attempts" in body:
        return "rate_limited"
    if "enter code" in body or "check your email" in body:
        return "otp"
    # 检查是否有邮箱输入框 (通用登录页检测)
    if page.query_selector(
        'input[name="email"], input[name="username"], input[type="email"]'
    ):
        return "login"
    return "unknown"


def _find_otp(page):
    otp = page.query_selector(
        'input[name="code"], input[autocomplete="one-time-code"], '
        'input[inputmode="numeric"], input[name="otp"], input[type="tel"]'
    )
    if not otp:
        singles = page.query_selector_all('input[maxlength="1"]')
        if len(singles) >= 4:
            otp = singles[0]
    if not otp:
        for inp in page.query_selector_all("input"):
            try:
                a = page.evaluate("(el)=>({type:el.type,name:el.name})", inp)
                if a.get("type") in ("text", "tel", "number", "") and a.get(
                    "name"
                ) not in ("password", "email", "username"):
                    return inp
            except:
                pass
    return otp


# ==========================================
# 5SIM 接码
# ==========================================
FIVESIM_API = "https://5sim.net/v1"


def fivesim_buy_number(
    api_key, country="usa", operator="any", product="openai", max_price=0
):
    """购买虚拟号码。max_price>0 时先查价格选最便宜的运营商"""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    # 如果设了最高价，先查价格选便宜的运营商
    if max_price > 0 and operator == "any":
        try:
            r = http_requests.get(
                f"{FIVESIM_API}/guest/prices",
                params={"country": country, "product": product},
                headers=headers,
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                # 结构: {country: {product: {operator: {cost, count}}}}
                ops = data.get(country, {}).get(product, {})
                cheap = [
                    (op, info.get("cost", 999))
                    for op, info in ops.items()
                    if info.get("count", 0) > 0
                ]
                cheap.sort(key=lambda x: x[1])
                for op, cost in cheap:
                    if cost <= max_price:
                        operator = op
                        print(
                            f"    [5SIM] 选运营商: {op} (${cost / 100:.2f})", flush=True
                        )
                        break
                else:
                    if cheap:
                        print(
                            f"    [5SIM] 最低 ${cheap[0][1] / 100:.2f} > 限价 ${max_price / 100:.2f}",
                            flush=True,
                        )
                    return None, None
        except Exception as e:
            print(f"    [5SIM] 查价异常: {e}", flush=True)

    url = f"{FIVESIM_API}/user/buy/activation/{country}/{operator}/{product}"
    try:
        r = http_requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            return data.get("id"), data.get("phone")
        else:
            print(f"    [5SIM] 购买失败: {r.status_code} {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"    [5SIM] 购买异常: {e}", flush=True)
    return None, None


def fivesim_get_sms(api_key, order_id, timeout_secs=120):
    """等待接收短信验证码"""
    url = f"{FIVESIM_API}/user/check/{order_id}"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    regex = r"(?<!\d)(\d{4,6})(?!\d)"
    print(f"    [5SIM] 等待短信", end="", flush=True)
    for _ in range(timeout_secs // 3):
        print(".", end="", flush=True)
        try:
            r = http_requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                sms_list = data.get("sms", [])
                if sms_list:
                    code_text = sms_list[-1].get("code", "") or sms_list[-1].get(
                        "text", ""
                    )
                    m = re.search(regex, code_text)
                    if m:
                        print(f" OK:{m.group(1)}")
                        return m.group(1)
        except:
            pass
        time.sleep(3)
    print(" 超时")
    return None


def fivesim_finish(api_key, order_id):
    """完成订单"""
    try:
        url = f"{FIVESIM_API}/user/finish/{order_id}"
        http_requests.get(
            url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10
        )
    except:
        pass


def fivesim_cancel(api_key, order_id):
    """取消订单"""
    try:
        url = f"{FIVESIM_API}/user/cancel/{order_id}"
        http_requests.get(
            url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10
        )
    except:
        pass


def _shot(page, email, tag):
    try:
        page.screenshot(path=f"debug_{email.split('@')[0]}_{tag}.png")
    except:
        pass


def do_browser_oauth(
    email,
    password,
    cpa_url,
    cpa_key,
    mail_api,
    headless=True,
    proxy=None,
    fivesim_key="",
    fivesim_country="usa",
    fivesim_operator="any",
    fivesim_max_price=0,
):
    """
    自己生成 PKCE，浏览器完成登录拿 code，自己换 token，本地保存后上传 CPA。
    返回 True/False/失败原因字符串
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    # 1) 自己生成 OAuth URL (不依赖 CPA)
    auth_url, state, code_verifier = generate_oauth_url()
    print(
        f"  [{time.strftime('%H:%M:%S')}] [OAuth] 自建 PKCE, state={state[:20]}...",
        flush=True,
    )

    # 2) 浏览器登录拿 callback URL
    captured_url = None
    since_ts = int(time.time() * 1000) - 30000  # 往前推 30 秒，避免时间偏差
    used_codes = set()
    otp_submitted = False

    def on_req(request):
        nonlocal captured_url
        if "localhost:1455" in request.url and "code=" in request.url:
            captured_url = request.url

    with Stealth().use_sync(sync_playwright()) as p:
        kw = {"headless": headless}
        if proxy:
            kw["proxy"] = {"server": proxy}
        browser = p.firefox.launch(**kw)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800}, locale="en-US"
        )
        page = ctx.new_page()
        page.on("request", on_req)
        page.set_default_timeout(120000)

        try:
            for att in range(3):
                page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
                _wait_stable(page)
                if _page_type(page) == "error":
                    btn = page.query_selector('button:has-text("Try again")')
                    if btn:
                        btn.click()
                        _wait_stable(page, 8)
                    continue
                break
            else:
                _shot(page, email, "load_fail")
                browser.close()
                return False

            last_pt = None
            for step in range(60):
                if captured_url:
                    break
                _wait_stable(page, 2)
                pt = _page_type(page)
                if pt != last_pt:
                    print(
                        f"  [{time.strftime('%H:%M:%S')}] [OAuth] 页面: {pt} | {page.url[:80]}",
                        flush=True,
                    )
                    last_pt = pt

                if pt == "callback":
                    captured_url = page.url
                    break
                if pt == "login":
                    ei = page.query_selector(
                        'input[name="email"], input[name="username"], input[type="email"]'
                    )
                    if ei and not ei.input_value():
                        ei.fill(email)
                        time.sleep(0.3)
                        btn = page.query_selector(
                            'button[type="submit"], button:has-text("Continue")'
                        )
                        if btn:
                            btn.click()
                        else:
                            ei.press("Enter")
                        for _ in range(5):
                            time.sleep(1)
                            if _page_type(page) != "login":
                                break
                    continue
                if pt == "password":
                    pi = page.query_selector(
                        'input[name="password"], input[type="password"]'
                    )
                    if pi and not pi.input_value():
                        pi.fill(password)
                        time.sleep(0.3)
                        btn = page.query_selector(
                            'button[type="submit"], button:has-text("Continue"), button:has-text("Log in")'
                        )
                        if btn:
                            btn.click()
                        else:
                            pi.press("Enter")
                        for _ in range(5):
                            time.sleep(1)
                            if _page_type(page) != "password":
                                break
                    continue
                if pt == "otp":
                    if otp_submitted:
                        time.sleep(1)
                        continue
                    otp = _find_otp(page)
                    if otp:
                        # 先等 20 秒看有没有验证码
                        code = get_oai_code_inbucket(
                            mail_api, email, since_ts, used_codes, timeout_secs=20
                        )
                        if not code:
                            # 没收到，点重发按钮
                            resend = page.query_selector(
                                'button:has-text("Resend"), a:has-text("Resend"), button:has-text("resend"), a:has-text("resend")'
                            )
                            if resend:
                                print(
                                    f"  [{time.strftime('%H:%M:%S')}] [OAuth] 点击重发验证码...",
                                    flush=True,
                                )
                                page.evaluate("(el)=>el.click()", resend)
                                time.sleep(3)
                                code = get_oai_code_inbucket(
                                    mail_api,
                                    email,
                                    since_ts,
                                    used_codes,
                                    timeout_secs=20,
                                )
                            if not code:
                                print(
                                    f"  [{time.strftime('%H:%M:%S')}] [OAuth] 重发后仍无验证码，放弃",
                                    flush=True,
                                )
                                browser.close()
                                return False
                        if code:
                            used_codes.add(code)
                            print(
                                f"  [{time.strftime('%H:%M:%S')}] [OAuth] 填入验证码 {code}",
                                flush=True,
                            )
                            otp.fill(code)
                            time.sleep(2)
                            btn = page.query_selector('button[type="submit"]')
                            if btn:
                                page.evaluate("(el)=>el.click()", btn)
                            else:
                                otp.press("Enter")
                            otp_submitted = True
                            for _ in range(15):
                                time.sleep(1)
                                if _page_type(page) != "otp":
                                    break
                        else:
                            browser.close()
                            return False
                    continue
                if pt == "consent":
                    # 列出页面上所有按钮
                    btns = page.query_selector_all("button")
                    for b in btns[:5]:
                        try:
                            txt = b.inner_text()[:50]
                            print(f"    [consent] 按钮: '{txt}'", flush=True)
                        except:
                            pass
                    btn = page.query_selector(
                        'button:has-text("Continue"), button:has-text("Sign in"), button[type="submit"]'
                    )
                    if btn:
                        print(
                            f"  [{time.strftime('%H:%M:%S')}] [OAuth] 点击 consent",
                            flush=True,
                        )
                        page.evaluate("(el)=>el.click()", btn)
                        for _ in range(8):
                            time.sleep(1)
                            npt = _page_type(page)
                            if npt != "consent":
                                print(
                                    f"  [{time.strftime('%H:%M:%S')}] [OAuth] consent 后: {npt} | {page.url[:80]}",
                                    flush=True,
                                )
                                break
                    else:
                        print(
                            f"  [{time.strftime('%H:%M:%S')}] [OAuth] consent 页无按钮，截图",
                            flush=True,
                        )
                        _shot(page, email, "consent_no_btn")
                    continue
                if pt == "add_phone":
                    print(
                        f"  [{time.strftime('%H:%M:%S')}] [OAuth] 需要手机验证，标记失败",
                        flush=True,
                    )
                    browser.close()
                    return "add_phone"
                if pt == "rate_limited":
                    browser.close()
                    return "rate_limited"
                if pt == "error":
                    browser.close()
                    return "error"
                time.sleep(3)

            if not captured_url:
                cur = page.url
                if "localhost:1455" in cur:
                    captured_url = cur
                else:
                    _shot(page, email, "no_redirect")
        except Exception as e:
            print(f"  [!] 浏览器异常: {e}")
            _shot(page, email, "exc")
        browser.close()

    if not captured_url:
        return False

    # 3) 自己用 code + verifier 换 token
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(captured_url).query)
    code = qs.get("code", [None])[0]
    cb_state = qs.get("state", [None])[0]
    if not code:
        print(f"  [!] callback 缺少 code")
        return False
    if cb_state != state:
        print(f"  [!] state 不匹配")
        return False

    print(f"  [{time.strftime('%H:%M:%S')}] [OAuth] 用 code 换 token...", flush=True)
    try:
        token_resp = exchange_code_for_token(code, code_verifier)
    except Exception as e:
        print(f"  [!] token 交换失败: {e}")
        return False

    auth_json = build_codex_auth_json(token_resp, email, password)
    if not auth_json.get("access_token"):
        print(f"  [!] 未获取到 access_token")
        return False

    # 4) 本地保存
    local_dir = _resolve_runtime_path("/app/data/auth_files")
    os.makedirs(local_dir, exist_ok=True)
    filename = f"codex-{email}.json"
    local_path = os.path.join(local_dir, filename)
    with open(local_path, "w") as f:
        json.dump(auth_json, f, indent=2)
    print(f"  [{time.strftime('%H:%M:%S')}] [OAuth] 本地保存: {local_path}", flush=True)

    # 5) 上传到 CLIProxyAPI
    print(f"  [{time.strftime('%H:%M:%S')}] [OAuth] 上传到 CPA...", flush=True)
    try:
        sc, resp_text = cpa_upload_auth(cpa_url, cpa_key, auth_json)
        if sc in (200, 201):
            print(f"  [OK] 上传成功!", flush=True)
            return True
        else:
            print(
                f"  [{time.strftime('%H:%M:%S')}] [!] 上传失败: {sc} {resp_text[:200]}",
                flush=True,
            )
            return False
    except Exception as e:
        print(
            f"  [{time.strftime('%H:%M:%S')}] [!] 上传异常: {e} (本地文件已保存)",
            flush=True,
        )
        return False


# ==========================================
# WARP IP 轮换
# ==========================================
def rotate_warp_ip(preferred_country=None, max_attempts=5):
    """重连 WARP 获取新 IP，可指定偏好国家 (如 'US')"""
    import subprocess

    for attempt in range(max_attempts):
        print(f"[IP] 重连 WARP ({attempt + 1}/{max_attempts})...", flush=True)
        try:
            subprocess.run(
                ["warp-cli", "--accept-tos", "disconnect"],
                capture_output=True,
                timeout=10,
            )
            time.sleep(2)
            subprocess.run(
                ["warp-cli", "--accept-tos", "connect"], capture_output=True, timeout=10
            )
            time.sleep(5)
            r = http_requests.get(
                "https://cloudflare.com/cdn-cgi/trace", timeout=10, verify=False
            )
            ip = re.search(r"ip=(.+)", r.text)
            loc = re.search(r"loc=(.+)", r.text)
            ip_str = ip.group(1) if ip else "?"
            loc_str = loc.group(1) if loc else "?"
            print(f"[IP] {ip_str} | 地区: {loc_str}", flush=True)
            if not preferred_country or loc_str == preferred_country:
                return loc_str
        except Exception as e:
            print(f"[IP] 失败: {e}", flush=True)
    print(f"[IP] 未获得 {preferred_country} IP，使用当前", flush=True)
    return None


# ==========================================
# 主入口: 注册 + 登录一条龙
# ==========================================
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# 实时统计
_stats_lock = threading.Lock()
_stats = {"running": 0, "success": 0, "fail": 0, "total": 0, "current_threads": {}}


def _update_thread_status(tid, status):
    with _stats_lock:
        _stats["current_threads"][tid] = status


def _print_dashboard():
    with _stats_lock:
        s = _stats
        lines = [
            f"\r\033[K[统计] 成功:{s['success']} 失败:{s['fail']} 进行中:{s['running']} 总:{s['total']}"
        ]
        for tid, status in list(s["current_threads"].items())[:10]:
            lines.append(f"  {tid}: {status}")
        print("\n".join(lines), flush=True)


file_lock = threading.Lock()


def run_one(args):
    """单次: 注册 → OAuth 登录 → 回填 CLIProxyAPI。返回结果 dict"""
    tid = threading.current_thread().name
    with _stats_lock:
        _stats["running"] += 1
    _update_thread_status(tid, "注册中...")
    print(f"\n[{tid}] 开始注册+登录", flush=True)

    result = do_register(
        args.email_domains,
        args.cf_worker_url,
        args.cf_api_token,
        args.mail_api,
        args.proxy,
        headless=not args.no_headless,
    )

    # 注册失败
    if result is None or (isinstance(result, tuple) and result[1] is None):
        reason = result[0] if isinstance(result, tuple) else "reg_fail"
        _update_thread_status(tid, f"注册失败: {reason}")
        with _stats_lock:
            _stats["running"] -= 1
        return {"ok": False, "reason": reason, "is_400": "400" in str(reason)}

    email, password = result
    _update_thread_status(tid, f"OAuth: {email[:20]}")

    ok = do_browser_oauth(
        email,
        password,
        args.cpa_url,
        args.cpa_key,
        args.mail_api,
        headless=not args.no_headless,
        proxy=args.proxy,
        fivesim_key=args.fivesim_key,
        fivesim_country=args.fivesim_country,
        fivesim_operator=args.fivesim_operator,
        fivesim_max_price=args.fivesim_max_price,
    )
    with _stats_lock:
        _stats["running"] -= 1
    if ok is True:
        _update_thread_status(tid, f"✓ {email[:20]}")
        with _stats_lock:
            _stats["success"] += 1
        return {"ok": True, "email": email, "password": password, "status": "oauth_ok"}
    else:
        reason = ok if isinstance(ok, str) else "unknown"
        _update_thread_status(tid, f"✗ {reason}: {email[:20]}")
        with _stats_lock:
            _stats["fail"] += 1
        return {
            "ok": False,
            "email": email,
            "password": password,
            "status": f"oauth_fail:{reason}",
        }


def run_batch(args, count):
    """跑一批，多线程并发，完成后统一写日志。返回 (成功数, 失败数)"""
    workers = min(args.workers, count)
    results = []

    if workers <= 1:
        for _ in range(count):
            r = run_one(args)
            results.append(r)
            # 每次成功后换 IP
            if r.get("ok"):
                rotate_warp_ip(
                    args.preferred_country
                    if hasattr(args, "preferred_country")
                    else None
                )
            w = random.randint(args.sleep_min, args.sleep_max)
            time.sleep(w)
    else:
        print(f"[*] {workers} 线程并发, 本批 {count} 个", flush=True)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="W") as pool:
            futures = []
            for i in range(count):
                futures.append(pool.submit(run_one, args))
                if i < count - 1:
                    time.sleep(random.randint(3, 8))
            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as e:
                    print(f"[!] 线程异常: {e}", flush=True)
                    results.append({"ok": False, "reason": str(e)})

    # 统一写日志
    log_lines = []
    for r in results:
        if r.get("email"):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_lines.append(
                f"{r['email']}----{r['password']}----{r['status']}----{ts}\n"
            )
    if log_lines:
        accounts_dir = os.path.dirname(args.accounts_log)
        if accounts_dir:
            os.makedirs(accounts_dir, exist_ok=True)
        with open(args.accounts_log, "a", encoding="utf-8") as f:
            f.writelines(log_lines)
        print(f"[日志] 写入 {len(log_lines)} 条到 {args.accounts_log}", flush=True)

    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count

    # 每批结束后换 IP
    print(f"[IP] 批次结束，换 IP", flush=True)
    rotate_warp_ip(
        args.preferred_country if hasattr(args, "preferred_country") else None
    )

    return ok_count, fail_count


def _update_account_log(path, email, new_status):
    """更新账号日志中某邮箱的状态"""
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    new = []
    for line in lines:
        s = line.rstrip("\n")
        if email in s and "----registered----" in s:
            s = s.replace("----registered----", f"----{new_status}----")
        new.append(s + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new)


def main():
    ap = argparse.ArgumentParser(description="Codex 注册+OAuth 登录一条龙")
    ap.add_argument("-c", "--config", default="pool_config.yaml", help="配置文件路径")
    # 以下参数可覆盖配置文件
    ap.add_argument("--cpa-url")
    ap.add_argument("--cpa-key")
    ap.add_argument("--mail-api")
    ap.add_argument("--cf-worker-url")
    ap.add_argument("--cf-api-token")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--accounts-log")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--rotate-after-fails", type=int)
    ap.add_argument("--sleep-min", type=int)
    ap.add_argument("--sleep-max", type=int)
    # 模式
    ap.add_argument("--loop", action="store_true", help="循环模式")
    ap.add_argument("--count", type=int, default=0, help="循环次数 (0=无限)")
    ap.add_argument("--pool-monitor", action="store_true", help="号池监控模式 (默认)")
    ap.add_argument("--pool-min", type=int)
    ap.add_argument("--pool-target", type=int)
    ap.add_argument("--pool-check-interval", type=int)
    ap.add_argument("--rotate-every", type=int)
    cli = ap.parse_args()

    # 加载配置文件
    cfg = load_config(cli.config)
    cp = cfg.get("cliproxy", {})
    pool = cfg.get("pool", {})
    email_cfg = cfg.get("email", {})

    # 合并: 命令行 > 配置文件 > 默认值
    class Args:
        pass

    args = Args()
    args.cpa_url = (cli.cpa_url or cp.get("url") or DEFAULTS["cpa_url"]).rstrip("/")
    args.cpa_key = cli.cpa_key or cp.get("key") or DEFAULTS["cpa_key"]
    raw_mail_cfg = cfg.get("mail_api", {})
    if cli.mail_api:
        raw_mail_cfg = cli.mail_api
    args.mail_api = normalize_mail_config(
        raw_mail_cfg or DEFAULTS["mail_api"],
        cfg.get("email_domains") or [f"*.{DEFAULTS['email_domain']}"],
    )
    args.email_domains = cfg.get("email_domains") or [f"*.{DEFAULTS['email_domain']}"]
    args.cf_worker_url = (
        cli.cf_worker_url or email_cfg.get("cf_worker_url") or DEFAULTS["cf_worker_url"]
    )
    args.cf_api_token = (
        cli.cf_api_token or email_cfg.get("cf_api_token") or DEFAULTS["cf_api_token"]
    )
    args.proxy = cli.proxy or None  # tunnel 模式不需要，留着给外部代理用
    args.no_headless = cli.no_headless or not cfg.get("headless", True)
    args.accounts_log = _resolve_runtime_path(
        cli.accounts_log or cfg.get("accounts_log") or "accounts_all.txt"
    )
    args.workers = cli.workers if cli.workers is not None else cfg.get("workers", 1)
    args.rotate_after_fails = (
        cli.rotate_after_fails
        if cli.rotate_after_fails is not None
        else cfg.get("rotate_after_fails", 3)
    )
    args.preferred_country = cfg.get("preferred_country", "") or ""
    fivesim_cfg = cfg.get("fivesim", {})
    args.fivesim_key = fivesim_cfg.get("api_key", "") or ""
    # 5SIM 国家跟随 preferred_country，也可单独配
    pc = args.preferred_country.lower()
    country_map = {
        # WARP(ISO) -> 5SIM
        "us": "usa",
        "gb": "england",
        "uk": "england",
        "de": "germany",
        "fr": "france",
        "nl": "netherlands",
        "jp": "japan",
        "kr": "korea",
        "ca": "canada",
        "au": "australia",
        "it": "italy",
        "se": "sweden",
        "id": "indonesia",
        "vn": "vietnam",
        "pt": "portugal",
        "ro": "romania",
        "ar": "argentina",
        "cz": "czech",
        "ma": "morocco",
        "pl": "poland",
        "uz": "uzbekistan",
        "be": "belgium",
    }
    default_5sim_country = country_map.get(pc, pc) if pc else "usa"
    args.fivesim_country = fivesim_cfg.get("country", "") or default_5sim_country
    args.fivesim_operator = fivesim_cfg.get("operator", "any") or "any"
    args.fivesim_max_price = int(
        fivesim_cfg.get("max_price", 0) or 0
    )  # 单位: 分 (如 50 = $0.50)
    args.sleep_min = (
        cli.sleep_min if cli.sleep_min is not None else cfg.get("sleep_min", 5)
    )
    args.sleep_max = (
        cli.sleep_max if cli.sleep_max is not None else cfg.get("sleep_max", 15)
    )
    args.pool_min = cli.pool_min if cli.pool_min is not None else pool.get("min", 5)
    args.pool_target = (
        cli.pool_target if cli.pool_target is not None else pool.get("target", 10)
    )
    args.pool_check_interval = (
        cli.pool_check_interval
        if cli.pool_check_interval is not None
        else pool.get("check_interval", 60)
    )
    args.rotate_every = (
        cli.rotate_every
        if cli.rotate_every is not None
        else cfg.get("rotate_after_fails", 3)
    )

    print(
        f"[*] 配置: CPA={args.cpa_url} | 号池={args.pool_min}/{args.pool_target} | 并发={args.workers} | 换IP=连续{args.rotate_after_fails}失败",
        flush=True,
    )

    success, fail, total, consecutive_fails = 0, 0, 0, 0

    if cli.pool_monitor or (not cli.loop and not cli.count):
        print(f"[*] 号池监控 | 间隔: {args.pool_check_interval}s", flush=True)
        while True:
            try:
                pt, pa, pu = cpa_get_pool_status(args.cpa_url, args.cpa_key)
                print(f"\n[号池] 总: {pt} | 可用: {pa} | 不可用: {pu}", flush=True)
                if pa < args.pool_min:
                    need = args.pool_target - pa
                    print(
                        f"[号池] 可用({pa}) < 最低({args.pool_min})，补充 {need} 个",
                        flush=True,
                    )
                    # 分批跑，每批 workers 个
                    batch_size = args.workers
                    remaining = need
                    while remaining > 0:
                        n = min(batch_size, remaining)
                        s, f = run_batch(args, n)
                        success += s
                        fail += f
                        total += n
                        remaining -= n
                        consecutive_fails = consecutive_fails + f if f > 0 else 0
                        if s > 0:
                            consecutive_fails = 0
                        if consecutive_fails >= args.rotate_after_fails:
                            rotate_warp_ip(args.preferred_country)
                            consecutive_fails = 0
                        # 检查是否够了
                        _, ca, _ = cpa_get_pool_status(args.cpa_url, args.cpa_key)
                        if ca >= args.pool_target:
                            print(
                                f"[号池] 已达目标 {ca}>={args.pool_target}", flush=True
                            )
                            break
                        w = random.randint(args.sleep_min, args.sleep_max)
                        time.sleep(w)
                    print(
                        f"[统计] 成功: {success}, 失败: {fail}, 共: {total}", flush=True
                    )
                else:
                    print(
                        f"[号池] 充足，{args.pool_check_interval}s 后再查", flush=True
                    )
            except Exception as e:
                print(f"[!] 号池异常: {e}", flush=True)
            time.sleep(args.pool_check_interval)

    elif cli.loop:
        print(
            f"[*] 循环 | 次数: {'无限' if cli.count == 0 else cli.count} | 并发: {args.workers}",
            flush=True,
        )
        while cli.count == 0 or total < cli.count:
            n = min(
                args.workers, (cli.count - total) if cli.count > 0 else args.workers
            )
            s, f = run_batch(args, n)
            success += s
            fail += f
            total += n
            consecutive_fails = consecutive_fails + f if f > 0 else 0
            if s > 0:
                consecutive_fails = 0
            if consecutive_fails >= args.rotate_after_fails:
                rotate_warp_ip(args.preferred_country)
                consecutive_fails = 0
            print(f"[统计] 成功: {success}, 失败: {fail}, 共: {total}", flush=True)
            w = random.randint(args.sleep_min, args.sleep_max)
            time.sleep(w)

    print(f"\n完成! 成功: {success}, 失败: {fail}", flush=True)


if __name__ == "__main__":
    main()
