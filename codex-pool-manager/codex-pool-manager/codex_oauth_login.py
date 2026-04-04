#!/usr/bin/env python3
"""
Codex OAuth 自动登录脚本 (Playwright Stealth + Firefox)
监控 accounts.txt，自动完成 OAuth 登录，token 回填 CLIProxyAPI。

依赖: pip install playwright requests playwright-stealth
      playwright install --with-deps firefox
"""

import argparse, json, os, re, sys, time, urllib.parse
from typing import Optional, List, Tuple
import requests as http_requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from mail_api_adapter import fetch_email_code, normalize_mail_config


# === CLIProxyAPI ===
def cpa_request_codex_auth_url(base_url, key):
    r = http_requests.get(
        f"{base_url}/v0/management/codex-auth-url",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
        verify=False,
    )
    r.raise_for_status()
    return r.json()


def cpa_check_auth_status(base_url, key, state):
    r = http_requests.get(
        f"{base_url}/v0/management/get-auth-status",
        headers={"Authorization": f"Bearer {key}"},
        params={"state": state},
        timeout=10,
        verify=False,
    )
    r.raise_for_status()
    return r.json()


def cpa_forward_callback(base_url, code, state):
    r = http_requests.get(
        f"{base_url}/codex/callback",
        params={"code": code, "state": state},
        timeout=15,
        verify=False,
    )
    return r.status_code


# === 浏览器自动化 ===
def _wait_for_page_stable(page, timeout=10):
    """等页面网络空闲 + DOM 稳定"""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout * 1000)
    except:
        pass
    time.sleep(1)


def _current_page_type(page):
    """根据 URL 和页面内容判断当前页面类型"""
    url = page.url
    if "localhost:1455" in url:
        return "callback"
    if "email-verification" in url or "verify" in url:
        return "otp"
    if "consent" in url:
        return "consent"
    if "password" in url:
        return "password"
    if "log-in" in url or "login" in url:
        return "login"
    if "add-phone" in url:
        return "add_phone"
    if "error" in url or page.query_selector('text="Oops, an error occurred"'):
        return "error"
    # 检查页面内容
    body = ""
    try:
        body = page.inner_text("body").lower()
    except:
        pass
    if "max_check_attempts" in body:
        return "rate_limited"
    if "enter code" in body or "check your email" in body:
        return "otp"
    return "unknown"


