#!/usr/bin/env python3
"""
HTTP 注册机 v2 (纯 HTTP + Playwright Sentinel)
================================================
注册流程全部用 curl_cffi 纯 HTTP，只在需要 sentinel token 的步骤
(register, create_account) 用 Playwright 加载 SentinelSDK 获取真实 token。

依赖: pip install curl_cffi pyyaml playwright playwright-stealth
      playwright install firefox

使用:
  python http_register.py --count 1
  python http_register.py --count 5 --workers 3
  python http_register.py --pool-monitor
"""

import argparse, base64, hashlib, json, os, random, re, secrets, string
import sys, time, uuid, urllib.parse, threading
from typing import Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from curl_cffi import requests as cffi_requests
import requests as http_requests
import yaml
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from sentinel_browser import get_sentinel_token_str, get_sentinel_tokens
from mail_api_adapter import (
    create_mailbox_address,
    fetch_email_code,
    normalize_mail_config,
)


# ==========================================
# 配置
# ==========================================
def load_config(path="pool_config.yaml"):
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_account_file(path: str):
    if not path or not os.path.isfile(path):
        return None
    for raw in open(path, "r", encoding="utf-8", errors="ignore").read().splitlines():
        line = raw.strip()
        if not line or "----" not in line:
            continue
        parts = line.split("----", 3)
        if len(parts) != 4:
            continue
        return {
            "email": parts[0].strip(),
            "mailbox_password": parts[1].strip(),
            "client_id": parts[2].strip(),
            "refresh_token": parts[3].strip(),
        }
    return None


# ==========================================
# 邮箱生成
# ==========================================
def generate_email(email_domains, mail_cfg):
    return create_mailbox_address(mail_cfg, email_domains)


# ==========================================
# 核心注册流程 (HTTP + Playwright Sentinel)
# ==========================================
def do_register(email, password, mail_cfg, proxy=None, headless=True):
    """
    纯 HTTP 注册，只在 register 和 create_account 步骤用 Playwright 获取 sentinel token。
    返回 True/失败原因字符串
    """
    ts = lambda: time.strftime("%H:%M:%S")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    s = None

    try:
        # 1) 从 chatgpt.com 获取 session
        print(f"  [{ts()}] 获取 session...", flush=True)
        last_exc = None
        csrf_token = ""
        did = ""
        for attempt in range(3):
            try:
                s = cffi_requests.Session(proxies=proxies, impersonate="chrome")
                print(f"  [{ts()}] session 请求 ({attempt + 1}/3)...", flush=True)
                s.get("https://chatgpt.com", timeout=30)
                print(f"  [{ts()}] 获取 csrf...", flush=True)
                csrf_resp = s.get("https://chatgpt.com/api/auth/csrf", timeout=20)
                csrf_token = (
                    csrf_resp.json().get("csrfToken", "")
                    if csrf_resp.status_code == 200
                    else ""
                )
                did = s.cookies.get("oai-did", str(uuid.uuid4()))
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                print(f"  [{ts()}] session 初始化失败: {exc}", flush=True)
                if attempt < 2:
                    print(f"  [{ts()}] 重建 session 后重试...", flush=True)
                    time.sleep(2)
        if last_exc:
            raise last_exc

        # 2) 发起注册
        print(f"  [{ts()}] 发起注册...", flush=True)
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
            return f"signin_{signin_resp.status_code}"

        auth_url = signin_resp.json().get("url", "")
        if auth_url:
            s.get(auth_url, timeout=15, allow_redirects=True)

        # 3) 获取 sentinel token (Playwright SDK)
        print(f"  [{ts()}] 获取 sentinel tokens...", flush=True)
        sentinel_tokens = get_sentinel_tokens(
            ["username_password_create"],
            proxy=proxy,
            headless=headless,
        )
        if not sentinel_tokens or not sentinel_tokens.get("username_password_create"):
            return "sentinel_fail"
        sentinel_header = json.dumps(sentinel_tokens["username_password_create"])

        # 4) 提交邮箱
        print(f"  [{ts()}] 提交邮箱...", flush=True)
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
            return f"signup_{signup_resp.status_code}"

        # 访问 continue_url
        try:
            cont_url = signup_resp.json().get("continue_url", "")
            if cont_url:
                s.get(cont_url, timeout=15)
        except:
            pass

        # 5) 设置密码 (用新的 sentinel token)
        print(f"  [{ts()}] 获取 register sentinel...", flush=True)
        reg_tokens = get_sentinel_tokens(
            ["username_password_create"], proxy=proxy, headless=headless
        )
        sentinel_header2 = ""
        if reg_tokens and reg_tokens.get("username_password_create"):
            sentinel_header2 = json.dumps(reg_tokens["username_password_create"])

        print(f"  [{ts()}] 设置密码...", flush=True)
        reg_resp = s.post(
            "https://auth.openai.com/api/accounts/user/register",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel_header2 or sentinel_header,
                "origin": "https://auth.openai.com",
                "referer": "https://auth.openai.com/create-account/password",
            },
            data=json.dumps({"password": password, "username": email}),
        )
        if reg_resp.status_code != 200:
            print(
                f"  [{ts()}] register 失败: {reg_resp.status_code} {reg_resp.text[:200]}",
                flush=True,
            )
            return f"reg_{reg_resp.status_code}"

        # 6) 发送验证码
        print(f"  [{ts()}] 发送验证码...", flush=True)
        send_resp = s.get(
            "https://auth.openai.com/api/accounts/email-otp/send",
            headers={"accept": "application/json"},
        )
        if send_resp.status_code != 200:
            return f"send_otp_{send_resp.status_code}"

        # 7) 获取验证码
        since_ts = int(time.time() * 1000) - 10000
        code = fetch_email_code(mail_cfg, email, since_ts, set(), timeout_secs=60)
        if not code:
            return "otp_timeout"

        # 8) 验证
        print(f"  [{ts()}] 验证 OTP...", flush=True)
        s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={"accept": "application/json", "content-type": "application/json"},
            data=json.dumps({"code": code}),
        )

        # 9) 创建账户
        print(f"  [{ts()}] 获取 create_account sentinel...", flush=True)
        create_tokens = get_sentinel_tokens(
            ["oauth_create_account"], proxy=proxy, headless=headless
        )
        sentinel_header3 = ""
        if create_tokens and create_tokens.get("oauth_create_account"):
            sentinel_header3 = json.dumps(create_tokens["oauth_create_account"])

        name = random.choice(string.ascii_uppercase) + "".join(
            random.choices(string.ascii_lowercase, k=random.randint(4, 8))
        )
        age = str(random.randint(22, 40))

        print(f"  [{ts()}] 创建账户...", flush=True)
        create_headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": "https://auth.openai.com",
            "referer": "https://auth.openai.com/about-you",
        }
        if sentinel_header3:
            create_headers["openai-sentinel-token"] = sentinel_header3
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
                f"  [{ts()}] create_account 失败: {create_resp.status_code} {create_resp.text[:200]}",
                flush=True,
            )
            return f"create_{create_resp.status_code}"

        print(f"  [{ts()}] 注册成功!", flush=True)
        return True

    except Exception as e:
        print(f"  [{ts()}] 异常: {e}", flush=True)
        return f"exception"


