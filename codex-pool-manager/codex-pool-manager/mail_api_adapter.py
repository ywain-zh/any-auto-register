#!/usr/bin/env python3

import os
import random
import re
import secrets
import string
import time
from datetime import datetime, timezone

import requests as http_requests


def normalize_mail_config(mail_api, email_domains=None):
    cfg = {}
    if isinstance(mail_api, dict):
        cfg.update(mail_api)
    else:
        cfg["url"] = str(mail_api or "").strip()

    provider = str(cfg.get("provider") or "").strip().lower()
    if not provider:
        provider = (
            "cloudmail"
            if cfg.get("admin_email") and cfg.get("admin_password")
            else "inbucket"
        )

    url = str(cfg.get("url") or cfg.get("mail_api") or "").strip().rstrip("/")
    domains = cfg.get("domains") or email_domains or []
    if isinstance(domains, str):
        parsed = []
        for chunk in domains.replace("\r", "\n").replace(",", "\n").split("\n"):
            value = chunk.strip().lstrip("@")
            if value:
                parsed.append(value)
        domains = parsed

    return {
        "provider": provider,
        "url": url,
        "admin_email": str(cfg.get("admin_email") or "").strip(),
        "admin_password": str(cfg.get("admin_password") or "").strip(),
        "domains": domains or [],
        "token": str(cfg.get("token") or "").strip(),
        "accounts_file": str(cfg.get("accounts_file") or "").strip(),
        "accounts": cfg.get("accounts") or [],
        "base_dir": str(cfg.get("base_dir") or os.getcwd()).strip(),
        "account_index": int(cfg.get("account_index") or 0),
    }


def _resolve_path(path_value, base_dir):
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    if os.path.isabs(raw):
        return raw
    return os.path.join(base_dir or os.getcwd(), raw)


def _load_hotmail_accounts(cfg):
    cached = cfg.get("accounts") or []
    if cached:
        return cached

    path = _resolve_path(cfg.get("accounts_file"), cfg.get("base_dir"))
    if not path or not os.path.isfile(path):
        return []

    accounts = []
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or "----" not in line:
                continue
            parts = line.split("----", 3)
            if len(parts) != 4:
                continue
            email, password, client_id, refresh_token = parts
            accounts.append(
                {
                    "email": email.strip(),
                    "password": password.strip(),
                    "client_id": client_id.strip(),
                    "refresh_token": refresh_token.strip(),
                }
            )
    cfg["accounts"] = accounts
    return accounts


def _persist_hotmail_accounts(cfg):
    path = _resolve_path(cfg.get("accounts_file"), cfg.get("base_dir"))
    accounts = cfg.get("accounts") or []
    if not path or not accounts:
        return
    with open(path, "w", encoding="utf-8") as handle:
        for item in accounts:
            handle.write(
                "----".join(
                    [
                        str(item.get("email") or ""),
                        str(item.get("password") or ""),
                        str(item.get("client_id") or ""),
                        str(item.get("refresh_token") or ""),
                    ]
                )
                + "\n"
            )


def _pick_hotmail_account(cfg, email=""):
    accounts = _load_hotmail_accounts(cfg)
    if not accounts:
        raise RuntimeError("Hotmail 账号文件为空或读取失败")
    if email:
        for item in accounts:
            if str(item.get("email") or "").strip().lower() == email.strip().lower():
                return item
    idx = int(cfg.get("account_index") or 0)
    if idx >= len(accounts):
        idx = 0
    account = accounts[idx]
    cfg["account_index"] = idx + 1
    return account


def _hotmail_mail_ts(item):
    raw = str(item.get("date") or "").strip()
    if not raw:
        return 0
    try:
        return int(
            datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000
        )
    except Exception:
        return 0


def _generate_email(email_domains):
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
    domain = domain.lstrip(".")
    local = "".join(
        random.choices(string.ascii_lowercase, k=random.randint(4, 8))
    ) + "".join(random.choices(string.digits, k=random.randint(2, 4)))
    return f"{local}@{domain}"


def create_mailbox_address(mail_cfg, email_domains):
    cfg = normalize_mail_config(mail_cfg, email_domains)
    if cfg["provider"] == "hotmail_api":
        email = _pick_hotmail_account(cfg).get("email", "")
        if isinstance(mail_cfg, dict):
            mail_cfg["account_index"] = cfg.get("account_index", 0)
            mail_cfg["accounts"] = cfg.get("accounts") or []
        return email
    if cfg["provider"] != "cloudmail":
        return _generate_email(email_domains)

    if not cfg["url"] or not cfg["admin_email"] or not cfg["admin_password"]:
        raise RuntimeError("Cloud Mail 配置不完整，缺少 url/admin_email/admin_password")

    token = cfg.get("token") or cloudmail_gen_token(cfg)
    email = _generate_email(cfg["domains"] or email_domains)
    resp = http_requests.post(
        f"{cfg['url']}/api/public/addUser",
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"list": [{"email": email}]},
        timeout=20,
        verify=False,
    )
    data = resp.json()
    if resp.status_code != 200 or data.get("code") != 200:
        raise RuntimeError(f"Cloud Mail 创建邮箱失败: {resp.status_code} {data}")
    cfg["token"] = token
    if isinstance(mail_cfg, dict):
        mail_cfg["token"] = token
    return email