def do_browser_login(
    auth_url, email, password, mail_api, headless=True, proxy=None, timeout_ms=120000
):
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    print(f"    [浏览器] {'无头' if headless else '有头'}模式", flush=True)
    captured_url = None
    since_ts = int(time.time() * 1000)
    used_codes = set()
    otp_submitted = False  # 标记验证码是否已提交

    def on_request(request):
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
        page.on("request", on_request)
        page.set_default_timeout(timeout_ms)

        try:
            # === 1) 加载授权页 ===
            for attempt in range(3):
                print(f"    [浏览器] 加载授权页 ({attempt + 1}/3)...", flush=True)
                page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
                _wait_for_page_stable(page)
                if _current_page_type(page) == "error":
                    print(f"    [!] 错误页，重试...", flush=True)
                    btn = page.query_selector('button:has-text("Try again")')
                    if btn:
                        btn.click()
                        _wait_for_page_stable(page, 8)
                    continue
                break
            else:
                _shot(page, email, "load_fail")
                browser.close()
                return None

            # === 主状态机循环 ===
            last_page_type = None
            for step in range(60):
                if captured_url:
                    break

                _wait_for_page_stable(page, 5)
                pt = _current_page_type(page)

                # 只在页面类型变化时打印
                if pt != last_page_type:
                    print(f"    [浏览器] 页面: {pt} | URL: {page.url[:80]}", flush=True)
                    last_page_type = pt

                # --- callback: 成功! ---
                if pt == "callback":
                    captured_url = page.url
                    break

                # --- login: 输入邮箱 ---
                if pt == "login":
                    ei = page.query_selector(
                        'input[name="email"], input[name="username"], input[type="email"]'
                    )
                    if ei and not ei.get_attribute("disabled"):
                        val = ei.input_value()
                        if not val:  # 只在空的时候填，避免重复
                            print(f"    [浏览器] 输入邮箱...", flush=True)
                            ei.fill(email)
                            time.sleep(0.5)
                            btn = page.query_selector(
                                'button[type="submit"], button:has-text("Continue")'
                            )
                            if btn:
                                btn.click()
                            else:
                                ei.press("Enter")
                            # 等 URL 离开 login 页
                            for _ in range(15):
                                time.sleep(2)
                                if _current_page_type(page) != "login":
                                    break
                    continue

                # --- password: 输入密码 ---
                if pt == "password":
                    pi = page.query_selector(
                        'input[name="password"], input[type="password"]'
                    )
                    if pi and not pi.input_value():  # 只在空的时候填
                        print(f"    [浏览器] 输入密码...", flush=True)
                        pi.fill(password)
                        time.sleep(0.5)
                        btn = page.query_selector(
                            'button[type="submit"], button:has-text("Continue"), button:has-text("Log in")'
                        )
                        if btn:
                            btn.click()
                        else:
                            pi.press("Enter")
                        for _ in range(15):
                            time.sleep(2)
                            if _current_page_type(page) != "password":
                                break
                    continue

                # --- otp: 输入验证码 ---
                if pt == "otp":
                    if otp_submitted:
                        # 已提交过，等页面跳转
                        time.sleep(3)
                        continue
                    otp = _find_otp_input(page)
                    if otp:
                        print(f"    [浏览器] 获取验证码...", flush=True)
                        code = fetch_email_code(mail_api, email, since_ts, used_codes)
                        if code:
                            used_codes.add(code)
                            print(f"    [浏览器] 填入验证码 {code}...", flush=True)
                            otp.fill(code)
                            time.sleep(2)
                            btn = page.query_selector('button[type="submit"]')
                            if btn:
                                page.evaluate("(el) => el.click()", btn)
                            else:
                                otp.press("Enter")
                            otp_submitted = True
                            print(f"    [浏览器] 验证码已提交，等待跳转...", flush=True)
                            for _ in range(30):
                                time.sleep(2)
                                if _current_page_type(page) != "otp":
                                    break
                        else:
                            print(f"    [!] 验证码获取失败", flush=True)
                            _shot(page, email, "no_code")
                            browser.close()
                            return None
                    continue

                # --- consent: 点击同意 ---
                if pt == "consent":
                    btn = page.query_selector(
                        'button:has-text("Continue"), button:has-text("Sign in"), button[type="submit"]'
                    )
                    if btn:
                        print(f"    [浏览器] 点击 consent...", flush=True)
                        page.evaluate("(el) => el.click()", btn)
                        _wait_for_page_stable(page, 10)
                    continue

                # --- rate_limited ---
                if pt == "rate_limited":
                    print(f"    [!] 账号被限流", flush=True)
                    browser.close()
                    return "rate_limited"

                # --- add_phone: 需要绑手机，跳过 ---
                if pt == "add_phone":
                    print(f"    [!] 需要绑定手机，跳过", flush=True)
                    browser.close()
                    return "add_phone"

                # --- error ---
                if pt == "error":
                    print(f"    [!] 错误页面", flush=True)
                    _shot(page, email, "error")
                    browser.close()
                    return None

                # --- unknown: 等一下 ---
                time.sleep(3)

            # 最后检查
            if not captured_url:
                cur = page.url
                if "localhost:1455" in cur:
                    captured_url = cur
                else:
                    _shot(page, email, "no_redirect")

        except Exception as e:
            print(f"    [!] 异常: {e}", flush=True)
            _shot(page, email, "exception")
        browser.close()
    return captured_url


def _find_otp_input(page):
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
                a = page.evaluate("(el) => ({type:el.type,name:el.name})", inp)
                if a.get("type") in ("text", "tel", "number", "") and a.get(
                    "name"
                ) not in ("password", "email", "username"):
                    return inp
            except:
                pass
    return otp


def _shot(page, email, tag):
    try:
        page.screenshot(path=f"debug_{email.split('@')[0]}_{tag}.png")
        print(f"    [!] 截图: debug_{email.split('@')[0]}_{tag}.png", flush=True)
    except:
        pass


