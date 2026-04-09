from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curl_cffi import requests as cffi_requests

from core.config_store import config_store


ROOT_DIR = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT_DIR / "reports" / "sub2api-monitor"
REQUEST_TIMEOUT = 60
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 20


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_sub2api_config() -> tuple[str, str]:
    base_url = config_store.get("sub2api_api_url", "")
    api_key = config_store.get("sub2api_api_key", "")
    return str(base_url or "").strip(), str(api_key or "").strip()


def _headers(base_url: str, api_key: str) -> dict[str, str]:
    base = base_url.rstrip("/")
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{base}/admin/accounts",
        "x-api-key": api_key,
    }


def _extract_payload(response) -> Any:
    try:
        payload = response.json()
    except Exception:
        return response.text
    if isinstance(payload, dict):
        for key in ("data", "result"):
            if key in payload:
                return payload.get(key)
    return payload


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
    if text:
        return text[:300]
    return f"HTTP {getattr(response, 'status_code', '?')}"


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> Any:
    response = cffi_requests.request(
        method,
        url,
        headers=headers,
        json=payload,
        timeout=timeout,
        verify=False,
        impersonate="chrome110",
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(_extract_error(response))
    return _extract_payload(response)


def _normalize_account(item: Any) -> dict[str, Any]:
    account = item if isinstance(item, dict) else {}
    extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
    credentials = account.get("credentials") if isinstance(account.get("credentials"), dict) else {}
    email = str(extra.get("email") or account.get("name") or "").strip()
    status = str(account.get("status") or account.get("state") or "").strip()
    type_name = str(account.get("type") or "").strip()
    platform = str(account.get("platform") or "").strip()
    expires_at = account.get("expires_at")
    if not isinstance(expires_at, int):
        expires_at = credentials.get("expires_at") if isinstance(credentials.get("expires_at"), int) else None
    disabled = bool(account.get("disabled") or status.lower() in {"disabled", "paused", "inactive"})
    return {
        "id": account.get("id"),
        "name": str(account.get("name") or "").strip(),
        "email": email,
        "status": status,
        "platform": platform,
        "type": type_name,
        "disabled": disabled,
        "expires_at": expires_at,
        "has_access_token": bool(str(credentials.get("access_token") or "").strip()),
        "has_refresh_token": bool(str(credentials.get("refresh_token") or "").strip()),
        "raw": account,
    }


def _classify_failure_text(text: str) -> str | None:
    lowered = str(text or "").lower()
    if not lowered.strip():
        return None
    if (
        "usage_limit_reached" in lowered
        or "the usage limit has been reached" in lowered
        or ('"type":"error"' in lowered and 'api returned 429' in lowered)
        or ('"type": "error"' in lowered and 'api returned 429' in lowered)
    ):
        return "quota_exhausted"
    if (
        '"status_code":401' in lowered
        or '"status_code": 401' in lowered
        or '"http_status":401' in lowered
        or '"http_status": 401' in lowered
        or "http 401" in lowered
        or "status code 401" in lowered
        or "api returned 401" in lowered
        or "unauthorized" in lowered
        or "access_token_invalidated" in lowered
        or "token_invalidated" in lowered
        or "account_deactivated" in lowered
        or "authentication token has been invalidated" in lowered
        or "deleted or deactivated" in lowered
    ):
        return "account_401"
    return None


def _classify_test_failure(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload or "")
    return _classify_failure_text(text) or "abnormal"


def _build_failed_test_result(message: Any, *, raw: Any = None) -> dict[str, Any]:
    error_text = str(message or "").strip()
    return {
        "ok": False,
        "failure_type": _classify_test_failure(raw if raw is not None else error_text),
        "message": error_text[:300],
        "raw": raw,
    }


def _summarize_test_result(payload: Any) -> dict[str, Any]:
    failure_type = _classify_test_failure(payload)
    if isinstance(payload, dict):
        success = payload.get("success")
        if isinstance(success, bool):
            ok = success
        else:
            status = str(payload.get("status") or payload.get("message") or "").lower()
            ok = status in {"success", "ok", "passed", "healthy"}
        return {
            "ok": bool(ok),
            "failure_type": None if ok else failure_type,
            "message": str(payload.get("message") or payload.get("msg") or payload.get("status") or "").strip(),
            "raw": payload,
        }
    text = str(payload or "").strip()
    lowered = text.lower()
    ok = '"success":true' in lowered or '"ok":true' in lowered or lowered in {"success", "ok"}
    return {
        "ok": ok,
        "failure_type": None if ok else failure_type,
        "message": text[:300],
        "raw": payload,
    }


def _fetch_accounts(base_url: str, api_key: str, *, page_size: int, max_pages: int) -> dict[str, Any]:
    headers = _headers(base_url, api_key)
    base = base_url.rstrip("/")
    accounts: list[dict[str, Any]] = []
    page_errors: list[dict[str, Any]] = []
    pages_fetched = 0
    stopped_early = False

    for page in range(1, max_pages + 1):
        url = f"{base}/api/v1/admin/accounts?page={page}&page_size={page_size}"
        try:
            payload = _request_json("GET", url, headers=headers, payload=None)
        except Exception as exc:
            page_errors.append({"page": page, "error": str(exc)})
            stopped_early = True
            break

        pages_fetched += 1
        outer = payload if isinstance(payload, dict) else {}
        items = outer.get("items") if isinstance(outer.get("items"), list) else payload if isinstance(payload, list) else []
        normalized_items = [_normalize_account(item) for item in items]
        accounts.extend(normalized_items)

        if len(items) < page_size:
            break

        total = outer.get("total")
        if isinstance(total, int) and total > 0 and len(accounts) >= total:
            break
    else:
        stopped_early = True

    return {
        "accounts": accounts,
        "pages_fetched": pages_fetched,
        "page_errors": page_errors,
        "stopped_early": stopped_early,
    }


def _test_account(base_url: str, api_key: str, account_id: Any) -> dict[str, Any]:
    headers = _headers(base_url, api_key)
    payload = _request_json(
        "POST",
        f"{base_url.rstrip('/')}/api/v1/admin/accounts/{account_id}/test",
        headers=headers,
        payload={},
        timeout=120,
    )
    return _summarize_test_result(payload)


def _build_counts(accounts: list[dict[str, Any]], tested_accounts: list[dict[str, Any]], run_errors: list[dict[str, Any]]) -> dict[str, int]:
    disabled = 0
    missing_tokens = 0
    expiring_soon = 0
    test_passed = 0
    test_failed = 0
    quota_exhausted = 0
    account_401 = 0
    abnormal = 0
    untested = 0
    now_ts = int(time.time())

    test_map = {str(item.get("id")): item.get("test") for item in tested_accounts}
    for account in accounts:
        if account.get("disabled"):
            disabled += 1
        if not (account.get("has_access_token") and account.get("has_refresh_token")):
            missing_tokens += 1

        expires_at = account.get("expires_at")
        if isinstance(expires_at, int) and expires_at > now_ts and expires_at - now_ts <= 86400:
            expiring_soon += 1

        test_info = test_map.get(str(account.get("id")))
        if test_info is None:
            untested += 1
        elif test_info.get("ok"):
            test_passed += 1
        else:
            test_failed += 1
            failure_type = str(test_info.get("failure_type") or "")
            if failure_type == "quota_exhausted":
                quota_exhausted += 1
            elif failure_type == "account_401":
                account_401 += 1
            elif failure_type == "abnormal":
                abnormal += 1

    available = max(len(accounts) - quota_exhausted - account_401 - abnormal, 0)

    return {
        "total": len(accounts),
        "available": available,
        "disabled": disabled,
        "missing_tokens": missing_tokens,
        "expiring_soon": expiring_soon,
        "tested_ok": test_passed,
        "tested_failed": test_failed,
        "quota_exhausted": quota_exhausted,
        "account_401": account_401,
        "abnormal": abnormal,
        "untested": untested,
        "errors": len(run_errors),
    }


def _make_run_output(
    *,
    accounts: list[dict[str, Any]],
    tested_accounts: list[dict[str, Any]],
    page_errors: list[dict[str, Any]],
    run_errors: list[dict[str, Any]],
    pages_fetched: int,
    enable_remote_test: bool,
    stopped_early: bool,
    started_at: str,
    finished_at: str,
    report_relpath: str,
) -> dict[str, Any]:
    counts = _build_counts(accounts, tested_accounts, [*page_errors, *run_errors])
    test_map = {str(item.get("id")): item.get("test") for item in tested_accounts}
    account_rows = []
    for account in accounts:
        test_info = test_map.get(str(account.get("id")))
        account_rows.append(
            {
                "id": account.get("id"),
                "email": account.get("email"),
                "name": account.get("name"),
                "status": account.get("status"),
                "platform": account.get("platform"),
                "type": account.get("type"),
                "disabled": account.get("disabled"),
                "expires_at": account.get("expires_at"),
                "has_access_token": account.get("has_access_token"),
                "has_refresh_token": account.get("has_refresh_token"),
                "test": test_info,
            }
        )

    return {
        "ok": len(page_errors) == 0 and len(run_errors) == 0,
        "summary": counts,
        "counts": counts,
        "latest_report_path": report_relpath,
        "started_at": started_at,
        "finished_at": finished_at,
        "pages_fetched": pages_fetched,
        "remote_test_enabled": enable_remote_test,
        "stopped_early": stopped_early,
        "errors": [*page_errors, *run_errors],
        "accounts": account_rows,
    }


def _ensure_report_dir() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def latest_report() -> dict[str, Any] | None:
    if not REPORT_DIR.exists():
        return None
    reports = sorted(REPORT_DIR.glob("report-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return None
    path = reports[0]
    try:
        return {
            "path": str(path.relative_to(ROOT_DIR)),
            "content": json.loads(path.read_text(encoding="utf-8")),
        }
    except Exception:
        return {
            "path": str(path.relative_to(ROOT_DIR)),
            "content": None,
        }


def run_sub2api_monitor(
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
    enable_remote_test: bool = True,
    stop_on_error: bool = False,
) -> dict[str, Any]:
    if page_size <= 0:
        raise ValueError("page_size 必须大于 0")
    if max_pages <= 0:
        raise ValueError("max_pages 必须大于 0")

    base_url, api_key = resolve_sub2api_config()
    if not base_url or not api_key:
        raise ValueError("未配置 Sub2API API 地址或 API Key")

    started_at = _utcnow_iso()
    fetch_result = _fetch_accounts(base_url, api_key, page_size=page_size, max_pages=max_pages)
    accounts = fetch_result["accounts"]
    tested_accounts: list[dict[str, Any]] = []
    run_errors: list[dict[str, Any]] = []
    stopped_early = bool(fetch_result["stopped_early"])

    if enable_remote_test:
        for account in accounts:
            account_id = account.get("id")
            if not account_id:
                run_errors.append({
                    "id": account_id,
                    "email": account.get("email"),
                    "error": "账号缺少 id，无法测试",
                })
                if stop_on_error:
                    stopped_early = True
                    break
                continue
            try:
                test_info = _test_account(base_url, api_key, account_id)
                tested_accounts.append({
                    "id": account_id,
                    "email": account.get("email"),
                    "test": test_info,
                })
            except Exception as exc:
                tested_accounts.append({
                    "id": account_id,
                    "email": account.get("email"),
                    "test": _build_failed_test_result(str(exc)),
                })
                run_errors.append({
                    "id": account_id,
                    "email": account.get("email"),
                    "error": str(exc),
                })
                if stop_on_error:
                    stopped_early = True
                    break

    finished_at = _utcnow_iso()
    _ensure_report_dir()
    report_name = f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    report_path = REPORT_DIR / report_name
    relpath = str(report_path.relative_to(ROOT_DIR))

    report = _make_run_output(
        accounts=accounts,
        tested_accounts=tested_accounts,
        page_errors=fetch_result["page_errors"],
        run_errors=run_errors,
        pages_fetched=fetch_result["pages_fetched"],
        enable_remote_test=enable_remote_test,
        stopped_early=stopped_early,
        started_at=started_at,
        finished_at=finished_at,
        report_relpath=relpath,
    )
    report["report_generated_at"] = finished_at
    report["config"] = {
        "base_url": base_url,
        "page_size": page_size,
        "max_pages": max_pages,
        "enable_remote_test": enable_remote_test,
        "stop_on_error": stop_on_error,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