def cloudmail_gen_token(mail_cfg):
    cfg = normalize_mail_config(mail_cfg)
    if cfg.get("token"):
        return cfg["token"]
    resp = http_requests.post(
        f"{cfg['url']}/api/public/genToken",
        json={"email": cfg["admin_email"], "password": cfg["admin_password"]},
        timeout=20,
        verify=False,
    )
    data = resp.json()
    token = ((data or {}).get("data") or {}).get("token", "")
    if resp.status_code != 200 or not token:
        raise RuntimeError(f"Cloud Mail 获取 token 失败: {resp.status_code} {data}")
    if isinstance(mail_cfg, dict):
        mail_cfg["token"] = token
    return token


def fetch_email_code(
    mail_cfg, email, since_ts, used_codes, timeout_secs=120, label="[邮件]"
):
    cfg = normalize_mail_config(mail_cfg)
    regex = r"(?<!\d)(\d{6})(?!\d)"
    print(f"    {label} 等待验证码", end="", flush=True)
    for _ in range(max(timeout_secs // 3, 1)):
        print(".", end="", flush=True)
        try:
            code = _fetch_once(cfg, email, since_ts, used_codes, regex)
            if code:
                print(f" OK:{code}")
                return code
        except Exception:
            pass
        time.sleep(3)
    print(" 超时")
    return None


def fetch_latest_mail(mail_cfg, email):
    cfg = normalize_mail_config(mail_cfg)
    if cfg["provider"] != "hotmail_api":
        raise RuntimeError("fetch_latest_mail 目前只支持 hotmail_api")

    account = _pick_hotmail_account(cfg, email=email)
    for mailbox in ("INBOX", "Junk"):
        resp = http_requests.get(
            f"{cfg['url']}/api/mail-new",
            params={
                "refresh_token": account.get("refresh_token", ""),
                "client_id": account.get("client_id", ""),
                "email": account.get("email", email),
                "mailbox": mailbox,
                "response_type": "json",
            },
            timeout=20,
            verify=False,
        )
        if resp.status_code != 200:
            continue
        payload = resp.json() or {}
        new_token = str(payload.get("new_refresh_token") or "").strip()
        if new_token and new_token != account.get("refresh_token"):
            account["refresh_token"] = new_token
            _persist_hotmail_accounts(cfg)
        items = payload.get("data") or []
        if isinstance(items, dict):
            items = [items]
        if items:
            return {"mailbox": mailbox, "mail": items[0]}
    return None


def _fetch_once(cfg, email, since_ts, used_codes, regex):
    if cfg["provider"] == "cloudmail":
        token = cfg.get("token") or cloudmail_gen_token(cfg)
        resp = http_requests.post(
            f"{cfg['url']}/api/public/emailList",
            headers={"Authorization": token, "Content-Type": "application/json"},
            json={
                "toEmail": email,
                "num": 1,
                "size": 20,
                "timeSort": "desc",
                "type": 0,
            },
            timeout=20,
            verify=False,
        )
        if resp.status_code != 200:
            return None
        items = (resp.json() or {}).get("data") or []
        for item in items:
            content = "\n".join(
                [
                    str(item.get("subject") or ""),
                    str(item.get("text") or ""),
                    str(item.get("content") or ""),
                ]
            )
            match = re.search(regex, content)
            if match and match.group(1) not in used_codes:
                return match.group(1)
        return None

    if cfg["provider"] == "hotmail_api":
        account = _pick_hotmail_account(cfg, email=email)
        for mailbox in ("INBOX", "Junk"):
            resp = http_requests.get(
                f"{cfg['url']}/api/mail-new",
                params={
                    "refresh_token": account.get("refresh_token", ""),
                    "client_id": account.get("client_id", ""),
                    "email": account.get("email", email),
                    "mailbox": mailbox,
                    "response_type": "json",
                },
                timeout=20,
                verify=False,
            )
            if resp.status_code != 200:
                continue
            payload = resp.json() or {}
            new_token = str(payload.get("new_refresh_token") or "").strip()
            if new_token and new_token != account.get("refresh_token"):
                account["refresh_token"] = new_token
                _persist_hotmail_accounts(cfg)
            items = payload.get("data") or []
            if isinstance(items, dict):
                items = [items]
            for item in sorted(items, key=_hotmail_mail_ts, reverse=True):
                if _hotmail_mail_ts(item) < since_ts:
                    continue
                content = "\n".join(
                    [
                        str(item.get("subject") or ""),
                        str(item.get("text") or ""),
                        str(item.get("html") or ""),
                        str(item.get("send") or ""),
                    ]
                )
                if "chatgpt" not in content.lower() and "openai" not in content.lower():
                    continue
                match = re.search(regex, content)
                if match and match.group(1) not in used_codes:
                    return match.group(1)
        return None

    local = email.split("@")[0]
    for mailbox_path in (f"/api/v1/mailbox/{local}", f"/api/v1/junkbox/{local}"):
        resp = http_requests.get(
            f"{cfg['url']}{mailbox_path}", timeout=10, verify=False
        )
        if resp.status_code != 200:
            continue
        msgs = resp.json()
        if not isinstance(msgs, list):
            continue
        for msg in sorted(msgs, key=lambda m: m.get("posix-millis", 0), reverse=True):
            if msg.get("posix-millis", 0) < since_ts:
                continue
            content = "\n".join(
                [
                    str(msg.get("subject") or ""),
                    str(msg.get("text") or ""),
                    str(msg.get("body") or ""),
                    str(msg.get("html") or ""),
                ]
            )
            if "chatgpt" not in content.lower() and "openai" not in content.lower():
                continue
            match = re.search(regex, content)
            if match and match.group(1) not in used_codes:
                return match.group(1)
    return None