# ==========================================
# 主入口
# ==========================================
def main():
    ap = argparse.ArgumentParser(
        description="HTTP 注册机 v2 (HTTP + Playwright Sentinel)"
    )
    ap.add_argument("-c", "--config", default="pool_config.yaml")
    ap.add_argument("--count", type=int, default=1, help="注册数量")
    ap.add_argument("--workers", type=int, default=1, help="并发数")
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--account-file", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    email_domains = cfg.get("email_domains", ["*.aais.example.com"])
    mail_cfg = normalize_mail_config(
        cfg.get("mail_api", "http://your-inbucket-server:9000"), email_domains
    )
    account_override = load_account_file(args.account_file)
    if account_override:
        mail_cfg["provider"] = "hotmail_api"
        mail_cfg["accounts"] = [account_override]
        mail_cfg["account_index"] = 0
    headless = not args.no_headless

    success, fail = 0, 0
    lock = threading.Lock()

    def run_one():
        nonlocal success, fail
        email = create_mailbox_address(mail_cfg, email_domains)
        password = (
            "".join(random.choices(string.ascii_letters + string.digits, k=10)) + "aA1!"
        )
        tid = threading.current_thread().name
        print(f"\n[{tid}] {email}", flush=True)

        result = do_register(email, password, mail_cfg, args.proxy, headless)
        with lock:
            if result is True:
                success += 1
                # 保存账号
                with open("registered_accounts.txt", "a") as f:
                    f.write(
                        f"{email}----{password}----ok----{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
            else:
                fail += 1
                with open("registered_accounts.txt", "a") as f:
                    f.write(
                        f"{email}----{password}----fail:{result}----{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
        print(
            f"[{tid}] {'成功' if result is True else f'失败:{result}'} | 累计 成功:{success} 失败:{fail}",
            flush=True,
        )

    if args.workers <= 1:
        for i in range(args.count):
            run_one()
            if i < args.count - 1:
                time.sleep(random.randint(3, 8))
    else:
        with ThreadPoolExecutor(
            max_workers=args.workers, thread_name_prefix="W"
        ) as pool:
            futures = []
            for i in range(args.count):
                futures.append(pool.submit(run_one))
                if i < args.count - 1:
                    time.sleep(random.randint(2, 5))
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    print(f"[!] {e}", flush=True)

    print(f"\n完成! 成功: {success}, 失败: {fail}", flush=True)


if __name__ == "__main__":
    main()
