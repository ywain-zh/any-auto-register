from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from core.db import MailboxServiceModel, get_session


router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


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
