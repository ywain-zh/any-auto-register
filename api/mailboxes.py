from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from core.db import MailboxServiceModel, get_session
from services.hotmail_accounts import (
    fetch_hotmail_latest_mail,
    get_hotmail_service_config,
    import_hotmail_accounts,
    list_hotmail_accounts,
    update_hotmail_registration_status,
)


router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])
ROOT_DIR = Path(__file__).resolve().parent.parent


def _utcnow():
    return datetime.now(timezone.utc)


class MailboxServiceCreate(BaseModel):
    name: str
    provider: str
    config: dict


class MailboxServiceUpdate(BaseModel):
    name: str
    provider: str
    config: dict
    is_active: bool = True


class HotmailImportRequest(BaseModel):
    lines: list[str]


class HotmailStatusUpdateRequest(BaseModel):
    email: str
    status: str
    openai_password: str = ""
    error: str = ""
    refresh_token: str = ""


class HotmailBindRequest(BaseModel):
    proxy: str = ""
    headless: bool = False


def _serialize(item: MailboxServiceModel):
    return {
        "id": item.id,
        "name": item.name,
        "provider": item.provider,
        "config": json.loads(item.config_json or "{}"),
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _serialize_hotmail_account(item):
    return {
        "id": item.id,
        "mailbox_service_id": item.mailbox_service_id,
        "email": item.email,
        "mailbox_password": item.mailbox_password,
        "client_id": item.client_id,
        "refresh_token": item.refresh_token,
        "register_status": item.register_status,
        "claimed_at": item.claimed_at,
        "last_error": item.last_error,
        "openai_password": item.openai_password,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("")
def list_mailbox_services(session: Session = Depends(get_session)):
    items = session.exec(
        select(MailboxServiceModel).order_by(MailboxServiceModel.updated_at.desc())
    ).all()
    return [_serialize(item) for item in items]


@router.post("")
def create_mailbox_service(
    body: MailboxServiceCreate, session: Session = Depends(get_session)
):
    item = MailboxServiceModel(
        name=body.name.strip(),
        provider=body.provider.strip(),
        config_json=json.dumps(body.config or {}, ensure_ascii=False),
        is_active=True,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _serialize(item)


@router.patch("/{mailbox_id}")
def update_mailbox_service(
    mailbox_id: int, body: MailboxServiceUpdate, session: Session = Depends(get_session)
):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item:
        raise HTTPException(404, "邮箱服务不存在")
    item.name = body.name.strip()
    item.provider = body.provider.strip()
    item.config_json = json.dumps(body.config or {}, ensure_ascii=False)
    item.is_active = body.is_active
    item.updated_at = _utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return _serialize(item)


@router.delete("/{mailbox_id}")
def delete_mailbox_service(mailbox_id: int, session: Session = Depends(get_session)):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item:
        raise HTTPException(404, "邮箱服务不存在")
    session.delete(item)
    session.commit()
    return {"ok": True}


@router.patch("/{mailbox_id}/toggle")
def toggle_mailbox_service(mailbox_id: int, session: Session = Depends(get_session)):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item:
        raise HTTPException(404, "邮箱服务不存在")
    item.is_active = not item.is_active
    item.updated_at = _utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"is_active": item.is_active}


@router.post("/{mailbox_id}/hotmail/import")
def import_hotmail_accounts_api(
    mailbox_id: int,
    body: HotmailImportRequest,
    session: Session = Depends(get_session),
):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item or item.provider != "hotmail":
        raise HTTPException(404, "Hotmail 邮箱服务不存在")
    return import_hotmail_accounts(
        session=session,
        mailbox_service_id=mailbox_id,
        lines=body.lines,
    )


@router.get("/{mailbox_id}/hotmail/accounts")
def list_hotmail_accounts_api(
    mailbox_id: int,
    page: int = 1,
    page_size: int = 10,
    session: Session = Depends(get_session),
):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item or item.provider != "hotmail":
        raise HTTPException(404, "Hotmail 邮箱服务不存在")
    total, rows = list_hotmail_accounts(
        session=session,
        mailbox_service_id=mailbox_id,
        page=page,
        page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_hotmail_account(row) for row in rows],
    }


@router.patch("/{mailbox_id}/hotmail/accounts/status")
def update_hotmail_account_status_api(
    mailbox_id: int,
    body: HotmailStatusUpdateRequest,
    session: Session = Depends(get_session),
):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item or item.provider != "hotmail":
        raise HTTPException(404, "Hotmail 邮箱服务不存在")
    update_hotmail_registration_status(
        session=session,
        mailbox_service_id=mailbox_id,
        email=body.email,
        status=body.status,
        openai_password=body.openai_password,
        error=body.error,
        refresh_token=body.refresh_token,
    )
    return {"ok": True}


@router.get("/{mailbox_id}/hotmail/accounts/{account_id}/latest-mail")
def get_hotmail_latest_mail_api(
    mailbox_id: int,
    account_id: int,
    session: Session = Depends(get_session),
):
    try:
        _, cfg = get_hotmail_service_config(session, mailbox_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    _, rows = list_hotmail_accounts(session=session, mailbox_service_id=mailbox_id)
    row = next((item for item in rows if int(item.id or 0) == account_id), None)
    if not row:
        raise HTTPException(404, "Hotmail 账号不存在")
    result = fetch_hotmail_latest_mail(
        api_url=cfg.get("hotmail_api_url")
        or cfg.get("api_url")
        or "https://www.appleemail.top",
        email=row.email,
        client_id=row.client_id,
        refresh_token=row.refresh_token,
    )
    new_refresh_token = str(result.get("new_refresh_token") or "").strip()
    if new_refresh_token and new_refresh_token != row.refresh_token:
        row.refresh_token = new_refresh_token
        row.updated_at = _utcnow()
        session.add(row)
        session.commit()
    return result


@router.post("/{mailbox_id}/hotmail/accounts/{account_id}/bind")
def bind_hotmail_account_api(
    mailbox_id: int,
    account_id: int,
    body: HotmailBindRequest,
    session: Session = Depends(get_session),
):
    try:
        _, cfg = get_hotmail_service_config(session, mailbox_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    _, rows = list_hotmail_accounts(session=session, mailbox_service_id=mailbox_id)
    row = next((item for item in rows if int(item.id or 0) == account_id), None)
    if not row:
        raise HTTPException(404, "Hotmail 账号不存在")
    if not row.openai_password:
        raise HTTPException(400, "该账号还没有 OpenAI 密码，无法直接登录绑定")
    if row.register_status == "unregistered":
        raise HTTPException(400, "未注册账号不能直接登录绑定，请先走完整注册流程")

    from core.config_store import config_store
    from services.codex_script_bridge import run_original_codex_oauth_bind

    cpa_url = (
        config_store.get("cliproxyapi_base_url", "")
        or config_store.get("cpa_api_url", "")
        or config_store.get("codex_proxy_url", "")
    )
    cpa_key = (
        config_store.get("cliproxyapi_management_key", "")
        or config_store.get("cpa_api_key", "")
        or config_store.get("codex_proxy_key", "")
    )
    if not cpa_url or not cpa_key:
        raise HTTPException(400, "未配置 CLIProxyAPI / CPA 地址或管理口令")

    try:
        result = run_original_codex_oauth_bind(
            email=row.email,
            password=row.openai_password,
            proxy=body.proxy or None,
            headless=body.headless,
            cpa_url=str(cpa_url).strip(),
            cpa_key=str(cpa_key).strip(),
            hotmail_account_record={
                "email": row.email,
                "mailbox_password": row.mailbox_password,
                "client_id": row.client_id,
                "refresh_token": row.refresh_token,
            },
        )
        if not result.get("ok"):
            raise RuntimeError(
                result.get("stderr") or result.get("stdout") or "原脚本执行失败"
            )
        update_hotmail_registration_status(
            session=session,
            mailbox_service_id=mailbox_id,
            email=row.email,
            status="success",
            openai_password=row.openai_password,
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        update_hotmail_registration_status(
            session=session,
            mailbox_service_id=mailbox_id,
            email=row.email,
            status="failed",
            error=str(exc),
        )
        raise HTTPException(400, str(exc))
