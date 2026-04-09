from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Iterable, Optional
from email.utils import parsedate_to_datetime

import requests
from requests import RequestException
from sqlmodel import Session, select

from core.db import HotmailAccountModel, MailboxServiceModel
from sqlalchemy import func


APPLE_MAIL_DEFAULT_URL = "https://www.appleemail.top"
MICROSOFT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
MICROSOFT_OUTLOOK_API_BASE_URL = "https://outlook.office.com/api/v2.0"
MICROSOFT_TOKEN_ENDPOINTS = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
    "https://login.live.com/oauth20_token.srf",
)
MICROSOFT_GRAPH_SCOPES = (
    "https://graph.microsoft.com/Mail.Read offline_access openid profile email",
    "https://graph.microsoft.com/.default",
    "https://graph.microsoft.com/.default offline_access",
)
MICROSOFT_IMAP_SCOPES = (
    "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    "https://outlook.office.com/IMAP.AccessAsUser.All",
)
HOTMAIL_MODE_GRAPH = "graph"
HOTMAIL_MODE_IMAP = "imap"
HOTMAIL_STATUS_UNREGISTERED = "unregistered"
HOTMAIL_STATUS_REGISTERED = "registered"
HOTMAIL_STATUS_PENDING_BIND = "pending_bind"
HOTMAIL_STATUS_SUCCESS = "success"
HOTMAIL_STATUS_FAILED = "failed"
HOTMAIL_MAILBOX_STATUS_UNKNOWN = "unknown"
HOTMAIL_MAILBOX_STATUS_VALID = "valid"
HOTMAIL_MAILBOX_STATUS_INVALID = "invalid"
HOTMAIL_FOLDERS = (
    ("INBOX", "inbox"),
    ("Junk", "junkemail"),
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_receive_mode(value: str, fallback: str = HOTMAIL_MODE_GRAPH) -> str:
    mode = str(value or "").strip().lower()
    if mode in {HOTMAIL_MODE_GRAPH, HOTMAIL_MODE_IMAP}:
        return mode
    return fallback


def _normalize_mailbox_status(value: str, fallback: str = HOTMAIL_MAILBOX_STATUS_UNKNOWN) -> str:
    status = str(value or "").strip().lower()
    if status in {
        HOTMAIL_MAILBOX_STATUS_VALID,
        HOTMAIL_MAILBOX_STATUS_INVALID,
        HOTMAIL_MAILBOX_STATUS_UNKNOWN,
    }:
        return status
    return fallback


def classify_hotmail_mailbox_error(error: str) -> str:
    message = str(error or "").strip().lower()
    if not message:
        return HOTMAIL_MAILBOX_STATUS_UNKNOWN
    invalid_markers = (
        "invalid_grant",
        "invalid refresh token",
        "refresh token is invalid",
        "input parameter 'refresh_token'",
        "input parameter \"refresh_token\"",
        "input parameter 'assertion'",
        "input parameter \"assertion\"",
        "unauthorized",
        "invalid client",
        "账号缺少 client_id 或 refresh_token",
        "authentication unsuccessful",
        "auth error",
        "token is invalid",
        "token expired",
    )
    if any(marker in message for marker in invalid_markers):
        return HOTMAIL_MAILBOX_STATUS_INVALID
    return HOTMAIL_MAILBOX_STATUS_UNKNOWN


def set_hotmail_mailbox_status(
    *,
    session: Session,
    row: HotmailAccountModel,
    mailbox_status: str,
    last_error: str | None = None,
    refresh_token: str | None = None,
) -> HotmailAccountModel:
    normalized_status = _normalize_mailbox_status(mailbox_status)
    row.mailbox_status = normalized_status
    if last_error is not None:
        row.last_error = str(last_error or "")
    if refresh_token:
        row.refresh_token = str(refresh_token).strip()
    row.updated_at = _utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _parse_hotmail_line(raw: str) -> dict | None:
    line = str(raw or "").strip()
    if not line or "----" not in line:
        return None
    parts = [part.strip() for part in line.split("----")]
    if len(parts) not in (4, 5):
        return None
    email, mailbox_password, client_id, refresh_token = parts[:4]
    receive_mode = _normalize_receive_mode(
        parts[4] if len(parts) == 5 else HOTMAIL_MODE_GRAPH,
        fallback="",
    )
    if not email or not client_id or not refresh_token or not receive_mode:
        return None
    return {
        "email": email,
        "mailbox_password": mailbox_password,
        "client_id": client_id,
        "refresh_token": refresh_token,
        "receive_mode": receive_mode,
    }


def import_hotmail_accounts(
    *,
    session: Session,
    mailbox_service_id: int,
    lines: Iterable[str],
) -> dict:
    created = 0
    updated = 0
    skipped = 0
    for raw in lines:
        parsed = _parse_hotmail_line(raw)
        if not parsed:
            skipped += 1
            continue

        row = session.exec(
            select(HotmailAccountModel)
            .where(HotmailAccountModel.mailbox_service_id == mailbox_service_id)
            .where(func.lower(HotmailAccountModel.email) == parsed["email"].lower())
        ).first()
        if row:
            row.mailbox_password = parsed["mailbox_password"]
            row.client_id = parsed["client_id"]
            row.refresh_token = parsed["refresh_token"]
            row.receive_mode = parsed["receive_mode"]
            row.updated_at = _utcnow()
            session.add(row)
            updated += 1
            continue

        row = HotmailAccountModel(
            mailbox_service_id=mailbox_service_id,
            email=parsed["email"],
            mailbox_password=parsed["mailbox_password"],
            client_id=parsed["client_id"],
            refresh_token=parsed["refresh_token"],
            receive_mode=parsed["receive_mode"],
            mailbox_status=HOTMAIL_MAILBOX_STATUS_UNKNOWN,
            register_status=HOTMAIL_STATUS_UNREGISTERED,
        )
        session.add(row)
        created += 1

    session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def list_hotmail_accounts(
    *,
    session: Session,
    mailbox_service_id: int,
    page: int = 1,
    page_size: int = 10,
) -> tuple[int, list[HotmailAccountModel]]:
    query = select(HotmailAccountModel).where(
        HotmailAccountModel.mailbox_service_id == mailbox_service_id
    )
    total = len(session.exec(query).all())
    items = session.exec(
        query.order_by(HotmailAccountModel.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return total, items


def claim_unregistered_hotmail_account(
    *,
    session: Session,
    mailbox_service_id: int,
) -> Optional[HotmailAccountModel]:
    row = session.exec(
        select(HotmailAccountModel)
        .where(HotmailAccountModel.mailbox_service_id == mailbox_service_id)
        .where(HotmailAccountModel.register_status == HOTMAIL_STATUS_UNREGISTERED)
        .order_by(HotmailAccountModel.created_at.asc())
    ).first()
    if not row:
        return None
    row.claimed_at = _utcnow()
    row.updated_at = _utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_hotmail_registration_status(
    *,
    session: Session,
    mailbox_service_id: int,
    email: str,
    status: str,
    openai_password: str = "",
    error: str = "",
    refresh_token: str = "",
) -> None:
    row = session.exec(
        select(HotmailAccountModel)
        .where(HotmailAccountModel.mailbox_service_id == mailbox_service_id)
        .where(func.lower(HotmailAccountModel.email) == email.lower())
    ).first()
    if not row:
        return
    row.register_status = status
    if openai_password:
        row.openai_password = openai_password
    row.last_error = str(error or "")
    if refresh_token:
        row.refresh_token = refresh_token
    row.updated_at = _utcnow()
    session.add(row)
    session.commit()


def get_hotmail_service_config(
    session: Session, mailbox_service_id: int
) -> tuple[MailboxServiceModel, dict]:
    item = session.get(MailboxServiceModel, mailbox_service_id)
    if not item or item.provider != "hotmail":
        raise ValueError("Hotmail 邮箱服务不存在")
    cfg = json.loads(item.config_json or "{}")
    cfg.setdefault("hotmail_api_url", APPLE_MAIL_DEFAULT_URL)
    return item, cfg


def _hotmail_mail_ts(item: dict) -> float:
    raw_candidates = [
        item.get("received_at"),
        item.get("date"),
        item.get("receivedDateTime"),
        item.get("DateTimeReceived"),
        item.get("createdDateTime"),
        item.get("sentDateTime"),
    ]
    for raw in raw_candidates:
        value = str(raw or "").strip()
        if not value:
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
        try:
            return parsedate_to_datetime(value).timestamp()
        except Exception:
            pass
    return 0


def _hotmail_mail_message_id(item: dict) -> str:
    for key in ("message_id", "id", "Id", "internetMessageId"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    date_part = str(item.get("date") or item.get("received_at") or item.get("DateTimeReceived") or "").strip()
    subject_part = str(item.get("subject") or item.get("Subject") or "").strip()
    sender_part = str(item.get("from") or item.get("from_email") or item.get("From") or "").strip()
    fallback = f"{date_part}|{subject_part}|{sender_part}".strip("|")
    return fallback or str(abs(hash(json.dumps(item, ensure_ascii=False, sort_keys=True))))


def _hotmail_mail_from(item: dict) -> str:
    from_value = item.get("from")
    if isinstance(from_value, dict):
        email_address = from_value.get("emailAddress") or {}
        name = str(email_address.get("name") or "").strip()
        address = str(email_address.get("address") or "").strip()
        return f"{name} <{address}>".strip() if name and address else (address or name)
    outlook_from = item.get("From")
    if isinstance(outlook_from, dict):
        name = str(outlook_from.get("Name") or "").strip()
        address = str(outlook_from.get("EmailAddress") or "").strip()
        return f"{name} <{address}>".strip() if name and address else (address or name)
    return str(
        from_value
        or outlook_from
        or item.get("from_email")
        or item.get("sender")
        or item.get("author")
        or ""
    ).strip()


def _hotmail_mail_body_text(item: dict) -> str:
    body = item.get("body")
    if isinstance(body, dict):
        content = str(body.get("content") or "").strip()
        content_type = str(body.get("contentType") or "").lower()
        if content_type == "text":
            return content
        if content and not item.get("body_text"):
            return content
    outlook_body = item.get("Body")
    if isinstance(outlook_body, dict):
        content = str(outlook_body.get("Content") or "").strip()
        content_type = str(outlook_body.get("ContentType") or "").lower()
        if content_type == "text":
            return content
        if content and not item.get("body_text"):
            return content
    return str(
        item.get("text")
        or item.get("body_text")
        or item.get("content")
        or item.get("Content")
        or ""
    ).strip()


def _hotmail_mail_body_html(item: dict) -> str:
    body = item.get("body")
    if isinstance(body, dict):
        content_type = str(body.get("contentType") or "").lower()
        if content_type == "html":
            return str(body.get("content") or "").strip()
    outlook_body = item.get("Body")
    if isinstance(outlook_body, dict):
        content_type = str(outlook_body.get("ContentType") or "").lower()
        if content_type == "html":
            return str(outlook_body.get("Content") or "").strip()
    return str(item.get("html") or item.get("body_html") or "").strip()


def _normalize_hotmail_mail(item: dict, folder: str, mode: str = HOTMAIL_MODE_GRAPH) -> dict:
    normalized_mode = _normalize_receive_mode(mode)
    body_text = _hotmail_mail_body_text(item)
    body_html = _hotmail_mail_body_html(item)
    snippet = str(
        item.get("snippet")
        or item.get("summary")
        or item.get("intro")
        or item.get("bodyPreview")
        or item.get("BodyPreview")
        or body_text[:240]
        or body_html[:240]
        or ""
    ).strip()
    received_at = str(
        item.get("received_at")
        or item.get("date")
        or item.get("receivedDateTime")
        or item.get("DateTimeReceived")
        or item.get("createdDateTime")
        or item.get("sentDateTime")
        or ""
    ).strip()
    raw_message_id = _hotmail_mail_message_id(item)
    message_id = raw_message_id
    prefix = f"{normalized_mode}:{str(folder or '').lower()}:"
    if raw_message_id and not raw_message_id.startswith(prefix):
        message_id = f"{prefix}{raw_message_id}"
    return {
        "message_id": message_id,
        "folder": folder,
        "subject": str(item.get("subject") or item.get("Subject") or item.get("title") or "").strip(),
        "from": _hotmail_mail_from(item),
        "received_at": received_at,
        "snippet": snippet,
        "body_text": body_text,
        "body_html": body_html,
        "raw": item,
    }


def _get_access_token_for_scopes(*, client_id: str, refresh_token: str, scopes: tuple[str, ...]) -> dict:
    last_error = ""
    for token_url in MICROSOFT_TOKEN_ENDPOINTS:
        for scope in scopes:
            data = {
                "client_id": client_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
            if token_url != "https://login.live.com/oauth20_token.srf":
                data["scope"] = scope
            try:
                resp = requests.post(
                    token_url,
                    data=data,
                    timeout=20,
                )
            except RequestException as exc:
                last_error = f"Microsoft token 接口请求失败: {exc}"
                continue
            try:
                payload = resp.json() or {}
            except ValueError as exc:
                last_error = f"Microsoft token 接口返回了无效 JSON: {exc}"
                continue
            if not resp.ok:
                last_error = (
                    payload.get("error_description")
                    or payload.get("error", {}).get("message")
                    or payload.get("error")
                    or f"Microsoft token 接口请求失败: HTTP {resp.status_code}"
                )
                continue
            access_token = str(payload.get("access_token") or "").strip()
            if not access_token:
                last_error = "Microsoft token 接口未返回 access_token"
                continue
            return {
                "access_token": access_token,
                "refresh_token": str(payload.get("refresh_token") or "").strip(),
                "token_url": token_url,
                "scope": scope,
            }
    raise RuntimeError(last_error or "Microsoft token 接口请求失败")


def _get_graph_access_token(*, client_id: str, refresh_token: str) -> dict:
    return _get_access_token_for_scopes(
        client_id=client_id,
        refresh_token=refresh_token,
        scopes=MICROSOFT_GRAPH_SCOPES,
    )


def _get_imap_access_token(*, client_id: str, refresh_token: str) -> dict:
    return _get_access_token_for_scopes(
        client_id=client_id,
        refresh_token=refresh_token,
        scopes=MICROSOFT_IMAP_SCOPES,
    )


def refresh_hotmail_token(*, client_id: str, refresh_token: str, receive_mode: str = HOTMAIL_MODE_GRAPH) -> dict:
    if not client_id or not refresh_token:
        raise RuntimeError("该 Hotmail 账号缺少 client_id 或 refresh_token，无法刷新令牌")
    normalized_mode = _normalize_receive_mode(receive_mode)
    token_result = (
        _get_imap_access_token(client_id=client_id, refresh_token=refresh_token)
        if normalized_mode == HOTMAIL_MODE_IMAP
        else _get_graph_access_token(client_id=client_id, refresh_token=refresh_token)
    )
    return {
        "access_token": str(token_result.get("access_token") or "").strip(),
        "refresh_token": str(token_result.get("refresh_token") or "").strip(),
        "token_url": str(token_result.get("token_url") or "").strip(),
        "scope": str(token_result.get("scope") or "").strip(),
        "receive_mode": normalized_mode,
    }


def _list_graph_folder_messages(*, access_token: str, folder_id: str) -> list[dict]:
    resp = requests.get(
        f"{MICROSOFT_GRAPH_BASE_URL}/me/mailFolders/{folder_id}/messages",
        params={
            "$top": 50,
            "$orderby": "receivedDateTime desc",
            "$select": "id,internetMessageId,subject,from,receivedDateTime,bodyPreview,body",
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
        },
        timeout=20,
    )
    try:
        payload = resp.json() or {}
    except ValueError as exc:
        raise RuntimeError(f"Microsoft Graph 返回了无效 JSON: {exc}")
    if not resp.ok:
        raise RuntimeError(
            payload.get("error", {}).get("message")
            or f"Microsoft Graph 请求失败: HTTP {resp.status_code}"
        )
    items = payload.get("value") or []
    return [item for item in items if isinstance(item, dict)]


def _list_outlook_messages(*, access_token: str) -> list[dict]:
    items: list[dict] = []
    next_url = f"{MICROSOFT_OUTLOOK_API_BASE_URL}/me/messages"
    params = {
        "$top": 100,
        "$orderby": "DateTimeReceived desc",
        "$select": "Id,Subject,From,DateTimeReceived,BodyPreview,Body",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    while next_url:
        resp = requests.get(
            next_url,
            params=params,
            headers=headers,
            timeout=20,
        )
        params = None
        try:
            payload = resp.json() or {}
        except ValueError as exc:
            raise RuntimeError(f"Outlook API 返回了无效 JSON: {exc}")
        if not resp.ok:
            raise RuntimeError(
                payload.get("error", {}).get("message")
                or payload.get("message")
                or f"Outlook API 请求失败: HTTP {resp.status_code}"
            )
        batch = payload.get("value") or []
        items.extend(item for item in batch if isinstance(item, dict))
        next_url = str(payload.get("@odata.nextLink") or "").strip()
        if not next_url:
            break
    return items


def _list_hotmail_mails_via_graph(*, email: str, client_id: str, refresh_token: str) -> dict:
    token_result = _get_graph_access_token(
        client_id=client_id,
        refresh_token=refresh_token,
    )
    access_token = token_result["access_token"]
    latest_refresh_token = token_result.get("refresh_token") or ""
    all_items: list[dict] = []
    last_error = ""
    for folder_name, folder_id in HOTMAIL_FOLDERS:
        try:
            items = _list_graph_folder_messages(
                access_token=access_token,
                folder_id=folder_id,
            )
        except RuntimeError as exc:
            last_error = str(exc)
            continue
        for item in items:
            sender = str(
                ((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""
            ).strip()
            if sender.lower() == email.lower():
                continue
            all_items.append(_normalize_hotmail_mail(item, folder_name, HOTMAIL_MODE_GRAPH))
    if not all_items and last_error:
        raise RuntimeError(last_error)
    all_items.sort(key=_hotmail_mail_ts, reverse=True)
    return {
        "items": all_items,
        "new_refresh_token": latest_refresh_token,
    }


def _list_hotmail_mails_via_imap(*, email: str, client_id: str, refresh_token: str) -> dict:
    token_result = _get_imap_access_token(
        client_id=client_id,
        refresh_token=refresh_token,
    )
    access_token = token_result["access_token"]
    items = _list_outlook_messages(access_token=access_token)
    normalized_items: list[dict] = []
    for item in items:
        sender = str(
            ((item.get("From") or {}).get("EmailAddress") or "")
        ).strip()
        if sender.lower() == email.lower():
            continue
        normalized_items.append(_normalize_hotmail_mail(item, "INBOX", HOTMAIL_MODE_IMAP))
    normalized_items.sort(key=_hotmail_mail_ts, reverse=True)
    return {
        "items": normalized_items,
        "new_refresh_token": str(token_result.get("refresh_token") or "").strip(),
    }


def _list_hotmail_mails_via_relay(
    *,
    api_url: str,
    email: str,
    client_id: str,
    refresh_token: str,
) -> dict:
    all_items: list[dict] = []
    latest_refresh_token = ""
    last_error = ""
    for folder_name, _folder_id in HOTMAIL_FOLDERS:
        try:
            resp = requests.get(
                f"{api_url.rstrip('/')}/api/mail-new",
                params={
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "email": email,
                    "mailbox": folder_name,
                    "response_type": "json",
                },
                timeout=20,
                verify=False,
            )
            resp.raise_for_status()
            payload = resp.json() or {}
        except RequestException as exc:
            last_error = f"Hotmail 邮件接口请求失败: {exc}"
            continue
        except ValueError as exc:
            last_error = f"Hotmail 邮件接口返回了无效 JSON: {exc}"
            continue
        if payload.get("new_refresh_token"):
            latest_refresh_token = str(payload.get("new_refresh_token") or "").strip()
        items = payload.get("data") or []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            if isinstance(item, dict):
                all_items.append(_normalize_hotmail_mail(item, folder_name, HOTMAIL_MODE_GRAPH))
    if not all_items and last_error:
        raise RuntimeError(last_error)
    all_items.sort(key=_hotmail_mail_ts, reverse=True)
    return {
        "items": all_items,
        "new_refresh_token": latest_refresh_token,
    }


def list_hotmail_mails(
    *,
    api_url: str,
    email: str,
    client_id: str,
    refresh_token: str,
    receive_mode: str = HOTMAIL_MODE_GRAPH,
) -> dict:
    if not client_id or not refresh_token:
        raise RuntimeError("该 Hotmail 账号缺少 client_id 或 refresh_token，无法查邮件")
    normalized_mode = _normalize_receive_mode(receive_mode)
    if normalized_mode == HOTMAIL_MODE_IMAP:
        return _list_hotmail_mails_via_imap(
            email=email,
            client_id=client_id,
            refresh_token=refresh_token,
        )
    graph_error = ""
    try:
        return _list_hotmail_mails_via_graph(
            email=email,
            client_id=client_id,
            refresh_token=refresh_token,
        )
    except Exception as exc:
        graph_error = str(exc)
    try:
        return _list_hotmail_mails_via_relay(
            api_url=api_url,
            email=email,
            client_id=client_id,
            refresh_token=refresh_token,
        )
    except Exception as exc:
        if graph_error:
            raise RuntimeError(f"Microsoft Graph 查信失败：{graph_error}；Relay 回退失败：{exc}")
        raise


def fetch_hotmail_latest_mail(
    *,
    api_url: str,
    email: str,
    client_id: str,
    refresh_token: str,
    receive_mode: str = HOTMAIL_MODE_GRAPH,
) -> dict:
    result = list_hotmail_mails(
        api_url=api_url,
        email=email,
        client_id=client_id,
        refresh_token=refresh_token,
        receive_mode=receive_mode,
    )
    items = result.get("items") or []
    if items:
        first = items[0]
        return {
            "mailbox": first.get("folder") or "",
            "mail": first.get("raw") or {},
            "new_refresh_token": result.get("new_refresh_token") or "",
        }
    return {"mailbox": "", "mail": None, "new_refresh_token": result.get("new_refresh_token") or ""}