# === 单账号流程 ===
def login_one(email, password, cpa_url, cpa_key, mail_api, headless=True, proxy=None):
    print(f"  [CPA] 请求 codex-auth-url...", flush=True)
    try:
        result = cpa_request_codex_auth_url(cpa_url, cpa_key)
    except Exception as e:
        print(f"  [!] CLIProxyAPI 失败: {e}", flush=True)
        return False
    auth_url = result.get("url", "")
    state = result.get("state", "")
    if not auth_url or not state:
        print(f"  [!] 返回异常: {result}", flush=True)
        return False
    print(f"  [CPA] state={state[:20]}...", flush=True)

    callback_url = do_browser_login(
        auth_url, email, password, mail_api, headless, proxy
    )
    if not callback_url:
        print(f"  [!] 浏览器流程失败", flush=True)
        return False
    # 如果返回的是失败原因字符串 (不是 URL)
    if callback_url and "localhost" not in callback_url:
        print(f"  [!] 失败: {callback_url}", flush=True)
        return callback_url

    qs = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query)
    code = qs.get("code", [None])[0]
    cb_state = qs.get("state", [None])[0]
    if not code or not cb_state:
        print(f"  [!] callback 缺少 code/state", flush=True)
        return False

    print(f"  [CPA] 转发 callback...", flush=True)
    try:
        sc = cpa_forward_callback(cpa_url, code, cb_state)
        print(f"  [CPA] 转发响应: {sc}", flush=True)
    except Exception as e:
        print(f"  [!] 转发失败: {e}", flush=True)
        return False

    print(f"  [CPA] 等待 token 交换...", flush=True)
    for _ in range(40):
        try:
            st = cpa_check_auth_status(cpa_url, cpa_key, state)
            s = st.get("status", "")
            if s == "ok":
                print(f"  [OK] 成功!", flush=True)
                return True
            elif s == "error":
                print(f"  [!] 失败: {st.get('error', '?')}", flush=True)
                return False
        except:
            pass
        time.sleep(2)
    print(f"  [!] 超时", flush=True)
    return False


# === accounts.txt 读写 ===
def parse_accounts_file(path):
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    entries = []
    normalized = re.sub(r"(oauth=ok(?:----done)?)\s*(?!----)", r"\1\n", raw)
    for line in normalized.splitlines():
        line = line.strip()
        if not line or "----" not in line:
            continue
        done = "----done" in line or "----fail" in line
        clean = re.sub(r"----done\s*$", "", line)
        clean = re.sub(r"----oauth=ok\s*$", "", clean)
        clean = re.sub(r"oauth=ok\s*$", "", clean).strip()
        if not clean:
            continue
        parts = clean.split("----", 1)
        if len(parts) == 2 and "@" in parts[0]:
            entries.append(
                {"email": parts[0].strip(), "password": parts[1].strip(), "done": done}
            )
    return entries


def mark_done(path, email):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    new = []
    for line in lines:
        s = line.rstrip("\n")
        if email in s and "----done" not in s and "----fail" not in s:
            s += "----done"
        new.append(s + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new)


def mark_fail(path, email, reason=""):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    tag = f"----fail:{reason}" if reason else "----fail"
    new = []
    for line in lines:
        s = line.rstrip("\n")
        if email in s and "----done" not in s and "----fail" not in s:
            s += tag
        new.append(s + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new)


# === WARP IP 轮换 ===
def rotate_warp_ip():
    """重连 WARP 获取新 IP"""
    import subprocess

    print(f"[IP] 重连 WARP 换 IP...", flush=True)
    try:
        subprocess.run(
            ["warp-cli", "--accept-tos", "disconnect"], capture_output=True, timeout=10
        )
        time.sleep(2)
        subprocess.run(
            ["warp-cli", "--accept-tos", "connect"], capture_output=True, timeout=10
        )
        time.sleep(5)
        try:
            r = http_requests.get(
                "https://cloudflare.com/cdn-cgi/trace", timeout=10, verify=False
            )
            ip_match = re.search(r"ip=(.+)", r.text)
            if ip_match:
                print(f"[IP] 新 IP: {ip_match.group(1)}", flush=True)
        except:
            pass
    except Exception as e:
        print(f"[IP] 换 IP 失败: {e}", flush=True)


# === 主逻辑 ===
import threading

file_lock = threading.Lock()  # 文件读写锁


def process_one(email, password, args):
    """处理单个账号 (线程安全)"""
    ok = login_one(
        email,
        password,
        args.cpa_url,
        args.cpa_key,
        args.mail_api,
        not args.no_headless,
        args.proxy,
    )
    with file_lock:
        if ok is True:
            mark_done(args.accounts, email)
            return "ok"
        elif isinstance(ok, str):
            mark_fail(args.accounts, email, ok)
            return ok
        else:
            mark_fail(args.accounts, email)
            return "fail"


