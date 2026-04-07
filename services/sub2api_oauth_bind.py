from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from curl_cffi import requests as cffi_requests

from platforms.chatgpt.sub2api_upload import DEFAULT_CLIENT_ID, DEFAULT_GROUP_IDS
from services.codex_script_bridge import SCRIPT_DIR


SUB2API_SYNC_NAME = "sub2api"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _headers(api_url: str, api_key: str) -> dict[str, str]:
    base = api_url.rstrip("/")
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{base}/admin/accounts",
        "x-api-key": api_key,
    }


def _extract_body(response) -> Any:
    try:
        data = response.json()
    except Exception:
        return response.text
    if isinstance(data, dict):
        for key in ("data", "result"):
            value = data.get(key)
            if value is not None:
                return value
    return data


def _extract_error(response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(
                payload.get("message")
                or payload.get("msg")
                or payload.get("error")
                or payload
            )
    except Exception:
        pass
    text = str(getattr(response, "text", "") or "").strip()
    return text[:300] or f"HTTP {getattr(response, 'status_code', '?')}"


def _request_json(method: str, url: str, *, headers: dict[str, str], payload: dict | None) -> Any:
    response = cffi_requests.request(
        method,
        url,
        headers=headers,
        json=payload,
        timeout=30,
        verify=False,
        impersonate="chrome110",
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(_extract_error(response))
    return _extract_body(response)


def _build_create_payload(email: str) -> dict[str, Any]:
    return {
        "name": email,
        "notes": "",
        "platform": "openai",
        "type": "oauth",
        "credentials": {},
        "extra": {"email": email},
        "group_ids": DEFAULT_GROUP_IDS,
        "concurrency": 10,
        "priority": 1,
        "auto_pause_on_expired": True,
    }


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        parts = str(token or "").split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_auth(payload: dict[str, Any]) -> dict[str, Any]:
    auth_info = payload.get("https://api.openai.com/auth")
    return auth_info if isinstance(auth_info, dict) else {}


def _extract_organization_id(id_token_payload: dict[str, Any]) -> str:
    auth_info = _extract_auth(id_token_payload)
    organization_id = str(auth_info.get("organization_id") or "").strip()
    if organization_id:
        return organization_id

    organizations = auth_info.get("organizations") or []
    if isinstance(organizations, list):
        for item in organizations:
            if isinstance(item, dict):
                organization_id = str(item.get("id") or "").strip()
                if organization_id:
                    return organization_id
    return ""


def _extract_auth_url(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    auth_url = str(
        payload.get("auth_url")
        or payload.get("url")
        or payload.get("authorize_url")
        or ""
    ).strip()
    session_id = str(payload.get("session_id") or payload.get("session") or "").strip()
    return auth_url, session_id


def _extract_code_and_state(callback_url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(callback_url)
    query = urllib.parse.parse_qs(parsed.query)
    code = str((query.get("code") or [""])[0] or "").strip()
    state = str((query.get("state") or [""])[0] or "").strip()
    return code, state


def _build_credentials_payload(email: str, exchange_resp: Any) -> dict[str, Any]:
    if not isinstance(exchange_resp, dict):
        raise RuntimeError(f"Sub2API exchange-code 返回异常: {exchange_resp}")

    access_token = str(exchange_resp.get("access_token") or "").strip()
    refresh_token = str(exchange_resp.get("refresh_token") or "").strip()
    id_token = str(exchange_resp.get("id_token") or "").strip()
    if not access_token or not refresh_token:
        raise RuntimeError(f"Sub2API exchange-code 未返回完整 token: {exchange_resp}")

    access_payload = _decode_jwt_payload(access_token)
    access_auth = _extract_auth(access_payload)
    id_payload = _decode_jwt_payload(id_token)
    expires_at = exchange_resp.get("expires_at")
    if not isinstance(expires_at, int) or expires_at <= 0:
        expires_at = access_payload.get("exp")
    if not isinstance(expires_at, int) or expires_at <= 0:
        expires_at = int(time.time()) + 863999

    expires_in = exchange_resp.get("expires_in")
    if not isinstance(expires_in, int) or expires_in <= 0:
        expires_in = max(expires_at - int(time.time()), 1)

    response_email = str(exchange_resp.get("email") or email or "").strip() or email
    organization_id = str(exchange_resp.get("organization_id") or "").strip() or _extract_organization_id(id_payload)
    client_id = str(exchange_resp.get("client_id") or DEFAULT_CLIENT_ID).strip() or DEFAULT_CLIENT_ID
    chatgpt_account_id = str(
        exchange_resp.get("chatgpt_account_id")
        or access_auth.get("chatgpt_account_id")
        or ""
    ).strip()
    chatgpt_user_id = str(
        exchange_resp.get("chatgpt_user_id")
        or access_auth.get("chatgpt_user_id")
        or ""
    ).strip()

    return {
        "name": response_email,
        "notes": "",
        "platform": "openai",
        "type": "oauth",
        "credentials": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "expires_at": expires_at,
            "chatgpt_account_id": chatgpt_account_id,
            "chatgpt_user_id": chatgpt_user_id,
            "organization_id": organization_id,
            "client_id": client_id,
            "id_token": id_token,
        },
        "extra": {"email": response_email},
        "group_ids": DEFAULT_GROUP_IDS,
        "concurrency": 10,
        "priority": 1,
        "auto_pause_on_expired": True,
    }


def _extract_account_id(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    account_id = payload.get("id")
    if isinstance(account_id, int) and account_id > 0:
        return account_id
    if isinstance(account_id, str) and account_id.isdigit():
        return int(account_id)
    return None


def _persist_credentials(
    base: str,
    headers: dict[str, str],
    *,
    email: str,
    account_id: int,
    exchange_resp: Any,
) -> dict[str, Any]:
    payload = _build_credentials_payload(email, exchange_resp)
    persisted = _request_json(
        "PUT",
        f"{base}/api/v1/admin/accounts/{account_id}",
        headers=headers,
        payload=payload,
    )
    if not isinstance(persisted, dict):
        raise RuntimeError(f"Sub2API 账号更新返回异常: {persisted}")
    credentials = persisted.get("credentials")
    if not isinstance(credentials, dict) or not str(credentials.get("access_token") or "").strip():
        raise RuntimeError("Sub2API 账号更新后仍未持久化 access_token")
    return persisted


def _load_do_browser_login() -> Callable[..., str]:
    module_path = SCRIPT_DIR / "codex_oauth_login.py"
    if not module_path.exists():
        raise RuntimeError(f"未找到浏览器 OAuth 脚本: {module_path}")
    spec = importlib.util.spec_from_file_location("codex_oauth_login_runtime", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载浏览器 OAuth 脚本: {module_path}")
    module = importlib.util.module_from_spec(spec)
    script_dir = str(SCRIPT_DIR)
    added_to_syspath = False
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
        added_to_syspath = True
    try:
        spec.loader.exec_module(module)
    finally:
        if added_to_syspath:
            try:
                sys.path.remove(script_dir)
            except ValueError:
                pass
    do_browser_login = getattr(module, "do_browser_login", None)
    if not callable(do_browser_login):
        raise RuntimeError(f"脚本缺少 do_browser_login: {module_path}")
    return do_browser_login


@lru_cache(maxsize=1)
def _get_do_browser_login() -> Callable[..., str]:
    return _load_do_browser_login()


def build_runtime_mail_api(merged_extra: dict, *, mail_provider: str, hotmail_record: dict | None = None) -> dict:
    runtime_email_domains = (
        []
        if mail_provider == "hotmail"
        else [
            x.strip()
            for x in str(merged_extra.get("cloudmail_domains") or "").splitlines()
            if x.strip()
        ]
    )
    if mail_provider == "hotmail":
        return {
            "provider": "hotmail_api",
            "url": str(merged_extra.get("hotmail_api_url") or "https://www.appleemail.top").strip() or "https://www.appleemail.top",
            "accounts_file": str(SCRIPT_DIR / "hotmail_accounts_runtime.txt"),
            "base_dir": str(SCRIPT_DIR),
        }
    return {
        "provider": "cloudmail",
        "url": str(merged_extra.get("cloudmail_api_url") or "").strip(),
        "admin_email": str(merged_extra.get("cloudmail_admin_email") or "").strip(),
        "admin_password": str(merged_extra.get("cloudmail_admin_password") or "").strip(),
        "domains": runtime_email_domains,
        "base_dir": str(SCRIPT_DIR),
    }


def run_sub2api_codex_oauth_bind(
    *,
    email: str,
    password: str,
    sub2api_url: str,
    sub2api_key: str,
    proxy: str | None,
    headless: bool,
    mail_api_config: dict,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    do_browser_login = _get_do_browser_login()

    def log(message: str) -> None:
        if log_fn:
            log_fn(message)

    base = sub2api_url.rstrip("/")
    headers = _headers(base, sub2api_key)
    result: dict[str, Any] = {
        "target": "sub2api",
        "email": email,
        "created_account": False,
        "generated_auth_url": False,
        "exchange_result": None,
        "needs_phone": False,
        "status": "pending",
        "message": "",
        "sync_state": {},
    }

    try:
        log("[SUB2API][ACCOUNT] 创建 OAuth 账号")
        create_resp = _request_json(
            "POST",
            f"{base}/api/v1/admin/accounts",
            headers=headers,
            payload=_build_create_payload(email),
        )
        result["created_account"] = True
        result["create_response"] = create_resp
        account_id = _extract_account_id(create_resp)
        if not account_id:
            raise RuntimeError(f"Sub2API create-account 返回异常: {create_resp}")
        result["account_id"] = account_id

        log("[SUB2API][AUTH] 生成 OpenAI OAuth 登录链接")
        auth_resp = _request_json(
            "POST",
            f"{base}/api/v1/admin/openai/generate-auth-url",
            headers=headers,
            payload={"redirect_uri": DEFAULT_REDIRECT_URI},
        )
        auth_url, session_id = _extract_auth_url(auth_resp)
        if not auth_url or not session_id:
            raise RuntimeError(f"Sub2API generate-auth-url 返回异常: {auth_resp}")
        result["generated_auth_url"] = True
        result["auth_url"] = auth_url
        result["session_id"] = session_id

        log("[BROWSER][NAV] 打开 Sub2API OAuth 登录链接")
        callback_url = do_browser_login(
            auth_url,
            email,
            password,
            mail_api_config,
            headless=headless,
            proxy=proxy,
        )
        result["callback_url"] = callback_url
        if callback_url == "add_phone":
            result["ok"] = False
            result["needs_phone"] = True
            result["status"] = "add_phone"
            result["message"] = "OpenAI 要求绑定手机号，流程已到达授权页"
            result["sync_state"] = {
                "target": "sub2api",
                "last_attempt_ok": False,
                "last_attempt_at": _utcnow_iso(),
                "stage": "browser_auth",
                "status": "add_phone",
                "message": result["message"],
            }
            return result
        if callback_url == "rate_limited":
            raise RuntimeError("OpenAI 登录流程被限流")
        if not callback_url or "code=" not in str(callback_url):
            raise RuntimeError("浏览器未获取到 OAuth callback URL")

        code, state = _extract_code_and_state(str(callback_url))
        if not code or not state:
            raise RuntimeError("OAuth callback 缺少 code/state")

        log("[SUB2API][TOKEN] 提交 code 给 Sub2API 交换 token")
        exchange_resp = _request_json(
            "POST",
            f"{base}/api/v1/admin/openai/exchange-code",
            headers=headers,
            payload={
                "session_id": session_id,
                "code": code,
                "state": state,
                "redirect_uri": DEFAULT_REDIRECT_URI,
            },
        )
        log("[SUB2API][ACCOUNT] 持久化 OAuth 凭证到账号")
        persisted_account = _persist_credentials(
            base,
            headers,
            email=email,
            account_id=account_id,
            exchange_resp=exchange_resp,
        )
        result["persist_response"] = persisted_account
        result["ok"] = True
        result["status"] = "success"
        result["message"] = "Sub2API OAuth 绑定成功"
        result["sync_state"] = {
            "target": "sub2api",
            "last_attempt_ok": True,
            "last_attempt_at": _utcnow_iso(),
            "stage": "persist_credentials",
            "status": "success",
            "uploaded": True,
            "uploaded_at": _utcnow_iso(),
            "message": result["message"],
        }
        return result
    except Exception as exc:
        result["ok"] = False
        if result.get("status") == "pending":
            result["status"] = "failed"
        result["message"] = str(exc)
        result["sync_state"] = {
            "target": "sub2api",
            "last_attempt_ok": False,
            "last_attempt_at": _utcnow_iso(),
            "stage": "failed",
            "status": result.get("status") or "failed",
            "message": str(exc),
        }
        return result
