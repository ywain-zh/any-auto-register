from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Iterable, Optional

import requests
from sqlmodel import Session, select

from core.db import HotmailAccountModel, MailboxServiceModel
from sqlalchemy import func


APPLE_MAIL_DEFAULT_URL = "https://www.appleemail.top"
HOTMAIL_STATUS_UNREGISTERED = "unregistered"
HOTMAIL_STATUS_REGISTERED = "registered"
HOTMAIL_STATUS_PENDING_BIND = "pending_bind"
HOTMAIL_STATUS_SUCCESS = "success"
HOTMAIL_STATUS_FAILED = "failed"


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
) -> list[HotmailAccountModel]:
    return session.exec(
        select(HotmailAccountModel)
        .where(HotmailAccountModel.mailbox_service_id == mailbox_service_id)
        .order_by(HotmailAccountModel.created_at.asc())
    ).all()


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


def fetch_hotmail_latest_mail(
    *,
    api_url: str,
    email: str,
    client_id: str,
    refresh_token: str,
) -> dict:
    for mailbox in ("INBOX", "Junk"):
        resp = requests.get(
            f"{api_url.rstrip('/')}/api/mail-new",
            params={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "email": email,
                "mailbox": mailbox,
                "response_type": "json",
            },
            timeout=20,
            verify=False,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        items = payload.get("data") or []
        if isinstance(items, dict):
            items = [items]
        if items:
            return {
                "mailbox": mailbox,
                "mail": items[0],
                "new_refresh_token": payload.get("new_refresh_token") or "",
            }
    return {"mailbox": "", "mail": None, "new_refresh_token": ""}
