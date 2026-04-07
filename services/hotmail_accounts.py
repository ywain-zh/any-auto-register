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
HOTMAIL_STATUS_UNREGISTERED = "unregistered"
HOTMAIL_STATUS_REGISTERED = "registered"
HOTMAIL_STATUS_PENDING_BIND = "pending_bind"
HOTMAIL_STATUS_SUCCESS = "success"
HOTMAIL_STATUS_FAILED = "failed"
HOTMAIL_FOLDERS = (
    ("INBOX", "inbox"),
    ("Junk", "junkemail"),
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_hotmail_line(raw: str) -> dict | None:
    line = str(raw or "").strip()
    if not line or "----" not in line:
        return None
    parts = line.split("----", 3)
    if len(parts) != 4:
        return None
    email, mailbox_password, client_id, refresh_token = [part.strip() for part in parts]
    if not email or not client_id or not refresh_token:
        return None
    return {
        "email": email,
        "mailbox_password": mailbox_password,
        "client_id": client_id,
        "refresh_token": refresh_token,
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
    for key in ("message_id", "id", "internetMessageId"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    date_part = str(item.get("date") or item.get("received_at") or "").strip()
    subject_part = str(item.get("subject") or "").strip()
    sender_part = str(item.get("from") or item.get("from_email") or "").strip()
    fallback = f"{date_part}|{subject_part}|{sender_part}".strip("|")
    return fallback or str(abs(hash(json.dumps(item, ensure_ascii=False, sort_keys=True))))


def _hotmail_mail_from(item: dict) -> str:
    from_value = item.get("from")
    if isinstance(from_value, dict):
        email_address = from_value.get("emailAddress") or {}
        name = str(email_address.get("name") or "").strip()
        address = str(email_address.get("address") or "").strip()
        return f"{name} <{address}>".strip() if name and address else (address or name)
    return str(
        from_value
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
    return str(item.get("text") or item.get("body_text") or item.get("content") or "").strip()


def _hotmail_mail_body_html(item: dict) -> str:
    body = item.get("body")
    if isinstance(body, dict):
        content_type = str(body.get("contentType") or "").lower()
        if content_type == "html":
            return str(body.get("content") or "").strip()
    return str(item.get("html") or item.get("body_html") or "").strip()


def _normalize_hotmail_mail(item: dict, folder: str) -> dict:
    body_text = _hotmail_mail_body_text(item)
    body_html = _hotmail_mail_body_html(item)
    snippet = str(
        item.get("snippet")
        or item.get("summary")
        or item.get("intro")
        or item.get("bodyPreview")
        or body_text[:240]
        or body_html[:240]
        or ""
    ).strip()
    received_at = str(
        item.get("received_at")
        or item.get("date")
        or item.get("receivedDateTime")
        or item.get("createdDateTime")
        or item.get("sentDateTime")
        or ""
    ).strip()
    raw_message_id = _hotmail_mail_message_id(item)
    message_id = raw_message_id
    if raw_message_id and not raw_message_id.startswith("graph:"):
        message_id = f"graph:{str(folder or '').lower()}:{raw_message_id}"
    return {
        "message_id": message_id,
        "folder": folder,
        "subject": str(item.get("subject") or item.get("title") or "").strip(),
        "from": _hotmail_mail_from(item),
        "received_at": received_at,
        "snippet": snippet,
        "body_text": body_text,
        "body_html": body_html,
        "raw": item,
    }


def _get_graph_access_token(*, client_id: str, refresh_token: str) -> dict:
    last_error = ""
    for token_url in MICROSOFT_TOKEN_ENDPOINTS:
        for scope in MICROSOFT_GRAPH_SCOPES:
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
            all_items.append(_normalize_hotmail_mail(item, folder_name))
    if not all_items and last_error:
        raise RuntimeError(last_error)
    all_items.sort(key=_hotmail_mail_ts, reverse=True)
    return {
        "items": all_items,
        "new_refresh_token": latest_refresh_token,
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
                all_items.append(_normalize_hotmail_mail(item, folder_name))
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
) -> dict:
    if not client_id or not refresh_token:
        raise RuntimeError("该 Hotmail 账号缺少 client_id 或 refresh_token，无法查邮件")
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
) -> dict:
    result = list_hotmail_mails(
        api_url=api_url,
        email=email,
        client_id=client_id,
        refresh_token=refresh_token,
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