def process_pending(args):
    if not os.path.isfile(args.accounts):
        print(f"[.] 文件不存在: {args.accounts}", flush=True)
        return 0, 0
    entries = parse_accounts_file(args.accounts)
    pending = [e for e in entries if not e["done"]]
    if not pending:
        return 0, 0
    print(f"\n[*] 发现 {len(pending)} 个待处理 (共 {len(entries)} 个)", flush=True)

    workers = args.workers
    rotate_every = args.rotate_every
    success, fail = 0, 0
    processed = 0

    if workers <= 1:
        # 单线程模式
        for i, e in enumerate(pending):
            # IP 轮换
            if rotate_every > 0 and processed > 0 and processed % rotate_every == 0:
                rotate_warp_ip()
            print(
                f"\n{'=' * 55}\n[{i + 1}/{len(pending)}] {e['email']}\n{'=' * 55}",
                flush=True,
            )
            result = process_one(e["email"], e["password"], args)
            if result == "ok":
                success += 1
            else:
                fail += 1
            processed += 1
            if i < len(pending) - 1:
                import random

                w = random.randint(args.sleep_min, args.sleep_max)
                print(f"[*] 等待 {w}s...", flush=True)
                time.sleep(w)
    else:
        # 多线程模式
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"[*] 多线程模式: {workers} 并发", flush=True)

        def worker_fn(idx, e):
            nonlocal processed
            print(f"\n[线程{idx}] {e['email']}", flush=True)
            result = process_one(e["email"], e["password"], args)
            processed += 1
            # IP 轮换 (只在主线程做，避免并发冲突)
            return result

        batch_size = rotate_every if rotate_every > 0 else len(pending)
        for batch_start in range(0, len(pending), batch_size):
            batch = pending[batch_start : batch_start + batch_size]
            if batch_start > 0 and rotate_every > 0:
                rotate_warp_ip()

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(worker_fn, i, e): e for i, e in enumerate(batch)
                }
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if result == "ok":
                            success += 1
                        else:
                            fail += 1
                    except Exception as ex:
                        print(f"[!] 线程异常: {ex}", flush=True)
                        fail += 1

    return success, fail


def main():
    ap = argparse.ArgumentParser(description="Codex OAuth -> CLIProxyAPI")
    ap.add_argument("--accounts", required=True)
    ap.add_argument("--cpa-url", default="http://your-cpa-server:8317")
    ap.add_argument("--cpa-key", default="your-management-key")
    ap.add_argument("--mail-api", default="http://your-inbucket-server:9000")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--watch-interval", type=int, default=30)
    ap.add_argument("--sleep-min", type=int, default=5)
    ap.add_argument("--sleep-max", type=int, default=15)
    ap.add_argument("--workers", type=int, default=1, help="并发线程数 (默认 1)")
    ap.add_argument(
        "--rotate-every", type=int, default=0, help="每 N 条换一次 WARP IP (0=不换)"
    )
    args = ap.parse_args()
    args.cpa_url = args.cpa_url.rstrip("/")
    mail_api_arg = str(args.mail_api or "").strip()
    if mail_api_arg.lower().endswith(".json") and os.path.isfile(mail_api_arg):
        with open(mail_api_arg, "r", encoding="utf-8") as handle:
            args.mail_api = normalize_mail_config(json.load(handle))
    else:
        args.mail_api = normalize_mail_config(mail_api_arg.rstrip("/"))

    ts, tf = 0, 0
    if args.watch:
        print(
            f"[*] Watch | 文件: {args.accounts} | CPA: {args.cpa_url} | 并发: {args.workers} | 换IP: 每{args.rotate_every}条",
            flush=True,
        )
        rnd = 0
        while True:
            rnd += 1
            s, f = process_pending(args)
            ts += s
            tf += f
            if s or f:
                print(
                    f"\n[*] 本轮: +{s}成功 +{f}失败 | 累计: {ts}成功 {tf}失败",
                    flush=True,
                )
            else:
                print(
                    f"[.] 第{rnd}轮: 无待处理, {args.watch_interval}s 后重试",
                    flush=True,
                )
            time.sleep(args.watch_interval)
    else:
        s, f = process_pending(args)
        print(f"\n完成! 成功: {s}, 失败: {f}", flush=True)


if __name__ == "__main__":
    main()
